#!/usr/bin/python3
"""Seal one passive watchdog ownership/configuration capture; never open devices."""
import argparse
import base64
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import signal
import socket
import stat
import tarfile
import time
import types

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {'runner.py': ROOT/'scripts/run-watchdog-inspection.py',
           'helper.py': ROOT/'scripts/run-production-inspection.py',
           'passive.py': ROOT/'scripts/run-phase3-node-inspection.py',
           'tests.py': ROOT/'tests/test_watchdog_inspection.py'}
MANAGER = 'RuntimeWatchdogUSec,RuntimeWatchdogPreUSec,RuntimeWatchdogPreGovernor,RebootWatchdogUSec,KExecWatchdogUSec,WatchdogDevice'
KEYS = ('RuntimeWatchdogSec', 'RuntimeWatchdogPreSec', 'RuntimeWatchdogPreGovernor',
        'RebootWatchdogSec', 'KExecWatchdogSec', 'WatchdogDevice')
CONFIG_ROOTS = ('/etc/systemd', '/run/systemd', '/usr/local/lib/systemd', '/usr/lib/systemd')
DEVICES = ('/dev/watchdog', '/dev/watchdog0', '/dev/watchdog1')
h = p = None


def selected_config(raw):
    section = ''; selected = []; incomplete = False
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith(('#', ';')): continue
        if line.startswith('['): section = line; continue
        if section == '[Manager]' and '=' in line:
            key, value = line.split('=', 1)
            if key.strip() in KEYS:
                selected.append([key.strip(), value.strip()])
                incomplete |= value.rstrip().endswith('\\')
    return {'watchdog_assignments': selected, 'continuation_requires_review': incomplete}


def configurations():
    rows = {}
    for root in CONFIG_ROOTS:
        paths = [Path(root)/'system.conf']
        directory = Path(root)/'system.conf.d'
        if directory.resolve() != directory:
            rows[str(directory)] = {'indirect_directory_not_enumerated': True}
        else:
            paths += [f for f in p.names(str(directory), 64) if f.suffix == '.conf']
        for f in paths:
            if f.is_symlink():
                rows[str(f)] = {'link': os.readlink(f), 'content_not_followed': True}
                continue
            row = h.file_record(f, True)
            if 'base64' in row:
                row.update(selected_config(base64.b64decode(row.pop('base64')).decode('utf-8', 'replace')))
            rows[str(f)] = row
    return rows


def process_identity(pid):
    """Read regular proc metadata, never cmdline/environ or fd contents."""
    row = p.text_record('/proc/'+pid+'/stat')
    raw = row.get('text', '')
    end = raw.rfind(')')
    if end < 0: raise ValueError('process stat unavailable')
    fields = raw[end+2:].split()
    return {'pid': int(pid), 'start_ticks': int(fields[19])}


