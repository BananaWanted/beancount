"""
Tests for general utils.
"""
import unittest
import time
from collections import namedtuple
import operator

from beancount.utils import misc_utils


class TestMiscUtils(unittest.TestCase):

    def test_print_time(self):
        with misc_utils.print_time('test-op'):
            time.sleep(0.1)

    def test_groupby(self):
        data = [('a', 1), ('b', 2), ('c', 3), ('d', 4)]
        grouped = misc_utils.groupby(lambda x: x[0], data)
        self.assertEqual(set(['a', 'b', 'c', 'd']), grouped.keys())
        self.assertEqual(
            [[('a', 1)], [('b', 2)], [('c', 3)], [('d', 4)]],
            sorted(grouped.values()))

    def test_uniquify_last(self):
        data = [('d', 9),
                ('b', 4),
                ('c', 8),
                ('c', 6),
                ('c', 7),
                ('a', 3),
                ('a', 1),
                ('a', 2),
                ('b', 5)]
        unique_data = misc_utils.uniquify_last(data, lambda x: x[0])
        self.assertEqual([('a', 2), ('b', 5), ('c', 7), ('d', 9)],
                         list(unique_data))

    def test_filter_type(self):
        class A: pass
        class B: pass
        class C: pass
        data = [x() for x in [A, B, A, A, C, B, C, A]]
        self.assertEqual([A, A, A, A],
                         list(map(type, misc_utils.filter_type(data, A))))

    def test_longest(self):
        data = [(1,), (2, 3, 4, 5), (2, 3)]
        self.assertEqual((2, 3, 4, 5), misc_utils.longest(data))

    def test_get_tuple_values(self):
        Something = namedtuple('Something', 'a b c d e')
        SomethingElse = namedtuple('SomethingElse', 'f g h')
        class A(str): pass
        ntuple = Something(1, 2, SomethingElse(A('a'), None, 2), [A('b'), 'c'], 5)
        x = misc_utils.get_tuple_values(ntuple, lambda x: isinstance(x, A))
        self.assertEqual([A('a'), A('b')], list(x))

    def test_index_key(self):
        objects = [object() for _ in range(10)]
        index = misc_utils.index_key(objects, objects[4], lambda x: x, operator.is_)
        self.assertEqual(4, index)

    def test_compute_unique_clean_ids(self):
        self.assertEqual({'a': 'a', 'b': 'b', 'c': 'c'},
                         misc_utils.compute_unique_clean_ids(['a', 'b', 'c']))

        self.assertEqual({'a-b': 'a-b', 'a_b': 'a b'},
                         misc_utils.compute_unique_clean_ids(['a b', 'a-b']))

        self.assertEqual({'a_b': 'a_b', 'ab': 'a b'},
                         misc_utils.compute_unique_clean_ids(['a b', 'a_b']))

    def test_map_namedtuple_attributes(self):
        Test = namedtuple('Test', 'a b c d')
        test = Test(None, None, 1, 2)
        new_test = misc_utils.map_namedtuple_attributes(
            ('b', 'd'), lambda num: num if num is None else num * 10, test)
        self.assertEqual(Test(None, None, 1, 20), new_test)
