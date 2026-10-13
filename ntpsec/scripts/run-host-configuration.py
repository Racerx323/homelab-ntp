#!/usr/bin/python3
"""Prepare offline and control separate, single-use hardware or runtime prerequisite stages."""
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
    spec=importlib.util.spec_from_file_location('config_'+name.replace('-','_'),ROOT/'scripts'/name)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result


c=module('run-foundation-preflight.py')
n=module('run-host-network.py')
s=module('host-configuration-stage.py')
COMMON={'host-configuration-stage.py','host-network-stage.py','foundation-install.py',
        'inspect-source-destinations.py','clockmaker.py','baseline.json','release.json',
        'network-spec.json','network-acceptance.json','network-cleanup.json','host-recipe.json',
        'architecture.md','operations.md','history.md','installation-assets.json',
        'source-build-recipe.json','accepted-packages.tsv','accepted-source-release.json'}
HARDWARE={'config-candidate.txt','cmdline-candidate.txt'}
RUNTIME={'timeservice.py','timeservice-template.json','timeservice-template.service',
         'hardware-spec.json','hardware-bundle-sha256.json'}
EXTRAS={'launcher.py','transport-controller.py','known_hosts','spec.json','manifest.json','review.md','tests.py'}


def validate(files, spec):
    kind=spec['operation'];s.validate_recipe(kind,spec['host_recipe'])
    network=json.loads(files['network-spec.json']);receipt=json.loads(files['network-acceptance.json'])
    cleanup=json.loads(files['network-cleanup.json']);baseline=json.loads(files['baseline.json'])
    n.s.validate_spec(network)
    keys={'schema','operation','operation_id','stage','hostname','kernel','boot_id','ssh','old_ipv4','mac',
          'original_uuid','candidate_name','recipe','network_candidate_uuid','network_bundle_sha256',
          'network_spec_sha256','prepared_epoch','expires_epoch','host_recipe','reference_hashes','members',
          'hardware_prerequisite'}
    inputs=COMMON | (HARDWARE if kind=='hardware' else RUNTIME)
    if (set(spec)!=keys or spec['schema']!=1 or not re.fullmatch('[a-z][a-z0-9-]{0,47}',spec['operation_id'])
            or spec['stage']!='/var/lib/ntp-host-'+spec['operation_id']
            or set(spec['members'])!=inputs or any(c.sha(files[name])!=digest for name,digest in spec['members'].items())
            or not 0<spec['expires_epoch']-spec['prepared_epoch']<=86400
            or receipt['state']!='host_network_accepted' or receipt['hostname']!=spec['hostname']
            or receipt['bundle_sha256']!=spec['network_bundle_sha256'] or receipt['spec_sha256']!=c.sha(files['network-spec.json'])
            or receipt['candidate_uuid']!=spec['network_candidate_uuid']
            or receipt['checks'].keys()!=n.s.LABELS or any(v is not True for v in receipt['checks'].values())
            or cleanup['bundle_sha256']!=receipt['bundle_sha256'] or cleanup['result']['phase']!='accepted'
            or cleanup['result']['candidate_uuid']!=receipt['candidate_uuid'] or cleanup['result']['transient_units_cleaned'] is not True
            or spec['network_spec_sha256']!=c.sha(files['network-spec.json'])
            or spec['host_recipe']!=json.loads(files['host-recipe.json'])
            or any(spec[k]!=network[k] for k in ('hostname','kernel','boot_id','ssh','old_ipv4','mac','original_uuid','candidate_name','recipe'))
            or spec['host_recipe']['hostname']!=spec['hostname']
            or spec['reference_hashes'].keys()!={'architecture','operations','history'}
            or any(c.sha(files[label+'.md'])!=digest for label,digest in spec['reference_hashes'].items())
            or baseline['observation']['boot_id']!=spec['boot_id']
            or c.sha(files['baseline.json'])!=network['members']['baseline.json']
            or c.sha(files['release.json'])!=network['members']['release.json']
            or json.loads(files['accepted-source-release.json'])!=json.loads(files['release.json'])
            or c.host_key(files['known_hosts'],spec['old_ipv4'])!=spec['ssh']['fingerprint']):
        raise ValueError('accepted network/target/native/recipe/reference binding required')
    if kind=='hardware':
        if spec['hardware_prerequisite'] is not None:
            raise ValueError('hardware is the first configuration gate')
        raw=[base64.b64decode(baseline['protected_files'][p]['base64'],validate=True).decode() for p in s.BOOT_PATHS]
        candidates=s.render_boot(*raw)
        if candidates!=(files['config-candidate.txt'],files['cmdline-candidate.txt']):
            raise ValueError('exact preserved boot rendering required')
    else:
        hardware=json.loads(files['hardware-spec.json']);gate=spec['hardware_prerequisite']
        if (hardware['operation']!='hardware' or hardware['hostname']!=spec['hostname']
                or hardware['network_bundle_sha256']!=spec['network_bundle_sha256']
                or gate!={'stage':hardware['stage'],'spec_sha256':c.sha(files['hardware-spec.json']),
                          'bundle_sha256':json.loads(files['hardware-bundle-sha256.json']),
                          'boot_hashes':dict(zip(s.BOOT_PATHS,(hardware['members']['config-candidate.txt'],hardware['members']['cmdline-candidate.txt'])))}):
            raise ValueError('exact conditional hardware bundle required')
    return spec


