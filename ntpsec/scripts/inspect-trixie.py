#!/usr/bin/python3
"""Read-only bootstrap evidence; stdout is private JSON, never an acceptance verdict."""
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import socket
import subprocess
import sys
import time
from urllib.parse import urlsplit

LIMIT = 65536
COMMAND_SECONDS = 12
TOTAL_SECONDS = 300
ENV = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LC_ALL': 'C',
       'SYSTEMD_PAGER': '', 'PAGER': 'cat', 'MANPAGER': 'cat'}
PROFILE_FIELDS = ('connection.uuid,connection.type,connection.interface-name,'
                  'connection.autoconnect,ipv4.method,ipv4.addresses,ipv4.gateway,'
                  'ipv4.dns,ipv4.ignore-auto-dns,ipv6.method,ipv6.addresses,'
                  'ipv6.gateway,ipv6.dns,ipv6.ignore-auto-dns,ipv6.addr-gen-mode')
COMMANDS = (
    ('packages', ['dpkg-query', '-W', '-f=${binary:Package}\t${Version}\t${db:Status-Abbrev}\n',
                  'apt', 'bash', 'python3', 'openssh-server', 'systemd', 'systemd-resolved',
                  'network-manager', 'dhcpcd-base', 'dhcpcd5', 'raspi-firmware',
                  'raspi-utils', 'rpi-eeprom', 'linux-image-rpi-v8', 'raspberrypi-kernel',
                  'raspberrypi-bootloader', 'ntpsec', 'gpsd', 'gpsd-clients', 'pps-tools',
                  'i2c-tools', 'lm-sensors', 'fancontrol', 'watchdog', 'webmin', 'munin-node',
                  'needrestart']),
    ('units', ['systemctl', '--no-pager', 'show',
               '--property=Id,LoadState,ActiveState,SubState,FragmentPath,UnitFileState',
               'NetworkManager.service', 'systemd-networkd.service', 'dhcpcd.service',
               'systemd-resolved.service', 'ssh.service', 'ntpsec.service', 'gpsd.service']),
    ('failed_units', ['systemctl', '--no-pager', '--failed']),
    ('nm_unit', ['systemctl', '--no-pager', 'show', '--property=Id,LoadState,ActiveState',
                 'NetworkManager.service']),
    ('nm_version', ['nmcli', '--version']),
    ('nm_help', ['nmcli', '--help']),
    ('nm_devices', ['nmcli', '--colors', 'no', '--fields', 'GENERAL,IP4,IP6', 'device', 'show']),
    ('nm_active', ['nmcli', '--colors', 'no', '--terse', '--fields', 'UUID,TYPE,DEVICE',
                   'connection', 'show', '--active']),
    ('wifi_radio', ['nmcli', '--colors', 'no', 'radio', 'wifi']),
    ('rfkill', ['rfkill', 'list']),
    ('addresses', ['ip', '-brief', 'address']),
    ('ipv4_routes', ['ip', 'route', 'show']),
    ('ipv6_routes', ['ip', '-6', 'route', 'show']),
    ('listeners', ['ss', '-H', '-lntu']),
    ('root_mount', ['findmnt', '-n', '-o', 'SOURCE,FSTYPE', '/']),
    ('storage', ['lsblk', '-o', 'NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT']),
    ('modules', ['lsmod']),
    ('firmware_version', ['vcgencmd', 'version']),
    ('throttled', ['vcgencmd', 'get_throttled']),
    ('temperature', ['vcgencmd', 'measure_temp']),
    ('local_manuals', ['man', '--where', 'nmcli', 'NetworkManager', 'systemd-networkd',
                      'sources.list', 'vcgencmd']),
)


