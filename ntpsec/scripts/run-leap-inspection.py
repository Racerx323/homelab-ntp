#!/usr/bin/python3
"""Seal one read-only leap-maintenance capture; never invoke the fetch utility."""
import argparse
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import signal
import socket
import tarfile
import time
import types

ROOT = Path(__file__).resolve().parents[1]
PATHS = {'runner.py': 'scripts/run-leap-inspection.py',
         'helper.py': 'scripts/run-production-inspection.py',
         'tests.py': 'tests/test_leap_inspection.py'}
FILES = ('/etc/ntp.conf', '/etc/systemd/system/ntpleapfetch.service',
         '/etc/systemd/system/ntpleapfetch.timer', '/usr/local/bin/ntpleapfetch',
         '/usr/local/share/man/man8/ntpleapfetch.8', '/usr/local/share/man/man8/ntpd.8',
         '/var/lib/ntpsec/leap-seconds.list')
UNITS = ('timeservice.service', 'ntpleapfetch.service', 'ntpleapfetch.timer')
BUNDLE = 'leap-inspection.tar'
helper = None


def load(path):
    spec = importlib.util.spec_from_file_location(path.stem.replace('-', '_'), path)
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value)
    return value


def boot():
    return Path('/proc/sys/kernel/random/boot_id').read_text().strip()


def command(argv):
    try:
        return helper.bounded(argv)
    except OSError as error:
        return {'argv': argv, 'returncode': None, 'error': str(error)}


def collect(spec):
    if socket.gethostname().split('.')[0] != spec['hostname'] or os.geteuid() != 0:
        raise ValueError('target/root identity mismatch')
    report = {'operation_id': spec['operation_id'], 'hostname': spec['hostname'],
              'spec_sha256': helper.sha(helper.encoded(spec)), 'started_epoch': time.time(),
              'boot_before': boot(), 'files': {}, 'commands': {}, 'capture_complete': False,
              'production_accepted': False}
    if report['boot_before'] != spec['boot_id']:
        report['error'] = 'accepted boot changed'; return report
    commands = {
        'peers': ['/usr/local/bin/ntpq', '-pn'],
        'system': ['/usr/local/bin/ntpq', '-c', 'rv 0'],
        'units': ['/usr/bin/systemctl', 'cat', 'ntpleapfetch.service', 'ntpleapfetch.timer'],
        'journal': ['/usr/bin/journalctl', '--boot=0', '--no-pager', '-o', 'json', '-n', '60',
                    '-u', 'ntpleapfetch.service', '-u', 'ntpleapfetch.timer']}
    for unit in UNITS:
        props = 'Id,LoadState,ActiveState,SubState,UnitFileState,FragmentPath,DropInPaths'
        if unit.endswith('.service'):
            props += ',MainPID,NRestarts,InvocationID,ExecStart,User,Group,Result'
        else:
            props += ',TimersMonotonic,RandomizedDelayUSec,LastTriggerUSec,NextElapseUSecMonotonic,NextElapseUSecRealtime'
        commands[unit] = ['/usr/bin/systemctl', 'show', unit, '--property='+props]
    report['commands']['service-before'] = command(commands['timeservice.service'])
    for path in FILES:
        report['files'][path] = helper.file_record(path, content=True)
    directory = Path('/var/lib/ntpsec')
    try:
        info = directory.lstat()
        report['leap_directory'] = {'mode': info.st_mode, 'uid': info.st_uid, 'gid': info.st_gid,
                                    'symlink': directory.is_symlink()}
    except OSError as error:
        report['leap_directory'] = {'error': str(error)}
    for name, argv in commands.items():
        report['commands'][name] = command(argv)
    report['boot_after'] = boot(); report['completed_epoch'] = time.time()
    rows = report['commands'].values()
    report['capture_complete'] = (report['boot_after'] == report['boot_before']
        and all(r.get('returncode') == 0 and not r.get('error') for r in rows)
        and all('error' not in r and not r.get('changed_during_read') for r in report['files'].values())
        and 'error' not in report['leap_directory'])
    # Missing files are retained findings, not evidence that activation is ready.
    return report


