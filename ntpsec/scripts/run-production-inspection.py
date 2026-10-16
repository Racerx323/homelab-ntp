#!/usr/bin/python3
"""Seal and capture read-only production-transition prerequisites over SSH stdin."""
import argparse
import base64
import hashlib
import io
import ipaddress
import json
import os
from pathlib import Path
import re
import selectors
import signal
import socket
import stat
import subprocess
import tarfile
import time

ROOT = Path(__file__).resolve().parents[1]
LIMIT = 1024 * 1024
INSTALLED = {
    '/usr/local/libexec/timeservice.py': 'timeservice.py',
    '/usr/local/libexec/gpsd-pairing.py': 'gpsd-pairing.py',
    '/usr/local/libexec/pps-startup.py': 'pps-startup.py',
    '/etc/ntp.conf': 'ntp.conf',
    '/etc/ntpsec-timeservice.json': 'timeservice.json',
    '/etc/systemd/system/timeservice.service': 'timeservice.service',
    '/etc/systemd/system/ntp-monitor-recovery.service': 'fault.service',
    '/etc/systemd/system/ntpleapfetch.service': 'ntpleapfetch.service',
    '/etc/systemd/system/ntpleapfetch.timer': 'ntpleapfetch.timer',
}


def encoded(value):
    return (json.dumps(value, sort_keys=True) + '\n').encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class CaptureDeadline(BaseException):
    """Abort the whole capture, including commands that catch ordinary timeouts."""


def expired(signum, frame):
    raise CaptureDeadline('remote capture deadline exceeded')


def bounded(argv, timeout=10, limit=LIMIT, payload=None, env=None):
    """Bound both pipes while draining them; never create target spool files."""
    result = {'argv': argv, 'stdout': '', 'stderr': '', 'returncode': None}
    outputs = {'stdout': bytearray(), 'stderr': bytearray()}
    process = subprocess.Popen(argv, stdin=subprocess.PIPE if payload is not None else subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
                               cwd='/', env=env if env is not None else {'PATH': '/usr/local/bin:/usr/local/sbin:/usr/bin:/bin',
                                             'LC_ALL': 'C', 'PYTHONDONTWRITEBYTECODE': '1'})
    deadline = time.monotonic() + timeout
    try:
        with selectors.DefaultSelector() as poll:
            for name in outputs:
                stream = getattr(process, name)
                os.set_blocking(stream.fileno(), False)
                poll.register(stream, selectors.EVENT_READ, name)
            pending = memoryview(payload or b'')
            if payload is not None:
                os.set_blocking(process.stdin.fileno(), False)
                poll.register(process.stdin, selectors.EVENT_WRITE, 'stdin')
            while poll.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError('command deadline exceeded')
                for key, _ in poll.select(min(remaining, 0.25)):
                    if key.data == 'stdin':
                        if pending:
                            pending = pending[os.write(key.fd, pending[:65536]):]
                        if not pending:
                            poll.unregister(key.fileobj)
                            key.fileobj.close()
                        continue
                    raw = os.read(key.fd, 65536)
                    if not raw:
                        poll.unregister(key.fileobj)
                        continue
                    output = outputs[key.data]
                    if len(output) + len(raw) > limit:
                        output.extend(raw[:limit-len(output)])
                        raise ValueError('command output bound exceeded')
                    output.extend(raw)
            result['returncode'] = process.wait(timeout=max(0.01, deadline-time.monotonic()))
    except (OSError, ValueError, TimeoutError, subprocess.TimeoutExpired) as error:
        result['error'] = str(error)
    finally:
        if result['returncode'] is None:
            # Stop descendants which might retain a pipe after the parent exits.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        process.wait()
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None:
                stream.close()
    result.update({name: bytes(raw).decode('utf-8', errors='replace') for name, raw in outputs.items()})
    return result


