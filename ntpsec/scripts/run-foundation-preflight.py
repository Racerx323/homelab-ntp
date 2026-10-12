#!/usr/bin/python3
"""Seal or submit a fresh read-only foundation snapshot, readback and cleanup."""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile
import time

ROOT = Path(__file__).resolve().parents[1]
INPUTS = {'capture-foundation-snapshot.py', 'foundation-install.py', 'inspect-trixie.py',
          'hook-closure-preflight.py', 'read-debconf-answers.py', 'recipe.json'}
EXTRAS = {'spec.json', 'stage.py', 'launcher.py', 'validator.py', 'asset-validator.py',
          'known_hosts', 'review.md', 'tests.py'}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return (json.dumps(value, sort_keys=True) + '\n').encode()


def private_file(path, limit=8 * 1024 * 1024):
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('symlink execution input')
    info = path.stat()
    if (not path.is_file() or info.st_uid != os.getuid() or info.st_mode & 0o077
            or info.st_nlink != 1 or info.st_size > limit):
        raise ValueError('bounded owner-private execution input required')
    return path.read_bytes()


def host_key(data, host):
    fields = data.decode('ascii').split()
    if len(fields) != 3 or fields[:2] != [host, 'ssh-ed25519']:
        raise ValueError('one exact pinned ED25519 endpoint required')
    return 'SHA256:' + base64.b64encode(hashlib.sha256(
        base64.b64decode(fields[2], validate=True)).digest()).decode().rstrip('=')


def validate_spec(spec):
    if (spec['schema'] != 1 or spec['operation'] != 'foundation-snapshot'
            or not re.fullmatch(r'[a-z][a-z0-9-]{0,63}', spec['operation_id'])
            or spec['stage'] != '/var/lib/ntp-preflight-' + spec['operation_id']
            or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,62}', spec['hostname'])
            or not re.fullmatch(r'[A-Za-z0-9.+_-]+-v8', spec['kernel'])
            or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]*', spec['ssh']['host'])
            or not re.fullmatch(r'SHA256:[A-Za-z0-9+/]{43}', spec['ssh']['fingerprint'])
            or type(spec['prepared_epoch']) is not int or type(spec['expires_epoch']) is not int
            or not 0 < spec['expires_epoch'] - spec['prepared_epoch'] <= 86400):
        raise ValueError('invalid fresh preflight specification')


def payload(spec, files, epoch, mode, terminal_sha=None):
    return ('import base64,json,sys\n'
        'spec=json.loads(' + repr(json.dumps(spec)) + ')\n'
        'files={n:base64.b64decode(d,validate=True) for n,d in json.loads(' +
        repr(json.dumps({n: base64.b64encode(files[n]).decode() for n in INPUTS})) + ').items()}\n'
        'ns={"__name__":"sealed_preflight"}\n'
        'exec(compile(base64.b64decode(' + repr(base64.b64encode(files['stage.py']).decode()) +
        '),"sealed-preflight-stage.py","exec"),ns)\n'
        'status=0\ntry:\n'
        '    result=ns["entry"](spec,files,' + repr(epoch) + ',' + repr(mode) + ',' + repr(terminal_sha) + ')\n'
        '    if result.get("state")=="snapshot_held": status=2\n'
        'except BaseException as error:\n'
        '    status=2\n'
        '    result={"state":"held","error":type(error).__name__+": "+str(error)}\n'
        'print(json.dumps(result,sort_keys=True))\n'
        'print("PREFLIGHT_EXIT_STATUS="+str(status))\n'
        'raise SystemExit(status)\n').encode()


