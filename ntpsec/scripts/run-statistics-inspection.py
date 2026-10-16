#!/usr/bin/python3
"""Seal a read-only statistics maintenance inventory; never run cleanup or plots."""
import argparse
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
SOURCES = {'runner.py': ROOT/'scripts/run-statistics-inspection.py',
           'helper.py': ROOT/'scripts/run-production-inspection.py',
           'tests.py': ROOT/'tests/test_statistics_inspection.py',
           'candidate': ROOT/'templates/ntpstats-retention.logrotate'}
h = None
PATTERN = re.compile(r'^(loopstats|peerstats|clockstats|protostats)(?:\.(\d{8})(\.gz)?)?$')
RELEVANT = re.compile(r'ntpstats|loopstats|peerstats|clockstats|protostats|ntpviz|logrotate', re.I)


def inventory(directory):
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError('statistics directory absent or indirect')
    entries = list(directory.iterdir())
    if len(entries) > 5000:
        raise ValueError('statistics file count bound exceeded')
    rows = []
    for p in sorted(entries):
        info = p.lstat()
        match = PATTERN.fullmatch(p.name)
        rows.append({'name': p.name, 'recognized': bool(match), 'date': match[2] if match else None,
                     'compressed': bool(match and match[3]), 'bytes': info.st_size,
                     'mtime': info.st_mtime, 'mode': stat.S_IMODE(info.st_mode),
                     'uid': info.st_uid, 'gid': info.st_gid, 'inode': info.st_ino,
                     'device': info.st_dev, 'links': info.st_nlink,
                     'regular': stat.S_ISREG(info.st_mode), 'symlink': stat.S_ISLNK(info.st_mode)})
    fs = os.statvfs(directory)
    meta = directory.stat()
    return {'files': rows, 'directory': {'uid': meta.st_uid, 'gid': meta.st_gid, 'mode': stat.S_IMODE(meta.st_mode)},
            'available_bytes': fs.f_bavail*fs.f_frsize,
            'total_bytes': fs.f_blocks*fs.f_frsize, 'available_inodes': fs.f_favail}


def maintenance_files():
    paths = {Path('/etc/logrotate.conf'), Path('/etc/crontab')}
    for directory in ('/etc/logrotate.d', '/etc/cron.d', '/etc/cron.daily', '/etc/cron.hourly',
                      '/etc/cron.weekly', '/etc/cron.monthly', '/var/spool/cron/crontabs',
                      '/etc/systemd/system', '/usr/lib/systemd/system'):
        root = Path(directory)
        if root.is_dir():
            paths.update(root.iterdir())
    if len(paths) > 3000:
        raise ValueError('maintenance file count bound exceeded')
    result = []
    for p in sorted(paths):
        if not p.exists() or p.is_symlink() or not p.is_file():
            continue
        if p.stat().st_size > h.LIMIT:
            raise ValueError('maintenance input too large: '+str(p))
        raw = p.read_bytes()
        lines = [line for line in raw.decode('utf-8', errors='replace').splitlines() if RELEVANT.search(line)]
        if lines or 'logrotate' in str(p):
            result.append({'path': str(p), 'record': h.file_record(str(p)), 'relevant_lines': lines})
    return result


def writer_snapshot(proc=Path('/proc'), statsdir='/var/log/ntpstats', inodes=()):
    """Inspect descriptors, never process arguments, environments or log contents."""
    processes = sorted(p for p in proc.iterdir() if p.name.isdigit())
    if len(processes) > 4096:
        raise ValueError('process count bound exceeded')
    result = {'processes': [], 'races': [], 'descriptor_count': 0}
    for p in processes:
        try:
            before = (p/'stat').read_text()
            start = before.rsplit(')', 1)[1].split()[19]
            comm = (p/'comm').read_text().strip()
            matches = []
            for fd in (p/'fd').iterdir():
                result['descriptor_count'] += 1
                if result['descriptor_count'] > 65536:
                    raise ValueError('descriptor count bound exceeded')
                try:
                    target = os.readlink(fd)
                    meta = fd.stat()
                    if (meta.st_dev, meta.st_ino) not in inodes and not target.startswith(statsdir+'/'):
                        continue
                    info = (p/'fdinfo'/fd.name).read_text()
                    flags = next(line.split()[1] for line in info.splitlines() if line.startswith('flags:'))
                    matches.append({'fd': fd.name, 'path': target, 'device': meta.st_dev,
                                    'inode': meta.st_ino, 'flags_octal': flags,
                                    'writable': int(flags, 8) & os.O_ACCMODE in (os.O_WRONLY, os.O_RDWR)})
                except FileNotFoundError:
                    result['races'].append(str(fd))
            if matches or comm == 'ntpd':
                after = (p/'stat').read_text().rsplit(')', 1)[1].split()[19]
                if start != after:
                    raise ValueError('process identity changed during snapshot')
                result['processes'].append({'pid': p.name, 'comm': comm, 'start_ticks': start,
                                            'uid': p.stat().st_uid, 'exe': os.readlink(p/'exe'),
                                            'descriptors': matches})
        except FileNotFoundError:
            result['races'].append(str(p))
    return result


