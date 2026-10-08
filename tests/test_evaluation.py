import unittest
from text2sql_demo.evaluation import compare_rows


class EvaluationTests(unittest.TestCase):
    def test_unordered_comparison_ignores_order(self):
        self.assertTrue(compare_rows([['a',1],['b',2]],[['b',2],['a',1]],ordered=False))

    def test_unordered_comparison_preserves_duplicate_rows(self):
        self.assertFalse(compare_rows([['a'],['a']],[['a']],ordered=False))

    def test_ranked_rows_preserve_order(self):
        self.assertFalse(compare_rows([['a',3],['b',2]],[['b',2],['a',3]],ordered=True))
