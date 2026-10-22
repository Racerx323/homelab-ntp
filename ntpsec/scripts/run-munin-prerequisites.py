#!/usr/bin/python3
"""Seal Munin inspections and a separately approved network-owned profile save."""
import argparse
import base64
import configparser
import gzip
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import signal
import socket
import tarfile
import time
import types

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {'runner.py': ROOT/'scripts/run-munin-prerequisites.py',
           'helper.py': ROOT/'scripts/run-production-inspection.py',
           'tests.py': ROOT/'tests/test_munin_prerequisites.py',
           'package-review.json': ROOT/'configs/munin-package-review.json',
           'package-qualification.md': ROOT.parent.parent/'homelab-monitoring-observability/Munin/docs/ntp-package-qualification.md',
           'profile-review.md': ROOT.parent.parent/'homelab-monitoring-observability/Munin/docs/ntp-monitoring-review.md'}
SOURCES['network-profile.py']=ROOT.parent.parent/'homelab-network/Ubiquiti/munin-master-profile/persist.py'
SOURCES['network-profile-tests.py']=ROOT.parent.parent/'homelab-network/Ubiquiti/munin-master-profile/test_persist.py'
SOURCES['network-readiness.py']=ROOT.parent.parent/'homelab-network/Ubiquiti/munin-master-profile/inspect.py'
SOURCES['network-readiness-tests.py']=ROOT.parent.parent/'homelab-network/Ubiquiti/munin-master-profile/test_inspect.py'
SOURCES['network-readiness-review.md']=ROOT.parent.parent/'homelab-network/Ubiquiti/svmf-static-network-review.md'
SOURCES['network-ipam.yaml']=ROOT.parent.parent/'homelab-network/ipam/hosts.yaml'
TARGETS = {'node-dependencies': ('10.1.0.51','ama','10.1.0.137'),
           'master': ('10.1.3.83','pi','svmf.local.theama.co'),
           'master-qualification': ('10.1.3.83','pi','svmf.local.theama.co'),
           'master-identity': ('10.1.3.83','pi','svmf.local.theama.co'),
           'master-persistence': ('10.1.3.83','pi','svmf.local.theama.co'),
           'master-profile-save': ('10.1.3.83','pi','svmf.local.theama.co'),
           'master-network-readiness': ('10.1.3.83','pi','svmf.local.theama.co'),
           'master-recovery-readiness': ('10.1.3.83','pi','svmf.local.theama.co')}
h = None
network = None
readiness = None


def properties(raw):
    result = {}
    for line in raw.splitlines():
        k,v = line.split('=',1)
        if k in result: raise ValueError('duplicate unit property')
        result[k] = v
    return result


def safe_url_text(text):
    # Cached repository metadata can contain authenticated URLs; export no userinfo/query.
    from urllib.parse import urlsplit, urlunsplit
    def redact(match):
        try:
            p = urlsplit(match[0]); host = p.hostname or ''
            if ':' in host: host = '['+host+']'
            if p.port: host += ':'+str(p.port)
            return urlunsplit((p.scheme,host,p.path,'',''))
        except ValueError:
            return '[URL omitted]'
    return re.sub(r'https?://[^\s<>]+',redact,text)


def configuration(path):
    """Hash one bounded regular file; retain structural/directive fields only."""
    if path.is_symlink() or any(p.is_symlink() for p in path.parents):
        return {'path':str(path),'indirect':True}
    record = h.file_record(path,content=True)
    if record.get('missing'): return {'path':str(path),'record':record}
    if record.get('error') or record.get('changed_during_read'):
        raise ValueError('unsafe configuration: '+str(path))
    raw = base64.b64decode(record.pop('base64'),validate=True)
    if len(raw) > 65536: raise ValueError('configuration size bound')
    rows = []
    for n,line in enumerate(raw.decode('utf-8',errors='replace').splitlines(),1):
        line = line.strip()
        if not line or line.startswith('#'): continue
        parts = line.split(None,1); key = parts[0]; value = parts[1] if len(parts)>1 else ''
        selected = None
        if line.startswith('[') and line.endswith(']') and re.fullmatch(r'[A-Za-z0-9_.;:\[\]-]+',line):
            selected = line
        elif key in ('includedir','include','address','port','use_node_name','update_rate','munin_user',
                     'dbdir','logdir','rundir','htmldir','contacts') and re.fullmatch(r'[A-Za-z0-9_./:\[\] -]+',value):
            selected = value
        elif key.endswith(('.warning','.critical','.unknown_limit')) and re.fullmatch(r'[0-9.:+-]+',value):
            selected = value
        rows.append({'line':n,'key':key,'value':selected if selected is not None else '[omitted]'})
    return {'path':str(path),'record':record,'directives':rows}


