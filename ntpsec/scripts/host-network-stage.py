#!/usr/bin/python3
"""Guard one NetworkManager candidate with a root-owned monotonic recovery timer."""
import argparse
import base64
import fcntl
import hashlib
import importlib.util
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import stat
import subprocess
import sys
import time

NM = '/usr/bin/nmcli'
SYSTEMCTL = '/usr/bin/systemctl'
GROUPS = 'connection,802-3-ethernet,ipv4,ipv6'
LABELS = {'profile', 'original_retained', 'registry', 'addresses', 'ipv6_ra',
          'dns', 'routes', 'dns_reachability', 'https_egress', 'continuity'}


def encoded(value):
    return (json.dumps(value, sort_keys=True) + '\n').encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def protected_bytes(path):
    if not re.fullmatch(r'/var/lib/ntp-network-[a-z][a-z0-9-]{0,47}/[a-z][a-z0-9.-]+',str(path)):
        raise ValueError('fixed root network staging path required')
    for parent in (path.parent,*path.parent.parents):
        info=parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid or info.st_gid or info.st_mode & 0o022:
            raise ValueError('unprotected network stage ancestor')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        info=os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid or info.st_gid or info.st_nlink!=1
                or stat.S_IMODE(info.st_mode)!=0o600 or info.st_size>2*1024**2):
            raise ValueError('protected bounded network input required')
        with os.fdopen(fd,'rb',closefd=False) as stream:return stream.read(2*1024**2+1)
    finally:os.close(fd)


def load(path, digest):
    if sha(protected_bytes(path))!=digest:raise ValueError('network helper hash drift')
    s = importlib.util.spec_from_file_location('network_' + path.stem.replace('-', '_'), path)
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m)
    return m


def properties(text):
    values = {}
    for line in text.splitlines():
        key, sep, value = line.partition(':')
        if not sep or key in values or not key.startswith(('connection.', '802-3-ethernet.', 'ipv4.', 'ipv6.')):
            raise ValueError('unique scoped Ethernet properties required')
        values[key] = re.sub(r'\\([:\\])',r'\1',value)
    if not 10 <= len(values) <= 256:
        raise ValueError('bounded Ethernet property set required')
    return values


def stable(values):
    return {k: v for k, v in values.items() if k != 'connection.timestamp'}


def settings(recipe):
    return {'connection.autoconnect': 'yes', 'connection.autoconnect-priority': '100',
        'ipv4.method': 'manual', 'ipv4.addresses': recipe['ipv4_address'],
        'ipv4.gateway': recipe['ipv4_gateway'], 'ipv4.dns': recipe['ipv4_dns'],
        'ipv4.ignore-auto-dns': 'yes', 'ipv4.dad-timeout': '3000', 'ipv4.may-fail': 'no',
        'ipv6.method': 'auto', 'ipv6.addresses': recipe['ipv6_address'],
        'ipv6.dns': recipe['ipv6_dns'], 'ipv6.ignore-auto-dns': 'yes', 'ipv6.may-fail': 'no'}


def validate_spec(spec):
    r = spec['recipe']
    expected = {'schema','hostname','interface','ipv4_address','ipv4_gateway','ipv4_dns',
        'ipv6_address','ipv6_dns','recovery_seconds','apply_max_seconds','acceptance_reserve_seconds',
        'snapshot_max_age_seconds','egress_url'}
    if (set(r) != expected or r['schema'] != 1 or r['interface'] != 'eth0'
            or r['egress_url'] != 'https://deb.debian.org/debian/'
            or r['recovery_seconds'] != 300 or r['apply_max_seconds'] != 180
            or r['acceptance_reserve_seconds'] != 45 or r['snapshot_max_age_seconds'] != 86400
            or not re.fullmatch(r'[a-z][a-z0-9-]{0,47}', spec['operation_id'])
            or spec['stage'] != '/var/lib/ntp-network-' + spec['operation_id']
            or spec['hostname'] != r['hostname'] or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,62}',r['hostname'])
            or spec['candidate_name'] != 'ntp-static-' + spec['operation_id']
            or not re.fullmatch(r'[0-9a-f-]{36}',spec['original_uuid'])
            or not re.fullmatch(r'(?:[0-9a-f]{2}:){5}[0-9a-f]{2}',spec['mac'])
            or not 0 < spec['expires_epoch'] - spec['prepared_epoch'] <= 86400):
        raise ValueError('fixed bounded networking specification required')
    v4 = ipaddress.IPv4Interface(r['ipv4_address']); v6 = ipaddress.IPv6Interface(r['ipv6_address'])
    if (v4.ip in (v4.network.network_address,v4.network.broadcast_address)
            or ipaddress.IPv4Address(r['ipv4_gateway']) not in v4.network
            or ipaddress.IPv4Address(r['ipv4_dns']) not in v4.network
            or not v6.ip in ipaddress.IPv6Network('fc00::/7')
            or ipaddress.IPv6Address(r['ipv6_dns']) not in v6.network):
        raise ValueError('planned local dual-stack addresses required')