def review(spec):
    return f'''# Read-only leap-maintenance inspection

Target **{spec['hostname']}**, operation `{spec['operation_id']}`.
Pinned boot `{spec['boot_id']}`; boot archive `{spec['boot_sha256']}` and accepted
client archive `{spec['client_sha256']}`. Expires at epoch {spec['expires_epoch']}.

One pinned-key SSH capture as ama, using sudo Python through stdin. Read only
the explicit ntp.conf, installed leap service/timer, ntpleapfetch script and
installed ntpleapfetch/ntpd manuals, leapfile and leap-directory metadata.
Retain file content, hashes, ownership/modes, absence, links and read failures.
Read effective leap units, service/timer properties, 60 current-boot leap-unit
journal records, localhost NTP peers/system variables, and timeservice state
before and after collection. Reject a changed boot before collection.

No ntpleapfetch execution, download, network probe beyond SSH/local ntpq,
leapfile write, service/timer change, package action, clock adjustment, restart,
reboot or target staging. SSH/sudo and ntpq may produce ordinary logs/counters.
No credentials, environment or control-key files are captured. No recovery is
needed because this inspection changes no target configuration.

Reuse the tested bounded SSH/file collector: 10 seconds and 1 MiB per command
stream/file; 180-second total remote deadline, 210-second SSH deadline and
16 MiB per SSH stream. Register locally before connecting; retain partial output.
Never retry a consumed or uncertain capture. Capture completion is not approval
of the installed command, leapfile validity, reload behavior or timer activation.
Review those findings before preparing a separate activation bundle.

The flat archive contains repository code/tests and selected baseline data;
no historical executable is loaded and no prior archive is embedded.

After approval of this archive's SHA-256, run from the repository root:
`python3 -I -B ntpsec/scripts/run-leap-inspection.py execute --bundle ABSOLUTE_BUNDLE --sha256 APPROVED_SHA256`
'''


def prepare(bundle, digest):
    raw = helper.private(bundle, 4*helper.LIMIT)
    if helper.sha(raw) != digest: raise ValueError('approved archive digest mismatch')
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        members = archive.getmembers(); names = set(PATHS) | {'spec.json', 'review.md', 'baseline.json', 'known_hosts'}
        if (len(members) != len(names) or {m.name for m in members} != names
                or any(not m.isfile() or m.size > helper.LIMIT for m in members)):
            raise ValueError('closed flat inspection archive required')
        files = {m.name: archive.extractfile(m).read() for m in members}
    spec = json.loads(files['spec.json'])
    if (spec['schema'] != 1 or spec['purpose'] != 'leap-inspection' or spec['hostname'] != 'j2-svntp1'
            or not re.fullmatch(r'[a-z][a-z0-9-]{0,47}', spec['operation_id'])
            or not re.fullmatch(r'[a-f0-9-]{36}', spec['boot_id'])
            or spec['members'] != {n: helper.sha(files[n]) for n in set(PATHS) | {'baseline.json', 'known_hosts'}}
            or files['review.md'] != review(spec).encode()
            or not spec['prepared_epoch']-300 <= time.time() < spec['expires_epoch']
            or not 0 < spec['expires_epoch']-spec['prepared_epoch'] <= 86400):
        raise ValueError('inspection input binding/window')
    for name, path in PATHS.items():
        if files[name] != (ROOT/path).read_bytes(): raise ValueError('current repository input drift')
    for name in ('spec.json', 'review.md', 'known_hosts'):
        if helper.private(bundle.parent/name) != files[name]: raise ValueError('local approval input drift')
    return spec, files


def seal(args):
    client = load(ROOT/'scripts/run-client-acceptance.py')
    old, _ = client.prepare(args.client_dir/'client-native-discovery.tar', args.client_sha256)
    result_raw = helper.private(args.client_dir/'result.json'); result = json.loads(result_raw)
    if (not result.get('client_accepted') or result.get('error')
            or result['bundle_sha256'] != args.client_sha256
            or result['spec_sha256'] != helper.sha(helper.private(args.client_dir/'spec.json'))
            or result['checks'] != dict.fromkeys(('ipv4', 'ipv6', 'mdns', 'queries_denied'), True)):
        raise ValueError('accepted client prerequisite required')
    boot_runner = load(ROOT/'scripts/run-production-boot.py')
    boot_spec, boot_files = boot_runner.prepare(args.boot_dir/'production-boot.tar', old['monitor_sha256'])
    observed = helper.private(args.boot_dir/f"observe-{old['observation_number']}-outcome.json")
    observation = json.loads(observed); state = observation['state']
    if (helper.sha(observed) != old['observation_sha256'] or observation.get('error')
            or observation['bundle_sha256'] != old['monitor_sha256']
            or helper.sha(helper.private(args.boot_dir/'spec.json')) != old['monitor_spec_sha256']
            or not observation.get('timing_ready') or state['phase'] != 'monitoring'
            or old['hostname'] != boot_spec['hostname'] or old['endpoints'] != boot_spec['endpoints']
            or not state['health']['epoch'] <= result['epoch'] <= time.time()):
        raise ValueError('accepted postboot observation binding required')
    now = int(time.time())
    spec = {'schema': 1, 'purpose': 'leap-inspection', 'operation_id': args.operation_id,
            'hostname': old['hostname'], 'endpoints': old['endpoints'], 'host_key_alias': boot_spec['host_key_alias'],
            'boot_id': state['new_boot_id'], 'boot_sha256': old['monitor_sha256'],
            'client_sha256': args.client_sha256, 'prepared_epoch': now, 'expires_epoch': min(now+86400, old['expires_epoch'])}
    files = {n: (ROOT/p).read_bytes() for n, p in PATHS.items()}
    files['known_hosts'] = boot_files['known_hosts']
    files['baseline.json'] = helper.encoded({'client_result_sha256': helper.sha(result_raw),
        'observation_sha256': helper.sha(observed), 'unit': state['health']['unit'], 'pair': state['health']['pair']})
    spec['members'] = {n: helper.sha(raw) for n, raw in files.items()}
    files.update({'spec.json': helper.encoded(spec), 'review.md': review(spec).encode()})
    os.umask(0o077); args.output.mkdir(mode=0o700)
    for name in ('spec.json', 'review.md', 'known_hosts'): (args.output/name).write_bytes(files[name])
    bundle = args.output/BUNDLE
    with tarfile.open(bundle, 'w') as archive:
        for name, raw in sorted(files.items()):
            item = tarfile.TarInfo(name); item.size = len(raw); item.mode = 0o600
            archive.addfile(item, io.BytesIO(raw))
    digest = helper.sha(bundle.read_bytes()); prepare(bundle, digest)
    result = {'sha256': digest, 'bundle': str(bundle), 'expires_epoch': spec['expires_epoch'],
              'target_contact': False, 'execution_authorized': False}
    (args.output/'sealing.json').write_bytes(helper.encoded(result)); return result


