#!/usr/bin/python3
"""Bounded unprivileged source build, staged acceptance and retained readback."""
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pwd
import signal
import socket
import stat
import subprocess
import sys
import sysconfig
import time

STAGE_NAME = '.ntp-source-build-v5'
HOSTNAME = 'j2-svntp1'
KERNEL = '6.18.50+rpt-rpi-v8'
STAGE = None
ENV = {'PATH': '/usr/bin:/bin', 'LC_ALL': 'C', 'PYTHONDONTWRITEBYTECODE': '1'}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def identity(spec, epoch):
    if (os.getuid() != 1000 or os.geteuid() != 1000 or pwd.getpwuid(1000).pw_name != 'ama'
            or not sys.flags.isolated or not sys.dont_write_bytecode
            or socket.gethostname() != HOSTNAME or spec['hostname'] != HOSTNAME
            or os.uname().machine != 'aarch64' or os.uname().release != KERNEL or spec['kernel'] != KERNEL):
        raise ValueError('approved unprivileged isolated target/caller required')
    if (not spec['prepared_epoch'] - 300 <= time.time() < spec['expires_epoch']
            or abs(time.time() - epoch) > 300):
        raise ValueError('approval clock/window mismatch')
    if (list(sys.version_info[:3]) != spec['python']['version']
            or sysconfig.get_path('purelib') != spec['python']['module_directory']
            or sysconfig.get_config_var('EXT_SUFFIX') != spec['python']['extension_suffix']):
        raise ValueError('observed interpreter/ABI/path drift')
    home = Path(pwd.getpwuid(1000).pw_dir)
    for parent in (home, *home.parents):
        s = parent.lstat()
        if not stat.S_ISDIR(s.st_mode) or s.st_uid not in (0, 1000) or s.st_mode & 0o022:
            raise ValueError('unprotected target home ancestor')
    return home / STAGE_NAME


def create(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())


def receipt(name, value):
    create(STAGE / (name + '.json'), (json.dumps(value, sort_keys=True) + '\n').encode())


def command(argv):
    result = subprocess.run(argv, cwd='/', env=ENV, capture_output=True, timeout=30, check=True)
    if len(result.stdout) + len(result.stderr) > 2 * 1024 * 1024 or result.stderr.strip():
        raise ValueError('preflight command output error/bound')
    return result.stdout.decode()


def packages():
    result = {}
    for line in command(['/usr/bin/dpkg-query', '-W', '-f=${binary:Package}\t${Version}\t${db:Status-Abbrev}\n']).splitlines():
        name, version, status = line.split('\t')
        if name in result:
            raise ValueError('duplicate package record')
        result[name] = [version, status]
    return result


def continuity():
    services = command(['/usr/bin/systemctl', 'show', '--no-pager',
                        '--property=Id,ActiveState,MainPID,NRestarts', 'ssh.service', 'NetworkManager.service'])
    return {'boot': Path('/proc/sys/kernel/random/boot_id').read_text().strip(), 'services': services}


def verify_files(spec, files, readback=False):
    expected = {'source-build-stage.py'} if readback else set(spec['members'])
    if set(files) != expected or any(sha(data) != spec['members'][n] for n, data in files.items()):
        raise ValueError('sealed source-stage input mismatch')
    if not readback:
        profile = json.loads(files['profile.json'])
        recipe = json.loads(files['recipe.json'])
        if (sha(files['recipe.json']) != profile['recipe_sha256']
                or profile['sources'] != recipe['sources']
                or 'timeservice=yes' not in profile['sources']['gpsd']['options']
                or not {'sirf=yes', 'earthmate=yes', 'evermore=yes', 'control_socket=yes'}.issubset(profile['sources']['gpsd']['options'])
                or any(a.split('=')[0] == 'minimal'
                       for a in profile['sources']['gpsd']['options'])
                or not {'pps-tools', 'bc'}.issubset({n.split(':')[0] for n in profile['packages']})):
            raise ValueError('corrected recipe and build prerequisites required')
        if (profile['hostname'] != HOSTNAME or profile['prefix'] != '/usr/local'
                or profile['python']['module_directory'] != spec['python']['module_directory']
                or profile['python']['version'] != spec['python']['version'][:2]
                or profile['jobs'] != 2):
            raise ValueError('fixed build profile binding required')
        if set(profile['sources']) != {'gpsd', 'ntpsec'}:
            raise ValueError('both pinned applications required')
        for source in profile['sources'].values():
            if sha(files[source['archive']]) != source['sha256']:
                raise ValueError('source archive binding mismatch')
        for name, checksum in profile['helpers'].items():
            if sha(files[name]) != checksum:
                raise ValueError('maintained helper binding mismatch')
        return profile


