#!/usr/bin/python3
"""Prepare offline or execute one separately approved service cutover."""
import argparse
import base64
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import time
import types
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[1]
INPUT_PATHS={
 'controller.py':'scripts/run-service-cutover.py','stage.py':'scripts/service-cutover-stage.py',
 'client.py':'scripts/check-time-client.py','measure.py':'scripts/measure-time-service.py',
 'transport.py':'scripts/run-foundation-preflight.py','timeservice.py':'scripts/timeservice.py',
 'gpsd-pairing.py':'scripts/gpsd-pairing.py','ntp.conf':'configs/j2-svntp1-ntp.conf',
 'recipe.json':'configs/service-cutover-recipe.json','leap-seconds.list':'configs/leap-seconds.list',
 'timeservice.service':'templates/timeservice.service','avahi.conf':'templates/avahi-ntp.conf',
 'ntpleapfetch.service':'templates/ntpleapfetch-j2.service','ntpleapfetch.timer':'templates/ntpleapfetch.timer',
 'tests.py':'tests/test_service_cutover.py','supervisor-tests.py':'tests/test_clockmaker.py',
 'architecture.md':'docs/ntp-architecture-deployment-plan-v1.0.md','operations.md':'docs/OPERATIONS.md','history.md':'HISTORY.md'}
EXTRA={'reference.py','reference.tar','reference-report.json','reference-receipt.json','reference-cleanup.json',
       'receiver-runtime.json','known_hosts','timeservice.json'}
MODES=('start','probe','readback','accept','recover','cleanup')


def encoded(value):return (json.dumps(value,sort_keys=True)+'\n').encode()
def sha(raw):return hashlib.sha256(raw).hexdigest()


