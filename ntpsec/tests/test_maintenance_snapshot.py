#!/usr/bin/python3
"""Offline boundaries and real native-parser/owned-cleanup qualification."""
import importlib.util
import json
import os
import subprocess
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


worker = load('maintenance', ROOT/'scripts/maintenance-snapshot.py')
worker.h = load('helper', ROOT/'scripts/run-production-inspection.py')
runner = load('runner', ROOT/'scripts/review-maintenance-snapshot.py')


class MaintenanceTests(unittest.TestCase):
    def test_redaction(self):
        text = 'URIs: https://user:pass@host/repo\npassword="value"\nSuites: trixie\n'
        result = worker.scrub(text)
        self.assertNotIn('user:pass', result)
        self.assertNotIn('value', result)
        self.assertIn('Suites: trixie', result)

    def test_closed_selection_excludes_auth(self):
        self.assertFalse(any('auth.conf' in p or 'msmtp' in p or '.ssh' in p for p in worker.FILES))
        self.assertEqual(len(worker.RULE_DIRS), 4)
        self.assertNotIn('/etc', worker.CONFIG_DIRS)

    def test_native_parser_and_cleanup(self):
        self.assertTrue(Path('/usr/bin/udevadm').is_file(), 'native udevadm required for qualification')
        with tempfile.TemporaryDirectory() as directory:
            stage = Path(directory)/'stage'
            result = worker.native_verify(stage, b'GOTO="missing"\n', b'ACTION=="add", ENV{MAINTENANCE_TEST}="1"\n')
            self.assertEqual(result['baseline.rules']['returncode'], 1)
            self.assertEqual(result['candidate.rules']['returncode'], 0)
            self.assertTrue(result['cleaned'])
            self.assertFalse(stage.exists())

    def test_preexisting_stage_never_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            stage = Path(directory)/'stage'; stage.mkdir()
            keep = stage/'keep'; keep.write_text('keep')
            result = worker.native_verify(stage, b'a', b'b')
            self.assertFalse(result['created'])
            self.assertEqual(keep.read_text(), 'keep')

    def test_interruption_cleans_only_created_files(self):
        def interrupt(*_):
            raise KeyboardInterrupt()
        with tempfile.TemporaryDirectory() as directory:
            stage = Path(directory)/'stage'
            result = worker.native_verify(stage, b'a', b'b', interrupt)
            self.assertTrue(result['cleaned'])
            self.assertIn('KeyboardInterrupt', result['error'])

    def test_changed_membership_not_recursively_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            stage = Path(directory)/'stage'
            def intrusion(*_):
                (stage/'unrelated').write_text('preserve')
                raise RuntimeError('interrupt')
            result = worker.native_verify(stage, b'a', b'b', intrusion)
            self.assertFalse(result['cleaned'])
            self.assertEqual((stage/'unrelated').read_text(), 'preserve')
            self.assertIn('cleanup_error', result)

    def test_symlink_stage_parent_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            link = Path(directory)/'link'; link.symlink_to(directory)
            with self.assertRaisesRegex(ValueError, 'unsafe scratch'):
                worker.native_verify(link/'stage', b'a', b'b')

    def test_failed_command_retained(self):
        report = {}
        with self.assertRaisesRegex(ValueError, 'command failed'):
            worker.query(report, 'failure', ['/usr/bin/false'])
        self.assertEqual(report['failure']['returncode'], 1)

    def test_identity_rejection_retains_partial_report(self):
        with patch.object(worker.os, 'geteuid', return_value=1000):
            result = worker.collect({'operation_id':'offline-only'}, b'a', b'b')
        self.assertFalse(result['capture_complete'])
        self.assertIn('identity drift', result['error'])
        json.dumps(result)

    def test_partial_report_json_paths(self):
        # Prevent recurrence of the Path-key serialization failure in the prior inspection.
        json.dumps(worker.lock_state())

    def test_receipt_prevents_second_submission(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'execution.json'
            runner.create(path, {'attempt': 1})
            with self.assertRaises(FileExistsError):
                runner.create(path, {'attempt': 2})
            self.assertEqual(json.loads(path.read_text())['attempt'], 1)

    def test_wrong_digest_stops_before_transport(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory)
            runner.create(p/'inspection.tar', b'not an archive')
            with patch.object(runner, 'ssh', side_effect=AssertionError('target contact')):
                with self.assertRaisesRegex(ValueError, 'archive digest'):
                    runner.inspect(p, '0'*64)
            self.assertFalse((p/'execution.json').exists())

    def test_real_authentication_and_strict_transport(self):
        with tempfile.TemporaryDirectory() as directory:
            key = Path(directory)/'key'
            subprocess.run(['/usr/bin/ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(key)], check=True)
            auth = runner.authentication(key)
            self.assertEqual(auth['agent'], 'none')
            self.assertTrue(auth['public_fingerprint'].startswith('SHA256:'))
            argv = runner.ssh(Path(directory), {'authentication': auth})
            self.assertIn('StrictHostKeyChecking=yes', argv)
            self.assertIn('IdentityAgent=none', argv)
            self.assertIn(str(key), argv)

    def test_payload_compiles_and_has_no_dispatch(self):
        files = {n:p.read_bytes() for n,p in runner.SOURCES.items()}
        files.update({'baseline.rules': b'a', 'candidate.rules': b'b'})
        payload = runner.payload({'operation_id':'offline'}, files)
        compile(payload, '<sealed-payload>', 'exec')
        self.assertNotIn(b'w.entry(', payload)
        self.assertNotIn(b'import common', payload)
        result = worker.h.bounded(['/usr/bin/python3', '-I', '-B', '-c', payload.decode()], timeout=10)
        self.assertEqual(result['returncode'], 0, result['stderr'])
        self.assertFalse(json.loads(result['stdout'])['capture_complete'])


if __name__ == '__main__':
    unittest.main()
