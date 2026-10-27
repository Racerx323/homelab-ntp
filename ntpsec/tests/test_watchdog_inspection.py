#!/usr/bin/python3
"""Offline qualification of watchdog metadata reads and one-use review binding."""
import importlib.util
import json
import io
import tarfile
import time
import os
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('watchdog', ROOT/'scripts/run-watchdog-inspection.py')
r = importlib.util.module_from_spec(spec); spec.loader.exec_module(r)
r.h = r.load(r.SOURCES['helper.py']); r.p = r.load(r.SOURCES['passive.py']); r.p.h = r.h


class Watchdog(unittest.TestCase):
    def make_bundle(self, directory):
        now = int(time.time())
        spec = {'schema': 1, 'purpose': 'watchdog-ownership', 'operation_id': directory.name,
            'directory': str(directory), 'prepared_epoch': now, 'expires_epoch': now+86400,
            'baseline_boot_id': 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
            'baseline_file_hashes': {f: 'a'*64 for f in r.p.PROTECTED},
            'baseline_capture_sha256': 'b'*64, 'members': {}}
        directory.mkdir(mode=0o700)
        files = {n: p.read_bytes() for n, p in r.SOURCES.items()}
        files.update(known_hosts=b'10.1.0.137 ssh-ed25519 TESTKEY\n', **{'baseline.json': b'{}'})
        spec['members'] = {n: r.h.sha(v) for n, v in files.items()}
        files.update({'spec.json': r.h.encoded(spec), 'review.md': r.review(spec).encode()})
        for n, raw in files.items():
            (directory/n).write_bytes(raw); (directory/n).chmod(0o600)
        with tarfile.open(directory/'inspection.tar', 'w') as archive:
            for n, raw in files.items():
                member = tarfile.TarInfo(n); member.size = len(raw)
                archive.addfile(member, io.BytesIO(raw))
        (directory/'inspection.tar').chmod(0o600)
        return r.h.sha((directory/'inspection.tar').read_bytes())

    def test_integrity_and_local_review_binding(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)/'watchdog-ownership-test'; digest = self.make_bundle(directory)
            r.prepare(directory, digest)
            with self.assertRaises(ValueError): r.prepare(directory, '0'*64)
            (directory/'review.md').write_text('changed')
            with self.assertRaises(ValueError): r.prepare(directory, digest)

    def test_consumed_receipt_blocks_transport(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)/'watchdog-ownership-test'; digest = self.make_bundle(directory)
            (directory/'execution.json').write_text('{}')
            with patch.object(r.h, 'bounded') as transport:
                with self.assertRaises(FileExistsError):
                    r.execute(types.SimpleNamespace(directory=directory, sha256=digest))
                transport.assert_not_called()

    def test_timeout_consumes_receipt_without_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)/'watchdog-ownership-test'; digest = self.make_bundle(directory)
            with patch.object(r.h, 'bounded', return_value={'stdout': '', 'stderr': '', 'returncode': None, 'error': 'timeout'}) as transport:
                result = r.execute(types.SimpleNamespace(directory=directory, sha256=digest))
                self.assertFalse(result['capture_complete']); self.assertEqual(transport.call_count, 1)
            self.assertTrue((directory/'execution.json').exists())

    def test_indirect_dropin_directory_not_enumerated(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); (root/'system.conf.d').symlink_to('/etc')
            with patch.object(r, 'CONFIG_ROOTS', (temp,)), patch.object(r.p, 'names') as names:
                rows = r.configurations(); names.assert_not_called()
            self.assertTrue(rows[str(root/'system.conf.d')]['indirect_directory_not_enumerated'])

    def test_expired_scope_rejected_before_transport(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)/'watchdog-ownership-test'; digest = self.make_bundle(directory)
            with patch.object(r.time, 'time', return_value=time.time()+86400):
                with self.assertRaises(ValueError): r.prepare(directory, digest)
            self.assertFalse((directory/'execution.json').exists())

    def test_config_exports_only_selected_manager_keys(self):
        row = r.selected_config('[Manager]\nDefaultEnvironment=SECRET\nRuntimeWatchdogSec=60s\n[Other]\nWatchdogDevice=SECRET\n')
        self.assertEqual(row['watchdog_assignments'], [['RuntimeWatchdogSec', '60s']])
        self.assertNotIn('SECRET', json.dumps(row))

    def test_continuation_is_not_silently_accepted(self):
        self.assertTrue(r.selected_config('[Manager]\nRuntimeWatchdogSec=60s\\\n')['continuation_requires_review'])

    def test_real_proc_identity(self):
        self.assertEqual(r.process_identity(str(os.getpid()))['pid'], os.getpid())
        self.assertGreater(r.process_identity(str(os.getpid()))['start_ticks'], 0)

    def test_no_device_identity_never_claims_complete_scan(self):
        with patch.object(r.p, 'metadata', return_value={'missing': True}), patch.object(r.os, 'scandir') as scan:
            self.assertFalse(r.owners()['scan_complete']); scan.assert_not_called()

    def test_scan_never_opens_matched_descriptor(self):
        # Real local /dev/null fd exercises char-device alias matching via metadata.
        with open('/dev/null', 'rb') as stream:
            identity = r.p.metadata('/dev/null')
            original_scan = os.scandir
            def scan(path):
                if path == '/proc':
                    class Entries:
                        def __enter__(self): return iter([types.SimpleNamespace(name=str(os.getpid()))])
                        def __exit__(self, *args): pass
                    return Entries()
                return original_scan(path)
            original_open = os.open
            def guarded_open(path, *args, **kwargs):
                self.assertNotIn('/fd/', str(path)); self.assertFalse(str(path).startswith('/dev/'))
                return original_open(path, *args, **kwargs)
            with patch.object(r.p, 'metadata', return_value=identity), patch.object(r.os, 'scandir', side_effect=scan), patch.object(r.os, 'open', side_effect=guarded_open):
                result = r.owners()
            match = next(m for m in result['matches'] if m['fd'] == stream.fileno())
            self.assertTrue(match['recheck_stable'])

    def test_payload_compiles_without_execution(self):
        files = {n: p.read_bytes() for n, p in r.SOURCES.items()}
        compile(r.payload({}, files), '<sealed>', 'exec')

    def test_closed_scope(self):
        with self.assertRaises(ValueError): r.validate({'purpose': 'anything'})
        self.assertNotIn('set-property', r.MANAGER)

    def test_symlink_configuration_is_not_read(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); (root/'system.conf').symlink_to('/etc/shadow')
            with patch.object(r, 'CONFIG_ROOTS', (temp,)), patch.object(r.h, 'file_record') as read:
                rows = r.configurations(); read.assert_not_called()
            self.assertTrue(rows[str(root/'system.conf')]['content_not_followed'])


if __name__ == '__main__': unittest.main()