def maintenance_followup():
    # Only these configuration trees are traversed; no referenced script executes.
    roots = ['/etc/logrotate.d', '/etc/cron.d', '/etc/cron.daily', '/etc/cron.hourly',
             '/etc/cron.weekly', '/etc/cron.monthly', '/var/spool/cron/crontabs',
             '/etc/systemd/system', '/run/systemd/system', '/usr/lib/systemd/system',
             '/etc/systemd/user', '/usr/lib/systemd/user']
    paths = {Path('/etc/logrotate.conf'), Path('/etc/crontab')}
    for root in roots:
        for parent, dirs, files in os.walk(root, followlinks=False):
            paths.update(Path(parent)/n for n in dirs+files)
            if len(paths) > 6000:
                raise ValueError('maintenance traversal bound exceeded')
    result = {'files': [], 'indirect': [], 'references': [],
              'coverage_limits': ['Per-user home configuration and dynamically generated jobs not inspected.',
                                  'Referenced local scripts retain relevant lines only, without recursive traversal.']}
    total = 0
    for p in sorted(paths):
        if p.is_symlink():
            result['indirect'].append({'path': str(p), 'target': os.readlink(p)})
            continue
        if not p.is_file():
            continue
        if p.stat().st_size > h.LIMIT:
            raise ValueError('maintenance input too large: '+str(p))
        raw = p.read_bytes(); total += len(raw)
        if total > 32*h.LIMIT:
            raise ValueError('maintenance byte bound exceeded')
        lines = raw.decode('utf-8', errors='replace').splitlines()
        relevant = [line for line in lines if RELEVANT.search(line)]
        full = str(p) in ('/etc/logrotate.conf', '/etc/cron.daily/logrotate') or str(p).startswith('/etc/logrotate.d/')
        if full or relevant:
            result['files'].append({'path': str(p), 'record': h.file_record(str(p)),
                                    'lines': lines if full else relevant, 'complete_content': full})
            for line in lines:
                if full and line.strip().startswith('include '):
                    result['references'].append({'source': str(p), 'include': line.strip()[8:],
                                                 'status': 'compare with captured paths; unresolved unless captured'})
                elif RELEVANT.search(line):
                    for target in re.findall(r'/[A-Za-z0-9_./@+-]+', line):
                        result['references'].append({'source': str(p), 'path': target,
                                                     'status': 'reference only; script content not captured'})
    scripts = sorted({v['path'] for v in result['references'] if 'path' in v
                      and v['path'].startswith(('/usr/local/sbin/', '/usr/local/bin/'))})
    if len(scripts) > 100:
        raise ValueError('referenced script count bound exceeded')
    result['referenced_scripts'] = []
    for name in scripts:
        p = Path(name)
        row = {'path': name, 'status': 'unresolved: absent, indirect or nonregular'}
        if p.resolve() == p and p.is_file():
            if p.stat().st_size > h.LIMIT:
                raise ValueError('referenced script too large: '+name)
            raw = p.read_bytes(); total += len(raw)
            if total > 32*h.LIMIT:
                raise ValueError('maintenance byte bound exceeded')
            row.update(record=h.file_record(name),
                       relevant_lines=[line for line in raw.decode('utf-8', errors='replace').splitlines()
                                       if RELEVANT.search(line)],
                       status='partial: relevant lines only; no recursive script traversal')
        result['referenced_scripts'].append(row)
    return result


