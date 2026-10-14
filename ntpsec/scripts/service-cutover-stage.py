#!/usr/bin/python3
"""One protected time-service cutover with independent timed recovery."""
import base64
import fcntl
import hashlib
import importlib.util
import json
import os
import re
from pathlib import Path
import socket
import stat
import subprocess
import sys
import time

ENV={'PATH':'/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin','LC_ALL':'C','PYTHONDONTWRITEBYTECODE':'1'}
DESTINATIONS={
 '/usr/local/libexec/timeservice.py':('timeservice.py',0o755),
 '/usr/local/libexec/gpsd-pairing.py':('gpsd-pairing.py',0o644),
 '/usr/local/libexec/pps-startup.py':('pps-startup.py',0o644),
 '/etc/ntp.conf':('ntp.conf',0o644),
 '/etc/ntpsec-timeservice.json':('timeservice.json',0o640),
 '/etc/systemd/system/timeservice.service':('timeservice.service',0o644),
 '/etc/avahi/avahi-daemon.conf':('avahi.conf',0o644),
 '/var/lib/ntpsec/leap-seconds.list':('leap-seconds.list',0o644),
 '/etc/systemd/system/ntpleapfetch.service':('ntpleapfetch.service',0o644),
 '/etc/systemd/system/ntpleapfetch.timer':('ntpleapfetch.timer',0o644)}
DIRECTORIES={'/var/lib/ntpsec':(0,0,0o755),'/var/lib/ntpsec/drift':(999,985,0o750),'/var/log/ntpstats':(999,985,0o750)}


def encoded(value):return (json.dumps(value,sort_keys=True)+'\n').encode()
def sha(raw):return hashlib.sha256(raw).hexdigest()


