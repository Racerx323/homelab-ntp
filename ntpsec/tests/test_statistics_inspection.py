#!/usr/bin/python3
"""Offline metadata, target rejection and sealed read-only inspection checks."""
import importlib.util
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(path):
    s = importlib.util.spec_from_file_location(path.stem, path)
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m)
    return m


r = load(ROOT/'scripts/run-statistics-inspection.py')
r.h = load(ROOT/'scripts/run-production-inspection.py')


class InspectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_metadata_only_preserves_aliases_and_never_follows_symlink(self):
        stats = self.root/'stats'; stats.mkdir()
        active = stats/'loopstats'; active.write_text('private statistics')
        os.link(active, stats/'loopstats.20261015')
        (stats/'peerstats.20261015').symlink_to('/nonexistent')
        before = active.read_bytes()
        result = r.inventory(stats)
        rows = {v['name']: v for v in result['files']}
        self.assertEqual(rows['loopstats']['inode'], rows['loopstats.20261015']['inode'])
        self.assertEqual(rows['loopstats']['links'], 2)
        self.assertTrue(rows['peerstats.20261015']['symlink'])
        self.assertNotIn('private statistics', json.dumps(result))
        self.assertEqual(active.read_bytes(), before)
        indirect = self.root/'indirect'; indirect.symlink_to(stats)
        with self.assertRaises(ValueError): r.inventory(indirect)

    def test_wrong_target_cannot_run_any_command(self):
        with patch.object(r.socket, 'gethostname', return_value='wrong'), patch.object(r.h, 'bounded') as command:
            result = r.collect({'operation_id': 'fixture'})
        self.assertFalse(result['capture_complete']); command.assert_not_called()

    def test_collector_success_and_command_failure_are_distinct(self):
        (self.root/'boot').write_text('boot\n')
        (self.root/'fds').mkdir()
        stats = self.root/'stats'; stats.mkdir()
        def path(*parts):
            name = str(Path(*parts))
            return {'/proc/sys/kernel/random/boot_id': self.root/'boot',
                    '/proc/123/fd': self.root/'fds', '/var/log/ntpstats': stats}.get(name, Path(*parts))
        calls = []
        fail = [False]
        def command(argv, **kwargs):
            calls.append(argv)
            text = 'MainPID=123\n' if argv[:3] == ['/usr/bin/systemctl', 'show', 'timeservice.service'] else ''
            code = 2 if fail[0] and '--version' in argv else 0
            return {'argv': argv, 'returncode': code, 'stdout': text, 'stderr': ''}
        spec = {'operation_id': 'fixture', 'boot_id': 'boot', 'service_identity': {'MainPID': '123'}}
        with patch.object(r, 'Path', side_effect=path), patch.object(r.os, 'geteuid', return_value=0), \
             patch.object(r.socket, 'gethostname', return_value='j2-svntp1'), \
             patch.object(r, 'maintenance_files', return_value=[]), \
             patch.object(r.h, 'file_record', return_value={'missing': True}), \
             patch.object(r.h, 'bounded', side_effect=command):
            self.assertTrue(r.collect(spec)['capture_complete'])
            fail[0] = True
            self.assertFalse(r.collect(spec)['capture_complete'])
        self.assertTrue(all(a[0] in {'/usr/bin/systemctl', '/usr/bin/dpkg-query', '/usr/sbin/logrotate', '/usr/bin/find', '/usr/bin/findmnt'} for a in calls))
        self.assertTrue(all('--version' in a for a in calls if a[0] in {'/usr/sbin/logrotate', '/usr/bin/find'}))

    def baseline(self):
        d = self.root/'baseline'; d.mkdir(mode=0o700)
        spec = {'operation_id': 'fixture', 'boot_id': 'boot', 'service_identity': {'MainPID': '123'}}
        with tarfile.open(d/'mail-reporting.tar', 'w') as t:
            for name, raw in {'spec.json': r.h.encoded(spec), 'known_hosts': b'fixture\n'}.items():
                m = tarfile.TarInfo(name); m.size = len(raw); t.addfile(m, io.BytesIO(raw))
        (d/'result.json').write_bytes(r.h.encoded({'accepted': True, 'bundle_sha256': r.h.sha((d/'mail-reporting.tar').read_bytes())}))
        (d/'stdout.txt').write_bytes(r.h.encoded({'accepted': True, 'operation_id': 'fixture', 'spec_sha256': r.h.sha(r.h.encoded(spec))}))
        for p in d.iterdir(): p.chmod(0o600)
        return d

    def test_seal_and_review_tamper_rejection(self):
        d = self.root/'inspection'
        result = r.seal(types.SimpleNamespace(baseline=self.baseline(), output=d))
        spec, _ = r.prepare(d, result['sha256'])
        self.assertEqual(spec['boot_id'], 'boot')
        (d/'review.md').write_text('changed')
        with self.assertRaisesRegex(ValueError, 'review drift'): r.prepare(d, result['sha256'])

    def test_followup_seals_from_completed_inspection(self):
        initial = self.root/'initial'
        sealed = r.seal(types.SimpleNamespace(baseline=self.baseline(), output=initial))
        spec, _ = r.prepare(initial, sealed['sha256'])
        (initial/'result.json').write_bytes(r.h.encoded({'capture_complete': True, 'bundle_sha256': sealed['sha256']}))
        (initial/'stdout.txt').write_bytes(r.h.encoded({'capture_complete': True,
            'operation_id': spec['operation_id'], 'spec_sha256': r.h.sha(r.h.encoded(spec))}))
        output = self.root/'followup'
        result = r.seal(types.SimpleNamespace(baseline=initial, output=output, followup=True))
        followup, _ = r.prepare(output, result['sha256'])
        self.assertTrue(followup['followup'])
        self.assertIn('65536 descriptors', (output/'review.md').read_text())
        (initial/'result.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'accepted baseline'):
            r.seal(types.SimpleNamespace(baseline=initial, output=self.root/'bad', followup=True))

    def test_writer_snapshot_finds_non_main_pid_and_writable_fd(self):
        proc = self.root/'proc'; proc.mkdir()
        p = proc/'456'; p.mkdir(); (p/'fd').mkdir(); (p/'fdinfo').mkdir()
        (p/'stat').write_text('456 (ntpd worker) '+ ' '.join(['0']*19+['12345']))
        (p/'comm').write_text('ntpd\n'); (p/'exe').symlink_to('/usr/local/sbin/ntpd')
        stats = self.root/'stats'; stats.mkdir()
        active = stats/'protostats'; active.write_text('must not be read')
        (p/'fd/7').symlink_to(active)
        (p/'fdinfo/7').write_text('flags:\t0100001\n')
        found = r.writer_snapshot(proc, str(stats))
        row = found['processes'][0]
        self.assertEqual(row['start_ticks'], '12345')
        self.assertTrue(row['descriptors'][0]['writable'])
        self.assertNotIn('must not be read', json.dumps(found))
        self.assertTrue(r.inventory(stats)['files'][0]['recognized'])
        (p/'fd/7').unlink()
        self.assertEqual(r.writer_snapshot(proc, str(stats))['processes'][0]['descriptors'], [])
        (p/'stat').unlink()
        self.assertEqual(r.writer_snapshot(proc, str(stats))['races'], [str(p)])

    def test_maintenance_followup_captures_nested_references_and_symlink_gaps(self):
        wrapper = self.root/'wrapper'; wrapper.write_text('guard line\nlogrotate /etc/logrotate.conf\n')
        nested = self.root/'nested'; nested.write_text('ExecStart=/usr/local/sbin/ntpstats-clean\n')
        link = self.root/'link'; link.symlink_to('/missing')
        # Real fixture files prove nested references and symlinks stay visible.
        with patch.object(r.os, 'walk', return_value=[(str(self.root), [], ['wrapper', 'nested', 'link'])]):
            result = r.maintenance_followup()
        self.assertTrue(any(v['path'] == str(link) for v in result['indirect']))
        self.assertTrue(any(v.get('path') == '/usr/local/sbin/ntpstats-clean' for v in result['references']))

    def test_single_use_prevents_transport(self):
        d = self.root/'inspection'
        result = r.seal(types.SimpleNamespace(baseline=self.baseline(), output=d))
        (d/'execution.json').write_text('{}')
        with patch.object(r.h, 'bounded') as command:
            with self.assertRaises(FileExistsError):
                r.execute(types.SimpleNamespace(directory=d, sha256=result['sha256']))
            command.assert_not_called()


if __name__ == '__main__': unittest.main()