def collect(spec):
    result = {'operation_id': spec['operation_id'], 'spec_sha256': h.sha(h.encoded(spec)),
              'capture_complete': False, 'commands': {}, 'deployment_accepted': False}
    def command(key, argv, allowed=(0,)):
        row = h.bounded(argv, timeout=20, env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LC_ALL': 'C'})
        result['commands'][key] = row
        if row.get('error') or row.get('returncode') not in allowed:
            raise ValueError('command capture failed: '+key)
        return row['stdout']
    def continuity(label):
        boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        text = command(label, ['/usr/bin/systemctl', 'show', 'timeservice.service',
                        '--property=LoadState,MainPID,InvocationID,NRestarts,ActiveState,SubState,UnitFileState'])
        identity = dict(line.split('=', 1) for line in text.splitlines() if '=' in line)
        if boot != spec['boot_id'] or any(identity.get(k) != v for k, v in spec['service_identity'].items()):
            raise ValueError('boot/NTP identity changed')
    try:
        if os.geteuid() != 0 or socket.gethostname().split('.')[0] != 'j2-svntp1':
            raise ValueError('target/root mismatch')
        continuity('ntp_before')
        result['observed_epoch'] = int(time.time())
        result['statistics'] = inventory(Path('/var/log/ntpstats'))
        result['configuration'] = h.file_record('/etc/ntp.conf', content=True)
        result['maintenance'] = maintenance_files()
        if spec.get('followup'):
            result['maintenance_followup'] = maintenance_followup()
        inodes = {(v['device'], v['inode']) for v in result['statistics']['files']}
        result['ntp_open_statistics'] = []
        pid = spec['service_identity']['MainPID']
        for fd in Path('/proc', pid, 'fd').iterdir():
            try:
                meta = fd.stat()
                if (meta.st_dev, meta.st_ino) in inodes:
                    result['ntp_open_statistics'].append({'fd': fd.name, 'path': os.readlink(fd), 'inode': meta.st_ino, 'device': meta.st_dev})
            except FileNotFoundError:
                continue
        if spec.get('followup'):
            result['writers_before'] = writer_snapshot(inodes=inodes)
            command('timeservice_definition', ['/usr/bin/systemctl', 'cat', 'timeservice.service'])
        command('packages', ['/usr/bin/dpkg-query', '-W', '-f=${binary:Package}\t${Version}\t${db:Status-Abbrev}\n',
                             'logrotate', 'findutils', 'gnuplot', 'gnuplot-nox', 'ntpsec-ntpviz', 'python3-ntp'], (0, 1))
        command('logrotate_version', ['/usr/sbin/logrotate', '--version'])
        command('find_version', ['/usr/bin/find', '--version'])
        command('timers', ['/usr/bin/systemctl', 'list-timers', '--all', '--no-pager'])
        command('logrotate_units', ['/usr/bin/systemctl', 'cat', 'logrotate.timer', 'logrotate.service'], (0, 1))
        command('scheduler', ['/usr/bin/systemctl', 'show', 'cron.service', 'logrotate.timer',
                              '--property=LoadState,ActiveState,SubState,UnitFileState,LastTriggerUSec,NextElapseUSecRealtime'])
        command('storage', ['/usr/bin/findmnt', '-T', '/var/log/ntpstats', '--json', '--output', 'TARGET,SOURCE,FSTYPE,OPTIONS'])
        result['ntpviz_paths'] = {p: h.file_record(p) for p in ('/usr/local/bin/ntpviz', '/usr/bin/ntpviz', '/usr/bin/gnuplot')}
        if spec.get('followup'):
            result['writers_after'] = writer_snapshot(inodes=inodes)
        continuity('ntp_after')
        result['capture_complete'] = True
    except Exception as error:
        result['error'] = str(error)
    return result


def review(spec):
    extra = '''
Follow-up scope: recognize protostats metadata; inspect up to 4096 processes and
65536 descriptors per snapshot, twice. Retain ntpd identity and every statistics
descriptor's path/inode/access flags, including deleted paths. No process arguments
or environments. Empty snapshots do not prove absence of a writer. Record races;
compare process start identities across snapshots before attributing writers.
Read timeservice's unit definition. Traverse bounded system configuration trees
(including nested drop-ins, runtime units and system-wide user-unit definitions),
without following symlinks; report indirect paths and referenced scripts/includes.
Read complete /etc/logrotate.conf, regular files under /etc/logrotate.d and
/etc/cron.daily/logrotate; other files retain relevant lines only. Limit 6000 paths,
1 MiB per file and 32 MiB total input. Per-user home jobs and uncaptured referenced
scripts remain explicit coverage gaps. At most 100 referenced regular local scripts
under /usr/local/bin or /usr/local/sbin retain hashes and relevant lines only; reject
indirect paths and never execute or recursively traverse their references.
The sealed cleanup candidate remains three-stream and is not executed. Extend it
only after writer/active-file findings support a fresh four-stream review.
''' if spec.get('followup') else ''
    return f'''# Read-only statistics-retention inspection

Target ama@10.1.0.51 (j2-svntp1), SSH alias 10.1.0.137.
Operation {spec['operation_id']}; expires epoch {spec['expires_epoch']}.
Require accepted boot {spec['boot_id']} and unchanged NTP identity before/after.
{extra}

Inspect /var/log/ntpstats entries by metadata only (maximum 5000): names, sizes,
timestamps, ownership, modes, inode/link identities, filesystem capacity/inodes.
Read the active NTP configuration and this NTP process's matching open descriptors.
Read bounded top-level logrotate, cron and systemd configuration files; retain
only relevant maintenance lines and metadata/hashes. Inspect systemd timers,
cron/logrotate unit state and logrotate unit/drop-in definitions. This is an
inventory, not exhaustive proof of absence: referenced scripts, indirect files,
unrelated unit names and user timers may require follow-up.

Capture installed package/tool versions, filesystem backing and ntpviz/gnuplot
path metadata. No statistics contents, raw receiver data, process environments,
credentials, SMTP, browser probes, package refresh/install, cleanup, compression,
plot generation, configuration changes or service/reboot actions. No plotting-host
contact. Commands are bounded to 20 seconds each; overall deadline 240 seconds.
Store both streams and result privately; partial failures remain explicit.

Use completed daily-file sizes to estimate storage demand, distinguishing
compressed files and partial days. A single snapshot does not measure live growth;
choose the storage alert threshold and any second sample after reviewing findings.
Compare observed names/links/ownership and installed tools with the sealed candidate;
do not execute logrotate or find cleanup, even in force mode. No live deletion
preview or deployment acceptance is claimed from filename metadata alone.

The selected architecture requires viewable ntpviz plots on a separate always-on
host with a private dashboard. Host identity, collection/refresh cadence, access
control and publication route still need review. This inspection does not deploy it.

After approval bound to sealing.json's SHA-256, from /home/aaron/code/homelab-ntp:

```text
python3 -I -B ntpsec/scripts/run-statistics-inspection.py execute --directory OUTPUT --sha256 APPROVED_SHA256
```

OUTPUT is this review directory. One execution; retain receipts, no automatic retry.
No mutation rollback is needed because no persistent target change is requested.
Normal SSH/sudo audit records and file access metadata may change.
'''


def seal(args):
    d = args.baseline
    receipt = json.loads(h.private(d/'result.json'))
    raw = h.private(d/'stdout.txt', 24*h.LIMIT)
    capture = json.loads(raw)
    followup = getattr(args, 'followup', False)
    archive = h.private(d/('inspection.tar' if followup else 'mail-reporting.tar'), 16*h.LIMIT)
    key = 'capture_complete' if followup else 'accepted'
    if receipt.get(key) is not True or capture.get(key) is not True or h.sha(archive) != receipt['bundle_sha256']:
        raise ValueError('accepted baseline required')
    with tarfile.open(fileobj=io.BytesIO(archive)) as t:
        old = json.loads(t.extractfile('spec.json').read())
        known = t.extractfile('known_hosts').read()
    if capture['spec_sha256'] != h.sha(h.encoded(old)) or capture['operation_id'] != old['operation_id']:
        raise ValueError('baseline binding')
    now = int(time.time())
    spec = {'operation_id': args.output.name, 'boot_id': old['boot_id'], 'service_identity': old['service_identity'],
            'followup': followup, 'prepared_epoch': now, 'expires_epoch': now+86400, 'baseline_sha256': h.sha(raw)}
    files = {n: p.read_bytes() for n, p in SOURCES.items()}
    files['known_hosts'] = known
    spec['members'] = {n: h.sha(v) for n, v in files.items()}
    files.update({'spec.json': h.encoded(spec), 'review.md': review(spec).encode()})
    os.umask(0o077)
    args.output.mkdir(mode=0o700)
    for n, v in files.items(): (args.output/n).write_bytes(v)
    with tarfile.open(args.output/'inspection.tar', 'w') as t:
        for n, v in sorted(files.items()):
            info = tarfile.TarInfo(n); info.size = len(v); info.mode = 0o600
            t.addfile(info, io.BytesIO(v))
    digest = h.sha((args.output/'inspection.tar').read_bytes())
    prepare(args.output, digest)
    output = {'sha256': digest, 'expires_epoch': spec['expires_epoch'], 'target_contact': False}
    (args.output/'sealing.json').write_bytes(h.encoded(output))
    return output


def prepare(directory, digest):
    raw = h.private(directory/'inspection.tar', 8*h.LIMIT)
    if h.sha(raw) != digest: raise ValueError('archive mismatch')
    with tarfile.open(fileobj=io.BytesIO(raw)) as t:
        members = t.getmembers()
        expected = set(SOURCES) | {'known_hosts', 'spec.json', 'review.md'}
        if len(members) != len(expected) or {m.name for m in members} != expected or any(not m.isfile() or m.size > h.LIMIT for m in members):
            raise ValueError('closed archive required')
        files = {m.name: t.extractfile(m).read() for m in members}
    spec = json.loads(files['spec.json'])
    if spec['members'] != {n: h.sha(files[n]) for n in set(SOURCES) | {'known_hosts'}}:
        raise ValueError('member binding')
    for n, p in SOURCES.items():
        if files[n] != p.read_bytes(): raise ValueError('source drift')
    for n in ('known_hosts', 'spec.json', 'review.md'):
        if h.private(directory/n) != files[n]: raise ValueError('review drift')
    if files['review.md'] != review(spec).encode(): raise ValueError('rendered review drift')
    if not re.fullmatch(r'[a-z0-9-]{1,64}', spec['operation_id']) or not spec['prepared_epoch']-300 <= time.time() < spec['expires_epoch']-270:
        raise ValueError('operation identity or validity window')
    return spec, files


def execute(args):
    os.umask(0o077)
    d = args.directory.absolute(); spec, files = prepare(d, args.sha256)
    payload = b"__name__='sealed_statistics'\n__file__='/sealed/runner.py'\n"+files['runner.py']
    payload += b"\nns={'__name__':'helper','__file__':'/sealed/helper.py'}\nexec(compile("+repr(files['helper.py']).encode()+b",ns['__file__'],'exec'),ns)\nh=types.SimpleNamespace(**ns)\n"
    payload += b'signal.signal(signal.SIGALRM,h.expired)\nsignal.alarm(240)\nprint(json.dumps(collect('+repr(spec).encode()+b')))\n'
    argv = h.ssh_argv({'endpoints': ['10.1.0.51'], 'host_key_alias': '10.1.0.137'}, d)
    with (d/'execution.json').open('xb') as f:
        f.write(h.encoded({'sha256': args.sha256, 'argv': argv, 'epoch': int(time.time()), 'payload_sha256': h.sha(payload)})); f.flush(); os.fsync(f.fileno())
    result = h.bounded(argv, timeout=270, limit=16*h.LIMIT, payload=payload, env=os.environ.copy())
    for n in ('stdout', 'stderr'): (d/(n+'.txt')).write_text(result.pop(n))
    result.update(bundle_sha256=args.sha256, capture_complete=False)
    if result.get('returncode') == 0 and not result.get('error'):
        try:
            state = json.loads((d/'stdout.txt').read_text())
            if state['operation_id'] != spec['operation_id'] or state['spec_sha256'] != h.sha(h.encoded(spec)): raise ValueError('result binding')
            result['capture_complete'] = state.get('capture_complete') is True
        except (ValueError, KeyError, TypeError) as error: result['error'] = str(error)
    (d/'result.json').write_bytes(h.encoded(result))
    return result


def main():
    global h
    module = importlib.util.spec_from_file_location('helper', SOURCES['helper.py'])
    h = importlib.util.module_from_spec(module); module.loader.exec_module(h)
    p = argparse.ArgumentParser(description=__doc__); sub = p.add_subparsers(dest='action', required=True)
    s = sub.add_parser('seal'); s.add_argument('--baseline', type=Path, required=True); s.add_argument('--output', type=Path, required=True)
    s.add_argument('--followup', action='store_true')
    e = sub.add_parser('execute'); e.add_argument('--directory', type=Path, required=True); e.add_argument('--sha256', required=True)
    args = p.parse_args(); result = seal(args) if args.action == 'seal' else execute(args)
    print(json.dumps(result))
    if args.action == 'execute' and not result['capture_complete']: raise SystemExit(1)


if __name__ == '__main__': main()