def identity(spec, caller=False):
    validate_spec(spec)
    if (os.geteuid() != 0 or os.getegid() != 0 or not sys.flags.isolated or not sys.dont_write_bytecode
            or socket.gethostname() != spec['hostname'] or os.uname().machine != 'aarch64'
            or os.uname().release != spec['kernel']
            or Path('/proc/sys/kernel/random/boot_id').read_text().strip() != spec['boot_id']
            or caller and (os.environ.get('SUDO_USER') != 'ama' or os.environ.get('SUDO_UID') != '1000' or os.environ.get('SUDO_GID') != '1000')):
        raise ValueError('approved isolated root target/boot/caller required')


class Transaction:
    def __init__(self, spec):
        self.spec = spec; self.root = Path(spec['stage']); self.r = spec['recipe']
        self.h = load(self.root/'foundation-install.py',spec['members']['foundation-install.py'])
        self.i = load(self.root/'inspect-source-destinations.py',spec['members']['inspect-source-destinations.py'])
        self.cm = load(self.root/'clockmaker.py',spec['members']['clockmaker.py'])
        self.baseline = json.loads(self.h.read(self.root/'baseline.json'))
        self.original = properties(self.baseline['queries']['ethernet_profiles'][spec['original_uuid']]['stdout'])

    def verify(self, files=None):
        self.h.ancestors(self.root)
        if stat.S_IMODE(self.root.stat().st_mode) != 0o700:
            raise ValueError('private root stage required')
        expected = set(self.spec['members']) | {'spec.json','manifest.json','state.json','.lock','before.json','state.json.new','before.json.new','commands.jsonl'}
        if not {p.name for p in self.root.iterdir()} <= expected:
            raise ValueError('unexpected stage entry; retain all evidence')
        if self.h.read(self.root/'spec.json') != encoded(self.spec):
            raise ValueError('network specification drift')
        if json.loads(self.h.read(self.root/'manifest.json'))!=self.spec['members']:
            raise ValueError('network member manifest drift')
        for path in self.root.iterdir():
            if stat.S_IMODE(path.lstat().st_mode)!=0o600:
                raise ValueError('root stage file modes must remain 0600')
            self.h.read(path,limit=(8 if path.name=='commands.jsonl' else 2)*1024**2)
        for name, digest in self.spec['members'].items():
            data = self.h.read(self.root/name, limit=2*1024**2)
            if sha(data) != digest or stat.S_IMODE((self.root/name).stat().st_mode) != 0o600:
                raise ValueError('sealed network member drift')
            if files is not None and data != files[name]:
                raise ValueError('submitted network member drift')

    def run(self, argv, allowed=(0,), timeout=15):
        executable=Path(argv[0]);self.h.ancestors(executable.parent)
        if executable.is_symlink() and (executable.lstat().st_uid or executable.lstat().st_gid):
            raise ValueError('protected executable alias required')
        self.h.read(executable.resolve(strict=True), unique=False)
        try:
            p = subprocess.run(argv, capture_output=True, timeout=timeout, check=False,
                env={'PATH':'/usr/sbin:/usr/bin:/sbin:/bin','LC_ALL':'C','SYSTEMD_PAGER':'','PAGER':'cat'})
        except subprocess.TimeoutExpired as error:
            p=subprocess.CompletedProcess(argv,-124,error.stdout or b'',error.stderr or b'')
        if len(p.stdout)>2*1024**2 or len(p.stderr)>65536:
            raise ValueError('network command stream bound exceeded')
        record=encoded({'argv':argv,'exit_status':p.returncode,'epoch':int(time.time()),
            'stdout_base64':base64.b64encode(p.stdout).decode(),'stderr_base64':base64.b64encode(p.stderr).decode()})
        fd=os.open(self.root/'commands.jsonl',os.O_WRONLY|os.O_CREAT|os.O_APPEND|os.O_NOFOLLOW,0o600)
        try:
            info=os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid!=self.h.OWNER or info.st_gid!=self.h.OWNER
                    or info.st_nlink!=1 or stat.S_IMODE(info.st_mode)!=0o600 or info.st_size+len(record)>8*1024**2):
                raise ValueError('protected bounded command journal required')
            while record:record=record[os.write(fd,record):]
            os.fsync(fd)
        finally:os.close(fd)
        if p.returncode not in allowed:
            raise ValueError('network command status '+str(p.returncode)+': '+repr(argv)[:250]+': '+p.stderr.decode(errors='replace')[:200])
        return p.stdout.decode()

    def write(self, name, value):
        path=self.root/name
        if path.exists(): self.h.read(path)
        temporary=self.root/(name+'.new')
        if temporary.exists():self.h.read(temporary);temporary.unlink()
        self.h.create(temporary, encoded(value));os.replace(temporary,path);self.h.sync(self.root)

    def state(self):
        return json.loads(self.h.read(self.root/'state.json'))

    def lock(self):
        fd=os.open(self.root/'.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=self.h.OWNER or info.st_gid!=self.h.OWNER or info.st_nlink!=1 or stat.S_IMODE(info.st_mode)!=0o600:
            os.close(fd);raise ValueError('protected transaction lock required')
        fcntl.flock(fd,fcntl.LOCK_EX)
        return os.fdopen(fd,'rb')

    def profile(self, uuid):
        return properties(self.run([NM,'-t','-f',GROUPS,'connection','show','uuid',uuid]))

    def registry(self):
        text=self.run([NM,'-t','-f','UUID,TYPE','connection','show'])
        lines=text.splitlines()
        if len(lines)>64 or len(lines)!=len(set(lines)):
            raise ValueError('bounded unique network registry required')
        result={}
        for line in lines:
            m=re.fullmatch(r'([a-f0-9-]{36}):([^:\s]+)',line)
            if not m or m[1] in result: raise ValueError('invalid network registry')
            result[m[1]]=m[2]
        return result

    def active_uuid(self):
        return self.run([NM,'-g','GENERAL.CON-UUID','device','show',self.r['interface']]).strip()

    def network(self):
        return {name:json.loads(self.run(['/usr/sbin/ip','-j',*args])) for name,args in
            (('addresses',['address','show','dev',self.r['interface']]),
             ('v4_routes',['-4','route','show']),('v6_routes',['-6','route','show']))}

    def resolver(self):
        path=Path('/etc/resolv.conf');self.h.ancestors(path.parent)
        info=path.lstat()
        if info.st_uid or info.st_gid:raise ValueError('root resolver configuration required')
        resolved=path.resolve(strict=True);data=self.h.read(resolved,limit=65536)
        servers=[]
        for line in data.decode().splitlines():
            fields=line.split()
            if fields and fields[0]=='nameserver':
                if len(fields)<2:raise ValueError('malformed resolver nameserver')
                servers.append(str(ipaddress.ip_address(fields[1])))
        if len(servers)!=2 or set(servers)!={self.r['ipv4_dns'],self.r['ipv6_dns']}:
            raise ValueError('direct resolver VIP view required; stub/other DNS needs separate review')
        return {'path':str(resolved),'sha256':sha(data),'nameservers':servers}

    def continuity(self):
        if self.i.observation()!=self.baseline['observation']:
            raise ValueError('package/service/boot/Python/process drift')
        if self.cm.inspect_install(self.root/'release.json',self.spec['members']['release.json'])!=self.baseline['installed_state']:
            raise ValueError('native release drift')
        for name,record in self.baseline['protected_files'].items():
            if name.startswith('/boot/firmware/'):
                try:data=self.h.read(Path(name),limit=256*1024)
                except FileNotFoundError:data=None
                if (data is None)!=(record is None) or data is not None and sha(data)!=record['sha256']:
                    raise ValueError('boot input drift')

    def preflight(self):
        self.continuity()
        if not self.spec['prepared_epoch']-300 <= time.time() < self.spec['expires_epoch']:
            raise ValueError('network apply window expired')
        if stable(self.profile(self.spec['original_uuid']))!=stable(self.original):
            raise ValueError('accepted Ethernet profile drift')
        expected=dict(line.split(':',1) for line in self.baseline['queries']['profile_registry']['stdout'].splitlines())
        if self.registry()!=expected or self.active_uuid()!=self.spec['original_uuid']:
            raise ValueError('network registry/active profile drift')
        if self.candidate({'candidate_uuid':None}) is not None:
            raise ValueError('operation candidate name already exists')
        net=self.network();addresses=net['addresses']
        if len(addresses)!=1 or addresses[0]['address'].lower()!=self.spec['mac']:
            raise ValueError('Ethernet MAC/interface drift')
        if not any(a['family']=='inet' and a['local']==self.spec['old_ipv4'] and a['prefixlen']==22
                   for a in addresses[0]['addr_info']):
            raise ValueError('bootstrap endpoint drift')
        if not any(r.get('dst')=='default' and r.get('gateway')==self.r['ipv4_gateway'] for r in net['v4_routes']):
            raise ValueError('bootstrap default route drift')
        arping=None
        for name in ('/usr/bin/arping','/usr/sbin/arping'):
            try:self.h.read(Path(name).resolve(strict=True),unique=False);arping=name;break
            except FileNotFoundError:pass
        if arping is None:raise ValueError('installed protected arping executable required')
        self.run([arping,'-D','-I',self.r['interface'],'-c','3','-w','5',self.r['ipv4_address'].split('/')[0]],timeout=10)
        return {'profile':self.original,'network':net,'registry':expected,'resolver':self.resolver()}

    def unit(self, kind):
        return 'ntp-network-'+kind+'-'+self.spec['operation_id']

    def arm(self):
        unit=self.unit('recovery')
        deadline=time.monotonic()+300
        self.run(['/usr/bin/systemd-run','--unit='+unit,'--on-active=300s','--timer-property=AccuracySec=1s',
            '--property=RuntimeMaxSec=120s','/usr/bin/python3','-I','-B',str(self.root/'host-network-stage.py'),
            '--root',str(self.root),'--mode','recover'])
        if self.run([SYSTEMCTL,'is-active',unit+'.timer']).strip()!='active':
            raise ValueError('recovery timer not active')
        state=self.state();state.update(phase='armed',deadline_monotonic=deadline)
        self.write('state.json',state)

    def candidate(self, state):
        uuid=state.get('candidate_uuid')
        if uuid: return uuid
        # Covers a crash after clone but before recording its allocated UUID.
        raw=self.run([NM,'-g','connection.uuid','connection','show','id',self.spec['candidate_name']],allowed=(0,10)).strip()
        if not raw: return None
        if not re.fullmatch(r'[a-f0-9-]{36}',raw) or raw==self.spec['original_uuid']:
            raise ValueError('ambiguous candidate identity')
        return raw

    def apply(self):
        with self.lock():
            self.verify()
            if self.state()['phase']!='staged': raise ValueError('network apply already consumed')
            try:
                self.write('before.json',self.preflight());self.arm()
                self.run([NM,'connection','clone','uuid',self.spec['original_uuid'],self.spec['candidate_name']])
                state=self.state();state['candidate_uuid']=self.candidate(state)
                if not state['candidate_uuid']: raise ValueError('clone UUID missing')
                self.write('state.json',state)
                clone=stable(self.original);clone.update({'connection.id':self.spec['candidate_name'],'connection.uuid':state['candidate_uuid']})
                observed=stable(self.profile(state['candidate_uuid']))
                if observed.get('connection.autoconnect') not in ('yes','no'):
                    raise ValueError('clone autoconnect state invalid')
                observed['connection.autoconnect']=clone['connection.autoconnect']
                if observed!=clone or stable(self.profile(self.spec['original_uuid']))!=stable(self.original):
                    raise ValueError('clone/original drift before candidate configuration')
                args=[NM,'connection','modify','uuid',state['candidate_uuid']]
                for key,value in settings(self.r).items(): args.extend([key,value])
                self.run(args)
                configured=stable(dict(clone,**settings(self.r)))
                if stable(self.profile(state['candidate_uuid']))!=configured or stable(self.profile(self.spec['original_uuid']))!=stable(self.original):
                    raise ValueError('candidate/original drift before activation')
                self.run([NM,'connection','modify','uuid',self.spec['original_uuid'],'connection.autoconnect','no'])
                self.run([NM,'--wait','45','connection','up','uuid',state['candidate_uuid'],'ifname',self.r['interface']],timeout=50)
                report=self.checks(state)
                state.update(phase='applied',checks=report);self.write('state.json',state)
            except BaseException as error:
                state=self.state();state.update(phase='apply_held',error=str(error)[:500]);self.write('state.json',state)
                raise

    def checks(self, state):
        self.continuity();uuid=state['candidate_uuid'];candidate=self.profile(uuid)
        desired=stable(dict(self.original,**settings(self.r)))
        desired.update({'connection.id':self.spec['candidate_name'],'connection.uuid':uuid})
        if stable(candidate)!=desired or self.active_uuid()!=uuid:
            raise ValueError('candidate profile/activation mismatch')
        original=stable(self.original);original['connection.autoconnect']='no'
        if stable(self.profile(self.spec['original_uuid']))!=original:
            raise ValueError('retained original profile drift')
        registry=json.loads(self.h.read(self.root/'before.json'))['registry'];registry[uuid]='802-3-ethernet'
        if self.registry()!=registry: raise ValueError('candidate registry drift')
        net=self.network();device=net['addresses']
        if len(device)!=1 or device[0]['address'].lower()!=self.spec['mac'] or 'UP' not in device[0]['flags']:
            raise ValueError('candidate link/MAC mismatch')
        addresses=device[0]['addr_info']
        for family,value in (('inet',self.r['ipv4_address']),('inet6',self.r['ipv6_address'])):
            address,prefix=value.split('/')
            if not any(a['family']==family and a['local']==address and a['prefixlen']==int(prefix)
                and not a.get('tentative') and not a.get('dadfailed') and not a.get('deprecated')
                and not set(a.get('flags',[])) & {'tentative','dadfailed','deprecated'} for a in addresses):
                raise ValueError('fixed address/DAD not ready')
        public=[a['local'] for a in addresses if a['family']=='inet6' and ipaddress.ip_address(a['local']).is_global
                and not a.get('tentative') and not a.get('dadfailed') and not a.get('deprecated')]
        if not public or not any(r.get('dst')=='default' and r.get('protocol')=='ra' and r.get('dev')==self.r['interface'] for r in net['v6_routes']):
            raise ValueError('IPv6 RA address/default route missing')
        if not any(r.get('dst')=='default' and r.get('gateway')==self.r['ipv4_gateway'] and r.get('dev')==self.r['interface'] for r in net['v4_routes']):
            raise ValueError('IPv4 default route missing')
        dns=self.run([NM,'-t','-f','IP4.DNS,IP6.DNS','device','show',self.r['interface']])
        values={l.split(':',1)[1] for l in dns.splitlines() if ':' in l and l.split(':',1)[1]}
        # nmcli escapes IPv6 colons in terse output.
        values={v.replace('\\:',':') for v in values}
        if values!={self.r['ipv4_dns'],self.r['ipv6_dns']}: raise ValueError('effective DNS VIP set mismatch')
        self.resolver()
        for family,source,destination in (('-4',self.r['ipv4_address'].split('/')[0],self.r['ipv4_dns']),
                ('-6',self.r['ipv6_address'].split('/')[0],self.r['ipv6_dns'])):
            routes=json.loads(self.run(['/usr/sbin/ip','-j',family,'route','get',destination,'from',source]))
            if not routes or any(r.get('dev')!=self.r['interface'] or source not in
                (r.get('from'),r.get('prefsrc'),r.get('src')) for r in routes):
                raise ValueError('source-specific DNS route mismatch')
            self.run(['/usr/bin/ping',family,'-I',source,'-c','1','-W','2',destination],timeout=5)
        for family,source in (('--ipv4',self.r['ipv4_address'].split('/')[0]),('--ipv6',public[0])):
            self.run(['/usr/bin/curl','--disable','--noproxy','*','--fail','--head','--silent','--show-error','--max-time','10',
                '--connect-timeout','5',family,'--interface',source,self.r['egress_url']],timeout=12)
        return dict.fromkeys(sorted(LABELS),True)

    def probe(self):
        state=self.state()
        if state['phase']!='applied': raise ValueError('applied candidate required for acceptance')
        checks=self.checks(state)
        return {'phase':'applied','hostname':self.spec['hostname'],'boot_id':self.spec['boot_id'],
            'spec_sha256':sha(encoded(self.spec)),'candidate_uuid':state['candidate_uuid'],
            'checks':checks,'remaining_seconds':state['deadline_monotonic']-time.monotonic()}

    def accept(self, proofs):
        with self.lock():
            state=self.state()
            if state['phase']!='applied' or state['deadline_monotonic']-time.monotonic()<=45:
                raise ValueError('acceptance deadline or phase held; leave recovery armed')
            expected={self.r['ipv4_address'].split('/')[0],self.r['ipv6_address'].split('/')[0]}
            if set(proofs)!=expected: raise ValueError('both new pinned SSH endpoints required')
            for endpoint,proof in proofs.items():
                if (proof['phase']!='applied' or proof['hostname']!=self.spec['hostname'] or proof['boot_id']!=self.spec['boot_id']
                        or proof['spec_sha256']!=sha(encoded(self.spec)) or proof['candidate_uuid']!=state['candidate_uuid']
                        or set(proof['checks'])!=LABELS or any(v is not True for v in proof['checks'].values())):
                    raise ValueError('bound dual-stack acceptance proof required')
            state['checks']=self.checks(state)
            if state['deadline_monotonic']-time.monotonic()<=45:
                raise ValueError('acceptance reserve exhausted; leave recovery armed')
            # Durable acceptance precedes cancellation: a crash cannot leave an uncommitted change with no timer.
            state.update(phase='accepted',ssh_proofs=proofs);self.write('state.json',state)
            self.run([SYSTEMCTL,'stop',self.unit('recovery')+'.timer'])
            return state

    def recover(self):
        with self.lock():
            self.verify();state=self.state()
            if state['phase'] in ('accepted','recovered'): return state
            try:
                current=stable(self.profile(self.spec['original_uuid']));expected=stable(self.original)
                current.pop('connection.autoconnect',None);expected.pop('connection.autoconnect',None)
                if current!=expected: raise ValueError('original profile drift; recovery held')
                uuid=self.candidate(state)
                if uuid:
                    candidate=self.profile(uuid)
                    if candidate.get('connection.id')!=self.spec['candidate_name'] or candidate.get('connection.uuid')!=uuid:
                        raise ValueError('candidate ownership ambiguous')
                    target=stable(dict(self.original,**settings(self.r)))
                    for key,value in stable(candidate).items():
                        if key in ('connection.id','connection.uuid'): continue
                        if key=='connection.autoconnect' and value in ('yes','no'):continue
                        if key not in target or value not in (self.original.get(key),target[key]):
                            raise ValueError('candidate changed outside transaction; retain for review')
                if uuid is None and self.active_uuid()==self.spec['original_uuid'] and stable(self.profile(self.spec['original_uuid']))==stable(self.original):
                    state['no_network_mutation_observed']=True
                else:
                    self.run([NM,'connection','modify','uuid',self.spec['original_uuid'],'connection.autoconnect',self.original['connection.autoconnect']])
                    self.run([NM,'--wait','45','connection','up','uuid',self.spec['original_uuid'],'ifname',self.r['interface']],timeout=50)
                if uuid: self.run([NM,'connection','delete','uuid',uuid])
                if stable(self.profile(self.spec['original_uuid']))!=stable(self.original) or self.active_uuid()!=self.spec['original_uuid']:
                    raise ValueError('original profile recovery incomplete')
                self.continuity()
                expected=dict(line.split(':',1) for line in self.baseline['queries']['profile_registry']['stdout'].splitlines())
                if self.registry()!=expected: raise ValueError('recovery registry mismatch')
                state.update(phase='recovered',network=self.network());self.write('state.json',state)
                self.run([SYSTEMCTL,'stop',self.unit('recovery')+'.timer'])
                return state
            except BaseException as error:
                state.update(phase='recovery_held',error=str(error)[:500]);self.write('state.json',state);raise

    def cleanup(self):
        with self.lock():
            self.verify();state=self.state()
            if state['phase'] not in ('accepted','recovered'): raise ValueError('terminal acceptance/recovery required')
            for kind,suffix in (('recovery','.timer'),('apply','.service')):
                unit=self.unit(kind)+suffix
                if self.run([SYSTEMCTL,'show','--property=LoadState','--value',unit]).strip()=='loaded':
                    self.run([SYSTEMCTL,'stop',unit]);self.run([SYSTEMCTL,'reset-failed',unit])
            state['transient_units_cleaned']=True;self.write('state.json',state)
            return state


def bootstrap(spec, files):
    identity(spec,caller=True)
    if (set(files)!=set(spec['members']) or any(sha(v)!=spec['members'][n] for n,v in files.items())
            or any(not re.fullmatch(r'[a-z][a-z0-9.-]+',name) for name in files)):
        raise ValueError('sealed network input binding required')
    root=Path(spec['stage']);ns={'__name__':'network_helper'}
    exec(compile(files['foundation-install.py'],'sealed-network-helper','exec'),ns)
    ns['ancestors'](root.parent);root.mkdir(mode=0o700);ns['sync'](root.parent)
    for name,data in {**files,'spec.json':encoded(spec),'manifest.json':encoded(spec['members']),
                      'state.json':encoded({'phase':'staged','candidate_uuid':None})}.items():
        if not re.fullmatch(r'[a-z][a-z0-9.-]+',name): raise ValueError('flat network inputs required')
        ns['create'](root/name,data)
    tx=Transaction(spec);tx.verify(files)
    tx.run(['/usr/bin/systemd-run','--unit='+tx.unit('apply'),'--collect','--property=RuntimeMaxSec=180s',
        '/usr/bin/python3','-I','-B',str(root/'host-network-stage.py'),'--root',str(root),'--mode','apply'])
    return {'phase':'submitted','hostname':spec['hostname'],'spec_sha256':sha(encoded(spec))}


def entry(spec, files, mode, proofs=None):
    if mode=='start': return bootstrap(spec,files)
    identity(spec,caller=True);tx=Transaction(spec);tx.verify(files)
    if mode=='probe': return tx.probe()
    if mode=='accept': return tx.accept(proofs)
    if mode=='readback': return tx.state()
    if mode=='recover': return tx.recover()
    if mode=='cleanup': return tx.cleanup()
    raise ValueError('closed network mode required')


def main():
    os.umask(0o077);p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,required=True);p.add_argument('--mode',choices=('apply','recover'),required=True)
    args=p.parse_args();spec=json.loads(protected_bytes(args.root/'spec.json'))
    if str(args.root)!=spec['stage']:raise ValueError('exact approved root stage required')
    identity(spec);tx=Transaction(spec);tx.verify()
    result=tx.apply() if args.mode=='apply' else tx.recover()
    print(json.dumps(result))


if __name__=='__main__':main()
