#!/usr/bin/python3
"""Read-only snapshot transport boundaries and privileged identity rejection."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
import tempfile
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
definition = importlib.util.spec_from_file_location('snapshot', ROOT/'scripts/capture-foundation-snapshot.py')
s = importlib.util.module_from_spec(definition)
definition.loader.exec_module(s)


class Snapshot(unittest.TestCase):
    def probe(self, result):
        worker = SimpleNamespace(read=Mock(return_value=b'protected native executable'))
        inspection = SimpleNamespace(run=Mock(return_value=result))
        return s.Probe(worker, inspection), worker, inspection

    def test_native_success_records_digest_without_writing_or_executing_packages(self):
        probe, worker, inspection = self.probe({'rc': 0, 'stdout': 'observation',
            'stderr': '', 'error': None, 'truncated': False})
        self.assertEqual(probe.command(['/usr/bin/dpkg', '--audit'], 'fixture'), 'observation')
        self.assertEqual(len(probe.commands), 1)
        self.assertNotIn('stdout', probe.commands[0])
        worker.record('observation', {})
        inspection.run.assert_called_once()

    def test_errors_truncation_stderr_and_deadline_reject(self):
        original = {'rc': 0, 'stdout': 'observed', 'stderr': '', 'error': None, 'truncated': False}
        for field, value in (('rc', 2), ('stderr', 'warning'), ('error', 'timeout'), ('truncated', True)):
            probe, _, _ = self.probe(dict(original, **{field: value}))
            with self.subTest(field=field), self.assertRaises(ValueError):
                probe.command(['/usr/bin/dpkg', '--audit'], 'fixture')
            self.assertEqual(probe.commands, [])
        probe, _, inspection = self.probe(original)
        probe.deadline = 0
        with self.assertRaises(ValueError): probe.command(['/usr/bin/dpkg', '--audit'], 'fixture')
        inspection.run.assert_not_called()

    def test_mutations_and_sensitive_unit_properties_never_reach_native_runner(self):
        probe, _, inspection = self.probe({})
        for command in (['/usr/bin/apt-get', 'install', 'bc'], ['/usr/bin/systemctl', 'restart', 'ssh.service'],
                        ['/usr/bin/systemctl', 'show', '--property=Environment', 'ssh.service'],
                        ['/usr/sbin/ip', 'address', 'add', '192.0.2.1/24', 'dev', 'eth0']):
            with self.subTest(command=command), self.assertRaisesRegex(ValueError, 'read-only'):
                probe.command(command, 'rejected')
        inspection.run.assert_not_called()

    def test_identity_failure_precedes_any_recipe_read_or_helper_import(self):
        with patch.object(s.os, 'geteuid', return_value=1000), patch.object(s, 'module') as load:
            with self.assertRaises(ValueError):
                s.collect(Path('/never-read'), 'a'*64, 'fixture', 'kernel', 'fixture.example', 1)
            load.assert_not_called()

    def test_user_workspace_cannot_be_imported_for_privileged_preflight(self):
        # Tests run as the workspace owner; the target requires protected root staging.
        if (ROOT/'scripts/foundation-install.py').stat().st_uid == 0:
            self.skipTest('workspace is root-owned')
        with self.assertRaisesRegex(ValueError, 'unprotected'):
            s.module('foundation-install.py')

    def test_password_database_is_rejected_before_read(self):
        probe, worker, _ = self.probe({})
        with self.assertRaisesRegex(ValueError, 'password database'):
            probe.record('/var/cache/debconf/./passwords.dat')
        worker.read.assert_not_called()

    def test_absent_file_with_missing_parent_binds_existing_protected_ancestor(self):
        probe, worker, _ = self.probe({})
        worker.ancestors = Mock()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'not-installed/nested/input'
            self.assertEqual(probe.record(path), {'path': str(path), 'absent': True})
            worker.ancestors.assert_called_once_with(Path(directory))
            worker.read.assert_not_called()


if __name__ == '__main__':
    unittest.main()
