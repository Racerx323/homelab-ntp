#!/usr/bin/python3
"""Exercise real boot transitions and controller interruption handling offline."""
import base64
import copy
import importlib.util
import io
import json
import os
import stat
from pathlib import Path
import tarfile
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]


def load(path):
    spec=importlib.util.spec_from_file_location(path.stem.replace('-','_'),path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


boot=load(ROOT/'scripts/production-boot.py')
runner=load(ROOT/'scripts/run-production-boot.py')
fixture=load(Path(__file__).with_name('test_production_transition.py'))


class Host(boot.Boot):
    read=fixture.Host.read
    snapshot=fixture.Host.snapshot
    pair=fixture.Host.pair
    measure=fixture.Host.measure
    unit=fixture.Host.unit
    replace=fixture.Host.replace
    state=fixture.Host.state
    boot=fixture.Host.boot

    def __init__(self,root):
        fixture.Host.__init__(self,root)
        self.spec.update(action='restart',prepared_epoch=int(time.time())-10,expires_epoch=int(time.time())+7200)
        self.units['timeservice.service'].update(ActiveState='active',SubState='running',MainPID='100')
        self.units['systemd-timesyncd.service']['ActiveState']='inactive'
        for name,row in self.identity.items():row.update(exe='/usr/local/sbin/'+name,start_ticks='old')
        self.baseline.update(running_pair=copy.deepcopy(self.identity),hardware={'fixture':'hardware'},boot_units={})
        for name,member in boot.base.CHANGES.items():
            self.files[Path(name)]=fixture.record(self.bytes[root/member])
            self.baseline['files'][name]=copy.deepcopy(self.files[Path(name)])
        for name in boot.BOOT_FILES:self.files[Path(name)]=fixture.record(b'boot config')
        self.hardware_failed=False

    def hardware(self):
        if self.hardware_failed:raise ValueError('hardware mismatch')
        return self.baseline['hardware']

    def shm(self):return {'nmea':{'cpid':str(self.identity['gpsd']['pid'])},'pps':{'cpid':str(self.identity['gpsd']['pid'])}}

    def run(self,argv,timeout=15):
        result=fixture.Host.run(self,argv,timeout)
        if argv[:2] in (['/usr/bin/systemctl','enable'],['/usr/bin/systemctl','disable']):
            self.units[argv[2]]['UnitFileState']='enabled' if argv[1]=='enable' else 'disabled'
        return result

    def boot_host(self):
        self.current_boot='new-boot'
        self.units['timeservice.service'].update(ActiveState='active',SubState='running',MainPID='200')
        for row in self.identity.values():row.update(pid=row['pid']+100,start_ticks='new')


class Lifecycle(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.tx=Host(Path(self.temp.name))
        p=patch.object(boot.socket,'gethostname',return_value='fixture');p.start();self.addCleanup(p.stop)
        p=patch.object(boot.base,'protocol_files',side_effect=self.protocol);p.start();self.addCleanup(p.stop)

    def protocol(self):
        if self.tx.current_boot=='boot':return {}
        epoch=time.time();value=float(base64.b64decode(self.tx.state()['drift_after_stop']['base64']))
        raw=f'{int(epoch//86400)+40587} {epoch%86400:.6f} 0.0.0.0 c012 02 freq_set kernel {value:.6f} PPM\n'.encode()
        return {'protostats.20261015':{'inode':1,'device':2,'size':len(raw),'sha256':boot.base.sha(raw),'raw':raw}}

    def start(self):
        self.tx.apply();self.tx.reboot();self.tx.boot_host();return self.tx.verify()

    def proofs(self,state):
        return {'endpoints':{a:copy.deepcopy(state) for a in self.tx.spec['endpoints']},'client':{
            'target':'fixture','spec_sha256':boot.base.sha(boot.base.encoded(self.tx.spec)),
            'epoch':time.time(),'checks':{'ipv4':True,'ipv6':True,'queries_denied':True}}}

    def test_enable_once_new_boot_drift_and_structural_handoff(self):
        state=self.start();self.assertTrue(state['drift_seed_observed'])
        result=self.tx.accept(self.proofs(state));self.assertEqual(result['phase'],'monitoring')
        self.assertEqual(self.tx.invoke('observe')['new_boot_id'],'new-boot')
        self.assertFalse(runner.parent.timing_ready(result['health']['measurement']))
        self.assertEqual(self.tx.units['timeservice.service']['UnitFileState'],'enabled')
        self.assertFalse(any(name in self.tx.writes for name in (*boot.base.CHANGES,boot.base.DRIFT,*boot.BOOT_FILES)))
        self.assertNotIn(['/usr/bin/systemctl','daemon-reload'],self.tx.calls)
        with self.assertRaisesRegex(ValueError,'single'):self.tx.reboot()

    def test_preflight_identity_failure_never_mutates_enablement(self):
        self.tx.identity['gpsd']['pid']+=1
        with self.assertRaises(ValueError):self.tx.apply()
        self.assertFalse(any(x[:2]==['/usr/bin/systemctl','enable'] for x in self.tx.calls))
        self.assertFalse((self.tx.root/'state.json').exists())

    def test_partial_enablement_failure_recovers_original_boot_states(self):
        original=self.tx.run
        def run(argv,timeout=15):
            result=original(argv,timeout)
            if argv==['/usr/bin/systemctl','enable','timeservice.service']:raise ValueError('lost enable reply')
            return result
        with patch.object(self.tx,'run',side_effect=run),self.assertRaisesRegex(ValueError,'lost enable'):self.tx.apply()
        self.assertEqual(self.tx.state()['phase'],'bootstrap_recovered')
        self.assertEqual(self.tx.units['timeservice.service']['UnitFileState'],'disabled')
        self.assertEqual(self.tx.units['systemd-timesyncd.service']['UnitFileState'],'enabled')

    def test_same_boot_verify_refuses_and_recovery_preserves_drift(self):
        self.tx.apply();self.tx.reboot()
        with self.assertRaisesRegex(ValueError,'waiting'):self.tx.verify()
        state=self.tx.recover();self.assertFalse(state['ntp_serving'])
        self.assertEqual(state['retained_drift']['sha256'],state['drift_after_stop']['sha256'])

    def test_new_boot_failure_recovery_and_expired_window(self):
        self.tx.apply();self.tx.reboot();self.tx.boot_host();self.tx.hardware_failed=True
        with self.assertRaisesRegex(ValueError,'hardware'):self.tx.verify()
        self.tx.spec['expires_epoch']=1
        result=self.tx.recover();self.assertEqual(result['phase'],'bootstrap_recovered')
        self.assertEqual(result['recovery_boot_id'],'new-boot')
        self.assertFalse(result['bootstrap_sync_accepted'])
        self.assertIn(self.tx.root/'recovery-diagnostics.json',self.tx.bytes)

    def test_uncertain_reboot_persists_intent_and_cannot_replay(self):
        self.tx.apply();original=self.tx.run
        def run(argv,timeout=15):
            if argv==['/usr/bin/systemctl','--no-block','reboot']:raise OSError('SSH lost')
            return original(argv,timeout)
        with patch.object(self.tx,'run',side_effect=run),self.assertRaises(OSError):self.tx.reboot()
        self.assertEqual(self.tx.state()['phase'],'reboot_submitted')
        with self.assertRaisesRegex(ValueError,'single'):self.tx.reboot()

    def test_recovery_holds_on_configuration_drift_and_surviving_children(self):
        self.tx.apply();self.tx.files[Path('/etc/ntp.conf')]=fixture.record(b'foreign')
        before=len(self.tx.calls)
        with self.assertRaisesRegex(ValueError,'baseline drift'):self.tx.recover()
        self.assertEqual(len(self.tx.calls),before)
        self.tx.files[Path('/etc/ntp.conf')]=copy.deepcopy(self.tx.baseline['files']['/etc/ntp.conf'])
        self.tx.helper.bounded=lambda *a,**k:{'returncode':0,'stdout':'999\n'}
        with self.assertRaisesRegex(ValueError,'child remains'):self.tx.recover()
        self.assertNotIn(['/usr/bin/systemctl','start','systemd-timesyncd.service'],self.tx.calls)

    def test_wrong_seed_or_old_protocol_cannot_pass(self):
        self.tx.apply();self.tx.reboot();self.tx.boot_host()
        with patch.object(boot.base,'protocol_files',return_value={}),self.assertRaisesRegex(ValueError,'seed'):self.tx.verify()
        self.assertIn('startup_journal',self.tx.state())

    def test_second_boot_changed_credentials_and_wrong_shm_creator_rejected(self):
        self.start();self.tx.current_boot='third-boot'
        with self.assertRaisesRegex(ValueError,'second reboot'):self.tx.verify()
        self.tx.current_boot='new-boot';self.tx.identity['gpsd']['uid']=[123]*4
        with self.assertRaisesRegex(ValueError,'daemon identity'):self.tx.verify()
        self.tx.identity['gpsd']['uid']=[65534]*4
        with patch.object(self.tx,'shm',return_value={'nmea':{'cpid':'9000'}}),self.assertRaisesRegex(ValueError,'SHM creator'):self.tx.verify()

    def test_missing_endpoint_or_stale_client_cannot_handoff(self):
        state=self.start();proof=self.proofs(state);proof['endpoints'].pop('2001:db8::1')
        with self.assertRaisesRegex(ValueError,'both endpoints'):self.tx.accept(proof)
        proof=self.proofs(state);proof['client']['epoch']-=500
        with self.assertRaisesRegex(ValueError,'client proof'):self.tx.accept(proof)
        self.assertEqual(self.tx.state()['phase'],'awaiting_handoff')

    def test_large_native_binary_uses_executable_bound_through_boot_and_recovery(self):
        native=self.tx.root/'ntpd';raw=b'x'*(2*1024*1024);native.write_bytes(raw);native.chmod(0o755)
        self.assertIn('error',runner.helper.file_record(str(native)))
        self.tx.spec['binaries']={str(native):{'sha256':boot.base.sha(raw),'mode':0o755}}
        original=self.tx.read
        self.tx.read=lambda path:native.read_bytes() if Path(path)==native else original(path)
        self.start();self.assertEqual(self.tx.recover()['phase'],'bootstrap_recovered')
        native.write_bytes(raw+b'changed')
        with self.assertRaisesRegex(ValueError,'binary drift'):self.tx.file_guard()

    def test_recovery_continuation_copies_data_only_and_forbids_reboot(self):
        state=self.tx.apply();source=self.tx
        root=source.root/'continuation';root.mkdir();tx=Host(root)
        tx.spec['purpose']='production-boot-recovery'
        tx.units=copy.deepcopy(source.units)
        tx.bytes[source.root/'spec.json']=boot.base.encoded(source.spec)
        tx.bytes[source.root/'state.json']=boot.base.encoded(state)
        tx.bytes[root/'recovery-state.json']=boot.base.encoded(state)
        tx.bytes[root/'recovery-source.json']=boot.base.encoded({'stage':str(source.root),
            'spec_sha256':boot.base.sha(boot.base.encoded(source.spec)),'state_sha256':boot.base.sha(boot.base.encoded(state))})
        tx.initialize_recovery()
        self.assertEqual(tx.invoke('recover')['phase'],'bootstrap_recovered')
        self.assertEqual(source.state(),state)
        with self.assertRaisesRegex(ValueError,'recovery-only'):tx.invoke('reboot')
        tx.bytes[source.root/'state.json']=b'changed'
        with self.assertRaisesRegex(ValueError,'continuity'):tx.initialize_recovery()


class RTCLifecycle(unittest.TestCase):
    protocol=Lifecycle.protocol
    start=Lifecycle.start
    proofs=Lifecycle.proofs

    def setUp(self):
        Lifecycle.setUp(self)
        self.rtc=load(ROOT/'scripts/rtc-commissioning.py')
        self.tx.spec['rtc_persistence']=True
        self.packages=f'{self.rtc.PACKAGE}\t{self.rtc.VERSION}\tii \n'
        self.clock='LocalRTC=no\n'
        self.timing='leap=00, stratum=1, refid=PPS, offset=0.01, rootdisp=1'
        self.rtc_offset=0;self.rtc_name='rtc-rv3028 1-0052'
        self.kernel=None
        for name in ('fake-hwclock.service','fake-hwclock-save.service','fake-hwclock-save.timer'):
            self.tx.units[name]={'LoadState':'not-found','ActiveState':'inactive'}
        original_load=boot.load
        original_run=self.tx.run
        original_bounded=self.tx.helper.bounded
        def execute(argv,**kwargs):
            if argv[0]=='/usr/bin/dpkg-query':out=self.packages
            elif argv[0]=='/usr/bin/dpkg':out=''
            elif argv[0]=='/usr/bin/timedatectl':
                self.assertEqual(argv,['/usr/bin/timedatectl','show']);out=self.clock
            elif argv[0]=='/usr/local/bin/ntpq':out=self.timing
            elif argv[0]=='/usr/sbin/hwclock':
                self.assertEqual(argv,['/usr/sbin/hwclock','--show','--utc','--noadjfile','--rtc=/dev/rtc0'])
                out='2026-10-15 21:00:00+00:00\n'
            else:return original_bounded(argv,**kwargs)
            self.tx.calls.append(argv)
            return {'returncode':0,'stdout':out,'stderr':''}
        def run(argv,timeout=15):
            if '--grep=rtc-rv3028' in argv:
                self.tx.calls.append(argv)
                rows=self.kernel if self.kernel is not None else [{'_BOOT_ID':self.tx.boot().replace('-',''),
                    'MESSAGE':f'rtc-rv3028 1-0052: setting system clock to 2026-10-15T21:00:00 UTC ({int(time.time())})'}]
                return '\n'.join(json.dumps(row) for row in rows)
            return original_run(argv,timeout)
        owner=self
        class RTCPath:
            def __init__(self,path):self.path=str(path)
            def __truediv__(self,name):return RTCPath(self.path+'/'+name)
            def lstat(self):return SimpleNamespace(st_mode=stat.S_IFCHR|0o600,st_rdev=os.makedev(251,0))
            def read_text(self):
                if self.path.endswith('/name'):return owner.rtc_name
                if self.path.endswith('/since_epoch'):return str(int(time.time())+owner.rtc_offset)
                raise AssertionError(self.path)
            def resolve(self):
                return {'/sys/class/rtc/rtc0':'/sys/devices/platform/soc/fe804000.i2c/i2c-1/1-0052/rtc/rtc0',
                    '/sys/class/rtc/rtc0/device/driver':'/sys/bus/i2c/drivers/rtc-rv3028',
                    '/sys/class/rtc/rtc0/device/of_node':'/sys/firmware/devicetree/base/soc/i2c@7e804000/rv3028@52'}[self.path]
        self.tx.helper.LIMIT=1024**2
        self.tx.helper.file_record=lambda path:{'sha256':self.rtc.HWCLOCK_SHA if path=='/usr/sbin/hwclock' else self.rtc.MANUAL_SHA}
        for obj,name,value in ((boot,'load',lambda path:self.rtc if path.name=='rtc-commissioning.py' else original_load(path)),
                (self.rtc,'Path',RTCPath),(self.tx.helper,'bounded',execute),(self.tx,'run',run),
                (boot.os.path,'lexists',lambda path:False)):
            p=patch.object(obj,name,value);p.start();self.addCleanup(p.stop)

    def test_read_only_rtc_proof_and_normal_boot_handoff(self):
        state=self.start()
        self.assertTrue(state['before']['rtc']['accepted'])
        self.assertTrue(state['rtc_after']['accepted'])
        self.assertEqual(self.tx.accept(self.proofs(state))['phase'],'monitoring')
        self.assertFalse(any('--systohc' in a or '--hctosys' in a for a in self.tx.calls))

    def test_bad_preflight_preserves_running_service_and_diagnostics(self):
        for name,value in (('packages',self.packages+'fake-hwclock\t1\tii \n'),('clock',''),
                           ('timing','leap=11'),('rtc_offset',90),('rtc_name','other RTC')):
            with self.subTest(name=name),patch.object(self,name,value),self.assertRaises(ValueError):self.tx.apply()
            self.assertFalse((self.tx.root/'state.json').exists())
            self.assertFalse(any(a[:2]==['/usr/bin/systemctl','stop'] for a in self.tx.calls))
            record=json.loads(self.tx.bytes[self.tx.root/'rtc-before.json'])
            self.assertFalse(record['accepted']);self.assertIn('error',record)

    def test_clock_hook_or_unit_blocks_before_mutation(self):
        with patch.object(boot.os.path,'lexists',side_effect=lambda p:p=='/etc/adjtime'):
            with self.assertRaisesRegex(ValueError,'clock file'):self.tx.apply()
        self.tx.units['fake-hwclock-save.timer']['LoadState']='loaded'
        with self.assertRaisesRegex(ValueError,'fake-clock'):self.tx.apply()
        self.assertFalse((self.tx.root/'state.json').exists())

    def test_kernel_proof_rejects_missing_foreign_duplicate_or_old_records(self):
        self.tx.apply();self.tx.reboot();self.tx.boot_host()
        valid={'_BOOT_ID':'newboot','MESSAGE':f'rtc-rv3028 1-0052: setting system clock to date UTC ({int(time.time())})'}
        for rows in ([],[dict(valid,_BOOT_ID='boot')],[valid,valid],
                     [dict(valid,MESSAGE='rtc-rv3028 1-0052: setting system clock to date UTC (1)')]):
            self.kernel=rows
            with self.subTest(rows=rows),self.assertRaisesRegex(ValueError,'initialization proof'):self.tx.invoke('verify')
            self.assertFalse(json.loads(self.tx.bytes[self.tx.root/'rtc-after.json'])['accepted'])
            # Re-enter the same submitted boot to exercise each independent I/O fixture.
            state=self.tx.state();state['phase']='reboot_submitted';self.tx.save(state)
        self.assertEqual(self.tx.recover()['phase'],'bootstrap_recovered')


class AcquisitionLifecycle(unittest.TestCase):
    setUp=Lifecycle.setUp
    protocol=Lifecycle.protocol
    proofs=Lifecycle.proofs

    def configure(self):
        self.clock=[10.0];self.tx.spec['acquisition_wait']=True
        raw=boot.base.encoded({'gpsd':['gpsd']})
        self.tx.bytes[self.tx.root/'timeservice.json']=raw
        self.tx.files[Path('/etc/ntpsec-timeservice.json')]=fixture.record(raw)
        self.tx.baseline['files']['/etc/ntpsec-timeservice.json']=fixture.record(raw)
        self.tx.apply();self.tx.reboot();self.tx.boot_host()
        self.gate={'state':'acquiring','boot_id':'new-boot','supervisor_pid':200,'gpsd_pid':201,
                   'started_monotonic':1,'updated_monotonic':10,'gpsd_start_ticks':'new','pairing':{'observed':False}}
        p=patch.object(boot.base.time,'monotonic',side_effect=lambda:self.clock[0]);p.start();self.addCleanup(p.stop)
        p=patch.object(boot.base,'process_identity',return_value=copy.deepcopy(self.tx.identity['gpsd']));p.start();self.addCleanup(p.stop)
        self.publish()

    def publish(self):
        self.gate['updated_monotonic']=self.clock[0]
        self.tx.bytes[Path('/run/ntpsec-startup/gate.json')]=boot.base.encoded(self.gate)

    def test_long_acquisition_then_saved_drift_and_boot_handoff(self):
        self.configure()
        for elapsed in (10,780,1860):
            self.clock[0]=elapsed;self.publish()
            self.assertEqual(self.tx.invoke('verify')['phase'],'acquiring')
        self.assertFalse(any(a[:2]==['/usr/bin/systemctl','start'] for a in self.tx.calls))
        self.gate.update(state='passed',pairing={'observed':True});self.publish()
        state=self.tx.verify();self.assertTrue(state['drift_seed_observed'])
        self.assertEqual(self.tx.accept(self.proofs(state))['phase'],'monitoring')
        self.assertEqual(self.tx.calls.count(['/usr/bin/systemctl','--no-block','reboot']),1)
        calls=list(self.tx.calls)
        self.assertEqual(self.tx.invoke('verify')['phase'],'monitoring')
        self.assertEqual(self.tx.calls,calls)

    def test_stale_progress_marks_fault_for_recovery_not_pending(self):
        self.configure();self.tx.invoke('verify');self.clock[0]=100
        with self.assertRaisesRegex(ValueError,'stale'):self.tx.invoke('verify')
        self.assertEqual(self.tx.state()['phase'],'startup_failed')
        self.assertEqual(self.tx.recover()['phase'],'bootstrap_recovered')

    def test_delayed_pairing_does_not_extend_structural_readiness(self):
        self.configure();self.tx.verify();self.clock[0]=780
        self.gate.update(state='passed',pairing={'observed':True});self.publish()
        with patch.object(self.tx,'measure',return_value={'peers':[]}):
            self.assertEqual(self.tx.invoke('verify')['phase'],'starting')
            self.clock[0]=901
            with self.assertRaisesRegex(ValueError,'associations'):self.tx.invoke('verify')
        self.assertEqual(self.tx.state()['phase'],'startup_failed')

    def test_prior_boot_gate_cannot_suppress_recovery(self):
        self.configure();self.gate['boot_id']='boot';self.publish()
        with self.assertRaisesRegex(ValueError,'invocation'):self.tx.invoke('verify')
        self.assertEqual(self.tx.state()['phase'],'startup_failed')


class Controller(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.spec={'purpose':'production-boot','prepared_epoch':int(time.time())-10,'expires_epoch':int(time.time())+3600,
                   'start_before_epoch':int(time.time())+2700,'endpoints':['192.0.2.1','2001:db8::1']}
        self.args=SimpleNamespace(bundle=self.root/'production-boot.tar',sha256='a'*64,mode='apply',console_ready=True,attempt=0)

    def run_controller(self,remote):
        with patch.object(runner,'prepare',return_value=(self.spec,{})),patch.object(runner,'remote',side_effect=remote),patch.object(runner.time,'sleep'):
            return runner.execute(self.args)

    def test_console_required_before_any_submission(self):
        self.args.console_ready=False
        with patch.object(runner,'prepare',return_value=(self.spec,{})),self.assertRaisesRegex(ValueError,'console'):runner.execute(self.args)
        self.assertFalse(list(self.root.glob('*-execution.json')))

    def test_uncertain_reboot_never_resubmits_and_failure_is_inspected(self):
        modes=[]
        def remote(root,spec,files,mode,label,address,proof=None):
            modes.append(mode)
            if mode in ('reboot','verify'):raise ValueError('transport lost')
            if mode=='readback':return {'phase':'reboot_submitted'}
            return {'phase':'bootstrap_recovered' if mode=='recover' else 'ready_to_reboot'}
        result=self.run_controller(remote)
        self.assertEqual(modes.count('reboot'),1);self.assertEqual(modes.count('verify'),20)
        self.assertEqual(modes[-2:],['readback','recover']);self.assertIn('recovery',result)

    def test_uncertain_handoff_keeps_monitoring_service(self):
        modes=[]
        def remote(root,spec,files,mode,label,address,proof=None):
            modes.append(mode)
            if mode=='accept':raise ValueError('lost handoff reply')
            return {'phase':'monitoring' if mode=='readback' else 'awaiting_handoff'}
        with patch.object(runner,'load',return_value=SimpleNamespace(check=lambda *a,**k:{})):
            result=self.run_controller(remote)
        self.assertNotIn('recover',modes);self.assertEqual(result['failure_readback']['phase'],'monitoring')

    def test_rejected_reboot_recovers_without_waiting_or_resubmitting(self):
        modes=[]
        def remote(root,spec,files,mode,label,address,proof=None):
            modes.append(mode)
            if mode=='reboot':raise ValueError('pre-reboot guard rejected')
            return {'phase':'bootstrap_recovered' if mode=='recover' else 'ready_to_reboot'}
        result=self.run_controller(remote)
        self.assertIn('recovery',result);self.assertNotIn('verify',modes)
        self.assertEqual(modes.count('reboot'),1)

    def test_resume_never_prepares_or_reboots(self):
        self.args.mode='resume';self.args.attempt=1;modes=[]
        def remote(root,spec,files,mode,label,address,proof=None):
            modes.append(mode);return {'phase':'monitoring','health':{'measurement':{}}}
        with patch.object(runner,'load',return_value=SimpleNamespace(check=lambda *a,**k:{})):self.run_controller(remote)
        self.assertNotIn('apply',modes);self.assertNotIn('reboot',modes)

    def test_recovery_allowed_after_expiry(self):
        self.spec['expires_epoch']=1;self.args.mode='recover';self.args.attempt=1
        result=self.run_controller(lambda *a,**k:{'phase':'bootstrap_recovered'})
        self.assertNotIn('error',result)

    def test_pending_acquisition_returns_without_recovery_and_resumes_after_expiry(self):
        self.spec['acquisition_wait']=True;modes=[]
        def remote(root,spec,files,mode,label,address,proof=None):
            modes.append(mode);return {'phase':'acquiring' if mode=='verify' else 'reboot_submitted'}
        first=self.run_controller(remote)
        self.assertEqual(first['state']['phase'],'acquiring')
        self.spec['expires_epoch']=1;self.args.mode='resume';self.args.attempt=61
        later=self.run_controller(remote)
        self.assertEqual(later['state']['phase'],'acquiring')
        self.assertEqual(modes,['apply','reboot','verify','verify'])

    def test_failed_gate_recovers_without_transport_retry_loop(self):
        self.spec['acquisition_wait']=True;self.args.mode='resume';self.args.attempt=1;modes=[]
        def remote(root,spec,files,mode,label,address,proof=None):
            modes.append(mode)
            if mode=='verify':raise ValueError('startup fault')
            return {'phase':'startup_failed' if mode=='readback' else 'bootstrap_recovered'}
        result=self.run_controller(remote)
        self.assertEqual(modes,['verify','readback','recover'])
        self.assertEqual(result['recovery']['phase'],'bootstrap_recovered')

    def test_seal_from_accepted_data_is_flat_and_rejects_changed_receipts(self):
        old_umask=os.umask(0o077);self.addCleanup(os.umask,old_umask)
        folder,archive,digest=fixture.Controller().fixture(self.root)
        old,files=fixture.controller.prepare(archive,digest)
        old['action']='restart'
        baseline=json.loads(files['baseline.json'])
        units={name:{'returncode':0,'stdout':'LoadState=not-found\nActiveState=inactive\nSubState=dead\nUnitFileState=\nDropInPaths=\n'}
               for name in ('gpsd.service','gpsd.socket','ntpsec.service','avahi-daemon.service','ntpleapfetch.timer')}
        capture=runner.encoded({'boot_before':'boot','boot_after':'boot','commands':units})
        (self.root/'stdout.txt').write_bytes(capture);baseline['capture_sha256']=runner.sha(capture)
        files['baseline.json']=runner.encoded(baseline)
        old['members']['baseline.json']=runner.sha(files['baseline.json']);files['spec.json']=runner.encoded(old)
        with tarfile.open(archive,'w') as out:
            for name,raw in files.items():
                info=tarfile.TarInfo(name);info.size=len(raw);out.addfile(info,io.BytesIO(raw))
        digest=runner.sha(archive.read_bytes());now=int(time.time())
        measurement=fixture.peers(old['nts_servers']);measurement['system']={'leap':0,'stratum':1,'refid':'PPS','offset':0.01}
        for row in measurement['peers']:row['variables'].update(reach=255,jitter=0.01,ntscookies=8)
        state={'phase':'monitoring','boot_id':'boot','drift_seed_observed':True,'health':{
            'epoch':now,'pair':{'fixture':'pair'},'unit':{'ActiveState':'active','UnitFileState':'disabled','NRestarts':'0','MainPID':'100'},
            'measurement':measurement}}
        outcome={'bundle_sha256':digest,'state':state,'timing_ready':True}
        for name,value in {'observe-18-outcome.json':outcome,'observe-18-result.json':state,
                           'observe-18-transport.json':{'returncode':0},
                           'observe-18-execution.json':{'mode':'observe','sha256':digest,'epoch':now},
                           'apply-outcome.json':outcome}.items():(folder/name).write_bytes(runner.encoded(value))
        hardware=self.root/'hardware';hardware.mkdir(mode=0o700)
        spec={'hostname':old['hostname']}
        report={'phase':'runtime_validated','boot_id':'boot','hardware':{'fixture':'hardware'},
                'checks':dict.fromkeys(('continuity','failed_stage','hardware','idle_workers','restoration','runtime','source_preserved'),True)}
        raw=runner.encoded(spec)
        with tarfile.open(hardware/'runtime-revalidation.tar','w') as out:
            info=tarfile.TarInfo('spec.json');info.size=len(raw);out.addfile(info,io.BytesIO(raw))
        receipt={'state':'runtime_validated','report_sha256':runner.sha(runner.encoded(report)),
                 'spec_sha256':runner.sha(raw),'bundle_sha256':runner.sha((hardware/'runtime-revalidation.tar').read_bytes())}
        for name,value in {'acceptance.json':receipt,'start-0-result.json':{'result':report},'spec.json':spec}.items():
            (hardware/name).write_bytes(runner.encoded(value))
        args=SimpleNamespace(restart_dir=folder,restart_sha256=digest,observation=18,hardware_dir=hardware,
                             inspection_dir=self.root,operation_id='boot-fixture',output=self.root/'sealed')
        sealed=runner.seal(args);new,members=runner.prepare(Path(sealed['bundle']),sealed['sha256'])
        self.assertEqual(new['purpose'],'production-boot')
        self.assertFalse(any(name.endswith('.tar') for name in members))
        self.assertEqual(members['ntp.conf'],files['ntp.conf'])
        rtc_dir=self.root/'rtc';rtc_dir.mkdir(mode=0o700)
        client_dir=self.root/'client';client_dir.mkdir(mode=0o700)
        rtc_spec={'action':'set-readback','boot_id':'boot','hostname':old['hostname'],'operation_id':'rtc-fixture'}
        client_spec={'monitor_sha256':digest,'monitor_spec_sha256':runner.sha(files['spec.json']),
                     'observation_sha256':runner.sha(runner.encoded(outcome)),
                     'hostname':old['hostname'],'endpoints':old['endpoints']}
        for dest,spec in ((rtc_dir/'rtc-commissioning.tar',rtc_spec),(client_dir/'client-native-discovery.tar',client_spec)):
            raw=runner.encoded(spec)
            with tarfile.open(dest,'w') as out:
                item=tarfile.TarInfo('spec.json');item.size=len(raw);out.addfile(item,io.BytesIO(raw))
        args.rtc_dir=rtc_dir;args.rtc_sha256=runner.sha((rtc_dir/'rtc-commissioning.tar').read_bytes())
        args.client_dir=client_dir;args.client_sha256=runner.sha((client_dir/'client-native-discovery.tar').read_bytes())
        rtc_result={'accepted':True,'returncode':0,'bundle_sha256':args.rtc_sha256}
        rtc_state={'accepted':True,'operation_id':'rtc-fixture','rtc_after':{'before_epoch':now-10,'after_epoch':now-9,'rtc_epoch':now-10}}
        client_result={'client_accepted':True,'bundle_sha256':args.client_sha256,'spec_sha256':runner.sha(runner.encoded(client_spec)),
                       'checks':dict.fromkeys(('ipv4','ipv6','mdns','queries_denied'),True),'epoch':now}
        for path,value in ((rtc_dir/'result.json',rtc_result),(rtc_dir/'stdout.txt',rtc_state),(client_dir/'result.json',client_result)):
            path.write_bytes(runner.encoded(value))
        args.output=self.root/'rtc-sealed'
        rtc_sealed=runner.seal(args);rtc_new,rtc_members=runner.prepare(Path(rtc_sealed['bundle']),rtc_sealed['sha256'])
        self.assertTrue(rtc_new['rtc_persistence'])
        self.assertFalse(any(name.endswith('.tar') for name in rtc_members))
        self.assertEqual(json.loads(rtc_members['baseline.json'])['rtc_commissioning']['readback'],rtc_state['rtc_after'])
        args.output=self.root/'rtc-rejected'
        for path,value,key,bad,match in ((rtc_dir/'result.json',rtc_result,'accepted',False,'commissioning'),
                (rtc_dir/'stdout.txt',rtc_state,'operation_id','foreign','commissioning'),
                (client_dir/'result.json',client_result,'client_accepted',False,'client proof')):
            changed=dict(value);changed[key]=bad;path.write_bytes(runner.encoded(changed))
            with self.assertRaisesRegex(ValueError,match):runner.seal(args)
            path.write_bytes(runner.encoded(value))
        self.assertFalse(args.output.exists())
        args.rtc_dir=args.rtc_sha256=args.client_dir=args.client_sha256=None
        args.output=Path(sealed['bundle']).parent
        failed_state={'phase':'ready_to_reboot','boot_id':'boot'}
        for name,value in {'apply-outcome.json':{'bundle_sha256':sealed['sha256'],'failure_readback':failed_state},
                           'apply-failure-readback-result.json':failed_state,
                           'apply-failure-readback-transport.json':{'returncode':0},
                           'apply-execution.json':{'sha256':sealed['sha256']}}.items():
            (args.output/name).write_bytes(runner.encoded(value))
        recovery=runner.seal_recovery(SimpleNamespace(failed_dir=args.output,failed_sha256=sealed['sha256'],
            operation_id='recovery-fixture',output=self.root/'recovery'))
        recovered,parts=runner.prepare(Path(recovery['bundle']),recovery['sha256'])
        self.assertEqual(recovered['purpose'],'production-boot-recovery')
        self.assertIn('recovery-state.json',parts)
        self.assertFalse(any(name.endswith('.tar') for name in parts))
        self.assertEqual(json.loads(parts['recovery-source.json'])['stage'],new['stage'])
        receipt['report_sha256']='0'*64;(hardware/'acceptance.json').write_bytes(runner.encoded(receipt))
        args.output=self.root/'rejected'
        with self.assertRaisesRegex(ValueError,'hardware report'):runner.seal(args)
        (Path(sealed['bundle']).parent/'review.md').write_text('tampered')
        with self.assertRaisesRegex(ValueError,'approval input'):runner.prepare(Path(sealed['bundle']),sealed['sha256'])

    def test_payload_compiles_and_has_only_flat_repository_code(self):
        spec={**self.spec,'stage':'/var/lib/ntp-boot-fixture','hostname':'fixture','members':{}}
        raw=runner.payload(spec,{'spec.json':runner.encoded(spec)},'verify',None)
        compile(raw,'payload','exec')
        self.assertNotIn(b'.local-evidence',raw);self.assertNotIn(b'tarfile',raw)


if __name__=='__main__':unittest.main()
