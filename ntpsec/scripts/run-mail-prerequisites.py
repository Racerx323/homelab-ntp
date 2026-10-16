#!/usr/bin/python3
"""Seal bounded, non-sending mail dependency and relay configuration inspections."""
import argparse
import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import tarfile
import time
import types

ROOT = Path(__file__).resolve().parents[1]
INPUTS = {'runner.py': 'scripts/run-mail-prerequisites.py',
          'helper.py': 'scripts/run-production-inspection.py',
          'tests.py': 'tests/test_mail_prerequisites.py'}
TARGETS = {
    'packages': ('10.1.0.51', 'ama', '10.1.0.137'),
    'relay': ('10.1.3.83', 'pi', 'svmf.local.theama.co'),
    'relay-environment': ('10.1.3.83', 'pi', 'svmf.local.theama.co'),
}
helper = None

# Runs inside the existing Mailrise container. Never load Mailrise configuration
# through its own loader: import_code can execute user-defined Python.
ROUTES = r'''
import hashlib, json, os, stat, sys
from pathlib import Path
stage = 'application_path'
try:
    application_site = '/home/mailrise/.local/lib/python3.14/site-packages'
    if not os.path.isdir(application_site):
        raise FileNotFoundError('observed application package directory absent')
    # Append exactly the observed directory; do not process .pth files or
    # enable automatic user-site/current-directory/environment imports.
    sys.path.append(application_site)
    stage = 'yaml_import'
    import yaml
    stage = 'metadata_import'
    from importlib.metadata import distribution
    stage = 'configuration_read'
    p = Path('/etc/mailrise.conf')
    before = p.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > 1048576:
        raise ValueError('configuration type/size')
    raw = p.read_bytes()
    after = p.lstat()
    if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
        raise ValueError('configuration changed')
    class UniqueLoader(yaml.SafeLoader):
        pass
    def mapping(loader, node):
        result = {}
        for key, value in node.value:
            key = loader.construct_object(key)
            if key in result:
                raise ValueError('duplicate mapping key')
            result[key] = loader.construct_object(value)
        return result
    UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
    stage = 'yaml_parse'
    data = yaml.load(raw, Loader=UniqueLoader)
    stage = 'configuration_shape'
    if not isinstance(data, dict) or data.get('import_code'):
        raise ValueError('unsupported custom configuration')
    configs = data.get('configs', {})
    if not isinstance(configs, dict):
        raise ValueError('configs type')
    result = {}
    for name in ('notify',):
        item = configs.get(name)
        urls = item.get('urls') if isinstance(item, dict) else None
        if isinstance(urls, str): urls = [urls]
        result[name+'@mailrise.xyz'] = {
            'exact_key_present': name in configs,
            'nonempty_urls': isinstance(urls, list) and bool(urls) and all(isinstance(u, str) and bool(u.strip()) for u in urls)}
    stage = 'distribution_lookup'
    dist = distribution('mailrise')
    stage = 'router_source_read'
    source = Path(dist.locate_file('mailrise/simple_router.py'))
    if not source.is_file() or source.stat().st_size > 131072:
        raise ValueError('installed router source unavailable')
    router = source.read_bytes()
    print(json.dumps({'application_site': application_site, 'mailrise_version': dist.version,
        'router_source_sha256': hashlib.sha256(router).hexdigest(),
        'router_source': router.decode('utf-8'),
        'configuration_sha256': hashlib.sha256(raw).hexdigest(),
        'configuration_mtime': before.st_mtime, 'routes': result,
        'notify_is_first_config': next(iter(configs), None) == 'notify',
        'delivery_verified': False}))
except Exception as error:
    # YAML exception messages can contain the offending secret source line.
    print(json.dumps({'stage': stage, 'error_type': type(error).__name__, 'routes_unverified': True}))
    raise SystemExit(1)
'''




