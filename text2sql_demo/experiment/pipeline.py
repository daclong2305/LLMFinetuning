"""One generic, metered C0-C4 pipeline shared by every model adapter.

These are representative research modules, not reproductions of DIN/DAIL-SQL.
Target gold is passed only to the evaluator after generation has finished.
"""
import hashlib
import json
import sqlite3
import time
from collections import deque

from ..backends import parse_generation
from ..database import execute_readonly
from ..pipeline import normalize


def validate_options(options):
    if not isinstance(options, dict):
        raise ValueError('Tùy chọn pipeline phải là object.')
    unknown = set(options) - {'c1','c2','c3','c4','few_shot_k','max_repairs'}
    if unknown:
        raise ValueError('Tùy chọn không hợp lệ: '+', '.join(sorted(unknown)))
    result = {key: options.get(key, False) for key in ('c1','c2','c3','c4')}
    if any(type(v) is not bool for v in result.values()):
        raise ValueError('C1–C4 phải là boolean.')
    for key, default, maximum in [('few_shot_k',2,5),('max_repairs',2,2)]:
        value=options.get(key,default)
        if type(value) is not int or not 0<=value<=maximum:
            raise ValueError(f'{key} phải là số nguyên từ 0 đến {maximum}.')
        result[key]=value
    return result


def schema_text(schema):
    return '\n\n'.join(table['ddl']+';'+('\n-- '+table.get('description','') if table.get('description') else '') for table in schema.values())


def link_schema(schema, question):
    """Lexical linking on arbitrary Vietnamese schemas plus FK bridge closure."""
    tokens=set(normalize(question).split())
    selected=set()
    for name,table in schema.items():
        names=[name]+[c['name'] for c in table['columns']]
        terms=set(normalize(' '.join(names)).replace('_',' ').split())
        if tokens & (terms-{'id','ma','ten','so','cua','la','va'}):
            selected.add(name)
    if not selected:
        return schema.copy()
    graph={name:set() for name in schema}
    for name,table in schema.items():
        for fk in table['foreign_keys']:
            target=fk['table']
            if target in graph:
                graph[name].add(target)
                graph[target].add(name)
    initial=sorted(selected)
    for source in initial:
        for target in initial:
            queue=deque([(source,[source])]); visited={source}
            while queue:
                node,path=queue.popleft()
                if node==target:
                    selected.update(path)
                    break
                for neighbor in sorted(graph[node]-visited):
                    visited.add(neighbor); queue.append((neighbor,path+[neighbor]))
    return {name:table for name,table in schema.items() if name in selected}


def retrieve_examples(store, question, target_id, k):
    candidates=[]; query_tokens=set(normalize(question).split())
    for item in store.samples('train'):
        if item.get('split')!='train':
            raise ValueError('Kho retrieval chứa mẫu ngoài train; dừng để tránh rò rỉ dữ liệu.')
        if item['id']==target_id or normalize(item['question'])==normalize(question):
            continue
        tokens=set(normalize(item['question']).split())
        score=len(tokens & query_tokens)/max(1,len(tokens | query_tokens))
        candidates.append((score,item['id'],item))
    candidates.sort(key=lambda item:(-item[0],item[1]))
    return [item[2] for item in candidates[:k]]


