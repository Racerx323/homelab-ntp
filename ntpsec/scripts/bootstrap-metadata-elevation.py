#!/usr/bin/python3
"""Rendered operator bootstrap/removal; copies bound data, never builds sources."""
import base64
import hashlib
import json
import os
from pathlib import Path
import socket
import stat
import subprocess
import sys
import time

BOUND_JSON = '@BOUND_JSON@'
DATA_JSON = '@DATA_JSON@'
ATTEMPT = '/var/lib/ntp-metadata-elevation/attempt-v6'
POLICY = '/etc/sudoers.d/ntp-metadata-attempt-v6'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def ancestors(path):
    for parent in (path, *path.parents):
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_gid != 0 or info.st_mode & 0o022:
            raise ValueError('unprotected directory: ' + str(parent))


def read_file(path, mode=None, limit=2 * 1024 * 1024):
    ancestors(path.parent)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_gid != 0
                or info.st_mode & 0o022 or info.st_nlink != 1 or info.st_size > limit
                or (mode is not None and stat.S_IMODE(info.st_mode) != mode)):
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


def write_new(path, data, mode=0o600):
    ancestors(path.parent)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    try:
        os.fchmod(fd, mode)
        while data:
            data = data[os.write(fd, data):]
        os.fsync(fd)
    finally:
        os.close(fd)
    sync_dir(path.parent)


