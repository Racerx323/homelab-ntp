#!/usr/bin/python3
"""Isolated authenticated metadata acquisition and simulation; never install."""
import base64
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit

import inspect_trixie as inspection  # Supplied by the exact bundled stdin wrapper.

OUTPUT_LIMIT = 4 * 1024 * 1024
STATE_FILES = ('/var/lib/dpkg/status', '/var/lib/apt/extended_states')


def remaining_module_paths(package_listing):
    paths = set()
    for line in package_listing.splitlines():
        path = Path(line)
        if '..' in path.parts:
            raise ValueError('parent traversal in module package listing rejected')
        if line.startswith('/usr/lib/python3/dist-packages/apt_listchanges/') and line.endswith('.py'):
            paths.add(path)
    if not paths or len(paths) > 128:
        raise ValueError('remaining apt-listchanges module count outside approved 1-128 bound')
    return sorted(paths)


def digest(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError('nonregular input: ' + str(path))
    sha = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(65536), b''):
            sha.update(block)
    return sha.hexdigest()


def state_hashes():
    return {p: digest(Path(p)) if Path(p).exists() else None for p in STATE_FILES}


def command(argv, env, deadline, seconds=60, on_spawn=None):
    """Bound bytes/time and terminate only this invocation's process group."""
    stop_at = min(deadline, time.monotonic() + seconds)
    if stop_at <= time.monotonic():
        raise ValueError('operation deadline exceeded before command')
    process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, env=env, cwd='/', start_new_session=True)
    output = bytearray()
    reason = None
    try:
        if on_spawn:
            on_spawn(process.pid)
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while selector.get_map():
                if time.monotonic() >= stop_at:
                    reason = 'timeout'
                    break
                for key, _ in selector.select(min(1, max(0, stop_at - time.monotonic()))):
                    block = os.read(key.fd, min(65536, OUTPUT_LIMIT + 1 - len(output)))
                    if not block:
                        selector.unregister(key.fileobj)
                    else:
                        output.extend(block)
                        if len(output) > OUTPUT_LIMIT:
                            reason = 'output_limit'
                            break
                if reason:
                    break
            if not reason:
                process.wait(timeout=max(0.01, stop_at - time.monotonic()))
    except subprocess.TimeoutExpired:
        reason = 'timeout'
    except BaseException:
        reason = 'interrupted'
        raise
    finally:
        if reason or process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            if reason:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        process.stdout.close()
    return {'argv': argv, 'rc': process.returncode,
            'output': output[:OUTPUT_LIMIT].decode(errors='replace'), 'error': reason}


def apt_configuration(work, foreign_architectures=None):
    architectures = ['arm64', *(foreign_architectures if foreign_architectures is not None else ['armhf'])]
    if len(architectures) != len(set(architectures)) or set(architectures) - {'arm64', 'armhf'}:
        raise ValueError('unsupported observed APT architectures')
    values = {
        'Dir::Etc::main': str(work / 'no-main.conf'), 'Dir::Etc::parts': str(work / 'empty'),
        'Dir::Etc::sourcelist': str(work / 'sources.list'),
        'Dir::Etc::sourceparts': str(work / 'sources'),
        'Dir::Etc::trusted': str(work / 'no-trusted.gpg'),
        'Dir::Etc::trustedparts': str(work / 'empty'),
        'Dir::Etc::preferences': str(work / 'no-preferences'),
        'Dir::Etc::preferencesparts': str(work / 'empty'),
        'Dir::State': str(work / 'state'), 'Dir::State::lists': str(work / 'lists'),
        'Dir::State::status': str(work / 'state/status'),
        'Dir::State::extended_states': str(work / 'state/extended_states'),
        'Dir::Cache': str(work / 'cache'), 'Dir::Cache::archives': str(work / 'cache/archives'),
        'Dir::Cache::pkgcache': '', 'Dir::Cache::srcpkgcache': '', 'Dir::Log': str(work / 'log'),
        'Dir::Bin::dpkg': '/bin/false', 'APT::Architecture': 'arm64',
        'APT::Install-Recommends': 'true', 'APT::Install-Suggests': 'false',
        'APT::Solver': 'internal', 'APT::Planner': 'internal',
        'APT::Get::AllowUnauthenticated': 'false', 'Acquire::AllowInsecureRepositories': 'false',
        'Acquire::AllowDowngradeToInsecureRepositories': 'false', 'Acquire::Check-Date': 'true',
        'Acquire::Check-Valid-Until': 'true', 'Acquire::Retries': '0',
        'Acquire::http::Timeout': '20', 'Acquire::https::Timeout': '20',
        'Acquire::Languages': 'none', 'APT::Sandbox::User': '_apt',
        'Debug::Acquire::gpgv': 'true', 'Debug::pkgAcquire::Auth': 'true',
    }
    text = ''.join(k + ' ' + json.dumps(v) + ';\n' for k, v in values.items())
    return text + 'APT::Architectures { ' + ' '.join(json.dumps(a) + ';' for a in architectures) + ' };\n', values


