import hashlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from text2sql_demo.experiment import training


def merged_fixture(root):
    (root / 'merged').mkdir()
    weights = root / 'merged/model.safetensors'
    weights.write_bytes(b'trained')
    manifest = {'status': 'trained', 'trained_steps': 741, 'trained_splits': ['train'], 'validation_split': 'dev',
                'dataset_fingerprint': 'fixed', 'base_model': 'Qwen/base', 'base_revision': 'revision',
                'artifact_kind': 'merged', 'artifact_files': {'merged/model.safetensors': hashlib.sha256(b'trained').hexdigest()}}
    (root / 'training_manifest.json').write_text(json.dumps(manifest))
    return manifest


def created_model_fixture(store, gguf_hash):
    payload = json.dumps({'layers': [{'mediaType': 'application/vnd.ollama.image.model',
                                    'digest': 'sha256:' + gguf_hash}]}).encode()
    path = store / 'manifests/registry.ollama.ai/library/custom/3b'
    path.parent.mkdir(parents=True)
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


class GGUFTrainingTests(unittest.TestCase):
    def test_export_converts_verified_merged_weights_and_records_gguf_hash(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); original = merged_fixture(root)
            converter = root / 'convert.py'; converter.write_text('# converter')
            quantizer = root / 'quantize.exe'; quantizer.write_bytes(b'quantizer')
            calls = []
            def execute(command, **kwargs):
                calls.append(command)
                if '--outfile' in command:
                    self.assertEqual(command[command.index('--outtype') + 1], 'f16')
                    self.assertIn('--use-temp-file', command)
                    Path(command[command.index('--outfile') + 1]).write_bytes(b'GGUFf16')
                else:
                    self.assertIn('--max-buffer-size', command)
                    self.assertEqual(command[-2], 'Q4_K_M')
                    Path(command[-3]).write_bytes(b'GGUFq4')
            with patch('text2sql_demo.experiment.training.subprocess.run', side_effect=execute):
                result = training.export_gguf(root, converter, quantizer)
            saved = json.loads((root / 'training_manifest.json').read_text())
            self.assertEqual(saved['artifact_files'], original['artifact_files'])
            self.assertEqual(result['source_artifact_files'], original['artifact_files'])
            self.assertEqual(result['quantization'], 'Q4_K_M')
            self.assertEqual(result['sha256'], hashlib.sha256(b'GGUFq4').hexdigest())
            self.assertEqual(len(calls), 2)
            self.assertTrue((root / result['path']).is_file())
            training.validate_training_manifest(root / 'training_manifest.json')

    def test_failed_export_does_not_change_training_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); merged_fixture(root)
            converter = root / 'convert.py'; converter.write_text('# converter')
            quantizer = root / 'quantize.exe'; quantizer.write_bytes(b'quantizer')
            path = root / 'training_manifest.json'; before = path.read_bytes()
            with patch('text2sql_demo.experiment.training.subprocess.run', side_effect=subprocess.CalledProcessError(1, ['convert'])):
                with self.assertRaisesRegex(RuntimeError, 'GGUF export failed'):
                    training.export_gguf(root, converter, quantizer)
            self.assertEqual(path.read_bytes(), before)

    def test_gguf_import_bypasses_safetensors_quantization_and_tracks_exact_export(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); manifest = merged_fixture(root)
            gguf = root / 'trained.gguf'; gguf.write_bytes(b'GGUFq4')
            manifest['gguf_export'] = {'path': 'trained.gguf', 'sha256': hashlib.sha256(b'GGUFq4').hexdigest(),
                                       'quantization': 'Q4_K_M', 'source_artifact_files': manifest['artifact_files']}
            (root / 'training_manifest.json').write_text(json.dumps(manifest))
            store = root / 'store'
            digest = created_model_fixture(store, manifest['gguf_export']['sha256'])
            responses = [io.BytesIO(b'{"models":[]}'), io.BytesIO(json.dumps({'models': [{'name': 'custom:3b', 'digest': digest}]}).encode())]
            def create(command, **kwargs):
                self.assertNotIn('--quantize', command)
                self.assertIn(gguf.as_posix(), (root / 'Modelfile').read_text())
            with patch('text2sql_demo.experiment.training.resolve_ollama_executable', return_value='ollama.exe'), \
                 patch('text2sql_demo.experiment.training.urllib.request.urlopen', side_effect=responses), \
                 patch('text2sql_demo.experiment.training.subprocess.run', side_effect=create):
                result = training.register_ollama(root, 'custom:3b', models_dir=store)
            self.assertEqual(result['quantization'], 'Q4_K_M')
            self.assertEqual(result['import_artifact']['sha256'], hashlib.sha256(b'GGUFq4').hexdigest())
            training.validate_training_manifest(root / 'training_manifest.json', model='custom:3b')
            gguf.write_bytes(b'GGUFchanged')
            with self.assertRaisesRegex(ValueError, 'GGUF'):
                training.validate_training_manifest(root / 'training_manifest.json', model='custom:3b')

    def test_unrelated_gguf_export_cannot_register_as_the_trained_model(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); manifest = merged_fixture(root)
            (root / 'wrong.gguf').write_bytes(b'GGUFwrong')
            manifest['gguf_export'] = {'path': 'wrong.gguf', 'sha256': hashlib.sha256(b'GGUFwrong').hexdigest(),
                                       'quantization': 'Q4_K_M', 'source_artifact_files': {'other.safetensors': 'other'}}
            (root / 'training_manifest.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, 'GGUF'):
                training.validate_training_manifest(root / 'training_manifest.json')

    def test_existing_server_tag_from_another_store_cannot_register_new_weights(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); manifest = merged_fixture(root)
            (root / 'trained.gguf').write_bytes(b'GGUFq4')
            export_hash = hashlib.sha256(b'GGUFq4').hexdigest()
            manifest['gguf_export'] = {'path': 'trained.gguf', 'sha256': export_hash,
                                       'quantization': 'Q4_K_M', 'source_artifact_files': manifest['artifact_files']}
            path = root / 'training_manifest.json'; path.write_text(json.dumps(manifest))
            before = path.read_bytes(); store = root / 'other-store'
            created_model_fixture(store, export_hash)
            responses = [io.BytesIO(b'{"models":[{"name":"custom:3b","digest":"old-server-digest"}]}') for _ in range(2)]
            with patch('text2sql_demo.experiment.training.resolve_ollama_executable', return_value='ollama.exe'), \
                 patch('text2sql_demo.experiment.training.urllib.request.urlopen', side_effect=responses), \
                 patch('text2sql_demo.experiment.training.subprocess.run'):
                with self.assertRaisesRegex(RuntimeError, 'model store|created model'):
                    training.register_ollama(root, 'custom:3b', models_dir=store)
            self.assertEqual(path.read_bytes(), before)

    def test_active_export_is_rejected_before_running_conversion(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); merged_fixture(root)
            lock = root / '.gguf-export.lock'; lock.write_text('{"pid": 123}')
            with patch('text2sql_demo.experiment.training.subprocess.run', side_effect=AssertionError('must not run converter')):
                with self.assertRaisesRegex(RuntimeError, 'already active'):
                    training.export_gguf(root)
            self.assertTrue(lock.exists())

    def test_completed_export_recovers_manifest_commit_without_reconversion(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); merged_fixture(root)
            converter = root / 'convert.py'; converter.write_text('# converter')
            quantizer = root / 'quantize.exe'; quantizer.write_bytes(b'quantizer')
            original_write = training._write_json
            def fail_manifest(path, value):
                if Path(path).name == 'training_manifest.json': raise OSError('simulated commit failure')
                original_write(path, value)
            def execute(command, **kwargs):
                if '--outfile' in command:
                    Path(command[command.index('--outfile') + 1]).write_bytes(b'GGUFf16')
                else:
                    Path(command[-3]).write_bytes(b'GGUFq4')
            with patch('text2sql_demo.experiment.training.subprocess.run', side_effect=execute), \
                 patch('text2sql_demo.experiment.training._write_json', side_effect=fail_manifest):
                with self.assertRaises(OSError):
                    training.export_gguf(root, converter, quantizer)
            self.assertFalse((root / '.gguf-export.lock').exists())
            with patch('text2sql_demo.experiment.training.subprocess.run', side_effect=AssertionError('must not reconvert')):
                result = training.export_gguf(root, converter, quantizer)
            self.assertEqual(result['sha256'], hashlib.sha256(b'GGUFq4').hexdigest())
            training.validate_training_manifest(root / 'training_manifest.json')


if __name__ == '__main__': unittest.main()
