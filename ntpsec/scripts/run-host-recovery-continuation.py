#!/usr/bin/python3
"""Seal one recovery reboot after accepted diagnosis of loopback UUID drift."""
import argparse
import base64
import fcntl
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import tarfile
import time

ROOT = Path(__file__).resolve().parents[1]
INPUTS = {'worker.py', 'helper.py', 'hardware.tar', 'diagnostic.json', 'diagnostic-acceptance.json',
          'diagnostic-cleanup.json', 'architecture.md', 'operations.md', 'history.md'}
EXTRAS = {'spec.json', 'manifest.json', 'review.md', 'known_hosts', 'transport.py', 'controller.py', 'tests.py'}
FIELDS = 'connection.id,connection.uuid,connection.type,connection.interface-name,connection.autoconnect,ipv4.method,ipv4.addresses,ipv4.gateway,ipv6.method,ipv6.addresses,ipv6.gateway'
LOOPBACK = {'connection.id': 'lo', 'connection.type': 'loopback', 'connection.interface-name': 'lo',
            'connection.autoconnect': 'no', 'ipv4.method': 'manual', 'ipv4.addresses': '127.0.0.1/8',
            'ipv4.gateway': '', 'ipv6.method': 'manual', 'ipv6.addresses': '::1/128', 'ipv6.gateway': ''}


def module(name):
    s = importlib.util.spec_from_file_location('recovery_'+name.replace('-', '_'), ROOT/'scripts'/name)
    result = importlib.util.module_from_spec(s); s.loader.exec_module(result)
    return result


def encoded(value):
    return (json.dumps(value, sort_keys=True)+'\n').encode()


def sha(value):
    import hashlib
    return hashlib.sha256(value).hexdigest()


def unpack(raw):
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:') as archive:
        members = archive.getmembers()
        if (len(members) > 64 or len({m.name for m in members}) != len(members)
                or any(not m.isfile() or not re.fullmatch('[a-z][a-z0-9._-]+', m.name) or m.size > 16*1024**2 for m in members)):
            raise ValueError('bounded flat regular archive required')
        files = {m.name: archive.extractfile(m).read() for m in members}
    if json.loads(files['manifest.json']) != {n: sha(v) for n, v in files.items() if n != 'manifest.json'}:
        raise ValueError('archive member digest mismatch')
    return files


def loopback_registry(expected, actual, fields):
    previous = [k for k, v in expected.items() if v == 'loopback']
    current = [k for k, v in actual.items() if v == 'loopback']
    if (len(previous) != 1 or len(current) != 1
            or {k: v for k, v in expected.items() if v != 'loopback'} != {k: v for k, v in actual.items() if v != 'loopback'}
            or fields != dict(LOOPBACK, **{'connection.uuid': current[0]})):
        raise ValueError('only verified lo UUID replacement allowed; non-loopback registry or lo settings drift')
    # Compatibility input for the sealed original check; no profile or evidence write.
    return dict(expected)


def bindings(spec, files):
    if (spec['operation'] != 'host-recovery-continuation'
            or not re.fullmatch('[a-z][a-z0-9-]{0,47}', spec['operation_id'])
            or spec['stage'] != '/var/lib/ntp-recovery-'+spec['operation_id']
            or spec['members'].keys() != INPUTS
            or any(sha(files[n]) != digest for n, digest in spec['members'].items())
            or sha(files['hardware.tar']) != spec['hardware_sha256']):
        raise ValueError('recovery input binding required')
    oldfiles = unpack(files['hardware.tar']); old = json.loads(oldfiles['spec.json'])
    diagnostic = json.loads(files['diagnostic.json']); receipt = json.loads(files['diagnostic-acceptance.json'])
    cleanup = json.loads(files['diagnostic-cleanup.json']); report = diagnostic['report']
    if (old['operation'] != 'hardware' or not re.fullmatch('/var/lib/ntp-host-[a-z][a-z0-9-]{0,47}', old['stage'])
            or any(spec[k] != old[k] for k in ('hostname', 'kernel', 'ssh', 'old_ipv4'))
            or spec['endpoints'] != [old['recipe'][k].split('/')[0] for k in ('ipv4_address', 'ipv6_address')]
            or receipt['state'] != 'diagnostic_accepted' or receipt['bundle_sha256'] != spec['inspection_sha256']
            or receipt['terminal_sha256'] != sha(encoded(report)) or diagnostic['terminal_sha256'] != receipt['terminal_sha256']
            or cleanup != {'phase': 'cleaned', 'terminal_sha256': receipt['terminal_sha256']}
            or report['hostname'] != spec['hostname'] or report['kernel'] != spec['kernel']
            or report['boot_id'] != spec['diagnosed_boot_id']
            or json.loads(base64.b64decode(report['retained']['state.json']))['phase'] != 'recovery_files_restored'
            or not 0 < spec['expires_epoch']-spec['prepared_epoch'] <= 86400
            or spec['expires_epoch'] > report['collected_epoch']+86400):
        raise ValueError('accepted fresh diagnosis/cleanup/hardware binding required')
    key = next(k for k, v in report['current_registry'].items() if v == 'loopback')
    fields = dict(l.split(':', 1) for l in report['queries']['profile-'+key]['stdout'].splitlines())
    loopback_registry(report['expected_registry'], report['current_registry'], fields)
    return old, oldfiles, report


