#!/usr/bin/python3
"""Inspect the live selected association without running plugins or changing services."""
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import stat
import subprocess
import time


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def protected(path):
    path = Path(path)
    for parent in path.parents:
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError('unprotected input ancestor')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != 0 or before.st_gid != 0
                or before.st_mode & 0o022 or before.st_nlink != 1 or before.st_size > 4*1048576):
            raise ValueError('unprotected regular input')
        raw = stream.read(4*1048576+1)
        after = os.fstat(stream.fileno())
    if len(raw) > 4*1048576 or any(getattr(before, k) != getattr(after, k)
            for k in ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')):
        raise ValueError('input changed during read')
    return raw


def command(argv):
    row = subprocess.run(argv, capture_output=True, text=True, timeout=12,
                         env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LC_ALL': 'C'})
    result = {'argv': argv, 'returncode': row.returncode, 'stdout': row.stdout, 'stderr': row.stderr}
    if len(row.stdout.encode()) > 65536 or len(row.stderr.encode()) > 65536:
        raise ValueError('bounded command output required')
    return result


def fields(row):
    if row['returncode'] != 0:
        raise ValueError('read-only unit query failed')
    pairs = [line.split('=', 1) for line in row['stdout'].splitlines()]
    if any(len(pair) != 2 for pair in pairs) or len(dict(pairs)) != len(pairs):
        raise ValueError('distinct unit properties required')
    return dict(pairs)


def selected_id(text):
    ids = re.findall(r'(?:^|[,\n ])peer\s*=\s*([0-9]+)(?=[,\n ]|$)', text)
    if len(ids) != 1 or not 0 < int(ids[0]) <= 65535:
        raise ValueError('one live selected association ID required')
    return int(ids[0])


def snapshot(spec):
    identity = fields(command(['/usr/bin/systemctl', 'show', 'timeservice.service',
        '--property=MainPID,InvocationID,NRestarts,ActiveState,SubState']))
    if identity != spec['service_identity']:
        raise ValueError('time-service continuity changed')
    node = fields(command(['/usr/bin/systemctl', 'show', 'munin-node.service',
        '--property=ActiveState,SubState,UnitFileState']))
    if node != {'ActiveState': 'inactive', 'SubState': 'dead', 'UnitFileState': 'disabled'}:
        raise ValueError('contained node state changed')
    listener = command(['/usr/bin/ss', '-H', '-lnt', 'sport = :4949'])
    if listener['returncode'] or listener['stdout'].strip():
        raise ValueError('contained listener state changed')
    hashes = {path: digest(protected(path)) for path in spec['files']}
    if hashes != spec['files'] or os.path.lexists(spec['permit_path']):
        raise ValueError('protected input/start-permit drift')
    return {'timeservice': identity, 'munin_node': node, 'listener_absent': True,
            'permit_absent': True, 'file_hashes': hashes}


def collect(spec):
    if os.geteuid() != 0 or os.getegid() != 0 or socket.gethostname() != spec['hostname']:
        raise ValueError('root/host mismatch')
    if Path('/proc/sys/kernel/random/boot_id').read_text().strip() != spec['boot_id']:
        raise ValueError('boot mismatch')
    before = snapshot(spec)
    # Match the deployed plugin's identity, binary, environment and local target.
    prefix = ['/usr/sbin/runuser', '-u', 'munin', '--', '/usr/local/bin/ntpq', '-n']
    raw = command([*prefix, '-c', 'rv 0 leap,stratum,offset,sys_jitter,peer,refid',
                   '-c', 'peers', '-c', 'associations', '127.0.0.1'])
    if raw['returncode']:
        raise ValueError('source-built ntpq read failed')
    association = selected_id(raw['stdout'])
    detail = command([*prefix, '-c', 'rv '+str(association), '127.0.0.1'])
    if detail['returncode']:
        raise ValueError('selected association read failed')
    # A second system-only query guards against selection changing across reads.
    ending = command([*prefix, '-c', 'rv 0 peer,refid,leap,stratum', '127.0.0.1'])
    after = snapshot(spec)
    return {'capture_complete': True, 'captured_epoch': time.time(), 'before': before, 'after': after,
            'ntp_config': protected('/etc/ntp.conf').decode(), 'raw': raw, 'association': detail,
            'selected_association': association, 'ending': ending,
            'selection_stable': ending['returncode'] == 0 and selected_id(ending['stdout']) == association,
            'target_mutation': False, 'plugins_executed': False, 'service_actions': False}
