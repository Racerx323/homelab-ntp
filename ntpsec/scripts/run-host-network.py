#!/usr/bin/python3
"""Seal offline; execute one fixed-network transaction with independent endpoint acceptance."""
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

ROOT=Path(__file__).resolve().parents[1]


def module(name):
    d=importlib.util.spec_from_file_location('network_controller_'+name.replace('-','_'),ROOT/'scripts'/name)
    m=importlib.util.module_from_spec(d);d.loader.exec_module(m);return m


c=module('run-foundation-preflight.py')
s=module('host-network-stage.py')
rr=module('run-runtime-discovery.py')
SCRIPTS={'host-network-stage.py','foundation-install.py','inspect-source-destinations.py','clockmaker.py'}
INPUTS=SCRIPTS|{'baseline.json','baseline-acceptance.json','release.json','network-recipe.json',
               'architecture.md','operations.md','history.md'}
EXTRAS={'launcher.py','transport-controller.py','tests.py','known_hosts','spec.json','review.md','manifest.json'}


def validate(files,spec):
    s.validate_spec(spec)
    baseline=json.loads(files['baseline.json']);accepted=json.loads(files['baseline-acceptance.json'])
    if (accepted['state']!='runtime_discovery_accepted' or accepted['configuration_ready'] is not False
            or accepted['activation_authorized'] is not False or accepted['runtime_sha256']!=c.sha(files['baseline.json'])
            or accepted['bundle_sha256']!=spec['snapshot_bundle_sha256']
            or accepted['release_sha256']!=c.sha(files['release.json'])
            or baseline['hostname']!=spec['hostname'] or baseline['kernel']!=spec['kernel']
            or baseline['observation']['boot_id']!=spec['boot_id']
            or baseline['collected_epoch']+86400<spec['expires_epoch']
            or spec['recipe']!=json.loads(files['network-recipe.json'])
            or any(spec['reference_hashes'][label]!=c.sha(files[label+'.md']) for label in ('architecture','operations','history'))):
        raise ValueError('accepted snapshot/recipe/reference binding required')
    profile=s.properties(baseline['queries']['ethernet_profiles'][spec['original_uuid']]['stdout'])
    if (profile['connection.type']!='802-3-ethernet' or profile['connection.interface-name']!='eth0'
            or profile['connection.uuid']!=spec['original_uuid'] or profile['connection.autoconnect']!='yes'
            or profile['ipv4.method']!='auto' or profile['ipv6.method']!='auto'
            or not set(s.settings(spec['recipe']))<=set(profile)):
        raise ValueError('complete accepted bootstrap profile required')
    nic=[n for n in json.loads(baseline['queries']['addresses']['stdout']) if n['ifname']=='eth0']
    if (len(nic)!=1 or nic[0]['address'].lower()!=spec['mac']
            or spec['old_ipv4']!=spec['ssh']['host']
            or not any(a['family']=='inet' and a['local']==spec['old_ipv4'] and a['prefixlen']==22 for a in nic[0]['addr_info'])):
        raise ValueError('accepted old endpoint/MAC binding required')
    if c.host_key(files['known_hosts'],spec['old_ipv4'])!=spec['ssh']['fingerprint']:
        raise ValueError('exact accepted SSH key required')


def prepare(bundle,checksum):
    raw=c.private_file(bundle)
    if not re.fullmatch(r'[a-f0-9]{64}',checksum) or c.sha(raw)!=checksum:
        raise ValueError('approved network archive hash mismatch')
    with tarfile.open(fileobj=io.BytesIO(raw),mode='r:') as archive:
        members=archive.getmembers();names=[m.name for m in members]
        if (set(names)!=INPUTS|EXTRAS or len(names)!=len(set(names))
                or any(not m.isfile() or m.size>2*1024**2 for m in members)):
            raise ValueError('closed network archive membership/type/bound required')
        files={m.name:archive.extractfile(m).read() for m in members}
    manifest=json.loads(files['manifest.json']);spec=json.loads(files['spec.json'])
    if (set(manifest)!=set(files)-{'manifest.json'} or any(c.sha(files[n])!=h for n,h in manifest.items())
            or set(spec['members'])!=INPUTS or any(c.sha(files[n])!=h for n,h in spec['members'].items())
            or files['launcher.py']!=Path(__file__).read_bytes()
            or files['transport-controller.py']!=(ROOT/'scripts/run-foundation-preflight.py').read_bytes()
            or c.private_file(bundle.parent/'known_hosts',4096)!=files['known_hosts']
            or bundle.parent.stat().st_uid!=os.getuid() or bundle.parent.stat().st_mode & 0o077):
        raise ValueError('network archive/member/controller/private path drift')
    validate(files,spec)
    for mode in ('start','probe','accept','readback','recover','cleanup'):compile(payload(spec,files,mode),'sealed-network','exec')
    return spec,files


