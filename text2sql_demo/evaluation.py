"""Tiny synthetic-data smoke comparator; not an official benchmark evaluator."""
from collections import Counter


def compare_rows(predicted, expected, ordered=False):
    if ordered:
        return predicted==expected
    return Counter(map(tuple,predicted))==Counter(map(tuple,expected))