ENVIRONMENT = r'''
import importlib.util, json, os, re, shutil, site, sys
from pathlib import Path
result = {'inspection_executable': sys.executable, 'python_version': sys.version.split()[0],
          'prefix': sys.prefix, 'base_prefix': sys.base_prefix, 'isolated': sys.flags.isolated,
          'user_site_enabled': site.ENABLE_USER_SITE, 'sys_path': sys.path,
          'user_site': site.getusersitepackages(), 'modules': {}, 'launchers': {}}
for name in ('yaml', 'mailrise'):
    spec = importlib.util.find_spec(name)
    result['modules'][name] = {'found': spec is not None,
                              'origin': spec.origin if spec is not None else None}
for name in ('python', 'python3', 'mailrise'):
    path = shutil.which(name)
    row = {'path': path}
    if path:
        row['resolved'] = str(Path(path).resolve())
        if name == 'mailrise':
            with open(path, 'rb') as stream:
                first = stream.readline(512)
            # Only the interpreter path, never arbitrary script text/arguments.
            match = re.fullmatch(rb'#![ \t]*(/[A-Za-z0-9_./+-]+)(?:[ \t]+[^\r\n]*)?[\r\n]*', first)
            row['shebang_interpreter'] = match.group(1).decode() if match else None
    result['launchers'][name] = row
try:
    result['pid1_executable'] = os.readlink('/proc/1/exe')
except OSError as error:
    result['pid1_error'] = type(error).__name__
# Check only fixed package names in Python's reported user site, not contents.
user_site = Path(site.getusersitepackages())
result['user_site_packages'] = {name: (user_site/name/'__init__.py').is_file()
                                for name in ('yaml', 'mailrise')}
print(json.dumps(result))
'''

def reader_diagnostic(row):
    """Retain fixed classifications, never exception text or raw stderr."""
    result = {'returncode': row.get('returncode'), 'command_error': bool(row.get('error')),
              'stdout_bytes': len(row.get('stdout', '').encode()),
              'stderr_bytes': len(row.get('stderr', '').encode()),
              'stage': 'reader_not_classified', 'error_type': 'Unclassified'}
    try:
        value = json.loads(row.get('stdout', ''))
    except (ValueError, TypeError):
        value = None
    stages = {'application_path', 'yaml_import', 'metadata_import', 'configuration_read', 'yaml_parse',
              'configuration_shape', 'distribution_lookup', 'router_source_read'}
    errors = {'ModuleNotFoundError', 'ImportError', 'FileNotFoundError',
              'PermissionError', 'ValueError', 'TypeError', 'KeyError',
              'UnicodeDecodeError', 'OSError', 'PackageNotFoundError',
              'ScannerError', 'ParserError', 'ConstructorError'}
    if isinstance(value, dict) and value.get('routes_unverified') is True:
        if isinstance(value.get('stage'), str) and value['stage'] in stages: result['stage'] = value['stage']
        if isinstance(value.get('error_type'), str) and value['error_type'] in errors: result['error_type'] = value['error_type']
    return result

def command(argv, timeout=10, payload=None):
    return helper.bounded(argv, timeout=timeout, payload=payload)


def identity():
    row = command(['/usr/bin/systemctl', 'show', 'timeservice.service',
        '--property=MainPID,InvocationID,NRestarts,ActiveState,SubState,UnitFileState'])
    if row.get('returncode') != 0 or row.get('error'): raise ValueError('NTP identity unavailable')
    return dict(line.split('=', 1) for line in row['stdout'].splitlines() if '=' in line)


def container(name):
    # Explicit selection omits environment, labels and command arguments.
    row = command(['/usr/bin/podman', 'inspect', '--format',
        '{{.Id}}|{{.Image}}|{{.State.Status}}|{{.State.Pid}}|{{.State.StartedAt}}', name])
    if row.get('returncode') != 0 or row.get('error'): raise ValueError('container identity unavailable')
    parts = row['stdout'].strip().split('|')
    if len(parts) != 5 or parts[2] != 'running': raise ValueError('container not running')
    return parts