def file_record(path, content=False):
    """Capture a regular file without following links, including mutable-file metadata."""
    path = Path(path)
    try:
        for parent in path.parents:
            if parent.is_symlink():
                raise ValueError('symlink ancestor')
        info = path.lstat()
        row = {'mode': stat.S_IMODE(info.st_mode), 'uid': info.st_uid, 'gid': info.st_gid,
               'size': info.st_size, 'inode': info.st_ino, 'device': info.st_dev,
               'mtime_ns': info.st_mtime_ns}
        if not stat.S_ISREG(info.st_mode):
            raise ValueError('regular file required')
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as stream:
            before = os.fstat(stream.fileno())
            if (before.st_dev, before.st_ino) != (info.st_dev, info.st_ino):
                raise ValueError('file identity changed')
            raw = stream.read(LIMIT+1)
            after = os.fstat(stream.fileno())
        if len(raw) > LIMIT:
            raise ValueError('file capture bound exceeded')
        row.update(sha256=sha(raw), changed_during_read=(before.st_size, before.st_mtime_ns)
                   != (after.st_size, after.st_mtime_ns))
        if content:
            row['base64'] = base64.b64encode(raw).decode()
        return row
    except FileNotFoundError:
        return {'missing': True}
    except (OSError, ValueError) as error:
        return {'error': str(error)}


def units(spec):
    return ['timeservice.service', 'gpsd.service', 'gpsd.socket', 'ntpsec.service',
            'systemd-timesyncd.service', 'avahi-daemon.service', 'ntpleapfetch.service',
            'ntpleapfetch.timer', 'ntp-monitor-recovery.service',
            spec['apply_unit']+'.service', spec['recovery_unit']+'.service',
            spec['recovery_unit']+'.timer']


def collect(spec):
    if spec['purpose'] == 'rtc-inspection':
        return collect_rtc(spec)
    started = time.time()
    actual = socket.gethostname().split('.')[0]
    if actual != spec['hostname'] or os.geteuid() != 0:
        raise ValueError('target hostname/root identity mismatch')
    stage = spec['stage']
    report = {'hostname': actual, 'operation_id': spec['operation_id'],
              'spec_sha256': sha(encoded(spec)), 'started_epoch': started, 'production_accepted': False,
              'boot_before': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
              'files': {}, 'commands': {}}
    content_paths = {'/etc/ntp.conf', '/etc/ntpsec-timeservice.json',
                     '/var/lib/ntpsec/drift/ntp.drift', stage+'/startup-monitor.json',
                     stage+'/state.json', stage+'/shm-access-state.json', '/run/ntpsec-startup/gate.json'}
    for path in sorted(set(INSTALLED) | content_paths):
        report['files'][path] = file_record(path, path in content_paths)
    commands = {'shm': ['/usr/bin/cat', '/proc/sysvipc/shm'],
                'ntp-account': ['/usr/bin/id', 'ntp'],
                'gpsd-account': ['/usr/bin/id', 'gpsd'],
                'processes': ['/usr/bin/ps', '-C', 'ntpd,gpsd', '-o', 'pid,ppid,lstart,args'],
                'peers': ['/usr/local/bin/ntpq', '-pn'],
                'system': ['/usr/local/bin/ntpq', '-c', 'rv 0'],
                'journal': ['/usr/bin/journalctl', '--boot=0', '--no-pager', '-n', '150',
                            '-o', 'json', '-u', 'timeservice.service', '-u', 'ntp-monitor-recovery.service']}
    for unit in units(spec):
        props = ['Id', 'LoadState', 'ActiveState', 'SubState', 'UnitFileState', 'FragmentPath',
                 'DropInPaths', 'InvocationID']
        if unit.endswith('.service'):
            props += ['MainPID', 'NRestarts', 'ExecStart', 'Restart', 'Result',
                      'ExecMainStartTimestampMonotonic']
        if unit.endswith('.timer'):
            props += ['LastTriggerUSec', 'NextElapseUSecRealtime', 'NextElapseUSecMonotonic']
        commands[unit] = ['/usr/bin/systemctl', 'show', unit, '--property='+','.join(props)]
    for name, argv in commands.items():
        try:
            report['commands'][name] = bounded(argv)
        except OSError as error:
            report['commands'][name] = {'argv': argv, 'error': str(error)}
    report['boot_after'] = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    report['completed_epoch'] = time.time()
    report['capture_complete'] = (report['boot_before'] == report['boot_after']
        and all('error' not in r for r in report['files'].values())
        and all(r.get('returncode') == 0 and 'error' not in r for r in report['commands'].values()))
    return report