def owners():
    devices = {path: p.metadata(path) for path in DEVICES}
    numbers = {v['device_number'] for v in devices.values() if v.get('type') == stat.S_IFCHR}
    if not numbers: return {'devices': devices, 'matches': [], 'scan_complete': False, 'gaps': ['no device identity']}
    matches = []; gaps = []; total = 0; count = 0
    # stat follows proc's descriptor metadata only; no open/read/dup of fd targets.
    with os.scandir('/proc') as entries:
        for entry in entries:
            if not entry.name.isdecimal(): continue
            count += 1
            if count > 4096: raise ValueError('process count bound')
            pid = entry.name
            try:
                identity = process_identity(pid)
                per_process = 0
                with os.scandir('/proc/'+pid+'/fd') as descriptors:
                    for fd in descriptors:
                        if not fd.name.isdecimal(): continue
                        total += 1; per_process += 1
                        if total > 65536 or per_process > 4096: raise ValueError('descriptor count bound')
                        try:
                            info = os.stat(fd.path)
                            if not stat.S_ISCHR(info.st_mode) or info.st_rdev not in numbers: continue
                            current = process_identity(pid)
                            if current != identity: raise ValueError('matched PID changed')
                            cgroup = p.text_record('/proc/'+pid+'/cgroup')
                            matches.append({**identity, 'fd': int(fd.name), 'rdev': info.st_rdev,
                                'uid': Path('/proc/'+pid).stat().st_uid,
                                'exe_link': os.readlink('/proc/'+pid+'/exe'),
                                'cgroup': cgroup, 'recheck_stable': False})
                        except OSError as error:
                            gaps.append({'pid': int(pid), 'fd': int(fd.name), 'error': type(error).__name__})
                if process_identity(pid) != identity: gaps.append({'pid': int(pid), 'error': 'PID changed'})
            except (OSError, ValueError) as error:
                if isinstance(error, ValueError) and 'bound' in str(error): raise
                gaps.append({'pid': int(pid), 'error': type(error).__name__})
            if len(gaps) > 1024 or len(matches) > 64: raise ValueError('scan report bound')
    for row in matches:
        pid = str(row['pid'])
        try:
            info = os.stat('/proc/'+pid+'/fd/'+str(row['fd']))
            row['recheck_stable'] = (process_identity(pid) == {'pid': row['pid'], 'start_ticks': row['start_ticks']}
                and stat.S_ISCHR(info.st_mode) and info.st_rdev == row['rdev'])
        except (OSError, ValueError): pass
    return {'devices': devices, 'matches': matches, 'scan_complete': not gaps,
            'gaps': gaps, 'process_count': count, 'descriptor_count': total,
            'limitation': 'snapshot of visible process leaders; races, namespaces and unshared thread tables can limit attribution'}


def manager():
    return p.command(['/usr/bin/systemctl', 'show', '--property='+MANAGER])


def collect(spec):
    if os.geteuid() != 0 or socket.gethostname() != 'j2-svntp1': raise ValueError('target identity')
    boot = Path('/proc/sys/kernel/random/boot_id')
    result = {'operation_id': spec['operation_id'], 'hostname': socket.gethostname(),
        'spec_sha256': h.sha(h.encoded(spec)), 'started_epoch': time.time(),
        'boot_before': boot.read_text().strip(), 'units_before': p.state(),
        'protected_before': {f: h.file_record(f) for f in p.PROTECTED},
        'manager_before': manager(), 'configuration_before': configurations()}
    if not all(p.properties(result['units_before'][u]).get('ActiveState') == 'active' for u in p.CORE):
        raise ValueError('core services not active')
    result['ownership'] = owners()
    result['watchdog_sysfs'] = {key: p.text_record('/sys/class/watchdog/watchdog0/'+key, True)
        for key in ('identity', 'state', 'status', 'bootstatus', 'nowayout', 'timeout', 'dev')}
    result['configuration_after'] = configurations(); result['manager_after'] = manager()
    result['protected_after'] = {f: h.file_record(f) for f in p.PROTECTED}
    result['units_after'] = p.state(); result['boot_after'] = boot.read_text().strip()
    result['baseline_boot_matches'] = result['boot_before'] == spec['baseline_boot_id']
    result['baseline_file_matches'] = {f: result['protected_before'][f].get('sha256') == digest
        for f, digest in spec['baseline_file_hashes'].items()}
    result['capture_complete'] = complete(result)
    result.update(completed_epoch=time.time(), target_configuration_mutated=False, production_accepted=False,
                  recovery_accepted=False)
    return result


def complete(r):
    return (r['boot_before'] == r['boot_after'] and r['baseline_boot_matches']
        and all(r['baseline_file_matches'].values())
        and r['protected_before'] == r['protected_after']
        and r['configuration_before'] == r['configuration_after']
        and not any(v.get('error') or v.get('changed_during_read') for v in r['configuration_before'].values())
        and r['manager_before'] == r['manager_after'] and r['manager_before'].get('returncode') == 0
        and bool(p.properties(r['manager_before']))
        and all(r['units_before'][u] == r['units_after'][u]
            and r['units_before'][u].get('returncode') == 0
            and p.properties(r['units_before'][u]).get('ActiveState') == 'active' for u in p.CORE))