def master_configuration(root=Path('/etc/munin')):
    paths = {root/'munin.conf'}
    for name in ('munin-conf.d','munin.conf.d','conf.d'):
        p = root/name
        if p.is_symlink():
            paths.add(p)
        elif p.is_dir():
            paths.update(p.iterdir())
    if len(paths)>64: raise ValueError('master configuration count bound')
    result = [configuration(p) for p in sorted(paths)]
    # Include custom paths only as redacted configuration references, never recurse into them.
    return result


def cron_structure(raw):
    rows=[]
    for n,line in enumerate(raw.decode('utf-8',errors='replace').splitlines(),1):
        line=line.strip()
        if not line or line.startswith('#'):continue
        tokens=line.split(None,6)
        if len(tokens)==7 and all(re.fullmatch(r'[0-9*/,-]+',v) for v in tokens[:5]):
            command=tokens[6]
            paths=[p for p in ('/usr/bin/munin-cron','/usr/share/munin/munin-cron',
                              '/usr/share/munin/munin-limits') if p in command]
            rows.append({'line':n,'schedule':tokens[:5],'user':tokens[5],
                         'recognized_paths':paths,'command_omitted':True})
    return rows


def scheduler_sources(helper):
    result=[]
    for name in ('/usr/bin/munin-cron','/usr/share/munin/munin-cron',
                 '/usr/share/munin/munin-limits','/usr/share/perl5/Munin/Master/Limits.pm'):
        row=helper.file_record(name,content=True)
        if row.get('missing'):
            result.append({'path':name,'record':row});continue
        if row.get('error') or row.get('changed_during_read'):raise ValueError('scheduler source capture')
        raw=base64.b64decode(row.pop('base64'),validate=True)
        result.append({'path':name,'record':row,'markers':{
            'update_reference':bool(re.search(rb'\bupdate\b',raw)),
            'limits_reference':bool(re.search(rb'\blimits\b',raw)),
            'master_limits_module':b'Munin::Master::Limits' in raw,
            'contact_reference':bool(re.search(rb'\bcontacts?\b',raw))}})
    return result


def activity_summary(path):
    """Inspect only a bounded tail and export counts/timestamps, never log lines."""
    import stat
    if path.is_symlink() or any(p.is_symlink() for p in path.parents):
        return {'path':str(path),'indirect':True}
    try:
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    except FileNotFoundError:return {'path':str(path),'missing':True}
    with os.fdopen(fd,'rb') as stream:
        meta=os.fstat(stream.fileno())
        if not stat.S_ISREG(meta.st_mode):raise ValueError('regular activity log required')
        offset=max(0,meta.st_size-65536);stream.seek(offset);raw=stream.read(65536)
    if offset and b'\n' in raw:raw=raw.split(b'\n',1)[1]
    text=raw.decode('utf-8',errors='replace')
    stamps=re.findall(r'\b20\d\d[-/]\d\d[-/]\d\d[- T]\d\d:\d\d:\d\d\b',text)
    return {'path':str(path),'bytes':meta.st_size,'mtime':meta.st_mtime,'tail_bytes':len(raw),
            'first_timestamp':stamps[0] if stamps else None,'last_timestamp':stamps[-1] if stamps else None,
            'start_markers':len(re.findall(r'Starting munin-(?:update|limits)',text,re.I)),
            'finish_markers':len(re.findall(r'munin-(?:update|limits) finished',text,re.I)),
            'error_marker_count':len(re.findall(r'\b(?:ERROR|FATAL)\b',text)),
            'raw_lines_omitted':True,'delivery_accepted':False}


def stable_id_features(value):
    return {'unset':value.strip() in ('','--'),
            'boot_dependent':'${BOOT}' in value,
            'random_dependent':'${RANDOM}' in value,
            'literal_omitted':True}


def nm_policy(raw):
    """Export only address-policy fields; never arbitrary NetworkManager config."""
    section='';rows=[]
    allowed={'match-device','stop-match','ipv6.addr-gen-mode','ipv6.ip6-privacy'}
    for line in raw.splitlines():
        line=line.strip()
        if line.startswith('[') and line.endswith(']'):section=line[1:-1]
        elif section.startswith(('connection','device')) and '=' in line and not line.startswith(('#',';')):
            key,value=map(str.strip,line.split('=',1))
            if key in allowed:rows.append({'section':section,'key':key,'value':value})
            elif key=='connection.stable-id':rows.append({'section':section,'key':key,'features':stable_id_features(value)})
    return rows


