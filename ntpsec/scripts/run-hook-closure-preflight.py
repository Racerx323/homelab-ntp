#!/usr/bin/python3
"""Verify a private approved bundle, register once, capture one SSH submission."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile
import time

FINGERPRINT = 'SHA256:yXiID8RObBoIejVpvr2KesaqIlocbSORyemD5dKrEys'
MEMBERS = {'collector.py', 'launcher.py', 'payload.py', 'spec.json', 'known_hosts',
           'review.md', 'tests.py', 'manifest.json'}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def private_file(path, limit):
    if path.is_symlink() or not path.is_file():
        raise ValueError('regular private input required')
    info = path.stat()
    if info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_nlink != 1 or info.st_size > limit:
        raise ValueError('private input protection/size mismatch')
    return path.read_bytes()


def transport(directory):
    options = ('BatchMode=yes', 'StrictHostKeyChecking=yes', 'HostKeyAlgorithms=ssh-ed25519',
               'UpdateHostKeys=no', 'ProxyCommand=none', 'ProxyJump=none', 'ControlMaster=no',
               'ControlPath=none', 'ControlPersist=no', 'PermitLocalCommand=no',
               'ClearAllForwardings=yes', 'ForwardAgent=no', 'ForwardX11=no',
               'GlobalKnownHostsFile=/dev/null', 'ConnectTimeout=10', 'ServerAliveInterval=15',
               'ServerAliveCountMax=2', 'UserKnownHostsFile=' + str(directory / 'known_hosts'))
    return ['/usr/bin/timeout', '--signal=TERM', '--kill-after=5s', '150s', '/usr/bin/ssh',
            '-F', '/dev/null', '-T', *[part for option in options for part in ('-o', option)],
            'ama@10.1.0.137', 'cd / && sudo -n -k /usr/bin/python3 -I -B -']


def render_payload(collector, spec):
    canonical = json.dumps(spec, sort_keys=True)
    return (collector + b'\nSPEC = json.loads(' + repr(canonical).encode('ascii') + b')'
               + b'\ntry:\n    report = collect(SPEC)\n    status = 2 if report["gaps"] else 0\n'
               + b'except Exception as exc:\n    report = {"state": "preflight_rejected", "error": type(exc).__name__, "installation_authorized": False}\n    status = 2\n'
               + b'print(json.dumps(report, sort_keys=True))\nprint("HOOK_CLOSURE_EXIT_STATUS=" + str(status))\nraise SystemExit(status)\n')


def prepare(bundle, expected):
    directory = bundle.parent
    for parent in (directory, *directory.parents):
        if parent.is_symlink():
            raise ValueError('symlink evidence ancestor')
    info = directory.stat()
    if info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError('private evidence directory required')
    data = private_file(bundle, 4 * 1024 * 1024)
    if digest(data) != expected:
        raise ValueError('approved bundle hash mismatch')
    with tarfile.open(bundle) as archive:
        members = archive.getmembers()
        if (len(members) != len(MEMBERS) or {m.name for m in members} != MEMBERS
                or not all(m.isfile() and m.size <= 2 * 1024 * 1024 for m in members)):
            raise ValueError('unexpected archive members')
        files = {m.name: archive.extractfile(m).read() for m in members}
    manifest = json.loads(files['manifest.json'])
    if set(manifest['members']) != MEMBERS - {'manifest.json'} or any(
            digest(files[name]) != sha for name, sha in manifest['members'].items()):
        raise ValueError('manifest mismatch')
    if files['launcher.py'] != Path(__file__).read_bytes():
        raise ValueError('launcher differs from approved bundle')
    fields = files['known_hosts'].decode('ascii').split()
    if len(fields) != 3 or fields[:2] != ['10.1.0.137', 'ssh-ed25519']:
        raise ValueError('unexpected host key binding')
    fp = 'SHA256:' + base64.b64encode(hashlib.sha256(base64.b64decode(fields[2], validate=True)).digest()).decode().rstrip('=')
    if fp != FINGERPRINT:
        raise ValueError('pinned host key mismatch')
    if private_file(directory / 'known_hosts', 4096) != files['known_hosts']:
        raise ValueError('external host key differs')
    spec = json.loads(files['spec.json'])
    wrapper = render_payload(files['collector.py'], spec)
    if files['payload.py'] != wrapper or spec['hostname'] != 'j2-svntp1':
        raise ValueError('collector rendering mismatch')
    compile(wrapper, 'approved-hook-closure.py', 'exec')
    return files['payload.py'], spec


def ssh_environment():
    agent = os.environ.get('SSH_AUTH_SOCK')
    if not agent:
        raise ValueError('existing SSH agent required before registration')
    return {'PATH': '/usr/bin:/bin', 'LC_ALL': 'C', 'SSH_AUTH_SOCK': agent}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    os.umask(0o077)
    payload, spec = prepare(args.bundle, args.sha256)
    if args.verify_only:
        print(json.dumps({'state': 'offline_verified', 'bundle_sha256': args.sha256}))
        return 0
    if not spec['not_before'] <= int(time.time()) < spec['expires_epoch']:
        raise ValueError('approved execution window expired')
    directory = args.bundle.parent
    environment = ssh_environment()
    argv = transport(directory)
    state = {'state': 'registered_before_submission', 'bundle_sha256': args.sha256,
             'argv': argv, 'payload_sha256': digest(payload), 'registered_epoch': int(time.time())}
    # Exclusive registration is permanent, including launch failures; never reset it.
    with (directory / 'execution.json').open('x') as stream:
        json.dump(state, stream); stream.flush(); os.fsync(stream.fileno())
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    with (directory / 'stdout').open('xb') as stdout, (directory / 'stderr').open('xb') as stderr:
        try:
            proc = subprocess.run(argv, input=payload, stdout=stdout, stderr=stderr, check=False,
                                  env=environment)
            state.update(state='transport_completed', transport_exit_status=proc.returncode)
        except BaseException as exc:
            state.update(state='submission_unresolved', error=type(exc).__name__)
            raise
        finally:
            state['finished_epoch'] = int(time.time())
            with (directory / 'terminal.json').open('x') as stream:
                json.dump(state, stream, indent=2); stream.flush(); os.fsync(stream.fileno())
    data = private_file(directory / 'stdout', 16 * 1024 * 1024)
    lines = data.splitlines()
    if len(lines) != 2 or lines[-1] not in (b'HOOK_CLOSURE_EXIT_STATUS=0', b'HOOK_CLOSURE_EXIT_STATUS=2'):
        raise ValueError('terminal evidence incomplete; preserve original submission')
    status = int(lines[-1][-1:])
    report = json.loads(lines[0])
    state.update(collector_exit_status=status, collector_report=report,
                 stdout_sha256=digest(data), stderr_sha256=digest(private_file(directory / 'stderr', 1024 * 1024)))
    with (directory / 'result.json').open('x') as stream:
        json.dump(state, stream, indent=2); stream.write('\n')
    print(json.dumps({'transport': proc.returncode, 'collector': status,
                      'result': str(directory / 'result.json')}))
    return 0 if proc.returncode == status and status == 0 else 2


if __name__ == '__main__':
    raise SystemExit(main())
