#!/usr/bin/python3
"""Scoped access and native master lifecycle for the existing OBS-09 collector.

Deployment is the reviewed native runbook, not an SSH installation framework.
The node gateway accepts named samples only; it never consumes uploaded code.
"""
import argparse
import base64
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pwd
import re
import socket
import stat
import subprocess
import sys
import time


def require(ok, message):
    if not ok:
        raise ValueError(message)


def trusted(path, directory=False):
    path = Path(path)
    for parent in (path, *path.parents):
        st = parent.lstat()
        require(not stat.S_ISLNK(st.st_mode) and st.st_uid == 0 and not st.st_mode & 0o022,
                'unsafe root-owned path: '+str(parent))
    require(path.is_dir() if directory else path.is_file(), 'wrong path type')


def load(bundle, expected):
    trusted(bundle, True)
    raw = (bundle/'manifest.json').read_bytes()
    require(hashlib.sha256(raw).hexdigest() == expected, 'manifest approval mismatch')
    manifest = json.loads(raw)
    require(manifest['execution_ready'] is True, 'not executable')
    for name, record in manifest['files'].items():
        require(re.fullmatch(r'[A-Za-z0-9_.-]+', name), 'unsafe member')
        trusted(bundle/name)
        data = (bundle/name).read_bytes()
        require(len(data) == record['bytes'] and hashlib.sha256(data).hexdigest() == record['sha256'],
                'sealed member drift: '+name)
    loader = importlib.util.spec_from_file_location('observer', bundle/'observer.py')
    observer = importlib.util.module_from_spec(loader); loader.loader.exec_module(observer)
    spec = observer.check(bundle, expected)
    require(spec.get('hosting') == 'master', 'master-hosted scope required')
    require(bundle == Path(spec['deployment_root'])/'inputs', 'closed deployment path')
    return observer, spec


def sample(label):
    if label == 'entry':
        return True
    require(re.fullmatch(r'slot-\d{3}', label), 'named sample required; no shell or stdin')
    slot = int(label[5:])
    require(0 <= slot <= 576, 'sample outside window')
    return slot in (0, 288, 576)


def admission(root, expected, role, now):
    trusted(root/'admission.json')
    value = json.loads((root/'admission.json').read_text())
    require(value['manifest_sha256'] == expected and value['role'] == role, 'admission mismatch')
    require(value['epoch'] <= now <= value['deadline'] <= value['epoch']+180000,
            'access deadline expired or invalid')
    require(value['boot'] == Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
            'boot changed since admission')
    return value


def key_line(public, spec, expected):
    parts = public.split()
    require(len(parts) in (2, 3) and parts[0] == 'ssh-ed25519', 'dedicated Ed25519 key required')
    blob = base64.b64decode(parts[1], validate=True)
    require(len(blob) == 51 and blob[:19] == b'\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20',
            'invalid Ed25519 blob')
    command = ('/usr/bin/python3 -I -B '+spec['gateway_path']+' node --bundle '+
               spec['deployment_root']+'/inputs --sha256 '+expected)
    require(re.fullmatch(r'[A-Za-z0-9_./ -]+', command), 'unsafe forced command')
    return ('restrict,from="10.1.3.83",command="'+command+'" '+parts[0]+' '+parts[1]+
            ' '+spec['operation']+'\n').encode()


def key_file(path, owner):
    for parent in path.parents:
        require(not parent.is_symlink(), 'indirect authorized-key path')
    st = path.lstat()
    require(stat.S_ISREG(st.st_mode) and st.st_uid == owner and st.st_nlink == 1
            and stat.S_IMODE(st.st_mode) == 0o600 and st.st_size <= 65536,
            'unsafe authorized-key file')
    return path.read_bytes(), st


