#!/usr/bin/python3
"""Real transition control flow with simulated host I/O; no target contact."""
import base64
import copy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import tarfile
import io
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]

def load(name):
    s=importlib.util.spec_from_file_location(name.replace('-','_'),ROOT/'scripts'/name)
    m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

stage=load('production-transition.py')
controller=load('run-production-transition.py')


def record(raw,uid=0,gid=0,mode=0o640):
    return {'sha256':stage.sha(raw),'base64':base64.b64encode(raw).decode(),
            'uid':uid,'gid':gid,'mode':mode}


def peers(names):
    return {'system':{'leap':3,'stratum':16},'peers':[
        {'variables':{'srchost':name,'reach':0}} for name in ['SHM(0)','SHM(2)',*names]]}


class Host(stage.Transition):
    """Replace host I/O; use real apply, preflight, health, handoff and recovery."""
    def __init__(self,root):
        self.root=root;self.calls=[];self.writes=[]
        self.spec={'hostname':'fixture','operation_id':'fixture','stage':str(root),'watchdog':'fixture-watchdog',
                   'start_before_epoch':int(time.time())+3600,'nts_servers':['a','b','c'],
                   'old_units':['old.service','old.timer'],'binaries':{},'endpoints':['192.0.2.1','2001:db8::1']}
        self.baseline={'boot_id':'boot','supervisor_pid':100,'pair_pids':{'gpsd':101,'ntpd':102},
                       'files':{p:record(b'old') for p in stage.CHANGES}}
        self.files={Path(p):record(b'old') for p in stage.CHANGES}
        self.files[Path(stage.DRIFT)]=record(b'-9.3\n',999,985,0o640)
        self.baseline['recovered_drift_sha256']=stage.sha(b'-9.3\n')
        self.bytes={root/'timeservice.json':b'new recipe',root/'timeservice.service':b'new unit',root/'ntp.conf':b'new config'}
        self.units={'timeservice.service':{'ActiveState':'inactive','SubState':'dead','UnitFileState':'disabled',
                                         'DropInPaths':'','NRestarts':'0','MainPID':'0','LoadState':'loaded'},
                    'systemd-timesyncd.service':{'LoadState':'loaded','ActiveState':'active','UnitFileState':'enabled','DropInPaths':''},
                    'fixture-watchdog.timer':{'ActiveState':'inactive'}}
        self.identity={'gpsd':{'pid':101,'uid':[65534]*4,'gid':[20]*4,'argv':['gpsd']},
                       'ntpd':{'pid':102,'uid':[999]*4,'gid':[985]*4,'argv':[
                           '/usr/local/sbin/ntpd','-n','-m','-c','/etc/ntp.conf','-u','ntp:ntp']}}
        self.helper=SimpleNamespace(bounded=lambda *a,**k:{'returncode':1,'stdout':''})
        self.current_boot='boot';self.fail_start=False;self.foreign_write=False

    def read(self,path):return self.bytes[Path(path)]
    def snapshot(self,path):return copy.deepcopy(self.files[Path(path)])
    def boot(self):return self.current_boot
    def pair(self,main):return copy.deepcopy(self.identity)
    def shm(self):return {'fixture':'attached'}
    def measure(self):return peers(self.spec['nts_servers'])
    def unit(self,name):return copy.deepcopy(self.units.get(name,{'ActiveState':'inactive'}))
    def replace(self,path,raw,uid,gid,mode):
        self.writes.append(str(path))
        if str(path)==stage.DRIFT:raise AssertionError('must never write learned drift')
        if str(path) in self.changes:self.files[Path(path)]=record(raw,uid,gid,mode)
        else:self.bytes[Path(path)]=raw
        if Path(path)==self.root/'state.json':Path(path).write_bytes(raw)
    def state(self):return json.loads(self.bytes[self.root/'state.json'])
    def run(self,argv,timeout=15):
        self.calls.append(argv)
        if argv[0]=='/usr/bin/journalctl':
            return json.dumps({'_BOOT_ID':'boot','_PID':'102','MESSAGE':'PROTO: 0.0.0.0 01 freq_set kernel -9.300000 PPM'})
        if argv[0]=='/usr/bin/systemd-run':self.units['fixture-watchdog.timer']['ActiveState']='active'
        if argv[:2]==['/usr/bin/systemctl','stop']:
            self.units[argv[2]]['ActiveState']='inactive'
        if argv[:2]==['/usr/bin/systemctl','start']:
            if argv[2]=='timeservice.service' and self.fail_start:raise ValueError('injected start failure')
            self.units[argv[2]]['ActiveState']='active'
            if argv[2]=='timeservice.service':self.units[argv[2]].update(SubState='running',MainPID='100')
        return ''


