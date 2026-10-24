#!/usr/bin/python3
"""Seal one non-sending OBS-04 prerequisite capture; never install a cron job."""
import argparse
import base64
import importlib.util
import io
import json
import os
from pathlib import Path
import pwd
import re
import signal
import socket
import tarfile
import time
import types

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {'runner.py': ROOT/'scripts/run-cron-mail-inspection.py',
           'helper.py': ROOT/'scripts/run-production-inspection.py',
           'tests.py': ROOT/'tests/test_cron_mail_inspection.py'}
CONTENT = ('/etc/cron.d/needrestart_check', '/usr/local/sbin/needrestart.sh',
           '/usr/local/libexec/ntp-maintenance-success.py',
           '/usr/lib/systemd/system/cron.service',
           '/usr/share/man/man8/cron.8.gz', '/usr/share/man/man5/crontab.5.gz',
           '/usr/share/man/man1/msmtp.1.gz')
HASH_ONLY = ('/etc/ntp.conf', '/etc/msmtprc', '/etc/aliases', '/etc/default/cron',
             '/etc/environment', '/usr/sbin/cron', '/usr/bin/msmtp',
             '/var/spool/cron/crontabs/root')
UNITS = ('cron.service', 'timeservice.service', 'gpsd.service',
         'munin-node.service', 'msmtpd.service')
PROPS = 'Id,LoadState,ActiveState,SubState,UnitFileState,InvocationID,MainPID,NRestarts,FragmentPath,DropInPaths'
h = None