def prepare(bundle, checksum):
    raw=c.private_file(bundle)
    if not re.fullmatch('[a-f0-9]{64}',checksum) or c.sha(raw)!=checksum:
        raise ValueError('approved host configuration archive hash mismatch')
    with tarfile.open(fileobj=io.BytesIO(raw),mode='r:') as archive:
        members=archive.getmembers();names=[m.name for m in members]
        if len(names)!=len(set(names)) or any(not m.isfile() or m.size>2*1024**2 for m in members):
            raise ValueError('closed regular bounded configuration archive required')
        files={m.name:archive.extractfile(m).read() for m in members}
    spec=json.loads(files['spec.json'])
    inputs=COMMON | (HARDWARE if spec['operation']=='hardware' else RUNTIME)
    if set(files)!=inputs|EXTRAS:
        raise ValueError('closed configuration archive membership required')
    manifest=json.loads(files['manifest.json'])
    if (set(manifest)!=set(files)-{'manifest.json'} or any(c.sha(files[name])!=digest for name,digest in manifest.items())
            or files['launcher.py']!=Path(__file__).read_bytes()
            or files['transport-controller.py']!=(ROOT/'scripts/run-foundation-preflight.py').read_bytes()
            or c.private_file(bundle.parent/'known_hosts',4096)!=files['known_hosts']
            or bundle.parent.stat().st_uid!=os.getuid() or bundle.parent.stat().st_mode & 0o077):
        raise ValueError('configuration archive/controller/private path drift')
    validate(files,spec)
    for mode in ('start','reboot','probe','accept','readback','recover','recovery-reboot','verify-recovery','cleanup'):
        compile(payload(spec,files,mode),'sealed-host-configuration','exec')
    return spec,files


