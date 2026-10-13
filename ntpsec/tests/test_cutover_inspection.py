#!/usr/bin/python3
"""Offline retained-evidence retrieval, closed scope and rejection tests."""
import base64
import copy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
s=importlib.util.spec_from_file_location('inspection',ROOT/'scripts/run-cutover-inspection.py')
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
c=m.load(ROOT/'scripts/run-service-cutover.py')


def bind(spec,files):
    spec['members']={n:m.sha(files[n]) for n in set(m.PATHS)|m.EXTRA}
    files['spec.json']=m.encoded(spec);files['review.md']=m.review(spec).encode()
    files['manifest.json']=m.encoded({n:m.sha(v) for n,v in files.items() if n!='manifest.json'})


def fixture():
    old=dict(hostname='fixture',kernel='fixture-kernel',boot_id='fixture-boot',
             endpoints=['192.0.2.1','2001:db8::1'],old_ipv4='192.0.2.1',stage='/var/lib/ntp-acquire-trial',members={})
    state=dict(phase='recovered',apply_epoch=100,recovered_epoch=150)
    checksum='a'*64;source=m.encoded(old)
    receipt=dict(state='recovered',spec_sha256=m.sha(source),state_sha256=m.sha(m.encoded(state)),bundle_sha256=checksum)
    state['transient_cleanup']=True
    files={n:(ROOT/p).read_bytes() for n,p in m.PATHS.items()}
    spec={k:old[k] for k in ('hostname','kernel','boot_id','endpoints','old_ipv4')}
    spec.update(schema=1,operation_id='inspect-fixture',stage='/var/lib/ntp-inspect-inspect-fixture',
                source_stage=old['stage'],source_bundle_sha256=checksum,prepared_epoch=200,expires_epoch=86600,journal_since=100,journal_until=151)
    files.update({'helper.py':b'# fixture helper\n','source-spec.json':source,
                  'source-cleanup.json':m.encoded({'spec_sha256':m.sha(source),'result':state}),
                  'source-receipt.json':m.encoded(receipt),'known_hosts':b'fixture key\n','launch.sh':m.launcher(spec['stage'])})
    bind(spec,files);return spec,files


class LocalFiles:
    @staticmethod
    def read(path,limit=m.LIMIT):
        raw=path.read_bytes()
        if len(raw)>limit:raise ValueError('bounded file exceeded')
        return raw
    @staticmethod
    def create(path,raw):
        with path.open('xb') as stream:stream.write(raw)


class BindingTests(unittest.TestCase):
    def test_frozen_inputs_and_all_payloads(self):
        spec,files=fixture();m.validate(spec,files)
        for mode in ('start','readback','cleanup'):compile(c.payload(spec,files,mode),mode,'exec')
        self.assertIn(b'cd /\nexec /usr/bin/python3 -I -B ',files['launch.sh'])

    def test_drift_rejected(self):
        spec,files=fixture()
        for key,value in [('hostname','other'),('kernel','other'),('boot_id','other'),('endpoints',['192.0.2.2']),
                          ('stage','/tmp/unsafe'),('operation_id','../escape'),('source_stage','/tmp/old'),
                          ('journal_since',101),('journal_until',152),('journal_since',True),
                          ('expires_epoch',90000),('source_bundle_sha256','x'*64)]:
            with self.subTest(key=key),self.assertRaises(ValueError):m.validate(dict(spec,**{key:value}),files)
        changed=dict(files);changed['stage.py']+=b'# drift'
        with self.assertRaises(ValueError):m.validate(spec,changed)

    def test_rebound_bad_recovery_rejected(self):
        for name in ('source-cleanup.json','source-receipt.json'):
            spec,files=fixture();row=json.loads(files[name])
            if name=='source-cleanup.json':row['result']['transient_cleanup']=False
            else:row['state']='accepted'
            files[name]=m.encoded(row);bind(spec,files)
            with self.assertRaises(ValueError):m.validate(spec,files)

    def test_receipt_requires_matching_complete_evidence(self):
        spec,files=fixture()
        evidence={n:{'sha256':m.sha(b'data'),'base64':base64.b64encode(b'data').decode()} for n in m.CAPTURE_FILES}
        report=dict(phase='captured',source_preserved=True,evidence=evidence)
        results=dict.fromkeys(spec['endpoints'],report)
        receipt=m.terminal_receipt(spec,files,'b'*64,results)
        self.assertFalse(receipt['time_service_accepted'])
        with self.assertRaises(ValueError):m.terminal_receipt(spec,files,'b'*64,{spec['endpoints'][0]:report})
        bad=copy.deepcopy(report);bad['evidence']['journal.stdout']['sha256']='0'*64
        with self.assertRaises(ValueError):m.terminal_receipt(spec,files,'b'*64,dict.fromkeys(spec['endpoints'],bad))
        bad=copy.deepcopy(report);bad['evidence'].pop('journal.stdout')
        with self.assertRaises(ValueError):m.terminal_receipt(spec,files,'b'*64,dict.fromkeys(spec['endpoints'],bad))

    def test_source_lock_protection(self):
        spec,files=fixture()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);spec['source_stage']=tmp
            (root/'.lock').symlink_to(root/'missing')
            helper=SimpleNamespace(ancestors=lambda p:None)
            with self.assertRaises(OSError):m.source_lock(helper,spec,files)
            (root/'.lock').unlink();(root/'.lock').write_bytes(b'');(root/'.lock').chmod(0o666)
            with self.assertRaises(ValueError):m.source_lock(helper,spec,files)

    def test_start_rejects_wrong_caller_before_staging(self):
        spec,files=fixture()
        with patch.object(m.os,'geteuid',return_value=1000),patch.object(m.Path,'mkdir') as mkdir:
            with self.assertRaises(ValueError):m.entry(spec,files,'start')
            mkdir.assert_not_called()

    def test_expired_start_rejects_before_staging(self):
        spec,files=fixture()
        with patch.object(m.os,'geteuid',return_value=0),patch.dict(m.os.environ,{'SUDO_USER':'ama'}), \
             patch.object(m.socket,'gethostname',return_value=spec['hostname']), \
             patch.object(m.os,'uname',return_value=SimpleNamespace(release=spec['kernel'])), \
             patch.object(m.Path,'read_text',return_value=spec['boot_id']), \
             patch.object(m.time,'time',return_value=spec['expires_epoch']),patch.object(m.Path,'mkdir') as mkdir:
            with self.assertRaises(ValueError):m.entry(spec,files,'start')
            mkdir.assert_not_called()


