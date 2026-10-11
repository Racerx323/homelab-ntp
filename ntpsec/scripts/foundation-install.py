#!/usr/bin/python3
"""One foundation transaction. Importable offline; entry requires sealed inputs."""
import base64
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import signal
import socket
import stat
import subprocess
import sys
import time
import types

STAGE = Path('/var/lib/ntp-foundation-v6')
OWNER = 0
DEADLINE = float('inf')
TIMERS = ('apt-daily.timer', 'apt-daily-upgrade.timer')
SERVICES = ('apt-daily.service', 'apt-daily-upgrade.service')
SYSTEMD_RUNTIME = Path('/run/systemd/system')
POLICY = Path('/usr/sbin/policy-rc.d')
LISTCHANGES = Path('/etc/apt/listchanges.conf')
NRPOLICY = Path('/etc/needrestart/conf.d/zz-ntp-policy.conf')
DENY = b'#!/bin/sh\nexit 101\n'
ENV = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LC_ALL': 'C',
       'DEBIAN_FRONTEND': 'noninteractive', 'APT_LISTCHANGES_FRONTEND': 'none',
       'NEEDRESTART_MODE': 'l', 'SYSTEMD_PAGER': '',
       'PAGER': 'cat', 'HOME': '/root'}
PROHIBITED = ('ntpsec', 'ntp', 'gpsd', 'gpsd-clients', 'python3-gps')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def archive_file(row):
    return ('archives/' + row['package'] + '_' + row['version'].replace(':', '%3a')
            + '_' + row['architecture'] + '.deb')


def ancestors(path):
    for item in (path, *path.parents):
        info = item.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != OWNER
                or info.st_gid != OWNER or info.st_mode & 0o022):
            raise ValueError('unprotected directory: ' + str(item))


def read(path, limit=64 * 1024 * 1024, unique=True):
    path = Path(path)
    ancestors(path.parent)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != OWNER
                or info.st_gid != OWNER or info.st_mode & 0o022
                or (unique and info.st_nlink != 1) or info.st_size > limit):
            raise ValueError('unprotected file: ' + str(path) + ' uid=' + str(info.st_uid)
                             + ' gid=' + str(info.st_gid) + ' mode=' + oct(stat.S_IMODE(info.st_mode))
                             + ' links=' + str(info.st_nlink) + ' size=' + str(info.st_size))
        data = bytearray()
        while len(data) <= limit:
            block = os.read(fd, min(65536, limit + 1 - len(data)))
            if not block:
                return bytes(data)
            data.extend(block)
        raise ValueError('file exceeds bound')
    finally:
        os.close(fd)


