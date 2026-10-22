#!/usr/bin/python3
"""Seal two bounded read-only Munin readiness scopes; never install, poll or notify."""
import argparse
import base64
from datetime import datetime
import gzip
import hashlib
import itertools
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
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
FLEET = ROOT.parent.parent/'homelab-monitoring-observability/Munin'
INVENTORY = ROOT.parent.parent/'homelab-server-configs/inventory/prod/hosts'
SOURCES = {
    'runner.py': ROOT/'scripts/run-munin-readiness.py',
    'support.py': ROOT/'scripts/run-munin-prerequisites.py',
    'helper.py': ROOT/'scripts/run-production-inspection.py',
    'tests.py': ROOT/'tests/test_munin_readiness.py',
    'package-review.json': ROOT/'configs/munin-package-review.json',
    'profile.json': FLEET/'node/profiles/ntp/profile.json',
    'node-inventory.yaml': INVENTORY/'j2-svntp1.yaml',
    'master-inventory.yaml': INVENTORY/'svmf.yaml',
    'node-review.md': FLEET/'docs/ntp-node-installation-review.md',
    'jobs-review.md': ROOT/'docs/monitoring-job-success-review.md',
    'master-review.md': FLEET/'docs/ntp-master-acceptance-review.md',
    'qualification.py': FLEET/'scripts/qualify_master.py',
    'qualification-tests.py': FLEET/'tests/test_master_qualification.py',
    'repository-master.conf': FLEET/'master/configs/munin.conf',
    'contact-example.conf': FLEET/'master/configs/j2-svntp1.conf.example',
    'config-review.md': FLEET/'docs/master-config-review.md',
    'baseline-sync.py': FLEET/'scripts/sync_master_baseline.py',
    'baseline-tests.py': FLEET/'tests/test_master_baseline.py',
    'configuration-lifecycle.md': FLEET/'master/configuration-lifecycle.md',
}
TARGETS = {'node': ('10.1.0.51', 'ama', '10.1.0.137', 'j2-svntp1'),
           'master': ('10.1.3.83', 'pi', 'svmf.local.theama.co', 'J1-SVMF'),
           'master-config': ('10.1.3.83', 'pi', 'svmf.local.theama.co', 'J1-SVMF'),
           'master-baseline': ('10.1.3.83', 'pi', 'svmf.local.theama.co', 'J1-SVMF')}
SERVICE_FIELDS = 'LoadState,ActiveState,SubState,MainPID,InvocationID,NRestarts,UnitFileState,FragmentPath,DropInPaths'
NODE_FILES = ('/etc/ntp.conf', '/usr/local/bin/ntpq', '/usr/sbin/policy-rc.d',
    '/etc/munin/munin-node.conf', '/etc/systemd/system/munin-node.service.d/00-ntp-install.conf',
    '/etc/logrotate.d/ntpstats-retention', '/var/lib/ntpstats-retention/trigger',
    '/usr/local/sbin/needrestart.sh', '/etc/cron.d/needrestart_check',
    '/var/lib/ntpstats-retention/last-success.json', '/var/lib/needrestart-reporting/last-success.json',
    '/run/lock/needrestart-check.lock', '/etc/localtime', '/etc/timezone',
    '/var/lib/logrotate/status', '/etc/logrotate.conf')
h = None
support = None
frozen_inputs = None


def record(path, metadata_only=False):
    """No link traversal, device reads, raw config or secret bytes in output."""
    path = Path(path)
    try:
        if any(p.is_symlink() for p in path.parents):
            return {'indirect_ancestor': True}
        info = path.lstat()
        meta = {'mode': stat.S_IMODE(info.st_mode), 'uid': info.st_uid, 'gid': info.st_gid,
                'size': info.st_size, 'inode': info.st_ino, 'device': info.st_dev, 'mtime_ns': info.st_mtime_ns}
        if stat.S_ISDIR(info.st_mode):
            return dict(meta, directory=True)
        if not stat.S_ISREG(info.st_mode):
            return dict(meta, indirect_or_special=True)
        return meta if metadata_only else h.file_record(path)
    except FileNotFoundError:
        return {'missing': True}


def metadata_directory(path, limit=512):
    p = Path(path)
    meta = record(p, metadata_only=True)
    if not meta.get('directory'):
        return {'directory': meta}
    entries = list(itertools.islice(p.iterdir(), limit+1))
    if len(entries) > limit:
        return {'directory': meta, 'count_at_least': len(entries), 'over_limit': True}
    return {'directory': meta, 'entries': {v.name: record(v, metadata_only=True) for v in sorted(entries)}}


