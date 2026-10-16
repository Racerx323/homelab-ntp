#!/usr/bin/python3
"""Seal and execute one leap-maintenance activation from inspected state."""
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
PATHS = {'runner.py': 'scripts/run-leap-activation.py', 'worker.py': 'scripts/leap-activation.py',
         'helper.py': 'scripts/run-production-inspection.py', 'tests.py': 'tests/test_leap_activation.py',
         'ntpleapfetch.service': 'templates/ntpleapfetch-j2.service'}
BUNDLE = 'leap-activation.tar'


def module(name):
    entry = importlib.util.spec_from_file_location(name.replace('-', '_'), ROOT/'scripts'/name)
    value = importlib.util.module_from_spec(entry); entry.loader.exec_module(value)
    return value


helper = module('run-production-inspection.py')
worker = module('leap-activation.py')


def review(spec):
    return f'''# Leap-maintenance activation review

Target **{spec['hostname']}**, boot `{spec['boot_id']}`.
Operation `{spec['operation_id']}`; expires at epoch {spec['expires_epoch']}.
Baseline inspection SHA-256 `{spec['inspection_sha256']}`.

One pinned-key SSH execution as ama with sudo Python through stdin. Reject
changed boot, time-service invocation/PID/restart count, inspected file hashes
or ownership/modes, leap-directory metadata, overrides, or non-idle leap units.
The live leapfile must remain outside the 60-day prefetch window.

Create a root-private `/var/lib/ntp-leap-{spec['operation_id']}` directory for
backup, candidate, download and state. Validate the candidate with the target's
systemd-analyze before installation. Use the hash-pinned installed ntpleapfetch
to force an HTTPS IANA download into this private directory, including its
checksum/expiry validation and file installation. Keep the downloaded file as
evidence; do not promote it to the live leapfile during this acceptance stage.

Replace only `/etc/systemd/system/ntpleapfetch.service`, root:root 0644.
Correct `-e 60` to `-e "60 days"` and `-i 10` to `-i 0`: the retry interval is
minutes, so ten minutes cannot fit TimeoutStartSec=120. Allow up to three fetch
attempts without an inter-attempt sleep, subject to the existing 120-second
total unit limit. Wget can retry internally; three completed attempts are not
guaranteed within that bound. No restart command is supplied to ntpleapfetch.

Reload systemd, start the maintenance oneshot once, require success and unchanged
live leapfile, then enable/start ntpleapfetch.timer. Require enabled/active/waiting
and a finite next trigger. Preserve the timer bytes: initial trigger 15 minutes
plus up to 30 minutes random delay; subsequent interval four weeks plus jitter.
Later automatic runs may update the live leapfile when inside the prefetch
window. Ntpd checks it daily without a restart. This approval includes that
ongoing scheduled maintenance, not only the initial test.

Require unchanged time-service PID/invocation/restart count and protected files
afterwards. No ntpd/timeservice restart, signal, receiver change, drift write,
clock adjustment, package action or reboot. Record success as leap maintenance
acceptance only, not overall production readiness.

Before mutation, failures leave installed configuration unchanged. After mutation,
conditionally disable/stop the leap timer, stop only the leap fetch service,
restore the exact original unit, reload systemd and clear that service's failure
state. Verify original files, disabled/inactive timer and NTP continuity. If
protected identities changed or recovery fails, hold and retain evidence; never
overwrite unrelated changes. The operation directory and logs remain for audit.

Remote deadline 360 seconds; synchronous recovery has bounded commands. SSH
deadline 600 seconds, allowing time for recovery. Ordinary catchable
interruptions attempt conditional recovery. Power loss/SIGKILL/uncertain
transport cannot guarantee rollback:
inspect the retained state and actual units before any retry. Local execution
receipt and exclusive target directory prevent blind reruns. No watchdog,
reboot or unrelated fallback is introduced.

The flat archive contains current repository code, unit, tests and selected
inspection data; no prior archive or historical executable is embedded.

After explicit approval of this archive's SHA-256, from the repository root:
`python3 -I -B ntpsec/scripts/run-leap-activation.py execute --bundle ABSOLUTE_BUNDLE --sha256 APPROVED_SHA256`
'''


