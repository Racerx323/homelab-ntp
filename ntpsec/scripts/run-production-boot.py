#!/usr/bin/python3
"""Seal and run a flat, console-backed production boot validation."""
import argparse
import base64
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import re
import tarfile
import time
import importlib.util

ROOT=Path(__file__).resolve().parents[1]


def load(path):
    spec=importlib.util.spec_from_file_location(path.stem.replace('-','_'),path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


parent=load(ROOT/'scripts/run-production-transition.py')
helper=parent.helper
sha=helper.sha
encoded=helper.encoded
PATHS={**parent.PATHS,'runner.py':'scripts/run-production-boot.py',
       'transition-runner.py':'scripts/run-production-transition.py',
       'production-boot.py':'scripts/production-boot.py',
       'host-configuration-stage.py':'scripts/host-configuration-stage.py',
       'check-pps.py':'scripts/check-pps.py','hardware-recipe.json':'configs/host-hardware-recipe.json',
       'boot-tests.py':'tests/test_production_boot.py',
       'rtc-commissioning.py':'scripts/rtc-commissioning.py'}
EXTRA=parent.EXTRA
BUNDLE='production-boot.tar'


def review(spec):
    if spec['purpose']=='production-boot-recovery':
        return f'''# Bootstrap-only recovery after blocked boot preparation

Target **j2-svntp1**, operation `{spec['operation_id']}`.
Failed boot archive SHA-256: `{spec['failed_boot_sha256']}`.

This operation permits recovery/readback only. It cannot enable NTP, restart
the time server, submit a reboot, or perform boot acceptance.

Stage current repository code and selected baseline/state data in a new sibling
directory. Verify the unchanged source-stage specification and state hashes,
same boot, installed files, native binary hashes/modes and retained drift before
recovery. Use the protected 16 MiB executable reader for native binaries;
the 1 MiB configuration snapshot limit does not apply to executable identity.
Historical code is never loaded and the original stage is not modified.

Retain service journal/startup-gate diagnostics. Stop timeservice and prove its
children gone; disable it for boot. Enable/start systemd-timesyncd and verify
the resulting states. Preserve all configuration, boot files, drift and evidence.
NTP serving remains stopped. Starting timesyncd does not prove synchronization.
Unexpected continuity, file or unit drift holds recovery without overwriting it.

The operation remains recovery-only after the original execution expiry.
No reboot or console/media action is requested. After explicit approval:

```bash
python3 -I -B ntpsec/scripts/run-production-boot.py execute --bundle ABSOLUTE_BUNDLE --sha256 APPROVED_SHA256 --mode recover --attempt 1
```
'''
    expiry=datetime.fromtimestamp(spec['expires_epoch'],timezone.utc).isoformat()
    start=datetime.fromtimestamp(spec['start_before_epoch'],timezone.utc).isoformat()
    verification=('Use one bounded read-only check per call; return pending acquisition for later resume.'
                  if spec.get('acquisition_wait') else 'Make at most 20 read-only verification attempts, at least 30 seconds apart.')
    rtc_note=('''RTC persistence scope: recheck the commissioned utility, RV3028 identity, UTC
policy, fake-clock absence and read-only RTC/system-time agreement before stopping
services. After reboot repeat identity/readback and retain the new boot's kernel
RV3028 system-clock initialization message within the pre/post reboot time bracket.
No RTC write, system-clock adjustment or power-off test is authorized. Warm reboot
persistence does not establish battery-backed retention through power loss.
The prerequisite RTC commissioning and final client receipts are pinned in the
baseline; all checks use repository code, without nested archives.
''' if spec.get('rtc_persistence') else '')
    acquisition_note=('''The installed wait policy keeps acquisition pending without a total deadline.
Each verification call returns pending while the protected gate is fresh and
belongs to the current boot, supervisor and GPSD. Resume with a fresh attempt
number; do not resubmit reboot. A stale gate, changed identity or failed service
is a fault, not acquisition. After pairing passes, structural readiness has 120
seconds and handoff has 600 seconds (60-second reserve). A successful pending
reply ends the controller call; later resume checks continue the same startup.
Expiry prevents a new apply/reboot, but permits continuation of the initiated
acquisition, readback and recovery. No reboot-persistent watchdog is introduced.
''' if spec.get('acquisition_wait') else '''The installed bounded supervisor retains its 30-second pairing gate.
This review does not certify cold receiver acquisition. Gate failure or automatic
restart fails structural acceptance; retain diagnostics before recovery.
''')
    return f'''# Controlled boot and persistence review

Target **j2-svntp1**, operation `{spec['operation_id']}`.
Approved restart prerequisite: `{spec['restart_sha256']}`.
Ready restart observation: `{spec['observation_sha256']}`.
Hardware acceptance receipt: `{spec['hardware_receipt_sha256']}`.
Flat package: repository code/tests and selected pinned data; no nested archives.

## Execution and mutation boundary

Execution requires explicit approval of this archive SHA-256 and confirmation
that console/media recovery is available (`--console-ready`). The current
service is kept running until that separately approved execution.

1. Revalidate accepted same-boot process identities, configuration, binaries,
   hardware mapping, drift and idle prior workers. Capture current boot files
   and kernel. Reject changed inputs before mutation.
2. Disable systemd-timesyncd boot startup; enable timeservice. Stop timeservice
   cleanly and retain its final learned drift and protocol statistics cursor.
3. Persist reboot intent and submit exactly one nonblocking systemctl reboot.
   A lost reply is uncertain submission, never permission to submit another.
4. {verification}
   Require a new boot, unchanged kernel/boot files/configuration, enabled
   timeservice, disabled/inactive timesyncd, zero automatic restarts, accepted
   GPSD/ntpd credentials and argv, GPIO PPS/UART/RTC mapping and fresh SHM creators
   with both consumers. Verify the first new protocol frequency seed matches
   stopped drift. All five associations must exist, but timing may still settle.
5. Require dual-stack pinned-key SSH readbacks and structural IPv4/IPv6 client
   responses/query denial. Commit structural handoff to continuous operation.
   Observe convergence separately at 30 seconds degraded / 300 seconds ready,
   up to 60 observations in this window. No timing-quality shutdown deadline.

{acquisition_note}
{rtc_note}

No boot-file/configuration replacement, drift reset, package installation,
receiver configuration, leap-timer change, evidence cleanup or second reboot.
Final synchronized client/native Windows discovery acceptance follows convergence;
structural boot handoff alone is not production acceptance.

## Recovery and interruption

There is **no automatic reboot-persistent watchdog** in this operation.
The controller attempts inspected bootstrap-only recovery after preparation,
verification or handoff failure. If the controller or network is lost, use the
console. Unreachable boot or damaged media requires manual console/media recovery.
Do not depend on an old transient timer surviving the reboot.

Recovery works on either boot and after the execution window expires. It verifies
pinned installed/boot files and supported enablement states, stops timeservice,
proves its children gone, restores timeservice disabled / timesyncd enabled,
and starts timesyncd. It preserves drift, configurations and diagnostics. The node
stops serving NTP; bootstrap synchronization is not claimed merely from startup.
Unexpected file/identity drift holds recovery for operator inspection.

Console command (readback first; recover only after inspecting it):

```bash
sudo /usr/bin/python3 -I -B {spec['stage']}/production-boot.py worker readback SPEC_SHA256
sudo /usr/bin/python3 -I -B {spec['stage']}/production-boot.py worker recover SPEC_SHA256
```

Use SHA-256 of the sealed `spec.json` for SPEC_SHA256. The bundle checksum is
recorded separately in `sealing.json`. Console/media access must not disrupt
the primary server or its shared antenna-power path.

## Window and command

Inherited inspection expiry: `{expiry}` (epoch `{spec['expires_epoch']}`).
Begin enablement/reboot before `{start}` (epoch `{spec['start_before_epoch']}`; 15-minute
reserve). No stale observation window is silently extended.

From the repository root, after approval and confirmation of recovery access:

```bash
python3 -I -B ntpsec/scripts/run-production-boot.py execute --bundle ABSOLUTE_BUNDLE --sha256 APPROVED_SHA256 --mode apply --console-ready
```

`--mode resume` verifies an already submitted reboot without submitting another;
`--mode recover` and `--mode readback` remain available after expiry.
'''


def validate(spec,files):
    if type(spec.get('rtc_persistence',False)) is not bool:raise ValueError('boolean RTC scope required')
    if type(spec.get('acquisition_wait',False)) is not bool or spec.get('install_acquisition'):
        raise ValueError('boot preserves installed acquisition policy')
    extra={'recovery-source.json','recovery-state.json'} if spec['purpose']=='production-boot-recovery' else set()
    if (spec['schema']!=1 or spec['purpose'] not in ('production-boot','production-boot-recovery') or spec['hostname']!='j2-svntp1'
            or spec['action']!='restart' or not re.fullmatch(r'[a-z][a-z0-9-]{0,47}',spec['operation_id'])
            or spec['stage']!='/var/lib/ntp-boot-'+spec['operation_id']
            or spec['members']!={n:sha(files[n]) for n in set(PATHS)|EXTRA|extra}
            or files['review.md']!=review(spec).encode()
            or not spec['prepared_epoch']<spec['start_before_epoch']<spec['expires_epoch']
            or spec['expires_epoch']-spec['prepared_epoch']>86400
            or spec['start_before_epoch']!=spec['expires_epoch']-900):raise ValueError('closed boot input binding')
    probe=dict(spec,purpose='production-inspection',monitor_operation_id='baseline',
               stage='/var/lib/ntp-acquire-baseline',apply_unit='ntp-monitor-baseline',
               recovery_unit='ntp-monitor-baseline-watchdog',monitor_sha256='0'*64)
    helper.validate(probe)
    baseline=json.loads(files['baseline.json'])
    if spec.get('rtc_persistence') and (set(baseline.get('rtc_commissioning',{}))!={'bundle_sha256','result_sha256','readback'} or not baseline.get('final_client_sha256')):
        raise ValueError('RTC commissioning and final client prerequisites required')
    if set(baseline['files'])!=set(helper.INSTALLED):raise ValueError('complete installed baseline required')
    if set(baseline['boot_units'])!={'gpsd.service','gpsd.socket','ntpsec.service','avahi-daemon.service','ntpleapfetch.timer'}:
        raise ValueError('complete boot prerequisite unit baseline required')
    for name,member in parent.load(ROOT/'scripts/production-transition.py').CHANGES.items():
        if sha(files[member])!=baseline['files'][name]['sha256']:raise ValueError('boot must preserve configurations')
    if files['timeservice.service']!=(ROOT/'templates/timeservice.service').read_bytes():raise ValueError('ordinary unit required')
    recipe=json.loads((ROOT/'configs/service-cutover-recipe.json').read_text())
    if spec.get('acquisition_wait'):
        recipe['timeservice']['startup_gate']=json.loads(files['production-startup-gate.json'])
        for name,member in parent.load(ROOT/'scripts/production-transition.py').RUNTIME.items():
            if baseline['files'][name]['sha256']!=sha(files[member]):raise ValueError('installed acquisition runtime binding')
    if json.loads(files['timeservice.json'])!=recipe['timeservice']:raise ValueError('ordinary supervisor required')


def prepare(bundle,checksum):
    raw=helper.private(bundle,4*1024**2)
    if sha(raw)!=checksum:raise ValueError('approved boot digest')
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        members=archive.getmembers()
        spec=json.load(archive.extractfile('spec.json'))
        extra={'recovery-source.json','recovery-state.json'} if spec['purpose']=='production-boot-recovery' else set()
        names=set(PATHS)|EXTRA|extra|{'spec.json','review.md'}
        if len(members)!=len(names) or {m.name for m in members}!=names or any(not m.isfile() or m.size>1024**2 for m in members):
            raise ValueError('closed flat boot archive')
        files={m.name:archive.extractfile(m).read() for m in members}
    spec=json.loads(files['spec.json']);validate(spec,files)
    for name,path in PATHS.items():
        if files[name]!=(ROOT/path).read_bytes():raise ValueError('current executable input drift')
    for name in ('spec.json','review.md','known_hosts'):
        if helper.private(bundle.parent/name)!=files[name]:raise ValueError('local approval input drift')
    return spec,files


def seal(args):
    rtc_inputs=[getattr(args,name,None) for name in ('rtc_dir','rtc_sha256','client_dir','client_sha256')]
    if any(value is not None for value in rtc_inputs) and not all(rtc_inputs):
        raise ValueError('RTC and final client directories and digests must be supplied together')
    directory=args.restart_dir
    raw=helper.private(directory/'production-transition.tar')
    if sha(raw)!=args.restart_sha256:raise ValueError('restart archive mismatch')
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        prior={n:archive.extractfile(n).read() for n in ('spec.json','baseline.json','known_hosts','ntp.conf','timeservice.json','timeservice.service')}
    old=json.loads(prior['spec.json']);baseline=json.loads(prior['baseline.json'])
    if old['purpose']!='production-transition' or old['action']!='restart':raise ValueError('controlled restart required')
    for name in prior.keys()-{'spec.json'}:
        if sha(prior[name])!=old['members'][name]:raise ValueError('accepted restart data binding')
    if old.get('install_acquisition'):
        with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
            for name,member in parent.load(ROOT/'scripts/production-transition.py').RUNTIME.items():
                content=archive.extractfile(member).read()
                if sha(content)!=old['members'][member]:raise ValueError('accepted runtime binding')
                baseline['files'][name].update(sha256=sha(content),base64=base64.b64encode(content).decode())
    observation=helper.private(directory/f'observe-{args.observation}-outcome.json');outcome=json.loads(observation)
    state=json.loads(helper.private(directory/f'observe-{args.observation}-result.json'))
    transport=json.loads(helper.private(directory/f'observe-{args.observation}-transport.json'))
    execution=json.loads(helper.private(directory/f'observe-{args.observation}-execution.json'))
    handoff=parent.handoff_result(directory,args.restart_sha256)
    health=state['health'];now=int(time.time())
    if (outcome['bundle_sha256']!=args.restart_sha256 or outcome.get('error') or outcome['state']!=state
            or state['phase']!='monitoring' or not outcome['timing_ready'] or not parent.timing_ready(health['measurement'])
            or transport.get('returncode')!=0 or transport.get('error') or execution['sha256']!=args.restart_sha256
            or execution['mode']!='observe' or not execution['epoch']<=health['epoch']<=now
            or now-health['epoch']>=86400 or handoff['bundle_sha256']!=args.restart_sha256 or handoff.get('error')
            or handoff['state']['phase']!='monitoring' or handoff['state']['boot_id']!=baseline['boot_id']
            or health['pair']!=handoff['state']['health']['pair'] or handoff['state']['drift_seed_observed'] is not True
            or health['unit']['ActiveState']!='active' or health['unit']['UnitFileState']!='disabled'
            or health['unit']['NRestarts']!='0'):raise ValueError('accepted restart and ready observation required')
    rtc_scope=getattr(args,'rtc_dir',None) is not None
    if rtc_scope:
        rtc_dir=args.rtc_dir
        rtc_raw=helper.private(rtc_dir/'rtc-commissioning.tar')
        if sha(rtc_raw)!=args.rtc_sha256:raise ValueError('RTC commissioning archive binding')
        with tarfile.open(fileobj=io.BytesIO(rtc_raw)) as archive:rtc_spec=json.load(archive.extractfile('spec.json'))
        rtc_result_raw=helper.private(rtc_dir/'result.json');rtc_result=json.loads(rtc_result_raw)
        rtc_state=json.loads(helper.private(rtc_dir/'stdout.txt'))
        if (rtc_spec['action']!='set-readback' or rtc_spec['boot_id']!=baseline['boot_id']
                or rtc_spec['hostname']!=old['hostname'] or rtc_result.get('accepted') is not True
                or rtc_result.get('returncode')!=0 or rtc_result['bundle_sha256']!=args.rtc_sha256
                or rtc_state.get('accepted') is not True or rtc_state.get('error')
                or rtc_state['operation_id']!=rtc_spec['operation_id']):raise ValueError('accepted same-boot RTC commissioning required')
        load(ROOT/'scripts/rtc-commissioning.py').check_readback(rtc_state['rtc_after'])
        client_raw=helper.private(args.client_dir/'client-native-discovery.tar')
        if sha(client_raw)!=args.client_sha256:raise ValueError('final client archive binding')
        with tarfile.open(fileobj=io.BytesIO(client_raw)) as archive:client_spec_raw=archive.extractfile('spec.json').read()
        client_spec=json.loads(client_spec_raw);client=json.loads(helper.private(args.client_dir/'result.json'))
        if (client.get('client_accepted') is not True or client.get('error')
                or client['bundle_sha256']!=args.client_sha256 or client['spec_sha256']!=sha(client_spec_raw)
                or client['checks']!=dict.fromkeys(('ipv4','ipv6','mdns','queries_denied'),True)
                or client_spec['monitor_sha256']!=args.restart_sha256
                or client_spec['monitor_spec_sha256']!=sha(prior['spec.json'])
                or client_spec['observation_sha256']!=sha(observation)
                or client_spec['hostname']!=old['hostname'] or client_spec['endpoints']!=old['endpoints']
                or not health['epoch']<=client['epoch']<=now):raise ValueError('accepted current final client proof required')
        baseline['rtc_commissioning']={'bundle_sha256':args.rtc_sha256,'result_sha256':sha(rtc_result_raw),'readback':rtc_state['rtc_after']}
        baseline['final_client_sha256']=args.client_sha256
    hardware_receipt=helper.private(args.hardware_dir/'acceptance.json');receipt=json.loads(hardware_receipt)
    report=json.loads(helper.private(args.hardware_dir/'start-0-result.json'))['result']
    hw_spec=json.loads(helper.private(args.hardware_dir/'spec.json'))
    hw_archive=helper.private(args.hardware_dir/'runtime-revalidation.tar',16*1024**2)
    if sha(hw_archive)!=receipt['bundle_sha256']:raise ValueError('hardware archive binding')
    with tarfile.open(fileobj=io.BytesIO(hw_archive)) as archive:
        if json.load(archive.extractfile('spec.json'))!=hw_spec:raise ValueError('hardware specification binding')
    if (receipt['state']!='runtime_validated' or receipt['report_sha256']!=sha(encoded(report))
            or receipt['spec_sha256']!=sha(encoded(hw_spec)) or report['phase']!='runtime_validated'
            or hw_spec['hostname']!=old['hostname'] or report['boot_id']!=baseline['boot_id']
            or report['checks']!=dict.fromkeys(('continuity','failed_stage','hardware','idle_workers','restoration','runtime','source_preserved'),True)):
        raise ValueError('accepted same-boot hardware report required')
    for name,member in parent.load(ROOT/'scripts/production-transition.py').CHANGES.items():
        baseline['files'][name].update(sha256=sha(prior[member]),base64=base64.b64encode(prior[member]).decode())
    baseline.update(supervisor_pid=int(health['unit']['MainPID']),running_pair=health['pair'],hardware=report['hardware'])
    capture_raw=helper.private(args.inspection_dir/'stdout.txt')
    if sha(capture_raw)!=baseline['capture_sha256']:raise ValueError('original inspection capture binding')
    capture=json.loads(capture_raw)
    if capture['boot_before']!=baseline['boot_id'] or capture['boot_after']!=baseline['boot_id']:
        raise ValueError('inspection boot binding')
    baseline['boot_units']={}
    for name in ('gpsd.service','gpsd.socket','ntpsec.service','avahi-daemon.service','ntpleapfetch.timer'):
        command=capture['commands'][name]
        if command.get('returncode')!=0 or command.get('error'):raise ValueError('inspected unit command incomplete')
        row=parent.load(ROOT/'scripts/production-transition.py').properties(command['stdout'])
        baseline['boot_units'][name]={k:row[k] for k in ('LoadState','ActiveState','SubState','UnitFileState','DropInPaths')}
    expires=old['expires_epoch']
    if expires-now<1800:raise ValueError('fresh inspection window required')
    spec={**old,'purpose':'production-boot','operation_id':args.operation_id,
          'stage':'/var/lib/ntp-boot-'+args.operation_id,'prepared_epoch':now,
          'start_before_epoch':expires-900,'expires_epoch':expires,'restart_sha256':args.restart_sha256,
          'observation_sha256':sha(observation),'hardware_receipt_sha256':sha(hardware_receipt),
          'old_units':list(dict.fromkeys([*old['old_units'],old['watchdog']+'.service',old['watchdog']+'.timer']))}
    spec['rtc_persistence']=rtc_scope
    spec.pop('install_acquisition',None)
    files={name:(ROOT/path).read_bytes() for name,path in PATHS.items()}
    files.update({name:prior[name] for name in ('known_hosts','ntp.conf','timeservice.json','timeservice.service')})
    files['baseline.json']=encoded(baseline);spec['members']={n:sha(v) for n,v in files.items()}
    files.update({'spec.json':encoded(spec),'review.md':review(spec).encode()});validate(spec,files)
    os.umask(0o077);args.output.mkdir(mode=0o700)
    for name in ('spec.json','review.md','known_hosts'):(args.output/name).write_bytes(files[name])
    bundle=args.output/BUNDLE
    with tarfile.open(bundle,'w') as archive:
        for name,value in sorted(files.items()):
            info=tarfile.TarInfo(name);info.size=len(value);info.mode=0o600;archive.addfile(info,io.BytesIO(value))
    digest=sha(bundle.read_bytes());prepare(bundle,digest)
    result={'sha256':digest,'bundle':str(bundle),'spec_sha256':sha(files['spec.json']),
            'expires_epoch':expires,'start_before_epoch':spec['start_before_epoch'],'target_contact':False,'execution_authorized':False}
    (args.output/'sealing.json').write_bytes(encoded(result));return result


def seal_recovery(args):
    raw=helper.private(args.failed_dir/BUNDLE,4*1024**2)
    if sha(raw)!=args.failed_sha256:raise ValueError('failed boot archive binding')
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        old=json.load(archive.extractfile('spec.json'))
        data={n:archive.extractfile(n).read() for n in EXTRA}
    if old['purpose']!='production-boot':raise ValueError('failed boot stage required')
    for name,value in data.items():
        if sha(value)!=old['members'][name]:raise ValueError('failed boot data binding')
    outcome=json.loads(helper.private(args.failed_dir/'apply-outcome.json'))
    state=json.loads(helper.private(args.failed_dir/'apply-failure-readback-result.json'))
    transport=json.loads(helper.private(args.failed_dir/'apply-failure-readback-transport.json'))
    execution=json.loads(helper.private(args.failed_dir/'apply-execution.json'))
    if (outcome['bundle_sha256']!=args.failed_sha256 or execution['sha256']!=args.failed_sha256
            or transport.get('returncode')!=0 or transport.get('error') or outcome['failure_readback']!=state
            or state['phase']!='ready_to_reboot' or 'reboot_submission_epoch' in state
            or state['boot_id']!=json.loads(data['baseline.json'])['boot_id']):
        raise ValueError('inspected pre-reboot failure state required')
    spec={**old,'purpose':'production-boot-recovery','operation_id':args.operation_id,
          'stage':'/var/lib/ntp-boot-'+args.operation_id,'failed_boot_sha256':args.failed_sha256}
    files={name:(ROOT/path).read_bytes() for name,path in PATHS.items()};files.update(data)
    files['recovery-state.json']=encoded(state)
    files['recovery-source.json']=encoded({'stage':old['stage'],'spec_sha256':sha(encoded(old)),'state_sha256':sha(encoded(state))})
    spec['members']={n:sha(v) for n,v in files.items()}
    files.update({'spec.json':encoded(spec),'review.md':review(spec).encode()});validate(spec,files)
    os.umask(0o077);args.output.mkdir(mode=0o700)
    for name in ('spec.json','review.md','known_hosts'):(args.output/name).write_bytes(files[name])
    bundle=args.output/BUNDLE
    with tarfile.open(bundle,'w') as archive:
        for name,value in sorted(files.items()):
            info=tarfile.TarInfo(name);info.size=len(value);info.mode=0o600;archive.addfile(info,io.BytesIO(value))
    digest=sha(bundle.read_bytes());prepare(bundle,digest)
    result={'sha256':digest,'bundle':str(bundle),'spec_sha256':sha(files['spec.json']),
            'target_contact':False,'execution_authorized':False,'recovery_only':True}
    (args.output/'sealing.json').write_bytes(encoded(result));return result


def payload(spec,files,mode,proof):
    data={n:base64.b64encode(v).decode() for n,v in files.items()}
    return f'''import base64,hashlib,importlib.util,json,os,socket,stat
from pathlib import Path
spec={spec!r}
root=Path(spec['stage'])
if os.geteuid()!=0 or socket.gethostname().split('.')[0]!=spec['hostname']:raise ValueError('target identity')
if {mode!r}=='apply' or (spec['purpose']=='production-boot-recovery' and {mode!r}=='recover' and not root.exists()):
    if not root.parent.is_dir() or root.parent.is_symlink():raise ValueError('stage parent')
    os.umask(0o077);root.mkdir(mode=0o700)
    for name,value in {data!r}.items():
        with (root/name).open('xb') as stream:stream.write(base64.b64decode(value))
info=root.lstat()
if not stat.S_ISDIR(info.st_mode) or info.st_uid or stat.S_IMODE(info.st_mode)!=0o700:raise ValueError('stage identity')
for name,digest in spec['members'].items():
    path=root/name;info=path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid or info.st_mode&0o022 or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:raise ValueError('stage member drift')
if (root/'spec.json').read_bytes()!=base64.b64decode({base64.b64encode(files['spec.json']).decode()!r}):raise ValueError('stage spec drift')
s=importlib.util.spec_from_file_location('boot',root/'production-boot.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
print(json.dumps(m.worker(root,{mode!r},{sha(encoded(spec))!r},{proof!r})))
'''.encode()


def remote(root,spec,files,mode,label,address,proof=None):
    request=payload(spec,files,mode,proof)
    argv=helper.ssh_argv(dict(spec,endpoints=[address,*spec['endpoints'][1:]]),root)
    with (root/(label+'-submission.json')).open('xb') as out:
        out.write(encoded({'mode':mode,'target':address,'payload_sha256':sha(request),'argv':argv}));out.flush();os.fsync(out.fileno())
    try:result=helper.bounded(argv,timeout=300 if mode in ('apply','recover') else 60,limit=8*1024**2,payload=request,env=os.environ.copy())
    except OSError as error:result={'returncode':None,'error':str(error),'stdout':'','stderr':''}
    for name in ('stdout','stderr'):(root/(label+'.'+name)).write_text(result.pop(name))
    (root/(label+'-transport.json')).write_bytes(encoded(result))
    if result.get('returncode')!=0 or result.get('error'):raise ValueError('remote '+label+' failed; output retained')
    value=json.loads((root/(label+'.stdout')).read_text());(root/(label+'-result.json')).write_bytes(encoded(value));return value


def execute(args):
    os.umask(0o077);root=args.bundle.absolute().parent
    spec,files=prepare(args.bundle.absolute(),args.sha256);now=int(time.time())
    if spec['purpose']=='production-boot-recovery' and args.mode not in ('recover','readback'):
        raise ValueError('recovery-only operation forbids activation/reboot')
    if args.mode not in ('recover','readback') and not (args.mode=='resume' and spec.get('acquisition_wait')) and not spec['prepared_epoch']-300<=now<spec['expires_epoch']:
        raise ValueError('execution window expired; readback/recovery remain available')
    if args.mode=='apply' and (not args.console_ready or now>=spec['start_before_epoch']):
        raise ValueError('confirmed console recovery and reboot reserve required')
    label=args.mode
    if args.mode in ('resume','observe','readback','recover'):
        if args.attempt<1 or (args.mode=='observe' and args.attempt>60):raise ValueError('unique bounded attempt required')
        label+='-'+str(args.attempt)
    if args.mode=='observe':
        if args.attempt==1:
            candidates=[root/'apply-outcome.json',*root.glob('resume-*-outcome.json')]
            outcomes=[json.loads(helper.private(p)) for p in candidates if p.exists()]
            accepted=[row for row in outcomes if row.get('state',{}).get('phase')=='monitoring' and not row.get('error')]
            if not accepted:raise ValueError('accepted boot handoff required before observations')
            old=max(accepted,key=lambda row:row['state']['health']['epoch'])
        else:old=json.loads(helper.private(root/f'observe-{args.attempt-1}-outcome.json'))
        if old.get('bundle_sha256')!=args.sha256:raise ValueError('observation bundle continuity')
        last=old['state']['health']['epoch']
        if now-last<(300 if old['timing_ready'] else 30):raise ValueError('observation interval')
    with (root/(label+'-execution.json')).open('xb') as out:
        out.write(encoded({'sha256':args.sha256,'mode':args.mode,'epoch':now}));out.flush();os.fsync(out.fileno())
    call=lambda mode,tag,address,proof=None:remote(root,spec,files,mode,label+'-'+tag,address,proof)
    result={'bundle_sha256':args.sha256,'production_accepted':False}
    try:
        if args.mode=='apply':
            call('apply','prepare',spec['endpoints'][0])
            try:call('reboot','reboot',spec['endpoints'][0])
            except (ValueError,OSError) as error:
                result['reboot_reply_uncertain']=str(error)
                try:submission=call('readback','reboot-status',spec['endpoints'][0])
                except (ValueError,OSError):submission=None
                if submission is not None and submission['phase']!='reboot_submitted':
                    raise ValueError('reboot was not submitted; recover inspected state')
        if args.mode in ('apply','resume'):
            for attempt in range(1,21):
                if not spec.get('acquisition_wait') and time.time()>=spec['expires_epoch']:raise ValueError('verification window expired')
                try:
                    state=call('verify','verify-'+str(attempt),spec['endpoints'][0])
                    if state['phase'] in ('starting','acquiring','monitoring','bootstrap_recovered'):
                        result.update(state=state,timing_ready=parent.timing_ready(state.get('health',{}).get('measurement',{})) if state['phase']=='monitoring' else False)
                        (root/(label+'-outcome.json')).write_bytes(encoded(result));return result
                    break
                except (ValueError,OSError):
                    if spec.get('acquisition_wait') or attempt==20:raise
                    time.sleep(30)
            proofs={'endpoints':{address:call('verify','endpoint-'+str(i),address) for i,address in enumerate(spec['endpoints'])}}
            proofs['client']=load(ROOT/'scripts/check-time-client.py').check(spec,sha(encoded(spec)),structural=True)
            (root/(label+'-client-proof.json')).write_bytes(encoded(proofs['client']))
            result['state']=call('accept','accept',spec['endpoints'][0],proofs)
        else:result['state']=call(args.mode,args.mode,spec['endpoints'][0])
    except BaseException as error:
        result['error']=str(error)
        if args.mode in ('apply','resume'):
            try:
                state=call('readback','failure-readback',spec['endpoints'][0]);result['failure_readback']=state
                if state['phase'] not in ('monitoring','bootstrap_recovered','acquiring'):
                    result['recovery']=call('recover','failure-recover',spec['endpoints'][0])
            except BaseException as recovery_error:result['followup_error']=str(recovery_error)
    result['timing_ready']=parent.timing_ready(result.get('state',{}).get('health',{}).get('measurement',{}))
    (root/(label+'-outcome.json')).write_bytes(encoded(result));return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='action',required=True)
    p=sub.add_parser('seal');p.add_argument('--restart-dir',type=Path,required=True);p.add_argument('--restart-sha256',required=True)
    p.add_argument('--observation',type=int,required=True);p.add_argument('--hardware-dir',type=Path,required=True)
    p.add_argument('--inspection-dir',type=Path,required=True)
    p.add_argument('--rtc-dir',type=Path);p.add_argument('--rtc-sha256')
    p.add_argument('--client-dir',type=Path);p.add_argument('--client-sha256')
    p.add_argument('--operation-id',required=True);p.add_argument('--output',type=Path,required=True)
    p=sub.add_parser('seal-recovery');p.add_argument('--failed-dir',type=Path,required=True);p.add_argument('--failed-sha256',required=True)
    p.add_argument('--operation-id',required=True);p.add_argument('--output',type=Path,required=True)
    p=sub.add_parser('execute');p.add_argument('--bundle',type=Path,required=True);p.add_argument('--sha256',required=True)
    p.add_argument('--mode',choices=['apply','resume','observe','readback','recover'],required=True)
    p.add_argument('--attempt',type=int,default=0);p.add_argument('--console-ready',action='store_true')
    args=parser.parse_args();result=seal(args) if args.action=='seal' else seal_recovery(args) if args.action=='seal-recovery' else execute(args)
    print(json.dumps(result));
    if result.get('error'):raise SystemExit(1)


if __name__=='__main__':main()
