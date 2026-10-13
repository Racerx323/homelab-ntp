#!/usr/bin/python3
"""Seal offline and transport one static runtime discovery after accepted native installation."""
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
    spec = importlib.util.spec_from_file_location('discovery_' + name.replace('-', '_'), ROOT / 'scripts' / name)
    result = importlib.util.module_from_spec(spec); spec.loader.exec_module(result)
    return result


c = module('run-foundation-preflight.py')
s = module('foundation-preflight-stage.py')
i = module('inspect-runtime.py')
INPUTS = s.INPUTS | s.RUNTIME_INPUTS
EXTRAS = {'launcher.py', 'stage.py', 'spec.json', 'known_hosts', 'review.md', 'tests.py',
          'manifest.json', 'transport-controller.py', 'installation-assets.json',
          'architecture.md', 'operations.md', 'history.md'}


def validate_bindings(files, spec):
    release, build, baseline, state = i.accepted_inputs(files, module('inspect-source-destinations.py'))
    if (spec['operation'] != 'runtime-discovery' or spec['hostname'] != release['hostname']
            or spec['kernel'] != release['kernel']
            or spec['installation_bundle_sha256'] != json.loads(files['installation-bundle-sha256.json'])
            or spec['ssh'] != json.loads(files['installation-spec.json'])['ssh']
            or spec['configuration_requirements'] != list(i.REQUIREMENTS)
            or spec['reference_hashes'].keys() != {'architecture', 'operations', 'history'}
            or any(h != c.sha(files[label+'.md']) for label,h in spec['reference_hashes'].items())
            or spec['asset_manifest_sha256'] != c.sha(files['installation-assets.json'])):
        raise ValueError('runtime target/installation/recipe/reference binding mismatch')
    return release, build, baseline, state


def prepare(bundle, checksum):
    raw = c.private_file(bundle)
    if not re.fullmatch(r'[a-f0-9]{64}', checksum) or c.sha(raw) != checksum:
        raise ValueError('approved runtime bundle hash mismatch')
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:') as archive:
        members = archive.getmembers()
        names = [m.name for m in members]
        if (len(names) != len(set(names)) or set(names) != INPUTS | EXTRAS
                or any(not m.isfile() or m.size > 2 * 1024**2 for m in members)):
            raise ValueError('fixed runtime archive membership/type/size required')
        files = {m.name: archive.extractfile(m).read() for m in members}
    manifest = json.loads(files['manifest.json'])
    if (set(manifest) != set(files) - {'manifest.json'}
            or any(c.sha(files[n]) != h for n,h in manifest.items())
            or files['launcher.py'] != Path(__file__).read_bytes()
            or files['transport-controller.py'] != (ROOT / 'scripts/run-foundation-preflight.py').read_bytes()):
        raise ValueError('runtime member/launcher/transport drift')
    spec = json.loads(files['spec.json']); c.validate_spec(spec)
    if (set(spec['members']) != INPUTS or any(c.sha(files[n]) != h for n,h in spec['members'].items())
            or c.host_key(files['known_hosts'], spec['ssh']['host']) != spec['ssh']['fingerprint']
            or c.private_file(bundle.parent/'known_hosts', 4096) != files['known_hosts']
            or bundle.parent.stat().st_uid != os.getuid() or bundle.parent.stat().st_mode & 0o077):
        raise ValueError('runtime inputs/key/private evidence binding mismatch')
    validate_bindings(files, spec)
    for mode in ('collect', 'readback', 'cleanup'):
        compile(c.payload(spec, files, spec['prepared_epoch'], mode), 'sealed-runtime-payload', 'exec')
    return spec, files


