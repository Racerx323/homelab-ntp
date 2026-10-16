#!/usr/bin/python3
"""One all-source restart with drift-preserving bootstrap-only recovery."""
import base64
import fcntl
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import pwd
import re
import signal
import socket
import stat
import sys
import time

CHANGES = {'/etc/ntpsec-timeservice.json': 'timeservice.json',
           '/etc/systemd/system/timeservice.service': 'timeservice.service',
           '/etc/ntp.conf': 'ntp.conf'}
RUNTIME = {'/usr/local/libexec/timeservice.py':'timeservice.py',
           '/usr/local/libexec/gpsd-pairing.py':'gpsd-pairing.py'}
DRIFT = '/var/lib/ntpsec/drift/ntp.drift'
STATS = Path('/var/log/ntpstats')


def encoded(value): return (json.dumps(value, sort_keys=True)+'\n').encode()
def sha(raw): return hashlib.sha256(raw).hexdigest()


def load(path):
    spec = importlib.util.spec_from_file_location(path.stem.replace('-', '_'), path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def properties(raw):
    return dict(line.split('=', 1) for line in raw.splitlines() if '=' in line)


def process_identity(pid, binary, parent, root=Path('/proc')):
    if type(pid) is not int or pid <= 1:
        raise ValueError('positive daemon PID required')
    path = root/str(pid)
    before = (path/'stat').read_text().rsplit(')', 1)[1].split()[19]
    if os.readlink(path/'exe') != binary:
        raise ValueError('daemon executable identity mismatch')
    fields = dict(line.split(':', 1) for line in (path/'status').read_text().splitlines() if ':' in line)
    if int(fields['PPid']) != parent:
        raise ValueError('daemon supervisor mismatch')
    ids = {k: [int(v) for v in fields[k].split()] for k in ('Uid', 'Gid', 'Groups')}
    if len(ids['Uid']) != 4 or len(ids['Gid']) != 4:
        raise ValueError('complete kernel credentials required')
    after = (path/'stat').read_text().rsplit(')', 1)[1].split()[19]
    if before != after:
        raise ValueError('PID reused during identity capture')
    try: account = pwd.getpwuid(ids['Uid'][1]).pw_name
    except KeyError: account = None
    argv = (path/'cmdline').read_bytes().decode().rstrip('\0').split('\0')
    return {'pid': pid, 'parent': parent, 'exe': binary, 'start_ticks': before,
            'uid': ids['Uid'], 'gid': ids['Gid'], 'groups': ids['Groups'], 'account': account,
            'argv': argv}


def structural(measurement, names):
    peers = measurement['peers']
    if len(peers) != 5:
        return False
    actual = [p['variables'].get('srchost') for p in peers]
    return sorted(actual, key=str) == sorted(['SHM(0)', 'SHM(2)', *names])


def drift_seed(raw, expected, started, finished):
    """Match the first new system frequency event, never a later corrective event."""
    for line in raw.splitlines():
        fields=line.split()
        if len(fields)<6 or fields[5]!='freq_set':continue
        if (len(fields)!=9 or fields[2]!='0.0.0.0' or fields[4]!='02'
                or fields[6] not in ('kernel','ntpd') or fields[8]!='PPM'):
            return False
        try:
            seconds=float(fields[1]);epoch=(int(fields[0])-40587)*86400+seconds
            value=float(fields[7])
        except ValueError:return False
        return (0<=seconds<86400 and started<=epoch<=finished
                and math.isclose(value,expected,rel_tol=0,abs_tol=0.000001))
    return False


def protocol_files():
    """Capture bounded regular daily records; the filegen convenience link is ignored."""
    if not STATS.is_dir() or any(path.is_symlink() for path in (STATS,*STATS.parents)):
        raise ValueError('regular protocol directory required')
    result={}
    for path in sorted(STATS.glob('protostats.*')):
        if not re.fullmatch(r'protostats\.[0-9]{8}',path.name):continue
        if len(result)>=512:raise ValueError('protocol file count bound')
        for parent in path.parents:
            if parent.is_symlink():raise ValueError('protocol directory symlink')
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        with os.fdopen(fd,'rb') as stream:
            info=os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode)
                    or info.st_uid not in (0,999) or info.st_gid not in (0,985)
                    or info.st_mode&0o022 or info.st_size>4*1024**2):
                raise ValueError('unsafe protocol statistics file')
            raw=stream.read(info.st_size)
            after=os.fstat(stream.fileno())
            if len(raw)!=info.st_size or after.st_size<info.st_size:
                raise ValueError('protocol file truncated during capture')
        result[path.name]={'inode':info.st_ino,'device':info.st_dev,
                           'size':len(raw),'sha256':sha(raw),'raw':raw}
    return result


