#!/usr/bin/python3
"""Seal one passive Phase 3 node capture; never change target configuration."""
import argparse
import base64
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import signal
import socket
import stat
import tarfile
import time
import types
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {'runner.py': ROOT/'scripts/run-phase3-node-inspection.py',
           'helper.py': ROOT/'scripts/run-production-inspection.py',
           'tests.py': ROOT/'tests/test_phase3_node_inspection.py'}
PROTECTED = ('/etc/ntp.conf', '/etc/cron.d/needrestart_check',
             '/usr/local/sbin/needrestart.sh', '/usr/local/libexec/ntp-maintenance-success.py')
FILES = PROTECTED + ('/usr/lib/os-release', '/etc/ssh/sshd_config',
    '/etc/watchdog.conf', '/etc/default/watchdog', '/boot/firmware/config.txt',
    '/boot/firmware/cmdline.txt', '/etc/systemd/system/ntpleapfetch.service',
    '/etc/systemd/system/ntpleapfetch.timer', '/usr/local/bin/ntpleapfetch',
    '/var/lib/ntpsec/leap-seconds.list')
CORE = ('timeservice.service', 'cron.service', 'munin-node.service', 'NetworkManager.service')
UNITS = CORE + ('webmin.service', 'ssh.service', 'watchdog.service', 'wd_keepalive.service',
               'ntpleapfetch.service', 'ntpleapfetch.timer')
COMMON_PROPS = 'Id,LoadState,ActiveState,SubState,UnitFileState,FragmentPath,DropInPaths'
SERVICE_PROPS = ',MainPID,NRestarts,InvocationID,Result,ExecMainStatus,ExecMainStartTimestamp,ExecMainExitTimestamp'
TIMER_PROPS = ',LastTriggerUSec,NextElapseUSecRealtime,NextElapseUSecMonotonic,TimersMonotonic,RandomizedDelayUSec'
NETWORK_FIELDS = ('connection.uuid,connection.type,connection.interface-name,connection.autoconnect,'
    'ipv4.method,ipv4.addresses,ipv4.gateway,ipv4.dns,ipv4.ignore-auto-dns,'
    'ipv6.method,ipv6.addresses,ipv6.gateway,ipv6.dns,ipv6.ignore-auto-dns,ipv6.addr-gen-mode')
COMMANDS = {
    'kernel': ['/usr/bin/uname', '-srvmo'],
    'packages': ['/usr/bin/dpkg-query', '-W', '-f=${binary:Package}\t${Version}\t${Architecture}\t${db:Status-Abbrev}\n'],
    'filesystems': ['/usr/bin/findmnt', '--json', '--output', 'TARGET,SOURCE,FSTYPE,VFS-OPTIONS', '--target', '/'],
    'boot_mount': ['/usr/bin/findmnt', '--json', '--output', 'TARGET,SOURCE,FSTYPE,VFS-OPTIONS', '--target', '/boot/firmware'],
    'capacity': ['/usr/bin/df', '-P', '-B1', '/', '/boot/firmware'],
    'inodes': ['/usr/bin/df', '-Pi', '/', '/boot/firmware'],
    'addresses': ['/usr/sbin/ip', '-j', 'address', 'show'],
    'routes4': ['/usr/sbin/ip', '-j', '-4', 'route', 'show', 'table', 'all'],
    'routes6': ['/usr/sbin/ip', '-j', '-6', 'route', 'show', 'table', 'all'],
    'listeners': ['/usr/bin/ss', '-H', '-lntu'],
    'network_devices': ['/usr/bin/nmcli', '-t', '-f', 'DEVICE,TYPE,STATE,CONNECTION', 'device', 'status'],
    'network_profiles': ['/usr/bin/nmcli', '-t', '-f', 'UUID,TYPE', 'connection', 'show'],
    'network_runtime': ['/usr/bin/nmcli', '-g',
        'GENERAL.DEVICE,IP4.ADDRESS,IP4.GATEWAY,IP4.DNS,IP6.ADDRESS,IP6.GATEWAY,IP6.DNS', 'device', 'show'],
    'leap_journal': ['/usr/bin/journalctl', '--boot=0', '--no-pager', '-o', 'json', '-n', '60',
                     '--output-fields=__REALTIME_TIMESTAMP,_BOOT_ID,_SYSTEMD_UNIT,SYSLOG_IDENTIFIER,MESSAGE,PRIORITY,_PID',
                     '-u', 'ntpleapfetch.service', '-u', 'ntpleapfetch.timer'],
}
REQUIRED_COMMANDS = ('kernel', 'packages', 'addresses', 'routes4', 'routes6',
                     'listeners', 'network_profiles', 'network_runtime')
