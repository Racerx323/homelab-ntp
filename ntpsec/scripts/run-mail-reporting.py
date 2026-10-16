#!/usr/bin/python3
"""Seal reporter capture tests and daily cron activation after confirmed delivery."""
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
SOURCES = {'runner.py': ROOT/'scripts/run-mail-reporting.py',
           'worker.py': ROOT/'scripts/mail-reporting.py',
           'base.py': ROOT/'scripts/mail-install.py',
           'helper.py': ROOT/'scripts/run-production-inspection.py',
           'tests.py': ROOT/'tests/test_mail_reporting.py',
           'reporter.sh': ROOT.parents[1]/'homelab-server-configs/Needrestart/scripts/needrestart.sh',
           'cron.template': ROOT/'templates/needrestart.cron.example',
           'policy.json': ROOT/'configs/j2-svntp1-mail.json'}
DATA = {'known_hosts', 'msmtprc', 'aliases', 'cron.pending', 'delivery.json'}


def load(path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


h = load(SOURCES['helper.py'])


def review(spec):
    return f'''# Needrestart capture acceptance and daily reporting activation

Operation `{spec['operation_id']}`; target `ama@10.1.0.51` (`j2-svntp1`),
SSH host-key alias `10.1.0.137`. One execution; expires epoch {spec['expires_epoch']}.
Baseline is the accepted mail installation and operator-confirmed receipt of both
synthetic notifications. Boot `{spec['boot_id']}` and existing NTP identity are pinned.

## Preconditions and acceptance

Require the accepted 701-package inventory, clean dpkg audit, unchanged installed
reporter, msmtp/alias/pending-cron bytes and root ownership/modes, unchanged msmtp
binary and masked/inactive msmtpd, no root-user msmtp overrides, unchanged protected
NTP/leap/needrestart files, America/Chicago timezone, and cron already running/enabled.
Require `/etc/cron.d/needrestart_check` absent. No package or service changes.

In a new root-private `/var/lib/ntp-mail-reporting-{spec['operation_id']}` directory,
run a copy of the pinned shared reporter through the exact cron shell wrapper.
Replace only its seven literal `/usr/sbin/sendmail` references with a private
capture helper; the installed reporter is unchanged. Capture files use exclusive
creation and contain any generated message, without contacting SMTP. Run the real
bounded list-only needrestart scan (NEEDRESTART_MODE=l); require successful status
and quiet cron output. A quiet scan may produce no report message.

For the failure fixture, additionally replace its four `/usr/sbin/needrestart`
references with a private scanner that prints a clearly synthetic failure and
exits 23. Require the reporter's failure message captured, status 23 preserved,
and diagnostic output exposed by the cron wrapper. Hold the private fixture lock
and require status 1 and the exact overlap fallback, with the reporter skipped.
The production scanner, lock, script and services are never replaced for these tests.
Raw reports remain private. No immediate test notification is sent.

## Activation and ongoing notifications

After all captures and continuity checks pass, install the exact previously staged
cron bytes as `/etc/cron.d/needrestart_check`, root:root 0644, using a hidden staging
file and an exclusive atomic link. Require more than 15 minutes before the next
scheduled run. Retain the pending source. Do not restart cron or invoke the live
reporter. Record the next 05:30 America/Chicago occurrence; cron uses the confirmed
host timezone, including local daylight-saving rules.

Approval of this stage authorizes recurring daily reporting: RECIPIENT is
`notify@mailrise.xyz`; cron failure output goes to `notify.failure@mailrise.xyz`.
The shared reporter generates its From header as root@observed-hostname and its
subject/body from scan results; the existing msmtp configuration remains unchanged.
These are ongoing operational reports, not additional fixed-message test sends.
The exact cron and reporter sources are included in this bundle for review.

Captured-mail tests validate reporter/wrapper behavior; they do not prove cron's
mail generation or the next scheduled run. Previously confirmed synthetic delivery
proves both recipient routes. First scheduled execution and any resulting delivery
remain pending observation; do not declare full reporting acceptance from capture tests.

## Failure and recovery

Any failed preflight or capture blocks cron installation. After publication, remove
only the byte-identical root-owned 0644 cron file authored by this operation on a
failed postcondition; hold for inspection on foreign drift. Retain private captures
and receipts. Do not remove installed mail packages/configuration, restart NTP, or
send recovery mail. Interruptions are not automatically retried; inspect state first.
Already generated recurring messages cannot be recalled.

## Execution

From /home/aaron/code/homelab-ntp, after approving sealing.json's archive SHA-256:

```text
python3 -I -B ntpsec/scripts/run-mail-reporting.py execute --directory OUTPUT --sha256 APPROVED_SHA256
```

Use this review directory for OUTPUT. The runner writes an exclusive execution
receipt before SSH, captures both streams and transport status, and is single-use.
'''


def seal(args):
    d = args.baseline
    result = json.loads(h.private(d/'result.json'))
    raw = h.private(d/'stdout.txt', 24*h.LIMIT)
    state = json.loads(raw)
    confirmation = h.private(d/'operator-delivery-confirmation.json')
    receipt = json.loads(confirmation)
    archive = h.private(d/'mail-install.tar', 16*h.LIMIT)
    if not result.get('accepted') or not state.get('accepted') or h.sha(archive) != result['bundle_sha256']:
        raise ValueError('accepted installation required')
    if not receipt.get('report_received') or not receipt.get('failure_received') or receipt['operation_id'] != state['operation_id']:
        raise ValueError('operator delivery confirmation required')
    with tarfile.open(fileobj=io.BytesIO(archive)) as t:
        old = json.loads(t.extractfile('spec.json').read())
        previous = {name: t.extractfile(name).read() for name in DATA-{'delivery.json'}}
        old_reporter = t.extractfile('reporter.sh').read()
    if state['spec_sha256'] != h.sha(h.encoded(old)) or state['operation_id'] != old['operation_id']:
        raise ValueError('installation receipt binding')
    files = {name: path.read_bytes() for name, path in SOURCES.items()}
    if old_reporter != files['reporter.sh']:
        raise ValueError('installed reporter source changed')
    inventories = [c['stdout'] for c in state['commands'] if c['argv'][0] == '/usr/bin/dpkg-query']
    inventory = inventories[-1]
    if inventory != (ROOT/'configs/accepted-packages.tsv').read_text() or len(inventory.splitlines()) != 701:
        raise ValueError('accepted inventory mismatch')
    files.update(previous)
    files['delivery.json'] = confirmation
    now = int(time.time())
    spec = {'operation_id': args.output.name, 'hostname': 'j2-svntp1', 'boot_id': old['boot_id'],
            'service_identity': old['service_identity'], 'msmtp_binary_sha256': old['msmtp_binary_sha256'],
            'packages_before': dict((v[0], v[1:]) for v in (line.split('\t') for line in inventory.splitlines())),
            'baseline_bundle_sha256': result['bundle_sha256'], 'baseline_capture_sha256': h.sha(raw),
            'prepared_epoch': now, 'expires_epoch': now+86400,
            'members': {name: h.sha(data) for name, data in files.items()}}
    files['spec.json'] = h.encoded(spec)
    files['review.md'] = review(spec).encode()
    os.umask(0o077)
    args.output.mkdir(mode=0o700)
    for name, data in files.items():
        (args.output/name).write_bytes(data)
    with tarfile.open(args.output/'mail-reporting.tar', 'w') as t:
        for name, data in sorted(files.items()):
            member = tarfile.TarInfo(name)
            member.size = len(data)
            member.mode = 0o600
            t.addfile(member, io.BytesIO(data))
    digest = h.sha((args.output/'mail-reporting.tar').read_bytes())
    prepare(args.output, digest)
    output = {'sha256': digest, 'expires_epoch': spec['expires_epoch'], 'target_contact': False, 'execution_authorized': False}
    (args.output/'sealing.json').write_bytes(h.encoded(output))
    return output


def prepare(directory, digest):
    raw = h.private(directory/'mail-reporting.tar', 16*h.LIMIT)
    if h.sha(raw) != digest:
        raise ValueError('archive digest mismatch')
    with tarfile.open(fileobj=io.BytesIO(raw)) as t:
        members = t.getmembers()
        if any(not m.isfile() or '/' in m.name or m.size > 4*h.LIMIT for m in members) or len({m.name for m in members}) != len(members):
            raise ValueError('flat regular archive required')
        files = {m.name: t.extractfile(m).read() for m in members}
    spec = json.loads(files['spec.json'])
    expected = set(SOURCES) | DATA
    if set(files) != expected | {'spec.json', 'review.md'} or spec['members'] != {name: h.sha(files[name]) for name in expected}:
        raise ValueError('member binding')
    for name, path in SOURCES.items():
        if files[name] != path.read_bytes():
            raise ValueError('current source drift')
    if not re.fullmatch(r'[a-z0-9-]{1,64}', spec['operation_id']) or spec['hostname'] != 'j2-svntp1':
        raise ValueError('identity')
    if not spec['prepared_epoch']-300 <= time.time() < spec['expires_epoch']-600:
        raise ValueError('expired review')
    policy = json.loads(files['policy.json'])
    cron = files['cron.template'].decode().replace('@CRON_RECIPIENT@', policy['failure_recipient']).replace('@ALERT_RECIPIENT@', policy['report_recipient']).encode()
    if files['cron.pending'] != cron or policy['report_recipient'] != 'notify@mailrise.xyz' or policy['failure_recipient'] != 'notify.failure@mailrise.xyz':
        raise ValueError('cron policy drift')
    if files['review.md'] != review(spec).encode():
        raise ValueError('review drift')
    for name in ('known_hosts', 'spec.json', 'review.md', 'cron.pending', 'reporter.sh'):
        if h.private(directory/name) != files[name]:
            raise ValueError('local review drift')
    return spec, files


def execute(args):
    os.umask(0o077)
    d = args.directory.absolute()
    spec, files = prepare(d, args.sha256)
    payload = b'import base64,json,os,signal,types\nos.umask(0o077)\n'
    for name, variable in [('helper.py', 'h'), ('base.py', 'base'), ('worker.py', 'worker')]:
        payload += b"ns={'__name__':'sealed','__file__':'/sealed/"+name.encode()+b"'}\nexec(compile("+repr(files[name]).encode()+b",ns['__file__'],'exec'),ns)\n"+variable.encode()+b'=types.SimpleNamespace(**ns)\n'
    payload += b'signal.signal(signal.SIGALRM,h.expired)\nsignal.alarm(540)\n'
    inputs = {k: base64.b64encode(files[k]).decode() for k in ('msmtprc', 'aliases', 'cron.pending', 'reporter.sh')}
    payload += b'inputs={k:base64.b64decode(v) for k,v in '+repr(inputs).encode()+b'.items()}\n'
    payload += b"print(json.dumps(worker.make_worker(base)("+repr(spec).encode()+b',inputs,h).run()))\n'
    argv = h.ssh_argv({'endpoints': ['10.1.0.51'], 'host_key_alias': '10.1.0.137'}, d)
    with (d/'execution.json').open('xb') as stream:
        stream.write(h.encoded({'bundle_sha256': args.sha256, 'argv': argv, 'epoch': int(time.time()), 'payload_sha256': h.sha(payload)}))
        stream.flush()
        os.fsync(stream.fileno())
    result = h.bounded(argv, timeout=570, limit=24*h.LIMIT, payload=payload, env=os.environ.copy())
    for name in ('stdout', 'stderr'):
        (d/(name+'.txt')).write_text(result.pop(name))
    result.update(bundle_sha256=args.sha256, accepted=False, scheduled_run_observed=False)
    if result.get('returncode') == 0 and not result.get('error'):
        try:
            state = json.loads((d/'stdout.txt').read_text())
            if state['operation_id'] != spec['operation_id'] or state['spec_sha256'] != h.sha(h.encoded(spec)):
                raise ValueError('result binding')
            result['accepted'] = all(state.get(k) is True for k in ('accepted', 'cron_active', 'runtime_capture_accepted', 'failure_capture_accepted', 'overlap_accepted'))
        except (ValueError, KeyError, TypeError) as error:
            result['error'] = str(error)
    (d/'result.json').write_bytes(h.encoded(result))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest='action', required=True)
    seal_args = actions.add_parser('seal')
    seal_args.add_argument('--baseline', type=Path, required=True)
    seal_args.add_argument('--output', type=Path, required=True)
    execution = actions.add_parser('execute')
    execution.add_argument('--directory', type=Path, required=True)
    execution.add_argument('--sha256', required=True)
    args = parser.parse_args()
    result = seal(args) if args.action == 'seal' else execute(args)
    print(json.dumps(result))
    if args.action == 'execute' and not result['accepted']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