class CaptureTests(unittest.TestCase):
    def test_command_timeout_retains_status_without_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);argv=['/usr/bin/journalctl','--quiet']
            with patch.object(m.subprocess,'run',side_effect=m.subprocess.TimeoutExpired(argv,20)) as run:
                with self.assertRaises(ValueError):m.command(LocalFiles,root,'journal',argv)
            self.assertEqual(run.call_count,1)
            self.assertEqual(json.loads((root/'journal.json').read_bytes())['status'],'timeout')
            self.assertTrue((root/'journal.stderr').exists())

    def run_capture(self,variant='good'):
        with tempfile.TemporaryDirectory() as tmp:
            parent=Path(tmp);source=parent/'original';root=parent/'inspection';source.mkdir();root.mkdir()
            spec,files=fixture();spec.update(source_stage=str(source),stage=str(root))
            journal=['/usr/bin/journalctl','--quiet','--no-pager','--output=short-unix','--since=@100',
                     '--unit=timeservice.service','--unit=avahi-daemon.service','--priority=0..3']
            (source/'before.json').write_bytes(m.encoded({'files':{'/etc/ntp.conf':None}}))
            (source/'state.json').write_bytes(m.encoded({'phase':'recovered'}))
            (source/'commands.jsonl').write_bytes(m.encoded({'argv':journal,'stdout':'retained error','stderr':'','status':0}))
            original={p.name:p.read_bytes() for p in source.iterdir()};calls=[]
            def command(h,r,name,argv):
                calls.append(argv)
                if variant=='command-failure':raise ValueError('diagnostic command failed')
                raw=b'{}\n'*(400 if variant=='truncated' else 1) if name=='journal' else b'ActiveState=inactive\n'
                h.create(r/(name+'.json'),m.encoded({'argv':argv,'status':0}))
                h.create(r/(name+'.stdout'),raw);h.create(r/(name+'.stderr'),b'')
                if variant=='drift' and name=='services':(source/'state.json').write_bytes(b'{}')
                return raw
            with patch.object(m,'source_lock',return_value=os.open(source,os.O_RDONLY)),patch.object(m,'command',side_effect=command):
                report=m.capture(LocalFiles,spec,files)
            if variant!='drift':self.assertEqual(original,{p.name:p.read_bytes() for p in source.iterdir()})
            self.assertEqual(json.loads((root/'report.json').read_bytes()),report)
            return report,calls

    def test_read_only_collection_preserves_original_bytes(self):
        report,calls=self.run_capture()
        self.assertEqual(report['phase'],'captured');self.assertTrue(report['source_preserved'])
        self.assertEqual(set(report['evidence']),set(m.CAPTURE_FILES))
        self.assertEqual(len(calls),2);self.assertIn('--boot=fixture-boot',calls[0]);self.assertIn('--until=@151',calls[0])
        self.assertEqual(calls[1][:2],['/usr/bin/systemctl','show'])
        self.assertNotIn('MainPID',str(calls[1]));self.assertNotIn('restart',str(calls))

    def test_incomplete_or_failed_capture_holds(self):
        for variant in ('truncated','command-failure','drift'):
            with self.subTest(variant=variant):
                report,_=self.run_capture(variant)
                self.assertEqual(report['phase'],'held');self.assertIsNone(report['source_preserved'])

    def test_aggregate_limit_holds_and_retains_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);spec,files=fixture();spec['stage']=tmp
            for name in m.CAPTURE_FILES:(root/name).write_bytes(b'1234')
            with patch.object(m,'collect',return_value={}),patch.object(m,'LIMIT',8):report=m.capture(LocalFiles,spec,files)
            self.assertEqual(report['phase'],'held');self.assertEqual(len(report['evidence']),2)
            self.assertTrue(all((root/n).exists() for n in m.CAPTURE_FILES))

    def test_cleanup_does_not_claim_unverified_preservation(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec,files=fixture();spec['stage']=tmp;root=Path(tmp)
            raw=m.encoded(dict(phase='held',source_preserved=None,evidence={}))
            (root/'report.json').write_bytes(raw)
            with patch.object(m,'protected',return_value=LocalFiles):
                with self.assertRaises(ValueError):m.entry(spec,files,'cleanup',{'report_sha256':'bad'})
                result=m.entry(spec,files,'cleanup',{'report_sha256':m.sha(raw)})
            self.assertIsNone(result['source_unchanged']);self.assertEqual((root/'report.json').read_bytes(),raw)
            self.assertEqual({p.name for p in root.iterdir()},{'report.json','cleanup.json'})

    def test_metadata_never_follows_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'ntp.conf';path.symlink_to('/unreadable-or-missing')
            self.assertEqual(m.metadata(path)['type'],'symlink')


if __name__=='__main__':unittest.main()
