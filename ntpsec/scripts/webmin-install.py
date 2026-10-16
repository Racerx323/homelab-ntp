#!/usr/bin/python3
"""Install a pinned Webmin candidate behind a persistent first-start condition."""
import base64
import http.client
import json
import os
from pathlib import Path
import re
import signal
import socket
import time

GUARD = Path('/etc/systemd/system/webmin.service.d/10-first-start.conf')
MARKER = Path('/etc/webmin/.installation-accepted')
CONFIG = Path('/etc/webmin/miniserv.conf')
SOURCE = Path('/etc/apt/sources.list.d/webmin-reviewed.list')
KEY = Path('/usr/share/keyrings/webmin-reviewed.gpg')
PIN = Path('/etc/apt/preferences.d/webmin-reviewed')
PROTECTED = ('/etc/ntp.conf', '/etc/ntpsec-timeservice.json',
             '/etc/systemd/system/ntpleapfetch.service', '/etc/systemd/system/ntpleapfetch.timer')
CONTINUATION_PATHS = ('/usr/lib/systemd/system/webmin.service',
                      '/etc/systemd/system/webmin.service.d/10-first-start.conf',
                      '/etc/webmin/start', '/etc/webmin/stop', '/etc/webmin/miniserv.conf',
                      '/usr/share/webmin/miniserv.pl', '/usr/share/webmin/miniserv-lib.pl')
RECOVERED_UNIT_KEYS = ('ActiveState','SubState','InvocationID','Result','ExecMainCode','ExecMainStatus')


def configure(raw, policy):
    lines = raw.decode().splitlines(); seen = set(); result = []
    for line in lines:
        key = line.partition('=')[0]
        if key in policy:
            if key in seen: raise ValueError('duplicate policy key: '+key)
            seen.add(key)
        else: result.append(line)
    result.extend(k+'='+v for k,v in policy.items())
    return ('\n'.join(result)+'\n').encode()


def properties(raw):
    result = {}
    for line in raw.splitlines():
        key,value = line.split('=',1)
        if key in result: raise ValueError('duplicate property')
        result[key] = value
    return result


def interrupt(signum, frame):
    raise RuntimeError('interrupted: '+str(signum))