def worker(spec, files, mode, proofs=None, console_ready=False):
    old, oldfiles, diagnosis = bindings(spec, files)
    ns = {'__name__': 'recovery_helper'}
    exec(compile(files['helper.py'], 'sealed-helper', 'exec'), ns)
    h = type('Helper', (), ns)
    ns = {'__name__': 'retained_worker', '__file__': old['stage']+'/host-configuration-stage.py'}
    exec(compile(oldfiles['host-configuration-stage.py'], 'retained-worker', 'exec'), ns)
    ns['identity'](old)
    root = Path(spec['stage']); os.umask(0o077)
    if mode == 'reboot':
        if console_ready is not True or not spec['prepared_epoch']-300 <= time.time() < spec['expires_epoch']:
            raise ValueError('fresh window and console-ready declaration required')
        if ns['boot_id']() != spec['diagnosed_boot_id']:
            raise ValueError('diagnosed boot changed')
        h.ancestors(root.parent); root.mkdir(mode=0o700); h.sync(root.parent)
        for name, data in {**files, 'spec.json': encoded(spec), 'state.json': encoded({'phase': 'prepared'}), '.lock': b''}.items():
            h.create(root/name, data)
    h.ancestors(root)
    expected = INPUTS | {'spec.json', 'state.json', '.lock'}
    if stat_mode(root) != 0o700 or {p.name for p in root.iterdir()} != expected:
        raise ValueError('protected closed recovery stage required')
    for path in root.iterdir():
        if stat_mode(path) != 0o600:
            raise ValueError('private recovery files required')
        h.read(path, limit=32*1024**2)
    for name, data in {**files, 'spec.json': encoded(spec)}.items():
        if h.read(root/name, limit=32*1024**2) != data:
            raise ValueError('recovery input drift')
    with (root/'.lock').open('rb') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = json.loads(h.read(root/'state.json'))
        def save():
            h.replace(root/'state.json', encoded(state), 0o600)
        tx = ns['Transaction'](old)
        tx.verify({n: oldfiles[n] for n in old['members']})
        expected_registry = diagnosis['expected_registry']
        original_registry = tx.core.registry
        observed = {}
        def compatible_registry():
            actual = original_registry()
            keys = [k for k, v in actual.items() if v == 'loopback']
            if len(keys) != 1:
                raise ValueError('exactly one loopback required')
            text = tx.run(['/usr/bin/nmcli', '-t', '-f', FIELDS, 'connection', 'show', 'uuid', keys[0]])
            fields = dict(l.split(':', 1) for l in text.splitlines())
            result = loopback_registry(expected_registry, actual, fields)
            observed.update(registry=actual, loopback=fields)
            return result
        tx.core.registry = compatible_registry
        if mode == 'readback':
            return {'phase': state['phase'], 'continuation': state, 'original': tx.state(), 'boot_id': ns['boot_id']()}
        if mode == 'reboot':
            for name, digest in diagnosis['retained_sha256'].items():
                if h.sha(h.read(Path(old['stage'])/name, limit=8*1024**2)) != digest:
                    raise ValueError('diagnosed retained evidence drift')
            for name, original in tx.before()['boot_files'].items():
                if tx.snapshot_file(Path(name)) != original:
                    raise ValueError('original boot bytes/ownership/mode required')
            state['phase'] = 'reboot_submitting'; save()
            result = tx.schedule_reboot(True, recovery=True)
            state.update(phase='reboot_submitted', original=result, observed_before=observed); save()
            return state
        if mode in ('probe', 'accept'):
            if state['phase'] not in ('reboot_submitting', 'reboot_submitted', 'accepted'):
                raise ValueError('registered recovery reboot required')
            if ns['boot_id']() == spec['diagnosed_boot_id']:
                raise ValueError('new recovery boot required')
            for name, original in tx.before()['boot_files'].items():
                if tx.snapshot_file(Path(name)) != original:
                    raise ValueError('restored original boot file drift')
            result = tx.probe(recovery=True)
            current = {'phase': 'recovery_ready', 'boot_id': result['boot_id'], 'observed': observed,
                       'checks': {'original_boot_files': True, 'new_boot': True, 'network_and_native_continuity': True}}
            if mode == 'probe':
                return current
            if state['phase'] == 'accepted' or set(proofs or {}) != set(spec['endpoints']) or any(p != current for p in proofs.values()):
                raise ValueError('one matching dual-endpoint recovery acceptance required')
            state.update(phase='accepted', proof=current, endpoint_proofs=proofs); save()
            return state
        if mode == 'cleanup':
            if state['phase'] != 'accepted':
                raise ValueError('accepted recovery required')
            result = tx.cleanup()
            state.update(transient_units_cleaned=result['transient_units_cleaned']); save()
            return state
        raise ValueError('closed continuation mode required')