def cron(path):
    meta = record(path)
    if 'sha256' not in meta:
        return {'record': meta}
    raw = h.file_record(path, content=True)
    if raw.get('changed_during_read') or 'base64' not in raw:
        raise ValueError('unstable cron input')
    rows = support.cron_structure(base64.b64decode(raw['base64'], validate=True))
    return {'record': meta, 'schedule': rows, 'command_bodies_omitted': True}


def selected_statistics():
    row = h.file_record('/etc/ntp.conf', content=True)
    if row.get('changed_during_read') or 'base64' not in row:
        raise ValueError('stable NTP configuration required')
    text = base64.b64decode(row['base64'], validate=True).decode(errors='replace')
    return [line.strip() for line in text.splitlines()
            if re.fullmatch(r'\s*(?:statsdir|statistics|filegen) [A-Za-z0-9_./ -]+\s*', line)]


def producer_structure(path):
    meta = record(path)
    if 'sha256' not in meta:
        return {'record': meta}
    row = h.file_record(path, content=True)
    if row.get('changed_during_read') or 'base64' not in row:
        raise ValueError('unstable producer')
    raw = base64.b64decode(row['base64'], validate=True)
    markers = (b'firstaction', b'postrotate', b'/usr/bin/find', b'last-success.json',
               b'/usr/sbin/needrestart', b'/usr/sbin/sendmail', b'TEST_NOTIFICATION')
    return {'record': meta, 'markers': {key.decode(): key in raw for key in markers},
            'fixed_executable_references': sorted(set(re.findall(
                r'/(?:usr/(?:local/)?s?bin|s?bin)/[a-zA-Z0-9_.-]+', raw.decode(errors='replace'))))[:32]}


def success_record(path, job):
    meta = record(path)
    if 'sha256' not in meta:
        return {'record': meta, 'evidence': False}
    if meta['uid'] != 0 or meta['mode'] != 0o600 or meta['size'] > 4096:
        return {'record': meta, 'evidence': False, 'invalid_metadata': True}
    row = h.file_record(path, content=True)
    try:
        if row.get('changed_during_read'):
            raise ValueError('changed record')
        value = json.loads(base64.b64decode(row['base64'], validate=True))
        epoch = value.get('completed_epoch')
        import math
        valid = (value.get('schema') == 1 and value.get('job') == job and value.get('status') == 'success'
                 and type(epoch) in (int, float) and math.isfinite(epoch) and 0 < epoch <= time.time())
        return {'record': meta, 'evidence': valid, 'completed_epoch': epoch if valid else None}
    except (KeyError, ValueError, TypeError, AttributeError):
        return {'record': meta, 'evidence': False, 'invalid_format': True}


def installed_excerpt(path):
    """Fixed package source/manual paths only; never runtime contact configuration."""
    meta = record(path)
    if 'sha256' not in meta:
        return {'record': meta}
    row = h.file_record(path, content=True)
    if row.get('changed_during_read') or 'base64' not in row:
        raise ValueError('unstable package documentation')
    raw = base64.b64decode(row['base64'], validate=True)
    if str(path).endswith('.gz'):
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
            raw = stream.read(262145)
    if len(raw) > 262144:
        return {'record': meta, 'excerpt_unavailable': 'decoded size bound'}
    pattern = r'(?i)\b(address|multihomed|multigraph|use_node_name|update_rate|unknown_limit|IO::Socket|inet6|AF_INET6|getaddrinfo|munin-update|munin-limits)\b'
    rows = [{'line': n, 'text': line[:256]} for n, line in enumerate(raw.decode(errors='replace').splitlines(), 1)
            if re.search(pattern, line)]
    return {'record': meta, 'excerpts': rows[:80], 'matches': len(rows)}


