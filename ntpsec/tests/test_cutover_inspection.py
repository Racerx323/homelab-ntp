#!/usr/bin/python3
"""Offline retained-evidence retrieval, closed scope and rejection tests."""
import base64
import copy
import importlib.util
import json
import os
import shutil
import subprocess
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
    old=dict(hostname='fixture',kernel='fixture-kernel',boot_id='12345678-1234-5678-9abc-123456789abc',
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


def held_fixture():
    spec,files=fixture();old=json.loads(files['source-spec.json'])
    old.update(purpose='runtime-diagnostic',operation_id='trial',apply_unit='ntp-cutover-trial',recovery_unit='ntp-cutover-trial-recovery')
    files['source-spec.json']=m.encoded(old)
    state={'phase':'recovery_held','apply_epoch':100,'apply_monotonic':90,'deadline':1890,
           'diagnostic_samples':[{'elapsed_seconds':10}],'error':'package/service/Python/process drift'}
    response={'spec_sha256':m.sha(files['source-spec.json']),'result':state}
    files.pop('source-cleanup.json');files.pop('source-receipt.json')
    files.update({'source-proof.json':m.encoded({'responses':[response,response],'attempt':13,'bundle_sha256':'a'*64}),
                  'source-baseline.json':m.encoded({'observation':{}}),
                  'observation.py':(ROOT/'scripts/inspect-source-destinations.py').read_bytes()})
    spec.update(purpose='recovery-inspection',journal_until=3700)
    spec['members']={n:m.sha(files[n]) for n in set(m.PATHS)|m.HELD_EXTRA}
    files['spec.json']=m.encoded(spec);files['review.md']=m.review(spec).encode()
    files['manifest.json']=m.encoded({n:m.sha(v) for n,v in files.items() if n!='manifest.json'})
    return spec,files


class LocalFiles:
    @staticmethod
    def ancestors(path):pass
    @staticmethod
    def read(path,limit=m.LIMIT):
        raw=path.read_bytes()
        if len(raw)>limit:raise ValueError('bounded file exceeded')
        return raw
    @staticmethod
    def create(path,raw):
        with path.open('xb') as stream:stream.write(raw)


class BindingTests(unittest.TestCase):
    def test_boot_filter_is_compact_without_changing_target_identity(self):
        spec,files=fixture();original=spec['boot_id']
        self.assertEqual(m.journal_boot_id(original),'12345678123456789abc123456789abc')
        m.validate(spec,files);self.assertEqual(spec['boot_id'],original)
        for value in (None,'',original+'+1',original.replace('-',''),original.upper(),'0','all'):
            with self.subTest(value=value),self.assertRaises(ValueError):m.journal_boot_id(value)

    @unittest.skipUnless(shutil.which('journalctl'),'journalctl unavailable on test workstation')
    def test_real_journalctl_parses_filter_without_opening_journal(self):
        spec,_=fixture()
        # --help exits after parsing; no system or target journal is queried.
        result=subprocess.run(['journalctl','--boot='+m.journal_boot_id(spec['boot_id']),'--help'],
                              capture_output=True,timeout=10,env=m.ENV,check=False)
        self.assertEqual(result.returncode,0,result.stderr.decode())

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


class HeldInspectionTests(unittest.TestCase):
    def test_binding_payloads_and_authorized_recovery_transitions(self):
        spec,files=held_fixture();m.validate(spec,files)
        for mode in ('start','readback','cleanup'):compile(c.payload(spec,files,mode),mode,'exec')
        retained=json.loads(files['source-proof.json'])['responses'][0]['result']
        m.held_state(spec,files,retained)
        m.held_state(spec,files,dict(retained,phase='recovered',recovered_epoch=2000,diagnostic_statistics={}))
        for change in ({'phase':'observing'},{'phase':'accepted'},{'transient_cleanup':True},
                       {'apply_epoch':101},{'diagnostic_samples':[]},{'unexpected':True}):
            with self.subTest(change=change),self.assertRaises(ValueError):m.held_state(spec,files,dict(retained,**change))
        for field,value in (('journal_until',3701),('source_stage','/tmp/other'),('hostname','other')):
            with self.subTest(field=field),self.assertRaises(ValueError):m.validate(dict(spec,**{field:value}),files)
        bad=dict(files);proof=json.loads(bad['source-proof.json']);proof['responses'][1]['result']['phase']='recovered'
        bad['source-proof.json']=m.encoded(proof)
        with self.assertRaises(ValueError):m.validate(spec,bad)

    def capture_held(self,variant='good'):
        spec,files=held_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'inspection';source=Path(tmp)/'source';root.mkdir();source.mkdir()
            spec.update(stage=str(root),source_stage=str(source));check=source/'runtime-check';check.mkdir()
            state=json.loads(files['source-proof.json'])['responses'][0]['result']
            for name,raw in {'before.json':b'{}','state.json':m.encoded(state),'commands.jsonl':b'{}\n','recovery-commands.jsonl':b'{}\n'}.items():
                (source/name).write_bytes(raw)
            (check/'baseline.json').write_bytes(files['source-baseline.json'])
            (check/'inspect-source-destinations.py').write_bytes(files['observation.py'])
            original={str(p.relative_to(source)):p.read_bytes() for p in source.rglob('*') if p.is_file()}
            observer=m.load(ROOT/'scripts/inspect-source-destinations.py');calls=[]
            def command(h,directory,name,argv):
                calls.append(argv)
                if variant=='command-failure':raise ValueError('bounded command failed')
                if name=='journal':raw=m.encoded({'_BOOT_ID':m.journal_boot_id(spec['boot_id']) if variant!='wrong-boot' else 'b'*32})
                elif name=='observation-0':raw=b'fixture\t1\tii \n'
                elif name=='observation-1':raw=b''
                else:raw=b'Id=fixture.service\nActiveState=inactive\n'
                if variant=='truncated' and name=='journal':raw*=m.JOURNAL_LINES
                if variant=='missing' and name=='journal':raw=b''
                if variant=='drift' and name=='timer':(source/'state.json').write_bytes(b'{}')
                if variant=='baseline-drift' and name=='timer':(check/'baseline.json').write_bytes(b'{}')
                h.create(directory/(name+'.json'),m.encoded({'argv':argv,'status':0}))
                h.create(directory/(name+'.stdout'),raw);h.create(directory/(name+'.stderr'),b'')
                return raw
            with patch.object(m,'source_lock',return_value=os.open(source,os.O_RDONLY)),patch.object(m,'command',side_effect=command),patch.object(m,'load',return_value=observer),patch.object(observer,'Path') as paths:
                paths.return_value.glob.return_value=[];paths.return_value.read_text.return_value=spec['boot_id']
                report=m.capture(LocalFiles,spec,files)
            if variant not in ('drift','baseline-drift'):
                self.assertEqual(original,{str(p.relative_to(source)):p.read_bytes() for p in source.rglob('*') if p.is_file()})
            return report,calls,spec,files

    def test_read_only_diff_timer_and_journal_capture_is_not_restoration(self):
        report,calls,spec,files=self.capture_held()
        self.assertEqual(report['phase'],'captured',report.get('error'));self.assertTrue(report['source_preserved'])
        self.assertEqual(set(report['evidence']),set(m.HELD_CAPTURE_FILES))
        self.assertFalse(report['summary']['continuity_matches']);self.assertFalse(report['summary']['restoration_accepted'])
        self.assertIn('services',report['summary']['different_fields']);self.assertEqual(len(calls),7)
        self.assertIn('--unit=ntp-cutover-trial-recovery.service',calls[0]);self.assertIn('--until=@3700',calls[0])
        self.assertEqual(calls[2][-1],'ntp-cutover-trial-recovery.timer');self.assertNotIn('MainPID',' '.join(calls[2]))
        self.assertFalse(any(word in ('restart','stop','start','disable','enable','set-time') for argv in calls for word in argv))
        result=m.terminal_receipt(spec,files,'a'*64,dict.fromkeys(spec['endpoints'],report))
        self.assertFalse(result['time_service_accepted'])
        incomplete=copy.deepcopy(report);incomplete['evidence'].pop('continuity.json')
        with self.assertRaises(ValueError):m.terminal_receipt(spec,files,'a'*64,dict.fromkeys(spec['endpoints'],incomplete))

    def test_partial_failed_changed_or_incomplete_capture_holds(self):
        for variant in ('command-failure','wrong-boot','truncated','missing','drift','baseline-drift'):
            with self.subTest(variant=variant):
                report,_,_,_=self.capture_held(variant)
                self.assertEqual(report['phase'],'held');self.assertIsNone(report['source_preserved'])


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
            if variant=='current':
                journal=['/usr/bin/journalctl','--quiet','--no-pager','--output=json','--boot='+m.journal_boot_id(spec['boot_id']),
                         '--unit=timeservice.service','--unit=avahi-daemon.service','--priority=0..3']
                (source/'commands.jsonl').write_bytes(m.encoded({'argv':journal,'stdout':'{}','stderr':'','status':0})*5)
            stats=source/'runtime-data';stats.mkdir(mode=0o700)
            (stats/'ntpstats-loopstats').write_bytes(b'retained timing sample\n')
            original={str(p.relative_to(source)):p.read_bytes() for p in source.rglob('*') if p.is_file()};calls=[]
            def command(h,r,name,argv):
                calls.append(argv)
                if variant=='command-failure':raise ValueError('diagnostic command failed')
                raw=b'{}\n'*(m.JOURNAL_LINES if variant=='truncated' else 1) if name=='journal' else b'ActiveState=inactive\n'
                h.create(r/(name+'.json'),m.encoded({'argv':argv,'status':0}))
                h.create(r/(name+'.stdout'),raw);h.create(r/(name+'.stderr'),b'')
                if variant=='drift' and name=='services':(source/'state.json').write_bytes(b'{}')
                if variant=='stats-drift' and name=='services':(stats/'ntpstats-loopstats').write_bytes(b'changed')
                return raw
            with patch.object(m,'source_lock',return_value=os.open(source,os.O_RDONLY)),patch.object(m,'command',side_effect=command):
                report=m.capture(LocalFiles,spec,files)
            if variant not in ('drift','stats-drift'):
                self.assertEqual(original,{str(p.relative_to(source)):p.read_bytes() for p in source.rglob('*') if p.is_file()})
            self.assertEqual(json.loads((root/'report.json').read_bytes()),report)
            return report,calls

    def test_read_only_collection_preserves_original_bytes(self):
        report,calls=self.run_capture()
        self.assertEqual(report['phase'],'captured');self.assertTrue(report['source_preserved'])
        self.assertEqual(set(report['evidence']),set(m.CAPTURE_FILES))
        self.assertEqual(len(calls),2);self.assertIn('--boot=12345678123456789abc123456789abc',calls[0]);self.assertIn('--until=@151',calls[0])
        self.assertEqual(calls[1][:2],['/usr/bin/systemctl','show'])
        self.assertNotIn('MainPID',str(calls[1]));self.assertNotIn('restart',str(calls))

    def test_incomplete_or_failed_capture_holds(self):
        for variant in ('truncated','command-failure','drift','stats-drift'):
            with self.subTest(variant=variant):
                report,_=self.run_capture(variant)
                self.assertEqual(report['phase'],'held');self.assertIsNone(report['source_preserved'])

    def test_five_current_probes_and_retained_statistics(self):
        report,calls=self.run_capture('current')
        self.assertEqual(report['phase'],'captured')
        self.assertEqual(report['summary']['retained_journal_probes'],5)
        self.assertFalse(report['summary']['packet_counters_retrieved'])
        data=json.loads(base64.b64decode(report['evidence']['runtime-data.json']['base64']))
        self.assertEqual(base64.b64decode(data['files']['ntpstats-loopstats']['base64']),b'retained timing sample\n')
        self.assertIn('--lines=2000',calls[0])

    def test_retained_journal_scope_count_and_boot_drift_rejected(self):
        spec,_=fixture()
        argv=['/usr/bin/journalctl','--quiet','--no-pager','--output=json','--boot='+m.journal_boot_id(spec['boot_id']),
              '--unit=timeservice.service','--unit=avahi-daemon.service','--priority=0..3']
        row={'argv':argv,'stdout':'','stderr':'','status':0}
        self.assertEqual(len(m.retained_journals([row]*41,spec)),41)
        for rows in ([],[row]*42,[dict(row,argv=argv+['--follow'])],
                     [dict(row,argv=[a.replace(m.journal_boot_id(spec['boot_id']),'0'*32) for a in argv])]):
            with self.assertRaises(ValueError):m.retained_journals(rows,spec)

    def test_runtime_file_names_links_types_and_bounds(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp);root=source/'runtime-data'
            self.assertEqual(m.runtime_data(LocalFiles,source),{'exists':False,'files':{}})
            root.mkdir(mode=0o700);self.assertEqual(m.runtime_data(LocalFiles,source),{'exists':True,'files':{}})
            bad=root/'unexpected';bad.write_bytes(b'x')
            with self.assertRaises(ValueError):m.runtime_data(LocalFiles,source)
            bad.unlink();path=root/'ntpstats-peerstats';path.symlink_to(source/'absent')
            with self.assertRaises(ValueError):m.runtime_data(LocalFiles,source)
            path.unlink();path.mkdir()
            with self.assertRaises(ValueError):m.runtime_data(LocalFiles,source)
            path.rmdir();path.write_bytes(b'1234');second=root/'ntpstats-peerstats.20261013';os.link(path,second)
            with self.assertRaises(ValueError):m.runtime_data(LocalFiles,source)
            second.unlink();second.write_bytes(b'5678')
            with patch.object(m,'STATS_LIMIT',7),self.assertRaises(ValueError):m.runtime_data(LocalFiles,source)
            with patch.object(m,'STATS_LIMIT',3),self.assertRaises(ValueError):m.runtime_data(LocalFiles,source)
            root.chmod(0o777)
            with self.assertRaises(ValueError):m.runtime_data(LocalFiles,source)

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
