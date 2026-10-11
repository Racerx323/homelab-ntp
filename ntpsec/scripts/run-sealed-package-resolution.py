#!/usr/bin/python3
"""One-shot submission to the sealed root runner; stdin is only a clock observation."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile
import time


def prepare(bundle, expected, host_fingerprint='SHA256:yXiID8RObBoIejVpvr2KesaqIlocbSORyemD5dKrEys'):
    if bundle.is_symlink() or hashlib.sha256(bundle.read_bytes()).hexdigest() != expected:
        raise ValueError('approved archive hash mismatch')
    with tarfile.open(bundle) as archive:
        names = archive.getnames()
        if len(names) != len(set(names)) or not all(i.isfile() for i in archive.getmembers()):
            raise ValueError('invalid archive members')
        manifest = json.load(archive.extractfile('manifest.json'))
        if set(manifest['members']) != set(names) - {'manifest.json'}:
            raise ValueError('manifest member set mismatch')
        sealed = json.load(archive.extractfile('sealed.json'))
        if (manifest['mode'] != 'sealed_source_prerequisites_metadata_resolution'
                or sealed['attempt_dir'] != '/var/lib/ntp-metadata-elevation/attempt-v6'
                or manifest['expires_epoch'] != sealed['expires_epoch']
                or archive.extractfile('operator-paste.txt').read() != b'@CONTROLLER_EPOCH@\n'):
            raise ValueError('unexpected sealed execution contract')
        if hashlib.sha256(archive.extractfile('payload.py').read()).hexdigest() != sealed['payload_sha256']:
            raise ValueError('sealed payload hash mismatch')
        spec = json.load(archive.extractfile('spec.json'))
        for roots in spec.get('groups', {}).values():
            for name in roots:
                package = name.split(':', 1)[0]
                if package.startswith('ntpsec') or package in ('ntp', 'gpsd', 'gpsd-clients', 'python3-gps'):
                    raise ValueError('superseded APT application roots; source-build operation required')
        for name, sha in manifest['members'].items():
            if hashlib.sha256(archive.extractfile(name).read()).hexdigest() != sha:
                raise ValueError('member hash mismatch: ' + name)
        directory = bundle.parent
        if directory.is_symlink() or directory.stat().st_uid != os.getuid() or directory.stat().st_mode & 0o077:
            raise ValueError('evidence directory must be owner-private')
        for filename, member in (('metadata-resolution-epoch-template.txt', 'operator-paste.txt'),
                                 ('metadata-resolution-known-hosts', 'known_hosts')):
            path = directory / filename
            if path.is_symlink() or path.read_bytes() != archive.extractfile(member).read():
                raise ValueError('external execution input mismatch')
        fields = (directory / 'metadata-resolution-known-hosts').read_text().split()
        fingerprint = 'SHA256:' + base64.b64encode(hashlib.sha256(base64.b64decode(fields[2], validate=True)).digest()).decode().rstrip('=')
        if fields[:2] != ['10.1.0.137', 'ssh-ed25519'] or fingerprint != host_fingerprint:
            raise ValueError('console-matching host key required')
        if archive.extractfile('run-sealed-package-resolution.py').read() != Path(__file__).read_bytes():
            raise ValueError('workstation launcher differs from approved input')
    argv = manifest['transport_argv']
    if (argv[:6] != ['timeout', '--signal=TERM', '--kill-after=5s', '840s', 'ssh', '-T']
            or argv[-2] != 'ama@10.1.0.137'
            or argv[-1] != 'cd / && sudo -n /usr/bin/python3 -I -B /var/lib/ntp-metadata-elevation/attempt-v6/runner.py'):
        raise ValueError('unexpected privileged transport template')
    for option in ('BatchMode=yes', 'StrictHostKeyChecking=yes', 'HostKeyAlgorithms=ssh-ed25519',
                   'UpdateHostKeys=no', 'ProxyCommand=none', 'ProxyJump=none', 'ControlMaster=no',
                   'ControlPath=none', 'ControlPersist=no', 'PermitLocalCommand=no',
                   'ClearAllForwardings=yes', 'ForwardAgent=no', 'ForwardX11=no',
                   'GlobalKnownHostsFile=/dev/null',
                   'UserKnownHostsFile=' + str(directory / 'metadata-resolution-known-hosts')):
        if argv.count(option) != 1:
            raise ValueError('missing/duplicate transport protection: ' + option)
    return manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--sha256', required=True)
    args = parser.parse_args()
    os.umask(0o077)
    manifest = prepare(args.bundle, args.sha256)
    directory = args.bundle.parent
    epoch = int(time.time())  # Declared runtime observation, not a payload edit.
    argv = list(manifest['transport_argv'])
    if epoch >= manifest['expires_epoch']:
        raise ValueError('execution approval window expired; prepare a new bundle')
    runtime_input = (str(epoch) + '\n').encode('ascii')
    state = {'state': 'registered_before_submission', 'bundle_sha256': args.sha256,
             'controller_epoch': epoch, 'runtime_input_sha256': hashlib.sha256(runtime_input).hexdigest(),
             'transport_argv': argv, 'execution_completed': False}
    state_path = directory / 'metadata-resolution-execution.json'
    with state_path.open('x') as stream:
        json.dump(state, stream, indent=2); stream.flush(); os.fsync(stream.fileno())
    with (directory / 'metadata-resolution.stdout').open('xb') as stdout, \
            (directory / 'metadata-resolution.stderr').open('xb') as stderr:
        state['state'] = 'submitted'
        state_path.write_text(json.dumps(state, indent=2))
        try:
            result = subprocess.run(argv, input=runtime_input, stdout=stdout, stderr=stderr, check=False,
                                    env={**os.environ, 'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'})
            state.update(state='transport_completed', transport_exit_status=result.returncode,
                         execution_completed=True, finished_epoch=int(time.time()))
        finally:
            state_path.write_text(json.dumps(state, indent=2))
    if (directory / 'metadata-resolution.stdout').stat().st_size > 32 * 1024 * 1024:
        raise ValueError('terminal output exceeded review bound; original evidence retained')
    data = (directory / 'metadata-resolution.stdout').read_bytes()
    match = re.fullmatch(rb'(.*)\nMETADATA_RESOLUTION_EXIT_STATUS=([02])\n', data, re.S)
    if not match:
        raise ValueError('missing terminal JSON/marker; preserve and inspect original execution')
    report = json.loads(match[1])
    status = int(match[2])
    state.update(state='completed' if report['state'] == 'completed' and status == 0 else 'completed_with_gaps',
                 collector_exit_status=status, transport_matches_collector=result.returncode == status,
                 collector_report=report, stdout_sha256=hashlib.sha256(data).hexdigest(),
                 stderr_sha256=hashlib.sha256((directory / 'metadata-resolution.stderr').read_bytes()).hexdigest())
    with (directory / 'metadata-resolution-result.json').open('x') as stream:
        json.dump(state, stream, indent=2); stream.write('\n')
    print(json.dumps({'transport': result.returncode, 'collector': status,
                      'state': state['state'], 'result': str(directory / 'metadata-resolution-result.json')}))
    return 0 if result.returncode == status else 1


if __name__ == '__main__':
    raise SystemExit(main())
