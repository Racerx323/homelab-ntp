#!/usr/bin/python3
"""Static runtime inputs and installed-byte verification; no application/device execution."""
import base64
import glob
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import sysconfig

QUERIES = {
    'addresses': ['/usr/sbin/ip', '-j', 'address', 'show'],
    'ipv4_routes': ['/usr/sbin/ip', '-j', '-4', 'route', 'show', 'table', 'all'],
    'ipv6_routes': ['/usr/sbin/ip', '-j', '-6', 'route', 'show', 'table', 'all'],
    'connections': ['/usr/bin/nmcli', '-t', '-f', 'NAME,UUID,TYPE,DEVICE', 'connection', 'show'],
    'network_devices': ['/usr/bin/nmcli', '-t', '-f', 'GENERAL,IP4,IP6', 'device', 'show'],
    'linker_cache': ['/usr/sbin/ldconfig', '-p'],
    'time_units': ['/usr/bin/systemctl', 'show', '--no-pager',
        '--property=Id,LoadState,ActiveState,SubState,FragmentPath,DropInPaths,User,Group,ExecStart',
        'timeservice.service', 'ntpd.service', 'ntpsec.service', 'gpsd.service',
        'avahi-daemon.service', 'systemd-timesyncd.service', 'chrony.service'],
    'accounts': ['/usr/bin/getent', '-s', 'files', 'passwd', 'root', 'ama', 'ntp', 'ntpd', 'gpsd'],
    'groups': ['/usr/bin/getent', '-s', 'files', 'group', 'root', 'ama', 'ntp', 'ntpd', 'gpsd', 'dialout', 'tty'],
}
FILE_PATHS = ('/boot/firmware/config.txt', '/boot/firmware/cmdline.txt',
    '/boot/firmware/usercfg.txt', '/boot/firmware/syscfg.txt', '/etc/ntp.conf',
    '/etc/ntpsec/ntp.conf', '/etc/default/gpsd', '/etc/ntpsec-timeservice.json',
    '/etc/ld.so.conf', '/etc/systemd/system/timeservice.service')
GLOBS = ('/etc/ld.so.conf.d/*.conf', '/etc/systemd/system/timeservice.service.d/*.conf')
REQUIREMENTS = ('observed_uart_pps_rtc_and_boot_includes', 'verified_native_loader_python_and_path',
    'explicit_runtime_accounts_and_device_access', 'fixed_dual_stack_network_profile_and_dns',
    'reviewed_ntp_shm_nts_restrictions_drift_and_leap_paths', 'ntpd_foreground_mdns_and_avahi_scope',
    'gpsd_foreground_115200_and_listener_scope', 'combined_service_and_recovery',
    'leap_maintenance_and_needrestart_mail_cron_acceptance')
