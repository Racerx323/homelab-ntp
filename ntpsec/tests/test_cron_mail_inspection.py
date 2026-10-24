#!/usr/bin/python3
"""Offline OBS-04 capture privacy, exact scope and one-use boundary checks."""
import importlib.util
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


r = load(ROOT/'scripts/run-cron-mail-inspection.py')
r.h = load(ROOT/'scripts/run-production-inspection.py')


class Inspection(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)/'obs04-cron-mail-readiness-test'
        now = int(time.time())
        self.spec = {'schema': 1, 'purpose': 'obs04-cron-mail-readiness',
            'operation_id': self.directory.name, 'directory': str(self.directory),
            'prepared_epoch': now, 'expires_epoch': now+86400,
            'baseline_boot_id': 'a'*8+'-'+'b'*4+'-'+'c'*4+'-'+'d'*4+'-'+'e'*12,
            'baseline_file_hashes': {p: 'a'*64 for p in ('/etc/ntp.conf',
                '/etc/cron.d/needrestart_check', '/usr/local/sbin/needrestart.sh',
                '/usr/local/libexec/ntp-maintenance-success.py')},
            'baseline_capture_sha256': 'b'*64, 'members': {}}

    def bundle(self, extra=None):
        self.directory.mkdir(mode=0o700)
        files = {n: p.read_bytes() for n, p in r.SOURCES.items()}
        files['known_hosts'] = b'10.1.0.137 ssh-ed25519 PUBLIC_TEST_KEY\n'
        self.spec['members'] = {n: r.h.sha(v) for n, v in files.items()}
        files.update({'spec.json': r.h.encoded(self.spec), 'review.md': r.review(self.spec).encode()})
        for n, v in files.items():
            p = self.directory/n; p.write_bytes(v); p.chmod(0o600)
        with tarfile.open(self.directory/'inspection.tar', 'w') as archive:
            for n, v in files.items():
                member = tarfile.TarInfo(n); member.size = len(v)
                archive.addfile(member, io.BytesIO(v))
            if extra:
                member = tarfile.TarInfo(extra); member.size = 0
                archive.addfile(member, io.BytesIO(b''))
        archive_path = self.directory/'inspection.tar'; archive_path.chmod(0o600)
        return r.h.sha(archive_path.read_bytes())

    def test_transport_filter_never_exports_secret_or_unsafe_values(self):
        raw = (b'account apprise\nhost relay.example\nport 8025\nfrom node@example.org\n'
               b'password SECRET\nuser SECRET\ninclude /SECRET\nhost https://SECRET\n'
               b'from SECRET\nallow_from_override\ton\n')
        result = r.safe_options(raw)
        self.assertNotIn('SECRET', json.dumps(result))
        self.assertTrue(result['includes_present'])
        self.assertIn(['allow_from_override', 'on'], result['options'])
        self.assertEqual(result['unexported_directives'], 5)

    def test_closed_scope_rejects_extra_commands_or_paths(self):
        r.validate(self.spec)
        for key in ('command', 'target', 'send_message'):
            with self.subTest(key=key), self.assertRaises(ValueError):
                r.validate(dict(self.spec, **{key: 'unapproved'}))
        self.spec['baseline_file_hashes']['/etc/shadow'] = 'c'*64
        with self.assertRaises(ValueError): r.validate(self.spec)

    def test_root_identity_rejected_before_reads_or_commands(self):
        with patch.object(r.os, 'geteuid', return_value=1000), patch.object(r.h, 'bounded') as run:
            with self.assertRaises(ValueError): r.collect(self.spec)
            run.assert_not_called()

    def test_wrong_host_rejected_before_commands(self):
        with patch.object(r.os, 'geteuid', return_value=0), patch.object(r.socket, 'gethostname', return_value='other'), patch.object(r.h, 'bounded') as run:
            with self.assertRaises(ValueError): r.collect(self.spec)
            run.assert_not_called()

    def test_bundle_check_and_payload_compile_without_contact(self):
        digest = self.bundle()
        with patch.object(r.h, 'bounded') as run:
            spec, files = r.prepare(self.directory, digest)
            compile(r.payload(spec, files), '<sealed-payload>', 'exec')
            run.assert_not_called()
        self.assertFalse((self.directory/'execution.json').exists())

    def test_tampered_review_and_archive_rejected_before_contact(self):
        digest = self.bundle()
        (self.directory/'review.md').write_bytes(b'changed')
        with self.assertRaises(ValueError): r.prepare(self.directory, digest)
        with self.assertRaises(ValueError): r.prepare(self.directory, '0'*64)

    def test_extra_archive_member_rejected(self):
        digest = self.bundle(extra='unapproved.sh')
        with self.assertRaises(ValueError): r.prepare(self.directory, digest)

    def test_expired_scope_rejected(self):
        self.spec['prepared_epoch'] -= 90000; self.spec['expires_epoch'] -= 90000
        digest = self.bundle()
        with self.assertRaises(ValueError): r.prepare(self.directory, digest)

    def test_uncertain_capture_retained_and_receipt_blocks_second_connection(self):
        digest = self.bundle()
        args = type('Args', (), {'directory': self.directory, 'sha256': digest})()
        with patch.object(r.h, 'bounded', return_value={'returncode': None, 'error': 'timeout',
                'stdout': 'partial', 'stderr': 'diagnostic'}) as run:
            result = r.execute(args)
            self.assertFalse(result['capture_complete']); self.assertFalse(result['obs04_accepted'])
            self.assertEqual((self.directory/'stdout.txt').read_text(), 'partial')
            self.assertTrue((self.directory/'execution.json').exists())
            with self.assertRaises(FileExistsError): r.execute(args)
            self.assertEqual(run.call_count, 1)
            argv = run.call_args.args[0]
            self.assertIn('StrictHostKeyChecking=yes', argv)
            self.assertIn('HostKeyAlias=10.1.0.137', argv)
            self.assertIn('ama@10.1.0.51', argv)


if __name__ == '__main__':
    unittest.main()
