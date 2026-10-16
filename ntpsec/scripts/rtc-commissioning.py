#!/usr/bin/python3
"""One-shot RTC utility installation or synchronized RTC write; transport supplies helper."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import stat
import time

PACKAGE = 'util-linux-extra'
VERSION = '2.41.5-0+deb13u1'
PACKAGE_SHA = '541f8442351445839b73f4c2dad86403a68910a7acd0dfc9c24aab6e90ff7912'
HWCLOCK_SHA = '2b3e0707985e19d2f6cb25a8280bff17dca1c657fc852451fa3c0458e584d051'
MANUAL_SHA = '741bff682202bffa48931033733c12eba249156a87cbee2d318bc5f126863b2b'
DEPENDENCIES = {'libaudit1': ('ge', '1:2.2.1'), 'libc6': ('ge', '2.38'),
                'libsmartcols1': ('eq', VERSION), 'zlib1g': ('ge', '1:1.1.4'),
                'util-linux': ('ge', '2.40.4-4~')}
DIVERSION_NAMES = ('ctrlaltdel', 'fsck.cramfs', 'fsck.minix', 'mkfs.bfs', 'mkfs.cramfs', 'mkfs.minix')


def command(argv, log, timeout=30):
    environment = {'PATH': '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
                   'LC_ALL': 'C', 'DEBIAN_FRONTEND': 'noninteractive',
                   'PYTHONDONTWRITEBYTECODE': '1'}
    result = helper.bounded(argv, timeout=timeout, limit=4*helper.LIMIT, env=environment)
    log.append(result)
    if result.get('returncode') != 0 or result.get('error'):
        raise ValueError('command failed: '+repr(argv))
    return result['stdout']


def inventory(log):
    text = command(['/usr/bin/dpkg-query', '-W', '-f=${binary:Package}\t${Version}\t${db:Status-Abbrev}\n'], log)
    return dict((parts[0], parts[1:]) for line in text.splitlines() if (parts := line.split('\t')) and len(parts) == 3)


def package_entry(packages, name):
    rows = [value for key, value in packages.items() if key in (name, name+':arm64')]
    if len(rows) > 1:
        raise ValueError('ambiguous native package: '+name)
    return rows[0] if rows else None


def installed(packages, name):
    row = package_entry(packages, name)
    return row and row[1] == 'ii '


def check_dependencies(packages, log):
    for name, (relation, version) in DEPENDENCIES.items():
        if not installed(packages, name):
            raise ValueError('missing installed dependency: '+name)
        command(['/usr/bin/dpkg', '--compare-versions', package_entry(packages, name)[0], relation, version], log)
    if installed(packages, 'initscripts'):
        command(['/usr/bin/dpkg', '--compare-versions', package_entry(packages, 'initscripts')[0], 'ge', '3.08-2~'], log)


def unchanged_packages(before, after):
    def other(rows):
        return {k: v for k, v in rows.items() if k not in (PACKAGE, PACKAGE+':arm64')}
    if other(before) != other(after):
        raise ValueError('unrelated package state changed')


def file_sha(path):
    record = helper.file_record(path)
    if record.get('changed_during_read') or 'sha256' not in record:
        raise ValueError('file identity/read failed: '+path)
    return record['sha256']


def verify_utility(packages, log):
    if package_entry(packages, PACKAGE) != [VERSION, 'ii ']:
        raise ValueError('exact installed utility package required')
    if file_sha('/usr/sbin/hwclock') != HWCLOCK_SHA or file_sha('/usr/share/man/man8/hwclock.8.gz') != MANUAL_SHA:
        raise ValueError('installed utility/manual hash mismatch')
    if command(['/usr/bin/dpkg', '--verify', PACKAGE], log).strip():
        raise ValueError('package verification reported differences')


def service_state(log):
    return command(['/usr/bin/systemctl', 'show', 'timeservice.service',
                    '--property=ActiveState,SubState,MainPID,NRestarts,InvocationID'], log)


def rtc_identity():
    node = Path('/sys/class/rtc/rtc0')
    info = Path('/dev/rtc0').lstat()
    if (not stat.S_ISCHR(info.st_mode) or (os.major(info.st_rdev), os.minor(info.st_rdev)) != (251, 0)
            or (node/'name').read_text().strip() != 'rtc-rv3028 1-0052'
            or str(node.resolve()) != '/sys/devices/platform/soc/fe804000.i2c/i2c-1/1-0052/rtc/rtc0'
            or str((node/'device/driver').resolve()) != '/sys/bus/i2c/drivers/rtc-rv3028'
            or str((node/'device/of_node').resolve()) != '/sys/firmware/devicetree/base/soc/i2c@7e804000/rv3028@52'):
        raise ValueError('accepted RTC identity changed')


def timing_ready(text):
    fields = dict(re.findall(r'(leap|stratum|refid|offset|rootdisp)\s*=\s*([^,\s]+)', text))
    try:
        if (fields['leap'] != '00' or fields['stratum'] != '1' or fields['refid'] != 'PPS'
                or not abs(float(fields['offset'])) <= 1.0
                or not 0 <= float(fields['rootdisp']) <= 10.0):
            raise ValueError('fresh PPS synchronization required')
    except (KeyError, OverflowError) as error:
        raise ValueError('incomplete timing proof') from error


def read_rtc(log):
    before = time.time()
    value = command(['/usr/sbin/hwclock', '--show', '--utc', '--noadjfile', '--rtc=/dev/rtc0'], log, 10)
    rtc_epoch = int(Path('/sys/class/rtc/rtc0/since_epoch').read_text())
    after = time.time()
    return {'before_epoch': before, 'after_epoch': after, 'rtc_epoch': rtc_epoch, 'display': value}


def check_readback(readback):
    if (not 0 <= readback['after_epoch']-readback['before_epoch'] <= 10
            or not readback['before_epoch']-2 <= readback['rtc_epoch'] <= readback['after_epoch']+2):
        raise ValueError('RTC readback outside two-second tolerance')


def reject_dpkg_hooks():
    paths = [Path('/etc/dpkg/dpkg.cfg'), *Path('/etc/dpkg/dpkg.cfg.d').glob('*')]
    for path in paths:
        if path.is_file():
            lines = [x.strip() for x in path.read_text().splitlines() if not x.lstrip().startswith('#')]
            if any(re.match(r'(?:--)?(?:pre|post)-invoke(?:[=\s]|$)', line) for line in lines):
                raise ValueError('unreviewed dpkg invocation hook')


def run(spec, package_b64):
    if (socket.gethostname().split('.')[0] != spec['hostname'] or os.geteuid() != 0
            or os.uname().machine != 'aarch64' or not time.time() < spec['expires_epoch']):
        raise ValueError('target/architecture/window mismatch')
    os.umask(0o077)
    root = Path('/var/lib/ntp-rtc-'+spec['operation_id'])
    root.mkdir(mode=0o700)  # Existing directory holds execution; never replay a mutation.
    log = []
    state = {'operation_id': spec['operation_id'], 'action': spec['action'], 'accepted': False,
             'started_epoch': time.time(), 'mutation_started': False, 'commands': log}
    def save():
        (root/'state.json').write_text(json.dumps(state, sort_keys=True)+'\n')
    save()
    before = None
    service = None
    try:
        boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        if boot != spec['boot_id']:
            raise ValueError('boot baseline changed')
        release = Path('/etc/os-release').read_text()
        if 'VERSION_CODENAME=trixie' not in release:
            raise ValueError('Trixie target required')
        if command(['/usr/bin/dpkg', '--print-architecture'], log).strip() != 'arm64':
            raise ValueError('native arm64 required')
        if command(['/usr/bin/dpkg', '--audit'], log).strip():
            raise ValueError('package audit not clean')
        before = inventory(log); state['packages_before'] = before
        service = service_state(log)
        if 'ActiveState=active\n' not in service or 'SubState=running\n' not in service:
            raise ValueError('running time service required')
        state['service_before'] = service
        protected = {p: helper.file_record(p) for p in ('/etc/ntp.conf', '/etc/ntpsec-timeservice.json', '/etc/adjtime')}
        state['protected_before'] = protected
        if protected['/etc/adjtime'] != {'missing': True}:
            raise ValueError('previously absent adjtime appeared')
        if spec['action'] == 'install':
            if package_entry(before, PACKAGE) not in (None, ['', 'un ']):
                raise ValueError('utility package must be absent from dpkg inventory')
            for name in spec['payload_paths']:
                if Path(name).exists() or Path(name).is_symlink():
                    raise ValueError('package payload path already exists: '+name)
            check_dependencies(before, log)
            reject_dpkg_hooks()
            diversions = command(['/usr/bin/dpkg-divert', '--list'], log)
            state['diversions_before'] = diversions
            for name in DIVERSION_NAMES:
                if any('/sbin/'+name in line for line in diversions.splitlines()) or Path('/sbin/'+name+'.usr-is-merged').exists():
                    raise ValueError('pre-existing package diversion')
            raw = base64.b64decode(package_b64, validate=True)
            if len(raw) != 290088 or hashlib.sha256(raw).hexdigest() != PACKAGE_SHA:
                raise ValueError('package payload digest/size mismatch')
            package = root/'util-linux-extra.deb'; package.write_bytes(raw)
            state['mutation_started'] = True; save()
            command(['/usr/bin/dpkg', '--install', str(package)], log, 180)
            after = inventory(log); state['packages_after'] = after
            unchanged_packages(before, after); verify_utility(after, log)
            if command(['/usr/bin/dpkg', '--audit'], log).strip():
                raise ValueError('post-install package audit not clean')
            state['diversions_after'] = command(['/usr/bin/dpkg-divert', '--list'], log)
        else:
            verify_utility(before, log); rtc_identity()
            clock = command(['/usr/bin/timedatectl', 'show'], log)
            if 'LocalRTC=no\n' not in clock or 'NTPSynchronized=yes\n' not in clock:
                raise ValueError('UTC synchronized system required')
            state['rtc_before'] = read_rtc(log)
            timing_ready(command(['/usr/local/bin/ntpq', '-c', 'rv 0'], log, 10))
            state['mutation_started'] = True; save()
            command(['/usr/sbin/hwclock', '--systohc', '--utc', '--noadjfile', '--rtc=/dev/rtc0'], log, 10)
            state['rtc_after'] = read_rtc(log); check_readback(state['rtc_after'])
            timing_ready(command(['/usr/local/bin/ntpq', '-c', 'rv 0'], log, 10))
        if service_state(log) != service or Path('/proc/sys/kernel/random/boot_id').read_text().strip() != boot:
            raise ValueError('time service or boot identity changed')
        for path, record in protected.items():
            if helper.file_record(path) != record:
                raise ValueError('protected clock configuration changed: '+path)
        state['accepted'] = True
    except Exception as error:
        state['error'] = str(error)
        if spec['action'] == 'install' and state['mutation_started']:
            try:
                unchanged_packages(before, inventory(log))
                command(['/usr/bin/dpkg', '--remove', PACKAGE], log, 180)
                after = inventory(log); unchanged_packages(before, after)
                if installed(after, PACKAGE) or command(['/usr/bin/dpkg', '--audit'], log).strip():
                    raise ValueError('package removal incomplete')
                if command(['/usr/bin/dpkg-divert', '--list'], log) != state['diversions_before']:
                    raise ValueError('package diversion recovery incomplete')
                if service_state(log) != service:
                    raise ValueError('service continuity not restored; no restart authorized')
                for path, record in protected.items():
                    if helper.file_record(path) != record:
                        raise ValueError('protected configuration recovery incomplete')
                if Path('/proc/sys/kernel/random/boot_id').read_text().strip() != boot:
                    raise ValueError('boot changed during package recovery')
                state['package_recovered'] = True
            except Exception as recovery_error:
                state['recovery_error'] = str(recovery_error)
        # An RTC write cannot be undone by restoring a stale timestamp. Hold for review.
    state['completed_epoch'] = time.time(); save()
    return state
