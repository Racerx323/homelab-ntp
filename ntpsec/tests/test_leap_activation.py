#!/usr/bin/python3
"""Offline activation, rollback, sealing and uncertain-transport regressions."""
import base64
import importlib.util
import io
import json
import os
from pathlib import Path
import shlex
import tarfile
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
entry = importlib.util.spec_from_file_location('leap_runner', ROOT/'scripts/run-leap-activation.py')
r = importlib.util.module_from_spec(entry); entry.loader.exec_module(r)
w, h = r.worker, r.helper


class ActivationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.calls = []; self.failure = None
        self.service = self.root/'ntpleapfetch.service'; self.service.write_bytes(b'original\n'); self.service.chmod(0o644)
        self.timer = self.root/'ntpleapfetch.timer'; self.timer.write_bytes(b'timer\n')
        self.leap = self.root/'leap.list'; self.leap.write_bytes(b'#@ '+str(int(time.time())+2208988800+180*86400).encode()+b'\n')
        self.conf = self.root/'ntp.conf'; self.conf.write_bytes(b'leapfile fixture\n'); self.conf.chmod(0o644)
        self.boot = self.root/'boot'; self.boot.write_text('fixture-boot')
        self.directory = self.root/'ntpsec'; self.directory.mkdir(mode=0o755); self.directory.chmod(0o755)
        self.unit = {'LoadState':'loaded','ActiveState':'active','SubState':'running','UnitFileState':'enabled',
                     'MainPID':'814','InvocationID':'abc','NRestarts':'0','DropInPaths':'','FragmentPath':'/etc/systemd/system/timeservice.service'}
        self.timer_enabled = False; self.timer_active = False; self.service_result = 'success'
        self.foreign = False; self.failures = 0
        self.spec = {'hostname':'j2-svntp1','boot_id':'fixture-boot','operation_id':'fixture'}
        self.candidate = (ROOT/'templates/ntpleapfetch-j2.service').read_bytes()
        real_record = h.file_record

        def record(path, content=False):
            row = real_record(self.conf if str(path) == '/etc/ntp.conf' else path, content)
            if 'uid' in row: row.update(uid=0,gid=0)
            return row

        self.record = record
        self.baseline = {'service':dict(self.unit), 'files':{str(p):record(p, True) for p in (self.service,self.timer,self.leap)}}
        self.baseline['files']['/etc/ntp.conf'] = record('/etc/ntp.conf',True)
        for obj, name, value in ((w,'SERVICE',str(self.service)),(w,'TIMER',str(self.timer)),(w,'LEAP',str(self.leap)),
                (w.socket,'gethostname',lambda:'j2-svntp1'),(w.os,'geteuid',lambda:0),(w.os,'fchown',lambda *args:None),
                (h,'file_record',record),(h,'bounded',self.external)):
            p=patch.object(obj,name,value);p.start();self.addCleanup(p.stop)
        def mapped(path):
            return {'/proc/sys/kernel/random/boot_id':self.boot,'/var/lib/ntpsec':self.directory}.get(str(path),Path(path))
        p=patch.object(w,'Path',mapped);p.start();self.addCleanup(p.stop)
        # Simulate observed root ownership without privileged local tests.
        original_lstat = Path.lstat
        def lstat(path):
            value=original_lstat(path)
            if path == self.directory:
                values=list(value);values[4]=0;values[5]=0;return os.stat_result(values)
            return value
        p=patch.object(Path,'lstat',lstat);p.start();self.addCleanup(p.stop)
        self.operation=w.Activation(self.spec,self.baseline,self.candidate,h)
        self.operation.root=self.root/'operation'

    def external(self, argv, timeout=10):
        self.calls.append((argv,timeout)); out=''
        if argv[0] == w.FETCH:
            if self.failure == 'fetch': return {'returncode':1,'stdout':'bad checksum','stderr':''}
            Path(argv[-1]).write_bytes(self.leap.read_bytes());Path(argv[-1]).chmod(0o644)
            if self.failure == 'expired':Path(argv[-1]).write_bytes(b'#@ 2208988801\n')
        if argv[0] == '/usr/bin/systemctl':
            action=argv[1]
            if action == 'show':
                name=argv[2]
                if name == 'timeservice.service': data=dict(self.unit)
                else:
                    timer=name.endswith('.timer')
                    data={'LoadState':'loaded','ActiveState':'active' if timer and self.timer_active else 'inactive',
                        'SubState':'waiting' if timer and self.timer_active else 'dead','DropInPaths':'',
                        'FragmentPath':str(self.timer if timer else self.service),
                        'UnitFileState':('enabled' if self.timer_enabled else 'disabled') if timer else 'static',
                        'Result':self.service_result,'NextElapseUSecMonotonic':'15min' if self.timer_active else 'infinity'}
                    if self.failure == 'no-schedule' and self.timer_active:data['NextElapseUSecMonotonic']='infinity'
                out=''.join(k+'='+v+'\n' for k,v in data.items())
            if action == 'enable':self.timer_enabled=True;self.timer_active=True
            if action == 'disable':self.timer_enabled=False;self.timer_active=False
            if action == 'reset-failed':self.service_result='success'
            if action == self.failure and not self.failures:
                self.failures+=1
                if self.foreign:self.conf.write_bytes(b'foreign change')
                if action == 'start':self.service_result='exit-code'
                return {'returncode':1,'stdout':'','stderr':'fixture failure'}
        return {'returncode':0,'stdout':out,'stderr':''}

    def test_success_isolated_download_then_timer_without_ntp_restart(self):
        result=self.operation.run();self.assertTrue(result['accepted'],result)
        self.assertEqual(self.service.read_bytes(),self.candidate)
        self.assertEqual(result['checks'],dict.fromkeys(('isolated_fetch','maintenance_service','timer','continuity'),True))
        fetch=next(a for a,t in self.calls if a[0]==w.FETCH)
        self.assertIn('-F',fetch);self.assertNotIn('-c',fetch)
        self.assertEqual(fetch[-1],str(self.operation.root/'downloaded.list'))
        for argv,timeout in self.calls:
            if argv[0]=='/usr/bin/systemctl' and argv[1]!='show':
                self.assertNotIn('timeservice.service',argv);self.assertNotIn('restart',argv)

    def test_preflight_drift_leaves_no_operation_or_changes(self):
        self.conf.write_bytes(b'changed')
        result=self.operation.run();self.assertFalse(result['accepted']);self.assertFalse(self.operation.root.exists())
        self.assertEqual(self.service.read_bytes(),b'original\n')

    def test_wrong_boot_and_changed_supervisor_stop(self):
        self.boot.write_text('other');self.assertFalse(self.operation.run()['accepted'])
        self.boot.write_text('fixture-boot');self.unit['InvocationID']='other'
        self.assertFalse(self.operation.run()['accepted']);self.assertFalse(self.operation.root.exists())

    def test_existing_operation_is_not_overwritten(self):
        self.operation.root.mkdir();(self.operation.root/'state.json').write_text('previous')
        self.assertFalse(self.operation.run()['accepted'])
        self.assertEqual((self.operation.root/'state.json').read_text(),'previous')

    def test_bad_download_stops_before_install(self):
        self.failure='fetch';result=self.operation.run()
        self.assertFalse(result['accepted']);self.assertEqual(result['rollback'],'not-needed')
        self.assertEqual(self.service.read_bytes(),b'original\n');self.assertFalse(self.timer_enabled)

    def test_expired_download_stops_before_install(self):
        self.failure='expired';self.assertFalse(self.operation.run()['accepted'])
        self.assertEqual(self.service.read_bytes(),b'original\n')

    def test_service_failure_rolls_back(self):
        self.failure='start';result=self.operation.run()
        self.assertFalse(result['accepted']);self.assertEqual(result['rollback'],'restored',result)
        self.assertEqual(self.service.read_bytes(),b'original\n');self.assertFalse(self.timer_enabled)

    def test_partial_timer_enable_failure_rolls_back(self):
        self.failure='enable';result=self.operation.run()
        self.assertEqual(result['rollback'],'restored',result);self.assertFalse(self.timer_enabled)

    def test_missing_schedule_rolls_back(self):
        self.failure='no-schedule';result=self.operation.run()
        self.assertEqual(result['rollback'],'restored',result)

    def test_foreign_change_holds_recovery(self):
        self.failure='start';self.foreign=True;result=self.operation.run()
        self.assertEqual(result['rollback'],'held');self.assertEqual(self.conf.read_bytes(),b'foreign change')

    def test_unsafe_original_symlink_rejected(self):
        self.service.unlink();self.service.symlink_to(self.conf)
        self.assertFalse(self.operation.run()['accepted']);self.assertFalse(self.operation.root.exists())

    def test_signal_after_install_recovers(self):
        original=self.operation.cmd
        def interrupt(argv,timeout=10):
            if argv[1:3]==['start','ntpleapfetch.service']:w.interrupted(15,None)
            return original(argv,timeout)
        with patch.object(self.operation,'cmd',side_effect=interrupt):result=self.operation.run()
        self.assertEqual(result['rollback'],'restored',result)

    def test_unit_has_bounded_retry_and_valid_date_interval(self):
        command=next(line.split('=',1)[1] for line in self.candidate.decode().splitlines() if line.startswith('ExecStart='))
        argv=shlex.split(command)
        self.assertEqual(argv[argv.index('-i')+1],'0');self.assertEqual(argv[argv.index('-r')+1],'3')
        self.assertEqual(argv[argv.index('-e')+1],'60 days');self.assertIn(b'TimeoutStartSec=120',self.candidate)


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.spec={'schema':1,'purpose':'leap-activation','hostname':'j2-svntp1','boot_id':'a'*8+'-'+'b'*4+'-'+'c'*4+'-'+'d'*4+'-'+'e'*12,
            'operation_id':'fixture','endpoints':['10.1.0.51','fd36:5aa8:6971:1::51'],'host_key_alias':'10.1.0.137',
            'prepared_epoch':int(time.time()),'expires_epoch':int(time.time())+3600,'inspection_sha256':'a'*64}
        self.files={n:(ROOT/p).read_bytes() for n,p in r.PATHS.items()}
        self.files.update({'baseline.json':b'{}','known_hosts':b'fixture'})
        self.spec['members']={n:h.sha(v) for n,v in self.files.items()}
        self.files.update({'spec.json':h.encoded(self.spec),'review.md':r.review(self.spec).encode()})
        self.path=self.root/r.BUNDLE;self.pack()

    def pack(self):
        with tarfile.open(self.path,'w') as archive:
            for name,raw in self.files.items():
                item=tarfile.TarInfo(name);item.size=len(raw);archive.addfile(item,io.BytesIO(raw))
        self.path.chmod(0o600)
        for n in ('spec.json','review.md','known_hosts'):
            (self.root/n).write_bytes(self.files[n]);(self.root/n).chmod(0o600)
        self.digest=h.sha(self.path.read_bytes())

    def test_binding_and_payload_compile(self):
        spec,files=r.prepare(self.path,self.digest);compile(r.payload(spec,files),'sealed','exec')
        self.assertIn(b"signal.signal(signal.SIGALRM,space['interrupted'])",r.payload(spec,files))
        with self.assertRaisesRegex(ValueError,'digest'):r.prepare(self.path,'0'*64)
        (self.root/'review.md').write_text('other')
        with self.assertRaisesRegex(ValueError,'approval'):r.prepare(self.path,self.digest)

    def test_extra_archive_member_rejected(self):
        self.files['old.tar']=b'not allowed';self.pack()
        with self.assertRaisesRegex(ValueError,'flat'):r.prepare(self.path,self.digest)

    def test_expired_scope_rejected(self):
        with patch.object(r.time,'time',return_value=self.spec['expires_epoch']):
            with self.assertRaisesRegex(ValueError,'window'):r.prepare(self.path,self.digest)

    def test_partial_transport_retained_and_no_retry(self):
        args=type('Args',(),{'bundle':self.path,'sha256':self.digest})()
        with patch.object(h,'bounded',return_value={'returncode':255,'stdout':'partial','stderr':'lost'}) as call:
            self.assertFalse(r.execute(args)['accepted'])
            with self.assertRaises(FileExistsError):r.execute(args)
            self.assertEqual(call.call_count,1)
        self.assertEqual((self.root/'stdout.txt').read_text(),'partial')

    def test_foreign_result_not_accepted(self):
        args=type('Args',(),{'bundle':self.path,'sha256':self.digest})()
        state={'accepted':True,'operation_id':'other','spec_sha256':h.sha(h.encoded(self.spec))}
        with patch.object(h,'bounded',return_value={'returncode':0,'stdout':json.dumps(state),'stderr':''}):
            self.assertFalse(r.execute(args)['accepted'])


if __name__ == '__main__': unittest.main()
