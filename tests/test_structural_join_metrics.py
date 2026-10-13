import unittest

from text2sql_demo.experiment.evaluation import evaluate_prediction, _normalize_inner_joins


class ArchitectureStore:
    def schema(self, db_id):
        return {
            'kiến trúc sư': {'columns': [
                {'name': 'id', 'type': 'INTEGER', 'pk': True},
                {'name': 'tên', 'type': 'TEXT'}], 'foreign_keys': []},
            'cầu': {'columns': [
                {'name': 'id', 'type': 'INTEGER', 'pk': True},
                {'name': 'id kiến trúc sư', 'type': 'INTEGER'}],
                'foreign_keys': [{'from': 'id kiến trúc sư',
                                  'table': 'kiến trúc sư', 'to': 'id'}]},
        }

    def database_path(self, db_id):
        return None


class PlainJoinStore(ArchitectureStore):
    def schema(self, db_id):
        return {name: {'columns': [{'name': 'id', 'type': 'INTEGER'}],
                       'foreign_keys': []} for name in ('a', 'b')}


class StructuralJoinMetricTests(unittest.TestCase):
    gold = ('select t1."id", t1."tên" from "kiến trúc sư" as t1 '
            'join "cầu" as t2 on t1."id" = t2."id kiến trúc sư" '
            'group by t1."id" having count(*) >= 3')
    base = ('SELECT T1.id, T1.tên FROM kiến trúc sư AS T1 '
            'INNER JOIN cầu AS T2 ON T1.id = T2.id kiến trúc sư '
            'GROUP BY T1.id HAVING COUNT(T2.id) >= 3')

    def score(self, sql, gold=None):
        return evaluate_prediction(sql, {'db_id': 'architecture',
                                         'gold_sql': gold or self.gold}, ArchitectureStore())

    def test_inner_join_matches_join_regardless_of_case_quotes_and_alias_style(self):
        query = self.base.replace('COUNT(T2.id)', 'COUNT(*)')
        for sql in (query, query.lower(), query.replace('INNER JOIN', 'InNeR\nJoIn'),
                    query.replace(' AS ', ' ')):
            with self.subTest(sql=sql):
                result = self.score(sql)
                self.assertTrue(result['syntax_valid'])
                self.assertEqual(result['em'], 1)
                self.assertEqual(result['cm'], 1)
                self.assertTrue(result['cm_components'])

    def test_inner_join_in_gold_is_supported_too(self):
        result = self.score(self.gold, self.gold.replace('join ', 'inner join '))
        self.assertEqual(result['em'], 1)
        self.assertEqual(result['cm'], 1)

    def test_screenshot_count_difference_retains_partial_component_credit(self):
        result = self.score(self.base)
        self.assertEqual(result['em'], 0)
        self.assertAlmostEqual(result['cm'], 5 / 6)
        self.assertEqual(result['cm_components']['select']['f1'], 1)
        self.assertEqual(result['cm_components']['group']['f1'], 0)
        self.assertNotIn('structural_prediction', result['unavailable_reasons'])

    def test_chained_inner_joins_match_plain_joins(self):
        query = ('select a.id from "kiến trúc sư" a '
                 'inner join "cầu" b on a.id = b."id kiến trúc sư" '
                 'inner join "cầu" c on a.id = c."id kiến trúc sư"')
        result = self.score(query, query.replace('inner join', 'join'))
        self.assertEqual(result['em'], 1)
        self.assertEqual(result['cm'], 1)

    def test_valid_unsupported_prediction_is_unavailable_not_zero(self):
        queries = [self.gold.replace('join ', 'left join '),
                   'with x as (select id from "kiến trúc sư") select id from x']
        for query in queries:
            with self.subTest(query=query):
                result = self.score(query)
                self.assertTrue(result['syntax_valid'])
                self.assertIsNone(result['em'])
                self.assertIsNone(result['cm'])
                self.assertEqual(result['cm_components'], {})
                for metric in ('em', 'cm'):
                    self.assertIn('unsupported', result['unavailable_reasons'][metric].lower())

    def test_unsupported_gold_remains_unavailable(self):
        result = self.score(self.gold, self.gold.replace('join ', 'left join '))
        self.assertIsNone(result['em'])
        self.assertIsNone(result['cm'])
        self.assertIn('em', result['unavailable_reasons'])

    def test_join_modifiers_are_not_mistaken_for_implicit_aliases(self):
        gold = 'select a.id from a join b'
        for join in ('left join', 'left outer join', 'cross join',
                     'natural join', 'natural inner join'):
            with self.subTest(join=join):
                result = evaluate_prediction(gold.replace('join ', join + ' '),
                                             {'db_id': 'x', 'gold_sql': gold}, PlainJoinStore())
                self.assertTrue(result['syntax_valid'])
                self.assertIsNone(result['em'])
                self.assertIsNone(result['cm'])

    def test_explicit_inner_alias_is_preserved(self):
        gold = 'select x.id from a as x join b on x.id = b.id'
        for sql in ('select inner.id from a as inner join b on inner.id = b.id',
                    'select inner.id from a AS\nINNER INNER JOIN b on inner.id = b.id'):
            with self.subTest(sql=sql):
                result = evaluate_prediction(sql, {'db_id': 'x', 'gold_sql': gold}, PlainJoinStore())
                self.assertTrue(result['syntax_valid'])
                self.assertEqual(result['em'], 1)
                self.assertEqual(result['cm'], 1)

    def test_invalid_prediction_still_receives_zero(self):
        result = self.score('select missing_column from "kiến trúc sư"')
        self.assertFalse(result['syntax_valid'])
        self.assertEqual(result['em'], 0)
        self.assertEqual(result['cm'], 0)

    def test_join_normalization_preserves_literals_identifiers_and_comments(self):
        protected = ("'inner join'", "'it''s INNER JOIN'", '"inner join"',
                     '`inner join`', '[inner join]', '-- INNER JOIN\n',
                     '/* INNER JOIN */')
        for fragment in protected:
            with self.subTest(fragment=fragment):
                self.assertEqual(_normalize_inner_joins(fragment), fragment)
        for join in ('left join', 'left outer join', 'right join', 'cross join',
                     'natural join', 'full outer join'):
            with self.subTest(join=join):
                self.assertEqual(_normalize_inner_joins(join), join)


if __name__ == '__main__':
    unittest.main()
