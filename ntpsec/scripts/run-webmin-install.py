#!/usr/bin/python3
"""Seal and execute a pinned HTTP Webmin installation with guarded startup."""
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

ROOT = Path(__file__).resolve().parents[1]
PATHS = {'runner.py': 'scripts/run-webmin-install.py', 'worker.py': 'scripts/webmin-install.py',
         'helper.py': 'scripts/run-production-inspection.py', 'tests.py': 'tests/test_webmin_install.py',
         'policy.json': 'configs/webmin-http-policy.json', 'guard.conf': 'templates/webmin-first-start.conf',
         'source.list': 'templates/webmin-reviewed.list', 'preferences': 'templates/webmin-reviewed.pref',
         'assets.json': 'configs/webmin-installation-assets.json',
         'candidate-check.py': 'scripts/validate-webmin-candidate.py'}
BUNDLE = 'webmin-install.tar'


def module(name):
    entry = importlib.util.spec_from_file_location(name.replace('-', '_'), ROOT/'scripts'/name)
    value = importlib.util.module_from_spec(entry); entry.loader.exec_module(value)
    return value


helper = module('run-production-inspection.py')
worker = module('webmin-install.py')


def review(spec):
    if spec.get('continuation'):
        return f'''# Webmin HTTP start continuation review

Target **{spec['hostname']}**, boot `{spec['boot_id']}`.
Operation `{spec['operation_id']}`. Expires at epoch {spec['expires_epoch']}.
Read-only startup inspection SHA-256 `{spec['inspection_sha256']}`.
Pinned complete miniserv.conf SHA-256:
`{spec['continuation_files'][str(worker.CONFIG)]['sha256']}`.

## Scope and preflight

Start the installed Webmin 2.670 with its unchanged approved HTTP policy:
10.1.0.51:10000 and [fd36:5aa8:6971:1::51]:10000, allowing only 10.1.0.0/22
and fd36:5aa8:6971:1::/64. Use ama system authentication, disable TLS and UDP
discovery. This is the previously approved interim HTTP policy; Caddy is deferred.
No package installation, APT action, configuration rewrite, DNS or firewall change.

Pinned-key SSH as ama, sudo Python through stdin. Require the inspected boot,
NTP process/invocation/restart identity, exact installed inventory and clean dpkg
audit. Verify SHA-256/owner/group/mode for the unit, guard, start/stop wrappers,
miniserv configuration and both miniserv implementation files. Require Webmin
the exact inspected {spec['continuation_unit']['ActiveState']}/{spec['continuation_unit']['SubState']}/disabled
state and prior invocation/exit result, PID/restarts zero, only the inspected drop-in, no permit,
no overriding /etc unit and no port-10000 listeners. Verify ama exists and run
systemd unit validation. Record protected NTP/leap configuration identities.

## Mutation and readiness

Create a fresh root-private operation directory and state record. If the pinned
state is failed, reset-failed only webmin.service, then require inactive/dead,
disabled, PID/restarts zero and the same drop-in before proceeding. Create only
this operation's root-private permit marker, then enable/start Webmin. Retain
the persistent first-start guard. Allow up to 60 seconds for both exact TCP
listeners, polling at most once per second with commands bounded by the remaining
deadline. Fail immediately on unexpected TCP/UDP listeners, failed service,
nonzero restarts or changed process/invocation. Empty or partial approved listener
sets may settle within the deadline; expiry enters recovery.

After listener readiness, require HTTP login endpoint status 200/301/302/303 over
both addresses, with no HTTPS redirect. Each HTTP connection is bounded at
10 seconds. Recheck service identity, configuration hash, guard and NTP continuity.
No NTP/GPSD restart, clock/RTC/drift change, leap run, reboot or password submission.
Local endpoint acceptance does not establish authenticated ama client access or
controller/External exposure. Those remain separate acceptance steps.

## Recovery and bounds

On failure after mutation, stop Webmin first and require no port-10000 sockets.
Verify guard and this operation's permit identity, remove that permit and disable
Webmin. Recheck NTP continuity. Retain installed packages/configuration/evidence.
Changed guard/permit or failed containment holds recovery for inspection.
No uninstall, dependency cleanup, automatic retry or second start.

Remote deadline 600 seconds; SSH 780 seconds includes bounded recovery. Catchable
interruptions attempt recovery; uncertain transport or power loss requires a
fresh inspection. The local execution receipt and target directory are single-use.
The flat bundle contains current repository code and selected inspection data;
no packages or previous archives are nested. Execution requires this bundle hash.

From the repository root after approval:
`python3 -I -B ntpsec/scripts/run-webmin-install.py execute --bundle ABSOLUTE_BUNDLE --sha256 APPROVED_SHA256`
'''
    packages = '\n'.join('- '+p['name']+' '+p['version']+' ('+p['architecture']+'), SHA-256 `'+p['sha256']+'`' for p in spec['packages'])
    return f'''# Webmin HTTP installation review

Target **{spec['hostname']}**, boot `{spec['boot_id']}`.
Operation `{spec['operation_id']}`. Expires at epoch {spec['expires_epoch']}.
Baseline inspection SHA-256 `{spec['inspection_sha256']}`.

## Approved access policy

HTTP, TCP 10000, on the host's fixed IPv4 10.1.0.51 and ULA
fd36:5aa8:6971:1::51 only. Allow clients from 10.1.0.0/22 and
fd36:5aa8:6971:1::/64 only; use ama with existing system authentication.
Set ssl=0 and ssl_redirect=0. Disable UDP Webmin discovery. HTTP carries login
traffic without encryption; this is the user's explicit October 15 decision.
Caddy reverse-proxy integration is a separate future project. No proxy, DNS,
UniFi/controller firewall changes or TLS commissioning are included here.

## Exact package and repository changes

Install these six sealed packages with dpkg, without APT refresh/download,
recommended extras, unrelated upgrades/removals or a floating setup script:

{packages}

Write the reviewed Webmin public key to /usr/share/keyrings/webmin-reviewed.gpg,
root:root 0644; add /etc/apt/sources.list.d/webmin-reviewed.list with a scoped
Signed-By reference for the official stable/contrib repository. Add the sealed
APT preference allowing Webmin at priority 500 and denying other packages from
that origin. No global trust-store update or background update is authorized.
These repository files configure future reviewed updates; no apt update is run.

## Preflight and first start

Pinned-key SSH as ama with sudo Python through stdin. Require accepted boot,
arm64, exact retained package inventory, clean dpkg audit, unchanged NTP service
identity and port 10000 free. Require Webmin files, unit/drop-in, repository paths
and /tmp/.webmin absent; reject unexpected files instead of overwriting them.
Reject dpkg pre/post invocation hooks. Require existing ama account. Use dpkg
--no-act --install on all staged packages to check actual dependency/providers
before configuration mutation. No forced dependency override is permitted.

Create a root-private operation directory for sealed packages and state. Before
dpkg installation, install the persistent Webmin drop-in ConditionPathExists=
/etc/webmin/.installation-accepted. That marker does not yet exist. The upstream
setup script rewrites main unit files but does not remove this drop-in. It calls
systemctl start; the unmet condition must keep the service inactive. Require no
port-10000 listener and an intact guard after package configuration.

While stopped, atomically configure the sealed HTTP policy, including exact
bindings, subnet allowlist, ama-only login and sudo-based system authentication.
Check installed versions, no unrelated package changes, audit, Perl modules,
unit validation and NTP continuity. Only then create the root-private permit
marker and enable/start Webmin. Retain the guard and marker as durable installed
configuration, independent of historical operation directories.

Allow a bounded 60-second readiness wait for active/enabled Webmin and exactly
the two approved TCP listeners; reject service failure, restart or unexpected
listeners immediately. Require no UDP
10000 listener, HTTP login endpoint responses over both addresses and unchanged
policy hash and NTP identity. Do not restart NTP/GPSD, alter drift/RTC, force leap
maintenance or reboot. Existing package triggers and normal system logs are in
scope. Generated Webmin/PAM/TLS files may exist even though serving uses HTTP;
never export their secrets. /tmp/.webmin is managed by reviewed package scripts.

## Acceptance and recovery limits

The runner accepts installation and local HTTP endpoints only. Authenticated
acceptance remains pending an operator login as ama from an approved client over
both intended families. Record only success/failure and observed client family,
never credentials or cookies. Do not claim controller/External reachability
acceptance from host-local HTTP checks. No automated password submission is in
this bundle; application deny behavior is tested offline and checked in config.

On failure after mutation, remove this operation's permit marker, stop/disable
only Webmin, confirm no port-10000 listener and NTP continuity. Keep the guard,
packages, repository files and evidence for inspection. This rollback restores
a non-serving state, not the pre-install package footprint. Do not invoke broad
uninstall hooks, autoremove, reconfigure/retry or remove shared dependencies.
If guard/marker identities changed or recovery fails, hold for inspection.

Commands are bounded; dpkg installation 300 seconds, remote operation 600 seconds,
SSH 780 seconds allowing bounded recovery. Catchable interruptions enter recovery;
power loss/SIGKILL/uncertain transport require inspection before another action.
A one-use local receipt and exclusive operation directory prevent blind reruns.

The flat archive contains repository code/tests/templates, selected inspection
data, exact packages and public key. No historical archive is nested or used as
runtime code. Host and workstation installed trust stores remain unchanged at
preparation time. Installation requires separate approval of this archive hash.

After execution approval, from the repository root:
`python3 -I -B ntpsec/scripts/run-webmin-install.py execute --bundle ABSOLUTE_BUNDLE --sha256 APPROVED_SHA256`
'''


