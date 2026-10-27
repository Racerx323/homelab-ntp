#!/usr/bin/python3
"""Bounded maintenance inventory and native static rule verification; injected helper."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import socket
import stat
import sys
import time

h = None
ENV = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LC_ALL': 'C', 'PYTHONDONTWRITEBYTECODE': '1'}
CONFIG_DIRS = ('/etc/apt/apt.conf.d', '/etc/apt/sources.list.d', '/etc/apt/preferences.d',
               '/etc/dpkg/dpkg.cfg.d', '/etc/needrestart/conf.d', '/etc/apt/keyrings',
               '/etc/apt/trusted.gpg.d', '/usr/share/keyrings', '/etc/cron.d')
RULE_DIRS = ('/etc/udev/rules.d', '/run/udev/rules.d', '/usr/local/lib/udev/rules.d', '/usr/lib/udev/rules.d')
FILES = ('/etc/apt/apt.conf', '/etc/apt/sources.list', '/etc/apt/preferences',
         '/etc/apt/trusted.gpg', '/etc/dpkg/dpkg.cfg', '/etc/needrestart/needrestart.conf',
         '/etc/needrestart/notify.conf', '/etc/default/rpi-eeprom-update',
         '/etc/default/raspberrypi-kernel', '/etc/default/ntpsec', '/etc/default/gpsd',
         '/etc/ntp.conf', '/etc/ntpsec-timeservice.json', '/etc/watchdog.conf', '/etc/crontab',
         '/usr/sbin/policy-rc.d', '/usr/sbin/needrestart', '/usr/lib/needrestart/apt-pinvoke',
         '/usr/bin/rpi-eeprom-update', '/usr/bin/rpi-eeprom-config', '/usr/bin/udevadm',
         '/usr/bin/apt-config', '/usr/bin/apt-get', '/usr/bin/dpkg', '/usr/bin/dpkg-query',
         '/usr/bin/gpgv', '/usr/bin/sqv', '/boot/firmware/config.txt', '/boot/firmware/cmdline.txt',
         '/boot/firmware/pieeprom.upd', '/boot/firmware/pieeprom.sig', '/boot/firmware/recovery.bin',
         '/var/lib/dpkg/status', '/var/lib/apt/extended_states', '/etc/os-release',
         '/usr/local/libexec/timeservice.py', '/usr/local/libexec/gpsd-pairing.py',
         '/usr/local/libexec/pps-startup.py')
SERVICES = ('timeservice.service', 'gpsd.service', 'gpsd.socket', 'cron.service', 'munin-node.service',
            'watchdog.service', 'rpi-eeprom-update.service', 'apt-daily.service',
            'apt-daily-upgrade.service', 'unattended-upgrades.service')
TIMERS = ('apt-daily.timer', 'apt-daily-upgrade.timer')
LOCKS = ('/var/lib/dpkg/lock', '/var/lib/dpkg/lock-frontend', '/var/lib/apt/lists/lock',
         '/var/cache/apt/archives/lock')
VENDOR = '/usr/lib/udev/rules.d/90-alsa-restore.rules'
PRIVATE = re.compile(r'(?i)(?:password|passwd|secret|token|authorization|private.key|://[^/\s]+@|-----BEGIN .*PRIVATE)')


def require(ok, message):
    if not ok:
        raise ValueError(message)


def scrub(text):
    # Preserve hashes, never preserve a potentially credential-bearing value.
    return '\n'.join('[REDACTED: review required]' if PRIVATE.search(line) else line
                     for line in text.splitlines()) + ('\n' if text.endswith('\n') else '')


def record(path, content=False):
    path = Path(path)
    require(not any(p.is_symlink() for p in path.parents), 'indirect ancestor: '+str(path))
    try:
        st = path.lstat()
    except FileNotFoundError:
        return {'missing': True}
    row = {'uid': st.st_uid, 'gid': st.st_gid, 'mode': stat.S_IMODE(st.st_mode),
           'device': st.st_dev, 'inode': st.st_ino, 'size': st.st_size, 'mtime_ns': st.st_mtime_ns}
    if stat.S_ISLNK(st.st_mode):
        return dict(row, link=os.readlink(path))
    require(stat.S_ISREG(st.st_mode) and st.st_uid == 0 and not st.st_mode & 0o022,
            'unprotected/nonregular input: '+str(path))
    require(st.st_size <= 16*1024**2, 'file bound: '+str(path))
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as stream:
        before = os.fstat(stream.fileno())
        require((before.st_dev, before.st_ino) == (st.st_dev, st.st_ino), 'file replaced')
        raw = stream.read(16*1024**2+1)
        after = os.fstat(stream.fileno())
    require(len(raw) <= 16*1024**2 and (before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
            (after.st_size, after.st_mtime_ns, after.st_ctime_ns), 'file changed/bound')
    row['sha256'] = hashlib.sha256(raw).hexdigest()
    if content and len(raw) <= 65536 and b'\x00' not in raw:
        row['text'] = scrub(raw.decode('utf-8', errors='replace'))
        row['redacted'] = '[REDACTED:' in row['text']
    return row


def members(directory):
    path = Path(directory)
    if not path.exists() and not path.is_symlink():
        return []
    info = path.lstat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o022,
            'unsafe directory: '+directory)
    names = sorted(path.iterdir())
    require(len(names) <= 256, 'directory bound: '+directory)
    return names


def configuration(extra=()):
    paths = set(map(Path, FILES)) | set(map(Path, extra))
    listing = {}
    for directory in CONFIG_DIRS + RULE_DIRS:
        names = members(directory)
        listing[directory] = [str(p) for p in names]
        for path in names:
            if directory in RULE_DIRS:
                if path.name.endswith('.rules'):
                    paths.add(path)
            else:
                require(not path.is_dir(), 'nested configuration needs review: '+str(path))
                paths.add(path)
    require(len(paths) <= 768, 'configuration total bound')
    result = {}
    for path in sorted(paths):
        # Private APT auth files are outside this closed selection. Public key bytes are not exported.
        text = str(path).startswith(('/etc/', '/usr/lib/udev/', '/usr/local/lib/udev/', '/usr/lib/systemd/', '/run/systemd/'))
        text = text and not any(s in str(path) for s in ('keyring', 'trusted.gpg'))
        result[str(path)] = record(path, text)
        require(len(json.dumps(result)) <= 1024**2, 'configuration output bound')
    return {'directories': listing, 'files': result}


def command(argv, allowed=(0,), timeout=12):
    row = h.bounded(argv, timeout=timeout, limit=1024**2, env=ENV)
    row['stdout'] = scrub(row.get('stdout', ''))
    row['stderr'] = scrub(row.get('stderr', ''))
    row['accepted'] = row.get('returncode') in allowed and not row.get('error')
    return row


def query(report, label, argv, allowed=(0,), timeout=12):
    row = command(argv, allowed, timeout)
    report[label] = row
    require(row['accepted'], 'command failed: '+label)
    return row['stdout']


def list_metadata():
    result = {}
    for path in members('/var/lib/apt/lists'):
        st = path.lstat()
        result[str(path)] = {'mode': st.st_mode, 'uid': st.st_uid, 'size': st.st_size,
                             'inode': st.st_ino, 'mtime_ns': st.st_mtime_ns}
    return result


def lock_state():
    identities = {}
    for name in LOCKS:
        p = Path(name)
        if p.exists():
            st = p.lstat()
            require(stat.S_ISREG(st.st_mode), 'nonregular package lock')
            identities[f'{os.major(st.st_dev):02x}:{os.minor(st.st_dev):02x}:{st.st_ino}'] = name
    text = Path('/proc/locks').read_text()
    require(len(text) <= 1024**2, 'lock bound')
    return {'files': identities, 'held': [line for line in text.splitlines()
                                        if any(key in line.split() for key in identities)]}


def native_verify(parent, baseline, candidate, run=command):
    """Exclusive scratch; exact inode-bound cleanup, including parser failure."""
    parent = Path(parent)
    info = parent.parent.lstat()
    require(parent.parent.resolve() == parent.parent.absolute() and stat.S_ISDIR(info.st_mode)
            and info.st_uid == os.geteuid() and (not info.st_mode & 0o022 or info.st_mode & stat.S_ISVTX),
            'unsafe scratch parent')
    result = {'workspace': str(parent), 'created': False, 'cleaned': False}
    identities = {}
    try:
        parent.mkdir(mode=0o700)
        result['created'] = True
        root = parent.stat()
        for name, raw in (('baseline.rules', baseline), ('candidate.rules', candidate)):
            fd = os.open(parent/name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'wb') as f:
                f.write(raw)
                f.flush()
                os.fsync(f.fileno())
                st = os.fstat(f.fileno())
                identities[name] = (st.st_dev, st.st_ino)
        for name in identities:
            result[name] = run(['/usr/bin/udevadm', 'verify', str(parent/name)], (0, 1))
    except BaseException as error:
        result['error'] = type(error).__name__+': '+str(error)
    finally:
        if result['created']:
            try:
                now = parent.lstat()
                require(stat.S_ISDIR(now.st_mode) and (now.st_dev, now.st_ino) == (root.st_dev, root.st_ino)
                        and now.st_uid == os.geteuid() and stat.S_IMODE(now.st_mode) == 0o700,
                        'scratch identity changed')
                require(set(p.name for p in parent.iterdir()) == set(identities), 'scratch membership changed')
                for name, identity in identities.items():
                    st = (parent/name).lstat()
                    require(stat.S_ISREG(st.st_mode) and st.st_nlink == 1 and (st.st_dev, st.st_ino) == identity,
                            'scratch file replaced')
                for name in identities:
                    (parent/name).unlink()
                parent.rmdir()
                result['cleaned'] = True
            except BaseException as error:
                result['cleanup_error'] = str(error)
    return result


def runtime(processes):
    result = {}
    for line in processes.splitlines():
        fields = line.split()
        if len(fields) == 3 and fields[2] in ('ntpd', 'gpsd', 'watchdog', 'munin-node', 'cron'):
            pid = int(fields[0])
            path = Path('/proc')/str(pid)
            value = (path/'stat').read_text().rsplit(')', 1)[1].split()
            executable = os.readlink(path/'exe')
            result[str(pid)] = {'name': fields[2], 'parent': fields[1], 'start_ticks': value[19],
                                'executable': executable, 'binary': record(executable)}
    require(len(result) <= 16, 'service process bound')
    require(any(row['name'] == 'ntpd' for row in result.values()), 'ntpd process missing')
    return result


def collect(spec, baseline, candidate):
    report = {'operation_id': spec['operation_id'], 'capture_complete': False, 'production_accepted': False,
              'started_epoch': time.time(), 'commands': {}, 'metadata_refreshed': False}
    def identity():
        require(os.geteuid() == 0 and os.environ.get('SUDO_USER') == 'ama' and os.environ.get('SUDO_UID') == '1000'
                and socket.gethostname() == spec['hostname'] and os.uname().release == spec['kernel_release'], 'identity drift')
        require(spec['prepared_epoch']-300 <= time.time() < spec['expires_epoch'], 'expired/clock drift')
        require(sys.dont_write_bytecode and sys.flags.isolated, 'isolated Python required')
        value = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        require(value == spec['boot'], 'boot drift')
        return value
    def services():
        result = {}
        for unit in SERVICES + TIMERS:
            props = 'Id,LoadState,ActiveState,SubState,FragmentPath,DropInPaths'
            if unit in SERVICES:
                props += ',MainPID,InvocationID,NRestarts'
            result[unit] = command(['/usr/bin/systemctl', '--no-pager', 'show', '--property='+props, unit])
            require(result[unit]['accepted'], 'unit query failed: '+unit)
        return result
    def alarm(*_):
        raise TimeoutError('180-second worker deadline')
    signal.signal(signal.SIGALRM, alarm)
    signal.signal(signal.SIGTERM, alarm)
    signal.signal(signal.SIGHUP, alarm)
    signal.alarm(180)
    try:
        report['boot_before'] = identity()
        report['services_before'] = services()
        unit_paths = []
        for row in report['services_before'].values():
            for line in row['stdout'].splitlines():
                if line.startswith(('FragmentPath=', 'DropInPaths=')):
                    for path in line.split('=', 1)[1].split():
                        require(path.startswith(('/etc/systemd/', '/usr/lib/systemd/', '/lib/systemd/', '/run/systemd/')), 'unit path')
                        # /lib is the distribution-owned merged-/usr alias; record canonical path explicitly.
                        unit_paths.append(str(Path(path).resolve()))
        report['before'] = configuration(unit_paths)
        require(report['before']['files'][VENDOR].get('sha256') == hashlib.sha256(baseline).hexdigest(), 'vendor drift')
        report['locks_before'] = lock_state()
        report['apt_lists_before'] = list_metadata()
        commands = report['commands']
        query(commands, 'inventory', ['/usr/bin/dpkg-query', '-W', '-f=${binary:Package}\t${Version}\t${db:Status-Abbrev}\n'])
        query(commands, 'holds', ['/usr/bin/dpkg', '--get-selections'])
        query(commands, 'audit', ['/usr/bin/dpkg', '--audit'])
        query(commands, 'architecture', ['/usr/bin/dpkg', '--print-architecture'])
        query(commands, 'foreign_architectures', ['/usr/bin/dpkg', '--print-foreign-architectures'])
        query(commands, 'apt_effective', ['/usr/bin/apt-config', 'dump'])
        query(commands, 'eeprom_package_files', ['/usr/bin/dpkg-query', '-L', 'rpi-eeprom'])
        query(commands, 'udev_version', ['/usr/bin/udevadm', '--version'])
        query(commands, 'process_names', ['/usr/bin/ps', '-eo', 'pid,ppid,comm'])
        report['runtime_before'] = runtime(commands['process_names']['stdout'])
        report['capacity'] = {}
        for path in ('/', '/boot', '/boot/firmware', '/var/tmp'):
            v = os.statvfs(path)
            report['capacity'][path] = {'available_bytes': v.f_bavail*v.f_frsize, 'available_inodes': v.f_favail}
        report['mounts'] = Path('/proc/'+str(os.getpid())+'/mountinfo').read_text()
        require(len(report['mounts']) <= 65536, 'mount bound')
        require(not report['locks_before']['held'], 'package lock held')
        require(not commands['audit']['stdout'].strip(), 'dpkg audit findings')
        for unit in ('apt-daily.service', 'apt-daily-upgrade.service'):
            require('ActiveState=inactive\n' in report['services_before'][unit]['stdout'], 'APT service active')
        require(not re.search(r'(?m)\s(?:apt|apt-get|dpkg|unattended-upgr)\s*$', commands['process_names']['stdout']), 'package process active')
        stage = '/var/tmp/'+spec['operation_id']
        report['parser'] = native_verify(stage, baseline, candidate)
        require(report['parser']['cleaned'] and 'error' not in report['parser'], 'parser/cleanup incomplete')
        require(report['parser']['baseline.rules']['accepted'] and report['parser']['baseline.rules']['returncode'] == 1,
                'baseline parser result changed')
        require(report['parser']['candidate.rules']['accepted'] and report['parser']['candidate.rules']['returncode'] == 0,
                'candidate parser rejected')
        report['after'] = configuration(unit_paths)
        after_processes = query(commands, 'process_names_after', ['/usr/bin/ps', '-eo', 'pid,ppid,comm'])
        report['runtime_after'] = runtime(after_processes)
        report['services_after'] = services()
        report['locks_after'] = lock_state()
        report['apt_lists_after'] = list_metadata()
        report['boot_after'] = identity()
        require(report['before'] == report['after'] and report['services_before'] == report['services_after']
                and not report['locks_after']['held'] and report['apt_lists_before'] == report['apt_lists_after']
                and report['runtime_before'] == report['runtime_after'],
                'configuration/service/package continuity')
        report['capture_complete'] = True
    except BaseException as error:
        report['error'] = type(error).__name__+': '+str(error)
    finally:
        signal.alarm(0)
        report['finished_epoch'] = time.time()
    return report