DEVICE_GLOBS = ('/dev/serial[01]', '/dev/ttyAMA[0-9]*', '/dev/ttyS[0-9]*', '/dev/pps[0-9]*', '/dev/rtc[0-9]*')
SYS_GLOBS = ('/sys/class/tty/ttyAMA[0-9]*', '/sys/class/tty/ttyS[0-9]*',
             '/sys/class/pps/pps[0-9]*', '/sys/class/rtc/rtc[0-9]*')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def load(path):
    spec = importlib.util.spec_from_file_location('runtime_' + path.stem.replace('-', '_'), path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def recipe(data):
    value = json.loads(data)
    if (set(value) != {'schema', 'queries', 'protected_files', 'protected_globs',
            'configuration_requirements', 'activation_authorized', 'receiver_io_authorized'}
            or value['schema'] != 1 or value['queries'] != list(QUERIES)
            or value['protected_files'] != list(FILE_PATHS) or value['protected_globs'] != list(GLOBS)
            or value['configuration_requirements'] != list(REQUIREMENTS)
            or value['activation_authorized'] is not False or value['receiver_io_authorized'] is not False):
        raise ValueError('fixed read-only runtime recipe required')
    return value


def accepted_inputs(files, inspector):
    release, build = inspector.accepted_inputs(files)
    accepted, readback, previous = (json.loads(files[n]) for n in
        ('installation-acceptance.json', 'installation-readback.json', 'installation-spec.json'))
    report = readback['report']
    if (accepted['state'] != 'native_installation_accepted'
            or accepted['bundle_sha256'] != json.loads(files['installation-bundle-sha256.json'])
            or readback['bundle_sha256'] != accepted['bundle_sha256']
            or readback['worker_status'] != 0 or readback['transport_exit_status'] != 0
            or report['state'] != 'installation_completed' or report['native_state'] != 'copied_not_activated'
            or report['spec_sha256'] != sha(files['installation-spec.json'])
            or previous['hostname'] != release['hostname'] or previous['kernel'] != release['kernel']
            or previous['members']['release.json'] != sha(files['release.json'])
            or previous['members']['build-spec.json'] != sha(files['build-spec.json'])
            or previous['members']['build-acceptance.json'] != sha(files['build-acceptance.json'])
            or previous['members']['clockmaker.py'] != sha(files['clockmaker.py'])
            or accepted['release_sha256'] != sha(files['release.json'])
            or accepted['installed_files'] != len(release['files']) or report['installed_files'] != len(release['files'])
            or accepted['terminal_sha256'] != report['terminal_sha256']
            or not re.fullmatch(r'[a-f0-9]{64}', accepted['terminal_sha256'])
            or any(report[k] is not False or accepted[k] is not False for k in
                   ('services_activated', 'library_cache_changed'))
            or report['continuity_unchanged'] is not True):
        raise ValueError('accepted native installation binding required')
    evidence = {}
    for name, record in report['evidence'].items():
        raw = base64.b64decode(record['base64'], validate=True)
        if sha(raw) != record['sha256']:
            raise ValueError('native evidence hash mismatch')
        evidence[name] = json.loads(raw)
    if evidence != accepted['evidence']:
        raise ValueError('native acceptance/readback evidence mismatch')
    receipt = evidence['journal/receipt.json']; before = evidence['before.json']
    if (receipt['state'] != 'copied_not_activated' or receipt['release_sha256'] != sha(files['release.json'])
            or receipt['before'] != before['state'] or receipt['after']['hostname'] != release['hostname']
            or set(receipt['installed']) != set(release['files'])
            or len(receipt['installed']) != len(release['files']) or receipt['removed']
            or set(receipt['after']['files']) != set(release['files'])
            or set(before['state']['files']) != set(release['files'])
            or any(v is not None for v in before['state']['files'].values())
            or before['observation']['inventory'] != build['inventory']
            or before['observation']['boot_id'] != build['boot_id']
            or before['observation']['python'] != build['python']):
        raise ValueError('native receipt manifest/baseline mismatch')
    for name, expected in release['files'].items():
        record = receipt['after']['files'][name]
        if record['uid'] != 0 or record['gid'] != 0 or any(record.get(k) != v for k, v in expected.items()):
            raise ValueError('native installed entry mismatch')
    native_parents(files)
    recipe(files['runtime-recipe.json'])
    installed = {'release_sha256': sha(files['release.json']), 'previous_sha256': None,
        'hostname': receipt['after']['hostname'], 'obsolete': [], 'files': receipt['after']['files']}
    return release, build, before['observation'], installed


def native_parents(files):
    evidence = json.loads(files['installation-acceptance.json'])['evidence']
    parents = evidence['before.json']['parents']; created = evidence['created-directories.json']
    if set(created) != {n for n,r in parents.items() if r is None}:
        raise ValueError('accepted created-directory coverage mismatch')
    result = {**parents, **created}
    for name,record in result.items():
        if (record is None or record['type'] != 'directory' or record['uid'] != 0 or record['gid'] != 0
                or record['mode'] & 0o022 or name in created and record['mode'] != 0o755
                or any(type(record[k]) is not int or record[k]<0 for k in ('device','inode'))):
            raise ValueError('unsafe accepted native directory identity')
    return result


def verify_parents(observed, expected):
    fields = ('type','uid','gid','mode','device','inode')
    if set(observed) != set(expected) or any(record is None or any(record[k]!=expected[n][k] for k in fields)
                                           for n,record in observed.items()):
        raise ValueError('accepted installed parent identity drift')


def query(argv, account_kind=None):
    result = subprocess.run(argv, env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LC_ALL': 'C',
        'SYSTEMD_PAGER': '', 'PAGER': 'cat'}, capture_output=True, timeout=15, check=False)
    if len(result.stdout) > 2 * 1024**2 or len(result.stderr) > 65536:
        raise ValueError('runtime query output bound exceeded')
    if result.returncode not in ((0, 2) if account_kind else (0,)) or result.stderr.strip():
        raise ValueError('runtime query failed: ' + argv[0])
    text = result.stdout.decode()
    if account_kind:
        entries = {}
        for line in text.splitlines():
            fields = line.split(':'); name = fields[0]
            if name in entries or len(fields) != (7 if account_kind == 'accounts' else 4):
                raise ValueError('malformed local account/group query')
            entries[name] = ({'uid': int(fields[2]), 'gid': int(fields[3]), 'home': fields[5], 'shell': fields[6]}
                if account_kind == 'accounts' else {'gid': int(fields[2]), 'members': fields[3].split(',') if fields[3] else []})
        return {'exit_status': result.returncode, 'entries': entries,
                'missing': sorted(set(argv[4:]) - set(entries))}
    return {'exit_status': result.returncode, 'stdout': text}


