#!/usr/bin/python3
"""Isolated signed metadata and whole-installed-system simulation; never install."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import sys
import time
from urllib.parse import urlsplit

f = m = None  # Frozen repository resolver primitives and maintenance read helpers.
KEYS = ('/usr/share/keyrings/debian-archive-keyring.pgp',
        '/usr/share/keyrings/raspberrypi-archive-keyring.pgp',
        '/usr/share/keyrings/webmin-reviewed.gpg')
SOURCES = ('/etc/apt/sources.list.d/debian.sources', '/etc/apt/sources.list.d/raspi.sources',
           '/etc/apt/sources.list.d/webmin-reviewed.list')
PIN = '/etc/apt/preferences.d/webmin-reviewed'
FIRMWARE = ('rpi-eeprom', 'raspi-firmware', 'raspberrypi-bootloader', 'raspberrypi-kernel')


def require(ok, message):
    if not ok:
        raise ValueError(message)


def configuration(work, foreign, sandbox='_apt'):
    _, values = f.apt_configuration(work, foreign)
    values.update({'Dir::Etc::preferences': str(work/'preferences'),
                   'Dir::Etc::netrc': str(work/'no-auth'), 'Dir::Etc::netrcparts': str(work/'empty'),
                   'Acquire::GzipIndexes': 'false', 'Acquire::IndexTargets::deb::DEP-11::DefaultEnabled': 'false',
                   'Acquire::IndexTargets::deb::CNF::DefaultEnabled': 'false',
                   'APT::Sandbox::User': sandbox})
    # A fresh process and cleared config prevent implicit live hooks/credentials.
    text = ''.join(k+' '+json.dumps(v)+';\n' for k,v in values.items())
    text += '#clear APT::Architectures;\nAPT::Architectures { '+''.join(json.dumps(a)+';' for a in ['arm64',*foreign])+' };\n'
    return text, values


def verify_config(text, values):
    f.verify_config(text, values)
    require(not re.search(r'(?:Pre-Invoke|Post-Invoke|Pre-Install-Pkgs|AptCli::Hooks|DPkg::.*(?:status-logger|pre-invoke|post-invoke))', text, re.I), 'unexpected package hook')


def verify_indexes(text, lists, spec, releases):
    checks = {r['uri']:r['package_checksums'] for r in releases}
    rows = []
    seen = set()
    for item in f.stanzas(text):
        if item.get('Identifier') != 'Packages':
            continue
        uri = item['URI']
        candidates = [s for s in spec['releases'] if uri.startswith(s['base_uri'].rstrip('/')+'/dists/'+s['suite']+'/')]
        require(len(candidates)==1, 'unexpected package index origin')
        source = candidates[0]
        prefix = source['base_uri'].rstrip('/')+'/dists/'+source['suite']+'/'
        relative = uri[len(prefix):]
        arch, component = item.get('Architecture'), item.get('Component')
        require(arch in ['arm64','all',*spec['foreign_architectures']] and component in source['components']
                and relative == component+'/binary-'+arch+'/Packages' and item.get('Trusted')=='yes'
                and item.get('Codename')==source['codename'], 'untrusted index identity')
        key = (prefix, relative)
        require(key not in seen, 'duplicate index')
        seen.add(key)
        signed = checks[prefix+'InRelease'].get(relative)
        path = Path(item['Filename'])
        require(path.parent==lists and not path.is_symlink() and signed is not None, 'index path/signature coverage')
        digest = f.digest(path)
        require(digest==signed['sha256'] and path.stat().st_size==signed['size'], 'index differs from signed Release')
        rows.append({'uri':uri,'filename':str(path),'sha256':digest,'size':path.stat().st_size,
                     'architecture':arch,'component':component})
    for source in spec['releases']:
        prefix = source['base_uri'].rstrip('/')+'/dists/'+source['suite']+'/'
        for component in source['components']:
            for arch in ['arm64',*spec['foreign_architectures']]:
                name = component+'/binary-'+arch+'/Packages'
                signed = checks[prefix+'InRelease'].get(name)
                require(signed is not None, 'required architecture/component missing from signed Release')
                require((prefix,name) in seen or signed['size']==0, 'required nonempty Packages index missing')
    return rows


def native_changes(text):
    installs, removals = set(), set()
    for line in text.splitlines():
        if line.startswith('Inst '):
            # Reuse the strict existing native install-line parser, one non-removal line at a time.
            installs.update(f.simulated_changes(line))
        elif line.startswith('Remv '):
            match = re.fullmatch(r'Remv (\S+) \[([^\]]+)\](?: .*)?', line)
            require(match is not None, 'unparsed native removal')
            removals.add((match[1],match[2]))
    return installs, removals


def full_plan(cache, native, allowed_hosts, held):
    import apt_pkg
    cache.clear()
    offered = {p.name:{'package':p.shortname,'architecture':p.installed.architecture,
                       'installed':p.installed.version,'candidate':p.candidate.version,'held':p.shortname in held}
               for p in cache if p.installed and p.candidate
               and apt_pkg.version_compare(p.candidate.version,p.installed.version)>0}
    cache.upgrade(dist_upgrade=True)
    require(cache.broken_count==0, 'broken Python APT solution')
    changes = cache.get_changes()
    require(len(changes)<=512, '512 changed-package bound')
    installs = {f.version_id(p.candidate) for p in changes if not p.marked_delete}
    removals = {(p.name,p.installed.version) for p in changes if p.marked_delete}
    actual_install, actual_remove = native_changes(native)
    # Native names omit the native architecture, but retain foreign qualifiers.
    expected_remove = {(p.shortname+(':'+p.installed.architecture if ':' in p.name else ''),p.installed.version)
                       for p in changes if p.marked_delete}
    require(installs==actual_install and (removals==actual_remove or expected_remove==actual_remove),
            'native/Python full-update disagreement')
    require(not any(p.shortname in held for p in changes), 'held package selected')
    records, findings = [], []
    for package in changes:
        if package.marked_delete:
            records.append({'package':package.name,'action':'remove','installed':package.installed.version})
            findings.append('removal:'+package.name)
            continue
        version = package.candidate
        uri = urlsplit(version.uri or '')
        origins = [{k:getattr(o,k) for k in ('site','origin','label','archive','component','trusted')} for o in version.origins]
        require(re.fullmatch('[0-9a-f]{64}',version.sha256 or '') is not None and uri.scheme in ('http','https','file')
                and not uri.username and not uri.password and (uri.hostname or '') in allowed_hosts
                and any(o['trusted'] and o['site'] in allowed_hosts for o in origins), 'untrusted package payload provenance')
        if uri.hostname=='download.webmin.com':
            require(package.shortname=='webmin', 'Webmin origin escaped package pin')
        action = 'upgrade' if package.installed else 'install'
        if package.marked_downgrade:
            action = 'downgrade'; findings.append('downgrade:'+package.name)
        if not package.installed:
            findings.append('addition:'+package.name)
        if package.shortname.startswith('ntpsec') or package.shortname in ('ntp','gpsd','gpsd-clients','python3-gps'):
            findings.append('source-built-service-conflict:'+package.name)
        if package.shortname in FIRMWARE or package.shortname.startswith('linux-image'):
            findings.append('boot-kernel-firmware-effects:'+package.name)
        records.append({'package':package.shortname,'architecture':version.architecture,'action':action,
                        'installed':package.installed.version if package.installed else None,'version':version.version,
                        'payload_sha256':version.sha256,'payload_uri':version.uri,'origins':origins,'record':str(version.record)})
    kept = []
    for name,row in offered.items():
        selected = f.selected_version(cache[name])
        if selected is not None and selected.version != row['candidate']:
            kept.append(dict(row, selected=selected.version,
                reason='offered candidate not selected by agreeing native/Python full-update solution; assess policy/dependencies'))
    require(len(kept)<=512, 'kept-back bound')
    return {'changes':records,'kept_back':kept,'held':held,'findings':findings,'installation_authorized':False,
            'eeprom_policy':'Default update channel and boot service -s -a were captured; payload/script/boot effects and recovery still require review, even if rpi-eeprom is not selected.'}


def cleanup(work, identity):
    require(shutil.rmtree.avoids_symlink_attacks, 'safe native cleanup unavailable')
    f.owned_cleanup(work, identity)
    require(not work.exists(), 'workspace residue')


def run(spec, snapshot):
    report = {'operation_id':spec['operation_id'],'resolution_complete':False,'installation_authorized':False,
              'commands':{},'started_epoch':time.time(),'workspace_created':False,'workspace_cleaned':False}
    work = Path(spec['workspace']); owner = None
    deadline = time.monotonic()+660
    previous_config = os.environ.get('APT_CONFIG')
    def query(label, argv, seconds=30):
        report['current_command'] = label
        row = f.command(argv, env, deadline, seconds)
        report['commands'][label] = row
        require(not row['rc'] and not row['error'], 'native command failed: '+label)
        return row['output']
    def units():
        return {unit:m.command(['/usr/bin/systemctl','--no-pager','show','--property=Id,LoadState,ActiveState,SubState,MainPID,InvocationID,NRestarts',unit])
                for unit in m.SERVICES if unit!='gpsd.socket'}
    def live_state():
        extras = [k for k in snapshot['before']['files'] if '/systemd/' in k]
        result = {'configuration':m.configuration(extras),'apt_lists':m.list_metadata(),'locks':m.lock_state(),'services':units()}
        result['processes'] = m.command(['/usr/bin/ps','-eo','pid,ppid,comm'])
        require(result['processes']['accepted'] and all(r['accepted'] for r in result['services'].values()), 'state query failure')
        result['runtime'] = m.runtime(result['processes']['stdout'])
        result['boot'] = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        return result
    def expired(*_):
        raise TimeoutError('660-second resolution deadline')
    signal.signal(signal.SIGALRM, expired); signal.signal(signal.SIGTERM, expired); signal.signal(signal.SIGHUP, expired)
    signal.alarm(660)
    env = dict(m.ENV)
    try:
        require(os.geteuid()==0 and os.environ.get('SUDO_USER')=='ama' and os.environ.get('SUDO_UID')=='1000'
                and socket.gethostname()=='j2-svntp1' and os.uname().release==spec['kernel'], 'target identity')
        require(sys.dont_write_bytecode and sys.flags.isolated, 'isolated Python required')
        require(spec['prepared_epoch']-300<=time.time()<spec['expires_epoch']-960, 'fresh snapshot/window required')
        before = live_state(); report['before'] = before
        require(before['configuration']==snapshot['before'] and before['boot']==snapshot['boot_after'], 'approved input/boot drift')
        require(not before['locks']['held'], 'package lock held')
        for unit in ('apt-daily.service','apt-daily-upgrade.service'):
            require('ActiveState=inactive\n' in before['services'][unit]['stdout'], 'APT job active')
        require(not re.search(r'(?m)\s(?:apt|apt-get|dpkg|unattended-upgr)\s*$', before['processes']['stdout']), 'package process active')
        require(not query('dpkg_audit',['/usr/bin/dpkg','--audit']).strip(), 'dpkg audit findings')
        require(query('native_arch',['/usr/bin/dpkg','--print-architecture']).strip()=='arm64', 'native architecture drift')
        require(query('foreign_arch',['/usr/bin/dpkg','--print-foreign-architectures']).split()==spec['foreign_architectures'], 'foreign architecture drift')
        require(m.record('/var/lib/dpkg/status')['sha256']==snapshot['before']['files']['/var/lib/dpkg/status']['sha256'], 'package selection drift')
        require(os.statvfs('/var/tmp').f_bavail*os.statvfs('/var/tmp').f_frsize>=2*1024**3, 'less than 2 GiB scratch headroom')
        parent=work.parent; st=parent.lstat()
        require(parent==Path('/var/tmp') and parent.resolve()==parent and st.st_uid==0 and st.st_mode & 0o1000, 'unsafe workspace parent')
        require(re.fullmatch(r'base-os-metadata-resolution-[0-9]{8}-v[0-9]+',work.name), 'workspace scope')
        work.mkdir(mode=0o700); st=work.stat(); owner=(st.st_dev,st.st_ino,st.st_uid)
        report.update(workspace_created=True,workspace=str(work),workspace_identity=list(owner))
        for name in ('empty','sources','keyrings','state','lists','cache','cache/archives','log','gnupg'):
            (work/name).mkdir(mode=0o700 if name in ('state','gnupg') else 0o755)
        work.chmod(0o711)
        for path in f.STATE_FILES:
            source=Path(path); target=work/'state'/source.name
            if source.exists():
                shutil.copyfile(source,target)
                require(f.digest(target)==snapshot['before']['files'][path]['sha256'], 'state-copy drift')
            else: target.touch()
            target.chmod(0o600)
        for key in KEYS:
            raw=Path(key).read_bytes()
            require(hashlib.sha256(raw).hexdigest()==spec['key_hashes'][key], 'keyring drift')
            target=work/'keyrings'/Path(key).name; target.write_bytes(raw); target.chmod(0o644)
        (work/'sources.list').write_text('')
        for source in SOURCES:
            raw=Path(source).read_bytes()
            require(hashlib.sha256(raw).hexdigest()==spec['source_hashes'][source], 'source drift')
            for key in KEYS:
                raw=raw.replace(key.encode(),str(work/'keyrings'/Path(key).name).encode())
            target=work/'sources'/Path(source).name; target.write_bytes(raw); target.chmod(0o644)
        raw=Path(PIN).read_bytes(); require(hashlib.sha256(raw).hexdigest()==spec['pin_sha256'], 'pin drift')
        (work/'preferences').write_bytes(raw); (work/'preferences').chmod(0o644)
        text,values=configuration(work,spec['foreign_architectures'])
        (work/'apt.conf').write_text(text); (work/'apt.conf').chmod(0o644)
        env['APT_CONFIG']=str(work/'apt.conf'); os.environ['APT_CONFIG']=env['APT_CONFIG']
        verify_config(query('isolated_configuration',['/usr/bin/apt-config','dump']),values)
        query('signed_update',['/usr/bin/apt-get','--error-on=any','update'],300)
        releases=f.release_evidence(work/'lists',spec,time.time())
        report['releases']=releases
        for i,source in enumerate(spec['releases']):
            uri=source['base_uri'].rstrip('/')+'/dists/'+source['suite']+'/InRelease'
            filename=uri.split('://',1)[1].replace('/','_')
            status=query('signature_'+str(i),['/usr/bin/gpgv','--homedir',str(work/'gnupg'),'--keyring',str(work/'keyrings'/Path(source['keyring']).name),
                        '--status-fd','1',str(work/'lists'/filename)])
            signatures=re.findall(r'\[GNUPG:\] VALIDSIG ([A-F0-9]{40,64})\b',status)
            require(signatures, 'no valid Release signature')
            if source.get('fingerprint'):
                # Primary fingerprint is the final VALIDSIG field when a signing subkey is used.
                require(any(source['fingerprint'] in line.split() for line in status.splitlines() if ' VALIDSIG ' in line), 'Webmin signing identity mismatch')
        report['indexes']=verify_indexes(query('index_targets',['/usr/bin/apt-get','indextargets']),work/'lists',spec,releases)
        import apt_pkg
        apt_pkg.config.clear(''); apt_pkg.init_config(); apt_pkg.init_system()
        import apt
        require(apt_pkg.VERSION==spec['apt_version'], 'native/Python APT version drift')
        for module in (apt,apt_pkg):
            path=Path(module.__file__); st=path.lstat()
            require(str(path).startswith('/usr/lib/python3/dist-packages/') and not path.is_symlink()
                    and st.st_uid==0 and not st.st_mode & 0o022, 'untrusted APT binding')
        require(apt_pkg.config.find('Dir::State::lists')==str(work/'lists') and
                apt_pkg.config.find('Dir::Etc::preferences')==str(work/'preferences'), 'Python isolation/pin drift')
        native=query('full_update_simulation',['/usr/bin/apt-get','--simulate','dist-upgrade'],120)
        with apt.Cache() as cache:
            report['plan']=full_plan(cache,native,{urlsplit(s['base_uri']).hostname for s in spec['releases']},spec['held'])
        require(all(f.digest(Path(row['filename']))==row['sha256'] for row in report['indexes']), 'Packages metadata changed')
        require(all(f.digest(work/'lists'/row['uri'].split('://',1)[1].replace('/','_'))==row['sha256'] for row in releases), 'Release metadata changed')
        report['resolution_complete']=True
    except BaseException as error:
        report.update(error=type(error).__name__+': '+str(error),held=True)
    finally:
        signal.alarm(0)
        if previous_config is None: os.environ.pop('APT_CONFIG',None)
        else: os.environ['APT_CONFIG']=previous_config
        if 'before' in report:
            try:
                after=live_state(); report['after']=after
                stable=all(before[k]==after[k] for k in ('configuration','apt_lists','services','runtime','boot')) and not after['locks']['held']
                report['live_state_unchanged']=stable
                if not stable: report.update(resolution_complete=False,held=True,continuity_error='live state changed')
            except BaseException as error:
                report.update(resolution_complete=False,held=True,continuity_error=str(error))
        if owner is not None:
            try:
                cleanup(work,owner); report['workspace_cleaned']=True
            except BaseException as error:
                report.update(resolution_complete=False,held=True,cleanup_error=str(error))
        report['finished_epoch']=time.time()
    return report