def sync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def native(argv):
    tool = Path(argv[0])
    ancestors(tool.parent)
    resolved = tool.resolve(strict=True)
    read_file(resolved, limit=64 * 1024 * 1024)
    result = subprocess.run(argv, check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            timeout=30, cwd='/', env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'})
    if len(result.stdout) > 1024 * 1024:
        raise ValueError('native tool output exceeds bound')
    return result.stdout.decode('utf-8', errors='strict')


def inputs(config, encoded):
    if set(encoded) != {'runner.py', 'payload.py', 'sealed.json', 'policy.sudoers'}:
        raise ValueError('unexpected bootstrap input set')
    data = {name: base64.b64decode(value, validate=True) for name, value in encoded.items()}
    if any(len(value) > 2 * 1024 * 1024 or sha(value) != config['files'][name]['sha256']
           for name, value in data.items()):
        raise ValueError('bootstrap input hash/size mismatch')
    return data


def identity(config):
    if (os.geteuid() != 0 or not sys.flags.isolated or not sys.dont_write_bytecode
            or socket.gethostname() != config['hostname'] or os.uname().release != config['kernel']
            or os.uname().machine != 'aarch64'):
        raise ValueError('approved target and isolated root interpreter required')
    release = read_file(Path('/usr/lib/os-release')).decode()
    if not all(line in release.splitlines() for line in ('ID=debian', 'VERSION_ID="13"', 'VERSION_CODENAME=trixie')):
        raise ValueError('approved Debian 13 Trixie identity required')
    result = native(['/usr/bin/id', '-u', 'ama']).strip()
    if result != '1000':
        raise ValueError('ama identity drift')


def verified_policy(config):
    path = Path(config['policy_path'])
    if sha(read_file(path, 0o440)) != config['files']['policy.sudoers']['sha256']:
        raise ValueError('sudoers fragment drift; removal held')
    return path


def install(config, encoded, controller_epoch):
    identity(config)
    data = inputs(config, encoded)  # All bytes are verified before any persistent writes.
    root = Path(config['attempt_dir'])
    policy = Path(config['policy_path'])
    if (not config['prepared_epoch'] - 300 <= time.time() < config['expires_epoch']
            or abs(time.time() - controller_epoch) > 300):
        raise ValueError('bootstrap clock/window mismatch')
    ancestors(root.parent.parent)
    ancestors(policy.parent)
    if root.exists() or root.is_symlink() or policy.exists() or policy.is_symlink():
        raise ValueError('existing attempt or sudoers fragment; preserve and inspect')
    read_file(Path('/etc/sudoers'), 0o440)
    before = native(['/usr/sbin/visudo', '-c'])
    policy_before = native(['/usr/bin/sudo', '-n', '-l', '-U', 'ama'])
    tools = {}
    for name, flags in (('/usr/bin/python3', ['-VV']), ('/usr/sbin/visudo', ['-V']),
                        ('/usr/bin/sudo', ['-V'])):
        resolved = Path(name).resolve(strict=True)
        tools[name] = {'resolved': str(resolved), 'sha256': sha(read_file(resolved, limit=64 * 1024 * 1024)),
                       'version': native([name, *flags]),
                       'package_owner': native(['/usr/bin/dpkg-query', '-S', str(resolved)])}
    manual = Path('/usr/share/man/man5/sudoers.5.gz')
    tools['sudoers_manual_sha256'] = sha(read_file(manual))
    if not root.parent.exists():
        root.parent.mkdir(mode=0o700)
    ancestors(root.parent)
    root.mkdir(mode=0o700)
    activated = False
    try:
        write_new(root / 'policy-before.txt', policy_before.encode())
        write_new(root / 'visudo-before.txt', before.encode())
        write_new(root / 'tools.json', (json.dumps(tools, indent=2) + '\n').encode())
        for name, value in data.items():
            write_new(root / name, value, config['files'][name]['mode'])
        native(['/usr/sbin/visudo', '-c', '-f', str(root / 'policy.sudoers')])
        if time.time() >= config['expires_epoch']:
            raise ValueError('approval expired before policy activation')
        # Publish only a complete file. An interrupted direct write could leave
        # a truncated command entry that accidentally permits arbitrary arguments.
        publish = root / 'policy-publish.sudoers'
        write_new(publish, data['policy.sudoers'], 0o440)
        if root.stat().st_dev != policy.parent.stat().st_dev:
            raise ValueError('policy publication requires the same filesystem; no fallback')
        os.link(publish, policy, follow_symlinks=False)  # Exclusive destination; no replacement.
        activated = True
        publish.unlink()
        sync_dir(policy.parent)
        effective = native(['/usr/sbin/visudo', '-c'])
        if str(policy) not in effective:
            raise ValueError('sudoers fragment not in effective include set')
        permissions = native(['/usr/bin/sudo', '-n', '-l', '-U', 'ama', '--',
                              '/usr/bin/python3', '-I', '-B', str(root / 'runner.py')])
        for name, value in data.items():
            if read_file(root / name, config['files'][name]['mode']) != value:
                raise ValueError('installed input drift')
        verified_policy(config)
        if (root / 'claim.json').exists():
            raise ValueError('unexpected execution claim during bootstrap')
        report = {'state': 'installed_pending_operator_policy_review',
                  'controller_epoch': controller_epoch, 'observed_epoch': int(time.time()),
                  'attempt_dir': str(root), 'expires_epoch': config['expires_epoch'],
                  'files': config['files'], 'effective_visudo': effective,
                  'command_permissions': permissions, 'tools': tools,
                  'claim_present': False, 'collector_executed': False}
        write_new(root / 'bootstrap-receipt.json', (json.dumps(report, indent=2) + '\n').encode())
        return report
    except BaseException as exc:
        rollback = {'policy_removed': False, 'error': type(exc).__name__ + ': ' + str(exc)}
        if activated:
            try:
                verified_policy(config).unlink()
                sync_dir(policy.parent)
                rollback['policy_removed'] = True
                native(['/usr/sbin/visudo', '-c'])
            except Exception as cleanup:
                rollback['cleanup_error'] = type(cleanup).__name__ + ': ' + str(cleanup)
        write_new(root / 'bootstrap-failure.json', (json.dumps(rollback, indent=2) + '\n').encode())
        raise


def remove(config, rollback=False):
    identity(config)
    root = Path(config['attempt_dir'])
    ancestors(root)
    claim = root / 'claim.json'
    if rollback:
        if claim.exists() or claim.is_symlink():
            raise ValueError('claimed attempt cannot be rolled back or reset')
    else:
        record = json.loads(read_file(claim, 0o600))
        if record['state'] not in ('completed', 'completed_with_gaps', 'interrupted_or_failed'):
            raise ValueError('collector state unresolved; recover before removal')
    # Verify every removable input before deleting the first one.
    if rollback:
        for name, info in config['files'].items():
            if sha(read_file(root / name, info['mode'])) != info['sha256']:
                raise ValueError('staging drift; rollback held')
    policy = verified_policy(config)
    write_new(root / 'removal-started.json',
              (json.dumps({'state': 'removal_started', 'rollback': rollback}) + '\n').encode())
    policy.unlink()
    sync_dir(policy.parent)
    effective = native(['/usr/sbin/visudo', '-c'])
    if rollback:
        for name in config['files']:
            (root / name).unlink()
    report = {'state': 'unclaimed_bootstrap_rolled_back' if rollback else 'policy_removed_evidence_preserved',
              'effective_visudo': effective, 'claim_preserved': not rollback}
    write_new(root / ('rollback-receipt.json' if rollback else 'removal-receipt.json'),
              (json.dumps(report, indent=2) + '\n').encode())
    return report


def main():
    os.umask(0o077)
    config = json.loads(BOUND_JSON)
    if (config['attempt_dir'] != ATTEMPT or config['policy_path'] != POLICY
            or len(sys.argv) != 3 or sys.argv[1] not in ('install', 'remove', 'rollback')
            or not sys.argv[2].isascii() or not sys.argv[2].isdigit() or len(sys.argv[2]) > 20):
        raise ValueError('fixed operation and paths required')
    report = install(config, json.loads(DATA_JSON), int(sys.argv[2])) if sys.argv[1] == 'install' else remove(
        config, rollback=sys.argv[1] == 'rollback')
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
