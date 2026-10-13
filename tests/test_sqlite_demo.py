import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from test_experiment_data import fixture
from text2sql_demo.database import execute_readonly
from text2sql_demo.experiment.dataset import DatasetStore
from text2sql_demo.experiment.evaluation import evaluate_prediction, _audit_database
from text2sql_demo.experiment.pipeline import execute_preview


class SQLiteDemoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def seed(self):
        try:
            from scripts.seed_visql_demo import seed_database
        except ImportError:
            self.fail('SQLite demo seed command is missing')
        return seed_database(self.root / 'database')

    def test_seed_supports_filters_joins_and_readonly_execution(self):
        path = self.seed()
        result = execute_readonly(path, 'SELECT COUNT(*) FROM "kiến trúc sư" WHERE "giới tính" = \'female\'')
        self.assertEqual(result['rows'], [[4]])
        joined = execute_readonly(path, 'SELECT a."tên", COUNT(*) FROM "kiến trúc sư" a JOIN "cầu" b ON b."id kiến trúc sư" = a.id GROUP BY a.id HAVING COUNT(*) >= 3')
        self.assertEqual(joined['rows'], [['Nguyễn Minh An', 3]])
        with closing(sqlite3.connect(path)) as con:
            self.assertEqual(con.execute('PRAGMA foreign_key_check').fetchall(), [])
        self.assertEqual(execute_readonly(path, 'DELETE FROM "cầu"')['status'], 'error')

    def test_seed_never_overwrites_existing_database(self):
        path = self.seed()
        original = path.read_bytes()
        with self.assertRaises(FileExistsError):
            self.seed()
        self.assertEqual(path.read_bytes(), original)

    def test_seed_does_not_shadow_supported_flat_database(self):
        folder = self.root / 'database'
        folder.mkdir()
        existing = folder / 'architecture.sqlite'
        existing.write_bytes(b'existing user database')
        with self.assertRaises(FileExistsError):
            self.seed()
        self.assertFalse((folder / 'architecture' / 'architecture.sqlite').exists())
        self.assertEqual(existing.read_bytes(), b'existing user database')

    def test_corrupt_database_is_reported_without_disabling_other_schemas(self):
        fixture(self.root)
        folder = self.root / 'database'
        folder.mkdir()
        (folder / 'b.sqlite').write_bytes(b'not a sqlite database')
        try:
            store = DatasetStore(self.root)
        except sqlite3.DatabaseError:
            self.fail('One broken SQLite file must not prevent loading the dataset')
        self.assertTrue(store.summary()['ready'])
        self.assertIn('b', store.summary()['database_errors'])
        self.assertIn('Khách hàng', store.schema('a'))
        with self.assertRaises(ValueError):
            store.database_path('b')

    def demo_store(self):
        fixture(self.root)
        folder = self.root / 'database'
        folder.mkdir()
        with closing(sqlite3.connect(folder / 'b.sqlite')) as con, con:
            con.execute('CREATE TABLE "Khách hàng" ("mã" NUMERIC PRIMARY KEY, "tên" TEXT)')
            con.execute('INSERT INTO "Khách hàng" VALUES (1, ?)', ('Nguyễn An',))
            con.execute('CREATE TABLE __visql_demo (description TEXT NOT NULL)')
            con.execute('INSERT INTO __visql_demo VALUES (?)', ('Dữ liệu mô phỏng để demo.',))
        return DatasetStore(self.root)

    def test_preview_identifies_seed_data_and_returns_real_rows(self):
        store = self.demo_store()
        result = execute_preview(store, 'b', 'SELECT "tên" FROM "Khách hàng"', store.schema('b'))
        self.assertEqual(result['rows'], [['Nguyễn An']])
        self.assertEqual(result['mode'], 'database')
        self.assertTrue(result.get('synthetic'), 'Demo data must be labeled in API results')
        self.assertEqual(store.summary().get('demo_databases'), ['b'])

    def test_demo_schema_exposes_actual_filter_values_to_model(self):
        store = self.demo_store()
        schema = store.schema('b')
        self.assertIn('Nguyễn An', schema['Khách hàng']['description'])
        self.assertNotIn('__visql_demo', schema)

    def test_demo_runs_sql_but_never_reports_execution_benchmark_scores(self):
        store = self.demo_store()
        sample = store.samples('dev')[0]
        result = evaluate_prediction(sample['gold_sql'], sample, store)
        self.assertTrue(result['execution_success'])
        for metric in ('ex', 'ts', 'ves'):
            self.assertIsNone(result[metric], metric)
            self.assertIn('demo', result['unavailable_reasons'][metric].lower())
        qualified, reason = _audit_database(store.database_path('b'), store.schema('b'), sample, store, 5)
        self.assertFalse(qualified, 'Demo must not qualify through the standalone audit command')
        self.assertIn('demo', reason.lower())


if __name__ == '__main__':
    unittest.main()
