#!/usr/bin/python3
"""Seal/check/inspect bounded maintenance effects; no installation or firmware invocation."""
import argparse
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import tarfile
import time
ROOT = Path(__file__).resolve().parents[1]
SOURCES = {'runner.py':Path(__file__).resolve(), 'worker.py':ROOT/'scripts/inspect-maintenance-effects.py',
           'common.py':ROOT/'scripts/review-maintenance-snapshot.py', 'snapshot.py':ROOT/'scripts/maintenance-snapshot.py',
           'helper.py':ROOT/'scripts/run-production-inspection.py', 'tests.py':ROOT/'tests/test_maintenance_effects.py',
           'procedure.md':ROOT/'docs/BASE-OS-MAINTENANCE.md',
           'containment.md':ROOT/'docs/EEPROM-MAINTENANCE-CONTAINMENT.md'}
loader=importlib.util.spec_from_file_location('common', SOURCES['common.py'])
c=importlib.util.module_from_spec(loader);loader.loader.exec_module(c)


def review(s):
    return f'''# Installed maintenance effects: read-only inspection

Sealed, unexecuted. Exact-hash execution approval required. Only j2-svntp1,
ama@10.1.0.51, strict host alias 10.1.0.137. Operation `{s['operation_id']}`.
Boot `{s['boot']}`, kernel `{s['kernel']}`. Expires epoch {s['expires_epoch']};
require 300 seconds remaining. External identity `{s['authentication']['identity_file']}`,
public fingerprint `{s['authentication']['public_fingerprint']}`; no key bytes,
agent, passwords or implicit SSH configuration. One exclusive receipt before SSH.

## Scope and boundaries

One streamed isolated Python worker, root via ama UID 1000 noninteractive sudo.
No target staging. Routine access logging is the only intended target write.
Read the installed control scripts/triggers/conffiles for the exact 22 packages
in spec.json, both unqualified and architecture-qualified dpkg info filenames.
Read bounded trigger registrations, initramfs/kernel/certificate hook trees,
APT listchanges configuration and selected helper implementations. Read EEPROM
unit/default/drop-in policy, default 2711 firmware hashes and backup hashes only,
boot-artifact hashes (16 MiB/file), four named device-tree properties, selected package/APT/
service/process continuity and capacity. Never open raw SPI/EEPROM/block devices.

The frozen worker's ROOTS, HELPERS, SUFFIXES and DT constants close the selection.
Trees: at most five levels, 256 children/directory, 768 records/root, 4 MiB JSON/root.
Regular file hash limit 16 MiB, content only up to 64 KiB, scrub potential secrets.
Symlinks are recorded, never followed; indirect ancestors reject. Large text,
redactions, missing files and symlinked hooks remain explicit assessment gaps.
Boot/initramfs files are hashed and compared again at the end; no contents exported.
A larger-than-bound artifact fails rather than silently skipping recovery evidence.
Include installed initramfs-tools/libc-bin trigger receivers, raspi-firmware defaults,
the complete /usr/share/initramfs-tools tree, modprobe and ld.so configuration,
EEPROM helper enable/mask bookkeeping and planned inhibit-path metadata.

Connect: ama UID 1000, known home path, plus at most 16 already-existing user managers. Inspect metadata of named unit links,
linger and auth.key sentinel; never read credentials, user environments or account
configuration. If its existing bus socket is present, issue a read-only systemctl
user show over the existing local machine bus. No login, daemon activation request,
unit start/restart, signin or external notification. Missing/unavailable user-bus
facts remain unresolved. Enumerate user@ service units and query Connect state only
where an existing /run/user/UID/bus socket is present. No user home or credential
content is read for additional managers. Dormant users remain outside this inventory.

No captured code/config is executed. No APT refresh/simulation, package action,
EEPROM utility, needrestart, initramfs rebuild, certificate trigger, service change,
firmware/media write, reboot, panic, mail, retry or recovery-card boot is allowed.

## Continuity, failure and acceptance

Bind accepted {s['baseline_kind']} capture `{s['baseline_capture_sha256']}` and outcome.
Require its selected package/configuration identity and boot before collection.
Repeat protected state and collected scripts/helpers/trees/firmware at the end;
changes, locks, missing identity or failed required commands hold acceptance.
Retain completed fields and failures, including transport stdout/stderr, on any
error. Worker main phase 240 seconds, final continuity at most 90 seconds,
controller 360 seconds; each native read
command 12 seconds and 1 MiB/stream, total transport 24 MiB. No target cleanup is
needed: no scratch or persistent control is created. A consumed receipt never
replays. No inference of production acceptance from capture completion alone.

Independently assess installed old scripts, triggers, native helper policy,
firmware selection and unresolved references before qualifying any inhibit.
Containment/restoration is not authorized on the node by this inspection.
The old card address is operator-confirmed 10.1.0.51, hostname j1-svntp1; never
operate it concurrently with the rebuilt node on that address. DHCP/static mode
and usable-NTP recovery remain unverified. Keep j1 and antenna power unchanged.
OBS-02/D1–D5 and bounded OBS-04 unchanged; panic/OBS-09 held.

Execute after approval, from homelab-ntp:
`python3 -I -B ntpsec/scripts/review-maintenance-effects.py inspect --directory {s['directory']} --sha256 APPROVED_SHA256`
'''


