#!/usr/bin/python3
"""Seal one controlled cron-originated mail transaction; never retry a send."""
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
import types

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {'runner.py': ROOT/'scripts/run-obs04-cron-test.py',
           'worker.py': ROOT/'scripts/obs04-cron-test.py',
           'helper.py': ROOT/'scripts/run-production-inspection.py',
           'tests.py': ROOT/'tests/test_obs04_cron_test.py',
           'cron.template': ROOT/'templates/needrestart.cron.example'}
DATA = {'known_hosts', 'body.txt', 'diagnostic.txt', 'preview.eml', 'message.json', 'native.json'}
PROTECTED = {'/etc/ntp.conf', '/etc/cron.d/needrestart_check', '/usr/local/sbin/needrestart.sh',
    '/usr/local/libexec/ntp-maintenance-success.py', '/etc/msmtprc', '/etc/aliases',
    '/etc/default/cron', '/etc/environment', '/usr/sbin/cron', '/usr/bin/msmtp',
    '/usr/lib/systemd/system/cron.service'}
h = None


def command(spec):
    return '/usr/bin/python3 -I -B /var/lib/ntp-obs04/'+spec['operation_id']+'/worker.py gate 2>/dev/null'


def subject(spec):
    return 'Cron <root@j2-svntp1> '+command(spec)


def production_wrapper(raw):
    rendered = raw.replace(b'@CRON_RECIPIENT@', b'notify.failure@mailrise.xyz').replace(
        b'@ALERT_RECIPIENT@', b'notify@mailrise.xyz')
    lines = [line for line in rendered.decode().splitlines() if line.startswith('30 5 ')]
    if len(lines) != 1 or lines[0].split(None, 6)[:6] != ['30', '5', '*', '*', '*', 'root']:
        raise ValueError('production wrapper schedule changed')
    wrapper = lines[0].split(None, 6)[6]
    if '%' in wrapper.replace('\\%', ''):
        raise ValueError('production cron percent contract')
    return rendered, wrapper.replace('\\%', '%').encode()


def message(spec, body):
    return {'recipient': 'notify.failure@mailrise.xyz',
        'envelope_sender': 'j2-svntp1@local.theama.co', 'subject': subject(spec),
        'body_sha256': h.sha(body), 'body_file': 'body.txt', 'attachments': [],
        'body_digest_representation': 'Exactly one ASCII !; SMTP may append one terminal LF/CRLF. Remove at most that terminal line ending before digest comparison.',
        'native_generated_headers': ['Date', 'Message-ID', 'X-Cron-Env', 'From display name',
                                     'transport Received/return-path headers'],
        'generated_headers_are_not_whole_wire_hash_bound': True,
        'content_type': 'text/plain; charset=UTF-8', 'content_transfer_encoding': '8bit',
        'approval_scope': 'one native cron mail attempt, with possible downstream fanout/partial delivery; no retry'}


def preview(spec, body):
    return ('From: CronDaemon <j2-svntp1@local.theama.co>\nTo: notify.failure@mailrise.xyz\n'
        +'Subject: '+subject(spec)+'\nMIME-Version: 1.0\nContent-Type: text/plain; charset=UTF-8\n'
        +'Content-Transfer-Encoding: 8bit\n\n').encode()+body+b'\n'