def protected_files(helper):
    names = set(FILE_PATHS)
    for pattern in GLOBS:
        names.update(glob.glob(pattern))
    if len(names) > 64:
        raise ValueError('runtime configuration file count bound exceeded')
    output = {}; total = 0
    for name in sorted(names):
        path = Path(name)
        try:
            data = helper.read(path, limit=256 * 1024)
        except FileNotFoundError:
            output[name] = None; continue
        total += len(data)
        if total > 4 * 1024**2:
            raise ValueError('runtime configuration total bound exceeded')
        output[name] = {'sha256': sha(data), 'base64': base64.b64encode(data).decode()}
    return output


def devices(helper):
    output = {'nodes': {}, 'sysfs': {}}
    for pattern in DEVICE_GLOBS:
        for name in sorted(glob.glob(pattern)):
            path = Path(name); info = path.lstat(); target = None
            if stat.S_ISLNK(info.st_mode):
                if info.st_uid != 0 or info.st_gid != 0:
                    raise ValueError('unsafe device alias')
                resolved = path.resolve(strict=True)
                if resolved.parent != Path('/dev'):
                    raise ValueError('device alias escapes /dev')
                target = str(resolved); info = resolved.lstat()
            if not stat.S_ISCHR(info.st_mode):
                raise ValueError('expected character device')
            output['nodes'][name] = {'uid': info.st_uid, 'gid': info.st_gid,
                'mode': stat.S_IMODE(info.st_mode), 'major': os.major(info.st_rdev),
                'minor': os.minor(info.st_rdev), 'target': target}
    for pattern in SYS_GLOBS:
        for name in sorted(glob.glob(pattern)):
            resolved = Path(name).resolve(strict=True)
            if not str(resolved).startswith('/sys/devices/'):
                raise ValueError('unexpected sysfs class target')
            details = {'target': str(resolved)}
            for child in ('name', 'path'):
                try:
                    details[child] = helper.read(resolved / child, limit=4096).decode().strip()
                except FileNotFoundError:
                    pass
            driver = resolved / 'device/driver'
            if driver.is_symlink():
                target = str(driver.resolve(strict=True))
                if not target.startswith('/sys/bus/'):
                    raise ValueError('unexpected device driver path')
                details['driver'] = target
            output['sysfs'][name] = details
    if len(output['nodes']) > 64 or len(output['sysfs']) > 64:
        raise ValueError('runtime device count bound exceeded')
    return output


def installed_state(root, spec, helper, inspector, release):
    clock = inspector.load(root / 'clockmaker.py'); paths = [clock.safe_destination(n) for n in sorted(release['files'])]
    ancestry = inspector.parents(paths); budget = [512 * 1024**2]
    clock.snapshot = lambda path: inspector.bounded_snapshot(path, helper, budget)
    state = clock.inspect_install(root / 'release.json', spec['members']['release.json'])
    return state, ancestry


