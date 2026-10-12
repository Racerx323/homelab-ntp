#!/usr/bin/python3
"""Read-only bootstrap evidence; stdout is private JSON, never an acceptance verdict."""
import base64
import gzip
import hashlib
import io
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
               'systemd-resolved.service', 'ssh.service', 'ntpsec.service', 'gpsd.service',
               'gpsd.socket', 'timeservice.service']),
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


def check_identity(hostname, release, machine, euid, expected_hostname='j2-svntp1'):
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
    if (hostname != expected_hostname or machine != 'aarch64' or euid == 0
            or values != {'ID': 'debian', 'VERSION_ID': '13', 'VERSION_CODENAME': 'trixie'}):
        raise ValueError('requires approved non-root hostname, Debian 13/trixie, aarch64')
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


def directory_files(directory, pattern, directory_members=None):
    if directory_members is None:
        return Path(directory).glob(pattern)
    return (Path(directory) / name for name in directory_members[directory] if Path(name).match(pattern))


def policy_files(directory_members=None):
    paths = {Path('/etc/needrestart/needrestart.conf'), Path('/etc/apt/apt.conf'),
             Path('/etc/apt/preferences'), Path('/usr/lib/needrestart/apt-pinvoke')}
    for directory, pattern in (('/etc/needrestart/conf.d', '*.conf'),
                               ('/etc/apt/apt.conf.d', '*'),
                               ('/etc/apt/preferences.d', '*')):
        paths.update(directory_files(directory, pattern, directory_members))
    if len(paths) > 96:
        raise ValueError('policy input count exceeds approved 96-file bound')
    return sorted(paths)


def redact_policy(text):
    # Keep executable policy as data. Never eval it or print credentials.
    text = re.sub(r'\b((?:https?|socks\d?)://)[^\s/@]+@', r'\1[redacted]@', text)
    return '\n'.join('[credential-bearing line redacted]' if re.search(
        r'(?i)(?:password|passwd|authorization|api[_-]?key|access[_-]?token|token|secret|credential)',
        line) else line for line in text.splitlines())


def policy_snapshot(paths, public_keyrings=(), compressed_documents=False):
    records = []
    for path in paths:
        record = {'path': str(path)}
        try:
            st = path.lstat()
            if path.is_symlink() or not path.is_file():
                raise ValueError('symlink or nonregular policy input rejected')
            data = read_file(path)
            record.update({'uid': st.st_uid, 'gid': st.st_gid, 'mode': oct(st.st_mode & 0o7777),
                           'sha256': hashlib.sha256(data).hexdigest()})
            if str(path) in public_keyrings:
                record['public_keyring_base64'] = base64.b64encode(data).decode('ascii')
            else:
                if compressed_documents and str(path).endswith('.gz'):
                    with gzip.GzipFile(fileobj=io.BytesIO(data)) as stream:
                        data = stream.read(262145)
                    if len(data) > 262144:
                        raise ValueError('expanded manual exceeds approved 256 KiB bound')
                record['text'] = redact_policy(data.decode())
        except FileNotFoundError:
            record['absent'] = True
        except (OSError, ValueError, UnicodeError, EOFError) as exc:
            record['error'] = str(exc)
        records.append(record)
    return records


BASELINE_PACKAGES = tuple(COMMANDS[0][1][3:]) + (
    'msmtp', 'msmtp-mta', 'cron', 'coreutils', 'ca-certificates', 'util-linux',
    'debian-archive-keyring', 'raspberrypi-archive-keyring', 'gpg', 'gpgv',
    'perl', 'dpkg', 'gettext-base', 'libintl-perl', 'libproc-processtable-perl',
    'libsort-naturally-perl', 'libterm-readkey-perl', 'libmodule-find-perl',
    'procps', 'xz-utils', 'libpam-systemd', 'sysvinit-core', 'libimvirt-perl')


def installation_input_files():
    paths = set(policy_files())
    paths.update(map(Path, ('/etc/apt/sources.list', '/etc/apt/listchanges.conf',
                           '/etc/dpkg/dpkg.cfg', '/etc/crontab',
                           '/etc/cron.d/needrestart_check')))
    for directory, pattern in (('/etc/apt/sources.list.d', '*.list'),
                               ('/etc/apt/sources.list.d', '*.sources'),
                               ('/etc/dpkg/dpkg.cfg.d', '*'),
                               ('/etc/apt/listchanges.conf.d', '*')):
        paths.update(Path(directory).glob(pattern))
    if len(paths) > 160:
        raise ValueError('installation input count exceeds approved 160-file bound')
    return sorted(paths)