h = None


def command(argv):
    try:
        return h.bounded(argv)
    except OSError as error:
        return {'argv': argv, 'returncode': None, 'error': type(error).__name__, 'stdout': '', 'stderr': ''}


def state():
    return {u: command(['/usr/bin/systemctl', 'show', u, '--property='+COMMON_PROPS
        +(TIMER_PROPS if u.endswith('.timer') else SERVICE_PROPS)]) for u in UNITS}


def properties(row):
    return dict(line.split('=', 1) for line in row.get('stdout', '').splitlines() if '=' in line)


def metadata(path):
    """lstat only: never open a character device, including watchdog devices."""
    try:
        info = Path(path).lstat()
        return {'mode': stat.S_IMODE(info.st_mode), 'uid': info.st_uid, 'gid': info.st_gid,
                'type': stat.S_IFMT(info.st_mode), 'device_number': info.st_rdev,
                'mtime_ns': info.st_mtime_ns, 'size': info.st_size,
                'link': os.readlink(path) if stat.S_ISLNK(info.st_mode) else None}
    except FileNotFoundError:
        return {'missing': True}


def text_record(path, sysfs=False):
    """Permit explicit sysfs class resolutions; keep /dev entirely out of reads."""
    original = Path(path)
    resolved = original.resolve()
    if str(original).startswith('/dev/') or str(resolved).startswith('/dev/'):
        raise ValueError('device content reads forbidden')
    if sysfs:
        if not (str(original).startswith('/sys/') and str(resolved).startswith('/sys/')):
            raise ValueError('sysfs-only resolution required')
    elif resolved != original:
        raise ValueError('indirect text input')
    row = h.file_record(resolved, True)
    if 'base64' in row:
        raw = base64.b64decode(row.pop('base64'), validate=True)
        if len(raw) > 65536:
            raise ValueError('text input bound')
        row['text'] = raw.decode('utf-8', errors='replace')
    return {'resolved': str(resolved), **row}


def names(directory, maximum):
    path = Path(directory)
    if not path.exists():
        return []
    result = []
    for item in path.iterdir():
        if len(result) >= maximum:
            raise ValueError('directory enumeration bound: '+directory)
        result.append(item)
    return sorted(result)


def hardware():
    result = {'devices': {p: metadata(p) for p in ('/dev/watchdog', '/dev/watchdog0', '/dev/watchdog1')},
              'sysfs': {}, 'unmeasured': ['switch PoE class/budget', 'firmware throttling flags',
                  'physical HAT label/revision', 'sustained thermal/fan/load behavior', 'watchdog recovery']}
    groups = [('/sys/class/watchdog', 8, ('identity', 'state', 'status', 'bootstatus', 'nowayout', 'timeout', 'dev')),
              ('/sys/class/thermal', 64, ('type', 'temp', 'cur_state', 'max_state')),
              ('/sys/class/hwmon', 32, ('name', 'fan1_input', 'pwm1')),
              ('/sys/class/rfkill', 16, ('name', 'type', 'soft', 'hard'))]
    for directory, maximum, fields in groups:
        for item in names(directory, maximum):
            if not re.fullmatch(r'(watchdog\d+|thermal_zone\d+|cooling_device\d+|hwmon\d+|rfkill\d+)', item.name):
                continue
            result['sysfs'][str(item)] = {field: text_record(item/field, True) for field in fields}
            if directory.endswith('watchdog'):
                result['sysfs'][str(item)]['driver_link'] = metadata(item/'device/driver')
    result['model'] = text_record('/sys/firmware/devicetree/base/model', True)
    return result