def seal(args):
    snapshot=args.snapshot_dir/'runtime-discovery.tar'
    previous,old=rr.prepare(snapshot,args.snapshot_sha256)
    raw=c.private_file(args.snapshot_dir/'runtime.json');baseline=json.loads(raw)
    acceptance=c.private_file(args.snapshot_dir/'acceptance.json');receipt=json.loads(acceptance)
    cleanup=json.loads(c.private_file(args.snapshot_dir/'cleanup-result.json'))
    readback=json.loads(c.private_file(args.snapshot_dir/'readback-result.json'))
    release,build,observation,installed=rr.validate_bindings(old,previous)
    rr.i.validate(baseline,previous,release,build)
    if (receipt['runtime_sha256']!=c.sha(raw) or receipt['bundle_sha256']!=args.snapshot_sha256
            or baseline['observation']!=observation or baseline['installed_state']!=installed
            or readback['bundle_sha256']!=args.snapshot_sha256 or readback['worker_status']!=0
            or readback['transport_exit_status']!=0 or readback['report']['inspection_sha256']!=c.sha(raw)
            or readback['report']['spec_sha256']!=c.sha(old['spec.json'])
            or cleanup['bundle_sha256']!=args.snapshot_sha256 or cleanup['worker_status']!=0
            or cleanup['transport_exit_status']!=0 or cleanup['report']['state']!='snapshot_stage_removed'):
        raise ValueError('accepted snapshot and cleanup required')
    recipe=json.loads(args.recipe.read_bytes());epoch=int(time.time())
    if not epoch-86400 <= baseline['collected_epoch'] <= epoch+300:
        raise ValueError('fresh accepted host-input report required')
    profiles=baseline['queries']['ethernet_profiles']
    selected=[uuid for uuid,r in profiles.items() if s.properties(r['stdout']).get('connection.interface-name')=='eth0']
    nic=[n for n in json.loads(baseline['queries']['addresses']['stdout']) if n['ifname']=='eth0']
    if len(selected)!=1 or len(nic)!=1:raise ValueError('one observed Ethernet profile/device required')
    files={name:(ROOT/'scripts'/name).read_bytes() for name in SCRIPTS}
    files.update({'baseline.json':raw,'baseline-acceptance.json':acceptance,'release.json':old['release.json'],
        'network-recipe.json':args.recipe.read_bytes(),'known_hosts':old['known_hosts'],
        'launcher.py':Path(__file__).read_bytes(),
        'transport-controller.py':(ROOT/'scripts/run-foundation-preflight.py').read_bytes(),
        'tests.py':(ROOT/'tests/test_host_network.py').read_bytes()})
    for label,path in (('architecture','docs/ntp-architecture-deployment-plan-v1.0.md'),('operations','docs/OPERATIONS.md'),('history','HISTORY.md')):
        files[label+'.md']=(ROOT/path).read_bytes()
    spec={'schema':1,'operation_id':args.operation_id,'stage':'/var/lib/ntp-network-'+args.operation_id,
        'hostname':baseline['hostname'],'kernel':baseline['kernel'],'boot_id':baseline['observation']['boot_id'],
        'ssh':previous['ssh'],'old_ipv4':previous['ssh']['host'],'mac':nic[0]['address'].lower(),
        'original_uuid':selected[0],'candidate_name':'ntp-static-'+args.operation_id,'recipe':recipe,
        'snapshot_bundle_sha256':args.snapshot_sha256,'prepared_epoch':epoch,
        'expires_epoch':min(epoch+86400,baseline['collected_epoch']+86400),
        'reference_hashes':{label:c.sha(files[label+'.md']) for label in ('architecture','operations','history')},
        'members':{name:c.sha(files[name]) for name in sorted(INPUTS)}}
    validate(files,spec);files['spec.json']=c.encoded(spec)
    files['review.md']=(f'# Fixed dual-stack networking review\n\nTarget: {spec["hostname"]}, ama UID/GID 1000, '
        f'{spec["old_ipv4"]}; {spec["kernel"]}, boot {spec["boot_id"]}.\n'
        f'Pinned ED25519: {spec["ssh"]["fingerprint"]}.\nOperation: {args.operation_id}.\n'
        f'Apply expires: {datetime.fromtimestamp(spec["expires_epoch"],timezone.utc).isoformat()}.\n'
        f'Accepted host-input bundle: {args.snapshot_sha256}.\nAccepted report: {c.sha(raw)}.\n\n'
        f'Create exclusive root-owned 0700 `{spec["stage"]}` with hash-bound 0600 inputs. One background\n'
        'systemd apply job, maximum 180 seconds; root timer is independent of SSH and restores\n'
        'the original DHCP profile at 300 seconds unless durable acceptance has completed.\n'
        'Preflight requires exact boot/kernel/hostname, inventory/services/Python/native release and\n'
        'boot-file continuity, Ethernet MAC, original UUID/registry/active connection and original\n'
        'scoped properties. Only connection.timestamp is volatile. Validate executable locations\n'
        'and reject an IPv4 duplicate using installed iputils arping before any profile mutation.\n\n'
        'Clone the original profile under a unique operation name, record its allocated UUID,\n'
        f'set IPv4 {recipe["ipv4_address"]}, gateway {recipe["ipv4_gateway"]}, DNS {recipe["ipv4_dns"]};\n'
        f'IPv6 auto/RA plus fixed ULA {recipe["ipv6_address"]}, DNS {recipe["ipv6_dns"]}.\n'
        'Ignore automatic DNS in both families; require both families, IPv4 DAD 3000 ms and\n'
        'candidate autoconnect priority 100. Retain other captured connection/Ethernet/IP settings.\n'
        'Disable original autoconnect, then activate candidate on eth0; SSH at the DHCP address\n'
        'may drop. No reboot, radio/hardware/GNSS changes, clock-service activation, package changes,\n'
        'controller/DNS/firewall edits or Wi-Fi/802.1X/VPN secret queries.\n\n'
        'Acceptance requires exact candidate/original/registry settings, ready fixed addresses\n'
        'without DAD failure, a public RA IPv6 address and RA default route, IPv4 default route,\n'
        'exact effective DNS VIPs, source-bound routes and ICMP to both DNS VIPs. Read protected\n'
        '/etc/resolv.conf (root-owned alias/target) and require the direct two-VIP nameserver view\n'
        'before and after activation; a local stub or other servers hold preflight for review. HEAD HTTPS to\n'
        'https://deb.debian.org/debian/ over IPv4 from the fixed IPv4 and IPv6 from the public\n'
        'RA address proves DNS/TLS/egress; no downloads. Curl configuration/proxies are disabled.\n'
        'Require pinned-key SSH probes to BOTH new fixed addresses before acceptance; all labelled\n'
        'checks must be true and 45 seconds must remain on the timer. Commit acceptance durably\n'
        'before stopping the timer. A lost acceptance response requires readback, never resubmission.\n\n'
        'Conditional readback may use new IPv4, new ULA and old IPv4 with the same pinned host key.\n'
        'Recovery changes only original autoconnect, reactivates original and deletes the proved\n'
        'operation candidate; unexpected original/candidate drift holds instead of overwriting.\n'
        'DHCP recovery restores policy; it cannot promise the old lease/address. Console access\n'
        'is required for lost transport, reboot, unavailable timer or held recovery. A read-only\n'
        'negative ARP result is not administrative address ownership proof; the governing plan\n'
        'allocates these addresses and runtime DAD/route/listener checks must still pass.\n'
        'Cleanup stops/resets only this operation\'s transient units after accepted/recovered state;\n'
        'retain root code, before-state, receipts and all private streams for recovery/audit.\n'
        'Reboot persistence is a later hardware/reboot gate, not claimed by this operation.\n\n'
        'Use run-host-network.py execute --bundle /absolute/host-network.tar --sha256 APPROVED_HASH\n'
        '--mode start once, then --mode verify (both endpoint probes and one conditional acceptance).\n'
        'Verification polls readback at new IPv4/old IPv4 for at most three passes with ten-second\n'
        'intervals, then probes each new endpoint once and submits acceptance once. All SSH calls\n'
        'have a 60-second transport bound. Use conditional --mode readback, --mode recover and\n'
        '--mode cleanup against this bundle only; recovery/cleanup locate with reads, then submit once.\n'
        'Preparation contacted no target. Separate approval must cover the exact mutation,\n'
        'endpoint probes, acceptance, timed/conditional recovery, readback and transient cleanup.\n').encode()
    files['manifest.json']=c.encoded({name:c.sha(data) for name,data in sorted(files.items())})
    os.umask(0o077);args.output.mkdir(mode=0o700)
    for name in ('known_hosts','spec.json','review.md'):(args.output/name).write_bytes(files[name])
    bundle=args.output/'host-network.tar'
    with tarfile.open(bundle,'w',format=tarfile.USTAR_FORMAT) as archive:
        for name,data in sorted(files.items()):
            member=tarfile.TarInfo(name);member.mode=0o600;member.size=len(data);member.mtime=epoch
            archive.addfile(member,io.BytesIO(data))
    result={'bundle':str(bundle),'sha256':c.sha(bundle.read_bytes()),'target':spec['hostname'],
        'expires_epoch':spec['expires_epoch'],'target_contact':False,'execution_authorized':False}
    prepare(bundle,result['sha256']);(args.output/'sealing.json').write_bytes(c.encoded(result));return result