def check(directory, digest, live=False):
    directory=c.private_dir(directory); raw=c.read(directory/'inspection.tar',32*1024**2)
    c.require(c.sha(raw)==digest,'archive SHA-256'); files=c.unpack(raw)
    c.require(set(files)==set(SOURCES)|{'spec.json','review.md','known_hosts','baseline.json','outcome.json','qualification.json'},'closed archive')
    s=json.loads(files['spec.json'])
    c.require(s['purpose']=='maintenance-effects-inspection' and s['directory']==str(directory)
              and s['operation_id']==directory.name and re.fullmatch(r'base-os-effects-inspection-\d{8}-v\d+',directory.name),'scope binding')
    c.require(files['review.md']==review(s).encode(),'review binding')
    c.require(s['members']=={n:c.sha(v) for n,v in files.items() if n not in ('spec.json','review.md')},'member hashes')
    for n,p in SOURCES.items(): c.require(files[n]==p.read_bytes(),'source drift: '+n)
    for n,v in files.items(): c.require(c.read(directory/n)==v,'local drift: '+n)
    c.require(s['expires_epoch']-s['prepared_epoch']==86400,'validity')
    if live:c.require(s['prepared_epoch']-300<=time.time()<s['expires_epoch']-300,'expired')
    return s,files


def payload(s,files):
    program='import types,json\n'
    for name,member in [('h','helper.py'),('m','snapshot.py'),('w','worker.py')]:
        program+=f'{name}=types.ModuleType({name!r}); {name}.__file__="/sealed/{member}"\nexec(compile({files[member]!r},"{member}","exec"),{name}.__dict__)\n'
    program+='m.h=h; w.m=m\nprint(json.dumps(w.collect('+repr(s)+','+repr(json.loads(files['baseline.json']))+'),sort_keys=True))\n'
    return ('exec('+repr(program)+')\n').encode()


def inspect(directory,digest):
    s,files=check(directory,digest,True)
    c.require(c.authentication(s['authentication']['identity_file'])==s['authentication'],'authentication drift')
    c.create(directory/'execution.json',{'sha256':digest,'epoch':time.time(),'purpose':s['purpose']})
    result={'capture_complete':False,'production_accepted':False,'no_retry':True}
    try:
        h=c.module('helper',files['helper.py'])
        row=h.bounded(c.ssh(directory,s),timeout=360,limit=24*1024**2,payload=payload(s,files),env=c.ENV)
        c.create(directory/'transport.json',row)
        try:
            capture=json.loads(row.get('stdout','')); c.create(directory/'capture.json',capture)
        except (ValueError,TypeError): capture={}
        c.require(row.get('returncode')==0 and not row.get('error'),'transport incomplete')
        c.require(capture.get('operation_id')==s['operation_id'] and capture.get('capture_complete') is True
                  and capture.get('protected_continuity') is True,'capture incomplete')
        result.update(capture_complete=True,capture_sha256=c.sha(c.read(directory/'capture.json',24*1024**2)))
    except (Exception,KeyboardInterrupt) as error: result.update(held=True,error=str(error))
    c.create(directory/'result.json',result);return result


