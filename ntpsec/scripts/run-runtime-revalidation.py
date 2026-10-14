#!/usr/bin/python3
"""Seal one read-only hardware/runtime revalidation; never replay activation."""
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
import signal
import socket
import stat
import subprocess
import sys
import tarfile
import time
import types

ROOT = Path(__file__).resolve().parents[1]
PATHS = {'stage.py': 'scripts/run-runtime-revalidation.py',
         'continuity.py': 'scripts/runtime-continuity.py', 'base.py': 'scripts/service-cutover-stage.py',
         'controller.py': 'scripts/run-service-cutover.py', 'transport.py': 'scripts/run-foundation-preflight.py',
         'monitor-controller.py': 'scripts/run-service-monitor.py',
         'tests.py': 'tests/test_runtime_revalidation.py', 'monitor-tests.py': 'tests/test_service_monitor.py',
         'acquisition-tests.py': 'tests/test_gpsd_acquisition.py',
         'architecture.md': 'docs/ntp-architecture-deployment-plan-v1.0.md',
         'operations.md': 'docs/OPERATIONS.md', 'history.md': 'HISTORY.md'}
EXTRA = {'monitor.tar', 'monitor-proof.json', 'helper.py', 'inspector.py', 'known_hosts', 'reference.py'}
CHECKS = {'restoration', 'failed_stage', 'idle_workers', 'runtime', 'hardware', 'continuity', 'source_preserved'}
EVIDENCE = ('current-runtime.json', 'before.json', 'commands.jsonl', 'failed-stage.json')
LIMIT = 32*1024**2
ARCHIVE_LIMIT = 64*1024**2
ENV = {'PATH': '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin', 'LC_ALL': 'C', 'PYTHONDONTWRITEBYTECODE': '1'}


def encoded(value): return (json.dumps(value, sort_keys=True)+'\n').encode()
def sha(raw): return hashlib.sha256(raw).hexdigest()


def frozen(raw):
    result = types.ModuleType('sealed_revalidation'); result.__file__ = '/sealed/stage.py'
    exec(compile(raw, result.__file__, 'exec'), result.__dict__)
    return result


def load(path):
    spec = importlib.util.spec_from_file_location('revalidation_'+path.stem.replace('-', '_'), path)
    result = importlib.util.module_from_spec(spec); spec.loader.exec_module(result)
    return result


def inputs(files):
    c = frozen(files['monitor-controller.py']); monitor = c.unpack(files['monitor.tar'])
    old = json.loads(monitor['spec.json']); validator = frozen(monitor['controller.py'])
    validator.validate(old, monitor)
    proof = json.loads(files['monitor-proof.json'])
    if 'recovered' in proof:
        recovered_source(old, monitor, proof)
    elif (set(proof) != {'start', 'readback'}
            or proof['start'] != {'spec_sha256': sha(monitor['spec.json']), 'result': {
                'phase': 'held', 'error': 'accepted bound hardware/reboot gate required'}}
            or proof['readback'] != {'spec_sha256': sha(monitor['spec.json']), 'result': {
                'phase': 'held', 'error': "[Errno 2] No such file or directory: '"+old['stage']+"/state.json'"}}):
        raise ValueError('bound preflight-only rejection and missing-state readback required')
    rspec, restoration, report, source = validator.restoration(monitor)
    if (files['helper.py'] != restoration['helper.py'] or files['inspector.py'] != restoration['inspector.py']
            or files['known_hosts'] != monitor['known_hosts'] or files['reference.py'] != monitor['reference.py']):
        raise ValueError('frozen protection helpers/key binding')
    return old, monitor, rspec, restoration, report, source


def recovered_source(old, monitor, proof):
    """Bind the latest recovered operation, its matching readbacks and closure."""
    if set(proof) != {'recovered', 'readbacks', 'cleanup'} or len(proof['readbacks']) != 2:
        raise ValueError('closed recovered monitor proof required')
    first, second = proof['readbacks']; state = first['result']
    receipt = {'state': 'recovered', 'bundle_sha256': proof['recovered']['bundle_sha256'],
               'spec_sha256': sha(monitor['spec.json']), 'state_sha256': sha(encoded(state)),
               'time_service_accepted': False}
    if (first != second or first['spec_sha256'] != receipt['spec_sha256']
            or state.get('phase') != 'recovered' or proof['recovered'] != receipt
            or proof['cleanup'] != {'spec_sha256': receipt['spec_sha256'],
                                   'result': dict(state, transient_cleanup=True)}):
        raise ValueError('matching recovered monitor receipt/readbacks/cleanup required')
    return proof['cleanup']['result']