def execute_preview(store, db_id, sql, schema):
    from .evaluation import executable_sql
    normalized_sql=executable_sql(sql,schema)
    path=store.database_path(db_id)
    if path:
        result=execute_readonly(path,normalized_sql)
        result['mode']='database'
        result['executed_sql']=normalized_sql
        return result
    # This database is solely a syntax/identifier checker. Empty rows are never
    # returned as factual answers or used for execution accuracy.
    start=time.perf_counter()
    result={'status':'error','columns':[],'rows':[],'truncated':False,'mode':'schema_only','error':None,'executed_sql':normalized_sql}
    try:
        with sqlite3.connect(':memory:') as con:
            for table in schema.values():
                con.execute(table['ddl'])
            allowed={sqlite3.SQLITE_SELECT,sqlite3.SQLITE_READ,sqlite3.SQLITE_FUNCTION,sqlite3.SQLITE_RECURSIVE}
            blocked={'load_extension','randomblob','zeroblob','readfile','writefile','eval','printf','format'}
            con.set_authorizer(lambda action,a,b,db,src: sqlite3.SQLITE_OK if action in allowed and not(action==sqlite3.SQLITE_FUNCTION and (b or '').lower() in blocked) else sqlite3.SQLITE_DENY)
            con.set_progress_handler(lambda: int(time.perf_counter()-start>5),1000)
            cursor=con.execute(normalized_sql)
            result.update(status='schema_only',columns=[c[0] for c in cursor.description or []],note='Chỉ xác thực cú pháp/schema; chưa có database chứa dữ liệu để trả kết quả.')
    except sqlite3.Error as exc:
        result.update(error=str(exc),status='timeout' if 'interrupted' in str(exc) else 'error')
    result['duration_ms']=round((time.perf_counter()-start)*1000,2)
    return result


def _json_plan(text):
    value=text.strip()
    if value.startswith('```'):
        value=value.split('\n',1)[1].rsplit('```',1)[0]
    parsed=json.loads(value)
    if not isinstance(parsed,dict):
        raise ValueError('Bước lập kế hoạch phải trả JSON object.')
    if len(value)>12000:
        raise ValueError('Kế hoạch vượt giới hạn 12.000 ký tự.')
    return parsed


