#!/usr/bin/python3
"""Offline sealing and one-shot transport for native first installation."""
import argparse
import base64
from datetime import datetime, timezone
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


def module(name):
    definition = importlib.util.spec_from_file_location('source_install_' + name.replace('-', '_'), ROOT / 'scripts' / name)
    result = importlib.util.module_from_spec(definition)
    definition.loader.exec_module(result)
    return result


c = module('run-foundation-preflight.py')
INPUTS = {'foundation-install.py', 'preflight-stage.py', 'stage.py', 'clockmaker.py',
          'inspect-source-destinations.py', 'release.json', 'build-spec.json', 'build-acceptance.json',
          'inspection.json', 'inspection-spec.json', 'inspection-acceptance.json', 'installation-state.json'}
EXTRAS = {'launcher.py', 'known_hosts', 'tests.py', 'review.md', 'spec.json', 'manifest.json', 'installation-assets.json', 'recipe.json', 'transport-controller.py'}


def bindings(files):
    inspector = module('inspect-source-destinations.py')
    release, build = inspector.accepted_inputs(files)
    report, previous_spec, receipt, state = (json.loads(files[n]) for n in
        ('inspection.json', 'inspection-spec.json', 'inspection-acceptance.json', 'installation-state.json'))
    inspector.validate(report, previous_spec, release, build)
    if (receipt['state'] != 'source_destinations_accepted'
            or receipt['inspection_sha256'] != c.sha(files['inspection.json'])
            or receipt['installation_state_sha256'] != c.sha(files['installation-state.json'])
            or receipt['release_sha256'] != c.sha(files['release.json'])
            or receipt['collision_count'] != 0 or receipt['destination_count'] != len(release['files'])
            or receipt['live_installed'] is not False or receipt['services_activated'] is not False
            or state != report['installation_state'] or any(v is not None for v in state['files'].values())
            or report['collisions'] or report['observation']['active_daemons']
            or release['sources'] != json.loads(files['recipe.json'])['sources']
            or previous_spec['operation'] != 'source-destinations'
            or not re.fullmatch(r'\.ntp-source-build-[a-z0-9-]+', build['stage_name'])):
        raise ValueError('accepted collision-free first-install evidence required')
    return release, build, report, previous_spec


def prepare(bundle, checksum):
    raw = c.private_file(bundle)
    if c.sha(raw) != checksum:
        raise ValueError('approved installation bundle hash mismatch')
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:') as archive:
        members = archive.getmembers()
        if (len(members) != len(INPUTS | EXTRAS) or {m.name for m in members} != INPUTS | EXTRAS
                or any(not m.isfile() or m.size > 2 * 1024**2 for m in members)):
            raise ValueError('unexpected installation archive membership')
        files = {m.name: archive.extractfile(m).read() for m in members}
    manifest = json.loads(files['manifest.json'])
    if set(manifest) != set(files) - {'manifest.json'} or any(c.sha(files[n]) != h for n, h in manifest.items()):
        raise ValueError('installation member hash drift')
    if files['launcher.py'] != Path(__file__).read_bytes() or files['transport-controller.py'] != (ROOT / 'scripts/run-foundation-preflight.py').read_bytes():
        raise ValueError('installation launcher drift')
    spec = json.loads(files['spec.json'])
    c.validate_spec(spec)
    if (spec['asset_manifest_sha256'] != c.sha(files['installation-assets.json'])
            or spec['recipe_sha256'] != c.sha(files['recipe.json'])
            or spec['operation'] != 'source-installation' or set(spec['members']) != INPUTS
            or any(c.sha(files[n]) != h for n, h in spec['members'].items())
            or c.host_key(files['known_hosts'], spec['ssh']['host']) != spec['ssh']['fingerprint']
            or c.private_file(bundle.parent / 'known_hosts', 4096) != files['known_hosts']
            or spec['source_stage'] != '/home/ama/' + json.loads(files['build-spec.json'])['stage_name'] + '/candidate/stage'):
        raise ValueError('installation input/target binding mismatch')
    if bundle.parent.stat().st_uid != os.getuid() or bundle.parent.stat().st_mode & 0o077:
        raise ValueError('private controller directory required')
    for mode in ('collect', 'readback', 'rollback', 'cleanup'):
        compile(c.payload(spec, files, spec['prepared_epoch'], mode), 'sealed-native-install-payload', 'exec')
    return spec, files