def repository_sources(raw):
    """Report source hosts/suites/components, never raw source lines or credentials."""
    result = {'hosts': [], 'suites': [], 'components': [], 'unexported_lines': 0}
    for line in raw.decode('utf-8', errors='replace').splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue
        hosts = []
        for uri in re.findall(r'(?:https?|ftp)://[^\s]+', stripped):
            parsed = urlsplit(uri)
            if parsed.hostname and re.fullmatch(r'[A-Za-z0-9.-]+', parsed.hostname):
                hosts.append(parsed.hostname)
        result['hosts'].extend(hosts)
        key, _, value = stripped.partition(':')
        if key in ('Suites', 'Components') and re.fullmatch(r'[A-Za-z0-9 ./_-]+', value):
            result[key.lower()].extend(value.split())
        else:
            result['unexported_lines'] += 1
    result['hosts'] = sorted(set(result['hosts']))
    return result


def complete(report):
    required = [report['commands'][n] for n in REQUIRED_COMMANDS]
    continuity = all(properties(report['units_before'][u]) == properties(report['units_after'][u])
        and properties(report['units_before'][u]).get('ActiveState') == 'active'
        and report['units_before'][u].get('returncode') == report['units_after'][u].get('returncode') == 0
        for u in CORE)
    return (report['boot_before'] == report['boot_after'] and continuity
        and all(v.get('returncode') == 0 and not v.get('error') for v in required)
        and bool(report['profiles'])
        and all(v.get('returncode') == 0 and not v.get('error') for v in report['profiles'].values())
        and report['files_before'] == report['files_after']
        and all(not v.get('error') and not v.get('changed_during_read') for v in report['files_before'].values()))