def review(spec):
    return f'''# OBS-04 controlled cron failure — executable review

**Unexecuted; requires separate exact-hash approval including one notification.**
Target j2-svntp1, `ama@10.1.0.51`, pinned Ed25519 alias `10.1.0.137`.
Operation `{spec['operation_id']}`. Expires at Unix epoch {spec['expires_epoch']}.

## Exact message and native evidence

Recipient: `notify.failure@mailrise.xyz`. Envelope sender:
`j2-svntp1@local.theama.co`. No attachments. Exact subject:
`{subject(spec)}`

Read [body](body.txt), [message contract](message.json) and [preview](preview.eml).
The preview omits runtime Date, Message-ID, X-Cron-Env and transport-generated
headers. The From display name is scheduler/mailer generated; the envelope
sender, recipient, subject and decoded body are fixed. Approval covers these
explicitly generated header classes, not a fictitious exact whole-wire hash.
The approved body is exactly one ASCII exclamation mark (`!`). SMTP may append
one terminal LF/CRLF; that line-ending framing is excluded from the body digest.
The full [failure diagnostic](diagnostic.txt) is validated privately, not mailed.

The official cron 3.0pl1-197 ARM64 package matches the accepted capture's binary,
unit and defaults hashes. Version-pinned, patched source establishes the subject
and native mailer arguments. Defaults have `EXTRA_OPTS=""`: short subject hostname
and log level 1, so no `(failed)` suffix. Captured msmtp policy forces the sender.
See [native proof](native.json). Current daemon arguments were not live-captured;
the transaction requires exactly `/usr/sbin/cron -f` and exact hostname
`j2-svntp1` before publication and again before output. Mismatch aborts without
installing/sending; it is not permission to adjust the daemon or message.

## Scope and scheduling

Pin accepted boot, cron/time-service identities, protected files, native binaries,
unit/defaults, mail config/aliases and authored worker bytes. Require running
cron/time/monitoring, no cron drop-ins and no root-user msmtp override. No existing
service, daily reporter entry, production lock or success record is modified.

One exclusive local controller receipt precedes SSH. Publish a separate
`/etc/cron.d/obs04_cron_failure` and root-private
`/var/lib/ntp-obs04/{spec['operation_id']}`. Keep stage evidence permanently until
later authorized cleanup. Register an independent, operation-owned transient
withdrawal timer before publishing the cron entry; no daemon reload/restart.
All code and non-secret inputs are sealed repository sources/data.

The reviewed scheduling rule selects and records one explicit host-local minute
at installation: the first whole minute strictly after now + 180 seconds. Reject
if within 15 minutes of ordinary 05:30 reporting, if fewer than 90 seconds of
publication lead remain, or if the approved expiry cannot accommodate recovery.
This replaces the draft's preselected-minute proposal to avoid stale approval
times; the fixed scheduling algorithm cannot change the approved message.
The entry is date/month limited; a durable attempt claim, boot guard and a
90-second post-due release window suppress repeats, including future-year matches.

## Failure and mail path

The installed reporter rejects `--obs04-controlled-failure` before scanning,
direct mail or success recording. Its inspected production failure wrapper is
used with only that argument and a private lock substituted. Require status 2
and byte-exact inspected diagnostic. All unexpected output stays private and
quiet. Require ancestry from the pinned actual cron daemon, then release the
approved single-byte marker once to its empty, anonymous regular output file.
This version uses a native tmpfile, not a pipe; PIPE_BUF is inapplicable. A
one-byte write has no nonempty partial prefix. The worker never invokes
sendmail/msmtp or an independent sender.

This covers argument-failure propagation and genuine cron marker delivery,
not transmission of the diagnostic, an internal scanner crash or every
maintenance failure. Native cron buffers the
job's output and invokes its mailer once. A release intent without a completed
record is uncertain and permanently consumed; there is no automatic resend.

## Observation, restoration and interruption

The controller makes one install connection, waits until the recorded due minute
+75 seconds, then makes one observe, one withdraw and one terminal-observe
connection. Each connection is bounded to 90 seconds and 4 MiB per stream.
Remote actions are limited to 60 seconds; gate execution to 45 seconds. The
installer and control actions use SSH stdin with no alternate-endpoint retry.
At most five SSH connections are possible: after an uncertain install, permit
one observation and conditional withdrawal/terminal observation, never install
again. Retain full controller/transport status and partial evidence privately.

The independent timer withdraws only this byte-identical root-owned cron entry
at due + approximately 180 seconds, even if the controller disappears. The gate
becomes quiet after due +90 seconds or a boot change. Withdrawal does not kill
cron or any mailer and does not cancel already submitted mail. Foreign files,
source/config drift, missing evidence or ambiguous process/mail status remain
held. No packages, normal jobs, mail queue, relay services or target credentials
are changed. Authored stage/receipt evidence remains; no broad deletion is allowed.

Observe own attempt/release records, service identity continuity and a bounded
selection of cron/recipient-specific journal entries. Lack of an MTA error is
not asserted to prove submission. Concurrent mail/log ambiguity holds acceptance.
The independent cleanup unit may remain in its own terminal/collected state;
ordinary services must remain unchanged and the authored cron entry absent.

OBS-04 closure requires reviewed daemon-origin evidence, exact one-use output,
submission disposition, restored normal reporting and operator-confirmed
downstream receipt for this subject/body. SMTP success alone is insufficient;
SMTP failure may coexist with partial delivery. Never retry an uncertain send.
This controller records no automatic delivery/OBS-04 acceptance. Qualified
OBS-02 and D1–D5 are unchanged; final observation is not started.

After approving the exact archive and message, execute from the repository root:
`python3 -I -B ntpsec/scripts/run-obs04-cron-test.py execute --directory {spec['directory']} --sha256 APPROVED_SHA256`
'''