def prepare(path, digest):
    raw = helper.private(path, 64*helper.LIMIT)
    if helper.sha(raw) != digest: raise ValueError('approved archive digest mismatch')
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        members = archive.getmembers()
        spec = json.load(archive.extractfile('spec.json'))
        names = set(PATHS) | {'baseline.json', 'known_hosts', 'spec.json', 'review.md'}
        if not spec.get('continuation'):
            names |= {'keyring.gpg'} | {p['member'] for p in spec['packages']}
        if (len(members) != len(names) or {m.name for m in members} != names
                or any(not m.isfile() or m.size > 32*helper.LIMIT for m in members)):
            raise ValueError('closed bounded flat archive required')
        files = {m.name: archive.extractfile(m).read() for m in members}
    spec = json.loads(files['spec.json'])
    if (spec['schema'] != 1 or spec['purpose'] != 'webmin-install' or spec['hostname'] != 'j2-svntp1'
            or spec['endpoints'] != ['10.1.0.51', 'fd36:5aa8:6971:1::51'] or spec['host_key_alias'] != '10.1.0.137'
            or not re.fullmatch(r'[a-z][a-z0-9-]{0,47}', spec['operation_id'])
            or not re.fullmatch(r'[a-f0-9-]{36}', spec['boot_id'])
            or not 0 < spec['expires_epoch']-spec['prepared_epoch'] <= 86400
            or not spec['prepared_epoch']-300 <= time.time() < spec['expires_epoch']-780
            or spec['members'] != {n: helper.sha(files[n]) for n in names-{'spec.json','review.md'}}
            or files['review.md'] != review(spec).encode()):
        raise ValueError('activation scope/window/input binding')
    for name, location in PATHS.items():
        if files[name] != (ROOT/location).read_bytes(): raise ValueError('current repository input drift')
    if spec.get('continuation'):
        if spec['continuation'] is not True or spec['packages'] or set(spec['continuation_files'])!=set(worker.CONTINUATION_PATHS):
            raise ValueError('continuation scope binding')
        unit=spec.get('continuation_unit',{})
        if (set(unit)!=set(worker.RECOVERED_UNIT_KEYS)
                or (unit.get('ActiveState'),unit.get('SubState')) not in (('inactive','dead'),('failed','failed'))):
            raise ValueError('continuation unit binding')
    else:
        assets=json.loads(files['assets.json'])
        expected=[{'name':p['Package'],'version':p['Version'],'architecture':p['Architecture'],
                   'member':Path(p['Filename']).name,'sha256':p['SHA256']} for p in assets['packages']]
        if (spec['packages']!=expected or helper.sha(files['keyring.gpg'])!=assets['keyring_sha256']
                or any(helper.sha(files[p['member']])!=p['sha256'] for p in expected)):
            raise ValueError('candidate package/key binding')
    for name in ('spec.json', 'review.md', 'known_hosts'):
        if helper.private(path.parent/name) != files[name]: raise ValueError('local approval input drift')
    return spec, files