def collect(spec):
    result = {'operation_id': spec['operation_id'], 'spec_sha256': h.sha(h.encoded(spec)),
              'capture_complete': False, 'target_mutation': False, 'commands': {},
              'installation_accepted': False, 'polling_accepted': False, 'delivery_verified': False}

    def cmd(key, argv, allowed=(0,)):
        row = h.bounded(argv, timeout=25, limit=h.LIMIT,
                        env={'PATH': '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
                             'LC_ALL': 'C', 'PYTHONDONTWRITEBYTECODE': '1'})
        for field in ('stdout', 'stderr'):
            row[field] = support.safe_url_text(row.get(field, ''))
        result['commands'][key] = row
        if row.get('error') or row.get('returncode') not in allowed:
            raise ValueError('required read-only command failed: '+key)
        return row['stdout']

    def continuity(label):
        if (os.geteuid() != 0 or socket.gethostname() != spec['hostname']
                or Path('/proc/sys/kernel/random/boot_id').read_text().strip() != spec['boot_id']):
            raise ValueError('root/host/boot mismatch')
        unit = 'timeservice.service' if spec['mode'] == 'node' else 'NetworkManager.service'
        current = support.properties(cmd(label, ['/usr/bin/systemctl', 'show', unit,
                                         '--property='+spec['continuity_fields']]))
        if current != spec['service_identity']:
            raise ValueError('accepted service identity changed')

    try:
        continuity('service_before')
        result['started_epoch'] = time.time()
        cmd('architecture', ['/usr/bin/dpkg', '--print-architecture'])
        cmd('packages', ['/usr/bin/dpkg-query', '-W', '-f=${binary:Package}\t${Version}\t${Architecture}\t${db:Status-Abbrev}\n'])
        ip = next((p for p in ('/usr/sbin/ip', '/usr/bin/ip') if Path(p).is_file()), None)
        if not ip:
            raise ValueError('ip tool missing')
        cmd('interface_addresses', [ip, '-json', 'address', 'show', 'dev', 'eth0'])
        destinations = ['10.1.3.83', 'fd36:5aa8:6971:1::83'] if spec['mode'] == 'node' else ['10.1.0.51', 'fd36:5aa8:6971:1::51']
        for family, address in zip((4, 6), destinations):
            cmd('route_'+str(family), [ip, '-'+str(family), '-json', 'route', 'get', address], (0, 2))
        cmd('listener_4949', ['/usr/bin/ss', '-H', '-lnt', 'sport = :4949'])
        if spec['mode'] == 'node':
            result['files'] = {p: record(p) for p in NODE_FILES}
            result['paths'] = {p: metadata_directory(p) for p in (
                '/etc/munin', '/etc/systemd/system/munin-node.service.d', '/usr/local/munin/lib/plugins',
                '/var/lib/munin-ntp-install', '/var/lib/ntpstats-retention', '/var/lib/needrestart-reporting',
                '/var/log/ntpstats', '/etc/logrotate.d', '/var/lib/apt/lists')}
            cmd('munin_identity', ['/usr/bin/getent', 'passwd', 'munin'], (0, 2))
            cmd('munin_group', ['/usr/bin/getent', 'group', 'munin'], (0, 2))
            cmd('node_service', ['/usr/bin/systemctl', 'show', 'munin-node.service', '--property='+SERVICE_FIELDS])
            cmd('producer_services', ['/usr/bin/systemctl', 'show', 'cron.service', 'logrotate.service', '--property='+SERVICE_FIELDS])
            cmd('retention_timer', ['/usr/bin/systemctl', 'show', 'logrotate.timer',
                '--property=LoadState,ActiveState,SubState,UnitFileState,NextElapseUSecRealtime,LastTriggerUSec'])
            for key, args in [('policy', ['policy']), ('dependencies', ['depends'])]:
                cmd('apt_'+key, ['/usr/bin/apt-cache', '-o', 'Dir::Cache::pkgcache=', '-o', 'Dir::Cache::srcpkgcache=', *args,
                                 'munin-node', 'munin-plugins-core'], (0, 100))
            cmd('apt_simulation', ['/usr/bin/apt-get', '-o', 'Dir::Cache::pkgcache=', '-o', 'Dir::Cache::srcpkgcache=',
                '--simulate', '--no-install-recommends', 'install', 'munin-node', 'munin-plugins-core'], (0, 100))
            cmd('timezone', ['/usr/bin/timedatectl', 'show', '--property=Timezone'])
            result['reporter_cron'] = cron('/etc/cron.d/needrestart_check')
            result['ntp_statistics_directives'] = selected_statistics()
            result['producer_structure'] = {p: producer_structure(p) for p in (
                '/etc/logrotate.d/ntpstats-retention', '/usr/local/sbin/needrestart.sh')}
            result['success_record_fields'] = {job: success_record(path, job) for job, path in (
                ('retention', '/var/lib/ntpstats-retention/last-success.json'),
                ('reporting', '/var/lib/needrestart-reporting/last-success.json'))}
            # Export only kernel lock rows matching known existing lock inodes; never acquire a lock.
            known = {str(row['inode']) for row in result['files'].values() if 'inode' in row and not row.get('indirect_or_special')}
            with Path('/proc/locks').open() as stream:
                locks = stream.read(65537)
            if len(locks) > 65536:
                raise ValueError('kernel lock table bound')
            result['matching_kernel_locks'] = [line for line in locks.splitlines()
                if any(':'+inode+' ' in line for inode in known)][:32]
            for path in ('/', '/var/log/ntpstats'):
                fs = os.statvfs(path)
                result.setdefault('capacity', {})[path] = {'available_bytes': fs.f_bavail*fs.f_frsize,
                    'available_inode_fraction': fs.f_favail/fs.f_files if fs.f_files else None}
            result['success_records'] = {p: record(p) for p in NODE_FILES if p.endswith('last-success.json')}
            result['producer_contents_omitted'] = True
        else:
            result['configuration'] = support.master_configuration()
            result['cron'] = cron('/etc/cron.d/munin')
            result['scheduler_sources'] = support.scheduler_sources(h)
            result['activity'] = [support.activity_summary(Path(p)) for p in (
                '/var/log/munin/munin-update.log', '/var/log/munin/munin-limits.log')]
            result['installed_polling_documentation'] = {p: installed_excerpt(p) for p in (
                '/usr/share/perl5/Munin/Master/Node.pm', '/usr/share/perl5/Munin/Master/Config.pm',
                '/usr/share/perl5/Munin/Master/Update.pm', '/usr/share/man/man5/munin.conf.5.gz',
                '/usr/share/man/man8/munin-update.8.gz')}
            cmd('master_services', ['/usr/bin/systemctl', 'show', 'cron.service', 'apache2.service',
                'munin-node.service', '--property='+SERVICE_FIELDS])
            cmd('master_timers', ['/usr/bin/systemctl', 'show', 'munin.timer',
                '--property=LoadState,ActiveState,SubState,UnitFileState,NextElapseUSecRealtime'])
            result['apache_vhost'] = record('/etc/apache2/sites-available/001-munin.theama.co-ssl.conf')
            result['apache_paths'] = {p: metadata_directory(p) for p in (
                '/etc/apache2/sites-enabled', '/var/cache/munin/www', '/var/lib/munin', '/usr/lib/munin/cgi')}
            result['j2_data'] = metadata_directory('/var/lib/munin/local.theama.co')
            result['unexpanded_includes_are_findings'] = True
            # This readiness scope intentionally does not resolve names or request CGI graphs.
            result['client_dns_and_live_graph_checks'] = 'deferred to separately approved master acceptance'
            if spec['mode'] in ('master-config','master-baseline'):
                namespace = {'__name__':'qualification','__file__':'/sealed/qualification.py'}
                exec(compile(frozen_inputs['qualification.py'], namespace['__file__'], 'exec'), namespace)
                result['master_qualification'] = namespace['collect'](h,
                    frozen_inputs['repository-master.conf'], frozen_inputs['contact-example.conf'],
                    export_sha256=spec.get('production_baseline_sha256'))
                cmd('activation_controls', ['/usr/bin/systemctl', 'show', 'munin-node.service',
                    'apache2.service', 'rrdcached.service', '--property=LoadState,ActiveState,SubState,CanReload,ExecReload,FragmentPath,DropInPaths'])
                result['native_sources'] = {p:h.file_record(p, content=True) for p in (
                    '/usr/share/perl5/Munin/Master/Config.pm',
                    '/usr/share/perl5/Munin/Common/Config.pm',
                    '/usr/share/perl5/Munin/Master/Utils.pm',
                    '/usr/share/perl5/Munin/Master/LimitsOld.pm',
                    '/usr/lib/munin/cgi/munin-cgi-graph',
                    '/usr/lib/munin/cgi/munin-cgi-html',
                    '/usr/lib/systemd/system/munin-node.service')}
                if spec['mode'] == 'master-baseline':
                    result['native_sources'].update({p:h.file_record(p, content=True) for p in (
                        '/usr/share/perl5/Munin/Master/GraphOld.pm',
                        '/usr/share/perl5/Munin/Master/UpdateWorker.pm',
                        '/usr/share/perl5/Munin/Master/Update.pm')})
        continuity('service_after')
        result['completed_epoch'] = time.time()
        result['capture_complete'] = True
    except Exception as error:
        result['error'] = str(error)
    return result


