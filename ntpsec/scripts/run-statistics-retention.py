#!/usr/bin/python3
"""Seal and execute one four-stream statistics retention deployment."""
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
PATHS = {'runner.py':'scripts/run-statistics-retention.py', 'worker.py':'scripts/statistics-retention.py',
         'helper.py':'scripts/run-production-inspection.py', 'tests.py':'tests/test_statistics_retention_deployment.py',
         'fixtures.py':'tests/test_stats_retention.py', 'candidate':'templates/ntpstats-retention.logrotate'}
BUNDLE = 'statistics-retention.tar'


def load(name):
    entry = importlib.util.spec_from_file_location(name, ROOT/'scripts'/name)
    value = importlib.util.module_from_spec(entry); entry.loader.exec_module(value)
    return value


h = load('run-production-inspection.py')
w = load('statistics-retention.py')


def review(spec):
    return f'''# Four-stream statistics retention deployment

Target ama@10.1.0.51 (j2-svntp1), pinned host-key alias 10.1.0.137.
Operation {spec['operation_id']}; accepted boot {spec['boot_id']}.
Expires at epoch {spec['expires_epoch']}. Inspection SHA-256:
{spec['inspection_sha256']}.

## Scope and prerequisites

Install the sealed logrotate rule for loopstats, peerstats, clockstats and
protostats. Keep completed files for at least 30 x 24 hours since their last
write, removing them at the next daily logrotate run (normally 30–31 days).
Keep statistics uncompressed. Preserve active base inodes, all multiple-hardlink
files, symlinks and unrecognized names. Missing or indirect bases block cleanup.
The older protostats daily file is active and protected despite its date/owner.
No NTP configuration, ownership, process, clock, package or service change.
No notification, plotting-host contact, reboot or global forced log rotation.

Require the same boot, NTP supervisor identity and ntpd process start identity.
Recheck pinned NTP/logrotate configuration hashes/owners/modes and logrotate.d
membership; require active writable associations for all four base files and
unchanged statistics-directory metadata. Reject any existing destination rule
or control directory. Require logrotate.timer enabled/waiting and logrotate.service
idle before and after. Reuse the existing scheduler without changing its units.
Inspected rules showed no overlap; per-user home jobs, unrelated script bodies
and dynamically generated jobs remain outside inspection coverage.

Proposed storage review thresholds: at least 10 GiB free and 5 percent free
inodes. Check these before/after installation; do not shorten retention on failure.
These are conservative operational floors, not measured capacity requirements.
The observed filesystem has about 106 GiB free and 7.6 million free inodes; one
completed three-stream day was 434399 bytes, not a sustained four-stream growth
measurement. Ongoing alerts and growth-budget validation remain acceptance work;
this operation does not configure or claim monitoring integration.

## Exact mutation and validation

Create root-private /var/lib/ntpstats-{spec['operation_id']} for durable receipts,
staged candidate, isolated fixture files and initial-run state. No existing
operation directory may be reused. Run the sealed four-stream fixture with the
target's Python, GNU find and logrotate against disposable private files. This
includes real fixture deletions, age boundaries, active/open hardlinks, symlinks,
compressed filenames and missing-base failure. Fixture cleanup affects only its
private test directory. No deletion test writes into /var/log/ntpstats.

Provision /var/lib/ntpstats-retention root:root 0700 and its empty trigger
root:root 0600. Debug-validate the candidate with a private state file; no debug
cleanup runs. Atomically publish /etc/logrotate.d/ntpstats-retention root:root
0644, only if absent. Force only this rule once using private initial-run state;
it rotates the disposable trigger, never a statistics file. Existing global
logrotate state and other logs are not forced or rewritten by this command.

The approved initial deletion preview is EMPTY. Recompute before installation
and the first run; any eligible file requires a new review rather than widening
this approval. Subsequent daily execution is authorized to delete only eligible
completed four-stream files under the sealed age/link/name rules. Deletion then
has no data rollback; separately archived copies are outside this policy.
The global scheduler uses its normal state file; its first encounter may initialize
this new entry and defer rotation until a later daily run. Do not infer scheduled
success from elapsed time or from the separately forced first run.

Require all labeled checks: preflight, target_fixtures, debug, empty_preview,
first_run and continuity. Recheck rule identity, active writable associations,
NTP continuity, maintenance configuration, scheduler and storage. Record installed
success separately from retention acceptance. Subsequent scheduled execution,
continued log growth, maintenance-failure reporting and ongoing space alerts remain
pending and are not authorized notification tests by this review.

## Recovery and execution

Before installation, failed checks leave production rules unchanged. After local
provisioning, catchable failure removes only this exact candidate rule and this
operation's empty private trigger/control directory, restoring their prior absence.
Foreign edits hold recovery; no unrelated file/service is overwritten or stopped.
Retain operation evidence. Removal disables future cleanup but cannot restore
statistics deleted by a later scheduled run. SIGKILL, power loss or uncertain SSH
requires read-only inspection before retry; no automatic retry or reboot.

Remote deadline 210 seconds; transport 300 seconds; commands 20 seconds and
isolated tests 90 seconds. A single-use local receipt and exclusive target operation
directory prevent replay. One strict-host-key SSH/sudo Python transaction, supplied
through stdin, with private bounded stdout/stderr evidence.

After execution approval bound to this archive's SHA-256, from homelab-ntp:

```text
python3 -I -B ntpsec/scripts/run-statistics-retention.py execute --bundle ABSOLUTE_BUNDLE --sha256 APPROVED_SHA256
```

ABSOLUTE_BUNDLE is this directory's statistics-retention.tar. Retention acceptance
and production readiness remain open until the pending checks are observed.
'''