def seal(args):
    epoch = int(time.time())
    original = c.private_file(args.installation_dir/'source-install.tar')
    if c.sha(original) != args.installation_sha256:
        raise ValueError('accepted native installation archive hash mismatch')
    native = module('run-source-install.py')
    with tarfile.open(fileobj=io.BytesIO(original), mode='r:') as archive:
        members=archive.getmembers(); names=[m.name for m in members]
        if (set(names) != native.INPUTS | native.EXTRAS or len(names) != len(set(names))
                or any(not m.isfile() or m.size > 2 * 1024**2 for m in members)):
            raise ValueError('accepted native archive input set/type/size mismatch')
        old = {m.name: archive.extractfile(m).read() for m in members}
    manifest=json.loads(old['manifest.json'])
    if set(manifest) != set(old)-{'manifest.json'} or any(c.sha(old[n]) != h for n,h in manifest.items()):
        raise ValueError('accepted native archive member hashes differ')
    files = {n: old[n] for n in s.DESTINATION_INPUTS - {'inspect-source-destinations.py'}}
    for name in s.INPUTS - {'recipe.json'}:
        files[name] = (ROOT/'scripts'/name).read_bytes()
    files['recipe.json'] = (ROOT/'configs/foundation-recipe.json').read_bytes()
    for name in ('inspect-source-destinations.py', 'inspect-runtime.py', 'timeservice.py'):
        files[name] = (ROOT/'scripts'/name).read_bytes()
    files['runtime-recipe.json'] = (ROOT/'configs/runtime-discovery-recipe.json').read_bytes()
    for name in ('timeservice.service', 'timeservice.json.example'):
        files[name]=(ROOT/'templates'/name).read_bytes()
    files['installation-spec.json']=old['spec.json']
    files['installation-bundle-sha256.json']=c.encoded(args.installation_sha256)
    for member,name in (('installation-acceptance.json','acceptance.json'), ('installation-readback.json','readback-result.json')):
        files[member]=c.private_file(args.installation_dir/name)
    cleanup=json.loads(c.private_file(args.installation_dir/'cleanup-result.json'))
    if (cleanup['bundle_sha256'] != args.installation_sha256 or cleanup['worker_status'] != 0
            or cleanup['transport_exit_status'] != 0 or cleanup['report']['state'] != 'installation_payload_removed'):
        raise ValueError('accepted installation payload cleanup required')
    files.update({'launcher.py': Path(__file__).read_bytes(), 'stage.py': (ROOT/'scripts/foundation-preflight-stage.py').read_bytes(),
        'transport-controller.py': (ROOT/'scripts/run-foundation-preflight.py').read_bytes(),
        'tests.py': (ROOT/'tests/test_runtime_discovery.py').read_bytes(), 'known_hosts': old['known_hosts'],
        'installation-assets.json': (ROOT/'configs/installation-assets.json').read_bytes()})
    release, build, _, _ = i.accepted_inputs(files, module('inspect-source-destinations.py'))
    mirror = (ROOT/'configs/accepted-source-release.json').read_bytes()
    if json.loads(files['release.json']) != json.loads(mirror):
        raise ValueError('accepted release mirror drift')
    module('clockmaker.py').read_release(ROOT/'configs/accepted-source-release.json',c.sha(mirror))
    inventory={}
    for line in (ROOT/'configs/accepted-packages.tsv').read_text().splitlines():
        name, version, status=line.split('\t')
        if name in inventory: raise ValueError('duplicate accepted inventory')
        inventory[name]=[version,status]
    if inventory != build['inventory']: raise ValueError('accepted inventory mirror drift')
    for label,path in (('architecture','docs/ntp-architecture-deployment-plan-v1.0.md'),
                       ('operations','docs/OPERATIONS.md'),('history','HISTORY.md')):
        files[label+'.md']=(ROOT/path).read_bytes()
    spec={'schema':1,'operation':'runtime-discovery','operation_id':args.operation_id,
        'stage':'/var/lib/ntp-preflight-'+args.operation_id,'hostname':release['hostname'],'kernel':release['kernel'],
        'ssh':json.loads(old['spec.json'])['ssh'], 'asset_manifest_sha256':c.sha(files['installation-assets.json']),
        'installation_bundle_sha256':args.installation_sha256,
        'configuration_requirements':list(i.REQUIREMENTS),
        'reference_hashes':{label:c.sha(files[label+'.md']) for label in ('architecture','operations','history')},
        'prepared_epoch':epoch,'expires_epoch':epoch+86400,'members':{n:c.sha(files[n]) for n in sorted(INPUTS)}}
    c.validate_spec(spec); validate_bindings(files,spec)
    files['spec.json']=c.encoded(spec)
    files['review.md']=(f'# Read-only runtime discovery review\n\n'
        f'Target: {spec["hostname"]}, ama UID/GID 1000, {spec["ssh"]["host"]}; aarch64 kernel {spec["kernel"]}.\n'
        f'Pinned ED25519: {spec["ssh"]["fingerprint"]}.\nOperation: {args.operation_id}.\n'
        f'Capture expires: {datetime.fromtimestamp(spec["expires_epoch"],timezone.utc).isoformat()}.\n'
        f'Accepted installation bundle SHA-256: {args.installation_sha256}.\n'
        f'Accepted installation receipt SHA-256: {spec["members"]["installation-acceptance.json"]}.\n\n'
        f'One privileged read-only capture in exclusive root-owned 0700 staging `{spec["stage"]}`.\n'
        'Stage only hash-bound root-owned 0600 inputs; isolated Python -I -B via existing sudo.\n'
        f'Verify all {len(release["files"])} installed release entries twice with 64 MiB/file and 512 MiB/pass bounds,\n'
        'root ownership/modes, protected ancestors and exact accepted package/boot/Python/service continuity.\n'
        'Require no active ntpd/GPSD. Drift holds acceptance; never repair automatically.\n\n'
        'Capture bounded boot/time/loader configuration files and approved drop-ins, UART/PPS/RTC\n'
        'device metadata and sysfs names/paths/drivers, local account/group identifiers (no password fields),\n'
        'IP addresses/routes, NetworkManager profile identifiers/device state and time-service properties.\n'
        'Read every registered Ethernet profile by UUID with only connection,802-3-ethernet,ipv4,ipv6\n'
        'property groups; exclude Wi-Fi/802.1X/VPN groups and secrets. Require unchanged registry and\n'
        'Ethernet properties across capture. Include nobody/nogroup, boot serial/Bluetooth unit state\n'
        'and bounded disable-bt, pps-gpio and i2c-rtc overlay bytes/hashes. These are capabilities,\n'
        'not board wiring or permission to choose a GPIO/RTC overlay.\n'
        'Record isolated root Python search/scheme paths and effective PATH without importing application modules;\n'
        'this does not establish the runtime account or operator shell environment.\n'
        'Inspect linker cache with ldconfig -p and ELF dependencies with readelf -d; execute no installed\n'
        'application/module. Never open UART/PPS/RTC devices, send receiver commands, read shadow,\n'
        'request Wi-Fi secrets, change accounts/configuration/cache/packages/network/services or reboot.\n'
        'Missing optional device/configuration entries remain explicit unknowns; required query errors hold.\n'
        'Configuration readiness remains false until report review and separately prepared runtime validation.\n\n'
        'One conditional terminal readback validates report/spec hashes, full installed coverage and scope.\n'
        'Recovery is terminal readback only; a held/lost capture never authorizes resubmission or mutation.\n'
        'Without a terminal receipt, retain stage and streams for separately reviewed state inspection.\n'
        'Cleanup requires the retained terminal hash and exact stage membership; remove only this observation\n'
        'stage after validating every removable root-owned file. Preserve native installation journals and\n'
        'all prior executed evidence/source workspaces. Unexpected entries hold cleanup.\n\n'
        'Strict pinned SSH, no proxy/forwarding/multiplexing/local command; 420-second transport limit.\n'
        'Readback/cleanup remain available after capture expiry. No live contact occurred during preparation.\n'
        'Use `run-runtime-discovery.py execute --bundle /absolute/runtime-discovery.tar`\n'
        'with `--sha256 APPROVED_SHA256 --mode collect`, then same bundle/hash for `readback` and `cleanup`.\n'
        'Separate hash-bound approval authorizes capture/readback/cleanup only. Host configuration, loader\n'
        'validation and activation require their own later approval after reviewing observed inputs.\n').encode()
    files['manifest.json']=c.encoded({n:c.sha(v) for n,v in sorted(files.items())})
    os.umask(0o077); args.output.mkdir(mode=0o700)
    for name in ('known_hosts','spec.json','review.md'):(args.output/name).write_bytes(files[name])
    bundle=args.output/'runtime-discovery.tar'
    with tarfile.open(bundle,'w',format=tarfile.USTAR_FORMAT) as archive:
        for name,data in sorted(files.items()):
            member=tarfile.TarInfo(name);member.mode=0o600;member.size=len(data);member.mtime=epoch
            archive.addfile(member,io.BytesIO(data))
    result={'bundle':str(bundle),'sha256':c.sha(bundle.read_bytes()),'target':spec['hostname'],
        'expires_epoch':spec['expires_epoch'],'target_contact':False,'execution_authorized':False}
    prepare(bundle,result['sha256']); (args.output/'sealing.json').write_bytes(c.encoded(result))
    return result