def prepare(bundle, checksum):
    data = private_file(bundle)
    if not re.fullmatch(r'[a-f0-9]{64}', checksum) or sha(data) != checksum:
        raise ValueError('approved bundle hash mismatch')
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:') as archive:
        members = archive.getmembers()
        names = [m.name for m in members]
        if (len(names) != len(set(names)) or set(names) != INPUTS | EXTRAS | {'manifest.json'}
                or any(not m.isfile() or m.size > 2 * 1024 * 1024 for m in members)):
            raise ValueError('unexpected bundle input set/type/size')
        files = {m.name: archive.extractfile(m).read() for m in members}
    manifest = json.loads(files['manifest.json'])
    if set(manifest) != set(files) - {'manifest.json'} or any(sha(files[n]) != h for n, h in manifest.items()):
        raise ValueError('member hash mismatch')
    if files['launcher.py'] != Path(__file__).read_bytes():
        raise ValueError('launcher differs from reviewed input')
    spec = json.loads(files['spec.json'])
    validate_spec(spec)
    if (set(spec['members']) != INPUTS or any(sha(files[n]) != h for n, h in spec['members'].items())
            or host_key(files['known_hosts'], spec['ssh']['host']) != spec['ssh']['fingerprint']
            or private_file(bundle.parent / 'known_hosts', 4096) != files['known_hosts']):
        raise ValueError('target input/key binding mismatch')
    if bundle.parent.stat().st_uid != os.getuid() or bundle.parent.stat().st_mode & 0o077:
        raise ValueError('owner-private evidence directory required')
    for mode in ('collect', 'readback', 'cleanup'):
        compile(payload(spec, files, spec['prepared_epoch'], mode), 'sealed-preflight-payload', 'exec')
    return spec, files


def seal(args):
    prepared = int(time.time())
    files = {n: (ROOT / 'scripts' / n).read_bytes() for n in INPUTS - {'recipe.json'}}
    files.update({'recipe.json': (ROOT / 'configs/foundation-recipe.json').read_bytes(),
        'stage.py': (ROOT / 'scripts/foundation-preflight-stage.py').read_bytes(),
        'launcher.py': Path(__file__).read_bytes(),
        'validator.py': (ROOT / 'scripts/prepare-foundation.py').read_bytes(),
        'asset-validator.py': (ROOT / 'scripts/fetch-installation-assets.py').read_bytes(),
        'tests.py': (ROOT / 'tests/test_foundation_preflight.py').read_bytes(),
        'known_hosts': private_file(args.known_hosts, 4096)})
    spec = {'schema': 1, 'operation': 'foundation-snapshot', 'operation_id': args.operation_id,
        'stage': '/var/lib/ntp-preflight-' + args.operation_id, 'hostname': args.hostname,
        'kernel': args.kernel, 'ssh': {'host': args.ssh_host, 'fingerprint': args.fingerprint},
        'prepared_epoch': prepared, 'expires_epoch': prepared + 86400,
        'members': {n: sha(files[n]) for n in sorted(INPUTS)}}
    validate_spec(spec)
    if host_key(files['known_hosts'], args.ssh_host) != args.fingerprint:
        raise ValueError('console-confirmed key mismatch')
    files['spec.json'] = encoded(spec)
    files['review.md'] = (f'# Fresh foundation snapshot review\n\n'
        f'Target: {args.hostname}, ama UID 1000, {args.ssh_host}; kernel {args.kernel}.\n'
        f'Pinned ED25519: {args.fingerprint}.\n\n'
        f'Collection expires: {datetime.fromtimestamp(spec["expires_epoch"], timezone.utc).isoformat()}.\n\n'
        f'One collection in exclusive root-owned 0700 staging `{spec["stage"]}`.\n'
        'Root uses isolated Python -I -B through existing passwordless sudo.\n'
        'Stage inputs are 0600, hash-verified before privileged helper imports.\n'
        'Only persistent target writes are this staging directory and its records.\n'
        'No package refresh/install, service/update/policy change, sudoers installation or reboot.\n\n'
        'Collector allowlist: dpkg inventory/audit/architecture and installed-file lists,\n'
        'id, pgrep ntpd/gpsd, safe systemctl show properties, ip address/routes.\n'
        'Read protected sources, keyrings, hooks, module/configuration hashes, boot/network/update state;\n'
        'read only five non-secret answers from the normal Debconf database.\n'
        'Never read passwords.dat. Bind recipe and observed host key; reject state drift.\n\n'
        'Acceptance: terminal receipt and snapshot hashes, transport/worker status agree;\n'
        'full checked-in snapshot validator passes. A held result is not accepted.\n'
        'Conditional readback retrieves the same terminal records without collecting again.\n'
        'Cleanup requires retained terminal readback; verifies all inputs and files first,\n'
        'then removes only this stage. Busy locks, unexpected entries, drift or incomplete\n'
        'staging hold cleanup. Preserve those states for separately reviewed recovery; never replay.\n'
        'Lost transport: retain original controller logs, attempt bound readback once;\n'
        'no recollection. Missing terminal receipt requires separate recovery review.\n\n'
        'Strict SSH host keys, no forwarding/multiplexing/proxy/local command; timeout 420s.\n'
        'Controller retains exclusive per-action registrations, complete stdout/stderr and result hashes.\n'
        'Run the repository launcher with execute --bundle foundation-preflight.tar --sha256\n'
        '<approved archive SHA256> --mode collect, then the same bound command with\n'
        '--mode readback and conditional --mode cleanup. Always use the absolute bundle path.\n'
        'Collection expires after 24 hours; bound readback/cleanup remain available after expiry.\n'
        'Metadata resolution is a subsequent bundle bound to the accepted snapshot hash.\n').encode()
    files['manifest.json'] = encoded({n: sha(d) for n, d in sorted(files.items())})
    os.umask(0o077)
    args.output.mkdir(mode=0o700)
    for n in ('known_hosts', 'review.md', 'spec.json'):
        (args.output / n).write_bytes(files[n])
    bundle = args.output / 'foundation-preflight.tar'
    with tarfile.open(bundle, 'w', format=tarfile.USTAR_FORMAT) as archive:
        for n, d in sorted(files.items()):
            member = tarfile.TarInfo(n)
            member.size, member.mode, member.mtime = len(d), 0o600, prepared
            archive.addfile(member, io.BytesIO(d))
    checksum = sha(bundle.read_bytes())
    prepare(bundle, checksum)
    result = {'bundle': str(bundle), 'sha256': checksum, 'expires_epoch': spec['expires_epoch'],
              'target_contact': False}
    (args.output / 'sealing.json').write_bytes(encoded(result))
    return result


