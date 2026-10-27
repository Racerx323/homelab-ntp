#!/usr/bin/python3
"""Real private-file tests of the small attended-runbook file helper."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
s = importlib.util.spec_from_file_location('files', ROOT/'scripts/maintenance-native-files.py')
m = importlib.util.module_from_spec(s); s.loader.exec_module(m)
s = importlib.util.spec_from_file_location('recovery', ROOT/'scripts/maintenance-recovery.py')
r = importlib.util.module_from_spec(s); s.loader.exec_module(r)


class NativeFiles(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT/'tests', prefix='.native-maintenance-')
        self.root = Path(self.temp.name)
        self.stage = self.root/'var/lib/ntp-maintenance/base-os-update-20261027-v3'
        for path in [self.stage, self.root/'etc/systemd/system', self.root/'etc/udev/rules.d', self.root/'var/lib/apt']:
            path.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.oldcwd = Path.cwd(); os.chdir(self.stage)
        shutil.copyfile(ROOT/'scripts/maintenance-recovery.py', 'recovery.py')
        self.spec = {'stage': str(self.stage), 'operation_id': self.stage.name}
        self.save()
    def save(self):
        Path('spec.json').write_text(json.dumps(self.spec))
    def tearDown(self):
        os.chdir(self.oldcwd); self.temp.cleanup()
    def run_action(self, action):
        with patch.object(sys, 'argv', ['files.py', action]):
            m.main(self.root, os.getuid())
    def test_publish_check_restore(self):
        self.run_action('publish'); self.run_action('check'); self.run_action('restore')
        self.assertFalse((self.root/r.MARKER.lstrip('/')).exists())
        self.assertFalse((self.root/r.DROPIN.lstrip('/')).parent.exists())
        self.assertFalse((self.root/'etc/systemd/system/apt-daily.timer').is_symlink())
    def test_foreign_mask_holds_all_cleanup(self):
        self.run_action('publish')
        p=self.root/'etc/systemd/system/apt-daily.service';p.unlink();p.write_text('foreign')
        with self.assertRaises(ValueError):self.run_action('restore')
        self.assertTrue((self.root/r.MARKER.lstrip('/')).exists())
        self.assertEqual(p.read_text(),'foreign')
    def test_partial_owned_marker_cleanup(self):
        r.publish_inhibit(self.root,self.spec['operation_id'],os.getuid())
        self.run_action('restore')
        self.assertFalse((self.root/r.MARKER.lstrip('/')).exists())
    def test_flags_and_rule_publication(self):
        p=self.root/'var/lib/apt/extended_states';p.write_bytes(b'old flags\n');p.chmod(0o644)
        expected={'/var/lib/apt/extended_states':r.read(p,os.getuid())[1]}
        raw=r.backup(self.root,expected,os.getuid())
        old=self.root/'var/lib/ntp-maintenance/base-os-update-20261027-v2';old.mkdir();(old/'recovery.tar.gz').write_bytes(raw)
        self.spec.update(backup=expected,independent_backup_sha256=r.sha(raw));self.save()
        p.write_bytes(b'changed flags\n');Path('candidate.rules').write_bytes(b'# candidate\n');Path('candidate.rules').chmod(0o600)
        self.run_action('publish-alsa-and-flags')
        self.assertEqual(p.read_bytes(),b'old flags\n')
        target=self.root/'etc/udev/rules.d/90-alsa-restore.rules'
        self.assertEqual(target.read_bytes(),b'# candidate\n')
        self.assertEqual(target.stat().st_mode & 0o777,0o644)
        with self.assertRaises(FileExistsError):self.run_action('publish-alsa-and-flags')
    def test_inherited_controls_check_and_restore(self):
        self.run_action('publish')
        previous = self.spec['operation_id']
        self.spec.update(operation_id='successor', control_operation_id=previous)
        self.save()
        self.run_action('check')
        with self.assertRaises(ValueError):self.run_action('publish')
        self.run_action('restore')
        self.assertFalse((self.root/r.MARKER.lstrip('/')).exists())
        self.assertFalse((self.root/'etc/systemd/system/apt-daily.timer').is_symlink())
    def test_wrong_inherited_owner_preserves_controls(self):
        self.run_action('publish')
        self.spec['control_operation_id']='foreign';self.save()
        with self.assertRaises(ValueError):self.run_action('check')
        with self.assertRaises(ValueError):self.run_action('restore')
        self.assertTrue((self.root/r.MARKER.lstrip('/')).exists())
        self.assertTrue((self.root/'etc/systemd/system/apt-daily.timer').is_symlink())
    def test_wrong_stage_before_writes(self):
        self.spec['stage']='wrong';self.save()
        with self.assertRaises(ValueError):self.run_action('publish')
        self.assertFalse((self.root/r.MARKER.lstrip('/')).exists())


if __name__=='__main__':unittest.main()
