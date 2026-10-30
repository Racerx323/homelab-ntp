#!/usr/bin/python3
"""Read-only, sealed entry capture and fixed-window observation; no target staging."""
import argparse
import base64
import concurrent.futures
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shlex
import signal
import socket
import stat
import subprocess
import sys
import time
import types

CADENCE = 300
DURATION = 172800
SLOTS = 577
STREAMS = ('node', 'master', 'client4', 'client6')
CAP = 2 * 1024**3
PROTECTED_FILE_CAP = 64 * 1024**2

# Existing Munin native Storable interface, restricted to the sealed graph pairs.
LIMITS_DECODER = r"""
use strict; use warnings; use Storable qw(fd_retrieve); use JSON::PP;
use Munin::Master::Utils;
binmode STDIN; my $d=fd_retrieve(\*STDIN); my %out;
my $pairs=decode_json($ARGV[1]); die 'graph bound' if @$pairs>64;
for my $pair (@$pairs) {
 my ($host,$graph)=@$pair; my $n=munin_get_node($d,[$host,$host,$graph]);
 if (ref($n) ne 'HASH') {$out{"$host/$graph"}={missing=>JSON::PP::true}; next;}
 my %selected;
 for my $k (keys %$n) {
  my $v=$n->{$k};
  if ($ARGV[0] eq 'config' && $k eq 'contacts' && !ref($v)) {$selected{$k}=$v;}
  next unless ref($v) eq 'HASH'; my %field;
  for my $f ($ARGV[0] eq 'config' ? qw(label type warning critical unknown_limit) : qw(state)) {
   $field{$f}=$v->{$f} if exists($v->{$f}) && !ref($v->{$f});
  }
  $selected{$k}=\%field if keys %field;
 }
 $out{"$host/$graph"}=\%selected;
}
print encode_json(\%out);
"""


def encoded(value):
    return (json.dumps(value, sort_keys=True, allow_nan=False) + '\n').encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def require(value, message):
    if not value:
        raise ValueError(message)


def module(name, raw):
    m = types.ModuleType(name)
    m.__file__ = '/sealed/' + name + '.py'
    exec(compile(raw, m.__file__, 'exec'), m.__dict__)
    return m


def write_new(path, value):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as f:
        f.write(encoded(value)); f.flush(); os.fsync(f.fileno())
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try: os.fsync(directory)
    finally: os.close(directory)


def private(path):
    require(path.is_dir() and path.resolve() == path.absolute(), 'direct output directory required')
    st = path.stat()
    require(st.st_uid == os.getuid() and not st.st_mode & 0o077, 'private owner directory required')


def check(bundle, expected):
    private(bundle)
    raw = (bundle/'manifest.json').read_bytes()
    require(digest(raw) == expected, 'manifest approval mismatch')
    manifest = json.loads(raw)
    require(manifest['execution_ready'] is True, 'not executable')
    for name, record in manifest['files'].items():
        require(re.fullmatch(r'[A-Za-z0-9_.-]+', name), 'unsafe sealed name')
        p = bundle/name
        require(p.is_file() and not p.is_symlink(), 'regular sealed input required')
        raw = p.read_bytes()
        require(len(raw) == record['bytes'] and digest(raw) == record['sha256'], 'sealed input drift: '+name)
    spec = json.loads((bundle/'spec.json').read_text())
    require(spec['duration_seconds'] == DURATION and spec['cadence_seconds'] == CADENCE, 'closed schedule')
    require(spec['node']['hostname'] == 'j2-svntp1' and spec['master']['hostname'] == 'J1-SVMF', 'closed targets')
    return spec


def emit(key, data):
    print(json.dumps({'key': key, 'data': data}, allow_nan=False), flush=True)


def protected_hash(path):
    """Hash bounded regular files without buffering installed binaries in memory."""
    path = Path(path)
    try:
        require(not any(p.is_symlink() for p in path.parents), 'indirect observation path')
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as stream:
            before = os.fstat(stream.fileno())
            require(stat.S_ISREG(before.st_mode), 'regular observation file required')
            require(before.st_size <= PROTECTED_FILE_CAP, 'protected file exceeds 64 MiB bound')
            result = hashlib.sha256(); total = 0
            while chunk := stream.read(1048576):
                total += len(chunk)
                require(total <= PROTECTED_FILE_CAP, 'protected file exceeds 64 MiB bound')
                result.update(chunk)
            after = os.fstat(stream.fileno())
            fields = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
            require(all(getattr(before, k) == getattr(after, k) for k in fields)
                    and total == before.st_size, 'protected file changed during read')
        return result.hexdigest()
    except (OSError, ValueError) as error:
        raise ValueError(f'protected file {path}: {error}') from error


