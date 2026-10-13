import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from text2sql_demo.experiment import backends
from text2sql_demo.experiment.provenance import experiment_snapshot


class BedrockTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            'AWS_ACCESS_KEY_ID': 'test-access', 'AWS_SECRET_ACCESS_KEY': 'test-secret',
            'AWS_SESSION_TOKEN': 'test-session', 'AWS_DEFAULT_REGION': 'us-east-1',
            'AWS_REGION': '', 'AWS_PROFILE': '', 'AWS_BEARER_TOKEN_BEDROCK': '',
        })
        self.env.start()
        os.environ.pop('AWS_PROFILE', None)
        self.addCleanup(self.env.stop)
        self.config = {'id': 'claude_haiku', 'provider': 'bedrock',
                       'model': 'us.anthropic.claude-haiku-4-5-20251001-v1:0',
                       'max_output_tokens': 2048, 'temperature': 0, 'timeout_s': 60,
                       'pricing': {'input': 1.1, 'output': 5.5, 'cached_input': .11, 'cache_write': 1.375}}

    def backend(self):
        registry = backends.BackendRegistry({'env_file': 'missing-env-for-test', 'models': [self.config]})
        return registry.create('claude_haiku')

    def response(self, stop='end_turn'):
        return {'output': {'message': {'role': 'assistant', 'content': [{'text': '{"sql":"SELECT 1"}'}]}},
                'stopReason': stop, 'usage': {'inputTokens': 100, 'outputTokens': 20, 'totalTokens': 120},
                'metrics': {'latencyMs': 10}, 'ResponseMetadata': {'RequestId': 'bedrock-test'}}

    def test_converse_payload_system_and_usage(self):
        from botocore.stub import Stubber
        backend = self.backend()
        client = backend._client()
        expected = {'modelId': self.config['model'],
                    'system': [{'text': 'Return SQL JSON.'}],
                    'messages': [{'role': 'user', 'content': [{'text': 'Tên khách hàng?'}]}],
                    'inferenceConfig': {'maxTokens': 2048, 'temperature': 0}}
        with Stubber(client) as stub:
            stub.add_response('converse', self.response(), expected)
            with patch.object(backend, '_client', return_value=client):
                result = backend.generate([{'role': 'system', 'content': 'Return SQL JSON.'},
                                           {'role': 'user', 'content': 'Tên khách hàng?'}])
            stub.assert_no_pending_responses()
        self.assertEqual(result['text'], '{"sql":"SELECT 1"}')
        self.assertEqual(result['input_tokens'], 100)
        self.assertEqual(result['output_tokens'], 20)
        self.assertEqual(result['cached_input_tokens'], 0)
        self.assertAlmostEqual(result['cost_usd'], .00022)
        self.assertEqual(result['response_id'], 'bedrock-test')
        self.assertEqual(client.meta.region_name, 'us-east-1')
        self.assertEqual(client.meta.config.retries['total_max_attempts'], 1)

    def test_cache_usage_counts_total_input_and_prices_writes_separately(self):
        raw = self.response()
        raw['usage'].update(cacheReadInputTokens=40, cacheWriteInputTokens=20)
        result = backends.normalize_usage(raw, self.config)
        self.assertEqual(result['input_tokens'], 160)
        self.assertEqual(result['cached_input_tokens'], 40)
        self.assertAlmostEqual(result['cost_usd'], .0002519)

    def test_unknown_usage_and_malformed_cache_stay_unavailable(self):
        for raw in ({}, {'usage': {'inputTokens': 100}},
                    {'usage': {'inputTokens': 100, 'outputTokens': 20, 'cacheReadInputTokens': True}}):
            with self.subTest(raw=raw):
                result = backends.normalize_usage(raw, self.config)
                self.assertIsNone(result['cost_usd'])

    def test_incomplete_generation_keeps_usage_and_safe_error(self):
        from botocore.stub import Stubber
        backend = self.backend()
        client = backend._client()
        with Stubber(client) as stub:
            stub.add_response('converse', self.response('max_tokens'))
            with patch.object(backend, '_client', return_value=client):
                with self.assertRaises(backends.BackendError) as caught:
                    backend.generate([{'role': 'user', 'content': 'SQL'}])
        self.assertEqual(caught.exception.code, 'response_max_tokens')
        self.assertEqual(caught.exception.usage['output_tokens'], 20)

    def test_access_denied_does_not_echo_provider_message_or_credentials(self):
        from botocore.stub import Stubber
        backend = self.backend()
        client = backend._client()
        with Stubber(client) as stub:
            stub.add_client_error('converse', 'AccessDeniedException',
                                  'test-secret test-session private-account-details', http_status_code=403)
            with patch.object(backend, '_client', return_value=client):
                with self.assertRaises(backends.BackendError) as caught:
                    backend.generate([{'role': 'user', 'content': 'SQL'}])
        self.assertIn('AccessDeniedException', str(caught.exception))
        self.assertNotIn('test-secret', str(caught.exception))
        self.assertNotIn('private-account-details', str(caught.exception))
        self.assertIsNone(caught.exception.usage['cost_usd'])

    def test_missing_credentials_disable_model_without_network_calls(self):
        with patch.dict(os.environ, {'AWS_ACCESS_KEY_ID': '', 'AWS_SECRET_ACCESS_KEY': '',
                                    'AWS_SESSION_TOKEN': '', 'AWS_PROFILE': '', 'AWS_BEARER_TOKEN_BEDROCK': ''}):
            registry = backends.BackendRegistry({'env_file': 'missing-env-for-test', 'models': [self.config]})
            self.assertFalse(registry.list_models()[0]['available'])
            with self.assertRaises(backends.BackendError):
                registry.create('claude_haiku')

    def test_env_fallback_loads_aws_allowlist_and_preserves_process_values(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'env').write_text('AWS_ACCESS_KEY_ID=local-access\nAWS_SECRET_ACCESS_KEY="local-secret"\n'
                                      'AWS_SESSION_TOKEN=local-session\nAWS_DEFAULT_REGION=us-west-2\n'
                                      'UNRELATED=$(bad)\n', encoding='utf-8')
            with patch.dict(os.environ, {}, clear=True):
                os.environ['AWS_DEFAULT_REGION'] = 'us-east-1'
                backends.load_local_env(root / '.env')
                self.assertEqual(os.environ['AWS_ACCESS_KEY_ID'], 'local-access')
                self.assertEqual(os.environ['AWS_SECRET_ACCESS_KEY'], 'local-secret')
                self.assertEqual(os.environ['AWS_SESSION_TOKEN'], 'local-session')
                self.assertEqual(os.environ['AWS_DEFAULT_REGION'], 'us-east-1')
                self.assertNotIn('UNRELATED', os.environ)

    def test_snapshot_records_region_and_never_credentials(self):
        backend = self.backend()
        snapshot = experiment_snapshot(backend, 'claude_haiku')
        self.assertEqual(snapshot['inference']['region'], 'us-east-1')
        for secret in ('test-access', 'test-secret', 'test-session'):
            self.assertNotIn(secret, json.dumps(snapshot))


if __name__ == '__main__':
    unittest.main()
