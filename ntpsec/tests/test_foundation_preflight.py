#!/usr/bin/python3
"""Offline sealed transport and protected staging lifecycle regression checks."""
import base64
import fcntl
import importlib.util
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]


def load(name, filename):
    definition = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / filename)
    result = importlib.util.module_from_spec(definition)
    definition.loader.exec_module(result)
    return result


s = load('preflight_stage', 'foundation-preflight-stage.py')
c = load('preflight_controller', 'run-foundation-preflight.py')


class Preflight(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.parent = Path(self.temp.name)
        os.chmod(self.parent, 0o700)
        self.known = self.parent / 'pinned'
        self.known.write_bytes(b'fixture.example ssh-ed25519 ' + base64.b64encode(b'fixture key') + b'\n')
        self.known.chmod(0o600)
        self.output = self.parent / 'sealed'
        self.sealed = c.seal(SimpleNamespace(hostname='fixture-node', kernel='fixture-v8',
            ssh_host='fixture.example', fingerprint=c.host_key(self.known.read_bytes(), 'fixture.example'),
            operation_id='fixture-one', known_hosts=self.known, output=self.output))
        self.bundle = Path(self.sealed['bundle'])
        self.spec, self.files = c.prepare(self.bundle, self.sealed['sha256'])

    def rewrite(self, transform):
        with tarfile.open(self.bundle) as archive:
            entries = {m.name: archive.extractfile(m).read() for m in archive.getmembers()}
        transform(entries)
        with tarfile.open(self.bundle, 'w', format=tarfile.USTAR_FORMAT) as archive:
            for name, data in entries.items():
                member = tarfile.TarInfo(name)
                member.mode, member.size = 0o600, len(data)
                archive.addfile(member, io.BytesIO(data))
        return c.sha(self.bundle.read_bytes())

    def test_seal_is_offline_and_all_modes_compile_with_strict_transport(self):
        self.assertFalse(self.sealed['target_contact'])
        self.assertEqual(set(self.spec['members']), s.INPUTS)
        for mode in ('collect', 'readback', 'cleanup'):
            compile(c.payload(self.spec, self.files, int(time.time()), mode), 'fixture', 'exec')
        argv = c.transport(self.output, 'fixture.example')
        self.assertIn('StrictHostKeyChecking=yes', argv)
        self.assertIn('ForwardAgent=no', argv)
        self.assertIn('ProxyCommand=none', argv)
        self.assertEqual(argv[-2:], ['ama@fixture.example', 'cd / && sudo -n /usr/bin/python3 -I -B -'])

    def test_archive_and_external_key_drift_reject_before_transport(self):
        with self.assertRaisesRegex(ValueError, 'bundle hash'):
            c.prepare(self.bundle, 'a' * 64)
        checksum = self.rewrite(lambda entries: entries.update({'../extra': b'unsafe'}))
        with self.assertRaisesRegex(ValueError, 'input set'):
            c.prepare(self.bundle, checksum)

    def test_member_manifest_and_external_key_are_both_enforced(self):
        self.output.joinpath('known_hosts').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'key binding'):
            c.prepare(self.bundle, self.sealed['sha256'])
        self.output.joinpath('known_hosts').write_bytes(self.known.read_bytes())
        checksum = self.rewrite(lambda entries: entries.update({'recipe.json': b'{}'}))
        with self.assertRaisesRegex(ValueError, 'member hash'):
            c.prepare(self.bundle, checksum)

    def test_expired_collection_and_unbound_cleanup_never_register_or_submit(self):
        arguments = SimpleNamespace(bundle=self.bundle, sha256=self.sealed['sha256'], mode='collect')
        with patch.object(c.time, 'time', return_value=self.spec['expires_epoch']), patch.object(c.subprocess, 'run') as run:
            with self.assertRaisesRegex(ValueError, 'expired'):
                c.execute(arguments)
            run.assert_not_called()
        arguments.mode = 'cleanup'
        with patch.object(c.subprocess, 'run') as run:
            with self.assertRaises(OSError):
                c.execute(arguments)
            run.assert_not_called()
        self.assertFalse((self.output / 'collect-execution.json').exists())

    def test_submission_is_registered_once_and_complete_held_logs_are_retained(self):
        args = SimpleNamespace(bundle=self.bundle, sha256=self.sealed['sha256'], mode='collect')
        def submitted(argv, **kwargs):
            self.assertTrue((self.output / 'collect-execution.json').exists())
            kwargs['stdout'].write(b'{"state":"snapshot_held","error":"observed drift"}\nPREFLIGHT_EXIT_STATUS=2\n')
            kwargs['stderr'].write(b'')
            return SimpleNamespace(returncode=2)
        with patch.dict(c.os.environ, {'SSH_AUTH_SOCK': '/fixture/agent'}), \
                patch.object(c.subprocess, 'run', side_effect=submitted) as run:
            result = c.execute(args)
            self.assertEqual(result['state'], 'snapshot_held')
            self.assertEqual(result['worker_status'], 2)
            self.assertTrue((self.output / 'collect-transport.json').exists())
            self.assertFalse((self.output / 'acceptance.json').exists())
            with self.assertRaises(FileExistsError):
                c.execute(args)
            run.assert_called_once()

    def fixture_stage(self):
        root = self.parent / 'stage'
        root.mkdir(mode=0o700)
        spec = dict(self.spec, stage=str(root))
        inputs = {n: self.files[n] for n in s.INPUTS}
        for name, data in {**inputs, 'spec.json': s.encoded(spec), 'lock': b''}.items():
            (root / name).write_bytes(data)
            (root / name).chmod(0o600)
        worker = SimpleNamespace(ancestors=Mock(), read=lambda p: p.read_bytes(),
                                 sync=Mock())
        claim = {'spec_sha256': s.sha(s.encoded(spec))}
        (root / 'claim.json').write_bytes(s.encoded(claim))
        terminal = {'state': 'snapshot_held', 'spec_sha256': claim['spec_sha256'], 'error': 'fixture'}
        (root / 'terminal.json').write_bytes(s.encoded(terminal))
        return root, spec, inputs, worker

    def test_readback_and_cleanup_use_terminal_without_recollecting(self):
        root, spec, inputs, worker = self.fixture_stage()
        with patch.object(s, 'identity'), patch.object(s.types, 'ModuleType', return_value=worker), patch('builtins.exec'):
            result = s.entry(spec, inputs, int(time.time()), 'readback')
            self.assertEqual(result['state'], 'snapshot_held')
            with self.assertRaisesRegex(ValueError, 'retained readback'):
                s.entry(spec, inputs, int(time.time()), 'cleanup', 'a' * 64)
            self.assertTrue(root.exists())
            cleaned = s.entry(spec, inputs, int(time.time()), 'cleanup', result['terminal_sha256'])
            self.assertEqual(cleaned['state'], 'snapshot_stage_removed')
            self.assertFalse(root.exists())

    def test_drift_unknown_entries_and_missing_receipts_hold_without_deleting(self):
        root, spec, inputs, worker = self.fixture_stage()
        with patch.object(s, 'identity'), patch.object(s.types, 'ModuleType', return_value=worker), patch('builtins.exec'):
            result = s.entry(spec, inputs, int(time.time()), 'readback')
            extra = root / 'unique-data'
            extra.write_bytes(b'preserve')
            with self.assertRaisesRegex(ValueError, 'unexpected'):
                s.entry(spec, inputs, int(time.time()), 'cleanup', result['terminal_sha256'])
            self.assertEqual(extra.read_bytes(), b'preserve')
            (root / 'recipe.json').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'input drift'):
                s.entry(spec, inputs, int(time.time()), 'readback')
            self.assertTrue((root / 'claim.json').exists())

    def test_recollection_cannot_reuse_existing_stage(self):
        root, spec, inputs, worker = self.fixture_stage()
        with patch.object(s, 'identity'), patch.object(s.types, 'ModuleType', return_value=worker), patch('builtins.exec'):
            with self.assertRaises(FileExistsError):
                s.entry(spec, inputs, int(time.time()), 'collect')
        self.assertTrue((root / 'terminal.json').exists())

    def test_busy_stage_and_missing_terminal_hold_without_removing_inputs(self):
        root, spec, inputs, worker = self.fixture_stage()
        with patch.object(s, 'identity'), patch.object(s.types, 'ModuleType', return_value=worker), patch('builtins.exec'):
            with (root / 'lock').open('rb') as locked:
                fcntl.flock(locked, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with self.assertRaises(BlockingIOError):
                    s.entry(spec, inputs, int(time.time()), 'readback')
            (root / 'terminal.json').unlink()
            with self.assertRaises(FileNotFoundError):
                s.entry(spec, inputs, int(time.time()), 'readback')
        self.assertEqual((root / 'recipe.json').read_bytes(), inputs['recipe.json'])

    def test_collect_success_failure_and_terminal_recovery(self):
        for outcome in ('success', 'failure'):
            root = self.parent / outcome
            spec = dict(self.spec, stage=str(root))
            inputs = {n: self.files[n] for n in s.INPUTS}
            def create(path, data):
                with path.open('xb') as stream:
                    stream.write(data)
                path.chmod(0o600)
            worker = SimpleNamespace(ancestors=Mock(), read=lambda p: p.read_bytes(),
                                     create=create, sync=Mock())
            snapshot = {'ssh': spec['ssh'], 'active_time_daemons': [],
                'hostname': spec['hostname'], 'kernel': spec['kernel'],
                'recipe_sha256': spec['members']['recipe.json'],
                'password_database_read': False, 'package_mutation_authorized': False}
            collector = SimpleNamespace(collect=Mock(return_value=snapshot))
            if outcome == 'failure':
                collector.collect.side_effect = ValueError('observed drift')
            definition = SimpleNamespace(loader=SimpleNamespace(exec_module=Mock()))
            with patch.object(s, 'identity'), patch.object(s.types, 'ModuleType', return_value=worker), \
                    patch('builtins.exec'), patch.object(s.signal, 'signal'), \
                    patch.object(s.importlib.util, 'spec_from_file_location', return_value=definition), \
                    patch.object(s.importlib.util, 'module_from_spec', return_value=collector):
                result = s.entry(spec, inputs, int(time.time()), 'collect')
                self.assertEqual(result['state'], 'snapshot_completed' if outcome == 'success' else 'snapshot_held')
                readback = s.entry(spec, inputs, int(time.time()), 'readback')
                self.assertEqual(readback['state'], result['state'])
                collector.collect.assert_called_once()
                if outcome == 'success':
                    self.assertEqual(base64.b64decode(readback['snapshot_base64']), s.encoded(snapshot))
                s.entry(spec, inputs, int(time.time()), 'cleanup', readback['terminal_sha256'])
                self.assertFalse(root.exists())

    def test_identity_and_hash_failures_precede_staging(self):
        with patch.object(s.os, 'geteuid', return_value=1000):
            with self.assertRaisesRegex(ValueError, 'isolated caller'):
                s.entry(self.spec, {n: self.files[n] for n in s.INPUTS}, int(time.time()), 'collect')
        altered = {n: self.files[n] for n in s.INPUTS}
        altered['recipe.json'] = b'changed'
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            s.entry(self.spec, altered, int(time.time()), 'collect')


if __name__ == '__main__':
    unittest.main()
