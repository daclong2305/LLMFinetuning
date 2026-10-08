import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from text2sql_demo.database import create_demo_database
from text2sql_demo.server import make_server


class ExperimentServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(); cls.root=Path(cls.temp.name)
        cls.db=cls.root/'retail.sqlite'; create_demo_database(cls.db)
        cls.config={'dataset_root':str(cls.root/'missing'),'database_dir':str(cls.root/'db'),'runs_dir':str(cls.root/'runs'),'models':[],'presets':[{'id':'c0','label':'C0','c1':False,'c2':False,'c3':False,'c4':False}]}
        cls.server=make_server(cls.db,port=0,experiment_config=cls.config)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True); cls.thread.start()
        cls.base=f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join(); cls.temp.cleanup()

    def request(self,path,payload=None,origin=None):
        headers={'Content-Type':'application/json'}
        if origin: headers['Origin']=origin
        req=urllib.request.Request(self.base+path,data=json.dumps(payload).encode() if payload is not None else None,headers=headers)
        try:
            with urllib.request.urlopen(req,timeout=20) as response:
                return response.status,json.load(response)
        except urllib.error.HTTPError as exc:
            return exc.code,json.load(exc)

    def test_experiment_info_exposes_unavailable_dataset_and_metric_definitions(self):
        code,value=self.request('/api/experiment/info')
        self.assertEqual(code,200)
        self.assertFalse(value['dataset']['ready'])
        self.assertTrue({'em','cm','ex','ts','ves'}.issubset({m['id'] for m in value['metric_definitions']}))
        self.assertNotIn('api_key',json.dumps(value).lower())

    def test_experiment_api_preserves_origin_protection(self):
        self.assertEqual(self.request('/api/experiment/compare',{'sample_id':'x','model_ids':['q']},origin='https://foreign.example')[0],403)

    def test_invalid_option_and_missing_dataset_are_actionable(self):
        code,value=self.request('/api/experiment/compare',{'question':'test','db_id':'x','model_ids':['q'],'options':{'c5':True}})
        self.assertEqual(code,400)
        self.assertIn('error',value)

    def test_missing_samples_returns_empty_list_without_retaining_demo_samples(self):
        code,value=self.request('/api/experiment/samples?split=dev&limit=10')
        self.assertEqual(code,200)
        self.assertEqual(value['items'],[])
        self.assertEqual(value['total'],0)

    def test_export_cannot_read_arbitrary_files(self):
        self.assertEqual(self.request('/api/experiment/export?id=../secret&format=json')[0],400)