def payload(spec, files):
    return ("__name__='sealed_leap'\n__file__='/sealed/runner.py'\n".encode()+files['runner.py']
        + b"\nnamespace={'__name__':'sealed_helper','__file__':'/sealed/helper.py'}\nexec(compile("
        + repr(files['helper.py']).encode()+b", '/sealed/helper.py', 'exec'),namespace)\nhelper=types.SimpleNamespace(**namespace)\n"
        + b'signal.signal(signal.SIGALRM,helper.expired)\nsignal.alarm(180)\nprint(json.dumps(collect('
        + repr(spec).encode()+b')))\n')


def execute(args):
    os.umask(0o077); root = args.bundle.absolute().parent
    spec, files = prepare(args.bundle.absolute(), args.sha256); request = payload(spec, files)
    argv = helper.ssh_argv(spec, root)
    with (root/'execution.json').open('xb') as stream:
        stream.write(helper.encoded({'sha256': args.sha256, 'argv': argv,
            'payload_sha256': helper.sha(request), 'epoch': int(time.time())})); stream.flush(); os.fsync(stream.fileno())
    try:
        result = helper.bounded(argv, timeout=210, limit=16*helper.LIMIT, payload=request, env=os.environ.copy())
    except OSError as error:
        result = {'returncode': None, 'error': str(error), 'stdout': '', 'stderr': ''}
    for name in ('stdout', 'stderr'): (root/(name+'.txt')).write_text(result.pop(name))
    result.update(bundle_sha256=args.sha256, capture_complete=False, production_accepted=False)
    if result.get('returncode') == 0 and not result.get('error'):
        try:
            capture = json.loads((root/'stdout.txt').read_text())
            if (capture['spec_sha256'] != helper.sha(helper.encoded(spec))
                    or capture['operation_id'] != spec['operation_id'] or capture['hostname'] != spec['hostname']):
                raise ValueError('capture identity binding')
            result['capture_complete'] = capture.get('capture_complete') is True
        except (ValueError, KeyError, TypeError) as error: result['error'] = str(error)
    (root/'result.json').write_bytes(helper.encoded(result)); return result


def main():
    global helper
    helper = load(ROOT/'scripts/run-production-inspection.py')
    parser = argparse.ArgumentParser(description=__doc__); sub = parser.add_subparsers(dest='action', required=True)
    p = sub.add_parser('seal'); p.add_argument('--boot-dir', type=Path, required=True)
    p.add_argument('--client-dir', type=Path, required=True); p.add_argument('--client-sha256', required=True)
    p.add_argument('--operation-id', required=True); p.add_argument('--output', type=Path, required=True)
    p = sub.add_parser('execute'); p.add_argument('--bundle', type=Path, required=True); p.add_argument('--sha256', required=True)
    args = parser.parse_args(); result = seal(args) if args.action == 'seal' else execute(args)
    print(json.dumps(result))
    if args.action == 'execute' and not result.get('capture_complete'): raise SystemExit(1)


if __name__ == '__main__': main()
