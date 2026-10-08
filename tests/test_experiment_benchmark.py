import tempfile
import os
import threading
import time
import unittest
from pathlib import Path


class BenchmarkTests(unittest.TestCase):
    def test_summary_counts_prediction_errors_and_exposes_missing_coverage(self):
        from text2sql_demo.experiment.benchmark import summarize_records
        records=[]
        for i,em in enumerate([True,False,False]):
            records.append({'sample_id':str(i),'model_id':'q','preset_id':'c0','difficulty':'easy','status':'ok' if i<2 else 'error','metrics':{'em':em,'cm':1 if em else 0,'ex':None,'ts':None,'ves':None,'syntax_valid':i<2,'execution_success':None,'latency_ms':[100,200,300][i],'calls':1,'input_tokens':10,'output_tokens':5,'cost_usd':0}})
        row=summarize_records(records,{'q:c0':3})['rows'][0]
        self.assertAlmostEqual(row['em'],1/3)
        self.assertEqual(row['n'],3)
        self.assertEqual(row['coverage']['ex'],0)
        self.assertIsNone(row['ex'])
        self.assertEqual(row['p50_latency_ms'],200)
        self.assertEqual(row['errors'],1)

    def test_partial_summary_reports_actual_and_expected_denominators(self):
        from text2sql_demo.experiment.benchmark import summarize_records
        r={'sample_id':'1','model_id':'q','preset_id':'c0','difficulty':'hard','metrics':{'em':True,'latency_ms':100}}
        row=summarize_records([r],{'q:c0':10})['rows'][0]
        self.assertEqual(row['n'],1)
        self.assertEqual(row['expected_n'],10)
        self.assertFalse(row['complete'])

    def test_rejects_arbitrary_run_path(self):
        from text2sql_demo.experiment.benchmark import RunRepository
        with tempfile.TemporaryDirectory() as temp:
            repo=RunRepository(Path(temp))
            with self.assertRaises(ValueError):
                repo.load('../secrets')

    def test_partial_metering_preserves_known_subtotals(self):
        from text2sql_demo.experiment.benchmark import summarize_records
        record={'model_id':'q','preset_id':'c0','metrics':{'calls':2,'input_tokens':None,'known_input_tokens':100,'output_tokens':None,'known_output_tokens':20,'cost_usd':None,'known_cost_usd':.01}}
        row=summarize_records([record],{'q:c0':1})['rows'][0]
        self.assertIsNone(row['cost_usd'])
        self.assertAlmostEqual(row['known_cost_usd'],.01)
        self.assertEqual(row['known_input_tokens'],100)

    def test_run_manifest_locks_effective_settings_and_cross_manager_liveness(self):
        from text2sql_demo.experiment.benchmark import BenchmarkManager
        started=threading.Event(); release=threading.Event()
        class Store:
            def summary(self): return {'fingerprint':'data-fixed','revision':'source-fixed','source_hashes':{'train.json':'abc'},'metric_assets_fingerprint':'metric-fixed'}
            def samples(self,split,limit=None): return [{'id':'dev:1','db_id':'x','question':'q','difficulty':'easy'}]
        class Backend:
            model='local-fixed'; model_digest='digest-fixed'; quantization='Q4_K_M'
            config={'provider':'ollama','model':'local-fixed','num_ctx':16384,'temperature':0,'api_key':'secret-must-not-persist'}
        class Registry:
            def create(self,model_id): return Backend()
        def runner(*args,**kwargs):
            started.set(); release.wait(2)
            return {'model_id':'q','status':'ok','metrics':{'em':True,'calls':1,'input_tokens':10,'output_tokens':5,'cost_usd':0}}
        with tempfile.TemporaryDirectory() as temp:
            manager=BenchmarkManager(Store(),Registry(),temp,[{'id':'c0'}],runner)
            job=manager.start({'model_ids':['q'],'preset_ids':['c0']})
            self.assertTrue(started.wait(1))
            try:
                observer=BenchmarkManager(Store(),Registry(),temp,[{'id':'c0'}],runner)
                self.assertEqual(observer.job(job['id'])['state'],'running')
                manifest=manager.repository.load(job['id'])
                self.assertEqual(manifest['models'][0]['inference']['num_ctx'],16384)
                self.assertEqual(manifest['models'][0]['model_digest'],'digest-fixed')
                self.assertEqual(manifest['metric_assets_fingerprint'],'metric-fixed')
                self.assertNotIn('secret-must-not-persist',str(manifest))
            finally:
                release.set(); manager.active[job['id']][1].join(2)

    def test_cancel_wait_preserves_current_inference_usage(self):
        from text2sql_demo.experiment.benchmark import BenchmarkManager
        started=threading.Event(); release=threading.Event()
        class Store:
            def summary(self): return {'fingerprint':'data-fixed'}
            def samples(self,split,limit=None): return [{'id':str(i),'db_id':'x','question':'q'} for i in range(2)]
        class Backend: model='fixture'
        class Registry:
            def create(self,model_id): return Backend()
        def runner(*args,**kwargs):
            started.set(); release.wait(2)
            return {'model_id':'q','status':'ok','metrics':{'calls':1,'input_tokens':10,'output_tokens':5,'cost_usd':.02}}
        with tempfile.TemporaryDirectory() as temp:
            manager=BenchmarkManager(Store(),Registry(),temp,[{'id':'c0'}],runner)
            job=manager.start({'model_ids':['q']})
            self.assertTrue(started.wait(1)); manager.cancel(job['id']); release.set()
            try:
                status=manager.wait(job['id'],timeout=2)
                self.assertEqual(status['state'],'cancelled')
                self.assertEqual(status['done'],1)
                self.assertAlmostEqual(status['summary']['rows'][0]['cost_usd'],.02)
            finally:
                manager.active[job['id']][1].join(2)

    def test_dead_owner_reconciles_status_history_and_export(self):
        from text2sql_demo.experiment.benchmark import RunRepository
        with tempfile.TemporaryDirectory() as temp:
            repo=RunRepository(temp)
            run_id='a'*32
            repo.save({'id':run_id,'state':'running','owner':{'pid':os.getpid(),'start_token':'not-this-process'},'split':'dev','created_at':'2026-10-07','done':0,'total':1,'summary':{'rows':[]}})
            self.assertEqual(repo.load(run_id)['state'],'interrupted')
            self.assertEqual(repo.list()[0]['state'],'interrupted')
