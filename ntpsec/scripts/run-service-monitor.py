#!/usr/bin/python3
"""Seal an independent PPS-first activation and continuous-monitor operation."""
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
import tarfile
import time
import types

ROOT = Path(__file__).resolve().parents[1]
PATHS = {'pps-checker.py': 'scripts/check-pps.py', 'hardware-checker.py': 'scripts/host-configuration-stage.py',
    'controller.py': 'scripts/run-service-monitor.py', 'stage.py': 'scripts/service-monitor-stage.py',
    'base-stage.py': 'scripts/service-cutover-stage.py', 'base-controller.py': 'scripts/run-service-cutover.py',
    'transport.py': 'scripts/run-foundation-preflight.py', 'client.py': 'scripts/check-time-client.py',
    'measure.py': 'scripts/measure-time-service.py', 'timeservice.py': 'scripts/timeservice.py',
    'pps-startup.py': 'scripts/pps-startup.py', 'gpsd-pairing.py': 'scripts/gpsd-pairing.py',
    'runtime-continuity.py': 'scripts/runtime-continuity.py',
    'revalidation-controller.py': 'scripts/run-runtime-revalidation.py',
    'ntp.conf': 'configs/j2-svntp1-ntp.conf', 'recipe.json': 'configs/service-cutover-recipe.json',
    'monitor-policy.json': 'configs/pps-monitor-policy.json', 'leap-seconds.list': 'configs/leap-seconds.list',
    'service-template': 'templates/timeservice.service', 'avahi.conf': 'templates/avahi-ntp.conf',
    'ntpleapfetch.service': 'templates/ntpleapfetch-j2.service', 'ntpleapfetch.timer': 'templates/ntpleapfetch.timer',
    'tests.py': 'tests/test_service_monitor.py', 'startup-tests.py': 'tests/test_pps_startup.py',
    'revalidation-tests.py': 'tests/test_runtime_revalidation.py',
    'architecture.md': 'docs/ntp-architecture-deployment-plan-v1.0.md',
    'operations.md': 'docs/OPERATIONS.md', 'history.md': 'HISTORY.md'}
REFERENCE = ('reference.py', 'reference.tar', 'reference-report.json', 'reference-receipt.json',
             'reference-cleanup.json', 'receiver-runtime.json', 'known_hosts')
EXTRA = {*REFERENCE, 'restoration.tar', 'restoration-proof.json', 'timeservice.json',
         'timeservice.service', 'fault.service', 'revalidation.tar', 'revalidation-proof.json'}
MODES = ('start', 'handoff', 'observe', 'readback', 'recover', 'cleanup')
FAULT_UNIT = 'ntp-monitor-recovery.service'
SAFETY = ('bootstrap_stopped', 'pair_running', 'same_supervisor', 'no_restarts',
          'no_overrides', 'credentials', 'journal_health')


def encoded(value): return (json.dumps(value, sort_keys=True)+'\n').encode()
def sha(raw): return hashlib.sha256(raw).hexdigest()