def validate(spec):
    keys = {'schema', 'purpose', 'operation_id', 'directory', 'prepared_epoch', 'expires_epoch',
            'schedule_rule', 'boot_id', 'fixed_units', 'protected_files', 'input_hashes',
            'body_sha256', 'diagnostic_sha256', 'wrapper_base64', 'members'}
    if (set(spec) != keys or spec['purpose'] != 'obs04-controlled-cron-failure' or spec['schema'] != 1
            or not re.fullmatch(r'obs04-cron-failure-[a-z0-9-]{1,36}', spec['operation_id'])
            or Path(spec['directory']).name != spec['operation_id']
            or not Path(spec['directory']).is_absolute()
            or spec['expires_epoch']-spec['prepared_epoch'] != 86400
            or spec['schedule_rule'] != 'first whole minute strictly after install_now+180s'
            or set(spec['protected_files']) != PROTECTED
            or set(spec['fixed_units']) != {'cron.service', 'timeservice.service'}
            or any(set(row) != {'MainPID', 'InvocationID', 'NRestarts'}
                   for row in spec['fixed_units'].values())
            or set(spec['input_hashes']) != {'worker.py', 'helper.py', 'body.txt', 'diagnostic.txt'}
            or len(base64.b64decode(spec['wrapper_base64'], validate=True)) > 8192
            or not all(re.fullmatch(r'[a-f0-9]{64}', v) for v in
                       [*spec['protected_files'].values(), *spec['input_hashes'].values(), spec['body_sha256'], spec['diagnostic_sha256']])):
        raise ValueError('closed controlled-test scope required')


def prepare(directory, digest):
    raw = h.private(directory/'execution.tar', 8*h.LIMIT)
    if h.sha(raw) != digest:
        raise ValueError('approved execution archive digest mismatch')
    names = set(SOURCES) | DATA | {'spec.json', 'review.md'}
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        members = archive.getmembers()
        if (len(members) != len(names) or {m.name for m in members} != names
                or any(not m.isfile() or m.size > h.LIMIT for m in members)):
            raise ValueError('closed bounded execution archive required')
        files = {m.name: archive.extractfile(m).read() for m in members}
    spec = json.loads(files['spec.json']); validate(spec)
    rendered, wrapper = production_wrapper(files['cron.template'])
    if (spec['members'] != {n: h.sha(files[n]) for n in set(SOURCES) | DATA}
            or spec['directory'] != str(directory.absolute())
            or files['review.md'] != review(spec).encode()
            or files['message.json'] != h.encoded(message(spec, files['body.txt']))
            or files['preview.eml'] != preview(spec, files['body.txt'])
            or h.sha(files['body.txt']) != spec['body_sha256']
            or files['body.txt'] != b'!'
            or h.sha(files['diagnostic.txt']) != spec['diagnostic_sha256']
            or base64.b64decode(spec['wrapper_base64'], validate=True) != wrapper
            or spec['protected_files']['/etc/cron.d/needrestart_check'] != h.sha(rendered)
            or any(h.sha(files[n]) != digest for n, digest in spec['input_hashes'].items())):
        raise ValueError('message/member/review binding mismatch')
    for n, path in SOURCES.items():
        if files[n] != path.read_bytes():
            raise ValueError('repository source drift')
    for n in ('spec.json', 'review.md', *DATA):
        if h.private(directory/n) != files[n]:
            raise ValueError('local approval input drift')
    if not spec['prepared_epoch']-300 <= time.time() < spec['expires_epoch']-900:
        raise ValueError('approved execution window')
    return spec, files