def validate(spec, files):
    if set(files) != set(PATHS)|EXTRA|{'spec.json', 'manifest.json', 'review.md'}:
        raise ValueError('closed revalidation bundle required')
    old, *rest = inputs(files)
    proof = json.loads(files['monitor-proof.json'])
    if 'recovered' in proof and proof['recovered']['bundle_sha256'] != sha(files['monitor.tar']):
        raise ValueError('recovered monitor archive binding')
    if (spec['schema'] != 1 or spec['purpose'] != 'runtime-revalidation'
            or not re.fullmatch(r'[a-z][a-z0-9-]{0,47}', spec['operation_id'])
            or spec['stage'] != '/var/lib/ntp-acquire-'+spec['operation_id']
            or spec['source_stage'] != old['stage'] or spec['source_sha256'] != sha(files['monitor.tar'])
            or any(spec[k] != old[k] for k in ('hostname', 'boot_id', 'kernel', 'endpoints', 'old_ipv4'))
            or type(spec['prepared_epoch']) is not int or type(spec['expires_epoch']) is not int
            or not 0 < spec['expires_epoch']-spec['prepared_epoch'] <= 86400
            or spec['members'] != {n: sha(files[n]) for n in set(PATHS)|EXTRA}):
        raise ValueError('revalidation identity/window/member binding')
    # Exercise the exact alias consumed by Transaction.runtime_context before SSH.
    reference = frozen(files['reference.py'])
    acquisition = reference.unpack(rest[0]['reference.tar'])
    alias = dict(json.loads(acquisition['spec.json']), operation_id=spec['operation_id'],
                 stage=spec['stage'], unit='ntp-acquire-'+spec['operation_id']+'.service')
    reference.validate(alias, acquisition)
    return (old, *rest)


def failed_stage(h, old, monitor, run, proof=None):
    root = Path(old['stage']); h.ancestors(root)
    if stat.S_IMODE(root.stat().st_mode) != 0o700: raise ValueError('private failed stage required')
    if h.read(root/'spec.json') != monitor['spec.json']: raise ValueError('failed stage spec drift')
    for name, digest in old['members'].items():
        if sha(h.read(root/name, limit=ARCHIVE_LIMIT if name.endswith('.tar') else LIMIT)) != digest: raise ValueError('failed stage member drift')
    recovered = proof is not None and 'recovered' in proof
    if recovered:
        expected = recovered_source(old, monitor, proof)
        if json.loads(h.read(root/'state.json', limit=LIMIT)) != expected:
            raise ValueError('recovered source state drift')
    elif any(os.path.lexists(root/name) for name in ('state.json', 'before.json', 'startup-monitor.json')):
        raise ValueError('failed stage progressed beyond approved preflight state')
    rows = {}
    for unit in (old['apply_unit']+'.service', old['recovery_unit']+'.service', old['recovery_unit']+'.timer',
                 'ntp-monitor-recovery.service'):
        value = run(['/usr/bin/systemctl', 'show', unit, '--property=LoadState', '--value']).strip()
        if value != 'not-found': raise ValueError('unexpected monitor worker/unit: '+unit)
        rows[unit] = value
    return {'source_spec_sha256': sha(monitor['spec.json']), 'state_absent': not recovered, 'units': rows}


