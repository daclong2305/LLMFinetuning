"""Persistent runs and transparent aggregation; no synthetic model results."""
import csv
import io
import json
import math
import re
import threading
import uuid
from collections import defaultdict
from datetime import datetime,timezone
from pathlib import Path
from .provenance import process_identity,owner_alive,experiment_snapshot,code_snapshot,runtime_snapshot


def percentile(values,p):
    if not values:
        return None
    values=sorted(values); at=(len(values)-1)*p
    low=math.floor(at); high=math.ceil(at)
    return values[low]+(values[high]-values[low])*(at-low)


def wilson(success,n):
    if not n:
        return None
    z=1.959963984540054; proportion=success/n; divisor=1+z*z/n
    center=(proportion+z*z/(2*n))/divisor
    half=z*math.sqrt(proportion*(1-proportion)/n+z*z/(4*n*n))/divisor
    return [max(0,center-half),min(1,center+half)]


def summarize_records(records,expected):
    groups=defaultdict(list)
    for row in records:
        groups[row['model_id']+':'+row['preset_id']].append(row)
    rows=[]
    for key in sorted(set(expected)|set(groups)):
        items=groups[key]; model_id,preset_id=key.split(':',1); n=len(items)
        row={'model_id':model_id,'preset_id':preset_id,'n':n,'expected_n':expected.get(key,n),'complete':n==expected.get(key,n),'errors':sum(i.get('status')=='error' for i in items),'coverage':{},'eligible_n':{},'intervals':{},'unavailable_reasons':{}}
        for metric in ('em','cm','ex','ts','ves','syntax_valid','execution_success'):
            values=[i['metrics'].get(metric) for i in items if i['metrics'].get(metric) is not None]
            numeric=[float(v) for v in values]
            output={'syntax_valid':'syntax_valid_rate','execution_success':'execution_success_rate'}.get(metric,metric)
            row[output]=sum(numeric)/len(numeric) if numeric else None
            row['coverage'][metric]=len(values)/n if n else 0
            row['eligible_n'][metric]=len(values)
            if metric in ('em','ex','ts','syntax_valid','execution_success'):
                row['intervals'][metric]=wilson(sum(numeric),len(numeric))
            reasons=set()
            for item in items:
                unavailable=item['metrics'].get('unavailable_reasons',{})
                if isinstance(unavailable,dict) and unavailable.get(metric):
                    reasons.add(str(unavailable[metric]))
            if reasons:
                row['unavailable_reasons'][metric]=sorted(reasons)
        for metric in ('input_tokens','output_tokens','cached_input_tokens','calls','repair_calls','cost_usd'):
            values=[i['metrics'].get(metric) for i in items]
            known=[v for v in values if isinstance(v,(int,float)) and not isinstance(v,bool)]
            row[metric]=sum(known) if len(known)==n and n else None
            row['known_'+metric]=sum(i['metrics'].get('known_'+metric, i['metrics'].get(metric) or 0) for i in items)
            row['coverage'][metric]=len(known)/n if n else 0
        times=[i['metrics']['latency_ms'] for i in items if isinstance(i['metrics'].get('latency_ms'),(int,float))]
        row['p50_latency_ms']=percentile(times,.5)
        row['p95_latency_ms']=percentile(times,.95)
        row['mean_latency_ms']=sum(times)/len(times) if times else None
        sql_times=[i['metrics']['sql_latency_ms'] for i in items if isinstance(i['metrics'].get('sql_latency_ms'),(int,float))]
        row['mean_sql_latency_ms']=sum(sql_times)/len(sql_times) if sql_times else None
        row['per_difficulty']={}
        for difficulty in sorted({i.get('difficulty','unknown') for i in items}):
            subset=[i for i in items if i.get('difficulty','unknown')==difficulty]
            detail={'n':len(subset)}
            for metric in ('em','cm','ex','ts'):
                values=[float(i['metrics'][metric]) for i in subset if i['metrics'].get(metric) is not None]
                detail[metric]=sum(values)/len(values) if values else None
                detail[metric+'_eligible_n']=len(values)
            row['per_difficulty'][difficulty]=detail
        row['cm_components']={}
        components=set()
        for i in items:
            components.update((i['metrics'].get('cm_components') or {}).keys())
        for component in sorted(components):
            scores=[]
            for i in items:
                value=(i['metrics'].get('cm_components') or {}).get(component)
                if isinstance(value,dict):
                    value=value.get('f1')
                if isinstance(value,(int,float)):
                    scores.append(value)
            row['cm_components'][component]=sum(scores)/len(scores) if scores else None
        rows.append(row)
    return {'rows':rows,'total_records':len(records),'expected_records':sum(expected.values()),'notes':['CM là trung bình F1 theo mẫu; xem cm_components để phân tích từng thành phần.','N/A không phải 0. Coverage ghi tỷ lệ mẫu đo được metric.','Độ trễ/token/chi phí gồm tất cả bước gọi model. Local API cost không bao gồm phần cứng/điện/huấn luyện.','Khoảng tin cậy Wilson 95% theo mẫu; các câu cùng database có thể tương quan.']}