def remote(role, rich, spec, sources, since):
    """Only this function runs on a target. Its helpers perform bounded reads."""
    h = module('helper', sources['helper.py']); o = module('munin', sources['munin.py']); o.h = h
    p = module('passive', sources['passive.py']); p.h = h
    def command(argv):
        r = h.bounded(argv, timeout=20, limit=1048576)
        require(r.get('returncode') == 0 and not r.get('error'), 'native command failed: '+repr(r))
        return r['stdout']
    def read(path, limit=65536):
        return o.read(path, limit)[0].decode()
    def identity():
        return {'host': socket.gethostname(), 'boot': read('/proc/sys/kernel/random/boot_id').strip()}
    before = identity(); emit('identity', before)
    require(before['host'] == spec[role]['hostname'] and os.geteuid() == 0, 'target identity/root mismatch')
    try:
        emit('manager', command(['/usr/bin/systemctl', 'show', '--property=RuntimeWatchdogUSec,RebootWatchdogUSec']))
        if role == 'node':
            value = json.loads(command(['/usr/bin/python3', '-I', '-B', '-c', sources['measure.py']]))
            checks = module('checks', sources['checks.py']).measurement_checks(value, spec['recipe'])
            checks['finite'] = all(math.isfinite(float(q['variables'][k])) for q in value['peers'] for k in ('offset', 'jitter'))
            emit('time', {'value': value, 'checks': checks})
            emit('services', p.state())
            emit('watchdog_owner', command(['/usr/bin/find', '/proc/1/fd', '-maxdepth', '1', '-type', 'l',
                  '-lname', '*watchdog*', '-printf', '%f %l\n']))
            emit('temperature', p.text_record('/sys/class/thermal/thermal_zone0/temp', True))
            emit('throttled', command(['/usr/bin/vcgencmd', 'get_throttled']))
            emit('capacity', {'bytes': command(['/usr/bin/df', '-P', '-B1', '/']),
                              'inodes': command(['/usr/bin/df', '-Pi', '/'])})
            if rich:
                for name, argv in p.COMMANDS.items():
                    emit(name, command(argv))
                emit('hardware', p.hardware())
                wifi = {'radio': command(['/usr/bin/nmcli', 'radio', 'all']),
                        'boot_directives': [line for line in read('/boot/firmware/config.txt').splitlines()
                                            if 'wifi' in line.lower()]}
                state_path = Path('/var/lib/NetworkManager/NetworkManager.state')
                wifi['saved_radio_state'] = ([line for line in read(str(state_path),4096).splitlines()
                                             if line.startswith('WirelessEnabled=')] if state_path.exists() else None)
                emit('wifi', wifi)
                trips = {}
                for i in range(16):
                    for suffix in ('temp', 'type'):
                        path = '/sys/class/thermal/thermal_zone0/trip_point_'+str(i)+'_'+suffix
                        if Path(path).exists(): trips[path] = p.text_record(path, True)
                emit('thermal_trips', trips)
                fields = p.NETWORK_FIELDS
                profiles = command(p.COMMANDS['network_profiles']).splitlines()
                require(len(profiles) <= 8, 'profile count bound')
                for line in profiles:
                    uuid = line.split(':', 1)[0]
                    require(re.fullmatch(r'[0-9a-f-]{36}', uuid), 'profile UUID')
                    emit('profile_'+uuid, command(['/usr/bin/nmcli', '-g', fields, 'connection', 'show', 'uuid', uuid]))
                emit('jobs', o.node({'producer_installed_epoch': spec['producer_installed_epoch']}, time.time()))
                emit('leap', {'service': command(['/usr/bin/systemctl', 'show', 'ntpleapfetch.service',
                      '--property=Result,ExecMainStatus,ExecMainStartTimestamp,ExecMainExitTimestamp']),
                    'listing': command(['/usr/bin/systemctl', 'list-timers', '--all', '--no-pager', 'ntpleapfetch.timer']),
                    'timer': command(['/usr/bin/systemctl', 'show', 'ntpleapfetch.timer',
                      '--property=ActiveState,LastTriggerUSec,NextElapseUSecRealtime,NextElapseUSecMonotonic']),
                    'file': read('/var/lib/ntpsec/leap-seconds.list')})
        else:
            ms = dict(spec['master_fields'])
            collection = o.master(ms, time.time())
            collection['local_log_cycles_advisory_only'] = True
            collection['canonical_time_evidence'] = 'cron_epochs and RRD epochs; local log timestamps cannot disambiguate DST'
            emit('collection', collection)
            emit('contact', o.contact_status())
            # Native Storable decode as munin. Select every declared graph, not a maintenance subset.
            pairs = [[host, graph] for host, graphs in ms['graphs'].items() for graph in graphs]
            code = LIMITS_DECODER
            for mode, path in [('config', '/var/lib/munin/datafile.storable'), ('limits', '/var/lib/munin/limits.storable')]:
                raw, meta = o.read(path, 4194304)
                import pwd
                require(meta['uid'] == pwd.getpwnam('munin').pw_uid and not meta['mode'] & 0o022
                        and meta['nlink'] == 1, 'unsafe native cache')
                r = h.bounded(['/usr/sbin/runuser', '-u', 'munin', '--', '/usr/bin/perl', '-e', code,
                               mode, json.dumps(pairs)], timeout=20, limit=1048576, payload=raw)
                require(r.get('returncode') == 0 and not r.get('error'), 'native cache decode failed')
                emit(mode, {'metadata': meta, 'selected': json.loads(r['stdout'])})
            emit('services', command(['/usr/bin/systemctl', 'show', 'cron.service', 'munin-node.service',
                  '--property=Id,ActiveState,SubState,InvocationID,NRestarts']))
            if rich:
                for name in ('addresses', 'routes4', 'routes6', 'network_runtime', 'listeners'):
                    emit(name, command(p.COMMANDS[name]))
        files = spec[role]['protected_files']
        emit('hashes', {f: protected_hash(f) for f in files})
        # A small overlapping interval each slot prevents relying on a two-day final journal tail.
        error_args = ['/usr/bin/journalctl', '--since=@'+str(int(since)), '--no-pager',
              '-o', 'json', '-n', '1001', '-p', 'err',
              '--output-fields=__CURSOR,__REALTIME_TIMESTAMP,_BOOT_ID,_SYSTEMD_UNIT,_EXE,_PID,PRIORITY,MESSAGE']
        if role == 'master':
            error_args += ['-u', 'cron.service', '-u', 'munin-node.service', '-u', 'apache2.service']
        errors = command(error_args)
        emit('errors', errors)
        require(len(errors.splitlines()) < 1001, 'journal record cap; coverage unavailable')
        after = identity(); emit('identity_after', after)
        require(before == after, 'boot changed within capture')
        emit('complete', True)
    except Exception as e:
        emit('failure', str(e)); raise