class Lifecycle(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.tx=Host(Path(self.temp.name))
        self.host=patch.object(stage.socket,'gethostname',return_value='fixture')
        self.host.start();self.addCleanup(self.host.stop)
        self.protocol=patch.object(stage,'protocol_files',side_effect=self.protocol_capture)
        self.protocol.start();self.addCleanup(self.protocol.stop)

    def protocol_capture(self):
        if not (self.tx.root/'state.json').exists() or 'startup_epoch' not in self.tx.state():return {}
        epoch=time.time()
        day=int(epoch//86400)+40587;second=epoch%86400
        value=float(base64.b64decode(self.tx.state()['drift_after_stop']['base64']))
        raw=f'{day} {second:.6f} 0.0.0.0 c012 02 freq_set kernel {value:.6f} PPM\n'.encode()
        return {'protostats.20261015':{'inode':1,'device':2,'size':len(raw),'sha256':stage.sha(raw),'raw':raw}}

    def proofs(self,state):
        return {'endpoints':{a:copy.deepcopy(state) for a in self.tx.spec['endpoints']},
                'client':{'target':'fixture','spec_sha256':stage.sha(stage.encoded(self.tx.spec)),
                          'epoch':int(time.time()),'checks':{'ipv4':True,'ipv6':True,'queries_denied':True}}}

    def restart_fixture(self):
        tx=self.tx;tx.spec['action']='restart'
        tx.units['timeservice.service'].update(ActiveState='active',SubState='running',MainPID='100')
        tx.units['systemd-timesyncd.service']['ActiveState']='inactive'
        for name,row in tx.identity.items():row['start_ticks']='old-'+name
        tx.baseline.update(supervisor_pid=100,running_pair=copy.deepcopy(tx.identity))
        for name,member in stage.CHANGES.items():
            tx.files[Path(name)]=record(tx.bytes[tx.root/member])
            tx.baseline['files'][name]=copy.deepcopy(tx.files[Path(name)])
        original=tx.run
        def run(argv,timeout=15):
            result=original(argv,timeout)
            if argv[:3]==['/usr/bin/systemctl','start','timeservice.service']:
                tx.units['timeservice.service']['MainPID']='200'
                for name,row in tx.identity.items():row.update(pid=row['pid']+100,start_ticks='new-'+name)
            return result
        return patch.object(tx,'run',side_effect=run)

    def test_restart_preserves_latest_drift_and_configuration(self):
        with self.restart_fixture():
            self.tx.files[Path(stage.DRIFT)]=record(b'-9.4\n',999,985,0o640)
            original=copy.deepcopy(self.tx.files)
            state=self.tx.apply();self.tx.accept(self.proofs(state))
        self.assertTrue(state['drift_seed_observed'])
        self.assertNotEqual(state['health']['pair'],self.tx.baseline['running_pair'])
        self.assertEqual(self.tx.files,original)
        self.assertFalse(set(self.tx.writes)&set(stage.CHANGES))
        self.assertNotIn(['/usr/bin/systemctl','daemon-reload'],self.tx.calls)
        self.assertIn(['/usr/bin/systemctl','stop','timeservice.service'],self.tx.calls)

    def test_restart_failure_uses_bootstrap_without_rewriting_configuration(self):
        with self.restart_fixture():
            original=copy.deepcopy(self.tx.files);self.tx.fail_start=True
            with self.assertRaisesRegex(ValueError,'start failure'):self.tx.apply()
        self.assertEqual(self.tx.state()['phase'],'bootstrap_recovered')
        self.assertEqual(self.tx.files,original)
        self.assertFalse(set(self.tx.writes)&set(stage.CHANGES))
        self.assertEqual(self.tx.unit('systemd-timesyncd.service')['ActiveState'],'active')

    def test_restart_refuses_changed_daemon_before_stopping_service(self):
        with self.restart_fixture():
            self.tx.identity['gpsd']['start_ticks']='unexpected'
            with self.assertRaisesRegex(ValueError,'daemon identity'):self.tx.apply()
        self.assertFalse(any(a[:2]==['/usr/bin/systemctl','stop'] for a in self.tx.calls))

    def test_restart_rejects_unchanged_invocations_after_start(self):
        self.restart_fixture()  # Configure running baseline; omit the simulated new PIDs.
        with patch.object(stage.time,'monotonic',side_effect=[0,0,130]):
            with self.assertRaisesRegex(ValueError,'new daemon invocation'):self.tx.apply()
        self.assertEqual(self.tx.state()['phase'],'bootstrap_recovered')

    def start_fixture(self):
        self.restart_fixture()
        self.tx.spec['action']='start'
        self.tx.units['timeservice.service'].update(ActiveState='inactive',SubState='dead',MainPID='0')
        self.tx.units['systemd-timesyncd.service']['ActiveState']='active'

    def test_recovered_start_preserves_configuration_and_large_native_binary(self):
        self.start_fixture();tx=self.tx
        native=tx.root/'ntpd';raw=b'x'*(2*1024**2);native.write_bytes(raw);native.chmod(0o755)
        tx.bytes[native]=raw;tx.spec['binaries']={str(native):{'sha256':stage.sha(raw),'mode':0o755}}
        original=copy.deepcopy(tx.files)
        state=tx.apply();result=tx.accept(self.proofs(state))
        self.assertEqual(result['phase'],'monitoring');self.assertTrue(result['drift_seed_observed'])
        self.assertEqual(tx.files,original);self.assertFalse(set(tx.writes)&set(stage.CHANGES))
        self.assertIn(['/usr/bin/systemctl','stop','systemd-timesyncd.service'],tx.calls)
        self.assertNotIn(['/usr/bin/systemctl','daemon-reload'],tx.calls)

    def test_recovered_start_failure_preserves_configuration(self):
        self.start_fixture();original=copy.deepcopy(self.tx.files);self.tx.fail_start=True
        with self.assertRaisesRegex(ValueError,'start failure'):self.tx.apply()
        self.assertEqual(self.tx.state()['phase'],'bootstrap_recovered')
        self.assertEqual(self.tx.files,original);self.assertFalse(set(self.tx.writes)&set(stage.CHANGES))
        self.assertNotIn(['/usr/bin/systemctl','daemon-reload'],self.tx.calls)
        self.assertEqual(self.tx.unit('systemd-timesyncd.service')['ActiveState'],'active')

    def test_recovered_start_watchdog_uses_unchanged_configuration_fallback(self):
        self.start_fixture();original=copy.deepcopy(self.tx.files);self.tx.apply()
        result=self.tx.invoke('watchdog')
        self.assertEqual(result['phase'],'bootstrap_recovered')
        self.assertEqual(self.tx.files,original);self.assertFalse(set(self.tx.writes)&set(stage.CHANGES))
        self.assertEqual(self.tx.unit('systemd-timesyncd.service')['ActiveState'],'active')

    def test_recovered_start_rejects_native_or_drift_mismatch_before_stopping_bootstrap(self):
        self.start_fixture();tx=self.tx
        native=tx.root/'ntpd';native.write_bytes(b'x'*(2*1024**2));native.chmod(0o755)
        tx.bytes[native]=native.read_bytes();tx.spec['binaries']={str(native):{'sha256':'0'*64,'mode':0o755}}
        with self.assertRaisesRegex(ValueError,'native binary'):tx.apply()
        self.assertFalse(any(row[:2]==['/usr/bin/systemctl','stop'] for row in tx.calls))
        tx.spec['binaries']={};tx.files[Path(stage.DRIFT)]=record(b'-8.0\n',999,985,0o640)
        with self.assertRaisesRegex(ValueError,'recovered drift changed'):tx.apply()
        self.assertFalse(any(row[:2]==['/usr/bin/systemctl','stop'] for row in tx.calls))

    def test_apply_handoff_does_not_wait_for_timing_or_touch_drift(self):
        original=self.tx.drift();state=self.tx.apply()
        self.assertEqual(state['phase'],'awaiting_handoff')
        self.assertEqual(state['health']['measurement']['system']['leap'],3)
        self.assertEqual(self.tx.unit('fixture-watchdog.timer')['ActiveState'],'active')
        state=self.tx.accept(self.proofs(state))
        self.assertEqual(state['phase'],'monitoring')
        self.assertFalse(state['production_accepted'])
        self.assertEqual(self.tx.drift(),original)
        self.assertEqual(self.tx.unit('fixture-watchdog.timer')['ActiveState'],'inactive')
        self.assertEqual(self.tx.invoke('watchdog')['phase'],'monitoring')
        with self.assertRaisesRegex(ValueError,'consumed'):self.tx.apply()

    def test_failed_start_restores_files_and_bootstrap_without_drift_reset(self):
        self.tx.fail_start=True;original=self.tx.drift()
        with self.assertRaisesRegex(ValueError,'start failure'):self.tx.apply()
        state=self.tx.state();self.assertEqual(state['phase'],'bootstrap_recovered')
        self.assertFalse(state['ntp_serving']);self.assertFalse(state['bootstrap_sync_accepted'])
        self.assertEqual(self.tx.unit('systemd-timesyncd.service')['ActiveState'],'active')
        self.assertEqual(self.tx.unit('timeservice.service')['ActiveState'],'inactive')
        self.assertEqual(self.tx.drift(),original)
        for row in self.tx.files.values():self.assertNotEqual(row['sha256'],stage.sha(b'new recipe'))
        count=len(self.tx.calls);self.tx.recover();self.assertEqual(len(self.tx.calls),count)

    def test_watchdog_recovers_uncommitted_candidate_and_preserves_updated_drift(self):
        self.tx.apply();self.tx.files[Path(stage.DRIFT)]=record(b'-9.4\n',999,985,0o640)
        self.assertEqual(self.tx.invoke('watchdog')['phase'],'bootstrap_recovered')
        self.assertEqual(self.tx.drift()['sha256'],stage.sha(b'-9.4\n'))

    def test_partial_install_failure_recovers_both_files(self):
        original=self.tx.replace;failed=[]
        def replace(path,raw,uid,gid,mode):
            if str(path)=='/etc/systemd/system/timeservice.service' and raw==b'new unit' and not failed:
                failed.append(True);raise OSError('injected write interruption')
            return original(path,raw,uid,gid,mode)
        with patch.object(self.tx,'replace',side_effect=replace):
            with self.assertRaisesRegex(OSError,'write interruption'):self.tx.apply()
        self.assertEqual(self.tx.state()['phase'],'bootstrap_recovered')
        for name in stage.CHANGES:self.assertEqual(self.tx.snapshot(name)['sha256'],stage.sha(b'old'))

    def test_missing_saved_frequency_proof_keeps_journal_and_recovers(self):
        with patch.object(stage,'protocol_files',return_value={}),patch.object(stage.time,'monotonic',side_effect=[0,0,130]):
            with self.assertRaisesRegex(ValueError,'seed not observed'):self.tx.apply()
        self.assertEqual(self.tx.state()['phase'],'bootstrap_recovered')
        self.assertFalse(self.tx.state()['drift_seed_observed'])
        self.assertTrue(self.tx.state()['startup_journal'])
        self.assertEqual(self.tx.state()['startup_protocol'],{})

    def test_existing_protocol_history_cannot_satisfy_seed_or_be_rewritten(self):
        self.tx.apply()
        state=self.tx.state();health=state['startup_health']
        raw=b'old protocol history\n'
        old={'inode':1,'device':2,'size':len(raw),'sha256':stage.sha(raw)}
        state['protocol_cursor']={'protostats.20261015':old};self.tx.save(state)
        good={**old,'raw':raw}
        with patch.object(stage,'protocol_files',return_value={'protostats.20261015':good}):
            with self.assertRaisesRegex(ValueError,'seed not observed'):self.tx.startup_seed(health)
        for bad in ({**good,'inode':3},{**good,'size':1},{**good,'raw':b'changed protocol!!!\n'}):
            with patch.object(stage,'protocol_files',return_value={'protostats.20261015':bad}):
                with self.assertRaisesRegex(ValueError,'identity/content'):self.tx.startup_seed(health)
        with patch.object(stage,'protocol_files',return_value={}):
            with self.assertRaisesRegex(ValueError,'disappeared'):self.tx.startup_seed(health)

    def test_new_day_and_appended_protocol_record_are_accepted(self):
        self.tx.apply();state=self.tx.state();health=state['startup_health']
        fresh=self.protocol_capture()['protostats.20261015']['raw']
        raw=b'old history\n';old={'inode':1,'device':2,'size':len(raw),'sha256':stage.sha(raw)}
        state['protocol_cursor']={'protostats.20261014':old};self.tx.save(state)
        captured={'protostats.20261014':{**old,'raw':raw},
                  'protostats.20261015':{'inode':3,'device':2,'size':len(fresh),'sha256':stage.sha(fresh),'raw':fresh}}
        with patch.object(stage,'protocol_files',return_value=captured):self.tx.startup_seed(health)
        self.assertTrue(self.tx.state()['drift_seed_observed'])
        state['protocol_cursor']={'protostats.20261015':old};self.tx.save(state)
        combined=raw+fresh
        with patch.object(stage,'protocol_files',return_value={'protostats.20261015':{
                **old,'raw':combined,'size':len(combined),'sha256':stage.sha(combined)}}):
            self.tx.startup_seed(health)
        self.assertTrue(self.tx.state()['drift_seed_observed'])

    def test_preflight_drift_rejects_before_any_service_mutation(self):
        for fault in ('file','boot','drift','service','old-worker'):
            with self.subTest(fault=fault),tempfile.TemporaryDirectory() as d:
                tx=Host(Path(d))
                if fault=='file':tx.files[Path('/etc/ntpsec-timeservice.json')]=record(b'unexpected')
                if fault=='boot':tx.current_boot='another'
                if fault=='drift':tx.files[Path(stage.DRIFT)]=record(b'nan\n',999,985,0o640)
                if fault=='service':tx.units['timeservice.service']['ActiveState']='active'
                if fault=='old-worker':tx.units['old.service']={'ActiveState':'active'}
                with self.assertRaises(ValueError):tx.apply()
                self.assertFalse(any(a[0]=='/usr/bin/systemd-run' or a[:2] in
                    (['/usr/bin/systemctl','stop'],['/usr/bin/systemctl','start']) for a in tx.calls))

    def test_handoff_rejects_missing_endpoint_wrong_pid_or_stale_proof(self):
        state=self.tx.apply()
        for case in ('endpoint','pid','stale'):
            proof=self.proofs(state)
            if case=='endpoint':del proof['endpoints']['2001:db8::1']
            if case=='pid':proof['endpoints']['192.0.2.1']['health']['pair']['gpsd']['pid']=900
            if case=='stale':proof['client']['epoch']-=300
            with self.subTest(case=case),self.assertRaises((ValueError,KeyError)):self.tx.accept(proof)
        self.assertEqual(self.tx.unit('fixture-watchdog.timer')['ActiveState'],'active')

    def test_recovery_holds_on_unknown_file_boot_or_surviving_process(self):
        self.tx.apply()
        self.tx.current_boot='changed'
        with self.assertRaisesRegex(ValueError,'boot'):self.tx.recover()
        self.tx.current_boot='boot';self.tx.files[Path('/etc/ntpsec-timeservice.json')]=record(b'operator')
        with self.assertRaisesRegex(ValueError,'file drift'):self.tx.recover()
        self.tx.files[Path('/etc/ntpsec-timeservice.json')]=record(b'new recipe')
        self.tx.helper.bounded=lambda *a,**k:{'returncode':0,'stdout':'123\n'}
        with self.assertRaisesRegex(ValueError,'child remains'):self.tx.recover()
        self.assertEqual(self.tx.unit('systemd-timesyncd.service')['ActiveState'],'inactive')

    def test_unarmed_prepared_watchdog_does_not_stop_original_service(self):
        self.tx.save({'phase':'prepared','boot_id':'boot'})
        self.assertEqual(self.tx.invoke('watchdog')['phase'],'unchanged')
        self.assertEqual(self.tx.unit('timeservice.service')['ActiveState'],'inactive')
        self.assertEqual(self.tx.unit('systemd-timesyncd.service')['ActiveState'],'active')

    def test_real_shm_parser_accepts_boot_permissions_and_rejects_missing_consumer(self):
        raw='key shmid perms size cpid lpid nattch uid gid cuid cgid\n1314148400 0 600 96 10 20 2 0 0 0 0\n1314148402 2 666 96 10 20 2 0 0 0 0\n'
        with patch.object(stage.Path,'read_text',return_value=raw):
            result=stage.Transition.shm(self.tx)
        self.assertEqual(result['1314148400']['perms'],'600')
        for changed in (raw.replace('20 2','20 1'),raw.replace('600 96','666 96'),raw+raw.splitlines()[1]+'\n'):
            with patch.object(stage.Path,'read_text',return_value=changed),self.assertRaises(ValueError):
                stage.Transition.shm(self.tx)


class AcquisitionLifecycle(unittest.TestCase):
    setUp=Lifecycle.setUp
    protocol_capture=Lifecycle.protocol_capture
    proofs=Lifecycle.proofs

    def configure(self):
        self.clock=[0.0]
        self.tx.identity['gpsd']['start_ticks']='101'
        self.tx.spec['acquisition_wait']=True
        self.tx.bytes[self.tx.root/'timeservice.json']=stage.encoded({'gpsd':['gpsd']})
        self.gate={'state':'acquiring','boot_id':'boot','supervisor_pid':100,'gpsd_pid':101,
                   'started_monotonic':0,'updated_monotonic':0,'gpsd_start_ticks':'101','pairing':{'observed':False}}
        p=patch.object(stage.time,'monotonic',side_effect=lambda:self.clock[0]);p.start();self.addCleanup(p.stop)
        p=patch.object(stage,'process_identity',side_effect=self.identity);p.start();self.addCleanup(p.stop)
        self.publish()

    def identity(self,pid,binary,parent):
        self.assertEqual((pid,binary,parent),(101,'/usr/local/sbin/gpsd',100))
        return copy.deepcopy(self.tx.identity['gpsd'])

    def publish(self):
        self.gate['updated_monotonic']=self.clock[0]
        self.tx.bytes[Path('/run/ntpsec-startup/gate.json')]=stage.encoded(self.gate)

    def test_watchdog_allows_13_and_31_minute_acquisition_then_handoff(self):
        self.configure();self.assertEqual(self.tx.apply()['phase'],'acquiring')
        for elapsed in (600,780,1200,1860):
            self.clock[0]=elapsed;self.publish()
            self.assertEqual(self.tx.invoke('watchdog')['phase'],'acquiring')
        self.assertIn('--on-unit-inactive=30s',next(a for a in self.tx.calls if a[0]=='/usr/bin/systemd-run'))
        self.gate.update(state='passed',pairing={'observed':True});self.publish()
        state=self.tx.resume();self.assertEqual(state['phase'],'awaiting_handoff')
        self.assertEqual(state['deadline_monotonic'],2460)
        self.tx.accept(self.proofs(state))
        self.assertEqual(self.tx.invoke('watchdog')['phase'],'monitoring')
        calls=list(self.tx.calls)
        self.assertEqual(self.tx.resume()['phase'],'monitoring')
        self.assertEqual(self.tx.calls,calls)
        self.assertEqual(self.tx.calls.count(['/usr/bin/systemctl','start','timeservice.service']),1)

    def test_missing_initial_gate_is_bounded(self):
        self.configure();del self.tx.bytes[Path('/run/ntpsec-startup/gate.json')]
        original=self.tx.read
        def read(path):
            if str(path)=='/run/ntpsec-startup/gate.json':raise FileNotFoundError(path)
            return original(path)
        with patch.object(self.tx,'read',side_effect=read):
            self.assertEqual(self.tx.apply()['phase'],'starting')
            self.clock[0]=121
            with self.assertRaisesRegex(ValueError,'missing'):self.tx.resume()
        self.assertEqual(self.tx.state()['phase'],'bootstrap_recovered')

    def test_stale_gate_recovers_even_when_old_transaction_deadline_elapsed(self):
        self.configure();self.tx.apply();self.clock[0]=780
        with self.assertRaisesRegex(ValueError,'stale'):self.tx.invoke('watchdog')
        self.assertEqual(self.tx.state()['phase'],'bootstrap_recovered')
        self.assertEqual(self.tx.drift()['sha256'],stage.sha(b'-9.3\n'))
        calls=list(self.tx.calls)
        self.assertEqual(self.tx.resume()['phase'],'bootstrap_recovered')
        self.assertEqual(self.tx.calls,calls)

    def test_identity_failure_and_unexpected_ntpd_are_not_pending(self):
        for field,value in (('boot_id','old'),('supervisor_pid',999),('state','failed')):
            with self.subTest(field=field):
                self.setUp();self.configure();self.tx.apply()
                self.gate[field]=value;self.publish()
                with self.assertRaises(ValueError):self.tx.resume()
                self.assertEqual(self.tx.state()['phase'],'bootstrap_recovered')
        self.setUp();self.configure();self.tx.apply()
        original=self.tx.helper.bounded
        self.tx.helper.bounded=lambda argv,**kw: {'returncode':0,'stdout':'999\n'} if 'ntpd' in argv else original(argv,**kw)
        with self.assertRaisesRegex(ValueError,'ntpd present'):self.tx.resume()
        self.assertEqual(self.tx.state()['phase'],'bootstrap_recovered')

    def test_post_pairing_structural_deadline_is_not_extended(self):
        self.configure();self.tx.apply();self.clock[0]=780
        self.gate.update(state='passed',pairing={'observed':True});self.publish()
        with patch.object(self.tx,'measure',return_value={'peers':[]}):
            self.assertEqual(self.tx.resume()['phase'],'starting')
            self.clock[0]=901
            with self.assertRaisesRegex(ValueError,'associations'):self.tx.resume()
        self.assertEqual(self.tx.state()['phase'],'bootstrap_recovered')

    def test_missing_handoff_recovers_after_pairing_not_after_start(self):
        self.configure();self.tx.apply();self.clock[0]=1860
        self.gate.update(state='passed',pairing={'observed':True});self.publish()
        self.tx.resume();self.clock[0]=2401
        with self.assertRaisesRegex(ValueError,'handoff deadline'):self.tx.invoke('watchdog')
        self.assertEqual(self.tx.state()['phase'],'bootstrap_recovered')

    def test_upgrade_restores_both_scripts_and_preserves_drift_on_failure(self):
        with Lifecycle.restart_fixture(self):
            self.tx.spec.update(install_acquisition=True,acquisition_wait=True)
            for name,member in stage.RUNTIME.items():
                old=record(b'old runtime',mode=0o755)
                self.tx.files[Path(name)]=old;self.tx.baseline['files'][name]=copy.deepcopy(old)
                self.tx.bytes[self.tx.root/member]=b'new runtime'
            self.tx.fail_start=True
            with self.assertRaisesRegex(ValueError,'start failure'):self.tx.apply()
        self.assertEqual(self.tx.state()['phase'],'bootstrap_recovered')
        for name in stage.RUNTIME:self.assertEqual(self.tx.files[Path(name)]['sha256'],stage.sha(b'old runtime'))
        self.assertEqual(self.tx.drift()['sha256'],stage.sha(b'-9.3\n'))


class ProcessIdentity(unittest.TestCase):
    def test_protocol_file_reader_rejects_symlinks_and_ignores_filegen_link(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'protostats').symlink_to('/missing')
            with patch.object(stage,'STATS',root):self.assertEqual(stage.protocol_files(),{})
            (root/'protostats.20261015').symlink_to('/etc/passwd')
            with patch.object(stage,'STATS',root),self.assertRaises(OSError):stage.protocol_files()

    def test_protocol_seed_requires_first_new_event_time_and_value(self):
        epoch=1792079643
        # Compute date fields from the controlled epoch instead of assuming a calendar day.
        row=f'{epoch//86400+40587} {epoch%86400:.6f} 0.0.0.0 c012 02 freq_set kernel -9.300000 PPM\n'
        self.assertTrue(stage.drift_seed(row,-9.3,epoch-1,epoch+1))
        for bad in (row.replace('-9.300000','0.000000'),row.replace('0.0.0.0','192.0.2.1'),row.replace('02 freq_set','03 freq_set')):
            self.assertFalse(stage.drift_seed(bad+row,-9.3,epoch-1,epoch+1))
        self.assertFalse(stage.drift_seed(row,-9.3,epoch+1,epoch+5))
        self.assertFalse(stage.drift_seed(row,-9.3,epoch-5,epoch-1))

    def test_kernel_identity_without_gpsd_account_and_wrong_parent_rejection(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);proc=root/'123';proc.mkdir()
            (proc/'exe').symlink_to('/usr/local/sbin/gpsd')
            (proc/'stat').write_text('123 (gpsd) '+' '.join(['S','99']+['0']*17+['777']))
            (proc/'status').write_text('PPid:\t99\nUid:\t65534 65534 65534 65534\nGid:\t20 20 20 20\nGroups:\t20\n')
            (proc/'cmdline').write_bytes(b'/usr/local/sbin/gpsd\0-N\0')
            with patch.object(stage.pwd,'getpwuid',return_value=SimpleNamespace(pw_name='nobody')):
                value=stage.process_identity(123,'/usr/local/sbin/gpsd',99,root)
            self.assertEqual(value['account'],'nobody');self.assertEqual(value['start_ticks'],'777')
            with self.assertRaisesRegex(ValueError,'supervisor'):stage.process_identity(123,'/usr/local/sbin/gpsd',98,root)


class Controller(unittest.TestCase):
    def test_seal_start_uses_recovery_data_and_preserves_installed_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);folder,bundle,digest=self.fixture(root)
            old,files=controller.prepare(bundle,digest);old['purpose']='production-boot-recovery'
            baseline=json.loads(files['baseline.json'])
            before={}
            for name,member in stage.CHANGES.items():
                baseline['files'][name]=record(files[member]);before[name]=baseline['files'][name]
            files['baseline.json']=stage.encoded(baseline)
            old['members']['baseline.json']=stage.sha(files['baseline.json'])
            recovery=root/'boot-recovery';recovery.mkdir(mode=0o700)
            archive=recovery/'production-boot.tar'
            with tarfile.open(archive,'w') as out:
                for name,raw in {'spec.json':stage.encoded(old),**{n:files[n] for n in controller.EXTRA}}.items():
                    info=tarfile.TarInfo(name);info.size=len(raw);out.addfile(info,io.BytesIO(raw))
            archive.chmod(0o600);digest=stage.sha(archive.read_bytes())
            state={'phase':'bootstrap_recovered','boot_id':'boot','recovery_boot_id':'boot','ntp_serving':False,
                   'retained_drift':record(b'-9.3\n',999,985,0o640),'before':{'files':before}}
            values={'recover-1-recover-result.json':state,'recover-1-outcome.json':{'bundle_sha256':digest,'state':state},
                    'recover-1-execution.json':{'sha256':digest,'mode':'recover'},'recover-1-recover-transport.json':{'returncode':0}}
            for name,value in values.items():(recovery/name).write_bytes(stage.encoded(value));(recovery/name).chmod(0o600)
            args=SimpleNamespace(boot_recovery_dir=recovery,recovery_sha256=digest,operation_id='start-fixture',output=root/'start')
            sealed=controller.seal(args);spec,new=controller.prepare(Path(sealed['bundle']),sealed['sha256'])
            self.assertEqual(spec['action'],'start')
            for name in ('ntp.conf','timeservice.json','timeservice.service'):self.assertEqual(new[name],files[name])
            self.assertFalse(any(name.endswith('.tar') for name in new))
            self.assertNotIn('running_pair',json.loads(new['baseline.json']))
            (recovery/'recover-1-recover-transport.json').write_bytes(stage.encoded({'returncode':1}))
            with self.assertRaisesRegex(ValueError,'confirmed same-boot recovery'):controller.seal(args)

    def test_restart_seal_uses_accepted_service_and_client_data_without_nesting(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);folder,bundle,digest=self.fixture(root)
            old,files=controller.prepare(bundle,digest)
            measurement=peers(old['nts_servers']);measurement['system']={'leap':0,'stratum':1,'refid':'PPS','offset':0.01}
            for row in measurement['peers']:row['variables'].update(reach=255,jitter=0.01,ntscookies=8)
            now=int(time.time())
            health={'pair':{'fixture':'same'},'epoch':now,'measurement':measurement,
                    'unit':{'MainPID':'100','ActiveState':'active','NRestarts':'0'}}
            state={'phase':'monitoring','health':health,'boot_id':'boot'}
            outcome={'bundle_sha256':digest,'state':state,'timing_ready':True}
            for name,value in {'observe-10-outcome.json':outcome,'observe-10-result.json':state,
                               'observe-10-transport.json':{'returncode':0},
                               'observe-10-execution.json':{'sha256':digest,'mode':'observe','epoch':now},
                               'apply-outcome.json':outcome}.items():
                (folder/name).write_bytes(stage.encoded(value));(folder/name).chmod(0o600)
            client=root/'client';client.mkdir(mode=0o700)
            client_spec={'monitor_sha256':digest,'monitor_spec_sha256':stage.sha(files['spec.json']),
                         'observation_sha256':stage.sha(stage.encoded(outcome)),
                         'hostname':old['hostname'],'endpoints':old['endpoints']}
            raw=stage.encoded(client_spec);archive=client/'client-native-discovery.tar'
            with tarfile.open(archive,'w') as out:
                info=tarfile.TarInfo('spec.json');info.size=len(raw);out.addfile(info,io.BytesIO(raw))
            archive.chmod(0o600);client_digest=stage.sha(archive.read_bytes())
            receipt={'bundle_sha256':client_digest,'spec_sha256':stage.sha(raw),'client_accepted':True,
                     'checks':dict.fromkeys(('ipv4','ipv6','mdns','queries_denied'),True),'epoch':now}
            (client/'result.json').write_bytes(stage.encoded(receipt));(client/'result.json').chmod(0o600)
            args=SimpleNamespace(restart_dir=folder,recovery_sha256=digest,observation=10,
                                 client_dir=client,client_sha256=client_digest,operation_id='restart-fixture',output=root/'restart')
            sealed=controller.seal(args);spec,new=controller.prepare(Path(sealed['bundle']),sealed['sha256'])
            self.assertEqual(spec['action'],'restart')
            for name in ('ntp.conf','timeservice.json','timeservice.service'):self.assertEqual(new[name],files[name])
            self.assertEqual(set(new),set(controller.PATHS)|controller.EXTRA|{'spec.json','review.md'})
            args.acquisition_wait=True;args.output=root/'wait-restart';args.operation_id='wait-fixture'
            sealed=controller.seal(args);wait_spec,wait_files=controller.prepare(Path(sealed['bundle']),sealed['sha256'])
            self.assertTrue(wait_spec['install_acquisition']);self.assertTrue(wait_spec['acquisition_wait'])
            self.assertEqual(json.loads(wait_files['timeservice.json'])['startup_gate']['acquisition_policy'],'wait')
            for name in ('timeservice.py','gpsd-pairing.py'):
                self.assertEqual(wait_files[name],(ROOT/'scripts'/name).read_bytes())
            self.assertEqual(wait_files['ntp.conf'],new['ntp.conf'])
            self.assertEqual(wait_files['timeservice.service'],new['timeservice.service'])
            receipt['client_accepted']=False;(client/'result.json').write_bytes(stage.encoded(receipt))
            with self.assertRaisesRegex(ValueError,'client proof'):controller.seal(args)
            # The upgrade may use this invocation's structural handoff and ready
            # observation, explicitly leaving final native discovery outstanding.
            proof={'target':old['hostname'],'spec_sha256':stage.sha(files['spec.json']),
                   'checks':dict.fromkeys(('ipv4','ipv6','queries_denied'),True),'epoch':now}
            outcome['state'].update(drift_seed_observed=True,startup_epoch=now-10,handoff_epoch=now)
            (folder/'apply-outcome.json').write_bytes(stage.encoded(outcome))
            (folder/'client-proof.json').write_bytes(stage.encoded(proof));(folder/'client-proof.json').chmod(0o600)
            args.client_dir=None;args.client_sha256=None;args.output=root/'structural-upgrade'
            sealed=controller.seal(args);candidate,_=controller.prepare(Path(sealed['bundle']),sealed['sha256'])
            self.assertEqual(candidate['client_prerequisite'],'structural')
            for change in ({'spec_sha256':'0'*64},{'checks':{'ipv4':True}},{'epoch':now+1}):
                (folder/'client-proof.json').write_bytes(stage.encoded({**proof,**change}))
                with self.assertRaisesRegex(ValueError,'structural client proof'):controller.seal(args)

    def fixture(self,root):
        source=root/'inspection';source.mkdir(mode=0o700)
        old={'hostname':'j2-svntp1','endpoints':['192.0.2.1','2001:db8::1'],
             'host_key_alias':'192.0.2.9','old_units':['old.service'],'watchdog':'old-watchdog','inspection_sha256':'1'*64}
        baseline={'boot_id':'boot','captured_epoch':int(time.time()),
                  'files':{name:record(b'old') for name in controller.helper.INSTALLED}}
        baseline['files']['/etc/ntp.conf']=record((ROOT/'configs/j2-svntp1-ntp.conf').read_bytes())
        restored_files=copy.deepcopy(baseline['files'])
        for row in baseline['files'].values():row.pop('base64')
        archive=source/'production-transition.tar'
        with tarfile.open(archive,'w') as out:
            for name,raw in {'spec.json':stage.encoded(old),'baseline.json':stage.encoded(baseline),'known_hosts':b'fixture key\n'}.items():
                item=tarfile.TarInfo(name);item.size=len(raw);out.addfile(item,io.BytesIO(raw))
        archive.chmod(0o600);digest=stage.sha(archive.read_bytes())
        receipt={'phase':'bootstrap_recovered','ntp_serving':False,'boot_id':'boot',
                 'retained_drift':record(b'-9.3\n',999,985,0o640),
                 'before':{'files':{n:restored_files[n] for n in stage.CHANGES if n!='/etc/ntp.conf'}}}
        values={'failure-readback-result.json':receipt,'apply-outcome.json':{'bundle_sha256':digest,'failure_readback':receipt},
                'apply-execution.json':{'sha256':digest},'failure-readback-transport.json':{'returncode':0}}
        for name,value in values.items():
            (source/name).write_bytes(stage.encoded(value));(source/name).chmod(0o600)
        output=root/'transition'
        sealed=controller.seal(SimpleNamespace(recovery_dir=source,recovery_sha256=digest,
                               operation_id='transition-fixture',output=output))
        return output,Path(sealed['bundle']),sealed['sha256']

    def test_seal_pins_flat_inputs_and_rejects_tampering(self):
        with tempfile.TemporaryDirectory() as d:
            root,bundle,digest=self.fixture(Path(d))
            spec,files=controller.prepare(bundle,digest)
            self.assertNotIn('pps_startup',json.loads(files['timeservice.json']))
            self.assertEqual(set(files),set(controller.PATHS)|controller.EXTRA|{'spec.json','review.md'})
            self.assertNotIn('OnFailure=',files['timeservice.service'].decode())
            original=(ROOT/'configs/j2-svntp1-ntp.conf').read_bytes()
            self.assertEqual(files['ntp.conf'],controller.production_config(original))
            self.assertEqual(files['ntp.conf'].count(b'filegen protostats'),1)
            self.assertNotIn('supervisor_pid',json.loads(files['baseline.json']))
            spec['members']['ntp.conf']=stage.sha(original)
            altered=dict(files,**{'ntp.conf':original,'review.md':controller.review(spec).encode()})
            with self.assertRaisesRegex(ValueError,'protocol-only'):controller.validate(spec,altered)
            with self.assertRaisesRegex(ValueError,'digest'):controller.prepare(bundle,'0'*64)
            (root/'review.md').write_text('changed')
            with self.assertRaisesRegex(ValueError,'input drift'):controller.prepare(bundle,digest)

    def test_controller_failure_reads_back_then_recovers_without_apply_replay(self):
        with tempfile.TemporaryDirectory() as d:
            root,bundle,digest=self.fixture(Path(d));calls=[]
            def remote(out,spec,files,mode,label,address,proof=None):
                calls.append(mode)
                if mode=='apply':raise ValueError('lost transport')
                return {'phase':'applying' if mode=='readback' else 'bootstrap_recovered'}
            args=SimpleNamespace(bundle=bundle,sha256=digest,mode='apply',attempt=0)
            with patch.object(controller,'remote',side_effect=remote):
                result=controller.execute(args)
                with self.assertRaises(FileExistsError):controller.execute(args)
            self.assertEqual(calls,['apply','readback','recover'])
            self.assertEqual(result['recovery']['phase'],'bootstrap_recovered')
            self.assertFalse(result['production_accepted'])

    def test_controller_uncertain_handoff_keeps_committed_service_running(self):
        with tempfile.TemporaryDirectory() as d:
            root,bundle,digest=self.fixture(Path(d));calls=[]
            def remote(out,spec,files,mode,label,address,proof=None):
                calls.append(mode)
                if mode=='apply':raise ValueError('connection lost')
                return {'phase':'monitoring'}
            with patch.object(controller,'remote',side_effect=remote):
                result=controller.execute(SimpleNamespace(bundle=bundle,sha256=digest,mode='apply',attempt=0))
            self.assertEqual(calls,['apply','readback']);self.assertNotIn('recovery',result)

    def test_pending_apply_and_expired_resume_do_not_replay_or_recover(self):
        with tempfile.TemporaryDirectory() as d:
            root,bundle,digest=self.fixture(Path(d));calls=[]
            def remote(out,spec,files,mode,label,address,proof=None):
                calls.append(mode);return {'phase':'acquiring'}
            args=SimpleNamespace(bundle=bundle,sha256=digest,mode='apply',attempt=0)
            with patch.object(controller,'remote',side_effect=remote):
                self.assertEqual(controller.execute(args)['state']['phase'],'acquiring')
                args.mode='resume';args.attempt=1
                with patch.object(controller.time,'time',return_value=time.time()+90000):
                    self.assertEqual(controller.execute(args)['state']['phase'],'acquiring')
            self.assertEqual(calls,['apply','resume'])

    def test_resume_handoff_is_retained_for_following_stages(self):
        with tempfile.TemporaryDirectory() as d:
            root,bundle,digest=self.fixture(Path(d));calls=[]
            def remote(out,spec,files,mode,label,address,proof=None):
                calls.append(mode)
                return {'phase':'monitoring' if mode=='accept' else 'awaiting_handoff',
                        'health':{'measurement':{}},'handoff_epoch':int(time.time())}
            (root/'apply-outcome.json').write_bytes(stage.encoded({'bundle_sha256':digest,'state':{'phase':'acquiring'}}))
            (root/'apply-outcome.json').chmod(0o600)
            args=SimpleNamespace(bundle=bundle,sha256=digest,mode='resume',attempt=1)
            with patch.object(controller,'remote',side_effect=remote),patch.object(controller,'load',return_value=SimpleNamespace(check=lambda *a,**k:{})):
                result=controller.execute(args)
            self.assertEqual(calls,['resume','readback','readback','accept'])
            self.assertEqual(controller.handoff_result(root,digest),result)
            self.assertEqual(json.loads((root/'apply-outcome.json').read_text())['state']['phase'],'acquiring')
            self.assertTrue((root/'resume-1-client-proof.json').exists())

    def test_timing_readiness_is_separate_from_structural_handoff(self):
        value=peers(['a','b','c']);self.assertFalse(controller.timing_ready(value))
        value['system']={'leap':0,'stratum':1,'refid':'PPS','offset':0.1}
        for p in value['peers']:p['variables'].update(reach=255,jitter=0.01,ntscookies=8)
        self.assertTrue(controller.timing_ready(value))
        value['peers'][3]['variables']['ntscookies']=0
        self.assertFalse(controller.timing_ready(value))

    def test_remote_payload_is_valid_python_and_contains_no_historical_import(self):
        spec={'stage':'/var/lib/ntp-production-fixture','hostname':'fixture','members':{}}
        files={'spec.json':stage.encoded(spec)}
        for mode in ('apply','readback','accept','recover'):
            raw=controller.payload(spec,files,mode,None);compile(raw,'payload','exec')
            self.assertNotIn(b'.local-evidence',raw)

    def test_structural_gate_accepts_unsynchronized_sources_but_not_missing_members(self):
        value=peers(['a','b','c'])
        self.assertTrue(stage.structural(value,['a','b','c']))
        value['peers'].pop();self.assertFalse(stage.structural(value,['a','b','c']))


if __name__=='__main__':unittest.main()