class Transition:
    def __init__(self, root):
        self.root = Path(root)
        self.spec = json.loads(self.read(self.root/'spec.json'))
        self.baseline = json.loads(self.read(self.root/'baseline.json'))
        self.helper = None

    @property
    def changes(self):
        return {**CHANGES, **(RUNTIME if self.spec.get('install_acquisition') else {})}

    def acquisition_wait(self):
        return self.spec.get('acquisition_wait') is True

    def acquisition(self, expected_boot=None, enabled='disabled'):
        """Accept only fresh progress from this boot and the current daemon invocation."""
        if self.boot() != (expected_boot or self.baseline['boot_id']):
            raise ValueError('acquisition boot changed')
        unit=self.unit('timeservice.service')
        if (unit['ActiveState']!='active' or unit['NRestarts']!='0' or unit['DropInPaths']
                or unit['UnitFileState']!=enabled or int(unit['MainPID'])<=0
                or self.unit('systemd-timesyncd.service')['ActiveState']!='inactive'):
            raise ValueError('acquisition service fault/restart/conflict')
        self.installed_files()
        gate=json.loads(self.read('/run/ntpsec-startup/gate.json'))
        now=time.monotonic()
        if (gate['boot_id']!=self.boot() or gate['supervisor_pid']!=int(unit['MainPID'])
                or not 0<=gate['started_monotonic']<=gate['updated_monotonic']<=now):
            raise ValueError('startup gate invocation mismatch')
        if gate['state']=='failed':raise ValueError('startup gate failed: '+gate.get('error','unknown'))
        if gate['state'] not in ('acquiring','passed'):raise ValueError('unknown startup gate state')
        gpsd=process_identity(gate['gpsd_pid'],'/usr/local/sbin/gpsd',int(unit['MainPID']))
        recipe=json.loads(self.read(self.root/'timeservice.json'))
        if (gpsd['start_ticks']!=gate['gpsd_start_ticks'] or gpsd['argv']!=recipe['gpsd'] or len(set(gpsd['uid']))!=1 or gpsd['uid'][0]==0):
            raise ValueError('acquisition GPSD identity changed')
        state=self.state()
        identity={'supervisor_pid':gate['supervisor_pid'],'gpsd':gpsd,'started_monotonic':gate['started_monotonic']}
        if state.get('acquisition_identity',identity)!=identity:raise ValueError('acquisition invocation changed')
        state['acquisition_identity']=identity
        state['startup_gate']=gate
        self.save(state)
        if gate['state']=='acquiring':
            if now-gate['updated_monotonic']>75:raise ValueError('stale acquisition progress')
            result=self.helper.bounded(['/usr/bin/ps','-C','ntpd','-o','pid='])
            if result.get('returncode')!=1 or result.get('stdout','').strip() or result.get('error'):
                raise ValueError('ntpd present before pairing acceptance')
            if state.get('pairing_passed_monotonic') is not None:
                raise ValueError('pairing state regressed')
            return gate
        if gate['pairing'].get('observed') is not True:raise ValueError('pairing acceptance missing')
        return None

    def advance(self):
        """One bounded check; never restart service or hold a lock during acquisition."""
        state=self.state()
        if state['phase'] not in ('starting','acquiring','awaiting_handoff'):
            raise ValueError('pending startup required')
        try:
            pending=self.acquisition()
        except FileNotFoundError:
            if state['phase']!='starting' or time.monotonic()>=state['structural_deadline']:
                raise ValueError('startup gate missing')
            return state
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
            if self.spec.get('action')=='restart':
                for name,row in health['pair'].items():
                    old=state['before']['health']['pair'][name]
                    if (row['pid'],row['start_ticks'])==(old['pid'],old['start_ticks']):
                        raise ValueError('new daemon invocation required after restart')
            self.startup_seed(health)
        except (ValueError,OSError,KeyError) as error:
            state=self.state();state.update(phase='starting',last_startup_error=str(error));self.save(state)
            if time.monotonic()>=state['structural_deadline']:raise
            return state
        state=self.state();state.update(phase='awaiting_handoff',health=health)
        self.save(state);return state

    def resume(self):
        state=self.state()
        if state['phase'] in ('monitoring','bootstrap_recovered','unchanged'):return state
        if state['phase'] not in ('starting','acquiring','awaiting_handoff'):
            raise ValueError('pending startup required')
        try:return self.advance()
        except BaseException as error:
            state=self.state();state['startup_error']=str(error);self.save(state)
            self.recover();raise

    def read(self, path):
        path = Path(path)
        for parent in path.parents:
            info = parent.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
                raise ValueError('unsafe path ancestry: '+str(parent))
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 16*1024**2
                or info.st_uid != 0 or info.st_mode & 0o022):
            raise ValueError('bounded regular file required')
        with path.open('rb') as stream: return stream.read(16*1024**2+1)

    def replace(self, path, raw, uid, gid, mode):
        path = Path(path)
        temporary = path.with_name('.'+path.name+'.'+self.spec['operation_id'])
        if temporary.exists():
            if path.parent!=self.root:raise ValueError('unresolved atomic-write temporary')
            self.read(temporary)  # Validate an interrupted private record before discarding it.
            temporary.unlink()
        fd = os.open(temporary, os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw); os.fchown(stream.fileno(), uid, gid); os.fchmod(stream.fileno(), mode)
            stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
        fd = os.open(path.parent, os.O_RDONLY|os.O_DIRECTORY)
        try: os.fsync(fd)
        finally: os.close(fd)

    def save(self, state):
        self.replace(self.root/'state.json', encoded(state), 0, 0, 0o600)

    def state(self): return json.loads(self.read(self.root/'state.json'))

    def run(self, argv, timeout=15):
        result = self.helper.bounded(argv, timeout=timeout)
        # Retain every command without modifying prior operation evidence.
        path = self.root/'commands.jsonl'
        fd = os.open(path, os.O_CREAT|os.O_APPEND|os.O_WRONLY|os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'ab') as out:
            info = os.fstat(out.fileno())
            if info.st_size > 8*1024**2 or info.st_uid or info.st_nlink != 1:
                raise ValueError('command journal boundary')
            out.write(encoded(result)); out.flush(); os.fsync(out.fileno())
        if result.get('returncode') != 0 or result.get('error'):
            raise ValueError('command failed: '+repr(argv))
        return result['stdout']

    def system(self, *args): return self.run(['/usr/bin/systemctl', *args])

    def unit(self, name):
        props = 'Id,LoadState,ActiveState,SubState,UnitFileState,DropInPaths'
        if name.endswith('.service'): props += ',MainPID,NRestarts'
        return properties(self.system('show', name, '--property='+props))

    def snapshot(self, name):
        row = self.helper.file_record(name, content=True)
        if 'error' in row or row.get('missing') or row.get('changed_during_read'):
            raise ValueError('stable file snapshot required: '+name)
        return row

    def drift(self):
        row = self.snapshot(DRIFT)
        if (row['uid'], row['gid'], row['mode']) != (999, 985, 0o640):
            raise ValueError('learned drift owner/mode changed')
        value=float(base64.b64decode(row['base64']))
        if not math.isfinite(value) or abs(value)>500:
            raise ValueError('finite learned drift required')
        return row

    def boot(self): return Path('/proc/sys/kernel/random/boot_id').read_text().strip()

    def pair(self, main):
        rows = self.run(['/usr/bin/ps', '-C', 'gpsd,ntpd', '-o', 'pid=,comm=']).splitlines()
        result = {}
        for line in rows:
            pid, name = line.split()
            if name not in ('gpsd', 'ntpd') or name in result:
                raise ValueError('exactly one GPSD and ntpd required')
            result[name] = process_identity(int(pid), '/usr/local/sbin/'+name, main)
        if set(result) != {'gpsd', 'ntpd'}:
            raise ValueError('complete daemon pair required')
        self.replace(self.root/'latest-process-identity.json',encoded(result),0,0,0o600)
        if result['ntpd']['uid'] != [999]*4 or result['ntpd']['gid'] != [985]*4:
            raise ValueError('ntpd credentials changed')
        # Discover GPSD from its PID; do not assume an account named gpsd exists.
        if len(set(result['gpsd']['uid'])) != 1 or result['gpsd']['uid'][1] == 0:
            raise ValueError('GPSD must have dropped root')
        return result

    def shm(self):
        lines = Path('/proc/sysvipc/shm').read_text().splitlines()
        rows = [dict(zip(lines[0].split(), line.split())) for line in lines[1:]]
        found = {key: [r for r in rows if int(r['key']) == key] for key in (0x4e545030, 0x4e545032)}
        if any(len(values) != 1 for values in found.values()):
            raise ValueError('one NMEA and one PPS segment required')
        result = {str(key): values[0] for key, values in found.items()}
        self.replace(self.root/'latest-shm.json',encoded(result),0,0,0o600)
        for row in result.values():
            if any(int(row[k]) != value for k, value in [('size',96),('uid',0),('cuid',0),('cgid',0)]):
                raise ValueError('SHM identity changed')
            if int(row['nattch']) < 2:
                raise ValueError('both SHM consumers must be attached')
        if (result[str(0x4e545030)]['perms'], result[str(0x4e545030)]['gid']) not in (('660','985'),('600','0')):
            raise ValueError('retained NMEA grant changed')
        if (result[str(0x4e545032)]['perms'], result[str(0x4e545032)]['gid']) != ('666','0'):
            raise ValueError('PPS segment permissions changed')
        return result

    def measure(self):
        return json.loads(self.run(['/usr/bin/python3','-I','-B',str(self.root/'measure.py')], 25))

    def preflight(self):
        if socket.gethostname().split('.')[0] != self.spec['hostname'] or self.boot() != self.baseline['boot_id']:
            raise ValueError('target/boot continuity changed')
        if time.time() >= self.spec['start_before_epoch']:
            raise ValueError('installation window expired')
        for name, expected in self.baseline['files'].items():
            actual = self.snapshot(name)
            if any(actual[k] != expected[k] for k in ('sha256','uid','gid','mode')):
                raise ValueError('baseline file drift: '+name)
        for name, expected in self.spec['binaries'].items():
            if sha(self.read(name)) != expected['sha256'] or stat.S_IMODE(Path(name).stat().st_mode) != expected['mode']:
                raise ValueError('accepted native binary mismatch')
        unit = self.unit('timeservice.service')
        restarting=self.spec.get('action')=='restart'
        if restarting:
            if (unit['ActiveState'],unit['SubState'],unit['UnitFileState'],unit['DropInPaths'],unit['NRestarts'])!=('active','running','disabled','','0'):
                raise ValueError('accepted running service required')
            if int(unit['MainPID'])!=self.baseline['supervisor_pid']:
                raise ValueError('accepted supervisor changed')
        elif (unit['ActiveState'],unit['SubState'],unit['UnitFileState'],unit['DropInPaths'],unit['MainPID']) != ('inactive','dead','disabled','','0'):
            raise ValueError('recovered stopped service required')
        bootstrap = self.unit('systemd-timesyncd.service')
        if (bootstrap['LoadState'],bootstrap['ActiveState'],bootstrap['UnitFileState'],bootstrap['DropInPaths']) != ('loaded','inactive' if restarting else 'active','enabled',''):
            raise ValueError('bootstrap recovery prerequisite changed')
        for name in self.spec['old_units']:
            u = self.unit(name)
            if u['ActiveState'] not in ('inactive','failed'):
                raise ValueError('old operation worker still active')
        before = {'unit':unit,'drift':self.drift(), 'files':{p:self.snapshot(p) for p in self.changes}}
        if restarting:
            before['health']=self.health(baseline_only=True) if self.spec.get('install_acquisition') else self.health()
            if before['health']['pair']!=self.baseline['running_pair']:
                raise ValueError('accepted daemon identity changed')
        else:self.stopped()
        if not restarting and before['drift']['sha256']!=self.baseline['recovered_drift_sha256']:
            raise ValueError('recovered drift changed')
        for name in self.changes:
            temporary=Path(name).with_name('.'+Path(name).name+'.'+self.spec['operation_id'])
            if os.path.lexists(temporary):raise ValueError('replacement temporary already exists')
        self.run(['/usr/bin/systemd-analyze','verify',str(self.root/'timeservice.service')])
        return before

    def installed_files(self, baseline_only=False):
        for name, expected in self.baseline['files'].items():
            actual=self.snapshot(name)
            digest=sha(self.read(self.root/self.changes[name])) if name in self.changes and not baseline_only else expected['sha256']
            if actual['sha256']!=digest or any(actual[k]!=expected[k] for k in ('uid','gid','mode')):
                raise ValueError('installed input drift')

    def health(self, expected_boot=None, enabled='disabled', baseline_only=False):
        if self.boot()!=(expected_boot or self.baseline['boot_id']):raise ValueError('candidate boot changed')
        if self.unit('systemd-timesyncd.service')['ActiveState']!='inactive':
            raise ValueError('conflicting bootstrap time writer')
        unit = self.unit('timeservice.service')
        if (unit['ActiveState'] != 'active' or unit['NRestarts'] != '0' or unit['DropInPaths']
                or unit['UnitFileState']!=enabled):
            raise ValueError('candidate service fault/restart/override')
        pair = self.pair(int(unit['MainPID']))
        if pair['ntpd']['argv'] != ['/usr/local/sbin/ntpd','-n','-m','-c','/etc/ntp.conf','-u','ntp:ntp']:
            raise ValueError('ordinary ntpd launch required')
        self.installed_files(baseline_only)
        self.drift()
        measure = self.measure()
        if not structural(measure,self.spec['nts_servers']):
            raise ValueError('all five source associations required')
        return {'unit':unit,'pair':pair,'shm':self.shm(),'measurement':measure,'epoch':int(time.time())}

    def stopped(self):
        if self.unit('timeservice.service')['ActiveState'] not in ('inactive','failed'):
            raise ValueError('candidate stop not confirmed')
        result=self.helper.bounded(['/usr/bin/ps','-C','ntpd,gpsd','-o','pid='])
        if result.get('returncode')!=1 or result.get('stdout','').strip() or result.get('error'):
            raise ValueError('time-service child remains; bootstrap start forbidden')

    def startup_seed(self,health):
        state=self.state();pid=health['pair']['ntpd']['pid']
        raw=self.run(['/usr/bin/journalctl','--quiet','--no-pager','--output=json','--lines=200',
                      '--boot='+self.boot().replace('-',''),'_PID='+str(pid)],15)
        rows=[json.loads(line) for line in raw.splitlines() if line.strip()]
        state['startup_journal']=rows
        state['startup_health']=health
        self.save(state)
        value=float(base64.b64decode(state['drift_after_stop']['base64']))
        captured=protocol_files();parts=[];evidence={}
        for name,old in state['protocol_cursor'].items():
            if name not in captured:raise ValueError('protocol baseline file disappeared')
            new=captured[name]
            if ((new['inode'],new['device'])!=(old['inode'],old['device'])
                    or new['size']<old['size'] or sha(new['raw'][:old['size']])!=old['sha256']):
                raise ValueError('protocol baseline identity/content changed')
        for name,row in captured.items():
            raw=row['raw'][state['protocol_cursor'].get(name,{}).get('size',0):]
            if raw:
                evidence[name]={'base64':base64.b64encode(raw).decode(),
                                **{k:v for k,v in row.items() if k!='raw'}}
                parts.append(raw.decode('ascii'))
        state['startup_protocol']=evidence
        state['drift_seed_observed']=drift_seed('\n'.join(parts),value,state['startup_epoch'],time.time())
        self.save(state)
        if not state['drift_seed_observed']:raise ValueError('saved drift protocol startup seed not observed')

    def apply(self):
        if (self.root/'state.json').exists(): raise ValueError('apply already consumed')
        before = self.preflight()
        state = {'phase':'prepared','before':before,'boot_id':self.boot(),
                 'deadline_monotonic':time.monotonic()+600,'production_accepted':False}
        self.save(state)
        self.run(['/usr/bin/systemd-run','--quiet','--unit='+self.spec['watchdog'],
                  '--on-active=600s',*(['--on-unit-inactive=30s'] if self.acquisition_wait() else []),
                  '--timer-property=AccuracySec=1s','--property=RuntimeMaxSec=180',
                  '/usr/bin/python3','-I','-B',str(self.root/'production-transition.py'),'worker','watchdog',
                  sha(encoded(self.spec))])
        if self.unit(self.spec['watchdog']+'.timer')['ActiveState'] != 'active':
            raise ValueError('independent watchdog not armed')
        state['phase']='applying'; self.save(state)
        try:
            restarting=self.spec.get('action')=='restart'
            unchanged=self.spec.get('action') in ('restart','start') and not self.spec.get('install_acquisition')
            self.system('stop','timeservice.service' if restarting else 'systemd-timesyncd.service')
            if self.unit('systemd-timesyncd.service')['ActiveState']!='inactive':
                raise ValueError('bootstrap time writer did not stop')
            self.stopped()
            state['drift_after_stop']=self.drift(); self.save(state)
            for name, member in self.changes.items():
                old=before['files'][name]
                current=self.snapshot(name)
                if any(current[k]!=old[k] for k in ('sha256','uid','gid','mode')):
                    raise ValueError('destination changed after preflight')
                if not unchanged:self.replace(name,self.read(self.root/member),old['uid'],old['gid'],old['mode'])
            if not unchanged:self.system('daemon-reload')
            state['protocol_cursor']={name:{k:v for k,v in row.items() if k!='raw'}
                                      for name,row in protocol_files().items()}
            state['startup_epoch']=time.time();self.save(state)
            self.system('start','timeservice.service')
            if self.acquisition_wait():
                state=self.state();state.update(phase='starting',structural_deadline=time.monotonic()+120)
                self.save(state);return self.advance()
            deadline=time.monotonic()+120
            while True:
                try:
                    health=self.health()
                    if restarting:
                        for name,row in health['pair'].items():
                            old=before['health']['pair'][name]
                            if (row['pid'],row['start_ticks'])==(old['pid'],old['start_ticks']):
                                raise ValueError('new daemon invocation required after restart')
                    self.startup_seed(health);break
                except (ValueError,OSError,KeyError) as error:
                    state=self.state();state['last_startup_error']=str(error); self.save(state)
                    if time.monotonic() >= deadline: raise
                    time.sleep(5)
            state=self.state();state.update(phase='awaiting_handoff',health=health)
            self.save(state); return state
        except BaseException as error:
            state=self.state();state['apply_error']=str(error);self.save(state)
            self.recover(); raise

    def accept(self, proof):
        state=self.state()
        if state['phase']!='awaiting_handoff' or time.monotonic()>state['deadline_monotonic']-60:
            raise ValueError('fresh awaiting-handoff state required')
        if state.get('drift_seed_observed') is not True:raise ValueError('saved drift seed proof required')
        if not proof or set(proof) != {'endpoints','client'}:
            raise ValueError('dual-stack and client proofs required')
        for address in self.spec['endpoints']:
            row=proof['endpoints'][address]
            if row['phase']!='awaiting_handoff' or row['health']['pair'] != state['health']['pair']:
                raise ValueError('same candidate over both endpoints required')
        client=proof['client']
        if (client.get('spec_sha256') != sha(encoded(self.spec)) or client.get('target') != self.spec['hostname']
                or client.get('checks') != {'ipv4':True,'ipv6':True,'queries_denied':True}
                or not 0<=time.time()-client['epoch']<120):
            raise ValueError('fresh structural client proof required')
        health=self.health()
        if health['pair']!=state['health']['pair']: raise ValueError('candidate process continuity changed')
        state.update(phase='monitoring',health=health,handoff_epoch=int(time.time()))
        self.save(state)
        try:
            self.system('stop',self.spec['watchdog']+'.timer')
            if self.unit(self.spec['watchdog']+'.timer')['ActiveState'] not in ('inactive','failed'):
                raise ValueError('watchdog cancellation unconfirmed')
        except BaseException:
            self.recover(); raise
        return state

    def recover(self):
        state=self.state()
        if state['phase']=='bootstrap_recovered':return state
        if state['phase']=='prepared':
            self.system('stop',self.spec['watchdog']+'.timer')
            state['phase']='unchanged';self.save(state);return state
        if self.boot()!=state['boot_id']:raise ValueError('recovery boot changed; operator review required')
        # Inspect before stopping. Never overwrite unexpected operator changes.
        for name,member in self.changes.items():
            actual=self.snapshot(name);old=state['before']['files'][name]
            if (actual['sha256'] not in (old['sha256'],sha(self.read(self.root/member)))
                    or any(actual[k]!=old[k] for k in ('uid','gid','mode'))):
                raise ValueError('recovery file drift')
            temporary=Path(name).with_name('.'+Path(name).name+'.'+self.spec['operation_id'])
            if temporary.exists():
                partial=self.read(temporary)
                if not any(raw.startswith(partial) for raw in
                           (base64.b64decode(old['base64']),self.read(self.root/member))):
                    raise ValueError('unrecognized interrupted replacement')
                temporary.unlink()
        self.drift()
        state['phase']='recovering';self.save(state)
        self.system('stop','timeservice.service')
        self.stopped()
        if self.unit('timeservice.service')['ActiveState']=='failed':
            if self.unit('timeservice.service')['MainPID']!='0':raise ValueError('failed service still has PID')
            self.system('reset-failed','timeservice.service')
        state['retained_drift']=self.drift(); self.save(state)
        if self.spec.get('action') not in ('restart','start') or self.spec.get('install_acquisition'):
            for name in self.changes:
                old=state['before']['files'][name]
                self.replace(name,base64.b64decode(old['base64']),old['uid'],old['gid'],old['mode'])
            self.system('daemon-reload')
        self.system('start','systemd-timesyncd.service')
        if self.unit('systemd-timesyncd.service')['ActiveState']!='active':
            raise ValueError('bootstrap service did not start')
        state.update(phase='bootstrap_recovered',ntp_serving=False,bootstrap_sync_accepted=False)
        self.save(state)
        self.system('stop',self.spec['watchdog']+'.timer')
        return state

    def invoke(self, mode, proof=None):
        if mode=='apply': return self.apply()
        if mode=='resume': return self.resume()
        if mode=='accept': return self.accept(proof)
        if mode=='recover': return self.recover()
        if mode=='watchdog':
            state=self.state()
            if state['phase'] in ('monitoring','bootstrap_recovered','unchanged'):return state
            if self.acquisition_wait() and state['phase'] in ('starting','acquiring','awaiting_handoff'):
                return self.resume()
            return self.recover()
        if mode=='readback':return self.state()
        if mode=='observe':
            state=self.state()
            if state['phase']!='monitoring':raise ValueError('monitoring state required')
            return {'phase':'monitoring','health':self.health(),'production_accepted':False}
        raise ValueError('closed worker mode required')


