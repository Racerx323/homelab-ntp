#!/usr/bin/python3
"""Offline passive node capture privacy, closed scope and one-use controls."""
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


r = load(ROOT/'scripts/run-phase3-node-inspection.py')
r.h = load(ROOT/'scripts/run-production-inspection.py')


class Inspection(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)/'phase3-node-readiness-test'
        now = int(time.time())
        self.spec = {'schema': 1, 'purpose': 'phase3-node-readiness',
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
        files['baseline.json'] = b'{}'
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

    def test_sources_do_not_export_credentials_paths_or_query(self):
        result = r.repository_sources(b'URIs: https://USER:PASSWORD@repo.example/PRIVATE?TOKEN=SECRET\nSuites: trixie\nComponents: main\nSigned-By: /SECRET\n')
        value = json.dumps(result)
        for word in ('USER', 'PASSWORD', 'PRIVATE', 'TOKEN', 'SECRET'):
            self.assertNotIn(word, value)
        self.assertEqual(result['hosts'], ['repo.example'])
        self.assertEqual(result['suites'], ['trixie'])

    def test_device_metadata_never_opens_device(self):
        with patch('builtins.open', side_effect=AssertionError('device opened')), patch.object(r.os, 'open', side_effect=AssertionError('device opened')):
            self.assertIn('type', r.metadata('/dev/null'))
        with patch.object(r.h, 'file_record') as read:
            with self.assertRaises(ValueError): r.text_record('/dev/null')
            read.assert_not_called()

    def test_sysfs_link_cannot_escape_to_credentials(self):
        with patch.object(r.Path, 'resolve', return_value=Path('/etc/shadow')), patch.object(r.h, 'file_record') as read:
            with self.assertRaises(ValueError): r.text_record('/sys/class/watchdog/watchdog0/identity', True)
            read.assert_not_called()

    def test_actual_sysfs_missing_attribute_is_gap(self):
        self.assertTrue(r.text_record('/sys/phase3_inspection_missing_attribute', True)['missing'])

    def test_timer_query_omits_service_only_properties(self):
        with patch.object(r, 'command', return_value={}) as run:
            r.state()
        for call in run.call_args_list:
            argv = call.args[0]
            if argv[2].endswith('.timer'):
                self.assertNotIn('MainPID', argv[-1]); self.assertNotIn('NRestarts', argv[-1])
            else:
                self.assertIn('MainPID', argv[-1])

    def test_read_scope_excludes_mutation_and_secret_fields(self):
        commands = list(r.COMMANDS.values())
        self.assertTrue(all(argv[0].startswith('/') for argv in commands))
        for argv in commands:
            self.assertNotIn('sudo', argv)
            self.assertNotIn('--show-secrets', argv)
            self.assertNotIn('start', argv); self.assertNotIn('reload', argv)
            self.assertNotIn('restart', argv); self.assertNotIn('up', argv)
        self.assertNotIn('802-11-wireless-security', r.NETWORK_FIELDS)
        self.assertNotIn('apt', {Path(a[0]).name for a in commands})

    def test_incomplete_or_changed_core_evidence_never_completes(self):
        import copy
        unit = {'returncode': 0, 'stdout': 'ActiveState=active\nMainPID=1\nInvocationID=abc\n'}
        report = {'commands': {n: {'returncode': 0} for n in r.REQUIRED_COMMANDS},
            'units_before': {n: unit for n in r.CORE}, 'units_after': {n: unit for n in r.CORE},
            'boot_before': 'boot', 'boot_after': 'boot', 'profiles': {'uuid': {'returncode': 0}},
            'files_before': {'/file': {'sha256': 'ok'}}, 'files_after': {'/file': {'sha256': 'ok'}}}
        self.assertTrue(r.complete(report))
        for label in ('boot', 'unit', 'file', 'command', 'profile', 'empty_profiles'):
            changed = copy.deepcopy(report)
            if label == 'boot': changed['boot_after'] = 'different'
            if label == 'unit': changed['units_after'][r.CORE[0]] = {'returncode': 0, 'stdout': 'ActiveState=inactive\n'}
            if label == 'file': changed['files_after']['/file'] = {'sha256': 'different'}
            if label == 'command': changed['commands'][r.REQUIRED_COMMANDS[0]]['returncode'] = 1
            if label == 'profile': changed['profiles']['uuid']['returncode'] = 1
            if label == 'empty_profiles': changed['profiles'] = {}
            with self.subTest(label=label): self.assertFalse(r.complete(changed))

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
            self.assertFalse(result['capture_complete']); self.assertFalse(result['production_accepted'])
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