def verify_config(text, values):
    for key, value in values.items():
        if key == 'Acquire::Languages':
            languages = re.findall(r'^Acquire::Languages::(?:\d+)? "([^"\n]*)";$', text, re.M)
            if languages:
                if languages != ['none']:
                    raise ValueError('unexpected language indexes in isolated configuration')
                continue
        if key + ' ' + json.dumps(value) + ';' not in text:
            raise ValueError('effective isolated APT setting mismatch: ' + key)
    if re.search(r'(?:Pre-Invoke|Post-Invoke|Pre-Install-Pkgs)', text, re.I):
        raise ValueError('unexpected hook in isolated APT configuration')


def stanzas(text):
    result = []
    for block in re.split(r'\n\s*\n', text.strip()):
        fields = {}
        last = None
        for line in block.splitlines():
            if line.startswith((' ', '\t')) and last:
                fields[last] += '\n' + line
            else:
                key, sep, value = line.partition(':')
                if not sep or key in fields:
                    raise ValueError('malformed/duplicate metadata field')
                fields[key] = value.strip()
                last = key
        if fields:
            result.append(fields)
    return result


def authenticated_indexes(text, lists, spec, releases):
    release_checksums = {r['uri']: r['package_checksums'] for r in releases}
    expected = {}
    for source in spec['releases']:
        checksums = release_checksums[source['base_uri'].rstrip('/') + '/dists/' + source['suite'] + '/InRelease']
        for arch in ('arm64', *spec.get('foreign_architectures', ['armhf'])):
            for component in source['components']:
                checksum = checksums.get(component + '/binary-' + arch + '/Packages')
                if checksum is None:
                    raise ValueError('required Packages checksum missing from signed release')
                if checksum['size'] == 0 and checksum['sha256'] != hashlib.sha256(b'').hexdigest():
                    raise ValueError('invalid signed empty Packages checksum')
                expected[(source['base_uri'], source['suite'], arch, component)] = checksum
    records = stanzas(text)
    matched = set()
    binaries = []
    for record in records:
        if record.get('Identifier') != 'Packages':
            continue
        uri = record.get('URI', '')
        source = next((s for s in spec['releases']
                       if uri.startswith(s['base_uri'].rstrip('/') + '/dists/' + s['suite'] + '/')), None)
        if not source or record.get('Trusted') != 'yes' or record.get('Codename') != source['codename']:
            raise ValueError('untrusted or unexpected package index identity')
        key = (source['base_uri'], source['suite'], record.get('Architecture'), record.get('Component'))
        if key not in expected or key in matched:
            raise ValueError('unexpected or duplicate package index')
        if uri != (source['base_uri'].rstrip('/') + '/dists/' + source['suite'] + '/'
                   + key[3] + '/binary-' + key[2] + '/Packages'):
            raise ValueError('package index URI/identity mismatch')
        path = Path(record['Filename'])
        if path.parent != lists or path.is_symlink():
            raise ValueError('index escaped owned lists directory')
        record['sha256'] = digest(path)
        if record['sha256'] != expected[key]['sha256'] or path.stat().st_size != expected[key]['size']:
            raise ValueError('package index differs from signed checksum/size')
        matched.add(key)
        binaries.append(record)
    empty = {key for key, checksum in expected.items() if checksum['size'] == 0}
    if matched | empty != set(expected):
        raise ValueError('missing or unexpected architecture/component package indexes')
    return binaries