def load(path):
    spec = importlib.util.spec_from_file_location('monitor_'+path.stem.replace('-', '_'), path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def frozen(raw):
    ns = {'__name__': 'sealed_monitor_reference', '__file__': '/sealed/reference.py'}
    exec(compile(raw, 'sealed-reference', 'exec'), ns)
    return types.SimpleNamespace(**ns)


def unpack(raw):
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        members = archive.getmembers()
        if len(members) > 100 or len({m.name for m in members}) != len(members):
            raise ValueError('unique bounded bundle members required')
        if any(not m.isfile() or '/' in m.name or m.size > 64*1024**2 for m in members):
            raise ValueError('regular bounded flat bundle required')
        if sum(m.size for m in members) > 96*1024**2:
            raise ValueError('bundle size bound')
        files = {m.name: archive.extractfile(m).read() for m in members}
        if 'manifest.json' in files and json.loads(files['manifest.json']) != {n: sha(v) for n, v in files.items() if n != 'manifest.json'}:
            raise ValueError('archive manifest mismatch')
        return files


def restoration(files):
    archive = unpack(files['restoration.tar'])
    validator = frozen(archive['stage.py']); spec = json.loads(archive['spec.json'])
    validator.validate(spec, archive)
    proof = json.loads(files['restoration-proof.json'])
    if set(proof) != {'acceptance', 'readbacks', 'cleanup'} or len(proof['readbacks']) != 2:
        raise ValueError('closed restoration proof required')
    first, second = proof['readbacks']
    if first != second or first['spec_sha256'] != sha(archive['spec.json']):
        raise ValueError('matching restoration readbacks required')
    result = first['result']
    receipt = validator.terminal(spec, sha(files['restoration.tar']), dict.fromkeys(spec['endpoints'], result))
    if receipt != proof['acceptance'] or receipt['state'] != 'restoration_verified':
        raise ValueError('accepted restoration continuation required')
    if proof['cleanup'] != {'spec_sha256': sha(archive['spec.json']), 'result': {
            'phase': 'cleaned', 'report_sha256': receipt['report_sha256'],
            'source_preserved': True, 'evidence_preserved': True}}:
        raise ValueError('accepted restoration closure required')
    source = unpack(archive['source.tar'])
    return spec, archive, result, source


def revalidation(files):
    controller = frozen(files['revalidation-controller.py']); archive = unpack(files['revalidation.tar'])
    spec = json.loads(archive['spec.json']); controller.validate(spec, archive)
    proof = json.loads(files['revalidation-proof.json']); first, second = proof['readbacks']
    if (set(proof) != {'acceptance', 'readbacks', 'cleanup'} or first != second
            or first['spec_sha256'] != sha(archive['spec.json'])):
        raise ValueError('matching runtime revalidation readbacks required')
    report = first['result']
    receipt = controller.terminal(spec, sha(files['revalidation.tar']), dict.fromkeys(spec['endpoints'], report))
    if (receipt != proof['acceptance'] or receipt['state'] != 'runtime_validated'
            or proof['cleanup'] != {'spec_sha256': sha(archive['spec.json']), 'result': {
                'phase': 'cleaned', 'evidence_preserved': True, 'report_sha256': receipt['report_sha256']}}
            or archive['continuity.py'] != files['runtime-continuity.py']
            or archive['hardware-checker.py'] != files['hardware-checker.py']
            or archive['pps-checker.py'] != files['pps-checker.py']
            or archive['stage.py'] != files['revalidation-controller.py']):
        raise ValueError('accepted closed revalidation and matching continuity checker required')
    origin = unpack(archive['monitor.tar'])
    if any(files[n] != origin[n] for n in (*REFERENCE, 'restoration.tar', 'restoration-proof.json')):
        raise ValueError('revalidated runtime/restoration provenance drift')
    return spec, archive, report


def rendered(spec, files):
    recipe = json.loads(files['recipe.json'])
    recipe['recovery_seconds'] = 600
    recipe['timeservice']['pps_startup'] = json.loads(files['monitor-policy.json'])
    recipe['timeservice']['pps_monitor_evidence'] = spec['stage']+'/startup-monitor.json'
    service = files['service-template']
    if service.count(b'\nRestart=on-failure\n') != 1 or b'OnFailure=' in service:
        raise ValueError('known service template required')
    service = service.replace(b'\n[Service]\n', ('\nOnFailure='+FAULT_UNIT+'\n\n[Service]\n').encode())
    service = service.replace(b'\nRestart=on-failure\n', b'\nRestart=no\nLimitFSIZE=8388608\n')
    fault = ('[Unit]\nDescription=Restore the approved time-service monitor baseline\n'
             '[Service]\nType=oneshot\nUMask=0077\nTimeoutStartSec=240\n'
             'ExecStart=/usr/bin/python3 -I -B '+spec['stage']+'/stage.py worker recover\n').encode()
    return recipe, service, fault


def validate(spec, files):
    if set(files) != set(PATHS)|EXTRA|{'spec.json', 'manifest.json', 'review.md'}:
        raise ValueError('closed monitor bundle required')
    restored, archive, report, source = restoration(files)
    fresh, _, current = revalidation(files)
    if (spec['schema'] != 2 or spec['purpose'] != 'service-monitor'
            or not re.fullmatch(r'[a-z][a-z0-9-]{0,47}', spec['operation_id'])
            or spec['stage'] != '/var/lib/ntp-acquire-'+spec['operation_id']
            or spec['apply_unit'] != 'ntp-monitor-'+spec['operation_id']
            or spec['recovery_unit'] != spec['apply_unit']+'-watchdog'
            or any(spec[k] != restored[k] for k in ('hostname', 'boot_id', 'kernel', 'endpoints', 'old_ipv4'))
            or spec['restoration_sha256'] != sha(files['restoration.tar'])
            or any(spec[k] != fresh[k] for k in ('hostname', 'boot_id', 'kernel', 'endpoints', 'old_ipv4'))
            or not fresh['prepared_epoch'] <= spec['prepared_epoch'] < spec['expires_epoch'] <= fresh['expires_epoch']
            or spec['expires_epoch'] > current['epoch']+86400
            or not 0 < spec['expires_epoch']-spec['prepared_epoch'] <= 86400
            or spec['members'] != {n: sha(files[n]) for n in set(PATHS)|EXTRA}):
        raise ValueError('monitor identity/window/input binding')
    if any(files[n] != source[n] for n in REFERENCE):
        raise ValueError('historical receiver provenance changed')
    recipe, service, fault = rendered(spec, files)
    if (spec['recipe'] != recipe or files['timeservice.json'] != encoded(recipe['timeservice'])
            or files['timeservice.service'] != service or files['fault.service'] != fault
            or recipe['timeservice']['pps_startup'] != frozen(files['pps-startup.py']).MONITOR_POLICY):
        raise ValueError('closed continuous-monitor profile required')
    if (recipe['hostname'] != spec['hostname'] or recipe['apply_max_seconds'] != 120
            or recipe['acceptance_reserve_seconds'] != 60 or recipe['ntp_uid'] != 999 or recipe['ntp_gid'] != 985
            or recipe['maximum_pps_offset_ms'] != 5 or recipe['maximum_pps_jitter_ms'] != 1
            or recipe['timeservice']['gpsd'] != ['/usr/local/sbin/gpsd', '-b', '-N', '-n', '-s', '115200', '/dev/serial0', '/dev/pps0']
            or recipe['timeservice']['ntpd'] != ['/usr/local/sbin/ntpd', '-n', '-m', '-c', '/etc/ntp.conf', '-u', 'ntp:ntp']
            or recipe['timeservice']['startup_gate'] != {'timeout_seconds': 30, 'matching_samples_per_source': 5, 'units': {'TOFF': 'NTP0', 'PPS': 'NTP2'}}):
        raise ValueError('closed hardware, credentials and receiver-write boundary required')
    return restored, archive, report, source


def payload(spec, files, mode, proofs=None):
    if mode not in MODES: raise ValueError('closed monitor mode')
    body = {n: base64.b64encode(files[n]).decode() for n in spec['members']}
    return ('import base64,json\nfiles={n:base64.b64decode(v) for n,v in '+repr(body)+'.items()}\n'
            'spec=json.loads('+repr(json.dumps(spec))+')\n'
            'ns={"__name__":"sealed_monitor","__file__":spec["stage"]+"/stage.py"}\n'
            'exec(compile(files["stage.py"],"sealed-monitor","exec"),ns)\n'
            'status=0\ntry: result=ns["entry"](spec,files,'+repr(mode)+','+repr(proofs)+')\n'
            'except BaseException as e: status=2; result={"phase":"held","error":str(e)[:500]}\n'
            'print(json.dumps({"spec_sha256":ns["sha"](ns["encoded"](spec)),"result":result},sort_keys=True))\n'
            'print("CUTOVER_EXIT_STATUS="+str(status))\nraise SystemExit(status)\n').encode()


def review(spec):
    end = datetime.fromtimestamp(spec['expires_epoch']-600, timezone.utc).isoformat()
    return f'''# PPS-first start-and-monitor execution review

Target **{spec['hostname']}**, operation `{spec['operation_id']}`.
Start before **{end}** so the installation watchdog fits the execution window.

One installation and startup bound to a newly accepted read-only runtime
revalidation, followed by fresh preflight that verifies target,
boot, protected files, native binaries, packages/Python, accounts, loader cache,
network, hardware, UART/SHM state and the retained restoration receipt/closure.
Historical receiver and cutover artifacts remain unchanged. Their expired
execution windows are not renewed: the separately accepted revalidation and this independently approved operation must
revalidate their factual prerequisites before mutation. Any drift stops the stage.

Root-owned 0700 staging binds all non-secret inputs. Preserve backups before
installing the rendered service/configuration and fault-recovery unit. Arm an
independent **600-second installation watchdog** before changes. Require the
existing bounded receiver pairing gate and localhost ntpd functionality.

Before handing off, require both pinned SSH endpoints, unchanged protected state,
correct daemon identities and credentials, a live startup monitor, workstation
IPv4/IPv6 NTP protocol responses and denied administrative queries. Unsynchronized
responses are allowed for this structural check; this is not timing acceptance.
No mDNS or stratum-1 quality claim is made during bootstrap. Retain service units
disabled for boot; keep the baseline timesyncd enablement, but stop it for this run.
Warm restart, reboot persistence, leap-fetch activation and final client/mDNS
timing acceptance remain separate work.

Only a successful structural handoff cancels the installation watchdog. Keep
PPS-first isolation indefinitely without a timing-quality shutdown deadline.
Monitor every 30 seconds, promote selectable NMEA and three NTS sources once
after qualification, then monitor every 300 seconds when ready. Degradation
resumes the faster cadence. Maintain bounded operation-owned evidence; no packet
capture or receiver writes. Daemon/promotion faults trigger baseline recovery.
The monitor checks a maximum of 128 statistics entries and 8 MiB of unique
statistics data each interval; the service also has an 8 MiB per-file limit.
A storage/type violation is a recovery fault, not a timing-quality deadline.

Approval includes up to **60 numbered observation captures** at the monitor's
cadence, conditional dual-stack readbacks, one explicit operator recovery and
post-recovery transient cleanup. Evidence and the active operation stage remain
preserved; no source-stage deletion. Readback/cleanup never accept timing.
An interrupted or uncertain start/handoff is never replayed. Inspect retained
state; the watchdog remains responsible for an incomplete installation.

Recovery rechecks actual hardware/runtime facts after any historical receipt
expiry, without rewriting old timestamps or relaxing identity/content checks.
It stops the pair, restores files/UART and baseline clock service, verifies
continuity and preserves terminal monitor records. A recovery hold requires
review; do not rearm, replay or clean a held stage. Monitoring has no expiry
shutdown; later readbacks/recovery address only this already-started operation.

From the repository root, use `python3 -I -B ntpsec/scripts/run-service-monitor.py
execute --bundle <review-directory>/service-monitor.tar
--sha256 <approved-sha256> --mode <mode>` (one shell command).
Use `start` once, then `handoff` only after observing startup. Retrieve stored
state with `readback --attempt N`; capture fresh status using `observe --attempt N`
with sequential numbers 1 through 60 and the agreed interval. An uncertain
observation is read back before deciding anything further. `recover` is the
explicit restoration path; `cleanup` follows matching recovered readbacks.
Do not replay submitted mutations. All transport uses the sealed pinned host key.
'''


def seal(args):
    transport = load(ROOT/'scripts/run-foundation-preflight.py')
    raw = transport.private_file(args.restoration_dir/'restoration.tar', 64*1024**2)
    if sha(raw) != args.restoration_sha256: raise ValueError('restoration archive digest')
    archive = unpack(raw); restored = json.loads(archive['spec.json'])
    source = unpack(archive['source.tar'])
    proof = {'acceptance': json.loads(transport.private_file(args.restoration_dir/'acceptance.json')),
             'readbacks': [json.loads(transport.private_file(args.restoration_dir/f'readback-1-{i}-result.json', 32*1024**2)) for i in (0, 1)],
             'cleanup': json.loads(transport.private_file(args.restoration_dir/'cleanup-0-result.json'))}
    files = {n: (ROOT/path).read_bytes() for n, path in PATHS.items()}
    files.update({n: source[n] for n in REFERENCE})
    files.update({'restoration.tar': raw, 'restoration-proof.json': encoded(proof)})
    fresh_raw = transport.private_file(args.revalidation_dir/'runtime-revalidation.tar', 64*1024**2)
    if sha(fresh_raw) != args.revalidation_sha256: raise ValueError('revalidation archive digest')
    fresh_proof = {'acceptance': json.loads(transport.private_file(args.revalidation_dir/'acceptance.json')),
        'readbacks': [json.loads(transport.private_file(args.revalidation_dir/f'readback-{args.revalidation_attempt}-{i}-result.json', 32*1024**2)) for i in (0, 1)],
        'cleanup': json.loads(transport.private_file(args.revalidation_dir/'cleanup-0-result.json'))}
    files.update({'revalidation.tar': fresh_raw, 'revalidation-proof.json': encoded(fresh_proof)})
    fresh, _, current = revalidation(files)
    now = int(time.time())
    spec = {k: restored[k] for k in ('hostname', 'boot_id', 'kernel', 'endpoints', 'old_ipv4')}
    spec.update(schema=2, purpose='service-monitor', operation_id=args.operation_id,
                stage='/var/lib/ntp-acquire-'+args.operation_id, apply_unit='ntp-monitor-'+args.operation_id,
                recovery_unit='ntp-monitor-'+args.operation_id+'-watchdog', prepared_epoch=now,
                expires_epoch=min(now+86400, fresh['expires_epoch'], current['epoch']+86400), restoration_sha256=sha(raw))
    if spec['expires_epoch']-now < 3600:
        raise ValueError('insufficient fresh revalidation window before sealing')
    recipe, service, fault = rendered(spec, files); spec['recipe'] = recipe
    files.update({'timeservice.json': encoded(recipe['timeservice']), 'timeservice.service': service, 'fault.service': fault})
    spec['members'] = {n: sha(v) for n, v in files.items()}
    files.update({'spec.json': encoded(spec), 'review.md': review(spec).encode()})
    files['manifest.json'] = encoded({n: sha(v) for n, v in files.items()})
    validate(spec, files)
    if spec['expires_epoch']-now < 3600: raise ValueError('insufficient new operation window')
    os.umask(0o077); args.output.mkdir(mode=0o700)
    for name, data in files.items():
        with (args.output/name).open('xb') as stream: stream.write(data)
    bundle = args.output/'service-monitor.tar'
    with tarfile.open(bundle, 'w') as tar:
        for name, data in sorted(files.items()):
            info = tarfile.TarInfo(name); info.mode = 0o600; info.size = len(data); info.mtime = 0
            tar.addfile(info, io.BytesIO(data))
    prepare(bundle, sha(bundle.read_bytes()))
    result = {'bundle': str(bundle), 'sha256': sha(bundle.read_bytes()), 'target': spec['hostname'],
              'start_before_epoch': spec['expires_epoch']-600, 'execution_authorized': False}
    transport.write_new(args.output/'sealing.json', result)
    return result


def prepare(bundle, checksum, require_current=True):
    transport = load(ROOT/'scripts/run-foundation-preflight.py')
    raw = transport.private_file(bundle, 96*1024**2)
    if sha(raw) != checksum: raise ValueError('approved monitor archive digest')
    files = unpack(raw); spec = json.loads(files['spec.json']); frozen(files['controller.py']).validate(spec, files)
    if require_current and any(files.get(n) != (ROOT/path).read_bytes() for n, path in PATHS.items()):
        raise ValueError('current monitor input drift')
    if require_current and any(transport.private_file(bundle.parent/name, 96*1024**2) != files[name]
                               for name in ('spec.json', 'review.md')):
        raise ValueError('local monitor review/spec drift')
    if require_current and time.time()+600 >= spec['expires_epoch']:
        raise ValueError('fresh prerequisite window cannot cover installation watchdog')
    if transport.private_file(bundle.parent/'known_hosts', 4096) != files['known_hosts']:
        raise ValueError('pinned host key drift')
    return spec, files


def execute(args):
    os.umask(0o077)
    spec, files = prepare(args.bundle.absolute(), args.sha256, require_current=args.mode == 'start')
    directory = args.bundle.absolute().parent
    if not os.environ.get('SSH_AUTH_SOCK'):
        raise ValueError('existing SSH agent required before registering execution')
    transport = frozen(files['transport.py'])
    base = frozen(files['base-controller.py'])
    # Frozen functions retain their own globals rather than the namespace wrapper.
    base.request.__globals__['payload'] = payload
    if args.mode == 'start':
        if not spec['prepared_epoch']-300 <= time.time() < spec['expires_epoch']-600:
            raise ValueError('installation window expired')
    elif json.loads(transport.private_file(directory/'start-execution.json'))['bundle_sha256'] != args.sha256:
        raise ValueError('registered start required')
    numbered = args.mode in ('observe', 'readback')
    label = args.mode+('-'+str(args.attempt) if numbered else '')
    if args.mode == 'cleanup':
        receipt = json.loads(transport.private_file(directory/'recovered-receipt.json'))
        if receipt['bundle_sha256'] != args.sha256 or receipt['state'] != 'recovered':
            raise ValueError('matching recovered readback receipt required')
    transport.write_new(directory/(label+'-execution.json'), {'bundle_sha256': args.sha256, 'epoch': int(time.time())})
    request = lambda mode, stem, endpoint, proof=None: base.request(transport, directory, spec, files, args.sha256, mode, stem, endpoint, proof)
    if args.mode == 'handoff':
        proof = {endpoint: request('readback', label+'-proof-'+str(i), endpoint) for i, endpoint in enumerate(spec['endpoints'])}
        if any(v['phase'] != 'observing' for v in proof.values()): raise ValueError('observing candidate required')
        proof['client'] = frozen(files['client.py']).check(spec, sha(files['spec.json']), structural=True)
        transport.write_new(directory/'client-structural-proof.json', proof['client'])
        results = {spec['endpoints'][0]: request('handoff', label+'-0', spec['endpoints'][0], proof)}
    else:
        endpoints = spec['endpoints'] if args.mode == 'readback' else spec['endpoints'][:1]
        proof = {'attempt': args.attempt} if args.mode == 'observe' else None
        results = {e: request(args.mode, label+'-'+str(i), e, proof) for i, e in enumerate(endpoints)}
    if args.mode == 'readback':
        if len({sha(encoded(v)) for v in results.values()}) != 1: raise ValueError('matching dual-stack readback required')
        state = next(iter(results.values()))
        if state['phase'] in ('monitoring', 'recovered'):
            name = 'recovered-receipt.json' if state['phase'] == 'recovered' else label+'-receipt.json'
            receipt = {'state': state['phase'], 'bundle_sha256': args.sha256,
                       'spec_sha256': sha(files['spec.json']), 'state_sha256': sha(encoded(state)), 'time_service_accepted': False}
            path = directory/name
            if path.exists():
                if json.loads(transport.private_file(path)) != receipt: raise ValueError('readback receipt conflict')
            else: transport.write_new(path, receipt)
    return {'mode': args.mode, 'phases': {e: v['phase'] for e, v in results.items()}}


def main():
    parser = argparse.ArgumentParser(description=__doc__); sub = parser.add_subparsers(dest='action', required=True)
    p = sub.add_parser('seal'); p.add_argument('--restoration-dir', type=Path, required=True)
    p.add_argument('--restoration-sha256', required=True); p.add_argument('--operation-id', required=True)
    p.add_argument('--revalidation-dir', type=Path, required=True); p.add_argument('--revalidation-sha256', required=True)
    p.add_argument('--revalidation-attempt', type=int, choices=(1, 2, 3), required=True)
    p.add_argument('--output', type=Path, required=True)
    p = sub.add_parser('execute'); p.add_argument('--bundle', type=Path, required=True)
    p.add_argument('--sha256', required=True); p.add_argument('--mode', choices=MODES, required=True)
    p.add_argument('--attempt', type=int, choices=range(1, 61), default=1)
    args = parser.parse_args(); print(json.dumps(seal(args) if args.action == 'seal' else execute(args), sort_keys=True))


if __name__ == '__main__': main()
