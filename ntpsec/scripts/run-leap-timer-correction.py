#!/usr/bin/python3
"""Seal a timer-only correction using accepted activation and recurrence evidence."""
import argparse
import base64
import io
import json
import os
from pathlib import Path
import re
import tarfile
import time
import types
import importlib.util

ROOT=Path(__file__).resolve().parents[1]
PATHS={'runner.py':'scripts/run-leap-timer-correction.py',
       'worker.py':'scripts/leap-timer-correction.py','base.py':'scripts/leap-activation.py',
       'helper.py':'scripts/run-production-inspection.py','tests.py':'tests/test_leap_timer_correction.py',
       'integration.py':'tests/test_leap_timer_systemd.py','Containerfile':'tests/Containerfile.leap-timer',
       'ntpleapfetch.timer':'templates/ntpleapfetch.timer'}
BUNDLE='leap-timer-correction.tar'


def load(name):
    entry=importlib.util.spec_from_file_location(name.replace('-','_'),ROOT/'scripts'/name)
    value=importlib.util.module_from_spec(entry);entry.loader.exec_module(value);return value


h=load('run-production-inspection.py')
base=load('leap-activation.py')
space={'base':base,'__name__':'timer_worker'}
exec(compile((ROOT/'scripts/leap-timer-correction.py').read_bytes(),'timer_worker','exec'),space)
worker=types.SimpleNamespace(**space)


def review(spec):
    return f'''# Timer-only leap-maintenance correction

Target **{spec['hostname']}**, boot `{spec['boot_id']}`.
Operation `{spec['operation_id']}`; expires at epoch {spec['expires_epoch']}.
Recurrence inspection SHA-256 `{spec['inspection_sha256']}`.
Accepted activation SHA-256 `{spec['activation_sha256']}`.

One pinned-key SSH transaction as ama, sudo Python through stdin. Require
accepted NTP PID/invocation/restart/state, boot identity, guarded file hashes and
owner/modes, enabled/active/waiting timer, idle successful static leap service,
expected unit paths and no drop-ins. Reject drift before mutation. Require the
live leapfile to remain outside the 60-day prefetch window.

Create root-private /var/lib/ntp-leap-{spec['operation_id']} for backup,
candidate and state. Verify the timer with target systemd-analyze. Stop only
ntpleapfetch.timer; recheck idle service. Atomically replace only
/etc/systemd/system/ntpleapfetch.timer, root:root 0644: OnActiveSec=15min becomes
OnBootSec=15min; all other bytes stay identical. Reload the system manager and
start the still-enabled timer. Manager reload is global and may rearm other
timers; no unrelated unit file is changed or service restarted.

Preserve the already successful scheduled maintenance invocation and its timer
trigger history during this same-boot upgrade. Do not wait for or claim a new
initial run: systemd retains the consumed boot-trigger history. Require unchanged
successful service invocation/start timestamp and timer last trigger, unchanged
guarded files and NTP identity, and a next monotonic trigger four weeks after
that service activation plus permitted jitter. Reload the manager once more and
require the same invocation and another next trigger within the four-week
window. Record both schedules. Do not force a fetch or manually start the leap
service. No reboot is included; isolated same-version initial-start, upgrade,
reload and container-boot tests cover the intended paths. Target reboot behavior
and its initial timer run remain a later acceptance check.

Ongoing scheduled leap maintenance remains enabled. This stage changes no NTP,
GPSD, drift, clock, package, mail, relay or Webmin configuration and sends no mail.
Guarded files include the leap service, timer, leapfile, fetch executable and NTP
configuration from accepted evidence, rechecked live before/after the transaction.

Before mutation, failures leave live configuration unchanged. After mutation,
conditional recovery stops the leap timer and fetch service, restores original
timer bytes, reloads the manager, clears only the fetch-service failure and
starts the original enabled timer. Its previous recurrence defect remains;
recovery restores prior state, not acceptance. Never overwrite foreign file
changes or overridden units. Hold on failed continuity or recovery and retain
evidence. No NTP restart or bootstrap fallback. Private operation data remains.

Remote deadline 180 seconds, SSH 360 seconds, 24 MiB per output stream;
ordinary commands have 10/30-second bounds. Catchable interruption attempts
conditional recovery. Power loss, SIGKILL or uncertain transport cannot guarantee
rollback: inspect retained state before retry. Single-use local receipt and
exclusive target directory prevent blind repeat execution.

The flat archive holds current code/tests/timer, selected baseline data and host
key, not historical executable archives. After approval of this archive SHA-256:
`python3 -I -B ntpsec/scripts/run-leap-timer-correction.py execute --bundle ABSOLUTE_BUNDLE --sha256 APPROVED_SHA256`
'''