def parse_remote(raw):
    result = {}
    for line in raw.splitlines():
        row = json.loads(line)
        require(set(row) == {'key', 'data'} and row['key'] not in result, 'duplicate/invalid remote record')
        result[row['key']] = row['data']
    return result


def stream_record(bundle, output, name, argv, payload, timeout, limit):
    """Spool each pipe from launch; helper also retains bounded return/error evidence."""
    h = module('helper', (bundle/'helper.py').read_text())
    write_new(output/(name+'.launch.json'), {'argv': argv, 'epoch': time.time(), 'monotonic': time.monotonic()})
    handles = {k: open(output/(name+'.'+k), 'xb', buffering=0) for k in ('stdout', 'stderr')}
    for f in handles.values(): os.fchmod(f.fileno(), 0o600)
    result = None
    try:
        result = h.bounded(argv, timeout=timeout, limit=limit, payload=payload,
                           sink=lambda stream, data: handles[stream].write(data))
        return result
    finally:
        for f in handles.values(): os.fsync(f.fileno()); f.close()
        write_new(output/(name+'.result.json'), {
            'epoch': time.time(), 'returncode': None if result is None else result['returncode'],
            'error': 'interrupted' if result is None else result.get('error'),
            'stdout_sha256': digest((output/(name+'.stdout')).read_bytes()),
            'stderr_sha256': digest((output/(name+'.stderr')).read_bytes())})


def target_argv(bundle, spec, role):
    t = spec[role]
    return ['/usr/bin/ssh', '-F', '/dev/null', '-T', '-i', spec['identity_file'],
            *sum((['-o', x] for x in spec['ssh_options']), []),
            '-o', 'UserKnownHostsFile='+str(bundle/'known_hosts'),
            '-o', 'HostKeyAlias='+t['host_key_alias'], t['target'],
            'cd / && sudo -n -- /usr/bin/timeout --kill-after=2s 130s /usr/bin/python3 -I -B -']


