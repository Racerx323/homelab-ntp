#!/usr/bin/python3
"""Complete the fixed retention cleanup or record a completed real reporter run."""
import argparse
import json
import os
from pathlib import Path
import secrets
import stat
import subprocess
import sys
import time

DIRECTORIES = {'retention': Path('/var/lib/ntpstats-retention'),
               'reporting': Path('/var/lib/needrestart-reporting')}
STATS = Path('/var/log/ntpstats')
STREAMS = ('loopstats', 'peerstats', 'clockstats', 'protostats')


def protected_directory(path):
    """Root CLI requires root-only ancestry; local unit tests use their own UID."""
    path = Path(path)
    for parent in (path, *path.parents):
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid not in (0, os.geteuid()) or info.st_mode & 0o022:
            raise ValueError('unsafe success-record directory')
    info = path.lstat()
    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError('success-record parent must be private and owned')


def destination(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid()
            or info.st_gid != os.getegid() or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > 4096):
        raise ValueError('unsafe existing success record')
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


def write_success(directory, job):
    if job not in DIRECTORIES:
        raise ValueError('fixed job required')
    directory = Path(directory)
    protected_directory(directory)
    path = directory/'last-success.json'
    before = destination(path)
    raw = (json.dumps({'schema': 1, 'job': job, 'status': 'success',
                       'completed_epoch': time.time()}, sort_keys=True)+'\n').encode()
    temporary = directory/('.last-success-'+secrets.token_hex(12))
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        if destination(path) != before:
            raise ValueError('concurrent success-record change')
        os.replace(temporary, path)
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        temporary.unlink(missing_ok=True)


def retention(directory=STATS):
    directory = Path(directory)
    if directory.is_symlink() or any(p.is_symlink() for p in directory.parents):
        raise ValueError('indirect statistics directory')
    for stream in STREAMS:
        info = (directory/stream).lstat()
        if not stat.S_ISREG(info.st_mode):
            raise ValueError('active statistics file missing or indirect: '+stream)
    argv = ['/usr/bin/find', str(directory), '-regextype', 'posix-extended', '-maxdepth', '1',
            '-type', 'f', '-links', '1', '-regex', str(directory)+
            '/(loopstats|peerstats|clockstats|protostats)\\.[0-9]{8}(\\.gz)?']
    for stream in STREAMS:
        argv.extend(['!', '-samefile', str(directory/stream)])
    argv.extend(['-mtime', '+29', '-delete'])
    row = subprocess.run(argv, capture_output=True, timeout=180)
    if row.returncode:
        raise RuntimeError('retention cleanup failed: '+row.stderr[:4096].decode(errors='replace'))


def complete(job):
    if job == 'retention':
        retention()
    write_success(DIRECTORIES[job], job)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('job', choices=DIRECTORIES)
    args = parser.parse_args()
    if os.geteuid() != 0 or os.getegid() != 0:
        raise SystemExit('root required')
    try:
        complete(args.job)
    except Exception as error:
        print('Maintenance completion failed: '+str(error), file=sys.stderr)
        raise SystemExit(1)


if __name__ == '__main__':
    main()