def saved_profile(path,uuid):
    p=Path(path)
    if p.parent!=Path('/etc/NetworkManager/system-connections'):
        raise ValueError('persistent system profile path required')
    for parent in p.parents:
        if parent.is_symlink():raise ValueError('profile symlink ancestor')
    row=h.file_record(p,content=True)
    if row.get('error') or row.get('missing') or row.get('changed_during_read'):
        raise ValueError('saved profile unavailable or changed')
    if row['uid']!=0 or row['mode']&0o077:raise ValueError('root-private saved profile required')
    parser=configparser.ConfigParser(interpolation=None)
    try:parser.read_string(base64.b64decode(row.pop('base64'),validate=True).decode())
    except Exception:raise ValueError('saved profile parse failed') from None
    if parser.get('connection','uuid',fallback=None)!=uuid:raise ValueError('saved profile UUID mismatch')
    fields={}
    for section,keys in {'connection':('uuid','interface-name','type','autoconnect'),
                         'ipv6':('method','addr-gen-mode','ip6-privacy','token')}.items():
        fields[section]={key:parser.get(section,key,fallback=None) for key in keys}
    fields['stable_id']=stable_id_features(parser.get('connection','stable-id',fallback=''))
    # The content hash and raw profile could cover credentials; export neither.
    row.pop('sha256',None)
    return {'path':str(p),'metadata':row,'fields':fields,'raw_profile_omitted':True}


def installed_nm_docs():
    result=[]
    for name in ('man5/nm-settings-nmcli.5.gz','man5/nm-settings.5.gz',
                 'man5/NetworkManager.conf.5.gz','man8/NetworkManager.8.gz'):
        p=Path('/usr/share/man')/name
        if not p.exists():result.append({'path':str(p),'missing':True});continue
        if p.is_symlink() or any(parent.is_symlink() for parent in p.parents):
            result.append({'path':str(p),'indirect':True});continue
        if p.stat().st_size>1048576:raise ValueError('manual size bound')
        with gzip.open(p,'rb') as stream:raw=stream.read(4*1048576+1)
        if len(raw)>4*1048576:raise ValueError('expanded manual size bound')
        lines=raw.decode(errors='replace').splitlines();indexes=set()
        for i,line in enumerate(lines):
            if any(term in line for term in ('addr-gen-mode','addr\\-gen\\-mode','stable-id','stable\\-id','secret_key')):
                indexes.update(range(max(0,i-2),min(len(lines),i+24)))
        excerpt='\n'.join(lines[i] for i in sorted(indexes))[:16000]
        result.append({'path':str(p),'expanded_sha256':h.sha(raw),'policy_excerpt':excerpt})
    return result