def prepare(path, digest):
    raw = h.private(path, 8*h.LIMIT)
    if h.sha(raw) != digest:
        raise ValueError('approved archive mismatch')
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        members = archive.getmembers()
        expected = set(PATHS) | {'baseline.json','spec.json','review.md','known_hosts'}
        if len(members) != len(expected) or {m.name for m in members} != expected or any(not m.isfile() or m.size > h.LIMIT for m in members):
            raise ValueError('closed flat archive required')
        files = {m.name:archive.extractfile(m).read() for m in members}
    spec = json.loads(files['spec.json'])
    if (spec['purpose'] != 'statistics-retention' or spec['hostname'] != 'j2-svntp1'
            or spec['endpoints'] != ['10.1.0.51'] or spec['host_key_alias'] != '10.1.0.137'
            or not re.fullmatch(r'[a-z][a-z0-9-]{0,63}',spec['operation_id'])
            or not 0 < spec['expires_epoch']-spec['prepared_epoch'] <= 86400
            or not spec['prepared_epoch']-300 <= time.time() < spec['expires_epoch']-300
            or spec['approved_deletion_preview'] != [] or spec['minimum_free_bytes'] != 10*1024**3
            or spec['minimum_free_inode_fraction'] != 0.05
            or spec['members'] != {n:h.sha(files[n]) for n in set(PATHS)|{'baseline.json','known_hosts'}}
            or files['review.md'] != review(spec).encode()):
        raise ValueError('scope/window/input binding')
    for n,p in PATHS.items():
        if files[n] != (ROOT/p).read_bytes():
            raise ValueError('source drift: '+n)
    for n in ('spec.json','review.md','known_hosts'):
        if files[n] != h.private(path.parent/n):
            raise ValueError('local approval input drift')
    return spec, files