def prepare(path,digest):
    raw=h.private(path,4*h.LIMIT)
    if h.sha(raw)!=digest:raise ValueError('approved archive digest mismatch')
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        members=archive.getmembers();names=set(PATHS)|{'baseline.json','known_hosts','spec.json','review.md'}
        if len(members)!=len(names) or {m.name for m in members}!=names or any(not m.isfile() or m.size>h.LIMIT for m in members):
            raise ValueError('closed flat archive required')
        files={m.name:archive.extractfile(m).read() for m in members}
    spec=json.loads(files['spec.json'])
    if (spec['schema']!=1 or spec['purpose']!='leap-timer-correction' or spec['hostname']!='j2-svntp1'
            or spec['endpoints']!=['10.1.0.51','fd36:5aa8:6971:1::51'] or spec['host_key_alias']!='10.1.0.137'
            or not re.fullmatch(r'[a-z][a-z0-9-]{0,47}',spec['operation_id'])
            or not re.fullmatch(r'[a-f0-9-]{36}',spec['boot_id'])
            or not 0<spec['expires_epoch']-spec['prepared_epoch']<=86400
            or not spec['prepared_epoch']-300<=time.time()<spec['expires_epoch']-360
            or spec['members']!={n:h.sha(files[n]) for n in set(PATHS)|{'baseline.json','known_hosts'}}
            or files['review.md']!=review(spec).encode()):raise ValueError('scope/window/input binding')
    for n,p in PATHS.items():
        if files[n]!=(ROOT/p).read_bytes():raise ValueError('current repository input drift')
    for n in ('spec.json','review.md','known_hosts'):
        if h.private(path.parent/n)!=files[n]:raise ValueError('local approval input drift')
    return spec,files


def seal(args):
    inspection=load('run-webmin-inspection.py');inspection.helper=h
    old,inspected=inspection.prepare(args.inspection_dir/inspection.BUNDLE,args.inspection_sha256)
    result=json.loads(h.private(args.inspection_dir/'result.json'))
    raw=h.private(args.inspection_dir/'stdout.txt',16*h.LIMIT);capture=json.loads(raw)
    if (result.get('capture_complete') is not True or result.get('returncode')!=0 or result.get('error')
            or result['bundle_sha256']!=args.inspection_sha256 or capture.get('capture_complete') is not True
            or not old.get('timer_recurrence') or capture['spec_sha256']!=h.sha(h.encoded(old))
            or capture['operation_id']!=old['operation_id'] or capture['hostname']!=old['hostname']
            or capture['boot_before']!=old['boot_id'] or capture['boot_after']!=old['boot_id']
            or capture['commands']['service-before']!=capture['commands']['timeservice.service']):
        raise ValueError('complete stable recurrence inspection required')
    activation=load('run-leap-activation.py')
    prior,activated=activation.prepare(args.activation_dir/activation.BUNDLE,args.activation_sha256)
    receipt=json.loads(h.private(args.activation_dir/'result.json'))
    state=json.loads(h.private(args.activation_dir/'stdout.txt',24*h.LIMIT))
    if (receipt.get('accepted') is not True or receipt.get('returncode')!=0 or receipt.get('error')
            or receipt['bundle_sha256']!=args.activation_sha256 or state.get('accepted') is not True
            or state.get('error') or state['spec_sha256']!=h.sha(h.encoded(prior))
            or state['operation_id']!=prior['operation_id'] or prior['boot_id']!=old['boot_id']
            or activated['known_hosts']!=inspected['known_hosts']):raise ValueError('accepted activation required')
    baseline=json.loads(activated['baseline.json'])
    baseline['files'].update(capture['files'])
    baseline['service']=base.properties(capture['commands']['timeservice.service']['stdout'])
    baseline['capture_sha256']=h.sha(raw)
    for row in baseline['files'].values():
        base.identity(row)
        if h.sha(base64.b64decode(row['base64'],validate=True))!=row['sha256']:raise ValueError('captured file hash mismatch')
    now=int(time.time());spec={k:old[k] for k in ('hostname','boot_id','endpoints','host_key_alias')}
    spec.update(schema=1,purpose='leap-timer-correction',operation_id=args.operation_id,
                inspection_sha256=args.inspection_sha256,activation_sha256=args.activation_sha256,
                prepared_epoch=now,expires_epoch=min(now+86400,old['expires_epoch']))
    files={n:(ROOT/p).read_bytes() for n,p in PATHS.items()}
    original=base64.b64decode(baseline['files'][base.TIMER]['base64'],validate=True)
    if original.count(b'OnActiveSec=15min')!=1 or original.replace(b'OnActiveSec=15min',b'OnBootSec=15min')!=files['ntpleapfetch.timer']:
        raise ValueError('candidate differs beyond initial trigger')
    files.update({'baseline.json':h.encoded(baseline),'known_hosts':inspected['known_hosts']})
    spec['members']={n:h.sha(v) for n,v in files.items()}
    files.update({'spec.json':h.encoded(spec),'review.md':review(spec).encode()})
    os.umask(0o077);args.output.mkdir(mode=0o700)
    for n in ('spec.json','review.md','known_hosts'):(args.output/n).write_bytes(files[n])
    bundle=args.output/BUNDLE
    with tarfile.open(bundle,'w') as archive:
        for n,v in sorted(files.items()):
            item=tarfile.TarInfo(n);item.size=len(v);item.mode=0o600;archive.addfile(item,io.BytesIO(v))
    digest=h.sha(bundle.read_bytes());prepare(bundle,digest)
    result={'sha256':digest,'bundle':str(bundle),'expires_epoch':spec['expires_epoch'],
            'target_contact':False,'execution_authorized':False}
    (args.output/'sealing.json').write_bytes(h.encoded(result));return result


