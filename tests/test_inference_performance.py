import hashlib
import io
import json
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from text2sql_demo.experiment import training
from text2sql_demo.experiment.backends import BackendRegistry, OllamaBackend
from text2sql_demo.experiment.provenance import experiment_snapshot


class InferencePerformanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.weights = self.root / 'model.safetensors'
        self.weights.write_bytes(b'weights')
        self.gguf = self.root / 'model.gguf'
        self.gguf.write_bytes(b'GGUFtest')
        files = {'model.safetensors': training.file_sha256(self.weights)}
        data = {}
        for name in ('train.jsonl', 'dev.jsonl'):
            (self.root / name).write_bytes(b'{}\n')
            data[name] = training.file_sha256(self.root / name)
        self.manifest = {
            'status': 'trained', 'trained_steps': 1, 'trained_splits': ['train'],
            'validation_split': 'dev', 'dataset_fingerprint': 'fixture',
            'base_model': 'base', 'base_revision': 'fixed', 'artifact_kind': 'merged',
            'artifact_files': files, 'data_files': data,
            'gguf_export': {'path': 'model.gguf', 'sha256': training.file_sha256(self.gguf),
                            'quantization': 'Q4_K_M', 'source_artifact_files': files},
            'registration': {'model': 'ft:3b', 'digest': 'abc', 'artifact_files': files,
                             'import_artifact': {'path': 'model.gguf', 'sha256': training.file_sha256(self.gguf)}},
        }
        self.manifest['data_snapshot_sha256'] = training._snapshot_fingerprint(self.manifest)
        self.path = self.root / 'training_manifest.json'
        self.path.write_text(json.dumps(self.manifest), encoding='utf-8')
        self.registry = BackendRegistry({'models': [{
            'id': 'ft', 'model': 'ft:3b', 'provider': 'ollama', 'trained': True,
            'training_manifest': str(self.path),
        }]})

    def tags(self, *args, **kwargs):
        return io.BytesIO(b'{"models":[{"name":"ft:3b","digest":"abc"}]}')

    def test_repeated_model_listing_hashes_each_artifact_only_once(self):
        with patch('urllib.request.urlopen', side_effect=self.tags), \
                patch.object(training, 'file_sha256', wraps=training.file_sha256) as digest:
            self.assertTrue(self.registry.list_models()[0]['available'])
            self.assertTrue(self.registry.list_models()[0]['available'])
            self.assertEqual(digest.call_count, 4)

    def test_status_and_interactive_create_share_cache_but_benchmark_create_is_strict(self):
        with patch('urllib.request.urlopen', side_effect=self.tags), \
                patch.object(training, 'file_sha256', wraps=training.file_sha256) as digest:
            self.registry.list_models()
            status = training.training_status(self.path, hash_cache=self.registry.artifact_hash_cache)
            self.assertTrue(status['ready'])
            self.registry.create('ft', verify_artifacts=False)
            self.assertEqual(digest.call_count, 4)
            self.registry.create('ft')  # BenchmarkManager uses this strict default.
            self.assertEqual(digest.call_count, 8)

    def test_changed_weights_gguf_and_training_data_invalidate_cache(self):
        for name in ('model.safetensors', 'model.gguf', 'train.jsonl', 'dev.jsonl'):
            with self.subTest(name=name), patch('urllib.request.urlopen', side_effect=self.tags):
                target = self.root / name
                original = target.read_bytes()
                self.assertTrue(self.registry.list_models()[0]['available'])
                stamp = target.stat()
                # Same length; explicitly change mtime for filesystem-independent testing.
                target.write_bytes(original[:-1] + b'!')
                os.utime(target, ns=(stamp.st_atime_ns, stamp.st_mtime_ns + 1_000_000_000))
                self.assertFalse(self.registry.list_models()[0]['available'])
                target.write_bytes(original)

    def test_manifest_registration_and_missing_files_are_not_cached(self):
        with patch('urllib.request.urlopen', side_effect=self.tags):
            self.assertTrue(self.registry.list_models()[0]['available'])
            self.manifest['registration']['digest'] = 'different'
            self.path.write_text(json.dumps(self.manifest), encoding='utf-8')
            self.assertFalse(self.registry.list_models()[0]['available'])
            self.manifest['registration']['digest'] = 'abc'
            self.path.write_text(json.dumps(self.manifest), encoding='utf-8')
            self.assertTrue(self.registry.list_models()[0]['available'])
            self.weights.unlink()
            self.assertFalse(self.registry.list_models()[0]['available'])

    def test_concurrent_hash_requests_read_file_once(self):
        cache = training.ArtifactHashCache()
        with patch.object(training, 'file_sha256', wraps=training.file_sha256) as digest:
            with ThreadPoolExecutor(max_workers=4) as pool:
                values = list(pool.map(cache, [self.weights] * 8))
            self.assertEqual(len(set(values)), 1)
            self.assertEqual(digest.call_count, 1)

    def test_file_changed_during_hash_is_rejected(self):
        cache = training.ArtifactHashCache()
        def changing(path):
            self.weights.write_bytes(b'changed while reading')
            return hashlib.sha256(b'weights').hexdigest()
        with patch.object(training, 'file_sha256', side_effect=changing):
            with self.assertRaisesRegex(ValueError, 'changed'):
                cache(self.weights)

    def test_keep_alive_is_sent_and_recorded_with_explicit_zero_supported(self):
        for keep_alive in ('30m', 0):
            with self.subTest(keep_alive=keep_alive):
                backend = OllamaBackend({'provider': 'ollama', 'model': 'base', 'keep_alive': keep_alive})
                with patch.object(backend, '_request', return_value={'message': {'content': '{}'}}) as request:
                    backend.generate([{'role': 'user', 'content': 'SQL'}])
                self.assertEqual(request.call_args.args[1].get('keep_alive'), keep_alive)
                self.assertEqual(experiment_snapshot(backend, 'base')['inference'].get('keep_alive'), keep_alive)


if __name__ == '__main__':
    unittest.main()
