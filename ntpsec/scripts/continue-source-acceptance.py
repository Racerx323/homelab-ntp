#!/usr/bin/python3
"""Accept the preserved v5 source candidate without rebuilding or installing it."""
import json
import os
from pathlib import Path
import signal
import stat
import time
import types

PREFIX = 'acceptance-continuation-v1'
ORIGIN_STAGE = '.ntp-source-build-v5'
ORIGIN_BUNDLE = 'fba4e9338a83a240b5f261360e7965ce5feb0000012992ffe02f26b5b46de55d'


def private_bytes(path, limit=40 * 1024 * 1024):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077 or info.st_nlink != 1 or info.st_size > limit):
            raise ValueError('protected original source evidence required: ' + str(path))
        data = stream.read(limit + 1)
        if len(data) > limit:
            raise ValueError('original evidence exceeds bound')
        return data


def continue_entry(spec, files, epoch, mode, worker):
    os.umask(0o077)
    if (mode not in ('accept', 'readback') or spec['operation'] != 'source-acceptance-continuation'
            or spec['origin_bundle_sha256'] != ORIGIN_BUNDLE or worker.STAGE_NAME != ORIGIN_STAGE
            or set(files) != {'source-build-stage.py'}
            or set(spec['retained']) != {'spec.json', 'claim.json', 'failure.json',
                                         'candidate/build.log', 'candidate/release.json', 'acceptance.log'}
            or worker.sha(files['source-build-stage.py']) != spec['members']['source-build-stage.py']):
        raise ValueError('bound v5 acceptance/readback only; no rebuild or installation')
    worker.STAGE = worker.identity(spec, epoch)
    root = worker.STAGE
    for path in (root, root / 'candidate', root / 'candidate/stage'):
        info = path.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o700):
            raise ValueError('protected retained candidate required')
    for name, checksum in spec['retained'].items():
        if name not in {'spec.json', 'claim.json', 'failure.json', 'candidate/build.log',
                        'candidate/release.json', 'acceptance.log'}:
            raise ValueError('unexpected retained evidence path')
        if worker.sha(private_bytes(root / name)) != checksum:
            raise ValueError('retained evidence drift: ' + name)
    origin = json.loads(private_bytes(root / 'spec.json'))
    for key in ('hostname', 'kernel', 'python', 'inventory', 'pps_header_sha256'):
        if spec[key] != origin[key]:
            raise ValueError('original target/prerequisite binding mismatch')
    original_files = {}
    for name, checksum in origin['members'].items():
        if Path(name).name != name:
            raise ValueError('unexpected original member path')
        original_files[name] = private_bytes(root / name)
        if worker.sha(original_files[name]) != checksum:
            raise ValueError('original member drift: ' + name)
    profile = worker.verify_files(origin, original_files)
    claim = json.loads(private_bytes(root / 'claim.json'))
    if claim['bundle_spec_sha256'] != spec['retained']['spec.json']:
        raise ValueError('original claim specification mismatch')
    release = json.loads(private_bytes(root / 'candidate/release.json'))
    if release['profile_sha256'] != origin['members']['profile.json']:
        raise ValueError('retained release profile mismatch')
    if mode == 'readback':
        return {'state': 'source_acceptance_readback', 'stage': str(root)}
    if (root / 'complete.json').exists() or (root / (PREFIX + '-complete.json')).exists():
        raise ValueError('accepted candidate cannot be replayed')
    if Path('/proc', str(claim['pid'])).exists():
        raise ValueError('original process identity unresolved; preserve candidate')
    if worker.packages() != spec['inventory'] or worker.continuity() != claim['continuity']:
        raise ValueError('original package/boot/access continuity changed')
    header = Path('/usr/include/sys/timepps.h')
    if header.is_symlink() or worker.sha(header.read_bytes()) != spec['pps_header_sha256']:
        raise ValueError('installed PPS header drift')
    worker.receipt(PREFIX + '-claim', {'controller_epoch': epoch,
                   'origin_bundle_sha256': ORIGIN_BUNDLE,
                   'continuation_spec_sha256': worker.sha((json.dumps(spec, sort_keys=True) + '\n').encode())})
    def interrupted(signum, frame):
        raise RuntimeError('acceptance continuation interrupted by signal ' + str(signum))
    for signum in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT, signal.SIGALRM):
        signal.signal(signum, interrupted)
    signal.alarm(600)
    try:
        clock = types.ModuleType('sealed_clockmaker')
        clock.__file__ = str(root / 'clockmaker.py')
        exec(compile(original_files['clockmaker.py'], clock.__file__, 'exec'), clock.__dict__)
        clock.target_identity(spec['hostname'])
        clock.require_no_package_applications()
        result = {'manifest': str(root / 'candidate/release.json'),
                  'sha256': spec['retained']['candidate/release.json']}
        accepted = worker.staged_acceptance(clock, root / 'candidate', profile, spec, result,
                                           'acceptance-continuation-v1.log')
        if worker.packages() != spec['inventory'] or worker.continuity() != claim['continuity']:
            raise ValueError('package/boot/access continuity changed during acceptance')
        worker.receipt(PREFIX + '-acceptance', accepted)
        report = dict(accepted, state='source_candidate_accepted_after_continuation',
                      stage=str(root), build_repeated=False, live_installed=False,
                      services_activated=False)
        worker.receipt(PREFIX + '-complete', report)
        return report
    except BaseException as exc:
        worker.receipt(PREFIX + '-failure', {'state': 'source_acceptance_held',
                       'error': type(exc).__name__ + ': ' + str(exc),
                       'candidate_preserved': True, 'automatic_retry_authorized': False})
        raise
    finally:
        signal.alarm(0)