def capture(h, spec, files):
    old, monitor, rspec, archive, report, source = validate(spec, files)
    root = Path(spec['stage']); restoration = frozen(archive['stage.py'])
    held = json.loads(source['spec.json']); restored = Path(rspec['stage'])
    h.ancestors(restored)
    for name, digest in rspec['members'].items():
        if sha(h.read(restored/name, limit=LIMIT)) != digest: raise ValueError('restoration input drift')
    if (json.loads(h.read(restored/'report.json', limit=LIMIT)) != report
            or json.loads(h.read(restored/'cleanup.json')) != json.loads(monitor['restoration-proof.json'])['cleanup']['result']):
        raise ValueError('accepted restoration report/closure drift')
    fd = restoration.source_lock(h, rspec, held, source)
    try:
        before_state = h.read(restored/'source-state-before.json')
        if h.read(Path(held['stage'])/'state.json') != before_state: raise ValueError('held source state drift')
        base = frozen(files['base.py']); continuity = frozen(files['continuity.py'])
        class Transaction(base.Transaction):
            def runtime_context(self, create=False):
                result = continuity.context(self, create)
                self.write('current-runtime.json', result)
                return result
        candidate = dict(old, stage=spec['stage'], operation_id=spec['operation_id'])
        tx = Transaction(candidate, monitor)
        clocks = restoration.timer_state(tx.run, held)
        if clocks['timer']['ActiveState'] != 'inactive': raise ValueError('old timer active')
        proof = json.loads(files['monitor-proof.json'])
        failed = failed_stage(h, old, monitor, tx.run, proof); tx.write('failed-stage.json', failed)
        tx.preflight()  # Reads original prerequisites; writes only this operation's private copies.
        current = tx.runtime_context()
        if current['observation'] != json.loads(restoration.evidence(report, 'continuity-after.json')):
            raise ValueError('current restored-state continuity drift')
        if failed_stage(h, old, monitor, tx.run, proof) != failed: raise ValueError('source stage changed during capture')
        if restoration.timer_state(tx.run, held) != clocks: raise ValueError('old recovery state changed')
        if h.read(Path(held['stage'])/'state.json') != before_state: raise ValueError('held source changed during capture')
        return {'phase': 'runtime_validated', 'epoch': int(time.time()), 'boot_id': spec['boot_id'],
                'checks': dict.fromkeys(sorted(CHECKS), True), 'time_service_accepted': False,
                'source_preserved': True, 'hardware': current['runtime']['hardware'],
                'observation_sha256': sha(encoded(current['observation']))}
    finally: os.close(fd)


def protected(spec, files):
    """Retain frozen protection rules with the explicit nested-archive bound."""
    root = Path(spec['stage'])
    if (os.geteuid() != 0 or socket.gethostname() != spec['hostname'] or os.uname().release != spec['kernel']
            or Path('/proc/sys/kernel/random/boot_id').read_text().strip() != spec['boot_id']):
        raise ValueError('approved target/kernel/boot identity required')
    h = frozen(files['helper.py']); h.ancestors(root)
    if stat.S_IMODE(root.stat().st_mode) != 0o700 or h.read(root/'spec.json') != encoded(spec):
        raise ValueError('protected diagnostic stage mismatch')
    for name, digest in spec['members'].items():
        if sha(h.read(root/name, limit=ARCHIVE_LIMIT if name.endswith('.tar') else LIMIT)) != digest:
            raise ValueError('sealed diagnostic input drift')
    return h


def entry(spec, files, mode, proofs=None):
    validate(spec, dict(files, **{'spec.json': encoded(spec), 'manifest.json': b'', 'review.md': b''}))
    root = Path(spec['stage']); os.umask(0o077)
    if mode == 'start':
        if (os.geteuid() != 0 or os.environ.get('SUDO_USER') != 'ama'
                or socket.gethostname() != spec['hostname'] or os.uname().release != spec['kernel']
                or Path('/proc/sys/kernel/random/boot_id').read_text().strip() != spec['boot_id']
                or not spec['prepared_epoch']-300 <= time.time() < spec['expires_epoch']-190):
            raise ValueError('approved caller/identity/start window required')
        h = frozen(files['helper.py']); h.ancestors(root.parent); root.mkdir(mode=0o700)
        for name, raw in dict(files, **{'spec.json': encoded(spec)}).items(): h.create(root/name, raw)
        h.create(root/'report.json', encoded({'phase': 'running'}))
    h = protected(spec, files)
    if mode == 'start':
        try:
            with (root/'worker.stdout').open('xb') as out, (root/'worker.stderr').open('xb') as err:
                process = subprocess.Popen(['/usr/bin/python3', '-I', '-B', str(root/'stage.py'), 'worker'],
                    cwd='/', stdout=out, stderr=err, env=ENV, start_new_session=True)
                try: process.wait(timeout=190)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL); process.wait(); raise ValueError('worker exceeded bound')
                if json.loads(h.read(root/'report.json', limit=LIMIT))['phase'] == 'running':
                    raise ValueError('worker lacks terminal report')
        except BaseException as error:
            write_report(h, root, files,
                {'phase': 'validation_held', 'error': str(error)[:500], 'time_service_accepted': False})
    if mode in ('start', 'readback'): return json.loads(h.read(root/'report.json', limit=LIMIT))
    if mode == 'cleanup':
        raw = h.read(root/'report.json', limit=LIMIT)
        if proofs != {'report_sha256': sha(raw)} or json.loads(raw)['phase'] not in ('runtime_validated', 'validation_held'):
            raise ValueError('matching terminal readback required for closure')
        result = {'phase': 'cleaned', 'evidence_preserved': True, 'report_sha256': sha(raw)}
        h.create(root/'cleanup.json', encoded(result)); return result
    raise ValueError('closed revalidation mode required')


