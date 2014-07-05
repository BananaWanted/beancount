import unittest
import tempfile

from beancount import loader
from beancount.parser import parser
from beancount.utils import test_utils


TEST_INPUT = """

2014-01-01 open Assets:MyBank:Checking   USD
2014-01-01 open Expenses:Restaurant   USD

2014-02-22 * "Something happened."
  Assets:MyBank:Checking       100.00 USD
  Expenses:Restaurant

2015-01-01 close Assets:MyBank:Checking
2015-01-01 close Expenses:Restaurant

"""


class TestLoader(unittest.TestCase):

    def test_run_transformations(self):
        # Test success case.
        entries, errors, options_map = parser.parse_string(TEST_INPUT)
        trans_entries, trans_errors = loader.run_transformations(
            entries, errors, options_map, None)
        self.assertEqual(0, len(trans_errors))

        # Test an invalid plugin name.
        entries, errors, options_map = parser.parse_string(
            'option "plugin" "invalid.module.name"\n\n' + TEST_INPUT)
        trans_entries, trans_errors = loader.run_transformations(
            entries, errors, options_map, None)
        self.assertEqual(1, len(trans_errors))

    def test_load(self):
        with test_utils.capture():
            with tempfile.NamedTemporaryFile('w') as f:
                f.write(TEST_INPUT)
                f.flush()
                entries, errors, options_map = loader.load(f.name)
                self.assertTrue(isinstance(entries, list))
                self.assertTrue(isinstance(errors, list))
                self.assertTrue(isinstance(options_map, dict))

                entries, errors, options_map = loader.load(f.name, log_function=print)
                self.assertTrue(isinstance(entries, list))
                self.assertTrue(isinstance(errors, list))
                self.assertTrue(isinstance(options_map, dict))

    def test_load_string(self):
        with test_utils.capture():
            entries, errors, options_map = loader.load_string(TEST_INPUT)
            self.assertTrue(isinstance(entries, list))
            self.assertTrue(isinstance(errors, list))
            self.assertTrue(isinstance(options_map, dict))

            entries, errors, options_map = loader.load_string(TEST_INPUT, log_function=print)
            self.assertTrue(isinstance(entries, list))
            self.assertTrue(isinstance(errors, list))
            self.assertTrue(isinstance(options_map, dict))


class TestLoadDoc(unittest.TestCase):

    def test_loaddoc(self):
        def test_function(self_, entries, errors, options_map):
            self.assertTrue(isinstance(entries, list))
            self.assertTrue(isinstance(errors, list))
            self.assertTrue(isinstance(options_map, dict))

        test_function.__doc__ = TEST_INPUT
        test_function = loader.loaddoc(test_function)
        test_function(self)

    @loader.loaddoc
    def test_loaddoc_empty(self, entries, errors, options_map):
        """
        """
        self.assertTrue(isinstance(entries, list))
        self.assertTrue(isinstance(errors, list))
        self.assertTrue(isinstance(options_map, dict))

    @loader.loaddoc
    def test_loaddoc_plugin(self, entries, errors, options_map):
        """
        option "plugin" "beancount.does.not.exist"
        """
        self.assertTrue(isinstance(entries, list))
        self.assertTrue(isinstance(options_map, dict))
        self.assertTrue([loader.LoadError], list(map(type, errors)))