def python_environment():
    # The service uses isolated /usr/bin/python3; this is its root search context.
    return {'context': 'isolated_root', 'executable': sys.executable,
        'search_paths': list(sys.path), 'scheme_paths': sysconfig.get_paths(),
        'effective_path': os.environ.get('PATH', ''), 'application_imports_executed': False}


def collect(root, spec, helper, epoch):
    files = {n: helper.read(root / n) for n in spec['members']}
    inspector = load(root / 'inspect-source-destinations.py')
    release, build, baseline, expected = accepted_inputs(files, inspector)
    observed = inspector.observation()
    if observed != baseline or observed['active_daemons']:
        raise ValueError('accepted installation continuity/daemon state drift')
    state, parents = installed_state(root, spec, helper, inspector, release)
    if state != expected:
        raise ValueError('installed release drift')
    verify_parents(parents,native_parents(files))
    configs = protected_files(helper); hardware = devices(helper)
    results = {name: query(argv, name if name in ('accounts', 'groups') else None) for name, argv in QUERIES.items()}
    elf = [n for n, r in release['files'].items() if r['type'] == 'file' and
           (n in ('usr/local/sbin/gpsd', 'usr/local/sbin/ntpd') or re.search(r'\.so(?:\.[0-9.]+)?$', n))]
    if not 2 <= len(elf) <= 16:
        raise ValueError('bounded native ELF set required')
    results['elf_dependencies'] = {n: query(['/usr/bin/readelf', '-d', '--', '/' + n]) for n in sorted(elf)}
    if len(json.dumps(results).encode()) > 2 * 1024**2:
        raise ValueError('runtime queries total bound exceeded')
    if (installed_state(root, spec, helper, inspector, release) != (state, parents)
            or inspector.observation() != observed or protected_files(helper) != configs or devices(helper) != hardware):
        raise ValueError('runtime collection continuity failed')
    return {'schema': 1, 'collected_epoch': epoch, 'hostname': spec['hostname'], 'kernel': spec['kernel'],
        'release_sha256': spec['members']['release.json'], 'installation_acceptance_sha256': spec['members']['installation-acceptance.json'],
        'runtime_recipe_sha256': spec['members']['runtime-recipe.json'], 'installed_state': state,
        'parents': parents, 'observation': observed, 'protected_files': configs, 'devices': hardware,
        'python_environment': python_environment(),
        'queries': results, 'continuity_unchanged': True, 'configuration_ready': False,
        'application_mutation_authorized': False, 'package_mutation_authorized': False,
        'activation_authorized': False, 'receiver_io_authorized': False}