def collect(spec):
    if os.geteuid() != 0 or socket.gethostname() != 'j2-svntp1':
        raise ValueError('exact target/root identity mismatch')
    boot = Path('/proc/sys/kernel/random/boot_id')
    report = {'operation_id': spec['operation_id'], 'spec_sha256': h.sha(h.encoded(spec)),
        'hostname': 'j2-svntp1', 'started_epoch': time.time(), 'boot_before': boot.read_text().strip(),
        'units_before': state(), 'files_before': {p: h.file_record(p) for p in FILES},
        'commands': {}, 'target_configuration_mutated': False, 'production_accepted': False}
    if not all(properties(report['units_before'][u]).get('ActiveState') == 'active'
            and report['units_before'][u].get('returncode') == 0 for u in CORE):
        report.update(capture_complete=False, error='core service inactive/unavailable; no D-Bus queries attempted')
        return report
    for label, argv in COMMANDS.items():
        report['commands'][label] = command(argv)
    report['os_release'] = text_record('/usr/lib/os-release')
    report['os_release_link'] = metadata('/etc/os-release')
    report['timezone_link'] = metadata('/etc/localtime')
    report['profiles'] = {}
    rows = report['commands']['network_profiles'].get('stdout', '').splitlines()
    if len(rows) > 32:
        raise ValueError('profile count bound')
    for line in rows:
        uuid, _, kind = line.partition(':')
        if not re.fullmatch(r'[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}', uuid):
            raise ValueError('profile UUID syntax')
        if kind in ('802-3-ethernet', '802-11-wireless', 'ethernet', 'wifi', 'loopback'):
            report['profiles'][uuid] = command(['/usr/bin/nmcli', '-g', NETWORK_FIELDS,
                'connection', 'show', 'uuid', uuid])
    report['resolver_file'] = {'link': metadata('/etc/resolv.conf')}
    resolved = Path('/etc/resolv.conf').resolve()
    if str(resolved) in ('/etc/resolv.conf', '/run/NetworkManager/resolv.conf',
            '/run/NetworkManager/no-stub-resolv.conf', '/run/systemd/resolve/stub-resolv.conf',
            '/run/systemd/resolve/resolv.conf'):
        report['resolver_file']['content'] = text_record(resolved)
    else:
        report['resolver_file']['unexported_target'] = str(resolved)
    report['hardware'] = hardware()
    report['accounts'] = {}
    local_accounts = {row[0]: row for line in text_record('/etc/passwd').get('text', '').splitlines()
                      if len(row := line.split(':')) == 7 and row[0] in ('root', 'ama', 'ntp')}
    for user in ('root', 'ama', 'ntp'):
        entry = local_accounts.get(user)
        report['accounts'][user] = ({'uid': int(entry[2]), 'gid': int(entry[3]),
            'home': entry[5], 'shell': entry[6]} if entry else {'missing_locally': True})
    source_paths = [Path('/etc/apt/sources.list')] + [p for p in names('/etc/apt/sources.list.d', 32)
        if p.suffix in ('.list', '.sources')]
    report['repository_sources'] = {}
    for path in source_paths:
        row = h.file_record(path, True)
        if 'base64' in row:
            row['summary'] = repository_sources(base64.b64decode(row.pop('base64'), validate=True))
        report['repository_sources'][str(path)] = row
    report['apt_cache'] = {'refresh_stamp': metadata('/var/lib/apt/periodic/update-success-stamp'),
        'list_metadata': [{k: getattr(p.lstat(), k) for k in ('st_size', 'st_mtime_ns')}
                          for p in names('/var/lib/apt/lists', 2048) if p.is_file() and not p.is_symlink()],
        'security_updates_current': 'unproved; no repository refresh, candidate resolution or package action'}
    leap = text_record('/var/lib/ntpsec/leap-seconds.list')
    raw = leap.pop('text', '')
    leap['header_epochs_ntp'] = dict(re.findall(r'^#([@$])\s+(\d+)', raw, re.M))
    leap['expiry_epoch_unix'] = (int(leap['header_epochs_ntp']['@'])-2208988800
                               if '@' in leap['header_epochs_ntp'] else None)
    leap['checksum_verified'] = False
    report['leap_file'] = leap
    report['units_after'] = state()
    report['files_after'] = {p: h.file_record(p) for p in FILES}
    report['boot_after'] = boot.read_text().strip()
    report['completed_epoch'] = time.time()
    report['baseline_boot_matches'] = report['boot_before'] == spec['baseline_boot_id']
    report['baseline_file_matches'] = {p: report['files_before'][p].get('sha256') == digest
        for p, digest in spec['baseline_file_hashes'].items()}
    report['capture_complete'] = complete(report)
    report['unknowns'] = ['controller firewall/External exposure', 'all client/VLAN coverage',
        'master persistence', 'watchdog ownership by an active process (not scanned)',
        'installed-package origins and current security-update availability',
        'running boot-firmware identity (no firmware device command)',
        'historical journal coverage completeness', 'final Phase 3 interval']
    return report