def accepted(path):
    """Bind accepted operation data, never import old executable implementations."""
    outcome_raw = h.private(path/'outcome.json')
    outcome = json.loads(outcome_raw)
    raw = h.private(path/'deployment.tar', 8*h.LIMIT)
    digest = h.sha(raw)
    if outcome.get('archive_sha256') != digest or not (outcome.get('accepted') is True or outcome.get('status') == 'accepted'):
        raise ValueError('accepted operation binding required')
    return {'archive_sha256': digest, 'outcome_sha256': h.sha(outcome_raw)}, outcome, raw


def review(spec):
    node = spec['mode'] == 'node'
    title = 'j2-svntp1 node/producer' if node else 'svmf native-master'
    scope = '''Capture full package inventory/architecture, cached APT policy/dependencies and one
no-recommends install simulation (no refresh/download/install). Read metadata,
hashes and bounded directory entries for the fixed installer/config/guard,
logrotate rule/trigger/state, reporter/cron/locks, two success records and
statistics paths. Capture Munin user/group, TCP 4949 listener state, service/timer
identity, schedule structure, exact node-to-master route lookups and statvfs
capacity. Match existing kernel lock rows without opening/acquiring the locks.
No ntpq query, plugin, scan, cleanup, logrotate invocation, mail, firewall/controller
query or content read of raw statistics. Raw producer/success-record contents are omitted; only fixed
structure markers and validated schema/job/status/numeric completion fields are retained; missing paths/records remain findings, not fabricated health.''' if node else '''Capture full installed package inventory, native /etc/munin/munin.conf plus
immediate standard include configuration (at most 64 files, 64 KiB each), retaining
only whitelisted structural/limit fields. Contact command values and raw config
are omitted. Custom include references are findings, not recursively followed.
Capture fixed scheduler source hashes/markers, /etc/cron.d/munin schedule,
bounded activity timestamps/counts (no raw log lines), fixed installed Munin
source/manual excerpts for family-selection design, route lookups to the NTP
node, Apache/cron/Munin unit state, current vhost hash and fixed CGI/cache/data
path metadata. Do not execute Apache configtest, CGI, Munin update/limits/plugins,
node protocol fetch, TLS request, getent DNS lookup or any notification. Graph
freshness/client-family DNS still need separate acceptance; metadata alone does
not prove fresh scheduled dual-family polling. Missing source/docs/includes remain gaps.'''
    if spec['mode'] in ('master-config','master-baseline'):
        scope += '''

Additionally compare production munin.conf bytes against the frozen canonical
repository master config. Parse bounded current config/include streams, a
preserving commissioning merge, the repository baseline and the contact example
with the installed Munin::Master::Config parser as munin. Parsing is in memory:
no include expansion, update, limits evaluation, contact execution, plugin run,
config installation, temporary target file or log initialization. Explicitly
retain effective include/inheritance acceptance as false until native source
semantics are reviewed. Preserve existing host names; new contacts are none in
the in-memory commissioning merge. Record the fixed native Config/Common/Utils/
LimitsOld and CGI sources, packaged node unit, activation/reload metadata and
rrdcached socket metadata. Source bytes stay in private evidence. Missing files,
parser failures and repository drift are findings; do not repair them. This
qualifies configuration and identifies supported activation/restoration paths;
it does not execute or accept a service restart, reload or actual restoration.
'''
    if spec['mode'] == 'master-baseline':
        scope += '''

Export only the exact /etc/munin/munin.conf bytes to private controller evidence
for the operator-authorized repository mirror. Require its SHA-256 to equal the
previous accepted production capture pinned in this spec; drift aborts export.
No raw includes, credentials or environment are exported. Read the fixed native
GraphOld, UpdateWorker and Update modules to resolve rrdcached fallback and graph
behavior from installed code. No cache probe, flush, daemon installation, RRD
write, service action or message is included. Import into the repository follows
successful capture and a private secret scan; it is a controller-only operation.
Additionally parse an in-memory commissioning candidate that removes only the
single reviewed stale rrdcached_socket directive, using native direct-RRD defaults.
This candidate is separate from the exact production mirror and is not installed.
'''
    expires = datetime.fromtimestamp(spec['expires_epoch'], ZoneInfo('America/Chicago')).isoformat()
    return f'''# {title} read-only readiness review

Operation `{spec['operation_id']}`. Prepared October 21, 2026; expires **{expires}**.
Approve inspection.tar's exact SHA-256 in sealing.json before target contact.
Target {spec['user']}@{spec['endpoint']}; established Ed25519 alias
{spec['host_key_alias']}; hostname {spec['hostname']}; boot {spec['boot_id']}.
The archive pins baseline capture, accepted network/DNS outcome hashes,
continuity fields, source, inventory, profile, stage definitions and review.
The corrected stdin bootstrap explicitly supplies `__file__` to the helper module;
its actual payload reaches the collection guard in local regression testing.
This correction changes no inspection commands or authorization boundaries.
Any prior consumed attempt remains immutable and cannot be replayed.
Only this one target is contacted. Other addresses occur in local route lookups;
no packets are sent to the other host or DNS/proxy VIPs by this inspection.

## Exact read-only scope

{scope}

Require root, exact host/boot and the sealed accepted service identity before
collection and again afterward. Boot/service drift yields an incomplete capture;
do not silently refresh pins or infer a failed inspection is permission to repair.
Read fixed protected regular files only, reject/report symlinks/special files,
limit files to 1 MiB and directory entries to 512. Commands use a fixed PATH/C
locale, 25-second deadlines and bounded output. Remote alarm 240 seconds; outer
transport 270 seconds. Only structural known command fields are retained from
cron/config. No arbitrary home files, TLS/control/private keys, msmtprc, container
environment or credentials are read. SSH/sudo/APT simulation may write normal
logs; no target staging or durable operation state is created.

## Execution and capture acceptance

After exact-hash approval use the frozen controller:

```bash
python3 -I -B DIRECTORY/runner.py execute --directory DIRECTORY --sha256 APPROVED_SHA256
```

A local exclusive execution.json is consumed before strict-host-key SSH with
sudo -n and isolated no-bytecode Python on stdin. No forwarding, proxy, connection
sharing, TOFU, host-key update or blind retry. Private stdout/stderr and result.json
retain bounded diagnostics. Capture acceptance requires transport exit 0, exact
operation/spec binding and capture_complete=true; it does not accept installation,
producer success, polling, alert delivery or any other target stage. A simulation
failure, missing identity/path/docs or unknown include is retained for review.
A consumed or failed inspection cannot be replayed; a changed scope requires a
new bundle/hash. No target recovery or cleanup is included because no mutation
is authorized. Retain local evidence even after an incomplete capture.

## Handoff

Reconcile captured inputs with the three stage definitions. {('Finish the outer guarded ARM64 node bundle and genuine producer implementation separately; preserve expected missing-record faults.' if node else 'Resolve one-canonical-identity scheduled dual-family polling, unknown-data/limits semantics and current master mutation/recovery before sealing.')}
No new HA fixtures, stand-ins, simulated failover, package installation, service
activation/reload/restart, NTP/GPS/RTC operation, lock acquisition, job invocation,
network/DNS/controller change or message is included. Existing network/DNS
receipts remain consumed. Retain OBS-02/OBS-07, client/graph/persistence work and
mandatory later separate-host ntpviz as independent acceptance obligations.
'''