def review(spec):
    if spec['purpose'] == 'rtc-inspection':
        return rtc_review(spec)
    return f'''# Read-only production-transition inspection

Target: **{spec['hostname']}**, SSH as `ama` to `{spec['endpoints'][0]}` with
pinned Ed25519 key alias `{spec['host_key_alias']}`. One capture only.
Operation: `{spec['operation_id']}`. Expires at Unix epoch {spec['expires_epoch']}.
Baseline: monitor bundle SHA-256 `{spec['monitor_sha256']}`; it is historical
comparison data, not a claim that the host still matches or that its old window applies.

Read the explicit installed file identities, final configuration, service recipe,
learned drift, monitor/state/SHM access records and receiver gate record.
Inspect SysV SHM metadata, ntp/gpsd account identities, localhost NTP peers/system
variables, 150 current-boot journal entries and the named service/timer states.
Service-only properties are not queried on sockets/timers. Retain missing files,
command failures, changed-during-read indications and boot changes as evidence.
Do not interpret capture completion as timing or production acceptance.

Send sealed repository code through SSH stdin to `sudo -n /usr/bin/python3 -I -B -`.
No target staging, writes to configuration, service/timer changes, SHM mutation,
restart, reboot, upstream/controller probes, cleanup or restoration. SSH/sudo and
local NTP queries may produce ordinary logs/counters. No control-key or process
environment capture. The running service remains untouched.

Each command is limited to 10 seconds and 1 MiB per output stream; each file to
1 MiB. Total remote execution is limited to 240 seconds; SSH capture to 270
seconds and 24 MiB per stream. Register execution locally before connection;
retain partial output and never automatically retry an uncertain capture.
There is no alternate-endpoint retry or target cleanup. Failure requires review.
Only known-host data, minimal baseline hashes, current code/tests and this review
are included; no old executable code or nested archives are loaded.

Execute from the repository root after approval:
`python3 -I -B ntpsec/scripts/run-production-inspection.py execute --bundle ABSOLUTE_BUNDLE --sha256 APPROVED_SHA256`
'''


def validate(spec):
    if spec.get('purpose') == 'rtc-inspection':
        validate_rtc(spec)
        return
    op = spec['operation_id']
    source = spec['monitor_operation_id']
    if (spec['schema'] != 1 or spec['purpose'] != 'production-inspection'
            or spec['hostname'] != 'j2-svntp1'
            or any(not re.fullmatch(r'[a-z][a-z0-9-]{0,47}', x) for x in (op, source))
            or spec['stage'] != '/var/lib/ntp-acquire-'+source
            or spec['apply_unit'] != 'ntp-monitor-'+source
            or spec['recovery_unit'] != spec['apply_unit']+'-watchdog'
            or [ipaddress.ip_address(x).version for x in spec['endpoints']] != [4, 6]
            or ipaddress.ip_address(spec['host_key_alias']).version != 4
            or not re.fullmatch(r'[a-f0-9]{64}', spec['monitor_sha256'])
            or not 0 < spec['expires_epoch']-spec['prepared_epoch'] <= 86400):
        raise ValueError('closed inspection scope required')


def private(path, limit=4*LIMIT):
    path = Path(path)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError('owner-private regular input required')
    with path.open('rb') as stream:
        raw = stream.read(limit+1)
    if len(raw) > limit:
        raise ValueError('input bound exceeded')
    return raw


def prepare(bundle, checksum, current=True):
    raw = private(bundle)
    if sha(raw) != checksum:
        raise ValueError('approved archive digest mismatch')
    names = {'runner.py', 'tests.py', 'spec.json', 'baseline.json', 'known_hosts', 'review.md'}
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        members = archive.getmembers()
        if (len(members) != len(names) or {m.name for m in members} != names
                or any(not m.isfile() or m.size > LIMIT for m in members)):
            raise ValueError('closed bounded archive required')
        files = {m.name: archive.extractfile(m).read() for m in members}
    spec = json.loads(files['spec.json'])
    validate(spec)
    if spec['members'] != {n: sha(files[n]) for n in names-{'spec.json', 'review.md'}}:
        raise ValueError('manifest binding mismatch')
    if files['review.md'] != review(spec).encode():
        raise ValueError('review binding mismatch')
    for name in ('spec.json', 'review.md', 'known_hosts'):
        if private(bundle.parent/name) != files[name]:
            raise ValueError('local approval input drift')
    if current and (files['runner.py'] != Path(__file__).read_bytes()
                    or files['tests.py'] != (ROOT/'tests/test_production_inspection.py').read_bytes()):
        raise ValueError('current repository input drift')
    if not spec['prepared_epoch']-300 <= time.time() < spec['expires_epoch']-300:
        raise ValueError('inspection execution window expired')
    return spec, files


