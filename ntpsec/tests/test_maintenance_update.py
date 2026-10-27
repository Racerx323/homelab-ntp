#!/usr/bin/python3
"""Real private-file recovery tests and closed parsing/receipt boundaries; no target access."""
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT/'scripts'/filename)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
r = load('recovery', 'maintenance-recovery.py')
u = load('update', 'maintenance-update.py'); u.r = r
review = load('update_review', 'review-maintenance-update.py')
OWNER = os.getuid()
OP = 'base-os-update-20261027-v1'

class RecoveryTests(unittest.TestCase):
    def setUp(self):
        # Protected ancestors, unlike the deliberately world-writable /tmp.
        self.temp = tempfile.TemporaryDirectory(prefix='.maintenance-test-', dir=ROOT/'tests')
        self.root = Path(self.temp.name)
        for name in ['boot/firmware','var/lib/ntp-maintenance','etc/systemd/system']:
            (self.root/name).mkdir(parents=True, exist_ok=True, mode=0o700)
    def tearDown(self): self.temp.cleanup()
    def baseline(self):
        expected = {}
        for name in ['/boot/initrd.img-kernel','/boot/firmware/initramfs8']:
            path = self.root/name.lstrip('/')
            r.create(path, b'original boot bytes', 0o644, OWNER)
            expected[name] = r.read(path, OWNER)[1]
        return expected
    def test_backup_roundtrip_and_boot_restoration(self):
        expected = self.baseline(); raw = r.backup(self.root, expected, OWNER)
        self.assertEqual(raw, r.backup(self.root, expected, OWNER))
        self.assertEqual(len(r.verify_backup(raw, expected)), 2)
        current = {}
        for name in expected:
            path = self.root/name.lstrip('/');path.write_bytes(b'new boot bytes')
            current[name] = r.read(path, OWNER)[1]
        result = r.restore_boot_files(self.root, raw, expected, current, OWNER)
        self.assertFalse(result['reboot_authorized'])
        for name, row in expected.items(): self.assertEqual(r.read(self.root/name.lstrip('/'), OWNER)[1], row)
    def test_backup_tamper_rejected(self):
        expected=self.baseline();raw=r.backup(self.root,expected,OWNER)
        expected['/boot/initrd.img-kernel']['sha256']='0'*64
        with self.assertRaises(ValueError):r.verify_backup(raw,expected)
    def test_symlink_input_rejected(self):
        expected=self.baseline();p=self.root/'boot/initrd.img-kernel';p.unlink();p.symlink_to('/etc/passwd')
        with self.assertRaises((OSError,ValueError)):r.backup(self.root,expected,OWNER)
    def test_hardlink_input_rejected(self):
        expected=self.baseline();os.link(self.root/'boot/initrd.img-kernel',self.root/'other')
        with self.assertRaises(ValueError):r.backup(self.root,expected,OWNER)
    def test_restore_refuses_drift_before_any_write(self):
        expected=self.baseline();raw=r.backup(self.root,expected,OWNER)
        (self.root/'boot/firmware/initramfs8').write_bytes(b'unexpected')
        with self.assertRaises(ValueError):r.restore_boot_files(self.root,raw,expected,expected,OWNER)
        self.assertEqual((self.root/'boot/initrd.img-kernel').read_bytes(),b'original boot bytes')
    def test_publish_native_condition_restore(self):
        r.publish_inhibit(self.root,OP,OWNER);r.check_inhibit(self.root,OP,OWNER)
        marker=self.root/r.MARKER.lstrip('/')
        command=['/usr/bin/systemd-analyze','condition','ConditionPathExists=!'+str(marker)]
        self.assertEqual(subprocess.run(command,capture_output=True).returncode,1)
        r.restore_inhibit(self.root,OP,OWNER)
        self.assertEqual(subprocess.run(command,capture_output=True).returncode,0)
    def test_foreign_marker_never_removed(self):
        r.create(self.root/r.MARKER.lstrip('/'),b'foreign',owner=OWNER)
        with self.assertRaises(ValueError):r.restore_inhibit(self.root,OP,OWNER)
        self.assertTrue((self.root/r.MARKER.lstrip('/')).exists())
    def test_partial_marker_publication_restores(self):
        r.create(self.root/r.MARKER.lstrip('/'),r.encoded({'operation_id':OP}),owner=OWNER)
        r.restore_inhibit(self.root,OP,OWNER)
        self.assertFalse((self.root/r.MARKER.lstrip('/')).exists())
    def test_foreign_dropin_retained(self):
        r.publish_inhibit(self.root,OP,OWNER)
        (self.root/r.DROPIN.lstrip('/')).parent.joinpath('foreign.conf').write_text('foreign')
        with self.assertRaises(ValueError):r.restore_inhibit(self.root,OP,OWNER)
        self.assertTrue((self.root/r.MARKER.lstrip('/')).exists())
    def test_receipt_replay_rejected(self):
        p=self.root/'receipt';r.create(p,b'first',owner=OWNER)
        with self.assertRaises(FileExistsError):r.create(p,b'second',owner=OWNER)
        self.assertEqual(p.read_bytes(),b'first')
    def test_reserve_floors(self):
        expected=self.baseline()
        r.reserve(20*1024**3,5000,10000,256*1024**2,expected,1000)
        with self.assertRaises(ValueError):r.reserve(9*1024**3,5000,10000,256*1024**2,expected,1000)
        with self.assertRaises(ValueError):r.reserve(20*1024**3,10,10000,256*1024**2,expected,1000)
        with self.assertRaises(ValueError):r.reserve(20*1024**3,5000,10000,1024,expected,1000)
    def test_boot_gates(self):
        config=b'auto_initramfs=1\n[all]\n'
        self.assertFalse(r.boot_conditions(b'console=tty1 root=x\n',config)['early_boot_watchdog_proven'])
        for cmd in [b'console=tty1 resize\n',b'console=tty1 systemd.run=/boot/firstrun.sh\n']:
            with self.assertRaises(ValueError):r.boot_conditions(cmd,config)
        with self.assertRaises(ValueError):r.boot_conditions(b'console=tty1\n',config+b'include custom.txt\n')
        self.assertTrue(r.boot_conditions(b'console=tty1 watchdog_disarm=0\n',config)['continuous_watchdog_requested'])
    def test_solver_delta_is_closed(self):
        packages=[{'package':'example','installed':'1','version':'2'}]
        u.validate_simulation('Inst example [1] (2 localhost [arm64])\n',packages)
        for text in ['Remv other [1]\n','Inst example (2 localhost [arm64])\n','Inst example [1] (3 localhost [arm64])\n']:
            with self.assertRaises(ValueError):u.validate_simulation(text,packages)
    def test_inventory_preserves_removed_package_configuration(self):
        rows=u.inventory('installed\tarm64\t1\tinstalled\nold\tarm64\t0\tconfig-files\n')
        self.assertEqual(rows['old:arm64'],('0','config-files'))
    def test_bad_seal_rejected_before_authentication(self):
        review.c.create(self.root/'update.tar',b'invalid')
        with patch.object(review.c,'authentication',side_effect=AssertionError('authentication reached')):
            with self.assertRaisesRegex(ValueError,'archive SHA-256'):
                review.execute(self.root,'0'*64,self.root/'absent-attendance')
        self.assertFalse((self.root/'execution.json').exists())
    def test_actual_bootstrap_rejects_controller_identity(self):
        files={n:p.read_bytes() for n,p in review.SOURCES.items()}
        files['baseline.json']=b'{"after":{}}'
        raw=review.payload({'operation_id':OP},files,'backup')
        result=subprocess.run(['/usr/bin/python3','-I','-B','-c',
                              'import sys;exec(sys.stdin.buffer.readline())'],input=raw,
                              capture_output=True,timeout=10)
        self.assertNotEqual(result.returncode,0)
        report = json.loads(result.stdout)
        self.assertIn('inspection preflight failed', report['error'])
        self.assertFalse(report['backup_complete'])
        self.assertFalse(report['preflight_evidence']['inspection']['capture_complete'])
        self.assertIn('identity', report['preflight_evidence']['inspection']['error'])
    def test_offnode_ack_failure_before_target_mutation(self):
        baseline={'after':{}}
        with patch.object(u,'preflight',return_value=({},{})),patch.object(r,'backup',return_value=b'x'):
            result=u.install({'operation_id':OP},baseline,{}, {})
        self.assertFalse(result['package_stage_complete'])
        self.assertEqual(result['phase'],'pre-package-failure')

    def test_service_policy_combined_lifecycle_and_rejections(self):
        services = {}
        for name in ('timeservice.service', 'munin-node.service', 'cron.service'):
            services[name] = {'accepted': True, 'stdout':
                'LoadState=loaded\nActiveState=active\nSubState=running\n'}
        services['gpsd.service'] = {'accepted': True, 'stdout':
            'LoadState=not-found\nActiveState=inactive\nSubState=dead\nMainPID=0\n'}
        for name in ('apt-daily.service', 'apt-daily-upgrade.service', 'unattended-upgrades.service'):
            services[name] = {'accepted': True, 'stdout': 'ActiveState=inactive\n'}
        services['rpi-eeprom-update.service'] = {'accepted': True, 'stdout': 'MainPID=0\nSubState=exited\n'}
        u.validate_services(services)
        for name, text in (('gpsd.service', 'LoadState=loaded\nActiveState=active\n'),
                           ('timeservice.service', 'ActiveState=inactive\n'),
                           ('apt-daily.service', 'ActiveState=active\n'),
                           ('rpi-eeprom-update.service', 'MainPID=42\nSubState=running\n')):
            changed = dict(services, **{name: {'accepted': True, 'stdout': text}})
            with self.subTest(unit=name), self.assertRaises(ValueError):
                u.validate_services(changed)

    def test_failed_collector_retained_before_backup(self):
        from types import SimpleNamespace
        partial = {'capture_complete': False, 'commands': {'audit': {'returncode': 1}},
                   'error': 'inspection stopped'}
        with patch.object(u, 'w', SimpleNamespace(collect=lambda *_: partial)), \
                patch.object(r, 'backup', side_effect=AssertionError('backup reached')):
            result = u.export_backup({'operation_id': OP}, {'after': {}})
        self.assertTrue(result['held'])
        self.assertEqual(result['preflight_evidence']['inspection'], partial)
        self.assertFalse(result['target_mutation'])

    def test_seal_rejects_contradictory_baseline_before_archive_creation(self):
        inputs = self.root/'inputs'; inputs.mkdir(mode=0o700)
        destination = self.root/OP
        review.c.create(inputs/'spec.json', {'operation_id': OP, 'directory': str(destination)})
        review.c.create(inputs/'qualification.json', {})
        review.c.create(inputs/'baseline.json', {'before': {'services': {'timeservice.service':
            {'accepted': True, 'stdout': 'ActiveState=inactive\n'}}}})
        with self.assertRaisesRegex(ValueError, 'inactive service: timeservice.service'):
            review.seal(destination, inputs)
        self.assertFalse(destination.exists())

    def test_late_preflight_failure_retains_native_results(self):
        def fail(spec, baseline, evidence):
            evidence['native'] = {'returncode': 1, 'stderr': 'native rejection'}
            raise ValueError('native check')
        with patch.object(u, 'preflight', side_effect=fail):
            backup = u.export_backup({'operation_id': OP}, {})
            install = u.install({'operation_id': OP}, {}, {}, {})
        for result in (backup, install):
            self.assertEqual(result['preflight_evidence']['native']['returncode'], 1)
            self.assertIn('native check', result['error'])
        self.assertFalse(install['package_stage_complete'])

    def test_controller_retains_failed_report_without_second_connection(self):
        from types import SimpleNamespace
        import time
        digest = 'a'*64
        operator = {'archive_sha256': digest, 'confirmed_epoch': time.time()}
        operator.update(dict.fromkeys(('attending_kvm', 'peer_and_antenna_continuity',
            'exclusive_recovery_card', 'no_other_package_or_reset_actions',
            'maintenance_window_90_minutes', 'pre_reboot_hold_accepted'), True))
        attendance = self.root/'attendance.json'; review.c.create(attendance, operator)
        report = {'operation_id': OP, 'backup_complete': False, 'held': True,
                  'preflight_evidence': {'inspection': {'error': 'retained'}}}
        transport = {'returncode': 1, 'stdout': json.dumps(report), 'stderr': ''}
        spec = {'operation_id': OP, 'authentication': {'identity_file': 'unused'}}
        calls = []
        def bounded(*args, **kwargs):
            calls.append(args); return transport
        with patch.object(review, 'check', return_value=(spec, {'helper.py': b'', 'recovery.py': b''})), \
                patch.object(review.c, 'authentication', return_value=spec['authentication']), \
                patch.object(review.c, 'module', side_effect=[SimpleNamespace(bounded=bounded), r]), \
                patch.object(review.c, 'ssh', return_value=['unused']), \
                patch.object(review, 'payload', return_value=b''):
            result = review.execute(self.root, digest, attendance)
        self.assertTrue(result['held'])
        self.assertEqual(len(calls), 1)
        self.assertEqual(json.loads((self.root/'backup-report.json').read_text()), report)
        self.assertFalse((self.root/'offnode-ack.json').exists())
        self.assertFalse((self.root/'install-transport.json').exists())

if __name__=='__main__':unittest.main()