def seal(args):
    inspection = module('run-webmin-inspection.py'); inspection.helper = helper
    old, old_files = inspection.prepare(args.inspection_dir/inspection.BUNDLE, args.inspection_sha256)
    result = json.loads(helper.private(args.inspection_dir/'result.json'))
    raw = helper.private(args.inspection_dir/'stdout.txt', 16*helper.LIMIT); capture = json.loads(raw)
    if (not result.get('capture_complete') or result.get('returncode') != 0 or result.get('error')
            or result['bundle_sha256'] != args.inspection_sha256 or not capture.get('capture_complete')
            or capture['spec_sha256'] != helper.sha(helper.encoded(old))
            or capture['hostname'] != old['hostname'] or capture['operation_id'] != old['operation_id']
            or capture['boot_before'] != old['boot_id'] or capture['boot_after'] != old['boot_id']):
        raise ValueError('complete stable inspection required')
    manifests=json.loads((ROOT/'configs/webmin-installation-assets.json').read_text())['packages']
    wanted=('perl-openssl-defaults','libnet-ssleay-perl','libauthen-pam-perl','libio-pty-perl','libsocket6-perl','webmin')
    packages=[]; files={n:(ROOT/p).read_bytes() for n,p in PATHS.items()}
    continuation = getattr(args,'continuation',False)
    for name in (() if continuation else wanted):
        row=next(r for r in manifests if r['Package']==name)
        member=Path(row['Filename']).name
        data=helper.private(args.assets/member,32*helper.LIMIT)
        if helper.sha(data)!=row['SHA256'] or len(data)!=int(row['Size']): raise ValueError('package identity mismatch')
        files[member]=data
        packages.append({'name':name,'version':row['Version'],'architecture':row['Architecture'],'member':member,'sha256':row['SHA256']})
    if not continuation: files['keyring.gpg']=helper.private(args.assets/'webmin-keyring.gpg')
    now=int(time.time());spec={k:old[k] for k in ('hostname','boot_id','endpoints','host_key_alias','service_identity')}
    spec.update(schema=1,purpose='webmin-install',operation_id=args.operation_id,inspection_sha256=args.inspection_sha256,
                prepared_epoch=now,expires_epoch=min(now+86400,old['expires_epoch']),packages=packages,
                packages_before={line.split('\t')[0]:line.split('\t')[1:] for line in capture['commands']['packages']['stdout'].splitlines()})
    if continuation:
        records=continuation_records(old,capture,files)
        unit=worker.properties(capture['commands']['webmin.service']['stdout'])
        spec.update(continuation=True,continuation_files=records,
                    continuation_unit={k:unit[k] for k in worker.RECOVERED_UNIT_KEYS})
    files['baseline.json']=helper.encoded({'capture_sha256':helper.sha(raw),'inspection_result':result})
    files['known_hosts']=old_files['known_hosts']
    spec['members']={n:helper.sha(v) for n,v in files.items()}
    files.update({'spec.json':helper.encoded(spec),'review.md':review(spec).encode()})
    os.umask(0o077);args.output.mkdir(mode=0o700)
    for name in ('spec.json','review.md','known_hosts'):(args.output/name).write_bytes(files[name])
    bundle=args.output/BUNDLE
    with tarfile.open(bundle,'w') as archive:
        for name,data in sorted(files.items()):
            item=tarfile.TarInfo(name);item.size=len(data);item.mode=0o600;archive.addfile(item,io.BytesIO(data))
    digest=helper.sha(bundle.read_bytes());prepare(bundle,digest)
    result={'sha256':digest,'bundle':str(bundle),'expires_epoch':spec['expires_epoch'],'execution_authorized':False,'target_contact':False}
    (args.output/'sealing.json').write_bytes(helper.encoded(result));return result


