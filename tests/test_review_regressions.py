import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from contextlib import closing

from text2sql_demo.experiment.dataset import DatasetStore,REVISION,FILES
from text2sql_demo.experiment.evaluation import evaluate_prediction


class QueryStore:
    def __init__(self,path=None): self.path=path
    def database_path(self,db_id): return self.path
    def schema(self,db_id):
        return {'t':{'columns':[{'name':c,'type':'INTEGER','pk':False} for c in ('a','b','c')],'foreign_keys':[]}}


def dataset_fixture(root):
    tables=[]
    for split in ('train','dev','test'):
        db='db_'+split
        rows=[{'db_id':db,'question':'Câu hỏi '+split,'query':'select a from t','sql':None}]
        (root/(split+'.json')).write_text(json.dumps(rows),encoding='utf-8')
        tables.append({'db_id':db,'table_names_original':['t'],'column_names_original':[[-1,'*'],[0,'a']],'column_types':['text','number'],'primary_keys':[],'foreign_keys':[]})
    (root/'tables.json').write_text(json.dumps(tables),encoding='utf-8')
    hashes={f:hashlib.sha256((root/f).read_bytes()).hexdigest() for f in FILES}
    (root/'source-lock.json').write_text(json.dumps({'revision':REVISION,'sha256':hashes}),encoding='utf-8')


class ReviewRegressionTests(unittest.TestCase):
    def test_column_rhs_or_is_not_dropped_from_structural_score(self):
        sample={'db_id':'x','gold_sql':'select a from t where a=b'}
        result=evaluate_prediction('select a from t where a=b or c=a',sample,QueryStore())
        self.assertEqual(result['em'],0)
        self.assertLess(result['cm'],1)

    def test_malformed_sql_cannot_receive_perfect_structural_score(self):
        sample={'db_id':'x','gold_sql':'select a from t'}
        for sql in ('select a, from t','select a from t where'):
            with self.subTest(sql=sql):
                result=evaluate_prediction(sql,sample,QueryStore())
                self.assertEqual(result['em'],0)
                self.assertEqual(result['cm'],0)
                self.assertFalse(result['syntax_valid'])

    def test_order_by_inside_literal_does_not_require_ordered_rows(self):
        with tempfile.TemporaryDirectory() as temp:
            db=Path(temp)/'t.sqlite'
            with closing(sqlite3.connect(db)) as con,con:
                con.executescript("create table t(a integer,b text,c integer); insert into t values(2,'order by',0),(1,'order by',0);")
            sample={'db_id':'x','gold_sql':"select a from t where b='order by'"}
            result=evaluate_prediction(sample['gold_sql']+' order by a',sample,QueryStore(db))
            self.assertEqual(result['ex'],1)

    def test_consistent_projection_permutation_is_equivalent(self):
        with tempfile.TemporaryDirectory() as temp:
            db=Path(temp)/'t.sqlite'
            with closing(sqlite3.connect(db)) as con,con:
                con.executescript('create table t(a integer,b integer,c integer); insert into t values(1,2,0),(2,3,0);')
            result=evaluate_prediction('select b,a from t',{'db_id':'x','gold_sql':'select a,b from t'},QueryStore(db))
            self.assertEqual(result['ex'],1)

    def test_wal_updates_are_rejected_instead_of_changing_snapshot_scores(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); dataset_fixture(root)
            folder=root/'database'; folder.mkdir(); path=folder/'db_dev.sqlite'
            with closing(sqlite3.connect(path)) as con,con:
                con.executescript('create table t(a integer); insert into t values(1);')
            writer=sqlite3.connect(path)
            try:
                writer.execute('pragma journal_mode=wal')
                writer.execute('pragma wal_checkpoint(truncate)')
                store=DatasetStore(root)
                writer.execute('insert into t values(2)'); writer.commit()
                with self.assertRaisesRegex(ValueError,'WAL|frozen|snapshot'):
                    store.database_path('db_dev')
            finally:
                writer.close()

    def test_database_attached_after_initialization_is_untracked(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); dataset_fixture(root); store=DatasetStore(root)
            folder=root/'database'; folder.mkdir()
            with closing(sqlite3.connect(folder/'db_dev.sqlite')) as con,con:
                con.executescript('create table t(a integer); insert into t values(1);')
            with self.assertRaisesRegex(ValueError,'snapshot|reload'):
                store.database_path('db_dev')

    def test_prediction_timeout_is_in_execution_accuracy_denominator(self):
        with tempfile.TemporaryDirectory() as temp:
            db=Path(temp)/'t.sqlite'
            with closing(sqlite3.connect(db)) as con,con:
                con.executescript('create table t(a integer,b integer,c integer); insert into t values(1,2,3);')
            sql='WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM n WHERE x<1000000000) SELECT SUM(x) FROM n'
            result=evaluate_prediction(sql,{'db_id':'x','gold_sql':'select a from t'},QueryStore(db),timeout_s=.01)
            self.assertEqual(result['ex'],0)
            self.assertFalse(result['execution_success'])
            self.assertTrue(result['syntax_valid'])
