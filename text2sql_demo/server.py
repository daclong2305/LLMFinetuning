"""Loopback-only demo web server. No third-party Python dependencies."""
import argparse
import json
import os
import threading
import urllib.request
from urllib.parse import urlsplit,parse_qs
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .backends import OfflineBackend, OllamaBackend
from .database import create_demo_database, inspect_schema, execute_readonly
from .examples import EXAMPLES
from .pipeline import run_question

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / 'demo' / 'static'


def make_server(db_path, port=8765, model=None, ollama_url=None, experiment_config=None):
    db_path = Path(db_path)
    model = model or os.environ.get('TEXT2SQL_MODEL','qwen2.5-coder:3b')
    ollama_url = ollama_url or os.environ.get('TEXT2SQL_OLLAMA_URL','http://127.0.0.1:11434')
    inference_lock = threading.Lock()
    experiment_ref = []
    experiment_init_lock = threading.Lock()

    def experiment():
        with experiment_init_lock:
            if not experiment_ref:
                from .experiment.service import ExperimentService
                experiment_ref.append(ExperimentService(ROOT,experiment_config,inference_lock))
        return experiment_ref[0]

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def send(self, data, status=200, content_type='application/json; charset=utf-8', filename=None):
            body = json.dumps(data,ensure_ascii=False).encode() if isinstance(data,(dict,list)) else data
            self.send_response(status)
            self.send_header('Content-Type',content_type)
            self.send_header('Content-Length',str(len(body)))
            if filename:
                self.send_header('Content-Disposition','attachment; filename="'+filename+'"')
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError,ConnectionResetError):
                pass

        def local_request(self):
            allowed_hosts = {f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'}
            allowed_origins = {'http://'+host for host in allowed_hosts}
            return self.headers.get('Host') in allowed_hosts and self.headers.get('Origin',next(iter(allowed_origins))) in allowed_origins

        def do_GET(self):
            if not self.local_request():
                return self.send({'error':'Chỉ hỗ trợ truy cập local.'},403)
            route = self.path.split('?')[0]
            if route.startswith('/api/experiment/'):
                try:
                    params={key:values[0] for key,values in parse_qs(urlsplit(self.path).query).items()}
                    data,status,mime,filename=experiment().get(route,params)
                    return self.send(data,status,mime,filename)
                except (ValueError,TypeError,KeyError,FileNotFoundError) as exc:
                    return self.send({'error':str(exc)},400)
                except Exception:
                    import traceback
                    traceback.print_exc()
                    return self.send({'error':'Lỗi hệ thống thực nghiệm; xem log server.'},500)
            if route=='/api/info':
                schema = inspect_schema(db_path)
                counts = {name:execute_readonly(db_path,f'SELECT COUNT(*) FROM "{name}"')['rows'][0][0] for name in schema}
                ollama = {'available':False,'models':[], 'model':model, 'compute':'CPU' if int(os.environ.get('TEXT2SQL_NUM_GPU','0'))==0 else 'GPU/auto'}
                try:
                    with urllib.request.urlopen(ollama_url+'/api/tags',timeout=2) as response:
                        data = json.load(response)
                    ollama['models'] = [m['name'] for m in data.get('models',[])]
                    ollama['available'] = model in ollama['models']
                except (OSError,ValueError,KeyError):
                    pass
                return self.send({'schema':schema,'counts':counts,'examples':[e['question'] for e in EXAMPLES], 'ollama':ollama,'dataset':'Dữ liệu bán hàng giả lập, seed 42; đơn vị VND.'})
            files = {'/':('experiment.html','text/html; charset=utf-8'), '/legacy':('index.html','text/html; charset=utf-8'),'/legacy/':('index.html','text/html; charset=utf-8'),'/experiment.js':('experiment.js','text/javascript; charset=utf-8'),'/experiment.css':('experiment.css','text/css; charset=utf-8'),'/app.js':('app.js','text/javascript; charset=utf-8'), '/style.css':('style.css','text/css; charset=utf-8')}
            if route in files:
                filename,mime = files[route]
                return self.send((STATIC/filename).read_bytes(),content_type=mime)
            return self.send({'error':'Không tìm thấy.'},404)

        def discard_rejected_body(self):
            # Closing with unread POST bytes can reset the socket on Windows.
            # Never wait indefinitely or consume an unbounded rejected upload.
            try:
                size=int(self.headers.get('Content-Length','0'))
            except ValueError:
                return
            if not 0<size<=32768:
                return
            previous_timeout=self.connection.gettimeout()
            try:
                self.connection.settimeout(1)
                self.rfile.read(size)
            except OSError:
                pass
            finally:
                self.connection.settimeout(previous_timeout)

        def do_POST(self):
            if not self.local_request():
                self.discard_rejected_body()
                return self.send({'error':'Nguồn truy cập không được phép.'},403)
            if self.headers.get('Content-Type','').split(';')[0]!='application/json':
                self.discard_rejected_body()
                return self.send({'error':'Yêu cầu application/json.'},415)
            try:
                size = int(self.headers.get('Content-Length','0'))
                if not 0<size<=32768:
                    raise ValueError('Body rỗng hoặc quá lớn.')
                payload = json.loads(self.rfile.read(size))
                if not isinstance(payload,dict):
                    raise ValueError('Body phải là object JSON.')
                if self.path.startswith('/api/experiment/'):
                    data,status=experiment().post(self.path,payload)
                    return self.send(data,status)
                if self.path=='/api/sql':
                    sql = payload.get('sql')
                    if not isinstance(sql,str) or not sql.strip() or len(sql)>20000:
                        raise ValueError('SQL rỗng hoặc quá dài.')
                    return self.send(execute_readonly(db_path,sql))
                if self.path!='/api/query':
                    return self.send({'error':'Không tìm thấy.'},404)
                question = payload.get('question')
                if not isinstance(question,str) or not question.strip() or len(question)>2000:
                    raise ValueError('Câu hỏi phải dài từ 1 đến 2.000 ký tự.')
                mode = payload.get('backend','ollama')
                if mode not in ('ollama','offline'):
                    raise ValueError('Backend không hợp lệ.')
                options = {key:payload.get(key,default) for key,default in [('few_shot',True),('linking',False),('repair',True)]}
                if any(type(v) is not bool for v in options.values()):
                    raise ValueError('Các tùy chọn phải là boolean.')
            except (ValueError,TypeError,KeyError,UnicodeDecodeError,RuntimeError) as exc:
                return self.send({'error':str(exc)},400)
            if not inference_lock.acquire(blocking=False):
                return self.send({'error':'Model đang xử lý một câu hỏi. Đợi hoàn tất rồi thử lại.'},409)
            try:
                backend = OllamaBackend(model,ollama_url) if mode=='ollama' else OfflineBackend()
                result = run_question(db_path,question.strip(),backend,**options)
                self.send(result)
            except Exception:
                self.send({'error':'Có lỗi nội bộ. Xem log server và thử lại.'},500)
                import traceback
                traceback.print_exc()
            finally:
                inference_lock.release()

    return ThreadingHTTPServer(('127.0.0.1',port),Handler)


def main():
    parser = argparse.ArgumentParser(description='Bản minh họa LLM-based Text-to-SQL')
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--db',type=Path,default=ROOT/'data'/'demo.sqlite')
    args = parser.parse_args()
    create_demo_database(args.db)
    server = make_server(args.db,args.port)
    print(f'Text-to-SQL demo: http://127.0.0.1:{server.server_port}',flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__=='__main__':
    main()