def write_report(h, root, files, result):
    result['evidence'] = {}; total = 0
    for name in EVIDENCE:
        try:
            if not os.path.lexists(root/name): continue
            raw = h.read(root/name, limit=8*1024**2); total += len(raw)
            if total > 8*1024**2: raise ValueError('aggregate evidence bound')
            result['evidence'][name] = {'sha256': sha(raw), 'base64': base64.b64encode(raw).decode()}
        except Exception as error:
            result.update(phase='validation_held', time_service_accepted=False)
            result['error'] = (result.get('error', '')+'; evidence '+name+': '+str(error))[-500:]
    frozen(files['base.py']).Transaction.write(types.SimpleNamespace(root=root, h=h), 'report.json', result)


def terminal(spec, checksum, results):
    if set(results) != set(spec['endpoints']) or len({sha(encoded(v)) for v in results.values()}) != 1:
        raise ValueError('matching dual-stack revalidation readbacks required')
    report = next(iter(results.values()))
    if report['phase'] not in ('runtime_validated', 'validation_held'): raise ValueError('terminal validation report required')
    total = 0
    for name, record in report.get('evidence', {}).items():
        raw = base64.b64decode(record['base64'], validate=True); total += len(raw)
        if name not in EVIDENCE or total > 8*1024**2 or sha(raw) != record['sha256']:
            raise ValueError('bounded evidence digest required')
    if report['phase'] == 'runtime_validated' and (report.get('checks') != dict.fromkeys(CHECKS, True)
            or any(value is not True for value in report['checks'].values())
            or report.get('source_preserved') is not True or report.get('time_service_accepted') is not False
            or report.get('boot_id') != spec['boot_id'] or set(report.get('evidence', {})) != set(EVIDENCE)
            or type(report.get('epoch')) is not int
            or not spec['prepared_epoch']-300 <= report['epoch'] < spec['expires_epoch']):
        raise ValueError('complete fresh validation report required')
    if report['phase'] == 'runtime_validated':
        current = json.loads(base64.b64decode(report['evidence']['current-runtime.json']['base64'], validate=True))
        if (current['runtime']['phase'] != 'ready' or current['runtime']['boot_id'] != spec['boot_id']
                or report['hardware'] != current['runtime']['hardware']
                or report['observation_sha256'] != sha(encoded(current['observation']))
                or type(current.get('epoch')) is not int
                or not spec['prepared_epoch']-300 <= current['epoch'] <= report['epoch']):
            raise ValueError('fresh runtime observation/report consistency required')
    return {'state': report['phase'], 'bundle_sha256': checksum, 'spec_sha256': sha(encoded(spec)),
            'report_sha256': sha(encoded(report)), 'time_service_accepted': False}