def worker(root, mode, expected, proof=None):
    root=Path(root)
    if os.geteuid()!=0:raise ValueError('root worker required')
    tx=Transition(root)
    spec=tx.spec
    if sha(encoded(spec))!=expected:raise ValueError('approved specification drift')
    if str(root)!=spec['stage']:raise ValueError('stage path mismatch')
    for name,digest in spec['members'].items():
        if sha(tx.read(root/name))!=digest:raise ValueError('sealed member drift')
    tx.helper=load(root/'inspection.py')
    fd=os.open(root/'.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'rb') as stream:
        info=os.fstat(stream.fileno())
        if info.st_uid or info.st_nlink!=1 or not stat.S_ISREG(info.st_mode):raise ValueError('unsafe lock')
        fcntl.flock(stream,fcntl.LOCK_EX)
        try:
            return tx.invoke(mode,proof)
        except BaseException as error:
            tx.replace(root/'worker-error.json',encoded({'mode':mode,'error':str(error),
                       'epoch':int(time.time())}),0,0,0o600)
            raise


if __name__=='__main__':
    if len(sys.argv)!=4 or sys.argv[1]!='worker':raise SystemExit('worker MODE SPEC_SHA256 required')
    print(json.dumps(worker(Path(__file__).resolve().parent,sys.argv[2],sys.argv[3]),sort_keys=True))