def replace_key_file(path, previous, value, metadata):
    """Atomic publication, preserving ownership and unrelated lines; fail on drift."""
    temp = path.with_name(path.name+'.obs09-new')
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(value); stream.flush(); os.fsync(stream.fileno())
            os.fchown(stream.fileno(), metadata.st_uid, metadata.st_gid)
        current, st = key_file(path, metadata.st_uid)
        require(current == previous and st.st_ino == metadata.st_ino, 'concurrent key edit; stop')
        os.replace(temp, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(directory)
        finally: os.close(directory)
    finally:
        if temp.exists(): temp.unlink()


def authorize(root, spec, expected, observer, remove=False):
    account = pwd.getpwnam('ama')
    path = Path(account.pw_dir)/'.ssh/authorized_keys'
    # Existing SSH-directory ownership is not changed. This is an operation lock,
    # not a claim that an unrelated editor cooperates with flock.
    with open(root/'key-edit.lock', 'ab') as lock:
        os.chmod(lock.name, 0o600); fcntl.flock(lock, fcntl.LOCK_EX)
        original, meta = key_file(path, account.pw_uid)
        receipt = root/'authorization.json'
        if not remove:
            require(not receipt.exists(), 'authorization already consumed')
            line = key_line((root/'public.pub').read_text(), spec, expected)
            require(spec['operation'].encode() not in original, 'existing operation key')
            require(line.split()[-2] not in original, 'key already present')
            combined = original + (b'\n' if original and not original.endswith(b'\n') else b'') + line
            observer.write_new(receipt, {'original_b64': base64.b64encode(original).decode(),
                                        'line_b64': base64.b64encode(line).decode(),
                                        'installed_sha256': observer.digest(combined)})
            replace_key_file(path, original, combined, meta)
        else:
            value = json.loads(receipt.read_text())
            line = base64.b64decode(value['line_b64'])
            if (root/'revoked.json').exists():
                require(line not in original and spec['operation'].encode() not in original,
                        'revoked operation key reappeared')
                return
            if observer.digest(original) == value['installed_sha256']:
                restored = base64.b64decode(value['original_b64'])
            else:
                require(original.splitlines(keepends=True).count(line) <= 1, 'ambiguous owned key')
                restored = b''.join(x for x in original.splitlines(keepends=True) if x != line)
                require(spec['operation'].encode() not in restored, 'owned key changed; inspect before cleanup')
            replace_key_file(path, original, restored, meta)
            observer.write_new(root/'revoked.json', {'epoch': time.time(), 'remaining_sha256': observer.digest(restored)})


def boundary_record(observer, bundle, spec, output, expected):
    observer.private(output)
    require(not any(output.iterdir()), 'empty boundary output required')
    started = time.time()
    observer.write_new(output/'launch.json', {'epoch': started, 'manifest_sha256': expected})
    observer.boundary_windows(bundle, spec, output, 'workstation')
    observer.boundary_commands(bundle, spec, output, 'workstation')
    observer.write_new(output/'boundary.json', {'started_epoch': started, 'finished_epoch': time.time(),
                                              'manifest_sha256': expected, 'complete': True,
                                              'files': {p.name: observer.digest(p.read_bytes())
                                                        for p in sorted(output.iterdir()) if p.is_file()}})


def validate_boundary(value, expected, endpoint, finish=False):
    require(value['manifest_sha256'] == expected and value['complete'] is True, 'boundary mismatch')
    first, last = value['started_epoch'], value['finished_epoch']
    require(first <= last and last-first <= 90, 'boundary duration exceeded')
    require(endpoint-1800 <= first <= last <= endpoint if not finish else
            endpoint <= first <= last <= endpoint+1800, 'boundary outside 30-minute allowance')


def wait_for_grant(root, deadline):
    """Wait only for an atomically published reviewed grant; never generate one."""
    while not (root/'grant.json').exists():
        require(time.monotonic() < deadline, 'entry review deadline; no automatic start')
        time.sleep(min(5, max(0, deadline-time.monotonic())))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('phase', choices=('node', 'node-root', 'admit', 'key', 'authorize', 'revoke',
                                     'run', 'retire-key', 'boundary', 'finish'))
    p.add_argument('--bundle', type=Path, required=True)
    p.add_argument('--sha256', required=True)
    p.add_argument('--role', choices=('node', 'master'))
    p.add_argument('--sample')
    p.add_argument('--output', type=Path)
    p.add_argument('--start', type=Path)
    a = p.parse_args()
    # This branch runs as ama via sshd's forced command, before reading root inputs.
    if a.phase == 'node':
        label = os.environ.get('SSH_ORIGINAL_COMMAND', '')
        sample(label)
        require(os.isatty(0) is False, 'PTY prohibited')
        os.execv('/usr/bin/sudo', ['sudo', '-n', '--', '/usr/bin/timeout', '--kill-after=2s', '130s',
                 '/usr/bin/python3', '-I', '-B', str(Path(__file__).absolute()), 'node-root',
                 '--bundle', str(a.bundle), '--sha256', a.sha256, '--sample', label])
    if a.phase in ('boundary', 'finish'):
        loader = importlib.util.spec_from_file_location('observer', a.bundle/'observer.py')
        observer = importlib.util.module_from_spec(loader); loader.loader.exec_module(observer)
        spec = observer.check(a.bundle, a.sha256)
        require(socket.gethostname() == spec['workstation_hostname'], 'wrong boundary workstation')
        boundary_record(observer, a.bundle, spec, a.output, a.sha256)
        if a.phase == 'finish':
            start = json.loads(a.start.read_text())
            require(start['manifest_sha256'] == a.sha256, 'wrong observation start')
            result = json.loads((a.output/'boundary.json').read_text())
            validate_boundary(result, a.sha256, start['epoch']+observer.DURATION, finish=True)
            observer.write_new(a.output/'finish-check.json', {'timing_pass': True,
                               'start_sha256': observer.digest(a.start.read_bytes()),
                               'phase3_accepted': False, 'webmin_confirmation_required': True})
        return
    require(os.geteuid() == 0, 'root required')
    observer, spec = load(a.bundle, a.sha256)
    root = a.bundle.parent
    role = 'node' if a.phase in ('node-root', 'authorize', 'revoke') else (a.role or 'master')
    require(socket.gethostname() == spec[role]['hostname'], 'wrong host')
    if a.phase == 'admit':
        require(time.time() < spec['not_after_epoch'], 'approval expired')
        require(not (root/'admission.json').exists(), 'admission already consumed')
        now = time.time()
        observer.write_new(root/'admission.json', {'epoch': now, 'deadline': now+180000,
                           'manifest_sha256': a.sha256, 'role': role,
                           'boot': Path('/proc/sys/kernel/random/boot_id').read_text().strip()})
        return
    if a.phase in ('revoke', 'retire-key'):
        if a.phase == 'revoke': authorize(root, spec, a.sha256, observer, remove=True)
        else:
            identity = Path(spec['identity_file'])
            if identity.exists(): trusted(identity); identity.unlink()
        return
    admission(root, a.sha256, role, time.time())
    if a.phase == 'node-root':
        rich = sample(a.sample)
        requests = root/'requests'
        observer.write_new(requests/(a.sample+'.json'), {'epoch': time.time(), 'label': a.sample})
        sources = {n: (a.bundle/n).read_text() for n in ('helper.py', 'passive.py', 'measure.py', 'checks.py', 'munin.py')}
        observer.remote('node', rich, spec, sources, time.time()-600)
    elif a.phase == 'key':
        identity = Path(spec['identity_file'])
        require(identity == root/'identity' and not identity.exists(), 'fresh dedicated key required')
        observer.write_new(root/'key-generation.json', {'epoch': time.time()})
        subprocess.run(['/usr/bin/ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-C', spec['operation'],
                        '-f', str(identity)], check=True, timeout=10, stdin=subprocess.DEVNULL)
        os.chmod(identity, 0o600)
        result = subprocess.run(['/usr/bin/ssh-keygen', '-lf', str(identity)], check=True,
                                capture_output=True, text=True, timeout=5)
        observer.write_new(root/'key.json', {'fingerprint': result.stdout.split()[1], 'epoch': time.time()})
    elif a.phase == 'authorize':
        authorize(root, spec, a.sha256, observer)
    elif a.phase == 'run':
        import signal
        signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
        observer.write_new(root/'run-launch.json', {'epoch': time.time(), 'manifest_sha256': a.sha256})
        try:
            review_deadline = time.monotonic()+1800
            observer.execute(a.bundle, root/'results', a.sha256, 'entry', None)
            wait_for_grant(root, review_deadline)
            admission(root, a.sha256, role, time.time())
            boundary_raw = (root/'start-boundary.json').read_bytes()
            boundary = json.loads(boundary_raw)
            validate_boundary(boundary, a.sha256, time.time())
            grant = json.loads((root/'grant.json').read_text())
            require(grant.get('start_boundary_sha256') == observer.digest(boundary_raw),
                    'start grant does not bind workstation boundary')
            observer.execute(a.bundle, root/'results', a.sha256, 'observe', root/'grant.json')
        except BaseException as error:
            observer.write_new(root/'results/hosted-error.json', {'epoch': time.time(), 'error': str(error),
                                                                'type': type(error).__name__, 'replay_permitted': False})
            raise
        finally:
            identity = Path(spec['identity_file'])
            if identity.exists(): trusted(identity); identity.unlink()


if __name__ == '__main__':
    main()