def review(spec):
    return f'''# Read-only hardware/runtime revalidation

Target **{spec['hostname']}**, operation `{spec['operation_id']}`.
Start before **{datetime.fromtimestamp(spec['expires_epoch']-190, timezone.utc).isoformat()}**, reserving the worker bound.

One capture in root-owned 0700 `{spec['stage']}`; all inputs/evidence 0600.
The stage prefix satisfies the frozen acquisition validator's path contract.
Sealing validates the exact runtime alias offline; execution rechecks it.
Bind current inputs, accepted restoration receipt/closure, and the exact previous
monitor archive with either its preflight rejection or recovered receipt,
matching dual-stack readbacks and transient cleanup.
Verify pinned SSH keys, same boot/kernel/host, original held-source lock, immutable
stage members, inactive old timer, and absence of prior monitor workers.
The prior stage must remain in its sealed missing-state or recovered/cleaned state.

Recheck boot-file hashes, UART/PPS/RTC mapping and permissions, accepted hardware
state/receipt, packages, native binaries, Python imports, accounts, loader cache,
network, idle UART/SHM state and restored files. Use private runtime copies and
compare the full current observation exactly with the accepted restoration
observation. Preserve the new full observation for activation. Historical
acceptance timestamps remain unchanged: fresh checks establish a new observation,
not a renewal of old approval. Original network checks include bounded dual-stack
gateway/egress probes. No service start/stop, timer change, configuration/receiver
write, clock adjustment, PPS acquisition, package install or reboot is authorized.

A 180-second worker bound holds failure and retains partial evidence, including
on controller timeout or a missing worker terminal report. Up to three
numbered conditional readbacks retrieve the stored report over both endpoints.
Matching complete readbacks accept hardware/runtime prerequisites only, never
timing or activation. Conditional cleanup writes diagnostic closure only; preserve
this stage, the failed monitor stage, original source stages and all evidence.
No lost/held capture is replayed. No recovery mutation is included in this review.

The shared continuity helper also supports recovery after historical acceptance
expiry by rechecking actual state; that path is tested offline. A later activation
must bind this accepted report and receive its own execution approval.

Execute from the repository root using `python3 -I -B ntpsec/scripts/run-runtime-revalidation.py
execute --bundle ABSOLUTE_BUNDLE --sha256 APPROVED_HASH --mode start` as one command;
then the same bundle/hash with `--mode readback --attempt N`, and conditional `--mode cleanup`.
'''


def prepare(bundle, checksum, current=False):
    t = load(ROOT/'scripts/run-foundation-preflight.py'); raw = t.private_file(bundle, ARCHIVE_LIMIT)
    if sha(raw) != checksum: raise ValueError('approved revalidation archive digest')
    files = load(ROOT/'scripts/run-service-monitor.py').unpack(raw)
    spec = json.loads(files['spec.json']); frozen(files['stage.py']).validate(spec, files)
    if current and any(files[n] != (ROOT/path).read_bytes() for n, path in PATHS.items()):
        raise ValueError('current revalidation input drift')
    if current and any(t.private_file(bundle.parent/name, LIMIT) != files[name]
                       for name in ('spec.json', 'review.md')):
        raise ValueError('local revalidation review/spec drift')
    if t.private_file(bundle.parent/'known_hosts', 4096) != files['known_hosts']: raise ValueError('pinned key drift')
    return spec, files


def seal(args):
    t = load(ROOT/'scripts/run-foundation-preflight.py'); c = load(ROOT/'scripts/run-service-monitor.py')
    raw = t.private_file(args.source_dir/'service-monitor.tar', ARCHIVE_LIMIT)
    if sha(raw) != args.source_sha256: raise ValueError('executed monitor archive digest')
    monitor = c.unpack(raw); old = json.loads(monitor['spec.json'])
    archive = c.unpack(monitor['restoration.tar'])
    if args.recovered_attempt is not None:
        proof = {'recovered': json.loads(t.private_file(args.source_dir/'recovered-receipt.json')),
                 'readbacks': [json.loads(t.private_file(args.source_dir/f'readback-{args.recovered_attempt}-{i}-result.json')) for i in range(2)],
                 'cleanup': json.loads(t.private_file(args.source_dir/'cleanup-0-result.json'))}
    else:
        proof = {'start': json.loads(t.private_file(args.source_dir/'start-0-result.json')),
                 'readback': json.loads(t.private_file(args.source_dir/'readback-1-0-result.json'))}
    files = {n: (ROOT/path).read_bytes() for n, path in PATHS.items()}
    files.update({'monitor.tar': raw, 'monitor-proof.json': encoded(proof), 'helper.py': archive['helper.py'],
                  'inspector.py': archive['inspector.py'], 'known_hosts': monitor['known_hosts'],
                  'reference.py': monitor['reference.py']})
    now = int(time.time()); spec = {k: old[k] for k in ('hostname', 'boot_id', 'kernel', 'endpoints', 'old_ipv4')}
    spec.update(schema=1, purpose='runtime-revalidation', operation_id=args.operation_id,
        stage='/var/lib/ntp-acquire-'+args.operation_id, source_stage=old['stage'], source_sha256=sha(raw),
        prepared_epoch=now, expires_epoch=now+86400, members={n: sha(v) for n, v in files.items()})
    files.update({'spec.json': encoded(spec), 'review.md': review(spec).encode()})
    files['manifest.json'] = encoded({n: sha(v) for n, v in files.items()}); validate(spec, files)
    os.umask(0o077); args.output.mkdir(mode=0o700)
    for name in ('spec.json', 'review.md', 'known_hosts'): (args.output/name).write_bytes(files[name])
    bundle = args.output/'runtime-revalidation.tar'
    with tarfile.open(bundle, 'w') as tar:
        for name, data in sorted(files.items()):
            item = tarfile.TarInfo(name); item.size = len(data); item.mode = 0o600; tar.addfile(item, io.BytesIO(data))
    checksum = sha(bundle.read_bytes()); prepare(bundle, checksum, current=True)
    result = {'bundle': str(bundle), 'sha256': checksum, 'target': spec['hostname'],
              'expires_epoch': spec['expires_epoch'], 'execution_authorized': False}
    t.write_new(args.output/'sealing.json', result); return result


