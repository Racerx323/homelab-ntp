#!/usr/bin/python3
"""Seal/check/execute one isolated metadata resolution; never deploy its plan."""
import argparse
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import tarfile
import time

ROOT=Path(__file__).resolve().parents[1]
SOURCES={'runner.py':Path(__file__).resolve(), 'worker.py':ROOT/'scripts/resolve-maintenance.py',
         'common.py':ROOT/'scripts/review-maintenance-snapshot.py',
         'snapshot-worker.py':ROOT/'scripts/maintenance-snapshot.py',
         'helper.py':ROOT/'scripts/run-production-inspection.py',
         'foundation.py':ROOT/'scripts/resolve-trixie-packages.py',
         'inspection.py':ROOT/'scripts/inspect-trixie.py',
         'policy.json':ROOT/'configs/maintenance-resolution-policy.json',
         'tests.py':ROOT/'tests/test_maintenance_resolution.py',
         'procedure.md':ROOT/'docs/BASE-OS-MAINTENANCE.md'}
loader=importlib.util.spec_from_file_location('maintenance_common',SOURCES['common.py'])
c=importlib.util.module_from_spec(loader);loader.loader.exec_module(c)


def review(spec):
    return f'''# Isolated signed-metadata/full-update resolution

Sealed, unexecuted; exact-hash approval required for `{spec['operation_id']}`.
Only j2-svntp1, ama@10.1.0.51, strict Ed25519 host alias 10.1.0.137.
Snapshot SHA-256 `{spec['snapshot_sha256']}`; captured boot `{spec['boot']}`,
kernel `{spec['kernel']}`. Expires epoch {spec['expires_epoch']}; require 960 seconds
remaining at start. The accepted snapshot must remain no older than 24 hours.

## Inputs and isolation

One isolated Python worker via noninteractive sudo, explicit external SSH key
`{spec['authentication']['identity_file']}` with public fingerprint
`{spec['authentication']['public_fingerprint']}`. Local key checks and exclusive
fsynced receipt precede SSH. No agent/password or arbitrary remote imports. Sources,
policy, helpers, tests, accepted snapshot/outcome and host key are frozen in this
archive. Never replay the consumed snapshot or foundation installer.

Before scratch/network access, verify the approved snapshot's complete selected
configuration/key/package-state hashes, ownership, links and membership, boot and
kernel; check root/ama UID, dpkg audit, architectures, package process/lock state,
inactive APT jobs and at least 2 GiB staging headroom. Capture selected native
services/process identities and live APT-list metadata before/after. Package
activity is observed, not disabled or locked out; any continuity change invalidates
the result. No timer/service changes are permitted.

Create exactly `/var/tmp/{spec['operation_id']}` exclusively, root-owned initially
0700, then 0711 for the native _apt sandbox. Copy dpkg status/extended-state into
0700 state with 0600 files. Only sources, public keyrings, pin and APT configuration
are staged 0644; lists/cache directories allow the native sandbox. Credentials are
not copied. All lists, caches, logs, sources, trust and preferences point inside this
workspace; main/parts/auth paths exclude live configuration, dpkg execution points
to /bin/false, and the actual native/Python configuration must match. No hooks,
maintainer scripts, needrestart, firmware utility, package download/install,
notification, udev action, reboot or panic is invoked.

## Network and resolution scope

Run one `apt-get --error-on=any update` using isolated lists with retries disabled,
20-second HTTP(S) timeouts and normal HTTPS verification. Sources are exactly the
captured Debian trixie/trixie-updates/security, Raspberry Pi trixie and Webmin stable
contrib endpoints, with their exact captured public keyring hashes. Preserve the
Webmin preference verbatim: webmin priority 500 for download.webmin.com; other
packages from that origin priority -1. Preserve arm64 plus armhf. The accepted
snapshot redacted four package-name rows. The bundled accepted predecessor
contains unredacted inventory/selections with the identical before/after dpkg-status
hash, proving the unchanged package versions and absence of holds. Changed dpkg
state/holds reject before access. No new target read was used for this reconciliation.
No public repository setup script or new trust key is downloaded/executed.

Require successful APT authentication, independently verify each retained InRelease
with gpgv and its staged keyring, and check the expected signed origin/suite/codename,
release date/expiry, exact Packages index hashes/sizes and architecture/component
coverage. Webmin must match its previously reviewed signing fingerprint. Sources
without Valid-Until are explicitly recorded; current retrieval and a valid signature
do not prove that a publisher issued newer metadata. No expiry/signature bypass.

Run native `apt-get --simulate dist-upgrade` and Python APT's full-upgrade solver
against the same isolated state/preferences. Require exact additions/upgrades/removal
agreement and no broken solution. Record every selected version/architecture,
trusted origin, payload URI/SHA-256 and package record, plus kept-back/held packages.
Removals, downgrades, additions, source-built NTP/GPSD conflicts and kernel/firmware
changes are explicit findings for later review, never permission to apply them.
An unsupported solver/metadata format or disagreement holds acceptance. Local
qualification uses real controller APT 2.8.3; the installed target APT 3.0.3 and
Python APT 3.0.0 must validate their configuration and agree during this stage.
Local tests do not substitute for that native target evidence.

## EEPROM and later maintenance

The accepted snapshot captured rpi-eeprom 28.33-1, default firmware channel and an
active/exited rpi-eeprom-update.service whose boot command is -s -a. Inspected
pieeprom.upd/pieeprom.sig/recovery.bin were absent. Preserve this evidence and flag
selected firmware/kernel packages. This operation does not inspect or execute new
package scripts, prove EEPROM rollback, disable that service, or authorize a reboot.
Even an unchanged EEPROM package requires later boot-effect/recovery disposition.

## Bounds, interruption and acceptance

Main worker work is limited to 660 seconds; native update 300 seconds, full solver
120 seconds, other commands 30 seconds; command output 4 MiB and controller output
16 MiB. Final continuity and cleanup have controller headroom up to 960 seconds.
At most 512 changed and 512 kept-back packages. Each selected read retains the
snapshot collector's bounds. Completed commands/partial findings survive handled
failure in the capture. Transport failure retains raw bounded output/status.

Always attempt cleanup of this owned disposable workspace after continuity and
metadata hashing. Require its recorded device/inode/root ownership and symlink-safe
rmtree; it never targets live APT paths. Uncertain interruption/changed ownership
leaves exact residue for a separately scoped inspection, never an automatic retry.
A receipt consumes the attempt even if metadata acquisition fails. No live package
or configuration rollback is needed; no installed state is intentionally changed.

Acceptance requires complete authenticated metadata, native/Python agreement,
unchanged live state and proved workspace removal, followed by reviewed findings.
Retain signed releases, signed index hashes, selected package records and command
results privately; bulk Packages files are deleted with scratch after hashing.
This is resolution evidence, not update readiness or deployment acceptance.
Exact payload/script/trigger/conffile/firmware effects and qualified recovery must
precede a separately approved update/reboot review. OBS-02/D1–D5 and bounded OBS-04
remain unchanged; panic and OBS-09 remain held.

After approval, from homelab-ntp:
`python3 -I -B ntpsec/scripts/review-maintenance-resolution.py execute --directory {spec['directory']} --sha256 APPROVED_SHA256`
'''