def seal(args):
    d = args.inspection
    receipt = json.loads(h.private(d/'result.json'))
    raw = h.private(d/'stdout.txt', 16*h.LIMIT); capture = json.loads(raw)
    archive = h.private(d/'inspection.tar', 8*h.LIMIT)
    if (h.sha(archive) != args.inspection_sha256 or receipt.get('bundle_sha256') != args.inspection_sha256
            or receipt.get('capture_complete') is not True or receipt.get('returncode') != 0 or receipt.get('error')
            or capture.get('capture_complete') is not True or capture.get('error')):
        raise ValueError('complete approved inspection required')
    with tarfile.open(fileobj=io.BytesIO(archive)) as t:
        old = json.loads(t.extractfile('spec.json').read())
        known = t.extractfile('known_hosts').read()
    if (capture['operation_id'] != old['operation_id'] or capture['spec_sha256'] != h.sha(h.encoded(old))
            or not old.get('followup')):
        raise ValueError('follow-up baseline binding')
    before, after = capture['writers_before']['processes'], capture['writers_after']['processes']
    writers = [row for row in before if row['comm'] == 'ntpd']
    if len(writers) != 1 or writers[0] not in after:
        raise ValueError('stable ntpd writer required')
    writer = writers[0]
    stats = capture['statistics']; active = {row['name']:row for row in stats['files'] if row['name'] in w.STREAMS}
    for name in w.STREAMS:
        row = active[name]
        if not row['regular'] or row['symlink'] or row['links'] < 2 or not any(fd['writable'] and (fd['device'],fd['inode']) == (row['device'],row['inode']) for fd in writer['descriptors']):
            raise ValueError('active writer association: '+name)
    # This first deployment must not authorize a newly discovered live deletion.
    for row in stats['files']:
        if row['date'] and row['regular'] and row['links'] == 1 and time.time()-row['mtime'] >= 30*86400:
            raise ValueError('nonempty deletion preview needs separate review')
    service = w.properties(capture['commands']['ntp_before']['stdout'])
    if (any(service.get(k) != v for k,v in old['service_identity'].items())
            or service.get('LoadState') != 'loaded'
            or service != w.properties(capture['commands']['ntp_after']['stdout'])):
        raise ValueError('stable service baseline required')
    guards = {'/etc/ntp.conf':w.identity(capture['configuration'])}
    rule_names = []
    for row in capture['maintenance_followup']['files']:
        name = row['path']
        if name in ('/etc/logrotate.conf','/etc/cron.daily/logrotate','/usr/lib/systemd/system/logrotate.service','/usr/lib/systemd/system/logrotate.timer') or name.startswith('/etc/logrotate.d/'):
            guards[name] = w.identity(row['record'])
            if name.startswith('/etc/logrotate.d/'):
                rule_names.append(Path(name).name)
    if '/etc/logrotate.conf' not in guards or not rule_names:
        raise ValueError('maintenance guard coverage missing')
    baseline = {'service':service, 'writer':{k:writer[k] for k in ('pid','start_ticks','exe')},
                'guards':guards, 'rule_names':sorted(rule_names),
                'stats_directory':[stats['directory'][k] for k in ('uid','gid','mode')],
                'capture_sha256':h.sha(raw)}
    now = int(time.time())
    spec = {'purpose':'statistics-retention','operation_id':args.output.name, 'hostname':'j2-svntp1',
            'endpoints':['10.1.0.51'],'host_key_alias':'10.1.0.137','boot_id':old['boot_id'],
            'inspection_sha256':args.inspection_sha256, 'prepared_epoch':now,'expires_epoch':now+86400,
            'approved_deletion_preview':[], 'minimum_free_bytes':10*1024**3,'minimum_free_inode_fraction':0.05}
    files = {n:(ROOT/p).read_bytes() for n,p in PATHS.items()}
    files.update({'baseline.json':h.encoded(baseline),'known_hosts':known})
    spec['members'] = {n:h.sha(v) for n,v in files.items()}
    files.update({'spec.json':h.encoded(spec),'review.md':review(spec).encode()})
    os.umask(0o077); args.output.mkdir(mode=0o700)
    for n in ('spec.json','review.md','known_hosts'):
        (args.output/n).write_bytes(files[n])
    bundle = args.output/BUNDLE
    with tarfile.open(bundle,'w') as t:
        for n,v in sorted(files.items()):
            m = tarfile.TarInfo(n); m.size = len(v); m.mode = 0o600; t.addfile(m,io.BytesIO(v))
    digest = h.sha(bundle.read_bytes()); prepare(bundle,digest)
    result = {'sha256':digest,'expires_epoch':spec['expires_epoch'],'target_contact':False,'execution_authorized':False}
    (args.output/'sealing.json').write_bytes(h.encoded(result))
    return result


def execute(args):
    os.umask(0o077)
    spec, files = prepare(args.bundle,args.sha256)
    payload = ("import types,json,os\nos.chdir('/')\nh=types.ModuleType('helper')\nh.__file__='/sealed/helper.py'\nexec("
               +repr(files['helper.py'])+",h.__dict__)\nw={'__name__':'worker'}\nexec("+repr(files['worker.py'])+",w)\nprint(json.dumps(w['run']("
               +repr(spec)+","+repr(json.loads(files['baseline.json']))+","+repr({n:files[n] for n in ('candidate','fixtures.py')})+",h)))\n").encode()
    d = args.bundle.parent; argv = h.ssh_argv(spec,d)
    with (d/'execution.json').open('xb') as f:
        f.write(h.encoded({'sha256':args.sha256,'payload_sha256':h.sha(payload),'argv':argv,'epoch':int(time.time())}))
        f.flush(); os.fsync(f.fileno())
    try:
        result = h.bounded(argv,timeout=300,limit=16*h.LIMIT,payload=payload,env=os.environ.copy())
    except OSError as error:
        result = {'returncode':None,'error':str(error),'stdout':'','stderr':''}
    for n in ('stdout','stderr'):
        (d/(n+'.txt')).write_text(result.pop(n))
    result.update(bundle_sha256=args.sha256,installed=False,retention_accepted=False)
    if result.get('returncode') == 0 and not result.get('error'):
        try:
            state = json.loads((d/'stdout.txt').read_text())
            result['installed'] = (state.get('installed') is True and not state.get('error')
                and state['operation_id'] == spec['operation_id'] and state['spec_sha256'] == h.sha(h.encoded(spec))
                and state['checks'] == dict.fromkeys(w.CHECKS,True))
        except (ValueError,KeyError,TypeError) as error:
            result['error'] = str(error)
    (d/'result.json').write_bytes(h.encoded(result)); return result


def main():
    p = argparse.ArgumentParser(description=__doc__); sub = p.add_subparsers(dest='action',required=True)
    s = sub.add_parser('seal'); s.add_argument('--inspection',type=Path,required=True)
    s.add_argument('--inspection-sha256',required=True); s.add_argument('--output',type=Path,required=True)
    e = sub.add_parser('execute'); e.add_argument('--bundle',type=Path,required=True); e.add_argument('--sha256',required=True)
    args = p.parse_args(); result = seal(args) if args.action == 'seal' else execute(args)
    print(json.dumps(result))
    if args.action == 'execute' and not result['installed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