def input_metadata():
    paths = {Path('/etc/msmtprc'), Path('/usr/sbin/sendmail'),
             Path('/etc/aliases'), Path('/etc/apt/trusted.gpg')}
    for directory, pattern in (('/boot', 'vmlinuz*'),
                               ('/boot/firmware', 'kernel*.img'),
                               ('/usr/share/keyrings', '*.gpg'),
                               ('/usr/share/keyrings', '*.asc'),
                               ('/usr/share/keyrings', '*.pgp'),
                               ('/etc/apt/keyrings', '*.gpg'),
                               ('/etc/apt/keyrings', '*.asc'),
                               ('/etc/apt/keyrings', '*.pgp'),
                               ('/etc/apt/trusted.gpg.d', '*.gpg'),
                               ('/etc/apt/trusted.gpg.d', '*.asc'),
                               ('/etc/apt/trusted.gpg.d', '*.pgp')):
        paths.update(Path(directory).glob(pattern))
    if len(paths) > 128:
        raise ValueError('metadata path count exceeds approved 128-file bound')
    records = []
    for path in sorted(paths):
        record = {'path': str(path)}
        try:
            st = path.lstat()
            record.update({'uid': st.st_uid, 'gid': st.st_gid,
                           'mode': oct(st.st_mode & 0o7777), 'size': st.st_size,
                           'symlink_target': os.readlink(path) if path.is_symlink() else None})
            if str(path) == '/etc/msmtprc':
                if path.is_symlink() or not path.is_file():
                    raise ValueError('symlink or nonregular relay configuration rejected')
                record['mail_account_fields'] = mail_account_fields(read_file(path).decode())
            # Never read or hash relay credentials. Public keyring hashes are
            # identifiers only; their trust is not established by this query.
            if 'keyrings' in str(path) or str(path).startswith('/etc/apt/trusted.gpg'):
                if path.is_symlink() or not path.is_file():
                    raise ValueError('symlink or nonregular keyring rejected')
                record['sha256'] = hashlib.sha256(read_file(path)).hexdigest()
        except FileNotFoundError:
            record['absent'] = True
        except (OSError, ValueError, UnicodeError) as exc:
            record['error'] = str(exc)
        records.append(record)
    return records


def mail_account_fields(text):
    allowed = {'defaults', 'account', 'host', 'port', 'from', 'domain', 'auth', 'tls',
               'aliases', 'set_from_header', 'allow_from_override'}
    records = []
    for line in text.splitlines():
        words = line.strip().split(None, 1)
        if not words or words[0].startswith('#'):
            continue
        if words[0] in allowed:
            records.append(redact_policy(line.strip()))
        else:
            records.append('[unreviewed directive value omitted]')
    return records