def execute(args):
    bundle=args.bundle.absolute(); directory=bundle.parent; spec,files=prepare(bundle,args.sha256)
    epoch=int(time.time()); terminal_sha=None
    if args.mode=='collect' and not spec['prepared_epoch']-300 <= epoch < spec['expires_epoch']:
        raise ValueError('runtime capture window expired')
    if args.mode=='cleanup':
        retained=json.loads(c.private_file(directory/'readback-result.json'))
        if (retained['bundle_sha256'] != args.sha256 or retained['transport_exit_status'] != retained['worker_status']
                or retained['report']['state'] not in ('inspection_completed','inspection_held')):
            raise ValueError('bound terminal readback required before cleanup')
        terminal_sha=retained['report']['terminal_sha256']
    agent=os.environ.get('SSH_AUTH_SOCK')
    if not agent: raise ValueError('existing SSH agent required')
    argv=c.transport(directory,spec['ssh']['host'],spec['operation']); data=c.payload(spec,files,epoch,args.mode,terminal_sha)
    c.write_new(directory/(args.mode+'-execution.json'),{'state':'registered_before_submission',
        'bundle_sha256':args.sha256,'argv':argv,'payload_sha256':c.sha(data),'controller_epoch':epoch})
    with (directory/(args.mode+'.stdout')).open('xb') as stdout,(directory/(args.mode+'.stderr')).open('xb') as stderr:
        result=subprocess.run(argv,input=data,stdout=stdout,stderr=stderr,check=False,
            env={'PATH':'/usr/bin:/bin','LC_ALL':'C','SSH_AUTH_SOCK':agent})
    c.write_new(directory/(args.mode+'-transport.json'),{'exit_status':result.returncode})
    raw=c.private_file(directory/(args.mode+'.stdout'),16*1024**2)
    match=re.fullmatch(rb'(.*)\nPREFLIGHT_EXIT_STATUS=([02])\n',raw,re.S)
    if not match: raise ValueError('missing terminal marker; retain streams and never resubmit')
    report=json.loads(match[1]);status=int(match[2])
    record={'bundle_sha256':args.sha256,'report':report,'worker_status':status,'transport_exit_status':result.returncode,
        'stdout_sha256':c.sha(raw),'stderr_sha256':c.sha(c.private_file(directory/(args.mode+'.stderr')))}
    c.write_new(directory/(args.mode+'-result.json'),record)
    if result.returncode != status: raise ValueError('runtime transport/worker mismatch')
    if args.mode=='readback' and status==0 and report['state']=='inspection_completed':
        raw=base64.b64decode(report['inspection_base64'],validate=True)
        if c.sha(raw)!=report['inspection_sha256'] or report['spec_sha256']!=c.sha(files['spec.json']):
            raise ValueError('runtime report/spec hash mismatch')
        observed=json.loads(raw);release,build,baseline,expected=validate_bindings(files,spec)
        i.validate(observed,spec,release,build)
        if observed['observation'] != baseline or observed['installed_state'] != expected:
            raise ValueError('runtime accepted installation continuity mismatch')
        i.verify_parents(observed['parents'],i.native_parents(files))
        with (directory/'runtime.json').open('xb') as stream:stream.write(raw)
        c.write_new(directory/'acceptance.json',{'state':'runtime_discovery_accepted','bundle_sha256':args.sha256,
            'runtime_sha256':c.sha(raw),'installation_acceptance_sha256':spec['members']['installation-acceptance.json'],
            'release_sha256':spec['members']['release.json'],'configuration_ready':False,'activation_authorized':False})
    return {'mode':args.mode,'state':report.get('state'),'worker_status':status}


def main():
    os.umask(0o077);parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='action',required=True)
    seal_parser=sub.add_parser('seal');seal_parser.add_argument('--installation-dir',type=Path,required=True)
    seal_parser.add_argument('--installation-sha256',required=True);seal_parser.add_argument('--operation-id',required=True)
    seal_parser.add_argument('--output',type=Path,required=True)
    run=sub.add_parser('execute');run.add_argument('--bundle',type=Path,required=True);run.add_argument('--sha256',required=True)
    run.add_argument('--mode',choices=('collect','readback','cleanup'),required=True)
    args=parser.parse_args();result=seal(args) if args.action=='seal' else execute(args)
    print(json.dumps(result));return result.get('worker_status',0)


if __name__=='__main__':raise SystemExit(main())