def validate_artifacts(manifest, module_directory, suffix):
    files = manifest['files']
    required = ['usr/local/sbin/gpsd', 'usr/local/sbin/ntpd', 'usr/local/bin/ntpq',
                'usr/local/bin/ntpleapfetch', 'usr/local/bin/ntploggps',
                'usr/local/bin/cgps', 'usr/local/bin/gpspipe']
    required += [module_directory.lstrip('/') + '/' + n for n in ('gps/__init__.py', 'ntp/__init__.py', 'ntp/ntpc' + suffix)]
    required += ['usr/local/share/man/' + n for n in ('man8/gpsd.8', 'man8/ntpd.8', 'man1/ntpq.1', 'man1/gpspipe.1')]
    for name in required:
        if name not in files or files[name]['type'] != 'file':
            raise ValueError('missing selected staged artifact: ' + name)
    if not any(n.startswith('usr/local/lib/libgps.so') for n in files):
        raise ValueError('missing staged shared GPSD library')


def validate_gpsd_features(gpsfeatures):
    if '#define HAVE_SYS_TIMEPPS_H 1' not in gpsfeatures:
        raise ValueError('installed RFC2783 header was not detected')
    for feature in ('SHM_EXPORT', 'MAGIC_HAT', 'GPSDCLIENTS', 'PYTHON', 'SHARED', 'NCURSES', 'CONTROL_SOCKET',
                    'SIRF', 'EARTHMATE', 'EVERMORE'):
        if '#define ' + feature + '_ENABLE 1' not in gpsfeatures:
            raise ValueError('selected GPSD feature missing: ' + feature)
    if '#define TIMESERVICE_ENABLE 1' not in gpsfeatures:
        raise ValueError('selected GPSD time-service feature missing')


def validate_gpsd_drivers(text):
    if not any(line.split() and line.split()[-1] == 'u-blox' for line in text.splitlines()):
        raise ValueError('selected u-blox receiver driver missing')


def staged_acceptance(clock, candidate, profile, spec, result, log_name='acceptance.log'):
    manifest = clock.bound_json(Path(result['manifest']), result['sha256'])
    if clock.inventory(candidate / 'stage') != manifest['files']:
        raise ValueError('staged inventory changed')
    module = spec['python']['module_directory']
    validate_artifacts(manifest, module, spec['python']['extension_suffix'])
    environment = dict(ENV, HOME=str(STAGE), LD_LIBRARY_PATH=str(candidate / 'stage/usr/local/lib'),
                       PYTHONPATH=str(candidate / 'stage' / module.lstrip('/')))
    log = STAGE / log_name
    for binary in ('usr/local/sbin/gpsd', 'usr/local/sbin/ntpd', 'usr/local/bin/ntpq'):
        path = candidate / 'stage' / binary
        clock.run([str(path), '--version'], candidate, environment, log)
    drivers = subprocess.run([str(candidate / 'stage/usr/local/sbin/gpsd'), '--drivers'],
                             cwd=candidate, env=environment, capture_output=True, check=True, timeout=30)
    validate_gpsd_drivers(drivers.stdout.decode())
    with log.open('ab') as f:
        f.write(b'GPSD compiled drivers\n' + drivers.stdout + drivers.stderr)
    libraries = [candidate / 'stage' / n for n,v in manifest['files'].items()
                 if v['type'] == 'file' and (n.startswith('usr/local/lib/') and '.so' in Path(n).name)]
    for path in [candidate / 'stage/usr/local/sbin/gpsd', candidate / 'stage/usr/local/sbin/ntpd', *libraries]:
        output = subprocess.run(['/usr/bin/ldd', str(path)], cwd=candidate, env=environment,
                                capture_output=True, check=True, timeout=30)
        if b'not found' in output.stdout + output.stderr:
            raise ValueError('unresolved staged library dependency')
        with log.open('ab') as f:
            f.write(str(path).encode() + b'\n' + output.stdout + output.stderr)
    imports = ('import importlib,pathlib,sys\nroot=pathlib.Path(sys.argv[1]).resolve()\n'
               'sys.path.insert(0,str(root))\n'
               'for name in ("gps","gps.client","ntp.packet","ntp.ntpc"):\n'
               ' m=importlib.import_module(name)\n p=pathlib.Path(m.__file__).resolve()\n'
               ' assert p.is_relative_to(root),(name,str(p))\n print(name,str(p))\n')
    clock.run(['/usr/bin/python3', '-I', '-B', '-c', imports, str(candidate / 'stage' / module.lstrip('/'))],
              candidate, environment, log)
    ntpheader = candidate / 'ntpsec' / profile['sources']['ntpsec']['archive_root'] / 'build/config.h'
    header = ntpheader.read_text()
    if '#define CLOCK_SHM 1' not in header or '#define DISABLE_NTS 1' in header or '#define HAVE_SECCOMP_H 1' not in header:
        raise ValueError('selected NTPsec SHM/NTS/seccomp feature mismatch')
    gpssource = profile['sources']['gpsd']
    gpsheader = candidate / 'gpsd' / gpssource['archive_root'] / ('gpsd-' + gpssource['version']) / 'include/gpsd_config.h'
    gpsfeatures = gpsheader.read_text()
    validate_gpsd_features(gpsfeatures)
    if clock.inventory(candidate / 'stage') != manifest['files']:
        raise ValueError('staged smoke checks changed candidate bytes')
    return {'release_sha256': result['sha256'], 'staged_files': len(manifest['files']),
            'manuals_modules_versions_linkage': True, 'source_tests_passed': True,
            'ntpsec_shm_nts_seccomp': True, 'gpsd_selected_features': True,
            'gpsd_ublox_driver': True}