def stat_mode(path):
    import stat
    return stat.S_IMODE(path.lstat().st_mode)


def prepare(bundle, checksum):
    c = module('run-foundation-preflight.py')
    raw = c.private_file(bundle, 32*1024**2)
    if sha(raw) != checksum:
        raise ValueError('approved recovery hash mismatch')
    files = unpack(raw)
    if (set(files) != INPUTS | EXTRAS or files['worker.py'] != Path(__file__).read_bytes()
            or files['controller.py'] != (ROOT/'scripts/run-host-configuration.py').read_bytes()
            or files['transport.py'] != (ROOT/'scripts/run-foundation-preflight.py').read_bytes()
            or c.private_file(bundle.parent/'known_hosts', 4096) != files['known_hosts']
            or bundle.parent.stat().st_uid != os.getuid() or bundle.parent.stat().st_mode & 0o077):
        raise ValueError('closed archive/controller/private path required')
    spec = json.loads(files['spec.json']); bindings(spec, files)
    if c.host_key(files['known_hosts'], spec['old_ipv4']) != spec['ssh']['fingerprint']:
        raise ValueError('pinned key mismatch')
    return spec, files


def payload(spec, files, mode, proofs=None, console_ready=False):
    return ('import base64,json,hashlib\n'
        'spec=json.loads('+repr(json.dumps(spec))+')\n'
        'files={n:base64.b64decode(v,validate=True) for n,v in json.loads('+repr(json.dumps(
            {n: base64.b64encode(files[n]).decode() for n in INPUTS}))+').items()}\n'
        'ns={"__name__":"sealed_recovery","__file__":spec["stage"]+"/worker.py"}\n'
        'exec(compile(files["worker.py"],"sealed-recovery","exec"),ns)\n'
        'status=0\ntry:\n result=ns["worker"](spec,files,'+repr(mode)+','+repr(proofs)+','+repr(console_ready)+')\n'
        'except BaseException as e:\n status=2\n result={"phase":"held","error":str(e)[:500]}\n'
        'print(json.dumps({"hostname":spec["hostname"],"spec_sha256":ns["sha"](ns["encoded"](spec)),"result":result}))\n'
        'print("HOST_EXIT_STATUS="+str(status))\nraise SystemExit(status)\n').encode()


