#!/usr/bin/python3
"""One console-backed reboot; reuse drift and recover without replaying startup."""
import base64
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import re
import socket
import stat
import sys
import time


def load(path):
    spec=importlib.util.spec_from_file_location(path.stem.replace('-','_'),path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


base=load(Path(__file__).with_name('production-transition.py'))
BOOT_FILES=('/boot/firmware/config.txt','/boot/firmware/cmdline.txt')


class Boot(base.Transition):
    def rtc_check(self, after_reboot=False):
        """Read only: reuse commissioned identity, utility and readback checks."""
        rtc=load(self.root/'rtc-commissioning.py');rtc.helper=self.helper
        log=[];record={'boot_id':self.boot(),'commands':log,'accepted':False}
        try:
            packages=rtc.inventory(log);rtc.verify_utility(packages,log)
            if rtc.installed(packages,'fake-hwclock'):raise ValueError('fake-hwclock installed')
            for name in ('fake-hwclock.service','fake-hwclock-save.service','fake-hwclock-save.timer'):
                row=self.unit(name)
                if row['LoadState']!='not-found' or row['ActiveState']!='inactive':
                    raise ValueError('fake-clock unit present: '+name)
            for path in ('/etc/adjtime','/usr/sbin/fake-hwclock','/etc/init.d/fake-hwclock','/etc/cron.hourly/fake-hwclock'):
                if os.path.lexists(path):raise ValueError('unexpected clock file: '+path)
            rtc.rtc_identity()
            clock=rtc.command(['/usr/bin/timedatectl','show'],log)
            if 'LocalRTC=no\n' not in clock:raise ValueError('UTC RTC policy required')
            if not after_reboot:
                rtc.timing_ready(rtc.command(['/usr/local/bin/ntpq','-c','rv 0'],log,10))
            record['readback']=rtc.read_rtc(log);rtc.check_readback(record['readback'])
            if after_reboot:
                raw=self.run(['/usr/bin/journalctl','--quiet','--no-pager','--output=json',
                    '--boot='+self.boot().replace('-',''),'_TRANSPORT=kernel','--grep=rtc-rv3028','--lines=30'])
                rows=[json.loads(line) for line in raw.splitlines() if line.strip()]
                record['kernel_records']=rows
                epochs=[]
                for row in rows:
                    match=re.fullmatch(r'rtc-rv3028 1-0052: setting system clock to .+ UTC \(([0-9]+)\)',row.get('MESSAGE',''))
                    if match and row.get('_BOOT_ID')==self.boot().replace('-',''):epochs.append(int(match[1]))
                before=self.state()['before']['rtc']['readback']['before_epoch']
                if len(epochs)!=1 or not before-2<=epochs[0]<=record['readback']['after_epoch']+2:
                    raise ValueError('new-boot RTC clock initialization proof missing or outside reboot bracket')
                record['boot_clock_epoch']=epochs[0]
            record['accepted']=True
            return record
        except BaseException as error:
            record['error']=str(error);raise
        finally:
            self.replace(self.root/('rtc-after.json' if after_reboot else 'rtc-before.json'),base.encoded(record),0,0,0o600)

    def unit_guard(self):
        for name,expected in self.baseline['boot_units'].items():
            actual=self.unit(name)
            if any(actual.get(k)!=v for k,v in expected.items()):
                raise ValueError('boot prerequisite unit drift: '+name)
        for name in self.spec['old_units']:
            row=self.unit(name)
            if row['ActiveState'] not in ('inactive','failed') or row.get('UnitFileState','') not in ('','disabled','static','transient'):
                raise ValueError('old worker could run at boot')

    def hardware(self):
        checker=load(self.root/'host-configuration-stage.py')
        tx=object.__new__(checker.Transaction)
        tx.recipe=json.loads(self.read(self.root/'hardware-recipe.json'))
        tx.state=lambda: json.loads(self.read(self.root/'hardware-observation.json')) if (self.root/'hardware-observation.json').exists() else {}
        tx.write=lambda name,value:self.replace(self.root/'hardware-observation.json',base.encoded(value),0,0,0o600)
        actual=tx.hardware_metadata()
        if actual!=self.baseline['hardware']:raise ValueError('accepted hardware mapping changed')
        return actual

    def file_guard(self):
        for name,expected in self.baseline['files'].items():
            actual=self.snapshot(name)
            if any(actual[k]!=expected[k] for k in ('sha256','uid','gid','mode')):
                raise ValueError('installed baseline drift: '+name)
        for name,expected in self.spec['binaries'].items():
            raw=self.read(name)
            if base.sha(raw)!=expected['sha256'] or stat.S_IMODE(Path(name).stat().st_mode)!=expected['mode']:
                raise ValueError('accepted binary drift')

    def health(self):
        if not (self.root/'state.json').exists():return super().health()
        state=self.state()
        expected=state.get('new_boot_id')
        if not expected or expected==state['boot_id']:raise ValueError('new boot identity required')
        self.file_guard()
        self.unit_guard()
        if self.unit('systemd-timesyncd.service')['UnitFileState']!='disabled':
            raise ValueError('bootstrap must remain disabled at boot')
        health=super().health(expected_boot=expected,enabled='enabled')
        for name,row in health['pair'].items():
            old=self.baseline['running_pair'][name]
            if any(row[k]!=old[k] for k in ('uid','gid','argv','exe')):
                raise ValueError('post-boot daemon identity changed')
        # SHM IDs may be reused in a new kernel. Creator identity proves the new pair.
        if any(int(row['cpid']) not in {p['pid'] for p in health['pair'].values()} for row in health['shm'].values()):
            raise ValueError('fresh SHM creator must belong to accepted daemon pair')
        health['hardware']=self.hardware()
        return health

    def apply(self):
        if (self.root/'state.json').exists():raise ValueError('boot preparation already consumed')
        self.file_guard()
        before=self.preflight()  # Same-boot accepted running identities, files and drift.
        self.unit_guard()
        before['hardware']=self.hardware()
        before['boot_files']={name:self.snapshot(name) for name in BOOT_FILES}
        before['kernel']=os.uname().release
        if self.spec.get('rtc_persistence'):before['rtc']=self.rtc_check()
        state={'phase':'prepared','boot_id':self.boot(),'before':before,'production_accepted':False}
        self.save(state)
        try:
            state['phase']='enabling';self.save(state)
            self.system('disable','systemd-timesyncd.service')
            self.system('enable','timeservice.service')
            if (self.unit('timeservice.service')['UnitFileState']!='enabled'
                    or self.unit('systemd-timesyncd.service')['UnitFileState']!='disabled'):
                raise ValueError('boot enablement confirmation required')
            self.system('stop','timeservice.service');self.stopped()
            state['drift_after_stop']=self.drift()
            state['protocol_cursor']={n:{k:v for k,v in row.items() if k!='raw'} for n,row in base.protocol_files().items()}
            state['startup_epoch']=time.time()
            state['phase']='ready_to_reboot';self.save(state)
            return state
        except BaseException as error:
            state=self.state();state['apply_error']=str(error);self.save(state)
            self.recover();raise

    def reboot(self):
        state=self.state()
        if state['phase']!='ready_to_reboot' or self.boot()!=state['boot_id']:
            raise ValueError('single same-boot reboot submission required')
        if time.time()>=self.spec['start_before_epoch']:raise ValueError('reboot reserve expired; recover instead')
        self.file_guard();self.stopped()
        if self.drift()['sha256']!=state['drift_after_stop']['sha256']:
            raise ValueError('stopped drift changed')
        state['phase']='reboot_submitted';state['reboot_submission_epoch']=time.time();self.save(state)
        # Persist before submission. An uncertain reply never permits resubmission.
        self.system('--no-block','reboot')
        return state

    def verify(self):
        state=self.state()
        if state['phase'] in ('monitoring','bootstrap_recovered'):return state
        if state['phase'] not in ('reboot_submitted','starting','acquiring','awaiting_handoff'):raise ValueError('submitted boot required')
        current=self.boot()
        if current==state['boot_id']:raise ValueError('waiting for new boot')
        if state.get('new_boot_id',current)!=current:raise ValueError('unexpected second reboot')
        state['new_boot_id']=current;self.save(state)
        if os.uname().release!=state['before']['kernel']:raise ValueError('kernel changed')
        for name,old in state['before']['boot_files'].items():
            row=self.snapshot(name)
            if any(row[k]!=old[k] for k in ('sha256','uid','gid','mode')):raise ValueError('boot configuration changed')
        if self.spec.get('rtc_persistence') and 'rtc_after' not in state:
            state['rtc_after']=self.rtc_check(after_reboot=True);self.save(state)
        if self.acquisition_wait():
            self.file_guard();self.unit_guard();self.hardware()
            if self.unit('systemd-timesyncd.service')['UnitFileState']!='disabled':
                raise ValueError('bootstrap must remain disabled at boot')
            try:pending=self.acquisition(expected_boot=current,enabled='enabled')
            except FileNotFoundError:
                state=self.state();state.setdefault('gate_deadline',time.monotonic()+120)
                if state['phase']=='acquiring' or time.monotonic()>=state['gate_deadline']:
                    raise ValueError('startup gate missing')
                state['phase']='starting';self.save(state);return state
            state=self.state()
            if pending:
                state.update(phase='acquiring');self.save(state);return state
            if 'pairing_passed_monotonic' not in state:
                passed=state['startup_gate']['updated_monotonic']
                state.update(pairing_passed_monotonic=passed,structural_deadline=passed+120,
                             deadline_monotonic=passed+600)
                self.save(state)
            if time.monotonic()>=state['deadline_monotonic']-60:
                raise ValueError('structural handoff deadline expired')
        try:
            health=self.health()
            self.startup_seed(health)
        except (ValueError,OSError,KeyError) as error:
            if not self.acquisition_wait() or time.monotonic()>=self.state()['structural_deadline']:raise
            state=self.state();state.update(phase='starting',last_startup_error=str(error))
            self.save(state);return state
        state=self.state();state.update(phase='awaiting_handoff',health=health,verified_epoch=int(time.time()))
        self.save(state);return state

    def accept(self,proof):
        state=self.verify()
        if state['phase']!='awaiting_handoff':raise ValueError('pairing/structural readiness pending')
        if not proof or set(proof)!={'endpoints','client'}:raise ValueError('dual-stack/client proof required')
        if set(proof['endpoints'])!=set(self.spec['endpoints']):raise ValueError('both endpoints required')
        for row in proof['endpoints'].values():
            if (row['phase']!='awaiting_handoff' or row['new_boot_id']!=state['new_boot_id']
                    or row['health']['pair']!=state['health']['pair']):raise ValueError('post-boot endpoint continuity')
        client=proof['client']
        if (client.get('spec_sha256')!=base.sha(base.encoded(self.spec)) or client.get('target')!=self.spec['hostname']
                or client.get('checks')!={'ipv4':True,'ipv6':True,'queries_denied':True}
                or not state['reboot_submission_epoch']<=client['epoch']<=time.time()
                or time.time()-client['epoch']>=120):raise ValueError('fresh structural client proof required')
        state.update(phase='monitoring',handoff_epoch=int(time.time()))
        self.save(state);return state

    def recover(self):
        state=self.state()
        if state['phase']=='bootstrap_recovered':return state
        if socket.gethostname().split('.')[0]!=self.spec['hostname']:raise ValueError('recovery target mismatch')
        self.file_guard();self.drift()
        for name,old in state['before']['boot_files'].items():
            row=self.snapshot(name)
            if any(row[k]!=old[k] for k in ('sha256','uid','gid','mode')):raise ValueError('recovery boot-file drift')
        for name in ('timeservice.service','systemd-timesyncd.service'):
            row=self.unit(name)
            if row['UnitFileState'] not in ('enabled','disabled') or row['DropInPaths']:
                raise ValueError('recovery enablement/override drift')
        diagnostics={'boot_id':self.boot()}
        try:
            diagnostics['journal']=self.run(['/usr/bin/journalctl','--quiet','--no-pager','--output=json',
                '--lines=200','--boot='+self.boot().replace('-',''),'--unit=timeservice.service'])
            diagnostics['startup_gate']=self.helper.file_record('/run/ntpsec-startup/gate.json',content=True)
        except Exception as error:diagnostics['capture_error']=str(error)
        self.replace(self.root/'recovery-diagnostics.json',base.encoded(diagnostics),0,0,0o600)
        state.update(phase='recovering',recovery_boot_id=self.boot());self.save(state)
        self.system('stop','timeservice.service');self.stopped()
        self.system('disable','timeservice.service')
        if self.unit('timeservice.service')['ActiveState']=='failed':
            if self.unit('timeservice.service')['MainPID']!='0':raise ValueError('failed service retains PID')
            self.system('reset-failed','timeservice.service')
        self.system('enable','systemd-timesyncd.service');self.system('start','systemd-timesyncd.service')
        if (self.unit('timeservice.service')['UnitFileState']!='disabled'
                or self.unit('systemd-timesyncd.service')['UnitFileState']!='enabled'
                or self.unit('systemd-timesyncd.service')['ActiveState']!='active'):
            raise ValueError('bootstrap recovery not confirmed')
        state.update(phase='bootstrap_recovered',retained_drift=self.drift(),ntp_serving=False,bootstrap_sync_accepted=False)
        self.save(state);return state

    def invoke(self,mode,proof=None):
        if self.spec.get('purpose')=='production-boot-recovery' and mode not in ('recover','readback'):
            raise ValueError('recovery-only operation forbids activation/reboot')
        if mode=='apply':return self.apply()
        if mode=='reboot':return self.reboot()
        if mode=='verify':
            try:return self.verify()
            except (ValueError,OSError,KeyError,TypeError) as error:
                state=self.state()
                if self.acquisition_wait() and state.get('new_boot_id')==self.boot():
                    state.update(phase='startup_failed',startup_error=str(error));self.save(state)
                raise
        if mode=='accept':return self.accept(proof)
        if mode=='recover':return self.recover()
        if mode=='readback':return self.state()
        if mode=='observe':
            state=self.state()
            if state['phase']!='monitoring':raise ValueError('monitoring phase required')
            health=self.health()
            if health['pair']!=state['health']['pair']:raise ValueError('post-boot invocation changed')
            return {'phase':'monitoring','new_boot_id':state['new_boot_id'],'health':health,'production_accepted':False}
        raise ValueError('closed boot worker mode required')

    def initialize_recovery(self):
        source=json.loads(self.read(self.root/'recovery-source.json'))
        old=Path(source['stage'])
        if (self.boot()!=self.baseline['boot_id']
                or base.sha(self.read(old/'spec.json'))!=source['spec_sha256']
                or base.sha(self.read(old/'state.json'))!=source['state_sha256']):
            raise ValueError('failed-stage continuity changed; no recovery mutation')
        state=json.loads(self.read(self.root/'recovery-state.json'))
        if base.sha(base.encoded(state))!=source['state_sha256']:raise ValueError('recovery state binding')
        self.file_guard();self.drift();self.save(state)


def worker(root,mode,expected,proof=None):
    root=Path(root)
    if os.geteuid()!=0:raise ValueError('root worker required')
    tx=Boot(root);spec=tx.spec
    if (base.sha(base.encoded(spec))!=expected or str(root)!=spec['stage']
            or socket.gethostname().split('.')[0]!=spec['hostname']):raise ValueError('sealed target/specification drift')
    for name,digest in spec['members'].items():
        if base.sha(tx.read(root/name))!=digest:raise ValueError('sealed member drift')
    # Recovery/readback remain available after expiry, including from the console.
    if mode not in ('recover','readback') and not (spec.get('acquisition_wait') and mode in ('verify','accept')) and not spec['prepared_epoch']-300<=time.time()<spec['expires_epoch']:
        raise ValueError('execution window expired; readback/recovery remain available')
    tx.helper=load(root/'inspection.py')
    fd=os.open(root/'.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'rb') as stream:
        info=os.fstat(stream.fileno())
        if info.st_uid or info.st_nlink!=1 or not stat.S_ISREG(info.st_mode):raise ValueError('unsafe lock')
        fcntl.flock(stream,fcntl.LOCK_EX)
        try:
            if spec['purpose']=='production-boot-recovery' and mode=='recover' and not (root/'state.json').exists():
                tx.initialize_recovery()
            return tx.invoke(mode,proof)
        except BaseException as error:
            tx.replace(root/'worker-error.json',base.encoded({'mode':mode,'error':str(error),'epoch':int(time.time())}),0,0,0o600)
            raise


if __name__=='__main__':
    if len(sys.argv)!=4 or sys.argv[1]!='worker':raise SystemExit('worker MODE SPEC_SHA256 required')
    print(json.dumps(worker(Path(__file__).resolve().parent,sys.argv[2],sys.argv[3]),sort_keys=True))