def seal(args):
    source = Path(args.monitor_dir)
    raw = private(source/'service-monitor.tar', 96*LIMIT)
    if sha(raw) != args.monitor_sha256:
        raise ValueError('historical monitor digest mismatch')
    # Read data only. Never import implementations from a historical archive.
    selected = {'spec.json', 'known_hosts', *INSTALLED.values()}
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        members = [m for m in archive.getmembers() if m.name in selected]
        if (len(members) != len(selected) or {m.name for m in members} != selected
                or any(not m.isfile() or m.size > LIMIT for m in members)):
            raise ValueError('baseline member identity/bounds')
        data = {m.name: archive.extractfile(m).read() for m in members}
    old = json.loads(data['spec.json'])
    baseline = {'monitor_spec_sha256': sha(data['spec.json']), 'boot_id': old['boot_id'],
                'installed_sha256': {p: sha(data[n]) for p, n in INSTALLED.items()}}
    now = int(time.time())
    spec = {'schema': 1, 'purpose': 'production-inspection', 'operation_id': args.operation_id,
            'hostname': old['hostname'], 'endpoints': old['endpoints'], 'host_key_alias': old['old_ipv4'],
            'monitor_operation_id': old['operation_id'], 'monitor_sha256': args.monitor_sha256,
            'stage': old['stage'], 'apply_unit': old['apply_unit'], 'recovery_unit': old['recovery_unit'],
            'prepared_epoch': now, 'expires_epoch': now+86400}
    return write_bundle(args, spec, baseline, data['known_hosts'])


def write_bundle(args, spec, baseline, known_hosts):
    validate(spec)
    files = {'runner.py': Path(__file__).read_bytes(),
             'tests.py': (ROOT/'tests/test_production_inspection.py').read_bytes(),
             'baseline.json': encoded(baseline), 'known_hosts': known_hosts}
    spec['members'] = {n: sha(v) for n, v in files.items()}
    files.update({'spec.json': encoded(spec), 'review.md': review(spec).encode()})
    os.umask(0o077)
    args.output.mkdir(mode=0o700)
    for name in ('spec.json', 'review.md', 'known_hosts'):
        (args.output/name).write_bytes(files[name])
    bundle = args.output/'production-inspection.tar'
    with tarfile.open(bundle, 'w') as archive:
        for name, value in sorted(files.items()):
            item = tarfile.TarInfo(name); item.size = len(value); item.mode = 0o600
            archive.addfile(item, io.BytesIO(value))
    digest = sha(bundle.read_bytes())
    prepare(bundle, digest)
    result = {'sha256': digest, 'bundle': str(bundle), 'expires_epoch': spec['expires_epoch'],
              'execution_authorized': False, 'target_contact': False}
    (args.output/'sealing.json').write_bytes(encoded(result))
    return result


def ssh_argv(spec, directory):
    options = ['BatchMode=yes', 'StrictHostKeyChecking=yes', 'HostKeyAlgorithms=ssh-ed25519',
               'UpdateHostKeys=no', 'ProxyCommand=none', 'ProxyJump=none', 'ControlMaster=no',
               'ControlPath=none', 'ControlPersist=no', 'PermitLocalCommand=no', 'ClearAllForwardings=yes',
               'ForwardAgent=no', 'ForwardX11=no', 'GlobalKnownHostsFile=/dev/null',
               'UserKnownHostsFile='+str(directory/'known_hosts'), 'HostKeyAlias='+spec['host_key_alias'],
               'ConnectTimeout=15', 'ServerAliveInterval=15', 'ServerAliveCountMax=3']
    return ['/usr/bin/ssh', '-F', '/dev/null', '-T',
            *[v for option in options for v in ('-o', option)], 'ama@'+spec['endpoints'][0],
            'cd / && sudo -n /usr/bin/python3 -I -B -']