def collect_master_qualification(spec):
    result={'operation_id':spec['operation_id'],'spec_sha256':h.sha(h.encoded(spec)),
            'capture_complete':False,'commands':{},'polling_accepted':False,'delivery_verified':False}
    def cmd(key,argv,allowed=(0,)):
        row=h.bounded(argv,timeout=20,env={'PATH':'/usr/sbin:/usr/bin:/sbin:/bin','LC_ALL':'C'})
        for field in ('stdout','stderr'):row[field]=safe_url_text(row.get(field,''))
        result['commands'][key]=row
        if row.get('error') or row.get('returncode') not in allowed:raise ValueError('command capture failed: '+key)
        return row['stdout']
    def continuity():
        if (os.geteuid()!=0 or socket.gethostname()!=spec['hostname']
                or Path('/proc/sys/kernel/random/boot_id').read_text().strip()!=spec['boot_id']):
            raise ValueError('master root/host/boot identity changed')
    try:
        continuity()
        ip=next((p for p in ('/usr/sbin/ip','/usr/bin/ip') if Path(p).is_file()),None)
        if not ip:raise ValueError('ip utility unavailable')
        cmd('route_ipv4',[ip,'-json','route','get','10.1.0.51'],(0,2))
        cmd('route_ipv6',[ip,'-6','-json','route','get','fd36:5aa8:6971:1::51'],(0,2))
        cmd('address_details',[ip,'-details','-json','address','show','dev','eth0'])
        cmd('network_services',['/usr/bin/systemctl','show','NetworkManager.service','systemd-networkd.service','dhcpcd.service',
                                '--property=LoadState,ActiveState,SubState,UnitFileState'])
        nm=next((p for p in ('/usr/bin/nmcli','/usr/sbin/nmcli') if Path(p).is_file()),None)
        if nm:
            profiles=cmd('nm_active',[nm,'-t','-f','UUID,DEVICE','connection','show','--active'],(0,10))
            ids=[]
            for line in profiles.splitlines():
                uuid,sep,device=line.partition(':')
                if sep and device=='eth0' and re.fullmatch(r'[0-9a-fA-F-]{36}',uuid):ids.append(uuid)
            if len(ids)>1:raise ValueError('multiple eth0 profiles')
            if ids:
                cmd('nm_eth0',[nm,'-f','connection.id,connection.uuid,connection.interface-name,ipv4.method,ipv4.addresses,ipv6.method,ipv6.addresses,ipv6.addr-gen-mode,ipv6.ip6-privacy',
                               'connection','show',ids[0]])
        else:result['networkmanager_profile_unavailable']=True
        result['ipv6_policy']={}
        for name in ('addr_gen_mode','use_tempaddr'):
            p=Path('/proc/sys/net/ipv6/conf/eth0')/name
            if p.is_file():result['ipv6_policy'][name]=p.read_text().strip()
        if spec['mode'] in ('master-identity','master-persistence'):
            if nm and ids:
                row=h.bounded([nm,'-g','connection.stable-id','connection','show',ids[0]],timeout=20,
                              env={'PATH':'/usr/sbin:/usr/bin:/sbin:/bin','LC_ALL':'C'})
                if row.get('error') or row.get('returncode')!=0:raise ValueError('stable-id query failed')
                result['stable_id']=stable_id_features(row['stdout'])
            manager=next((p for p in ('/usr/sbin/NetworkManager','/usr/bin/NetworkManager') if Path(p).is_file()),None)
            if manager:
                row=h.bounded([manager,'--print-config'],timeout=20,
                              env={'PATH':'/usr/sbin:/usr/bin:/sbin:/bin','LC_ALL':'C'})
                if row.get('error') or row.get('returncode')!=0:raise ValueError('effective NM policy query failed')
                result['effective_nm_policy']=nm_policy(row['stdout'])
            else:result['effective_nm_policy_unavailable']=True
            # Presence/ownership only: do not open or hash the host secret or machine ID.
            result['identity_file_metadata']=[]
            for name in ('/var/lib/NetworkManager/secret_key','/etc/machine-id'):
                p=Path(name)
                try:
                    info=p.lstat()
                    result['identity_file_metadata'].append({'path':name,'mode':info.st_mode,
                        'uid':info.st_uid,'gid':info.st_gid,'size':info.st_size,'mtime':info.st_mtime,
                        'indirect':p.is_symlink()})
                except FileNotFoundError:result['identity_file_metadata'].append({'path':name,'missing':True})
            if spec['mode']=='master-persistence':
                if not nm or len(ids)!=1:raise ValueError('one active eth0 profile required')
                cmd('nm_version',[nm,'--version'])
                cmd('nm_packages',['/usr/bin/dpkg-query','-W','-f=${binary:Package}\t${Version}\n','network-manager','libnm0'])
                row=h.bounded([nm,'-t','-f','UUID,FILENAME','connection','show'],timeout=20,
                              env={'PATH':'/usr/sbin:/usr/bin:/sbin:/bin','LC_ALL':'C'})
                if row.get('error') or row.get('returncode')!=0:raise ValueError('profile filename query unsupported')
                matches=[line.partition(':')[2] for line in row['stdout'].splitlines() if line.partition(':')[0]==ids[0]]
                if len(matches)!=1:raise ValueError('saved profile selection ambiguous')
                result['selected_profile_filename']=matches[0]
                try:result['saved_profile']=saved_profile(matches[0],ids[0])
                except ValueError as error:result['saved_profile_gap']=str(error)
                result['installed_nm_docs']=installed_nm_docs()
                result['reboot_or_renewal_exercised']=False
            result['persistence_accepted']=False
            continuity();result['capture_complete']=True
            return result
        row=h.file_record('/etc/cron.d/munin',content=True)
        if row.get('error') or row.get('missing') or row.get('changed_during_read'):raise ValueError('cron input unavailable')
        raw=base64.b64decode(row.pop('base64'),validate=True)
        result['cron']={'record':row,'jobs':cron_structure(raw)}
        result['scheduler_sources']=scheduler_sources(h)
        result['activity']=[activity_summary(Path(p)) for p in ('/var/log/munin/munin-update.log','/var/log/munin/munin-limits.log')]
        result['configuration']=master_configuration()
        continuity();result['capture_complete']=True
    except Exception as error:result['error']=str(error)
    return result


