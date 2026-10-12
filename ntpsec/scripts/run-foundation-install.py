#!/usr/bin/python3
"""Verify the approved private archive, submit once, preserve original evidence."""
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tarfile
import time

FINGERPRINT = 'SHA256:yXiID8RObBoIejVpvr2KesaqIlocbSORyemD5dKrEys'
TARGET = 'ama@10.1.0.137'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def private_file(path, limit):
    for parent in path.parents:
        if parent.is_symlink():
            raise ValueError('symlink evidence ancestor')
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or info.st_mode & 0o077 or info.st_nlink != 1 or info.st_size > limit):
        raise ValueError('private regular input required')
    return path.read_bytes()


def prepare(bundle, expected):
    directory = bundle.parent
    if directory.stat().st_uid != os.getuid() or directory.stat().st_mode & 0o077:
        raise ValueError('owner-private bundle directory required')
    data = private_file(bundle, 80 * 1024 * 1024)
    if not re.fullmatch(r'[0-9a-f]{64}', expected) or digest(data) != expected:
        raise ValueError('approved bundle hash mismatch')
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:') as archive:
        members = archive.getmembers()
        names = [m.name for m in members]
        if (len(names) != len(set(names)) or len(names) > 80
                or any(not m.isfile() or m.size > 40 * 1024 * 1024
                       or not re.fullmatch(r'(?:archives/)?[a-zA-Z0-9_.+%~-]+', m.name) for m in members)
                or sum(m.size for m in members) > 75 * 1024 * 1024):
            raise ValueError('unsafe bundle members')
        files = {m.name: archive.extractfile(m).read() for m in members}
    manifest = json.loads(files['manifest.json'])
    if set(manifest) != set(files) - {'manifest.json'} or any(digest(files[n]) != v for n, v in manifest.items()):
        raise ValueError('bundle member hash mismatch')
    if files['launcher.py'] != Path(__file__).read_bytes():
        raise ValueError('launcher differs from sealed source')
    fields = files['known_hosts'].decode('ascii').split()
    if len(fields) != 3 or fields[:2] != ['10.1.0.137', 'ssh-ed25519']:
        raise ValueError('unexpected host key binding')
    fp = 'SHA256:' + base64.b64encode(hashlib.sha256(base64.b64decode(fields[2], validate=True)).digest()).decode().rstrip('=')
    if fp != FINGERPRINT or private_file(directory / 'known_hosts', 4096) != files['known_hosts']:
        raise ValueError('pinned host key mismatch')
    spec = json.loads(files['spec.json'])
    extra = {'spec.json', 'launcher.py', 'known_hosts', 'manifest.json', 'tests.py', 'native-protocol.txt', 'review.md'}
    if spec.get('schema') == 2:
        extra |= {'recipe.json', 'installation-assets.json', 'snapshot.json', 'resolution.json', 'provenance.json'}
        provenance = json.loads(files['provenance.json'])
        for name, field in (('recipe.json', 'recipe_sha256'), ('installation-assets.json', 'asset_manifest_sha256'),
                            ('snapshot.json', 'snapshot_sha256'), ('resolution.json', 'resolution_sha256')):
            if digest(files[name]) != provenance[field] or spec['preparation'][field] != provenance[field]:
                raise ValueError('fresh preparation evidence binding mismatch')
    else:
        extra.add('native-alcapt.py')
    if set(files) != set(spec['members']) | extra:
        raise ValueError('unexpected bundle input set')
    if any(digest(files[n]) != checksum for n, checksum in spec['members'].items()):
        raise ValueError('target input manifest mismatch')
    compile(files['worker.py'], 'sealed-foundation.py', 'exec')
    return spec, {n: files[n] for n in spec['members']}


def payload(spec, files, epoch, mode):
    if mode != 'install':
        files = {'worker.py': files['worker.py']}
    code = ('import base64,json\n'
            + 'spec=json.loads(' + repr(json.dumps(spec, sort_keys=True)) + ')\n'
            + 'files={k:base64.b64decode(v,validate=True) for k,v in json.loads('
            + repr(json.dumps({n: base64.b64encode(d).decode('ascii') for n, d in files.items()})) + ').items()}\n'
            + 'ns={"__name__":"sealed_foundation"}\n'
            + 'exec(compile(files["worker.py"],"sealed-foundation.py","exec"),ns)\n'
            + 'status=0\ntry:\n    report=ns["entry"](spec,files,' + str(epoch) + ',' + repr(mode) + ')\n'
            + 'except BaseException as exc:\n    status=2\n    report={"state":"held","error":type(exc).__name__+": "+str(exc)}\n'
            + 'try:\n    report["evidence"]=ns["evidence"]()\nexcept Exception as exc:\n    status=2\n    report["evidence_error"]=str(exc)\n'
            + 'print(json.dumps(report,sort_keys=True))\nprint("FOUNDATION_EXIT_STATUS="+str(status))\n'
            + 'raise SystemExit(status)\n')
    return code.encode()