def entry(spec, files, epoch, mode):
    global STAGE
    os.umask(0o077)
    if mode not in ('build', 'readback'):
        raise ValueError('source build/readback only')
    STAGE = identity(spec, epoch)
    profile = verify_files(spec, files, mode == 'readback')
    if mode == 'readback':
        s = STAGE.lstat()
        if not stat.S_ISDIR(s.st_mode) or s.st_uid != 1000 or stat.S_IMODE(s.st_mode) != 0o700:
            raise ValueError('protected original stage required')
        return {'state': 'source_build_readback', 'stage': str(STAGE)}
    if packages() != spec['inventory']:
        raise ValueError('accepted foundation package inventory changed')
    header = Path('/usr/include/sys/timepps.h')
    if header.is_symlink() or not header.is_file() or sha(header.read_bytes()) != spec['pps_header_sha256']:
        raise ValueError('installed pps-tools header missing or changed')
    before = continuity()
    capacity = os.statvfs(STAGE.parent)
    if capacity.f_bavail * capacity.f_frsize < 2 * 1024 ** 3:
        raise ValueError('source workspace needs at least 2 GiB free')
    STAGE.mkdir(mode=0o700)  # Exclusive submission; never reuse partial output.
    receipt('claim', {'epoch': epoch, 'bundle_spec_sha256': sha((json.dumps(spec, sort_keys=True)+'\n').encode()),
                      'pid': os.getpid(), 'continuity': before})
    def interrupted(signum, frame):
        raise RuntimeError('source stage interrupted by signal ' + str(signum))
    for signum in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT, signal.SIGALRM):
        signal.signal(signum, interrupted)
    signal.alarm(10800)
    try:
        for name, data in files.items():
            create(STAGE / name, data)
        create(STAGE / 'spec.json', (json.dumps(spec, sort_keys=True)+'\n').encode())
        s = importlib.util.spec_from_file_location('clock', STAGE / 'clockmaker.py')
        clock = importlib.util.module_from_spec(s)
        s.loader.exec_module(clock)
        candidate = STAGE / 'candidate'
        result = clock.build(STAGE / 'profile.json', spec['members']['profile.json'], candidate)
        accepted = staged_acceptance(clock, candidate, profile, spec, result)
        if packages() != spec['inventory'] or continuity() != before:
            raise ValueError('package/boot/access-service continuity changed during build')
        receipt('acceptance', accepted)
        report = dict(accepted, state='source_build_staged_accepted', stage=str(STAGE),
                      live_installed=False, services_activated=False)
        receipt('complete', report)
        return report
    except BaseException as exc:
        receipt('failure', {'state': 'source_build_held', 'error': type(exc).__name__ + ': ' + str(exc),
                            'candidate_preserved': True, 'automatic_retry_authorized': False})
        raise
    finally:
        signal.alarm(0)


def evidence():
    if STAGE is None or not STAGE.exists():
        return {}
    result, size = {}, 0
    paths = list(STAGE.glob('*.json')) + list(STAGE.glob('acceptance*.log')) + [STAGE / 'candidate/build.log', STAGE / 'candidate/release.json']
    for path in sorted(paths):
        if not path.exists():
            continue
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as f:
            info = os.fstat(f.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != 1000 or info.st_mode & 0o077:
                raise ValueError('private build evidence required')
            data = f.read(16 * 1024 * 1024 + 1)
        size += len(data)
        if len(data) > 16 * 1024 * 1024 or size > 32 * 1024 * 1024:
            raise ValueError('build readback exceeds bound; original files preserved')
        result[str(path.relative_to(STAGE))] = {'sha256': sha(data), 'base64': base64.b64encode(data).decode('ascii')}
    return result