def collect(spec):
    if spec.get('mode')=='master-recovery-readiness':return readiness.collect_recovery(spec,h)
    if spec.get('mode')=='master-network-readiness':return readiness.collect(spec,h)
    if spec.get('mode')=='master-profile-save':return network.apply(spec,h)
    if spec.get('mode') in ('master-qualification','master-identity','master-persistence'):return collect_master_qualification(spec)
    result = {'operation_id':spec['operation_id'],'spec_sha256':h.sha(h.encoded(spec)),
              'capture_complete':False,'commands':{},'deployment_accepted':False,
              'polling_accepted':False,'delivery_verified':False,'dependencies_accepted':False}
    def cmd(key,argv,allowed=(0,)):
        row = h.bounded(argv,timeout=30,env={'PATH':'/usr/sbin:/usr/bin:/sbin:/bin','LC_ALL':'C'})
        for field in ('stdout','stderr'): row[field] = safe_url_text(row.get(field,''))
        result['commands'][key] = row
        if row.get('error') or row.get('returncode') not in allowed:
            raise ValueError('command capture failed: '+key)
        return row['stdout']
    def continuity(label):
        boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        if boot != result['boot_before']: raise ValueError('boot changed during capture')
        if spec['mode']=='node-dependencies':
            raw = cmd(label,['/usr/bin/systemctl','show','timeservice.service',
                            '--property=LoadState,MainPID,InvocationID,NRestarts,ActiveState,SubState,UnitFileState'])
            if boot != spec['boot_id'] or properties(raw) != spec['service_identity']:
                raise ValueError('accepted node boot/NTP identity changed')
    try:
        if os.geteuid()!=0: raise ValueError('root required')
        result['hostname'] = socket.gethostname()
        if spec['mode']=='node-dependencies' and result['hostname'].split('.')[0]!='j2-svntp1':
            raise ValueError('node hostname mismatch')
        result['boot_before'] = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        continuity('ntp_before')
        cmd('architecture',['/usr/bin/dpkg','--print-architecture'])
        cmd('installed',['/usr/bin/dpkg-query','-W','-f=${binary:Package}\t${Version}\t${db:Status-Abbrev}\n',
                         'munin','munin-node','munin-plugins-core','munin-plugins-extra','perl','libnet-cidr-perl'],(0,1))
        if spec['mode']=='node-dependencies':
            cmd('policy',['/usr/bin/apt-cache','-o','Dir::Cache::pkgcache=','-o','Dir::Cache::srcpkgcache=','policy','munin-node','munin-plugins-core','munin-plugins-extra'])
            cmd('candidate_metadata',['/usr/bin/apt-cache','-o','Dir::Cache::pkgcache=','-o','Dir::Cache::srcpkgcache=','show','--no-all-versions','munin-node','munin-plugins-core'],(0,100))
            cmd('dependencies',['/usr/bin/apt-cache','-o','Dir::Cache::pkgcache=','-o','Dir::Cache::srcpkgcache=','depends','munin-node','munin-plugins-core'],(0,100))
            cmd('simulation',['/usr/bin/apt-get','-o','Dir::Cache::pkgcache=','-o','Dir::Cache::srcpkgcache=','--simulate','--no-install-recommends','install','munin-node','munin-plugins-core'],(0,100))
            lists = Path('/var/lib/apt/lists')
            result['apt_cache'] = []
            if lists.is_dir() and not lists.is_symlink():
                entries=list(lists.iterdir())
                if len(entries)>512:raise ValueError('APT list count bound')
                for p in sorted(entries):
                    if p.is_file() and not p.is_symlink():
                        m=p.stat();result['apt_cache'].append({'name':p.name,'bytes':m.st_size,'mtime':m.st_mtime})
            result['node_service'] = cmd('node_service',['/usr/bin/systemctl','show','munin-node.service',
                                      '--property=LoadState,ActiveState,SubState,UnitFileState'])
        else:
            result['configuration'] = master_configuration()
            cmd('master_units',['/usr/bin/systemctl','show','munin.service','munin.timer','munin-node.service',
                               '--property=LoadState,ActiveState,SubState,UnitFileState,FragmentPath,DropInPaths'])
            cmd('timers',['/usr/bin/systemctl','list-timers','--all','--no-pager'])
            result['cron'] = configuration(Path('/etc/cron.d/munin'))
            ip = next((p for p in ('/usr/sbin/ip','/usr/bin/ip') if Path(p).is_file()),None)
            if ip:cmd('interface_addresses',[ip,'-json','address','show'])
            else:result['interface_addresses_unavailable']=True
            cmd('munin_packages_files',['/usr/bin/dpkg-query','-L','munin'],(0,1))
            result['path_metadata'] = {p:h.file_record(p) for p in ('/usr/bin/munin-cron','/usr/share/munin/munin-update',
                                       '/usr/share/munin/munin-limits')}
        continuity('ntp_after')
        result['boot_after']=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        if result['boot_after']!=result['boot_before']:raise ValueError('boot changed')
        result['capture_complete']=True
    except Exception as error:
        result['error']=str(error)
    return result


