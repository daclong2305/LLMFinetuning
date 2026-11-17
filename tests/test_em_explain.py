import unittest

from text2sql_demo.experiment.evaluation import explain_structural

SCHEMA = {
    'kiến trúc sư': {'columns': [
        {'name': 'id', 'type': 'INTEGER', 'pk': True},
        {'name': 'tên', 'type': 'TEXT'},
        {'name': 'quốc tịch', 'type': 'TEXT'}], 'foreign_keys': []},
    'cầu': {'columns': [
        {'name': 'id', 'type': 'INTEGER', 'pk': True},
        {'name': 'id kiến trúc sư', 'type': 'INTEGER'}],
        'foreign_keys': [{'from': 'id kiến trúc sư', 'table': 'kiến trúc sư', 'to': 'id'}]},
}
GOLD = ('select t1.tên from kiến trúc sư as t1 join cầu as t2 on t1.id = t2.id kiến trúc sư '
        "where t1.quốc tịch = 'Mỹ' group by t1.id order by count ( * ) desc limit 1")


class ExplainStructuralTests(unittest.TestCase):
    def test_components_are_readable_and_values_dropped(self):
        out = explain_structural(GOLD, GOLD, SCHEMA)
        self.assertEqual(out['em'], 1)
        gold = out['gold']
        self.assertEqual(gold['tables'], ['cầu', 'kiến trúc sư'])
        self.assertEqual(gold['components']['select'], ['kiến trúc sư.tên'])
        self.assertEqual(gold['components']['where'], ['kiến trúc sư.quốc tịch = ?'])
        self.assertEqual(gold['components']['where(no OP)'], ['kiến trúc sư.quốc tịch'])
        # FK equivalence: t2."id kiến trúc sư" would map to kiến trúc sư.id
        self.assertEqual(gold['components']['group(no Having)'], ['kiến trúc sư.id'])
        self.assertEqual(gold['components']['order'], ['DESC count(*)', 'LIMIT'])
        self.assertEqual(gold['components']['keywords'], ['desc', 'group', 'limit', 'order', 'where'])
        self.assertTrue(all(row['match'] for row in out['comparison']))
        self.assertIn('u0', gold['canonical_sql'])
        self.assertEqual(gold['tokens']['u0'], 'kiến trúc sư')
        self.assertNotIn('u99', gold['tokens'])

    def test_mismatch_lists_failed_component(self):
        pred = ('SELECT k."tên" FROM "kiến trúc sư" k JOIN "cầu" c ON k."id" = c."id kiến trúc sư" '
                "WHERE k.\"quốc tịch\" = 'Pháp' GROUP BY k.\"id\" ORDER BY COUNT(c.\"id\") DESC LIMIT 1")
        out = explain_structural(pred, GOLD, SCHEMA)
        self.assertEqual(out['em'], 0)
        order = next(row for row in out['comparison'] if row['key'] == 'order')
        self.assertFalse(order['match'])
        self.assertEqual(out['pred']['components']['order'], ['DESC count(cầu.id)', 'LIMIT'])
        where = next(row for row in out['comparison'] if row['key'] == 'where')
        self.assertTrue(where['match'])  # literal 'Pháp' vs 'Mỹ' is ignored

    def test_unparseable_prediction_reports_error(self):
        out = explain_structural('SELECT FROM', GOLD, SCHEMA)
        self.assertIsNone(out['pred']['components'])
        self.assertTrue(out['pred']['error'])
        self.assertIsNone(out['em'])
        self.assertEqual(out['gold']['components']['select'], ['kiến trúc sư.tên'])


if __name__ == '__main__':
    unittest.main()


class StubStore:
    samples = {
        'dev:1': {'id': 'dev:1', 'split': 'dev', 'db_id': 'arch', 'question': 'Q', 'gold_sql': GOLD, 'difficulty': 'easy'},
        'test:1': {'id': 'test:1', 'split': 'test', 'db_id': 'arch', 'question': 'Q', 'gold_sql': GOLD, 'difficulty': 'easy'},
    }

    def get_sample(self, sample_id):
        return dict(self.samples[sample_id])

    def schema(self, db_id):
        return SCHEMA

    def database_path(self, db_id):
        return None


class EmExplainRouteTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from text2sql_demo.experiment.service import ExperimentService
        self.temp = tempfile.TemporaryDirectory()
        config = {'dataset_root': self.temp.name + '/missing', 'database_dir': self.temp.name + '/db',
                  'runs_dir': self.temp.name + '/runs', 'models': [], 'presets': []}
        self.service = ExperimentService(self.temp.name, config)
        self.service.store = StubStore()

    def tearDown(self):
        self.temp.cleanup()

    def test_returns_gold_and_components_for_dev_sample(self):
        data, status = self.service.post('/api/experiment/metric-explain', {'sample_id': 'dev:1', 'sql': GOLD, 'metric': 'em'})
        self.assertEqual(status, 200)
        self.assertEqual(data['metric'], 'em')
        self.assertEqual((data['gold_sql'], data['pred_sql'], data['db_id']), (GOLD, GOLD, 'arch'))
        ex, status = self.service.post('/api/experiment/metric-explain', {'sample_id': 'dev:1', 'sql': GOLD, 'metric': 'ex'})
        self.assertEqual((status, ex['metric'], ex['available']), (200, 'ex', False))
        self.assertEqual(data['gold']['sql'], GOLD)
        self.assertEqual(data['em'], 1)
        self.assertEqual(data['sample_id'], 'dev:1')

    def test_test_split_and_bad_sql_are_rejected(self):
        with self.assertRaises(ValueError):
            self.service.post('/api/experiment/metric-explain', {'sample_id': 'test:1', 'sql': GOLD})
        with self.assertRaises(ValueError):
            self.service.post('/api/experiment/metric-explain', {'sample_id': 'dev:1', 'sql': 42})
        with self.assertRaises(ValueError):
            self.service.post('/api/experiment/metric-explain', {'sample_id': 'dev:1', 'sql': GOLD, 'metric': 'bogus'})
