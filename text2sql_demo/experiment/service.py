"""Local API orchestration; credentials never enter a response or run manifest."""
import hashlib
import json
import os
import threading
import uuid
from pathlib import Path

from .backends import BackendRegistry,load_local_env
from .benchmark import BenchmarkManager
from .dataset import DatasetStore
from .pipeline import run_experiment,validate_options
from .training import training_status


METRICS=[
    {'id':'em','label':'EM','description':'Exact Set Match theo Spider: cấu trúc SQL, bỏ giá trị literal và DISTINCT theo chính sách evaluator gốc. Không phải so chuỗi.'},
    {'id':'cm','label':'CM / F1','description':'Trung bình F1 các thành phần SQL có mặt; có breakdown SELECT/WHERE/GROUP/ORDER/KEYWORDS và thành phần phụ của Spider.'},
    {'id':'ex','label':'EX','description':'Kết quả SQL khớp gold trên database đầy đủ đã audit. Giữ duplicate và thứ tự khi gold có ORDER BY; không dùng preview 200 dòng.'},
    {'id':'ts','label':'TS','description':'Test Suite Accuracy: so kết quả trên nhiều database tương thích. N/A khi chưa có test suite đã xác minh.'},
    {'id':'ves','label':'VES','description':'Điểm kết hợp SQL đúng và hiệu quả thực thi tương đối với gold. Cần database và đo lặp ổn định, không dùng độ trễ LLM thay thế.'},
    {'id':'syntax_valid','label':'SQL hợp lệ','description':'Kiểm tra cú pháp và tên bảng/cột bằng SQLite schema. Schema-only không chứng minh kết quả dữ liệu đúng.'},
    {'id':'execution_success','label':'Thực thi thành công','description':'SQL chạy được trên database có dữ liệu. Khác EX: SQL có thể chạy nhưng sai ý câu hỏi.'},
    {'id':'latency_ms','label':'Độ trễ toàn pipeline','description':'Thời gian tất cả bước model, SQL và evaluation; benchmark có p50/p95. Điều kiện phần cứng/mạng khác nhau được lưu.'},
    {'id':'sql_latency_ms','label':'Độ trễ SQL','description':'Thời gian chạy SQL, riêng với thời gian LLM.'},
    {'id':'calls','label':'Lượt gọi model','description':'Tính C1/C3/sinh SQL/sửa lỗi, kể cả yêu cầu lỗi.'},
    {'id':'input_tokens','label':'Token đầu vào','description':'Usage thực từ tất cả lượt gọi; tokenizers giữa các nhà cung cấp có thể khác. N/A nếu nhà cung cấp không báo.'},
    {'id':'output_tokens','label':'Token đầu ra','description':'Usage thực từ tất cả lượt gọi.'},
    {'id':'cached_input_tokens','label':'Cached tokens','description':'Token đầu vào được cache; tính theo đơn giá cached riêng khi provider cung cấp.'},
    {'id':'cost_usd','label':'Chi phí API USD','description':'Tổng tất cả lượt gọi theo bảng giá cấu hình. Local API cost không gồm điện/GPU/huấn luyện. N/A khi thiếu usage hoặc đơn giá.'},
]


def load_config(root,provided=None):
    root=Path(root)
    if provided is None:
        provided=root/'config'/'experiment.json'
    config=json.loads(Path(provided).read_text(encoding='utf-8')) if not isinstance(provided,dict) else json.loads(json.dumps(provided))
    for key,default in [('dataset_root','.runtime/datasets/vitext2sql'),('database_dir','.runtime/datasets/vitext2sql/database'),('runs_dir','reports/experiments'),('env_file','.env')]:
        value=Path(config.get(key,default))
        config[key]=str(value if value.is_absolute() else root/value)
    configured_dir=os.environ.get('TEXT2SQL_DATABASE_DIR')
    if configured_dir:
        config['database_dir']=str(Path(configured_dir).resolve())
    for model in config.get('models',[]):
        if model.get('training_manifest'):
            path=Path(model['training_manifest'])
            model['training_manifest']=str(path if path.is_absolute() else root/path)
    return config