def prepare(path, digest):
    raw = helper.private(path, 4*helper.LIMIT)
    if helper.sha(raw) != digest: raise ValueError('approved archive digest mismatch')
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        members = archive.getmembers(); names = set(PATHS) | {'baseline.json', 'known_hosts', 'spec.json', 'review.md'}
        if (len(members) != len(names) or {m.name for m in members} != names
                or any(not m.isfile() or m.size > helper.LIMIT for m in members)):
            raise ValueError('closed bounded flat archive required')
        files = {m.name: archive.extractfile(m).read() for m in members}
    spec = json.loads(files['spec.json'])
    if (spec['schema'] != 1 or spec['purpose'] != 'leap-activation' or spec['hostname'] != 'j2-svntp1'
            or spec['endpoints'] != ['10.1.0.51', 'fd36:5aa8:6971:1::51'] or spec['host_key_alias'] != '10.1.0.137'
            or not re.fullmatch(r'[a-z][a-z0-9-]{0,47}', spec['operation_id'])
            or not re.fullmatch(r'[a-f0-9-]{36}', spec['boot_id'])
            or not 0 < spec['expires_epoch']-spec['prepared_epoch'] <= 86400
            or not spec['prepared_epoch']-300 <= time.time() < spec['expires_epoch']-600
            or spec['members'] != {n: helper.sha(files[n]) for n in set(PATHS) | {'baseline.json', 'known_hosts'}}
            or files['review.md'] != review(spec).encode()):
        raise ValueError('activation scope/window/input binding')
    for name, location in PATHS.items():
        if files[name] != (ROOT/location).read_bytes(): raise ValueError('current repository input drift')
    for name in ('spec.json', 'review.md', 'known_hosts'):
        if helper.private(path.parent/name) != files[name]: raise ValueError('local approval input drift')
    return spec, files


def seal(args):
    inspection = module('run-leap-inspection.py'); inspection.helper = helper
    old, old_files = inspection.prepare(args.inspection_dir/inspection.BUNDLE, args.inspection_sha256)
    result = json.loads(helper.private(args.inspection_dir/'result.json'))
    raw = helper.private(args.inspection_dir/'stdout.txt', 16*helper.LIMIT); capture = json.loads(raw)
    if (not result.get('capture_complete') or result.get('returncode') != 0 or result.get('error')
            or result['bundle_sha256'] != args.inspection_sha256 or not capture.get('capture_complete')
            or capture['spec_sha256'] != helper.sha(helper.encoded(old))
            or capture['hostname'] != old['hostname'] or capture['operation_id'] != old['operation_id']
            or capture['boot_before'] != old['boot_id'] or capture['boot_after'] != old['boot_id']
            or capture['commands']['service-before'] != capture['commands']['timeservice.service']):
        raise ValueError('complete stable inspection required')
    # Retain only selected file data and service identity, not old operation bundles.
    selected = capture['files']
    if set(selected) != set(inspection.FILES): raise ValueError('inspection file scope mismatch')
    for row in selected.values():
        worker.identity(row)
        if helper.sha(base64.b64decode(row['base64'], validate=True)) != row['sha256']:
            raise ValueError('captured content hash mismatch')
    baseline = {'files': selected, 'service': worker.properties(capture['commands']['timeservice.service']['stdout']),
                'capture_sha256': helper.sha(raw)}
    now = int(time.time())
    spec = {k: old[k] for k in ('hostname', 'boot_id', 'endpoints', 'host_key_alias')}
    spec.update(schema=1, purpose='leap-activation', operation_id=args.operation_id,
                inspection_sha256=args.inspection_sha256, prepared_epoch=now,
                expires_epoch=min(now+86400, old['expires_epoch']))
    files = {n: (ROOT/p).read_bytes() for n,p in PATHS.items()}
    files.update({'baseline.json': helper.encoded(baseline), 'known_hosts': old_files['known_hosts']})
    spec['members'] = {n: helper.sha(v) for n,v in files.items()}
    files.update({'spec.json': helper.encoded(spec), 'review.md': review(spec).encode()})
    os.umask(0o077); args.output.mkdir(mode=0o700)
    for name in ('spec.json', 'review.md', 'known_hosts'): (args.output/name).write_bytes(files[name])
    bundle = args.output/BUNDLE
    with tarfile.open(bundle, 'w') as archive:
        for name, data in sorted(files.items()):
            item = tarfile.TarInfo(name); item.size = len(data); item.mode = 0o600
            archive.addfile(item, io.BytesIO(data))
    digest = helper.sha(bundle.read_bytes()); prepare(bundle, digest)
    result = {'sha256': digest, 'bundle': str(bundle), 'expires_epoch': spec['expires_epoch'],
              'execution_authorized': False, 'target_contact': False}
    (args.output/'sealing.json').write_bytes(helper.encoded(result)); return result


