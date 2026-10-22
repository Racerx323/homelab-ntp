#!/usr/bin/python3
"""Offline selection parser and preflight rejection checks."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
s = importlib.util.spec_from_file_location('selection', ROOT/'scripts/inspect-munin-ntp-selection.py')
r = importlib.util.module_from_spec(s); s.loader.exec_module(r)


class Tests(unittest.TestCase):
    def test_selected_id_is_numeric_and_unique(self):
        self.assertEqual(r.selected_id('leap=00, peer=12345, refid=PPS'), 12345)
        for raw in ('peer=0', 'peer=65536', 'peer=1, peer=2', 'peer=abc', 'xpeer=4'):
            with self.assertRaises(ValueError):r.selected_id(raw)

    def test_unit_properties_are_distinct(self):
        self.assertEqual(r.fields({'returncode': 0, 'stdout': 'ActiveState=inactive\n'}), {'ActiveState': 'inactive'})
        for row in ({'returncode': 1}, {'returncode': 0, 'stdout': 'x=1\nx=2'}, {'returncode': 0, 'stdout': 'bad'}):
            with self.assertRaises(ValueError):r.fields(row)

    def test_root_guard_precedes_commands(self):
        with patch.object(r.os, 'geteuid', return_value=1000), patch.object(r, 'command') as cmd:
            with self.assertRaises(ValueError):r.collect({'hostname': 'node'})
        cmd.assert_not_called()

    def test_command_does_not_use_shell_or_mutation(self):
        source = Path(r.__file__).read_text()
        self.assertNotIn('shell=True', source)
        self.assertNotIn('write_text(', source)
        self.assertNotIn("'start'", source)
        self.assertNotIn("'restart'", source)


if __name__ == '__main__':unittest.main()