def check_identity(hostname, release, machine, euid):
    values = {}
    for line in release.splitlines():
        key, separator, value = line.partition('=')
        if separator and key in ('ID', 'VERSION_ID', 'VERSION_CODENAME'):
            if key in values:
                raise ValueError('duplicate OS identity field')
            parts = shlex.split(value)
            if len(parts) != 1:
                raise ValueError('malformed OS identity field')
            values[key] = parts[0]
    if (hostname != 'j2-svntp1' or machine != 'aarch64' or euid == 0
            or values != {'ID': 'debian', 'VERSION_ID': '13', 'VERSION_CODENAME': 'trixie'}):
        raise ValueError('requires non-root j2-svntp1, Debian 13/trixie, aarch64')
    return {'hostname': hostname, 'machine': machine, 'euid': euid, 'os': values}


def run(argv, seconds=COMMAND_SECONDS):
    try:
        result = subprocess.run(argv, capture_output=True, timeout=seconds,
                                check=False, env=ENV, cwd='/')
        stdout, stderr, rc = result.stdout, result.stderr, result.returncode
        error = None
    except subprocess.TimeoutExpired as exc:
        stdout, stderr, rc, error = exc.stdout or b'', exc.stderr or b'', 124, 'timeout'
    except OSError as exc:
        stdout, stderr, rc, error = b'', str(exc).encode(), 127, 'unavailable'
    truncated = len(stdout) > LIMIT or len(stderr) > LIMIT
    return {'argv': argv, 'rc': rc, 'stdout': stdout[:LIMIT].decode(errors='replace'),
            'stderr': stderr[:LIMIT].decode(errors='replace'), 'error': error,
            'truncated': truncated}


def read_file(path):
    path = Path(path)
    if not path.is_file():
        raise ValueError('not a readable regular file: ' + str(path))
    with path.open('rb') as stream:
        data = stream.read(LIMIT + 1)
    if len(data) > LIMIT:
        raise ValueError('file exceeds retained-input limit: ' + str(path))
    return data


def source_hosts(text):
    # Retain scheme/hostname only: URI credentials, paths, queries and fragments
    # never enter the report. This is inventory, not an apt parser or trust check.
    hosts = []
    for uri in re.findall(r'\b(?:https?|file)://[^\s\]#]+', text):
        parsed = urlsplit(uri)
        hosts.append({'scheme': parsed.scheme, 'hostname': parsed.hostname})
    return hosts


def source_fields(text):
    # Raw allowlisted single-line hints only; do not claim effective apt policy.
    return [line.strip() for line in text.splitlines() if re.fullmatch(
        r'(?:Types|Suites|Components|Enabled|Signed-By): [A-Za-z0-9_./:+ -]+', line)]


def ethernet_uuid(record):
    if record['rc'] != 0 or record['truncated'] or record['stderr'].strip():
        raise ValueError('active connection inventory unavailable')
    matches = []
    for line in record['stdout'].splitlines():
        parts = line.split(':')
        if len(parts) != 3:
            raise ValueError('unexpected active connection row')
        uuid, kind, device = parts
        if device == 'eth0':
            if kind != '802-3-ethernet' or not re.fullmatch(
                    r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}', uuid):
                raise ValueError('unexpected Ethernet UUID/type')
            matches.append(uuid)
    if len(matches) != 1:
        raise ValueError('requires exactly one observed active eth0 profile')
    return matches[0]