def review(spec):
    if spec['mode'] in ('master-network-readiness','master-recovery-readiness'):return readiness.review(spec)
    if spec['mode']=='master-profile-save':return network.review(spec)
    scope = '''Node dependency scope: require the accepted j2 boot/NTP identity before/after.
Read cached APT candidates, policy, metadata/dependencies and list-file age metadata.
Simulate only munin-node plus munin-plugins-core with --no-install-recommends.
Disable APT on-disk package-cache generation. No refresh, download, installation,
plugin autoconfiguration or script execution.
APT simulation status 100/candidate errors are retained findings, not permission
to repair or refresh the cache. Review removals/upgrades and competing time-daemon
risk before selecting exact versions and a package installation bundle.'''
    if spec['mode']=='master':
        scope = '''Native-master scope, confirmed by the operator: /etc/munin/munin.conf.
Record host/boot identity, architecture, installed Munin packages, unit/timer state,
cron configuration structure and candidate local interface addresses. Inspect at
most 64 regular configuration files from that file and immediate munin-conf.d,
munin.conf.d or conf.d entries, 64 KiB each. Skip/report symlinks; do not recurse
into arbitrary includes. Retain node headings, plain address/port/include paths,
selected scheduling/limit fields and contact key presence. Omit all contact command
bodies, URLs, credential/environment values and other configuration values.
Record executable hashes and package-file listing; no log contents, plugin runs,
munin-update, munin-limits, node queries, route probes or notification tests.
Interface addresses are source candidates, not proof of the address used to reach
j2. Unknown includes and effective scheduler/contact behavior remain explicit gaps.
Require unchanged boot during capture; no prior master boot acceptance is assumed.'''
    if spec['mode']=='master-qualification':
        scope = '''Master routing/scheduler qualification: require the accepted master hostname
and boot from its completed native inspection. Read local IPv4/IPv6 route lookups
to fixed j2 addresses (10.1.0.51 and fd36:5aa8:6971:1::51) via ip route get;
these are kernel queries, not probes or connections. Record detailed eth0 address
lifetimes/flags and local IPv6 generation/privacy sysctls. If NetworkManager is
present, query only active eth0 UUID and explicit connection identity/address/
generation/privacy fields, never secrets. Do not infer persistence from a route
snapshot; unsupported network management or profile details remain gaps.

Parse /etc/cron.d/munin into schedule/user and recognized munin-cron/limits paths;
omit complete command bodies. Hash bounded known scheduler sources and report only
update/limits/contact references. Read at most the last 64 KiB of each fixed
munin-update.log and munin-limits.log, exporting only timestamp/start/finish/error
counts. No raw log lines, contact commands or URLs are retained. Repeat redacted
native configuration inspection (64 files, 64 KiB each) to identify applicable
contact/limit presence.
Log timestamps/markers do not establish alert delivery or polling of absent j2.

No DNS, route mutation, packet probe, node fetch, plugin run, munin-update/limits
execution, notification or network configuration change. Do not force a reboot
to prove address stability. Record remaining stability/alert gaps explicitly.'''
    if spec['mode'] in ('master-identity','master-persistence'):
        scope = '''Master source-identity follow-up: require the accepted native master hostname
and boot before/after. Repeat only local eth0 IPv4/IPv6 route, address, service,
active-profile and generation/privacy queries from the routing qualification.
Read connection.stable-id in memory and export only unset/BOOT/RANDOM flags.
Run NetworkManager --print-config in memory, retaining only connection/device
section match-device, stop-match, IPv6 address-generation/privacy fields and
stable-id dependency flags. Never retain complete output or stderr. Stat only
/var/lib/NetworkManager/secret_key and /etc/machine-id; never open/hash their
contents. Missing effective policy remains an explicit gap.

No scheduler/log/Munin-configuration inspection, secret retrieval, DHCP renewal,
profile activation, reload, restart, reboot, packet probe or network mutation.
This snapshot alone cannot prove renewal/reboot persistence. Correlate it with
network-owner proof of the existing IPv4 reservation and ULA prefix policy;
preserve current networking. No controller access is part of this SSH stage.'''
        if spec['mode']=='master-persistence':
            scope+='''

Also read nmcli/package versions and UUID,FILENAME connection listing in memory.
Retain the active eth0 UUID's selected filename before evaluating it. Select
only its saved profile file, requiring a regular
root-private file directly under /etc/NetworkManager/system-connections with no
symlink ancestors. Retain only connection UUID/type/interface/autoconnect,
IPv6 method/generation/privacy/token and stable-id dependency flags plus file
metadata. Do not retain its raw bytes, content hash, other profile data or secrets.
Read bounded fixed installed NetworkManager/settings/conf manual pages and
export only public policy excerpts and document hashes. Unsupported filename
fields, missing docs, UUID drift or runtime-only profiles remain explicit gaps.
Do not require a filename suffix. If its storage path is outside the permitted
directory, record that path and gap without opening it, and still collect the
listed installed manual/version evidence. Do not infer a saved profile exists.

This qualifies saved deterministic policy if evidence matches; it does not
exercise renewal/reboot. Keep empirical confirmation in the observation register.
No reload, renewal, activation, reboot, profile write or controller request.'''
    host,user,alias=TARGETS[spec['mode']]
    return f'''# Read-only Munin {spec['mode']} review

Operation {spec['operation_id']}; expires epoch {spec['expires_epoch']}.
Target {user}@{host}, pinned Ed25519 host-key alias {alias}.
Master role: svmf.local.theama.co; node role: j2-svntp1.

{scope}

Read installed package/architecture metadata. Hash/redact configuration safely;
retain no raw master config or contact command. Commands bounded to 30 seconds
and 1 MiB; remote deadline 240 seconds, SSH 270 seconds and 16 MiB per stream.
Report missing packages, unresolved sources, simulation errors and partial failures.
A complete capture does not accept dependencies, a profile, alerts or polling.

The bundled profile-review.md is a review draft owned by the Munin repository.
It proposes baseline/storage/time-health/statistics/job-health measurements,
minimal privilege and the approved 10 GiB/5 percent free-inode floors. It is not
a deployable plugin list, inventory assignment or master registration.

One pinned-key SSH/sudo Python transaction through stdin, with no target staging.
No package refresh/download/install, service/container action, file mutation,
plugin execution, peer contact, SMTP or notification. Normal access/audit metadata
may change; no persistent mutation needs rollback. A single-use receipt prevents
blind replay. Before/after identity failures remain unaccepted; no automatic retry.

After execution approval bound to sealing.json's archive SHA-256:

```text
python3 -I -B ntpsec/scripts/run-munin-prerequisites.py execute --directory OUTPUT --sha256 APPROVED_SHA256
```

OUTPUT is this review directory. Node and master are separate approved stages.
After findings, select exact packages/plugins and source-address/access/alert
scope, then prepare separate node installation and master registration/acceptance.
'''


