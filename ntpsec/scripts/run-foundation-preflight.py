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
RESOLUTION_INPUTS = {'resolver.py', 'resolver-spec.json', 'snapshot.json',
                     'installation-assets.json', 'resolution-policy.json'}
DESTINATION_INPUTS = {'inspect-source-destinations.py', 'clockmaker.py', 'release.json',
                      'build-spec.json', 'build-acceptance.json'}
EXTRAS = {'spec.json', 'stage.py', 'launcher.py', 'validator.py', 'asset-validator.py',
          'known_hosts', 'review.md', 'tests.py', 'installation-assets.json'}


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
    if (spec['schema'] != 1 or spec['operation'] not in ('foundation-snapshot', 'foundation-resolution', 'source-destinations')
            or not re.fullmatch(r'[a-z][a-z0-9-]{0,63}', spec['operation_id'])
            or spec['stage'] != '/var/lib/ntp-preflight-' + spec['operation_id']
            or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,62}', spec['hostname'])
            or not re.fullmatch(r'[A-Za-z0-9.+_-]+-v8', spec['kernel'])
            or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]*', spec['ssh']['host'])
            or not re.fullmatch(r'SHA256:[A-Za-z0-9+/]{43}', spec['ssh']['fingerprint'])
            or not re.fullmatch(r'[a-f0-9]{64}', spec['asset_manifest_sha256'])
            or type(spec['prepared_epoch']) is not int or type(spec['expires_epoch']) is not int
            or not 0 < spec['expires_epoch'] - spec['prepared_epoch'] <= 86400):
        raise ValueError('invalid fresh preflight specification')


