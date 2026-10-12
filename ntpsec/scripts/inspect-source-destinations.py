#!/usr/bin/python3
"""Bounded manifest-only observations; never imports or executes installed applications."""
import hashlib
import importlib.util
import json
import os
import re
from pathlib import Path
import stat
import subprocess
import sys
import sysconfig

UNITS = ('ssh.service', 'NetworkManager.service', 'ntpsec.service', 'ntpd.service',
         'gpsd.service', 'gpsd.socket', 'timeservice.service')


def load(path):
    definition = importlib.util.spec_from_file_location('inspected_clockmaker', path)
    module = importlib.util.module_from_spec(definition)
    definition.loader.exec_module(module)
    return module


def accepted_inputs(files):
    release, build, receipt = (json.loads(files[n]) for n in
                               ('release.json', 'build-spec.json', 'build-acceptance.json'))
    sha = lambda data: hashlib.sha256(data).hexdigest()
    if (receipt['state'] != 'mdns_source_build_accepted'
            or receipt['release_sha256'] != sha(files['release.json'])
            or receipt['spec_sha256'] != sha(files['build-spec.json'])
            or receipt['profile_sha256'] != release['profile_sha256']
            or receipt['acceptance']['ntpsec_mdns_registration'] is not True
            or any(receipt['acceptance'].get(k) is not True for k in
                   ('source_tests_passed', 'gpsd_selected_features', 'gpsd_ublox_driver',
                    'manuals_modules_versions_linkage', 'ntpsec_shm_nts_seccomp'))
            or receipt['acceptance']['release_sha256'] != receipt['release_sha256']
            or receipt['staged_files'] != len(release['files'])
            or receipt['inventory_records'] != len(build['inventory'])
            or receipt['transport_exit_status'] != 0 or receipt['worker_status'] != 0
            or receipt['live_installed'] is not False or receipt['services_activated'] is not False
            or release['hostname'] != build['hostname'] or release['kernel'] != build['kernel']
            or release['operation'] != 'build' or not 0 < len(release['files']) <= 512
            or release['helpers']['clockmaker.py'] != sha(files['clockmaker.py'])):
        raise ValueError('accepted first-install mDNS release/build/helper binding required')
    return release, build


