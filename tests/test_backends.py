import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from text2sql_demo.backends import OllamaBackend


class BackendTests(unittest.TestCase):
    def setUp(self):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args): pass
            def do_POST(self):
                data=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                if data['model']=='broken':
                    self.send_response(500);self.end_headers();self.wfile.write(b'{"error":"driver incompatible"}');return
                # The test fixture only responds when the real adapter sends the required CPU config.
                if data.get('options',{}).get('num_gpu')!=0:
                    self.send_response(400);self.end_headers();return
                self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers()
                self.wfile.write(json.dumps({'message':{'content':'{"sql":"SELECT 73"}'},'prompt_eval_count':17,'eval_count':8,'model':data['model']}).encode())
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.base=f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join()

    def test_adapter_cpu_setting_and_token_usage(self):
        backend=OllamaBackend(base_url=self.base,num_gpu=0)
        result=backend.generate([{'role':'user','content':'A test question'}])
        self.assertEqual(result['text'],'{"sql":"SELECT 73"}')
        self.assertEqual(result['input_tokens'],17)
        self.assertEqual(result['output_tokens'],8)

    def test_provider_error_details_are_preserved(self):
        backend=OllamaBackend(model='broken',base_url=self.base)
        with self.assertRaisesRegex(RuntimeError,'driver incompatible'):
            backend.generate([{'role':'user','content':'A question'}])