def capture(bundle, spec, output, label, role, rich, since):
    start = time.time(); mono = time.monotonic()
    if role in ('node', 'master'):
        sources = {n: (bundle/n).read_text() for n in ('helper.py', 'passive.py', 'measure.py', 'checks.py', 'munin.py')}
        program = ('import types\nm=types.ModuleType("observer")\nexec('+repr((bundle/'observer.py').read_text())+',m.__dict__)\n'
                   'm.remote('+repr(role)+','+repr(rich)+','+repr(spec)+','+repr(sources)+','+repr(since)+')\n')
        r = stream_record(bundle, output, label+'-'+role, target_argv(bundle, spec, role), program.encode(), 140, 1048576)
        data = parse_remote(r['stdout']) if r['returncode'] == 0 and not r.get('error') else {}
        complete = data.get('complete') is True
    else:
        endpoint = spec['node']['endpoints'][0 if role == 'client4' else 1]
        # Reuse nonce/protocol checks. Boundary denial probes are explicit; regular slots are NTP only.
        program = ('import types,json\nm=types.ModuleType("client")\nexec('+repr((bundle/'client.py').read_text())+',m.__dict__)\n'
                   'print(json.dumps(m.client_ntp('+repr(endpoint)+',administrative='+repr(rich)+')))\n')
        r = stream_record(bundle, output, label+'-'+role, ['/usr/bin/python3', '-I', '-B', '-'], program.encode(), 20, 65536)
        data = json.loads(r['stdout']) if r['returncode'] == 0 and not r.get('error') else {}
        complete = bool(data)
    row = {'role': role, 'start_epoch': start, 'start_monotonic': mono, 'finished_epoch': time.time(),
           'complete': complete, 'recorded': r['returncode'] is not None, 'data': data, 'returncode': r['returncode'], 'error': r.get('error')}
    write_new(output/(label+'-'+role+'.json'), {k:v for k,v in row.items() if k != 'data'})
    return row


def parallel_capture(bundle, spec, output, label, rich, since):
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        jobs = {role: pool.submit(capture, bundle, spec, output, label, role, rich, since) for role in STREAMS}
        return {role: job.result() for role, job in jobs.items()}


def boundary(bundle, spec, output, label):
    deadline = time.monotonic()+90
    c = module('client', (bundle/'client.py').read_text())
    compare = module('compare', (bundle/'compare.py').read_text())
    mdns = spec['windows']
    queries = compare.queries(mdns, c.__dict__)
    value = base64.b64encode(encoded(dict(source_ipv4=mdns['source_ipv4'], queries=queries))).decode()
    script = (bundle/'windows.ps1').read_text()+'\nInvoke-MdnsCapture -SpecBase64 "'+value+'"\n'
    args = [mdns['executable'], '-NoProfile', '-NonInteractive', '-EncodedCommand',
            base64.b64encode(script.encode('utf-16-le')).decode()]
    r = stream_record(bundle, output, label+'-windows', args, None, 25, 1048576)
    require(r['returncode'] == 0 and not r.get('error'), 'Windows discovery failed')
    native = json.loads(r['stdout'].lstrip('\ufeff')); compare.decode(native, mdns, c.__dict__)
    require(native.get("matched") is True, "Windows discovery records do not match")
    for i, item in enumerate(spec['boundary_commands']):
        argv = [x.replace('{bundle}', str(bundle)) for x in item['argv']]
        remaining = deadline-time.monotonic()
        require(remaining > 0, 'boundary deadline')
        name = label+'-check'+str(i)
        r = stream_record(bundle, output, name, argv, None, min(25,remaining), 1048576)
        require(r['returncode'] == 0 and not r.get('error'), 'boundary check failed')
        if item['kind'] == 'dns':
            require(set(r['stdout'].strip().splitlines()) == set(item['expected_lines']), 'unexpected DNS answer')
        else:
            raw = (output/(name+'.stdout')).read_bytes()
            body, trailer = raw.rsplit(b'\nOBS09_HTTP:',1)
            require(trailer.strip().startswith(b'200:'), 'HTTPS status')
            if item['kind'] == 'png':
                require(body.startswith(b'\x89PNG\r\n\x1a\n') and b'image/png' in trailer, 'PNG signature/type')
            else:
                require(b'text/html' in trailer and b'j2-svntp1' in body.lower(), 'host HTML/type')


