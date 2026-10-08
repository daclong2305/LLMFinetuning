"""Run a frozen experiment matrix via the same service used by the dashboard."""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser(description='Benchmark Text-to-SQL trên split ViText2SQL cố định')
    parser.add_argument('--config',type=Path,default=ROOT/'config'/'experiment.json')
    parser.add_argument('--split',choices=['dev','test'],default='dev')
    parser.add_argument('--limit',type=int,default=10)
    parser.add_argument('--models',nargs='+',default=['qwen_base'])
    parser.add_argument('--presets',nargs='+',default=['c0'])
    parser.add_argument('--final-evaluation',action='store_true')
    parser.add_argument('--output',type=Path)
    parser.add_argument('--status',metavar='RUN_ID')
    args=parser.parse_args()
    if hasattr(sys.stdout,'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    from text2sql_demo.experiment.service import ExperimentService
    service=ExperimentService(ROOT,args.config)
    if args.status:
        print(json.dumps(service.benchmarks.job(args.status),ensure_ascii=False,indent=2)); return
    job=service.benchmarks.start({'split':args.split,'limit':args.limit,'model_ids':args.models,'preset_ids':args.presets,'final_evaluation':args.final_evaluation})
    print('Run: '+job['id'],flush=True)
    try:
        previous=None
        while True:
            status=service.benchmarks.job(job['id'])
            progress=(status['state'],status['done'])
            if progress!=previous:
                print(f"{status['state']}: {status['done']}/{status['total']}",flush=True); previous=progress
            if status['state']!='running':
                break
            time.sleep(1)
    except KeyboardInterrupt:
        service.benchmarks.cancel(job['id'])
        print('Đã yêu cầu dừng sau lượt suy luận hiện tại.',flush=True)
        while True:
            status=service.benchmarks.wait(job['id'],timeout=1)
            if status['state']!='running':
                break
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_bytes(service.benchmarks.repository.csv(job['id']))
    print(json.dumps(status,ensure_ascii=False,indent=2))
    if status['state']!='completed':
        raise SystemExit(130 if status['state']=='cancelled' else 1)


if __name__=='__main__':
    main()
