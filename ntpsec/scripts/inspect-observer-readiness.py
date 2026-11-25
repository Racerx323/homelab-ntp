#!/usr/bin/python3
"""Passive OBS-09 controller inputs; never authenticate onward or change services."""
import base64
import hashlib
import json
import os
from pathlib import Path
import pwd
import shlex
import socket
import stat
import time

SOURCES = ('10.1.3.83', 'fd36:5aa8:6971:1::83')
DESTINATIONS = ('10.1.0.51', 'fd36:5aa8:6971:1::51')


def emit(key, data):
    print(json.dumps({'key': key, 'data': data}, allow_nan=False), flush=True)


def metadata(path):
    try:
        s = path.lstat()
        return {'uid': s.st_uid, 'gid': s.st_gid, 'mode': stat.S_IMODE(s.st_mode),
                'type': stat.S_IFMT(s.st_mode), 'size': s.st_size}
    except FileNotFoundError:
        return {'missing': True}


def read_public(path):
    """No private-key or credential reads; reject indirect/special/oversized input."""
    if path.resolve() != path.absolute():
        raise ValueError('indirect public input: '+str(path))
    with path.open('rb') as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            raise ValueError('regular public input required')
        raw = f.read(65537)
    if len(raw) > 65536:
        raise ValueError('public input exceeds 64KiB')
    return raw.decode('ascii')


def public_fingerprints(text):
    """Return only key fingerprints and presence of restrictions, never comments/options."""
    result = []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        try:
            words = shlex.split(line)
            index = next(i for i, word in enumerate(words)
                         if word.startswith(('ssh-', 'ecdsa-', 'sk-')))
            raw = base64.b64decode(words[index+1], validate=True)
            if len(raw) < 4:
                raise ValueError('short key')
            size = int.from_bytes(raw[:4], 'big')
            if raw[4:4+size].decode('ascii') != words[index]:
                raise ValueError('key type mismatch')
            result.append({'line': number, 'fingerprint': 'SHA256:'+base64.b64encode(
                hashlib.sha256(raw).digest()).decode().rstrip('='),
                'has_options': index != 0})
        except (ValueError, StopIteration, IndexError, UnicodeError):
            result.append({'line': number, 'invalid_public_record': True})
    return result


def ssh_metadata(user, authorized=False):
    account = pwd.getpwnam(user)
    directory = Path(account.pw_dir)/'.ssh'
    result = {'user': user, 'uid': account.pw_uid, 'directory': str(directory),
              'metadata': metadata(directory), 'entries': {}}
    if result['metadata'].get('missing'):
        return result
    if directory.resolve() != directory or not directory.is_dir():
        raise ValueError('indirect SSH directory')
    entries = sorted(directory.iterdir())
    if len(entries) > 64:
        raise ValueError('SSH directory entry cap')
    for path in entries:
        row = metadata(path)
        if path.suffix == '.pub' or (authorized and path.name == 'authorized_keys'):
            row['public_keys'] = public_fingerprints(read_public(path))
        result['entries'][path.name] = row
    return result


def bind_sources():
    """Bind only: no connect, packet, NTP request or administrative probe."""
    rows = []
    for address, family in zip(SOURCES, (socket.AF_INET, socket.AF_INET6)):
        row = {'expected_source': address}
        try:
            with socket.socket(family, socket.SOCK_DGRAM) as sock:
                sock.bind((address, 0))
                row['actual_source'] = sock.getsockname()[0]
        except OSError as error:
            row['error'] = str(error)
        rows.append(row)
    return rows


def collect(role, expected_hostname, helper):
    before = {'hostname': socket.gethostname(),
              'boot': Path('/proc/sys/kernel/random/boot_id').read_text().strip()}
    emit('identity', before)
    if before['hostname'] != expected_hostname or os.geteuid() != 0:
        raise ValueError('root/host mismatch')
    commands = {}
    if role == 'master':
        commands = {
            'addresses': ['/usr/sbin/ip', '-j', 'address', 'show', 'dev', 'eth0'],
            'route4': ['/usr/sbin/ip', '-j', '-4', 'route', 'get', DESTINATIONS[0], 'from', SOURCES[0]],
            'route6': ['/usr/sbin/ip', '-j', '-6', 'route', 'get', DESTINATIONS[1], 'from', SOURCES[1]],
            'network': ['/usr/bin/nmcli', '-g', 'GENERAL.DEVICE,GENERAL.CON-UUID,IP4.ADDRESS,IP6.ADDRESS', 'device', 'show', 'eth0'],
            'systemd': ['/usr/bin/systemctl', '--version'],
            'manager': ['/usr/bin/systemctl', 'show', '--property=SystemState,Version'],
            'services': ['/usr/bin/systemctl', 'show', 'munin-node.service', 'cron.service', '--property=Id,ActiveState,SubState'],
            'filesystem': ['/usr/bin/findmnt', '-J', '-T', '/var/lib', '-o', 'TARGET,SOURCE,FSTYPE,OPTIONS'],
        }
        emit('source_bind', bind_sources())
        emit('ssh_metadata', [ssh_metadata(user) for user in ('pi', 'root')])
        space = os.statvfs('/var/lib')
        emit('capacity', {'available_bytes': space.f_bavail*space.f_frsize,
                          'available_inodes': space.f_favail})
        paths = ('/usr/bin/python3', '/usr/bin/ssh', '/usr/bin/systemd-run',
                 '/usr/bin/systemctl', '/usr/bin/timeout', '/usr/bin/sudo',
                 '/usr/bin/runuser', '/usr/sbin/runuser', '/usr/bin/rrdtool', '/usr/bin/perl',
                 '/var/lib/munin', '/var/lib/munin/datafile', '/var/lib/munin/limits',
                 '/etc/munin/munin.conf', '/var/lib/ntp-observation')
        emit('paths', {p: metadata(Path(p)) for p in paths})
    elif role == 'node':
        emit('ssh_metadata', ssh_metadata('ama', authorized=True))
        emit('ssh_host_key', public_fingerprints(read_public(Path('/etc/ssh/ssh_host_ed25519_key.pub'))))
        commands = {
            'sudo_policy': ['/usr/bin/sudo', '-n', '-l', '-U', 'ama'],
            'ssh_policy': ['/usr/sbin/sshd', '-T', '-C', 'user=ama,addr=10.1.3.83,host=J1-SVMF'],
        }
    else:
        raise ValueError('closed inspection role')
    for name, argv in commands.items():
        row = helper.bounded(argv, timeout=8, limit=65536)
        if name == 'ssh_policy':
            # Keep only authentication/location controls, not the entire daemon configuration.
            allowed = ('pubkeyauthentication ', 'authorizedkeysfile ', 'authorizedkeyscommand ',
                       'allowusers ', 'denyusers ', 'authenticationmethods ', 'strictmodes ')
            row['stdout'] = '\n'.join(x for x in row.get('stdout', '').splitlines() if x.startswith(allowed))
        emit(name, row)
    after = {'hostname': socket.gethostname(),
             'boot': Path('/proc/sys/kernel/random/boot_id').read_text().strip()}
    emit('identity_after', after)
    emit('finished_epoch', time.time())
    if before != after:
        raise ValueError('boot/identity changed within capture')
    emit('complete', True)