def review(spec):
    return f'''# Phase 3 passive node readiness inspection

**Sealed, unexecuted; exact-hash execution approval required.**
Target: j2-svntp1, `ama@10.1.0.51`, strict existing Ed25519 alias `10.1.0.137`.
Operation `{spec['operation_id']}`. Expires at Unix epoch {spec['expires_epoch']}
(24 hours after preparation); leave 270 seconds for the bounded capture.

## Closed scope

One SSH connection, remote working directory `/`, code on stdin to
`sudo -n /usr/bin/python3 -I -B -`. No target staging or locks. Read installed
package names/versions/status, uname, root/boot mount and capacity, selected
local-account IDs/home/shell, hashed fixed files and sanitized configured APT hosts.
No NSS lookup or directory-service contact is used.
Package origins and up-to-date security status remain unproved: no apt refresh,
upgrade simulation, repository download or package change is allowed.

Read addresses and IPv4/IPv6 routes, listening TCP/UDP sockets, NetworkManager
device/profile metadata and only the fixed IP/DNS/autoconnect fields for up to
32 Ethernet/Wi-Fi/loopback UUIDs. No connection secrets or raw profile contents.
Read active NetworkManager IP/DNS state and resolv.conf through the declared target
allowlist. No DNS, NTP, HTTP, egress or External probe; no lease/RA renewal.

Use lstat on /dev/watchdog, watchdog0 and watchdog1 only: **never open a device**.
Read bounded /sys class metadata for up to 8 watchdog, 64 thermal, 32 hwmon and 16 rfkill
entries, with explicit sysfs-only link resolution. Read identity/state/driver,
timeout/nowayout/boot status, temperature and fan/control metadata where present.
No ioctl, firmware command, watchdog feed/enablement/reset, module load, stress,
GPIO/I2C/RTC/GPS/UART access or power/switch change. Active watchdog process
ownership, firmware throttling flags and physical PoE/HAT facts remain unknown.

Read existing leap service/timer properties and at most 60 current-boot journal
entries, plus leapfile hash and update/expiry header epochs. No fetch/checksum
utility or job invocation; leapfile authentication/checksum validity and complete
four-week recurrence are not inferred. Timer queries exclude service-only
MainPID/NRestarts properties. The file/command/unit allowlists below are exact.

## Integrity, gaps and interruption

Pin accepted OBS-04 outcome/evidence provenance and compare historical boot and
four protected-file hashes, without treating differences as permission to repair.
Compare current boot, core service identities and fixed files before/after.
Missing optional files, commands or sysfs attributes remain gaps, never a pass
for their owning requirement. Core command/profile failure or continuity drift
prevents complete capture. A completed capture is not production acceptance.

One exclusive local fsynced receipt precedes SSH. No retry or endpoint fallback,
including after timeout/partial output. Retain both streams/status privately.
Per command: 10 seconds, 1 MiB per stream. Per file: 1 MiB; exported text 64 KiB.
Remote total 240 seconds; controller 270 seconds, 24 MiB per stream. SSH/sudo,
D-Bus and file reads can create ordinary access/audit logs and access times.
Require core services already active before NetworkManager queries; do not query
resolved/timedated or invoke rfkill/firmware commands that could activate helpers.
No target configuration changes, cron install, service start/reload/restart,
timers, sends, cleanup or final observation start. No raw credentials, process
environments, private keys, arbitrary home files or unrelated journals.

OBS-02/D1–D5 and bounded OBS-04 acceptance remain unchanged. Review the capture
before preparing any watchdog/recovery or final-observation operation. Controller
policy, switch facts and master persistence require separate target scopes.

## Exact inspection inputs

Fixed hash-only files: `{json.dumps(FILES)}`.
Units: `{json.dumps(UNITS)}`.
Network fields: `{NETWORK_FIELDS}`.
Fixed commands: `{json.dumps(COMMANDS, sort_keys=True)}`.
Accepted baseline capture SHA-256: `{spec['baseline_capture_sha256']}`.

After separate approval, from the repository root:
`python3 -I -B ntpsec/scripts/run-phase3-node-inspection.py execute --directory {spec['directory']} --sha256 APPROVED_SHA256`
'''


def validate(spec):
    keys = {'schema', 'purpose', 'operation_id', 'directory', 'prepared_epoch', 'expires_epoch',
            'baseline_boot_id', 'baseline_file_hashes', 'baseline_capture_sha256', 'members'}
    if (set(spec) != keys or spec['schema'] != 1 or spec['purpose'] != 'phase3-node-readiness'
            or not re.fullmatch(r'phase3-node-readiness-[a-z0-9-]{1,40}', spec['operation_id'])
            or not Path(spec['directory']).is_absolute()
            or Path(spec['directory']).name != spec['operation_id']
            or spec['expires_epoch']-spec['prepared_epoch'] != 86400
            or set(spec['baseline_file_hashes']) != set(PROTECTED)
            or not all(re.fullmatch(r'[a-f0-9]{64}', v) for v in
                [*spec['baseline_file_hashes'].values(), spec['baseline_capture_sha256']])
            or not re.fullmatch(r'[a-f0-9-]{36}', spec['baseline_boot_id'])):
        raise ValueError('closed Phase 3 node inspection scope required')