def seal(args):
    old_raw = h.private(args.baseline/'inspection.tar', 8*h.LIMIT)
    receipt = json.loads(h.private(args.baseline/'result.json'))
    capture_raw = h.private(args.baseline/'stdout.txt', 16*h.LIMIT)
    capture = json.loads(capture_raw)
    if receipt.get('bundle_sha256') != h.sha(old_raw) or receipt.get('returncode') != 0 or not receipt.get('capture_complete') or not capture.get('capture_complete') or receipt.get('error') or capture.get('error'):
        raise ValueError('accepted inspection baseline required')
    with tarfile.open(fileobj=io.BytesIO(old_raw)) as archive:
        old = json.loads(archive.extractfile('spec.json').read())
        known = archive.extractfile('known_hosts').read()
    if capture.get('operation_id') != old['operation_id'] or capture.get('spec_sha256') != h.sha(h.encoded(old)):
        raise ValueError('inspection baseline binding')
    network, network_outcome, network_raw = accepted(args.network_baseline)
    dns, dns_outcome, dns_raw = accepted(args.dns_baseline)
    with tarfile.open(fileobj=io.BytesIO(dns_raw)) as archive:
        dns_candidate = archive.extractfile('bundle/candidate.conf').read()
    if h.sha(dns_candidate) != dns_outcome.get('candidate_sha256') or not all(line in dns_candidate for line in (
            b'munin.local.theama.co. IN AAAA fd36:5aa8:6971:1::83',
            b'svmf.local.theama.co. IN AAAA fd36:5aa8:6971:1::83',
            b'fd36:5aa8:6971:1::83 svmf.local.theama.co.')):
        raise ValueError('accepted Munin/svmf DNS candidate required')
    if network_outcome.get('phase') != 'committed' or network_outcome.get('addresses') != ['10.1.3.83', 'fd36:5aa8:6971:1::83']:
        raise ValueError('accepted static master network required')
    endpoint, user, alias, hostname = TARGETS[args.mode]
    if (old['endpoint'], old['user'], old['host_key_alias']) != (endpoint, user, alias):
        raise ValueError('inspection SSH identity baseline mismatch')
    now = int(time.time())
    spec = {'mode': args.mode, 'endpoint': endpoint, 'user': user, 'host_key_alias': alias,
            'hostname': hostname, 'operation_id': args.output.name, 'prepared_epoch': now,
            'expires_epoch': now+86400, 'baseline_bundle_sha256': h.sha(old_raw),
            'baseline_capture_sha256': h.sha(capture_raw), 'accepted_network': network, 'accepted_dns': dns}
    if args.mode == 'node':
        if old.get('mode') != 'node-dependencies':
            raise ValueError('accepted node dependency baseline required')
        spec.update(boot_id=old['boot_id'], service_identity=old['service_identity'])
    else:
        with tarfile.open(fileobj=io.BytesIO(network_raw)) as archive:
            net_spec = json.loads(archive.extractfile('spec.json').read())
            if known != archive.extractfile('known_hosts').read():
                raise ValueError('master key continuity mismatch')
        if network_outcome.get('phase') != 'committed' or net_spec['hostname'] != hostname:
            raise ValueError('committed static master identity required')
        spec.update(boot_id=net_spec['boot_id'], service_identity=net_spec['manager'])
    spec['continuity_fields'] = ','.join(spec['service_identity'])
    if args.mode == 'master-baseline':
        if old.get('mode') != 'master-config':
            raise ValueError('completed native master-config baseline required')
        records = capture.get('master_qualification',{}).get('files',[])
        if not records or records[0].get('path') != '/etc/munin/munin.conf':
            raise ValueError('production master configuration hash required')
        spec['production_baseline_sha256'] = records[0]['record']['sha256']
    files = {name: path.read_bytes() for name, path in SOURCES.items()}
    files['known_hosts'] = known
    spec['members'] = {n: h.sha(v) for n, v in files.items()}
    files.update({'spec.json': h.encoded(spec), 'review.md': review(spec).encode()})
    os.umask(0o077)
    args.output.mkdir(mode=0o700)
    for name, raw in files.items():
        (args.output/name).write_bytes(raw)
    with tarfile.open(args.output/'inspection.tar', 'w') as archive:
        for name, raw in sorted(files.items()):
            m = tarfile.TarInfo(name); m.size = len(raw); m.mode = 0o600
            archive.addfile(m, io.BytesIO(raw))
    digest = h.sha((args.output/'inspection.tar').read_bytes())
    prepare(args.output, digest)
    result = {'sha256': digest, 'expires_epoch': spec['expires_epoch'], 'target_contact': False}
    (args.output/'sealing.json').write_bytes(h.encoded(result))
    return result