def payload(spec, files):
    program='import types, sys, json\n'
    for name,key in [('h','helper.py'),('inspection','inspection.py'),('f','foundation.py'),('m','snapshot-worker.py'),('w','worker.py')]:
        program+=name+'=types.ModuleType('+repr(name)+'); '+name+'.__file__='+repr('/sealed/'+key)+'\n'
        if name=='f':program+='sys.modules["inspect_trixie"]=inspection\n'
        program+='exec(compile('+repr(files[key])+','+repr(key)+',"exec"),'+name+'.__dict__)\n'
    program+='m.h=h\nw.f=f\nw.m=m\n'
    program+='print(json.dumps(w.run('+repr(spec)+',json.loads('+repr(files['snapshot.json'])+')),sort_keys=True))\n'
    return ('exec('+repr(program)+')\n').encode()


def check(directory,digest,live=False):
    directory=c.private_dir(directory);raw=c.read(directory/'resolution.tar')
    c.require(c.sha(raw)==digest,'archive SHA mismatch')
    files=c.unpack(raw)
    c.require(set(files)==set(SOURCES)|{'spec.json','review.md','known_hosts','snapshot.json','snapshot-outcome.json','qualification.json','package-event.json','package-outcome.json'},'closed archive')
    spec=json.loads(files['spec.json'])
    c.require(spec['purpose']=='isolated-maintenance-resolution' and spec['hostname']=='j2-svntp1','scope')
    c.require(str(directory)==spec['directory'] and directory.name==spec['operation_id']
              and re.fullmatch(r'base-os-metadata-resolution-[0-9]{8}-v[0-9]+',directory.name),'operation binding')
    c.require(spec['workspace']=='/var/tmp/'+directory.name,'workspace binding')
    c.require(files['review.md']==review(spec).encode(),'review binding')
    c.require(spec['members']=={n:c.sha(v) for n,v in files.items() if n not in ('spec.json','review.md')},'member hashes')
    for name,path in SOURCES.items():c.require(files[name]==path.read_bytes(),'source drift: '+name)
    for name,raw in files.items():c.require(c.read(directory/name)==raw,'local artifact drift: '+name)
    if live:c.require(spec['prepared_epoch']-300<=time.time()<spec['expires_epoch']-960,'approval/fresh-snapshot window')
    return spec,files


