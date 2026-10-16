#!/usr/bin/python3
"""Install reviewed outbound mail assets and submit two approved messages once."""
import json
import os
import pwd
from pathlib import Path
import socket

FILES = {'msmtprc': ('/etc/msmtprc', 0o600), 'aliases': ('/etc/aliases', 0o644),
         'reporter.sh': ('/usr/local/sbin/needrestart.sh', 0o755),
         'cron.pending': ('/usr/local/sbin/needrestart_check.pending', 0o600)}
MASK = Path('/etc/systemd/system/msmtpd.service')
PROTECTED = ('/etc/ntp.conf', '/etc/ntpsec-timeservice.json',
             '/etc/systemd/system/ntpleapfetch.service', '/etc/systemd/system/ntpleapfetch.timer',
             '/etc/needrestart/conf.d/zz-ntp-policy.conf', '/etc/needrestart/conf.d/rpi-kernel.conf')


def properties(text):
    return dict(line.split('=', 1) for line in text.splitlines() if '=' in line)


class Install:
    def __init__(self, spec, inputs, helper):
        self.spec, self.inputs, self.h = spec, inputs, helper
        self.root = Path('/var/lib/ntp-mail-'+spec['operation_id'])
        self.state = {'operation_id':spec['operation_id'], 'spec_sha256':helper.sha(helper.encoded(spec)),
                      'installed':False, 'delivery_verified':False, 'reporting_accepted':False, 'cron_active':False,
                      'recovery':'not-needed', 'commands':[], 'messages':{}}
        self.written=[]; self.created=False; self.mutated=False

    def cmd(self, argv, timeout=30, payload=None, accepted=(0,)):
        result=self.h.bounded(argv, timeout=timeout, payload=payload,
            env={'PATH':'/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
                 'LC_ALL':'C','DEBIAN_FRONTEND':'noninteractive','NEEDRESTART_MODE':'l'})
        self.state['commands'].append(result)
        if result.get('returncode') not in accepted or result.get('error'):
            raise ValueError('command failed: '+repr(argv))
        return result['stdout']

    def save(self):
        if self.created: (self.root/'state.json').write_bytes(self.h.encoded(self.state))

    def write_new(self, path, raw, mode):
        for parent in path.parents:
            if parent.is_symlink(): raise ValueError('symlink parent')
        fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,mode)
        with os.fdopen(fd,'wb') as stream:
            os.fchmod(stream.fileno(),mode);stream.write(raw);stream.flush();os.fsync(stream.fileno())

    def inventory(self):
        text=self.cmd(['/usr/bin/dpkg-query','-W','-f=${binary:Package}\t${Version}\t${db:Status-Abbrev}\n'])
        return dict((parts[0],parts[1:]) for parts in (line.split('\t') for line in text.splitlines()))

    def unit(self, name):
        return properties(self.cmd(['/usr/bin/systemctl','show',name,
            '--property=LoadState,ActiveState,SubState,UnitFileState,MainPID,InvocationID,NRestarts']))

    def continuity(self):
        if Path('/proc/sys/kernel/random/boot_id').read_text().strip()!=self.spec['boot_id']:
            raise ValueError('boot changed')
        unit=self.unit('timeservice.service')
        if any(unit.get(k)!=v for k,v in self.spec['service_identity'].items()):
            raise ValueError('NTP identity changed')
        if hasattr(self,'protected'):
            for p,expected in self.protected.items():
                if self.h.file_record(p)!=expected: raise ValueError('protected file changed: '+p)

    def preflight(self):
        if os.geteuid()!=0 or socket.gethostname().split('.')[0]!='j2-svntp1': raise ValueError('target/root identity')
        self.continuity()
        if self.cmd(['/usr/bin/dpkg','--print-architecture']).strip()!='arm64': raise ValueError('architecture')
        if self.cmd(['/usr/bin/dpkg','--audit']).strip(): raise ValueError('dpkg audit')
        if self.inventory()!=self.spec['packages_before']: raise ValueError('package baseline changed')
        if self.cmd(['/usr/bin/timedatectl','show','--property=Timezone','--value']).strip()!='America/Chicago':
            raise ValueError('reporting timezone mismatch')
        for p in [*PROTECTED]:
            record=self.h.file_record(p)
            if record.get('missing') or record.get('error') or record.get('changed_during_read'):
                raise ValueError('protected path unreadable')
        self.protected={p:self.h.file_record(p) for p in PROTECTED}
        root_home=Path(pwd.getpwuid(0).pw_dir)
        forbidden=[str(root_home/'.msmtprc'),str(root_home/'.config/msmtp/config')]+[p for p,_ in FILES.values()]+[str(MASK),'/etc/cron.d/needrestart_check',
            '/etc/default/msmtpd','/usr/bin/msmtp','/usr/bin/msmtpd','/usr/sbin/sendmail',
            '/usr/lib/sendmail','/usr/bin/newaliases','/etc/apparmor.d/usr.bin.msmtp']
        for name in forbidden:
            p=Path(name)
            if os.path.lexists(p) or any(x.is_symlink() for x in p.parents):
                raise ValueError('pre-existing or indirect destination: '+name)
        if self.cmd(['/usr/bin/getent','passwd','msmtp'],accepted=(0,2)).strip():
            raise ValueError('existing msmtp account')
        configs=[Path('/etc/dpkg/dpkg.cfg'),*Path('/etc/dpkg/dpkg.cfg.d').glob('*')]
        for p in configs:
            if p.is_symlink(): raise ValueError('indirect dpkg configuration')
            if p.is_file():
                for line in p.read_text().splitlines():
                    token=line.strip().lstrip('-').split('=',1)[0].split(None,1)
                    if token and token[0] in ('pre-invoke','post-invoke'): raise ValueError('dpkg invocation hook')
        if self.unit('msmtpd.service')['LoadState']!='not-found': raise ValueError('existing msmtpd unit')
        self.root.mkdir(mode=0o700);self.created=True;self.save()
        self.package_paths=[]
        for p in self.spec['packages']:
            raw=self.inputs[p['filename']]
            if self.h.sha(raw)!=p['sha256']: raise ValueError('package digest')
            path=self.root/p['filename'];self.write_new(path,raw,0o600);self.package_paths.append(str(path))
        self.cmd(['/usr/bin/dpkg','--no-act','--install',*self.package_paths],120)

    def accept_files(self):
        for member,(name,mode) in FILES.items():
            record=self.h.file_record(name)
            if (record.get('sha256')!=self.h.sha(self.inputs[member]) or record.get('uid')!=0
                    or record.get('gid')!=0): raise ValueError('installed file mismatch: '+name)
            if Path(name).stat().st_mode & 0o777 != mode: raise ValueError('installed mode mismatch')
        if not MASK.is_symlink() or os.readlink(MASK)!='/dev/null': raise ValueError('listener mask changed')
        unit=self.unit('msmtpd.service')
        if unit['ActiveState']!='inactive' or unit['UnitFileState']!='masked': raise ValueError('listener not masked/inactive')
        if os.path.lexists('/etc/cron.d/needrestart_check'): raise ValueError('cron unexpectedly active')
        if Path('/usr/sbin/sendmail').resolve()!=Path('/usr/bin/msmtp'): raise ValueError('sendmail target mismatch')
        if self.h.sha(Path('/usr/bin/msmtp').read_bytes())!=self.spec['msmtp_binary_sha256']:
            raise ValueError('msmtp binary mismatch')

    def submit(self, member):
        # Record intent before submission. Neither failures nor interruptions retry.
        self.state['messages'][member]={'attempted':True,'sha256':self.h.sha(self.inputs[member]),'smtp_accepted':False}
        self.save()
        self.cmd(['/usr/sbin/sendmail','-t'],timeout=60,payload=self.inputs[member])
        self.state['messages'][member]['smtp_accepted']=True;self.save()

    def apply(self):
        self.preflight();self.continuity();self.mutated=True;self.state['recovery']='pending';self.save()
        os.symlink('/dev/null',MASK)
        self.cmd(['/usr/bin/systemctl','daemon-reload'])
        # Keep Debian's AppArmor protection enabled; no credential-bearing debconf data.
        self.cmd(['/usr/bin/debconf-set-selections'],payload=b'msmtp msmtp/apparmor boolean true\n')
        self.cmd(['/usr/bin/dpkg','--install',*self.package_paths],300)
        if self.cmd(['/usr/bin/dpkg','--audit']).strip(): raise ValueError('post-install audit')
        after=self.inventory();selected={p['package']:p for p in self.spec['packages']}
        if {k:v for k,v in after.items() if k.split(':')[0] not in selected}!=self.spec['packages_before']:
            raise ValueError('unrelated package change')
        for name,p in selected.items():
            if [v for k,v in after.items() if k.split(':')[0]==name]!=[[p['version'],'ii ']]:
                raise ValueError('selected package version/status')
        for member,(name,mode) in FILES.items():
            self.write_new(Path(name),self.inputs[member],mode);self.written.append(member);self.save()
        self.accept_files();self.continuity()
        self.cmd(['/bin/bash','-n','/usr/local/sbin/needrestart.sh'])
        self.cmd(['/usr/bin/msmtp','--pretend','--account=apprise','notify@mailrise.xyz'])
        self.cmd(['/usr/bin/msmtp','--pretend','--account=apprise','notify.failure@mailrise.xyz'])
        self.state['installed']=True;self.save()
        for member in ('report.eml','failure.eml'): self.submit(member)
        self.accept_files();self.continuity()
        self.state['recovery']='not-needed';self.state['accepted']=True;self.save()

    def recover(self):
        if not self.mutated: return
        # Retain package state for inspection; do not purge dependencies/accounts.
        # Withdraw only files created by this invocation and still byte-identical.
        for member in reversed(self.written):
            name,_=FILES[member];p=Path(name)
            if p.is_symlink() or not p.is_file() or self.h.sha(p.read_bytes())!=self.h.sha(self.inputs[member]):
                raise ValueError('foreign file; recovery held')
            p.unlink()
        if not MASK.is_symlink() or os.readlink(MASK)!='/dev/null': raise ValueError('mask drift; recovery held')
        if self.unit('msmtpd.service')['ActiveState'] not in ('inactive','failed'):
            self.cmd(['/usr/bin/systemctl','stop','msmtpd.service'])
        self.continuity()
        self.state['installed']=False;self.state['packages_retained']=True
        self.state['recovery']='mail configuration withdrawn; packages and listener mask retained'

    def run(self):
        try:
            self.apply()
        except Exception as error:
            self.state['accepted']=False;self.state['error']=str(error)
            try: self.recover()
            except Exception as recovery_error:
                self.state['recovery']='held';self.state['recovery_error']=str(recovery_error)
            self.save()
        return self.state