def payload(spec, files, epoch, mode, terminal_sha=None):
    return ('import base64,json,sys\n'
        'spec=json.loads(' + repr(json.dumps(spec)) + ')\n'
        'files={n:base64.b64decode(d,validate=True) for n,d in json.loads(' +
        repr(json.dumps({n: base64.b64encode(files[n]).decode() for n in spec['members']})) + ').items()}\n'
        'ns={"__name__":"sealed_preflight"}\n'
        'exec(compile(base64.b64decode(' + repr(base64.b64encode(files['stage.py']).decode()) +
        '),"sealed-preflight-stage.py","exec"),ns)\n'
        'status=0\ntry:\n'
        '    result=ns["entry"](spec,files,' + repr(epoch) + ',' + repr(mode) + ',' + repr(terminal_sha) + ')\n'
        '    if result.get("state") in ("snapshot_held","resolution_held","inspection_held"): status=2\n'
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
        if (len(names) != len(set(names)) or set(names) not in (INPUTS | EXTRAS | {'manifest.json'},
                INPUTS | RESOLUTION_INPUTS | EXTRAS | {'manifest.json'},
                INPUTS | DESTINATION_INPUTS | EXTRAS | {'manifest.json'})
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
    if spec['asset_manifest_sha256'] != sha(files['installation-assets.json']):
        raise ValueError('pinned asset manifest binding mismatch')
    required = INPUTS | (RESOLUTION_INPUTS if spec['operation'] == 'foundation-resolution' else
                        DESTINATION_INPUTS if spec['operation'] == 'source-destinations' else set())
    if (set(files) != required | EXTRAS | {'manifest.json'} or set(spec['members']) != required
            or any(sha(files[n]) != h for n, h in spec['members'].items())
            or host_key(files['known_hosts'], spec['ssh']['host']) != spec['ssh']['fingerprint']
            or private_file(bundle.parent / 'known_hosts', 4096) != files['known_hosts']):
        raise ValueError('target input/key binding mismatch')
    if bundle.parent.stat().st_uid != os.getuid() or bundle.parent.stat().st_mode & 0o077:
        raise ValueError('owner-private evidence directory required')
    for mode in ('collect', 'readback', 'cleanup'):
        compile(payload(spec, files, spec['prepared_epoch'], mode), 'sealed-preflight-payload', 'exec')
    return spec, files


def validator(files):
    for name, member in (('prepare-foundation.py', 'validator.py'), ('fetch-installation-assets.py', 'asset-validator.py'),
                         ('foundation-install.py', 'foundation-install.py'), ('read-debconf-answers.py', 'read-debconf-answers.py')):
        if (ROOT / 'scripts' / name).read_bytes() != files[member]:
            raise ValueError('acceptance validator dependency drift')
    definition = importlib.util.spec_from_file_location('fresh_preflight_validator', ROOT / 'scripts/prepare-foundation.py')
    module = importlib.util.module_from_spec(definition)
    definition.loader.exec_module(module)
    return module


def resolution_spec(snapshot, snapshot_sha, recipe, manifest, policy, operation_id, checker):
    requirements, _ = checker.package_requirements(recipe, manifest)
    missing = checker.delta(requirements, snapshot['baseline'])
    pins = {r['package']: r['version'] for r in requirements}
    providers = manifest.get('root_providers', {})
    if policy['schema'] != 1 or not policy['releases'] or not policy['verify_packages']:
        raise ValueError('reviewed resolution policy required')
    inputs = {r['path']: r for r in snapshot['inputs']}
    hashes = {n: r['sha256'] for n, r in inputs.items() if not r.get('absent')}
    metadata = {n: {k: r[k] for k in ('uid', 'gid', 'mode')} for n, r in inputs.items() if not r.get('absent')}
    verified = [n if n in snapshot['baseline'] else n + ':arm64' for n in policy['verify_packages']]
    if any(snapshot['baseline'].get(n, ['', ''])[1] != 'ii ' for n in verified):
        raise ValueError('required APT/verification package not installed')
    # Use the same discovery rules with snapshot memberships, without reading the controller's /etc.
    definition = importlib.util.spec_from_file_location('snapshot_inspection', ROOT / 'scripts/inspect-trixie.py')
    inspector = importlib.util.module_from_spec(definition)
    definition.loader.exec_module(inspector)
    configs = sorted(str(p) for p in inspector.keyring_hook_files('', snapshot['directories']) if str(p).startswith('/etc/'))
    if not set(configs).issubset(inputs) or not set(inspector.PUBLIC_KEYRINGS).issubset(hashes):
        raise ValueError('snapshot lacks required source/configuration/public-key coverage')
    spec = {'hostname': snapshot['hostname'], 'kernel': snapshot['kernel'], 'caller_uid': 1000,
        'snapshot_sha256': snapshot_sha, 'input_hashes': hashes, 'input_metadata': metadata,
        'absent_inputs': [n for n, r in inputs.items() if r.get('absent')],
        'expected_config_paths': configs, 'source_files': snapshot['coverage']['source_files'],
        'foreign_architectures': snapshot['foreign_architectures'], 'verify_packages': verified,
        'expected_version_lines': [n+'\t'+'\t'.join(snapshot['baseline'][n]) for n in verified],
        'apt_version': snapshot['baseline']['apt'][0].split('-')[0], 'releases': policy['releases'],
        'groups': {'foundation': recipe['roots']}, 'root_pins': {n: pins[providers.get(n, n)] for n in recipe['roots']},
        'root_providers': providers,
        'workspace': '/var/tmp/ntp-resolution-' + operation_id}
    return spec, missing


def seal(args):
    prepared = int(time.time())
    files = {n: (ROOT / 'scripts' / n).read_bytes() for n in INPUTS - {'recipe.json'}}
    files.update({'recipe.json': (ROOT / 'configs/foundation-recipe.json').read_bytes(),
        'installation-assets.json': (ROOT / 'configs/installation-assets.json').read_bytes(),
        'stage.py': (ROOT / 'scripts/foundation-preflight-stage.py').read_bytes(),
        'launcher.py': Path(__file__).read_bytes(),
        'validator.py': (ROOT / 'scripts/prepare-foundation.py').read_bytes(),
        'asset-validator.py': (ROOT / 'scripts/fetch-installation-assets.py').read_bytes(),
        'tests.py': (ROOT / 'tests/test_foundation_preflight.py').read_bytes(),
        'known_hosts': private_file(args.known_hosts, 4096)})
    checker = validator(files)
    checker.package_requirements(json.loads(files['recipe.json']), json.loads(files['installation-assets.json']))
    resolution_mode = getattr(args, 'action', 'seal') == 'seal-resolution'
    destination_mode = getattr(args, 'action', 'seal') == 'seal-destinations'
    required = INPUTS
    expires = prepared + 86400
    if resolution_mode:
        raw = private_file(args.snapshot)
        if sha(raw) != args.snapshot_sha256:
            raise ValueError('accepted snapshot hash mismatch')
        snapshot = json.loads(raw)
        recipe = json.loads(files['recipe.json'])
        checker.validate_snapshot(snapshot, recipe, sha(files['recipe.json']), prepared)
        args.hostname, args.kernel = snapshot['hostname'], snapshot['kernel']
        args.ssh_host, args.fingerprint = snapshot['ssh']['host'], snapshot['ssh']['fingerprint']
        files.update({'snapshot.json': raw, 'resolver.py': (ROOT / 'scripts/resolve-trixie-packages.py').read_bytes(),
            'resolution-policy.json': (ROOT / 'configs/foundation-resolution-policy.json').read_bytes()})
        rspec, missing = resolution_spec(snapshot, sha(raw), recipe, json.loads(files['installation-assets.json']),
            json.loads(files['resolution-policy.json']), args.operation_id, checker)
        files['resolver-spec.json'] = encoded(rspec)
        required = INPUTS | RESOLUTION_INPUTS
        expires = min(expires, snapshot['collected_epoch'] + recipe['maximum_snapshot_age_seconds'])
    if destination_mode:
        for member, path, checksum in (
                ('release.json', args.release, args.release_sha256),
                ('build-spec.json', args.build_spec, args.build_spec_sha256),
                ('build-acceptance.json', args.build_acceptance, args.build_acceptance_sha256)):
            raw = private_file(path)
            if sha(raw) != checksum:
                raise ValueError('accepted source input hash mismatch: ' + member)
            files[member] = raw
        files['clockmaker.py'] = (ROOT / 'scripts/clockmaker.py').read_bytes()
        files['inspect-source-destinations.py'] = (ROOT / 'scripts/inspect-source-destinations.py').read_bytes()
        files['tests.py'] = (ROOT / 'tests/test_source_destinations.py').read_bytes()
        definition = importlib.util.spec_from_file_location('destination_validator', ROOT / 'scripts/inspect-source-destinations.py')
        inspector = importlib.util.module_from_spec(definition)
        definition.loader.exec_module(inspector)
        release, build = inspector.accepted_inputs(files)
        # The checked-in helper validates every manifest record without target contact.
        inspector.load(ROOT / 'scripts/clockmaker.py').read_release(args.release, sha(files['release.json']))
        inventory = {}
        for line in (ROOT / 'configs/accepted-packages.tsv').read_text().splitlines():
            name, version, status = line.split('\t')
            if name in inventory:
                raise ValueError('duplicate accepted inventory mirror record')
            inventory[name] = [version, status]
        if inventory != build['inventory']:
            raise ValueError('accepted inventory mirror mismatch')
        args.hostname, args.kernel = release['hostname'], release['kernel']
        args.ssh_host = files['known_hosts'].decode('ascii').split()[0]
        args.fingerprint = host_key(files['known_hosts'], args.ssh_host)
        required = INPUTS | DESTINATION_INPUTS
    spec = {'schema': 1, 'operation': 'foundation-snapshot', 'operation_id': args.operation_id,
        'stage': '/var/lib/ntp-preflight-' + args.operation_id, 'hostname': args.hostname,
        'kernel': args.kernel, 'ssh': {'host': args.ssh_host, 'fingerprint': args.fingerprint},
        'asset_manifest_sha256': sha(files['installation-assets.json']),
        'prepared_epoch': prepared, 'expires_epoch': expires,
        'members': {n: sha(files[n]) for n in sorted(required)}}
    if resolution_mode:
        spec['operation'] = 'foundation-resolution'
    if destination_mode:
        spec['operation'] = 'source-destinations'
    validate_spec(spec)
    if host_key(files['known_hosts'], args.ssh_host) != args.fingerprint:
        raise ValueError('console-confirmed key mismatch')
    files['spec.json'] = encoded(spec)
    files['review.md'] = (f'# Fresh foundation snapshot review\n\n'
        f'Target: {args.hostname}, ama UID 1000, {args.ssh_host}; kernel {args.kernel}.\n'
        f'Pinned ED25519: {args.fingerprint}.\n\n'
        f'Recipe SHA-256: {sha(files["recipe.json"])}.\n'
        f'Pinned asset manifest SHA-256: {spec["asset_manifest_sha256"]}.\n'
        'The pinned manifest is retained controller-side; snapshot collection does not fetch assets.\n\n'
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
    if resolution_mode:
        files['review.md'] = (f'# Snapshot-bound foundation metadata resolution review\n\n'
            f'Target: {args.hostname}, ama UID 1000, {args.ssh_host}; kernel {args.kernel}.\n'
            f'Pinned ED25519: {args.fingerprint}.\n'
            f'Snapshot SHA-256: {args.snapshot_sha256}.\n'
            f'Collection expires: {datetime.fromtimestamp(expires, timezone.utc).isoformat()}.\n\n'
            f'Exclusive root-owned code/evidence stage: `{spec["stage"]}`.\n'
            f'Disposable native APT workspace: `{rspec["workspace"]}`.\n'
            'One isolated Python -I -B execution through existing operator-managed sudo.\n'
            'No sudoers installation, live APT list/cache refresh, package installation,\n'
            'service/update/policy change, application deployment or reboot.\n\n'
            'Recheck the full accepted snapshot before and after resolution, allowing only\n'
            'the new observation timestamp and command records. Validate protected inputs,\n'
            'package inventory, boot, Debconf answers, network and automatic-update state.\n'
            'Only the five non-secret normal Debconf answers are read; never passwords.dat.\n\n'
            'Copy verified public keyrings, reviewed credential-free deb822 sources and\n'
            'installed package state into disposable APT storage. Reject source credentials,\n'
            'authentication overrides, unexpected URIs/suites/components and legacy nonempty sources.\n'
            'Use the checked-in repository policy; acquire authenticated InRelease/Packages\n'
            'with apt-get --error-on=any update, exclusively against isolated paths.\n'
            'Hooks/preferences are disabled and dpkg is /bin/false. Native commands also\n'
            'include apt-config dump, indextargets, dpkg verification/audit/queries and safe\n'
            'systemctl/ip/pgrep observations. Then simulate one combined foundation group\n'
            'using --simulate --no-remove install with exact root version pins; no install.\n'
            f'Expected missing pinned packages: {len(missing)}; exact identities are derived\n'
            'from the recipe, manifest and snapshot, never fixed historical counts.\n\n'
            'Accept only signed release/index identity/checksums, full dependency closure,\n'
            'native/Python APT agreement, exact pinned delta, intact metadata and target continuity.\n'
            'Retain signed release bytes, selected Packages records and complete query output\n'
            'in the private resolution wrapper; apply the full checked-in validator after readback.\n'
            'Process completion alone does not establish acceptance.\n\n'
            'One conditional terminal readback, without rerunning resolution; then conditional\n'
            'cleanup after local terminal retention. Verify the terminal hash and every stage\n'
            'file; delete only the exclusive disposable APT workspace after root/device/inode\n'
            'identity checks, and the exact code/evidence stage. Metadata lists are disposable;\n'
            'signed release bytes, selected records and query evidence remain on the controller.\n'
            'Busy locks, changed files, missing terminal records or workspace collisions hold\n'
            'cleanup/replay for separately reviewed recovery. Never reset or reuse the claim.\n\n'
            'Strict SSH host keys, no forwarding/proxy/multiplexing/local commands; 1320s transport bound.\n'
            'Complete exclusive controller logs and registrations precede submission. Use execute\n'
            '--bundle <absolute foundation-resolution.tar> --sha256 <approved archive SHA256>\n'
            '--mode collect, then the same bound command with readback and conditional cleanup.\n'
            'Readback/cleanup remain available after the collection expiry.\n').encode()
    if destination_mode:
        files['review.md'] = (f'# Source destination/collision inspection review\n\n'
            f'Target: {args.hostname}, ama UID 1000, {args.ssh_host}; kernel {args.kernel}.\n'
            f'Pinned ED25519: {args.fingerprint}.\n'
            f'Operation: {args.operation_id}.\n'
            f'Release SHA-256: {sha(files["release.json"])}.\n'
            f'Accepted build specification SHA-256: {sha(files["build-spec.json"])}.\n'
            f'Accepted build receipt SHA-256: {sha(files["build-acceptance.json"])}.\n'
            f'Collection expires: {datetime.fromtimestamp(expires, timezone.utc).isoformat()}.\n\n'
            f'One capture in exclusive root-owned 0700 staging `{spec["stage"]}`.\n'
            'Isolated Python -I -B through existing operator-managed sudo; stage inputs are\n'
            '0600 and hash-verified before privileged imports. Only target writes are this\n'
            'new stage and its observation records; cleanup removes only that stage.\n'
            'Preserve both accepted source workspaces and every prior executed record.\n\n'
            f'Inspect exactly {len(release["files"])} manifest destinations under /usr/local.\n'
            'Validate root-owned, non-writable, non-symlink ancestors before reading destinations.\n'
            'Record absent files, file hashes/ownership/modes, link text without following final\n'
            'links, parent identity and identical/different collisions. Hash at most 64 MiB per\n'
            'file and 512 MiB per pass; compare two passes within this single capture.\n'
            'Unsafe parents/files, special-file collisions, state drift or bounds hold acceptance.\n'
            'No earlier installed release is supplied; no obsolete-file removal scope.\n\n'
            'Read-only commands: dpkg-query inventory, dpkg --audit and systemctl show\n'
            'safe service/socket properties. Observe ntpd/gpsd PIDs/executable links in /proc;\n'
            'read OS/boot identity and stdlib Python ABI. Recheck exact accepted inventory,\n'
            'boot, Python and stable service/process state. Do not execute/import installed\n'
            'application code, collect credentials or inspect files outside manifest/identity scope.\n'
            'Foundation collectors retained in the bundle are not invoked in this mode.\n'
            'No refresh, build, install, replacement, service/configuration/update/policy change,\n'
            'sudoers installation or reboot. Observed collisions/daemons authorize no mutation.\n\n'
            'Accept transport/worker agreement, terminal/spec/report hashes, complete destination\n'
            'coverage, collision classification, protected ancestors and unchanged bound target state.\n'
            'Retain inspection.json, canonical installation-state.json and acceptance receipt privately.\n'
            'Acceptance is an observation gate; live installation requires a new reviewed bundle.\n\n'
            'One conditional terminal readback without recollection, then conditional verified cleanup.\n'
            'Cleanup requires retained terminal readback and exact terminal hash; verify all stage\n'
            'inputs/files first. Busy locks, unexpected entries, drift or missing terminal hold cleanup.\n'
            'Lost transport: preserve complete original logs and attempt bound readback once; never\n'
            'replay capture or reset the claim. Incomplete staging requires separate recovery review.\n'
            'Readback/cleanup remain available after expiry. No application rollback is needed because\n'
            'application state is unchanged; recovery is confined to retained observation staging.\n\n'
            'Strict pinned SSH, no forwarding/proxy/multiplexing/local command; timeout 420s.\n'
            'Execute the repository launcher with `execute --bundle /absolute/source-destinations.tar`\n'
            'and `--sha256 APPROVED_SHA256 --mode collect`; then the same bound command\n'
            'with --mode readback and conditional --mode cleanup. Separate execution approval required.\n').encode()
    files['manifest.json'] = encoded({n: sha(d) for n, d in sorted(files.items())})
    os.umask(0o077)
    args.output.mkdir(mode=0o700)
    for n in ('known_hosts', 'review.md', 'spec.json'):
        (args.output / n).write_bytes(files[n])
    bundle = args.output / ('source-destinations.tar' if destination_mode else
                            'foundation-resolution.tar' if resolution_mode else 'foundation-preflight.tar')
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


def transport(directory, host, operation='foundation-snapshot'):
    options = ['BatchMode=yes', 'StrictHostKeyChecking=yes', 'HostKeyAlgorithms=ssh-ed25519',
        'UpdateHostKeys=no', 'ProxyCommand=none', 'ProxyJump=none', 'ControlMaster=no',
        'ControlPath=none', 'ControlPersist=no', 'PermitLocalCommand=no', 'ClearAllForwardings=yes',
        'ForwardAgent=no', 'ForwardX11=no', 'GlobalKnownHostsFile=/dev/null',
        'UserKnownHostsFile=' + str(directory / 'known_hosts'), 'ConnectTimeout=15',
        'ServerAliveInterval=15', 'ServerAliveCountMax=3']
    seconds = '1320s' if operation == 'foundation-resolution' else '420s'
    return ['timeout', '--signal=TERM', '--kill-after=10s', seconds, 'ssh', '-F', '/dev/null', '-T',
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
                or retained['report']['state'] not in ('snapshot_completed', 'snapshot_held', 'resolution_completed', 'resolution_held',
                                                       'inspection_completed', 'inspection_held')):
            raise ValueError('bound terminal readback required before cleanup')
        terminal_sha = retained['report']['terminal_sha256']
    agent = os.environ.get('SSH_AUTH_SOCK')
    if not agent:
        raise ValueError('existing SSH agent required before registration')
    argv = transport(directory, spec['ssh']['host'], spec['operation'])
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
        validator(files).validate_snapshot(json.loads(snapshot), json.loads(files['recipe.json']), sha(files['recipe.json']), epoch)
        with (directory / 'snapshot.json').open('xb') as stream:
            stream.write(snapshot)
        write_new(directory / 'acceptance.json', {'state': 'snapshot_accepted', 'bundle_sha256': args.sha256,
                                                 'snapshot_sha256': sha(snapshot)})
    if mode == 'readback' and report.get('state') == 'resolution_completed' and status == 0:
        raw = base64.b64decode(report['resolution_base64'], validate=True)
        if sha(raw) != report['resolution_sha256'] or report['spec_sha256'] != sha(files['spec.json']):
            raise ValueError('retained resolution/spec hash mismatch')
        checker = validator(files)
        recipe, manifest, snapshot = (json.loads(files[n]) for n in ('recipe.json', 'installation-assets.json', 'snapshot.json'))
        checker.validate_snapshot(snapshot, recipe, sha(files['recipe.json']), epoch)
        requirements, _ = checker.package_requirements(recipe, manifest)
        missing = checker.delta(requirements, snapshot['baseline'])
        checker.validate_resolution(json.loads(raw), sha(files['snapshot.json']), sha(files['installation-assets.json']),
                                    snapshot, recipe, requirements, missing)
        with (directory / 'resolution.json').open('xb') as stream:
            stream.write(raw)
        write_new(directory / 'acceptance.json', {'state': 'resolution_accepted', 'bundle_sha256': args.sha256,
                                                 'resolution_sha256': sha(raw), 'snapshot_sha256': sha(files['snapshot.json'])})
    if mode == 'readback' and report.get('state') == 'inspection_completed' and status == 0:
        raw = base64.b64decode(report['inspection_base64'], validate=True)
        if sha(raw) != report['inspection_sha256'] or report['spec_sha256'] != sha(files['spec.json']):
            raise ValueError('retained inspection/spec hash mismatch')
        import types
        inspector = types.ModuleType('sealed_destination_validator')
        exec(compile(files['inspect-source-destinations.py'], 'sealed-destination-validator.py', 'exec'), inspector.__dict__)
        release, build = inspector.accepted_inputs(files)
        observed = json.loads(raw)
        inspector.validate(observed, spec, release, build)
        with (directory / 'inspection.json').open('xb') as stream:
            stream.write(raw)
        state = encoded(observed['installation_state'])
        with (directory / 'installation-state.json').open('xb') as stream:
            stream.write(state)
        write_new(directory / 'acceptance.json', {'state': 'source_destinations_accepted',
            'bundle_sha256': args.sha256, 'inspection_sha256': sha(raw),
            'installation_state_sha256': sha(state), 'release_sha256': sha(files['release.json']),
            'destination_count': len(release['files']), 'collision_count': len(observed['collisions']),
            'live_installed': False, 'services_activated': False})
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
    resolution_parser = sub.add_parser('seal-resolution')
    resolution_parser.add_argument('--snapshot', type=Path, required=True)
    resolution_parser.add_argument('--snapshot-sha256', required=True)
    resolution_parser.add_argument('--known-hosts', type=Path, required=True)
    resolution_parser.add_argument('--operation-id', required=True)
    resolution_parser.add_argument('--output', type=Path, required=True)
    destinations = sub.add_parser('seal-destinations')
    for name in ('release', 'build-spec', 'build-acceptance'):
        destinations.add_argument('--' + name, type=Path, required=True)
        destinations.add_argument('--' + name + '-sha256', required=True)
    destinations.add_argument('--known-hosts', type=Path, required=True)
    destinations.add_argument('--operation-id', required=True)
    destinations.add_argument('--output', type=Path, required=True)
    running = sub.add_parser('execute')
    running.add_argument('--bundle', type=Path, required=True)
    running.add_argument('--sha256', required=True)
    running.add_argument('--mode', choices=('collect', 'readback', 'cleanup'), required=True)
    args = parser.parse_args()
    result = execute(args) if args.action == 'execute' else seal(args)
    print(json.dumps(result))
    return result.get('worker_status', 0)


if __name__ == '__main__':
    raise SystemExit(main())
