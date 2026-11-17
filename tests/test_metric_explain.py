import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from text2sql_demo.experiment.evaluation import explain_execution, explain_test_suite

SCHEMA = {'kiến trúc sư': {'columns': [
    {'name': 'id', 'type': 'INTEGER', 'pk': True}, {'name': 'tên', 'type': 'TEXT'},
    {'name': 'quốc tịch', 'type': 'TEXT'}], 'foreign_keys': []}}
GOLD = 'select tên from kiến trúc sư where quốc tịch = \'Mỹ\' order by id'


def make_db(path, rows):
    with closing(sqlite3.connect(path)) as con:
        con.execute('CREATE TABLE "kiến trúc sư" ("id" INTEGER PRIMARY KEY, "tên" TEXT, "quốc tịch" TEXT)')
        con.executemany('INSERT INTO "kiến trúc sư" VALUES (?,?,?)', rows)
        con.commit()


class Store:
    def __init__(self, root, states=()):
        self.path = Path(root) / 'main.sqlite'
        make_db(self.path, [(1, 'An', 'Mỹ'), (2, 'Bình', 'Pháp'), (3, 'Chi', 'Mỹ')])
        self.states = list(states)

    def schema(self, db_id):
        return SCHEMA

    def database_path(self, db_id):
        return self.path

    def samples_for_database(self, db_id):
        return [{'gold_sql': GOLD}]

    def test_suite_assets(self, db_id):
        if len(self.states) < 2:
            return {'available': False, 'reason': 'At least two distinct test-suite states required for this database.', 'files': []}
        return {'available': True, 'reason': None, 'files': [{'path': p} for p in self.states]}


SAMPLE = {'id': 'dev:1', 'db_id': 'arch', 'gold_sql': GOLD}


class ExplainExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp.cleanup()

    def test_match_returns_both_results(self):
        out = explain_execution('SELECT "tên" FROM "kiến trúc sư" WHERE "quốc tịch" = \'Mỹ\' ORDER BY "id"', SAMPLE, Store(self.temp.name))
        self.assertTrue(out['available'])
        self.assertTrue(out['ordered'])
        self.assertEqual(out['gold']['rows'], [['An'], ['Chi']])
        self.assertEqual(out['pred']['row_count'], 2)
        self.assertEqual((out['ex'], out['verdict']), (1, 'match'))

    def test_wrong_rows_and_columns_are_diagnosed(self):
        store = Store(self.temp.name)
        rows = explain_execution('SELECT "tên" FROM "kiến trúc sư" ORDER BY "id"', SAMPLE, store)
        self.assertEqual((rows['ex'], rows['verdict']), (0, 'row_count'))
        cols = explain_execution('SELECT "tên", "id" FROM "kiến trúc sư" WHERE "quốc tịch" = \'Mỹ\' ORDER BY "id"', SAMPLE, store)
        self.assertEqual((cols['ex'], cols['verdict']), (0, 'column_count'))
        values = explain_execution('SELECT "tên" FROM "kiến trúc sư" WHERE "quốc tịch" = \'Mỹ\' ORDER BY "id" DESC', SAMPLE, store)
        self.assertEqual((values['ex'], values['verdict']), (0, 'values'))
        broken = explain_execution('SELECT nope FROM "kiến trúc sư"', SAMPLE, store)
        self.assertEqual((broken['ex'], broken['verdict']), (0, 'pred_error'))
        self.assertTrue(broken['pred']['error'])

    def test_missing_database_is_unavailable(self):
        store = Store(self.temp.name)
        store.database_path = lambda db_id: None
        out = explain_execution('SELECT 1', SAMPLE, store)
        self.assertFalse(out['available'])
        self.assertTrue(out['reason'])

    def test_rows_are_capped_for_display(self):
        out = explain_execution('SELECT "tên" FROM "kiến trúc sư" WHERE "quốc tịch" = \'Mỹ\' ORDER BY "id"', SAMPLE, Store(self.temp.name), max_rows=1)
        self.assertEqual(out['gold']['rows'], [['An']])
        self.assertEqual(out['gold']['row_count'], 2)


class ExplainTestSuiteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.s1, self.s2 = root / 's1.sqlite', root / 's2.sqlite'
        make_db(self.s1, [(1, 'An', 'Mỹ'), (2, 'Bình', 'Pháp')])
        make_db(self.s2, [(1, 'An', 'Pháp'), (2, 'Bình', 'Mỹ')])

    def tearDown(self):
        self.temp.cleanup()

    def test_each_state_reported_and_all_must_match(self):
        store = Store(self.temp.name, [self.s1, self.s2])
        ok = explain_test_suite('SELECT "tên" FROM "kiến trúc sư" WHERE "quốc tịch" = \'Mỹ\' ORDER BY "id"', SAMPLE, store)
        self.assertEqual(ok['ts'], 1)
        self.assertEqual([s['match'] for s in ok['states']], [True, True])
        self.assertEqual(ok['states'][0]['name'], 's1.sqlite')
        # Hard-coding the answer of one state passes it but fails the other.
        bad = explain_test_suite('SELECT "tên" FROM "kiến trúc sư" WHERE "id" = 1', SAMPLE, store)
        self.assertEqual(bad['ts'], 0)
        self.assertEqual([s['match'] for s in bad['states']], [True, False])

    def test_unavailable_suite_reports_reason(self):
        out = explain_test_suite('SELECT 1', SAMPLE, Store(self.temp.name))
        self.assertFalse(out['available'])
        self.assertIn('two distinct', out['reason'])


if __name__ == '__main__':
    unittest.main()