def seal(args):
    d=args.baseline
    receipt=json.loads(h.private(d/'result.json'));raw=h.private(d/'stdout.txt',16*h.LIMIT);capture=json.loads(raw)
    archive_raw=h.private(d/'inspection.tar',8*h.LIMIT)
    if (receipt.get('capture_complete') is not True or receipt.get('returncode')!=0 or receipt.get('error')
            or capture.get('capture_complete') is not True or capture.get('error')
            or receipt.get('bundle_sha256')!=h.sha(archive_raw)):
        raise ValueError('complete bound inspection baseline required')
    with tarfile.open(fileobj=io.BytesIO(archive_raw)) as archive:
        old=json.loads(archive.extractfile('spec.json').read());known=archive.extractfile('known_hosts').read()
    if capture['operation_id']!=old['operation_id'] or capture['spec_sha256']!=h.sha(h.encoded(old)):
        raise ValueError('baseline binding')
    endpoint,user,alias=TARGETS[args.mode]
    now=int(time.time())
    spec={'mode':args.mode,'endpoint':endpoint,'user':user,'host_key_alias':alias,'operation_id':args.output.name,
          'prepared_epoch':now,'expires_epoch':now+86400,'baseline_bundle_sha256':h.sha(archive_raw),
          'baseline_capture_sha256':h.sha(raw)}
    if args.mode=='node-dependencies':
        if old.get('monitoring') is not True:raise ValueError('monitoring baseline required')
        spec.update(boot_id=old['boot_id'],service_identity=old['service_identity'])
    elif (old.get('endpoint'),old.get('user'),old.get('host_key_alias')) != TARGETS['master']:
        raise ValueError('master SSH identity baseline mismatch')
    if args.mode=='master-profile-save':
        if old.get('mode')!='master-persistence' or capture.get('selected_profile_filename')!='/run/NetworkManager/system-connections/Wired connection 1.nmconnection':
            raise ValueError('observed runtime profile baseline required')
        spec.update(hostname=old['hostname'],boot_id=old['boot_id'])
    if args.mode=='master-network-readiness':
        if old.get('mode')!='master-profile-save' or capture.get('persisted') is not True or capture.get('running_network_unchanged') is not True:
            raise ValueError('accepted persistent profile-save baseline required')
        spec.update(hostname=old['hostname'],boot_id=old['boot_id'])
    if args.mode=='master-recovery-readiness':
        if old.get('mode')!='master-network-readiness' or capture.get('target_mutation') is not False:
            raise ValueError('completed read-only network readiness baseline required')
        spec.update(hostname=old['hostname'],boot_id=old['boot_id'])
    if args.mode in ('master-qualification','master-identity','master-persistence'):
        if old.get('mode')!='master':raise ValueError('native master inspection baseline required')
        spec.update(hostname=capture['hostname'],boot_id=capture['boot_after'])
    files={n:p.read_bytes() for n,p in SOURCES.items()};files['known_hosts']=known
    spec['members']={n:h.sha(v) for n,v in files.items()}
    files.update({'spec.json':h.encoded(spec),'review.md':review(spec).encode()})
    os.umask(0o077);args.output.mkdir(mode=0o700)
    for n,v in files.items():(args.output/n).write_bytes(v)
    with tarfile.open(args.output/'inspection.tar','w') as t:
        for n,v in sorted(files.items()):
            m=tarfile.TarInfo(n);m.size=len(v);m.mode=0o600;t.addfile(m,io.BytesIO(v))
    digest=h.sha((args.output/'inspection.tar').read_bytes());prepare(args.output,digest)
    result={'sha256':digest,'target_contact':False,'expires_epoch':spec['expires_epoch']}
    (args.output/'sealing.json').write_bytes(h.encoded(result));return result