def rrd_membership(data):
    result = {}
    for host, graphs in data['collection']['rrd'].items():
        for graph, value in graphs.items():
            require('files' in value, 'RRD inventory unavailable')
            result[host+'/'+graph] = sorted(row['filename'] for row in value['files'])
    return result


def require_entry(rows):
    require(all(r['complete'] for r in rows.values()), 'incomplete entry')
    master = rows['master']['data']
    require(rrd_membership(master) and all(rrd_membership(master).values()), 'missing master graph')
    node = rows['node']['data']
    require(node['time']['checks'] and all(v is True for v in node['time']['checks'].values()), 'node not precision ready')
    require(node['throttled'].strip() == 'throttled=0x0', 'throttle/undervoltage indication')


def fingerprint(spec):
    p = Path(spec['identity_file']); st = p.stat()
    require(p.resolve() == p.absolute() and st.st_uid == os.getuid() and not st.st_mode & 0o077, 'unsafe SSH identity')
    r = subprocess.run(['/usr/bin/ssh-keygen', '-lf', str(p)], capture_output=True, timeout=5, check=True)
    require(r.stdout.decode().split()[1] == spec['identity_fingerprint'], 'SSH identity fingerprint changed')


def summarize(rows):
    summary = {}
    for role in STREAMS:
        stamps = [r['streams'][role]['start_monotonic'] for r in rows if not r.get('missing')
                  and role in r['streams'] and r['streams'][role]['recorded']
                  and 0 <= r['streams'][role]['start_monotonic']-r['due_monotonic'] <= 60]
        gaps = [b-a for a,b in zip(stamps, stamps[1:])]
        summary[role] = {'on_time': len(stamps), 'required': 572, 'max_gap': max(gaps, default=None),
                         'completeness_pass': len(stamps) >= 572 and bool(gaps) and max(gaps) <= 600
                             and len(rows) == SLOTS
                             and all(not row.get('missing') and role in row['streams']
                                     and row['streams'][role]['recorded']
                                     and 0 <= row['streams'][role]['start_monotonic']-row['due_monotonic'] <= 60
                                     for row in (rows[0], rows[-1]))}
    return {'streams': summary, 'acceptance': 'requires review of health, boundaries, gaps and all gates'}