def transport(directory, host):
    options = ['BatchMode=yes', 'StrictHostKeyChecking=yes', 'HostKeyAlgorithms=ssh-ed25519',
        'UpdateHostKeys=no', 'ProxyCommand=none', 'ProxyJump=none', 'ControlMaster=no',
        'ControlPath=none', 'ControlPersist=no', 'PermitLocalCommand=no', 'ClearAllForwardings=yes',
        'ForwardAgent=no', 'ForwardX11=no', 'GlobalKnownHostsFile=/dev/null',
        'UserKnownHostsFile=' + str(directory / 'known_hosts'), 'ConnectTimeout=15',
        'ServerAliveInterval=15', 'ServerAliveCountMax=3']
    return ['timeout', '--signal=TERM', '--kill-after=10s', '420s', 'ssh', '-F', '/dev/null', '-T',
            *[v for option in options for v in ('-o', option)], 'ama@' + host,
            'cd / && sudo -n /usr/bin/python3 -I -B -']


def write_new(path, value):
    with path.open('xb') as stream:
        stream.write(encoded(value))
        stream.flush()
        os.fsync(stream.fileno())


def execute(args):
    bundle = args.bundle.absolute()
    spec, files = prepare(bundle, args.sha256)
    epoch = int(time.time())
    mode, directory = args.mode, bundle.parent
    if mode == 'collect' and not spec['prepared_epoch'] - 300 <= epoch < spec['expires_epoch']:
        raise ValueError('collection window expired; seal a new bundle')
    terminal_sha = None
    if mode == 'cleanup':
        retained = json.loads(private_file(directory / 'readback-result.json'))
        if (retained['bundle_sha256'] != args.sha256 or retained['transport_exit_status'] != retained['worker_status']
                or retained['report']['state'] not in ('snapshot_completed', 'snapshot_held')):
            raise ValueError('bound terminal readback required before cleanup')
        terminal_sha = retained['report']['terminal_sha256']
    agent = os.environ.get('SSH_AUTH_SOCK')
    if not agent:
        raise ValueError('existing SSH agent required before registration')
    argv = transport(directory, spec['ssh']['host'])
    data = payload(spec, files, epoch, mode, terminal_sha)
    write_new(directory / (mode + '-execution.json'), {'state': 'registered_before_submission',
        'bundle_sha256': args.sha256, 'controller_epoch': epoch, 'argv': argv, 'payload_sha256': sha(data)})
    with (directory / (mode + '.stdout')).open('xb') as stdout, (directory / (mode + '.stderr')).open('xb') as stderr:
        result = subprocess.run(argv, input=data, stdout=stdout, stderr=stderr, check=False,
            env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C', 'SSH_AUTH_SOCK': agent})
    write_new(directory / (mode + '-transport.json'), {'exit_status': result.returncode, 'finished_epoch': int(time.time())})
    raw = private_file(directory / (mode + '.stdout'), 16 * 1024 * 1024)
    match = re.fullmatch(rb'(.*)\nPREFLIGHT_EXIT_STATUS=([02])\n', raw, re.S)
    if not match:
        raise ValueError('missing terminal marker; retain original logs and use conditional readback')
    report, status = json.loads(match[1]), int(match[2])
    record = {'bundle_sha256': args.sha256, 'transport_exit_status': result.returncode,
        'worker_status': status, 'report': report, 'stdout_sha256': sha(raw),
        'stderr_sha256': sha(private_file(directory / (mode + '.stderr')))}
    write_new(directory / (mode + '-result.json'), record)
    if result.returncode != status:
        raise ValueError('transport/worker status mismatch; preserve and read back')
    if mode == 'readback' and report.get('state') == 'snapshot_completed' and status == 0:
        snapshot = base64.b64decode(report['snapshot_base64'], validate=True)
        if sha(snapshot) != report['snapshot_sha256'] or report['spec_sha256'] != sha(files['spec.json']):
            raise ValueError('retained snapshot/spec hash mismatch')
        for n, member in (('prepare-foundation.py', 'validator.py'), ('fetch-installation-assets.py', 'asset-validator.py'),
                          ('foundation-install.py', 'foundation-install.py'),
                          ('read-debconf-answers.py', 'read-debconf-answers.py')):
            if (ROOT / 'scripts' / n).read_bytes() != files[member]:
                raise ValueError('acceptance validator dependency drift')
        definition = importlib.util.spec_from_file_location('fresh_preflight_validator', ROOT / 'scripts/prepare-foundation.py')
        validator = importlib.util.module_from_spec(definition)
        definition.loader.exec_module(validator)
        validator.validate_snapshot(json.loads(snapshot), json.loads(files['recipe.json']), sha(files['recipe.json']), epoch)
        with (directory / 'snapshot.json').open('xb') as stream:
            stream.write(snapshot)
        write_new(directory / 'acceptance.json', {'state': 'snapshot_accepted', 'bundle_sha256': args.sha256,
                                                 'snapshot_sha256': sha(snapshot)})
    return {'mode': mode, 'state': report.get('state'), 'worker_status': status, 'result': str(directory / (mode + '-result.json'))}


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    sealing = sub.add_parser('seal')
    for name in ('hostname', 'kernel', 'ssh-host', 'fingerprint', 'operation-id'):
        sealing.add_argument('--' + name, required=True)
    sealing.add_argument('--known-hosts', type=Path, required=True)
    sealing.add_argument('--output', type=Path, required=True)
    running = sub.add_parser('execute')
    running.add_argument('--bundle', type=Path, required=True)
    running.add_argument('--sha256', required=True)
    running.add_argument('--mode', choices=('collect', 'readback', 'cleanup'), required=True)
    args = parser.parse_args()
    result = seal(args) if args.action == 'seal' else execute(args)
    print(json.dumps(result))
    return result.get('worker_status', 0)


if __name__ == '__main__':
    raise SystemExit(main())
