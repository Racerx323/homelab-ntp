#!/usr/bin/python3
"""Offline inspection sealing, scope, bounded I/O and single-execution tests."""
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tarfile
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('production_inspection', ROOT/'scripts/run-production-inspection.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


class Inspection(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.old = {'hostname': 'j2-svntp1', 'operation_id': 'monitor-fixture',
                    'old_ipv4': '192.0.2.1', 'endpoints': ['192.0.2.2', '2001:db8::2'],
                    'boot_id': 'a'*32, 'stage': '/var/lib/ntp-acquire-monitor-fixture',
                    'apply_unit': 'ntp-monitor-monitor-fixture',
                    'recovery_unit': 'ntp-monitor-monitor-fixture-watchdog'}
        archive = self.root/'service-monitor.tar'
        files = {n: b'raise AssertionError("historical executable must never run")\n'
                 for n in m.INSTALLED.values()}
        files.update({'spec.json': m.encoded(self.old), 'known_hosts': b'192.0.2.1 ssh-ed25519 fixture\n'})
        self.tar(archive, files)
        archive.chmod(0o600)
        self.output = self.root/'inspection'
        self.sealed = m.seal(SimpleNamespace(monitor_dir=self.root,
            monitor_sha256=m.sha(archive.read_bytes()), operation_id='production-fixture', output=self.output))
        self.bundle = self.output/'production-inspection.tar'
        self.spec, self.files = m.prepare(self.bundle, self.sealed['sha256'])

    def tar(self, path, files):
        with tarfile.open(path, 'w') as archive:
            for name, raw in files.items():
                item = tarfile.TarInfo(name); item.size = len(raw); item.mode = 0o600
                archive.addfile(item, io.BytesIO(raw))

    def test_flat_bundle_and_historical_data_only(self):
        self.assertEqual(set(self.files), {'runner.py','tests.py','spec.json','review.md','known_hosts','baseline.json'})
        baseline = json.loads(self.files['baseline.json'])
        self.assertEqual(set(baseline['installed_sha256']), set(m.INSTALLED))
        self.assertNotIn('raise AssertionError', self.files['baseline.json'].decode())
        self.assertFalse(self.sealed['target_contact'])

    def test_hash_expiry_local_review_and_current_source_rejection(self):
        with self.assertRaisesRegex(ValueError, 'digest'):
            m.prepare(self.bundle, '0'*64)
        with patch.object(m.time,'time',return_value=self.spec['expires_epoch']):
            with self.assertRaisesRegex(ValueError,'window'):
                m.prepare(self.bundle,self.sealed['sha256'])
        (self.output/'review.md').write_text('changed')
        with self.assertRaisesRegex(ValueError,'approval input'):
            m.prepare(self.bundle,self.sealed['sha256'])

    def test_scope_rejects_path_unit_target_and_endpoint_injection(self):
        for key, value in [('stage','/etc'),('recovery_unit','other'),('hostname','other'),
                           ('endpoints',['192.0.2.2; reboot','2001:db8::2']),
                           ('host_key_alias','x -o ProxyCommand=evil')]:
            candidate = dict(self.spec); candidate[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                m.validate(candidate)

    def test_unknown_archive_member_rejected(self):
        files = dict(self.files); files['extra.tar'] = b'bad'
        self.tar(self.bundle,files)
        with self.assertRaisesRegex(ValueError,'archive'):
            m.prepare(self.bundle,m.sha(self.bundle.read_bytes()))

    def test_file_limits_symlinks_missing_and_drift_bytes(self):
        path = self.root/'drift'; path.write_bytes(b'1.250\n')
        row = m.file_record(path,True)
        self.assertEqual(row['sha256'],m.sha(b'1.250\n'))
        self.assertFalse(row['changed_during_read'])
        self.assertEqual(path.read_bytes(),b'1.250\n')
        link = self.root/'link'; link.symlink_to(path)
        self.assertIn('error',m.file_record(link))
        self.assertEqual(m.file_record(self.root/'absent'),{'missing':True})
        path.write_bytes(b'x'*(m.LIMIT+1))
        self.assertIn('error',m.file_record(path))

    def test_collect_closed_readonly_commands_and_type_correct_unit_properties(self):
        seen = []
        def command(argv, **kwargs):
            seen.append(argv)
            return {'argv':argv,'returncode':0,'stdout':'','stderr':''}
        with patch.object(m.socket,'gethostname',return_value='j2-svntp1'), \
                patch.object(m.os,'geteuid',return_value=0), \
                patch.object(m,'file_record',return_value={'missing':True}), \
                patch.object(m,'bounded',side_effect=command):
            report = m.collect(self.spec)
        self.assertTrue(report['capture_complete'])
        self.assertFalse(report['production_accepted'])
        self.assertEqual(len(seen),len(m.units(self.spec))+7)
        for argv in seen:
            self.assertNotIn('restart',argv); self.assertNotIn('stop',argv)
            if argv[0] == '/usr/bin/systemctl':
                self.assertEqual(argv[1],'show')
                if not argv[2].endswith('.service'):
                    self.assertNotIn('MainPID',argv[-1]); self.assertNotIn('NRestarts',argv[-1])
        with patch.object(m.socket,'gethostname',return_value='wrong'), patch.object(m,'bounded') as run:
            with self.assertRaisesRegex(ValueError,'identity'):m.collect(self.spec)
            run.assert_not_called()

    def test_bounded_process_output_input_timeout_and_nonzero(self):
        result = m.bounded([sys.executable,'-c','import sys; print(sys.stdin.read()); print("err",file=sys.stderr)'],payload=b'fixture')
        self.assertEqual(result['returncode'],0)
        self.assertEqual(result['stdout'],'fixture\n')
        self.assertEqual(result['stderr'],'err\n')
        result = m.bounded([sys.executable,'-c','print("x"*5000)'],limit=100)
        self.assertIn('bound',result['error']); self.assertEqual(len(result['stdout']),100)
        result = m.bounded([sys.executable,'-c','import time; time.sleep(5)'],timeout=0.1)
        self.assertIn('deadline',result['error'])
        self.assertEqual(m.bounded([sys.executable,'-c','raise SystemExit(2)'])['returncode'],2)

    def test_execute_registers_before_connection_and_never_replays(self):
        args = SimpleNamespace(bundle=self.bundle,sha256=self.sealed['sha256'])
        def command(argv, **kwargs):
            self.assertTrue((self.output/'execution.json').exists())
            self.assertIn('StrictHostKeyChecking=yes',argv)
            self.assertIn('HostKeyAlias=192.0.2.1',argv)
            self.assertEqual(argv[-1],'cd / && sudo -n /usr/bin/python3 -I -B -')
            compile(kwargs['payload'],'sealed-payload','exec')
            return {'stdout':'partial','stderr':'transport failed','returncode':255}
        with patch.object(m,'bounded',side_effect=command) as run:
            result = m.execute(args)
            self.assertEqual(result['returncode'],255)
            self.assertEqual((self.output/'stdout.txt').read_text(),'partial')
            with self.assertRaises(FileExistsError):m.execute(args)
            self.assertEqual(run.call_count,1)

    def test_remote_deadline_reaps_the_active_child(self):
        launch = m.subprocess.Popen
        children = []
        def spawn(*args, **kwargs):
            child = launch(*args, **kwargs); children.append(child); return child
        with patch.object(m.subprocess, 'Popen', side_effect=spawn), \
                patch.object(m.selectors.DefaultSelector, 'select', side_effect=m.CaptureDeadline()):
            with self.assertRaises(m.CaptureDeadline):
                m.bounded([sys.executable, '-c', 'import time; time.sleep(10)'])
        self.assertIsNotNone(children[0].poll())

    def test_transport_spawn_failure_is_retained(self):
        with patch.object(m, 'bounded', side_effect=OSError('cannot launch ssh')):
            result = m.execute(SimpleNamespace(bundle=self.bundle, sha256=self.sealed['sha256']))
        self.assertIn('cannot launch', result['error'])
        self.assertTrue((self.output/'result.json').exists())

    def test_success_compares_files_without_claiming_production(self):
        baseline = json.loads(self.files['baseline.json'])
        capture = {'capture_complete':True,'hostname':self.spec['hostname'],
                   'operation_id':self.spec['operation_id'],'spec_sha256':m.sha(m.encoded(self.spec)),
                   'files':{p:{'sha256':v} for p,v in baseline['installed_sha256'].items()}}
        with patch.object(m,'bounded',return_value={'stdout':json.dumps(capture),'stderr':'','returncode':0}):
            result = m.execute(SimpleNamespace(bundle=self.bundle,sha256=self.sealed['sha256']))
        self.assertTrue(result['capture_complete'])
        self.assertTrue(all(result['baseline_comparison'].values()))
        self.assertFalse(result['production_accepted'])


    def rtc_fixture(self):
        old = dict(self.old, purpose='production-transition', action='start',
                   host_key_alias=self.old['old_ipv4'],
                   members={'known_hosts': m.sha(b'fixture key')})
        archive = self.root/'production-transition.tar'
        self.tar(archive, {'spec.json': m.encoded(old), 'known_hosts': b'fixture key'})
        archive.chmod(0o600)
        digest = m.sha(archive.read_bytes())
        convergence = {'convergence_accepted': True, 'last_attempt': 2,
                       'first_ready_epoch': 1000, 'last_ready_epoch': 1301}
        (self.root/'convergence-result.json').write_bytes(m.encoded(convergence))
        for attempt, epoch in ((1, 1000), (2, 1301)):
            receipt = {'bundle_sha256': digest, 'timing_ready': True,
                       'state': {'health': {'epoch': epoch}}}
            (self.root/f'observe-{attempt}-outcome.json').write_bytes(m.encoded(receipt))
        return SimpleNamespace(start_dir=self.root, start_sha256=digest,
                               operation_id='rtc-fixture', output=self.root/'rtc')

    def test_rtc_flat_seal_binding_and_convergence_rejection(self):
        args = self.rtc_fixture()
        result = m.seal_rtc(args)
        spec, files = m.prepare(Path(result['bundle']), result['sha256'])
        self.assertEqual(spec['purpose'], 'rtc-inspection')
        self.assertEqual(len(json.loads(files['baseline.json'])['observations']), 2)
        self.assertFalse(any(n.endswith('.tar') for n in files))
        args.output = self.root/'rejected'
        p = self.root/'observe-2-outcome.json'
        receipt = json.loads(p.read_text()); receipt['bundle_sha256'] = '0'*64
        p.write_bytes(m.encoded(receipt))
        with self.assertRaisesRegex(ValueError, 'binding'):
            m.seal_rtc(args)
        self.assertFalse(args.output.exists())

    def test_rtc_metadata_nondefault_device_hooks_and_absence(self):
        root = self.root/'target'
        node = root/'sys/class/rtc/rtc3'; node.mkdir(parents=True)
        for name, value in {'name':'rv3028', 'date':'2026-10-15', 'time':'18:00:00',
                            'since_epoch':'1792087200', 'hctosys':'1', 'dev':'252:3'}.items():
            (node/name).write_text(value)
        cron = root/'etc/cron.hourly'; cron.mkdir(parents=True)
        (cron/'save-clock').write_text('/sbin/fake-hwclock save\n')
        wants = root/'etc/systemd/system/sysinit.target.wants'; wants.mkdir(parents=True)
        (wants/'fake-hwclock.service').symlink_to('/usr/lib/systemd/system/fake-hwclock.service')
        result = m.rtc_metadata(root)
        self.assertEqual(result['devices'][0]['attributes']['name'], 'rv3028')
        self.assertIn('error', result['devices'][0]['device'])
        self.assertIn('/etc/cron.hourly/save-clock', result['files'])
        self.assertTrue(result['files']['/etc/adjtime']['missing'])
        self.assertIn(str(wants/'fake-hwclock.service'), result['registrations'])

    def test_rtc_capture_keeps_missing_commands_and_has_no_mutation(self):
        args = self.rtc_fixture(); sealed = m.seal_rtc(args)
        spec, _ = m.prepare(Path(sealed['bundle']), sealed['sha256'])
        seen = []
        def command(argv, **kwargs):
            seen.append(argv)
            return {'argv': argv, 'returncode': 1, 'stdout': '', 'stderr': 'missing fixture'}
        with patch.object(m.socket, 'gethostname', return_value='j2-svntp1'), \
                patch.object(m.os, 'geteuid', return_value=0), \
                patch.object(m, 'rtc_metadata', return_value={'devices': [], 'files': {}}), \
                patch.object(m, 'bounded', side_effect=command):
            result = m.collect(spec)
        self.assertTrue(result['capture_complete'])
        self.assertEqual(len(result['unresolved_commands']), len(seen))
        self.assertFalse(result['production_accepted'])
        for argv in seen:
            self.assertFalse(set(argv) & {'start', 'stop', 'restart', 'enable', 'disable', '--systohc', '--hctosys'})
            self.assertNotIn('/usr/sbin/hwclock', argv)
            if argv[0] == '/usr/bin/systemctl':
                self.assertIn(argv[1], ('show', 'cat', 'list-unit-files'))
        with patch.object(m.socket, 'gethostname', return_value='wrong'), patch.object(m, 'rtc_metadata') as capture:
            with self.assertRaisesRegex(ValueError, 'identity'):
                m.collect(spec)
            capture.assert_not_called()


    def test_utility_scope_seals_and_rejects_unknown_scope(self):
        args = self.rtc_fixture(); args.utility_only = True
        result = m.seal_rtc(args)
        spec, files = m.prepare(Path(result['bundle']), result['sha256'])
        self.assertEqual(spec['rtc_scope'], 'utility')
        self.assertIn('No invocation of hwclock', files['review.md'].decode())
        spec['rtc_scope'] = 'write'
        with self.assertRaisesRegex(ValueError, 'scope'):
            m.validate(spec)

    def test_utility_files_handles_usr_merge_absence_and_bad_targets(self):
        root = self.root/'utilities'; (root/'usr/sbin').mkdir(parents=True)
        (root/'sbin').symlink_to('usr/sbin')
        binary = root/'usr/sbin/hwclock'; binary.write_bytes(b'fixture')
        result = m.rtc_utility_files(root)
        self.assertEqual(result['/sbin/hwclock']['resolved'], str(binary))
        self.assertEqual(result['/sbin/hwclock']['size'], 7)
        self.assertNotIn('content', result['/sbin/hwclock'])
        self.assertTrue(result['/sbin/fake-hwclock']['missing'])
        binary.unlink(); binary.symlink_to(root/'etc/private')
        result = m.rtc_utility_files(root)
        self.assertIn('outside allowed', result['/sbin/hwclock']['error'])
        binary.unlink(); binary.mkdir()
        self.assertIn('not regular', m.rtc_utility_files(root)['/sbin/hwclock']['error'])

    def test_utility_capture_never_invokes_clock_or_contacts_package_source(self):
        args = self.rtc_fixture(); args.utility_only = True
        result = m.seal_rtc(args)
        spec, _ = m.prepare(Path(result['bundle']), result['sha256'])
        seen = []
        def command(argv, **kwargs):
            seen.append(argv)
            return {'argv': argv, 'returncode': 1, 'stdout': 'partial', 'stderr': 'missing fixture'}
        with patch.object(m.socket, 'gethostname', return_value='j2-svntp1'), \
                patch.object(m.os, 'geteuid', return_value=0), \
                patch.object(m, 'rtc_utility_files', return_value={}), \
                patch.object(m, 'rtc_metadata') as rtc, \
                patch.object(m, 'bounded', side_effect=command):
            capture = m.collect(spec)
            rtc.assert_not_called()
        self.assertTrue(capture['capture_complete'])
        self.assertEqual(len(capture['unresolved_commands']), 4)
        self.assertEqual([a[0] for a in seen], ['/usr/bin/dpkg-query']*3+['/usr/bin/apt-cache'])
        self.assertEqual(seen[-1], ['/usr/bin/apt-cache', 'policy', 'util-linux-extra'])
        self.assertFalse(capture['production_accepted'])


if __name__ == '__main__':
    unittest.main()