def release_evidence(lists, spec, now):
    records = []
    expected_files = []
    for source in spec['releases']:
        url = source['base_uri'].rstrip('/') + '/dists/' + source['suite'] + '/InRelease'
        name = url.split('://', 1)[1].replace('/', '_')
        expected_files.append(name)
        path = lists / name
        if path.is_symlink() or not path.is_file():
            raise ValueError('nonregular InRelease')
        with path.open('rb') as stream:
            data = stream.read(512 * 1024 + 1)
        if len(data) > 512 * 1024:
            raise ValueError('invalid/oversized InRelease')
        text = data.decode()
        if not text.startswith('-----BEGIN PGP SIGNED MESSAGE-----\n') or '\n-----BEGIN PGP SIGNATURE-----\n' not in text:
            raise ValueError('clear-signed InRelease required')
        body = text.split('\n\n', 1)[1].split('\n-----BEGIN PGP SIGNATURE-----\n', 1)[0]
        fields = stanzas('\n'.join(line[2:] if line.startswith('- ') else line
                                   for line in body.splitlines()))[0]
        if (fields.get('Codename') != source['codename']
                or fields.get('Origin') != source['origin']
                or fields.get('Suite') != source['release_suite']):
            raise ValueError('unexpected signed release identity')
        date = parsedate_to_datetime(fields['Date']).timestamp()
        if date > now + 600 or ('Valid-Until' in fields and
                               parsedate_to_datetime(fields['Valid-Until']).timestamp() < now):
            raise ValueError('release date/expiry rejected')
        checksums = {}
        for line in fields.get('SHA256', '').splitlines():
            if not line.strip():
                continue
            checksum, size, name = line.split()
            if not re.fullmatch(r'[0-9a-f]{64}', checksum) or not re.fullmatch(r'[0-9]{1,20}', size):
                raise ValueError('malformed signed SHA256 entry')
            if name.endswith('/Packages'):
                if name in checksums:
                    raise ValueError('duplicate signed Packages checksum')
                checksums[name] = {'sha256': checksum, 'size': int(size)}
        records.append({'uri': url, 'sha256': hashlib.sha256(data).hexdigest(),
                        'package_checksums': checksums,
                        'identity': {k: fields.get(k) for k in ('Origin', 'Label', 'Suite', 'Codename',
                                                              'Version', 'Date', 'Valid-Until')},
                        'signed_bytes_base64': base64.b64encode(data).decode()})
    if sorted(p.name for p in lists.glob('*_InRelease')) != sorted(expected_files):
        raise ValueError('unexpected release set')
    return records


def version_id(version):
    return (version.package.shortname, version.version, version.architecture)


def selected_version(package):
    if package.marked_delete:
        return None
    return package.candidate if (package.marked_install or package.marked_upgrade
                                 or package.marked_downgrade or package.marked_reinstall) else package.installed


def simulated_changes(text):
    if re.search(r'^Remv ', text, re.M):
        raise ValueError('removal in simulation')
    changes = set()
    for line in text.splitlines():
        if line.startswith('Inst '):
            match = re.fullmatch(r'Inst (\S+)(?: \[[^\]]+\])? \((\S+) .*\[([a-z0-9-]+)\]\)(?: \[\])?', line)
            if not match:
                raise ValueError('unparsed native simulation install line')
            changes.add((match[1].split(':')[0], match[2], match[3]))
    return changes