def review(spec):
    return f'''# Passive watchdog ownership/configuration inspection

Sealed and unexecuted. Exact-hash execution approval required.
Target j2-svntp1: `ama@10.1.0.51`, existing Ed25519 alias `10.1.0.137`.
Operation `{spec['operation_id']}`; expires at Unix epoch {spec['expires_epoch']}.
Leave 270 seconds before expiry. One SSH connection; no retry or fallback.

## Question and retained evidence

The accepted October 26 node snapshot showed watchdog0 active with timeout 60,
nowayout 0, while watchdog.service/wd_keepalive.service and their fixed
configuration files were absent. Inventory common policy says watchdog=true;
that is intent, not evidence of ownership. Identify the existing descriptor
holder and effective systemd policy before proposing any competing owner or test.
Baseline capture SHA-256: `{spec['baseline_capture_sha256']}`.

## Exact read scope

Code travels on stdin to `cd / && sudo -n /usr/bin/python3 -I -B -`.
No target files/locks are created. Query systemctl show manager properties:
`{MANAGER}`. Retain absent properties as unsupported/unknown, not disabled.
Reuse only the passive collector's fixed ten-unit property queries for continuity
and related service metadata; no unit activation or service-only timer properties.
Read boot ID and hashes of the four protected NTP/cron/reporter files before/after.

Read `{CONFIG_ROOTS}` system.conf and up to 64 entries in each system.conf.d,
selecting .conf files. Regular files only; retain hashes and only [Manager]
assignments for `{KEYS}`. No other configuration values or raw contents exported.
Record symlink targets without following/opening them, including /dev/null masks.
Do not enumerate indirect drop-in directories; retain them as a coverage gap.
Continuations, links, missing properties and source/effective mismatches require
manual review; do not infer effective precedence from this selected parser.

Lstat only `{DEVICES}`. Enumerate numeric /proc process leaders (maximum 4096),
read their stat start ticks and stat their descriptor targets (maximum 4096 per
process, 65536 total). Stat obtains metadata; never open, read or duplicate an
fd target. Match character-device rdev to the lstat device identities, including
holders using an alias. Export only matching PID/start ticks/fd/rdev/UID, exe link
and bounded cgroup metadata. Never read cmdline, environ, process memory, arbitrary
file contents or unrelated descriptor link destinations. Recheck matched PID/fd
identities. Retain bounded races/permission gaps (maximum 1024) and up to 64 matches.
Do not silently skip a gap or claim exhaustive ownership across namespaces,
process churn or unshared thread descriptor tables.

Read watchdog0 sysfs identity,state,status,bootstatus,nowayout,timeout,dev through
sysfs-only resolution. No other hardware, network, package or journal discovery.
Per command 10 seconds/1 MiB per stream; per regular file 1 MiB (text 64 KiB).
Remote alarm 240 seconds; controller 270 seconds/24 MiB per stream.

## Boundaries and acceptance

No device open/ioctl/feed, service start/reload/restart, manager reexec, module
load, sysctl, write, signal, reset, reboot, failure injection, message, package
operation or recovery test. SSH/sudo/D-Bus/read access may create routine audit
logs/access times. Independent recovery and peer/shared-antenna continuity are
prerequisites for a later disruptive review, not claims established here.

Exclusive fsynced local receipt precedes SSH. Interruption/partial output consumes
that receipt; retain streams/status and do not retry. No target cleanup is needed.
Complete capture requires stable boot/core units/protected files/configuration/
manager properties and accepted baseline continuity. Ownership has separate
labels: stable observed holder, scan gaps, missing properties and unresolved
configuration. Capture completion does not imply owner identified or recovery
accepted. Correlate PID 1 only if actually observed; do not assume systemd owns it.

Review results before preparing recovery. OBS-02/D1–D5 and bounded OBS-04 remain
unchanged; OBS-09 remains unstarted. No previous receipt is replayed.

After approval, run from homelab-ntp:
`python3 -I -B ntpsec/scripts/run-watchdog-inspection.py execute --directory {spec['directory']} --sha256 APPROVED_SHA256`
'''


