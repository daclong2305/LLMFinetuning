"""Live model checks on synthetic demo data; not Spider/BIRD evaluation."""
import json
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from text2sql_demo.backends import OllamaBackend
from text2sql_demo.database import create_demo_database, execute_readonly
from text2sql_demo.examples import EXAMPLES
from text2sql_demo.evaluation import compare_rows
from text2sql_demo.pipeline import run_question

root = Path(__file__).resolve().parent.parent
db = root/'data'/'demo.sqlite'
create_demo_database(db)
backend = OllamaBackend()
records = []
cases = [dict(EXAMPLES[i],ordered=i in (0,4,5)) for i in (0,1,2,3,4,5)]
# The question asks for customer identity, not their city; check names only.
cases[3]['sql'] = 'SELECT c.name FROM customers c LEFT JOIN orders o ON o.customer_id=c.id WHERE o.id IS NULL ORDER BY c.id'
cases += [{'question':'Liệt kê tên các sản phẩm thuộc danh mục Điện tử, sắp xếp theo mã sản phẩm.', 'sql':"SELECT name FROM products WHERE category='Điện tử' ORDER BY id",'ordered':True}]
for case in cases:
    result = run_question(db,case['question'],backend,linking=True)
    gold = execute_readonly(db,case['sql'])
    matched = result['status']=='ok' and compare_rows(result['execution']['rows'],gold['rows'],ordered=case['ordered'])
    records.append({'question':case['question'],'matched_reference':matched,'ordered':case['ordered'],'reference_sql':case['sql'],'reference_rows':gold['rows'],'result':result})
    print(json.dumps({'question':case['question'],'matched':matched,'seconds':round(result['duration_ms']/1000,2),'attempts':len(result['attempts']),'error':result['error']},ensure_ascii=True),flush=True)
output = root/'reports'/'demo-live-smoke.json'
output.parent.mkdir(exist_ok=True)
output.write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
print(f'Passed {sum(r["matched_reference"] for r in records)}/{len(records)} live checks; {output}',flush=True)
sys.exit(0 if all(r['matched_reference'] for r in records) else 1)