def execute(args):
    os.umask(0o077)
    bundle = args.bundle.absolute()
    spec, files = prepare(bundle, args.sha256)
    root = bundle.parent
    payload = ("__name__ = 'sealed_inspection'\n__file__ = '/sealed/runner.py'\n".encode()
               + files['runner.py'] + b'\n'
               + b'signal.signal(signal.SIGALRM, expired)\nsignal.alarm(240)\nprint(json.dumps(collect('
               + repr(spec).encode()+b')))\n')
    argv = ssh_argv(spec, root)
    with (root/'execution.json').open('xb') as stream:
        stream.write(encoded({'bundle_sha256': args.sha256, 'payload_sha256': sha(payload),
                              'epoch': int(time.time()), 'argv': argv}))
        stream.flush(); os.fsync(stream.fileno())
    try:
        result = bounded(argv, timeout=270, limit=24*LIMIT, payload=payload, env=os.environ.copy())
    except OSError as error:
        result = {'returncode': None, 'error': str(error), 'stdout': '', 'stderr': ''}
    for name in ('stdout', 'stderr'):
        (root/(name+'.txt')).write_text(result.pop(name))
    result.update(bundle_sha256=args.sha256, production_accepted=False)
    if result.get('returncode') == 0 and 'error' not in result:
        try:
            capture = json.loads((root/'stdout.txt').read_text())
            if (capture.get('hostname') != spec['hostname']
                    or capture.get('operation_id') != spec['operation_id']
                    or capture.get('spec_sha256') != sha(encoded(spec))):
                raise ValueError('capture target/operation binding mismatch')
            result['capture_complete'] = capture.get('capture_complete') is True
            result['baseline_comparison'] = {p: capture['files'].get(p, {}).get('sha256') == digest
                for p, digest in json.loads(files['baseline.json'])['installed_sha256'].items()}
        except (ValueError, KeyError, TypeError) as error:
            result['error'] = str(error)
    (root/'result.json').write_bytes(encoded(result))
    return result


def validate_rtc(spec):
    if spec.get('rtc_scope', 'full') not in ('full', 'utility'):
        raise ValueError('closed RTC utility scope required')
    if (spec['schema'] != 1 or spec['hostname'] != 'j2-svntp1'
            or not re.fullmatch(r'[a-z][a-z0-9-]{0,47}', spec['operation_id'])
            or [ipaddress.ip_address(x).version for x in spec['endpoints']] != [4, 6]
            or ipaddress.ip_address(spec['host_key_alias']).version != 4
            or not re.fullmatch(r'[a-f0-9]{64}', spec['start_sha256'])
            or not 0 < spec['expires_epoch']-spec['prepared_epoch'] <= 86400):
        raise ValueError('closed RTC inspection scope required')


def rtc_review(spec):
    if spec.get('rtc_scope') == 'utility':
        return rtc_utility_review(spec)
    return f"""# Read-only RTC inspection

Target: **{spec['hostname']}**, SSH as `ama` to `{spec['endpoints'][0]}`,
pinned Ed25519 alias `{spec['host_key_alias']}`. One capture only.
Operation: `{spec['operation_id']}`. Expires at Unix epoch {spec['expires_epoch']}.
Accepted start archive: `{spec['start_sha256']}`. The flat baseline retains
convergence results and both ready observations; historical code is not loaded.

Read RTC class identities, driver/device-tree ancestry, device major/minor,
sysfs date/time/epoch/hctosys, /proc/driver/rtc, /etc/adjtime and timezone.
Retain package versions, selected clock files, clock-named service/init/cron
registrations, RTC udev rules, hwclock manual, current-boot kernel and clock-unit
journals, systemd clock properties, and local NTP peers/system variables.
Missing components, inaccessible files and failed commands remain explicit
unknowns. Capture completion does not certify RTC accuracy or production.

No RTC writes, system-clock changes, device opens, I2C scans, package changes,
udev edits, service changes, staging, reboot or cleanup. Read sysfs RTC attributes
only. SSH/sudo and NTP queries may produce ordinary logs/counters.
Use existing bounded SSH-stdin capture: 10 seconds/1 MiB per command stream,
240 seconds remote, 270 seconds/24 MiB SSH. Retain partial output; no retry.

Execution after approval:
`python3 -I -B ntpsec/scripts/run-production-inspection.py execute --bundle ABSOLUTE_BUNDLE --sha256 APPROVED_SHA256`
"""


def rtc_utility_review(spec):
    return f"""# Read-only RTC utility inspection

Target: **{spec['hostname']}**, SSH as `ama` to `{spec['endpoints'][0]}`,
pinned Ed25519 alias `{spec['host_key_alias']}`. One capture only.
Operation: `{spec['operation_id']}`. Expires at Unix epoch {spec['expires_epoch']}.
Accepted start archive: `{spec['start_sha256']}`. Flat prerequisite data only.

Inspect fixed hwclock/fake-hwclock executable paths and their resolved regular-file
metadata, including /sbin aliases. Read only the listed local manual files.
Query dpkg package status, file ownership and file lists for util-linux,
util-linux-extra and fake-hwclock. Read apt-cache policy for util-linux-extra
without refreshing metadata or contacting repositories. Retain missing files,
symlink targets and command errors explicitly; do not infer absence from errors.

No invocation of hwclock or fake-hwclock, RTC/device access, time queries,
clock writes, service changes, package download/install/removal, reboot or cleanup.
Existing SSH-stdin runner: 10 seconds/1 MiB per command stream, 240 seconds remote,
270 seconds/24 MiB SSH. No target staging or automatic retry. SSH/sudo may log.
Capture completion is not RTC commissioning or production acceptance.

Execution after approval:
`python3 -I -B ntpsec/scripts/run-production-inspection.py execute --bundle ABSOLUTE_BUNDLE --sha256 APPROVED_SHA256`
"""