def prepare(directory, digest):
    info = directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError('private owned bundle directory required')
    raw = h.private(directory/'inspection.tar', 8*h.LIMIT)
    if h.sha(raw) != digest:
        raise ValueError('approved archive hash mismatch')
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        entries = archive.getmembers(); expected = set(SOURCES)|{'known_hosts', 'spec.json', 'review.md'}
        if len(entries) != len(expected) or {m.name for m in entries} != expected or any(not m.isfile() or m.size > h.LIMIT for m in entries):
            raise ValueError('closed bounded regular archive required')
        files = {m.name: archive.extractfile(m).read() for m in entries}
    spec = json.loads(files['spec.json'])
    if (spec['mode'] not in TARGETS or tuple(spec[k] for k in ('endpoint', 'user', 'host_key_alias', 'hostname')) != TARGETS[spec['mode']]
            or not re.fullmatch(r'[a-z][a-z0-9-]{0,63}', spec['operation_id'])
            or not 0 < spec['expires_epoch']-spec['prepared_epoch'] <= 86400
            or not spec['prepared_epoch'] <= time.time() < spec['expires_epoch']-270
            or spec['members'] != {n: h.sha(files[n]) for n in set(SOURCES)|{'known_hosts'}}
            or files['review.md'] != review(spec).encode()):
        raise ValueError('scope, expiry or member binding')
    if files['runner.py'] != Path(__file__).read_bytes():
        raise ValueError('frozen controller required')
    for name, raw in files.items():
        if h.private(directory/name) != raw:
            raise ValueError('local frozen input drift: '+name)
    return spec, files


