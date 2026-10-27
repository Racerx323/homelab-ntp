#!/usr/bin/python3
"""Offline rejection, evidence-retention and no-content-read boundaries."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import types
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

r=load('effects_review','scripts/review-maintenance-effects.py')
w=load('effects','scripts/inspect-maintenance-effects.py')
w.m=load('snapshot','scripts/maintenance-snapshot.py')

class EffectsTests(unittest.TestCase):
    def test_wrong_hash_before_auth_or_receipt(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);r.c.create(p/'inspection.tar',b'invalid')
            with patch.object(r.c,'authentication',side_effect=AssertionError('auth attempted')):
                with self.assertRaisesRegex(ValueError,'SHA-256'):r.inspect(p,'0'*64)
            self.assertFalse((p/'execution.json').exists())

    def test_unaccepted_successor_baseline_rejected_before_seal(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);prior=p/'prior';prior.mkdir(mode=0o700)
            r.c.create(prior/'capture.json',b'{}')
            r.c.create(prior/'outcome.json',{'capture_accepted':False})
            args=types.SimpleNamespace(directory=p/'next',baseline=prior,qualification=p/'unused')
            with self.assertRaisesRegex(ValueError,'accepted baseline'):r.seal(args)
            self.assertFalse((p/'next').exists())

    def test_baseline_capture_drift_rejected_before_seal(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);prior=p/'prior';prior.mkdir(mode=0o700)
            r.c.create(prior/'capture.json',b'{}')
            r.c.create(prior/'outcome.json',{'capture_accepted':True,'capture_sha256':'0'*64})
            args=types.SimpleNamespace(directory=p/'next',baseline=prior,qualification=p/'unused')
            with self.assertRaisesRegex(ValueError,'baseline capture hash'):r.seal(args)
            self.assertFalse((p/'next').exists())

    def test_credential_sentinel_metadata_never_reads_content(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'auth.key';p.write_text('not-exported')
            with patch.object(Path,'open',side_effect=AssertionError('content read')):
                value=w.metadata(p)
            self.assertEqual(value['size'],12)
            self.assertNotIn('text',value)

    def test_indirect_parent_not_followed(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'dir').mkdir();(p/'link').symlink_to(p/'dir',target_is_directory=True)
            self.assertIn('unresolved_indirect_parent',w.metadata(p/'link'/'auth.key'))
            with self.assertRaisesRegex(ValueError,'indirect'):w.tree(p/'link'/'child')

    def test_file_symlink_records_only_destination(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'hook';p.symlink_to('/nonexistent-target')
            rows=w.tree(p)
            self.assertEqual(rows[str(p)]['link'],'/nonexistent-target')

    def test_real_bootstrap_rejects_controller_identity(self):
        files={n:p.read_bytes() for n,p in r.SOURCES.items()}
        files['baseline.json']=b'{}'
        result=subprocess.run(['/usr/bin/python3','-I','-B','-c',
            'import sys;exec(sys.stdin.buffer.readline())'],input=r.payload({'operation_id':'offline-test'},files),
            capture_output=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        data=json.loads(result.stdout)
        self.assertFalse(data['capture_complete']);self.assertIn('identity',data['error'])
        self.assertEqual(data['commands'],{})

    def test_native_inhibit_condition_and_restoration(self):
        # Native condition evaluation only; no unit installation or manager action.
        with tempfile.TemporaryDirectory() as d:
            marker=Path(d)/'inhibit'
            def status():
                return subprocess.run(['/usr/bin/systemd-analyze','condition',
                    'ConditionPathExists=!'+str(marker)],capture_output=True,timeout=10).returncode
            self.assertEqual(status(),0)
            marker.write_text('controller-only qualification')
            self.assertEqual(status(),1)
            marker.unlink()
            self.assertEqual(status(),0)

    def test_partial_capture_preserved_on_transport_failure(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)
            spec={'purpose':'test','authentication':{'identity_file':'unused'}}
            partial={'operation_id':'test','capture_complete':False,'error':'stopped','scripts':{'retained':True}}
            class H:
                def bounded(self,*a,**k):return {'returncode':1,'stdout':json.dumps(partial),'stderr':'native failure'}
            with patch.object(r,'check',return_value=(spec,{'helper.py':b''})), \
                 patch.object(r.c,'authentication',return_value=spec['authentication']), \
                 patch.object(r.c,'module',return_value=H()),patch.object(r.c,'ssh',return_value=[]), \
                 patch.object(r,'payload',return_value=b''):
                result=r.inspect(p,'approved-test-digest')
            self.assertFalse(result['capture_complete'])
            self.assertEqual(json.loads((p/'capture.json').read_text()),partial)
            self.assertTrue((p/'execution.json').exists())
            self.assertEqual(json.loads((p/'transport.json').read_text())['returncode'],1)

if __name__=='__main__':unittest.main()