def seal(args):
    inspection = args.inspection
    outcome = json.loads(h.private(inspection/'outcome.json'))
    raw = h.private(inspection/'stdout.txt', 24*h.LIMIT)
    capture = json.loads(raw)
    archive_raw = h.private(inspection/'inspection.tar', 8*h.LIMIT)
    if (outcome.get('cron_mail_prerequisite_capture_accepted') is not True
            or h.sha(raw) != outcome['capture_sha256']
            or h.sha(archive_raw) != outcome['archive_sha256']
            or h.sha(h.private(inspection/'execution.json')) != outcome['execution_receipt_sha256']
            or capture.get('capture_complete') is not True):
        raise ValueError('accepted non-sending inspection required')
    with tarfile.open(fileobj=io.BytesIO(archive_raw)) as archive:
        selected = [m for m in archive.getmembers() if m.name in ('known_hosts', 'spec.json')]
        if (len(selected) != 2 or len({m.name for m in selected}) != 2
                or any(not m.isfile() or m.size > h.LIMIT for m in selected)):
            raise ValueError('inspection data member bounds/identity')
        known = archive.extractfile('known_hosts').read()
        old = json.loads(archive.extractfile('spec.json').read())
    if capture['spec_sha256'] != h.sha(h.encoded(old)) or capture['operation_id'] != old['operation_id']:
        raise ValueError('inspection spec binding')
    native_raw = h.private(args.native)
    native = json.loads(native_raw)
    for key, path in [('observed_binary_sha256', '/usr/sbin/cron'),
                      ('defaults_sha256', '/etc/default/cron'),
                      ('unit_sha256', '/usr/lib/systemd/system/cron.service')]:
        if native[key] != capture['files'][path]['sha256']:
            raise ValueError('native qualification/capture mismatch')
    if (native.get('qualified') is not True or native['version'] != '3.0pl1-197'
            or native['default_log_level'] != 1 or native['default_fqdn_subject'] != 0
            or native['subject_template'] != 'Subject: Cron <%s@%s> %s%s\n'
            or native['extra_opts'] != ''
            or native.get('native_output_sink') != 'anonymous_regular_file'
            or native.get('approved_output_strategy') != 'single_ASCII_marker'):
        raise ValueError('native subject qualification incomplete')
    diagnostic = h.private(args.diagnostic)
    body = b'!'
    if not diagnostic or len(diagnostic) > 4096 or not diagnostic.startswith(b"Error: unknown option '--obs04-controlled-failure'.\n"):
        raise ValueError('bounded controlled-failure body required')
    files = {n: path.read_bytes() for n, path in SOURCES.items()}
    rendered, wrapper = production_wrapper(files['cron.template'])
    actual_cron = base64.b64decode(capture['files']['/etc/cron.d/needrestart_check']['base64'], validate=True)
    if actual_cron != rendered:
        raise ValueError('current production wrapper differs from repository template')
    now = int(time.time())
    rows = {name: dict(line.split('=', 1) for line in value['stdout'].splitlines() if '=' in line)
            for name, value in capture['units_before'].items()}
    spec = {'schema': 1, 'purpose': 'obs04-controlled-cron-failure',
        'operation_id': args.output.name, 'directory': str(args.output.absolute()),
        'prepared_epoch': now, 'expires_epoch': now+86400,
        'schedule_rule': 'first whole minute strictly after install_now+180s',
        'boot_id': capture['boot_before'],
        'fixed_units': {n: {k: rows[n][k] for k in ('MainPID', 'InvocationID', 'NRestarts')}
                        for n in ('cron.service', 'timeservice.service')},
        'protected_files': {n: capture['files'][n]['sha256'] for n in PROTECTED},
        'input_hashes': {}, 'body_sha256': h.sha(body), 'diagnostic_sha256': h.sha(diagnostic),
        'wrapper_base64': base64.b64encode(wrapper).decode(), 'members': {}}
    files.update({'known_hosts': known, 'native.json': native_raw, 'body.txt': body, 'diagnostic.txt': diagnostic})
    spec['input_hashes'] = {n: h.sha(files[n]) for n in ('worker.py', 'helper.py', 'body.txt', 'diagnostic.txt')}
    files['message.json'] = h.encoded(message(spec, body)); files['preview.eml'] = preview(spec, body)
    spec['members'] = {n: h.sha(v) for n, v in files.items()}
    validate(spec)
    files.update({'spec.json': h.encoded(spec), 'review.md': review(spec).encode()})
    os.umask(0o077); args.output.mkdir(mode=0o700)
    for n, raw in files.items(): (args.output/n).write_bytes(raw)
    with tarfile.open(args.output/'execution.tar', 'w') as archive:
        for n, raw in sorted(files.items()):
            info = tarfile.TarInfo(n); info.mode = 0o600; info.size = len(raw)
            archive.addfile(info, io.BytesIO(raw))
    digest = h.sha((args.output/'execution.tar').read_bytes())
    prepare(args.output, digest)
    result = {'sha256': digest, 'expires_epoch': spec['expires_epoch'],
        'execution_ready': True, 'execution_approved': False, 'send_approved': False,
        'target_contact': False, 'message_sha256': h.sha(files['message.json']),
        'preview_sha256': h.sha(files['preview.eml'])}
    (args.output/'sealing.json').write_bytes(h.encoded(result))
    return result