def payload(spec,files):
    return ("import types,signal,json,os\nos.chdir('/')\nhelper=types.ModuleType('helper')\n"
            "helper.__file__='/sealed/helper.py'\nexec("+repr(files['helper.py'])+",helper.__dict__)\n"
            "b={'__name__':'base_worker'}\nexec("+repr(files['base.py'])+",b)\n"
            "space={'__name__':'timer_worker','base':types.SimpleNamespace(**b)}\nexec("+repr(files['worker.py'])+",space)\n"
            "signal.signal(signal.SIGALRM,b['interrupted'])\nsignal.alarm(180)\nprint(json.dumps(space['run']("
            +repr(spec)+","+repr(json.loads(files['baseline.json']))+","+repr(files['ntpleapfetch.timer'])+",helper)))\n").encode()


def execute(args):
    os.umask(0o077);spec,files=prepare(args.bundle,args.sha256);request=payload(spec,files)
    root=args.bundle.parent;argv=h.ssh_argv(spec,root)
    with (root/'execution.json').open('xb') as stream:
        stream.write(h.encoded({'epoch':int(time.time()),'sha256':args.sha256,'payload_sha256':h.sha(request),'argv':argv}))
        stream.flush();os.fsync(stream.fileno())
    try:result=h.bounded(argv,timeout=360,limit=24*h.LIMIT,payload=request,env=os.environ.copy())
    except OSError as error:result={'returncode':None,'error':str(error),'stdout':'','stderr':''}
    for n in ('stdout','stderr'):(root/(n+'.txt')).write_text(result.pop(n))
    result.update(accepted=False,bundle_sha256=args.sha256)
    if result.get('returncode')==0 and not result.get('error'):
        try:
            state=json.loads((root/'stdout.txt').read_text())
            result['accepted']=(state.get('accepted') is True and not state.get('error')
                and state['operation_id']==spec['operation_id'] and state['spec_sha256']==h.sha(h.encoded(spec))
                and state['checks']==dict.fromkeys(worker.CHECKS,True))
        except (ValueError,KeyError,TypeError) as error:result['error']=str(error)
    (root/'result.json').write_bytes(h.encoded(result));return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='action',required=True)
    p=sub.add_parser('seal')
    for name in ('inspection','activation'):
        p.add_argument('--'+name+'-dir',type=Path,required=True);p.add_argument('--'+name+'-sha256',required=True)
    p.add_argument('--operation-id',required=True);p.add_argument('--output',type=Path,required=True)
    p=sub.add_parser('execute');p.add_argument('--bundle',type=Path,required=True);p.add_argument('--sha256',required=True)
    args=parser.parse_args();result=seal(args) if args.action=='seal' else execute(args);print(json.dumps(result))
    if args.action=='execute' and not result['accepted']:raise SystemExit(1)


if __name__=='__main__':main()
