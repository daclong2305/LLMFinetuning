import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from text2sql_demo.experiment.backends import BackendError, BackendRegistry, normalize_usage


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.requests = []
        records = self.requests
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                self.send_response(200); self.end_headers()
                self.wfile.write(b'{"models":[{"name":"base:3b","digest":"abc","details":{"quantization_level":"Q4_K_M"}}]}')
            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                records.append((self.path, payload, self.headers.get('Authorization')))
                if self.path == '/api/chat':
                    data = {'message': {'content': '{"sql":"SELECT 1"}'}, 'prompt_eval_count': 20, 'eval_count': 5}
                else:
                    data = {'id': 'resp_1', 'model': payload['model'], 'status': 'completed',
                            'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': '{"sql":"SELECT 2"}'}]}],
                            'usage': {'input_tokens': 100, 'output_tokens': 20, 'input_tokens_details': {'cached_tokens': 40}}}
                    if payload['input'][0]['content'] == 'fail':
                        data.update(status='failed', error={'message': 'secret-token failure'})
                self.send_response(200); self.end_headers(); self.wfile.write(json.dumps(data).encode())
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}'
        self.config = {'models': [
            {'id': 'local', 'label': 'Base', 'provider': 'ollama', 'model': 'base:3b', 'base_url': self.url, 'options': {'num_gpu': 0}},
            {'id': 'gpt', 'provider': 'openai', 'model': 'gpt-4.1-mini-2025-04-14', 'base_url': self.url, 'pricing': {'input': .4, 'cached_input': .1, 'output': 1.6}}]}

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()

    def test_responses_payload_and_cached_usage_price(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'secret-token'}):
            backend = BackendRegistry(self.config).create('gpt')
            result = backend.generate([{'role': 'user', 'content': 'SQL please'}])
        self.assertEqual(self.requests[0][0], '/responses')
        payload = self.requests[0][1]
        self.assertEqual(payload['model'], 'gpt-4.1-mini-2025-04-14')
        self.assertEqual(payload['text']['format']['type'], 'json_object')
        self.assertFalse(payload['store'])
        self.assertEqual(result['text'], '{"sql":"SELECT 2"}')
        self.assertEqual(result['cached_input_tokens'], 40)
        self.assertAlmostEqual(result['cost_usd'], .000060)
        self.assertEqual(result['response_id'], 'resp_1')

    def test_failed_response_preserves_usage_and_redacts_secret(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'secret-token'}):
            backend = BackendRegistry(self.config).create('gpt')
            with self.assertRaises(BackendError) as caught:
                backend.generate([{'role': 'user', 'content': 'fail'}])
        self.assertEqual(caught.exception.usage['input_tokens'], 100)
        self.assertAlmostEqual(caught.exception.usage['cost_usd'], .000060)
        self.assertNotIn('secret-token', str(caught.exception))

    def test_ollama_options_and_local_api_cost(self):
        backend = BackendRegistry(self.config).create('local')
        result = backend.generate([{'role': 'user', 'content': 'SQL'}])
        self.assertEqual(self.requests[0][1]['options']['num_gpu'], 0)
        self.assertEqual(result['input_tokens'], 20)
        self.assertEqual(result['cost_usd'], 0)
        self.assertEqual(result['cached_input_tokens'], 0)

    def test_missing_key_unavailable_and_not_in_model_metadata(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': ''}):
            registry = BackendRegistry(self.config)
            item = registry.list_models()[1]
            self.assertFalse(item['available'])
            with self.assertRaises(BackendError): registry.create('gpt')
        self.assertNotIn('api_key', json.dumps(item))

    def test_missing_finetune_manifest_cannot_use_base_weights(self):
        config = {'models': [{'id': 'fake_ft', 'provider': 'ollama', 'model': 'base:3b', 'trained': True,
                              'training_manifest': 'missing-training-manifest.json', 'base_url': self.url}]}
        registry = BackendRegistry(config)
        self.assertFalse(registry.list_models()[0]['available'])
        with self.assertRaises(BackendError): registry.create('fake_ft')

    def test_dotenv_never_executes_expansion_or_overrides_environment(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / '.env'
            path.write_text('OPENAI_API_KEY="local-key"\nUNRELATED=$(bad)\n', encoding='utf-8')
            with patch.dict(os.environ, {'OPENAI_API_KEY': 'existing-key'}):
                registry = BackendRegistry({**self.config, 'env_file': str(path)})
                self.assertTrue(registry.list_models()[1]['available'])
                self.assertEqual(os.environ['OPENAI_API_KEY'], 'existing-key')

    def test_unknown_or_malformed_usage_is_not_reported_as_zero(self):
        cfg = self.config['models'][1]
        for raw in ({}, {'usage': [1]}, {'usage': {'input_tokens': 10, 'output_tokens': 2}},
                    {'usage': {'input_tokens': 10, 'output_tokens': 2, 'input_tokens_details': [1]}}):
            result = normalize_usage(raw, cfg)
            self.assertIsNone(result['cost_usd'])
            self.assertIsNone(result['cached_input_tokens'])

    def test_top_level_inference_settings_reach_ollama(self):
        self.config['models'][0].update(num_ctx=32768, num_predict=3000, seed=17, temperature=.2, num_gpu=1)
        BackendRegistry(self.config).create('local').generate([{'role': 'user', 'content': 'SQL'}])
        settings = self.requests[0][1]['options']
        self.assertEqual(settings['num_ctx'], 32768)
        self.assertEqual(settings['num_predict'], 3000)
        self.assertEqual(settings['seed'], 17)
        self.assertEqual(settings['temperature'], .2)
        # Explicit nested options override the corresponding top-level setting.
        self.assertEqual(settings['num_gpu'], 0)

    def test_custom_provider_can_register_without_pipeline_changes(self):
        class Custom:
            def __init__(self, config): self.model = config['model']
            def generate(self, messages): return {'text': messages[0]['content'], 'model': self.model}
        registry = BackendRegistry({'models': [{'id': 'new', 'provider': 'custom', 'model': 'separate'}]})
        registry.register_provider('custom', Custom, lambda config: (True, None))
        self.assertTrue(registry.list_models()[0]['available'])
        self.assertEqual(registry.create('new').generate([{'content': 'OK'}])['text'], 'OK')

    def test_installed_ollama_identity_is_available_for_run_snapshots(self):
        registry = BackendRegistry(self.config)
        item = registry.list_models()[0]
        self.assertEqual(item['model_digest'], 'abc')
        self.assertEqual(item['quantization'], 'Q4_K_M')
        self.assertEqual(registry.create('local').model_digest, 'abc')


if __name__ == '__main__': unittest.main()