def rtc_utility_files(root=Path('/')):
    executables = ('/usr/sbin/hwclock', '/sbin/hwclock', '/usr/bin/hwclock',
                   '/bin/hwclock', '/usr/sbin/fake-hwclock', '/sbin/fake-hwclock')
    manuals = ('/usr/share/man/man8/hwclock.8.gz', '/usr/share/man/man8/hwclock.8',
               '/usr/share/man/man8/fake-hwclock.8.gz')
    result = {}
    root = root.resolve()
    for name in executables + manuals:
        path = root/name.lstrip('/')
        row = {}; result[name] = row
        try:
            resolved = path.resolve()
            row['resolved'] = str(resolved)
            allowed = (root/'usr', root/'sbin', root/'bin')
            if not any(resolved.is_relative_to(base) for base in allowed):
                raise ValueError('resolved utility path outside allowed directories')
            info = resolved.lstat()
            if not stat.S_ISREG(info.st_mode):
                raise ValueError('resolved utility path is not regular')
            row.update(mode=stat.S_IMODE(info.st_mode), uid=info.st_uid, gid=info.st_gid,
                       size=info.st_size, inode=info.st_ino, device=info.st_dev)
            if name in manuals:
                row['content'] = file_record(resolved, True)
        except FileNotFoundError:
            row['missing'] = True
        except (OSError, ValueError, RuntimeError) as error:
            row['error'] = str(error)
    return result


def collect_rtc_utility(spec):
    if socket.gethostname().split('.')[0] != spec['hostname'] or os.geteuid() != 0:
        raise ValueError('target hostname/root identity mismatch')
    boot = Path('/proc/sys/kernel/random/boot_id')
    report = {'hostname': spec['hostname'], 'operation_id': spec['operation_id'],
              'spec_sha256': sha(encoded(spec)), 'started_epoch': time.time(),
              'boot_before': boot.read_text().strip(), 'production_accepted': False,
              'files': {}, 'commands': {}, 'utility_files': rtc_utility_files()}
    packages = ['util-linux', 'util-linux-extra', 'fake-hwclock']
    commands = {
        'packages': ['/usr/bin/dpkg-query', '-W', '-f=${binary:Package} ${Version} ${db:Status-Abbrev}\n', *packages],
        'package-files': ['/usr/bin/dpkg-query', '-L', *packages],
        'ownership': ['/usr/bin/dpkg-query', '-S', '/usr/sbin/hwclock', '/sbin/hwclock',
                      '/usr/share/man/man8/hwclock.8.gz', '/usr/sbin/fake-hwclock', '/sbin/fake-hwclock'],
        'cached-policy': ['/usr/bin/apt-cache', 'policy', 'util-linux-extra'],
    }
    for name, argv in commands.items():
        try:
            report['commands'][name] = bounded(argv)
        except OSError as error:
            report['commands'][name] = {'argv': argv, 'error': str(error)}
    report['boot_after'] = boot.read_text().strip()
    report['completed_epoch'] = time.time()
    report['capture_complete'] = report['boot_before'] == report['boot_after']
    report['unresolved_commands'] = [n for n, r in report['commands'].items()
                                     if r.get('returncode') != 0 or 'error' in r]
    return report