def prepare(directory, digest):
    raw = h.private(directory/'inspection.tar', 8*h.LIMIT)
    if h.sha(raw) != digest:
        raise ValueError('approved archive digest mismatch')
    expected = set(SOURCES) | {'known_hosts', 'baseline.json', 'spec.json', 'review.md'}
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        members = archive.getmembers()
        if (len(members) != len(expected) or {m.name for m in members} != expected
                or any(not m.isfile() or m.size > h.LIMIT for m in members)):
            raise ValueError('closed bounded archive required')
        files = {m.name: archive.extractfile(m).read() for m in members}
    spec = json.loads(files['spec.json']); validate(spec)
    bound = set(SOURCES) | {'known_hosts', 'baseline.json'}
    if (spec['members'] != {n: h.sha(files[n]) for n in bound}
            or files['review.md'] != review(spec).encode()
            or spec['directory'] != str(directory.absolute())):
        raise ValueError('review/member/directory binding mismatch')
    for n, path in SOURCES.items():
        if files[n] != path.read_bytes():
            raise ValueError('repository source drift')
    for n in ('spec.json', 'review.md', 'known_hosts', 'baseline.json'):
        if h.private(directory/n) != files[n]:
            raise ValueError('local approval input drift')
    if not spec['prepared_epoch']-300 <= time.time() < spec['expires_epoch']-270:
        raise ValueError('inspection validity window')
    return spec, files


def seal(args):
    base = args.baseline
    outcome_raw = h.private(base/'outcome.json')
    outcome = json.loads(outcome_raw)
    if outcome.get('obs04_accepted') is not True or outcome.get('operator_confirmed_downstream_receipt') is not True:
        raise ValueError('accepted OBS-04 baseline required')
    for name, digest in outcome['evidence_sha256'].items():
        if Path(name).name != name or h.sha(h.private(base/name, 24*h.LIMIT)) != digest:
            raise ValueError('baseline evidence binding mismatch')
    capture_raw = h.private(base/'3-observe-stdout.txt', 24*h.LIMIT)
    capture = json.loads(capture_raw)
    with tarfile.open(fileobj=io.BytesIO(h.private(base/'execution.tar', 8*h.LIMIT))) as archive:
        selected = [m for m in archive.getmembers() if m.name in ('spec.json', 'known_hosts')]
        if (len(selected) != 2 or len({m.name for m in selected}) != 2
                or any(not m.isfile() or m.size > h.LIMIT for m in selected)):
            raise ValueError('baseline data member bounds')
        old = json.loads(archive.extractfile('spec.json').read())
        known = archive.extractfile('known_hosts').read()
    if (old['purpose'] != 'obs04-controlled-cron-failure' or not capture['cron_record'].get('missing')
            or capture['runtime']['spec'] != old
            or not capture['records']['gate.json'].get('released')
            or outcome['archive_sha256'] != h.sha(h.private(base/'execution.tar', 8*h.LIMIT))):
        raise ValueError('accepted terminal observation required')
    if not re.fullmatch(rb'10\.1\.0\.137 ssh-ed25519 [A-Za-z0-9+/=]+\n?', known):
        raise ValueError('exact existing host key required')
    now = int(time.time())
    spec = {'schema': 1, 'purpose': 'phase3-node-readiness', 'operation_id': args.output.name,
        'directory': str(args.output.absolute()), 'prepared_epoch': now, 'expires_epoch': now+86400,
        'baseline_boot_id': old['boot_id'], 'baseline_file_hashes': {p: old['protected_files'][p] for p in PROTECTED},
        'baseline_capture_sha256': h.sha(capture_raw), 'members': {}}
    validate(spec)
    files = {n: p.read_bytes() for n, p in SOURCES.items()}
    files['known_hosts'] = known
    files['baseline.json'] = h.encoded({'outcome_sha256': h.sha(outcome_raw),
        'archive_sha256': outcome['archive_sha256'], 'evidence_sha256': outcome['evidence_sha256']})
    spec['members'] = {n: h.sha(v) for n, v in files.items()}
    files.update({'spec.json': h.encoded(spec), 'review.md': review(spec).encode()})
    os.umask(0o077); args.output.mkdir(mode=0o700)
    for n, raw in files.items():
        (args.output/n).write_bytes(raw)
    with tarfile.open(args.output/'inspection.tar', 'w') as archive:
        for n, raw in sorted(files.items()):
            member = tarfile.TarInfo(n); member.size = len(raw); member.mode = 0o600
            archive.addfile(member, io.BytesIO(raw))
    digest = h.sha((args.output/'inspection.tar').read_bytes())
    prepare(args.output, digest)
    result = {'sha256': digest, 'expires_epoch': spec['expires_epoch'],
        'execution_ready': True, 'execution_approved': False, 'target_contact': False}
    (args.output/'sealing.json').write_bytes(h.encoded(result))
    return result