def inspect():
    identity = check_identity(socket.gethostname(), read_file('/etc/os-release').decode(),
                              os.uname().machine, os.geteuid())
    started = time.monotonic()
    boot_before = read_file('/proc/sys/kernel/random/boot_id').decode().strip()
    files = ['/etc/os-release', '/boot/firmware/config.txt', '/boot/firmware/cmdline.txt',
             '/etc/apt/sources.list']
    files += sorted(str(p) for p in Path('/etc/apt/sources.list.d').glob('*')
                    if p.suffix in ('.list', '.sources'))
    if len(files) > 24:
        raise ValueError('too many source files for approved bounded inspection')
    file_records = []
    before = {}
    for name in files:
        record = {'path': name}
        try:
            data = read_file(name)
            before[name] = hashlib.sha256(data).hexdigest()
            record['sha256'] = before[name]
            if '/apt/' in name:
                text = data.decode(errors='replace')
                record['repository_hosts'] = source_hosts(text)
                record['source_field_hints'] = source_fields(text)
            elif name == '/boot/firmware/config.txt':
                record['hardware_settings'] = [line.strip() for line in data.decode().splitlines()
                    if re.fullmatch(r'\s*(?:dtoverlay|dtparam|enable_uart|arm_64bit|include)'
                                    r'[= ][A-Za-z0-9_.,=:+/ -]+\s*', line)]
                record['includes_not_followed'] = True
        except (OSError, ValueError, UnicodeError) as exc:
            record['error'] = str(exc)
        file_records.append(record)
    records = []

    def command(label, argv):
        remaining = TOTAL_SECONDS - (time.monotonic() - started)
        if remaining <= 0:
            record = {'argv': argv, 'rc': 124, 'stdout': '', 'stderr': '',
                      'error': 'overall_deadline', 'truncated': False}
        else:
            record = run(argv, min(COMMAND_SECONDS, remaining))
        record['label'] = label
        records.append(record)
        return record

    for label, argv in COMMANDS:
        if label in ('nm_devices', 'nm_active', 'wifi_radio'):
            unit_result = next(r for r in records if r['label'] == 'nm_unit')
            manager_active = (unit_result['rc'] == 0 and not unit_result['truncated']
                              and not unit_result['stderr'].strip() and any(
                'Id=NetworkManager.service' in block.splitlines()
                and 'ActiveState=active' in block.splitlines()
                for block in unit_result['stdout'].split('\n\n')))
            if not manager_active:
                records.append({'label': label, 'argv': argv, 'rc': 126, 'stdout': '',
                                'stderr': '', 'error': 'NetworkManager active state not established',
                                'truncated': False})
                continue
        command(label, argv)
    profile_error = None
    try:
        uuid = ethernet_uuid(next(r for r in records if r['label'] == 'nm_active'))
        command('ethernet_profile', ['nmcli', '--colors', 'no', '--fields', PROFILE_FIELDS,
                                    'connection', 'show', 'uuid', uuid])
    except ValueError as exc:
        profile_error = str(exc)
    passive = []
    paths = [Path('/sys/firmware/devicetree/base/model')]
    for pattern in ('/sys/class/thermal/thermal_zone*/type',
                    '/sys/class/thermal/thermal_zone*/temp',
                    '/sys/class/hwmon/hwmon*/name', '/sys/class/hwmon/hwmon*/fan*_input'):
        paths.extend(sorted(Path('/').glob(pattern.lstrip('/'))))
    if len(paths) > 64:
        passive.append({'error': 'passive file count exceeds 64; remaining paths omitted'})
    for path in paths[:64]:
        record = {'path': str(path)}
        try:
            record['value'] = read_file(path).decode(errors='replace').strip('\x00\n')
        except (OSError, ValueError) as exc:
            record['error'] = str(exc)
        passive.append(record)
    devices = []
    for pattern in ('serial[0-9]*', 'ttyAMA[0-9]*', 'ttyS[0-9]*', 'pps[0-9]*',
                    'rtc[0-9]*', 'i2c-[0-9]*'):
        for path in sorted(Path('/dev').glob(pattern)):
            if len(devices) >= 32:
                break
            record = {'path': str(path)}
            try:
                st = path.lstat()
                record.update({'mode': oct(st.st_mode), 'uid': st.st_uid, 'gid': st.st_gid,
                               'symlink_target': os.readlink(path) if path.is_symlink() else None})
            except OSError as exc:
                record['error'] = str(exc)
            devices.append(record)
    drift = []
    for name, digest in before.items():
        try:
            if hashlib.sha256(read_file(name)).hexdigest() != digest:
                drift.append(name)
        except (OSError, ValueError):
            drift.append(name)
    boot_error = None
    try:
        boot_after = read_file('/proc/sys/kernel/random/boot_id').decode().strip()
    except (OSError, ValueError, UnicodeError) as exc:
        boot_after, boot_error = None, str(exc)
    gaps = (bool(profile_error) or bool(drift) or boot_before != boot_after
            or any(r['rc'] != 0 or r['stderr'].strip() or r['truncated'] for r in records)
            or len(devices) == 32 or any('error' in r for r in file_records + passive + devices))
    return {'identity': identity, 'kernel': os.uname().release, 'boot_id': boot_before,
            'boot_unchanged': boot_before == boot_after, 'boot_after_error': boot_error,
            'files': file_records,
            'commands': records, 'passive': passive, 'device_metadata': devices,
            'device_metadata_limit_reached': len(devices) == 32,
            'profile_error': profile_error,
            'file_hash_drift': drift, 'collection_has_gaps': gaps,
            'platform_or_service_accepted': False,
            'limitations': ['snapshot only; no sensor, firmware, network or service mutation',
                            'source hints and boot snippets are not effective configuration or trust validation',
                            'missing tools, permissions and unsupported fields remain gaps',
                            'no Wi-Fi disablement, thermal stress or NTP/GPSD acceptance']}