def rtc_metadata(root=Path('/')):
    result = {'devices': [], 'registrations': {}, 'files': {}}
    for node in sorted((root/'sys/class/rtc').glob('rtc[0-9]*')):
        row = {'class': str(node), 'resolved': str(node.resolve()), 'attributes': {}}
        for name in ('name', 'date', 'time', 'since_epoch', 'hctosys', 'dev'):
            try:
                row['attributes'][name] = (node/name).read_text()[:4096].strip()
            except OSError as error:
                row['attributes'][name] = {'error': str(error)}
        for name in ('device/driver', 'device/of_node'):
            row[name] = str((node/name).resolve()) if (node/name).exists() else None
        dev = root/'dev'/node.name
        try:
            info = dev.stat()
            row['device'] = {'path': str(dev), 'character': stat.S_ISCHR(info.st_mode),
                             'major': os.major(info.st_rdev), 'minor': os.minor(info.st_rdev)}
        except OSError as error:
            row['device'] = {'path': str(dev), 'error': str(error)}
        result['devices'].append(row)
    result['localtime_target'] = str((root/'etc/localtime').resolve())
    paths = {'etc/adjtime', 'etc/timezone', 'proc/driver/rtc', 'etc/rc.local', 'etc/crontab',
             'etc/default/hwclock', 'etc/default/fake-hwclock',
             'usr/lib/udev/hwclock-set', 'sbin/fake-hwclock',
             'var/log/fake-hwclock.data', 'boot/firmware/config.txt'}
    for directory in ('etc/init.d', 'etc/cron.d', 'etc/cron.hourly', 'etc/cron.daily',
                      'etc/rc0.d', 'etc/rc1.d', 'etc/rc2.d', 'etc/rc3.d',
                      'etc/rc4.d', 'etc/rc5.d', 'etc/rc6.d', 'etc/rcS.d',
                      'etc/systemd/system', 'usr/lib/systemd/system',
                      'etc/udev/rules.d', 'usr/lib/udev/rules.d'):
        base = root/directory
        for entry in sorted(base.glob('*')):
            entries = [entry]
            if entry.is_dir() and not entry.is_symlink() and entry.name.endswith(('.wants', '.requires', '.d')):
                entries += sorted(entry.glob('*'))
            for item in entries:
                clock_named = 'hwclock' in item.name or 'rtc' in item.name
                rtc_rule = False
                if (directory.endswith('rules.d') or directory.startswith('etc/cron')
                        or directory == 'etc/init.d') and item.is_file() and not item.is_symlink():
                    with item.open('rb') as stream:
                        raw = stream.read(LIMIT+1)
                    if len(raw) > LIMIT:
                        raise ValueError('clock hook inspection bound exceeded')
                    rtc_rule = b'rtc' in raw or b'hwclock' in raw
                if clock_named or rtc_rule:
                    result['registrations'][str(item)] = str(item.resolve())
                    if item.is_file() and not item.is_symlink():
                        paths.add(str(item.relative_to(root)))
    if len(paths) > 96:
        raise ValueError('RTC file inventory bound exceeded')
    for path in sorted(paths):
        result['files']['/'+path] = file_record(root/path, True)
    return result


def collect_rtc(spec):
    if spec.get('rtc_scope') == 'utility':
        return collect_rtc_utility(spec)
    if socket.gethostname().split('.')[0] != spec['hostname'] or os.geteuid() != 0:
        raise ValueError('target hostname/root identity mismatch')
    boot = Path('/proc/sys/kernel/random/boot_id')
    report = {'hostname': spec['hostname'], 'operation_id': spec['operation_id'],
              'spec_sha256': sha(encoded(spec)), 'started_epoch': time.time(),
              'boot_before': boot.read_text().strip(), 'production_accepted': False,
              'commands': {}, 'files': {}}
    report['rtc'] = rtc_metadata()
    commands = {
        'packages': ['/usr/bin/dpkg-query', '-W', '-f=${binary:Package} ${Version} ${db:Status-Abbrev}\n',
                     'fake-hwclock', 'util-linux', 'util-linux-extra', 'systemd', 'udev'],
        'clock': ['/usr/bin/timedatectl', 'show'],
        'peers': ['/usr/local/bin/ntpq', '-pn'],
        'system': ['/usr/local/bin/ntpq', '-c', 'rv 0'],
        'kernel': ['/usr/bin/journalctl', '-k', '-b', '--no-pager', '-n', '400', '-o', 'short-iso'],
        'clock-journal': ['/usr/bin/journalctl', '-b', '--no-pager', '-n', '120', '-o', 'short-iso',
                          '-u', 'fake-hwclock.service', '-u', 'hwclock.service', '-u', 'timeservice.service'],
        'hwclock-manual': ['/usr/bin/zcat', '/usr/share/man/man8/hwclock.8.gz'],
        'clock-units': ['/usr/bin/systemctl', 'list-unit-files', '*hwclock*', '*rtc*', '--no-pager'],
    }
    for unit in ('fake-hwclock.service', 'fake-hwclock-save.service', 'fake-hwclock-save.timer',
                 'hwclock.service', 'timeservice.service', 'systemd-timesyncd.service'):
        commands[unit] = ['/usr/bin/systemctl', 'show', unit,
                         '--property=LoadState,ActiveState,SubState,UnitFileState,FragmentPath,DropInPaths']
        commands[unit+'-definition'] = ['/usr/bin/systemctl', 'cat', unit]
    for name, argv in commands.items():
        try:
            report['commands'][name] = bounded(argv)
        except OSError as error:
            report['commands'][name] = {'argv': argv, 'error': str(error)}
    report['boot_after'] = boot.read_text().strip()
    report['completed_epoch'] = time.time()
    report['capture_complete'] = report['boot_before'] == report['boot_after']
    report['unresolved_commands'] = [n for n, r in report['commands'].items()
                                     if r.get('returncode') != 0 or 'error' in r]
    return report