def review(spec):
    common=(f'# {spec["operation"].title()} configuration review\n\nTarget: {spec["hostname"]}, '
            f'ama UID/GID 1000, aarch64 kernel {spec["kernel"]}.\n'
            f'Operation: {spec["operation_id"]}.\nRoot stage: `{spec["stage"]}`.\n'
            f'Pinned ED25519: {spec["ssh"]["fingerprint"]}.\n'
            f'Management: {spec["recipe"]["ipv4_address"]} and {spec["recipe"]["ipv6_address"]}.\n'
            f'Initial apply expires: {datetime.fromtimestamp(spec["expires_epoch"],timezone.utc).isoformat()}.\n'
            f'Accepted network bundle: {spec["network_bundle_sha256"]}.\n\n'
            'Exclusive root-owned 0700 staging; sealed inputs and all journals/receipts 0600. '
            'Bind native files, package inventory, services, boot inputs, target identity, pinned assets, '
            'recipes and all three governing document hashes. Recheck drift before mutation. '
            'One apply; controller registers each submission before SSH and preserves complete private streams. '
            'Never replay a consumed mode after uncertain output.\n\n')
    if spec['operation']=='hardware':
        scope=('Scope: replace only /boot/firmware/config.txt and cmdline.txt, preserving byte-exact originals '
               'in protected before-state. Add enable_uart=1, i2c_arm=on, disable-bt, PPS GPIO18 rising '
               'and i2c-rtc,rv3028 under [all]; remove exactly console=serial0,115200, retaining root/storage '
               'and all unrelated command-line settings. Existing relevant directives/includes or '
               'unexpected serial-getty/hciuart state hold preflight. No service enablement changes.\n\n'
               'Execution covers one controlled reboot after a console-ready declaration, then pinned SSH '
               'over BOTH fixed addresses, retained dual-stack network/DNS/route/HTTPS checks, unchanged '
               'package/native/service state, exact boot-file hashes, changed boot ID, PL011 serial0 mapping, '
               'one PPS device with GPIO18/rising device-tree metadata, and one RV3028 RTC at I2C 0x52. '
               'Record observed device names/permissions; do not assume rtc0 or pps0. Kernel driver '
               'probing and ordinary RTC boot-time use are inherent in enabling overlays. No user-space serial/PPS/RTC '
               'device opens, GNSS commands, sample collection, RTC time setting, daemon or watchdog activation. '
               'Metadata acceptance does not prove GNSS fix, pulse health, RTC accuracy or PoE/thermal stability.\n\n'
               'Recovery: inspect retained state first; restore both boot files only if each still equals '
               'its original or sealed candidate with unchanged ownership/mode. Unrelated drift holds. '
               'Before reboot, restoration needs no reboot. After reboot, permit one console-ready '
               'recovery reboot and verify restored boot files plus retained dual-stack management. '
               'There is no automatic timer across reboot. If endpoints are lost or the boot fails, '
               'use console/media recovery and the protected before-state. On the ama console, sudo '
               '/usr/bin/python3 -I -B STAGE/host-configuration-stage.py --root STAGE --mode readback '
               'or recover uses the retained guarded worker; recovery-reboot additionally requires '
               '--console-ready. Substitute the exact root stage above. Preserve the original Debian 11 '
               'card and primary antenna-power path. No primary contact/power/splitter changes.\n\n')
    else:
        scope=(f'Conditional on accepted hardware bundle {spec["hardware_prerequisite"]["bundle_sha256"]}, '
               'its exact root specification, successful new-boot/device/dual-stack acceptance and current '
               'accepted boot ID. Scope: create a dedicated ntp system user/group using useradd '
               '--system --user-group --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin. '
               'Names must be absent first; retain nobody/dialout for GPSD. Standard account databases '
               'and tool backups change; no password/shadow data is captured.\n\n'
               'Back up /etc/ld.so.cache, refresh using ldconfig -X (no library-symlink changes); '
               'preserve loader configuration and every installed native file/link/mode. Check libgps cache '
               'entry, root gpsd/ntpd --version and isolated root GPS/NTP imports. Check isolated ntp-user '
               'NTP Python imports and observed UART group access for GPSD. GPS clients remain root-only. '
               'Render timeservice-candidate.json from accepted serial0 metadata with 115200 baud, '
               'foreground GPSD nowait, foreground ntpd -m and ntp:ntp identity; retain and validate the '
               'service candidate inside this private root stage only. No service/config copy into /etc, '
               'service activation, timesyncd cutover, device opens, final ntp.conf or directory ownership changes.\n\n'
               'Acceptance: exact recorded account/cache/candidate, native continuity, protected loader '
               'configuration, both pinned management endpoints and network checks, bound hardware receipt, '
               'isolated imports and target systemd-analyze verify. Final NTP SHM/upstream/access/drift/leap '
               'configuration, GNSS/PPS sampling, service installation and activation remain separate reviews.\n\n'
               'Recovery: restore the cache only if unchanged since recorded refresh, delete only the '
               'recorded newly created idle ntp identity/group if its fields/membership still match. '
               'Unrecorded partial account/cache mutation or unrelated drift holds for inspection. '
               'No account home was created; no recursive deletion. Preserve candidates and evidence. '
               'An accepted stage requires a new review for reversal.\n\n')
    return (common+scope+
            'Use run-host-configuration.py execute --bundle /absolute/host-configuration.tar '
            '--sha256 APPROVED_HASH --mode start once. Hardware then uses --mode reboot --console-ready; '
            '--mode verify polls for at most six passes with 20-second intervals and submits acceptance '
            'once after both endpoint proofs. Conditional --mode readback, recover, recovery-reboot '
            '--console-ready, verify-recovery and cleanup are separately registered single-use modes. '
            'SSH calls have 60-second transport bounds. Cleanup stops/resets only operation reboot timers/services '
            'after accepted/recovered state; retain root code, before-state, candidates, receipts and all '
            'prior executed evidence. Preparation contacts no target. Approval is for this exact hash '
            'and scope, not for any later stage.\n').encode()