def seal(args):
    epoch = int(time.time())
    files = {}
    for member, name in (('foundation-install.py', 'foundation-install.py'),
                         ('preflight-stage.py', 'foundation-preflight-stage.py'),
                         ('stage.py', 'source-install-stage.py'), ('clockmaker.py', 'clockmaker.py'),
                         ('inspect-source-destinations.py', 'inspect-source-destinations.py')):
        files[member] = (ROOT / 'scripts' / name).read_bytes()
    for name in INPUTS - set(files):
        path = args.inputs / name
        files[name] = c.private_file(path)
        if c.sha(files[name]) != args.input_hashes[name]:
            raise ValueError('accepted installation input hash mismatch: ' + name)
    files.update({'launcher.py': Path(__file__).read_bytes(), 'known_hosts': c.private_file(args.known_hosts, 4096),
        'tests.py': (ROOT / 'tests/test_source_install.py').read_bytes(),
        'recipe.json': (ROOT / 'configs/source-build-recipe.json').read_bytes(),
        'transport-controller.py': (ROOT / 'scripts/run-foundation-preflight.py').read_bytes(),
        'installation-assets.json': (ROOT / 'configs/installation-assets.json').read_bytes()})
    release, build, report, previous = bindings(files)
    module('clockmaker.py').read_release(args.inputs / 'release.json', c.sha(files['release.json']))
    expires = min(epoch + 86400, report['collected_epoch'] + 86400)
    spec = {'schema': 1, 'operation': 'source-installation', 'operation_id': args.operation_id,
        'stage': '/var/lib/ntp-preflight-' + args.operation_id, 'hostname': previous['hostname'],
        'kernel': previous['kernel'], 'ssh': previous['ssh'], 'prepared_epoch': epoch, 'expires_epoch': expires,
        'asset_manifest_sha256': c.sha(files['installation-assets.json']),
        'recipe_sha256': c.sha(files['recipe.json']),
        'source_stage': '/home/ama/' + build['stage_name'] + '/candidate/stage',
        'members': {n: c.sha(files[n]) for n in sorted(INPUTS)}}
    c.validate_spec(spec)
    if c.host_key(files['known_hosts'], spec['ssh']['host']) != spec['ssh']['fingerprint']:
        raise ValueError('accepted inspection host-key drift')
    files['spec.json'] = c.encoded(spec)
    files['review.md'] = (f'# Native GPSD/NTPsec first-install review\n\n'
        f'Target: {spec["hostname"]}, ama UID 1000, {spec["ssh"]["host"]}; kernel {spec["kernel"]}.\n'
        f'Pinned ED25519: {spec["ssh"]["fingerprint"]}.\n'
        f'Operation: {args.operation_id}.\n'
        f'Collection expires: {datetime.fromtimestamp(expires, timezone.utc).isoformat()}.\n'
        f'Release SHA-256: {c.sha(files["release.json"])}.\n'
        f'Accepted pre-state SHA-256: {c.sha(files["installation-state.json"])}.\n\n'
        f'One privileged installation in exclusive root-owned 0700 staging `{spec["stage"]}`.\n'
        f'Read accepted native payload from `{spec["source_stage"]}` without executing it.\n'
        'Walk source ancestors using no-follow directory descriptors; bound reads to 64 MiB/file\n'
        'and 512 MiB total. Copy hash-verified bytes/approved links into protected root staging.\n'
        'Root imports only sealed root-owned inputs with isolated Python -I -B through existing sudo.\n\n'
        f'Install exactly {len(release["files"])} accepted file/link entries under /usr/local with\n'
        'root:root ownership and manifest file modes. New parent directories are root:root 0755.\n'
        'Recheck accepted absent destination state, parent metadata, packages, boot, Python and\n'
        'safe service/process observations before effects. Require stopped ntpd/GPSD and no\n'
        'conflicting APT application packages. Never stop services automatically.\n'
        'Call the accepted clockmaker native install helper against protected verified payload.\n'
        'No builds, refresh/install of packages, ldconfig/cache change, pip, runtime configuration,\n'
        'accounts, service activation, sudoers change or reboot. Library/Python runtime discovery\n'
        'and activation remain separate reviewed stages. Result is copied_not_activated.\n\n'
        'Before mutation retain accepted baseline/parent metadata and directory identities; native\n'
        'journal/backups survive every failure. All destinations were absent, so prior-file backup\n'
        'set is empty. Existing directories and all prior executed/source evidence are preserved.\n'
        'Verify every installed hash/link, owner/mode and exact target continuity after copying.\n'
        'Terminal readback rechecks installed files and target continuity before retaining the\n'
        'hash-verified native receipt/baseline/directory records privately.\n'
        'Controller acceptance requires complete exact manifest coverage and bound receipt.\n\n'
        'Conditional recovery applies only to a held installation with complete baseline records.\n'
        'Before any removal verify every current file is absent or exactly the accepted installed\n'
        'artifact with root ownership, and every parent identity matches existing/created records.\n'
        'Restore absent file state by removing only proved accepted files; remove only proved\n'
        'new empty directories in reverse order. Verify canonical baseline and target continuity.\n'
        'Missing records, unknown ownership/content, interrupted directory journaling or state drift\n'
        'hold recovery for a new review. Recovery registers exclusively and cannot be replayed.\n\n'
        'One conditional terminal readback; never resubmit installation to recover output.\n'
        'Cleanup requires retained terminal hash and completed installation or verified recovery.\n'
        'Remove only verified temporary payload, preserving executed code, journal, backups and all\n'
        'receipts on target and controller. Unsafe/unexpected payload files hold cleanup.\n'
        'A lost transport with no terminal receipt requires separately reviewed state inspection.\n'
        'Readback/recovery/cleanup remain available after installation expiry.\n\n'
        'Strict pinned SSH; no forwarding/proxy/multiplexing/local command; 420s transport bound.\n'
        'Use `run-source-install.py execute --bundle /absolute/source-install.tar` with\n'
        '`--sha256 APPROVED_SHA256 --mode collect`, then the same bundle/hash for `readback`,\n'
        'conditional `rollback` and `cleanup`. Separate hash-bound execution approval required.\n').encode()
    files['manifest.json'] = c.encoded({n: c.sha(v) for n, v in sorted(files.items())})
    os.umask(0o077); args.output.mkdir(mode=0o700)
    for name in ('known_hosts', 'review.md', 'spec.json'):
        (args.output / name).write_bytes(files[name])
    bundle = args.output / 'source-install.tar'
    with tarfile.open(bundle, 'w', format=tarfile.USTAR_FORMAT) as archive:
        for name, data in sorted(files.items()):
            member = tarfile.TarInfo(name); member.mode = 0o600; member.size = len(data); member.mtime = epoch
            archive.addfile(member, io.BytesIO(data))
    result = {'bundle': str(bundle), 'sha256': c.sha(bundle.read_bytes()), 'target': spec['hostname'],
              'expires_epoch': expires, 'target_contact': False, 'execution_authorized': False}
    prepare(bundle, result['sha256'])
    (args.output / 'sealing.json').write_bytes(c.encoded(result))
    return result


