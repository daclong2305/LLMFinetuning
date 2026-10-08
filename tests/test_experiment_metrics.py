import sqlite3
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

try:
    from text2sql_demo.experiment.evaluation import evaluate_prediction, execute_full_readonly, parse_structural
except ImportError:
    evaluate_prediction = execute_full_readonly = None


class Store:
    def __init__(self, path=None):
        self.path = path
    def database_path(self, db_id):
        return self.path
    def schema(self, db_id):
        return {'Khách hàng': {'columns': [{'name': 'mã', 'type': 'INTEGER', 'pk': True},
                 {'name': 'tên', 'type': 'TEXT', 'pk': False}], 'foreign_keys': []}}


class MetricTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(evaluate_prediction, 'Evaluation feature is missing')
        self.sample = {'db_id': 'b', 'gold_sql': 'select mã from Khách hàng'}
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'b.sqlite'
        with sqlite3.connect(self.path) as con:
            con.execute('create table "Khách hàng"("mã" integer, "tên" text)')
            con.executemany('insert into "Khách hàng" values (?,?)', [(i, 'x') for i in range(1, 302)] + [(301, 'x')])

    def test_structural_alias_match_and_wrong_column_difference(self):
        result = evaluate_prediction('SELECT t."mã" FROM "Khách hàng" AS t', self.sample, Store())
        self.assertEqual(result['em'], 1)
        self.assertEqual(result['cm'], 1)
        wrong = evaluate_prediction('select "tên" from "Khách hàng"', self.sample, Store())
        self.assertEqual(wrong['em'], 0)
        self.assertEqual(wrong['cm_components']['select']['f1'], 0)
        self.assertIsNone(wrong['ex'])

    def test_partial_components_not_raw_string_comparison(self):
        result = evaluate_prediction('select "mã" from "Khách hàng" where "mã" > 20', self.sample, Store())
        self.assertEqual(result['em'], 0)
        self.assertGreater(result['cm'], 0)
        self.assertLess(result['cm'], 1)

    def test_full_rows_beyond_preview_and_duplicates(self):
        result = evaluate_prediction('select "mã" from "Khách hàng" where "mã" <= 300', self.sample, Store(self.path))
        self.assertEqual(result['ex'], 0)
        result = evaluate_prediction('select distinct "mã" from "Khách hàng"', self.sample, Store(self.path))
        self.assertEqual(result['ex'], 0)
        full = execute_full_readonly(self.path, 'select "mã" from "Khách hàng"')
        self.assertEqual(len(full['rows']), 302)
        bounded = execute_full_readonly(self.path, 'select "mã" from "Khách hàng"', max_rows=200)
        self.assertFalse(bounded['complete'])

    def test_ordered_gold_requires_row_order_and_sql_is_readonly(self):
        self.sample['gold_sql'] += ' order by mã asc'
        result = evaluate_prediction('select "mã" from "Khách hàng" order by "mã" desc', self.sample, Store(self.path))
        self.assertEqual(result['ex'], 0)
        denied = execute_full_readonly(self.path, 'delete from "Khách hàng"')
        self.assertNotEqual(denied['status'], 'ok')

    def test_empty_database_never_qualifies_for_execution_accuracy(self):
        with sqlite3.connect(self.path) as con:
            con.execute('delete from "Khách hàng"')
        result = evaluate_prediction(self.sample['gold_sql'], self.sample, Store(self.path))
        self.assertIsNone(result['ex'])
        self.assertIn('ex', result['unavailable_reasons'])

    def test_invalid_prediction_is_zero_structural_not_missing(self):
        result = evaluate_prediction('nonsense', self.sample, Store())
        self.assertEqual(result['em'], 0)
        self.assertEqual(result['cm'], 0)
        self.assertFalse(result['syntax_valid'])

    def test_negative_decimal_literals_and_select_alias(self):
        self.sample['gold_sql'] = 'select mã from Khách hàng where mã between -50.5 and 50.5'
        result = evaluate_prediction('select "mã" AS code from "Khách hàng" where "mã" between -50.5 and 50.5', self.sample, Store())
        self.assertEqual(result['em'], 1)
        self.assertTrue(result['gold_valid'])

    def test_quoted_column_on_right_side_preserves_identity(self):
        self.sample['gold_sql'] = 'select mã from Khách hàng where mã = mã'
        result = evaluate_prediction('select "mã" from "Khách hàng" where "mã" = "mã"', self.sample, Store())
        self.assertEqual(result['em'], 1)

    def test_different_qualified_unicode_columns_do_not_collapse(self):
        schema = {'Khách hàng': Store().schema('b')['Khách hàng'],
                  'Nhà cung cấp': Store().schema('b')['Khách hàng']}
        a = parse_structural('select a."mã" from "Khách hàng" a join "Nhà cung cấp" b on a."mã" = b."mã"', schema)
        b = parse_structural('select b."mã" from "Khách hàng" a join "Nhà cung cấp" b on a."mã" = b."mã"', schema)
        self.assertNotEqual(a['select'], b['select'])

    def test_failed_generation_with_none_sql_does_not_crash_evaluator(self):
        result = evaluate_prediction(None, self.sample, Store(self.path))
        self.assertEqual(result['em'], 0)
        self.assertEqual(result['ex'], 0)

    def test_double_quoted_literal_not_column_in_out_of_scope_table(self):
        class ScopedStore(Store):
            def schema(self, db_id):
                return {**super().schema(db_id), 'Khác': {'columns': [{'name': 'R', 'type': 'TEXT'}], 'foreign_keys': []}}
        self.sample['gold_sql'] = 'select mã from Khách hàng where tên = "R"'
        result = evaluate_prediction('select "mã" from "Khách hàng" where "tên" = \'R\'', self.sample, ScopedStore())
        self.assertEqual(result['em'], 1)

    def test_unclosed_quote_is_not_silently_removed(self):
        result = evaluate_prediction('select "mã from Khách hàng', self.sample, Store())
        self.assertEqual(result['em'], 0)
        self.assertFalse(result['syntax_valid'])

    def test_subtraction_and_negative_literals_have_distinct_tokens(self):
        self.sample['gold_sql'] = 'select mã - mã from Khách hàng where mã > - 2'
        result = evaluate_prediction('select "mã"-"mã" from "Khách hàng" where "mã">-2', self.sample, Store())
        self.assertEqual(result['em'], 1)

    def test_quoted_multiword_aliases_preserve_qualified_columns(self):
        result = evaluate_prediction('select "bảng khách"."mã" from "Khách hàng" AS "bảng khách"', self.sample, Store())
        self.assertEqual(result['em'], 1)
        result = evaluate_prediction('select "bảng khách"."mã" from "Khách hàng" "bảng khách"', self.sample, Store())
        self.assertEqual(result['em'], 1)

    def _optional_store(self, with_suite=False, repeats=None):
        from test_experiment_data import fixture
        from text2sql_demo.experiment.dataset import DatasetStore
        root = Path(self.tmp.name) / 'dataset'
        root.mkdir()
        fixture(root)
        databases = root / 'database'
        databases.mkdir()
        path = databases / 'b.sqlite'
        with sqlite3.connect(path) as con:
            con.execute('create table "Khách hàng"("mã" integer, "tên" text)')
            con.executemany('insert into "Khách hàng" values (?,?)', [(1, 'a'), (2, 'b')])
        con.close()
        store = DatasetStore(root)
        if repeats is not None:
            (root / 'evaluation-options.json').write_text(json.dumps({'ves_repeats': repeats}), encoding='utf-8')
        if with_suite:
            files = []
            for index, values in enumerate(([(1, 'a'), (2, 'b')], [(1, 'a'), (2, 'b'), (20, 'c')])):
                suite = root / ('state' + str(index) + '.sqlite')
                with sqlite3.connect(suite) as con:
                    con.execute('create table "Khách hàng"("mã" integer, "tên" text)')
                    con.executemany('insert into "Khách hàng" values (?,?)', values)
                con.close()
                files.append({'db_id': 'b', 'path': suite.name, 'sha256': hashlib.sha256(suite.read_bytes()).hexdigest()})
            (root / 'test-suite-manifest.json').write_text(json.dumps({'version': 1,
                'dataset_fingerprint': store.summary()['fingerprint'],
                'provenance': {'source': 'local test fixture', 'description': 'Two deliberately different states'},
                'files': files}), encoding='utf-8')
        return DatasetStore(root)

    def test_test_suite_finds_accidental_single_database_equality(self):
        store = self._optional_store(with_suite=True)
        sample = {'db_id': 'b', 'gold_sql': 'select mã from Khách hàng'}
        result = evaluate_prediction('select mã from Khách hàng where mã < 10', sample, store)
        self.assertEqual(result['ex'], 1)
        self.assertEqual(result['ts'], 0)
        self.assertEqual(result['ts_details']['validated_states'], 2)
        good = evaluate_prediction(sample['gold_sql'], sample, store)
        self.assertEqual(good['ts'], 1)

    def test_test_suite_rejects_path_escape_hash_and_missing_provenance(self):
        store = self._optional_store(with_suite=True)
        manifest_path = store.root / 'test-suite-manifest.json'
        original = json.loads(manifest_path.read_text(encoding='utf-8'))
        from text2sql_demo.experiment.dataset import DatasetStore
        for mutation in ('path', 'hash', 'provenance', 'fingerprint', 'single_state'):
            manifest = json.loads(json.dumps(original))
            if mutation == 'path':
                manifest['files'][0]['path'] = '../b.sqlite'
            elif mutation == 'hash':
                manifest['files'][0]['sha256'] = '0' * 64
            elif mutation == 'provenance':
                manifest.pop('provenance')
            elif mutation == 'fingerprint':
                manifest['dataset_fingerprint'] = 'wrong'
            else:
                manifest['files'] = manifest['files'][:1]
            manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
            with self.subTest(mutation=mutation):
                result = evaluate_prediction('select mã from Khách hàng', self.sample, DatasetStore(store.root))
                self.assertIsNone(result['ts'])
                self.assertIn('ts', result['unavailable_reasons'])

    def test_ves_requires_explicit_repetition_budget_and_correct_execution(self):
        store = self._optional_store(repeats=100)
        sample = {'db_id': 'b', 'gold_sql': 'select mã from Khách hàng'}
        good = evaluate_prediction(sample['gold_sql'], sample, store)
        self.assertGreater(good['ves'], 0)
        self.assertEqual(good['ves_details']['completed_pairs'], 100)
        self.assertEqual(good['ves_details']['sql_executions'], 200)
        wrong = evaluate_prediction('select mã from Khách hàng where mã = 1', sample, store)
        self.assertEqual(wrong['ex'], 0)
        self.assertEqual(wrong['ves'], 0)

    def test_ves_under_100_repetitions_has_no_score(self):
        store = self._optional_store(repeats=99)
        result = evaluate_prediction(self.sample['gold_sql'], self.sample, store)
        self.assertIsNone(result['ves'])
        self.assertIn('ves', result['unavailable_reasons'])

    def test_ves_expired_total_budget_does_not_report_partial_score(self):
        store = self._optional_store(repeats=100)
        (store.root / 'evaluation-options.json').write_text(json.dumps({'ves_repeats': 100, 'ves_budget_s': 1e-12}), encoding='utf-8')
        from text2sql_demo.experiment.dataset import DatasetStore
        result = evaluate_prediction(self.sample['gold_sql'], self.sample, DatasetStore(store.root))
        self.assertIsNone(result['ves'])
        self.assertEqual(result['ves_details']['completed_pairs'], 0)
        self.assertIn('budget', result['unavailable_reasons']['ves'])

    def test_test_suite_rejects_metadata_distinct_but_identical_data(self):
        store = self._optional_store(with_suite=True)
        first = store.root / 'state0.sqlite'
        second = store.root / 'state1.sqlite'
        second.write_bytes(first.read_bytes())
        with sqlite3.connect(second) as con:
            con.execute('pragma user_version=12')
        con.close()
        manifest_path = store.root / 'test-suite-manifest.json'
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        manifest['files'][1]['sha256'] = hashlib.sha256(second.read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
        from text2sql_demo.experiment.dataset import DatasetStore
        result = evaluate_prediction(self.sample['gold_sql'], self.sample, DatasetStore(store.root))
        self.assertIsNone(result['ts'])
        self.assertIn('distinct data states', result['unavailable_reasons']['ts'])

    def test_test_suite_missing_schema_or_changed_snapshot_is_unavailable(self):
        store = self._optional_store(with_suite=True)
        with sqlite3.connect(store.root / 'state1.sqlite') as con:
            con.execute('drop table "Khách hàng"')
        con.close()
        result = evaluate_prediction(self.sample['gold_sql'], self.sample, store)
        self.assertIsNone(result['ts'])
        self.assertIn('snapshot', result['unavailable_reasons']['ts'])
        manifest_path = store.root / 'test-suite-manifest.json'
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        manifest['files'][1]['sha256'] = hashlib.sha256((store.root / 'state1.sqlite').read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
        from text2sql_demo.experiment.dataset import DatasetStore
        result = evaluate_prediction(self.sample['gold_sql'], self.sample, DatasetStore(store.root))
        self.assertIsNone(result['ts'])
        self.assertIn('schema', result['unavailable_reasons']['ts'])
