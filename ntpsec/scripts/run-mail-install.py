#!/usr/bin/python3
"""Seal outbound-mail installation and exact-message submission for review."""
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
SOURCES={'runner.py':ROOT/'scripts/run-mail-install.py', 'worker.py':ROOT/'scripts/mail-install.py',
 'helper.py':ROOT/'scripts/run-production-inspection.py', 'tests.py':ROOT/'tests/test_mail_install.py',
 'assets.json':ROOT/'configs/mail-installation-assets.json', 'policy.json':ROOT/'configs/j2-svntp1-mail.json',
 'msmtprc.template':ROOT/'templates/msmtprc.example', 'cron.template':ROOT/'templates/needrestart.cron.example',
 'reporter.sh':ROOT.parents[1]/'homelab-server-configs/Needrestart/scripts/needrestart.sh'}


def load(path):
    entry=importlib.util.spec_from_file_location(path.stem,path)
    module=importlib.util.module_from_spec(entry);entry.loader.exec_module(module);return module


h=load(ROOT/'scripts/run-production-inspection.py')


def render(files, operation):
    policy=json.loads(files['policy.json'])
    conf=files['msmtprc.template'].decode()
    for name,value in {'@MAILRISE_HOST@':policy['relay'],'@MAILRISE_PORT@':str(policy['port']),
                       '@MAIL_DOMAIN@':policy['sender_domain']}.items(): conf=conf.replace(name,value)
    conf=conf.replace('from %H@'+policy['sender_domain'], 'from '+policy['sender'])
    cron=files['cron.template'].decode().replace('@CRON_RECIPIENT@',policy['failure_recipient']).replace('@ALERT_RECIPIENT@',policy['report_recipient'])
    result={'msmtprc':conf.encode(),'aliases':('root: '+policy['failure_recipient']+'\n').encode(),
            'cron.pending':cron.encode()}
    for kind,recipient in [('report',policy['report_recipient']),('failure',policy['failure_recipient'])]:
        text=(f"From: {policy['sender']}\nTo: {recipient}\n"
              f"Subject: [TEST] j2-svntp1 mail acceptance - {kind}\n"
              f"Message-ID: <{operation}-{kind}@{policy['sender_domain']}>\n\n"
              f"Synthetic {kind} notification for j2-svntp1 mail acceptance.\n"
              "No service failure is being reported. No action is required.\n"
              f"Operation: {operation}\n")
        result[kind+'.eml']=text.encode()
    return result


def review(spec,files):
    packages='\n'.join('- '+p['package']+' '+p['version']+' ('+p['architecture']+')' for p in spec['packages'])
    return f'''# Outbound mail installation and two-message submission review

Target ama@10.1.0.51, host-key alias 10.1.0.137; hostname j2-svntp1.
Operation {spec['operation_id']}; boot {spec['boot_id']}.
Expires at epoch {spec['expires_epoch']}. One execution only.

## Package and service scope

Install only these eight sealed, hash-verified packages from the existing cache:

{packages}

No APT refresh/download, upgrade/removal, reboot or NTP restart. Require unchanged
accepted package inventory, boot/NTP identity, clean dpkg audit, ARM64, and
America/Chicago timezone. Reject existing mail destinations, listener unit/account
or dpkg invocation hooks. Require root user msmtp configuration overrides absent
(check paths beneath the observed root home without reading their contents).
Snapshot protected NTP/leap/needrestart configuration
and require unchanged content/metadata. Stage payloads and receipts in a new
root-private /var/lib/ntp-mail-{spec['operation_id']} directory. Run dpkg --no-act
before installing. Normal dpkg state/log/trigger updates are included.

Mask msmtpd.service to /dev/null before package installation and retain the mask
as the outbound-only policy. Reload the systemd manager; do not start the listener.
Set msmtp/apparmor=true and allow package AppArmor profile setup/reload, msmtp
system-account creation and library/manual triggers. Verify the listener remains
masked/inactive, selected versions and msmtp binary, clean audit, unrelated
package states and NTP/protected-file continuity.

## Transport and reporting

Install /etc/msmtprc root:root 0600, /etc/aliases root:root 0644, and the sealed
shared needrestart.sh as /usr/local/sbin/needrestart.sh root:root 0755.
Use mailrise.local.theama.co:8025, auth off, TLS off on the approved trusted LAN;
default account apprise; From explicitly j2-svntp1@local.theama.co.
Root alias maps to notify.failure@mailrise.xyz. This activates the default
system-wide outbound transport: existing system jobs may now send mail through
it. No promise of exactly two total host-originated messages is made.

Stage the daily 05:30 America/Chicago cron content at
/usr/local/sbin/needrestart_check.pending root:root 0600. Do not install it under
/etc/cron.d or run needrestart.sh in this stage. Verify reporter syntax and both
msmtp accounts/recipients in --pretend mode without sending. Validate installed
file hashes/owners/modes and sendmail -> msmtp. Runtime reporter and scheduled
failure-path acceptance remain later work; the schedule stays inactive until
operator-confirmed downstream receipt and separately approved activation.

## Exact approved test messages

Submit each following message once through /usr/sbin/sendmail -t, after all
installation checks pass. No attachment, CC or BCC. Keep the shown From/To/Subject,
Message-ID and body. A nonzero or interrupted submission is not retried.

Report message:

```text
{files['report.eml'].decode().rstrip()}
```

Failure-type message:

```text
{files['failure.eml'].decode().rstrip()}
```

Record submission intent before each send. Successful sendmail exit establishes
submission only, not downstream delivery; obtain operator confirmation of both
notifications. Delivery and final production acceptance remain false until then.

## Recovery and limits

On ordinary failure, withdraw only this invocation's byte-identical authored
mail/report/pending-cron files. Retain installed or partially installed packages,
msmtp account/debconf/AppArmor state, listener mask and private receipts for
inspection; do not purge dependencies or undo any submitted message. Stop only
msmtpd if it unexpectedly became active. Preserve NTP. Foreign file/mask drift
holds recovery. Failed or interrupted transport is never retried automatically;
inspect retained state before any continuation. This is containment, not an
exact package rollback. SMTP acceptance cannot be undone.

Each command is bounded; installation 300 seconds, each message 60 seconds;
remote deadline 720 seconds, SSH deadline 750 seconds. Target writes and sends
are authorized only after approval of this exact archive hash AND both previews.

Execute from repository root after approval:
`python3 -I -B ntpsec/scripts/run-mail-install.py execute --directory ABSOLUTE_DIRECTORY --sha256 APPROVED_SHA256`
'''