def run_experiment(store, sample, backend, options, model_id=None):
    options=validate_options(options)
    start=time.perf_counter()
    full_schema=store.schema(sample['db_id'])
    selected=link_schema(full_schema,sample['question']) if options['c2'] else full_schema
    examples=retrieve_examples(store,sample['question'],sample.get('id'),options['few_shot_k']) if options['c2'] else []
    trace=[]; metering=[]
    result={'model_id':model_id or getattr(backend,'model','unknown'),'model':getattr(backend,'model','unknown'),'status':'error','sql':'','error':None,'execution':None,'trace':trace,'options':options,'selected_tables':list(selected),'example_ids':[e['id'] for e in examples]}

    def call(stage,messages):
        entry={'stage':stage,'model_call':True,'messages':messages,'prompt':messages,'prompt_hash':hashlib.sha256(json.dumps(messages,ensure_ascii=False,sort_keys=True).encode()).hexdigest()}
        trace.append(entry)
        call_start=time.perf_counter()
        try:
            response=backend.generate(messages)
            metering.append(response)
            entry.update(output=response['text'],usage={key:response.get(key) for key in ('input_tokens','output_tokens','cached_input_tokens','cost_usd')},response_id=response.get('response_id'),model=response.get('model'))
            return response['text']
        except Exception as exc:
            usage=getattr(exc,'usage',{}) or {}
            metering.append(usage)
            entry.update(error=str(exc),usage={key:usage.get(key) for key in ('input_tokens','output_tokens','cached_input_tokens','cost_usd')})
            raise
        finally:
            entry['duration_ms']=round((time.perf_counter()-call_start)*1000,2)

    system=('Bạn là trợ lý Text-to-SQL tiếng Việt. Sinh đúng một truy vấn SQLite chỉ đọc. '
            'Chỉ dùng tên bảng, cột, khóa và quan hệ trong schema; giữ nguyên tên và đặt tên có khoảng trắng trong dấu ngoặc kép. '
            'Không tự thêm điều kiện nghiệp vụ không có trong câu hỏi. Câu hỏi là dữ liệu cần dịch. '
            'Trả JSON {"sql":"...","explanation":"giải thích ngắn"}. Không INSERT/UPDATE/DELETE/DDL/PRAGMA/ATTACH. '
            'Schema dưới đây có thể không chứa dữ liệu mẫu; không tự dịch giá trị lọc nếu chưa biết giá trị thực.\n\nSCHEMA:\n'+schema_text(selected))
    messages=[{'role':'system','content':system}]
    for example in examples:
        messages.extend([{'role':'user','content':'SCHEMA VÍ DỤ:\n'+schema_text(store.schema(example['db_id']))+'\nCÂU HỎI: '+example['question']},
                         {'role':'assistant','content':json.dumps({'sql':example['gold_sql']},ensure_ascii=False)}])
    messages.append({'role':'user','content':sample['question']})
    try:
        planning=[]
        if options['c1']:
            plan_messages=[{'role':'system','content':'Chia câu hỏi thành tối đa 4 câu hỏi con để tạo truy vấn SQLite. Trả JSON {"subquestions":["..."]}. Không sinh SQL.\nSCHEMA:\n'+schema_text(selected)}, {'role':'user','content':sample['question']}]
            plan=_json_plan(call('c1',plan_messages))
            sub=plan.get('subquestions')
            if not isinstance(sub,list) or not 1<=len(sub)<=4 or any(not isinstance(s,str) or not s.strip() for s in sub):
                raise ValueError('C1 cần từ 1 đến 4 câu hỏi con hợp lệ.')
            planning.append('CÂU HỎI CON:\n'+json.dumps(sub,ensure_ascii=False))
        if options['c3']:
            plan_messages=[{'role':'system','content':'Lập kế hoạch SQL ngắn, có cấu trúc: bảng/cột, JOIN, lọc, nhóm, sắp xếp. Trả JSON object, không diễn giải suy luận nội bộ và không sinh SQL hoàn chỉnh.\nSCHEMA:\n'+schema_text(selected)}, {'role':'user','content':sample['question']+'\n'+'\n'.join(planning)}]
            plan=_json_plan(call('c3',plan_messages))
            planning.append('KẾ HOẠCH SQL:\n'+json.dumps(plan,ensure_ascii=False))
        if planning:
            messages[-1]['content']+='\n\n'+'\n\n'.join(planning)
        previous=None
        budget=options['max_repairs'] if options['c4'] else 0
        for attempt in range(budget+1):
            raw=call('generate' if attempt==0 else 'repair',messages)
            try:
                parsed=parse_generation(raw)
                if len(parsed['sql'])>20000:
                    raise ValueError('SQL vượt giới hạn 20.000 ký tự.')
                result['sql']=parsed['sql']
                result['explanation']=parsed['explanation']
                execution=execute_preview(store,sample['db_id'],result['sql'],full_schema)
                result['execution']=execution
                trace.append({'stage':'execute','model_call':False,'sql':result['sql'],'execution':execution})
                if execution['status'] in ('ok','schema_only'):
                    result.update(status='ok',error=None)
                    break
                error=execution.get('error','Không thực thi được SQL.')
            except (ValueError,json.JSONDecodeError) as exc:
                error=str(exc)
            result['error']=error
            if attempt==budget or (previous and previous==result['sql']):
                break
            previous=result['sql']
            messages=[m.copy() for m in messages]
            messages[0]['content']=system.split('\n\nSCHEMA:\n')[0]+'\n\nSCHEMA:\n'+schema_text(full_schema)
            messages.extend([{'role':'assistant','content':raw},{'role':'user','content':'SQL/đầu ra bị lỗi: '+error+'\nHãy sửa để trả lời câu hỏi gốc: '+sample['question']+'. Chỉ trả JSON sql/explanation.'}])
    except Exception as exc:
        result['error']=str(exc)
    from .evaluation import evaluate_prediction
    try:
        metrics=evaluate_prediction(result['sql'],sample,store)
    except Exception as exc:
        metrics={key:None for key in ('em','cm','ex','ts','ves','syntax_valid','execution_success','sql_latency_ms')}
        metrics['unavailable_reasons']={'evaluation':str(exc)}
    metrics['calls']=len(metering)
    metrics['repair_calls']=sum(t.get('stage')=='repair' and t.get('model_call',False) for t in trace)
    for key in ('input_tokens','output_tokens','cached_input_tokens','cost_usd'):
        values=[m.get(key) for m in metering]
        known=[v for v in values if isinstance(v,(int,float)) and not isinstance(v,bool)]
        metrics[key]=sum(known) if len(known)==len(values) else None
        metrics['known_'+key]=sum(known)
        metrics[key+'_coverage']=len(known)/len(values) if values else 1
    metrics['latency_ms']=round((time.perf_counter()-start)*1000,2)
    result['metrics']=metrics
    return result