def payload(spec, files):
    return ("import types,signal,json,os\nos.chdir('/')\nhelper=types.ModuleType('helper')\n"
            "helper.__file__='/sealed/helper.py'\nexec("+repr(files['helper.py'])+",helper.__dict__)\n"
            "space={'__name__':'leap_worker'}\nexec("+repr(files['worker.py'])+",space)\n"
            "signal.signal(signal.SIGALRM,space['interrupted'])\nsignal.alarm(360)\n"
            "print(json.dumps(space['run']("+repr(spec)+","+repr(json.loads(files['baseline.json']))+","
            +repr(files['ntpleapfetch.service'])+",helper)))\n").encode()


def execute(args):
    os.umask(0o077); spec, files = prepare(args.bundle, args.sha256)
    request = payload(spec, files); root = args.bundle.parent; argv = helper.ssh_argv(spec, root)
    with (root/'execution.json').open('xb') as stream:
        stream.write(helper.encoded({'epoch': int(time.time()), 'sha256': args.sha256,
                                     'payload_sha256': helper.sha(request), 'argv': argv}))
        stream.flush(); os.fsync(stream.fileno())
    try:
        result = helper.bounded(argv, timeout=600, limit=24*helper.LIMIT, payload=request, env=os.environ.copy())
    except OSError as error:
        result = {'returncode': None, 'error': str(error), 'stdout': '', 'stderr': ''}
    for name in ('stdout', 'stderr'): (root/(name+'.txt')).write_text(result.pop(name))
    result.update(accepted=False, bundle_sha256=args.sha256)
    if result.get('returncode') == 0 and not result.get('error'):
        try:
            state = json.loads((root/'stdout.txt').read_text())
            result['accepted'] = (state.get('accepted') is True and not state.get('error')
                and state['operation_id'] == spec['operation_id']
                and state['spec_sha256'] == helper.sha(helper.encoded(spec))
                and state['checks'] == dict.fromkeys(('isolated_fetch', 'maintenance_service', 'timer', 'continuity'), True))
        except (ValueError, KeyError, TypeError) as error: result['error'] = str(error)
    (root/'result.json').write_bytes(helper.encoded(result)); return result


def main():
    parser = argparse.ArgumentParser(description=__doc__); sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('seal'); p.add_argument('--inspection-dir', type=Path, required=True)
    p.add_argument('--inspection-sha256', required=True); p.add_argument('--operation-id', required=True)
    p.add_argument('--output', type=Path, required=True)
    p = sub.add_parser('execute'); p.add_argument('--bundle', type=Path, required=True); p.add_argument('--sha256', required=True)
    args = parser.parse_args(); result = seal(args) if args.command == 'seal' else execute(args)
    print(json.dumps(result))
    if args.command == 'execute' and not result['accepted']: raise SystemExit(1)


if __name__ == '__main__': main()