def seal_rtc(args):
    source = Path(args.start_dir)
    raw = private(source/'production-transition.tar', 16*LIMIT)
    if sha(raw) != args.start_sha256:
        raise ValueError('accepted start digest mismatch')
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        selected = [x for x in archive.getmembers() if x.name in ('spec.json', 'known_hosts')]
        if (len(selected) != 2 or {x.name for x in selected} != {'spec.json', 'known_hosts'}
                or any(not x.isfile() or x.size > LIMIT for x in selected)):
            raise ValueError('start data identity/bounds')
        data = {x.name: archive.extractfile(x).read() for x in selected}
    old = json.loads(data['spec.json'])
    if sha(data['known_hosts']) != old['members']['known_hosts']:
        raise ValueError('start known-host binding mismatch')
    if old.get('purpose') != 'production-transition' or old.get('action') != 'start':
        raise ValueError('accepted start operation required')
    convergence_raw = private(source/'convergence-result.json')
    convergence = json.loads(convergence_raw)
    if (convergence.get('convergence_accepted') is not True
            or convergence['last_ready_epoch']-convergence['first_ready_epoch'] < 300):
        raise ValueError('accepted convergence required')
    observations = []
    for attempt in (convergence['last_attempt']-1, convergence['last_attempt']):
        receipt = json.loads(private(source/f'observe-{attempt}-outcome.json'))
        if receipt.get('bundle_sha256') != args.start_sha256 or receipt.get('timing_ready') is not True:
            raise ValueError('ready observation binding mismatch')
        observations.append(receipt)
    if [r['state']['health']['epoch'] for r in observations] != [
            convergence['first_ready_epoch'], convergence['last_ready_epoch']]:
        raise ValueError('convergence observation epoch mismatch')
    baseline = {'installed_sha256': {}, 'observations': observations, 'start_spec_sha256': sha(data['spec.json']),
                'convergence': convergence, 'convergence_sha256': sha(convergence_raw)}
    now = int(time.time())
    spec = {'schema': 1, 'purpose': 'rtc-inspection', 'operation_id': args.operation_id,
            'hostname': old['hostname'], 'endpoints': old['endpoints'],
            'host_key_alias': old['host_key_alias'], 'start_sha256': args.start_sha256,
            'prepared_epoch': now, 'expires_epoch': now+86400}
    spec['rtc_scope'] = 'utility' if getattr(args, 'utility_only', False) else 'full'
    return write_bundle(args, spec, baseline, data['known_hosts'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    p = sub.add_parser('seal')
    p.add_argument('--monitor-dir', type=Path, required=True)
    p.add_argument('--monitor-sha256', required=True)
    p.add_argument('--operation-id', required=True)
    p.add_argument('--output', type=Path, required=True)
    p = sub.add_parser('seal-rtc')
    p.add_argument('--utility-only', action='store_true')
    p.add_argument('--start-dir', type=Path, required=True)
    p.add_argument('--start-sha256', required=True)
    p.add_argument('--operation-id', required=True)
    p.add_argument('--output', type=Path, required=True)
    p = sub.add_parser('execute')
    p.add_argument('--bundle', type=Path, required=True)
    p.add_argument('--sha256', required=True)
    args = parser.parse_args()
    result = (seal(args) if args.action == 'seal' else
              seal_rtc(args) if args.action == 'seal-rtc' else execute(args))
    print(json.dumps(result))
    if args.action == 'execute' and result.get('capture_complete') is not True:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
