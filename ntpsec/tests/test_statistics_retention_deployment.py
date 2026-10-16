#!/usr/bin/python3
"""Offline transaction, scope binding and conditional recovery checks."""
import importlib.util
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
import time
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    s = importlib.util.spec_from_file_location(name,ROOT/'scripts'/name)
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m


r = load('run-statistics-retention.py')
w = r.w


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.stats = self.root/'stats'; self.stats.mkdir()
        self.rule = self.root/'rules/ntpstats-retention'; self.rule.parent.mkdir()
        self.control = self.root/'control'
        for name,value in [('STATS',self.stats),('RULE',self.rule),('CONTROL',self.control)]:
            p = patch.object(w,name,value); p.start(); self.addCleanup(p.stop)
        for name in w.STREAMS:
            p = self.stats/name; p.write_text('active')
            os.link(p,self.stats/(name+'.20200101'))
            os.utime(p,(1,1))

    def test_preview_matches_age_and_link_rules(self):
        now = time.time()
        for name,age in [('protostats.20200102',30*86400),('loopstats.20200102',30*86400-1),
                         ('clockstats.20200102.gz',31*86400),('unknown.20200102',40*86400)]:
            p = self.stats/name; p.write_text('fixture'); os.utime(p,(now-age,now-age))
        (self.stats/'peerstats.20200102').symlink_to(self.stats/'unknown.20200102')
        self.assertEqual([p['name'] for p in w.preview(now)],['clockstats.20200102.gz','protostats.20200102'])
        (self.stats/'protostats').unlink()
        with self.assertRaises(FileNotFoundError): w.preview(now)

    def operation(self, fail=None, foreign=False):
        spec = {'operation_id':'fixture','approved_deletion_preview':[]}
        files = {'candidate':b'fixture config\n','fixtures.py':b'fixture tests\n'}
        def record(path):
            row = r.h.file_record(path)
            if not row.get('missing') and not row.get('error'):
                row.update(uid=0,gid=0)
            return row
        helper = types.SimpleNamespace(sha=r.h.sha,encoded=r.h.encoded,file_record=record)
        op = w.Deployment(spec,{},files,helper); op.root = self.root/'operation'
        op.continuity = lambda: None
        op.guards = lambda: None
        op.active = lambda: {'protostats':{'inode':123,'bytes':7}}
        def command(argv,timeout=20,env=None):
            if fail and fail in argv:
                if foreign: self.rule.write_text('foreign edit')
                raise ValueError('injected failure')
            return ''
        op.command = command
        # Ownership is modeled as root; the test filesystem stays unprivileged.
        original = w.directory
        op_dir = patch.object(w,'directory',side_effect=lambda p,owner=None,mode=None: original(p,None,mode))
        op_dir.start(); self.addCleanup(op_dir.stop)
        return op

    def test_success_installs_exact_rule_but_acceptance_stays_pending(self):
        op = self.operation(); result = op.run()
        self.assertTrue(result['installed'],result)
        self.assertFalse(result['retention_accepted'])
        self.assertEqual(result['checks'],dict.fromkeys(w.CHECKS,True))
        self.assertEqual(self.rule.read_bytes(),op.files['candidate'])
        self.assertEqual(self.rule.stat().st_mode & 0o777,0o644)
        self.assertEqual(self.control.stat().st_mode & 0o777,0o700)
        self.assertEqual((self.control/'trigger').stat().st_mode & 0o777,0o600)
        self.assertTrue((op.root/'state.json').exists())

    def test_early_failure_and_nonempty_preview_do_not_install(self):
        op = self.operation(); op.continuity = lambda: (_ for _ in ()).throw(ValueError('identity drift'))
        result = op.run()
        self.assertFalse(result['installed']); self.assertFalse(op.root.exists())
        self.assertFalse(self.rule.exists()); self.assertFalse(self.control.exists())
        op = self.operation()
        p = self.stats/'protostats.20200102'; p.touch(); os.utime(p,(1,1))
        result = op.run()
        self.assertIn('preview changed',result['error'])
        self.assertFalse(self.rule.exists()); self.assertFalse(self.control.exists())

    def test_debug_failure_restores_absence(self):
        op = self.operation('--debug'); result = op.run()
        self.assertIn('restored',result['rollback'])
        self.assertFalse(self.rule.exists()); self.assertFalse(self.control.exists())

    def test_run_failure_removes_only_candidate_and_keeps_evidence(self):
        op = self.operation('--force'); result = op.run()
        self.assertFalse(result['installed']); self.assertIn('restored',result['rollback'])
        self.assertFalse(self.rule.exists()); self.assertFalse(self.control.exists())
        self.assertTrue((op.root/'state.json').exists())

    def test_foreign_rule_holds_recovery(self):
        op = self.operation('--force',foreign=True); result = op.run()
        self.assertEqual(result['rollback'],'held')
        self.assertEqual(self.rule.read_text(),'foreign edit')

    def test_existing_paths_never_overwritten(self):
        self.rule.write_text('existing')
        op = self.operation(); result = op.run()
        self.assertFalse(result['installed']); self.assertEqual(self.rule.read_text(),'existing')
        self.assertFalse(self.control.exists())

    def baseline(self):
        d = self.root/'inspection'; d.mkdir(mode=0o700)
        service = {'MainPID':'814'}
        spec = {'operation_id':'inspection','followup':True,'boot_id':'boot','service_identity':service}
        with tarfile.open(d/'inspection.tar','w') as t:
            for name,raw in {'spec.json':r.h.encoded(spec),'known_hosts':b'fixture host key'}.items():
                m = tarfile.TarInfo(name); m.size = len(raw); t.addfile(m,io.BytesIO(raw))
        digest = r.h.sha((d/'inspection.tar').read_bytes())
        writer = {'pid':'836','start_ticks':'2684','exe':'/usr/local/sbin/ntpd','comm':'ntpd','descriptors':[
            {'writable':True,'device':1,'inode':i} for i in range(4)]}
        record = {'sha256':'0'*64,'uid':0,'gid':0,'mode':0o644}
        capture = {'operation_id':'inspection','spec_sha256':r.h.sha(r.h.encoded(spec)),'capture_complete':True,
                   'writers_before':{'processes':[writer]},'writers_after':{'processes':[writer]},
                   'statistics':{'directory':{'uid':999,'gid':985,'mode':0o750},'files':[
                       {'name':name,'date':None,'regular':True,'symlink':False,'links':2,'device':1,'inode':i}
                       for i,name in enumerate(w.STREAMS)]},
                   'commands':{key:{'stdout':'MainPID=814\nLoadState=loaded\n'} for key in ('ntp_before','ntp_after')},
                   'configuration':record,
                   'maintenance_followup':{'files':[{'path':p,'record':record} for p in ('/etc/logrotate.conf','/etc/logrotate.d/apt')]}}
        (d/'result.json').write_bytes(r.h.encoded({'bundle_sha256':digest,'capture_complete':True,'returncode':0}))
        (d/'stdout.txt').write_bytes(r.h.encoded(capture))
        for p in d.iterdir(): p.chmod(0o600)
        return d,digest

    def test_seal_binding_tamper_and_single_use(self):
        baseline,digest = self.baseline(); output = self.root/'sealed'
        result = r.seal(types.SimpleNamespace(inspection=baseline,inspection_sha256=digest,output=output))
        spec,files = r.prepare(output/r.BUNDLE,result['sha256'])
        self.assertEqual(spec['approved_deletion_preview'],[])
        self.assertIn('protostats',files['candidate'].decode())
        (output/'execution.json').write_text('{}')
        with patch.object(r.h,'bounded') as transport:
            with self.assertRaises(FileExistsError):
                r.execute(types.SimpleNamespace(bundle=output/r.BUNDLE,sha256=result['sha256']))
            transport.assert_not_called()
        (output/'review.md').write_text('changed')
        with self.assertRaisesRegex(ValueError,'approval input drift'):
            r.prepare(output/r.BUNDLE,result['sha256'])
        with self.assertRaisesRegex(ValueError,'archive mismatch'):
            r.prepare(output/r.BUNDLE,'0'*64)

    def test_incomplete_inspection_rejected(self):
        baseline,digest = self.baseline()
        (baseline/'result.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'complete approved inspection'):
            r.seal(types.SimpleNamespace(inspection=baseline,inspection_sha256=digest,output=self.root/'sealed'))


if __name__ == '__main__': unittest.main()