def payload(spec,files,mode,proofs=None):
    return ('import base64,json\n'
        'spec=json.loads('+repr(json.dumps(spec))+')\n'
        'files={n:base64.b64decode(d,validate=True) for n,d in json.loads('+repr(json.dumps(
            {n:base64.b64encode(files[n]).decode() for n in spec['members']}))+').items()}\n'
        'ns={"__name__":"sealed_network","__file__":spec["stage"]+"/host-network-stage.py"}\n'
        'exec(compile(files["host-network-stage.py"],"sealed-network-stage","exec"),ns)\n'
        'status=0\ntry:\n'
        '    result=ns["entry"](spec,files,'+repr(mode)+','+repr(proofs)+')\n'
        'except BaseException as error:\n    status=2\n    result={"phase":"held","error":str(error)[:500]}\n'
        'print(json.dumps({"hostname":spec["hostname"],"spec_sha256":ns["sha"](ns["encoded"](spec)),"result":result},sort_keys=True))\n'
        'print("NETWORK_EXIT_STATUS="+str(status))\nraise SystemExit(status)\n').encode()


def remote(directory,spec,files,host,mode,label,proofs=None):
    agent=os.environ.get('SSH_AUTH_SOCK')
    if not agent:raise ValueError('existing SSH agent required')
    argv=c.transport(directory,host)
    index=argv.index('ama@'+host)
    argv[index:index]=['-o','HostKeyAlias='+spec['old_ipv4']]
    argv[3]='60s'
    data=payload(spec,files,mode,proofs)
    c.write_new(directory/(label+'-execution.json'),{'host':host,'mode':mode,'argv':argv,
        'payload_sha256':c.sha(data),'spec_sha256':c.sha(files['spec.json']),'registered_epoch':int(time.time())})
    with (directory/(label+'.stdout')).open('xb') as stdout,(directory/(label+'.stderr')).open('xb') as stderr:
        result=subprocess.run(argv,input=data,stdout=stdout,stderr=stderr,check=False,
            env={'PATH':'/usr/bin:/bin','LC_ALL':'C','SSH_AUTH_SOCK':agent})
    c.write_new(directory/(label+'-transport.json'),{'exit_status':result.returncode})
    raw=c.private_file(directory/(label+'.stdout'),8*1024**2)
    match=re.fullmatch(rb'(.*)\nNETWORK_EXIT_STATUS=([02])\n',raw,re.S)
    if not match:raise ValueError('lost terminal; retain streams, never resubmit mutation')
    report=json.loads(match[1]);status=int(match[2])
    record={'host':host,'mode':mode,'worker_status':status,'transport_exit_status':result.returncode,'report':report}
    c.write_new(directory/(label+'-result.json'),record)
    if (result.returncode!=status or report['hostname']!=spec['hostname']
            or report['spec_sha256']!=c.sha(files['spec.json'])):
        raise ValueError('network transport/target/spec mismatch')
    if status:raise ValueError('network operation held: '+report['result'].get('error','unknown'))
    return report['result']


