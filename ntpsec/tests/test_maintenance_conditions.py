#!/usr/bin/python3
"""Closed native condition parsing; no target or service access."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('conditions', Path(__file__).resolve().parents[1] /
                                            'scripts/check-maintenance-conditions.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class Conditions(unittest.TestCase):
    def test_inhibit_all_cached_states(self):
        for state in (-1, 0, 1):
            m.validate({'type': 'a(sbbsi)', 'data': [
                ['ConditionPathExists', False, True, m.MARKER, state]]}, True)

    def test_bad_or_missing_inhibit(self):
        for row in ([], ['ConditionPathExists', True, True, m.MARKER, 0],
                    ['ConditionPathExists', False, False, m.MARKER, 0],
                    ['ConditionPathExists', False, True, '/wrong', 0]):
            with self.assertRaises(ValueError):
                m.validate({'type': 'a(sbbsi)', 'data': [row] if row else []}, True)

    def test_duplicate_rejected(self):
        row = ['ConditionPathExists', False, True, m.MARKER, 0]
        with self.assertRaises(ValueError):
            m.validate({'type': 'a(sbbsi)', 'data': [row, row]}, True)

    def test_unknown_representation_rejected(self):
        for value in ('Conditions=[unprintable]', {}, {'type': 'as', 'data': []},
                      {'type': 'a(sbbsi)', 'data': [['ConditionPathExists', 0, True, m.MARKER, 0]]}):
            with self.assertRaises(ValueError):
                m.validate(value, True)

    def test_restored_and_foreign_conditions(self):
        m.validate({'type': 'a(sbbsi)', 'data': []}, False)
        m.validate({'type': 'a(sbbsi)', 'data': [
            ['ConditionDirectoryNotEmpty', False, False, '/sys/fs/pstore', 0]]}, False)
        with self.assertRaises(ValueError):
            m.validate({'type': 'a(sbbsi)', 'data': [
                ['ConditionPathExists', False, True, m.MARKER, 0]]}, False)


if __name__ == '__main__':
    unittest.main()