def load(path):
    spec=importlib.util.spec_from_file_location('cutover_'+path.stem.replace('-','_'),path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def clear_restored_failure(systemctl):
    """Clear only an unloaded, stopped timeservice left failed by startup."""
    def observed():
        raw=systemctl('show','timeservice.service','--no-pager',
                      '--property=Id,LoadState,ActiveState,SubState,MainPID,FragmentPath,DropInPaths')
        rows=[line.split('=',1) for line in raw.splitlines() if '=' in line]
        result=dict(rows)
        if len(rows)!=len(result):raise ValueError('duplicate restored service properties')
        return result
    expected={'Id':'timeservice.service','LoadState':'not-found','ActiveState':'inactive',
              'SubState':'dead','MainPID':'0','FragmentPath':'','DropInPaths':''}
    actual=observed()
    if actual==expected:return False
    if actual!=dict(expected,ActiveState='failed',SubState='failed'):
        raise ValueError('unexpected restored timeservice state')
    systemctl('reset-failed','timeservice.service')
    if observed()!=expected:raise ValueError('timeservice failure reset not confirmed')
    return True


def measurement_checks(value,recipe):
    peers=value['peers'];pps=[p for p in peers if p['variables'].get('srcadr') in ('SHM(2)','127.127.28.2')]
    if len(pps)!=1:raise ValueError('one PPS association required')
    pps=pps[0];v=pps['variables'];system=value['system']
    checks={'leap':int(system.get('leap',3))==0,'stratum':int(system.get('stratum',16))==1,
        'pps_selected':((pps['status']>>8)&7) in (6,7),
        'pps_reachable':int(v.get('reach',0))!=0,
        'offset':abs(float(v.get('offset',1e9)))<=recipe['maximum_pps_offset_ms'],
        'jitter':0<=float(v.get('jitter',1e9))<=recipe['maximum_pps_jitter_ms']}
    nmea=[p for p in peers if p['variables'].get('srcadr') in ('SHM(0)','127.127.28.0')]
    checks['serial_reachable']=len(nmea)==1 and int(nmea[0]['variables'].get('reach',0))!=0
    upstreams=[p for p in peers if p['variables'].get('srchost') in recipe['nts_servers']]
    checks['associations']=len(peers)==5 and {p['variables'].get('srchost') for p in upstreams}==set(recipe['nts_servers'])
    checks['nts']=len(upstreams)==3 and all((p['status']>>8)&0x60==0x60 and int(p['variables'].get('reach',0))!=0
         and int(p['variables'].get('ntscookies',0))>0 for p in upstreams)
    return checks


MINSANE_MESSAGE='SYNC: Found 5 servers, suggest minsane at least 3'


def journal_health(raw,boot_id,apply_monotonic,ntpd_pid,promoted_monotonic=None,control_key=False):
    """Classify bounded startup telemetry, without accepting NTS packet service."""
    allowed=[];unexpected=[];seen=set();counts={'minsane':0,'read':0,'cookies':0}
    key_read_stamp=None
    if control_key:counts.update(key_read=0,key_added=0)
    for line in raw.splitlines():
        row=json.loads(line)
        stamp=int(row['__MONOTONIC_TIMESTAMP'])/1_000_000
        if row['_BOOT_ID']!=boot_id.replace('-',''):
            raise ValueError('journal boot mismatch')
        if stamp<apply_monotonic:continue
        expected={'PRIORITY':'3','_SYSTEMD_UNIT':'timeservice.service',
                  '_EXE':'/usr/local/sbin/ntpd','_COMM':'ntpd','_TRANSPORT':'syslog',
                  'SYSLOG_IDENTIFIER':'ntpd','_PID':str(ntpd_pid)}
        message=row.get('MESSAGE');kind=None
        if isinstance(message,str):
            # Pinned 1.2.5 authreadkeys.c logs successful loading at LOG_ERR.
            if control_key and message=='AUTH: authreadkeys: reading /run/ntpsec-startup/control.key':kind='key_read'
            if control_key and message=='AUTH: authreadkeys: added 1 keys':kind='key_added'
            if message==MINSANE_MESSAGE:kind='minsane'
            read=re.fullmatch(r'NTSc: read ([1-9][0-9]{0,3}) bytes',message)
            cookies=re.fullmatch(r'NTSc: Got ([1-8]) cookies, length ([1-9][0-9]{0,2}), aead=(15|16|17)\.',message)
            # Pinned 1.2.5: nts_client.c buffer; nts.h cookie and AEAD bounds.
            if read and int(read[1])<=2048:kind='read'
            if cookies and int(cookies[2])<=192:kind='cookies'
        digest=sha(encoded(row))
        key_message=kind in ('key_read','key_added')
        origin=apply_monotonic if key_message or promoted_monotonic is None else promoted_monotonic
        if (kind and all(row.get(k)==v for k,v in expected.items())
                and origin<=stamp<=origin+120 and digest not in seen
                and counts[kind]<(1 if key_message or kind=='minsane' else 3)
                and (kind!='key_added' or key_read_stamp is not None and stamp>=key_read_stamp)):
            counts[kind]+=1;allowed.append(row)
            if kind=='key_read':key_read_stamp=stamp
        else:unexpected.append(row)
        seen.add(digest)
    paired=counts['read']==counts['cookies']
    loaded=not control_key or counts['key_read']==counts['key_added']==1
    return {'healthy':not unexpected and paired and loaded,'allowed':allowed,'unexpected':unexpected,
            'control_key_check_passed':loaded,
            'startup_counts':counts,'response_counts_match':paired}


class Transaction:
    def __init__(self,spec,files,code_root=None):
        self.s=spec;self.f=files;self.root=Path(spec['stage'])
        code = self.root if code_root is None else Path(code_root)
        self.a=load(code/'reference.py');self.rf=self.a.unpack(files['reference.tar'])
        self.rs=json.loads(self.rf['spec.json'])
        self.h=load(code/'helper.py') if code_root is not None or spec.get('purpose')=='service-monitor' else self.a.bootstrap(self.rs,self.rf)
        self.alias=dict(self.rs,operation_id=spec['operation_id'],stage=spec['stage'],unit='ntp-acquire-'+spec['operation_id']+'.service')

    def write(self,name,value):
        tmp=self.root/(name+'.new')
        if tmp.exists():self.h.read(tmp);tmp.unlink()
        self.h.create(tmp,encoded(value));os.replace(tmp,self.root/name);self.h.sync(self.root)

    def state(self):return json.loads(self.h.read(self.root/'state.json'))

    def lock(self):
        fd=os.open(self.root/'.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or (info.st_uid,info.st_gid,info.st_nlink,stat.S_IMODE(info.st_mode))!=(0,0,1,0o600):
            os.close(fd);raise ValueError('protected lock required')
        fcntl.flock(fd,fcntl.LOCK_EX);return os.fdopen(fd,'rb')

    def run(self,argv,timeout=15):
        deadline=getattr(self,'command_deadline',None)
        if deadline is not None:
            timeout=min(timeout,deadline-time.monotonic())
            if timeout<=0:raise ValueError('diagnostic observation deadline')
        p=subprocess.run(argv,env=ENV,capture_output=True,timeout=timeout,check=False)
        if len(p.stdout)>2*1024**2 or len(p.stderr)>65536:raise ValueError('command output bound')
        record=encoded({'argv':argv,'status':p.returncode,'stdout':p.stdout.decode(errors='replace'),
                        'stderr':p.stderr.decode(errors='replace')})
        log='recovery-commands.jsonl' if getattr(self,'recovering',False) and (self.s['recipe'].get('diagnostic') or self.s.get('purpose')=='service-monitor') else 'commands.jsonl'
        fd=os.open(self.root/log,os.O_WRONLY|os.O_CREAT|os.O_APPEND|os.O_NOFOLLOW,0o600)
        try:
            info=os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or (info.st_uid,info.st_gid,info.st_nlink,stat.S_IMODE(info.st_mode))!=(0,0,1,0o600) or info.st_size+len(record)>8*1024**2:
                raise ValueError('protected bounded command journal required')
            while record:record=record[os.write(fd,record):]
            os.fsync(fd)
        finally:os.close(fd)
        if p.returncode:raise ValueError('command failed: '+repr(argv))
        return p.stdout.decode()

    def systemctl(self,*args):return self.run(['/usr/bin/systemctl',*args])

    def cancel_timer(self):
        unit=self.s['recovery_unit']+'.timer'
        if self.systemctl('show',unit,'--property=LoadState','--value').strip()!='not-found':self.systemctl('stop',unit)

    def snapshot(self,name):
        path=Path(name)
        try:info=path.lstat()
        except FileNotFoundError:return None
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_mode&0o022:raise ValueError('protected regular destination required: '+name)
        raw=self.h.read(path,limit=2*1024**2)
        return {'sha256':sha(raw),'base64':base64.b64encode(raw).decode(),'uid':info.st_uid,'gid':info.st_gid,'mode':stat.S_IMODE(info.st_mode)}

    def replace(self,name,raw,mode,uid=0,gid=0):
        path=Path(name);self.h.ancestors(path.parent)
        temp=path.with_name('.'+path.name+'.'+self.s['operation_id'])
        fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'wb') as stream:
            stream.write(raw);os.fchown(stream.fileno(),uid,gid);os.fchmod(stream.fileno(),mode);stream.flush();os.fsync(stream.fileno())
        os.replace(temp,path);self.h.sync(path.parent)

    def retained(self):
        root=Path(self.rs['stage']);self.h.ancestors(root)
        for name,digest in self.rs['members'].items():
            if sha(self.h.read(root/name,limit=32*1024**2))!=digest:raise ValueError('executed input drift')
        report=json.loads(self.f['reference-report.json'])
        for name,row in report['evidence'].items():
            if sha(self.h.read(root/name,limit=8388608))!=row['sha256']:raise ValueError('accepted receiver evidence drift')

    def runtime_context(self,create=False):
        return self.a.context(self.h,self.alias,self.rf,create=create)

    def hardware_gate(self,transaction):
        return transaction.hardware_gate()

    def preflight(self):
        self.retained();self.runtime_context(create=True);self.a.idle();self.a.prior_guard(self.h,self.alias,self.rf)
        expected=json.loads(self.f['receiver-runtime.json'])['runtime']
        before={n:self.snapshot(n) for n in DESTINATIONS}
        for name,record in expected['files'].items():
            current=self.snapshot(name)
            if (record is None)!=(current is None) or record and any(current[k]!=record[k] for k in ('sha256','uid','gid','mode')):
                raise ValueError('receiver/runtime file drift: '+name)
        for name in DESTINATIONS:
            if name not in ('/usr/local/libexec/timeservice.py','/etc/avahi/avahi-daemon.conf') and before[name] is not None:
                raise ValueError('unexpected candidate destination collision')
        for name in DIRECTORIES:
            if os.path.lexists(name):raise ValueError('candidate directory collision')
        for name in ('timeservice.service','ntpleapfetch.service','ntpleapfetch.timer'):
            if self.systemctl('show',name,'--property=LoadState','--value').strip()!='not-found':raise ValueError('candidate unit collision')
            if list(Path('/etc/systemd/system').glob(name+'.d/*')):raise ValueError('candidate unit drop-in collision')
            if self.systemctl('show',name,'--property=DropInPaths','--value').strip():raise ValueError('unreviewed drop-ins')
        for name in ('/etc/systemd/system/multi-user.target.wants/timeservice.service',
                     '/etc/systemd/system/timers.target.wants/ntpleapfetch.timer'):
            if os.path.lexists(name):raise ValueError('candidate enablement collision')
        self.write('before.json',{'files':before,'termios':self.run(['/usr/bin/stty','-F','/dev/serial0','-g']).strip(),
                                'serial':self.a.serial_identity()})
        self.write('state.json',{'phase':'staged','probe_count':0,'stable':0,'created_directories':[],
                                'installed':[],'deadline':time.monotonic()+self.s['recipe']['recovery_seconds']})
        if self.s['recipe'].get('diagnostic'):
            load(self.root/'runtime-diagnostic.py').library()
            state=self.state();state['network_before']=self.network_observation()
            self.write('state.json',state)

    def network_observation(self):
        return {name:json.loads(self.run(argv,timeout=5)) for name,argv in (
            ('addresses',['ip','-json','address','show','dev','eth0']),
            ('routes4',['ip','-json','-4','route','show','table','main']),
            ('routes6',['ip','-json','-6','route','show','table','main']))}

    def start_packet_capture(self):
        unit=self.s['apply_unit']+'-packets'
        self.run(['/usr/bin/systemd-run','--quiet','--unit='+unit,
                  '--property=WorkingDirectory='+str(self.root),'--property=RuntimeMaxSec=1640',
                  '--property=TimeoutStopSec=10','--property=LimitFSIZE=1048576','--property=UMask=0077',
                  '/usr/bin/python3','-I','-B',str(self.root/'runtime-diagnostic.py'),'capture'])
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            path=self.root/'packet-ready.json'
            if path.exists():
                ready=json.loads(self.h.read(path))
                pid=int(self.systemctl('show',unit+'.service','--property=MainPID','--value'))
                if ready.get('ready') is True and ready.get('pid')==pid and pid>0:return
                raise ValueError('packet observer identity mismatch')
            time.sleep(.1)
        raise ValueError('packet observer not ready before activation')

    def arm(self):
        self.run(['/usr/bin/systemd-run','--quiet','--unit='+self.s['recovery_unit'],
                  '--on-active='+str(self.s['recipe']['recovery_seconds'])+'s','--timer-property=AccuracySec=1s',
                  '--property=WorkingDirectory='+str(self.root),'--property=RuntimeMaxSec=240','--property=TimeoutStopSec=20','--property=UMask=0077',
                  '/usr/bin/python3','-I','-B',str(self.root/'stage.py'),'worker','recover'])
        if self.systemctl('is-active',self.s['recovery_unit']+'.timer').strip()!='active':raise ValueError('recovery timer not armed')

    def apply(self):
        with self.lock():
            state=self.state()
            if state['phase']!='staged':raise ValueError('one staged apply required')
            state['phase']='applying';state['apply_epoch']=int(time.time());state['apply_monotonic']=time.monotonic();self.write('state.json',state)
            try:
                if self.s['recipe'].get('diagnostic'):
                    state['journal_cursor']=self.journal_cursor();self.write('state.json',state)
                for name,(uid,gid,mode) in DIRECTORIES.items():
                    self.h.ancestors(Path(name).parent)
                    # Claim each mutation before execution so interruption remains recoverable.
                    state['created_directories'].append(name);self.write('state.json',state)
                    Path(name).mkdir(mode=0o700);os.chown(name,uid,gid);os.chmod(name,mode)
                for name,(member,mode) in DESTINATIONS.items():
                    state['installed'].append(name);self.write('state.json',state)
                    self.replace(name,self.f[member],mode)
                self.run(['/usr/bin/systemd-analyze','verify',*[name for name in DESTINATIONS if name.startswith('/etc/systemd/system/')]])
                self.systemctl('daemon-reload');self.systemctl('restart','avahi-daemon.service')
                if self.s['recipe'].get('diagnostic'):self.start_packet_capture()
                self.systemctl('stop','systemd-timesyncd.service')
                self.systemctl('start','timeservice.service')
                deadline=time.monotonic()+55
                while time.monotonic()<deadline:
                    path=Path('/run/ntpsec-startup/gate.json')
                    if path.exists():
                        gate=json.loads(self.h.read(path))
                        pid=int(self.systemctl('show','timeservice.service','--property=MainPID','--value'))
                        if gate['supervisor_pid']==pid:
                            if gate['state']!='passed':raise ValueError('early GPSD/PPS functionality failed')
                            time.sleep(2)
                            argv=['/usr/bin/python3','-I','-B',str(self.root/'measure.py')]
                            if self.s['recipe'].get('diagnostic'):argv.append('--diagnostic')
                            early=json.loads(self.run(argv,timeout=20))
                            if 'leap' not in early['system']:raise ValueError('early ntpd control response missing')
                            state.update(phase='observing',gate=gate,supervisor_pid=pid,early_ntpd=early)
                            if self.s['recipe'].get('diagnostic'):
                                state['diagnostic_samples']=[]
                            self.write('state.json',state)
                            if self.s['recipe'].get('diagnostic'):
                                self.run(['/usr/bin/systemd-run','--quiet','--unit='+self.s['apply_unit']+'-diagnostic',
                                          '--property=WorkingDirectory='+str(self.root),'--property=RuntimeMaxSec=1620',
                                          '--property=TimeoutStopSec=240','--property=UMask=0077','--property=KillMode=control-group',
                                          '--property=ExecStopPost=/usr/bin/python3 -I -B '+str(self.root/'stage.py')+' worker recover',
                                          '/usr/bin/python3','-I','-B',str(self.root/'stage.py'),'worker','diagnose'])
                            return state
                    time.sleep(.25)
                raise ValueError('early functionality unavailable')
            except BaseException as error:
                state=self.state();state.update(phase='apply_held',error=str(error)[:500]);self.write('state.json',state)
                self.recover(locked=True);raise

    def continuity_observation(self, transaction):
        return transaction.baseline['observation']

    def daemon_children(self):
        """Identify daemon children, allowing only the pinned startup journal reader."""
        pid=self.state()['supervisor_pid']; daemons={}; readers=[]
        children=Path('/proc/'+str(pid)+'/task/'+str(pid)+'/children').read_text().split()
        for child in children:
            try:
                executable=os.readlink('/proc/'+child+'/exe')
                status=Path('/proc/'+child+'/status').read_text().splitlines()
                argv=Path('/proc/'+child+'/cmdline').read_bytes().rstrip(b'\0').split(b'\0') if executable=='/usr/bin/journalctl' else []
            except FileNotFoundError:
                continue  # A short-lived reader may exit; missing daemons still fail below.
            ids={line.split(':',1)[0]:[int(v) for v in line.split(':',1)[1].split()] for line in status if line.startswith(('Uid:','Gid:'))}
            if executable=='/usr/bin/journalctl' and self.s['recipe']['timeservice'].get('pps_startup'):
                readers.append((argv,ids));continue
            if executable not in ('/usr/local/sbin/gpsd','/usr/local/sbin/ntpd') or executable in daemons:
                raise ValueError('unexpected or duplicate supervisor child')
            daemons[executable]={'pid':int(child),'ids':ids}
        if set(daemons)!={'/usr/local/sbin/gpsd','/usr/local/sbin/ntpd'} or len(readers)>1:
            raise ValueError('missing daemon or duplicate journal reader')
        expected=[b'/usr/bin/journalctl',b'--quiet',b'--no-pager',b'--output=json',
                  ('--boot='+self.s['boot_id'].replace('-','')).encode(),
                  ('_PID='+str(daemons['/usr/local/sbin/ntpd']['pid'])).encode(),
                  b'_EXE=/usr/local/sbin/ntpd',b'--lines=1000']
        for argv,ids in readers:
            if (argv[:len(expected)]!=expected or len(argv) not in (len(expected),len(expected)+1)
                    or len(argv)>len(expected) and not re.fullmatch(rb'--after-cursor=[A-Za-z0-9;=:_-]{1,1024}',argv[-1])
                    or ids!={'Uid':[0]*4,'Gid':[0]*4}):
                raise ValueError('unapproved startup journal reader')
        return daemons

    def unchanged(self):
        self.retained()
        root=self.root/'runtime-check';m=load(root/'host-configuration-stage.py')
        transaction=m.Transaction(json.loads(self.h.read(root/'spec.json')))
        for name,digest in transaction.spec['hardware_prerequisite']['boot_hashes'].items():
            if sha(self.h.read(Path(name)))!=digest:raise ValueError('boot configuration drift')
        if transaction.accounts()!=transaction.state()['created_account']:raise ValueError('runtime account drift')
        if transaction.snapshot_file(Path('/etc/ld.so.cache'))!=transaction.state()['cache_after']:raise ValueError('loader cache drift')
        observed=transaction.core.i.observation();expected=self.continuity_observation(transaction)
        for name in ('inventory','boot_id','python'):
            if observed[name]!=expected[name]:raise ValueError('package/boot/Python drift')
        children=self.daemon_children()
        if {p['pid'] for p in observed['active_daemons']}!={p['pid'] for p in children.values()} or len(observed['active_daemons'])!=2:
            raise ValueError('competing or missing time daemon')
        native=transaction.core.cm.inspect_install(root/'release.json',transaction.spec['members']['release.json'])
        expected_native=transaction.baseline['installed_state']
        for name,row in native['files'].items():
            if '/'+name not in DESTINATIONS and row!=expected_native['files'][name]:raise ValueError('unrelated native drift')
        for name,record in transaction.baseline['protected_files'].items():
            if name in DESTINATIONS or name in transaction.spec['hardware_prerequisite']['boot_hashes'] or name=='/etc/ld.so.cache':continue
            current=self.snapshot(name)
            if (current is None)!=(record is None) or record and current['sha256']!=record['sha256']:
                raise ValueError('protected configuration drift: '+name)
        for directory,pattern in (('/etc/ld.so.conf.d','*.conf'),('/etc/systemd/system/timeservice.service.d','*.conf')):
            if {str(p) for p in Path(directory).glob(pattern)}!={p for p in transaction.baseline['protected_files'] if Path(p).parent==Path(directory)}:
                raise ValueError('loader/service membership drift')
        original=m.unit_states(transaction.baseline['queries']['time_units']['stdout'])
        remaining={k:v for k,v in original.items() if k not in ('timeservice.service','systemd-timesyncd.service','avahi-daemon.service')}
        actual=m.unit_states(self.systemctl('show','--no-pager','--property=Id,LoadState,ActiveState,SubState,UnitFileState,FragmentPath,DropInPaths,User,Group',*remaining))
        if actual!=remaining:raise ValueError('unrelated service drift')
        for name,record in json.loads(self.f['receiver-runtime.json'])['runtime']['files'].items():
            if name not in DESTINATIONS and self.snapshot(name)!=record:
                # Captured records need not include content; compare metadata and digest.
                current=self.snapshot(name)
                if (current is None)!=(record is None) or record and any(current[k]!=record[k] for k in ('sha256','uid','gid','mode')):
                    raise ValueError('receiver runtime input drift')
        raw=Path('/proc/sysvipc/shm').read_bytes().decode().splitlines();columns=raw[0].split();at=columns.index('nattch')
        normalized=[raw[0]]
        for line in raw[1:]:
            fields=line.split();fields[at]='0';normalized.append(' '.join(fields))
        if self.a.shm_inventory(('\n'.join(normalized)+'\n').encode())!=self.a.shm_inventory(self.rf['prior-shm-after.txt']):
            raise ValueError('SHM ownership/membership drift')
        # Reuse network and hardware checks with only the explicitly changed continuity fields replaced.
        transaction.core.continuity=lambda:None
        transaction.network_checks();self.hardware_gate(transaction)
        for name,(member,mode) in DESTINATIONS.items():
            record=self.snapshot(name)
            if not record or record['sha256']!=sha(self.f[member]) or record['mode']!=mode or record['uid'] or record['gid']:raise ValueError('installed candidate drift')
        for name,(uid,gid,mode) in DIRECTORIES.items():
            info=Path(name).lstat()
            if not stat.S_ISDIR(info.st_mode) or (info.st_uid,info.st_gid,stat.S_IMODE(info.st_mode))!=(uid,gid,mode):raise ValueError('runtime directory drift')

    def measure(self):
        argv=['/usr/bin/python3','-I','-B',str(self.root/'measure.py')]
        if self.s['recipe'].get('diagnostic'):argv.append('--diagnostic')
        raw=self.run(argv,timeout=20)
        value=json.loads(raw);recipe=self.s['recipe']
        checks=measurement_checks(value,recipe)
        checks['bootstrap_stopped']=self.systemctl('show','systemd-timesyncd.service','--property=ActiveState','--value').strip()=='inactive'
        checks['pair_running']=self.systemctl('show','timeservice.service','--property=ActiveState','--value').strip()=='active'
        pid=int(self.systemctl('show','timeservice.service','--property=MainPID','--value'))
        checks['same_supervisor']=pid==self.state()['supervisor_pid']
        checks['no_restarts']=self.systemctl('show','timeservice.service','--property=NRestarts','--value').strip()=='0'
        checks['no_overrides']=not self.systemctl('show','timeservice.service','--property=DropInPaths','--value').strip()
        children=self.daemon_children()
        identities={name:row['ids'] for name,row in children.items()}
        ntpd_pid=children['/usr/local/sbin/ntpd']['pid']
        checks['credentials']=identities=={'/usr/local/sbin/gpsd':{'Uid':[65534]*4,'Gid':[20]*4},
                                           '/usr/local/sbin/ntpd':{'Uid':[999]*4,'Gid':[985]*4}}
        errors=self.run(['/usr/bin/journalctl','--quiet','--no-pager','--output=json',
                         '--boot='+self.s['boot_id'].replace('-',''),
                         '--unit=timeservice.service','--unit=avahi-daemon.service','--priority=0..3']
                         +(self.journal_scope() if self.s['recipe'].get('diagnostic') else []),timeout=10)
        promotion=None
        if self.s['recipe']['timeservice'].get('pps_startup'):
            promotion=json.loads(self.h.read(Path('/run/ntpsec-startup/promotion.json')))
            if promotion.get('supervisor_pid')!=pid or promotion.get('ntpd_pid')!=ntpd_pid:
                raise ValueError('startup promotion process identity')
            checks['startup_ready']=promotion.get('phase')=='ready'
        journal=journal_health(errors,self.s['boot_id'],self.state()['apply_monotonic'],ntpd_pid,
                               promotion.get('promoted_monotonic') if promotion else None,
                               control_key=bool(self.s['recipe']['timeservice'].get('pps_startup')))
        checks['journal_health']=journal['healthy']
        return {'checks':checks,'measurement':value,'journal':journal,'promotion':promotion}

    def journal_cursor(self):
        raw=self.run(['/usr/bin/journalctl','--quiet','--no-pager','--output=json','--lines=1',
                      '--boot='+self.s['boot_id'].replace('-',''),
                      '--output-fields=__CURSOR,_BOOT_ID,__MONOTONIC_TIMESTAMP'],timeout=10)
        rows=[json.loads(line) for line in raw.splitlines()]
        if len(rows)!=1:raise ValueError('one journal cursor required')
        row=rows[0];cursor=row.get('__CURSOR')
        if (row.get('_BOOT_ID')!=self.s['boot_id'].replace('-','')
                or not isinstance(cursor,str) or not re.fullmatch(r'[A-Za-z0-9;=:_-]{1,1024}',cursor)
                or not 0<=int(row['__MONOTONIC_TIMESTAMP'])/1_000_000<=time.monotonic()):
            raise ValueError('current boot journal cursor required')
        return cursor

    def journal_scope(self):
        cursor=self.state().get('journal_cursor')
        if not isinstance(cursor,str) or not re.fullmatch(r'[A-Za-z0-9;=:_-]{1,1024}',cursor):
            raise ValueError('saved journal cursor required')
        return ['--after-cursor='+cursor,
                '--output-fields=MESSAGE,PRIORITY,_SYSTEMD_UNIT,_EXE,_COMM,_TRANSPORT,SYSLOG_IDENTIFIER,_PID']

    def diagnostic_sample(self):
        with self.lock():
            state=self.state();recipe=self.s['recipe']['diagnostic']
            if state['phase']!='observing':return False
            elapsed=time.monotonic()-state['apply_monotonic']
            if elapsed>=recipe['observation_seconds'] or len(state['diagnostic_samples'])>=recipe['maximum_samples']:return False
            self.command_deadline=state['apply_monotonic']+recipe['observation_seconds']
            value=self.measure();measurement=value['measurement']
            upstreams=[p['variables'] for p in measurement['peers'] if p['variables'].get('srchost') in self.s['recipe']['nts_servers']]
            pending=[p for p in upstreams if p.get('srcadr') is None and p.get('refid')=='NTS']
            outside=[p for p in upstreams if p not in pending and p.get('srcadr') not in recipe['upstream_addresses']]
            counters=measurement['counters'];previous=state['diagnostic_samples'][-1]['result']['measurement']['counters'] if state['diagnostic_samples'] else state['early_ntpd']['counters']
            error=None
            if outside:error='upstream address outside sealed packet scope'
            promotion=value.get('promotion')
            nts_elapsed=time.monotonic()-promotion['promoted_monotonic'] if promotion and promotion.get('promoted_monotonic') else elapsed
            if promotion and promotion.get('phase')=='failed':error='PPS startup promotion failed'
            elif pending and nts_elapsed>=recipe['nts_setup_seconds']:error='NTS association setup deadline elapsed'
            elif any(counters[k]<v for k,v in previous.items()):error='diagnostic counters reset'
            settled=elapsed>=recipe['settling_seconds']
            sample={'elapsed_seconds':elapsed,'settling_window_elapsed':settled,'result':value,
                    'pending_upstreams':pending,'outside_upstreams':outside,
                    'counter_delta':{k:counters[k]-v for k,v in previous.items()}}
            state['diagnostic_samples'].append(sample)
            state.update(last_measurement=value,probe_count=len(state['diagnostic_samples']))
            # Persist the rejecting measurement before fallible ancillary collection.
            if error:sample['error']=error
            self.write('state.json',state)
            if error:raise ValueError(error)
            try:
                capture_active=self.systemctl('is-active',self.s['apply_unit']+'-packets.service').strip()=='active'
                safety=('bootstrap_stopped','pair_running','same_supervisor','no_restarts','no_overrides','credentials','journal_health')
                if not capture_active or not all(value['checks'][k] for k in safety):
                    raise ValueError('runtime diagnostic safety/observer gate failed')
                sample['network']=self.network_observation()
                state['stable']=state['stable']+1 if settled and not pending and all(value['checks'].values()) else 0
            except BaseException as failure:
                sample['error']=str(failure)[:500];self.write('state.json',state);raise
            self.write('state.json',state)
            return state['stable']<self.s['recipe']['stable_probes']

    def diagnose(self):
        if not self.s['recipe'].get('diagnostic'):raise ValueError('diagnostic profile required')
        try:
            while self.diagnostic_sample():
                remaining=self.state()['apply_monotonic']+self.s['recipe']['diagnostic']['observation_seconds']-time.monotonic()
                time.sleep(max(0,min(self.s['recipe']['diagnostic']['interval_seconds'],remaining)))
            with self.lock():
                state=self.state()
                if state['phase']=='observing':
                    state['observation_completed']=True;self.write('state.json',state)
        except BaseException as error:
            with self.lock():
                state=self.state();state['diagnostic_error']=str(error)[:500];self.write('state.json',state)
        finally:self.recover()
        return self.state()


    def probe(self):
        if self.s['recipe'].get('diagnostic'):raise ValueError('diagnostic observations are autonomous and bounded')
        with self.lock():
            state=self.state()
            if state['phase'] not in ('observing','ready'):return state
            if state['probe_count']>=self.s['recipe']['max_probes']:raise ValueError('probe budget consumed')
            now=time.monotonic()
            if now-state.get('last_probe',0)<self.s['recipe']['probe_interval_seconds']:raise ValueError('probe interval')
            try:result=self.measure()
            except (ValueError,KeyError,TypeError,OSError,subprocess.SubprocessError) as error:result={'checks':{'measurement':False},'error':str(error)[:500]}
            state['stable']=state['stable']+1 if all(result['checks'].values()) else 0
            state.update(phase='ready' if state['stable']>=self.s['recipe']['stable_probes'] else 'observing',
                         probe_count=state['probe_count']+1,last_probe=now,last_measurement=result)
            self.write('state.json',state);return state

    def accept(self,proofs):
        if self.s['recipe'].get('diagnostic'):raise ValueError('diagnostic-only profile always recovers; no service acceptance')
        with self.lock():
            state=self.state()
            if state['phase']!='ready' or state['deadline']-time.monotonic()<self.s['recipe']['acceptance_reserve_seconds']:
                raise ValueError('stable candidate and recovery reserve required')
            if not proofs or set(proofs)!=set(self.s['endpoints'])|{'client'}:raise ValueError('dual-stack and client proofs required')
            for endpoint in self.s['endpoints']:
                if proofs[endpoint].get('phase')!='ready' or proofs[endpoint].get('supervisor_pid')!=state['supervisor_pid']:
                    raise ValueError('candidate SSH proof mismatch')
            client=proofs['client']
            if (client.get('target')!=self.s['hostname'] or client.get('checks')!={'ipv4':True,'ipv6':True,'queries_denied':True,'mdns':True}
                    or client.get('spec_sha256')!=sha(encoded(self.s))
                    or not 0<=time.time()-client.get('epoch',0)<120):
                raise ValueError('NTP/mDNS client acceptance required')
            self.unchanged()
            if not all(self.measure()['checks'].values()):raise ValueError('candidate lost convergence')
            if state['deadline']-time.monotonic()<60:raise ValueError('recovery reserve expired during checks')
            self.systemctl('enable','timeservice.service');self.systemctl('disable','systemd-timesyncd.service')
            self.systemctl('enable','--now','ntpleapfetch.timer')
            if time.monotonic()>=state['deadline']:raise ValueError('recovery deadline elapsed during acceptance')
            state.update(phase='accepted',accepted_epoch=int(time.time()),proofs=proofs)
            self.write('state.json',state)  # Acceptance precedes timer cancellation.
            self.cancel_timer();return state

    def recover(self,locked=False):
        self.command_deadline=None  # Evidence deadlines must never prevent restoration.
        self.recovering=True  # A full observation journal must not block recovery commands.
        if not locked:
            with self.lock():return self.recover(locked=True)
        state=self.state()
        if state['phase'] in ('accepted','recovered'):return state
        try:
            if self.s['recipe']['timeservice'].get('pps_startup'):
                try:
                    state['startup_promotion']=json.loads(self.h.read(Path('/run/ntpsec-startup/promotion.json')))
                except (OSError,ValueError) as error:
                    state['startup_promotion']={'phase':'unavailable','error':str(error)[:300]}
                self.write('state.json',state)
            for unit in ('ntpleapfetch.timer','ntpleapfetch.service','timeservice.service'):
                if self.systemctl('show',unit,'--property=LoadState','--value').strip()!='not-found':self.systemctl('stop',unit)
            if self.s['recipe'].get('diagnostic'):
                unit=self.s['apply_unit']+'-packets.service'
                if self.systemctl('show',unit,'--property=LoadState','--value').strip()!='not-found':self.systemctl('stop',unit)
                packet_file=self.root/'packet-report.json'
                try:
                    state['packet_observation']=json.loads(self.h.read(packet_file,limit=512*1024)) if packet_file.exists() else {'phase':'missing','complete':False}
                except (OSError,ValueError) as error:
                    state['packet_observation']={'phase':'held','complete':False,'error':str(error)[:300]}
                self.write('state.json',state)
            for unit in ('ntpleapfetch.timer','timeservice.service'):
                if self.systemctl('show',unit,'--property=LoadState','--value').strip()!='not-found':self.systemctl('disable',unit)
            self.a.idle();before=json.loads(self.h.read(self.root/'before.json'))
            for name in reversed(state['installed']):
                member,mode=DESTINATIONS[name];current=self.snapshot(name);old=before['files'][name]
                temp=Path(name).with_name('.'+Path(name).name+'.'+self.s['operation_id'])
                if os.path.lexists(temp):
                    self.snapshot(str(temp));temp.unlink()
                if current==old:continue
                if not current or current['sha256']!=sha(self.f[member]):raise ValueError('recovery destination drift: '+name)
                if old is None:Path(name).unlink()
                else:self.replace(name,base64.b64decode(old['base64']),old['mode'],old['uid'],old['gid'])
                self.h.sync(Path(name).parent)
            # Keep runtime-generated drift/statistics as evidence, then remove only empty owned directories.
            saved=self.root/'runtime-data';saved.mkdir(mode=0o700,exist_ok=True)
            for name in reversed(state['created_directories']):
                path=Path(name)
                if not os.path.lexists(path):continue
                info=path.lstat();uid,gid,mode=DIRECTORIES[name]
                if not stat.S_ISDIR(info.st_mode) or info.st_uid not in (0,uid) or stat.S_IMODE(info.st_mode) not in (0o700,mode) or info.st_gid not in (0,gid):raise ValueError('recovery directory drift')
                for child in path.iterdir():
                    pattern=r'(?:loopstats|peerstats|clockstats)(?:\.\d{8})?' if name=='/var/log/ntpstats' else r'ntp\.drift(?:\.TEMP)?' if name.endswith('/drift') else r'leap-seconds\.tmp'
                    if not re.fullmatch(pattern,child.name) or child.is_symlink() or not child.is_file():raise ValueError('unexpected recovery directory content')
                    fd=os.open(child,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
                    with os.fdopen(fd,'rb') as stream:raw=stream.read(8*1024**2+1)
                    if len(raw)>8*1024**2:raise ValueError('runtime recovery evidence bound')
                    destination=saved/(path.name+'-'+child.name)
                    if destination.exists():
                        if self.h.read(destination,limit=8*1024**2)!=raw:raise ValueError('recovery evidence conflict')
                    else:self.h.create(destination,raw)
                    child.unlink()
                path.rmdir()
            if self.a.serial_identity()!=before['serial']:raise ValueError('UART identity drift during recovery')
            self.run(['/usr/bin/stty','-F','/dev/serial0',before['termios']])
            if self.run(['/usr/bin/stty','-F','/dev/serial0','-g']).strip()!=before['termios']:raise ValueError('UART recovery failed')
            self.systemctl('daemon-reload');self.systemctl('restart','avahi-daemon.service')
            self.systemctl('enable','--now','systemd-timesyncd.service')
            clear_restored_failure(self.systemctl)
            self.runtime_context()
            if self.s['recipe'].get('diagnostic'):
                try:
                    state['diagnostic_statistics']={};total=0
                    for path in sorted(saved.iterdir()):
                        raw=self.h.read(path,limit=2*1024**2);total+=len(raw)
                        if total>2*1024**2:raise ValueError('diagnostic statistics bound')
                        state['diagnostic_statistics'][path.name]={'sha256':sha(raw),'base64':base64.b64encode(raw).decode()}
                    state['network_after']=self.network_observation()
                    raw=self.run(['/usr/bin/journalctl','--quiet','--no-pager','--output=json','--lines=2000',
                        '--boot='+self.s['boot_id'].replace('-',''),'--unit=timeservice.service','--unit=avahi-daemon.service',
                        '--unit='+self.s['apply_unit']+'-diagnostic.service','--unit='+self.s['apply_unit']+'-packets.service']+self.journal_scope(),timeout=10)
                    rows=[json.loads(line) for line in raw.splitlines()]
                    if len(rows)>=2000 or any(row['_BOOT_ID']!=self.s['boot_id'].replace('-','') for row in rows):
                        raise ValueError('bounded complete diagnostic journal required')
                    selected=[row for row in rows if int(row['__MONOTONIC_TIMESTAMP'])/1_000_000>=state['apply_monotonic']]
                    if not selected:raise ValueError('operation journal missing')
                    state['diagnostic_journal']={'complete':True,'records':selected}
                except (ValueError,KeyError,OSError,subprocess.SubprocessError) as error:
                    state['diagnostic_evidence_error']='post-recovery evidence: '+str(error)[:300]
                    state.setdefault('diagnostic_error',state['diagnostic_evidence_error'])
            state.update(phase='recovered',recovered_epoch=int(time.time()));self.write('state.json',state)
            self.cancel_timer();return state
        except BaseException as error:
            state.update(phase='recovery_held',error=str(error)[:500]);self.write('state.json',state);raise


def entry(spec,files,mode,proofs=None):
    if os.geteuid()!=0 or socket.gethostname()!=spec['hostname'] or os.uname().release!=spec['kernel'] or Path('/proc/sys/kernel/random/boot_id').read_text().strip()!=spec['boot_id']:
        raise ValueError('approved root/target/boot identity required')
    root=Path(spec['stage']);os.umask(0o077)
    if mode=='start':
        if os.environ.get('SUDO_USER')!='ama' or not spec['prepared_epoch']-300<=time.time()<spec['expires_epoch']:raise ValueError('caller/window')
        for parent in (root.parent,*root.parent.parents):
            info=parent.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid or info.st_gid or info.st_mode&0o022:raise ValueError('protected stage parent required')
        root.mkdir(mode=0o700)
        for name,raw in files.items():
            with (root/name).open('xb') as stream:stream.write(raw)
        with (root/'spec.json').open('xb') as stream:stream.write(encoded(spec))
    tx=Transaction(spec,files);tx.h.ancestors(root)
    if stat.S_IMODE(root.stat().st_mode)!=0o700 or tx.h.read(root/'spec.json')!=encoded(spec):raise ValueError('protected stage mismatch')
    for name,digest in spec['members'].items():
        limit=64*1024**2 if spec.get('purpose')=='service-monitor' and name.endswith('.tar') else 32*1024**2
        if sha(tx.h.read(root/name,limit=limit))!=digest:raise ValueError('sealed cutover input drift')
    if mode=='start':
        tx.preflight();tx.arm()
        tx.run(['/usr/bin/systemd-run','--quiet','--unit='+spec['apply_unit'],
                '--property=WorkingDirectory='+str(root),'--property=LimitFSIZE=8388608','--property=RuntimeMaxSec=120','--property=TimeoutStopSec=20','--property=KillMode=control-group','--property=UMask=0077',
                '--property=ExecStopPost=/usr/bin/python3 -I -B '+str(root/'stage.py')+' worker recover-if-applying',
                '/usr/bin/python3','-I','-B',str(root/'stage.py'),'worker','apply'])
        deadline=time.monotonic()+65
        while tx.state()['phase'] in ('staged','applying') and time.monotonic()<deadline:time.sleep(.5)
        return tx.state()
    if mode=='apply':return tx.apply()
    if mode=='diagnose':return tx.diagnose()
    if mode=='probe':return tx.probe()
    if mode=='accept':return tx.accept(proofs)
    if mode=='recover':return tx.recover()
    if mode=='recover-if-applying':
        return tx.recover() if tx.state()['phase'] in ('applying','apply_held') else tx.state()
    if mode=='readback':return tx.state()
    if mode=='cleanup':
        state=tx.state()
        if state['phase'] not in ('accepted','recovered'):raise ValueError('terminal acceptance/recovery required')
        tx.cancel_timer()
        units=[spec['apply_unit']+'.service',spec['recovery_unit']+'.service']
        if spec['recipe'].get('diagnostic'):units.extend([spec['apply_unit']+'-diagnostic.service',spec['apply_unit']+'-packets.service'])
        for unit in units:
            if tx.systemctl('show',unit,'--property=ActiveState','--value').strip() in ('active','activating','deactivating'):raise ValueError('transient unit still running')
            if tx.systemctl('show',unit,'--property=LoadState','--value').strip()!='not-found':tx.systemctl('reset-failed',unit)
        state['transient_cleanup']=True;tx.write('state.json',state);return state
    raise ValueError('closed cutover mode required')


if __name__=='__main__':
    if len(sys.argv)!=3 or sys.argv[1]!='worker':raise SystemExit('sealed worker only')
    root=Path(__file__).resolve().parent;s=json.loads((root/'spec.json').read_bytes())
    f={n:(root/n).read_bytes() for n in s['members']};entry(s,f,sys.argv[2])