def reject_package_applications(names):
    for name in names:
        package = name.split(':', 1)[0]
        if package.startswith('ntpsec') or package in ('ntp', 'gpsd', 'gpsd-clients', 'python3-gps'):
            raise ValueError('source-built application cannot be selected from APT: ' + name)


def dependency_plan(cache, roots, native_output, allowed_hosts, pins=None, providers=None):
    reject_package_applications(roots)
    providers = providers or {}
    concrete = {r: providers.get(r, r) for r in roots}
    reject_package_applications(concrete.values())
    cache.clear()
    for root in roots:
        package = cache[concrete[root] + ':arm64']
        if pins is not None:
            if root not in pins:
                raise ValueError('required root pin missing')
            package.candidate = package.versions[pins[root]]
        package.mark_install()
    if pins is not None and any(cache[concrete[r] + ':arm64'].candidate.version != pins[r] for r in roots):
        raise ValueError('solver changed an exact root pin')
    changes = cache.get_changes()
    if cache.broken_count or any(p.marked_delete for p in changes):
        raise ValueError('broken/removing Python APT solution')
    reject_package_applications(p.candidate.package.shortname for p in changes)
    changed = {version_id(p.candidate) for p in changes}
    if changed != simulated_changes(native_output):
        raise ValueError('native/Python APT solution disagreement')
    pending = [selected_version(cache[concrete[root] + ':arm64']) for root in roots]
    pending += [p.candidate for p in changes]
    records = {}
    while pending:
        version = pending.pop()
        if version is None:
            raise ValueError('unselected required root')
        reject_package_applications([version.package.shortname])
        identity = version_id(version)
        if identity in records:
            continue
        if len(records) >= 1024:
            raise ValueError('dependency graph exceeds approved 1024-version bound')
        origins = [{k: getattr(o, k) for k in ('site', 'origin', 'label', 'archive', 'component', 'trusted')}
                   for o in version.origins]
        archive_uri = urlsplit(version.uri or '')
        if identity in changed and (not re.fullmatch(r'[0-9a-f]{64}', version.sha256 or '')
                                   or not any(o['trusted'] and o['site'] in allowed_hosts for o in origins)
                                   or archive_uri.hostname not in allowed_hosts
                                   or archive_uri.scheme not in ('http', 'https')
                                   or archive_uri.username or archive_uri.password):
            raise ValueError('changed package lacks trusted archive hash/origin')
        edges = []
        for group in version.get_dependencies('PreDepends', 'Depends', 'Recommends'):
            alternatives = group.or_dependencies
            selected = {}
            for alternative in alternatives:
                for target in alternative.target_versions:
                    chosen = selected_version(target.package)
                    if chosen is not None and version_id(chosen) == version_id(target):
                        selected[version_id(target)] = target
            kind = alternatives[0].rawtype
            if not selected and kind != 'Recommends':
                raise ValueError('required dependency has no selected satisfier')
            edges.append({'type': kind, 'alternatives': [a.rawstr for a in alternatives],
                          'selected_satisfiers': [list(k) for k in sorted(selected)]})
            pending.extend(selected.values())
        records[identity] = {'package': identity[0], 'version': identity[1], 'architecture': identity[2],
                             'changed': identity in changed, 'origins': origins,
                             'archive_sha256': version.sha256, 'archive_uri': version.uri,
                             'record': str(version.record), 'dependencies': edges}
    return {'roots': roots, 'changes': [list(k) for k in sorted(changed)],
            'versions': [records[k] for k in sorted(records)], 'recommends_enabled': True}


def owned_cleanup(work, identity):
    st = work.lstat()
    if work.is_symlink() or (st.st_dev, st.st_ino, st.st_uid) != identity:
        raise ValueError('workspace cleanup ownership/identity mismatch')
    shutil.rmtree(work)


