#!/usr/bin/python3
"""Seal and control one read-only inspection of a held hardware operation."""
import argparse
import base64
import fcntl
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import socket
import stat
import subprocess
import tarfile
import time

ROOT = Path(__file__).resolve().parents[1]
BOOT = ('/boot/firmware/config.txt', '/boot/firmware/cmdline.txt')
FIELDS = 'connection.id,connection.uuid,connection.type,connection.interface-name,connection.autoconnect,ipv4.method,ipv4.addresses,ipv4.gateway,ipv6.method,ipv6.addresses,ipv6.gateway'
INPUTS = {'worker.py', 'helper.py', 'hardware-spec.json', 'hardware-recovery.json',
          'architecture.md', 'operations.md', 'history.md'}
EXTRAS = {'spec.json', 'manifest.json', 'review.md', 'known_hosts', 'tests.py', 'transport.py'}


def encoded(value):
    return (json.dumps(value, sort_keys=True)+'\n').encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def module(name):
    spec = importlib.util.spec_from_file_location('registry_'+name.replace('-', '_'), ROOT/'scripts'/name)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def registry(text):
    result = {}
    for line in text.splitlines():
        key, kind = line.split(':', 1)
        if not re.fullmatch('[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}', key) or key in result:
            raise ValueError('unique canonical profile UUID required')
        if not re.fullmatch('[a-zA-Z0-9-]+', kind):
            raise ValueError('profile type required')
        result[key] = kind
    if not 1 <= len(result) <= 64:
        raise ValueError('bounded nonempty profile registry required')
    return result


def validate(spec, files):
    old = json.loads(files['hardware-spec.json'])
    receipt = json.loads(files['hardware-recovery.json'])
    if (spec['schema'] != 1 or spec['operation'] != 'host-registry-inspection'
            or not re.fullmatch('[a-z][a-z0-9-]{0,47}', spec['operation_id'])
            or spec['stage'] != '/var/lib/ntp-inspect-'+spec['operation_id']
            or not re.fullmatch('/var/lib/ntp-host-[a-z][a-z0-9-]{0,47}', old['stage'])
            or old['operation'] != 'hardware' or spec['hostname'] != old['hostname']
            or spec['kernel'] != old['kernel'] or spec['ssh'] != old['ssh']
            or spec['old_ipv4'] != old['old_ipv4']
            or spec['endpoints'] != [old['recipe'][key].split('/')[0] for key in ('ipv4_address', 'ipv6_address')]
            or receipt['bundle_sha256'] != spec['hardware_bundle_sha256']
            or receipt['result']['phase'] != 'recovery_files_restored'
            or spec['members'].keys() != INPUTS
            or any(sha(files[n]) != v for n, v in spec['members'].items())
            or not 0 < spec['expires_epoch']-spec['prepared_epoch'] <= 86400):
        raise ValueError('held hardware/target/input binding required')
    return old


def private_root_file(h, path, limit=8*1024**2):
    data = h.read(path, limit=limit)
    if stat.S_IMODE(path.lstat().st_mode) != 0o600:
        raise ValueError('private root evidence required')
    return data


