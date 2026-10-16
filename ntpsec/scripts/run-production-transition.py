#!/usr/bin/python3
"""Seal a flat all-source transition and execute only its approved lifecycle."""
import argparse
import base64
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import tarfile
import time

ROOT=Path(__file__).resolve().parents[1]
PATHS={'runner.py':'scripts/run-production-transition.py',
       'production-transition.py':'scripts/production-transition.py',
       'inspection.py':'scripts/run-production-inspection.py',
       'measure.py':'scripts/measure-time-service.py','client.py':'scripts/check-time-client.py',
       'tests.py':'tests/test_production_transition.py',
       'timeservice.py':'scripts/timeservice.py','gpsd-pairing.py':'scripts/gpsd-pairing.py',
       'production-startup-gate.json':'configs/production-startup-gate.json'}
EXTRA={'baseline.json','timeservice.json','timeservice.service','ntp.conf','known_hosts'}


def load(path):
    spec=importlib.util.spec_from_file_location(path.stem.replace('-','_'),path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


helper=load(ROOT/'scripts/run-production-inspection.py')
encoded=helper.encoded
sha=helper.sha


def production_config(original):
    line=b'statistics loopstats peerstats clockstats\n'
    if original.count(line)!=1 or b'protostats' in original:
        raise ValueError('known statistics configuration required')
    return original.replace(line,line.rstrip(b'\n')+b' protostats\n')+b'\nfilegen protostats file protostats type day enable\n'


def review(spec):
    if spec.get('acquisition_wait'):
        return f'''# Acquisition-aware all-source startup

Target **{spec['hostname']}**, operation `{spec['operation_id']}`.
Action: `{spec.get('action','transition')}`. Install updated acquisition runtime:
`{bool(spec.get('install_acquisition'))}`. Execution requires this bundle's SHA-256 approval.
Prerequisite archive: `{spec['recovery_sha256']}`.
Client prerequisite: `{spec.get('client_prerequisite','final-native')}`. Structural
client checks do not establish synchronized timing or native-discovery acceptance;
repeat final client/discovery acceptance after this upgrade.
Start before epoch `{spec['start_before_epoch']}`; observation expiry
`{spec['expires_epoch']}`. These inherited limits are not extended by preparation.

Verify baseline files, native binaries, daemon identities, saved drift and idle
prior workers before mutation. For an acquisition upgrade, stop the accepted
service and atomically install the pinned supervisor, pairing helper and wait
recipe. Preserve ntp.conf and the systemd unit. Otherwise preserve the accepted
installed inputs. Keep saved drift; launch ntpd with all configured sources only
after five valid serial/PPS matches. No reboot or boot enablement is included.

Arm the independent watchdog before stopping the original time writer. Each
controller call returns a pending state during acquisition; resume never replays
startup. The first watchdog check is at 600 seconds, then every 30 seconds after
each check completes. A fresh protected gate from the same boot, supervisor and
GPSD invocation permits continued acquisition, without an elapsed-time cutoff.
Stale progress (75 seconds), wrong identities, failed gates, unexpected ntpd or
service faults cause bootstrap-only recovery. Missing initial gate is bounded
by 120 seconds. After pairing passes, allow 120 seconds for structural readiness
and 600 seconds for handoff, with the existing 60-second handoff reserve.

Require saved-drift protocol proof, all associations, dual-stack readbacks and
structural client replies/query denial before cancelling the watchdog. Timing
convergence and final client acceptance remain separate. Approval expiry bounds
initial apply; resume/readback/recovery of the initiated transaction remain
available afterward. Independent recovery retains drift and restores backed-up
files when installation occurred, then starts systemd-timesyncd. This fallback
stops NTP serving and does not itself establish synchronization.

Run `execute --mode apply` once; if pending, use `execute --mode resume --attempt N`
with a fresh positive attempt number. Do not retry apply. Each execute invocation
also requires `--bundle ABSOLUTE_BUNDLE --sha256 APPROVED_SHA256`. After handoff,
use ordinary bounded convergence observations. Recovery is `execute --mode recover`.
'''
    if spec.get('action')=='start':
        return f'''# Start the unchanged all-source service after bootstrap recovery

Target **j2-svntp1**, operation `{spec['operation_id']}`.
Accepted recovery archive: `{spec['recovery_sha256']}`.
Start before epoch {spec['start_before_epoch']}; expires {spec['expires_epoch']}.
Stage: `{spec['stage']}`. Flat current repository code and selected baseline data.

Use the existing tested transition worker and its protected executable reader.
Require the recovered boot, unchanged files/native binaries and learned drift,
stopped/disabled timeservice, no surviving GPSD/ntpd, active/enabled timesyncd,
and inactive prior workers. Any mismatch stops before service mutation.

Arm the existing independent 600-second transaction watchdog. Stop timesyncd,
preserve drift and protocol cursors, then start the installed all-source service.
Do not replace configurations, reload systemd, change boot enablement, or reboot.
Require both SHM attachments, all five source associations and the first new
protocol frequency event matching saved drift. The existing structural startup
check is 120 seconds; the unchanged supervisor retains its 30-second receiver
pairing gate. Neither establishes cold receiver acquisition acceptance.

Obtain dual-stack readbacks and structural client responses/query denial,
verify daemon continuity, then cancel the watchdog and leave the service running.
Observe convergence at 30 seconds while degraded and 300 seconds when ready,
up to 60 observations in the inherited window. Timing quality has no shutdown
deadline. Final synchronized client/discovery and boot acceptance remain separate.

On startup/handoff failure, use the existing inspected bootstrap recovery:
stop NTP, prove children gone, preserve configuration/drift and restart timesyncd.
This fallback does not serve NTP or itself prove bootstrap synchronization.
Never replay an uncertain apply; read back and recover only an uncommitted stage.
No installation, configuration replacement, SHM grant, boot/leap enablement,
reboot, historical code loading or evidence cleanup is included.

After separate approval of this bundle SHA-256:

```bash
python3 -I -B ntpsec/scripts/run-production-transition.py execute --bundle ABSOLUTE_BUNDLE --sha256 APPROVED_SHA256 --mode apply
```
'''
    if spec.get('action')=='restart':
        return f'''# Controlled all-source restart and bootstrap-only recovery

Target **j2-svntp1**, operation `{spec['operation_id']}`.
Accepted service archive: `{spec['recovery_sha256']}`.
Accepted client archive: `{spec['client_sha256']}`.
Start before epoch {spec['start_before_epoch']}; expires {spec['expires_epoch']}.
Stage: `{spec['stage']}`. Flat repository-owned code and pinned baseline data.

One controlled stop/start of timeservice.service on the accepted boot. Preflight
requires unchanged installed files/native binaries, the accepted supervisor and
daemon identities, active ordinary all-source service with no restarts/overrides,
inactive bootstrap, disabled boot enablement and inactive prior operation units.
Capture the current learned drift; allow normal drift learning since observation.
Any prerequisite mismatch stops before service mutation.

Arm an independent 600-second transaction watchdog. Stop timeservice and prove
ntpd/GPSD have exited. Preserve the latest drift bytes in place and record the
protocol-file byte boundaries. Start the unchanged service/configuration. Require
new daemon invocations, both SHM attachments, all five associations and the first
new protocol frequency event matching the stopped drift within 120 seconds.
Retain journals and protocol evidence. Obtain dual-stack readbacks and structural
client proofs, recheck process continuity, then cancel the watchdog at handoff.
The service remains running; timing quality has no shutdown deadline. Allow up
to 60 sequential read-only observations, 30 seconds while degraded and 300 when
ready, within this window. No final production acceptance is implied.

On failed restart/handoff, stop NTP, prove its children have exited, preserve
drift/statistics and start systemd-timesyncd. Conditionally clear only stopped,
PID-zero failed service state. This bootstrap-only fallback does NOT serve NTP;
bootstrap synchronization remains unaccepted. Unexpected file changes/new boot
hold recovery for review. Never restart a drift-rejecting PPS-first profile.

No configuration replacement, daemon-reload, SHM permission changes, installation,
boot enablement, leap timer activation, reboot or cleanup. The three approved
configuration members are identity checks only. Prior evidence remains intact.
Watchdog recovery remains authorized after the start window. One apply attempt;
never replay uncertain mutation. On apply transport failure, read back once and
recover only a proven uncommitted stage. Explicit recovery is allowed once.

After separate hash-bound execution approval, from the repository root:
`python3 -I -B ntpsec/scripts/run-production-transition.py execute --bundle ABSOLUTE_BUNDLE --sha256 APPROVED_SHA256 --mode apply`
'''
    return f'''# All-source production transition and bootstrap-only recovery

Target **j2-svntp1**, one same-boot transition. Start before Unix epoch
{spec['start_before_epoch']}; operation expires {spec['expires_epoch']}.
Baseline inspection SHA-256: `{spec['inspection_sha256']}`.
Confirmed bootstrap recovery archive SHA-256: `{spec['recovery_sha256']}`.
Stage: `{spec['stage']}`. No historical archives or executable evidence imports.

Before service changes, verify pinned files/binaries, the captured boot, service
state, unchanged recovered drift, inactive old workers, stopped NTP/GPSD and active
systemd-timesyncd. After startup, resolve GPSD identity from its live PID, executable, parent,
start ticks and kernel UID/GID; do not require an account named gpsd. Require
GPSD non-root and ntpd's accepted ntp credentials. Validate the candidate unit.
Any prerequisite mismatch stops before service mutation and retains the stage.

Arm a 600-second installation watchdog. Stop systemd-timesyncd, preserve the current
learned drift in place, and replace /etc/ntpsec-timeservice.json,
/etc/systemd/system/timeservice.service and /etc/ntp.conf. The only ntp.conf change
enables daily protocol statistics; source and restriction policy stays identical.
Start the ordinary supervisor with all
five configured sources immediately, PPS preferred and NMEA selectable. No PPS
promotion helper, drift reset, source restriction change, SHM permission change,
boot enablement, leap timer activation or reboot is included. The old fault unit
file is preserved; the new service unit does not reference it.

Require the actual /etc/ntp.conf launch, both daemons, both SHM attachments and
all five associations within 120 seconds. Retain startup journals for diagnosis.
Before startup, capture protocol-file identities, sizes and prefix hashes. Require
the first newly appended system frequency-set record to match the saved drift
value and startup time window. Reject replaced/truncated files, changed prefixes,
stale records and a mismatched first seed; old records cannot satisfy this check.
Protocol statistics do not contain PIDs: attribution uses stopped old daemons,
the prestart byte boundary and the current same-boot supervised daemon pair.
This validates initialization, not a new timing-quality threshold. It is structural startup, not a
PPS timing-quality deadline. Obtain readbacks through both fixed endpoints and
IPv4/IPv6 structural NTP/client-query checks. Recheck process continuity before
handoff and cancel the installation watchdog. The service remains running after
handoff; no quality-expiry shutdown is installed. Later observe calls are bounded
to 60 sequential captures during this window, no faster than 30 seconds. Use
30 seconds while converging/degraded and 300 seconds when ready.

**Approved fallback policy:** on a failed transition, stop candidate NTP,
restore the three original files, preserve learned drift and statistics, and start
systemd-timesyncd without changing its enablement. The node then synchronizes its
own clock but does NOT serve NTP. Never restart the old drift-rejecting PPS-first
profile. Conditionally clear only a stopped, PID-zero failed timeservice state
before restoring its prior unit. Require stopped candidate and active bootstrap; bootstrap synchronization
itself remains separately observable. Unexpected files, boot changes or failed
recovery hold for review; never overwrite operator changes. Watchdog recovery can
finish after the start window; it is independent of the SSH connection. Preserve
all stage evidence and previous trial records; no cleanup is included.

One apply attempt only. On transport failure, retain partial results, read back
once and recover only if the stage proves mutation started and handoff did not
complete. Never automatically replay apply or an uncertain recovery. Explicit
recover is allowed once within this execution window. No target other than
j2-svntp1 is contacted. Execution does not declare timing or production acceptance.

After separate hash-bound execution approval, from the repository root:
`python3 -I -B ntpsec/scripts/run-production-transition.py execute --bundle ABSOLUTE_BUNDLE --sha256 APPROVED_SHA256 --mode apply`
'''


def validate(spec,files):
    if any(type(spec.get(key,False)) is not bool for key in ('acquisition_wait','install_acquisition')):
        raise ValueError('explicit boolean acquisition policy required')
    if (spec['schema']!=1 or spec['purpose']!='production-transition' or spec['hostname']!='j2-svntp1'
        or spec.get('action','transition') not in ('transition','restart','start')
        or not re.fullmatch(r'[a-z][a-z0-9-]{0,47}',spec['operation_id'])
        or spec['stage']!='/var/lib/ntp-production-'+spec['operation_id']
        or spec['watchdog']!='ntp-production-'+spec['operation_id']
        or spec['members']!={n:sha(files[n]) for n in set(PATHS)|EXTRA}
        or files['review.md']!=review(spec).encode()
        or not spec['prepared_epoch']<spec['start_before_epoch']<spec['expires_epoch']
        or spec['expires_epoch']-spec['prepared_epoch']>86400):
        raise ValueError('closed transition input binding')
    # Reuse the closed transport identity validator, without its inspection-only fields.
    probe=dict(spec,schema=1,purpose='production-inspection',monitor_operation_id='baseline',
               stage='/var/lib/ntp-acquire-baseline',apply_unit='ntp-monitor-baseline',
               recovery_unit='ntp-monitor-baseline-watchdog',monitor_sha256='0'*64)
    helper.validate(probe)
    baseline=json.loads(files['baseline.json'])
    if spec.get('install_acquisition') and (spec.get('action')!='restart' or not spec.get('acquisition_wait')):
        raise ValueError('acquisition installation requires controlled restart')
    if spec.get('action') in ('restart','start'):
        for name,member in (('/etc/ntp.conf','ntp.conf'),('/etc/ntpsec-timeservice.json','timeservice.json'),
                            ('/etc/systemd/system/timeservice.service','timeservice.service')):
            if name=='/etc/ntpsec-timeservice.json' and spec.get('install_acquisition'):continue
            if sha(files[member])!=baseline['files'][name]['sha256']:
                raise ValueError('restart configuration must remain identical')
    elif files['ntp.conf']!=production_config(base64.b64decode(baseline['files']['/etc/ntp.conf']['base64'])):
        raise ValueError('protocol-only configuration change required')
    recipe=json.loads(files['timeservice.json'])
    if set(recipe)!={'gpsd','ntpd','uart_device','startup_gate'}:
        raise ValueError('ordinary supervisor recipe only')
    expected=json.loads((ROOT/'configs/service-cutover-recipe.json').read_text())['timeservice']
    if spec.get('acquisition_wait'):
        expected['startup_gate']=json.loads(files['production-startup-gate.json'])
        if expected['startup_gate'].get('acquisition_policy')!='wait':raise ValueError('wait policy required')
        for name,member in load(ROOT/'scripts/production-transition.py').RUNTIME.items():
            if not spec.get('install_acquisition') and baseline['files'][name]['sha256']!=sha(files[member]):
                raise ValueError('installed acquisition runtime differs from pinned code')
    if recipe!=expected:
        raise ValueError('current ordinary recipe drift')
    if files['timeservice.service']!=(ROOT/'templates/timeservice.service').read_bytes():
        raise ValueError('ordinary service template drift')


def prepare(bundle,checksum):
    raw=helper.private(bundle,4*1024**2)
    if sha(raw)!=checksum:raise ValueError('approved transition digest')
    names=set(PATHS)|EXTRA|{'spec.json','review.md'}
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        members=archive.getmembers()
        if len(members)!=len(names) or {m.name for m in members}!=names or any(not m.isfile() or m.size>1024**2 for m in members):
            raise ValueError('closed flat transition archive')
        files={m.name:archive.extractfile(m).read() for m in members}
    spec=json.loads(files['spec.json']);validate(spec,files)
    for name,path in PATHS.items():
        if files[name]!=(ROOT/path).read_bytes():raise ValueError('current code/test drift')
    for name in ('spec.json','review.md','known_hosts'):
        if helper.private(bundle.parent/name)!=files[name]:raise ValueError('local approval input drift')
    return spec,files


def seal(args):
    if getattr(args,'acquisition_wait',False) and not getattr(args,'restart_dir',None):
        raise ValueError('acquisition upgrade requires accepted restart prerequisites')
    if getattr(args,'boot_recovery_dir',None):return seal_start(args)
    if getattr(args,'restart_dir',None):return seal_restart(args)
    directory=args.recovery_dir
    raw=helper.private(directory/'production-transition.tar')
    if sha(raw)!=args.recovery_sha256:raise ValueError('recovery archive mismatch')
    # Read pinned data only; historical executable members are never imported.
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        old=json.loads(archive.extractfile('spec.json').read())
        baseline=json.loads(archive.extractfile('baseline.json').read())
        key=archive.extractfile('known_hosts').read()
    receipt_raw=helper.private(directory/'failure-readback-result.json')
    receipt=json.loads(receipt_raw)
    outcome=json.loads(helper.private(directory/'apply-outcome.json'))
    execution=json.loads(helper.private(directory/'apply-execution.json'))
    transport=json.loads(helper.private(directory/'failure-readback-transport.json'))
    if (outcome['bundle_sha256']!=args.recovery_sha256 or execution['sha256']!=args.recovery_sha256
        or transport.get('returncode')!=0 or transport.get('error')
        or outcome['failure_readback']!=receipt or receipt['phase']!='bootstrap_recovered'
        or receipt['ntp_serving'] is not False or receipt['boot_id']!=baseline['boot_id']):
        raise ValueError('confirmed same-boot bootstrap recovery required')
    for name,row in receipt['before']['files'].items():
        if row!=baseline['files'][name]:
            # Capture timestamps may differ; file identity and bytes must agree.
            if any(row[k]!=baseline['files'][name][k] for k in ('sha256','uid','gid','mode')):
                raise ValueError('recovered file baseline mismatch')
        if sha(base64.b64decode(row['base64']))!=row['sha256']:
            raise ValueError('recovery file content mismatch')
    baseline.pop('supervisor_pid',None);baseline.pop('pair_pids',None)
    baseline['recovered_drift_sha256']=receipt['retained_drift']['sha256']
    baseline['recovery_receipt_sha256']=sha(receipt_raw)
    if set(baseline['files'])!=set(helper.INSTALLED):raise ValueError('complete installed baseline required')
    original=(ROOT/'configs/j2-svntp1-ntp.conf').read_bytes()
    if sha(original)!=baseline['files']['/etc/ntp.conf']['sha256']:raise ValueError('accepted config mirror drift')
    baseline['files']['/etc/ntp.conf']['base64']=base64.b64encode(original).decode()
    recipe=json.loads((ROOT/'configs/service-cutover-recipe.json').read_text())
    release=json.loads((ROOT/'configs/accepted-source-release.json').read_text())
    now=int(time.time());expires=int(baseline['captured_epoch'])+86400
    if expires-now<1800:raise ValueError('fresh inspection window required')
    spec={'schema':1,'purpose':'production-transition','operation_id':args.operation_id,
          'hostname':old['hostname'],'endpoints':old['endpoints'],'host_key_alias':old['host_key_alias'],
          'stage':'/var/lib/ntp-production-'+args.operation_id,'watchdog':'ntp-production-'+args.operation_id,
          'inspection_sha256':old['inspection_sha256'],'recovery_sha256':args.recovery_sha256,'prepared_epoch':now,'expires_epoch':expires,
          'start_before_epoch':expires-600,'nts_servers':recipe['nts_servers'],
          'old_units':list(dict.fromkeys([*old['old_units'],old['watchdog']+'.service',old['watchdog']+'.timer'])),
          'binaries':{'/'+p:r for p,r in release['files'].items() if p in ('usr/local/sbin/ntpd','usr/local/sbin/gpsd')}}
    files={n:(ROOT/path).read_bytes() for n,path in PATHS.items()}
    files.update({'baseline.json':encoded(baseline),'known_hosts':key,
                  'timeservice.json':encoded(recipe['timeservice']),
                  'timeservice.service':(ROOT/'templates/timeservice.service').read_bytes(),
                  'ntp.conf':production_config(original)})
    spec['members']={n:sha(v) for n,v in files.items()}
    return write_bundle(args.output,spec,files)


def seal_start(args):
    directory=args.boot_recovery_dir
    raw=helper.private(directory/'production-boot.tar',4*1024**2)
    if sha(raw)!=args.recovery_sha256:raise ValueError('bootstrap recovery archive mismatch')
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        old=json.load(archive.extractfile('spec.json'))
        prior={n:archive.extractfile(n).read() for n in EXTRA}
    if old['purpose']!='production-boot-recovery':raise ValueError('recovery-only prerequisite required')
    for name,value in prior.items():
        if sha(value)!=old['members'][name]:raise ValueError('recovery data binding')
    receipt_raw=helper.private(directory/'recover-1-recover-result.json');receipt=json.loads(receipt_raw)
    outcome=json.loads(helper.private(directory/'recover-1-outcome.json'))
    execution=json.loads(helper.private(directory/'recover-1-execution.json'))
    transport=json.loads(helper.private(directory/'recover-1-recover-transport.json'))
    baseline=json.loads(prior['baseline.json'])
    if (outcome['bundle_sha256']!=args.recovery_sha256 or outcome.get('error') or outcome['state']!=receipt
            or execution['sha256']!=args.recovery_sha256 or execution['mode']!='recover'
            or transport.get('returncode')!=0 or transport.get('error') or receipt['phase']!='bootstrap_recovered'
            or receipt['ntp_serving'] is not False or receipt['boot_id']!=baseline['boot_id']
            or receipt['recovery_boot_id']!=baseline['boot_id']):
        raise ValueError('confirmed same-boot recovery required')
    for name,member in (('/etc/ntp.conf','ntp.conf'),('/etc/ntpsec-timeservice.json','timeservice.json'),
                        ('/etc/systemd/system/timeservice.service','timeservice.service')):
        row=receipt['before']['files'][name]
        if (sha(prior[member])!=row['sha256']
                or any(row[k]!=baseline['files'][name][k] for k in ('sha256','uid','gid','mode'))):
            raise ValueError('unchanged recovered configuration required')
    drift=receipt['retained_drift']
    if sha(base64.b64decode(drift['base64'],validate=True))!=drift['sha256']:raise ValueError('recovered drift data binding')
    baseline.update(recovered_drift_sha256=drift['sha256'],recovery_receipt_sha256=sha(receipt_raw))
    for name in ('running_pair','supervisor_pid','pair_pids'):baseline.pop(name,None)
    now=int(time.time());expires=old['expires_epoch']
    if expires-now<1800:raise ValueError('fresh inspection window required')
    spec={**old,'purpose':'production-transition','action':'start','operation_id':args.operation_id,
          'stage':'/var/lib/ntp-production-'+args.operation_id,'watchdog':'ntp-production-'+args.operation_id,
          'prepared_epoch':now,'start_before_epoch':expires-600,'recovery_sha256':args.recovery_sha256}
    files={name:(ROOT/path).read_bytes() for name,path in PATHS.items()};files.update(prior)
    files['baseline.json']=encoded(baseline);spec['members']={n:sha(v) for n,v in files.items()}
    return write_bundle(args.output,spec,files)


def seal_restart(args):
    directory=args.restart_dir
    raw=helper.private(directory/'production-transition.tar')
    if sha(raw)!=args.recovery_sha256:raise ValueError('accepted service archive mismatch')
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        prior={name:archive.extractfile(name).read() for name in
               ('spec.json','baseline.json','known_hosts','ntp.conf','timeservice.json','timeservice.service')}
    old=json.loads(prior['spec.json']);baseline=json.loads(prior['baseline.json'])
    if old['purpose']!='production-transition':raise ValueError('accepted service purpose')
    for name in prior.keys()-{'spec.json'}:
        if sha(prior[name])!=old['members'][name]:raise ValueError('accepted service data binding')
    observed=helper.private(directory/f'observe-{args.observation}-outcome.json')
    outcome=json.loads(observed)
    readback=json.loads(helper.private(directory/f'observe-{args.observation}-result.json'))
    transport=json.loads(helper.private(directory/f'observe-{args.observation}-transport.json'))
    execution=json.loads(helper.private(directory/f'observe-{args.observation}-execution.json'))
    handoff=handoff_result(directory,args.recovery_sha256)
    health=readback['health'];now=int(time.time())
    if (outcome['bundle_sha256']!=args.recovery_sha256 or outcome.get('error')
        or outcome['state']!=readback or readback['phase']!='monitoring'
        or transport.get('returncode')!=0 or transport.get('error')
        or execution['sha256']!=args.recovery_sha256 or execution['mode']!='observe'
        or handoff['bundle_sha256']!=args.recovery_sha256 or handoff.get('error')
        or handoff['state']['phase']!='monitoring' or handoff['state']['boot_id']!=baseline['boot_id']
        or health['pair']!=handoff['state']['health']['pair']
        or health['unit']['ActiveState']!='active' or health['unit']['NRestarts']!='0'
        or not outcome['timing_ready'] or not timing_ready(health['measurement'])
        or not execution['epoch']<=health['epoch']<=now
        or not 0<=now-health['epoch']<86400):raise ValueError('accepted ready running observation required')
    structural_client=getattr(args,'acquisition_wait',False) and args.client_dir is None
    if structural_client:
        client_receipt_raw=helper.private(directory/'client-proof.json')
        client=json.loads(client_receipt_raw)
        if (client.get('target')!=old['hostname'] or client.get('spec_sha256')!=sha(prior['spec.json'])
                or client.get('checks')!={'ipv4':True,'ipv6':True,'queries_denied':True}
                or handoff['state'].get('drift_seed_observed') is not True
                or not handoff['state']['startup_epoch']<=client['epoch']<=handoff['state']['handoff_epoch']
                or not client['epoch']<=health['epoch']<=now):
            raise ValueError('accepted structural client proof required for acquisition upgrade')
    else:
        client_raw=helper.private(args.client_dir/'client-native-discovery.tar')
        if sha(client_raw)!=args.client_sha256:raise ValueError('client archive mismatch')
        with tarfile.open(fileobj=io.BytesIO(client_raw)) as archive:
            client_spec_raw=archive.extractfile('spec.json').read()
        client_spec=json.loads(client_spec_raw)
        client_receipt_raw=helper.private(args.client_dir/'result.json');client=json.loads(client_receipt_raw)
        if (client['bundle_sha256']!=args.client_sha256 or client['spec_sha256']!=sha(client_spec_raw)
            or client.get('error') or client['client_accepted'] is not True
            or client['checks']!={'ipv4':True,'ipv6':True,'mdns':True,'queries_denied':True}
            or client_spec['monitor_sha256']!=args.recovery_sha256
            or client_spec['monitor_spec_sha256']!=sha(prior['spec.json'])
            or client_spec['observation_sha256']!=sha(observed)
            or client_spec['hostname']!=old['hostname'] or client_spec['endpoints']!=old['endpoints']
            or not health['epoch']<=client['epoch']<=now):raise ValueError('accepted post-transition client proof required')
    for name,member in (('/etc/ntp.conf','ntp.conf'),('/etc/ntpsec-timeservice.json','timeservice.json'),
                        ('/etc/systemd/system/timeservice.service','timeservice.service')):
        baseline['files'][name].update(sha256=sha(prior[member]),base64=base64.b64encode(prior[member]).decode())
    if old.get('install_acquisition'):
        for name,member in load(ROOT/'scripts/production-transition.py').RUNTIME.items():
            with tarfile.open(fileobj=io.BytesIO(raw)) as archive:content=archive.extractfile(member).read()
            if sha(content)!=old['members'][member]:raise ValueError('accepted runtime binding')
            baseline['files'][name].update(sha256=sha(content),base64=base64.b64encode(content).decode())
    baseline.update(running_pair=health['pair'],supervisor_pid=int(health['unit']['MainPID']),
                    ready_observation_sha256=sha(observed),client_receipt_sha256=sha(client_receipt_raw))
    baseline.pop('recovered_drift_sha256',None)
    expires=old['expires_epoch']
    if expires-now<1800:raise ValueError('fresh restart window required')
    spec={**old,'action':'restart','operation_id':args.operation_id,
          'stage':'/var/lib/ntp-production-'+args.operation_id,'watchdog':'ntp-production-'+args.operation_id,
          'prepared_epoch':now,'start_before_epoch':expires-600,'expires_epoch':expires,
          'recovery_sha256':args.recovery_sha256,'client_sha256':args.client_sha256,
          'client_prerequisite':'structural' if structural_client else 'final-native',
          'old_units':list(dict.fromkeys([*old['old_units'],old['watchdog']+'.service',old['watchdog']+'.timer']))}
    files={n:(ROOT/path).read_bytes() for n,path in PATHS.items()}
    files.update({n:prior[n] for n in ('known_hosts','ntp.conf','timeservice.json','timeservice.service')})
    if getattr(args,'acquisition_wait',False):
        candidate=json.loads(files['timeservice.json'])
        candidate['startup_gate']=json.loads(files['production-startup-gate.json'])
        files['timeservice.json']=encoded(candidate)
        spec.update(acquisition_wait=True,install_acquisition=True)
    else:
        spec['acquisition_wait']=json.loads(files['timeservice.json'])['startup_gate'].get('acquisition_policy')=='wait'
        spec.pop('install_acquisition',None)
    files['baseline.json']=encoded(baseline);spec['members']={n:sha(v) for n,v in files.items()}
    return write_bundle(args.output,spec,files)


def write_bundle(output,spec,files):
    files.update({'spec.json':encoded(spec),'review.md':review(spec).encode()});validate(spec,files)
    os.umask(0o077);output.mkdir(mode=0o700)
    for name in ('spec.json','review.md','known_hosts'):(output/name).write_bytes(files[name])
    bundle=output/'production-transition.tar'
    with tarfile.open(bundle,'w') as archive:
        for name,value in sorted(files.items()):
            info=tarfile.TarInfo(name);info.size=len(value);info.mode=0o600;archive.addfile(info,io.BytesIO(value))
    digest=sha(bundle.read_bytes());prepare(bundle,digest)
    result={'sha256':digest,'bundle':str(bundle),'start_before_epoch':spec['start_before_epoch'],
            'expires_epoch':spec['expires_epoch'],'execution_authorized':False,'target_contact':False}
    (output/'sealing.json').write_bytes(encoded(result));return result


def payload(spec,files,mode,proof):
    # Installer writes only the new operation directory. Worker verifies pinned code
    # again before using it; all later calls consume that same immutable package.
    data={n:base64.b64encode(v).decode() for n,v in files.items()}
    return f'''import base64,hashlib,importlib.util,json,os,socket,stat
from pathlib import Path
spec={spec!r}
root=Path(spec['stage'])
if os.geteuid()!=0 or socket.gethostname().split('.')[0]!=spec['hostname']:raise ValueError('target identity')
if {mode!r}=='apply':
    if not root.parent.is_dir() or root.parent.is_symlink():raise ValueError('stage parent')
    os.umask(0o077);root.mkdir(mode=0o700)
    for name,value in {data!r}.items():
        with (root/name).open('xb') as stream:stream.write(base64.b64decode(value))
else:
    info=root.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid or stat.S_IMODE(info.st_mode)!=0o700:raise ValueError('stage identity')
for name,digest in spec['members'].items():
    path=root/name;info=path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid or info.st_mode&0o022 or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:raise ValueError('stage member drift')
if (root/'spec.json').read_bytes()!=base64.b64decode({base64.b64encode(files['spec.json']).decode()!r}):raise ValueError('stage spec drift')
s=importlib.util.spec_from_file_location('transition',root/'production-transition.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
try:
    result=m.worker(root,{mode!r},{sha(encoded(spec))!r},{proof!r})
    print(json.dumps(result))
except BaseException as error:
    print(json.dumps({{'error':str(error),'mode':{mode!r}}}))
    raise
'''.encode()


def remote(root,spec,files,mode,label,address,proof=None):
    request=payload(spec,files,mode,proof)
    transport=dict(spec,endpoints=[address,*spec['endpoints'][1:]])
    argv=helper.ssh_argv(transport,root)
    with (root/(label+'-submission.json')).open('xb') as out:
        out.write(encoded({'mode':mode,'target':address,'payload_sha256':sha(request),'argv':argv}))
        out.flush();os.fsync(out.fileno())
    try: result=helper.bounded(argv,timeout=300,limit=8*1024**2,payload=request,env=os.environ.copy())
    except OSError as error:result={'returncode':None,'error':str(error),'stdout':'','stderr':''}
    for name in ('stdout','stderr'):(root/(label+'.'+name)).write_text(result.pop(name))
    (root/(label+'-transport.json')).write_bytes(encoded(result))
    if result.get('returncode')!=0 or result.get('error'):raise ValueError('remote '+label+' failed; retained output')
    value=json.loads((root/(label+'.stdout')).read_text())
    (root/(label+'-result.json')).write_bytes(encoded(value));return value


def timing_ready(measurement):
    try:
        system=measurement['system'];peers=measurement['peers']
        pps=[p['variables'] for p in peers if p['variables'].get('srchost')=='SHM(2)']
        upstreams=[p['variables'] for p in peers if p['variables'].get('srchost') not in ('SHM(0)','SHM(2)')]
        return (system['leap']==0 and system['stratum']==1 and system['refid']=='PPS'
                and abs(float(system['offset']))<=5 and len(pps)==1 and float(pps[0]['jitter'])<=1
                and len(peers)==5 and all(int(p['variables']['reach'])>0 for p in peers)
                and len(upstreams)==3 and all(int(p['ntscookies'])>0 for p in upstreams))
    except (KeyError,ValueError,TypeError):return False


def handoff_result(directory,digest):
    paths=[directory/'apply-outcome.json',*directory.glob('resume-*-outcome.json')]
    rows=[json.loads(helper.private(p)) for p in paths if p.exists()]
    accepted=[row for row in rows if row.get('bundle_sha256')==digest and not row.get('error')
              and row.get('state',{}).get('phase')=='monitoring']
    if not accepted or any(row['state']!=accepted[0]['state'] for row in accepted[1:]):
        raise ValueError('one consistent accepted structural handoff required')
    return accepted[0]


def execute(args):
    os.umask(0o077);root=args.bundle.absolute().parent
    spec,files=prepare(args.bundle.absolute(),args.sha256)
    now=int(time.time())
    if args.mode not in ('recover','readback','resume') and not spec['prepared_epoch']-300<=now<spec['expires_epoch']:raise ValueError('execution window expired')
    if args.mode=='apply' and now>=spec['start_before_epoch']:raise ValueError('installation reserve exhausted')
    label=args.mode
    if args.mode in ('resume','readback'):
        if args.attempt<1:raise ValueError('positive unique attempt required')
        label+='-'+str(args.attempt)
    if args.mode=='observe':
        if not 1<=args.attempt<=60:raise ValueError('bounded observation attempt required')
        label+='-'+str(args.attempt)
        previous='apply-execution.json' if args.attempt==1 else 'observe-'+str(args.attempt-1)+'-execution.json'
        old=json.loads(helper.private(root/previous))
        prior='apply-outcome.json' if args.attempt==1 else 'observe-'+str(args.attempt-1)+'-outcome.json'
        outcome=handoff_result(root,args.sha256) if args.attempt==1 else json.loads(helper.private(root/prior))
        if args.attempt==1:old={'epoch':outcome['state'].get('handoff_epoch',old['epoch'])}
        interval=300 if outcome.get('timing_ready') is True else 30
        if now-old['epoch']<interval:raise ValueError('observation interval')
    with (root/(label+'-execution.json')).open('xb') as out:
        out.write(encoded({'sha256':args.sha256,'mode':args.mode,'epoch':now}));out.flush();os.fsync(out.fileno())
    call=lambda mode,tag,address,proof=None:remote(root,spec,files,mode,(label+'-'+tag if args.mode=='resume' else tag),address,proof)
    result={'bundle_sha256':args.sha256,'production_accepted':False}
    try:
        if args.mode in ('apply','resume'):
            state=call(args.mode,args.mode,spec['endpoints'][0])
            if state['phase'] in ('starting','acquiring','monitoring','bootstrap_recovered','unchanged'):
                result['state']=state
                result['timing_ready']=timing_ready(state.get('health',{}).get('measurement',{})) if state['phase']=='monitoring' else False
                (root/(label+'-outcome.json')).write_bytes(encoded(result));return result
            proofs={'endpoints':{address:call('readback','readback-'+str(i),address) for i,address in enumerate(spec['endpoints'])}}
            proofs['client']=load(ROOT/'scripts/check-time-client.py').check(spec,sha(encoded(spec)),structural=True)
            (root/('client-proof.json' if args.mode=='apply' else label+'-client-proof.json')).write_bytes(encoded(proofs['client']))
            result['state']=call('accept','accept',spec['endpoints'][0],proofs)
        else:result['state']=call(args.mode,label,spec['endpoints'][0])
    except BaseException as error:
        result['error']=str(error)
        if args.mode in ('apply','resume'):
            try:
                state=call('readback','failure-readback',spec['endpoints'][0]);result['failure_readback']=state
                if state['phase'] in ('applying','starting','awaiting_handoff','recovering'):
                    result['recovery']=call('recover','failure-recover',spec['endpoints'][0])
            except BaseException as recovery_error:result['followup_error']=str(recovery_error)
    result['timing_ready']=timing_ready(result.get('state',{}).get('health',{}).get('measurement',{}))
    (root/(label+'-outcome.json')).write_bytes(encoded(result));return result


def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='action',required=True)
    s=sub.add_parser('seal');source=s.add_mutually_exclusive_group(required=True)
    source.add_argument('--recovery-dir',type=Path);source.add_argument('--restart-dir',type=Path)
    source.add_argument('--boot-recovery-dir',type=Path)
    s.add_argument('--recovery-sha256',required=True);s.add_argument('--operation-id',required=True)
    s.add_argument('--output',type=Path,required=True)
    s.add_argument('--acquisition-wait',action='store_true',help='Install the pinned acquisition runtime during a controlled restart')
    s.add_argument('--observation',type=int);s.add_argument('--client-dir',type=Path);s.add_argument('--client-sha256')
    s=sub.add_parser('execute');s.add_argument('--bundle',type=Path,required=True);s.add_argument('--sha256',required=True)
    s.add_argument('--mode',choices=['apply','resume','readback','observe','recover'],required=True);s.add_argument('--attempt',type=int,default=0)
    args=p.parse_args();result=seal(args) if args.action=='seal' else execute(args)
    print(json.dumps(result))
    if result.get('error'):raise SystemExit(1)


if __name__=='__main__':main()