def sync(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def create(path, data, mode=0o600):
    ancestors(path.parent)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    try:
        os.fchmod(fd, mode)
        while data:
            data = data[os.write(fd, data):]
        os.fsync(fd)
    finally:
        os.close(fd)
    sync(path.parent)


def replace(path, data, mode):
    # The same protected directory owns both names; never follow a destination link.
    if path.exists() or path.is_symlink():
        read(path)
    temporary = path.with_name(path.name + '.ntp-foundation-new')
    create(temporary, data, mode)
    os.replace(temporary, path)
    sync(path.parent)


def record(name, value):
    create(STAGE / (name + '.json'), (json.dumps(value, sort_keys=True) + '\n').encode())


def run(argv, label, seconds=30, accepted=(0,), data=None, env=None, information=None):
    """Bounded pipes, durable original logs, owned process group, terminal receipt."""
    tool = Path(argv[0]).resolve(strict=True)
    read(tool, unique=False)
    outpath, errpath = STAGE / (label + '.stdout'), STAGE / (label + '.stderr')
    create(outpath, b'')
    create(errpath, b'')
    state = {'argv': argv, 'boot': boot(), 'started_epoch': int(time.time())}
    with outpath.open('ab') as out, errpath.open('ab') as err:
        child_env = dict(env or ENV)
        info_fd = None
        if information is not None:
            if len(information) > 1024 * 1024:
                raise ValueError('hook information exceeds bound')
            input_path = STAGE / (label + '.input')
            create(input_path, information)
            info_fd = os.open(input_path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
            if info_fd < 3:
                original = info_fd
                info_fd = fcntl.fcntl(original, fcntl.F_DUPFD_CLOEXEC, 3)
                os.close(original)
            child_env['APT_HOOK_INFO_FD'] = str(info_fd)
            state.update(information_sha256=sha(information), information_fd=info_fd)
        try:
            proc = subprocess.Popen(argv, stdin=subprocess.PIPE if data is not None else subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd='/',
                                    env=child_env, pass_fds=() if info_fd is None else (info_fd,),
                                    start_new_session=True)
        finally:
            if info_fd is not None:
                os.close(info_fd)
        state.update(pid=proc.pid, start_ticks=process_ticks(proc.pid), pgid=proc.pid)
        record(label + '-started', state)
        captured = [bytearray(), bytearray()]
        deadline, failure = min(time.monotonic() + seconds, DEADLINE), None
        with selectors.DefaultSelector() as selector:
            for i, stream in enumerate((proc.stdout, proc.stderr)):
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ, i)
            if data is not None:
                os.set_blocking(proc.stdin.fileno(), False)
                selector.register(proc.stdin, selectors.EVENT_WRITE, 2)
            try:
                while selector.get_map():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError('command deadline')
                    for key, _ in selector.select(min(remaining, 1)):
                        if key.data == 2:
                            try:
                                count = os.write(key.fd, data[:65536])
                                data = data[count:]
                            except BrokenPipeError:
                                data = b''
                            if not data:
                                selector.unregister(key.fileobj)
                                key.fileobj.close()
                            continue
                        block = os.read(key.fd, 65536)
                        if not block:
                            selector.unregister(key.fileobj)
                            key.fileobj.close()
                            continue
                        captured[key.data].extend(block)
                        (out, err)[key.data].write(block)
                        if sum(map(len, captured)) > 16 * 1024 * 1024:
                            raise ValueError('command output exceeds bound')
                proc.wait(timeout=max(0.1, deadline - time.monotonic()))
            except BaseException as exc:
                failure = type(exc).__name__ + ': ' + str(exc)
                os.killpg(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait(timeout=15)
            finally:
                for stream in (proc.stdin, proc.stdout, proc.stderr):
                    if stream is not None:
                        stream.close()
                for stream in (out, err):
                    stream.flush()
                    os.fsync(stream.fileno())
                state.update(exit_status=proc.returncode, failure=failure,
                             finished_epoch=int(time.time()))
                record(label + '-terminal', state)
        if failure or proc.returncode not in accepted:
            raise RuntimeError(label + ' failed; inspect retained command logs')
    return bytes(captured[0]).decode('utf-8', errors='strict')


def process_ticks(pid):
    try:
        return Path('/proc/' + str(pid) + '/stat').read_text().rsplit(')', 1)[1].split()[19]
    except FileNotFoundError:
        return None


def boot():
    return Path('/proc/sys/kernel/random/boot_id').read_text().strip()


def validate_spec(spec):
    rows = spec['packages']
    names = [r['package'] for r in rows]
    scope = spec.get('scope', 'foundation')
    required_count = 46 if scope == 'foundation' else 1
    required = {'pps-tools', 'bc'} if scope == 'foundation' else {
        'pps-supplement': {'pps-tools'}, 'bc-supplement': {'bc'}}.get(scope, set())
    if (spec['stage'] != str(STAGE) or spec['hostname'] != 'j2-svntp1'
            or scope not in ('foundation', 'pps-supplement', 'bc-supplement')
            or len(rows) != required_count or len(set(names)) != required_count
            or not required.issubset(names)
            or any(n in PROHIBITED or n.startswith('ntpsec') for n in names)):
        raise ValueError('fixed foundation scope required')
    for row in rows:
        if (not re.fullmatch(r'[a-z0-9][a-z0-9+.-]+', row['package'])
                or row['architecture'] not in ('arm64', 'all')
                or not re.fullmatch(r'[A-Za-z0-9.+:~_-]+', row['version'])
                or not re.fullmatch(r'[0-9a-f]{64}', row['sha256'])
                or row['file'] != archive_file(row)
                or row['binary_package'] not in (row['package'], row['package'] + ':arm64')
                or any(n.split(':')[0] == row['package'] for n in spec['baseline'])):
            raise ValueError('invalid package binding')


def identity(spec, epoch):
    if (os.geteuid() != 0 or os.getegid() != 0 or os.environ.get('SUDO_USER') != 'ama'
            or os.environ.get('SUDO_UID') != '1000' or not sys.flags.isolated
            or not sys.dont_write_bytecode or socket.gethostname() != spec['hostname']
            or os.uname().machine != 'aarch64' or os.uname().release != spec['kernel']):
        raise ValueError('isolated approved root/target/caller required')
    release = read(Path('/usr/lib/os-release')).decode().splitlines()
    if not all(s in release for s in ('ID=debian', 'VERSION_ID="13"', 'VERSION_CODENAME=trixie')):
        raise ValueError('OS drift')
    if (not spec['prepared_epoch'] - 300 <= time.time() < spec['expires_epoch']
            or abs(time.time() - epoch) > 300):
        raise ValueError('approval clock/window mismatch')


def package_rows(text):
    result = {}
    for line in text.splitlines():
        name, version, state = line.split('\t')
        if name in result or not re.fullmatch(r'[a-z0-9][a-z0-9+.:_-]+', name):
            raise ValueError('duplicate/malformed package row')
        result[name] = [version, state]
    return result


def inventory(label):
    return package_rows(run(['/usr/bin/dpkg-query', '-W',
                             '-f=${binary:Package}\t${Version}\t${db:Status-Abbrev}\n'], label))


def expected_inventory(spec):
    result = dict(spec['baseline'])
    for row in spec['packages']:
        # New Multi-Arch:same packages have binary:Package suffixed by architecture.
        result[row['binary_package']] = [row['version'], 'ii ']
    return result


def recovery_packages(current, spec):
    baseline = spec['baseline']
    allowed = {r['binary_package']: r for r in spec['packages']}
    if any(current.get(k) != v for k, v in baseline.items()) or set(current) - set(baseline) - set(allowed):
        raise ValueError('recovery outside approved package set')
    pending = []
    for name in set(current) - set(baseline):
        version, state = current[name]
        if version != allowed[name]['version'] or state not in ('ii ', 'iU ', 'iF ', 'iW ', 'it '):
            raise ValueError('unapproved recovery version/state')
        if state != 'ii ':
            pending.append(name)
    return sorted(pending)


def validate_simulation(text, spec):
    actual = set()
    for line in text.splitlines():
        if line.startswith('Remv '):
            raise ValueError('simulation removes packages')
        if not line.startswith('Inst '):
            continue
        match = re.fullmatch(r'Inst (\S+) \((\S+) .*\[([a-z0-9-]+)\]\)(?: \[\])?', line)
        if not match or match[1].split(':')[0] in spec['baseline']:
            raise ValueError('unparsed/upgrading simulation')
        row = (match[1].split(':')[0], match[2], match[3])
        if row in actual:
            raise ValueError('duplicate install line')
        actual.add(row)
    if actual != {(r['package'], r['version'], r['architecture']) for r in spec['packages']}:
        raise ValueError('combined native delta differs from bound package set')


def protocol(data, spec):
    """APT Version 2 only; complete new-package archive union, no configure/remove."""
    text = data.decode('utf-8', errors='strict')
    header, separator, body = text.partition('\n\n')
    lines = header.splitlines()
    if not separator or not lines or lines[0] != 'VERSION 2' or any('=' not in l for l in lines[1:]):
        raise ValueError('APT Version 2 framing required')
    expected = {r['package']: r for r in spec['packages']}
    paths, seen, configured = [], set(), set()
    for line in body.splitlines():
        parts = line.split()
        if len(parts) != 5:
            raise ValueError('malformed APT action row')
        name, old, direction, new, action = parts
        row = expected.get(name)
        if row is None or old != '-' or direction != '<' or new != row['version']:
            raise ValueError('unexpected APT action/old version/archive')
        if action == '**CONFIGURE**':
            if name not in seen or name in configured:
                raise ValueError('unexpected configure action')
            configured.add(name)
            continue
        if action != str(STAGE / row['file']) or name in seen:
            raise ValueError('unexpected archive action')
        seen.add(name)
        paths.append(action)
    if seen != set(expected):
        raise ValueError('incomplete archive union')
    return paths


def check_inputs(spec, after=False, controls=False):
    allowed = {str(LISTCHANGES), str(POLICY), str(NRPOLICY)}
    if after:
        allowed |= set(spec['package_created_inputs']) | {'/var/lib/dpkg/status'}
    for item in spec['inputs']:
        path = Path(item['path'])
        if str(path) in allowed:
            continue
        if item.get('absent'):
            if path.exists() or path.is_symlink():
                raise ValueError('expected absent input: ' + str(path))
        else:
            data = read(path)
            info = path.lstat()
            if ((item.get('sha256') is not None and sha(data) != item['sha256']) or info.st_uid != item['uid']
                    or info.st_gid != item['gid'] or stat.S_IMODE(info.st_mode) != int(item['mode'], 8)):
                raise ValueError('bound input drift: ' + str(path))
    if after:
        for name, checksum in spec['package_created_inputs'].items():
            if sha(read(name)) != checksum:
                raise ValueError('installed candidate policy/helper drift: ' + name)
    for directory, names in spec['directories'].items():
        path = Path(directory)
        if path.is_symlink():
            raise ValueError('config directory link')
        observed = sorted(p.name for p in path.iterdir()) if path.exists() else []
        if directory == str(NRPOLICY.parent):
            names = [*names, *([NRPOLICY.name] if controls or after else []),
                     *(['README.needrestart'] if after else [])]
            names = sorted(set(names))
        if after and directory == '/etc/apt/apt.conf.d':
            names = sorted(set([*names, '99needrestart']))
        if after and directory == '/etc/dpkg/dpkg.cfg.d' and any(r['package'] == 'needrestart' for r in spec['packages']):
            names = sorted(set([*names, 'needrestart']))
        if observed != names:
            raise ValueError('config input set drift: ' + directory)


def locks_free(paths=('/var/lib/dpkg/lock-frontend', '/var/lib/dpkg/lock', '/var/lib/apt/lists/lock')):
    for name in paths:
        path = Path(name)
        if not path.exists():
            continue
        read(path)
        fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
        try:
            fcntl.lockf(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.lockf(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def clean_dpkg(label):
    if run(['/usr/bin/dpkg', '--audit'], label).strip():
        raise ValueError('dpkg audit not clean')
    if any(Path('/var/lib/dpkg/updates').iterdir()) or read('/var/lib/dpkg/triggers/Unincorp').strip():
        raise ValueError('pending dpkg updates/triggers')


def network(label):
    units = run(['/usr/bin/systemctl', 'show', '--property=Id,ActiveState,SubState,MainPID,NRestarts',
                 'ssh.service', 'NetworkManager.service'], label + '-units')
    blocks = [b.splitlines() for b in units.strip().split('\n\n')]
    if len(blocks) != 2 or any('ActiveState=active' not in b for b in blocks):
        raise ValueError('SSH/network service not active')
    addresses = json.loads(run(['/usr/sbin/ip', '-j', 'address', 'show'], label + '-addresses'))
    stable = sorted([r['ifname'], a['family'], a['local'], a['prefixlen']]
                    for r in addresses for a in r['addr_info'])
    routes = []
    for flag in ('-4', '-6'):
        rows = json.loads(run(['/usr/sbin/ip', flag, '-j', 'route', 'show'], label + '-routes' + flag))
        routes.extend({k: v for k, v in r.items() if k not in ('expires', 'cache')} for r in rows)
    return {'units': units, 'addresses': stable, 'routes': routes, 'boot': boot()}


def unit_state(unit, label):
    return run(['/usr/bin/systemctl', 'show', '--property=Id,LoadState,ActiveState,SubState,UnitFileState,FragmentPath,DropInPaths',
                unit], label)


def auto_snapshot():
    result = {}
    for unit in (*TIMERS, *SERVICES):
        text = unit_state(unit, 'before-' + unit)
        values = dict(line.split('=', 1) for line in text.splitlines())
        if (values['LoadState'] != 'loaded' or values['DropInPaths']
                or values['UnitFileState'] not in ('enabled', 'static')
                or Path('/etc/systemd/system/' + unit).is_symlink()
                and os.readlink('/etc/systemd/system/' + unit) == '/dev/null'
                or os.path.lexists(SYSTEMD_RUNTIME / unit)):
            raise ValueError('unexpected auto-update unit/mask/drop-in state')
        result[unit] = values
    record('automatic-update-before', result)
    return result


def pause_updates(before):
    for timer in TIMERS:
        run(['/usr/bin/systemctl', 'stop', timer], 'stop-' + timer)
    # A runtime mask prevents new starts; an already running update finishes normally.
    for unit in (*TIMERS, *SERVICES):
        record('mask-intent-' + unit, {'unit': unit})
        run(['/usr/bin/systemctl', 'mask', '--runtime', unit], 'mask-' + unit)
    end = time.monotonic() + 120
    counter = 0
    while True:
        active = [unit_state(u, 'settle-' + str(counter) + '-' + u) for u in SERVICES]
        if all('ActiveState=inactive\n' in s for s in active):
            break
        if time.monotonic() >= end:
            raise ValueError('existing updates did not settle; never killed')
        counter += 1
        time.sleep(5)
    locks_free()
    record('automatic-update-paused', {'before': before})


def backup_policies(spec):
    states = {}
    for path in (LISTCHANGES, POLICY, NRPOLICY):
        if path == LISTCHANGES or (path == NRPOLICY and spec.get('scope') in ('pps-supplement', 'bc-supplement')):
            data = read(path)
            expected = (spec['prior_needrestart_sha256'] if path == NRPOLICY else
                        next(x['sha256'] for x in spec['inputs'] if x['path'] == str(path)))
            if sha(data) != expected:
                raise ValueError('prior policy drift: ' + str(path))
            name = 'needrestart-before' if path == NRPOLICY else 'listchanges-before'
            create(STAGE / name, data)
            if read(STAGE / name) != data:
                raise ValueError('backup unreadable')
            states[str(path)] = {'file': name, 'sha256': sha(data), 'mode': stat.S_IMODE(path.stat().st_mode)}
        else:
            if path.exists() or path.is_symlink():
                raise ValueError('policy path no longer absent')
            states[str(path)] = {'absent': True}
    states['created_dirs'] = [str(p) for p in (NRPOLICY.parent.parent, NRPOLICY.parent) if not p.exists()]
    record('policy-before', states)
    return states


def install_controls(spec, states):
    for name in states['created_dirs']:
        path = Path(name)
        ancestors(path.parent)
        path.mkdir(mode=0o755)
        sync(path.parent)
    replace(LISTCHANGES, read(STAGE / 'listchanges.conf'), 0o644)
    create(POLICY, DENY, 0o755)
    replace(NRPOLICY, read(STAGE / 'needrestart.conf'), 0o644)
    record('controls-installed', {'listchanges': sha(read(LISTCHANGES)), 'deny': sha(DENY),
                                  'needrestart': sha(read(NRPOLICY))})


def guard_controls():
    for path, data in ((LISTCHANGES, read(STAGE / 'listchanges.conf')),
                       (POLICY, DENY), (NRPOLICY, read(STAGE / 'needrestart.conf'))):
        if read(path) != data:
            raise ValueError('transaction control drift: ' + str(path))


def restore_controls(spec, success, label):
    states = json.loads(read(STAGE / 'policy-before.json'))
    for path, expected in ((LISTCHANGES, read(STAGE / 'listchanges.conf')),
                           (POLICY, DENY), (NRPOLICY, read(STAGE / 'needrestart.conf'))):
        if path == NRPOLICY and success:
            continue
        if not path.exists() and not path.is_symlink() and states[str(path)].get('absent'):
            continue
        current = read(path)
        old = states[str(path)]
        if not old.get('absent') and sha(current) == old['sha256']:
            continue
        if current != expected:
            raise ValueError('cleanup held on policy drift')
        if old.get('absent'):
            path.unlink()
            sync(path.parent)
        else:
            data = read(STAGE / old['file'])
            if sha(data) != old['sha256']:
                raise ValueError('backup hash mismatch')
            replace(path, data, old['mode'])
    if not success:
        for name in reversed(states['created_dirs']):
            path = Path(name)
            if path.exists():
                path.rmdir()  # Unexpected contents hold cleanup.
    before = json.loads(read(STAGE / 'automatic-update-before.json'))
    for unit in (*TIMERS, *SERVICES):
        path = SYSTEMD_RUNTIME / unit
        if path.is_symlink() and os.readlink(path) == '/dev/null':
            if not (STAGE / ('mask-intent-' + unit + '.json')).exists():
                raise ValueError('mask was not ours')
            run(['/usr/bin/systemctl', 'unmask', '--runtime', unit], label + '-unmask-' + unit)
        elif path.exists() or path.is_symlink():
            raise ValueError('mask drift')
    for timer in TIMERS:
        if before[timer]['ActiveState'] == 'active':
            run(['/usr/bin/systemctl', 'start', timer], label + '-restart-' + timer)
    for unit in (*TIMERS, *SERVICES):
        text = unit_state(unit, label + '-restored-' + unit)
        current = dict(line.split('=', 1) for line in text.splitlines())
        keys = ('LoadState', 'UnitFileState', 'FragmentPath', 'DropInPaths')
        if any(current[k] != before[unit][k] for k in keys):
            raise ValueError('automatic-update disposition not restored')
        if unit in TIMERS and current['ActiveState'] != before[unit]['ActiveState']:
            raise ValueError('timer activity not restored')
    record(label + '-cleanup', {'temporary_policies_restored': True, 'automatic_updates_restored': True,
                               'final_needrestart_retained': success})


def apt_config(spec):
    config = ('Dir::Etc::parts "' + str(STAGE / 'empty') + '";\n'
              'Dir::Etc::main "' + str(STAGE / 'no-main') + '";\n'
              'Dir::Etc::sourcelist "' + str(STAGE / 'no-sources') + '";\n'
              'Dir::Etc::sourceparts "' + str(STAGE / 'empty') + '";\n'
              'Dir::State::lists "' + str(STAGE / 'lists') + '";\n'
              'Dir::State::status "/var/lib/dpkg/status";\n'
              'Dir::Cache::archives "' + str(STAGE / 'archives') + '";\n'
              'Dir::Cache::pkgcache ""; Dir::Cache::srcpkgcache "";\n'
              'Dir::Log "' + str(STAGE / 'apt-logs') + '";\n'
              'APT::Architecture "arm64"; APT::Architectures { "arm64"; };\n'
              'APT::Install-Recommends "true"; APT::Install-Suggests "false";\n'
              'APT::Get::AllowUnauthenticated "false";\n'
              'DPkg::Lock::Timeout "0";\n'
              '#include "/etc/apt/apt.conf.d/01autoremove";\n')
    for mode in ('validate', 'listchanges', 'debconf'):
        cmd = str(STAGE / ('hook-' + mode))
        config += ('DPkg::Pre-Install-Pkgs { "' + cmd + '"; };\n'
                   'DPkg::Tools::Options::"' + cmd + '"::Version "2";\n'
                   'DPkg::Tools::Options::"' + cmd + '"::InfoFD "20";\n')
    config += 'DPkg::Post-Invoke { "' + str(STAGE / 'hook-needrestart') + '"; };\n'
    return config.encode()


def hook_wrapper(mode):
    checksum = sha(read(STAGE / 'spec.json'))
    return ('#!/bin/bash\nset -Eeuo pipefail\nexec /usr/bin/python3 -I -B '
            + str(STAGE / 'worker.py') + ' hook ' + checksum + ' ' + mode + '\n').encode()


def verify_archives(spec, label):
    for row in spec['packages']:
        path = STAGE / row['file']
        data = read(path)
        if sha(data) != row['sha256'] or len(data) != row['size']:
            raise ValueError('archive drift')
        fields = run(['/usr/bin/dpkg-deb', '-f', str(path), 'Package', 'Version', 'Architecture'],
                     label + '-' + row['package'])
        values = dict(line.split(': ', 1) for line in fields.splitlines())
        if values != {k.title(): row[k] for k in ('package', 'version', 'architecture')}:
            raise ValueError('archive identity drift')


def effective_needrestart(label):
    # Candidate config is approved executable Perl; check the actual final load order.
    code = ("our %nrconf; our $LOGPREF='ntp'; $!=0; do '/etc/needrestart/needrestart.conf'; "
            "die $@ if $@; die $! if $!; "
            "die 'restart' unless $nrconf{restart} eq 'l'; "
            "die 'notify' unless $nrconf{sendnotify} == 0; "
            "die 'kernelhints' unless $nrconf{kernelhints} == 1; "
            "die 'ucodehints' unless defined $nrconf{ucodehints} && $nrconf{ucodehints} == 0; "
            "die 'glob' unless $nrconf{kernel_linux_glob} eq '/boot/vmlinuz-*-v8'; "
            "die 'v8' unless '/boot/vmlinuz-6.18.50+rpt-rpi-v8' =~ $nrconf{kernelfilter}; "
            "die '2712' if '/boot/vmlinuz-6.18.50+rpt-rpi-2712' =~ $nrconf{kernelfilter}; "
            'print "EFFECTIVE_POLICY_OK\\n";')
    if run(['/usr/bin/perl', '-e', code], label).strip() != 'EFFECTIVE_POLICY_OK':
        raise ValueError('effective needrestart policy failed')


def forbidden_units(label):
    text = run(['/usr/bin/systemctl', 'show', '--property=Id,LoadState,ActiveState',
                *[u + '.service' for u in ('ntpsec', 'gpsd', 'watchdog', 'wd_keepalive',
                                           'munin-node', 'msmtpd', 'apache2', 'lighttpd')],
                'gpsd.socket', 'apparmor.service'], label)
    for block in text.strip().split('\n\n'):
        fields = dict(line.split('=', 1) for line in block.splitlines())
        if fields['ActiveState'] != 'inactive' or (fields['Id'] != 'apparmor.service'
                                                  and fields['LoadState'] != 'not-found'):
            raise ValueError('prohibited daemon/unit present or active')


def seen_snapshot():
    result = {}
    for name in ('/var/lib/apt/listchanges', '/var/lib/apt/listchanges.db', '/var/lib/apt/listchanges-snapshot'):
        path = Path(name)
        result[name] = sha(read(path)) if path.exists() else None
        if path.is_symlink():
            raise ValueError('seen/snapshot link')
    return result


def validate_needrestart_report(text, spec):
    fields = {}
    for line in text.splitlines():
        if line.startswith(('NEEDRESTART-VER:', 'NEEDRESTART-KCUR:', 'NEEDRESTART-KEXP:', 'NEEDRESTART-KSTA:')):
            key, value = line.split(': ', 1)
            if key in fields:
                raise ValueError('duplicate needrestart acceptance field')
            fields[key] = value
    if (fields.get('NEEDRESTART-VER') != '3.11' or fields.get('NEEDRESTART-KCUR') != spec['kernel']
            or fields.get('NEEDRESTART-KEXP') != spec['kernel'] or fields.get('NEEDRESTART-KSTA') != '1'):
        raise ValueError('needrestart kernel/report gap; preserve controls for review')
    return fields


def acceptance(spec, label):
    if inventory(label + '-packages') != expected_inventory(spec):
        raise ValueError('final package delta failed')
    clean_dpkg(label + '-audit')
    check_inputs(spec, after=True)
    guard_controls()
    if network(label + '-network') != json.loads(read(STAGE / 'network-before.json')):
        raise ValueError('boot/SSH/network continuity failed')
    forbidden_units(label + '-forbidden')
    if seen_snapshot() != json.loads(read(STAGE / 'seen-before.json')):
        raise ValueError('listchanges seen/snapshot changed')
    effective_needrestart(label + '-effective-policy')
    report = run(['/usr/sbin/needrestart', '-b', '-r', 'l', '-k', '-l'], label + '-needrestart-report', seconds=120)
    fields = validate_needrestart_report(report, spec)
    if network(label + '-after-report') != json.loads(read(STAGE / 'network-before.json')):
        raise ValueError('service/boot continuity after needrestart failed')
    record(label + '-acceptance', {'exact_packages': True, 'clean_dpkg': True,
                                 'continuity': True, 'effective_policy': True,
                                 'seen_unchanged': True, 'no_prohibited_units': True, 'needrestart_fields': fields})


def hook(spec, mode):
    if time.time() >= spec['expires_epoch']:
        raise ValueError('approval expired before hook')
    guard_controls()
    if mode == 'needrestart':
        effective_needrestart('hook-effective-policy')
        run(['/usr/lib/needrestart/apt-pinvoke'], 'hook-needrestart', seconds=120)
        return
    if os.environ.get('APT_HOOK_INFO_FD') != '20':
        raise ValueError('APT information FD drift')
    data = bytearray()
    while len(data) <= 1024 * 1024:
        block = os.read(20, min(65536, 1024 * 1024 + 1 - len(data)))
        if not block:
            break
        data.extend(block)
    if len(data) > 1024 * 1024:
        raise ValueError('APT protocol exceeds bound')
    paths = protocol(bytes(data), spec)
    if inventory('hook-' + mode + '-packages') != spec['baseline']:
        raise ValueError('package baseline drift under APT locking')
    check_inputs(spec, controls=True)
    verify_archives(spec, 'hook-' + mode + '-archive')
    if mode == 'validate':
        record('hook-validate-accepted', {'archives': paths})
    elif mode == 'listchanges':
        run(['/usr/bin/apt-listchanges', '--apt'], 'hook-listchanges', seconds=120,
            information=bytes(data))
    elif mode == 'debconf':
        run(['/usr/sbin/dpkg-preconfigure', '--apt'], 'hook-debconf', seconds=120,
            data=('\n'.join(paths) + '\n').encode())
    else:
        raise ValueError('unknown hook mode')


def preflight(spec):
    if spec.get('scope') in ('pps-supplement', 'bc-supplement') and sha(read(NRPOLICY)) != spec['prior_needrestart_sha256']:
        raise ValueError('accepted prior needrestart policy drift')
    check_inputs(spec)
    if inventory('preflight-packages') != spec['baseline']:
        raise ValueError('package baseline drift')
    if run(['/usr/bin/dpkg', '--print-architecture'], 'native-architecture').strip() != 'arm64':
        raise ValueError('architecture drift')
    if run(['/usr/bin/dpkg', '--print-foreign-architectures'], 'foreign-architectures').strip() != 'armhf':
        raise ValueError('foreign architecture drift')
    clean_dpkg('preflight-audit')
    if run(['/usr/bin/id', '-u', 'ama'], 'caller-uid').strip() != '1000':
        raise ValueError('caller identity drift')
    helper_ns, answer_ns = {'__name__': 'sealed_helper'}, {'__name__': 'sealed_answers'}
    exec(compile(read(STAGE / 'hook-helper.py'), 'sealed-helper.py', 'exec'), helper_ns)
    exec(compile(read(STAGE / 'answer-helper.py'), 'sealed-answers.py', 'exec'), answer_ns)
    answer_spec = dict(spec['answers'], not_before=spec['prepared_epoch'] - 300,
                       expires_epoch=spec['expires_epoch'], hostname=spec['hostname'], kernel=spec['kernel'])
    answers = answer_ns['collect_answers'](answer_spec, types.SimpleNamespace(**helper_ns))
    if answers['answers'] != spec['answers']['expected']:
        raise ValueError('Debconf answers drift')
    record('debconf-preflight', answers)
    for name in ('/etc/debconf.conf', '/usr/share/debconf/debconf.conf'):
        if helper_ns['debconf_structure'](read(name).decode()) != spec['answers']['structure']:
            raise ValueError('Debconf structure drift')
    tools = {}
    for name in ('apt-get', 'apt-config', 'dpkg', 'dpkg-query', 'dpkg-deb', 'python3',
                 'perl', 'systemctl', 'ip', 'id'):
        directory = '/usr/sbin/' if name == 'ip' else '/usr/bin/'
        path = Path(directory + name).resolve(strict=True)
        info = path.lstat()
        tools[name] = {'resolved': str(path), 'sha256': sha(read(path, unique=False)),
                       'uid': info.st_uid, 'gid': info.st_gid, 'mode': oct(stat.S_IMODE(info.st_mode)),
                       'links': info.st_nlink,
                       'owner': run(['/usr/bin/dpkg-query', '-S', str(path)], 'tool-owner-' + name)}
    record('tools-before', tools)
    forbidden_units('preflight-forbidden')
    for directory in ('/etc/apache2', '/etc/lighttpd'):
        if spec.get('scope', 'foundation') == 'foundation' and os.path.lexists(directory):
            raise ValueError('web integration no longer absent')
    for directory in ('/var', '/usr', '/boot'):
        usage = os.statvfs(directory)
        if usage.f_bavail * usage.f_frsize < spec['minimum_free_bytes']:
            raise ValueError('insufficient free space: ' + directory)
    record('network-before', network('preflight-network'))
    record('seen-before', seen_snapshot())
    verify_archives(spec, 'preflight-archive')


def install(spec):
    global DEADLINE
    preflight(spec)
    before = auto_snapshot()
    states = backup_policies(spec)
    try:
        pause_updates(before)
        install_controls(spec, states)
        check_inputs(spec, controls=True)
        if inventory('paused-packages') != spec['baseline']:
            raise ValueError('package baseline changed during update settling')
        clean_dpkg('paused-audit')
        args = ['/usr/bin/apt-get', '--no-download', '--no-remove', '--no-install-suggests',
                '--install-recommends', '-y', 'install',
                *[str(STAGE / row['file']) for row in spec['packages']]]
        environment = dict(ENV, APT_CONFIG=str(STAGE / 'apt.conf'))
        simulated = run([*args[:1], '--simulate', *args[1:]], 'combined-simulation', env=environment)
        validate_simulation(simulated, spec)
        if time.time() >= spec['expires_epoch']:
            raise ValueError('approval expired before unpack')
        record('unpack-authorized', {'packages': len(spec['packages']), 'boot': boot()})
        run(args, 'apt-install', seconds=900, env=environment)
        for mode in ('listchanges', 'debconf', 'needrestart'):
            terminal = json.loads(read(STAGE / ('hook-' + mode + '-terminal.json')))
            if terminal['exit_status'] != 0 or terminal['failure']:
                raise ValueError('hook terminal status failed')
        read(STAGE / 'hook-validate-accepted.json')
        acceptance(spec, 'installation')
        restore_controls(spec, True, 'installation')
        record('complete', {'state': 'foundation_accepted', 'packages': len(spec['packages']), 'build_performed': False})
    except BaseException as exc:
        DEADLINE = max(DEADLINE, time.monotonic() + 180)  # Reserve bounded cleanup/readback time.
        # An APT call can fail before or after unpack. Inventory determines cleanup.
        changed = inventory('failure-packages') != spec['baseline']
        if not changed:
            clean_dpkg('failure-audit')
            restore_controls(spec, False, 'early-failure')
        record('failure', {'state': 'package_recovery_required' if changed else 'early_failure_restored',
                           'error': type(exc).__name__ + ': ' + str(exc), 'safety_controls_retained': changed})
        raise


def recover(spec):
    if (STAGE / 'complete.json').exists():
        raise ValueError('accepted attempt cannot be repaired/replayed')
    record('recovery-claim', {'epoch': int(time.time())})
    if (STAGE / 'apt-install-started.json').exists():
        started = json.loads(read(STAGE / 'apt-install-started.json'))
        if started['boot'] != boot() or process_ticks(started['pid']) == started['start_ticks']:
            raise ValueError('original process live or boot changed; recovery held')
        terminal = json.loads(read(STAGE / 'apt-install-terminal.json'))
        if terminal['exit_status'] is None:
            raise ValueError('original command terminal evidence missing')
    locks_free()
    current = inventory('recovery-packages')
    pending = recovery_packages(current, spec)
    if not (STAGE / 'policy-before.json').exists():
        if current != spec['baseline']:
            raise ValueError('preflight failed with unrelated package changes')
        record('recovery-complete', {'state': 'preflight_failure_no_controls_changed'})
        return
    if current == spec['baseline']:
        clean_dpkg('recovery-early-audit')
        restore_controls(spec, False, 'recovery-early')
        record('recovery-complete', {'state': 'early_failure_restored'})
        return
    guard_controls()
    # Repair only already unpacked, exactly bound pending packages; never unpack again.
    if pending:
        record('configure-authorized', {'packages': pending})
        run(['/usr/bin/dpkg', '--configure', *pending], 'recovery-configure', seconds=600)
    acceptance(spec, 'recovery')
    restore_controls(spec, True, 'recovery')
    record('recovery-complete', {'state': 'foundation_accepted_after_configuration_repair'})


def entry(spec, files, epoch, mode):
    global DEADLINE
    DEADLINE = time.monotonic() + (1800 if mode == 'install' else 1200)
    os.umask(0o077)
    validate_spec(spec)
    identity(spec, epoch)
    if mode == 'install':
        if set(files) != set(spec['members']) or any(sha(data) != spec['members'][name] for name, data in files.items()):
            raise ValueError('sealed input mismatch')
        ancestors(STAGE.parent)
        STAGE.mkdir(mode=0o700)  # Exclusive claim; installation has no replay mode.
        sync(STAGE.parent)
        record('claim', {'epoch': epoch, 'boot': boot(), 'state': 'claimed_before_controls'})
        for directory in ('archives', 'empty', 'lists', 'apt-logs'):
            (STAGE / directory).mkdir(mode=0o700)
        for name, data in files.items():
            if name not in ('spec.json',):
                create(STAGE / name, data)
        create(STAGE / 'spec.json', (json.dumps(spec, sort_keys=True) + '\n').encode())
        for operation in ('validate', 'listchanges', 'debconf', 'needrestart'):
            create(STAGE / ('hook-' + operation), hook_wrapper(operation), 0o700)
        create(STAGE / 'apt.conf', apt_config(spec))
        install(spec)
    elif mode == 'recover':
        ancestors(STAGE)
        if json.loads(read(STAGE / 'spec.json')) != spec:
            raise ValueError('recovery specification drift')
        for name, checksum in spec['members'].items():
            if sha(read(STAGE / name)) != checksum:
                raise ValueError('recovery sealed member drift')
        if read(STAGE / 'apt.conf') != apt_config(spec):
            raise ValueError('recovery APT configuration drift')
        for operation in ('validate', 'listchanges', 'debconf', 'needrestart'):
            if read(STAGE / ('hook-' + operation)) != hook_wrapper(operation):
                raise ValueError('recovery hook wrapper drift')
        recover(spec)
    elif mode == 'readback':
        ancestors(STAGE)
        if json.loads(read(STAGE / 'spec.json')) != spec:
            raise ValueError('readback specification drift')
        return {'state': 'readback_collected', 'stage': str(STAGE)}
    else:
        raise ValueError('fixed operation required')
    return {'state': 'foundation_accepted' if mode == 'install' else 'recovery_completed',
            'stage': str(STAGE), 'rebooted': False, 'source_build_performed': False}


def evidence():
    result = {}
    size = 0
    for path in sorted(STAGE.iterdir()):
        if path.suffix not in ('.json', '.stdout', '.stderr', '.input') or path.name == 'spec.json':
            continue
        data = read(path, 16 * 1024 * 1024)
        size += len(data)
        if size > 32 * 1024 * 1024:
            raise ValueError('readback exceeds aggregate bound')
        result[path.name] = {'sha256': sha(data), 'base64': base64.b64encode(data).decode('ascii')}
    return result


if __name__ == '__main__':
    if len(sys.argv) != 4 or sys.argv[1] != 'hook':
        raise SystemExit('use the sealed workstation launcher')
    data = read(STAGE / 'spec.json')
    if sha(data) != sys.argv[2] or os.geteuid() != 0 or not sys.flags.isolated or not sys.dont_write_bytecode:
        raise SystemExit('protected bound hook required')
    hook(json.loads(data), sys.argv[3])