def seal(args):
    network,old=n.prepare(args.network_dir/'host-network.tar',args.network_sha256)
    receipt=c.private_file(args.network_dir/'acceptance.json');cleanup=c.private_file(args.network_dir/'cleanup-result.json')
    # Validate the existing local receipt against full durable endpoint proofs, without creating one.
    n.record_acceptance(args.network_dir,network,argparse.Namespace(sha256=args.network_sha256),json.loads(cleanup)['result'])
    kind=args.kind;epoch=int(time.time());baseline=json.loads(old['baseline.json'])
    if kind=='hardware' and not epoch-86400<=baseline['collected_epoch']<=epoch+300:
        raise ValueError('fresh accepted host-input baseline required')
    inputs=COMMON | (HARDWARE if kind=='hardware' else RUNTIME)
    files={name:(ROOT/'scripts'/name).read_bytes() for name in inputs if name.endswith('.py')}
    files.update({name:old[name] for name in ('baseline.json','release.json','known_hosts')})
    files.update({'network-spec.json':old['spec.json'],'network-acceptance.json':receipt,'network-cleanup.json':cleanup,
                  'host-recipe.json':(ROOT/'configs'/('host-'+kind+'-recipe.json')).read_bytes(),
                  'launcher.py':Path(__file__).read_bytes(),'transport-controller.py':(ROOT/'scripts/run-foundation-preflight.py').read_bytes(),
                  'tests.py':(ROOT/'tests/test_host_configuration.py').read_bytes()})
    for name in ('installation-assets.json','source-build-recipe.json','accepted-packages.tsv','accepted-source-release.json'):
        files[name]=(ROOT/'configs'/name).read_bytes()
    for label,path in (('architecture','docs/ntp-architecture-deployment-plan-v1.0.md'),('operations','docs/OPERATIONS.md'),('history','HISTORY.md')):
        files[label+'.md']=(ROOT/path).read_bytes()
    gate=None
    if kind=='hardware':
        boot=[base64.b64decode(baseline['protected_files'][p]['base64'],validate=True).decode() for p in s.BOOT_PATHS]
        files['config-candidate.txt'],files['cmdline-candidate.txt']=s.render_boot(*boot)
    else:
        hardware,previous=prepare(args.hardware_dir/'host-configuration.tar',args.hardware_sha256)
        files.update({'hardware-spec.json':previous['spec.json'],'hardware-bundle-sha256.json':c.encoded(args.hardware_sha256),
                      'timeservice-template.json':(ROOT/'templates/timeservice.json.example').read_bytes(),
                      'timeservice-template.service':(ROOT/'templates/timeservice.service').read_bytes()})
        gate={'stage':hardware['stage'],'spec_sha256':c.sha(previous['spec.json']),'bundle_sha256':args.hardware_sha256,
              'boot_hashes':dict(zip(s.BOOT_PATHS,(hardware['members']['config-candidate.txt'],hardware['members']['cmdline-candidate.txt'])))}
    spec={k:network[k] for k in ('hostname','kernel','boot_id','ssh','old_ipv4','mac','original_uuid','candidate_name','recipe')}
    spec.update(schema=1,operation=kind,operation_id=args.operation_id,stage='/var/lib/ntp-host-'+args.operation_id,
        network_candidate_uuid=json.loads(receipt)['candidate_uuid'],network_bundle_sha256=args.network_sha256,
        network_spec_sha256=c.sha(old['spec.json']),prepared_epoch=epoch,
        expires_epoch=min(epoch+86400,baseline['collected_epoch']+86400) if kind=='hardware' else epoch+86400,
        host_recipe=json.loads(files['host-recipe.json']),hardware_prerequisite=gate,
        reference_hashes={label:c.sha(files[label+'.md']) for label in ('architecture','operations','history')},
        members={name:c.sha(files[name]) for name in sorted(inputs)})
    validate(files,spec);files['spec.json']=c.encoded(spec);files['review.md']=review(spec)
    files['manifest.json']=c.encoded({name:c.sha(data) for name,data in sorted(files.items())})
    os.umask(0o077);args.output.mkdir(mode=0o700)
    for name in ('spec.json','review.md','known_hosts'):(args.output/name).write_bytes(files[name])
    bundle=args.output/'host-configuration.tar'
    with tarfile.open(bundle,'w',format=tarfile.USTAR_FORMAT) as archive:
        for name,data in sorted(files.items()):
            item=tarfile.TarInfo(name);item.mode=0o600;item.size=len(data);item.mtime=epoch;archive.addfile(item,io.BytesIO(data))
    digest=c.sha(bundle.read_bytes());prepare(bundle,digest)
    result={'bundle':str(bundle),'sha256':digest,'target':spec['hostname'],'expires_epoch':spec['expires_epoch'],
            'target_contact':False,'execution_authorized':False}
    (args.output/'sealing.json').write_bytes(c.encoded(result));return result