def validate(report, spec, release, build):
    if (report['schema'] != 1 or report['hostname'] != spec['hostname'] or report['kernel'] != spec['kernel']
            or type(report['collected_epoch']) is not int
            or not spec['prepared_epoch'] - 300 <= report['collected_epoch'] < spec['expires_epoch']
            or any(report[k] != spec['members'][n] for k, n in (
                ('release_sha256','release.json'), ('installation_acceptance_sha256','installation-acceptance.json'),
                ('runtime_recipe_sha256','runtime-recipe.json')))
            or report['continuity_unchanged'] is not True or report['configuration_ready'] is not False
            or any(report[k] is not False for k in ('application_mutation_authorized', 'package_mutation_authorized',
                                                  'activation_authorized', 'receiver_io_authorized'))
            or report['observation']['inventory'] != build['inventory']
            or report['observation']['boot_id'] != build['boot_id'] or report['observation']['python'] != build['python']
            or report['observation']['active_daemons'] or set(report['installed_state']['files']) != set(release['files'])
            or set(report['queries']) != set(QUERIES) | {'elf_dependencies'}
            or not set(FILE_PATHS) <= set(report['protected_files']) or len(report['protected_files']) > 64
            or set(report['devices']) != {'nodes', 'sysfs'}):
        raise ValueError('complete bound static runtime discovery required')
    inspector = load(Path(__file__).with_name('inspect-source-destinations.py'))
    comparable = dict(report, installation_state=report['installed_state'],
        build_spec_sha256=spec['members']['build-spec.json'],
        collisions=dict.fromkeys(release['files'], 'identical'))
    inspector.validate(comparable, spec, release, build)
    environment = report['python_environment']
    if (set(environment) != {'context','executable','search_paths','scheme_paths','effective_path','application_imports_executed'}
            or environment['context'] != 'isolated_root' or environment['application_imports_executed'] is not False
            or not isinstance(environment['search_paths'],list) or len(environment['search_paths'])>64
            or not isinstance(environment['scheme_paths'],dict) or len(environment['scheme_paths'])>32
            or any(not isinstance(v,str) or len(v)>4096 for v in
                   [environment['executable'],environment['effective_path'],*environment['search_paths'],*environment['scheme_paths'].values()])):
        raise ValueError('bounded static isolated Python/PATH context required')
    for name, expected in release['files'].items():
        current = report['installed_state']['files'][name]
        if current is None or current['uid'] != 0 or current['gid'] != 0 or any(current.get(k) != v for k,v in expected.items()):
            raise ValueError('installed release manifest mismatch')
    for record in report['protected_files'].values():
        if record is not None:
            raw = base64.b64decode(record['base64'], validate=True)
            if len(raw) > 256 * 1024 or sha(raw) != record['sha256']:
                raise ValueError('runtime configuration evidence mismatch')
    if sum(len(base64.b64decode(r['base64'])) for r in report['protected_files'].values() if r) > 4 * 1024**2:
        raise ValueError('runtime configuration total bound exceeded')
    for name in report['protected_files']:
        if name not in FILE_PATHS and not any(Path(name).match(pattern) for pattern in GLOBS):
            raise ValueError('unapproved configuration path')
    expected_elf = {n for n,r in release['files'].items() if r['type'] == 'file' and
        (n in ('usr/local/sbin/gpsd', 'usr/local/sbin/ntpd') or re.search(r'\.so(?:\.[0-9.]+)?$', n))}
    if set(report['queries']['elf_dependencies']) != expected_elf:
        raise ValueError('complete installed ELF coverage required')
    for name, result in report['queries'].items():
        if name == 'elf_dependencies':
            records = result.values()
        elif name in ('accounts', 'groups'):
            requested = set(QUERIES[name][4:]); entries = result['entries']
            if (result['exit_status'] not in (0,2) or not set(entries) <= requested
                    or result['missing'] != sorted(requested-set(entries))):
                raise ValueError('local account/group coverage mismatch')
            for entry in entries.values():
                keys = {'uid','gid','home','shell'} if name=='accounts' else {'gid','members'}
                if set(entry)!=keys or any(type(entry[k]) is not int or entry[k]<0 for k in keys & {'uid','gid'}):
                    raise ValueError('invalid sanitized local account/group metadata')
            continue
        else:
            records = (result,)
        for record in records:
            if record['exit_status'] != 0 or len(record['stdout'].encode()) > 2 * 1024**2:
                raise ValueError('runtime query evidence status/bound mismatch')
    for name in ('addresses','ipv4_routes','ipv6_routes'):
        if not isinstance(json.loads(report['queries'][name]['stdout']),list):
            raise ValueError('network query JSON list required')
    for kind, records in report['devices'].items():
        if len(records)>64:
            raise ValueError('device evidence count bound exceeded')
        for name, record in records.items():
            patterns=DEVICE_GLOBS if kind=='nodes' else SYS_GLOBS
            if not any(Path(name).match(pattern) for pattern in patterns):
                raise ValueError('unapproved device evidence path')
            if kind=='nodes' and (set(record)!={'uid','gid','mode','major','minor','target'}
                    or any(type(record[k]) is not int or record[k]<0 for k in ('uid','gid','mode','major','minor'))
                    or record['mode']>0o7777
                    or record['target'] is not None and Path(record['target']).parent!=Path('/dev')):
                raise ValueError('invalid character-device metadata')
            if kind=='sysfs' and (not set(record)<={'target','name','path','driver'}
                    or not record['target'].startswith('/sys/devices/')
                    or any(not isinstance(v,str) or len(v)>4096 for v in record.values())
                    or 'driver' in record and not record['driver'].startswith('/sys/bus/')):
                raise ValueError('invalid sysfs metadata')
