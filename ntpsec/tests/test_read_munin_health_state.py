#!/usr/bin/python3
"""Focused retained-output selection and read-only guard checks."""
import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('retained_health', ROOT/'scripts/read-munin-health-state.py')
r = importlib.util.module_from_spec(spec); spec.loader.exec_module(r)


class Tests(unittest.TestCase):
    def test_only_retained_health_rows_are_returned(self):
        row = {'argv': ['/usr/sbin/munin-run', 'ntp_health'], 'returncode': 0,
               'stdout': 'query_ok.value 0\nsynced.value U\n', 'stderr': ''}
        state = {'spec_sha256': 'digest', 'commands': [row,
                 {'argv': ['other'], 'stdout': 'UNRELATED PRIVATE OUTPUT'}]}
        self.assertEqual(r.health_rows(state, 'digest'), [row])

    def test_wrong_digest_and_oversize_fail(self):
        with self.assertRaises(ValueError):r.health_rows({'spec_sha256': 'wrong'}, 'digest')
        row = {'argv': ['/usr/sbin/munin-run', 'ntp_health'], 'returncode': 0,
               'stdout': 'x'*65537, 'stderr': ''}
        with self.assertRaises(ValueError):r.health_rows({'spec_sha256': 'digest', 'commands': [row]}, 'digest')

    def test_root_guard_precedes_state_access(self):
        with patch.object(r.os, 'geteuid', return_value=1000), patch.object(r.os, 'open') as opened:
            with self.assertRaises(ValueError):r.collect({'hostname': 'node'})
        opened.assert_not_called()

    def test_collector_has_no_subprocess_or_write_operation(self):
        source = Path(r.__file__).read_text()
        self.assertNotIn('subprocess', source)
        self.assertNotIn('O_WRONLY', source)
        self.assertNotIn('write_text', source)


if __name__ == '__main__':unittest.main()
