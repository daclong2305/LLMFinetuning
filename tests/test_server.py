import json
import io
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import Mock

from text2sql_demo.database import create_demo_database
from text2sql_demo.server import make_server


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.db = Path(cls.temp.name) / 'demo.sqlite'
        create_demo_database(cls.db)
        cls.server = make_server(cls.db, port=0)
        cls.thread = threading.Thread(target=cls.server.serve_forever,daemon=True)
        cls.thread.start()
        cls.base = f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.temp.cleanup()

    def request(self, route, payload=None, origin=None):
        headers = {'Content-Type':'application/json'}
        if origin:
            headers['Origin'] = origin
        req = urllib.request.Request(self.base+route, data=json.dumps(payload).encode() if payload is not None else None,headers=headers)
        try:
            with urllib.request.urlopen(req,timeout=10) as r:
                return r.status,json.load(r)
        except urllib.error.HTTPError as e:
            return e.code,json.load(e)

    def test_info_exposes_synthetic_schema_and_counts(self):
        status,data = self.request('/api/info')
        self.assertEqual(status,200)
        self.assertEqual(data['counts']['customers'],32)
        self.assertEqual(data['counts']['orders'],144)
        self.assertEqual(len(data['schema']),4)

    def test_offline_http_query_executes_and_labels_backend(self):
        status,data = self.request('/api/query', {'question':'Có bao nhiêu đơn hàng theo từng trạng thái?', 'backend':'offline'})
        self.assertEqual(status,200)
        self.assertEqual(data['status'],'ok')
        self.assertEqual(data['backend'],'offline')
        self.assertEqual(sum(row[1] for row in data['execution']['rows']),144)

    def test_validation_rejects_boolean_strings_and_empty_questions(self):
        for payload in ({'question':''},{'question':7},{'question':'test','few_shot':'false'}, {'question':'test','backend':'other'}):
            with self.subTest(payload=payload):
                self.assertEqual(self.request('/api/query',payload)[0],400)

    def test_foreign_origin_is_denied(self):
        self.assertEqual(self.request('/api/sql',{'sql':'SELECT 1'},origin='https://example.com')[0],403)

    def test_rejected_post_consumes_bounded_body_without_parsing(self):
        for origin,content_type,status in [('https://foreign.example','application/json',403),(self.base,'text/plain',415)]:
            with self.subTest(status=status):
                handler=object.__new__(self.server.RequestHandlerClass)
                body=b'not valid JSON'
                handler.server=self.server
                handler.headers={'Host':self.base.removeprefix('http://'),'Origin':origin,'Content-Type':content_type,'Content-Length':str(len(body))}
                handler.rfile=io.BytesIO(body)
                handler.connection=Mock()
                handler.connection.gettimeout.return_value=None
                handler.send=Mock()
                handler.do_POST()
                self.assertEqual(handler.send.call_args.args[1],status)
                self.assertEqual(handler.rfile.tell(),len(body))

    def test_sql_endpoint_denies_write_without_mutating_database(self):
        status,data = self.request('/api/sql',{'sql':'DELETE FROM customers'})
        self.assertEqual(status,200)
        self.assertEqual(data['status'],'error')
        self.assertEqual(self.request('/api/info')[1]['counts']['customers'],32)


if __name__=='__main__':
    unittest.main()
