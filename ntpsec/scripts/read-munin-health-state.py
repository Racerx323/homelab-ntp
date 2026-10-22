#!/usr/bin/python3
"""Read retained Munin health command results; execute no plugin or service action."""
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import stat
import time

LIMIT = 2 * 1048576


def health_rows(state, expected_digest):
    if state.get('spec_sha256') != expected_digest:
        raise ValueError('retained state specification mismatch')
    commands = state.get('commands')
    if not isinstance(commands, list) or len(commands) > 1000:
        raise ValueError('bounded retained command list required')
    selected = []
    for row in commands:
        if row.get('argv') not in (['/usr/sbin/munin-run', 'ntp_health'],
                                   ['/usr/sbin/munin-run', 'ntp_health', 'config']):
            continue
        if any(not isinstance(row.get(key), str) or len(row[key]) > 65536
               for key in ('stdout', 'stderr')):
            raise ValueError('bounded retained health output required')
        selected.append({key: row[key] for key in ('argv', 'returncode', 'stdout', 'stderr')})
    return selected


def collect(spec):
    if os.geteuid() != 0 or os.getegid() != 0 or socket.gethostname() != spec['hostname']:
        raise ValueError('root/host mismatch')
    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    if boot != spec['boot_id']:
        raise ValueError('boot mismatch; retained state retrieval held')
    if not re.fullmatch(r'munin-node-install-[a-z0-9-]{1,55}', spec['source_operation']):
        raise ValueError('fixed node-install state scope required')
    path = Path('/var/lib/munin-ntp-install') / spec['source_operation'] / 'state.json'
    for parent in path.parents:
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError('unsafe retained state ancestor')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != 0 or before.st_gid != 0
                or stat.S_IMODE(before.st_mode) != 0o600 or before.st_nlink != 1 or before.st_size > LIMIT):
            raise ValueError('unsafe retained state file')
        raw = stream.read(LIMIT + 1)
        after = os.fstat(stream.fileno())
    keys = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
    if len(raw) > LIMIT or any(getattr(before, key) != getattr(after, key) for key in keys):
        raise ValueError('retained state changed during read')
    state = json.loads(raw)
    rows = health_rows(state, spec['worker_spec_sha256'])
    return {'capture_complete': True, 'captured_epoch': time.time(), 'hostname': spec['hostname'],
            'boot_id': boot, 'source_archive_sha256': spec['source_archive_sha256'],
            'state_file_sha256': hashlib.sha256(raw).hexdigest(),
            'state': {key: state.get(key) for key in
                      ('spec_sha256', 'accepted', 'phase', 'recovery', 'recovery_errors')},
            'health_commands': rows, 'target_mutation': False, 'plugins_executed': False}
