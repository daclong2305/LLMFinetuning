"""Safe reproducibility metadata and read-only process identity checks."""
import hashlib
import json
import os
import platform
import subprocess
import sys
from pathlib import Path


def file_hash(path):
    path=Path(path)
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def process_identity(pid=None):
    pid=os.getpid() if pid is None else pid
    if type(pid) is not int or pid<=0:
        return None
    if os.name=='nt':
        import ctypes
        from ctypes import wintypes
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
        kernel.OpenProcess.restype=wintypes.HANDLE
        kernel.GetProcessTimes.argtypes=[wintypes.HANDLE]+[ctypes.POINTER(wintypes.FILETIME)]*4
        kernel.GetProcessTimes.restype=wintypes.BOOL
        kernel.GetExitCodeProcess.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)]
        kernel.GetExitCodeProcess.restype=wintypes.BOOL
        kernel.CloseHandle.argtypes=[wintypes.HANDLE]
        handle=kernel.OpenProcess(0x1000,False,pid)
        if not handle:
            return {'pid':pid,'start_token':None,'unknown':True} if ctypes.get_last_error()==5 else None
        try:
            exit_code=wintypes.DWORD()
            if not kernel.GetExitCodeProcess(handle,ctypes.byref(exit_code)) or exit_code.value!=259:
                return None
            times=[wintypes.FILETIME() for _ in range(4)]
            if not kernel.GetProcessTimes(handle,*[ctypes.byref(t) for t in times]):
                return {'pid':pid,'start_token':None,'unknown':True}
            token=(times[0].dwHighDateTime<<32)|times[0].dwLowDateTime
            return {'pid':pid,'start_token':str(token)}
        finally:
            kernel.CloseHandle(handle)
    proc=Path('/proc')/str(pid)/'stat'
    if Path('/proc').is_dir():
        try:
            fields=proc.read_text().rsplit(')',1)[1].split()
            return {'pid':pid,'start_token':fields[19]}
        except FileNotFoundError:
            return None
        except (PermissionError,IndexError):
            return {'pid':pid,'start_token':None,'unknown':True}
    try:
        token=subprocess.check_output(['ps','-o','lstart=','-p',str(pid)],timeout=2,text=True).strip()
        return {'pid':pid,'start_token':token} if token else None
    except (OSError,subprocess.SubprocessError):
        return {'pid':pid,'start_token':None,'unknown':True}


def owner_alive(owner):
    if not isinstance(owner,dict):
        return False
    actual=process_identity(owner.get('pid'))
    if actual is None:
        return False
    if actual.get('unknown') or owner.get('start_token') is None:
        return None
    return actual['start_token']==owner.get('start_token')


def runtime_snapshot():
    result={'python':sys.version,'platform':platform.platform(),'processor':platform.processor(),'logical_cpu_count':os.cpu_count()}
    try:
        text=subprocess.check_output(['nvidia-smi','--query-gpu=name,memory.total,driver_version','--format=csv,noheader'],timeout=3,text=True,stderr=subprocess.DEVNULL).strip()
        result['gpu']=text
    except (OSError,subprocess.SubprocessError):
        result['gpu']=None
    return result


def experiment_snapshot(backend,model_id):
    allowed=('provider','model','base_url','num_gpu','num_ctx','num_predict','temperature','seed','timeout_s','max_output_tokens','options','pricing','pricing_date','api_key_env')
    config=getattr(backend,'config',{})
    inference={key:config[key] for key in allowed if key in config}
    # Do not include any raw credentials, even from an extension's options.
    def redact(value):
        if isinstance(value,dict):
            return {k:redact(v) for k,v in value.items() if not any(s in k.lower() for s in ('secret','password','authorization','token','api_key'))}
        if isinstance(value,list):
            return [redact(v) for v in value]
        return value
    inference=redact(inference)
    manifest=config.get('training_manifest')
    return {'id':model_id,'model':getattr(backend,'model',None),'provider':getattr(backend,'name',config.get('provider')),'inference':inference,'model_digest':getattr(backend,'model_digest',None),'quantization':getattr(backend,'quantization',None),'training_manifest_sha256':file_hash(manifest) if manifest else None,'config_sha256':hashlib.sha256(json.dumps(inference,sort_keys=True).encode()).hexdigest()}


def code_snapshot():
    root=Path(__file__).resolve().parent
    paths=list(root.glob('*.py'))+list((root/'vendor'/'spider').glob('*.py'))
    return {str(p.relative_to(root)).replace('\\','/'):file_hash(p) for p in sorted(paths)}


def evaluator_fingerprint():
    code=code_snapshot()
    keys=('dataset.py','evaluation.py','vendor/spider/process_sql.py','vendor/spider/evaluation.py')
    return hashlib.sha256(json.dumps({k:code[k] for k in keys},sort_keys=True).encode()).hexdigest()


def validate_comparable_runs(runs):
    if not runs:
        raise ValueError('Chưa có run để đối chiếu.')
    keys=('dataset_fingerprint','metric_assets_fingerprint','split','sample_ids','evaluator_policy','code_sha256')
    reference=runs[0]
    for run in runs:
        if run.get('state')!='completed':
            raise ValueError('Chỉ đối chiếu run đã hoàn tất; run partial/cancelled/interrupted không tương đương full benchmark.')
        for key in keys:
            if key not in run or run[key]!=reference.get(key):
                raise ValueError('Run không có cùng giao thức đối chiếu: '+key)
    return True
