#!/usr/bin/python3
"""Target-local source builds and manifest-bound installs; no OS/service changes.

Adapted workflow from NTPsec's microserver HOWTO clockmaker. Upstream bytes and
the deliberate departures are recorded in source-build-audit-20261010.md.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import signal
import stat
import subprocess
import sys
import sysconfig
import tarfile
import tempfile


PREFIX = '/usr/local'
APPLICATIONS = ('gpsd', 'ntpsec')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def regular_bytes(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError('regular file required: ' + str(path))
        return stream.read()


def bound_json(path, expected):
    data = regular_bytes(path)
    if digest(data) != expected:
        raise ValueError('input hash mismatch: ' + str(path))
    return json.loads(data)


def target_identity(hostname):
    release_path = Path('/etc/os-release')
    if release_path.is_symlink():
        release_path = release_path.resolve(strict=True)
        if release_path != Path('/usr/lib/os-release'):
            raise ValueError('unexpected OS release symlink')
    release = dict(line.split('=', 1) for line in
                   regular_bytes(release_path).decode().splitlines()
                   if '=' in line)
    if (os.uname().nodename != hostname or os.uname().machine != 'aarch64'
            or release.get('VERSION_ID', '').strip('"') != '13'):
        raise ValueError('wrong target identity/architecture/OS')


def require_no_package_applications():
    records = subprocess.check_output(
        ['/usr/bin/dpkg-query', '-W', '-f=${Package}\t${db:Status-Abbrev}\n'],
        env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'}, timeout=10).decode()
    for line in records.splitlines():
        package, status = line.split('\t', 1)
        if status.startswith('ii') and (package.startswith('ntpsec') or
                package in ('ntp', 'gpsd', 'gpsd-clients', 'python3-gps')):
            raise ValueError('conflicting package application: ' + package)


def require_stopped_daemons():
    for process in Path('/proc').glob('[0-9]*/comm'):
        try:
            name = process.read_text().strip()
        except FileNotFoundError:
            continue
        if name in ('ntpd', 'gpsd'):
            raise ValueError('both daemons must be stopped by the approved cutover')


def validate_profile(profile):
    if profile['schema'] != 1 or profile['prefix'] != PREFIX:
        raise ValueError('unsupported profile/prefix')
    if set(profile['sources']) != set(APPLICATIONS):
        raise ValueError('both source applications required')
    if any(s.get('archive_format') == 'publisher-release' for s in profile['sources'].values()):
        python = profile.get('python', {})
        directory = python.get('module_directory', '')
        if (python.get('executable') != '/usr/bin/python3'
                or python.get('version') != list(sys.version_info[:2])
                or not directory.startswith('/usr/local/lib/')
                or directory not in set(sys.path) | {sysconfig.get_path('purelib'), sysconfig.get_path('platlib')}
                or '..' in PurePosixPath(directory).parts):
            raise ValueError('observed Python interpreter/version and local module directory required')
    if set(profile['helpers']) != {'clockmaker.py', 'pinup.py', 'timeservice.py'}:
        raise ValueError('reviewed maintained helper hashes required')
    if not profile['packages']:
        raise ValueError('reviewed build prerequisite versions required')
    for package, version in profile['packages'].items():
        if not re.fullmatch(r'[a-z0-9][a-z0-9+.-]*(?::[a-z0-9]+)?', package) or not version:
            raise ValueError('invalid prerequisite package/version')
    for name, source in profile['sources'].items():
        if (not re.fullmatch(r'[0-9a-f]{40}', source['commit'])
                or not re.fullmatch(r'[0-9a-f]{64}', source['sha256'])
                or not source['release_tag'] or not source['origin'].startswith('https://')):
            raise ValueError('reviewed release tag, commit, origin and digest required')
        if source.get('archive_format', 'git-archive') == 'publisher-release':
            root = source.get('archive_root', '')
            if not root or PurePosixPath(root).parts != (root,) or root in ('.', '..'):
                raise ValueError('one explicit publisher archive root required')
        elif source.get('archive_format', 'git-archive') != 'git-archive':
            raise ValueError('unsupported source archive format')
        if name == 'ntpsec':
            reserved = ('--prefix', '--destdir') + (('--pythondir', '--pythonarchdir', '--pyshebang') if 'python' in profile else ())
            if any(not a.startswith('--') or a.startswith(reserved)
                   for a in source['options']):
                raise ValueError('invalid NTPsec configure options')
        elif any(not re.fullmatch(r'[a-z][a-z0-9_]*=[A-Za-z0-9_./,+:-]+', a)
                 or a.startswith(('prefix=', 'libdir=', 'bindir=', 'sbindir=') +
                                 (('target_python=', 'python_libdir=', 'python_shebang=') if 'python' in profile else ()))
                 for a in source['options']):
            raise ValueError('invalid GPSD build options')


def unpack_source(data, source, destination):
    """Extract hash-bound source; publisher signature/tag review is external."""
    import io
    if digest(data) != source['sha256']:
        raise ValueError('source archive hash mismatch')
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        publisher = source.get('archive_format', 'git-archive') == 'publisher-release'
        if not publisher and archive.pax_headers.get('comment') != source['commit']:
            raise ValueError('archive does not identify the reviewed Git commit')
        members = archive.getmembers()
        if len(members) > 10000 or sum(m.size for m in members) > 256 * 1024 * 1024:
            raise ValueError('source archive exceeds bounds')
        seen = set()
        by_name = {m.name.rstrip('/'): m for m in members}
        for member in members:
            path = PurePosixPath(member.name)
            if (path.is_absolute() or '..' in path.parts or member.name in seen
                    or not (member.isfile() or member.isdir() or member.issym())):
                raise ValueError('unsafe/duplicate source archive member')
            if publisher and (not path.parts or path.parts[0] != source['archive_root']):
                raise ValueError('publisher archive root mismatch')
            if member.issym():
                target = os.path.normpath(str(path.parent / member.linkname))
                resolved = by_name.get(target)
                if (PurePosixPath(member.linkname).is_absolute() or resolved is None
                        or not resolved.isfile() or (publisher and PurePosixPath(target).parts[0] != source['archive_root'])):
                    raise ValueError('source symlink must target an internal regular file')
            seen.add(member.name)
        archive.extractall(destination, filter='data')
    return destination / source['archive_root'] if publisher else destination


def run(argv, cwd, environment, log):
    with log.open('ab') as stream:
        stream.write((json.dumps(argv) + '\n').encode())
        stream.flush()
        process = subprocess.Popen(argv, cwd=cwd, env=environment, stdout=stream,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        try:
            returncode = process.wait(timeout=1800)
        except BaseException:
            # Only the process group created for this build command is owned.
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            except ProcessLookupError:
                pass
            raise
        if returncode:
            raise subprocess.CalledProcessError(returncode, argv)


def inventory(stage):
    files = {}
    for path in sorted(stage.rglob('*')):
        relative = path.relative_to(stage).as_posix()
        destination = '/' + relative
        if path.is_dir() and not path.is_symlink():
            continue
        if not destination.startswith(PREFIX + '/') or relative.startswith(('usr/local/etc/', 'usr/local/var/')):
            raise ValueError('native installer wrote outside /usr/local')
        info = path.lstat()
        if stat.S_ISREG(info.st_mode):
            mode = stat.S_IMODE(info.st_mode)
            if mode & 0o7022 != 0:
                raise ValueError('unsafe installed file mode')
            files[relative] = {'type': 'file', 'sha256': digest(regular_bytes(path)),
                               'mode': mode}
        elif stat.S_ISLNK(info.st_mode):
            link = os.readlink(path)
            if (PurePosixPath(link).is_absolute()
                    or not path.resolve().is_relative_to((stage / 'usr/local').resolve())
                    or not path.resolve().is_file()):
                raise ValueError('unsafe/broken staged symlink')
            files[relative] = {'type': 'symlink', 'target': link}
        else:
            raise ValueError('unexpected native output type')
    for required in ('usr/local/sbin/ntpd', 'usr/local/sbin/gpsd',
                     'usr/local/bin/ntpq', 'usr/local/bin/ntpleapfetch'):
        if required not in files or files[required]['type'] != 'file':
            raise ValueError('missing staged application/tool: ' + required)
    return files


def build(profile_path, expected, output, updating=False):
    if os.geteuid() == 0:
        raise ValueError('build/update must be unprivileged')
    profile = bound_json(profile_path, expected)
    validate_profile(profile)
    target_identity(profile['hostname'])
    require_no_package_applications()
    for package, version in profile['packages'].items():
        installed = subprocess.check_output(
            ['/usr/bin/dpkg-query', '-W', '-f=${Version}\t${db:Status-Abbrev}', package],
            env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'}, timeout=10).decode()
        if installed != version + '\tii ':
            raise ValueError('build prerequisite changed/missing: ' + package)
    # Verify all input bytes before creating workspace or running build code.
    sources = {}
    for name, source in profile['sources'].items():
        sources[name] = regular_bytes(profile_path.parent / source['archive'])
        if digest(sources[name]) != source['sha256']:
            raise ValueError('source archive hash mismatch')
    helpers = {}
    for name, expected_hash in profile['helpers'].items():
        helper_path = Path(__file__).parent / name
        if name == 'timeservice.py' and not helper_path.exists():
            helper_path = Path('/usr/local/libexec') / name
        helpers[name] = regular_bytes(helper_path)
        if digest(helpers[name]) != expected_hash:
            raise ValueError('maintained helper hash mismatch: ' + name)
    output.mkdir(mode=0o700)  # Never reuse or clobber a previous candidate.
    stage = output / 'stage'
    stage.mkdir(mode=0o700)
    environment = {'PATH': '/usr/bin:/bin', 'HOME': str(output.resolve()),
                   'LC_ALL': 'C', 'PYTHONDONTWRITEBYTECODE': '1'}
    log = output / 'build.log'
    for command in (['/usr/bin/cc', '--version'], ['/usr/bin/python3', '--version'],
                    ['/usr/bin/scons', '--version']):
        run(command, output, environment, log)
    for name in APPLICATIONS:
        source = profile['sources'][name]
        directory = output / name
        directory.mkdir()
        directory = unpack_source(sources[name], source, directory)
        if name == 'gpsd':
            base = ['/usr/bin/scons', 'prefix=' + PREFIX] + source['options']
            if 'python' in profile:
                base += ['target_python=' + profile['python']['executable'],
                         'python_shebang=' + profile['python']['executable'],
                         'python_libdir=' + profile['python']['module_directory']]
            commands = [base, base + ['check'], base + ['install']]
        else:
            base = ['/usr/bin/python3', 'waf']
            python_options = []
            if 'python' in profile:
                python_options = ['--pythondir=' + profile['python']['module_directory'],
                                  '--pythonarchdir=' + profile['python']['module_directory'],
                                  '--pyshebang=' + profile['python']['executable']]
                environment['PYTHONPATH'] = str(stage / profile['python']['module_directory'].lstrip('/'))
            commands = [base + ['configure', '--prefix=' + PREFIX] + source['options'] + python_options,
                        base + ['build'], base + ['check'],
                        base + ['install', '--destdir=' + str(stage.resolve())]]
        for command in commands:
            env = dict(environment)
            if command[-1] == 'install':
                env['DESTDIR'] = str(stage.resolve())
            run(command, directory, env, log)
    for name, data in helpers.items():
        destination = stage / ('usr/local/libexec' if name == 'timeservice.py' else 'usr/local/bin') / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        destination.chmod(0o755)
    files = inventory(stage)
    manifest = {'schema': 1, 'hostname': profile['hostname'], 'profile_sha256': expected,
                'sources': profile['sources'], 'packages': profile['packages'],
                'helpers': profile['helpers'], 'kernel': os.uname().release, 'files': files,
                'operation': 'update' if updating else 'build',
                'build_log_sha256': digest(regular_bytes(log))}
    if 'python' in profile:
        manifest['python'] = profile['python']
    path = output / 'release.json'
    path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + '\n')
    return {'manifest': str(path), 'sha256': digest(path.read_bytes())}


def safe_destination(relative):
    path = PurePosixPath(relative)
    if (path.is_absolute() or '..' in path.parts or path.as_posix() != relative
            or not relative.startswith('usr/local/')
            or relative.startswith(('usr/local/etc/', 'usr/local/var/'))):
        raise ValueError('invalid installed path')
    return Path('/') / relative


def snapshot(path):
    if not path.exists() and not path.is_symlink():
        return None
    info = path.lstat()
    result = {'uid': info.st_uid, 'gid': info.st_gid, 'mode': stat.S_IMODE(info.st_mode)}
    if path.is_symlink():
        result.update(type='symlink', target=os.readlink(path))
    elif stat.S_ISREG(info.st_mode):
        result.update(type='file', sha256=digest(regular_bytes(path)))
    else:
        raise ValueError('installed path is not file/link')
    return result


def read_release(path, expected):
    manifest = bound_json(path, expected)
    if manifest['schema'] != 1 or not manifest['files']:
        raise ValueError('invalid release manifest')
    for relative, record in manifest['files'].items():
        safe_destination(relative)
        if record.get('type') == 'file':
            if (set(record) != {'type', 'sha256', 'mode'}
                    or not re.fullmatch(r'[0-9a-f]{64}', record['sha256'])
                    or type(record['mode']) is not int or not 0 <= record['mode'] <= 0o777
                    or record['mode'] & 0o022):
                raise ValueError('unsafe release file record')
        elif record.get('type') == 'symlink':
            if set(record) != {'type', 'target'} or not isinstance(record['target'], str):
                raise ValueError('unsafe release symlink record')
        else:
            raise ValueError('unsupported release file type')
    return manifest


def inspect_install(path, expected, previous_path=None, previous_hash=None):
    manifest = read_release(path, expected)
    target_identity(manifest['hostname'])
    if manifest.get('operation') == 'update' and previous_path is None:
        raise ValueError('updates require the accepted previous release manifest')
    old_files = {}
    if previous_path is not None:
        previous = read_release(previous_path, previous_hash)
        if previous['hostname'] != manifest['hostname']:
            raise ValueError('previous release target mismatch')
        old_files = previous['files']
        for relative, old in old_files.items():
            current = snapshot(safe_destination(relative))
            if current is None or any(current.get(k) != v for k, v in old.items()):
                raise ValueError('previous application files drifted: ' + relative)
    return {'release_sha256': expected, 'previous_sha256': previous_hash,
            'hostname': manifest['hostname'], 'obsolete': sorted(set(old_files) - set(manifest['files'])),
            'files': {p: snapshot(safe_destination(p)) for p in sorted(set(manifest['files']) | set(old_files))}}


def install(path, expected, state_path, state_hash, journal,
            previous_path=None, previous_hash=None):
    """Copy verified native staged output; never execute build code as root.

    Journal and backups survive failure. A later rollback must be explicitly
    scoped; this entry point never restarts daemons, changes config or reboots.
    """
    if os.geteuid() != 0:
        raise ValueError('installation requires root')
    manifest = read_release(path, expected)
    target_identity(manifest['hostname'])
    require_no_package_applications()
    require_stopped_daemons()
    state = bound_json(state_path, state_hash)
    if state != inspect_install(path, expected, previous_path, previous_hash):
        raise ValueError('installation pre-state changed')
    payload = {}
    for relative, record in manifest['files'].items():
        source = path.parent / 'stage' / relative
        if record['type'] == 'file':
            payload[relative] = regular_bytes(source)
            if digest(payload[relative]) != record['sha256'] or record['mode'] & 0o7022:
                raise ValueError('staged payload/mode mismatch')
        elif record['type'] == 'symlink':
            if os.readlink(source) != record['target']:
                raise ValueError('staged symlink changed')
            # Resolve lexically against the approved destination list.
            resolved = os.path.normpath(str(PurePosixPath(relative).parent / record['target']))
            if PurePosixPath(record['target']).is_absolute() or resolved not in manifest['files']:
                raise ValueError('unapproved installed symlink target')
        else:
            raise ValueError('unsupported payload type')
    # Check existing parents before any persistent install effect.
    for relative in state['files']:
        for parent in safe_destination(relative).parents:
            if parent.exists() or parent.is_symlink():
                info = parent.lstat()
                if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
                    raise ValueError('unsafe installation parent: ' + str(parent))
    parent_info = journal.parent.lstat()
    if not stat.S_ISDIR(parent_info.st_mode) or parent_info.st_uid != 0 or parent_info.st_mode & 0o022:
        raise ValueError('unsafe journal parent')
    journal.mkdir(mode=0o700)
    backups = journal / 'before'
    backups.mkdir(mode=0o700)
    receipt = {'release_sha256': expected, 'before': state, 'installed': [],
               'removed': [], 'state': 'started'}
    receipt_path = journal / 'receipt.json'
    receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
    for relative in state['files']:
        destination = safe_destination(relative)
        before = state['files'][relative]
        if before and before['type'] == 'file':
            backup = backups / relative
            backup.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            backup.write_bytes(regular_bytes(destination))
            if digest(backup.read_bytes()) != before['sha256']:
                raise ValueError('rollback backup mismatch')
    if state != inspect_install(path, expected, previous_path, previous_hash):
        raise ValueError('pre-state changed during backup')
    for relative, record in manifest['files'].items():
        destination = safe_destination(relative)
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
        fd, temporary_name = tempfile.mkstemp(prefix='.clockmaker-', dir=destination.parent)
        temporary = Path(temporary_name)
        try:
            if record['type'] == 'file':
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(payload[relative])
                    stream.flush()
                    os.fchmod(stream.fileno(), record['mode'])
                    os.fchown(stream.fileno(), 0, 0)
                    os.fsync(stream.fileno())
            else:
                os.close(fd)
                temporary.unlink()
                os.symlink(record['target'], temporary)
                os.lchown(temporary, 0, 0)
            os.replace(temporary, destination)
            receipt['installed'].append(relative)
            receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
        finally:
            temporary.unlink(missing_ok=True)
    for relative in state['obsolete']:
        safe_destination(relative).unlink()
        receipt['removed'].append(relative)
        receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
    receipt['state'] = 'copied_not_activated'
    receipt['after'] = {'hostname': manifest['hostname'], 'files': {
        relative: snapshot(safe_destination(relative)) for relative in manifest['files']}}
    for relative, record in manifest['files'].items():
        current = receipt['after']['files'][relative]
        if current is None or current['uid'] != 0 or current['gid'] != 0 or any(
                current.get(k) != v for k, v in record.items()):
            raise ValueError('installed artifact verification failed')
    receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
    return {'journal': str(journal), 'state': receipt['state']}


def rollback(receipt_path, expected):
    if os.geteuid() != 0:
        raise ValueError('rollback requires root')
    for parent in (receipt_path, *receipt_path.absolute().parents):
        info = parent.lstat()
        if stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError('unsafe rollback receipt/parent')
    receipt = bound_json(receipt_path, expected)
    if receipt['state'] != 'copied_not_activated':
        raise ValueError('partial install requires state inspection and a new recovery definition')
    target_identity(receipt['before']['hostname'])
    require_stopped_daemons()
    before = receipt['before']['files']
    payload = {}
    for relative, previous in before.items():
        destination = safe_destination(relative)
        current = receipt['after']['files'].get(relative)
        if snapshot(destination) != current:
            raise ValueError('application changed after install; rollback held')
        if previous and previous['type'] == 'file':
            backup = receipt_path.parent / 'before' / relative
            payload[relative] = regular_bytes(backup)
            if digest(payload[relative]) != previous['sha256']:
                raise ValueError('rollback backup hash mismatch')
    # Record the new operation before its first file mutation; never rerun it.
    status = receipt_path.parent / 'rollback.json'
    with status.open('x') as stream:
        json.dump({'receipt_sha256': expected, 'state': 'started'}, stream)
    for relative, previous in before.items():
        destination = safe_destination(relative)
        if previous is None:
            destination.unlink(missing_ok=True)
            continue
        descriptor, name = tempfile.mkstemp(prefix='.clockmaker-rollback-', dir=destination.parent)
        try:
            if previous['type'] == 'file':
                with os.fdopen(descriptor, 'wb') as stream:
                    stream.write(payload[relative])
                    stream.flush()
                    os.fchown(stream.fileno(), previous['uid'], previous['gid'])
                    os.fchmod(stream.fileno(), previous['mode'])
                    os.fsync(stream.fileno())
            else:
                os.close(descriptor)
                Path(name).unlink()
                os.symlink(previous['target'], name)
                os.lchown(name, previous['uid'], previous['gid'])
            os.replace(name, destination)
        finally:
            Path(name).unlink(missing_ok=True)
    if any(snapshot(safe_destination(p)) != old for p, old in before.items()):
        raise ValueError('rollback verification failed; preserve original journal')
    status.write_text(json.dumps({'receipt_sha256': expected, 'state': 'restored_not_activated'}) + '\n')
    return {'state': 'restored_not_activated', 'receipt': str(status)}


def configure(profile_path, expected, output):
    """Stage reviewed per-host configuration; never replace live configuration."""
    profile = bound_json(profile_path, expected)
    if profile['schema'] != 1:
        raise ValueError('unsupported configuration profile')
    for name in ('gpsd', 'ntpd'):
        argv = profile['timeservice'][name]
        if not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv) or argv[0] != '/usr/local/sbin/' + name:
            raise ValueError('explicit source daemon argument arrays required')
    if '-N' not in profile['timeservice']['gpsd'] or '-n' not in profile['timeservice']['ntpd']:
        raise ValueError('both daemons must stay in foreground')
    device = profile['timeservice']['uart_device']
    if not isinstance(device, str) or not device.startswith('/dev/') or '..' in Path(device).parts:
        raise ValueError('explicit observed UART device required')
    gpsd = profile['timeservice']['gpsd'][1:]
    if (gpsd.count('-s') != 1 or
            gpsd[gpsd.index('-s') + 1:gpsd.index('-s') + 2] != ['115200'] or
            any(a.startswith('--speed') or (a.startswith('-s') and a != '-s') for a in gpsd) or
            device not in gpsd):
        raise ValueError('GPSD requires one explicit -s 115200 and the observed UART device')
    ntpd = profile['timeservice']['ntpd']
    if '-c' not in ntpd or ntpd[ntpd.index('-c') + 1:ntpd.index('-c') + 2] != ['/etc/ntp.conf']:
        raise ValueError('explicit canonical /etc/ntp.conf required')
    if '-u' not in ntpd or not ntpd[ntpd.index('-u') + 1:ntpd.index('-u') + 2]:
        raise ValueError('explicit reviewed NTP runtime user/group required')
    content = {}
    for key, name in (('ntp_config', 'ntp.conf'), ('unit', 'timeservice.service')):
        source = profile[key]
        data = regular_bytes(profile_path.parent / source['path'])
        if digest(data) != source['sha256']:
            raise ValueError('configuration input hash mismatch')
        content[name] = data
    content['ntpsec-timeservice.json'] = (json.dumps(profile['timeservice'], indent=2) + '\n').encode()
    output.mkdir(mode=0o700)
    files = {}
    for name, data in content.items():
        path = output / name
        path.write_bytes(data)
        mode = 0o644 if name.endswith('.service') else 0o640
        path.chmod(mode)
        files[name] = {'sha256': digest(data), 'uid': 0, 'gid': 0, 'mode': mode}
    manifest = {'hostname': profile['hostname'], 'profile_sha256': expected,
                'state': 'configuration_staged_not_installed', 'files': files}
    path = output / 'configuration.json'
    path.write_text(json.dumps(manifest, indent=2) + '\n')
    return {'manifest': str(path), 'sha256': digest(path.read_bytes())}


def parse_arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = ('build', 'update', 'configure', 'inspect', 'install', 'rollback')
    aliases = {prefix + alias: mode for mode in modes for prefix in ('-', '--')
               for alias in ((mode, 'config') if mode == 'configure' else (mode,))}
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in aliases:
        argv[0] = aliases[argv[0]]
    parser.epilog = ('Modes also accept --build/--update/--install/--config/--inspect/--rollback '
                     'and single-hyphen aliases. Legacy --mask/--secure/--strip are removed; '
                     '--config now stages application configuration, never OS changes.')
    parser.add_argument('mode', choices=modes)
    parser.add_argument('--input', type=Path, required=True, help='profile or release.json')
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--state', type=Path)
    parser.add_argument('--state-sha256')
    parser.add_argument('--journal', type=Path)
    parser.add_argument('--previous', type=Path, help='accepted previous release.json for an update')
    parser.add_argument('--previous-sha256')
    args = parser.parse_args(argv)
    if (args.previous is None) != (args.previous_sha256 is None):
        parser.error('--previous and --previous-sha256 must be supplied together')
    if args.mode in ('build', 'update', 'configure') and args.output is None:
        parser.error('--output required for build/update/configure')
    if args.mode == 'install' and None in (args.state, args.state_sha256, args.journal):
        parser.error('--state, --state-sha256 and --journal required for install')
    if args.mode not in ('build', 'update', 'configure') and args.output is not None:
        parser.error('--output applies only to build/update/configure')
    if args.mode != 'install' and any(value is not None for value in (args.state, args.state_sha256, args.journal)):
        parser.error('--state/--state-sha256/--journal apply only to install')
    if args.mode not in ('inspect', 'install') and args.previous is not None:
        parser.error('--previous/--previous-sha256 apply only to inspect/install')
    return parser, args


def main(argv=None):
    parser, args = parse_arguments(argv)
    try:
        if args.mode in ('build', 'update', 'configure'):
            result = (configure(args.input, args.sha256, args.output) if args.mode == 'configure'
                      else build(args.input, args.sha256, args.output, args.mode == 'update'))
        elif args.mode == 'inspect':
            result = inspect_install(args.input, args.sha256, args.previous, args.previous_sha256)
        elif args.mode == 'rollback':
            result = rollback(args.input, args.sha256)
        else:
            result = install(args.input, args.sha256, args.state, args.state_sha256, args.journal,
                             args.previous, args.previous_sha256)
        print(json.dumps(result, indent=2))
    except (OSError, ValueError, KeyError, subprocess.SubprocessError, tarfile.TarError) as exc:
        parser.exit(1, str(exc) + '\n')


if __name__ == '__main__':
    main()