def reviewed_sources(path, data, spec):
    """Validate fresh-stage sources as data before network access or public copies."""
    text = '\n'.join(line for line in data.decode().splitlines() if not line.lstrip().startswith('#'))
    if not text.strip():
        return
    if Path(path).suffix != '.sources':
        raise ValueError('nonempty legacy sources require separate policy review')
    allowed = {'Types', 'URIs', 'Suites', 'Components', 'Signed-By', 'Architectures', 'Enabled'}
    for row in stanzas(text):
        if set(row) - allowed or row.get('Types') != 'deb' or row.get('Enabled', 'yes') != 'yes':
            raise ValueError('unsupported source fields or authentication override')
        if row.get('Signed-By') not in inspection.PUBLIC_KEYRINGS:
            raise ValueError('source requires the reviewed public keyring')
        if 'Architectures' in row and sorted(row['Architectures'].split()) != sorted(['arm64', *spec['foreign_architectures']]):
            raise ValueError('source architecture filter differs from snapshot')
        for uri in row.get('URIs', '').split():
            parsed = urlsplit(uri)
            if parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise ValueError('credential-bearing or unsupported source URI')
            for suite in row.get('Suites', '').split():
                match = [r for r in spec['releases'] if r['base_uri'].rstrip('/') == uri.rstrip('/') and r['suite'] == suite]
                if len(match) != 1 or sorted(row.get('Components', '').split()) != sorted(match[0]['components']):
                    raise ValueError('source URI/suite/components differ from reviewed policy')
        if not row.get('URIs', '').strip() or not row.get('Suites', '').strip():
            raise ValueError('source URI and suite required')


