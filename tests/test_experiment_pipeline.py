import json
import sqlite3
import tempfile
import unittest
from pathlib import Path


class StoreFixture:
    def __init__(self, db):
        self.db = db
        self.training = [{'id': 'train-1', 'split': 'train', 'db_id': 'shop', 'question': 'Liệt kê khách hàng', 'gold_sql': 'SELECT name FROM customers'}]

    def schema(self, db_id):
        return {'customers': {'ddl': 'CREATE TABLE customers(id INTEGER PRIMARY KEY, name TEXT)', 'description': '', 'columns': [{'name':'id','type':'INTEGER','pk':True},{'name':'name','type':'TEXT','pk':False}], 'foreign_keys': []}}

    def database_path(self, db_id):
        return self.db

    def samples(self, split, limit=None):
        if split != 'train':
            raise AssertionError('Retrieval must only access train')
        return self.training[:limit] if limit else self.training


class SequenceBackend:
    name = 'test-http-boundary'
    model = 'test-checkpoint'

    def __init__(self, replies):
        self.replies = iter(replies)
        self.prompts = []

    def generate(self, messages):
        self.prompts.append(json.loads(json.dumps(messages)))
        item = next(self.replies)
        if isinstance(item, Exception):
            raise item
        return {'text': json.dumps(item), 'input_tokens':10, 'output_tokens':5, 'cached_input_tokens':2, 'cost_usd':0.001, 'model':self.model}


class ExperimentPipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name)/'shop.sqlite'
        with sqlite3.connect(self.db) as con:
            con.executescript("CREATE TABLE customers(id INTEGER PRIMARY KEY,name TEXT); INSERT INTO customers VALUES(1,'Lan'),(2,'An');")
        self.store = StoreFixture(self.db)
        self.sample = {'id':'dev-1','split':'dev','db_id':'shop','question':'Tên khách hàng theo mã tăng dần','gold_sql':'SELECT name FROM customers ORDER BY id','difficulty':'easy'}

    def tearDown(self):
        self.temp.cleanup()

    def run_pipeline(self, backend, options=None):
        from text2sql_demo.experiment.pipeline import run_experiment
        return run_experiment(self.store,self.sample,backend,options or {},model_id='fixture')

    def test_c0_uses_generic_schema_without_retail_rules_or_gold(self):
        b=SequenceBackend([{'sql':'SELECT name FROM customers ORDER BY id'}])
        r=self.run_pipeline(b)
        prompt=json.dumps(b.prompts,ensure_ascii=False)
        self.assertNotIn(self.sample['gold_sql'],prompt)
        self.assertNotIn("orders.status",prompt)
        self.assertEqual(r['metrics']['calls'],1)
        self.assertEqual(r['execution']['rows'],[['Lan'],['An']])

    def test_auxiliary_calls_and_repairs_all_count_usage(self):
        b=SequenceBackend([{'subquestions':['Xác định tên khách hàng']},{'select':['name'],'order_by':['id ASC']},{'sql':'SELECT missing FROM customers'},{'sql':'SELECT name FROM customers ORDER BY id'}])
        r=self.run_pipeline(b,{'c1':True,'c3':True,'c4':True})
        self.assertEqual(r['status'],'ok')
        self.assertEqual(r['metrics']['calls'],4)
        self.assertEqual(r['metrics']['input_tokens'],40)
        self.assertAlmostEqual(r['metrics']['cost_usd'],0.004)
        self.assertEqual([t['stage'] for t in r['trace'] if t.get('model_call')],['c1','c3','generate','repair'])

    def test_retrieval_excludes_same_question_and_non_train(self):
        self.store.training.append({**self.sample,'id':'train-duplicate','split':'train'})
        b=SequenceBackend([{'sql':'SELECT name FROM customers ORDER BY id'}])
        r=self.run_pipeline(b,{'c2':True})
        self.assertNotIn('train-duplicate',r['example_ids'])
        self.assertEqual(r['example_ids'],['train-1'])

    def test_repair_budget_stops_even_when_sql_keeps_changing(self):
        b=SequenceBackend([{'sql':f'SELECT missing{i} FROM customers'} for i in range(4)])
        r=self.run_pipeline(b,{'c4':True,'max_repairs':2})
        self.assertEqual(r['metrics']['calls'],3)
        self.assertEqual(r['status'],'error')

    def test_free_question_has_no_gold_scores(self):
        self.sample['gold_sql']=None
        b=SequenceBackend([{'sql':'SELECT name FROM customers'}])
        r=self.run_pipeline(b)
        self.assertIsNone(r['metrics']['em'])
        self.assertIsNone(r['metrics']['ex'])

    def test_auxiliary_error_keeps_previous_usage_and_missing_usage_unknown(self):
        b=SequenceBackend([{'subquestions':['Tên khách hàng']}, RuntimeError('Transport failed')])
        r=self.run_pipeline(b,{'c1':True,'c3':True})
        self.assertEqual(r['status'],'error')
        self.assertEqual(r['metrics']['calls'],2)
        self.assertIsNone(r['metrics']['input_tokens'])
        self.assertEqual(r['metrics']['known_input_tokens'],10)

    def test_vietnamese_raw_identifier_policy_matches_evaluator(self):
        from text2sql_demo.experiment.pipeline import execute_preview
        schema={'kiến trúc sư':{'ddl':'CREATE TABLE "kiến trúc sư"("giới tính" TEXT)','columns':[{'name':'giới tính','type':'TEXT','pk':False}],'foreign_keys':[]}}
        class SchemaOnly:
            def database_path(self,db_id): return None
        result=execute_preview(SchemaOnly(),'architecture',"SELECT COUNT(*) FROM kiến trúc sư WHERE giới tính = 'Nữ'",schema)
        self.assertEqual(result['status'],'schema_only')
        self.assertIn('"kiến trúc sư"',result['executed_sql'])
        self.assertEqual(result['rows'],[])