def validate_acceptance(report, files, spec):
    if (report['state'] != 'installation_completed' or report['spec_sha256'] != c.sha(files['spec.json'])
            or report['native_state'] != 'copied_not_activated' or report['continuity_unchanged'] is not True
            or report['services_activated'] is not False or report['library_cache_changed'] is not False):
        raise ValueError('complete bound native installation acceptance required')
    evidence = {}
    for name, record in report['evidence'].items():
        raw = base64.b64decode(record['base64'], validate=True)
        if c.sha(raw) != record['sha256']:
            raise ValueError('installation evidence hash mismatch')
        evidence[name] = json.loads(raw)
    receipt = evidence['journal/receipt.json']; release = json.loads(files['release.json'])
    state = json.loads(files['installation-state.json']); before = evidence['before.json']
    if (receipt['state'] != 'copied_not_activated' or receipt['release_sha256'] != c.sha(files['release.json'])
            or receipt['before'] != state or before['state'] != state
            or receipt['after']['hostname'] != spec['hostname']
            or before['parents'] != json.loads(files['inspection.json'])['parents']
            or set(receipt['installed']) != set(release['files'])
            or len(receipt['installed']) != len(release['files']) or receipt['removed']
            or set(receipt['after']['files']) != set(release['files'])
            or before['observation'] != json.loads(files['inspection.json'])['observation']):
        raise ValueError('native journal/pre-state coverage mismatch')
    for name, record in receipt['after']['files'].items():
        if (record is None or record['uid'] != 0 or record['gid'] != 0
                or any(record.get(k) != v for k, v in release['files'][name].items())):
            raise ValueError('native installed manifest mismatch')
    expected_dirs = {n for n, record in before['parents'].items() if record is None}
    created = evidence['created-directories.json']
    if set(created) != expected_dirs or any(record.get('type') != 'directory'
            or record.get('uid') != 0 or record.get('gid') != 0 or record.get('mode') != 0o755
            or type(record.get('device')) is not int or type(record.get('inode')) is not int
            for record in created.values()):
        raise ValueError('complete explicit created-directory metadata required')
    if report['installed_files'] != len(release['files']):
        raise ValueError('native installed count mismatch')
    return evidence