def execute(bundle, output, expected, phase, grant):
    spec = check(bundle, expected); private(output); fingerprint(spec)
    require(time.time() <= spec['not_after_epoch'], 'execution scope expired')
    require(Path(spec['windows']['executable']).is_file(), 'Windows native executable missing')
    for argv in [t['argv'] for t in spec['boundary_commands']]:
        require(os.access(argv[0], os.X_OK), 'boundary executable missing')
    require(socket.gethostname() == spec['controller_hostname'], 'wrong controller')
    if phase == 'entry':
        require(not any(output.iterdir()), 'new empty output directory required')
        space = os.statvfs(output)
        require(space.f_bavail*space.f_frsize >= CAP+1024**3, 'controller free space below 3 GiB')
        write_new(output/'execution.json', {'manifest_sha256': expected, 'epoch': time.time(), 'phase': 'entry'})
        rows = parallel_capture(bundle, spec, output, 'entry', True, time.time()-300)
        boundary(bundle, spec, output, 'entry')
        require_entry(rows)
        write_new(output/'entry.json', {'manifest_sha256': expected, 'epoch': time.time(), 'streams': rows})
        return
    receipt = json.loads((output/'execution.json').read_text())
    require(receipt['manifest_sha256'] == expected, 'execution receipt mismatch')
    entry_raw = (output/'entry.json').read_bytes(); entry = json.loads(entry_raw)
    require(grant.is_file() and not grant.is_symlink() and grant.resolve() == grant.absolute(), 'direct grant required')
    gst = grant.stat()
    require(gst.st_uid == os.getuid() and not gst.st_mode & 0o077, 'private operator grant required')
    g = json.loads(grant.read_text())
    require(g['manifest_sha256'] == expected and g['entry_sha256'] == digest(entry_raw), 'entry grant mismatch')
    required = ('identity_configuration','wifi_hardware','native_time','master_fields_freshness_limits',
                'jobs_leap_deadline','client_dns_discovery','webmin_both_families','controller_capacity_awake',
                'journal_dispositions','obs02_storage_floors','thermal_trip_policy')
    require(set(g['checks']) == set(required) and all(v is True for v in g['checks'].values()), 'unresolved entry gate')
    require(isinstance(g.get('obs05_due_epoch'), (int,float)) and math.isfinite(g['obs05_due_epoch'])
            and g['obs05_due_epoch'] > entry['epoch']
            and g.get('obs05_followup_epoch') == g['obs05_due_epoch']+86400, 'concrete OBS05 deadline required')
    require(g['operator'] == 'Aaron' and entry['epoch'] <= g['epoch'] <= time.time()
            and time.time()-receipt['epoch'] <= 1800, 'stale entry/grant')
    require(entry['manifest_sha256'] == expected, 'entry manifest mismatch')
    write_new(output/'start.json', {'manifest_sha256': expected, 'entry_sha256': digest(entry_raw),
                                  'grant': g, 'epoch': time.time(), 'monotonic': time.monotonic()})
    start = json.loads((output/'start.json').read_text()); records = []
    reference = {role: entry['streams'][role]['data'] for role in STREAMS}
    try:
        for k in range(SLOTS):
            check(bundle, expected)
            require(time.time()-receipt['epoch'] < 176400, 'overall scope deadline')
            require(abs((time.time()-start['epoch'])-(time.monotonic()-start['monotonic'])) <= 2,
                    'controller wall clock stepped; stop for assessment')
            due = start['monotonic'] + k*CADENCE
            while time.monotonic() < due:
                time.sleep(max(0, min(30, due-time.monotonic())))
            require(sum(p.stat().st_size for p in output.iterdir() if p.is_file()) < CAP-64*1024**2, 'result capacity cap')
            record = {'slot': k, 'due_monotonic': due, 'streams': {}}
            if time.monotonic() > due+60:
                record['missing'] = True
            else:
                rows = parallel_capture(bundle, spec, output, 'slot-'+str(k).zfill(3), k in (0,288,576), time.time()-600)
                record['streams'] = {role: {key:value for key,value in row.items() if key != 'data'}
                                     for role,row in rows.items()}
                for role in ('node','master'):
                    row = rows[role]
                    require(row['returncode'] != 255, 'SSH authentication/transport failed; no retry')
                    require(row['complete'], 'incomplete target capture; stop for assessment')
                    require(row['data']['identity'] == reference[role]['identity'], 'boot/identity changed')
                    require(row['data']['hashes'] == reference[role]['hashes'], 'protected configuration changed')
                require(rrd_membership(rows['master']['data']) == rrd_membership(reference['master']),
                        'RRD field/device membership changed')
                require(rows['master']['data']['config']['selected'] == reference['master']['config']['selected'],
                        'master limits/configuration changed')
                services = rows['node']['data']['services']
                baseline = reference['node']['services']
                for unit in ('timeservice.service',):
                    current = dict(x.split('=',1) for x in services[unit]['stdout'].splitlines() if '=' in x)
                    previous = dict(x.split('=',1) for x in baseline[unit]['stdout'].splitlines() if '=' in x)
                    require(current.get('InvocationID') == previous.get('InvocationID'), 'time service restarted')
                for role in ('client4','client6'):
                    if rows[role]['complete']:
                        require(rows[role]['data']['local_address'] == reference[role]['local_address'], 'client source changed')
                if k in (0,576): boundary(bundle, spec, output, 'boundary-'+str(k))
            write_new(output/('slot-'+str(k).zfill(3)+'-summary.json'), record); records.append(record)
        write_new(output/'completion.json', summarize(records))
    finally:
        write_new(output/'terminal.json', {'epoch': time.time(), 'recorded_slots': len(records),
                                         'completed': (output/'completion.json').exists(), 'replay_permitted': False})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('check','entry','observe'))
    parser.add_argument('--bundle', required=True, type=Path)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--grant', type=Path)
    a = parser.parse_args()
    if a.phase == 'check':
        check(a.bundle, a.sha256); print('sealed inputs verified; no contact'); return
    require(a.output is not None and (a.phase != 'observe' or a.grant is not None), 'output/grant required')
    # SIGTERM follows the same partial-evidence cleanup as an attended interrupt.
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    try:
        execute(a.bundle, a.output, a.sha256, a.phase, a.grant)
    except BaseException as error:
        if a.output.is_dir():
            private(a.output)
            path = a.output/(a.phase+'-error.json')
            if not path.exists():
                write_new(path, {'epoch': time.time(), 'type': type(error).__name__,
                                 'error': str(error), 'replay_permitted': False})
        raise


if __name__ == '__main__':
    main()