def validate(spec):
    checked = dict(spec)
    if spec.get('purpose') != 'watchdog-ownership' or not re.fullmatch(r'watchdog-ownership-[a-z0-9-]{1,40}', spec.get('operation_id', '')):
        raise ValueError('closed watchdog scope required')
    checked['purpose'] = 'phase3-node-readiness'
    checked['operation_id'] = 'phase3-node-readiness-check'
    checked['directory'] = str(Path(spec['directory']).parent/checked['operation_id'])
    if Path(spec['directory']).name != spec['operation_id']: raise ValueError('directory identity')
    p.validate(checked)


def payload(spec, files):
    raw = b''
    for name, label in [('helper.py', 'helper'), ('passive.py', 'passive'), ('runner.py', 'watchdog')]:
        raw += (f"{label}={{'__name__':'{label}','__file__':'/sealed/{name}'}}\n".encode()
            +b'exec(compile('+repr(files[name]).encode()+f",'/sealed/{name}','exec'),{label})\n".encode())
    raw += b"import types,signal,json\nh=types.SimpleNamespace(**helper)\npassive['h']=h\np=types.SimpleNamespace(**passive)\nwatchdog.update(h=h,p=p)\nsignal.signal(signal.SIGALRM,h.expired)\nsignal.alarm(240)\n"
    return raw+b"print(json.dumps(watchdog['collect']("+repr(spec).encode()+b")))\n"


def prepare(directory, digest):
    raw = h.private(directory/'inspection.tar', 8*h.LIMIT)
    if h.sha(raw) != digest:
        raise ValueError('approved archive digest mismatch')
    expected = set(SOURCES) | {'known_hosts', 'baseline.json', 'spec.json', 'review.md'}
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        members = archive.getmembers()
        if (len(members) != len(expected) or {m.name for m in members} != expected
                or any(not m.isfile() or m.size > h.LIMIT for m in members)):
            raise ValueError('closed bounded archive required')
        files = {m.name: archive.extractfile(m).read() for m in members}
    spec = json.loads(files['spec.json']); validate(spec)
    bound = set(SOURCES) | {'known_hosts', 'baseline.json'}
    if (spec['members'] != {n: h.sha(files[n]) for n in bound}
            or files['review.md'] != review(spec).encode()
            or spec['directory'] != str(directory.absolute())):
        raise ValueError('review/member/directory binding mismatch')
    for n, path in SOURCES.items():
        if files[n] != path.read_bytes():
            raise ValueError('repository source drift')
    for n in ('spec.json', 'review.md', 'known_hosts', 'baseline.json'):
        if h.private(directory/n) != files[n]:
            raise ValueError('local approval input drift')
    if not spec['prepared_epoch']-300 <= time.time() < spec['expires_epoch']-270:
        raise ValueError('inspection validity window')
    return spec, files


def execute(args):
    os.umask(0o077)
    directory = args.directory.absolute(); spec, files = prepare(directory, args.sha256)
    data = payload(spec, files)
    argv = h.ssh_argv({'endpoints': ['10.1.0.51'], 'host_key_alias': '10.1.0.137'}, directory)
    with (directory/'execution.json').open('xb') as stream:
        stream.write(h.encoded({'sha256': args.sha256, 'payload_sha256': h.sha(data),
                               'epoch': time.time(), 'argv': argv}))
        stream.flush(); os.fsync(stream.fileno())
    try:
        result = h.bounded(argv, timeout=270, limit=24*h.LIMIT, payload=data, env=os.environ.copy())
    except OSError as error:
        result = {'error': type(error).__name__, 'returncode': None, 'stdout': '', 'stderr': ''}
    for name in ('stdout', 'stderr'):
        (directory/(name+'.txt')).write_text(result.pop(name))
    result.update(bundle_sha256=args.sha256, capture_complete=False, production_accepted=False)
    if result.get('returncode') == 0 and not result.get('error'):
        try:
            capture = json.loads((directory/'stdout.txt').read_text())
            if (capture['operation_id'] != spec['operation_id'] or capture['hostname'] != 'j2-svntp1'
                    or capture['spec_sha256'] != h.sha(h.encoded(spec))):
                raise ValueError('capture binding mismatch')
            result['capture_complete'] = capture.get('capture_complete') is True
        except (ValueError, KeyError, TypeError):
            result['error'] = 'invalid capture binding'
    (directory/'result.json').write_bytes(h.encoded(result))
    return result