def record_acceptance(directory,spec,args,result):
    endpoints={spec['recipe'][key].split('/')[0] for key in ('ipv4_address','ipv6_address')}
    if (result['phase']!='accepted' or set(result['checks'])!=s.LABELS
            or any(v is not True for v in result['checks'].values()) or set(result['ssh_proofs'])!=endpoints):
        raise ValueError('complete durable network acceptance required')
    for proof in result['ssh_proofs'].values():
        if (proof['hostname']!=spec['hostname'] or proof['boot_id']!=spec['boot_id']
                or proof['spec_sha256']!=c.sha(c.encoded(spec)) or proof['candidate_uuid']!=result['candidate_uuid']
                or set(proof['checks'])!=s.LABELS or any(v is not True for v in proof['checks'].values())):
            raise ValueError('complete bound dual-stack receipt required')
    receipt={'state':'host_network_accepted','bundle_sha256':args.sha256,
        'spec_sha256':c.sha(c.encoded(spec)),'snapshot_sha256':spec['snapshot_bundle_sha256'],
        'hostname':spec['hostname'],'candidate_uuid':result['candidate_uuid'],'checks':result['checks'],
        'reboot_persistence_accepted':False,'application_activation_authorized':False}
    path=directory/'acceptance.json'
    if path.exists():
        if c.private_file(path)!=c.encoded(receipt):raise ValueError('conflicting retained acceptance receipt')
    else:c.write_new(path,receipt)