def run(spec, controller_epoch):
    if os.geteuid() != 0 or os.environ.get('SUDO_USER') != 'ama' or os.environ.get('SUDO_UID') != str(spec['caller_uid']):
        raise ValueError('requires noninteractive sudo from the approved ama identity')
    for roots in spec['groups'].values():
        reject_package_applications(roots)
    identity = inspection.check_identity(socket.gethostname(), inspection.read_file('/etc/os-release').decode(),
                                         os.uname().machine, spec['caller_uid'],
                                         expected_hostname=spec.get('hostname', 'j2-svntp1'))
    if 'snapshot_sha256' in spec and not re.fullmatch(r'[0-9a-f]{64}', spec['snapshot_sha256']):
        raise ValueError('fresh snapshot digest required')
    if abs(time.time() - controller_epoch) > 300 or os.uname().release != spec['kernel']:
        raise ValueError('clock/kernel preflight mismatch')
    if not sys.dont_write_bytecode:
        raise ValueError('Python bytecode writes must be disabled')
    for path, expected in spec['input_hashes'].items():
        if digest(Path(path)) != expected:
            raise ValueError('approved input drift: ' + path)
        st = Path(path).lstat()
        metadata = {'uid': st.st_uid, 'gid': st.st_gid, 'mode': oct(st.st_mode & 0o7777)}
        if metadata != spec['input_metadata'][path]:
            raise ValueError('approved input ownership/mode drift: ' + path)
    if any(Path(path).exists() or Path(path).is_symlink() for path in spec['absent_inputs']):
        raise ValueError('previously absent input appeared')
    config_paths = sorted(str(p) for p in inspection.keyring_hook_files('') if str(p).startswith('/etc/'))
    if config_paths != spec['expected_config_paths']:
        raise ValueError('configuration file-set drift')
    deadline = time.monotonic() + 660
    report = {'identity': identity, 'controller_epoch': controller_epoch, 'state': 'preflight',
              'snapshot_sha256': spec.get('snapshot_sha256'),
              'commands': [], 'groups': {}, 'metadata_accepted': False, 'package_mutation_authorized': False}
    baseline = state_hashes()
    boot = inspection.read_file('/proc/sys/kernel/random/boot_id').decode().strip()
    work = None
    work_identity = None
    refresh_started = False
    env = dict(inspection.ENV)
    previous_apt_config = os.environ.get('APT_CONFIG')

    def query(label, argv, seconds=60):
        report['current_command'] = {'label': label, 'argv': argv, 'state': 'registered_before_submission'}
        if work:
            (work / 'evidence/state.json').write_text(json.dumps(report, indent=2))
        def register_pid(pid):
            report['current_command'].update(state='submitted', process_group=pid)
            if work:
                (work / 'evidence/state.json').write_text(json.dumps(report, indent=2))
        result = command(argv, env, deadline, seconds, on_spawn=register_pid)
        result['label'] = label
        report['commands'].append(result)
        report['current_command'].update(state='completed', rc=result['rc'], error=result['error'])
        if work:
            (work / 'evidence/state.json').write_text(json.dumps(report, indent=2))
        if result['rc'] or result['error']:
            raise ValueError('native query failed: ' + label)
        return result['output']

    try:
        if query('native_architecture', ['/usr/bin/dpkg', '--print-architecture']).strip() != 'arm64':
            raise ValueError('native architecture drift')
        if query('foreign_architectures', ['/usr/bin/dpkg', '--print-foreign-architectures']).split() != spec.get('foreign_architectures', ['armhf']):
            raise ValueError('foreign architecture drift')
        versions = query('package_versions', ['/usr/bin/dpkg-query', '-W',
                         '-f=${binary:Package}\t${Version}\t${db:Status-Abbrev}\n'] + spec['verify_packages'])
        for line in spec['expected_version_lines']:
            if line not in versions.splitlines():
                raise ValueError('approved package version drift')
        if query('package_file_verification', ['/usr/bin/dpkg', '--verify'] + spec['verify_packages']).strip():
            raise ValueError('package-file verification findings')
        import sysconfig
        report['python_environment'] = {
            'executable': sys.executable, 'version': list(sys.version_info[:3]),
            'search_path': list(sys.path), 'purelib': sysconfig.get_path('purelib'),
            'platlib': sysconfig.get_path('platlib'),
            'extension_suffix': sysconfig.get_config_var('EXT_SUFFIX')}
        if query('dpkg_audit', ['/usr/bin/dpkg', '--audit']).strip():
            raise ValueError('dpkg audit findings')
        units = query('update_services', ['/usr/bin/systemctl', '--no-pager', 'show',
                      '--property=Id,ActiveState', 'apt-daily.service', 'apt-daily-upgrade.service'])
        if len(re.findall(r'^ActiveState=inactive$', units, re.M)) != 2:
            raise ValueError('automatic APT activity not inactive')
        listing = query('remaining_module_listing', ['/usr/bin/dpkg-query', '-L', 'apt-listchanges', 'debconf'])
        module_paths = remaining_module_paths(listing)
        report['remaining_module_inputs'] = inspection.policy_snapshot(module_paths)
        if shutil.disk_usage('/var/tmp').free < 1073741824:
            raise ValueError('less than 1 GiB staging headroom')
        parent = Path('/var/tmp')
        st = parent.lstat()
        if (parent.is_symlink() or not parent.is_dir() or st.st_uid != 0
                or (st.st_mode & 0o022 and not st.st_mode & 0o1000)):
            raise ValueError('unsafe staging parent')
        if 'workspace' in spec:
            candidate = Path(spec['workspace'])
            if candidate.parent != parent or not re.fullmatch(r'ntp-resolution-[a-z][a-z0-9-]{0,63}', candidate.name):
                raise ValueError('exclusive resolution workspace required')
            candidate.mkdir(mode=0o700)
            work = candidate
        else:
            work = Path(tempfile.mkdtemp(prefix='ntp-metadata-', dir='/var/tmp'))
        st = work.stat()
        work_identity = (st.st_dev, st.st_ino, st.st_uid)
        report['workspace'] = str(work)
        report['workspace_identity'] = list(work_identity)
        work.chmod(0o711)  # Public metadata traversable by the native _apt sandbox.
        for name in ('empty', 'sources', 'keyrings', 'state', 'cache', 'cache/archives', 'lists', 'log'):
            (work / name).mkdir(mode=0o755)
            (work / name).chmod(0o700 if name == 'state' else 0o755)
        (work / 'evidence').mkdir(mode=0o700)
        for path in STATE_FILES:
            target = work / 'state' / Path(path).name
            if Path(path).exists():
                shutil.copyfile(path, target)
            else:
                target.touch(mode=0o644)
            target.chmod(0o600)
            if baseline[path] is not None and digest(target) != baseline[path]:
                raise ValueError('installed-state copy does not match the before snapshot')
        (work / 'sources.list').touch(mode=0o644)
        for key in inspection.PUBLIC_KEYRINGS:
            data = inspection.read_file(key)
            if 'snapshot_sha256' in spec and hashlib.sha256(data).hexdigest() != spec['input_hashes'][key]:
                raise ValueError('public keyring drift before staging')
            (work / 'keyrings' / Path(key).name).write_bytes(data)
            (work / 'keyrings' / Path(key).name).chmod(0o644)
        for source in spec['source_files']:
            data = inspection.read_file(source)
            if 'snapshot_sha256' in spec:
                if hashlib.sha256(data).hexdigest() != spec['input_hashes'][source]:
                    raise ValueError('source drift before staging')
                reviewed_sources(source, data, spec)
            for key in inspection.PUBLIC_KEYRINGS:
                data = data.replace(key.encode(), str(work / 'keyrings' / Path(key).name).encode())
            target = work / 'sources' / Path(source).name
            target.write_bytes(data)
            target.chmod(0o644)
        config, values = apt_configuration(work, spec.get('foreign_architectures'))
        (work / 'apt.conf').write_text(config)
        (work / 'apt.conf').chmod(0o644)
        env['APT_CONFIG'] = str(work / 'apt.conf')
        verify_config(query('isolated_configuration', ['/usr/bin/apt-config', 'dump']), values)
        os.environ['APT_CONFIG'] = env['APT_CONFIG']
        import apt_pkg
        apt_pkg.init_config()
        apt_pkg.init_system()
        import apt
        if apt_pkg.VERSION != spec['apt_version']:
            raise ValueError('Python/native APT library version mismatch')
        for module in (apt, apt_pkg):
            path = Path(module.__file__)
            if (not str(path).startswith('/usr/lib/python3/dist-packages/')
                    or path.is_symlink() or path.stat().st_uid != 0 or path.stat().st_mode & 0o022):
                raise ValueError('unexpected/unprotected APT binding path')
        if not all(hasattr(apt.package.Version, name) for name in ('sha256', 'uri', 'get_dependencies')):
            raise ValueError('required installed APT binding interface unavailable')
        if apt_pkg.config.find('Dir::State::lists') != str(work / 'lists'):
            raise ValueError('Python APT did not load the isolated configuration')
        refresh_started = True
        report['state'] = 'metadata_refresh'
        query('fresh_authenticated_update', ['/usr/bin/apt-get', '--error-on=any', 'update'], 240)
        # Successful native update authenticates these retained release bytes.
        report['releases'] = release_evidence(work / 'lists', spec, time.time())
        indexes = authenticated_indexes(query('index_targets', ['/usr/bin/apt-get', 'indextargets']),
                                        work / 'lists', spec, report['releases'])
        report['indexes'] = indexes
        report['metadata_accepted'] = True
        hosts = {urlsplit(s['base_uri']).hostname for s in spec['releases']}
        for name, roots in spec['groups'].items():
            try:
                pins = spec.get('root_pins')
                providers = spec.get('root_providers', {})
                arguments = [providers.get(p, p) + ':arm64' + ('=' + pins[p] if pins is not None else '') for p in roots]
                native = query('simulate_' + name, ['/usr/bin/apt-get', '--simulate', '--no-remove', 'install'] + arguments)
                cache = apt.Cache()
                try:
                    report['groups'][name] = {'accepted': True, 'plan': dependency_plan(cache, roots, native, hosts, pins, providers)}
                finally:
                    cache.close()
            except (ValueError, KeyError, AttributeError, SystemError) as exc:
                report['groups'][name] = {'accepted': False, 'error': str(exc)}
        report['webmin'] = {'accepted': False, 'reason': 'provenance/source not authorized; no source added'}
        report['metadata_unchanged'] = all(digest(Path(i['Filename'])) == i['sha256'] for i in report['indexes'])
        report['metadata_unchanged'] &= all(
            digest(work / 'lists' / item['uri'].split('://', 1)[1].replace('/', '_')) == item['sha256']
            for item in report['releases'])
        if not report['metadata_unchanged']:
            raise ValueError('staged metadata changed during resolution')
        report['state'] = 'completed'
    except Exception as exc:
        report['state'] = 'held'
        report['error'] = type(exc).__name__ + ': ' + str(exc)
        if report.get('metadata_unchanged') is False:
            report['metadata_accepted'] = False
            for group in report['groups'].values():
                group['accepted'] = False
    finally:
        if previous_apt_config is None:
            os.environ.pop('APT_CONFIG', None)
        else:
            os.environ['APT_CONFIG'] = previous_apt_config
        try:
            report['installed_state_unchanged'] = state_hashes() == baseline
            report['boot_unchanged'] = inspection.read_file('/proc/sys/kernel/random/boot_id').decode().strip() == boot
            report['approved_inputs_unchanged'] = all(digest(Path(p)) == sha for p, sha in spec['input_hashes'].items())
            report['approved_inputs_unchanged'] = report['approved_inputs_unchanged'] and not any(
                Path(p).exists() or Path(p).is_symlink() for p in spec['absent_inputs'])
            for path, expected in spec['input_metadata'].items():
                st = Path(path).lstat()
                report['approved_inputs_unchanged'] &= {
                    'uid': st.st_uid, 'gid': st.st_gid, 'mode': oct(st.st_mode & 0o7777)} == expected
            report['approved_inputs_unchanged'] &= sorted(
                str(p) for p in inspection.keyring_hook_files('') if str(p).startswith('/etc/')) == spec['expected_config_paths']
        except (OSError, ValueError) as exc:
            report.update(installed_state_unchanged=False, boot_unchanged=False,
                          approved_inputs_unchanged=False, continuity_error=str(exc))
        if not all(report[k] for k in ('installed_state_unchanged', 'boot_unchanged', 'approved_inputs_unchanged')):
            report['state'] = 'held'
            report['error'] = 'continuity failure; no package plan accepted'
            report['metadata_accepted'] = False
            for group in report['groups'].values():
                group['accepted'] = False
        if work:
            if not refresh_started:
                try:
                    owned_cleanup(work, work_identity)
                    report['workspace_cleaned'] = True
                except (OSError, ValueError) as exc:
                    report.update(state='held', workspace_cleaned=False,
                                  cleanup_error=str(exc), manual_intervention_required=True)
            else:
                (work / 'evidence/state.json').write_text(json.dumps(report, indent=2))
                report['workspace_retained'] = True
        report['refresh_started'] = refresh_started
    return report


def main(spec, controller_epoch):
    os.umask(0o077)
    def interrupted(signum, frame):
        raise RuntimeError('interrupted by signal ' + str(signum))
    for signum in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
        signal.signal(signum, interrupted)
    try:
        report = run(spec, controller_epoch)
    except Exception as exc:
        report = {'state': 'preflight_rejected', 'error': type(exc).__name__ + ': ' + str(exc),
                  'metadata_accepted': False, 'package_mutation_authorized': False}
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report['state'] == 'completed' and all(g['accepted'] for g in report['groups'].values()) else 2