def seal(args):
    d=args.baseline
    result=json.loads(h.private(d/'result.json'));raw=h.private(d/'stdout.txt',16*h.LIMIT);baseline=json.loads(raw)
    archive=h.private(d/'inspection.tar',16*h.LIMIT)
    if h.sha(archive)!=result['bundle_sha256'] or not result.get('capture_complete') or not baseline.get('capture_complete'):
        raise ValueError('accepted dependency capture required')
    with tarfile.open(fileobj=io.BytesIO(archive)) as t:
        old=json.loads(t.extractfile('spec.json').read());known=t.extractfile('known_hosts').read()
    if baseline['spec_sha256']!=h.sha(h.encoded(old)) or baseline['operation_id']!=old['operation_id']:
        raise ValueError('baseline binding')
    files={name:path.read_bytes() for name,path in SOURCES.items()}
    manifest=json.loads(files['assets.json']);packages=manifest['assets']
    selected={p['package'] for p in packages}
    simulated={line.split()[1]:line.split()[2].lstrip('(') for line in baseline['commands']['simulation']['stdout'].splitlines() if line.startswith('Inst ')}
    if {p['package']:p['version'] for p in packages}!=simulated or len(packages)!=8: raise ValueError('package selection drift')
    for p in packages:
        data=h.private(args.cache/p['filename'],4*h.LIMIT)
        if h.sha(data)!=p['sha256'] or len(data)!=p['size']: raise ValueError('package cache mismatch')
        files[p['filename']]=data
    # Read the package data stream locally without running any maintainer script.
    import subprocess
    package=next(p for p in packages if p['package']=='msmtp')
    data=subprocess.run(['dpkg-deb','--fsys-tarfile',str(args.cache/package['filename'])],check=True,capture_output=True).stdout
    with tarfile.open(fileobj=io.BytesIO(data)) as t: binary=t.extractfile('./usr/bin/msmtp').read()
    before=dict((v[0],v[1:]) for v in (line.split('\t') for line in baseline['commands']['packages']['stdout'].splitlines()))
    if any(k.split(':')[0] in selected for k in before): raise ValueError('selected package already present')
    now=int(time.time());spec={'operation_id':args.output.name,'hostname':'j2-svntp1','boot_id':baseline['boot_after'],
      'service_identity':baseline['ntp_after'],'packages_before':before,'packages':packages,
      'msmtp_binary_sha256':h.sha(binary),'baseline_sha256':h.sha(raw),
      'baseline_bundle_sha256':result['bundle_sha256'],'prepared_epoch':now,'expires_epoch':now+86400}
    files.update(render(files,spec['operation_id']));files['known_hosts']=known
    spec['members']={name:h.sha(data) for name,data in files.items()}
    files['spec.json']=h.encoded(spec);files['review.md']=review(spec,files).encode()
    os.umask(0o077);args.output.mkdir(mode=0o700)
    for name,data in files.items(): (args.output/name).write_bytes(data)
    with tarfile.open(args.output/'mail-install.tar','w') as t:
        for name,data in sorted(files.items()):
            info=tarfile.TarInfo(name);info.size=len(data);info.mode=0o600;t.addfile(info,io.BytesIO(data))
    digest=h.sha((args.output/'mail-install.tar').read_bytes());prepare(args.output,digest)
    result={'sha256':digest,'expires_epoch':spec['expires_epoch'],'target_contact':False,'execution_authorized':False}
    (args.output/'sealing.json').write_bytes(h.encoded(result));return result