def seal(args):
    c = module('run-foundation-preflight.py'); inspection = module('run-host-registry-inspection.py')
    inspected, _ = inspection.prepare(args.inspection_dir/'registry-inspection.tar', args.inspection_sha256)
    old, previous = module('run-host-configuration.py').prepare(args.hardware_dir/'host-configuration.tar', args.hardware_sha256)
    report = json.loads(c.private_file(args.inspection_dir/'capture-result.json', 20*1024**2))
    receipt = inspection.accept(inspected, report)
    stored = json.loads(c.private_file(args.inspection_dir/'acceptance.json'))
    if stored != dict(receipt, bundle_sha256=args.inspection_sha256) or inspected['hardware_bundle_sha256'] != args.hardware_sha256:
        raise ValueError('accepted inspection binding required')
    files = {'worker.py': Path(__file__).read_bytes(), 'helper.py': previous['foundation-install.py'],
             'hardware.tar': c.private_file(args.hardware_dir/'host-configuration.tar'),
             'diagnostic.json': encoded(report), 'diagnostic-acceptance.json': encoded(stored),
             'diagnostic-cleanup.json': c.private_file(args.inspection_dir/'cleanup-result.json'),
             'known_hosts': previous['known_hosts'], 'controller.py': (ROOT/'scripts/run-host-configuration.py').read_bytes(),
             'transport.py': (ROOT/'scripts/run-foundation-preflight.py').read_bytes(),
             'tests.py': (ROOT/'tests/test_host_recovery_continuation.py').read_bytes()}
    for label, path in (('architecture', 'docs/ntp-architecture-deployment-plan-v1.0.md'), ('operations', 'docs/OPERATIONS.md'), ('history', 'HISTORY.md')):
        files[label+'.md'] = (ROOT/path).read_bytes()
    epoch = int(time.time()); spec = {k: old[k] for k in ('hostname', 'kernel', 'ssh', 'old_ipv4')}
    spec.update(operation='host-recovery-continuation', operation_id=args.operation_id,
                stage='/var/lib/ntp-recovery-'+args.operation_id, prepared_epoch=epoch,
                expires_epoch=min(epoch+86400, report['report']['collected_epoch']+86400),
                diagnosed_boot_id=report['report']['boot_id'], hardware_sha256=args.hardware_sha256,
                inspection_sha256=args.inspection_sha256, endpoints=inspected['endpoints'],
                members={n: sha(files[n]) for n in INPUTS})
    bindings(spec, files)
    files['spec.json'] = encoded(spec)
    files['review.md'] = (f'# Hardware recovery continuation\n\nTarget: {spec["hostname"]}. Operation: {args.operation_id}.\n'
        f'Root stage: `{spec["stage"]}`. Initial submission expires epoch {spec["expires_epoch"]}.\n'
        f'Hardware SHA-256: `{args.hardware_sha256}`.\nInspection SHA-256: `{args.inspection_sha256}`.\n\n'
        'One recovery reboot, only after a current console-ready declaration and exact diagnosed boot, '
        'retained state/before/journal hashes, original boot bytes/owners/modes, native files and network checks. '
        'The accepted diagnosis proves only the loopback UUID changed. The continuation accepts UUID replacement '
        'only for exactly one loopback profile with the observed lo identity, manual 127.0.0.1/8 and ::1/128, '
        'no gateways and autoconnect=no. Every non-loopback UUID/type must match exactly. Existing Ethernet '
        'profile, active interface, address, RA, DNS, route, HTTPS, package/native/service checks remain in force. '
        'No profile is modified, no boot file edited, and no service activated.\n\n'
        'Create a separate root-owned 0700 stage with 0600 inputs/state. Run the sealed original worker '
        'with an in-memory registry adapter; preserve its code and before-state byte-for-byte. Its command '
        'journal and recovery state advance normally. Register submission locally and durably record '
        'reboot_submitting before scheduling the original recovery timer. Never retry uncertain submission. '
        'Verify a new boot and restored original boot files over both pinned fixed endpoints, then record '
        'one matching acceptance. Conditional readback via either fixed endpoint inspects both journals. Conditional cleanup stops '
        'only original operation reboot timers/services; retain both root stages and all local evidence.\n\n'
        'Use run-host-recovery-continuation.py execute --bundle ABSOLUTE_BUNDLE --sha256 APPROVED_HASH '
        '--mode reboot --console-ready once; then --mode verify. Conditional modes are readback and cleanup. '
        'Verification waits at most six passes separated by 20 seconds; SSH bounds are 60 seconds. '
        'There is no automatic recovery timer across reboot. Keep console/media recovery ready and the '
        'original Debian 11 card preserved. If SSH or boot fails, preserve state and use console/media '
        'recovery; no second reboot or broadened repair is authorized. Runtime/account activation remains blocked.\n').encode()
    files['manifest.json'] = encoded({n: sha(v) for n, v in files.items()})
    os.umask(0o077); args.output.mkdir(mode=0o700)
    for n in ('spec.json', 'review.md', 'known_hosts'):
        (args.output/n).write_bytes(files[n])
    bundle = args.output/'recovery-continuation.tar'
    with tarfile.open(bundle, 'w', format=tarfile.USTAR_FORMAT) as archive:
        for n, data in sorted(files.items()):
            info = tarfile.TarInfo(n); info.size=len(data); info.mode=0o600; info.mtime=epoch
            archive.addfile(info, io.BytesIO(data))
    result = {'bundle': str(bundle), 'sha256': sha(bundle.read_bytes()), 'target': spec['hostname'],
              'expires_epoch': spec['expires_epoch'], 'target_contact': False, 'execution_authorized': False}
    prepare(bundle, result['sha256']); c.write_new(args.output/'sealing.json', result)
    return result