def policy_files():
    paths = {Path('/etc/needrestart/needrestart.conf'), Path('/etc/apt/apt.conf'),
             Path('/etc/apt/preferences'), Path('/usr/lib/needrestart/apt-pinvoke')}
    for directory, pattern in (('/etc/needrestart/conf.d', '*.conf'),
                               ('/etc/apt/apt.conf.d', '*'),
                               ('/etc/apt/preferences.d', '*')):
        paths.update(Path(directory).glob(pattern))
    if len(paths) > 96:
        raise ValueError('policy input count exceeds approved 96-file bound')
    return sorted(paths)


def redact_policy(text):
    # Keep executable policy as data. Never eval it or print credentials.
    text = re.sub(r'\b((?:https?|socks\d?)://)[^\s/@]+@', r'\1[redacted]@', text)
    return '\n'.join('[credential-bearing line redacted]' if re.search(
        r'(?i)(?:password|passwd|authorization|api[_-]?key|access[_-]?token|token|secret|credential)',
        line) else line for line in text.splitlines())


def policy_snapshot(paths):
    records = []
    for path in paths:
        record = {'path': str(path)}
        try:
            st = path.lstat()
            if path.is_symlink() or not path.is_file():
                raise ValueError('symlink or nonregular policy input rejected')
            data = read_file(path)
            record.update({'uid': st.st_uid, 'gid': st.st_gid, 'mode': oct(st.st_mode & 0o7777),
                           'sha256': hashlib.sha256(data).hexdigest(),
                           'text': redact_policy(data.decode())})
        except FileNotFoundError:
            record['absent'] = True
        except (OSError, ValueError, UnicodeError) as exc:
            record['error'] = str(exc)
        records.append(record)
    return records


