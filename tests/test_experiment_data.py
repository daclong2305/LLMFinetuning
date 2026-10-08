import hashlib
import json
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

try:
    from text2sql_demo.experiment.dataset import DatasetStore, REVISION
except ImportError:
    DatasetStore = None
    REVISION = 'e759141d891feb794bb9a9fb912d544b25583b3c'


def fixture(root, leak=False):
    tables = []
    for db in ('a', 'b', 'c'):
        tables.append({'db_id': db, 'table_names_original': ['Khách hàng'],
            'table_names': ['Khách hàng'], 'column_names_original': [[-1, '*'], [0, 'mã'], [0, 'tên']],
            'column_names': [[-1, '*'], [0, 'mã'], [0, 'tên']], 'column_types': ['text', 'number', 'text'],
            'primary_keys': [1], 'foreign_keys': []})
    files = {'tables.json': tables}
    for split, db in zip(('train', 'dev', 'test'), ('a', 'a' if leak else 'b', 'c')):
        files[split + '.json'] = [{'db_id': db, 'question': 'Tên khách?',
            'query': 'select tên from Khách hàng', 'sql': None}]
    hashes = {}
    for name, value in files.items():
        raw = json.dumps(value, ensure_ascii=False).encode('utf-8')
        (root / name).write_bytes(raw)
        hashes[name] = hashlib.sha256(raw).hexdigest()
    (root / 'source-lock.json').write_text(json.dumps({'revision': REVISION, 'sha256': hashes}), encoding='utf-8')


class DatasetTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(DatasetStore, 'DatasetStore feature is missing')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_missing_dataset_is_unavailable_without_download(self):
        store = DatasetStore(self.root)
        self.assertFalse(store.summary()['ready'])
        self.assertEqual(list(store.samples('dev')), [])

    def test_database_disjoint_split_rejects_leakage(self):
        fixture(self.root, leak=True)
        with self.assertRaisesRegex(ValueError, 'leak|disjoint|overlap'):
            DatasetStore(self.root)

    def test_unicode_schema_and_stable_sample_ids(self):
        fixture(self.root)
        store = DatasetStore(self.root)
        sample = list(store.samples('dev'))[0]
        self.assertEqual(sample['gold_sql'], 'select tên from Khách hàng')
        self.assertEqual(store.get_sample(sample['id']), sample)
        schema = store.schema('b')['Khách hàng']
        self.assertEqual([c['name'] for c in schema['columns']], ['mã', 'tên'])
        self.assertIn('"Khách hàng"', schema['ddl'])
        self.assertIsNone(store.database_path('b'))
        self.assertTrue(store.summary()['leakage_audit']['passed'])

    def test_tampered_source_hash_rejected(self):
        fixture(self.root)
        (self.root / 'dev.json').write_text('[]', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'hash|integrity'):
            DatasetStore(self.root)

    def test_sqlite_content_changes_dataset_fingerprint(self):
        import sqlite3
        fixture(self.root)
        databases = self.root / 'database'
        databases.mkdir()
        path = databases / 'b.sqlite'
        with closing(sqlite3.connect(path)) as con, con:
            con.execute('create table x(n integer)')
            con.execute('insert into x values (1)')
        first = DatasetStore(self.root).summary()['fingerprint']
        with closing(sqlite3.connect(path)) as con, con:
            con.execute('insert into x values (2)')
        self.assertNotEqual(first, DatasetStore(self.root).summary()['fingerprint'])

    def test_store_rejects_database_changed_after_snapshot(self):
        import sqlite3
        fixture(self.root)
        databases = self.root / 'database'
        databases.mkdir()
        path = databases / 'b.sqlite'
        with closing(sqlite3.connect(path)) as con, con:
            con.execute('create table x(n integer)')
        store = DatasetStore(self.root)
        with closing(sqlite3.connect(path)) as con, con:
            con.execute('insert into x values (2)')
        with self.assertRaisesRegex(ValueError, 'changed|snapshot'):
            store.database_path('b')

    def test_offline_preparation_does_not_label_arbitrary_bytes_official(self):
        from scripts.prepare_vitext2sql import prepare
        fixture(self.root)
        with self.assertRaisesRegex(ValueError, 'official|pinned'):
            prepare(self.root, offline=True)