def execute(args):
    os.umask(0o077)
    directory = args.directory.absolute()
    spec, files = prepare(directory, args.sha256)
    payload = b"__name__='sealed_readiness'\n__file__='/sealed/runner.py'\n"+files['runner.py']
    payload += b"\nns={'__name__':'helper','__file__':'/sealed/helper.py'}\nexec("+repr(files['helper.py']).encode()+b",ns)\nh=types.SimpleNamespace(**ns)"
    payload += b"\nns={'__name__':'support','__file__':'/sealed/support.py'}\nexec("+repr(files['support.py']).encode()+b",ns)\nsupport=types.SimpleNamespace(**ns)\nsupport.h=h\n"
    # Functions defined by support retain their own globals; set h there as well.
    payload += b"ns['h']=h\nsignal.signal(signal.SIGALRM,h.expired)\nsignal.alarm(240)\nprint(json.dumps(collect("+repr(spec).encode()+b")))\n"
    if spec.get('mode') in ('master-config','master-baseline'):
        payload = payload.replace(b"ns['h']=h\n", b"frozen_inputs="+repr({n:files[n] for n in (
            'qualification.py','repository-master.conf','contact-example.conf')}).encode()+b"\nns['h']=h\n", 1)
    argv = h.ssh_argv({'endpoints': [spec['endpoint']], 'host_key_alias': spec['host_key_alias']}, directory)
    argv[-2] = spec['user']+'@'+spec['endpoint']
    with (directory/'execution.json').open('xb') as stream:
        stream.write(h.encoded({'sha256': args.sha256, 'payload_sha256': h.sha(payload), 'argv': argv, 'epoch': time.time()}))
        stream.flush(); os.fsync(stream.fileno())
    row = h.bounded(argv, timeout=270, limit=16*h.LIMIT, payload=payload, env=os.environ.copy())
    for field in ('stdout', 'stderr'):
        (directory/(field+'.txt')).write_text(row.pop(field))
    row.update(bundle_sha256=args.sha256, capture_complete=False)
    if row.get('returncode') == 0 and not row.get('error'):
        capture = json.loads((directory/'stdout.txt').read_text())
        if capture.get('operation_id') != spec['operation_id'] or capture.get('spec_sha256') != h.sha(h.encoded(spec)):
            raise ValueError('capture binding mismatch')
        row['capture_complete'] = capture.get('capture_complete') is True
    (directory/'result.json').write_bytes(h.encoded(row))
    return row


