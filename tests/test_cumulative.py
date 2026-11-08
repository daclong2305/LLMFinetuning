import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_experiment_pipeline import StoreFixture, SequenceBackend
from text2sql_demo.experiment.benchmark import BenchmarkManager, select_samples
from text2sql_demo.experiment.pipeline import preview_prompt, run_experiment


class CumulativeTests(unittest.TestCase):
    def test_config_presets_add_exactly_one_module(self):
        config=json.loads((Path(__file__).parents[1]/'config/experiment.json').read_text(encoding='utf-8'))
        presets={p['id']:p for p in config['presets']}
        for n in range(5):
            self.assertEqual([presets[f'p{n}'][f'c{k}'] for k in range(1,5)], [k<=n for k in range(1,5)])

    def test_preview_does_not_call_model_or_read_target_gold(self):
        class NoGold(dict):
            def __getitem__(self,key):
                if key=='gold_sql': raise AssertionError('gold accessed')
                return super().__getitem__(key)
        store=StoreFixture(None)
        sample=NoGold(id='dev-1',db_id='shop',question='Tên khách hàng')
        with patch.object(SequenceBackend,'generate',side_effect=AssertionError('model called')):
            result=preview_prompt(store,sample,{'c1':True,'c2':True,'c3':True,'c4':True})
        text=json.dumps(result,ensure_ascii=False)
        self.assertFalse(result['model_called'])
        self.assertEqual(result['example_ids'],['train-1'])
        self.assertIn('chưa gọi model C1',text)
        self.assertIn('chưa gọi model C3',text)

    def test_c4_success_does_not_make_repair_call_and_trace_is_immutable(self):
        backend=SequenceBackend([{'sql':'SELECT name FROM customers'}])
        result=run_experiment(StoreFixture(None),{'id':'dev-1','db_id':'shop','question':'Tên khách hàng','gold_sql':None},backend,{'c4':True})
        self.assertEqual(result['status'],'ok')
        self.assertEqual(result['metrics']['repair_calls'],0)
        self.assertEqual(result['metrics']['calls'],1)
        backend.prompts[0][0]['content']='changed'
        self.assertNotEqual(result['trace'][0]['messages'][0]['content'],'changed')

    def test_balanced_selection_is_deterministic_unique_and_spreads_databases(self):
        samples=[{'id':str(i),'db_id':str(i//4),'difficulty':['easy','hard'][i%2]} for i in range(20)]
        selected=select_samples(samples,8,'balanced')
        self.assertEqual(selected,select_samples(samples,8,'balanced'))
        self.assertEqual(len({s['id'] for s in selected}),8)
        self.assertGreater(len({s['db_id'] for s in selected}),1)
        self.assertEqual(len(select_samples(samples,100,'balanced')),20)

    def test_explicit_sample_ids_cannot_bypass_split_or_duplicate(self):
        class Store:
            def samples(self,split,limit=None): return [{'id':'dev:1','db_id':'x'}]
        class Registry:
            def create(self,m): return object()
        with tempfile.TemporaryDirectory() as temp:
            manager=BenchmarkManager(Store(),Registry(),temp,[{'id':'p0'}])
            for ids in [['test:1'],['dev:1','dev:1'],[]]:
                with self.assertRaises(ValueError):
                    manager.start({'split':'dev','model_ids':['q'],'preset_ids':['p0'],'sample_ids':ids})
            with self.assertRaises(ValueError):
                manager.start({'split':'test','model_ids':['q'],'preset_ids':['p0'],'sample_ids':['dev:1']})