def continuation_records(old,capture,files):
    unit=worker.properties(capture['commands']['webmin.service']['stdout'])
    policy=json.loads(files['policy.json'])
    if (not old.get('startup_diagnostic')
            or (unit.get('ActiveState'),unit.get('SubState')) not in (('inactive','dead'),('failed','failed'))
            or any(k not in unit for k in worker.RECOVERED_UNIT_KEYS)
            or unit.get('UnitFileState')!='disabled'
            or unit.get('MainPID')!='0' or unit.get('NRestarts')!='0'
            or unit.get('DropInPaths')!=str(worker.GUARD)
            or capture['commands']['listeners']['stdout'].strip()
            or capture['commands']['dpkg-audit']['stdout'].strip()
            or capture['files'][str(worker.MARKER)]!={'missing':True}
            or capture['files']['/etc/systemd/system/webmin.service']!={'missing':True}
            or any(capture['webmin']['settings'].get(k)!=v for k,v in policy.items())):
        raise ValueError('inspected recovered HTTP baseline required')
    source={**capture['files'],**capture['payload_fingerprints'],str(worker.CONFIG):capture['webmin']}
    records={}
    for path in worker.CONTINUATION_PATHS:
        row=source[path]
        if row.get('missing') or row.get('error') or row.get('changed_during_read') or row.get('uid')!=0 or row.get('gid')!=0:
            raise ValueError('unsafe inspected file: '+path)
        records[path]={k:row[k] for k in ('sha256','uid','gid','mode')}
    if records[str(worker.GUARD)]['sha256']!=helper.sha(files['guard.conf']): raise ValueError('inspected guard mismatch')
    return records


