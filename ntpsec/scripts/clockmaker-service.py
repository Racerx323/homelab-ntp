#!/usr/bin/python3
"""Fresh-host configuration and activation for clockmaker; no historical inputs."""
import fcntl
from contextlib import contextmanager
import importlib.util
import ipaddress
import json
import math
import secrets
import os
from pathlib import Path
import pwd
import grp
import signal
import shlex
import socket
import stat
import subprocess
import time


def load(path):
    spec = importlib.util.spec_from_file_location(path.stem.replace('-', '_'), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


c = load(Path(__file__).with_name('clockmaker.py'))
UNIT = 'timeservice.service'
BOOTSTRAP = 'systemd-timesyncd.service'
DESTINATIONS = {'ntp.conf': '/etc/ntp.conf',
                'ntpsec-timeservice.json': '/etc/ntpsec-timeservice.json',
                'timeservice.service': '/etc/systemd/system/timeservice.service',
                'leap-seconds.list': '/var/lib/ntpsec/leap-seconds.list'}
DIRECTORIES = ('/var/lib/ntpsec', '/var/lib/ntpsec/drift', '/var/log/ntpstats')
CONFLICTS = ('ntp.service', 'ntpsec.service', 'ntpd.service', 'gpsd.service',
             'gpsd.socket', 'chrony.service', 'chronyd.service')
ENV = {'PATH': '/usr/local/bin:/usr/local/sbin:/usr/bin:/usr/sbin:/bin', 'LC_ALL': 'C'}


def protected(path, missing=False):
    for parent in (path, *path.absolute().parents):
        if missing and not os.path.lexists(parent):
            continue
        info = parent.lstat()
        if stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError('unprotected path: ' + str(parent))
        if parent != path and not stat.S_ISDIR(info.st_mode):
            raise ValueError('non-directory parent')


def atomic(path, data, mode=0o600, uid=0, gid=0):
    import tempfile
    protected(path.parent)
    fd, name = tempfile.mkstemp(prefix='.clockmaker-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data); stream.flush()
            os.fchown(stream.fileno(), uid, gid); os.fchmod(stream.fileno(), mode)
            os.fsync(stream.fileno())
        os.replace(name, path)
        descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(descriptor)
        finally: os.close(descriptor)
    finally:
        Path(name).unlink(missing_ok=True)


def save(path, value):
    atomic(path, (json.dumps(value, sort_keys=True, indent=2) + '\n').encode())


def command(argv, journal=None, timeout=20, allowed=(0,)):
    result = None; failure = None
    try:
        result = subprocess.run(argv, capture_output=True, timeout=timeout, env=ENV)
        if result.returncode not in allowed:
            raise ValueError('native command failed: ' + repr(argv) + ': ' + result.stderr.decode(errors='replace')[:1000])
        return result.stdout.decode()
    except BaseException as error:
        failure = error
        raise
    finally:
        if journal is not None:
            row = {'argv': argv, 'returncode': None if result is None else result.returncode,
                   'stdout': ((getattr(failure, 'output', None) or b'') if result is None else result.stdout).decode(errors='replace'),
                   'stderr': ((getattr(failure, 'stderr', None) or b'') if result is None else result.stderr).decode(errors='replace'),
                   'error': None if failure is None else str(failure)}
            with (journal / 'commands.jsonl').open('a') as stream:
                os.chmod(stream.name, 0o600)
                stream.write(json.dumps(row) + '\n'); stream.flush(); os.fsync(stream.fileno())


def unit(name, journal=None):
    text = command(['/usr/bin/systemctl', 'show', name, '--no-pager',
                    '--property=LoadState,ActiveState,SubState,UnitFileState,MainPID,NRestarts,InvocationID,FragmentPath,DropInPaths'],
                   journal, allowed=(0, 4))
    rows = dict(line.split('=', 1) for line in text.splitlines() if '=' in line)
    required = {'LoadState', 'ActiveState', 'UnitFileState'}
    if not name.endswith('.timer'): required.add('MainPID')
    if not required.issubset(rows):
        raise ValueError('incomplete service state: ' + name)
    return rows


def installed(release):
    c.target_identity(release['hostname'])
    for name, record in release['files'].items():
        path = c.safe_destination(name)
        protected(path.parent)
        current = c.snapshot(path)
        if current is None or current['uid'] != 0 or current['gid'] != 0 or any(current.get(k) != v for k, v in record.items()):
            raise ValueError('installed release drift: ' + name)
    required = {'usr/local/sbin/ntpd', 'usr/local/sbin/gpsd', 'usr/local/bin/gpspipe',
                'usr/local/bin/ntpshmmon', 'usr/local/libexec/timeservice.py',
                'usr/local/libexec/gpsd-pairing.py', 'usr/local/libexec/measure-time-service.py',
                'usr/local/libexec/check-time-client.py'}
    if not required.issubset(release['files']):
        raise ValueError('release lacks activation helpers/tools; rebuild with fleet prepare')


def inputs(path, checksum):
    spec = c.bound_json(path, checksum)
    if set(spec) != {'schema', 'hostname', 'release', 'configuration', 'health', 'client'} or spec['schema'] != 1:
        raise ValueError('closed service deployment profile required')
    release = c.read_release(path.parent / spec['release']['path'], spec['release']['sha256'])
    profile, content = c.configuration_inputs(path.parent / spec['configuration']['path'], spec['configuration']['sha256'])
    if release['hostname'] != spec['hostname'] or profile['hostname'] != spec['hostname']:
        raise ValueError('service target binding mismatch')
    if set(content) != set(DESTINATIONS):
        raise ValueError('configuration needs a supplied leapfile; no implicit download')
    directives = {}
    for line in content['ntp.conf'].decode().splitlines():
        fields = shlex.split(line, comments=True)
        if not fields: continue
        if fields[0] == 'includefile': raise ValueError('unbound NTP include is unsupported')
        if fields[0] in ('driftfile', 'statsdir', 'leapfile'):
            if fields[0] in directives or len(fields) != 2: raise ValueError('ambiguous NTP storage directive')
            directives[fields[0]] = fields[1].rstrip('/')
    if directives != {'driftfile': '/var/lib/ntpsec/drift/ntp.drift',
                       'statsdir': '/var/log/ntpstats', 'leapfile': '/var/lib/ntpsec/leap-seconds.list'}:
        raise ValueError('explicit canonical NTP runtime paths required')
    expiry_rows = [line.split() for line in content['leap-seconds.list'].decode().splitlines()
                   if line.startswith('#@')]
    expiry = [row[1] for row in expiry_rows if len(row) == 2]
    if len(expiry_rows) != 1: raise ValueError('one leapfile expiry required')
    if len(expiry) != 1 or not expiry[0].isdigit() or int(expiry[0]) - 2208988800 <= time.time():
        raise ValueError('unexpired supplied leapfile required')
    config = profile['timeservice']
    # Reuse the supervisor's actual argument/gate validation without starting it.
    supervisor_path = Path(__file__).with_name('timeservice.py')
    if not supervisor_path.exists():
        supervisor_path = Path('/usr/local/libexec/timeservice.py')
    supervisor = load(supervisor_path)
    supervisor.validate(config); supervisor.validate_startup_gate(config)
    if config['uart_device'] != '/dev/serial0' or '/dev/pps0' not in config['gpsd']:
        raise ValueError('current pairing implementation requires serial0 and pps0')
    user, group = config['ntpd'][config['ntpd'].index('-u') + 1].split(':')
    uid = pwd.getpwuid(int(user)).pw_uid if user.isdigit() else pwd.getpwnam(user).pw_uid
    gid = grp.getgrgid(int(group)).gr_gid if group.isdigit() else grp.getgrnam(group).gr_gid
    if uid == 0 or gid == 0:
        raise ValueError('pre-provisioned non-root NTP account required')
    h = spec['health']
    if set(h) != {'timeout_seconds', 'interval_seconds', 'consecutive_samples', 'offset_ms', 'jitter_ms', 'peers', 'ipv4', 'ipv6', 'credentials'}:
        raise ValueError('closed health criteria required')
    for name, low, high in (('timeout_seconds', 90, 1200), ('interval_seconds', 30, 60), ('consecutive_samples', 3, 10)):
        if type(h[name]) is not int or not low <= h[name] <= high:
            raise ValueError('invalid health bound: ' + name)
    for name in ('offset_ms', 'jitter_ms'):
        if type(h[name]) not in (int, float) or not math.isfinite(h[name]) or not 0 < h[name] <= (5 if name == 'offset_ms' else 1):
            raise ValueError('finite positive timing limit required')
    if (not isinstance(h['peers'], list) or len(h['peers']) != 5
            or not all(isinstance(v, str) and v for v in h['peers']) or len(set(h['peers'])) != len(h['peers'])):
        raise ValueError('explicit unique expected peers required')
    for name, version in (('ipv4', 4), ('ipv6', 6)):
        address = ipaddress.ip_address(h[name])
        if address.version != version or address.is_unspecified or address.is_multicast or address.is_loopback:
            raise ValueError('fixed non-loopback target address required')
    refs = {'SHM(' + value[3:] + ')' for value in config['startup_gate']['units'].values()}
    if not refs <= set(h['peers']) or any(p.startswith('SHM(') for p in set(h['peers']) - refs):
        raise ValueError('two observed refclocks and three NTS peers required')
    credentials = h['credentials']
    if set(credentials) != {'ntpd', 'gpsd'}:
        raise ValueError('explicit daemon credentials required')
    for ids in credentials.values():
        if set(ids) != {'uid', 'gid'} or any(not isinstance(v, list) or len(v) != 4 or
                any(type(i) is not int or i < 0 for i in v) for v in ids.values()):
            raise ValueError('four real/effective/saved/filesystem IDs required')
    if credentials['ntpd'] != {'uid': [uid]*4, 'gid': [gid]*4}:
        raise ValueError('NTP credentials must match non-root account')
    client = spec['client']
    if set(client) != {'hostname', 'ipv4', 'ipv6'} or not client['hostname'] or client['hostname'] == spec['hostname']:
        raise ValueError('explicit independent client required')
    for key, version in (('ipv4', 4), ('ipv6', 6)):
        address = ipaddress.ip_address(client[key])
        if address.version != version or address.is_unspecified or address.is_multicast or address.is_loopback or client[key] == h[key]:
            raise ValueError('independent client source address required')
    h['pps_peer'] = 'SHM(' + config['startup_gate']['units']['PPS'][3:] + ')'
    return spec, release, content, (uid, gid)


def directory_metadata(name, account):
    return (0, 0, 0o755) if name == DIRECTORIES[0] else (*account, 0o750)


def hardware(config):
    result = {}
    for name in (config['uart_device'], '/dev/pps0'):
        path = Path(name).resolve(strict=True)
        st = path.stat()
        if not stat.S_ISCHR(st.st_mode) or st.st_uid != 0:
            raise ValueError('root-owned UART/PPS character device required')
        result[name] = {'path': str(path), 'rdev': st.st_rdev, 'uid': st.st_uid, 'gid': st.st_gid}
    return result


def journal_errors(boot, since, journal=None):
    raw = command(['/usr/bin/journalctl', '--quiet', '--no-pager', '--output=json',
                   '--boot=' + boot, '--priority=err',
                   '--unit=' + UNIT, '--unit=avahi-daemon.service', '--lines=1001'], journal)
    rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
    if len(rows) >= 1001 or any(int(row['__MONOTONIC_TIMESTAMP']) >= since for row in rows):
        raise ValueError('service/Avahi error journal requires assessment')


def preflight(path, checksum, phase):
    if phase not in ('apply-configuration', 'activate'):
        raise ValueError('unsupported service preflight')
    spec, release, content, account = inputs(path, checksum)
    if os.geteuid() != 0: raise ValueError('service preflight requires root observations')
    installed(release); c.require_no_package_applications(); c.require_stopped_daemons()
    for tool in ('systemctl', 'systemd-run', 'systemd-analyze', 'journalctl', 'ps', 'python3'):
        if not os.access('/usr/bin/' + tool, os.X_OK): raise ValueError('missing native command: ' + tool)
    journal_errors(Path('/proc/sys/kernel/random/boot_id').read_text().strip(), int(time.monotonic()*1000000))
    devices = hardware(json.loads(content['ntpsec-timeservice.json']))
    service = unit(UNIT); bootstrap = unit(BOOTSTRAP)
    if (service['ActiveState'] != 'inactive' or service['UnitFileState'] not in ('', 'disabled')
            or service.get('DropInPaths') or service['LoadState'] not in ('loaded', 'not-found')):
        raise ValueError('fresh inactive/disabled service without overrides required')
    if (bootstrap['LoadState'] != 'loaded' or bootstrap['ActiveState'] not in ('active', 'inactive')
            or bootstrap['UnitFileState'] not in ('enabled', 'disabled') or bootstrap.get('DropInPaths')):
        raise ValueError('supported bootstrap service baseline required')
    for name in CONFLICTS:
        row = unit(name)
        if row['ActiveState'] != 'inactive' or row['UnitFileState'] not in ('', 'disabled', 'masked', 'static'):
            raise ValueError('conflicting service/socket: ' + name)
    before = {}
    for name, destination in DESTINATIONS.items():
        target = Path(destination); protected(target, missing=True)
        record = c.snapshot(target)
        if record is not None and record['type'] != 'file':
            raise ValueError('regular configuration destination required')
        before[name] = record
        if phase == 'activate' and record != desired(name, content[name]):
            raise ValueError('configuration must be applied before activation')
    directories = {}
    for name in DIRECTORIES:
        target = Path(name); protected(target.parent, missing=True)
        if target.exists():
            st = target.lstat()
            if not stat.S_ISDIR(st.st_mode) or (st.st_uid, st.st_gid, stat.S_IMODE(st.st_mode)) != directory_metadata(name, account):
                raise ValueError('runtime directory ownership/mode mismatch: ' + name)
            directories[name] = True
        else:
            if phase == 'activate': raise ValueError('runtime directory missing: ' + name)
            directories[name] = False
    # Verify the unit with its real parser, using a private local copy; no reload/start.
    import tempfile
    with tempfile.TemporaryDirectory(prefix='clockmaker-unit-') as directory:
        candidate = Path(directory) / UNIT
        candidate.write_bytes(content['timeservice.service'])
        command(['/usr/bin/systemd-analyze', 'verify', str(candidate)])
    return {'profile_sha256': checksum, 'hostname': spec['hostname'], 'phase': phase,
            'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
            'files': before, 'directories': directories, 'devices': devices,
            'service': service, 'bootstrap': bootstrap}


def desired(name, data):
    return {'type': 'file', 'sha256': c.digest(data), 'uid': 0, 'gid': 0,
            'mode': 0o644 if name in ('timeservice.service', 'leap-seconds.list') else 0o640}


def timing_ok(measurement, health):
    peers = measurement['peers']; system = measurement['system']
    if sorted(p['variables']['srchost'] for p in peers) != sorted(health['peers']): return False
    selected = [p['variables'] for p in peers if (p['status'] >> 8) & 7 == 6]
    if len(selected) != 1 or str(selected[0].get('refid', '')).strip('.') != 'PPS' or selected[0].get('srchost') != health['pps_peer']: return False
    peer = selected[0]
    if any(int(p['variables'].get('reach', 0)) <= 0 for p in peers): return False
    upstreams = [p for p in peers if not p['variables']['srchost'].startswith('SHM(')]
    if len(upstreams) != 3 or any((p['status'] >> 8) & 0x60 != 0x60 or int(p['variables'].get('ntscookies', 0)) <= 0 for p in upstreams): return False
    values = [float(system['offset']), float(peer['offset']), float(peer['jitter'])]
    return (int(system['leap']) == 0 and int(system['stratum']) == 1
            and int(peer['reach']) > 0 and all(math.isfinite(v) for v in values)
            and abs(values[0]) <= health['offset_ms'] and abs(values[1]) <= health['offset_ms']
            and 0 <= values[2] <= health['jitter_ms'])


def health_sample(spec, journal):
    service = unit(UNIT, journal)
    if (service['ActiveState'] != 'active' or service.get('NRestarts') != '0'
            or int(service['MainPID']) <= 0 or not service.get('InvocationID')
            or service.get('FragmentPath') != DESTINATIONS['timeservice.service']
            or service.get('DropInPaths') or unit(BOOTSTRAP, journal)['ActiveState'] != 'inactive'):
        raise ValueError('service not ready or restarted')
    children = command(['/usr/bin/ps', '--ppid', service['MainPID'], '-o', 'pid='], journal).split()
    observed = {}
    for pid in children:
        if not pid.isdigit(): raise ValueError('invalid child PID')
        root = Path('/proc') / pid
        executable = os.readlink(root / 'exe')
        name = Path(executable).name
        if executable not in ('/usr/local/sbin/gpsd', '/usr/local/sbin/ntpd') or name in observed:
            raise ValueError('supervised GPSD/NTP pair missing or unexpected child')
        rows = dict(line.split(':', 1) for line in (root / 'status').read_text().splitlines())
        observed[name] = {'uid': [int(v) for v in rows['Uid'].split()], 'gid': [int(v) for v in rows['Gid'].split()]}
    if observed != spec['health']['credentials']:
        raise ValueError('daemon credentials/pair mismatch')
    plan = json.loads(c.regular_bytes(journal / 'recovery.json'))
    journal_errors(plan['before']['boot_id'], plan['started_monotonic_us'], journal)
    measured = json.loads(command(['/usr/bin/python3', '-I', '-B', '/usr/local/libexec/measure-time-service.py'], journal))
    if not timing_ok(measured, spec['health']): raise ValueError('timing not ready')
    checker = load(Path('/usr/local/libexec/check-time-client.py'))
    import secrets
    for endpoint in (spec['health']['ipv4'], spec['health']['ipv6']):
        family = socket.AF_INET6 if ':' in endpoint else socket.AF_INET
        with socket.socket(family, socket.SOCK_DGRAM) as sock:
            sock.settimeout(3); sock.connect((endpoint, 123))
            nonce = secrets.token_bytes(8); packet = bytearray(48); packet[0] = 0x23; packet[40:48] = nonce
            sock.send(packet); checker.ntp_response(sock.recv(512), nonce)
    return {'service': service, 'measurement': measured, 'credentials': observed, 'epoch': time.time()}


def guard_name(journal):
    return 'clockmaker-recovery-' + c.digest(str(journal.resolve()).encode())[:24]


def arm_guard(journal, plan_hash):
    runner = journal / 'runner'
    runner.mkdir(mode=0o700)
    for name, source in (('clockmaker.py', Path(c.__file__)), ('clockmaker-service.py', Path(__file__))):
        atomic(runner / name, c.regular_bytes(source), 0o600)
    name = guard_name(journal)
    command(['/usr/bin/systemd-run', '--quiet', '--unit=' + name, '--on-active=1800s',
             '--timer-property=AccuracySec=1s', '--property=Type=oneshot',
             '--property=TimeoutStartSec=300s', '--property=UMask=0077',
             '/usr/bin/python3', '-I', '-B', str(runner / 'clockmaker.py'), 'expire-service',
             '--input', str(journal / 'recovery.json'), '--sha256', plan_hash], journal)
    if unit(name + '.timer', journal)['ActiveState'] != 'active':
        raise ValueError('independent recovery timer not active')


def disarm_guard(journal):
    # Never stop an already firing recovery service: it serializes against acceptance.
    name = guard_name(journal) + '.timer'
    if unit(name, journal).get('LoadState') != 'not-found':
        command(['/usr/bin/systemctl', 'stop', name], journal)


def read_plan(path, checksum):
    if os.geteuid() != 0: raise ValueError('service transaction requires root')
    protected(path); protected(path.parent / 'status.json')
    plan = c.bound_json(path, checksum)
    if plan['schema'] != 1 or plan['phase'] not in ('apply-configuration', 'activate'):
        raise ValueError('invalid recovery plan')
    c.target_identity(plan['before']['hostname'])
    if Path('/proc/sys/kernel/random/boot_id').read_text().strip() != plan['before']['boot_id']:
        raise ValueError('recovery after reboot needs fresh assessment')
    return plan, json.loads(c.regular_bytes(path.parent / 'status.json'))


def restore(journal, plan, status):
    if Path('/proc/sys/kernel/random/boot_id').read_text().strip() != plan['before']['boot_id']:
        raise ValueError('boot changed; manual recovery assessment required')
    protected(journal)
    service = unit(UNIT, journal)
    if service.get('DropInPaths') or unit(BOOTSTRAP, journal).get('DropInPaths'):
        raise ValueError('service override prevents recovery')
    if plan['phase'] == 'apply-configuration' and (service['ActiveState'] != 'inactive' or service['UnitFileState'] not in ('', 'disabled')):
        raise ValueError('restore activation before configuration')
    # Apply rollback restores only old/new bytes, never overwrites unrelated drift.
    for name, before in plan['before']['files'].items():
        current = c.snapshot(Path(DESTINATIONS[name]))
        if current != before and current != plan['after'][name]:
            raise ValueError('configuration drift prevents recovery: ' + name)
    backups = {}
    for name, before in plan['before']['files'].items():
        if before is not None:
            backups[name] = c.regular_bytes(journal / 'before' / name)
            if c.digest(backups[name]) != before['sha256']:
                raise ValueError('backup hash mismatch')
    if plan['phase'] == 'activate':
        command(['/usr/bin/systemctl', 'stop', UNIT], journal)
        c.require_stopped_daemons()
        command(['/usr/bin/systemctl', 'disable', UNIT], journal)
        command(['/usr/bin/systemctl', 'reset-failed', UNIT], journal)
    for name, before in plan['before']['files'].items():
        target = Path(DESTINATIONS[name])
        if c.snapshot(target) == before: continue
        if before is None: target.unlink()
        else:
            atomic(target, backups[name], before['mode'], before['uid'], before['gid'])
    command(['/usr/bin/systemctl', 'daemon-reload'], journal)
    if plan['phase'] == 'activate':
        command(['/usr/bin/systemctl', 'enable' if plan['before']['bootstrap']['UnitFileState'] == 'enabled' else 'disable', BOOTSTRAP], journal)
        command(['/usr/bin/systemctl', 'start' if plan['before']['bootstrap']['ActiveState'] == 'active' else 'stop', BOOTSTRAP], journal)
    if any(c.snapshot(Path(DESTINATIONS[n])) != v for n, v in plan['before']['files'].items()):
        raise ValueError('configuration restoration mismatch')
    service = unit(UNIT, journal); bootstrap = unit(BOOTSTRAP, journal)
    if (service['ActiveState'] != 'inactive' or service['UnitFileState'] not in ('', 'disabled')
            or any(bootstrap[k] != plan['before']['bootstrap'][k] for k in ('ActiveState', 'UnitFileState'))):
        raise ValueError('service restoration mismatch')
    status['state'] = 'restored'
    # Preserve runtime data, including drift/statistics produced during a trial.
    status['retained_runtime_directories'] = [n for n, existed in plan['before']['directories'].items() if not existed and Path(n).exists()]
    save(journal / 'status.json', status)
    disarm_guard(journal)
    return status


def _execute(path, checksum, phase, state_path, state_hash, journal):
    if os.geteuid() != 0: raise ValueError('configuration/activation requires root')
    spec, release, content, account = inputs(path, checksum)
    before = c.bound_json(state_path, state_hash)
    if preflight(path, checksum, phase) != before: raise ValueError('service pre-state changed')
    protected(journal.parent)
    journal.mkdir(mode=0o700)
    (journal / 'before').mkdir(mode=0o700)
    for name, record in before['files'].items():
        if record:
            data = c.regular_bytes(Path(DESTINATIONS[name]))
            if c.digest(data) != record['sha256']: raise ValueError('backup changed')
            atomic(journal / 'before' / name, data)
    plan = {'schema': 1, 'phase': phase, 'before': before,
            'started_monotonic_us': int(time.monotonic()*1000000),
            'deadline_monotonic': time.monotonic() + 1800,
            'spec': spec, 'release': release,
            'nonce': secrets.token_hex(32),
            'after': {n: desired(n, data) for n, data in content.items()}}
    save(journal / 'recovery.json', plan)
    status = {'state': 'started', 'samples': []}
    save(journal / 'status.json', status)
    plan_hash = c.digest(c.regular_bytes(journal / 'recovery.json'))
    previous = {}
    def interrupted(signum, frame): raise InterruptedError('service operation interrupted')
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP): previous[sig] = signal.signal(sig, interrupted)
    try:
        if preflight(path, checksum, phase) != before: raise ValueError('pre-state changed during backup')
        arm_guard(journal, plan_hash)
        if phase == 'apply-configuration':
            for name, existed in before['directories'].items():
                if not existed:
                    target = Path(name)
                    uid, gid, mode = directory_metadata(name, account)
                    target.mkdir(mode=mode); os.chown(target, uid, gid); target.chmod(mode)
            for name, data in content.items():
                atomic(Path(DESTINATIONS[name]), data, plan['after'][name]['mode'])
            command(['/usr/bin/systemctl', 'daemon-reload'], journal)
            if any(c.snapshot(Path(DESTINATIONS[n])) != v for n, v in plan['after'].items()):
                raise ValueError('configuration readback mismatch')
            current_service = unit(UNIT, journal)
            if (current_service['ActiveState'] != 'inactive' or current_service['UnitFileState'] != 'disabled'
                    or any(unit(BOOTSTRAP, journal)[k] != before['bootstrap'][k]
                           for k in ('ActiveState', 'UnitFileState'))):
                raise ValueError('configuration application changed service state')
            status['state'] = 'configured_inactive'
        else:
            deadline = time.monotonic() + spec['health']['timeout_seconds']
            command(['/usr/bin/systemctl', 'stop', BOOTSTRAP], journal)
            if unit(BOOTSTRAP, journal)['ActiveState'] != 'inactive':
                raise ValueError('bootstrap did not stop')
            command(['/usr/bin/systemctl', 'start', UNIT], journal)
            consecutive = 0; invocation = None
            while time.monotonic() < deadline:
                try:
                    sample = health_sample(spec, journal)
                    current = sample['service']['InvocationID']
                    consecutive = consecutive + 1 if current == invocation else 1
                    invocation = current
                except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
                    sample = {'error': str(error), 'epoch': time.time()}; consecutive = 0
                status['samples'].append(sample); save(journal / 'status.json', status)
                if consecutive >= spec['health']['consecutive_samples'] and time.monotonic() < deadline: break
                time.sleep(min(spec['health']['interval_seconds'], max(0, deadline - time.monotonic())))
            else: raise ValueError('activation health deadline exceeded')
            installed(release)
            status.update(state='awaiting_acceptance', final=status['samples'][-1])
            challenge = {'schema': 1, 'hostname': spec['hostname'],
                         'endpoints': [spec['health']['ipv4'], spec['health']['ipv6']],
                         'client': spec['client'], 'nonce': plan['nonce'],
                         'boot_id': before['boot_id'], 'invocation': invocation,
                         'checker_sha256': release['files']['usr/local/libexec/check-time-client.py']['sha256']}
            save(journal / 'client-challenge.json', challenge)
        if phase == 'apply-configuration':
            save(journal / 'completion.json', status)
        save(journal / 'status.json', status)
        if phase == 'apply-configuration':
            try: disarm_guard(journal)
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                status['timer_cleanup_error'] = str(error); save(journal / 'status.json', status)
        return status
    except BaseException as error:
        status['error'] = str(error); status['state'] = 'recovery_required'
        save(journal / 'status.json', status)
        try: restore(journal, plan, status)
        except BaseException as recovery_error:
            status.update(state='manual_recovery_required', recovery_error=str(recovery_error))
            save(journal / 'status.json', status)
        raise
    finally:
        for sig, handler in previous.items(): signal.signal(sig, handler)


def _recover(path, checksum, completed=False, automatic=False):
    plan, status = read_plan(path, checksum); journal = path.parent
    if automatic and status['state'] in ('active_enabled', 'configured_inactive', 'restored'):
        disarm_guard(journal)
        return status
    if automatic and time.monotonic() < plan['deadline_monotonic']:
        raise ValueError('automatic recovery deadline not reached')
    if completed:
        if status['state'] not in ('active_enabled', 'configured_inactive'):
            raise ValueError('completed restoration requires completed transaction')
        request = journal / 'restoration.json'
        if request.exists(): raise ValueError('restoration already requested; inspect recovery state')
        save(request, {'plan_sha256': checksum, 'completion': status})
    elif status['state'] not in ('started', 'awaiting_acceptance', 'recovery_required', 'manual_recovery_required'):
        raise ValueError('completed operation needs explicit restore-service')
    status['state'] = 'recovery_required'; save(journal / 'status.json', status)
    try: return restore(journal, plan, status)
    except BaseException as error:
        status.update(state='manual_recovery_required', recovery_error=str(error))
        save(journal / 'status.json', status)
        raise


def check_client(path, checksum):
    challenge = c.bound_json(path, checksum)
    if challenge['schema'] != 1: raise ValueError('client challenge schema')
    c.target_identity(challenge['client']['hostname'])
    checker_path = Path(__file__).with_name('check-time-client.py')
    if not checker_path.exists(): checker_path = Path('/usr/local/libexec/check-time-client.py')
    if c.digest(c.regular_bytes(checker_path)) != challenge['checker_sha256']:
        raise ValueError('client checker hash mismatch')
    result = load(checker_path).check(challenge, checksum)
    for key in ('ipv4', 'ipv6'):
        if result['observations'][key]['local_address'] != challenge['client'][key]:
            raise ValueError('unexpected client source address')
    result.update(client=challenge['client'], nonce=challenge['nonce'],
                  boot_id=challenge['boot_id'], invocation=challenge['invocation'])
    return result


def accept(path, checksum, result_path, result_hash):
    with lifecycle_lock():
        plan, status = read_plan(path, checksum); journal = path.parent
        if plan['phase'] != 'activate' or status['state'] != 'awaiting_acceptance':
            raise ValueError('acceptance requires a pending trial')
        if time.monotonic() > plan['deadline_monotonic'] - 300:
            raise ValueError('insufficient acceptance/recovery margin; recover before proceeding')
        result = c.bound_json(result_path, result_hash)
        if (result.get('target') != plan['spec']['hostname'] or result.get('client') != plan['spec']['client']
                or result.get('nonce') != plan['nonce'] or result.get('boot_id') != plan['before']['boot_id']
                or result.get('invocation') != status['final']['service']['InvocationID']
                or result.get('spec_sha256') != c.digest(c.regular_bytes(journal / 'client-challenge.json'))
                or result.get('checks') != {'ipv4': True, 'ipv6': True, 'queries_denied': True, 'mdns': True}
                or not -5 <= time.time() - result.get('epoch', 0) <= 120):
            raise ValueError('fresh bound external acceptance required')
        for key in ('ipv4', 'ipv6'):
            if result['observations'][key]['local_address'] != plan['spec']['client'][key]:
                raise ValueError('external source mismatch')
        if unit(guard_name(journal) + '.timer', journal)['ActiveState'] != 'active':
            raise ValueError('independent recovery protection missing')
        installed(plan['release'])
        if any(c.snapshot(Path(DESTINATIONS[n])) != v for n, v in plan['after'].items()):
            raise ValueError('configuration drift before acceptance')
        try:
            sample = health_sample(plan['spec'], journal)
            if sample['service']['InvocationID'] != status['final']['service']['InvocationID']:
                raise ValueError('service invocation changed')
            save(journal / 'client-result.json', result)
            command(['/usr/bin/systemctl', 'disable', BOOTSTRAP], journal)
            command(['/usr/bin/systemctl', 'enable', UNIT], journal)
            final = health_sample(plan['spec'], journal)
            if (final['service']['UnitFileState'] != 'enabled' or final['service']['InvocationID'] != sample['service']['InvocationID']
                    or time.monotonic() >= plan['deadline_monotonic']):
                raise ValueError('activation persistence mismatch')
            status.update(state='active_enabled', final=final, client_result_sha256=result_hash)
            save(journal / 'completion.json', status)
            save(journal / 'status.json', status)
        except BaseException as error:
            status.update(state='recovery_required', error=str(error)); save(journal / 'status.json', status)
            try: restore(journal, plan, status)
            except BaseException as recovery_error:
                status.update(state='manual_recovery_required', recovery_error=str(recovery_error)); save(journal / 'status.json', status)
            raise
        # Committed state precedes cancellation. A racing timer sees the commit and exits.
        try: disarm_guard(journal)
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            status['timer_cleanup_error'] = str(error); save(journal / 'status.json', status)
        return status


@contextmanager
def lifecycle_lock(wait=False):
    path = Path('/run/clockmaker-service.lock')
    protected(path, missing=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
            raise ValueError('private regular lifecycle lock required')
        deadline = time.monotonic() + 90
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if not wait or time.monotonic() >= deadline: raise
                time.sleep(1)
        yield
    finally:
        os.close(fd)


def execute(path, checksum, phase, state_path, state_hash, journal):
    if phase not in ('apply-configuration', 'activate'):
        raise ValueError('unsupported service operation')
    with lifecycle_lock():
        return _execute(path, checksum, phase, state_path, state_hash, journal)


def recover(path, checksum, completed=False, automatic=False):
    with lifecycle_lock(wait=automatic):
        return _recover(path, checksum, completed, automatic)