def collect(spec):
    report = {'operation_id': spec['operation_id'], 'spec_sha256': helper.sha(helper.encoded(spec)),
              'capture_complete': False, 'delivery_verified': False}
    if os.geteuid() != 0: raise ValueError('root required')
    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    report['boot_before'] = boot
    if spec['mode'] == 'packages':
        if boot != spec['boot_id']: raise ValueError('accepted boot changed')
        before = identity()
        if before != spec['service_identity']: raise ValueError('accepted NTP identity changed')
        commands = {
            'architecture': ['/usr/bin/dpkg', '--print-architecture'],
            'packages': ['/usr/bin/dpkg-query', '-W', '-f=${binary:Package}\t${Version}\t${db:Status-Abbrev}\n'],
            'audit': ['/usr/bin/dpkg', '--audit'],
            'policy': ['/usr/bin/apt-cache', 'policy', 'msmtp', 'msmtp-mta', 'needrestart', 'cron'],
            'metadata': ['/usr/bin/apt-cache', 'show', '--no-all-versions', 'msmtp', 'msmtp-mta'],
            'simulation': ['/usr/bin/apt-get', '--simulate', '--no-install-recommends', 'install', 'msmtp', 'msmtp-mta'],
            'msmtpd': ['/usr/bin/systemctl', 'show', 'msmtpd.service', '--property=LoadState,ActiveState,UnitFileState'],
        }
        report['commands'] = {name: command(argv, timeout=30) for name, argv in commands.items()}
        report['paths'] = {p: helper.file_record(p) for p in ('/etc/aliases', '/etc/msmtprc', '/usr/bin/msmtp')}
        report['ntp_before'] = before
        report['ntp_after'] = identity()
        report['capture_complete'] = before == report['ntp_after'] and all(
            x.get('returncode') == 0 and not x.get('error') for x in report['commands'].values())
    elif spec['mode'] in ('relay', 'relay-environment'):
        before = {name: container(name) for name in ('mailrise', 'apprise-api')}
        report['containers_before'] = before
        # A separate Python process reads mounted configuration without sending
        # SMTP/HTTP requests, importing custom route code or exporting URLs.
        environment = spec['mode'] == 'relay-environment'
        row = command(['/usr/bin/podman', 'exec', '-i', 'mailrise', 'python3', '-I', '-B', '-'],
                      timeout=30, payload=(ENVIRONMENT if environment else ROUTES).encode())
        report['reader_diagnostic'] = reader_diagnostic(row)
        if row.get('returncode') != 0 or row.get('error'):
            report['route_capture_error'] = 'route parser unavailable or unsupported configuration'
        else:
            try:
                value = json.loads(row['stdout'])
                required = 'modules' if environment else 'routes'
                if not isinstance(value, dict) or value.get('routes_unverified') or not isinstance(value.get(required), dict):
                    raise ValueError('reader result shape')
                report['python_environment' if environment else 'route_configuration'] = value
            except (ValueError, TypeError):
                report['route_capture_error'] = 'invalid reader result'

        report['containers_after'] = {name: container(name) for name in before}
        report['capture_complete'] = (before == report['containers_after']
            and ('python_environment' if environment else 'route_configuration') in report)
    else:
        raise ValueError('unknown mode')
    report['boot_after'] = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    report['capture_complete'] &= boot == report['boot_after']
    return report


def review(spec):
    description = ('''Inspect installed package versions, architecture, dpkg audit, cached APT
candidate metadata, a no-recommends apt-get simulation, msmtpd unit state and
mail configuration metadata. Do not refresh APT or download/install packages.
Require the accepted boot and exact NTP identity before/after collection.
Cached candidates may be stale; simulation is not installation acceptance.'''
        if spec['mode'] == 'packages' else '''Inspect the existing rootful mailrise and apprise-api container identities.
Require both running and unchanged before/after. Execute one isolated Python
reader inside mailrise for /etc/mailrise.conf. Keep python3 -I -B and append only
the observed /home/mailrise/.local/lib/python3.14/site-packages directory to the
isolated search path. Do not enable automatic user-site processing, run .pth
files, use PYTHONPATH or import from the current directory. This path was observed
in accepted mail-environment-inspection-20261015-v1; missing path fails closed.
Safe-parse YAML without custom
code; return only its hash, mtime, first-key and exact-key/nonempty-URL booleans for notify. The first-key
check avoids assuming that an earlier wildcard does not override it. Read
the installed Mailrise version and simple_router.py source to verify that both
notify@mailrise.xyz and notify.failure@mailrise.xyz select it, with the latter
setting failure notification type. These are findings for review, not automatic
route acceptance. Never export destinations,
keys, auth settings, environment or logs. Unknown YAML/custom routing fails
closed. This confirms configuration presence only: downstream routes, loaded
configuration freshness and delivery still need assessment. No SMTP/HTTP probe.
Retain the inner return code, command-error flag, output byte counts and
allowlisted failure stage/error class. Catch YAML/import/file/distribution
failures without exporting exception messages, source lines or raw stderr.
Unclassified process failures stay explicit; do not guess a cause. This fixes
the earlier collector's loss of the inner failure details.
Rootful storage follows the repository's documented deployment; failure does
not authorize probing another user/storage or changing containers.''')
    if spec['mode'] == 'relay-environment':
        description = '''Inspect unchanged running rootful mailrise/apprise-api container identities.
Run one stdlib-only python3 -I -B reader inside mailrise. Report the inspection
interpreter/version, prefixes, isolation/user-site flags, Python search paths,
module-spec locations for yaml/mailrise without importing them, and which-paths
for python/python3/mailrise. Read only the interpreter token from the mailrise
launcher shebang, the /proc/1/exe symlink, and existence of fixed yaml/mailrise
package files in Python's reported user site. Do not read process command lines,
process environment values, configuration, credentials or arbitrary file contents.
Do not invoke the application launcher, change interpreters or install modules.
These observations locate possible application environments; they do not prove
which interpreter a wrapped PID 1 uses, route selection or notification delivery.
Unknown/missing launchers or modules are findings; capture failure stays explicit.
The supplied operator configuration is separate evidence: notify forwards to
Apprise configuration ID apprise. No live YAML parsing is needed in this scope.'''
    return f'''# Read-only mail {spec['mode']} review

Target `{spec['user']}@{spec['endpoint']}`; host-key alias `{spec['host_key_alias']}`.
Operation `{spec['operation_id']}`. Expires at epoch {spec['expires_epoch']}.

{description}

One pinned-key SSH connection, sudo Python through stdin, no target staging.
No service/container lifecycle change, configuration write, package mutation,
needrestart invocation, cron activation, email or notification. Ordinary audit
logs and Podman exec bookkeeping may occur. No rollback is needed.
Commands are bounded to 10–30 seconds and 1 MiB; remote deadline 240 seconds,
SSH deadline 270 seconds and 16 MiB per stream. Retain partial evidence; no retry.

After approval bound to sealing.json SHA-256, execute from the repository:
`python3 -I -B ntpsec/scripts/run-mail-prerequisites.py execute --directory ABSOLUTE_DIRECTORY --sha256 APPROVED_SHA256`
'''