def payload(spec, files):
    inputs={n:base64.b64encode(v).decode() for n,v in files.items() if n not in ('runner.py','helper.py','worker.py','tests.py','spec.json','review.md','baseline.json','known_hosts')}
    return ("import types,json,os,base64\nos.chdir('/')\nhelper=types.ModuleType('helper')\n"
            "helper.__file__='/sealed/helper.py'\nexec("+repr(files['helper.py'])+",helper.__dict__)\n"
            "space={'__name__':'webmin_worker'}\nexec("+repr(files['worker.py'])+",space)\n"
            "inputs={n:base64.b64decode(v,validate=True) for n,v in "+repr(inputs)+".items()}\n"
            "print(json.dumps(space['run']("+repr(spec)+",inputs,helper)))\n").encode()


def execute(args):
    os.umask(0o077); spec, files = prepare(args.bundle, args.sha256)
    request = payload(spec, files); root = args.bundle.parent; argv = helper.ssh_argv(spec, root)
    with (root/'execution.json').open('xb') as stream:
        stream.write(helper.encoded({'epoch': int(time.time()), 'sha256': args.sha256,
                                     'payload_sha256': helper.sha(request), 'argv': argv}))
        stream.flush(); os.fsync(stream.fileno())
    try:
        result = helper.bounded(argv, timeout=780, limit=24*helper.LIMIT, payload=request, env=os.environ.copy())
    except OSError as error:
        result = {'returncode': None, 'error': str(error), 'stdout': '', 'stderr': ''}
    for name in ('stdout', 'stderr'): (root/(name+'.txt')).write_text(result.pop(name))
    result.update(accepted=False, bundle_sha256=args.sha256)
    if result.get('returncode') == 0 and not result.get('error'):
        try:
            state = json.loads((root/'stdout.txt').read_text())
            result['accepted'] = (state.get('installed') is True and not state.get('error')
                and state['operation_id'] == spec['operation_id']
                and state['spec_sha256'] == helper.sha(helper.encoded(spec))
                and state.get('authenticated_accepted') is False)
        except (ValueError, KeyError, TypeError) as error: result['error'] = str(error)
    (root/'result.json').write_bytes(helper.encoded(result)); return result


def main():
    parser = argparse.ArgumentParser(description=__doc__); sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('seal'); p.add_argument('--inspection-dir', type=Path, required=True)
    p.add_argument('--inspection-sha256', required=True); p.add_argument('--assets',type=Path); p.add_argument('--continuation',action='store_true'); p.add_argument('--operation-id', required=True)
    p.add_argument('--output', type=Path, required=True)
    p = sub.add_parser('execute'); p.add_argument('--bundle', type=Path, required=True); p.add_argument('--sha256', required=True)
    args = parser.parse_args()
    if args.command=='seal' and not args.continuation and args.assets is None: parser.error('--assets required for installation')
    result = seal(args) if args.command == 'seal' else execute(args)
    print(json.dumps(result))
    if args.command == 'execute' and not result['accepted']: raise SystemExit(1)


if __name__ == '__main__': main()