def collect(h, spec, files):
    old = validate(spec, files)
    root = Path(old['stage'])
    h.ancestors(root)
    if stat.S_IMODE(root.stat().st_mode) != 0o700:
        raise ValueError('private retained stage required')
    # Share the existing operation lock; never create or rewrite its files.
    private_root_file(h, root/'.lock')
    fd = os.open(root/'.lock', os.O_RDONLY | os.O_NOFOLLOW)
    try:
        fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        if private_root_file(h, root/'spec.json') != files['hardware-spec.json']:
            raise ValueError('retained specification drift')
        for name, digest in old['members'].items():
            if not re.fullmatch('[a-z][a-z0-9.-]+', name) or sha(private_root_file(h, root/name)) != digest:
                raise ValueError('retained member drift')
        retained = {name: private_root_file(h, root/name) for name in ('state.json', 'before.json', 'commands.jsonl')}
        if json.loads(retained['state.json']) != json.loads(files['hardware-recovery.json'])['result']:
            raise ValueError('recovered state drift; inspect scope needs review')
        boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        report = {'schema': 1, 'hostname': socket.gethostname(), 'kernel': os.uname().release,
                  'boot_id': boot, 'collected_epoch': int(time.time()),
                  'retained': {n: base64.b64encode(v).decode() for n, v in retained.items()},
                  'retained_sha256': {n: sha(v) for n, v in retained.items()}, 'boot_files': {}, 'queries': {}}
        for name in BOOT:
            data = h.read(Path(name), limit=256*1024)
            info = Path(name).lstat()
            report['boot_files'][name] = {'sha256': sha(data), 'base64': base64.b64encode(data).decode(),
                                        'mode': stat.S_IMODE(info.st_mode), 'uid': info.st_uid, 'gid': info.st_gid}
        deadline = time.monotonic()+90
        def query(label, argv):
            remaining = deadline-time.monotonic()
            if remaining <= 0:
                raise ValueError('capture deadline exceeded')
            p = subprocess.run(argv, capture_output=True, timeout=min(10, remaining), check=False,
                               env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LC_ALL': 'C', 'HOME': '/root'})
            if len(p.stdout)+len(p.stderr) > 512*1024:
                raise ValueError('query output exceeds bound')
            report['queries'][label] = {'argv': argv, 'status': p.returncode,
                                       'stdout': p.stdout.decode(), 'stderr': p.stderr.decode()}
            if len(encoded(report['queries'])) > 2*1024**2:
                raise ValueError('aggregate query output exceeds bound')
            if p.returncode:
                raise ValueError('read-only query failed: '+label)
            return p.stdout.decode()
        current = registry(query('registry', ['/usr/bin/nmcli', '-t', '-f', 'UUID,TYPE', 'connection', 'show']))
        report['expected_registry'] = dict(json.loads(retained['before.json'])['registry'])
        report['expected_registry'][old['network_candidate_uuid']] = '802-3-ethernet'
        report['current_registry'] = current
        for uuid in sorted(current):
            query('profile-'+uuid, ['/usr/bin/nmcli', '-t', '-f', FIELDS, 'connection', 'show', 'uuid', uuid])
        query('active', ['/usr/bin/nmcli', '-t', '-f', 'UUID,TYPE,DEVICE', 'connection', 'show', '--active'])
        query('addresses', ['/usr/sbin/ip', '-j', 'address', 'show'])
        for family in ('-4', '-6'):
            query('routes'+family, ['/usr/sbin/ip', '-j', family, 'route', 'show'])
        query('cmdline', ['/usr/bin/cat', '/proc/cmdline'])
        if registry(query('registry-end', ['/usr/bin/nmcli', '-t', '-f', 'UUID,TYPE', 'connection', 'show'])) != current:
            raise ValueError('registry changed during capture')
        if boot != Path('/proc/sys/kernel/random/boot_id').read_text().strip():
            raise ValueError('boot changed during capture')
        if any(private_root_file(h, root/n) != data for n, data in retained.items()):
            raise ValueError('retained state changed during capture')
        report['checks'] = {'read_only_capture': True, 'retained_state_stable': True, 'registry_stable': True}
        return report
    finally:
        os.close(fd)


def worker(spec, files, mode, terminal_sha=None):
    validate(spec, files)
    if (os.geteuid() != 0 or os.environ.get('SUDO_USER') != 'ama'
            or os.environ.get('SUDO_UID') != '1000' or os.environ.get('SUDO_GID') != '1000'
            or socket.gethostname() != spec['hostname'] or os.uname().release != spec['kernel']):
        raise ValueError('approved sudo target identity required')
    ns = {'__name__': 'registry_helper'}
    exec(compile(files['helper.py'], 'sealed-helper', 'exec'), ns)
    h = type('Helper', (), ns)
    root = Path(spec['stage'])
    os.umask(0o077)
    if mode == 'capture':
        if not spec['prepared_epoch']-300 <= time.time() < spec['expires_epoch']:
            raise ValueError('inspection expired')
        h.ancestors(root.parent)
        root.mkdir(mode=0o700)
        h.sync(root.parent)
        for name, data in {**files, 'spec.json': encoded(spec)}.items():
            h.create(root/name, data)
        h.create(root/'started.json', encoded({'phase': 'capture_started'}))
        report = collect(h, spec, files)
        terminal = encoded(report)
        if len(terminal) > 16*1024**2:
            raise ValueError('terminal exceeds bound; preserve stage')
        h.create(root/'terminal.json', terminal)
    elif mode not in ('readback', 'cleanup'):
        raise ValueError('closed inspection mode required')
    h.ancestors(root)
    expected = INPUTS | {'spec.json', 'started.json', 'terminal.json'}
    if stat.S_IMODE(root.stat().st_mode) != 0o700 or {p.name for p in root.iterdir()} != expected:
        raise ValueError('incomplete or unknown inspection entries; preserve stage')
    for name, data in {**files, 'spec.json': encoded(spec)}.items():
        if private_root_file(h, root/name) != data:
            raise ValueError('inspection input drift')
    private_root_file(h, root/'started.json')
    terminal = private_root_file(h, root/'terminal.json', limit=16*1024**2)
    result = {'phase': 'captured', 'terminal_sha256': sha(terminal), 'report': json.loads(terminal)}
    if mode == 'cleanup':
        if terminal_sha != sha(terminal):
            raise ValueError('accepted terminal hash required before cleanup')
        for name in expected:
            (root/name).unlink()
        root.rmdir()
        h.sync(root.parent)
        result = {'phase': 'cleaned', 'terminal_sha256': terminal_sha}
    return result


def prepare(bundle, checksum):
    c = module('run-foundation-preflight.py')
    raw = c.private_file(bundle, 32*1024**2)
    if sha(raw) != checksum:
        raise ValueError('approved archive hash mismatch')
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:') as archive:
        members = archive.getmembers()
        if ({m.name for m in members} != INPUTS | EXTRAS or len(members) != len(INPUTS | EXTRAS)
                or any(not m.isfile() or m.size > 2*1024**2 for m in members)):
            raise ValueError('closed bounded archive required')
        files = {m.name: archive.extractfile(m).read() for m in members}
    manifest = json.loads(files['manifest.json'])
    if (manifest != {n: sha(v) for n, v in files.items() if n != 'manifest.json'}
            or files['worker.py'] != Path(__file__).read_bytes()
            or files['transport.py'] != (ROOT/'scripts/run-foundation-preflight.py').read_bytes()
            or files['known_hosts'] != c.private_file(bundle.parent/'known_hosts', 4096)
            or bundle.parent.stat().st_uid != os.getuid() or bundle.parent.stat().st_mode & 0o077):
        raise ValueError('manifest/launcher/transport/private path drift')
    spec = json.loads(files['spec.json'])
    validate(spec, files)
    if c.host_key(files['known_hosts'], spec['old_ipv4']) != spec['ssh']['fingerprint']:
        raise ValueError('pinned host key mismatch')
    return spec, files


def seal(args):
    c = module('run-foundation-preflight.py')
    prior = module('run-host-configuration.py')
    old, previous = prior.prepare(args.hardware_dir/'host-configuration.tar', args.hardware_sha256)
    recovery = c.private_file(args.hardware_dir/'recover-result.json')
    files = {'worker.py': Path(__file__).read_bytes(), 'helper.py': (ROOT/'scripts/foundation-install.py').read_bytes(),
             'hardware-spec.json': previous['spec.json'], 'hardware-recovery.json': recovery,
             'known_hosts': previous['known_hosts'], 'tests.py': (ROOT/'tests/test_host_registry_inspection.py').read_bytes(),
             'transport.py': (ROOT/'scripts/run-foundation-preflight.py').read_bytes()}
    for label, path in (('architecture', 'docs/ntp-architecture-deployment-plan-v1.0.md'),
                        ('operations', 'docs/OPERATIONS.md'), ('history', 'HISTORY.md')):
        files[label+'.md'] = (ROOT/path).read_bytes()
    epoch = int(time.time())
    spec = {k: old[k] for k in ('hostname', 'kernel', 'ssh', 'old_ipv4')}
    spec.update(schema=1, operation='host-registry-inspection', operation_id=args.operation_id,
                stage='/var/lib/ntp-inspect-'+args.operation_id, prepared_epoch=epoch, expires_epoch=epoch+86400,
                endpoints=[old['recipe'][k].split('/')[0] for k in ('ipv4_address', 'ipv6_address')],
                hardware_bundle_sha256=args.hardware_sha256, members={n: sha(files[n]) for n in INPUTS})
    validate(spec, files)
    files['spec.json'] = encoded(spec)
    files['review.md'] = (f'# Read-only registry inspection\n\nTarget: {spec["hostname"]}. Operation: {args.operation_id}.\n'
        f'Protected root staging: `{spec["stage"]}`. Expires epoch: {spec["expires_epoch"]}.\n'
        f'Hardware bundle: `{args.hardware_sha256}`.\n\n'
        'One capture via pinned-key IPv4 SSH, with conditional terminal readback via either fixed endpoint. '
        'Bind the exact retained hardware specification, all sealed member hashes and recovered state. '
        'Hold the existing operation lock shared while reading; preserve every original operation file. '
        'Read the retained state, before-state and command journal; current boot ID, kernel command line, '
        'both boot files and ownership/modes; NetworkManager UUID/type registry, public connection settings '
        'for at most 64 profiles, active connections, addresses and routes. No secrets, raw keyfiles, '
        'receiver/device I/O, profile writes, service changes or reboot.\n\n'
        'Only the new root-owned 0700 diagnostic stage and its 0600 inputs/report are created. '
        'Accept a complete report bound to this specification, stable boot/registry/retained state and '
        'successful queries. This is diagnostic acceptance, not hardware or network acceptance. '
        'Conditional readback recovers a completed terminal without rerunning capture; interrupted captures '
        'remain preserved and require a new review. Conditional cleanup requires the accepted terminal hash '
        'and removes only the closed set of new diagnostic stage files. Preserve local evidence and the '
        'original hardware stage. Cleanup uncertainty is held; never replay a consumed mode.\n\n'
        'Use this script execute --bundle ABSOLUTE_BUNDLE --sha256 APPROVED_HASH --mode capture; '
        'conditional modes are readback and cleanup. Each is registered locally before target contact. '
        'Fixed queries have 10-second bounds and a 90-second aggregate deadline; SSH is bounded to 180 seconds. '
        'Preparation is offline. Recovery continuation requires these findings and separate approval.\n').encode()
    files['manifest.json'] = encoded({n: sha(v) for n, v in files.items()})
    os.umask(0o077)
    args.output.mkdir(mode=0o700)
    for n in ('spec.json', 'review.md', 'known_hosts'):
        (args.output/n).write_bytes(files[n])
    bundle = args.output/'registry-inspection.tar'
    with tarfile.open(bundle, 'w', format=tarfile.USTAR_FORMAT) as archive:
        for n, data in sorted(files.items()):
            info = tarfile.TarInfo(n); info.size = len(data); info.mode = 0o600; info.mtime = epoch
            archive.addfile(info, io.BytesIO(data))
    result = {'bundle': str(bundle), 'sha256': sha(bundle.read_bytes()), 'target': spec['hostname'],
              'expires_epoch': spec['expires_epoch'], 'execution_authorized': False, 'target_contact': False}
    prepare(bundle, result['sha256'])
    c.write_new(args.output/'sealing.json', result)
    return result


def payload(spec, files, mode, terminal_sha):
    return ('import base64,json,hashlib\n'
        'spec=json.loads('+repr(json.dumps(spec))+')\n'
        'files={n:base64.b64decode(v,validate=True) for n,v in json.loads('+repr(json.dumps(
            {n: base64.b64encode(files[n]).decode() for n in INPUTS}))+').items()}\n'
        'ns={"__name__":"sealed_registry","__file__":spec["stage"]+"/worker.py"}\n'
        'exec(compile(files["worker.py"],"sealed-registry","exec"),ns)\n'
        'status=0\ntry:\n result=ns["worker"](spec,files,'+repr(mode)+','+repr(terminal_sha)+')\n'
        'except BaseException as e:\n status=2\n result={"phase":"held","error":str(e)[:500]}\n'
        'print(json.dumps({"spec_sha256":ns["sha"](ns["encoded"](spec)),"result":result}))\n'
        'print("INSPECT_EXIT_STATUS="+str(status))\nraise SystemExit(status)\n').encode()


def accept(spec, result):
    report = result['report']
    queries = {'registry', 'registry-end', 'active', 'addresses', 'routes-4', 'routes-6', 'cmdline'}
    queries |= {'profile-'+key for key in report['current_registry']}
    if (result['phase'] != 'captured' or sha(encoded(report)) != result['terminal_sha256']
            or report['hostname'] != spec['hostname'] or report['kernel'] != spec['kernel']
            or report['checks'] != {'read_only_capture': True, 'retained_state_stable': True, 'registry_stable': True}
            or set(report['queries']) != queries
            or set(report['boot_files']) != set(BOOT)
            or set(report['retained']) != {'state.json', 'before.json', 'commands.jsonl'}
            or report['retained_sha256'] != {n: sha(base64.b64decode(v, validate=True)) for n, v in report['retained'].items()}
            or any(q['status'] != 0 for q in report['queries'].values())):
        raise ValueError('complete bound diagnostic report required')
    return {'state': 'diagnostic_accepted', 'terminal_sha256': result['terminal_sha256'],
            'spec_sha256': sha(encoded(spec)), 'boot_id': report['boot_id']}


def execute(args):
    c = module('run-foundation-preflight.py')
    bundle = args.bundle.absolute(); directory = bundle.parent
    spec, files = prepare(bundle, args.sha256)
    if args.mode == 'capture' and not spec['prepared_epoch']-300 <= time.time() < spec['expires_epoch']:
        raise ValueError('capture window expired')
    if args.mode != 'capture':
        if json.loads(c.private_file(directory/'capture-execution.json'))['bundle_sha256'] != args.sha256:
            raise ValueError('registered capture required')
    terminal_sha = None
    if args.mode == 'cleanup':
        receipt = json.loads(c.private_file(directory/'acceptance.json'))
        if receipt['bundle_sha256'] != args.sha256 or receipt['spec_sha256'] != sha(files['spec.json']):
            raise ValueError('bound acceptance required')
        terminal_sha = receipt['terminal_sha256']
    agent = os.environ.get('SSH_AUTH_SOCK')
    if not agent:
        raise ValueError('existing SSH agent required')
    c.write_new(directory/(args.mode+'-execution.json'), {'bundle_sha256': args.sha256, 'registered_epoch': int(time.time())})
    # Only readback may try the second endpoint. Never retry capture or cleanup.
    endpoints = spec['endpoints'] if args.mode == 'readback' else spec['endpoints'][:1]
    for index, host in enumerate(endpoints):
        label = args.mode+'-'+str(index)
        argv = c.transport(directory, host); argv[3] = '180s'
        argv[argv.index('ama@'+host):argv.index('ama@'+host)] = ['-o', 'HostKeyAlias='+spec['old_ipv4']]
        data = payload(spec, files, args.mode, terminal_sha)
        c.write_new(directory/(label+'-submission.json'), {'argv': argv, 'payload_sha256': sha(data)})
        with (directory/(label+'.stdout')).open('xb') as out, (directory/(label+'.stderr')).open('xb') as err:
            p = subprocess.run(argv, input=data, stdout=out, stderr=err, check=False,
                               env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C', 'SSH_AUTH_SOCK': agent})
        c.write_new(directory/(label+'-transport.json'), {'exit_status': p.returncode})
        raw = c.private_file(directory/(label+'.stdout'), 20*1024**2)
        match = re.fullmatch(rb'(.*)\nINSPECT_EXIT_STATUS=([02])\n', raw, re.S)
        if match and p.returncode == int(match[2]):
            response = json.loads(match[1])
            if response['spec_sha256'] != sha(files['spec.json']):
                raise ValueError('terminal specification mismatch')
            c.write_new(directory/(label+'-result.json'), response)
            if p.returncode:
                raise ValueError('capture held: '+response['result'].get('error', 'unknown'))
            result = response['result']
            if args.mode == 'cleanup':
                if result != {'phase': 'cleaned', 'terminal_sha256': terminal_sha}:
                    raise ValueError('cleanup terminal mismatch')
            else:
                receipt = dict(accept(spec, result), bundle_sha256=args.sha256)
                path = directory/'acceptance.json'
                if path.exists():
                    if c.private_file(path) != encoded(receipt):
                        raise ValueError('conflicting acceptance')
                else:
                    c.write_new(path, receipt)
            c.write_new(directory/(args.mode+'-result.json'), result)
            return {'mode': args.mode, 'phase': result['phase'], 'target': spec['hostname']}
    raise ValueError('terminal unavailable; preserve evidence and do not replay capture/cleanup')


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    p = sub.add_parser('seal')
    p.add_argument('--hardware-dir', type=Path, required=True); p.add_argument('--hardware-sha256', required=True)
    p.add_argument('--operation-id', required=True); p.add_argument('--output', type=Path, required=True)
    p = sub.add_parser('execute')
    p.add_argument('--bundle', type=Path, required=True); p.add_argument('--sha256', required=True)
    p.add_argument('--mode', choices=('capture', 'readback', 'cleanup'), required=True)
    args = parser.parse_args()
    print(json.dumps(seal(args) if args.action == 'seal' else execute(args)))


if __name__ == '__main__':
    main()