def seal(args):
    host, user, alias = TARGETS[args.mode]
    now = int(time.time())
    spec = {'mode': args.mode, 'endpoint': host, 'user': user, 'host_key_alias': alias,
            'operation_id': args.output.name, 'prepared_epoch': now, 'expires_epoch': now+86400}
    if args.mode == 'packages':
        if not args.baseline: raise ValueError('accepted timer-correction baseline required')
        receipt = json.loads(helper.private(args.baseline/'result.json'))
        state_raw = helper.private(args.baseline/'stdout.txt', 16*helper.LIMIT)
        state = json.loads(state_raw)
        if receipt.get('accepted') is not True or state.get('accepted') is not True:
            raise ValueError('baseline unaccepted')
        archive_raw = helper.private(args.baseline/'leap-timer-correction.tar', 16*helper.LIMIT)
        if helper.sha(archive_raw) != receipt['bundle_sha256']: raise ValueError('baseline archive digest')
        with tarfile.open(fileobj=io.BytesIO(archive_raw)) as archive:
            old = json.loads(archive.extractfile('spec.json').read())
        if (state.get('spec_sha256') != helper.sha(helper.encoded(old))
                or state.get('operation_id') != old['operation_id']
                or receipt.get('returncode') != 0): raise ValueError('baseline result binding')
        rows = [r for r in state['commands'] if r['argv'][:3] ==
                ['/usr/bin/systemctl', 'show', 'timeservice.service']]
        if not rows or rows[-1].get('returncode') != 0: raise ValueError('baseline identity missing')
        values = dict(line.split('=',1) for line in rows[-1]['stdout'].splitlines() if '=' in line)
        service = {k: values[k] for k in ('MainPID','InvocationID','NRestarts','ActiveState','SubState','UnitFileState')}
        spec.update(boot_id=old['boot_id'], service_identity=service,
                    baseline_sha256=helper.sha(state_raw), baseline_bundle_sha256=receipt['bundle_sha256'])
    key = subprocess.run(['ssh-keygen', '-F', alias], check=True, capture_output=True, text=True).stdout
    keys = [line.split() for line in key.splitlines() if not line.startswith('#') and ' ssh-ed25519 ' in line]
    if len(keys) != 1: raise ValueError('one known Ed25519 key required')
    files = {n: (ROOT/p).read_bytes() for n,p in INPUTS.items()}
    files['known_hosts'] = (alias+' ssh-ed25519 '+keys[0][2]+'\n').encode()
    files['spec.json'] = helper.encoded(spec); files['review.md'] = review(spec).encode()
    os.umask(0o077); args.output.mkdir(mode=0o700)
    for n, raw in files.items(): (args.output/n).write_bytes(raw)
    with tarfile.open(args.output/'inspection.tar', 'w') as archive:
        for n, raw in sorted(files.items()):
            info=tarfile.TarInfo(n); info.size=len(raw); info.mode=0o600
            archive.addfile(info,io.BytesIO(raw))
    result={'sha256':helper.sha((args.output/'inspection.tar').read_bytes()),
            'target_contact':False,'expires_epoch':spec['expires_epoch']}
    (args.output/'sealing.json').write_bytes(helper.encoded(result))
    return result