class RunRepository:
    def __init__(self,root):
        self.root=Path(root)
        self.root.mkdir(parents=True,exist_ok=True)
        self.lock=threading.RLock()

    def path(self,run_id):
        if not isinstance(run_id,str) or not re.fullmatch(r'[a-f0-9]{32}',run_id):
            raise ValueError('Run ID không hợp lệ.')
        return self.root/(run_id+'.json')

    def save(self,run):
        path=self.path(run['id'])
        with self.lock:
            temporary=path.with_suffix('.tmp')
            temporary.write_text(json.dumps(run,ensure_ascii=False,indent=2),encoding='utf-8')
            temporary.replace(path)

    def load(self,run_id):
        with self.lock:
            run=json.loads(self.path(run_id).read_text(encoding='utf-8'))
            if run.get('state')=='running' and owner_alive(run.get('owner')) is False:
                run.update(state='interrupted',error='Tiến trình sở hữu run đã dừng; lượt đang chạy có thể chưa được ghi usage.',accounting_complete=False)
                self.save(run)
            return run

    def list(self):
        items=[]
        with self.lock:
            for path in sorted(self.root.glob('*.json'),key=lambda p:p.stat().st_mtime,reverse=True)[:50]:
                try:
                    value=self.load(path.stem)
                    items.append({key:value.get(key) for key in ('id','state','split','created_at','summary','dataset_fingerprint','done','total','error')})
                except (ValueError,OSError):
                    continue
        return items

    def csv(self,run_id):
        run=self.load(run_id); stream=io.StringIO(newline='')
        keys=['model_id','preset_id','n','expected_n','complete','em','cm','ex','ts','ves','syntax_valid_rate','execution_success_rate','errors','p50_latency_ms','p95_latency_ms','mean_sql_latency_ms','input_tokens','output_tokens','cached_input_tokens','calls','repair_calls','cost_usd','coverage','eligible_n','intervals','cm_components','per_difficulty','unavailable_reasons']
        writer=csv.DictWriter(stream,fieldnames=keys); writer.writeheader()
        for row in run['summary']['rows']:
            writer.writerow({key:json.dumps(row[key],ensure_ascii=False) if isinstance(row.get(key),(dict,list)) else row.get(key) for key in keys})
        return ('\ufeff'+stream.getvalue()).encode('utf-8')