class Install:
    def __init__(self, spec, inputs, helper):
        self.spec, self.inputs, self.h = spec, inputs, helper
        self.root = Path('/var/lib/ntp-webmin-'+spec['operation_id'])
        self.state = {'operation_id':spec['operation_id'], 'spec_sha256':helper.sha(helper.encoded(spec)),
                      'installed':False, 'authenticated_accepted':False, 'recovery':'not-needed', 'commands':[]}
        self.created = False; self.mutated = False

    def cmd(self, argv, timeout=30):
        row = self.h.bounded(argv, timeout=timeout, env={'PATH':'/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
                              'LC_ALL':'C','DEBIAN_FRONTEND':'noninteractive','PYTHONDONTWRITEBYTECODE':'1'})
        self.state['commands'].append(row)
        if row.get('returncode') != 0 or row.get('error'): raise ValueError('command failed: '+repr(argv))
        return row['stdout']

    def save(self):
        (self.root/'state.json').write_bytes(self.h.encoded(self.state))

    def unit(self, name, timeout=30):
        return properties(self.cmd(['/usr/bin/systemctl','show',name,
            '--property=LoadState,ActiveState,SubState,UnitFileState,MainPID,NRestarts,InvocationID,DropInPaths,ConditionResult,Result,ExecMainCode,ExecMainStatus'],timeout))

    def continuity(self):
        if (os.geteuid()!=0 or socket.gethostname().split('.')[0]!=self.spec['hostname']
                or Path('/proc/sys/kernel/random/boot_id').read_text().strip()!=self.spec['boot_id']):
            raise ValueError('host/root/boot mismatch')
        row = self.unit('timeservice.service')
        if any(row.get(k)!=v for k,v in self.spec['service_identity'].items()):
            raise ValueError('time service continuity changed')
        for path, expected in getattr(self,'protected',{}).items():
            if self.record(path)!=expected: raise ValueError('protected file changed: '+path)

    def record(self, path):
        row = self.h.file_record(path)
        if row.get('missing') or row.get('error') or row.get('changed_during_read'): raise ValueError('unsafe file: '+str(path))
        return {k:row[k] for k in ('sha256','uid','gid','mode')}

    def write_new(self, path, raw, mode=0o644):
        for parent in path.parents:
            if parent.is_symlink(): raise ValueError('symlink parent')
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,mode)
        with os.fdopen(fd,'wb') as stream:
            stream.write(raw);stream.flush();os.fchmod(stream.fileno(),mode);os.fsync(stream.fileno())

    def inventory(self):
        text=self.cmd(['/usr/bin/dpkg-query','-W','-f=${binary:Package}\t${Version}\t${Architecture}\t${db:Status-Abbrev}\n'])
        return {line.split('\t')[0]:line.split('\t')[1:] for line in text.splitlines()}

    def no_listener(self):
        if self.cmd(['/usr/bin/ss','-H','-lntu','sport = :10000']).strip(): raise ValueError('unexpected port 10000 listener')

    def guard(self):
        if self.record(GUARD)['sha256']!=self.h.sha(self.inputs['guard.conf']): raise ValueError('first-start guard changed')

    def preflight(self):
        self.continuity()
        if self.cmd(['/usr/bin/dpkg','--print-architecture']).strip()!='arm64': raise ValueError('wrong architecture')
        if self.cmd(['/usr/bin/dpkg','--audit']).strip(): raise ValueError('dpkg audit not clean')
        self.before=self.inventory()
        if self.before!=self.spec['packages_before']: raise ValueError('package baseline changed')
        for path in ('/etc/webmin','/var/webmin','/usr/share/webmin','/etc/pam.d/webmin','/tmp/.webmin',
                     '/etc/init.d/webmin','/usr/bin/webmin',
                     '/etc/systemd/system/webmin.service','/etc/systemd/system/webmin.service.d',
                     '/usr/lib/systemd/system/webmin.service',str(SOURCE),str(KEY),str(PIN)):
            if os.path.lexists(path): raise ValueError('expected absent: '+path)
        for path in [Path('/etc/dpkg/dpkg.cfg'), *Path('/etc/dpkg/dpkg.cfg.d').glob('*')]:
            if path.is_file():
                raw=self.h.file_record(path,content=True)
                self.record(path)
                lines=base64.b64decode(raw['base64']).decode().splitlines()
                if any(re.match(r'\s*(?:--)?(?:pre|post)-invoke(?:[=\s]|$)',x) for x in lines):
                    raise ValueError('unreviewed dpkg invocation hook')
        row=self.unit('webmin.service')
        if row['LoadState']!='not-found' or row['ActiveState']!='inactive': raise ValueError('Webmin already present')
        self.no_listener();self.protected={p:self.record(p) for p in PROTECTED}
        self.cmd(['/usr/bin/id','ama'])
        self.root.mkdir(mode=0o700);self.created=True;self.save()
        self.package_paths=[]
        for package in self.spec['packages']:
            raw=self.inputs[package['member']]
            if self.h.sha(raw)!=package['sha256']: raise ValueError('package input hash')
            path=self.root/package['member'];self.write_new(path,raw,0o600);self.package_paths.append(str(path))
        # Uses the real installed dpkg provider/dependency view without mutation.
        self.cmd(['/usr/bin/dpkg','--no-act','--install',*self.package_paths],120)

    def apply(self):
        if self.spec.get('continuation'):
            self.continue_start()
            return
        self.preflight();self.continuity()
        self.mutated=True;self.state['recovery']='pending';self.save()
        GUARD.parent.mkdir(mode=0o755);GUARD.parent.chmod(0o755);self.write_new(GUARD,self.inputs['guard.conf'])
        self.cmd(['/usr/bin/systemctl','daemon-reload'])
        self.cmd(['/usr/bin/dpkg','--install',*self.package_paths],300)
        self.guard();self.no_listener()
        stopped=self.unit('webmin.service')
        if stopped['ActiveState']!='inactive': raise ValueError('package started Webmin')
        if stopped.get('DropInPaths')!=str(GUARD): raise ValueError('unexpected effective Webmin overrides')
        if self.cmd(['/usr/bin/dpkg','--audit']).strip(): raise ValueError('post-install dpkg audit')
        after=self.inventory(); selected={p['name']:p for p in self.spec['packages']}
        if {k:v for k,v in after.items() if k.split(':')[0] not in selected}!=self.before:
            raise ValueError('unrelated package state changed')
        for name,p in selected.items():
            found=[v for k,v in after.items() if k.split(':')[0]==name]
            if found!=[[p['version'],p['architecture'],'ii ']]: raise ValueError('package version/status mismatch')
        before=self.record(CONFIG);raw=self.h.file_record(CONFIG,content=True)
        policy=json.loads(self.inputs['policy.json']);new=configure(base64.b64decode(raw['base64']),policy)
        temp=CONFIG.with_name('.miniserv-reviewed.tmp');self.write_new(temp,new,0o600)
        if self.record(CONFIG)!=before: raise ValueError('configuration changed while preparing')
        os.replace(temp,CONFIG)
        self.state['configuration_sha256']=self.h.sha(new)
        self.write_new(KEY,self.inputs['keyring.gpg']);self.write_new(SOURCE,self.inputs['source.list'])
        self.write_new(PIN,self.inputs['preferences'])
        self.cmd(['/usr/bin/perl','-MAuthen::PAM','-MIO::Pty','-MNet::SSLeay','-MSocket6','-e','exit 0'])
        self.cmd(['/usr/bin/systemd-analyze','verify','webmin.service'])
        self.start_and_accept()

    def continue_start(self):
        self.continuity()
        if self.cmd(['/usr/bin/dpkg','--audit']).strip(): raise ValueError('dpkg audit not clean')
        if self.inventory()!=self.spec['packages_before']: raise ValueError('package baseline changed')
        for path, expected in self.spec['continuation_files'].items():
            if self.record(path)!=expected: raise ValueError('installed file changed: '+path)
        if os.path.lexists(MARKER) or os.path.lexists('/etc/systemd/system/webmin.service'):
            raise ValueError('unexpected permit or overriding unit')
        row=self.unit('webmin.service')
        if (row.get('LoadState')!='loaded' or row.get('UnitFileState')!='disabled'
                or row.get('MainPID')!='0' or row.get('NRestarts')!='0'
                or row.get('DropInPaths')!=str(GUARD)
                or any(row.get(k)!=v for k,v in self.spec['continuation_unit'].items())):
            raise ValueError('recovered Webmin state changed')
        self.guard();self.no_listener()
        self.protected={p:self.record(p) for p in PROTECTED}
        self.cmd(['/usr/bin/id','ama'])
        self.cmd(['/usr/bin/systemd-analyze','verify','webmin.service'])
        self.root.mkdir(mode=0o700);self.created=True
        self.state['configuration_sha256']=self.record(CONFIG)['sha256']
        self.mutated=True;self.state['recovery']='pending';self.save()
        if self.spec['continuation_unit']['ActiveState']=='failed':
            self.cmd(['/usr/bin/systemctl','reset-failed','webmin.service'])
            cleared=self.unit('webmin.service')
            if (cleared.get('ActiveState')!='inactive' or cleared.get('SubState')!='dead'
                    or cleared.get('MainPID')!='0' or cleared.get('NRestarts')!='0'
                    or cleared.get('UnitFileState')!='disabled' or cleared.get('DropInPaths')!=str(GUARD)):
                raise ValueError('Webmin failure reset did not preserve stopped state')
        self.start_and_accept()

    def wait_ready(self):
        deadline=time.monotonic()+60
        expected={'10.1.0.51:10000','[fd36:5aa8:6971:1::51]:10000'}
        identity=None
        def remaining():
            value=deadline-time.monotonic()
            if value<=0: raise ValueError('Webmin readiness deadline exceeded')
            return min(5,value)
        while True:
            row=self.unit('webmin.service',remaining())
            if (row.get('ActiveState')!='active' or row.get('SubState')!='running'
                    or row.get('UnitFileState')!='enabled' or int(row.get('MainPID','0'))<=0
                    or row.get('NRestarts')!='0' or not row.get('InvocationID')
                    or row.get('DropInPaths')!=str(GUARD)):
                raise ValueError('Webmin failed during readiness')
            current=(row['MainPID'],row['InvocationID'])
            if identity is not None and current!=identity: raise ValueError('Webmin restarted during readiness')
            identity=current
            listeners=self.cmd(['/usr/bin/ss','-H','-lnt','sport = :10000'],remaining())
            addresses={line.split()[3] for line in listeners.splitlines()}
            if not addresses<=expected: raise ValueError('listener scope mismatch')
            if self.cmd(['/usr/bin/ss','-H','-lnu','sport = :10000'],remaining()).strip():
                raise ValueError('unexpected UDP discovery listener')
            remaining()
            if addresses==expected:
                self.state['webmin_unit']=row
                return
            time.sleep(min(1,remaining()))

    def start_and_accept(self):
        self.guard();self.continuity();self.no_listener()
        self.write_new(MARKER,b'HTTP configuration checked by '+self.spec['operation_id'].encode()+b'\n',0o600)
        self.state['start_permitted']=True;self.save()
        self.cmd(['/usr/bin/systemctl','enable','--now','webmin.service'],60)
        self.wait_ready()
        self.state['http']={}
        for host in self.spec['endpoints']:
            connection=http.client.HTTPConnection(host,10000,timeout=10)
            try:
                connection.request('GET','/');response=connection.getresponse()
                location=response.getheader('Location','');status=response.status;response.read(65536)
                if status not in (200,301,302,303) or location.lower().startswith('https:'):
                    raise ValueError('HTTP login endpoint failed')
                self.state['http'][host]={'status':status}
            finally:connection.close()
        if self.record(CONFIG)['sha256']!=self.state['configuration_sha256']: raise ValueError('configuration drift after start')
        final=self.unit('webmin.service')
        if any(final.get(k)!=self.state['webmin_unit'].get(k) for k in
               ('MainPID','InvocationID','NRestarts','ActiveState','SubState','UnitFileState','DropInPaths')):
            raise ValueError('Webmin changed during HTTP checks')
        self.guard();self.continuity()
        self.state.update(installed=True,recovery='not-needed')

    def recover(self):
        # Contain only the newly introduced service; retain packages for inspection.
        # Stop it even when a missing/altered guard prevents safe configuration cleanup.
        self.cmd(['/usr/bin/systemctl','stop','webmin.service'],60)
        self.no_listener();self.state['service_stopped']=True
        self.guard()
        if MARKER.exists():
            expected=b'HTTP configuration checked by '+self.spec['operation_id'].encode()+b'\n'
            if self.record(MARKER)['sha256']!=self.h.sha(expected): raise ValueError('foreign permit marker')
            MARKER.unlink()
        self.cmd(['/usr/bin/systemctl','disable','webmin.service'])
        self.no_listener();self.continuity()
        self.state['recovery']='non-serving; packages retained'

    def run(self):
        os.umask(0o077)
        try:self.apply()
        except Exception as error:
            signal.alarm(0);self.state['error']=str(error)
            if self.mutated:
                try:self.recover()
                except Exception as failure:self.state.update(recovery='held',recovery_error=str(failure))
        finally:
            if self.created:self.save()
        return self.state


def run(spec, inputs, helper):
    for sig in (signal.SIGALRM,signal.SIGINT,signal.SIGTERM,signal.SIGHUP):signal.signal(sig,interrupt)
    signal.alarm(600)
    return Install(spec,inputs,helper).run()
