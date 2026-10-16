#!/usr/bin/python3
"""Exercise the logrotate candidate against disposable statistics files."""
import grp
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT/'templates/ntpstats-retention.logrotate'


@unittest.skipUnless(shutil.which('logrotate'), 'logrotate unavailable')
class RetentionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.stats = self.root/'stats'
        self.stats.mkdir()
        self.control = self.root/'control'
        self.control.mkdir(mode=0o700)
        self.marker = self.control/'trigger'
        self.marker.touch(mode=0o600)
        for stream in ('loopstats', 'peerstats', 'clockstats', 'protostats'):
            self.file(stream, 40)
        user = pwd.getpwuid(os.getuid()).pw_name
        group = grp.getgrgid(os.getgid()).gr_name
        text = TEMPLATE.read_text().replace('/var/log/ntpstats', str(self.stats)).replace('/var/lib/ntpstats-retention', str(self.control))
        text = text.replace('0600 root root', f'0600 {user} {group}').replace('su root root', f'su {user} {group}')
        self.config = self.root/'logrotate.conf'
        self.config.write_text(text)
        self.config.chmod(0o600)

    def file(self, name, days):
        path = self.stats/name
        path.write_text('fixture\n')
        stamp = time.time()-days*86400
        os.utime(path, (stamp, stamp))
        return path

    def run_rotation(self, debug=False):
        return subprocess.run([shutil.which('logrotate'), '--debug' if debug else '--force',
                               '--state', str(self.control/'state'), str(self.config)],
                              text=True, capture_output=True, timeout=15)

    def test_30_day_boundary_and_active_unrelated_link_safety(self):
        old = self.file('loopstats.20260901', 30.1)
        old_gz = self.file('peerstats.20260901.gz', 31)
        recent = self.file('clockstats.20261001', 29.9)
        young_mtime = self.file('loopstats.20200101', 1)
        unrelated = self.file('other.20260901', 40)
        suffix = self.file('clockstats.20260901.1', 40)
        active = self.stats/'loopstats.20260801'
        os.link(self.stats/'loopstats', active)
        indirect = self.stats/'peerstats.20260801'
        indirect.symlink_to(unrelated)
        nested = self.stats/'nested'
        nested.mkdir()
        nested_file = nested/'loopstats.20200101'
        nested_file.write_text('keep')
        debug = self.run_rotation(debug=True)
        self.assertEqual(debug.returncode, 0, debug.stderr)
        self.assertTrue(old.exists())
        result = self.run_rotation()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(old.exists())
        self.assertFalse(old_gz.exists())
        for p in (recent, young_mtime, unrelated, suffix, active, indirect, nested_file):
            self.assertTrue(p.exists(), str(p))
        self.assertEqual(self.marker.stat().st_mode & 0o777, 0o600)

    def test_protostats_retention_preserves_old_open_hardlink(self):
        active = self.stats/'protostats'
        dated = self.stats/'protostats.20260801'
        os.link(active, dated)
        expired = self.file('protostats.20260901', 30.01)
        compressed = self.file('protostats.20260902.gz', 40)
        boundary = self.file('protostats.20260903', 30-60/86400)
        extra_link = self.file('protostats.20260904', 40)
        os.link(extra_link, self.stats/'preserved-link')
        with active.open('a') as writer:
            before = os.fstat(writer.fileno()).st_ino
            result = self.run_rotation()
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(dated.stat().st_ino, before)
            writer.write('still writable\n'); writer.flush()
        self.assertFalse(expired.exists())
        self.assertFalse(compressed.exists())
        self.assertTrue(boundary.exists())
        self.assertTrue(extra_link.exists())
        self.assertIn('still writable', active.read_text())

    def test_protostats_missing_or_indirect_blocks_all_deletion(self):
        expired = self.file('protostats.20260901', 40)
        other = self.file('loopstats.20260901', 40)
        active = self.stats/'protostats'; active.unlink()
        self.assertNotEqual(self.run_rotation().returncode, 0)
        self.assertTrue(expired.exists()); self.assertTrue(other.exists())
        active.symlink_to(self.stats/'loopstats')
        self.assertNotEqual(self.run_rotation().returncode, 0)
        self.assertTrue(expired.exists()); self.assertTrue(other.exists())

    def test_missing_or_symlink_active_file_blocks_cleanup(self):
        old = self.file('loopstats.20260901', 40)
        active = self.stats/'clockstats'
        active.unlink()
        result = self.run_rotation()
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(old.exists())
        active.symlink_to(self.stats/'peerstats')
        result = self.run_rotation()
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(old.exists())


if __name__ == '__main__':
    unittest.main()
