import hashlib
import importlib.util
import json
import tempfile
import unittest
import io
from unittest.mock import patch
from pathlib import Path

from text2sql_demo.experiment.training import (prepare_training_data, encode_completion,
    dependency_diagnostics, validate_training_manifest, resolve_ollama_executable, register_ollama, _verified_data)


class FixtureStore:
    def summary(self): return {'ready': True, 'fingerprint': 'fixed-data', 'revision': 'pinned', 'leakage_audit': {'ok': True}}
    def samples(self, split, limit=None):
        if split == 'test': raise AssertionError('Test split must never be loaded for training')
        return [{'id': split + ':1', 'split': split, 'db_id': split + '_db', 'question': 'Có bao nhiêu người?', 'gold_sql': 'SELECT COUNT(*) FROM người'}]
    def schema(self, db_id): return {'người': {'ddl': 'CREATE TABLE "người" (id INTEGER)', 'columns': [{'name': 'id', 'type': 'INTEGER'}], 'foreign_keys': []}}


class TokenizerFixture:
    eos_token_id = 9
    def apply_chat_template(self, messages, tokenize, add_generation_prompt):
        return [1, 2, 3]
    def encode(self, text, add_special_tokens=False): return [4, 5]


class TrainingTests(unittest.TestCase):
    def test_export_has_train_and_dev_only_with_schema_and_target_separate(self):
        with tempfile.TemporaryDirectory() as temp:
            manifest = prepare_training_data(FixtureStore(), temp)
            train = json.loads((Path(temp) / 'train.jsonl').read_text(encoding='utf-8'))
            self.assertEqual(manifest['trained_splits'], ['train'])
            self.assertEqual(manifest['validation_split'], 'dev')
            self.assertEqual(manifest['counts'], {'train': 1, 'dev': 1})
            self.assertIn('CREATE TABLE', train['messages'][1]['content'])
            self.assertNotIn('SELECT COUNT', json.dumps(train['messages']))
            self.assertEqual(json.loads(train['completion'])['sql'], 'SELECT COUNT(*) FROM "người"')
            self.assertFalse((Path(temp) / 'test.jsonl').exists())

    def test_prompt_tokens_are_masked_and_target_keeps_eos(self):
        encoded = encode_completion({'messages': [], 'completion': 'SQL'}, TokenizerFixture(), 6)
        self.assertEqual(encoded['input_ids'], [1, 2, 3, 4, 5, 9])
        self.assertEqual(encoded['labels'], [-100, -100, -100, 4, 5, 9])

    def test_overlong_example_rejected_instead_of_losing_target(self):
        with self.assertRaisesRegex(ValueError, 'length'):
            encode_completion({'messages': [], 'completion': 'SQL'}, TokenizerFixture(), 3)

    def test_train_and_dev_database_overlap_is_rejected(self):
        class Leaking(FixtureStore):
            def samples(self, split, limit=None):
                return [{**super().samples(split)[0], 'db_id': 'same_db'}]
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError, 'database'):
                prepare_training_data(Leaking(), temp)

    def test_prepared_data_is_never_a_trained_artifact(self):
        with tempfile.TemporaryDirectory() as temp:
            prepare_training_data(FixtureStore(), temp)
            with self.assertRaisesRegex(ValueError, 'trained'):
                validate_training_manifest(Path(temp) / 'training_manifest.json')

    def test_artifact_tampering_invalidates_provenance(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            artifact = root / 'adapter.safetensors'; artifact.write_bytes(b'weights')
            manifest = {'status': 'trained', 'trained_steps': 2, 'trained_splits': ['train'], 'validation_split': 'dev',
                        'dataset_fingerprint': 'fixed', 'base_model': 'Qwen/base', 'base_revision': 'revision',
                        'artifact_kind': 'adapter', 'artifact_files': {'adapter.safetensors': hashlib.sha256(b'weights').hexdigest()}}
            path = root / 'training_manifest.json'; path.write_text(json.dumps(manifest))
            self.assertEqual(validate_training_manifest(path)['artifact_kind'], 'adapter')
            artifact.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'hash'):
                validate_training_manifest(path)

    def test_optional_dependencies_diagnostics_do_not_import_torch(self):
        diagnostics = dependency_diagnostics()
        self.assertIn('missing', diagnostics)
        self.assertEqual('torch' in diagnostics['missing'], importlib.util.find_spec('torch') is None)

    def test_registration_cannot_point_to_replaced_artifact(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            artifact = root / 'model.safetensors'; artifact.write_bytes(b'weights')
            files = {'model.safetensors': hashlib.sha256(b'weights').hexdigest()}
            manifest = {'status': 'trained', 'trained_steps': 2, 'trained_splits': ['train'], 'validation_split': 'dev',
                        'dataset_fingerprint': 'fixed', 'base_model': 'Qwen/base', 'base_revision': 'revision',
                        'artifact_kind': 'merged', 'artifact_files': files,
                        'registration': {'model': 'custom:3b', 'digest': 'old', 'artifact_files': {'model.safetensors': 'different'}}}
            path = root / 'training_manifest.json'; path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, 'registered'):
                validate_training_manifest(path, model='custom:3b')

    def test_bad_schema_targets_are_excluded_with_original_counts(self):
        class InvalidStore(FixtureStore):
            def samples(self, split, limit=None):
                valid = super().samples(split)
                return valid + [{**valid[0], 'id': split + ':bad', 'gold_sql': 'SELECT missing_column FROM người'}]
        with tempfile.TemporaryDirectory() as temp:
            manifest = prepare_training_data(InvalidStore(), temp)
            self.assertEqual(manifest['original_counts'], {'train': 2, 'dev': 2})
            self.assertEqual(manifest['counts'], {'train': 1, 'dev': 1})
            self.assertEqual(manifest['excluded_samples']['train'][0]['id'], 'train:bad')
            self.assertIn('missing_column', manifest['excluded_samples']['train'][0]['reason'])
            self.assertIn('quote', manifest['completion_policy'])

    def test_cli_handles_vietnamese_diagnostics_on_windows_ascii_console(self):
        from scripts.train_qwen import main
        with io.TextIOWrapper(io.BytesIO(), encoding='ascii') as stdout:
            with patch('sys.stdout', stdout), patch('scripts.train_qwen.training_status', return_value={'reason': 'lỗi tên cột'}):
                self.assertEqual(main(['--status']), 0)

    def test_ollama_resolver_prefers_explicit_then_portable(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            portable = root / '.runtime' / 'ollama' / 'ollama.exe'; portable.parent.mkdir(parents=True); portable.write_bytes(b'portable')
            explicit = root / 'custom.exe'; explicit.write_bytes(b'custom')
            self.assertEqual(resolve_ollama_executable(str(explicit), root), str(explicit.resolve()))
            self.assertEqual(resolve_ollama_executable(project_root=root), str(portable.resolve()))

    def test_missing_ollama_has_actionable_diagnostic(self):
        with tempfile.TemporaryDirectory() as temp, patch('text2sql_demo.experiment.training.shutil.which', return_value=None):
            with self.assertRaisesRegex(RuntimeError, 'ollama-executable'):
                resolve_ollama_executable(project_root=temp)

    def test_registration_uses_resolved_executable(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp); weights = out / 'model.safetensors'; weights.write_bytes(b'trained')
            manifest = {'status': 'trained', 'trained_steps': 1, 'trained_splits': ['train'], 'validation_split': 'dev',
                        'dataset_fingerprint': 'fixed', 'base_model': 'base', 'base_revision': 'revision', 'artifact_kind': 'merged',
                        'artifact_files': {'model.safetensors': hashlib.sha256(b'trained').hexdigest()}}
            (out / 'training_manifest.json').write_text(json.dumps(manifest))
            responses = [io.BytesIO(b'{"models":[]}'), io.BytesIO(b'{"models":[{"name":"custom:3b","digest":"trained"}]}')]
            with patch('text2sql_demo.experiment.training.resolve_ollama_executable', return_value='C:/portable/ollama.exe'), \
                 patch('text2sql_demo.experiment.training.urllib.request.urlopen', side_effect=responses), \
                 patch('text2sql_demo.experiment.training.subprocess.run') as runner:
                result = register_ollama(out, 'custom:3b')
            self.assertEqual(runner.call_args.args[0][0], 'C:/portable/ollama.exe')
            self.assertEqual(result['digest'], 'trained')

    def test_preparation_rejects_changed_dataset_snapshot(self):
        class Changed(FixtureStore):
            def summary(self): return {**super().summary(), 'fingerprint': 'other-source'}
        with tempfile.TemporaryDirectory() as temp:
            prepare_training_data(FixtureStore(), temp)
            with self.assertRaisesRegex(ValueError, 'snapshot'):
                prepare_training_data(Changed(), temp)

    def test_snapshot_metadata_changes_cannot_bypass_export_hashes(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp); manifest = prepare_training_data(FixtureStore(), out)
            manifest['dataset_fingerprint'] = 'changed-source'
            (out / 'training_manifest.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, 'snapshot'):
                _verified_data(out)

    def test_repreparation_retains_prior_snapshot_and_active_run_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp); first = prepare_training_data(FixtureStore(), out)
            second = prepare_training_data(FixtureStore(), out)
            self.assertEqual(second['preparation_history'][0]['data_snapshot_sha256'], first['data_snapshot_sha256'])
            self.assertEqual(_verified_data(out)['data_snapshot_sha256'], second['data_snapshot_sha256'])
            (out / '.training.lock').write_text('{}')
            with self.assertRaisesRegex(ValueError, 'active'):
                prepare_training_data(FixtureStore(), out)

    def test_completed_training_still_requires_unchanged_data_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp); manifest = prepare_training_data(FixtureStore(), out)
            weights = out / 'model.safetensors'; weights.write_bytes(b'trained')
            manifest.update(status='trained', trained_steps=1, base_model='base', base_revision='revision', artifact_kind='adapter',
                            artifact_files={'model.safetensors': hashlib.sha256(b'trained').hexdigest()})
            (out / 'training_manifest.json').write_text(json.dumps(manifest))
            (out / 'train.jsonl').write_text('tampered')
            with self.assertRaisesRegex(ValueError, 'hash'):
                validate_training_manifest(out / 'training_manifest.json')


if __name__ == '__main__': unittest.main()