def execute(directory,digest):
    spec,files=check(directory,digest,True)
    c.require(c.authentication(spec['authentication']['identity_file'])==spec['authentication'],'authentication drift')
    c.create(directory/'execution.json',{'sha256':digest,'epoch':time.time(),'purpose':spec['purpose']})
    result={'resolution_complete':False,'installation_authorized':False,'no_retry':True}
    try:
        helper=c.module('helper',files['helper.py'])
        row=helper.bounded(c.ssh(directory,spec),timeout=960,limit=16*1024**2,payload=payload(spec,files),env=c.ENV)
        c.create(directory/'transport.json',row)
        c.require(row.get('returncode')==0 and not row.get('error'),'transport incomplete')
        capture=json.loads(row['stdout']);c.create(directory/'capture.json',capture)
        c.require(capture['operation_id']==spec['operation_id'] and capture['resolution_complete']
                  and capture['workspace_cleaned'] and capture['live_state_unchanged'],'resolution held')
        result.update(resolution_complete=True,capture_sha256=c.sha(c.read(directory/'capture.json')))
    except (Exception,KeyboardInterrupt) as error:result.update(held=True,error=str(error))
    c.create(directory/'result.json',result);return result


def seal(args):
    directory=args.directory.absolute();c.require(not directory.exists(),'existing operation')
    base=c.private_dir(args.snapshot.absolute());outcome_raw=c.read(base/'outcome.json');outcome=json.loads(outcome_raw)
    c.require(outcome.get('capture_accepted') is True and outcome.get('native_parser_accepted') is True
              and outcome.get('scratch_cleaned') is True,'accepted snapshot required')
    for name,digest in outcome['evidence_sha256'].items():
        c.require(Path(name).name==name and c.sha(c.read(base/name))==digest,'snapshot evidence drift')
    archive=c.read(base/'inspection.tar');c.require(c.sha(archive)==outcome['archive_sha256'],'snapshot seal drift')
    prior=c.unpack(archive);snapshot_raw=c.read(base/'capture.json');snapshot=json.loads(snapshot_raw)
    policy=json.loads(SOURCES['policy.json'].read_text());rows=snapshot['before']['files']
    for key in ('/etc/apt/apt.conf','/etc/apt/preferences'):
        c.require(rows[key].get('missing') is True,'additional base APT policy requires review')
    c.require(rows['/etc/apt/sources.list'].get('text','').strip()=='','nonempty legacy base sources require review')
    c.require(snapshot['before']['directories']['/etc/apt/sources.list.d']==[
              '/etc/apt/sources.list.d/debian.sources','/etc/apt/sources.list.d/raspi.sources','/etc/apt/sources.list.d/webmin-reviewed.list'], 'source membership review')
    c.require(snapshot['before']['directories']['/etc/apt/preferences.d']==['/etc/apt/preferences.d/webmin-reviewed'],'additional pin review')
    pin='Package: webmin\nPin: origin download.webmin.com\nPin-Priority: 500\n\nPackage: *\nPin: origin download.webmin.com\nPin-Priority: -1\n'
    c.require(rows['/etc/apt/preferences.d/webmin-reviewed']['text']==pin,'Webmin pin policy')
    source='deb [signed-by=/usr/share/keyrings/webmin-reviewed.gpg] https://download.webmin.com/download/newkey/repository stable contrib\n'
    c.require(rows['/etc/apt/sources.list.d/webmin-reviewed.list']['text']==source,'Webmin source policy')
    c.require(rows['/usr/share/keyrings/webmin-reviewed.gpg']['sha256']==policy['webmin_keyring_sha256'],'Webmin approved key identity')
    # Validate the captured Deb822 sources against the original reviewed Debian/RPi policy.
    inspection=c.module('inspection',SOURCES['inspection.py'].read_bytes())
    import sys
    old=sys.modules.get('inspect_trixie');sys.modules['inspect_trixie']=inspection
    try:f=c.module('foundation',SOURCES['foundation.py'].read_bytes())
    finally:
        if old is None:sys.modules.pop('inspect_trixie',None)
        else:sys.modules['inspect_trixie']=old
    for name in ('debian.sources','raspi.sources'):
        key='/etc/apt/sources.list.d/'+name
        c.require(not rows[key].get('redacted'),'redacted source')
        f.reviewed_sources(key,rows[key]['text'].encode(),dict(policy,foreign_architectures=['armhf']))
    effective=snapshot['commands']['apt_effective']['stdout']
    c.require('[REDACTED:' not in effective,'redacted APT policy')
    c.require('APT::Install-Recommends "1";' in effective and 'APT::Install-Suggests "0";' in effective,
              'install recommendation policy drift')
    c.require(not re.search(r'(?mi)^(?:APT::Default-Release|APT::Get::(?:Ignore-Hold|Always-Include-Phased-Updates|Never-Include-Phased-Updates)|APT::(?:Solver|Planner))\s',effective),
              'additional solver policy requires qualification')
    c.require(snapshot['commands']['architecture']['stdout'].strip()=='arm64'
              and snapshot['commands']['foreign_architectures']['stdout'].split()==['armhf'],'snapshot architecture policy')
    package_base=c.private_dir(args.package_baseline.absolute())
    package_outcome_raw=c.read(package_base/'outcome.json');package_outcome=json.loads(package_outcome_raw)
    c.require(package_outcome_raw==prior['prior-outcome.json'] and package_outcome.get('capture_accepted') is True,
              'package evidence must be the accepted snapshot predecessor')
    for name,digest in package_outcome['evidence_sha256'].items():
        c.require(Path(name).name==name and c.sha(c.read(package_base/name))==digest,'predecessor evidence drift')
    package_event=c.read(package_base/'event-0001-journal-inputs.json')
    package_capture=json.loads(json.loads(package_event)['data']['stdout'])
    status_hash=rows['/var/lib/dpkg/status']['sha256']
    c.require(package_capture['capture_complete'] and all(package_capture[k]['dpkg_status']['sha256']==status_hash
              for k in ('package_metadata_before','package_metadata_after')),'package state is not identical to fresh snapshot')
    selections=package_capture['selections']['stdout'].splitlines()
    c.require(all(re.fullmatch(r'[a-z0-9][a-z0-9+.:_-]*\s+(?:install|hold|deinstall|purge)',line) for line in selections),
              'unparsed package selection')
    held=[line.split()[0] for line in selections if line.split()[-1]=='hold']
    c.require(not held,'held selections require dedicated solver qualification')
    inventory=dict(line.split('\t')[:2] for line in package_capture['installed_packages']['stdout'].splitlines())
    files={n:p.read_bytes() for n,p in SOURCES.items()};proof=json.loads(c.read(args.qualification.absolute()))
    c.require(proof.get('sources')=={n:c.sha(v) for n,v in files.items()} and proof.get('tests_exit')==0
              and proof.get('native_signed_solver_passed') is True and proof.get('target_contact') is False,'qualification binding')
    files.update({'snapshot.json':snapshot_raw,'snapshot-outcome.json':outcome_raw,'known_hosts':prior['known_hosts'],
                  'package-event.json':package_event,'package-outcome.json':package_outcome_raw,'qualification.json':c.encoded(proof)})
    now=int(time.time());expires=min(now+86400,int(snapshot['started_epoch'])+policy['maximum_snapshot_age_seconds'])
    c.require(now<expires-960,'snapshot too old for resolution')
    spec={'schema':1,'purpose':'isolated-maintenance-resolution','operation_id':directory.name,'directory':str(directory),
          'workspace':'/var/tmp/'+directory.name,'hostname':'j2-svntp1','kernel':'6.18.50+rpt-rpi-v8','boot':snapshot['boot_after'],
          'prepared_epoch':now,'expires_epoch':expires,'snapshot_sha256':c.sha(snapshot_raw),'snapshot_outcome_sha256':c.sha(outcome_raw),
          'authentication':c.authentication(args.identity_file),'foreign_architectures':['armhf'],'held':held,
          'apt_version':inventory['apt'].split('-')[0],'releases':policy['releases'],
          'source_hashes':{p:rows[p]['sha256'] for p in snapshot['before']['directories']['/etc/apt/sources.list.d']},
          'key_hashes':{p:rows[p]['sha256'] for p in {s['keyring'] for s in policy['releases']}},
          'pin_sha256':rows['/etc/apt/preferences.d/webmin-reviewed']['sha256'],'members':{n:c.sha(v) for n,v in files.items()}}
    c.require(re.fullmatch(r'base-os-metadata-resolution-[0-9]{8}-v[0-9]+',directory.name),'operation name')
    files.update({'spec.json':c.encoded(spec),'review.md':review(spec).encode()})
    directory.mkdir(mode=0o700)
    for name,raw in files.items():c.create(directory/name,raw)
    buffer=io.BytesIO()
    with tarfile.open(fileobj=buffer,mode='w',format=tarfile.USTAR_FORMAT) as archive:
        for name,raw in sorted(files.items()):
            item=tarfile.TarInfo(name);item.mode=0o600;item.size=len(raw);archive.addfile(item,io.BytesIO(raw))
    raw=buffer.getvalue();c.create(directory/'resolution.tar',raw);digest=c.sha(raw);check(directory,digest)
    result={'sha256':digest,'execution_ready':True,'execution_approved':False,'target_contact':False,'expires_epoch':expires}
    c.create(directory/'sealing.json',result);return result


def main():
    os.umask(0o077);p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='action',required=True)
    s=sub.add_parser('seal')
    for name in ('directory','snapshot','package-baseline','qualification','identity-file'):s.add_argument('--'+name,type=Path,required=True)
    for name in ('check','execute'):
        s=sub.add_parser(name);s.add_argument('--directory',type=Path,required=True);s.add_argument('--sha256',required=True)
    args=p.parse_args()
    if args.action=='seal':result=seal(args)
    elif args.action=='check':check(args.directory.absolute(),args.sha256);result={'integrity':True,'target_contact':False}
    else:result=execute(args.directory.absolute(),args.sha256)
    print(json.dumps(result,sort_keys=True))
    if result.get('held'):raise SystemExit(1)


if __name__=='__main__':main()
