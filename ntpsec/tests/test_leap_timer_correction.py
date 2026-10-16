#!/usr/bin/python3
"""Timer transaction success, rejection, conditional recovery and sealed transport."""
import importlib.util
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
entry=importlib.util.spec_from_file_location('timer_runner',ROOT/'scripts/run-leap-timer-correction.py')
r=importlib.util.module_from_spec(entry);entry.loader.exec_module(r)
w,b,h=r.worker,r.base,r.h


class Transaction(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.now=1000.;self.calls=[];self.failure=None;self.failed=False
        self.active=True;self.invocation='old';self.start=900.;self.result='success';self.due=None
        self.reloads=0
        self.service=self.root/'ntpleapfetch.service';self.service.write_bytes(b'unchanged service\n')
        self.timer=self.root/'ntpleapfetch.timer'
        self.candidate=(ROOT/'templates/ntpleapfetch.timer').read_bytes()
        self.original=self.candidate.replace(b'OnBootSec=',b'OnActiveSec=');self.timer.write_bytes(self.original)
        self.leap=self.root/'leap.list';self.leap.write_bytes(b'#@ '+str(int(time.time())+2208988800+180*86400).encode()+b'\n')
        self.boot=self.root/'boot';self.boot.write_text('fixture-boot')
        for p in (self.service,self.timer,self.leap):p.chmod(0o644)
        self.ntp={'MainPID':'814','InvocationID':'ntp','NRestarts':'0','ActiveState':'active','SubState':'running',
                  'UnitFileState':'enabled','DropInPaths':'','FragmentPath':'/etc/systemd/system/timeservice.service'}
        real_record=h.file_record
        def record(path,content=False):
            row=real_record(path,content)
            if 'uid' in row:row.update(uid=0,gid=0)
            return row
        self.helper=SimpleNamespace(file_record=record,bounded=self.external,sha=h.sha,encoded=h.encoded)
        self.baseline={'service':dict(self.ntp),'files':{str(p):record(p,True) for p in (self.service,self.timer,self.leap)}}
        self.spec={'operation_id':'timer-fixture','hostname':'j2-svntp1','boot_id':'fixture-boot'}
        for obj,name,value in ((b,'SERVICE',str(self.service)),(b,'TIMER',str(self.timer)),(b,'LEAP',str(self.leap)),
                (b.socket,'gethostname',lambda:'j2-svntp1'),(b.os,'geteuid',lambda:0),(w.os,'fchown',lambda *a:None),
                (w.time,'monotonic',lambda:self.now),(w.time,'sleep',self.advance)):
            p=patch.object(obj,name,value);p.start();self.addCleanup(p.stop)
        p=patch.object(b,'Path',lambda path:self.boot if str(path)=='/proc/sys/kernel/random/boot_id' else Path(path))
        p.start();self.addCleanup(p.stop)
        self.op=w.TimerCorrection(self.spec,self.baseline,self.candidate,self.helper);self.op.root=self.root/'operation'

    def advance(self,seconds):self.now+=seconds

    def external(self,argv,timeout=10):
        self.calls.append(argv);out=''
        action=argv[1] if len(argv)>1 else ''
        if action==self.failure and not self.failed:
            self.failed=True
            return {'returncode':1,'stdout':'','stderr':'fixture failure'}
        if argv[0]=='/usr/bin/systemctl':
            if action=='daemon-reload':self.reloads+=1
            if action=='stop':
                if argv[2].endswith('.timer'):self.active=False;self.due=None
            elif action=='reset-failed':self.result='success'
            elif action=='start':
                self.active=True
                if self.timer.read_bytes()==self.candidate and self.failure=='service':self.result='exit-code'
            elif action=='show':
                name=argv[2]
                if name=='timeservice.service':data=dict(self.ntp)
                else:
                    if self.due is not None and self.now>=self.due and self.failure!='never':
                        self.start=self.due;self.due=None;self.invocation='new'
                        if self.failure=='service':self.result='exit-code'
                    timer=name.endswith('.timer')
                    data={'LoadState':'loaded','DropInPaths':'','FragmentPath':str(self.timer if timer else self.service),
                          'UnitFileState':'enabled' if timer else 'static',
                          'ActiveState':('active' if self.active else 'inactive') if timer else 'inactive',
                          'SubState':('waiting' if self.active else 'dead') if timer else 'dead',
                          'Result':self.result,'InvocationID':self.invocation,'ExecMainStatus':'0',
                          'ExecMainStartTimestampMonotonic':str(int(self.start*1e6)),
                          'LastTriggerUSec':'observed',
                          'NextElapseUSecMonotonic':str(self.start+(30 if self.failure=='schedule' or (self.failure=='reload-schedule' and self.reloads>=2) else 2419205))+'s'}
                    if self.failure=='foreign' and self.timer.read_bytes()==self.candidate:
                        self.service.write_bytes(b'foreign service')
                        data['Result']='exit-code'
                out=''.join(k+'='+v+'\n' for k,v in data.items())
        return {'returncode':0,'stdout':out,'stderr':''}

    def test_success_and_timer_only_scope(self):
        result=self.op.run();self.assertTrue(result['accepted'],result)
        self.assertEqual(result['checks'],dict.fromkeys(w.CHECKS,True))
        self.assertEqual(self.timer.read_bytes(),self.candidate)
        self.assertEqual(self.service.read_bytes(),b'unchanged service\n')
        self.assertEqual(result['schedule_seconds'],2419205)
        self.assertEqual(result['reload_schedule_seconds'],2419205)
        for argv in self.calls:
            if argv[0]=='/usr/bin/systemctl' and argv[1] in ('start','stop','reset-failed'):
                self.assertIn(argv[2],('ntpleapfetch.timer','ntpleapfetch.service'))
        self.assertNotIn(['/usr/bin/systemctl','start','ntpleapfetch.service'],self.calls)

    def test_preflight_drift_makes_no_mutation(self):
        self.timer.write_bytes(b'foreign')
        result=self.op.run();self.assertFalse(result['accepted']);self.assertEqual(result['rollback'],'not-needed')
        self.assertFalse(self.op.root.exists())
        self.assertFalse(any(a[1]=='stop' for a in self.calls))

    def test_syntax_failure_keeps_live_state(self):
        self.failure='verify';result=self.op.run()
        self.assertFalse(result['accepted']);self.assertEqual(result['rollback'],'not-needed')
        self.assertEqual(self.timer.read_bytes(),self.original);self.assertTrue(self.active)

    def test_failure_after_replace_restores_original_timer(self):
        self.failure='daemon-reload';result=self.op.run()
        self.assertFalse(result['accepted']);self.assertTrue(result['rollback'].startswith('restored'),result)
        self.assertEqual(self.timer.read_bytes(),self.original);self.assertTrue(self.active)

    def test_failed_service_and_bad_schedules_recover(self):
        # Fresh fixtures ensure each simulated mutation is single-use.
        for failure in ('service','schedule','reload-schedule'):
            with self.subTest(failure=failure):
                instance=Transaction('test_success_and_timer_only_scope');instance.setUp()
                try:
                    instance.failure=failure;result=instance.op.run()
                    self.assertFalse(result['accepted']);self.assertTrue(result['rollback'].startswith('restored'),result)
                    self.assertEqual(instance.timer.read_bytes(),instance.original)
                finally:instance.doCleanups()

    def test_foreign_change_holds_recovery(self):
        self.failure='foreign';result=self.op.run()
        self.assertFalse(result['accepted']);self.assertEqual(result['rollback'],'held')
        self.assertEqual(self.service.read_bytes(),b'foreign service')

    def test_ntp_change_prevents_mutation(self):
        self.ntp['InvocationID']='changed'
        result=self.op.run()
        self.assertFalse(result['accepted']);self.assertFalse(self.op.root.exists())
        self.assertEqual(self.timer.read_bytes(),self.original)

    def test_candidate_scope_rejected_before_mutation(self):
        self.op.candidate=self.candidate+b'\nOnCalendar=daily\n'
        result=self.op.run()
        self.assertFalse(result['accepted']);self.assertFalse(self.op.root.exists())
        self.assertEqual(self.timer.read_bytes(),self.original)

    def test_timespan_parser_rejects_partial_or_infinite_values(self):
        self.assertEqual(w.seconds('4w 2h 25min 28.127848s'),2419200+7200+1500+28.127848)
        for value in ('infinity','','4w garbage','4w -1s'):
            with self.assertRaises(ValueError):w.seconds(value)


class Sealing(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.spec={'schema':1,'purpose':'leap-timer-correction','hostname':'j2-svntp1',
            'operation_id':'timer-fixture','boot_id':'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
            'endpoints':['10.1.0.51','fd36:5aa8:6971:1::51'],'host_key_alias':'10.1.0.137',
            'prepared_epoch':int(time.time()),'expires_epoch':int(time.time())+8000,
            'inspection_sha256':'a'*64,'activation_sha256':'b'*64}
        self.files={n:(ROOT/p).read_bytes() for n,p in r.PATHS.items()}
        self.files.update({'baseline.json':b'{}\n','known_hosts':b'fixture'})
        self.spec['members']={n:h.sha(v) for n,v in self.files.items()}
        self.files.update({'spec.json':h.encoded(self.spec),'review.md':r.review(self.spec).encode()})
        self.bundle=self.root/r.BUNDLE
        with tarfile.open(self.bundle,'w') as archive:
            for n,v in self.files.items():
                item=tarfile.TarInfo(n);item.size=len(v);archive.addfile(item,io.BytesIO(v))
        self.bundle.chmod(0o600)
        for n in ('spec.json','review.md','known_hosts'):
            (self.root/n).write_bytes(self.files[n]);(self.root/n).chmod(0o600)
        self.digest=h.sha(self.bundle.read_bytes())

    def test_binding_and_compiled_payload(self):
        spec,files=r.prepare(self.bundle,self.digest);compile(r.payload(spec,files),'payload','exec')
        with self.assertRaisesRegex(ValueError,'digest'):r.prepare(self.bundle,'0'*64)
        (self.root/'review.md').write_text('changed')
        with self.assertRaisesRegex(ValueError,'approval'):r.prepare(self.bundle,self.digest)

    def test_partial_transport_retained_without_retry(self):
        args=SimpleNamespace(bundle=self.bundle,sha256=self.digest)
        with patch.object(h,'bounded',return_value={'returncode':255,'stdout':'partial','stderr':'lost'}):
            self.assertFalse(r.execute(args)['accepted'])
            self.assertEqual((self.root/'stdout.txt').read_text(),'partial')
            with self.assertRaises(FileExistsError):r.execute(args)

    def test_acceptance_requires_all_checks_and_identity(self):
        args=SimpleNamespace(bundle=self.bundle,sha256=self.digest)
        state={'accepted':True,'operation_id':self.spec['operation_id'],
               'spec_sha256':h.sha(h.encoded(self.spec)),'checks':dict.fromkeys(w.CHECKS,True)}
        with patch.object(h,'bounded',return_value={'returncode':0,'stdout':json.dumps(state),'stderr':''}):
            self.assertTrue(r.execute(args)['accepted'])

    def test_missing_check_is_not_accepted(self):
        args=SimpleNamespace(bundle=self.bundle,sha256=self.digest)
        state={'accepted':True,'operation_id':self.spec['operation_id'],
               'spec_sha256':h.sha(h.encoded(self.spec)),'checks':dict.fromkeys(w.CHECKS[:-1],True)}
        with patch.object(h,'bounded',return_value={'returncode':0,'stdout':json.dumps(state),'stderr':''}):
            self.assertFalse(r.execute(args)['accepted'])


if __name__=='__main__':unittest.main()