def main():
    global h, support
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    p = sub.add_parser('seal'); p.add_argument('--mode', choices=TARGETS, required=True)
    for name in ('baseline', 'network-baseline', 'dns-baseline', 'output'):
        p.add_argument('--'+name, type=Path, required=True)
    for action in ('check', 'execute'):
        p = sub.add_parser(action); p.add_argument('--directory', type=Path, required=True); p.add_argument('--sha256', required=True)
    args = parser.parse_args()
    if args.action == 'seal':
        for name, filename in (('h', 'helper.py'), ('support', 'support.py')):
            loader = importlib.util.spec_from_file_location(name, SOURCES[filename])
            module = importlib.util.module_from_spec(loader); loader.loader.exec_module(module)
            globals()[name] = module
        support.h = h
    else:
        # Authenticate archive bytes before importing any local executable dependency.
        with (args.directory/'inspection.tar').open('rb') as stream:
            raw = stream.read(8*1048576+1)
        if len(raw) > 8*1048576 or hashlib.sha256(raw).hexdigest() != args.sha256:
            raise ValueError('approved archive hash mismatch')
        with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
            entries = archive.getmembers()
            expected = set(SOURCES)|{'known_hosts', 'spec.json', 'review.md'}
            if len(entries) != len(expected) or {m.name for m in entries} != expected or any(not m.isfile() or m.size > 1048576 for m in entries):
                raise ValueError('closed bounded archive required')
            for name, filename in (('h', 'helper.py'), ('support', 'support.py')):
                module = types.ModuleType(name); module.__file__ = '/sealed/'+filename
                exec(compile(archive.extractfile(filename).read(), module.__file__, 'exec'), module.__dict__)
                globals()[name] = module
        support.h = h
    if args.action == 'seal':
        result = seal(args)
    elif args.action == 'execute':
        result = execute(args)
    else:
        spec, _ = prepare(args.directory, args.sha256)
        result = {'verified': True, 'target_contact': False, 'mode': spec['mode']}
    print(json.dumps(result))
    if args.action == 'execute' and not result['capture_complete']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