def package_policy(input_review=False):
    identity = check_identity(socket.gethostname(), read_file('/etc/os-release').decode(),
                              os.uname().machine, os.geteuid())
    boot_before = read_file('/proc/sys/kernel/random/boot_id').decode().strip()
    file_list = installation_input_files if input_review else policy_files
    paths = file_list()
    before = policy_snapshot(paths)
    metadata_before = input_metadata() if input_review else []
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
    if input_review:
        packages = list(dict.fromkeys(BASELINE_PACKAGES))
        commands += (
            ('native_architecture', ['dpkg', '--print-architecture']),
            ('foreign_architectures', ['dpkg', '--print-foreign-architectures']),
            ('baseline_package_status', ['dpkg-query', '-W',
             '-f=${binary:Package}\t${Version}\t${db:Status-Abbrev}\n'] + packages),
            ('baseline_cached_candidates', ['apt-cache', '-o', 'Dir::Cache::pkgcache=',
             '-o', 'Dir::Cache::srcpkgcache=', 'policy'] + packages),
            ('baseline_cached_dependencies', ['apt-cache', '-o', 'Dir::Cache::pkgcache=',
             '-o', 'Dir::Cache::srcpkgcache=', 'depends'] + packages),
            ('pi_fragment_owner', ['dpkg-query', '-S', '/etc/needrestart/conf.d/rpi-kernel.conf']),
            ('mail_transport_owner', ['dpkg-query', '-S', '/usr/sbin/sendmail']),
            ('reporting_units', ['systemctl', '--no-pager', 'show',
             '--property=Id,LoadState,ActiveState,SubState,FragmentPath,UnitFileState',
             'cron.service', 'msmtp.service', 'watchdog.service', 'munin-node.service',
             'webmin.service']),
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
        after = policy_snapshot(file_list())
    except (OSError, ValueError) as exc:
        after, after_error = [], str(exc)

    def signatures(items):
        return {r['path']: {k: v for k, v in r.items() if k != 'text'} for r in items}

    drift = bool(after_error) or signatures(before) != signatures(after)
    metadata_after = input_metadata() if input_review else []
    metadata_drift = metadata_before != metadata_after
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
    gap = (drift or metadata_drift or boot_before != boot_after or not audit_clean
           or any('error' in r for r in before + after + binaries)
           or any('error' in r for r in metadata_before + metadata_after)
           or any(r['rc'] != 0 or r['truncated'] for r in records))
    return {'mode': 'installation_inputs' if input_review else 'package_policy',
            'identity': identity, 'kernel': os.uname().release,
            'boot_id': boot_before, 'boot_unchanged': boot_before == boot_after,
            'boot_after_error': boot_error, 'policy_before': before, 'policy_after': after,
            'policy_drift': drift, 'policy_after_error': after_error,
            'dpkg_audit_clean': audit_clean, 'commands': records, 'binary_metadata': binaries,
            'input_metadata_before': metadata_before, 'input_metadata_after': metadata_after,
            'input_metadata_drift': metadata_drift,
            'collection_has_gaps': gap, 'effective_policy_accepted': False,
            'package_mutation_authorized': False,
            'limitations': ['cached package candidates are not refreshed or accepted update inputs',
                            'policy captured as text, never loaded as Perl or shell',
                            'needrestart, notification scripts and apt hooks not executed',
                            'ownership, overrides and effective policy require explicit review',
                            'cached direct dependencies are not a fresh resolved dependency closure',
                            'keyring metadata/hashes do not prove signatures or capture public key material',
                            'msmtprc fields are allowlisted without credential hashes; aliases content omitted',
                            'custom includes, keyring paths and other schedules require closure review']}


PUBLIC_KEYRINGS = ('/usr/share/keyrings/debian-archive-keyring.pgp',
                   '/usr/share/keyrings/raspberrypi-archive-keyring.pgp')
HOOK_PACKAGES = ('apt', 'apt-listchanges', 'debconf', 'debian-archive-keyring',
                 'raspberrypi-archive-keyring', 'raspberrypi-sys-mods', 'gpgv', 'sqv')


def keyring_hook_files(package_listing, directory_members=None):
    paths = set(policy_files() if directory_members is None else policy_files(directory_members))
    paths.update(map(Path, PUBLIC_KEYRINGS + (
        '/etc/apt/sources.list', '/etc/apt/listchanges.conf', '/etc/dpkg/dpkg.cfg',
        '/usr/bin/apt-listchanges', '/usr/sbin/dpkg-preconfigure',
        '/usr/share/man/man1/apt-listchanges.1.gz',
        '/usr/share/man/man8/dpkg-preconfigure.8.gz',
        '/usr/share/man/man8/apt-get.8.gz', '/usr/share/man/man8/apt-secure.8.gz',
        '/usr/share/man/man5/apt.conf.5.gz', '/usr/share/man/man5/sources.list.5.gz')))
    for directory, pattern in (('/etc/apt/sources.list.d', '*.list'),
                               ('/etc/apt/sources.list.d', '*.sources'),
                               ('/etc/apt/listchanges.conf.d', '*'),
                               ('/etc/dpkg/dpkg.cfg.d', '*')):
        paths.update(directory_files(directory, pattern, directory_members))
    for line in package_listing.splitlines():
        path = Path(line)
        if '..' in path.parts:
            raise ValueError('parent traversal in hook package listing rejected')
        if (((line.startswith('/usr/share/apt-listchanges/')
              or line.startswith('/usr/lib/python3/dist-packages/apt_listchanges/'))
             and line.endswith('.py'))
                or (line.startswith('/usr/share/perl5/Debconf/') and line.endswith('.pm'))):
            paths.add(path)
    if len(paths) > 128:
        raise ValueError('keyring/hook input count exceeds approved 128-file bound')
    return sorted(paths)


def keyring_hooks():
    identity = check_identity(socket.gethostname(), read_file('/etc/os-release').decode(),
                              os.uname().machine, os.geteuid())
    boot_before = read_file('/proc/sys/kernel/random/boot_id').decode().strip()
    records = []

    def query(label, argv):
        record = run(argv)
        record['label'] = label
        record['stdout'] = redact_policy(record['stdout'])
        record['stderr'] = redact_policy(record['stderr'])
        records.append(record)
        return record

    versions_argv = ['dpkg-query', '-W',
                     '-f=${binary:Package}\t${Version}\t${db:Status-Abbrev}\n'] + list(HOOK_PACKAGES)
    listing_argv = ['dpkg-query', '-L', 'apt-listchanges', 'debconf']
    versions_before = query('package_versions_before', versions_argv)
    listing_before = query('hook_package_files_before', listing_argv)
    paths = keyring_hook_files(listing_before['stdout'])
    before = policy_snapshot(paths, PUBLIC_KEYRINGS, compressed_documents=True)
    query('keyring_and_hook_owners', ['dpkg-query', '-S'] + list(PUBLIC_KEYRINGS) + [
        '/usr/bin/apt-listchanges', '/usr/sbin/dpkg-preconfigure',
        '/etc/needrestart/conf.d/rpi-kernel.conf'])
    verification = query('package_file_verification', ['dpkg', '--verify',
        'debian-archive-keyring', 'raspberrypi-archive-keyring', 'apt-listchanges', 'debconf'])
    audit = query('dpkg_audit', ['dpkg', '--audit'])
    query('apt_version', ['apt-get', '--version'])
    query('update_units', ['systemctl', '--no-pager', 'show',
        '--property=Id,LoadState,ActiveState,SubState,FragmentPath,UnitFileState',
        'apt-daily.timer', 'apt-daily-upgrade.timer', 'apt-daily.service',
        'apt-daily-upgrade.service', 'unattended-upgrades.service'])
    listing_after = query('hook_package_files_after', listing_argv)
    versions_after = query('package_versions_after', versions_argv)
    after = policy_snapshot(keyring_hook_files(listing_after['stdout']), PUBLIC_KEYRINGS,
                            compressed_documents=True)
    boot_after = read_file('/proc/sys/kernel/random/boot_id').decode().strip()

    def signatures(items):
        return {r['path']: {k: v for k, v in r.items()
                            if k not in ('text', 'public_keyring_base64')} for r in items}

    drift = (signatures(before) != signatures(after)
             or versions_before['stdout'] != versions_after['stdout']
             or listing_before['stdout'] != listing_after['stdout'])
    previous = {r['path']: r for r in before}
    for record in after:
        if record.get('sha256') == previous.get(record['path'], {}).get('sha256'):
            record.pop('text', None)
            record.pop('public_keyring_base64', None)
    audit_clean = audit['rc'] == 0 and not audit['stdout'].strip() and not audit['stderr'].strip()
    verification_clean = (verification['rc'] == 0 and not verification['stdout'].strip()
                          and not verification['stderr'].strip())
    redaction = any('[credential-bearing line redacted]' in r.get('text', '')
                    or '[redacted]@' in r.get('text', '') for r in before + after)
    keyring_gaps = any(not any(r['path'] == path and 'public_keyring_base64' in r
                              for r in before) for path in PUBLIC_KEYRINGS)
    gap = (drift or boot_before != boot_after or keyring_gaps or redaction
           or not audit_clean or not verification_clean
           or any('error' in r for r in before + after)
           or any(r['rc'] != 0 or r['truncated'] for r in records))
    return {'mode': 'keyring_hooks', 'identity': identity, 'kernel': os.uname().release,
            'boot_id': boot_before, 'boot_unchanged': boot_before == boot_after,
            'inputs_before': before, 'inputs_after': after, 'input_drift': drift,
            'commands': records, 'dpkg_audit_clean': audit_clean,
            'package_file_verification_clean': verification_clean,
            'redaction_present': redaction, 'collection_has_gaps': gap,
            'package_mutation_authorized': False, 'signature_trust_accepted': False,
            'effective_hook_policy_accepted': False,
            'limitations': ['public keyrings are captured without importing or invoking a verifier',
                            'package ownership/checksums do not independently establish archive trust',
                            'hook programs, modules and manuals are data; imports/includes need review',
                            'no metadata refresh, package solver, hooks, notifications or sudo executed']}


def main():
    if sys.argv[1:] not in (['--inspect'], ['--package-policy'], ['--installation-inputs'],
                           ['--keyring-hooks']):
        print('usage: inspect-trixie.py --inspect | --package-policy | --installation-inputs | --keyring-hooks', file=sys.stderr)
        return 1
    try:
        report = (keyring_hooks() if sys.argv[1:] == ['--keyring-hooks'] else
                  inspect() if sys.argv[1:] == ['--inspect'] else
                  package_policy(input_review=sys.argv[1:] == ['--installation-inputs']))
    except (OSError, ValueError, UnicodeError) as exc:
        print(json.dumps({'inspection_error': str(exc), 'completion_verified': False}))
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 2 if report['collection_has_gaps'] else 0


if __name__ == '__main__':
    sys.exit(main())