def metadata(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    kind = ('symlink' if stat.S_ISLNK(info.st_mode) else 'directory' if stat.S_ISDIR(info.st_mode)
            else 'file' if stat.S_ISREG(info.st_mode) else 'special')
    return {'type': kind, 'uid': info.st_uid, 'gid': info.st_gid,
            'mode': stat.S_IMODE(info.st_mode), 'device': info.st_dev,
            'inode': info.st_ino, 'links': info.st_nlink, 'size': info.st_size,
            'mtime_ns': info.st_mtime_ns, 'ctime_ns': info.st_ctime_ns}


def parents(paths):
    observed = {}
    for path in paths:
        absent = False
        for parent in reversed(path.parents):
            name = str(parent)
            record = None if absent else metadata(parent)
            if record is None:
                absent = True
            elif (record['type'] != 'directory' or record['uid'] != 0
                    or record['gid'] != 0 or record['mode'] & 0o022):
                raise ValueError('unsafe destination ancestor: ' + name)
            if name in observed and observed[name] != record:
                raise ValueError('destination ancestor changed during observation')
            observed[name] = record
    return observed


def bounded_snapshot(path, helper, budget):
    before = metadata(path)
    if before is None:
        return None
    result = {k: before[k] for k in ('uid', 'gid', 'mode')}
    if before['type'] == 'symlink':
        result.update(type='symlink', target=os.readlink(path))
    elif before['type'] == 'file':
        if before['size'] > 64 * 1024**2 or before['size'] > budget[0]:
            raise ValueError('destination hash byte bound exceeded')
        data = helper.read(path, limit=64 * 1024**2)
        budget[0] -= len(data)
        result.update(type='file', sha256=hashlib.sha256(data).hexdigest())
    else:
        raise ValueError('non-file destination collision: ' + str(path))
    if metadata(path) != before:
        raise ValueError('destination changed while hashing: ' + str(path))
    return result


def command(argv):
    result = subprocess.run(argv, env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'},
                            capture_output=True, timeout=30, check=False)
    if result.returncode or result.stderr.strip() or len(result.stdout) > 2 * 1024**2:
        raise ValueError('read-only query failed or exceeded bound: ' + argv[0])
    return result.stdout.decode()


def observation():
    packages = {}
    raw = command(['/usr/bin/dpkg-query', '-W', '-f=${binary:Package}\t${Version}\t${db:Status-Abbrev}\n'])
    for line in raw.splitlines():
        name, version, status = line.split('\t')
        if name in packages:
            raise ValueError('duplicate installed package record')
        packages[name] = [version, status]
    if command(['/usr/bin/dpkg', '--audit']).strip():
        raise ValueError('dpkg audit findings')
    services = command(['/usr/bin/systemctl', 'show', '--no-pager',
        '--property=Id,LoadState,ActiveState,SubState,MainPID,NRestarts,FragmentPath,DropInPaths',
        *[name for name in UNITS if name.endswith('.service')]])
    services += command(['/usr/bin/systemctl', 'show', '--no-pager',
        '--property=Id,LoadState,ActiveState,SubState,FragmentPath,DropInPaths', 'gpsd.socket'])
    daemons = []
    for process in sorted(Path('/proc').glob('[0-9]*/comm')):
        try:
            with process.open('r') as stream:
                name = stream.read(64).strip()
            if name in ('ntpd', 'gpsd'):
                daemons.append({'pid': int(process.parent.name), 'name': name,
                                'uid': process.parent.stat().st_uid,
                                'executable': os.readlink(process.parent / 'exe')})
        except FileNotFoundError:
            continue
    if len(daemons) > 128:
        raise ValueError('daemon observation bound exceeded')
    return {'inventory': packages, 'services': services, 'active_daemons': daemons,
            'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
            'python': {'version': list(sys.version_info[:3]),
                       'module_directory': sysconfig.get_path('purelib'),
                       'extension_suffix': sysconfig.get_config_var('EXT_SUFFIX')}}


def collect(root, spec, helper, epoch):
    build = json.loads(helper.read(root / 'build-spec.json'))
    clock = load(root / 'clockmaker.py')
    release = clock.read_release(root / 'release.json', spec['members']['release.json'])
    if release['operation'] != 'build' or len(release['files']) > 512:
        raise ValueError('bounded first-install manifest required; no previous installed release supplied')
    before = observation()
    if (before['inventory'] != build['inventory'] or before['boot_id'] != build['boot_id']
            or before['python'] != build['python']):
        raise ValueError('accepted build target/package/Python state drift')
    destinations = [clock.safe_destination(name) for name in sorted(release['files'])]
    ancestry = parents(destinations)
    original = clock.snapshot
    try:
        clock.snapshot = lambda path: bounded_snapshot(path, helper, budget)
        budget = [512 * 1024**2]
        state = clock.inspect_install(root / 'release.json', spec['members']['release.json'])
        if parents(destinations) != ancestry:
            raise ValueError('destination parents changed')
        budget = [512 * 1024**2]
        if clock.inspect_install(root / 'release.json', spec['members']['release.json']) != state:
            raise ValueError('destination pre-state drift')
    finally:
        clock.snapshot = original
    if parents(destinations) != ancestry or observation() != before:
        raise ValueError('target or destination continuity failed')
    collisions = {name: ('identical' if all(record.get(k) == v for k, v in release['files'][name].items())
                         else 'different') for name, record in state['files'].items() if record is not None}
    return {'schema': 1, 'collected_epoch': epoch, 'hostname': spec['hostname'], 'kernel': spec['kernel'],
            'release_sha256': spec['members']['release.json'],
            'build_spec_sha256': spec['members']['build-spec.json'],
            'installation_state': state, 'parents': ancestry, 'observation': before,
            'collisions': collisions, 'continuity_unchanged': True,
            'package_mutation_authorized': False, 'application_mutation_authorized': False}


def validate(report, spec, release, build):
    if (type(report['collected_epoch']) is not int
            or not spec['prepared_epoch'] - 300 <= report['collected_epoch'] < spec['expires_epoch']):
        raise ValueError('inspection outside approved capture window')
    state = report['installation_state']
    if set(state) != {'release_sha256', 'previous_sha256', 'hostname', 'obsolete', 'files'}:
        raise ValueError('unexpected installation state fields')
    expected_parents = set()
    for name, record in state['files'].items():
        path = Path('/') / name
        if (not name.startswith('usr/local/') or '..' in path.parts
                or name.startswith(('usr/local/etc/', 'usr/local/var/'))
                or path.as_posix() != '/' + name):
            raise ValueError('unsafe observed destination')
        expected_parents.update(str(p) for p in path.parents)
        if record is None:
            continue
        kind = record.get('type')
        extra = {'sha256'} if kind == 'file' else {'target'} if kind == 'symlink' else set()
        if (not extra or set(record) != {'type', 'uid', 'gid', 'mode'} | extra
                or any(type(record[k]) is not int or record[k] < 0 for k in ('uid', 'gid', 'mode'))
                or record['mode'] > 0o7777
                or (kind == 'file' and (record['uid'] != 0 or record['gid'] != 0
                    or record['mode'] & 0o022 or not re.fullmatch(r'[a-f0-9]{64}', record['sha256'])))
                or (kind == 'symlink' and not isinstance(record['target'], str))):
            raise ValueError('invalid observed destination record')
    if set(report['parents']) != expected_parents:
        raise ValueError('complete ancestor coverage required')
    if report['parents'].get('/') is None:
        raise ValueError('root ancestor observation required')
    for name, record in report['parents'].items():
        if record is not None and (set(record) != {'type', 'uid', 'gid', 'mode', 'device', 'inode',
                'links', 'size', 'mtime_ns', 'ctime_ns'}
                or any(type(record[k]) is not int or record[k] < 0 for k in set(record) - {'type'})
                or record['mode'] > 0o7777 or record['type'] != 'directory' or record['uid'] != 0
                                  or record['gid'] != 0 or record['mode'] & 0o022):
            raise ValueError('unsafe observed ancestor')
        parent = str(Path(name).parent)
        if name != '/' and report['parents'][parent] is None and record is not None:
            raise ValueError('inconsistent missing ancestor')
    if (report['schema'] != 1 or report['hostname'] != spec['hostname'] or report['kernel'] != spec['kernel']
            or report['release_sha256'] != spec['members']['release.json']
            or report['build_spec_sha256'] != spec['members']['build-spec.json']
            or state['release_sha256'] != report['release_sha256'] or state['previous_sha256'] is not None
            or state['hostname'] != spec['hostname'] or state['obsolete'] != []
            or set(state['files']) != set(release['files'])
            or report['observation']['inventory'] != build['inventory']
            or report['observation']['boot_id'] != build['boot_id']
            or report['observation']['python'] != build['python']
            or report['continuity_unchanged'] is not True
            or report['package_mutation_authorized'] is not False
            or report['application_mutation_authorized'] is not False):
        raise ValueError('complete bound destination observation required')
    if (not isinstance(report['observation']['services'], str)
            or len(report['observation']['services']) > 4 * 1024**2
            or not isinstance(report['observation']['active_daemons'], list)
            or len(report['observation']['active_daemons']) > 128):
        raise ValueError('bounded service/process observations required')
    expected = {name: ('identical' if all(record.get(k) == v for k, v in release['files'][name].items())
                      else 'different') for name, record in state['files'].items() if record is not None}
    if report['collisions'] != expected:
        raise ValueError('collision classification mismatch')