def ssh_environment():
    agent = os.environ.get('SSH_AUTH_SOCK')
    if not agent:
        raise ValueError('existing SSH agent required before registration')
    return {'PATH': '/usr/bin:/bin', 'LC_ALL': 'C', 'SSH_AUTH_SOCK': agent}


def transport(directory):
    options = ('BatchMode=yes', 'StrictHostKeyChecking=yes', 'HostKeyAlgorithms=ssh-ed25519',
               'UpdateHostKeys=no', 'ProxyCommand=none', 'ProxyJump=none', 'ControlMaster=no',
               'ControlPath=none', 'ControlPersist=no', 'PermitLocalCommand=no',
               'ClearAllForwardings=yes', 'ForwardAgent=no', 'ForwardX11=no',
               'GlobalKnownHostsFile=/dev/null', 'ConnectTimeout=10', 'ServerAliveInterval=15',
               'ServerAliveCountMax=2', 'UserKnownHostsFile=' + str(directory / 'known_hosts'))
    return ['/usr/bin/timeout', '--signal=TERM', '--kill-after=10s', '2100s', '/usr/bin/ssh',
            '-F', '/dev/null', '-T', *[v for option in options for v in ('-o', option)],
            TARGET, 'cd / && sudo -n -k /usr/bin/python3 -I -B -']


def save(path, value):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(value, stream, sort_keys=True)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def main():
    os.umask(0o077)
    if len(sys.argv) != 4 or sys.argv[3] not in ('install', 'recover', 'readback'):
        raise ValueError('bundle, approved SHA-256, fixed operation required')
    bundle, checksum, mode = Path(sys.argv[1]).absolute(), sys.argv[2], sys.argv[3]
    spec, files = prepare(bundle, checksum)
    epoch = int(time.time())
    if not spec['prepared_epoch'] - 300 <= epoch < spec['expires_epoch']:
        raise ValueError('bundle approval window expired')
    environment = ssh_environment()
    data = payload(spec, files, epoch, mode)
    directory = bundle.parent
    argv = transport(directory)
    state = {'mode': mode, 'bundle_sha256': checksum, 'payload_sha256': digest(data),
             'argv': argv, 'registered_epoch': epoch, 'state': 'registered_before_submission'}
    save(directory / (mode + '-registration.json'), state)
    # Failure/timeout never authorizes resubmission. Recover/readback use distinct claims.
    with (directory / (mode + '.stdout')).open('xb') as out, (directory / (mode + '.stderr')).open('xb') as err:
        try:
            proc = subprocess.run(argv, input=data, stdout=out, stderr=err, env=environment,
                                  cwd='/', timeout=2130, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            state.update(state='transport_unresolved_readback_required',
                         error=type(exc).__name__ + ': ' + str(exc), finished_epoch=int(time.time()))
            save(directory / (mode + '-result.json'), state)
            raise
        finally:
            for stream in (out, err):
                stream.flush()
                os.fsync(stream.fileno())
    state.update(state='transport_terminal', transport_exit_status=proc.returncode,
                 finished_epoch=int(time.time()))
    save(directory / (mode + '-transport.json'), state)
    raw = private_file(directory / (mode + '.stdout'), 64 * 1024 * 1024)
    lines = raw.decode().splitlines()
    if len(lines) == 2 and lines[-1] in ('FOUNDATION_EXIT_STATUS=0', 'FOUNDATION_EXIT_STATUS=2'):
        status, report = int(lines[-1][-1]), json.loads(lines[0])
        state.update(worker_status=status, report=report)
    else:
        status = 2
        state.update(state='terminal_readback_required')
    save(directory / (mode + '-result.json'), state)
    print(json.dumps({'transport': proc.returncode, 'worker': status,
                      'state': state['state'], 'evidence': str(directory / (mode + '-result.json'))}))
    return 0 if status == proc.returncode == 0 else 2


if __name__ == '__main__':
    raise SystemExit(main())