def prepare(d,digest):
    raw=h.private(d/'inspection.tar',8*h.LIMIT)
    if h.sha(raw)!=digest:raise ValueError('archive mismatch')
    with tarfile.open(fileobj=io.BytesIO(raw)) as t:
        members=t.getmembers();expected=set(SOURCES)|{'known_hosts','spec.json','review.md'}
        if len(members)!=len(expected) or {m.name for m in members}!=expected or any(not m.isfile() or m.size>h.LIMIT for m in members):
            raise ValueError('closed flat archive required')
        files={m.name:t.extractfile(m).read() for m in members}
    spec=json.loads(files['spec.json'])
    if (spec['mode'] not in TARGETS or (spec['endpoint'],spec['user'],spec['host_key_alias'])!=TARGETS[spec['mode']]
            or not re.fullmatch(r'[a-z][a-z0-9-]{0,63}',spec['operation_id'])
            or not 0<spec['expires_epoch']-spec['prepared_epoch']<=86400
            or not spec['prepared_epoch']-300<=time.time()<spec['expires_epoch']-270
            or spec['members']!={n:h.sha(files[n]) for n in set(SOURCES)|{'known_hosts'}}
            or files['review.md']!=review(spec).encode()):raise ValueError('scope/window/member binding')
    for n,p in SOURCES.items():
        if files[n]!=p.read_bytes():raise ValueError('source drift: '+n)
    for n in ('known_hosts','spec.json','review.md'):
        if h.private(d/n)!=files[n]:raise ValueError('approval input drift')
    return spec,files


def execute(args):
    os.umask(0o077);d=args.directory.absolute();spec,files=prepare(d,args.sha256)
    payload=(b"__name__='sealed_munin'\n__file__='/sealed/runner.py'\n"+files['runner.py']
             +b"\nns={'__name__':'helper','__file__':'/sealed/helper.py'}\nexec("+repr(files['helper.py']).encode()
             +b",ns)\nh=types.SimpleNamespace(**ns)\nnnet={'__name__':'network_profile','__file__':'/sealed/network-profile.py'}\nexec("
             +repr(files['network-profile.py']).encode()+b",nnet)\nnetwork=types.SimpleNamespace(**nnet)\nnready={'__name__':'network_readiness','__file__':'/sealed/network-readiness.py'}\nexec("
             +repr(files['network-readiness.py']).encode()+b",nready)\nreadiness=types.SimpleNamespace(**nready)\nsignal.signal(signal.SIGALRM,h.expired)\nsignal.alarm(240)\nprint(json.dumps(collect("
             +repr(spec).encode()+b")))\n")
    argv=h.ssh_argv({'endpoints':[spec['endpoint']],'host_key_alias':spec['host_key_alias']},d)
    argv[-2]=spec['user']+'@'+spec['endpoint']
    with (d/'execution.json').open('xb') as f:
        f.write(h.encoded({'sha256':args.sha256,'payload_sha256':h.sha(payload),'argv':argv,'epoch':int(time.time())}));f.flush();os.fsync(f.fileno())
    result=h.bounded(argv,timeout=270,limit=16*h.LIMIT,payload=payload,env=os.environ.copy())
    for n in ('stdout','stderr'):(d/(n+'.txt')).write_text(result.pop(n))
    result.update(bundle_sha256=args.sha256,capture_complete=False)
    if result.get('returncode')==0 and not result.get('error'):
        try:
            state=json.loads((d/'stdout.txt').read_text())
            if state['operation_id']!=spec['operation_id'] or state['spec_sha256']!=h.sha(h.encoded(spec)):raise ValueError('capture binding')
            result['capture_complete']=state.get('capture_complete') is True
        except (ValueError,KeyError,TypeError) as error:result['error']=str(error)
    (d/'result.json').write_bytes(h.encoded(result));return result


def main():
    global h,network,readiness
    s=importlib.util.spec_from_file_location('helper',SOURCES['helper.py']);h=importlib.util.module_from_spec(s);s.loader.exec_module(h)
    s=importlib.util.spec_from_file_location('network_profile',SOURCES['network-profile.py']);network=importlib.util.module_from_spec(s);s.loader.exec_module(network)
    s=importlib.util.spec_from_file_location('network_readiness',SOURCES['network-readiness.py']);readiness=importlib.util.module_from_spec(s);s.loader.exec_module(readiness)
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='action',required=True)
    a=sub.add_parser('seal');a.add_argument('--mode',choices=TARGETS,required=True);a.add_argument('--baseline',type=Path,required=True);a.add_argument('--output',type=Path,required=True)
    a=sub.add_parser('execute');a.add_argument('--directory',type=Path,required=True);a.add_argument('--sha256',required=True)
    args=p.parse_args();result=seal(args) if args.action=='seal' else execute(args);print(json.dumps(result))
    if args.action=='execute' and not result['capture_complete']:raise SystemExit(1)


if __name__=='__main__':main()