def execute(args):
    os.umask(0o077); bundle = args.bundle.absolute(); spec, files = prepare(bundle, args.sha256, current=args.mode == 'start')
    root = bundle.parent; c = frozen(files['controller.py']); t = frozen(files['transport.py']); proofs = None
    if not os.environ.get('SSH_AUTH_SOCK'): raise ValueError('existing SSH agent required before registering execution')
    if args.mode == 'start':
        if not spec['prepared_epoch']-300 <= time.time() < spec['expires_epoch']-190: raise ValueError('start window expired')
    elif json.loads(t.private_file(root/'start-execution.json'))['bundle_sha256'] != args.sha256:
        raise ValueError('registered start required')
    if args.mode == 'cleanup':
        receipt = json.loads(t.private_file(root/'acceptance.json'))
        if receipt['bundle_sha256'] != args.sha256 or receipt['state'] not in ('runtime_validated', 'validation_held'):
            raise ValueError('matching terminal receipt required')
        proofs = {'report_sha256': receipt['report_sha256']}
    label = args.mode+('-'+str(args.attempt) if args.mode == 'readback' else '')
    t.write_new(root/(label+'-execution.json'), {'epoch': int(time.time()), 'bundle_sha256': args.sha256})
    endpoints = spec['endpoints'] if args.mode == 'readback' else spec['endpoints'][:1]
    results = {e: c.request(t, root, spec, files, args.sha256, args.mode, label+'-'+str(i), e, proofs) for i, e in enumerate(endpoints)}
    if args.mode == 'readback':
        receipt = frozen(files['stage.py']).terminal(spec, args.sha256, results); path = root/'acceptance.json'
        if path.exists():
            if json.loads(t.private_file(path)) != receipt: raise ValueError('terminal receipt conflict')
        else: t.write_new(path, receipt)
    return {'mode': args.mode, 'phases': {k: v['phase'] for k, v in results.items()}}


def main():
    if sys.argv[1:] == ['worker']:
        root = Path(__file__).resolve().parent; spec = json.loads((root/'spec.json').read_bytes())
        files = {n: (root/n).read_bytes() for n in spec['members']}
        files.update({'spec.json': encoded(spec), 'manifest.json': b'', 'review.md': b''})
        validate(spec, files); h = protected(spec, files)
        def expired(*args): raise TimeoutError('revalidation worker bound')
        signal.signal(signal.SIGALRM, expired); signal.alarm(180)
        try: result = capture(h, spec, files)
        except BaseException as error: result = {'phase': 'validation_held', 'error': str(error)[:500], 'time_service_accepted': False}
        finally: signal.alarm(0)
        write_report(h, root, files, result)
        return
    parser = argparse.ArgumentParser(description=__doc__); sub = parser.add_subparsers(dest='action', required=True)
    p = sub.add_parser('seal'); p.add_argument('--source-dir', type=Path, required=True); p.add_argument('--source-sha256', required=True)
    p.add_argument('--recovered-attempt', type=int, choices=range(1, 61))
    p.add_argument('--operation-id', required=True); p.add_argument('--output', type=Path, required=True)
    p = sub.add_parser('execute'); p.add_argument('--bundle', type=Path, required=True); p.add_argument('--sha256', required=True)
    p.add_argument('--mode', choices=('start', 'readback', 'cleanup'), required=True); p.add_argument('--attempt', type=int, choices=(1, 2, 3), default=1)
    args = parser.parse_args(); print(json.dumps(seal(args) if args.action == 'seal' else execute(args), sort_keys=True))


if __name__ == '__main__': main()
