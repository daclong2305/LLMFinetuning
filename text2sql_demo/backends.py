import json
import os
import re
import urllib.error
import urllib.request

from .examples import EXAMPLES


def parse_generation(text):
    if not isinstance(text,str) or not text.strip():
        raise ValueError('Model không trả SQL. Thử lại hoặc chọn model khác.')
    text = text.strip()
    fence = re.fullmatch(r'```(?:sql|json)?\s*\n?(.*?)\n?```',text,re.S|re.I)
    if fence:
        text = fence.group(1).strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        if not re.match(r'^(SELECT|WITH)\b',text,re.I):
            raise ValueError('Output không có JSON SQL hoặc truy vấn SELECT/WITH hợp lệ.')
        value = {'sql':text}
    if not isinstance(value,dict) or not isinstance(value.get('sql'),str) or not value['sql'].strip():
        raise ValueError('Trường sql phải là chuỗi SQL không rỗng.')
    return {'sql':value['sql'].strip(), 'explanation':str(value.get('explanation',''))[:2000]}


class OllamaBackend:
    name = 'ollama'

    def __init__(self, model='qwen2.5-coder:3b', base_url='http://127.0.0.1:11434', timeout_s=180, num_gpu=None):
        self.model = model
        self.base_url = base_url.rstrip('/')
        self.timeout_s = timeout_s
        self.num_gpu = int(os.environ.get('TEXT2SQL_NUM_GPU','0')) if num_gpu is None else num_gpu

    def generate(self, messages):
        body = {'model':self.model,'messages':messages,'stream':False,'format':'json',
                'options':{'temperature':0,'seed':42,'num_ctx':4096,'num_predict':512,'num_gpu':self.num_gpu}}
        req = urllib.request.Request(self.base_url+'/api/chat',data=json.dumps(body).encode(),headers={'Content-Type':'application/json'})
        try:
            with urllib.request.urlopen(req,timeout=self.timeout_s) as response:
                result = json.load(response)
        except urllib.error.HTTPError as exc:
            try:
                detail = str(json.loads(exc.read(4096)).get('error',''))[:400]
            except (ValueError,TypeError,AttributeError):
                detail = ''
            raise RuntimeError(f'Ollama HTTP {exc.code}: {detail or "Kiểm tra model và dịch vụ đang chạy."}') from exc
        except (urllib.error.URLError,TimeoutError,OSError) as exc:
            raise RuntimeError('Không kết nối được Ollama hoặc quá thời gian. Chạy start-demo.ps1 và kiểm tra model.') from exc
        if not isinstance(result,dict) or not isinstance(result.get('message'),dict):
            raise ValueError('Ollama trả dữ liệu không có message hợp lệ.')
        return {'text':result['message'].get('content',''), 'input_tokens':result.get('prompt_eval_count'),
                'output_tokens':result.get('eval_count'), 'model':result.get('model',self.model)}


class OfflineBackend:
    name = 'offline'
    model = 'Bộ ví dụ cố định; không phải LLM'

    def generate(self, messages):
        target = messages[-1]['content']
        for example in EXAMPLES:
            if target==example['question']:
                return {'text':json.dumps({'sql':example['sql'],'explanation':'SQL tham chiếu của câu hỏi mẫu, không do LLM sinh.'}), 'input_tokens':None,'output_tokens':None}
        raise ValueError('Chế độ offline chỉ chạy các câu hỏi mẫu. Chọn Ollama để hỏi tự do.')