def safe_options(raw):
    """Export only constrained non-secret transport settings, never raw lines."""
    rules = {'account': r'[A-Za-z0-9_-]+(?:\s*:\s*[A-Za-z0-9_-]+)?',
             'host': r'[A-Za-z0-9.-]+', 'port': r'[0-9]{1,5}',
             'from': r'[A-Za-z0-9_.+-]+@[A-Za-z0-9.-]+',
             'allow_from_override': r'on|off', 'set_from_header': r'on|off|auto',
             'auth': r'on|off|plain|login|cram-md5|external', 'tls': r'on|off',
             'aliases': r'/etc/aliases'}
    result = {'options': [], 'unexported_directives': 0, 'includes_present': False}
    for line in raw.decode('utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = line.split(None, 1)
        key, value = parts[0], parts[1].strip() if len(parts) == 2 else ''
        if key == 'include':
            result['includes_present'] = True
        if key in rules and re.fullmatch(rules[key], value):
            result['options'].append([key, value])
        else:
            result['unexported_directives'] += 1
    return result


def read_options(path):
    record = h.file_record(path, True)
    if 'base64' not in record or record.get('changed_during_read'):
        return {'unavailable': True}
    return safe_options(base64.b64decode(record['base64'], validate=True))


def state():
    return {name: h.bounded(['/usr/bin/systemctl', 'show', name,
                            '--property='+PROPS]) for name in UNITS}


def collect(spec):
    if os.geteuid() != 0 or socket.gethostname().split('.')[0] != 'j2-svntp1':
        raise ValueError('target/root identity mismatch')
    boot = Path('/proc/sys/kernel/random/boot_id')
    report = {'operation_id': spec['operation_id'], 'spec_sha256': h.sha(h.encoded(spec)),
              'hostname': 'j2-svntp1', 'started_epoch': time.time(),
              'boot_before': boot.read_text().strip(), 'units_before': state(),
              'files': {}, 'commands': {}, 'target_mutation': False,
              'notification_sent': False, 'obs04_accepted': False}
    for path in CONTENT + HASH_ONLY:
        report['files'][path] = h.file_record(path, path in CONTENT)
    report['transport_options'] = read_options('/etc/msmtprc')
    # Alias content and credentials are deliberately excluded; exact aliases are
    # an unresolved prerequisite if the pinned route cannot be established.
    report['aliases_content_exported'] = False
    root_home = Path(pwd.getpwuid(0).pw_dir)
    report['root_transport_override_present'] = any(os.path.lexists(p) for p in
        (root_home/'.msmtprc', root_home/'.config/msmtp/config'))
    report['sendmail_links'] = {}
    for name in ('/usr/sbin/sendmail', '/usr/lib/sendmail'):
        p = Path(name)
        report['sendmail_links'][name] = {
            'symlink': p.is_symlink(), 'resolved': str(p.resolve()),
            'resolves_to_observed_msmtp': p.resolve() == Path('/usr/bin/msmtp')}
    entries = sorted(p.name for p in Path('/etc/cron.d').iterdir())
    if len(entries) > 256:
        raise ValueError('cron directory entry bound')
    report['cron_directory_names'] = entries
    report['test_paths_present'] = {p: os.path.lexists(p) for p in
        ('/etc/cron.d/obs04_cron_failure', '/var/lib/ntp-obs04')}
    commands = {
        'packages': ['/usr/bin/dpkg-query', '-W', '-f=${binary:Package} ${Version} ${db:Status-Abbrev}\n',
                     'cron', 'cron-daemon-common', 'msmtp', 'msmtp-mta', 'needrestart'],
        'timezone': ['/usr/bin/timedatectl', 'show', '--property=Timezone', '--value']}
    for key, argv in commands.items():
        report['commands'][key] = h.bounded(argv)
    report['units_after'] = state()
    report['files_after'] = {p: h.file_record(p) for p in CONTENT + HASH_ONLY}
    report['boot_after'] = boot.read_text().strip()
    report['completed_epoch'] = time.time()
    report['baseline_boot_matches'] = report['boot_before'] == spec['baseline_boot_id']
    report['baseline_file_matches'] = {p: report['files'][p].get('sha256') == digest
        for p, digest in spec['baseline_file_hashes'].items()}
    report['capture_complete'] = (report['boot_before'] == report['boot_after']
        and report['units_before'] == report['units_after']
        and all(v.get('returncode') == 0 and 'error' not in v
                for v in [*report['commands'].values(), *report['units_before'].values()])
        and all('error' not in v and not v.get('changed_during_read')
                for v in [*report['files'].values(), *report['files_after'].values()])
        and all(report['files'][p] == report['files_after'][p]
                for p in HASH_ONLY)
        and all({k: v for k, v in report['files'][p].items() if k != 'base64'}
                == report['files_after'][p] for p in CONTENT))
    return report


def review(spec):
    return f'''# OBS-04 non-sending cron/mail readiness inspection

Target: **j2-svntp1**, `ama@10.1.0.51`, existing pinned Ed25519 alias
`10.1.0.137`. Operation `{spec['operation_id']}`. One capture; no automatic retry.
Expires at Unix epoch {spec['expires_epoch']} (24 hours after preparation).

Read exact current cron/reporter/success-producer bytes, cron unit and installed
cron/crontab/msmtp compressed manuals. Hash the fixed NTP/mail/default-environment,
native cron/msmtp binary and root-crontab paths without exporting their contents.
Export only allowlisted, format-constrained non-secret msmtp options; credentials,
aliases content and root-user configuration contents are excluded. Record root
override presence, the two sendmail link resolutions, up to 256 cron-directory
names and presence of the proposed test paths. Do not follow includes or invoke
cron, the reporter, needrestart, sendmail or msmtp.

Read package versions and timezone. Capture cron, timeservice, gpsd, munin-node
and msmtpd service identity/state before and after, plus boot and fixed-file
continuity. Compare historical closing boot and selected protected hashes;
record differences without repairing them. Missing optional files and unresolved
options remain evidence gaps; completion is not approval of a test or route.

Code arrives over SSH stdin to `sudo -n /usr/bin/python3 -I -B -` with remote
working directory `/`. No target staging, cron installation, failure injection,
service changes, lock acquisition, message, network probe or cleanup. SSH/sudo
and these reads can generate ordinary audit logs. No environment, credentials,
mail bodies, unrelated cron contents or relay/container contact is captured.

Per command: 10 seconds and 1 MiB per stream. Fixed files: 1 MiB each. Remote:
240 seconds. Controller: 270 seconds, 24 MiB per stream. Register the exclusive
local receipt before SSH. Retain partial evidence on interruption; never replay.

After separate exact-hash approval, from the repository root:
`python3 -I -B ntpsec/scripts/run-cron-mail-inspection.py execute --directory {spec['directory']} --sha256 APPROVED_SHA256`

This stage establishes inputs for a later exact-message test review. It cannot
close OBS-04, infer current relay delivery, or authorize a notification.
'''


def validate(spec):
    expected = {'schema', 'purpose', 'operation_id', 'directory', 'prepared_epoch',
                'expires_epoch', 'baseline_boot_id', 'baseline_file_hashes',
                'baseline_capture_sha256', 'members'}
    if (set(spec) != expected or spec['schema'] != 1
            or spec['purpose'] != 'obs04-cron-mail-readiness'
            or not re.fullmatch(r'obs04-cron-mail-readiness-[a-z0-9-]{1,40}', spec['operation_id'])
            or Path(spec['directory']).name != spec['operation_id']
            or not Path(spec['directory']).is_absolute()
            or spec['expires_epoch'] - spec['prepared_epoch'] != 86400
            or set(spec['baseline_file_hashes']) != {'/etc/ntp.conf', '/etc/cron.d/needrestart_check',
                '/usr/local/sbin/needrestart.sh', '/usr/local/libexec/ntp-maintenance-success.py'}
            or not all(re.fullmatch(r'[a-f0-9]{64}', v) for v in
                [*spec['baseline_file_hashes'].values(), spec['baseline_capture_sha256']])
            or not re.fullmatch(r'[a-f0-9-]{36}', spec['baseline_boot_id'])):
        raise ValueError('closed OBS-04 inspection scope required')


def prepare(directory, digest):
    raw = h.private(directory/'inspection.tar', 8*h.LIMIT)
    if h.sha(raw) != digest:
        raise ValueError('approved archive digest mismatch')
    names = set(SOURCES) | {'known_hosts', 'spec.json', 'review.md'}
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        members = archive.getmembers()
        if (len(members) != len(names) or {m.name for m in members} != names
                or any(not m.isfile() or m.size > h.LIMIT for m in members)):
            raise ValueError('closed bounded archive required')
        files = {m.name: archive.extractfile(m).read() for m in members}
    spec = json.loads(files['spec.json']); validate(spec)
    if (spec['members'] != {n: h.sha(files[n]) for n in set(SOURCES) | {'known_hosts'}}
            or files['review.md'] != review(spec).encode()
            or spec['directory'] != str(directory.absolute())):
        raise ValueError('review/member/directory binding mismatch')
    for n, path in SOURCES.items():
        if files[n] != path.read_bytes():
            raise ValueError('repository source drift')
    for n in ('spec.json', 'review.md', 'known_hosts'):
        if h.private(directory/n) != files[n]:
            raise ValueError('local approval input drift')
    if not spec['prepared_epoch']-300 <= time.time() < spec['expires_epoch']-270:
        raise ValueError('inspection validity window')
    return spec, files


def seal(args):
    baseline = args.baseline
    outcome = json.loads(h.private(baseline/'outcome.json'))
    capture_raw = h.private(baseline/'stdout.txt', 24*h.LIMIT)
    capture = json.loads(capture_raw)
    if (outcome.get('growth_checkpoint_node_accepted') is not True
            or h.sha(capture_raw) != outcome['capture_sha256']
            or h.sha(h.private(baseline/'execution.json')) != outcome['execution_receipt_sha256']
            or h.sha(h.private(baseline/'inspection.tar', 16*h.LIMIT)) != outcome['archive_sha256']
            or capture.get('capture_complete') is not True):
        raise ValueError('accepted closing node baseline required')
    with tarfile.open(fileobj=io.BytesIO(h.private(baseline/'inspection.tar', 16*h.LIMIT))) as archive:
        selected_members = [m for m in archive.getmembers() if m.name in ('spec.json', 'known_hosts')]
        if (len(selected_members) != 2 or len({m.name for m in selected_members}) != 2
                or any(not m.isfile() or m.size > h.LIMIT for m in selected_members)):
            raise ValueError('baseline data member identity/bounds')
        old = json.loads(archive.extractfile('spec.json').read())
        known_hosts = archive.extractfile('known_hosts').read()
    if (capture['spec_sha256'] != h.sha(h.encoded(old))
            or capture['operation_id'] != old['operation_id']
            or old['hostname'] != 'j2-svntp1' or old['endpoint'] != '10.1.0.51'
            or old['host_key_alias'] != '10.1.0.137'):
        raise ValueError('baseline target/spec binding')
    now = int(time.time())
    selected = ('/etc/ntp.conf', '/etc/cron.d/needrestart_check',
                '/usr/local/sbin/needrestart.sh', '/usr/local/libexec/ntp-maintenance-success.py')
    spec = {'schema': 1, 'purpose': 'obs04-cron-mail-readiness',
            'operation_id': args.output.name, 'directory': str(args.output.absolute()),
            'prepared_epoch': now, 'expires_epoch': now+86400,
            'baseline_boot_id': old['boot_id'],
            'baseline_file_hashes': {p: capture['before']['file_hashes'][p] for p in selected},
            'baseline_capture_sha256': h.sha(capture_raw), 'members': {}}
    validate(spec)
    files = {n: p.read_bytes() for n, p in SOURCES.items()}
    files['known_hosts'] = known_hosts
    spec['members'] = {n: h.sha(v) for n, v in files.items()}
    files.update({'spec.json': h.encoded(spec), 'review.md': review(spec).encode()})
    os.umask(0o077); args.output.mkdir(mode=0o700)
    for n, v in files.items():
        (args.output/n).write_bytes(v)
    with tarfile.open(args.output/'inspection.tar', 'w') as archive:
        for n, v in sorted(files.items()):
            member = tarfile.TarInfo(n); member.size = len(v); member.mode = 0o600
            archive.addfile(member, io.BytesIO(v))
    digest = h.sha((args.output/'inspection.tar').read_bytes())
    prepare(args.output, digest)
    result = {'sha256': digest, 'expires_epoch': spec['expires_epoch'],
              'execution_ready': True, 'execution_approved': False, 'target_contact': False}
    (args.output/'sealing.json').write_bytes(h.encoded(result))
    return result


def payload(spec, files):
    return (b"__name__='obs04_inspection'\n__file__='/sealed/runner.py'\n"+files['runner.py']
        + b"\nns={'__name__':'helper','__file__':'/sealed/helper.py'}\nexec(compile("
        + repr(files['helper.py']).encode()+b",ns['__file__'],'exec'),ns)\nh=types.SimpleNamespace(**ns)\n"
        + b'signal.signal(signal.SIGALRM,h.expired)\nsignal.alarm(240)\nprint(json.dumps(collect('
        + repr(spec).encode()+b')))\n')


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
    result.update(bundle_sha256=args.sha256, capture_complete=False, obs04_accepted=False)
    if result.get('returncode') == 0 and 'error' not in result:
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


def main():
    global h
    module = importlib.util.spec_from_file_location('helper', SOURCES['helper.py'])
    h = importlib.util.module_from_spec(module); module.loader.exec_module(h)
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    s = sub.add_parser('seal'); s.add_argument('--baseline', type=Path, required=True)
    s.add_argument('--output', type=Path, required=True)
    for name in ('check', 'execute'):
        p = sub.add_parser(name); p.add_argument('--directory', type=Path, required=True)
        p.add_argument('--sha256', required=True)
    args = parser.parse_args()
    if args.action == 'seal':
        result = seal(args)
    elif args.action == 'check':
        prepare(args.directory.absolute(), args.sha256); result = {'integrity': True, 'target_contact': False}
    else:
        result = execute(args)
    print(json.dumps(result))
    if args.action == 'execute' and not result['capture_complete']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
