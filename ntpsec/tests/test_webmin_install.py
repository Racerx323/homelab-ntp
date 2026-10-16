#!/usr/bin/python3
"""Offline package gates, HTTP policy, startup guard and containment tests."""
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import tarfile
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
entry=importlib.util.spec_from_file_location('webmin_runner',ROOT/'scripts/run-webmin-install.py')
r=importlib.util.module_from_spec(entry);entry.loader.exec_module(r)
w,h=r.worker,r.helper


class Transaction(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.calls=[];self.phase='before';self.active=False;self.failure=None;self.failed=False
        self.stopped_unit={'ActiveState':'inactive','SubState':'dead','InvocationID':'',
                           'Result':'success','ExecMainCode':'0','ExecMainStatus':'0'}
        def mapped(p):
            p=Path(p)
            return p if str(p).startswith(str(self.root)) else self.root/str(p).lstrip('/')
        self.mapped=mapped
        for name in ('GUARD','MARKER','CONFIG','SOURCE','KEY','PIN'):
            value=mapped(getattr(w,name));value.parent.mkdir(parents=True,exist_ok=True)
            p=patch.object(w,name,value);p.start();self.addCleanup(p.stop)
        # Preflight expects no Webmin configuration/drop-in directory yet.
        w.GUARD.parent.rmdir();w.CONFIG.parent.rmdir()
        boot=mapped('/proc/sys/kernel/random/boot_id');boot.parent.mkdir(parents=True);boot.write_text('boot')
        protected=[]
        for n in w.PROTECTED:
            p=mapped(n);p.parent.mkdir(parents=True,exist_ok=True);p.write_text('protected');protected.append(str(p))
        mapped('/var/lib').mkdir(parents=True,exist_ok=True)
        p=patch.object(w,'PROTECTED',tuple(protected));p.start();self.addCleanup(p.stop)
        p=patch.object(w,'Path',side_effect=mapped);p.start();self.addCleanup(p.stop)
        original=os.path.lexists
        p=patch.object(w.os.path,'lexists',side_effect=lambda path:original(mapped(path)));p.start();self.addCleanup(p.stop)
        for obj,name,value in ((w.os,'geteuid',lambda:0),(w.socket,'gethostname',lambda:'j2-svntp1'),(h,'bounded',self.external)):
            p=patch.object(obj,name,value);p.start();self.addCleanup(p.stop)
        self.identity={'MainPID':'814','InvocationID':'same','NRestarts':'0','ActiveState':'active','SubState':'running','UnitFileState':'enabled'}
        self.before={'perl':['5.40','arm64','ii ']}
        self.inputs={'policy.json':(ROOT/'configs/webmin-http-policy.json').read_bytes(),'guard.conf':(ROOT/'templates/webmin-first-start.conf').read_bytes(),
                     'source.list':b'source','keyring.gpg':b'key','preferences':b'pin','webmin.deb':b'package'}
        self.spec={'hostname':'j2-svntp1','boot_id':'boot','operation_id':'fixture','service_identity':dict(self.identity),
                   'packages_before':self.before,'packages':[{'member':'webmin.deb','name':'webmin','version':'2.670','architecture':'all','sha256':h.sha(b'package')}],
                   'endpoints':['10.1.0.51','fd36:5aa8:6971:1::51']}
        self.worker=w.Install(self.spec,self.inputs,h)
        self.http=patch.object(w.http.client,'HTTPConnection');self.connection=self.http.start();self.addCleanup(self.http.stop)
        response=self.connection.return_value.getresponse.return_value;response.status=200;response.getheader.return_value=''

    def external(self,argv,timeout=30,env=None):
        self.calls.append(argv);out=''
        if argv[0]=='/usr/bin/dpkg-query':
            rows=dict(self.before)
            if self.phase=='installed':rows['webmin']=['2.670','all','ii ']
            if self.failure=='unrelated' and self.phase=='installed':rows['foreign']=['1','all','ii ']
            out=''.join(k+'\t'+'\t'.join(v)+'\n' for k,v in rows.items())
        elif argv[0]=='/usr/bin/dpkg':
            if '--print-architecture' in argv:out='arm64\n'
            if '--no-act' in argv and self.failure=='dependency':return {'returncode':1,'stdout':'missing dependency','stderr':''}
            if argv[1]=='--install':
                self.assertTrue(w.GUARD.exists());self.assertFalse(w.MARKER.exists())
                w.CONFIG.parent.mkdir();w.CONFIG.write_text('port=10000\nssl=1\nroot=/usr/share/webmin\n')
                self.phase='installed'
                if self.failure=='guard':w.GUARD.write_bytes(b'foreign guard')
                if self.failure=='dpkg':return {'returncode':1,'stdout':'failed','stderr':''}
        elif argv[0]=='/usr/bin/systemctl':
            if argv[1]=='show':
                if argv[2]=='timeservice.service':data=self.identity
                else:data={'LoadState':'not-found' if self.phase=='before' else 'loaded','ActiveState':'active' if self.active else 'inactive',
                          'UnitFileState':'enabled' if self.active else 'disabled','MainPID':'555' if self.active else '0',
                          'SubState':'running' if self.active else 'dead','NRestarts':'0','InvocationID':'webmin' if self.active else '',
                          'Result':'success','ExecMainCode':'0','ExecMainStatus':'0',
                          'DropInPaths':str(w.GUARD) if self.phase=='installed' else ''}
                if argv[2]=='webmin.service' and not self.active:data.update(self.stopped_unit)
                out=''.join(k+'='+v+'\n' for k,v in data.items())
            if argv[1]=='enable':
                self.assertTrue(w.MARKER.exists());self.assertIn('ssl=0\n',w.CONFIG.read_text());self.active=True
                if self.failure=='start' and not self.failed:
                    self.failed=True;return {'returncode':1,'stdout':'','stderr':'start failed'}
            if argv[1]=='stop':self.active=False
            if argv[1]=='reset-failed' and self.failure!='reset':
                self.stopped_unit.update(ActiveState='inactive',SubState='dead',InvocationID='',
                                         Result='success',ExecMainCode='0',ExecMainStatus='0')
        elif argv[0]=='/usr/bin/ss' and self.active and '-lnt' in argv:
            out='LISTEN 0 5 10.1.0.51:10000 0.0.0.0:*\nLISTEN 0 5 [fd36:5aa8:6971:1::51]:10000 [::]:*\n'
            if self.failure=='wildcard':out=out.replace('10.1.0.51:10000','0.0.0.0:10000')
        return {'returncode':0,'stdout':out,'stderr':''}

    def test_success_has_guard_before_install_and_policy_before_first_start(self):
        state=self.worker.run();self.assertTrue(state['installed'],state)
        self.assertFalse(state['authenticated_accepted']);self.assertTrue(w.MARKER.exists())
        self.assertEqual(self.connection.call_count,2)
        self.assertFalse(any('restart' in a or 'apt-get' in a[0] for a in self.calls))

    def test_dependency_failure_precedes_mutation(self):
        self.failure='dependency';state=self.worker.run()
        self.assertFalse(state['installed']);self.assertFalse(w.GUARD.exists());self.assertFalse(w.CONFIG.exists())

    def test_package_failure_leaves_guard_and_nonserving_packages(self):
        self.failure='dpkg';state=self.worker.run()
        self.assertEqual(state['recovery'],'non-serving; packages retained',state);self.assertFalse(self.active)

    def test_changed_guard_still_stops_new_service_but_holds_cleanup(self):
        self.failure='guard';state=self.worker.run()
        self.assertFalse(state['installed']);self.assertTrue(state['service_stopped'])
        self.assertEqual(state['recovery'],'held');self.assertEqual(w.GUARD.read_bytes(),b'foreign guard')

    def test_interruption_after_permit_enters_containment(self):
        original=self.worker.cmd
        def interrupt(argv,timeout=30):
            if argv[1:3]==['enable','--now']:w.interrupt(15,None)
            return original(argv,timeout)
        with patch.object(self.worker,'cmd',side_effect=interrupt):state=self.worker.run()
        self.assertEqual(state['recovery'],'non-serving; packages retained',state)
        self.assertFalse(w.MARKER.exists())

    def test_partial_start_failure_stops_and_removes_permit(self):
        self.failure='start';state=self.worker.run()
        self.assertEqual(state['recovery'],'non-serving; packages retained',state)
        self.assertFalse(self.active);self.assertFalse(w.MARKER.exists())

    def test_wildcard_listener_rejected_and_contained(self):
        self.failure='wildcard';state=self.worker.run()
        self.assertFalse(state['installed']);self.assertFalse(self.active);self.assertFalse(w.MARKER.exists())

    def test_unrelated_package_change_rejected(self):
        self.failure='unrelated';state=self.worker.run()
        self.assertFalse(state['installed']);self.assertFalse(w.MARKER.exists())

    def test_changed_supervisor_rejected_before_staging(self):
        self.identity['InvocationID']='different';state=self.worker.run()
        self.assertFalse(state['installed']);self.assertFalse(self.worker.root.exists())

    def test_existing_configuration_is_not_overwritten(self):
        w.CONFIG.parent.mkdir();w.CONFIG.write_text('foreign')
        self.assertFalse(self.worker.run()['installed']);self.assertEqual(w.CONFIG.read_text(),'foreign')

    def test_configuration_duplicates_rejected(self):
        with self.assertRaisesRegex(ValueError,'duplicate'):w.configure(b'ssl=1\nssl=0\n',{'ssl':'0'})

    def test_https_redirect_is_rejected(self):
        self.connection.return_value.getresponse.return_value.getheader.return_value='https://host:10000/'
        state=self.worker.run();self.assertFalse(state['installed']);self.assertFalse(self.active)

    def test_configuration_preserves_unrelated_settings(self):
        raw=w.configure(b'root=/usr/share/webmin\nssl=1\n',json.loads(self.inputs['policy.json']))
        self.assertIn(b'root=/usr/share/webmin\n',raw);self.assertIn(b'allowusers=ama\n',raw)
        self.assertIn(b'listen=\n',raw);self.assertIn(b'ssl=0\n',raw)

    def make_continuation(self):
        self.phase='installed'
        w.GUARD.parent.mkdir();w.GUARD.write_bytes(self.inputs['guard.conf'])
        w.CONFIG.parent.mkdir();w.CONFIG.write_bytes(w.configure(b'root=/usr/share/webmin\n',json.loads(self.inputs['policy.json'])))
        self.spec.update(continuation=True,packages_before={**self.before,'webmin':['2.670','all','ii ']})
        self.spec['continuation_unit']=dict(self.stopped_unit)
        self.spec['continuation_files']={str(p):self.worker.record(p) for p in (w.GUARD,w.CONFIG)}

    def test_continuation_preserves_installed_files_and_never_installs_packages(self):
        self.make_continuation();before=w.CONFIG.read_bytes()
        state=self.worker.run();self.assertTrue(state['installed'],state)
        self.assertEqual(w.CONFIG.read_bytes(),before)
        self.assertFalse(any('--install' in a or 'daemon-reload' in a for a in self.calls))
        self.assertFalse(w.SOURCE.exists());self.assertFalse(w.KEY.exists())

    def test_continuation_rejects_changed_config_before_mutation(self):
        self.make_continuation();w.CONFIG.write_text('foreign')
        state=self.worker.run();self.assertFalse(state['installed'])
        self.assertFalse(self.worker.mutated);self.assertFalse(w.MARKER.exists())
        self.assertFalse(any(a[1]=='enable' for a in self.calls))

    def test_continuation_partial_start_failure_recovers(self):
        self.make_continuation();self.failure='start'
        state=self.worker.run();self.assertEqual(state['recovery'],'non-serving; packages retained',state)
        self.assertFalse(w.MARKER.exists());self.assertFalse(self.active)

    def set_failed_baseline(self):
        self.make_continuation()
        self.stopped_unit.update(ActiveState='failed',SubState='failed',InvocationID='prior-webmin',
                                 Result='exit-code',ExecMainCode='1',ExecMainStatus='1')
        self.spec['continuation_unit']=dict(self.stopped_unit)

    def test_pinned_failed_state_reset_precedes_single_start(self):
        self.set_failed_baseline();before=w.CONFIG.read_bytes()
        state=self.worker.run();self.assertTrue(state['installed'],state)
        reset=self.calls.index(['/usr/bin/systemctl','reset-failed','webmin.service'])
        start=self.calls.index(['/usr/bin/systemctl','enable','--now','webmin.service'])
        self.assertLess(reset,start);self.assertEqual(w.CONFIG.read_bytes(),before)
        self.assertEqual(sum(a[1]=='reset-failed' for a in self.calls),1)

    def test_changed_failed_identity_prevents_mutation(self):
        self.set_failed_baseline();self.stopped_unit['InvocationID']='foreign'
        state=self.worker.run();self.assertFalse(state['installed']);self.assertFalse(self.worker.mutated)
        self.assertFalse(any(a[1] in ('reset-failed','enable') for a in self.calls))

    def test_unsuccessful_reset_cannot_start_webmin(self):
        self.set_failed_baseline();self.failure='reset'
        state=self.worker.run();self.assertIn('reset',state['error'])
        self.assertFalse(any(a[1]=='enable' for a in self.calls));self.assertFalse(w.MARKER.exists())
        self.assertEqual(state['recovery'],'non-serving; packages retained')

    def test_delayed_listener_readiness_succeeds_with_one_start(self):
        self.make_continuation();clock=[0];queries=[0]
        def external(argv,**kwargs):
            result=self.external(argv,**kwargs)
            if self.active and '-lnt' in argv:
                queries[0]+=1
                if queries[0]==1:result['stdout']=''
                elif queries[0]==2:result['stdout']=result['stdout'].splitlines()[0]+'\n'
            return result
        with patch.object(h,'bounded',side_effect=external),patch.object(w.time,'monotonic',side_effect=lambda:clock[0]), \
                patch.object(w.time,'sleep',side_effect=lambda seconds:clock.__setitem__(0,clock[0]+seconds)):
            state=self.worker.run()
        self.assertTrue(state['installed'],state);self.assertEqual(clock[0],2)
        self.assertEqual(sum(a[1]=='enable' for a in self.calls),1)

    def test_missing_listeners_hit_deadline_and_recover(self):
        self.make_continuation();clock=[0]
        def external(argv,**kwargs):
            result=self.external(argv,**kwargs)
            if '-lnt' in argv:result['stdout']=''
            return result
        with patch.object(h,'bounded',side_effect=external),patch.object(w.time,'monotonic',side_effect=lambda:clock[0]), \
                patch.object(w.time,'sleep',side_effect=lambda seconds:clock.__setitem__(0,clock[0]+seconds)):
            state=self.worker.run()
        self.assertIn('deadline',state['error']);self.assertEqual(clock[0],60)
        self.assertEqual(state['recovery'],'non-serving; packages retained');self.assertFalse(w.MARKER.exists())

    def test_service_failure_restart_and_udp_fail_without_wait(self):
        for failure in ('failed','restart','udp'):
            with self.subTest(failure=failure):
                self.active=True
                def external(argv,**kwargs):
                    result=self.external(argv,**kwargs)
                    if 'webmin.service' in argv and argv[1]=='show':
                        if failure=='failed':result['stdout']=result['stdout'].replace('ActiveState=active','ActiveState=failed')
                        if failure=='restart':result['stdout']=result['stdout'].replace('NRestarts=0','NRestarts=1')
                    if '-lnu' in argv and failure=='udp':result['stdout']='UNCONN 0 0 *:10000 *:*\n'
                    return result
                self.phase='installed'
                with patch.object(h,'bounded',side_effect=external),patch.object(w.time,'sleep') as sleep:
                    with self.assertRaises(ValueError):self.worker.wait_ready()
                    sleep.assert_not_called()

    def test_process_change_during_wait_is_rejected(self):
        self.phase='installed';self.active=True;reads=[0]
        def external(argv,**kwargs):
            result=self.external(argv,**kwargs)
            if 'webmin.service' in argv and argv[1]=='show':
                reads[0]+=1
                if reads[0]>1:result['stdout']=result['stdout'].replace('MainPID=555','MainPID=556')
            if '-lnt' in argv:result['stdout']=''
            return result
        with patch.object(h,'bounded',side_effect=external),patch.object(w.time,'sleep'):
            with self.assertRaisesRegex(ValueError,'restarted'):self.worker.wait_ready()


class Platform(unittest.TestCase):
    def test_real_systemd_condition_blocks_until_permitted(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'accepted';argv=['systemd-analyze','condition','ConditionPathExists='+str(path)]
            self.assertNotEqual(subprocess.run(argv,capture_output=True).returncode,0)
            path.write_text('checked')
            self.assertEqual(subprocess.run(argv,capture_output=True).returncode,0)


class Sealing(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.repository=self.root/'repo';self.repository.mkdir();self.bundle=self.root/r.BUNDLE
        self.files={n:(ROOT/p).read_bytes() for n,p in r.PATHS.items()}
        self.package={'name':'webmin','version':'fixture','architecture':'all','member':'webmin.deb','sha256':h.sha(b'package')}
        assets={'packages':[{'Package':'webmin','Version':'fixture','Architecture':'all','Filename':'pool/webmin.deb','SHA256':h.sha(b'package')}],
                'keyring_sha256':h.sha(b'key')}
        self.files['assets.json']=h.encoded(assets)
        for n,p in r.PATHS.items():
            path=self.repository/p;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(self.files[n])
        patched=patch.object(r,'ROOT',self.repository);patched.start();self.addCleanup(patched.stop)
        self.files.update({'webmin.deb':b'package','keyring.gpg':b'key','known_hosts':b'fixture','baseline.json':b'{}'})
        self.spec={'schema':1,'purpose':'webmin-install','hostname':'j2-svntp1','boot_id':'a'*8+'-'+'b'*4+'-'+'c'*4+'-'+'d'*4+'-'+'e'*12,
                   'operation_id':'fixture','inspection_sha256':'a'*64,'endpoints':['10.1.0.51','fd36:5aa8:6971:1::51'],
                   'host_key_alias':'10.1.0.137','prepared_epoch':int(time.time()),'expires_epoch':int(time.time())+3600,'packages':[self.package]}
        self.spec['members']={n:h.sha(v) for n,v in self.files.items()}
        self.files.update({'spec.json':h.encoded(self.spec),'review.md':r.review(self.spec).encode()});self.pack()

    def pack(self):
        with tarfile.open(self.bundle,'w') as archive:
            for n,data in self.files.items():
                item=tarfile.TarInfo(n);item.size=len(data);archive.addfile(item,io.BytesIO(data))
        self.bundle.chmod(0o600)
        for n in ('spec.json','review.md','known_hosts'):
            (self.root/n).write_bytes(self.files[n]);(self.root/n).chmod(0o600)
        self.digest=h.sha(self.bundle.read_bytes())

    def test_archive_binding_and_payload_compile(self):
        spec,files=r.prepare(self.bundle,self.digest);compile(r.payload(spec,files),'payload','exec')
        with self.assertRaisesRegex(ValueError,'digest'):r.prepare(self.bundle,'0'*64)
        (self.root/'review.md').write_text('changed')
        with self.assertRaisesRegex(ValueError,'approval'):r.prepare(self.bundle,self.digest)

    def test_package_drift_is_rejected(self):
        self.files['webmin.deb']=b'changed';self.pack()
        with self.assertRaisesRegex(ValueError,'binding'):r.prepare(self.bundle,self.digest)

    def test_extra_member_is_rejected(self):
        self.files['old-operation.tar']=b'forbidden';self.pack()
        with self.assertRaisesRegex(ValueError,'flat'):r.prepare(self.bundle,self.digest)

    def test_expired_bundle_is_rejected(self):
        with patch.object(r.time,'time',return_value=self.spec['expires_epoch']):
            with self.assertRaisesRegex(ValueError,'window'):r.prepare(self.bundle,self.digest)

    def test_uncertain_transport_is_retained_and_not_retried(self):
        args=type('Args',(),{'bundle':self.bundle,'sha256':self.digest})()
        with patch.object(h,'bounded',return_value={'returncode':255,'stdout':'partial','stderr':'disconnected'}) as call:
            self.assertFalse(r.execute(args)['accepted'])
            with self.assertRaises(FileExistsError):r.execute(args)
            self.assertEqual(call.call_count,1)
        self.assertEqual((self.root/'stdout.txt').read_text(),'partial')

    def test_continuation_bundle_has_no_packages_and_compiles(self):
        del self.files['webmin.deb'];del self.files['keyring.gpg']
        self.spec.update(continuation=True,packages=[],continuation_files={p:{'sha256':'a'*64} for p in w.CONTINUATION_PATHS})
        self.spec['continuation_unit']={'ActiveState':'failed','SubState':'failed','InvocationID':'prior',
                                       'Result':'exit-code','ExecMainCode':'1','ExecMainStatus':'1'}
        self.spec['members']={n:h.sha(v) for n,v in self.files.items() if n not in ('spec.json','review.md')}
        self.files.update({'spec.json':h.encoded(self.spec),'review.md':r.review(self.spec).encode()});self.pack()
        spec,files=r.prepare(self.bundle,self.digest)
        compile(r.payload(spec,files),'continuation-payload','exec')
        self.assertFalse(any(n.endswith('.deb') for n in files))
        self.files['webmin.deb']=b'not authorized';self.pack()
        with self.assertRaisesRegex(ValueError,'flat'):r.prepare(self.bundle,self.digest)

    def test_continuation_requires_inspected_policy_and_recovered_state(self):
        record={'sha256':'a'*64,'uid':0,'gid':0,'mode':0o644}
        files={p:dict(record) for p in w.CONTINUATION_PATHS}
        files[str(w.GUARD)]['sha256']=h.sha(self.files['guard.conf'])
        files[str(w.MARKER)]={'missing':True};files['/etc/systemd/system/webmin.service']={'missing':True}
        capture={'files':files,'payload_fingerprints':{},'webmin':{**record,'settings':json.loads(self.files['policy.json'])},
                 'commands':{'webmin.service':{'stdout':'ActiveState=inactive\nSubState=dead\nUnitFileState=disabled\nMainPID=0\nNRestarts=0\nInvocationID=\nResult=success\nExecMainCode=0\nExecMainStatus=0\nDropInPaths='+str(w.GUARD)+'\n'},
                             'listeners':{'stdout':''},'dpkg-audit':{'stdout':''}}}
        self.assertEqual(set(r.continuation_records({'startup_diagnostic':True},capture,self.files)),set(w.CONTINUATION_PATHS))
        with self.assertRaisesRegex(ValueError,'baseline'):r.continuation_records({},capture,self.files)
        capture['webmin']['settings']['allow']='0.0.0.0/0'
        with self.assertRaisesRegex(ValueError,'baseline'):r.continuation_records({'startup_diagnostic':True},capture,self.files)


if __name__=='__main__':unittest.main()