def load(path):
    spec=importlib.util.spec_from_file_location('cutover_'+path.stem.replace('-','_'),path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def frozen(raw):
    ns={'__name__':'sealed_reference','__file__':'/sealed/reference.py'}
    exec(compile(raw,'sealed-reference','exec'),ns);return types.SimpleNamespace(**ns)


def unpack(raw):
    with tarfile.open(fileobj=io.BytesIO(raw),mode='r:') as archive:
        members=archive.getmembers()
        if len(members)>64 or len({m.name for m in members})!=len(members) or any(not m.isfile() or not re.fullmatch(r'[a-z][a-z0-9._-]+',m.name) or m.size>32*1024**2 for m in members):
            raise ValueError('bounded flat regular archive required')
        files={m.name:archive.extractfile(m).read() for m in members}
    if json.loads(files['manifest.json'])!={n:sha(v) for n,v in files.items() if n!='manifest.json'}:raise ValueError('manifest mismatch')
    return files


def validate(spec,files):
    if set(files)!=set(INPUT_PATHS)|EXTRA|{'spec.json','manifest.json','review.md'}:raise ValueError('closed cutover archive required')
    if not re.fullmatch('[a-z][a-z0-9-]{0,47}',spec['operation_id']):raise ValueError('operation ID')
    if (spec['schema']!=1 or spec['stage']!='/var/lib/ntp-acquire-'+spec['operation_id']
            or spec['apply_unit']!='ntp-cutover-'+spec['operation_id']
            or spec['recovery_unit']!=spec['apply_unit']+'-recovery'
            or not 0<spec['expires_epoch']-spec['prepared_epoch']<=86400
            or spec['members']!={n:sha(files[n]) for n in set(INPUT_PATHS)|EXTRA}):raise ValueError('specification/input binding')
    ref=unpack(files['reference.tar']);old=json.loads(ref['spec.json'])
    if files['reference.py']!=ref['worker.py']:raise ValueError('frozen accepted checker required')
    a=frozen(files['reference.py']);a.validate(old,ref)
    report=json.loads(files['reference-report.json']);receipt=json.loads(files['reference-receipt.json'])
    if a.terminal_receipt(old,ref,sha(files['reference.tar']),dict.fromkeys(old['endpoints'],report))!=receipt or receipt['state']!='receiver_runtime_inputs_captured':
        raise ValueError('accepted receiver/runtime capture required')
    cleanup=json.loads(files['reference-cleanup.json'])
    terminal=report['evidence']['terminal.json']
    if cleanup['spec_sha256']!=sha(ref['spec.json']) or cleanup['result']!={'phase':'cleaned','evidence_preserved':True,'shm_preserved':True,'terminal_sha256':terminal['sha256']}:
        raise ValueError('accepted receiver cleanup required')
    for name,row in report['evidence'].items():
        if sha(base64.b64decode(row['base64'],validate=True))!=row['sha256']:raise ValueError('receiver evidence digest')
    if files['receiver-runtime.json']!=base64.b64decode(report['evidence']['receiver-runtime.json']['base64']):raise ValueError('runtime evidence mismatch')
    if any(spec[k]!=old[k] for k in ('hostname','kernel','boot_id','old_ipv4','endpoints')) or spec['expires_epoch']>old['expires_epoch'] or files['known_hosts']!=ref['known_hosts']:
        raise ValueError('accepted target/boot/window/key binding')
    recipe=json.loads(files['recipe.json'])
    if spec['recipe']!=recipe or recipe['hostname']!=spec['hostname'] or json.loads(files['timeservice.json'])!=recipe['timeservice']:
        raise ValueError('rendered recipe binding')
    if (recipe['recovery_seconds']!=1800 or recipe['apply_max_seconds']!=120 or recipe['max_probes']!=40
            or recipe['probe_interval_seconds']!=30 or recipe['stable_probes']!=3 or recipe['acceptance_reserve_seconds']!=60
            or recipe['timeservice']['startup_gate']!={'timeout_seconds':30,'matching_samples_per_source':5,'units':{'TOFF':'NTP0','PPS':'NTP2'}}
            or recipe['timeservice']['gpsd']!=['/usr/local/sbin/gpsd','-b','-N','-n','-s','115200','/dev/serial0','/dev/pps0']
            or recipe['timeservice']['ntpd']!=['/usr/local/sbin/ntpd','-n','-m','-c','/etc/ntp.conf','-u','ntp:ntp']):raise ValueError('closed runtime bounds/profile required')
    if sha(files['leap-seconds.list'])!=recipe['leapfile']['sha256']:raise ValueError('pinned leap input')
    for name in ('stage.py','client.py','measure.py','timeservice.py','gpsd-pairing.py'):
        compile(files[name],name,'exec')


def prepare(bundle,checksum):
    c=load(ROOT/'scripts/run-foundation-preflight.py');raw=c.private_file(bundle,64*1024**2)
    if sha(raw)!=checksum:raise ValueError('exact approved bundle SHA-256 required')
    files=unpack(raw);spec=json.loads(files['spec.json']);validate(spec,files)
    if any(files[n]!=(ROOT/p).read_bytes() for n,p in INPUT_PATHS.items()) or c.private_file(bundle.parent/'known_hosts',4096)!=files['known_hosts']:
        raise ValueError('current reviewed inputs changed; reseal and obtain new approval')
    for mode in MODES:compile(payload(spec,files,mode),'sealed-payload','exec')
    return spec,files


def payload(spec,files,mode,proofs=None):
    if mode not in MODES:raise ValueError('closed transport mode')
    body={n:base64.b64encode(files[n]).decode() for n in spec['members']}
    return ('import base64,json\nfiles={n:base64.b64decode(v) for n,v in '+repr(body)+'.items()}\n'
            'spec=json.loads('+repr(json.dumps(spec))+')\n'
            'ns={"__name__":"sealed_cutover","__file__":spec["stage"]+"/stage.py"}\n'
            'exec(compile(files["stage.py"],"sealed-cutover","exec"),ns)\n'
            'status=0\ntry: result=ns["entry"](spec,files,'+repr(mode)+','+repr(proofs)+')\n'
            'except BaseException as e: status=2; result={"phase":"held","error":str(e)[:500]}\n'
            'print(json.dumps({"spec_sha256":ns["sha"](ns["encoded"](spec)),"result":result},sort_keys=True))\n'
            'print("CUTOVER_EXIT_STATUS="+str(status))\nraise SystemExit(status)\n').encode()


def review(spec):
    expiry=datetime.fromtimestamp(spec['expires_epoch'],timezone.utc).isoformat()
    return f'''# GPSD/NTPsec service cutover: {spec['operation_id']}

Target **{spec['hostname']}**, boot `{spec['boot_id']}`; expires **{expiry}**.
Addresses: {', '.join(spec['endpoints'])}. One start; no reboot or receiver setting writes.
Archive contains all non-secret inputs, current recipes, tests and governing documents.
The workstation lacks the pinned ntpleapfetch executable; exact unit/executable validation
therefore remains mandatory on the target before activation.
Root-owned 0700 stage: `{spec['stage']}`; retain backups and all prior evidence.

Install the reviewed supervisor, pairing helper, NTP/supervisor configuration, service unit,
LAN-only Avahi configuration, pinned leap list, leap maintenance unit/timer and owned
drift/statistics directories. Back up exact previous bytes/metadata first. Reject drift,
collisions, changed boot, foreign SHM ownership/membership and unreviewed unit overrides.
Restart Avahi, stop bootstrap timesyncd, start supervised GPSD and NTPsec. This disciplines
the system clock; recovery restores service/files, not elapsed time or clock corrections.
GPSD uses -b and explicit serial0/pps0 at 115200; no GNSS configuration or IPC deletion.
NTP0 serial NMEA is selectable without calibration; NTP2 PPS is preferred. All three
reviewed NTS servers are configured. Serve only Default LAN IPv4/ULA clients;
administrative queries remain localhost-only. ntpd -m publishes through eth0-only Avahi.

Before ntpd launches, require five independent leap-0 timestamp matches for each
observed SHM source within 30 seconds (plus at most 15 seconds socket readiness).
Stop monitors before ntpd reads SHM. Require early localhost ntpd response and expose
the result within the start readback. Failure stops the pair and restores the baseline.
No automatic replay of a lost or failed start. Apply is independently limited to 120 seconds.

Arm an independent 1800-second systemd recovery timer before mutations. Up to 40
probes at least 30 seconds apart require three consecutive successful observations:
PPS selected/reachable, serial reachable, leap 0, stratum 1, absolute PPS offset <=5 ms and jitter <=1 ms,
all three configured NTS peers authenticated/reachable with cookies, same supervisor,
bootstrap stopped. Thresholds are initial service gates, not calibrated accuracy claims.
Verify packages/native files, accounts/loader, boot/network/hardware and installed inputs.
Require both SSH endpoints plus this workstation's IPv4/IPv6 NTP response, denied external
mode-6 queries and `_ntp._udp.local` SRV port 123 with the host's fixed A/AAAA records.
Workstation multicast/reachability is not assumed. Failed client checks prevent acceptance.

Only then enable timeservice, disable timesyncd, enable/start the four-week leap timer,
record durable acceptance and cancel recovery. The timer's first check occurs after
15 minutes plus up to 30 minutes random delay; subsequent checks use the approved
IANA HTTPS source with bounded retries. ntpd reloads the leapfile without a restart.
Maintenance fetch is authorized by this cutover only after acceptance.

On failure/timeout, stop the pair/timer, restore exact backups, preserve bounded generated
statistics as private evidence, restore UART termios, restart Avahi and bootstrap timesyncd,
and verify original runtime continuity. Unexplained drift holds recovery for inspection.
There is no automatic recovery across a reboot. Conditional readbacks (up to 60), one
explicit recovery and terminal cleanup are covered; no second cutover start. Cleanup
requires matching dual-endpoint accepted/recovered receipts and retains stage/evidence.
Acceptance is initial operation, not long-term timing, holdover, monitoring or reboot acceptance.

Execute only after separate approval of this archive's SHA-256:
`python3 -I -B ntpsec/scripts/run-service-cutover.py execute --bundle <absolute-archive> --sha256 <approved-hash> --mode start`
Use the same archive/hash with numbered `probe`/`readback`; `accept` performs both endpoint
proofs and workstation checks, then commits acceptance. On uncertainty use readback;
never replay start. Use `recover` if needed, then dual-stack readback and `cleanup`.
'''


def seal(args):
    c=load(ROOT/'scripts/run-foundation-preflight.py')
    raw=c.private_file(args.receiver_dir/'gpsd-acquisition.tar',32*1024**2)
    if sha(raw)!=args.receiver_sha256:raise ValueError('accepted receiver archive digest')
    reference=unpack(raw);old=json.loads(reference['spec.json'])
    receipt=c.private_file(args.receiver_dir/'acceptance.json');accepted=json.loads(receipt);reports={}
    for path in sorted(args.receiver_dir.glob('readback-*-result.json')):
        response=json.loads(c.private_file(path,96*1024**2));report=response.get('result',{})
        if sha(encoded(report))!=accepted['report_sha256']:continue
        submitted=json.loads(c.private_file(path.with_name(path.name.replace('-result.json','-submission.json'))))
        endpoint=next(x[4:] for x in submitted['argv'] if x.startswith('ama@'))
        if response['spec_sha256']==sha(reference['spec.json']) and endpoint in old['endpoints']:reports[endpoint]=report
    if set(reports)!=set(old['endpoints']):raise ValueError('both accepted endpoint reports required')
    report=next(iter(reports.values()))
    files={n:(ROOT/p).read_bytes() for n,p in INPUT_PATHS.items()};recipe=json.loads(files['recipe.json'])
    files.update({'reference.tar':raw,'reference.py':reference['worker.py'],'reference-report.json':encoded(report),
                  'reference-receipt.json':receipt,'reference-cleanup.json':c.private_file(args.receiver_dir/'cleanup-0-result.json'),
                  'receiver-runtime.json':base64.b64decode(report['evidence']['receiver-runtime.json']['base64']),
                  'known_hosts':reference['known_hosts'],'timeservice.json':encoded(recipe['timeservice'])})
    epoch=int(time.time());spec={k:old[k] for k in ('hostname','kernel','boot_id','endpoints','old_ipv4')}
    spec.update(schema=1,operation_id=args.operation_id,stage='/var/lib/ntp-acquire-'+args.operation_id,
                apply_unit='ntp-cutover-'+args.operation_id,recovery_unit='ntp-cutover-'+args.operation_id+'-recovery',
                prepared_epoch=epoch,expires_epoch=min(epoch+86400,old['expires_epoch']),recipe=recipe,
                members={n:sha(v) for n,v in files.items()})
    files['spec.json']=encoded(spec);files['review.md']=review(spec).encode();files['manifest.json']=encoded({n:sha(v) for n,v in files.items()})
    validate(spec,files)
    if spec['expires_epoch']-epoch<3600:raise ValueError('insufficient accepted input freshness for cutover')
    os.umask(0o077);args.output.mkdir(mode=0o700)
    for n in ('spec.json','review.md','known_hosts'):(args.output/n).write_bytes(files[n])
    bundle=args.output/'service-cutover.tar'
    with tarfile.open(bundle,'w',format=tarfile.USTAR_FORMAT) as archive:
        for name,data in sorted(files.items()):
            item=tarfile.TarInfo(name);item.mode=0o600;item.size=len(data);item.mtime=epoch;archive.addfile(item,io.BytesIO(data))
    checksum=sha(bundle.read_bytes());prepare(bundle,checksum)
    result={'bundle':str(bundle),'sha256':checksum,'target':spec['hostname'],'expires_epoch':spec['expires_epoch'],'target_contact':False,'execution_authorized':False}
    c.write_new(args.output/'sealing.json',result);return result


def request(c,directory,spec,files,checksum,mode,stem,endpoint,proofs=None):
    argv=c.transport(directory,endpoint);argv[3]='240s'
    argv[argv.index('ama@'+endpoint):argv.index('ama@'+endpoint)]=['-o','HostKeyAlias='+spec['old_ipv4']]
    data=payload(spec,files,mode,proofs)
    c.write_new(directory/(stem+'-submission.json'),{'argv':argv,'payload_sha256':sha(data),'bundle_sha256':checksum})
    with (directory/(stem+'.stdout')).open('xb') as out,(directory/(stem+'.stderr')).open('xb') as err:
        p=subprocess.run(argv,input=data,stdout=out,stderr=err,check=False,env={'PATH':'/usr/bin:/bin','LC_ALL':'C','SSH_AUTH_SOCK':os.environ['SSH_AUTH_SOCK']})
    c.write_new(directory/(stem+'-transport.json'),{'status':p.returncode})
    raw=c.private_file(directory/(stem+'.stdout'),16*1024**2);match=re.fullmatch(rb'(.*)\nCUTOVER_EXIT_STATUS=([02])\n',raw,re.S)
    if not match:raise ValueError('terminal lost; retain evidence and use conditional readback, never repeat start')
    response=json.loads(match[1]);c.write_new(directory/(stem+'-result.json'),response)
    if p.returncode!=int(match[2]) or response['spec_sha256']!=sha(files['spec.json']):raise ValueError('transport/spec mismatch')
    if p.returncode:raise ValueError(response['result'].get('error','cutover held'))
    return response['result']


def terminal_receipt(spec,checksum,results):
    if set(results)!=set(spec['endpoints']) or len({sha(encoded(v)) for v in results.values()})!=1:raise ValueError('matching dual-endpoint state required')
    state=next(iter(results.values()))
    if state['phase'] not in ('accepted','recovered'):return None
    return {'state':state['phase'],'bundle_sha256':checksum,'spec_sha256':sha(encoded(spec)),'state_sha256':sha(encoded(state))}


def execute(args):
    os.umask(0o077);c=load(ROOT/'scripts/run-foundation-preflight.py');bundle=args.bundle.absolute()
    spec,files=prepare(bundle,args.sha256);directory=bundle.parent
    if args.mode=='start':
        if not spec['prepared_epoch']-300<=time.time()<spec['expires_epoch']-spec['recipe']['recovery_seconds']:raise ValueError('full trial must fit accepted execution window')
    elif json.loads(c.private_file(directory/'start-execution.json'))['bundle_sha256']!=args.sha256:raise ValueError('registered start required')
    if args.mode=='cleanup':
        receipt=json.loads(c.private_file(directory/'terminal-receipt.json'))
        if receipt['bundle_sha256']!=args.sha256 or receipt['state'] not in ('accepted','recovered'):raise ValueError('accepted/recovered readback receipt required')
    numbered=args.mode in ('readback','probe');label=args.mode+('-'+str(args.attempt) if numbered else '')
    if args.mode=='probe' and args.attempt>40:raise ValueError('probe budget')
    if numbered and args.attempt>1:
        previous=json.loads(c.private_file(directory/(args.mode+'-'+str(args.attempt-1)+'-execution.json')))
        if time.time()-previous['epoch']<30:raise ValueError('bounded observation interval')
    c.write_new(directory/(label+'-execution.json'),{'bundle_sha256':args.sha256,'epoch':int(time.time())})
    if args.mode=='accept':
        proofs={e:request(c,directory,spec,files,args.sha256,'readback',label+'-proof-'+str(i),e) for i,e in enumerate(spec['endpoints'])}
        if any(v['phase']!='ready' for v in proofs.values()):raise ValueError('stable target required before client checks')
        client=load(ROOT/'scripts/check-time-client.py');proofs['client']=client.check(spec,sha(files['spec.json']))
        c.write_new(directory/'client-proof.json',proofs['client'])
        results={spec['endpoints'][0]:request(c,directory,spec,files,args.sha256,'accept',label+'-0',spec['endpoints'][0],proofs)}
    else:
        endpoints=spec['endpoints'] if args.mode=='readback' else spec['endpoints'][:1]
        results={e:request(c,directory,spec,files,args.sha256,args.mode,label+'-'+str(i),e) for i,e in enumerate(endpoints)}
    if args.mode=='readback':
        receipt=terminal_receipt(spec,args.sha256,results)
        if receipt:
            path=directory/'terminal-receipt.json'
            if path.exists():
                if json.loads(c.private_file(path))!=receipt:raise ValueError('terminal receipt conflict')
            else:c.write_new(path,receipt)
    return {'mode':args.mode,'results':{e:{k:v[k] for k in ('phase','gate','last_measurement','transient_cleanup') if k in v} for e,v in results.items()}}


def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='action',required=True)
    p=sub.add_parser('seal');p.add_argument('--receiver-dir',type=Path,required=True);p.add_argument('--receiver-sha256',required=True)
    p.add_argument('--operation-id',required=True);p.add_argument('--output',type=Path,required=True)
    p=sub.add_parser('execute');p.add_argument('--bundle',type=Path,required=True);p.add_argument('--sha256',required=True)
    p.add_argument('--mode',choices=MODES,required=True);p.add_argument('--attempt',type=int,choices=range(1,61),default=1)
    args=parser.parse_args();print(json.dumps(seal(args) if args.action=='seal' else execute(args),sort_keys=True))


if __name__=='__main__':main()
