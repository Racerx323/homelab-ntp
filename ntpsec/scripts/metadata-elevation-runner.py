#!/usr/bin/python3
"""Rendered, fixed-input, one-shot metadata runner. Unrendered source refuses use."""
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import signal
import socket
import stat
import sys
import time

BOUND_JSON = '@BOUND_JSON@'
ATTEMPT = '/var/lib/ntp-metadata-elevation/attempt-v4'


def ancestors(path):
    for parent in (path, *path.parents):
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_gid != 0 or info.st_mode & 0o022:
            raise ValueError('unprotected directory: ' + str(parent))


def protected_bytes(path, mode=0o600, limit=2 * 1024 * 1024):
    ancestors(path.parent)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_gid != 0
                or stat.S_IMODE(info.st_mode) != mode or info.st_nlink != 1 or info.st_size > limit):
            raise ValueError('unprotected file: ' + str(path))
        data = bytearray()
        while len(data) <= limit:
            block = os.read(fd, min(65536, limit + 1 - len(data)))
            if not block:
                return bytes(data)
            data.extend(block)
        raise ValueError('file exceeds bound')
    finally:
        os.close(fd)


def read_epoch(fd=0, seconds=10):
    stop = time.monotonic() + seconds
    data = bytearray()
    with selectors.DefaultSelector() as selector:
        selector.register(fd, selectors.EVENT_READ)
        while True:
            remaining = stop - time.monotonic()
            if remaining <= 0 or not selector.select(remaining):
                raise ValueError('timestamp input deadline exceeded')
            block = os.read(fd, 22 - len(data))
            if not block:
                break
            data.extend(block)
            if len(data) >= 22:
                raise ValueError('timestamp input exceeds bound')
    if not re.fullmatch(rb'[0-9]{1,20}\n', data):
        raise ValueError('decimal timestamp and EOF required')
    return int(data)


def claim_record(fd, record):
    data = (json.dumps(record, sort_keys=True) + '\n').encode()
    os.lseek(fd, 0, os.SEEK_SET)
    os.ftruncate(fd, 0)
    while data:
        data = data[os.write(fd, data):]
    os.fsync(fd)


def execute(config, epoch):
    root = Path(config['attempt_dir'])
    if (os.geteuid() != 0 or os.environ.get('SUDO_USER') != 'ama'
            or os.environ.get('SUDO_UID') != '1000' or not sys.flags.isolated
            or not sys.dont_write_bytecode):
        raise ValueError('isolated root execution through approved sudo identity required')
    if socket.gethostname() != config['hostname']:
        raise ValueError('unexpected target hostname')
    if time.time() >= config['expires_epoch'] or abs(time.time() - epoch) > 300:
        raise ValueError('approval expired or controller clock mismatch')
    ancestors(root)
    if stat.S_IMODE(root.stat().st_mode) != 0o700:
        raise ValueError('attempt directory requires mode 0700')
    manifest = protected_bytes(root / 'sealed.json')
    payload = protected_bytes(root / 'payload.py')
    if (hashlib.sha256(manifest).hexdigest() != config['manifest_sha256']
            or hashlib.sha256(payload).hexdigest() != config['payload_sha256']):
        raise ValueError('sealed input hash mismatch')
    sealed = json.loads(manifest)
    if (sealed['payload_sha256'] != config['payload_sha256']
            or sealed['expires_epoch'] != config['expires_epoch']
            or sealed['attempt_dir'] != config['attempt_dir']):
        raise ValueError('sealed manifest disagreement')
    receipt = json.loads(protected_bytes(root / 'bootstrap-receipt.json'))
    if (receipt['state'] != 'installed_pending_operator_policy_review'
            or receipt['attempt_dir'] != config['attempt_dir'] or receipt['claim_present']
            or receipt['expires_epoch'] != config['expires_epoch']
            or receipt['files']['payload.py']['sha256'] != config['payload_sha256']
            or receipt['files']['runner.py']['sha256'] != hashlib.sha256(
                protected_bytes(root / 'runner.py')).hexdigest()):
        raise ValueError('completed bootstrap receipt required')
    code = compile(payload, 'sealed-metadata.py', 'exec')
    if time.time() >= config['expires_epoch']:
        raise ValueError('approval expired before claim')
    fd = os.open(root / 'claim.json', os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    record = {'state': 'registered_before_collector', 'controller_epoch': epoch,
              'payload_sha256': config['payload_sha256'], 'started_epoch': int(time.time()),
              'runner_pid': os.getpid()}
    try:
        claim_record(fd, record)
        directory_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        os.environ.clear()
        os.environ.update(PATH='/usr/bin:/bin', LC_ALL='C', SUDO_USER='ama', SUDO_UID='1000')
        sys.argv = ['sealed-metadata.py', '--controller-epoch', str(epoch)]
        try:
            exec(code, {'__name__': '__main__'})
        except SystemExit as exc:
            if type(exc.code) is not int or exc.code not in (0, 2):
                raise ValueError('unexpected collector exit status') from exc
            record.update(state='completed' if exc.code == 0 else 'completed_with_gaps',
                          collector_exit_status=exc.code)
            return exc.code
        raise ValueError('collector did not emit its terminal exit')
    except BaseException as exc:
        record.update(state='interrupted_or_failed', error=type(exc).__name__ + ': ' + str(exc))
        raise
    finally:
        record['finished_epoch'] = int(time.time())
        try:
            claim_record(fd, record)
        finally:
            os.close(fd)


def main():
    os.umask(0o077)
    def interrupted(signum, frame):
        raise RuntimeError('interrupted by signal ' + str(signum))
    for signum in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
        signal.signal(signum, interrupted)
    try:
        config = json.loads(BOUND_JSON)
        if len(sys.argv) != 1 or config['attempt_dir'] != ATTEMPT:
            raise ValueError('fixed runner with no additional arguments required')
        if Path(__file__).absolute() != Path(ATTEMPT) / 'runner.py':
            raise ValueError('runner must be installed at its fixed path')
        protected_bytes(Path(__file__))
        return execute(config, read_epoch())
    except Exception as exc:
        print(json.dumps({'state': 'preflight_rejected', 'metadata_accepted': False,
                          'package_mutation_authorized': False,
                          'error': type(exc).__name__ + ': ' + str(exc)}, sort_keys=True))
        print('METADATA_RESOLUTION_EXIT_STATUS=2')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
