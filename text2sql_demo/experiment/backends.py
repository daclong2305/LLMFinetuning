"""Configurable inference adapters; core runtime has no third-party dependencies."""
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

from .training import validate_training_manifest


class BackendError(RuntimeError):
    def __init__(self, message, usage=None, code='provider_error'):
        super().__init__(message)
        self.usage = usage or {}
        self.code = code


def load_local_env(path):
    """Read only API-key assignments, without interpolation or executing shell syntax."""
    path = Path(path)
    if not path.is_file(): return
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        match = re.fullmatch(r'\s*(?:export\s+)?([A-Z][A-Z0-9_]*API_KEY)\s*=\s*(.*?)\s*', line)
        if not match: continue
        name, value = match.groups()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        else:
            value = value.split(' #', 1)[0].strip()
        if value and name not in os.environ: os.environ[name] = value


def _count(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def normalize_usage(result, config):
    provider = config['provider']
    usage = result.get('usage') if isinstance(result.get('usage'), dict) else {}
    if provider == 'ollama':
        incoming, outgoing, cached = _count(result.get('prompt_eval_count')), _count(result.get('eval_count')), 0
        cost = 0.0
    else:
        incoming, outgoing = _count(usage.get('input_tokens')), _count(usage.get('output_tokens'))
        details = usage.get('input_tokens_details') if isinstance(usage.get('input_tokens_details'), dict) else {}
        cached = _count(details.get('cached_tokens'))
        rates = config.get('pricing', config.get('rates', {}))
        cost = None
        if incoming is not None and outgoing is not None and cached is not None and 0 <= cached <= incoming:
            if all(isinstance(rates.get(key), (int, float)) and rates[key] >= 0 for key in ('input', 'cached_input', 'output')):
                cost = ((incoming - cached) * rates['input'] + cached * rates['cached_input'] + outgoing * rates['output']) / 1_000_000
    return {'text': '', 'input_tokens': incoming, 'output_tokens': outgoing, 'cached_input_tokens': cached,
            'cost_usd': cost, 'model': result.get('model', config['model']), 'response_id': result.get('id')}


class _HTTPBackend:
    def __init__(self, config):
        self.config = dict(config)
        self.model = config['model']
        self.name = config['provider']
        self.timeout_s = config.get('timeout_s', 180)

    def _request(self, url, payload, headers=None):
        request = urllib.request.Request(url, json.dumps(payload, ensure_ascii=False).encode('utf-8'),
                                         {'Content-Type': 'application/json', **(headers or {})})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                result = json.load(response)
        except urllib.error.HTTPError as exc:
            try:
                result = json.loads(exc.read(65536))
                if not isinstance(result, dict): result = {}
            except (ValueError, OSError): result = {}
            raise BackendError(f'{self.name} HTTP {exc.code}; request failed.', normalize_usage(result, self.config), f'http_{exc.code}') from None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            raise BackendError(f'{self.name}: connection, timeout or invalid response.', normalize_usage({}, self.config), 'transport_error') from None
        if not isinstance(result, dict):
            raise BackendError(f'{self.name}: invalid response.', normalize_usage({}, self.config), 'invalid_response')
        return result


class OllamaBackend(_HTTPBackend):
    def generate(self, messages):
        options = {'temperature': 0, 'seed': 42, 'num_ctx': 16384, 'num_predict': 2048,
                   'num_gpu': int(os.environ.get('TEXT2SQL_NUM_GPU', '0'))}
        options.update({name: self.config[name] for name in options if name in self.config})
        options.update(self.config.get('options', {}))
        body = {'model': self.model, 'messages': messages, 'stream': False, 'format': 'json', 'options': options}
        result = self._request(self.config.get('base_url', 'http://127.0.0.1:11434').rstrip('/') + '/api/chat', body)
        normalized = normalize_usage(result, self.config)
        message = result.get('message') or {}
        if result.get('error') or not isinstance(message.get('content'), str):
            raise BackendError('Ollama: generation failed.', normalized)
        normalized['text'] = message['content']
        return normalized


class OpenAIBackend(_HTTPBackend):
    def generate(self, messages):
        key = os.environ.get(self.config.get('api_key_env', 'OPENAI_API_KEY'), '').strip()
        if not key: raise BackendError('OpenAI API credential is not configured.', normalize_usage({}, self.config), 'unavailable')
        body = {'model': self.model, 'input': messages, 'store': False,
                'text': {'format': {'type': 'json_object'}}, 'temperature': self.config.get('temperature', 0),
                'max_output_tokens': self.config.get('max_output_tokens', 2048)}
        result = self._request(self.config.get('base_url', 'https://api.openai.com/v1').rstrip('/') + '/responses', body,
                               {'Authorization': 'Bearer ' + key})
        normalized = normalize_usage(result, self.config)
        if result.get('status') != 'completed' or result.get('error'):
            # Provider messages can echo user inputs or credentials; use only a safe status.
            status = result.get('status') if result.get('status') in ('failed', 'incomplete', 'cancelled', 'queued', 'in_progress') else 'invalid'
            raise BackendError(f'OpenAI response {status}.', normalized, 'response_' + status)
        parts = [part['text'] for item in result.get('output', []) if item.get('type') == 'message'
                 for part in item.get('content', []) if part.get('type') == 'output_text' and isinstance(part.get('text'), str)]
        if not parts: raise BackendError('OpenAI response contains no text.', normalized, 'invalid_response')
        normalized['text'] = ''.join(parts)
        return normalized


class BackendRegistry:
    def __init__(self, config):
        self.config = config
        load_local_env(config.get('env_file', '.env'))
        self.models = {item['id']: dict(item) for item in config.get('models', [])}
        self.providers = {'ollama': (OllamaBackend, None), 'openai': (OpenAIBackend, None)}
        if len(self.models) != len(config.get('models', [])): raise ValueError('Duplicate model IDs.')

    def register_provider(self, name, factory, availability):
        """An extension supplies a factory and a credential-safe (ready, reason) check."""
        if not isinstance(name, str) or not name or not callable(factory) or not callable(availability):
            raise ValueError('Provider name, factory and availability callable are required.')
        self.providers[name] = (factory, availability)

    def _availability(self, item, tags_cache):
        if item.get('trained'):
            try:
                manifest = validate_training_manifest(item.get('training_manifest', ''), model=item['model'])
            except (ValueError, OSError, TypeError): return False, 'Valid trained checkpoint and registered provenance are required.'
        else: manifest = None
        registration = self.providers.get(item['provider'])
        if registration and registration[1] is not None:
            return registration[1](dict(item))
        if item['provider'] == 'openai':
            ready = bool(os.environ.get(item.get('api_key_env', 'OPENAI_API_KEY'), '').strip())
            return ready, None if ready else 'OpenAI API credential is not configured.'
        if item['provider'] != 'ollama': return False, 'Unsupported provider.'
        url = item.get('base_url', 'http://127.0.0.1:11434').rstrip('/')
        if url not in tags_cache:
            try:
                with urllib.request.urlopen(url + '/api/tags', timeout=3) as response:
                    tags_cache[url] = json.load(response).get('models', [])
            except (OSError, ValueError, AttributeError): tags_cache[url] = None
        tags = tags_cache[url]
        if tags is None: return False, 'Ollama service is unavailable.'
        model_name = item['model'] if ':' in item['model'] else item['model'] + ':latest'
        matched = next((tag for tag in tags if tag.get('name') in (item['model'], model_name)), None)
        if not matched: return False, 'Configured Ollama model is not installed.'
        if manifest and matched.get('digest') != manifest['registration']['digest']:
            return False, 'Ollama model digest differs from the registered training artifact.'
        return True, None

    def list_models(self):
        cache, result = {}, []
        for item in self.models.values():
            ready, reason = self._availability(item, cache)
            identity = self._model_identity(item, cache)
            result.append({'id': item['id'], 'label': item.get('label', item['id']), 'provider': item['provider'],
                           'model': item['model'], 'trained': bool(item.get('trained')), 'available': ready,
                           'state': 'ready' if ready else 'unavailable', 'reason': reason, 'unavailable_reason': reason, **identity,
                           'cost_basis': 'local API only; hardware/training excluded' if item['provider'] == 'ollama' else 'configured USD API pricing'})
        return result

    def _model_identity(self, item, cache):
        url = item.get('base_url', 'http://127.0.0.1:11434').rstrip('/')
        canonical = item['model'] if ':' in item['model'] else item['model'] + ':latest'
        tag = next((tag for tag in cache.get(url) or [] if tag.get('name') in (item['model'], canonical)), {})
        details = tag.get('details') if isinstance(tag.get('details'), dict) else {}
        return {'model_digest': tag.get('digest'), 'quantization': details.get('quantization_level')}

    def create(self, model_id):
        if model_id not in self.models: raise BackendError('Unknown model ID.', code='unknown_model')
        item = self.models[model_id]
        cache = {}
        ready, reason = self._availability(item, cache)
        if not ready: raise BackendError(reason, normalize_usage({}, item), 'unavailable')
        backend = self.providers[item['provider']][0](item)
        identity = self._model_identity(item, cache)
        backend.model_digest = identity['model_digest']
        backend.quantization = identity['quantization']
        return backend