def acceptance(spec, result):
    if (result['phase'] != 'accepted' or set(result['endpoint_proofs']) != set(spec['endpoints'])
            or any(p != result['proof'] for p in result['endpoint_proofs'].values())
            or result['proof']['boot_id'] == spec['diagnosed_boot_id']
            or result['proof']['checks'] != {'original_boot_files': True, 'new_boot': True, 'network_and_native_continuity': True}):
        raise ValueError('bound dual-endpoint recovery acceptance required')
    return result


def execute(args):
    c = module('run-foundation-preflight.py'); transport = module('run-host-configuration.py')
    transport.payload = payload  # Reuse its registered strict-key transport with this sealed worker.
    bundle=args.bundle.absolute(); directory=bundle.parent; spec, files=prepare(bundle,args.sha256)
    if args.mode == 'reboot':
        if not args.console_ready or not spec['prepared_epoch']-300 <= time.time() < spec['expires_epoch']:
            raise ValueError('fresh window and console readiness required')
    elif json.loads(c.private_file(directory/'reboot-execution.json'))['bundle_sha256'] != args.sha256:
        raise ValueError('registered recovery reboot required')
    c.write_new(directory/(args.mode+'-execution.json'), {'bundle_sha256': args.sha256,
                'registered_epoch': int(time.time()), 'console_ready': args.console_ready})
    hosts=spec['endpoints']
    def remote(host, mode, label, proofs=None):
        return transport.remote(directory,spec,files,host,mode,label,proofs,args.console_ready)
    if args.mode == 'reboot':
        result=remote(hosts[0],'reboot','reboot-submit')
    elif args.mode == 'verify':
        import subprocess
        for attempt in range(6):
            try:
                remote(hosts[0],'probe','wait-'+str(attempt)); break
            except (ValueError,subprocess.TimeoutExpired):
                if attempt==5: raise
                time.sleep(20)
        proofs={host:remote(host,'probe','endpoint-'+str(index)) for index,host in enumerate(hosts)}
        result=remote(hosts[0],'accept','accept',proofs)
    else:
        for index, host in enumerate(hosts):
            try:
                result=remote(host,'readback','readback-before-'+args.mode+'-'+str(index)); break
            except ValueError:
                if index == len(hosts)-1: raise
        if args.mode == 'cleanup':
            acceptance(spec,result['continuation'])
            result=remote(host,'cleanup','cleanup-submit')
    if result['phase']=='accepted':
        if args.mode == 'readback':
            result=result['continuation']
        acceptance(spec,result)
        receipt={'bundle_sha256':args.sha256,'spec_sha256':sha(files['spec.json']),
                 'state':'recovery_accepted','proof':result['proof'],'endpoint_proofs':result['endpoint_proofs']}
        path=directory/'acceptance.json'
        if not path.exists():c.write_new(path,receipt)
        elif c.private_file(path)!=encoded(receipt):raise ValueError('acceptance conflict')
    c.write_new(directory/(args.mode+'-result.json'),result)
    return {'mode':args.mode,'phase':result['phase'],'target':spec['hostname']}


def main():
    os.umask(0o077); parser=argparse.ArgumentParser(description=__doc__); sub=parser.add_subparsers(dest='action',required=True)
    p=sub.add_parser('seal')
    for n in ('hardware','inspection'):
        p.add_argument('--'+n+'-dir',type=Path,required=True); p.add_argument('--'+n+'-sha256',required=True)
    p.add_argument('--operation-id',required=True); p.add_argument('--output',type=Path,required=True)
    p=sub.add_parser('execute'); p.add_argument('--bundle',type=Path,required=True); p.add_argument('--sha256',required=True)
    p.add_argument('--mode',choices=('reboot','verify','readback','cleanup'),required=True);p.add_argument('--console-ready',action='store_true')
    args=parser.parse_args(); print(json.dumps(seal(args) if args.action=='seal' else execute(args)))


if __name__=='__main__':main()