class BenchmarkManager:
    def __init__(self,store,registry,root,presets,runner=None):
        from .pipeline import run_experiment
        self.store=store; self.registry=registry; self.repository=RunRepository(root)
        self.presets={p['id']:p for p in presets}; self.runner=runner or run_experiment
        self.lock=threading.Lock(); self.active={}

    def start(self,payload):
        split=payload.get('split','dev')
        if split not in ('dev','test'):
            raise ValueError('Benchmark dùng dev hoặc test; không chấm trên train.')
        if split=='test' and payload.get('final_evaluation') is not True:
            raise ValueError('Test được khóa; cần final_evaluation=true sau khi chốt cấu hình.')
        limit=payload.get('limit',10)
        if type(limit) is not int or limit<1 or limit>20000:
            raise ValueError('Số mẫu benchmark phải từ 1 đến 20.000.')
        model_ids=payload.get('model_ids',[]); preset_ids=payload.get('preset_ids',['c0'])
        if not isinstance(model_ids,list) or not model_ids or len(model_ids)>8 or len(set(model_ids))!=len(model_ids):
            raise ValueError('Chọn từ 1 đến 8 model khác nhau.')
        if not isinstance(preset_ids,list) or not preset_ids or any(p not in self.presets for p in preset_ids) or len(set(preset_ids))!=len(preset_ids):
            raise ValueError('Preset không hợp lệ hoặc trùng lặp.')
        models={m:self.registry.create(m) for m in model_ids}
        samples=self.store.samples(split,limit=limit)
        if not samples:
            raise ValueError('Chưa có dataset hoặc split rỗng.')
        metadata=self.store.summary()
        expected={m+':'+p:len(samples) for m in model_ids for p in preset_ids}
        code=code_snapshot()
        run={'id':uuid.uuid4().hex,'state':'running','split':split,'created_at':datetime.now(timezone.utc).isoformat(),'done':0,'total':sum(expected.values()),'error':None,'owner':process_identity(),'sample_ids':[s['id'] for s in samples],'dataset_fingerprint':metadata.get('fingerprint'),'dataset_revision':metadata.get('revision'),'dataset_source_hashes':metadata.get('source_hashes'),'database_hashes':metadata.get('database_hashes'),'metric_assets_fingerprint':metadata.get('metric_assets_fingerprint'),'evaluation_options':metadata.get('evaluation_options'),'models':[experiment_snapshot(models[m],m) for m in model_ids],'presets':[self.presets[p] for p in preset_ids],'code_sha256':code,'runtime':runtime_snapshot(),'records':[],'expected':expected,'summary':summarize_records([],expected),'evaluator_policy':'Spider EM/CM adapter ignores literal values and DISTINCT, uses FK equivalence; full bounded read-only EX only with compatible data; predicted values, no oracle plug_value; local validated TS and repeated VES adapters'}
        with self.lock:
            if any(not event.is_set() for event,thread in self.active.values() if thread.is_alive()):
                raise ValueError('Một benchmark đang chạy. Đợi hoàn tất hoặc hủy trước.')
            event=threading.Event()
            thread=threading.Thread(target=self._work,args=(run,samples,models,preset_ids,event),daemon=False)
            self.active[run['id']]=(event,thread)
            self.repository.save(run)
            thread.start()
        return {key:run[key] for key in ('id','state','total')}

    def _work(self,run,samples,models,presets,event):
        try:
            for sample in samples:
                for model_id,backend in models.items():
                    for preset_id in presets:
                        if event.is_set():
                            run['state']='cancelled'; return
                        options={k:v for k,v in self.presets[preset_id].items() if k in ('c1','c2','c3','c4','few_shot_k','max_repairs')}
                        prediction=self.runner(self.store,sample,backend,options,model_id=model_id)
                        record={**prediction,'sample_id':sample['id'],'db_id':sample['db_id'],'difficulty':sample.get('difficulty','unknown'),'preset_id':preset_id,'question':sample['question']}
                        run['records'].append(record)
                        run['done']=len(run['records']); run['summary']=summarize_records(run['records'],run['expected'])
                        self.repository.save(run)
            run['state']='completed'
        except Exception as exc:
            run.update(state='failed',error=str(exc))
        finally:
            run['summary']=summarize_records(run['records'],run['expected'])
            self.repository.save(run)

    def job(self,run_id):
        run=self.repository.load(run_id)
        return {key:run.get(key) for key in ('id','state','done','total','error','summary','dataset_fingerprint','split')}

    def wait(self,run_id,timeout=None):
        self.repository.path(run_id)
        with self.lock:
            active=self.active.get(run_id)
        if active:
            active[1].join(timeout)
        return self.job(run_id)

    def cancel(self,run_id):
        self.repository.path(run_id)
        with self.lock:
            if run_id in self.active:
                self.active[run_id][0].set()
        return self.job(run_id)