def execute(args):
    bundle=args.bundle.absolute();spec,files=prepare(bundle,args.sha256);directory=bundle.parent
    if args.mode=='start' and not spec['prepared_epoch']-300<=time.time()<spec['expires_epoch']:
        raise ValueError('network execution window expired')
    if args.mode!='start':
        initial=json.loads(c.private_file(directory/'start-execution.json'))
        if initial['bundle_sha256']!=args.sha256 or initial['mode']!='start':
            raise ValueError('bound registered start required before conditional networking actions')
    c.write_new(directory/(args.mode+'-execution.json'),{'bundle_sha256':args.sha256,'mode':args.mode,'registered_epoch':int(time.time())})
    v4=spec['recipe']['ipv4_address'].split('/')[0];v6=spec['recipe']['ipv6_address'].split('/')[0]
    if args.mode=='start':result=remote(directory,spec,files,spec['old_ipv4'],'start','start-ssh')
    elif args.mode=='verify':
        ready=False
        for attempt in range(3):
            for index,host in enumerate((v4,spec['old_ipv4'])):
                try:state=remote(directory,spec,files,host,'readback','wait-'+str(attempt)+'-'+str(index))
                except (ValueError,subprocess.TimeoutExpired):continue
                if state['phase']=='applied':ready=True;break
                if state['phase'] in ('apply_held','recovery_held','recovered','accepted'):
                    raise ValueError('network apply held or already terminal; use readback, never reapply')
            if ready:break
            if attempt<2:time.sleep(10)
        if not ready:raise ValueError('candidate did not reach applied state; recovery remains armed')
        proofs={}
        for family,host in (('v4',v4),('v6',v6)):
            proofs[host]=remote(directory,spec,files,host,'probe','probe-'+family)
        result=remote(directory,spec,files,v4,'accept','accept-ssh',proofs)
        record_acceptance(directory,spec,args,result)
    else:
        errors=[];result=None
        for index,host in enumerate((v4,v6,spec['old_ipv4'])):
            try:
                result=remote(directory,spec,files,host,'readback',args.mode+'-locate-'+str(index));break
            except (ValueError,subprocess.TimeoutExpired) as error:errors.append(str(error))
        if result is None:raise ValueError('all scoped endpoints held; retain state and use console: '+'; '.join(errors))
        if args.mode!='readback':
            # Locate with read-only calls, then submit exactly one action. Never retry a lost mutation response.
            result=remote(directory,spec,files,host,args.mode,args.mode+'-action')
        elif result['phase']=='accepted':record_acceptance(directory,spec,args,result)
    c.write_new(directory/(args.mode+'-result.json'),{'bundle_sha256':args.sha256,'result':result})
    return {'mode':args.mode,'phase':result['phase'],'target':spec['hostname']}


def main():
    os.umask(0o077);p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='action',required=True)
    seal_parser=sub.add_parser('seal');seal_parser.add_argument('--snapshot-dir',type=Path,required=True)
    seal_parser.add_argument('--snapshot-sha256',required=True);seal_parser.add_argument('--operation-id',required=True)
    seal_parser.add_argument('--recipe',type=Path,default=ROOT/'configs/host-network-recipe.json')
    seal_parser.add_argument('--output',type=Path,required=True)
    run=sub.add_parser('execute');run.add_argument('--bundle',type=Path,required=True);run.add_argument('--sha256',required=True)
    run.add_argument('--mode',choices=('start','verify','readback','recover','cleanup'),required=True)
    args=p.parse_args();print(json.dumps(seal(args) if args.action=='seal' else execute(args)))


if __name__=='__main__':main()
