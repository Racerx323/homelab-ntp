#!/usr/bin/python3
"""Offline scope, redaction, metadata sampling and baseline-binding checks."""
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
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m


r = load(ROOT/'scripts/run-statistics-inspection.py')
r.h = load(ROOT/'scripts/run-production-inspection.py')


class MonitoringTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_settings_redact_environment_and_never_execute_plugins(self):
        etc = self.root/'etc'; (etc/'munin/plugin-conf.d').mkdir(parents=True)
        (etc/'munin/munin-node.conf').write_text('host 10.1.0.51\nport 4949\nallow ^10\\.1\\.3\\.83$\ntls_private_key SECRET-KEY-PATH\n')
        (etc/'munin/plugin-conf.d/test').write_text('[df]\nuser root\nenv.password NEVER-EXPORT\n')
        (etc/'munin/plugins').mkdir()
        (etc/'munin/plugins/df').symlink_to('/missing/plugin')
        (etc/'cron.d').mkdir()
        (etc/'cron.d/disk-alert').write_text('* * * * * root command --password NEVER-EXPORT # diskspace\n')
        result = r.monitoring_configuration(etc, self.root/'no-vendor')
        text = json.dumps(result)
        self.assertNotIn('NEVER-EXPORT', text); self.assertNotIn('SECRET-KEY-PATH', text)
        self.assertIn('env.password', text)
        self.assertEqual(result['plugins'][0]['target'], '/missing/plugin')
        self.assertEqual(result['job_references'][0]['matched_terms'], ['diskspace'])

    def test_indirect_paths_are_reported_without_following(self):
        etc = self.root/'etc'; (etc/'munin').mkdir(parents=True)
        (etc/'munin/plugin-conf.d').symlink_to('/nonexistent')
        (etc/'munin/munin-node.conf').symlink_to('/nonexistent-secret')
        result = r.monitoring_configuration(etc, self.root/'no-vendor')
        self.assertEqual(len(result['indirect']), 2)
        self.assertFalse(result['settings'])

    def test_file_count_bound(self):
        etc = self.root/'etc'; (etc/'munin/plugin-conf.d').mkdir(parents=True)
        for i in range(64): (etc/'munin/plugin-conf.d'/str(i)).touch()
        with self.assertRaisesRegex(ValueError, 'count bound'):
            r.monitoring_configuration(etc, self.root/'no-vendor')

    def test_growth_deduplicates_hardlinks_and_preserves_negative_changes(self):
        a = {'device':1,'inode':2,'name':'loopstats','bytes':100,'regular':True,'recognized':True}
        before = {'files':[a,dict(a,name='loopstats.20261020')]}
        after = {'files':[dict(a,bytes=90),dict(a,name='loopstats.20261020',bytes=90),dict(a,inode=3,bytes=5)]}
        result = r.growth_summary(before,after)
        self.assertEqual(len(result['same_inode_deltas']),1)
        self.assertEqual(result['same_inode_deltas'][0]['bytes_delta'],-10)
        self.assertEqual(result['new_inodes'],1)
        self.assertFalse(result['sustained_budget_accepted'])

    def test_wrong_target_runs_no_commands(self):
        with patch.object(r.socket,'gethostname',return_value='wrong'), patch.object(r.h,'bounded') as cmd:
            result = r.collect_monitoring({'operation_id':'fixture','poller':'master.example'})
        self.assertFalse(result['capture_complete']); cmd.assert_not_called()

    def test_collection_success_and_command_failure_without_real_wait_or_host_contact(self):
        boot = self.root/'boot'; boot.write_text('boot\n')
        def path(*parts):
            p = Path(*parts)
            return boot if str(p) == '/proc/sys/kernel/random/boot_id' else p
        def command(argv,**kwargs):
            text = 'MainPID=123\n' if argv[:3] == ['/usr/bin/systemctl','show','timeservice.service'] else ''
            return {'argv':argv,'returncode':0,'stdout':text,'stderr':''}
        sample = {'files':[],'available_bytes':20*1024**3}
        fs = types.SimpleNamespace(f_files=100,f_favail=90)
        spec = {'operation_id':'fixture','boot_id':'boot','service_identity':{'MainPID':'123'},
                'sample_interval_seconds':60,'poller':'master.example'}
        with patch.object(r,'Path',side_effect=path), patch.object(r.os,'geteuid',return_value=0), \
             patch.object(r.socket,'gethostname',return_value='j2-svntp1'), \
             patch.object(r,'inventory',side_effect=lambda p:dict(sample)), \
             patch.object(r.os,'statvfs',return_value=fs), patch.object(r,'monitoring_configuration',return_value={}), \
             patch.object(r.h,'file_record',return_value={'missing':True}), \
             patch.object(r.h,'bounded',side_effect=command) as cmd, \
             patch.object(r.time,'monotonic',side_effect=[0,1,60]), patch.object(r.time,'sleep') as wait:
            result = r.collect_monitoring(spec)
        self.assertTrue(result['capture_complete'],result)
        self.assertFalse(result['polling_accepted']); wait.assert_called_once_with(59)
        for call in cmd.call_args_list:
            self.assertIn(call.args[0][0],('/usr/bin/systemctl','/usr/bin/dpkg-query','/usr/bin/ss'))
        with patch.object(r,'Path',side_effect=path), patch.object(r.os,'geteuid',return_value=0), \
             patch.object(r.socket,'gethostname',return_value='j2-svntp1'), \
             patch.object(r.h,'bounded',return_value={'returncode':2,'stdout':'','stderr':'failed'}):
            self.assertFalse(r.collect_monitoring(spec)['capture_complete'])

    def baseline(self):
        d = self.root/'baseline'; d.mkdir(mode=0o700)
        spec = {'operation_id':'installed','purpose':'statistics-retention','boot_id':'boot'}
        archive = {'spec.json':r.h.encoded(spec),'known_hosts':b'fixture key',
                   'baseline.json':r.h.encoded({'service':{'MainPID':'123'}})}
        with tarfile.open(d/'statistics-retention.tar','w') as t:
            for n,raw in archive.items():
                m = tarfile.TarInfo(n);m.size=len(raw);t.addfile(m,io.BytesIO(raw))
        (d/'result.json').write_bytes(r.h.encoded({'installed':True,'returncode':0,
                                    'bundle_sha256':r.h.sha((d/'statistics-retention.tar').read_bytes())}))
        (d/'stdout.txt').write_bytes(r.h.encoded({'operation_id':'installed','spec_sha256':r.h.sha(r.h.encoded(spec)),
                     'installed':True,'checks':dict.fromkeys(('preflight','target_fixtures','debug','empty_preview','first_run','continuity'),True)}))
        for p in d.iterdir():p.chmod(0o600)
        return d

    def test_seal_from_installed_baseline_and_reject_review_tamper(self):
        d = self.root/'monitoring'
        result = r.seal(types.SimpleNamespace(baseline=self.baseline(),output=d,monitoring=True,poller='master.example'))
        spec,_ = r.prepare(d,result['sha256'])
        self.assertTrue(spec['monitoring']);self.assertEqual(spec['sample_interval_seconds'],60)
        self.assertEqual(spec['service_identity'],{'MainPID':'123'})
        self.assertIn('master.example',(d/'review.md').read_text())
        (d/'review.md').write_text('tampered')
        with self.assertRaisesRegex(ValueError,'review drift'):r.prepare(d,result['sha256'])

    def test_incomplete_baseline_rejected(self):
        b = self.baseline(); (b/'result.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'accepted baseline'):
            r.seal(types.SimpleNamespace(baseline=b,output=self.root/'bad',monitoring=True,poller='master.example'))


if __name__ == '__main__': unittest.main()