class ExperimentService:
    def __init__(self,root,config=None,inference_lock=None):
        self.root=Path(root); self.config=load_config(root,config)
        self.store=DatasetStore(self.config['dataset_root'],self.config['database_dir'])
        self.registry=BackendRegistry(self.config)
        self.inference_lock=inference_lock or threading.Lock()
        self.benchmarks=BenchmarkManager(self.store,self.registry,self.config['runs_dir'],self.config.get('presets',[]),runner=self._benchmark_run)

    def _refresh_credentials(self):
        load_local_env(self.config['env_file'])

    def _benchmark_run(self,*args,**kwargs):
        with self.inference_lock:
            return run_experiment(*args,**kwargs)

    def info(self):
        self._refresh_credentials()
        trained=next((m for m in self.config.get('models',[]) if m.get('trained')),None)
        status=training_status(trained.get('training_manifest','')) if trained else {'state':'unavailable','reason':'No trained model is configured.'}
        return {'dataset':self.store.summary(),'models':self.registry.list_models(),'presets':self.config.get('presets',[]),'metric_definitions':METRICS,'training':status,'gpt_snapshot':'gpt-4.1-mini-2025-04-14','method_note':'C1–C4 là module nghiên cứu đại diện; không phải tái lập nguyên bản DIN-SQL/DAIL-SQL.','setup':{'dataset':'python scripts/prepare_vitext2sql.py --audit','training':'python scripts/train_qwen.py --prepare-only','credential':'Tạo .env local từ .env.example hoặc cấu hình biến môi trường cho API. Không gửi khóa trong chat.'}}

    def get(self,route,params):
        if route=='/api/experiment/info':
            return self.info(),200,'application/json; charset=utf-8',None
        if route=='/api/experiment/samples':
            split=params.get('split','dev'); limit=int(params.get('limit','30')); offset=int(params.get('offset','0'))
            if not 1<=limit<=100 or offset<0:
                raise ValueError('Pagination không hợp lệ.')
            samples=self.store.samples(split)
            question=params.get('q','').casefold().strip()
            if question:
                samples=[s for s in samples if question in s['question'].casefold() or question in s['db_id'].casefold()]
            return {'items':[{k:s[k] for k in ('id','split','db_id','question','difficulty')} for s in samples[offset:offset+limit]],'total':len(samples),'split':split},200,'application/json; charset=utf-8',None
        if route=='/api/experiment/schema':
            db=params.get('db_id','')
            return {'db_id':db,'schema':self.store.schema(db)},200,'application/json; charset=utf-8',None
        if route=='/api/experiment/job':
            return self.benchmarks.job(params.get('id','')),200,'application/json; charset=utf-8',None
        if route=='/api/experiment/runs':
            return {'runs':self.benchmarks.repository.list()},200,'application/json; charset=utf-8',None
        if route=='/api/experiment/export':
            run_id=params.get('id',''); kind=params.get('format','json')
            if kind=='csv':
                return self.benchmarks.repository.csv(run_id),200,'text/csv; charset=utf-8',f'benchmark-{run_id}.csv'
            if kind=='json':
                return self.benchmarks.repository.load(run_id),200,'application/json; charset=utf-8',f'benchmark-{run_id}.json'
            raise ValueError('Export dùng csv hoặc json.')
        return {'error':'Không tìm thấy API thực nghiệm.'},404,'application/json; charset=utf-8',None

    def post(self,route,payload):
        self._refresh_credentials()
        if route=='/api/experiment/compare':
            options=validate_options(payload.get('options',{}))
            if not self.store.summary()['ready']:
                raise ValueError('ViText2SQL chưa được chuẩn bị; chạy scripts/prepare_vitext2sql.py.')
            model_ids=payload.get('model_ids',[])
            if not isinstance(model_ids,list) or not model_ids or len(model_ids)>8 or any(not isinstance(x,str) for x in model_ids) or len(set(model_ids))!=len(model_ids):
                raise ValueError('Chọn từ 1 đến 8 model khác nhau.')
            if payload.get('sample_id'):
                sample=self.store.get_sample(payload['sample_id'])
                if sample['split']=='test':
                    raise ValueError('Mẫu test được khóa cho benchmark đánh giá cuối.')
            else:
                question=payload.get('question',''); db=payload.get('db_id','')
                if not isinstance(question,str) or not 1<=len(question.strip())<=2000 or not isinstance(db,str):
                    raise ValueError('Câu hỏi cần từ 1 đến 2.000 ký tự và database hợp lệ.')
                self.store.schema(db)
                sample={'id':'custom:'+uuid.uuid4().hex,'split':'custom','db_id':db,'question':question.strip(),'gold_sql':None,'difficulty':'unknown'}
            backends={m:self.registry.create(m) for m in model_ids}
            if not self.inference_lock.acquire(blocking=False):
                return {'error':'Model đang xử lý truy vấn/benchmark. Đợi hoàn tất rồi thử lại.'},409
            try:
                results=[]; labels={m['id']:m.get('label',m['id']) for m in self.config['models']}
                for model_id,backend in backends.items():
                    result=run_experiment(self.store,sample,backend,options,model_id)
                    result['label']=labels[model_id]; results.append(result)
                return {'id':uuid.uuid4().hex,'sample':sample,'results':results,'dataset_fingerprint':self.store.summary()['fingerprint']},200
            finally:
                self.inference_lock.release()
        if route=='/api/experiment/benchmark':
            return self.benchmarks.start(payload),202
        if route=='/api/experiment/cancel':
            return self.benchmarks.cancel(payload.get('id','')),200
        return {'error':'Không tìm thấy API thực nghiệm.'},404