def package_policy():
    identity = check_identity(socket.gethostname(), read_file('/etc/os-release').decode(),
                              os.uname().machine, os.geteuid())
    boot_before = read_file('/proc/sys/kernel/random/boot_id').decode().strip()
    paths = policy_files()
    before = policy_snapshot(paths)
    commands = (
        ('package_status', ['dpkg-query', '-W', '-f=${binary:Package}\t${Version}\t${db:Status-Abbrev}\n',
                            'needrestart', 'apt', 'libc6', 'systemd', 'openssh-server',
                            'linux-image-rpi-v8', 'raspi-firmware', 'unattended-upgrades']),
        ('cached_candidates', ['apt-cache', '-o', 'Dir::Cache::pkgcache=',
                                '-o', 'Dir::Cache::srcpkgcache=', 'policy', 'needrestart',
                                'apt', 'libc6', 'systemd', 'openssh-server',
                                'linux-image-rpi-v8', 'raspi-firmware']),
        ('dpkg_audit', ['dpkg', '--audit']),
        ('needrestart_package_files', ['dpkg-query', '-L', 'needrestart']),
        ('update_units', ['systemctl', '--no-pager', 'show',
                          '--property=Id,LoadState,ActiveState,SubState,FragmentPath,UnitFileState',
                          'apt-daily.timer', 'apt-daily-upgrade.timer', 'apt-daily.service',
                          'apt-daily-upgrade.service', 'unattended-upgrades.service']),
        ('local_manuals', ['man', '--where', 'needrestart', 'apt-get', 'apt-cache', 'apt.conf']),
    )
    records = []
    for label, argv in commands:
        record = run(argv)
        record['label'] = label
        # apt-cache can describe configured repository/proxy URIs.
        record['stdout'] = redact_policy(record['stdout'])
        record['stderr'] = redact_policy(record['stderr'])
        records.append(record)
    after_error = None
    try:
        after = policy_snapshot(policy_files())
    except (OSError, ValueError) as exc:
        after, after_error = [], str(exc)

    def signatures(items):
        return {r['path']: {k: v for k, v in r.items() if k != 'text'} for r in items}

    drift = bool(after_error) or signatures(before) != signatures(after)
    before_by_path = {r['path']: r for r in before}
    for record in after:
        if record.get('sha256') == before_by_path.get(record['path'], {}).get('sha256'):
            record.pop('text', None)
    boot_error = None
    try:
        boot_after = read_file('/proc/sys/kernel/random/boot_id').decode().strip()
    except (OSError, ValueError, UnicodeError) as exc:
        boot_after, boot_error = None, str(exc)
    binaries = []
    for path in (Path('/usr/sbin/needrestart'), Path('/usr/lib/needrestart/apt-pinvoke')):
        record = {'path': str(path)}
        try:
            st = path.lstat()
            record.update({'mode': oct(st.st_mode), 'uid': st.st_uid, 'gid': st.st_gid,
                           'symlink_target': os.readlink(path) if path.is_symlink() else None})
        except FileNotFoundError:
            record['absent'] = True
        except OSError as exc:
            record['error'] = str(exc)
        binaries.append(record)
    audit = next(r for r in records if r['label'] == 'dpkg_audit')
    audit_clean = audit['rc'] == 0 and not audit['stdout'].strip() and not audit['stderr'].strip()
    gap = (drift or boot_before != boot_after or not audit_clean
           or any('error' in r for r in before + after + binaries)
           or any(r['rc'] != 0 or r['truncated'] for r in records))
    return {'mode': 'package_policy', 'identity': identity, 'kernel': os.uname().release,
            'boot_id': boot_before, 'boot_unchanged': boot_before == boot_after,
            'boot_after_error': boot_error, 'policy_before': before, 'policy_after': after,
            'policy_drift': drift, 'policy_after_error': after_error,
            'dpkg_audit_clean': audit_clean, 'commands': records, 'binary_metadata': binaries,
            'collection_has_gaps': gap, 'effective_policy_accepted': False,
            'package_mutation_authorized': False,
            'limitations': ['cached package candidates are not refreshed or accepted update inputs',
                            'policy captured as text, never loaded as Perl or shell',
                            'needrestart, notification scripts and apt hooks not executed',
                            'ownership, overrides and effective policy require explicit review']}


def main():
    if sys.argv[1:] not in (['--inspect'], ['--package-policy']):
        print('usage: inspect-trixie.py --inspect | --package-policy', file=sys.stderr)
        return 1
    try:
        report = package_policy() if sys.argv[1:] == ['--package-policy'] else inspect()
    except (OSError, ValueError, UnicodeError) as exc:
        print(json.dumps({'inspection_error': str(exc), 'completion_verified': False}))
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 2 if report['collection_has_gaps'] else 0


if __name__ == '__main__':
    sys.exit(main())