def payload(spec, files, mode, proofs=None, console_ready=False):
    return ('import base64,hashlib,json\n'
        'spec=json.loads('+repr(json.dumps(spec))+')\n'
        'files={n:base64.b64decode(d,validate=True) for n,d in json.loads('+repr(json.dumps(
            {n:base64.b64encode(files[n]).decode() for n in spec['members']}))+').items()}\n'
        'ns={"__name__":"sealed_host","__file__":spec["stage"]+"/host-configuration-stage.py"}\n'
        'exec(compile(files["host-configuration-stage.py"],"sealed-host-stage","exec"),ns)\n'
        'status=0\ntry:\n    result=ns["entry"](spec,files,'+repr(mode)+','+repr(proofs)+','+repr(console_ready)+')\n'
        'except BaseException as error:\n    status=2\n    result={"phase":"held","error":str(error)[:500]}\n'
        'print(json.dumps({"hostname":spec["hostname"],"spec_sha256":hashlib.sha256(ns["encoded"](spec)).hexdigest(),"result":result},sort_keys=True))\n'
        'print("HOST_EXIT_STATUS="+str(status))\nraise SystemExit(status)\n').encode()


def remote(directory,spec,files,host,mode,label,proofs=None,console_ready=False):
    agent=os.environ.get('SSH_AUTH_SOCK')
    if not agent:raise ValueError('existing SSH agent required')
    argv=c.transport(directory,host);index=argv.index('ama@'+host)
    argv[index:index]=['-o','HostKeyAlias='+spec['old_ipv4']];argv[3]='60s'
    data=payload(spec,files,mode,proofs,console_ready)
    c.write_new(directory/(label+'-execution.json'),{'host':host,'mode':mode,'argv':argv,
        'payload_sha256':c.sha(data),'spec_sha256':c.sha(files['spec.json']),'registered_epoch':int(time.time())})
    with (directory/(label+'.stdout')).open('xb') as stdout,(directory/(label+'.stderr')).open('xb') as stderr:
        process=subprocess.run(argv,input=data,stdout=stdout,stderr=stderr,check=False,
            env={'PATH':'/usr/bin:/bin','LC_ALL':'C','SSH_AUTH_SOCK':agent})
    c.write_new(directory/(label+'-transport.json'),{'exit_status':process.returncode})
    raw=c.private_file(directory/(label+'.stdout'),8*1024**2)
    match=re.fullmatch(rb'(.*)\nHOST_EXIT_STATUS=([02])\n',raw,re.S)
    if not match:raise ValueError('lost terminal; preserve streams, never resubmit mutation')
    report=json.loads(match[1]);status=int(match[2])
    c.write_new(directory/(label+'-result.json'),{'host':host,'mode':mode,'worker_status':status,
                'transport_exit_status':process.returncode,'report':report})
    if process.returncode!=status or report['hostname']!=spec['hostname'] or report['spec_sha256']!=c.sha(s.encoded(spec)):
        raise ValueError('configuration transport/target/spec mismatch')
    if status:raise ValueError('configuration held: '+report['result'].get('error','unknown'))
    return report['result']