def payload(spec, files):
    return (b"__name__='phase3_inspection'\n__file__='/sealed/runner.py'\n"+files['runner.py']
        +b"\nns={'__name__':'helper','__file__':'/sealed/helper.py'}\nexec(compile("
        +repr(files['helper.py']).encode()+b",ns['__file__'],'exec'),ns)\nh=types.SimpleNamespace(**ns)\n"
        +b'signal.signal(signal.SIGALRM,h.expired)\nsignal.alarm(240)\nprint(json.dumps(collect('
        +repr(spec).encode()+b')))\n')


def execute(args):
    os.umask(0o077)
    directory = args.directory.absolute(); spec, files = prepare(directory, args.sha256)
    data = payload(spec, files)
    argv = h.ssh_argv({'endpoints': ['10.1.0.51'], 'host_key_alias': '10.1.0.137'}, directory)
    with (directory/'execution.json').open('xb') as stream:
        stream.write(h.encoded({'sha256': args.sha256, 'payload_sha256': h.sha(data),
                               'epoch': time.time(), 'argv': argv}))
        stream.flush(); os.fsync(stream.fileno())
    try:
        result = h.bounded(argv, timeout=270, limit=24*h.LIMIT, payload=data, env=os.environ.copy())
    except OSError as error:
        result = {'error': type(error).__name__, 'returncode': None, 'stdout': '', 'stderr': ''}
    for name in ('stdout', 'stderr'):
        (directory/(name+'.txt')).write_text(result.pop(name))
    result.update(bundle_sha256=args.sha256, capture_complete=False, production_accepted=False)
    if result.get('returncode') == 0 and not result.get('error'):
        try:
            capture = json.loads((directory/'stdout.txt').read_text())
            if (capture['operation_id'] != spec['operation_id'] or capture['hostname'] != 'j2-svntp1'
                    or capture['spec_sha256'] != h.sha(h.encoded(spec))):
                raise ValueError('capture binding mismatch')
            result['capture_complete'] = capture.get('capture_complete') is True
        except (ValueError, KeyError, TypeError):
            result['error'] = 'invalid capture binding'
    (directory/'result.json').write_bytes(h.encoded(result))
    return result


def main():
    global h
    module = importlib.util.spec_from_file_location('helper', SOURCES['helper.py'])
    h = importlib.util.module_from_spec(module); module.loader.exec_module(h)
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    s = sub.add_parser('seal'); s.add_argument('--baseline', type=Path, required=True)
    s.add_argument('--output', type=Path, required=True)
    for name in ('check', 'execute'):
        p = sub.add_parser(name); p.add_argument('--directory', type=Path, required=True)
        p.add_argument('--sha256', required=True)
    args = parser.parse_args()
    if args.action == 'seal':
        result = seal(args)
    elif args.action == 'check':
        prepare(args.directory.absolute(), args.sha256); result = {'integrity': True, 'target_contact': False}
    else:
        result = execute(args)
    print(json.dumps(result))
    if args.action == 'execute' and not result['capture_complete']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