def remote(spec, files, action):
    if action not in ('install', 'observe', 'withdraw'):
        raise ValueError('closed remote action')
    data = (b"import types,signal,json\nns={'__name__':'helper','__file__':'/sealed/helper.py'}\nexec(compile("
        +repr(files['helper.py']).encode()+b",ns['__file__'],'exec'),ns)\nh=types.SimpleNamespace(**ns)\n"
        +b"w={'__name__':'worker','__file__':'/sealed/worker.py'}\nexec(compile("
        +repr(files['worker.py']).encode()+b",w['__file__'],'exec'),w)\nw['h']=h\n"
        +b'signal.signal(signal.SIGALRM,h.expired)\nsignal.alarm(60)\n')
    expression = "w['"+action+"']("+repr(spec)
    if action == 'install':
        expression += ', '+repr({n: files[n] for n in spec['input_hashes']})
    return data+('print(json.dumps('+expression+')))\n').encode()


def execute(args):
    os.umask(0o077); directory = args.directory.absolute()
    spec, files = prepare(directory, args.sha256)
    argv = h.ssh_argv({'endpoints': ['10.1.0.51'], 'host_key_alias': '10.1.0.137'}, directory)
    with (directory/'execution.json').open('xb') as stream:
        stream.write(h.encoded({'archive_sha256': args.sha256, 'epoch': time.time(), 'argv': argv,
            'payload_hashes': {a: h.sha(remote(spec, files, a)) for a in ('install', 'observe', 'withdraw')}}))
        stream.flush(); os.fsync(stream.fileno())
    steps = []
    def call(action):
        index = len(steps)
        try:
            response = h.bounded(argv, timeout=90, limit=4*h.LIMIT,
                payload=remote(spec, files, action), env=os.environ.copy())
        except OSError as error:
            response = {'returncode': None, 'error': type(error).__name__, 'stdout': '', 'stderr': ''}
        raw = response.pop('stdout'); (directory/f'{index}-{action}-stdout.txt').write_text(raw)
        (directory/f'{index}-{action}-stderr.txt').write_text(response.pop('stderr'))
        response.update(action=action, index=index)
        data = None
        if response.get('returncode') == 0 and not response.get('error'):
            try:
                data = json.loads(raw)
            except ValueError:
                response['error'] = 'unparseable control response'
        steps.append(response)
        (directory/'steps.json').write_bytes(h.encoded(steps))
        print(json.dumps({'phase': action, 'index': index, 'completed': data is not None}), flush=True)
        return data
    installed = call('install')
    if installed and installed.get('installed'):
        deadline = installed['due_epoch']+75
        print(json.dumps({'phase': 'waiting for scheduled cron', 'due_epoch': installed['due_epoch'],
                          'observe_epoch': deadline}), flush=True)
        while time.time() < deadline:
            time.sleep(min(30, deadline-time.time()))
    observed = call('observe')
    withdrawn = call('withdraw') if observed else None
    terminal = call('observe') if withdrawn else None
    result = {'archive_sha256': args.sha256, 'steps': steps,
        'installed_response_received': bool(installed), 'terminal_response_received': bool(terminal),
        'authored_cron_absent': bool(terminal and terminal['cron_record'].get('missing')),
        'gate_record': (terminal or observed or {}).get('records', {}).get('gate.json'),
        'native_mail_and_service_evidence_requires_review': True,
        'delivery_accepted': False, 'obs04_accepted': False, 'retry_performed': False}
    (directory/'result.json').write_bytes(h.encoded(result))
    return result


def main():
    global h
    module = importlib.util.spec_from_file_location('helper', SOURCES['helper.py'])
    h = importlib.util.module_from_spec(module); module.loader.exec_module(h)
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    s = sub.add_parser('seal'); s.add_argument('--inspection', type=Path, required=True)
    s.add_argument('--native', type=Path, required=True); s.add_argument('--diagnostic', type=Path, required=True)
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
    if args.action == 'execute' and not result['authored_cron_absent']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
