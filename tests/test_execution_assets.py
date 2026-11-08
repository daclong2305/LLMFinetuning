import json
import sqlite3
import tempfile
import unittest
import hashlib
import zipfile
from contextlib import closing
from unittest.mock import patch
from pathlib import Path

try:
    from scripts.prepare_execution_assets import adapt_database, prepare_assets, audit_assets
except ImportError:
    adapt_database = None


class ExecutionAssetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / 'source.sqlite'
        with closing(sqlite3.connect(self.source)) as con, con:
            con.executescript('''
                CREATE TABLE parent(id INTEGER PRIMARY KEY, name TEXT);
                CREATE TABLE child(id INTEGER PRIMARY KEY, parent_id INTEGER REFERENCES parent(id), score REAL);
                CREATE INDEX child_score ON child(score);
                INSERT INTO parent VALUES(1, 'Alice'), (2, NULL);
                INSERT INTO child VALUES(7, 1, 3.5), (8, 2, 4.5);
            ''')
        self.english = {'db_id': 'db', 'table_names_original': ['parent', 'child'],
            'column_names_original': [[-1, '*'], [0, 'id'], [0, 'name'], [1, 'id'], [1, 'parent_id'], [1, 'score']],
            'column_types': ['text', 'number', 'text', 'number', 'number', 'number'],
            'primary_keys': [1, 3], 'foreign_keys': [[4, 1]]}
        self.vietnamese = {**self.english, 'table_names_original': ['cha mẹ', 'con'],
            'column_names_original': [[-1, '*'], [0, 'mã'], [0, 'tên'], [1, 'mã'], [1, 'mã cha mẹ'], [1, 'điểm']]}

    def test_adapter_preserves_rows_types_nulls_indexes_and_foreign_keys(self):
        self.assertIsNotNone(adapt_database, 'Execution asset adapter missing')
        before = self.source.read_bytes()
        output = self.root / 'target.sqlite'
        adapt_database(self.source, output, self.english, self.vietnamese)
        with closing(sqlite3.connect(output)) as con, con:
            self.assertEqual(con.execute('SELECT * FROM "cha mẹ" ORDER BY "mã"').fetchall(), [(1, 'Alice'), (2, None)])
            self.assertEqual(con.execute('SELECT typeof("điểm"), "điểm" FROM con ORDER BY "mã"').fetchall(), [('real', 3.5), ('real', 4.5)])
            self.assertEqual(con.execute('PRAGMA foreign_key_check').fetchall(), [])
            self.assertEqual(con.execute('PRAGMA foreign_key_list(con)').fetchone()[2:5], ('cha mẹ', 'mã cha mẹ', 'mã'))
            self.assertEqual(con.execute('PRAGMA index_info(child_score)').fetchone()[2], 'điểm')
        self.assertEqual(self.source.read_bytes(), before)

    def test_identifier_swaps_do_not_collide(self):
        self.assertIsNotNone(adapt_database, 'Execution asset adapter missing')
        target = {**self.english, 'table_names_original': ['child', 'parent'],
            'column_names_original': [[-1, '*'], [0, 'name'], [0, 'id'], [1, 'score'], [1, 'parent_id'], [1, 'id']]}
        output = self.root / 'swapped.sqlite'
        adapt_database(self.source, output, self.english, target)
        with closing(sqlite3.connect(output)) as con, con:
            self.assertEqual(con.execute('SELECT name, id FROM child ORDER BY name').fetchall(), [(1, 'Alice'), (2, None)])

    def test_bad_schema_alignment_cannot_publish_database(self):
        self.assertIsNotNone(adapt_database, 'Execution asset adapter missing')
        target = {**self.vietnamese, 'column_names_original': self.vietnamese['column_names_original'][:-1]}
        output = self.root / 'bad.sqlite'
        with self.assertRaisesRegex(ValueError, 'align|column'):
            adapt_database(self.source, output, self.english, target)
        self.assertFalse(output.exists())

    def test_existing_output_is_never_overwritten(self):
        self.assertIsNotNone(adapt_database, 'Execution asset adapter missing')
        output = self.root / 'existing.sqlite'
        output.write_bytes(b'keep user data')
        with self.assertRaises(FileExistsError):
            adapt_database(self.source, output, self.english, self.vietnamese)
        self.assertEqual(output.read_bytes(), b'keep user data')

    def test_adapter_preserves_non_utf8_text_without_decoding_or_repair(self):
        self.assertIsNotNone(adapt_database, 'Execution asset adapter missing')
        with closing(sqlite3.connect(self.source)) as con, con:
            con.execute("INSERT INTO parent VALUES(3, CAST(X'80' AS TEXT))")
        output = self.root / 'non-utf8.sqlite'
        adapt_database(self.source, output, self.english, self.vietnamese)
        with closing(sqlite3.connect(output)) as con:
            con.text_factory = bytes
            self.assertEqual(con.execute('SELECT typeof("tên"), "tên" FROM "cha mẹ" WHERE "mã"=3').fetchone(), (b'text', b'\x80'))

    def test_published_sqlite_sequence_is_copied_as_queryable_user_table(self):
        self.assertIsNotNone(adapt_database, 'Execution asset adapter missing')
        source = self.root / 'sequence.sqlite'
        with closing(sqlite3.connect(source)) as con, con:
            con.executescript("CREATE TABLE parent(id INTEGER PRIMARY KEY AUTOINCREMENT); INSERT INTO parent DEFAULT VALUES;")
        english = {'db_id': 'db', 'table_names_original': ['parent', 'sqlite_sequence'],
            'column_names_original': [[-1, '*'], [0, 'id'], [1, 'name'], [1, 'seq']],
            'column_types': ['text', 'number', 'text', 'number'], 'primary_keys': [1], 'foreign_keys': []}
        vietnamese = {**english, 'table_names_original': ['cha mẹ', 'thứ tự sqlite'],
            'column_names_original': [[-1, '*'], [0, 'mã'], [1, 'tên'], [1, 'số thứ tự']]}
        output = self.root / 'sequence-target.sqlite'
        adapt_database(source, output, english, vietnamese)
        with closing(sqlite3.connect(output)) as con:
            self.assertEqual(con.execute('SELECT * FROM "thứ tự sqlite"').fetchall(), [('parent', 1)])
            self.assertEqual(con.execute('SELECT * FROM "cha mẹ"').fetchall(), [(1,)])

    def test_import_audit_metrics_and_rerun_with_verified_sources(self):
        self.assertIsNotNone(adapt_database, 'Execution asset adapter missing')
        from test_experiment_data import fixture
        from text2sql_demo.experiment.dataset import DatasetStore
        dataset = self.root / 'dataset'
        dataset.mkdir()
        fixture(dataset)
        sources = self.root / 'sources'
        sources.mkdir()
        schemas = []
        raw_database = self.root / 'raw.sqlite'
        with closing(sqlite3.connect(raw_database)) as con, con:
            con.executescript("CREATE TABLE customer(id INTEGER PRIMARY KEY, name TEXT); INSERT INTO customer VALUES (1, 'Alice');")
        alternate = self.root / 'other.sqlite'
        with closing(sqlite3.connect(alternate)) as con, con:
            con.executescript("CREATE TABLE customer(id INTEGER PRIMARY KEY, name TEXT); INSERT INTO customer VALUES (2, 'Bob');")
        for db in ('a', 'b', 'c'):
            schemas.append({'db_id': db, 'table_names_original': ['customer'],
                'column_names_original': [[-1, '*'], [0, 'id'], [0, 'name']],
                'column_types': ['text', 'number', 'text'], 'primary_keys': [1], 'foreign_keys': []})
        with zipfile.ZipFile(sources / 'spider_data.zip', 'w') as z:
            z.writestr('spider_data/tables.json', json.dumps(schemas))
            for db in ('a', 'b', 'c'):
                z.write(raw_database, f'spider_data/database/{db}/{db}.sqlite')
        with zipfile.ZipFile(sources / 'testsuitedatabases.zip', 'w') as z:
            for db in ('a', 'b', 'c'):
                z.write(raw_database, f'database/{db}/{db}.sqlite')
                z.write(alternate, f'database/{db}/{db}_other.sqlite')
        (sources / 'suite-tables.json').write_text(json.dumps(schemas), encoding='utf-8')
        for name in ('spider_data.zip', 'testsuitedatabases.zip', 'suite-tables.json'):
            digest = hashlib.sha256((sources / name).read_bytes()).hexdigest()
            (sources / (name + '.source.json')).write_text(json.dumps({'url': 'fixture', 'sha256': digest}), encoding='utf-8')
        first = prepare_assets(dataset, sources)
        ready = audit_assets(dataset, self_check=True)
        self.assertEqual(ready['coverage']['dev'], {'total': 1, 'ex': 1, 'ts': 1, 'ves_eligible': 1})
        for check in ready['self_checks']:
            self.assertEqual(check['gold']['ex'], 1)
            self.assertEqual(check['gold']['ts'], 1)
            self.assertGreater(check['gold']['ves'], 0)
            self.assertEqual(check['gold_ves_completed_pairs'], 100)
            self.assertEqual(check['negative_control'], {'ex': 0, 'ts': 0, 'ves': 0.0})
        self.assertEqual(len(DatasetStore(dataset).test_suite_assets('b')['files']), 2)
        second = prepare_assets(dataset, sources)
        self.assertEqual(json.loads(json.dumps(first['databases'])), second['databases'])
        self.assertEqual(first['test_suites'], second['test_suites'])
        from scripts import prepare_execution_assets as assets
        original_write = assets.write_json
        def interrupt_after_checkpoint(path, value):
            original_write(path, value)
            if Path(path).name == 'execution-assets-import.json':
                if any(v.get('complete') is False and v.get('files') for v in value.get('test_suites', {}).values()):
                    raise KeyboardInterrupt('Simulated interruption after a durable checkpoint')
        with patch.object(assets, 'write_json', side_effect=interrupt_after_checkpoint):
            with self.assertRaises(KeyboardInterrupt):
                prepare_assets(dataset, sources)
        resumed = prepare_assets(dataset, sources)
        self.assertEqual(second['test_suites'], resumed['test_suites'])
        base = dataset / 'database' / 'b' / 'b.sqlite'
        with closing(sqlite3.connect(base)) as con, con:
            con.execute('UPDATE "Khách hàng" SET "tên" = ?', ('tampered',))
        changed = audit_assets(dataset)
        self.assertFalse(changed['databases']['b']['ex'])
        self.assertIn('hash', changed['databases']['b']['ex_reason'])
        # Two good states do not make a full suite when another member failed.
        report_path = dataset / 'execution-assets-import.json'
        report = json.loads(report_path.read_text(encoding='utf-8'))
        report['test_suites']['a']['errors'].append({'source_member': 'missing.sqlite', 'reason': 'failed'})
        report_path.write_text(json.dumps(report), encoding='utf-8')
        partial = audit_assets(dataset)
        self.assertFalse(partial['databases']['a']['ts'])
        self.assertIn('partial suites', partial['databases']['a']['ts_reason'])
        with (sources / 'suite-tables.json').open('a', encoding='utf-8') as f:
            f.write(' ')
        with self.assertRaisesRegex(ValueError, 'hash changed'):
            prepare_assets(dataset, sources)

    def test_downloader_refuses_tampered_cache_without_network_or_overwrite(self):
        from scripts.download_execution_sources import download_file
        cached = self.root / 'cached.zip'
        cached.write_bytes(b'user bytes')
        with patch('scripts.download_execution_sources.urllib.request.build_opener') as network:
            with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
                download_file(cached, ['https://example.invalid'], hashlib.sha256(b'expected').hexdigest())
            network.assert_not_called()
        self.assertEqual(cached.read_bytes(), b'user bytes')

    def test_downloader_rejects_html_instead_of_publishing_an_archive(self):
        from scripts.download_execution_sources import download_file
        from io import BytesIO
        body = BytesIO(b'<html>Quota exceeded</html>')
        body.headers = {'Content-Type': 'text/html'}
        with patch('scripts.download_execution_sources.urllib.request.build_opener') as network:
            network.return_value.open.return_value = body
            target = self.root / 'html.zip'
            with self.assertRaisesRegex(ValueError, 'HTML/quota'):
                download_file(target, ['https://example.invalid'], '0' * 64)
        self.assertFalse(target.exists())


if __name__ == '__main__':
    unittest.main()