def seal(args):
    base = args.baseline
    outcome_raw = h.private(base/'outcome.json'); outcome = json.loads(outcome_raw)
    if outcome.get('capture_accepted') is not True or outcome.get('operation_id') != 'phase3-node-readiness-20261026-v1':
        raise ValueError('accepted node baseline required')
    for name, digest in outcome['evidence_sha256'].items():
        if Path(name).name != name or h.sha(h.private(base/name, 24*h.LIMIT)) != digest:
            raise ValueError('baseline evidence changed')
    capture_raw = h.private(base/'stdout.txt', 24*h.LIMIT); capture = json.loads(capture_raw)
    if not capture['capture_complete'] or capture['hostname'] != 'j2-svntp1': raise ValueError('baseline capture')
    with tarfile.open(fileobj=io.BytesIO(h.private(base/'inspection.tar', 8*h.LIMIT))) as archive:
        selected = [m for m in archive.getmembers() if m.name == 'known_hosts']
        if len(selected) != 1 or not selected[0].isfile() or selected[0].size > h.LIMIT:
            raise ValueError('known hosts member')
        known = archive.extractfile(selected[0]).read()
    if not re.fullmatch(rb'10\.1\.0\.137 ssh-ed25519 [A-Za-z0-9+/=]+\n?', known): raise ValueError('host pin')
    now = int(time.time())
    spec = {'schema': 1, 'purpose': 'watchdog-ownership', 'operation_id': args.output.name,
        'directory': str(args.output.absolute()), 'prepared_epoch': now, 'expires_epoch': now+86400,
        'baseline_boot_id': capture['boot_after'],
        'baseline_file_hashes': {f: capture['files_after'][f]['sha256'] for f in p.PROTECTED},
        'baseline_capture_sha256': h.sha(capture_raw), 'members': {}}
    validate(spec)
    files = {n: f.read_bytes() for n, f in SOURCES.items()}
    files['known_hosts'] = known
    files['baseline.json'] = h.encoded({'outcome_sha256': h.sha(outcome_raw), 'evidence_sha256': outcome['evidence_sha256']})
    spec['members'] = {n: h.sha(v) for n, v in files.items()}
    files.update({'spec.json': h.encoded(spec), 'review.md': review(spec).encode()})
    os.umask(0o077); args.output.mkdir(mode=0o700)
    for n, raw in files.items(): (args.output/n).write_bytes(raw)
    with tarfile.open(args.output/'inspection.tar', 'w') as archive:
        for n, raw in sorted(files.items()):
            member = tarfile.TarInfo(n); member.size = len(raw); member.mode = 0o600
            archive.addfile(member, io.BytesIO(raw))
    digest = h.sha((args.output/'inspection.tar').read_bytes()); prepare(args.output, digest)
    result = {'sha256': digest, 'expires_epoch': spec['expires_epoch'],
        'execution_ready': True, 'execution_approved': False, 'target_contact': False}
    (args.output/'sealing.json').write_bytes(h.encoded(result))
    return result


def load(path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def main():
    global h, p
    h = load(SOURCES['helper.py']); p = load(SOURCES['passive.py']); p.h = h
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    s = sub.add_parser('seal'); s.add_argument('--baseline', type=Path, required=True); s.add_argument('--output', type=Path, required=True)
    for name in ('check', 'execute'):
        s = sub.add_parser(name); s.add_argument('--directory', type=Path, required=True); s.add_argument('--sha256', required=True)
    args = parser.parse_args()
    if args.action == 'seal': result = seal(args)
    elif args.action == 'check':
        prepare(args.directory.absolute(), args.sha256); result = {'integrity': True, 'target_contact': False}
    else: result = execute(args)
    print(json.dumps(result))
    if args.action == 'execute' and not result['capture_complete']: raise SystemExit(1)


if __name__ == '__main__':
    main()