def record_acceptance(directory,spec,checksum,result):
    labels=s.HARDWARE_LABELS if spec['operation']=='hardware' else s.RUNTIME_LABELS
    endpoints={spec['recipe'][k].split('/')[0] for k in ('ipv4_address','ipv6_address')}
    if (result['phase']!='accepted' or result['checks'].keys()!=labels or any(v is not True for v in result['checks'].values())
            or set(result['ssh_proofs'])!=endpoints
            or any(p['hostname']!=spec['hostname'] or p['boot_id']!=result['accepted_boot_id']
                   or p['spec_sha256']!=c.sha(s.encoded(spec)) or p['checks']!=result['checks']
                   or p['hardware']!=result['hardware'] for p in result['ssh_proofs'].values())):
        raise ValueError('complete bound dual-stack configuration acceptance required')
    receipt={'state':spec['operation']+'_configuration_accepted','bundle_sha256':checksum,
             'spec_sha256':c.sha(s.encoded(spec)),'hostname':spec['hostname'],'boot_id':result['accepted_boot_id'],
             'checks':result['checks'],'hardware':result['hardware'],'service_activation_authorized':False,
             'receiver_timing_accepted':False}
    path=directory/'acceptance.json'
    if path.exists():
        if c.private_file(path)!=c.encoded(receipt):raise ValueError('conflicting configuration receipt')
    else:c.write_new(path,receipt)


def execute(args):
    bundle=args.bundle.absolute();spec,files=prepare(bundle,args.sha256);directory=bundle.parent
    if args.mode=='start' and not spec['prepared_epoch']-300<=time.time()<spec['expires_epoch']:
        raise ValueError('configuration execution window expired')
    if args.mode in ('reboot','recovery-reboot') and (spec['operation']!='hardware' or args.console_ready is not True):
        raise ValueError('hardware stage and console-ready declaration required')
    if args.mode!='start':
        initial=json.loads(c.private_file(directory/'start-execution.json'))
        if initial['bundle_sha256']!=args.sha256:raise ValueError('bound registered start required')
    c.write_new(directory/(args.mode+'-execution.json'),{'bundle_sha256':args.sha256,'mode':args.mode,
        'console_ready':args.console_ready,'registered_epoch':int(time.time())})
    endpoints=[spec['recipe'][k].split('/')[0] for k in ('ipv4_address','ipv6_address')]
    if args.mode=='start':result=remote(directory,spec,files,endpoints[0],'start','start-ssh')
    elif args.mode=='verify':
        ready=False
        for attempt in range(6):
            try:
                result=remote(directory,spec,files,endpoints[0],'probe','wait-'+str(attempt));ready=True;break
            except (ValueError,subprocess.TimeoutExpired):
                if attempt<5:time.sleep(20)
        if not ready:raise ValueError('configuration not ready; use conditional readback/recovery')
        proofs={host:remote(directory,spec,files,host,'probe','probe-'+str(index)) for index,host in enumerate(endpoints)}
        result=remote(directory,spec,files,endpoints[0],'accept','accept-ssh',proofs)
        record_acceptance(directory,spec,args.sha256,result)
    else:
        result=None
        for index,host in enumerate(endpoints):
            try:result=remote(directory,spec,files,host,'readback',args.mode+'-locate-'+str(index));break
            except (ValueError,subprocess.TimeoutExpired):continue
        if result is None:raise ValueError('scoped endpoints unavailable; retain evidence and use console/media recovery')
        if args.mode!='readback':
            result=remote(directory,spec,files,host,args.mode,args.mode+'-action',console_ready=args.console_ready)
        elif result['phase']=='accepted':record_acceptance(directory,spec,args.sha256,result)
    c.write_new(directory/(args.mode+'-result.json'),{'bundle_sha256':args.sha256,'result':result})
    return {'mode':args.mode,'phase':result['phase'],'target':spec['hostname']}


def main():
    os.umask(0o077);parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='action',required=True)
    p=sub.add_parser('seal');p.add_argument('--kind',choices=('hardware','runtime'),required=True)
    p.add_argument('--network-dir',type=Path,required=True);p.add_argument('--network-sha256',required=True)
    p.add_argument('--hardware-dir',type=Path);p.add_argument('--hardware-sha256')
    p.add_argument('--operation-id',required=True);p.add_argument('--output',type=Path,required=True)
    p=sub.add_parser('execute');p.add_argument('--bundle',type=Path,required=True);p.add_argument('--sha256',required=True)
    p.add_argument('--mode',choices=('start','reboot','verify','readback','recover','recovery-reboot','verify-recovery','cleanup'),required=True)
    p.add_argument('--console-ready',action='store_true')
    args=parser.parse_args()
    if args.action=='seal' and args.kind=='runtime' and (args.hardware_dir is None or args.hardware_sha256 is None):
        parser.error('runtime sealing requires exact conditional hardware bundle')
    print(json.dumps(seal(args) if args.action=='seal' else execute(args)))


if __name__=='__main__':main()