def prepare(directory, digest):
    raw=helper.private(directory/'inspection.tar', 4*helper.LIMIT)
    if helper.sha(raw)!=digest: raise ValueError('archive digest mismatch')
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        members=archive.getmembers()
        names=set(INPUTS)|{'known_hosts','spec.json','review.md'}
        if len(members)!=len(names) or {m.name for m in members}!=names or any(not m.isfile() or m.size>helper.LIMIT for m in members):
            raise ValueError('closed flat archive required')
        files={m.name:archive.extractfile(m).read() for m in members}
    for n,p in INPUTS.items():
        if files[n]!=(ROOT/p).read_bytes(): raise ValueError('repository input drift')
    for n in ('known_hosts','spec.json','review.md'):
        if helper.private(directory/n)!=files[n]: raise ValueError('review input drift')
    spec=json.loads(files['spec.json'])
    if (spec['endpoint'],spec['user'],spec['host_key_alias'])!=TARGETS[spec['mode']]: raise ValueError('target mismatch')
    if not spec['prepared_epoch']-300 <= time.time() < spec['expires_epoch']-270: raise ValueError('expired review')
    if files['review.md']!=review(spec).encode(): raise ValueError('review mismatch')
    return spec,files


def execute(args):
    os.umask(0o077); directory=args.directory.absolute()
    spec,files=prepare(directory,args.sha256)
    payload=(b"__name__='sealed_mail'\n__file__='/sealed/runner.py'\n"+files['runner.py']
        +b"\nnamespace={'__name__':'sealed_helper','__file__':'/sealed/helper.py'}\nexec(compile("
        +repr(files['helper.py']).encode()+b",'/sealed/helper.py','exec'),namespace)\nhelper=types.SimpleNamespace(**namespace)\n"
        +b"signal.signal(signal.SIGALRM,helper.expired)\nsignal.alarm(240)\nprint(json.dumps(collect("
        +repr(spec).encode()+b")))\n")
    argv=helper.ssh_argv({'endpoints':[spec['endpoint']], 'host_key_alias':spec['host_key_alias']},directory)
    argv[-2]=spec['user']+'@'+spec['endpoint']
    with (directory/'execution.json').open('xb') as stream:
        stream.write(helper.encoded({'sha256':args.sha256,'argv':argv,'payload_sha256':helper.sha(payload),'epoch':int(time.time())}))
        stream.flush();os.fsync(stream.fileno())
    result=helper.bounded(argv,timeout=270,limit=16*helper.LIMIT,payload=payload,env=os.environ.copy())
    for n in ('stdout','stderr'): (directory/(n+'.txt')).write_text(result.pop(n))
    result.update(bundle_sha256=args.sha256,capture_complete=False,delivery_verified=False)
    if result.get('returncode')==0 and not result.get('error'):
        try:
            capture=json.loads((directory/'stdout.txt').read_text())
            if capture['operation_id']!=spec['operation_id'] or capture['spec_sha256']!=helper.sha(helper.encoded(spec)):
                raise ValueError('capture binding')
            result['capture_complete']=capture.get('capture_complete') is True
        except (ValueError,KeyError,TypeError) as error: result['error']=str(error)
    (directory/'result.json').write_bytes(helper.encoded(result));return result


def main():
    global helper
    module=importlib.util.spec_from_file_location('mail_helper',ROOT/'scripts/run-production-inspection.py')
    helper=importlib.util.module_from_spec(module);module.loader.exec_module(helper)
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='action',required=True)
    p=sub.add_parser('seal');p.add_argument('--mode',choices=TARGETS,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--baseline',type=Path)
    p=sub.add_parser('execute');p.add_argument('--directory',type=Path,required=True);p.add_argument('--sha256',required=True)
    args=parser.parse_args();result=seal(args) if args.action=='seal' else execute(args)
    print(json.dumps(result))
    if args.action=='execute' and not result['capture_complete']:raise SystemExit(1)


if __name__=='__main__': main()