def prepare(directory,digest):
    raw=h.private(directory/'mail-install.tar',16*h.LIMIT)
    if h.sha(raw)!=digest: raise ValueError('archive digest mismatch')
    with tarfile.open(fileobj=io.BytesIO(raw)) as t:
        members=t.getmembers()
        if any(not m.isfile() or '/' in m.name or m.size>4*h.LIMIT for m in members) or len({m.name for m in members})!=len(members):
            raise ValueError('flat regular archive required')
        files={m.name:t.extractfile(m).read() for m in members}
    spec=json.loads(files['spec.json'])
    expected=set(SOURCES)|{'known_hosts','msmtprc','aliases','cron.pending','report.eml','failure.eml'}|{p['filename'] for p in spec['packages']}
    if set(files)!=expected|{'spec.json','review.md'} or spec['members']!={n:h.sha(files[n]) for n in expected}:
        raise ValueError('member binding')
    for name,path in SOURCES.items():
        if files[name]!=path.read_bytes(): raise ValueError('current source drift')
    if not re.fullmatch(r'[a-z0-9-]{1,64}',spec['operation_id']) or spec['hostname']!='j2-svntp1': raise ValueError('identity')
    if not spec['prepared_epoch']-300<=time.time()<spec['expires_epoch']-750: raise ValueError('expired review')
    for name,data in render(files,spec['operation_id']).items():
        if files[name]!=data: raise ValueError('rendered input drift')
    if files['review.md']!=review(spec,files).encode(): raise ValueError('review drift')
    for name in ('known_hosts','spec.json','review.md','report.eml','failure.eml'):
        if h.private(directory/name)!=files[name]: raise ValueError('local review drift')
    return spec,files


def execute(args):
    os.umask(0o077);d=args.directory.absolute();spec,files=prepare(d,args.sha256)
    payload=(b"import base64,json,os,signal,types\nos.umask(0o077)\n"
       +b"ns={'__name__':'helper','__file__':'/sealed/helper.py'}\nexec(compile("
       +repr(files['helper.py']).encode()+b",'/sealed/helper.py','exec'),ns)\nh=types.SimpleNamespace(**ns)\n"
       +b"ns={'__name__':'worker','__file__':'/sealed/worker.py'}\nexec(compile("
       +repr(files['worker.py']).encode()+b",'/sealed/worker.py','exec'),ns)\n"
       +b"signal.signal(signal.SIGALRM,h.expired)\nsignal.alarm(720)\ninputs={k:base64.b64decode(v) for k,v in "
       +repr({k:base64.b64encode(v).decode() for k,v in files.items() if k not in ('runner.py','helper.py','worker.py','review.md','tests.py','spec.json')}).encode()
       +b".items()}\nprint(json.dumps(ns['Install']("+repr(spec).encode()+b",inputs,h).run()))\n")
    argv=h.ssh_argv({'endpoints':['10.1.0.51'],'host_key_alias':'10.1.0.137'},d)
    with (d/'execution.json').open('xb') as f:
        f.write(h.encoded({'bundle_sha256':args.sha256,'argv':argv,'epoch':int(time.time()),'payload_sha256':h.sha(payload)}));f.flush();os.fsync(f.fileno())
    result=h.bounded(argv,timeout=750,limit=24*h.LIMIT,payload=payload,env=os.environ.copy())
    for n in ('stdout','stderr'): (d/(n+'.txt')).write_text(result.pop(n))
    result.update(bundle_sha256=args.sha256,accepted=False,delivery_verified=False)
    if result.get('returncode')==0 and not result.get('error'):
        try:
            state=json.loads((d/'stdout.txt').read_text())
            if state['spec_sha256']!=h.sha(h.encoded(spec)) or state['operation_id']!=spec['operation_id']: raise ValueError('result binding')
            result['accepted']=state.get('accepted') is True
        except (ValueError,KeyError,TypeError) as e: result['error']=str(e)
    (d/'result.json').write_bytes(h.encoded(result));return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='action',required=True)
    p=sub.add_parser('seal');p.add_argument('--baseline',type=Path,required=True);p.add_argument('--cache',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p=sub.add_parser('execute');p.add_argument('--directory',type=Path,required=True);p.add_argument('--sha256',required=True)
    args=parser.parse_args();result=seal(args) if args.action=='seal' else execute(args);print(json.dumps(result))
    if args.action=='execute' and not result['accepted']:raise SystemExit(1)


if __name__=='__main__':main()