def seal(args):
    d=args.directory.absolute();c.require(not d.exists(),'existing operation')
    prior=c.private_dir(args.baseline.absolute());raw=c.read(prior/'capture.json');out=c.read(prior/'outcome.json')
    accepted=json.loads(out);capture=json.loads(raw)
    kind = 'resolution' if accepted.get('resolution_accepted') is True else 'installed-effects'
    c.require(accepted.get('resolution_accepted') is True or accepted.get('capture_accepted') is True,'accepted baseline')
    c.require(accepted['capture_sha256']==c.sha(raw),'baseline capture hash')
    archive = c.read(prior/('resolution.tar' if kind == 'resolution' else 'inspection.tar'),32*1024**2)
    c.require(accepted['archive_sha256']==c.sha(archive),'prior archive')
    prior_files=c.unpack(archive);old=json.loads(prior_files['spec.json'])
    c.require(old['purpose'] == ('isolated-maintenance-resolution' if kind == 'resolution' else 'maintenance-effects-inspection'),'baseline scope')
    c.require(accepted['execution_receipt_sha256']==c.sha(c.read(prior/'execution.json')),'baseline receipt')
    files={n:p.read_bytes() for n,p in SOURCES.items()};proof=json.loads(c.read(args.qualification.absolute()))
    c.require(proof['sources']=={n:c.sha(v) for n,v in files.items()} and proof['tests_exit']==0,'qualification binding')
    files.update({'known_hosts':prior_files['known_hosts'],'baseline.json':c.encoded(capture['after']),
                  'outcome.json':out,'qualification.json':c.encoded(proof)})
    now=int(time.time())
    s={'purpose':'maintenance-effects-inspection','directory':str(d),'operation_id':d.name,'prepared_epoch':now,
       'expires_epoch':now+86400,'boot':capture['after']['boot'],'kernel':old['kernel'],
       'authentication':old['authentication'],'baseline_capture_sha256':c.sha(raw),'baseline_kind':kind,
       'packages':[{k:x[k] for k in ('package','architecture','installed','version')} for x in (capture['plan']['changes'] if kind == 'resolution' else old['packages'])],
       'members':{n:c.sha(v) for n,v in files.items()}}
    c.require(len(s['packages'])==22 and re.fullmatch(rb'10\.1\.0\.137 ssh-ed25519 [A-Za-z0-9+/=]+\n?',files['known_hosts']),'closed target/selection')
    files.update({'spec.json':c.encoded(s),'review.md':review(s).encode()});d.mkdir(mode=0o700)
    for n,v in files.items():c.create(d/n,v)
    buf=io.BytesIO()
    with tarfile.open(fileobj=buf,mode='w',format=tarfile.USTAR_FORMAT) as tf:
        for n,v in sorted(files.items()):
            info=tarfile.TarInfo(n);info.size=len(v);info.mode=0o600;tf.addfile(info,io.BytesIO(v))
    c.create(d/'inspection.tar',buf.getvalue());digest=c.sha(buf.getvalue());check(d,digest)
    result={'sha256':digest,'execution_ready':True,'execution_approved':False,'target_contact':False,'expires_epoch':s['expires_epoch']}
    c.create(d/'sealing.json',result);return result


def main():
    os.umask(0o077);p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='action',required=True)
    for action in ('check','inspect','seal'):
        q=sub.add_parser(action);q.add_argument('--directory',required=True,type=Path)
        if action=='seal':
            q.add_argument('--baseline',required=True,type=Path);q.add_argument('--qualification',required=True,type=Path)
        else:q.add_argument('--sha256',required=True)
    a=p.parse_args()
    if a.action=='seal':result=seal(a)
    elif a.action=='check':check(a.directory.absolute(),a.sha256);result={'integrity':True,'target_contact':False}
    else:result=inspect(a.directory.absolute(),a.sha256)
    print(json.dumps(result));return 1 if result.get('held') else 0

if __name__=='__main__':raise SystemExit(main())