def execute(args):
    bundle = args.bundle.absolute(); directory = bundle.parent
    spec, files = prepare(bundle, args.sha256)
    epoch = int(time.time()); terminal_sha = None
    if args.mode == 'collect' and not spec['prepared_epoch'] - 300 <= epoch < spec['expires_epoch']:
        raise ValueError('installation window expired')
    if args.mode in ('rollback', 'cleanup'):
        retained = json.loads(c.private_file(directory / 'readback-result.json'))
        if (retained['bundle_sha256'] != args.sha256
                or retained['transport_exit_status'] != retained['worker_status']
                or retained['report']['state'] not in ('installation_completed', 'installation_held')
                or args.mode == 'rollback' and retained['report']['state'] != 'installation_held'):
            raise ValueError('bound terminal readback required before conditional recovery/cleanup')
        terminal_sha = retained['report']['terminal_sha256']
    agent = os.environ.get('SSH_AUTH_SOCK')
    if not agent:
        raise ValueError('existing SSH agent required')
    argv = c.transport(directory, spec['ssh']['host'], spec['operation'])
    data = c.payload(spec, files, epoch, args.mode, terminal_sha)
    c.write_new(directory / (args.mode + '-execution.json'), {'state': 'registered_before_submission',
        'bundle_sha256': args.sha256, 'argv': argv, 'payload_sha256': c.sha(data), 'controller_epoch': epoch})
    with (directory / (args.mode + '.stdout')).open('xb') as stdout, (directory / (args.mode + '.stderr')).open('xb') as stderr:
        result = subprocess.run(argv, input=data, stdout=stdout, stderr=stderr, check=False,
            env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C', 'SSH_AUTH_SOCK': agent})
    c.write_new(directory / (args.mode + '-transport.json'), {'exit_status': result.returncode})
    raw = c.private_file(directory / (args.mode + '.stdout'), 16 * 1024**2)
    match = re.fullmatch(rb'(.*)\nPREFLIGHT_EXIT_STATUS=([02])\n', raw, re.S)
    if not match:
        raise ValueError('missing terminal marker; retain original logs, never resubmit')
    report = json.loads(match[1]); status = int(match[2])
    record = {'bundle_sha256': args.sha256, 'report': report, 'worker_status': status,
              'transport_exit_status': result.returncode, 'stdout_sha256': c.sha(raw),
              'stderr_sha256': c.sha(c.private_file(directory / (args.mode + '.stderr')))}
    c.write_new(directory / (args.mode + '-result.json'), record)
    if result.returncode != status:
        raise ValueError('installation transport/worker mismatch')
    if args.mode == 'readback' and report.get('state') == 'installation_completed' and status == 0:
        evidence = validate_acceptance(report, files, spec)
        c.write_new(directory / 'acceptance.json', {'state': 'native_installation_accepted',
            'bundle_sha256': args.sha256, 'release_sha256': c.sha(files['release.json']),
            'installed_files': report['installed_files'], 'services_activated': False, 'library_cache_changed': False,
            'terminal_sha256': report['terminal_sha256'], 'evidence': evidence})
    return {'mode': args.mode, 'state': report.get('state'), 'worker_status': status}


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__); sub = parser.add_subparsers(dest='action', required=True)
    sealing = sub.add_parser('seal')
    sealing.add_argument('--inputs', type=Path, required=True)
    sealing.add_argument('--input-hashes', type=Path, required=True)
    sealing.add_argument('--known-hosts', type=Path, required=True)
    sealing.add_argument('--operation-id', required=True); sealing.add_argument('--output', type=Path, required=True)
    running = sub.add_parser('execute'); running.add_argument('--bundle', type=Path, required=True)
    running.add_argument('--sha256', required=True); running.add_argument('--mode', choices=('collect','readback','rollback','cleanup'), required=True)
    args = parser.parse_args()
    if args.action == 'seal':
        args.input_hashes = json.loads(c.private_file(args.input_hashes)); result = seal(args)
    else:
        result = execute(args)
    print(json.dumps(result)); return result.get('worker_status', 0)


if __name__ == '__main__':
    raise SystemExit(main())
