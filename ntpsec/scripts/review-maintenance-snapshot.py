#!/usr/bin/python3
"""Seal one maintenance snapshot/native-parser stage; no refresh or installation."""
import argparse
import base64
import hashlib
import stat
import subprocess
import types
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import tarfile
import time

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {'runner.py': Path(__file__).resolve(),
           'collector.py': ROOT/'scripts/maintenance-snapshot.py',
           'helper.py': ROOT/'scripts/run-production-inspection.py',
           'tests.py': ROOT/'tests/test_maintenance_snapshot.py',
           'procedure.md': ROOT/'docs/BASE-OS-MAINTENANCE.md'}


# Same strict transport/file boundaries as the qualified watchdog controller.
# Kept self-contained: this stage must not import a sibling's uncommitted runner.
LIMIT = 1024**2
ENV = {'PATH': '/usr/bin:/bin', 'LC_ALL': 'C', 'PYTHONDONTWRITEBYTECODE': '1'}


def encoded(v): return (json.dumps(v, sort_keys=True)+'\n').encode()


def sha(raw): return hashlib.sha256(raw).hexdigest()


def require(ok, why):
    if not ok: raise ValueError(why)


def private_dir(path):
    path = Path(path).absolute()
    require(path.resolve() == path, 'indirect evidence directory')
    info = path.stat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
            and not info.st_mode & 0o077, 'owner-private evidence directory required')
    return path


def read(path, limit=16*LIMIT):
    require(path.resolve() == path.absolute(), 'indirect input')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as f:
        info = os.fstat(f.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                and info.st_nlink == 1 and not info.st_mode & 0o077, 'private regular input')
        raw = f.read(limit+1)
        require(len(raw) <= limit, 'input size bound')
        require(os.fstat(f.fileno()).st_mtime_ns == info.st_mtime_ns, 'input changed')
        return raw


def create(path, value):
    raw = value if isinstance(value, bytes) else encoded(value)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as f:
        f.write(raw); f.flush(); os.fsync(f.fileno())
    parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try: os.fsync(parent)
    finally: os.close(parent)


def module(name, raw):
    m = types.ModuleType(name); m.__file__ = '/sealed/'+name+'.py'
    exec(compile(raw, m.__file__, 'exec'), m.__dict__)
    return m


def authentication(path):
    """Validate an external secret reference without recording private key bytes."""
    path = Path(path).absolute()
    require(path.resolve() == path, 'indirect authentication input')
    info = path.stat()
    require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
            and info.st_nlink == 1 and not info.st_mode & 0o077, 'private authentication input')
    parent = path.parent.stat()
    require(parent.st_uid == os.getuid() and not parent.st_mode & 0o022, 'authentication parent permissions')
    proc = subprocess.run(['/usr/bin/ssh-keygen', '-y', '-P', '', '-f', str(path)],
                          capture_output=True, timeout=5, env=ENV)
    require(proc.returncode == 0, 'identity unavailable for noninteractive authentication')
    parts = proc.stdout.split()
    require(len(parts) in (2, 3) and parts[0] == b'ssh-ed25519', 'Ed25519 identity required')
    after = path.stat()
    fields = ('st_dev', 'st_ino', 'st_mode', 'st_uid', 'st_nlink', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
    require(all(getattr(after, k) == getattr(info, k) for k in fields), 'authentication input changed')
    fingerprint = 'SHA256:'+base64.b64encode(hashlib.sha256(base64.b64decode(parts[1], validate=True)).digest()).decode().rstrip('=')
    return {'identity_file': str(path), 'public_fingerprint': fingerprint,
            'agent': 'none', 'method': 'publickey'}


def ssh(directory, spec):
    opts = ['IdentityAgent=none', 'IdentitiesOnly=yes', 'PreferredAuthentications=publickey',
            'PasswordAuthentication=no', 'KbdInteractiveAuthentication=no', 'BatchMode=yes', 'StrictHostKeyChecking=yes', 'HostKeyAlgorithms=ssh-ed25519',
            'UpdateHostKeys=no', 'ProxyCommand=none', 'ProxyJump=none', 'ControlMaster=no',
            'ControlPath=none', 'ControlPersist=no', 'PermitLocalCommand=no', 'ClearAllForwardings=yes',
            'ForwardAgent=no', 'ForwardX11=no', 'GlobalKnownHostsFile=/dev/null',
            'UserKnownHostsFile='+str(directory/'known_hosts'), 'HostKeyAlias=10.1.0.137',
            'ConnectTimeout=3', 'ConnectionAttempts=1', 'ServerAliveInterval=5', 'ServerAliveCountMax=1']
    return ['/usr/bin/ssh', '-F', '/dev/null', '-T', '-i', spec['authentication']['identity_file'], *[v for x in opts for v in ('-o', x)],
            'ama@10.1.0.51', "cd / && sudo -n /usr/bin/python3 -I -B -c 'import sys; exec(sys.stdin.buffer.readline())'"]


def review(spec):
    return f'''# Maintenance snapshot and native ALSA parser qualification

Sealed, unexecuted. Separate exact-hash approval required. Target j2-svntp1 only,
`ama@10.1.0.51`, strict Ed25519 alias `10.1.0.137`. Operation `{spec['operation_id']}`.
Validity: epoch {spec['prepared_epoch']} through {spec['expires_epoch']}; require
five minutes remaining. Boot `{spec['boot']}` and kernel `{spec['kernel_release']}`
are pinned; drift consumes any submitted attempt without retry.

## Scope

One streamed isolated Python worker under noninteractive sudo from ama UID 1000.
No remote code installation. External SSH key reference
`{spec['authentication']['identity_file']}`; public fingerprint
`{spec['authentication']['public_fingerprint']}`. Owner/mode/link and public-key
checks precede the exclusive fsynced receipt. No key bytes exported; no agent,
password, alternate host or implicit SSH configuration. Local controller helpers
supply authentication, transport and protected local files only; this entrypoint
cannot dispatch the panic runner or metadata resolver.

The frozen collector defines the exact paths and commands. Read installed package
inventory, selections, audit, architectures, effective apt-config dump, rpi-eeprom
package file list, native udev version, process names (no arguments/environments),
package-lock owners from /proc/locks, root/boot/staging capacity and mount metadata.
Inspect bounded direct configuration membership/content in APT sources/preferences,
APT/dpkg/needrestart configuration, cron and all four udev rules search paths;
public key metadata/hashes only. Inspect explicit EEPROM update policy, staging
file metadata/hashes, NTP/GPSD/watchdog configuration and selected native tools.
Capture package status/extended-state hashes, live APT-list metadata and selected
unit files/drop-ins. Compare selected ntpd/GPSD/cron/Munin/watchdog process IDs,
parent IDs, start ticks, executable links and binary hashes before/after.
Record symlink destinations without exporting linked file contents. Unexpected
nested configuration or unsupported inputs stop or remain explicit assessment gaps.

Read only systemctl show properties for timeservice, gpsd service/socket, cron,
munin-node, watchdog, rpi-eeprom-update, apt-daily/upgrade and unattended-upgrades;
timer queries omit service-only properties. Active APT jobs, package processes,
held locks or dpkg audit findings prevent parser staging. Observed quiet state
is not a reservation against later timer activity. Before/after configuration,
package-state, boot and service identity must match; a race invalidates acceptance.

Private APT authentication, mail credentials, environments and private keys are
not selected. Potential credential-bearing configuration lines are suppressed and
marked unresolved; retain all output privately. Redaction or an uninspected hook
reference is not resolved policy. No hook, EEPROM tool, needrestart, plugin,
maintenance job or captured configuration is executed.

## Native parser and restoration

Create exactly `/var/tmp/{spec['operation_id']}` root-owned 0700, exclusively;
existing paths reject. Write only sealed baseline.rules and candidate.rules 0600.
Both bytes are frozen from the accepted maintenance draft; require the current
vendor rule hash to equal the baseline before staging. Run `/usr/bin/udevadm
verify FILE` once for each. Require baseline exit 1 and candidate exit 0; assess
diagnostics before accepting the result. This is static syntax verification, not
audio/device behavior or deployment. No udev test, trigger, reload or publication.

Remove only the two recorded regular single-link file inodes and their verified
directory. Changed membership/identity stops cleanup and records exact residue;
never recurse or remove an unrelated path. Normal failure and catchable interrupt
attempt cleanup. Host loss/SIGKILL can leave this exact private directory; record
uncertainty and obtain scoped recovery approval, never retry automatically.

Worker 180 seconds, controller 200 seconds, commands 12 seconds/1 MiB per stream;
16 MiB per hashed file, 64 KiB per text file, 256 entries/directory, 768 total files,
1 MiB configuration snapshot and 8 MiB transport output. Completed fields, failed
commands and cleanup results are retained on failure. A consumed receipt forbids
replay. Routine SSH/sudo access logging and the isolated scratch files are the only
intended target writes. No network repository access, APT refresh, package action,
service change, reboot, panic, device access or notification.

## Acceptance and next stage

Require complete bounded capture, identity/configuration/package/service continuity,
quiet package controls and proved scratch removal. Independently assess native
parser diagnostics, source/key policy, pins/holds, hooks, firmware staging and
concurrency before approving a resolution specification. Collector completion does
not accept maintenance readiness or prove that the OS is current.

Fresh signed-metadata resolution remains separate: bind this accepted capture and
reviewed sources/keyrings; isolated lists/cache/status only, no live hooks or
package writes. The old foundation resolver selects pinned additions and must not
be used as a full-update plan. Exact full-update solver coverage and package
provenance, effects and recovery require their own qualification and approval.
OBS-02/D1–D5 and bounded OBS-04 unchanged. Panic and OBS-09 remain held.

After exact-hash approval, from homelab-ntp:
`python3 -I -B ntpsec/scripts/review-maintenance-snapshot.py inspect --directory {spec['directory']} --sha256 APPROVED_SHA256`
'''


def unpack(raw):
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        rows = archive.getmembers()
        require(len(rows) == len({m.name for m in rows}) and all(m.isfile() and m.size <= 2**20 for m in rows), 'archive members')
        return {m.name: archive.extractfile(m).read() for m in rows}


def check(directory, digest, live=False):
    directory = private_dir(directory)
    raw = read(directory/'inspection.tar')
    require(sha(raw) == digest, 'archive digest')
    files = unpack(raw)
    require(set(files) == set(SOURCES) | {'spejson', 'review.md', 'known_hosts', 'baseline.rules',
              'candidate.rules', 'qualification.json', 'prior-outcome.json'}, 'closed archive')
    spec = json.loads(files['spejson'])
    require(spec['purpose'] == 'maintenance-snapshot-native-parser' and spec['hostname'] == 'j2-svntp1', 'scope')
    require(re.fullmatch(r'base-os-maintenance-snapshot-[0-9]{8}-v[0-9]+', spec['operation_id'])
              and directory.name == spec['operation_id'] and str(directory) == spec['directory'], 'directory binding')
    require(spec['expires_epoch']-spec['prepared_epoch'] == 86400, 'validity')
    require(files['review.md'] == review(spec).encode(), 'review binding')
    require(spec['members'] == {n:sha(v) for n,v in files.items() if n not in ('spejson', 'review.md')}, 'member hashes')
    for name, path in SOURCES.items():
        require(path.read_bytes() == files[name], 'repository drift: '+name)
    for name, raw in files.items():
        require(read(directory/name) == raw, 'local artifact drift: '+name)
    if live:
        require(spec['prepared_epoch']-300 <= time.time() < spec['expires_epoch']-300, 'execution window')
    return spec, files


def payload(spec, files):
    # All implementation is pinned repository source, not a target import.
    program = 'import types, json\n'
    program += 'h=types.ModuleType("helper"); h.__file__="/sealed/helper.py"\nexec(compile('+repr(files['helper.py'])+',"helper.py","exec"),h.__dict__)\n'
    program += 'w=types.ModuleType("collector"); w.__file__="/sealed/collector.py"\nexec(compile('+repr(files['collector.py'])+',"collector.py","exec"),w.__dict__)\nw.h=h\n'
    program += 'print(json.dumps(w.collect('+repr(spec)+','+repr(files['baseline.rules'])+','+repr(files['candidate.rules'])+'),sort_keys=True))\n'
    return ('exec('+repr(program)+')\n').encode()


def inspect(directory, digest):
    spec, files = check(directory, digest, live=True)
    require(authentication(spec['authentication']['identity_file']) == spec['authentication'], 'authentication drift')
    create(directory/'execution.json', {'sha256': digest, 'epoch': time.time(), 'purpose': spec['purpose']})
    result = {'capture_complete': False, 'production_accepted': False, 'no_retry': True}
    try:
        h = module('helper', files['helper.py'])
        row = h.bounded(ssh(directory, spec), timeout=200, limit=8*1024**2,
                        payload=payload(spec, files), env=ENV)
        create(directory/'transport.json', row)
        require(row.get('returncode') == 0 and not row.get('error'), 'transport incomplete')
        capture = json.loads(row['stdout'])
        create(directory/'capture.json', capture)
        require(capture['operation_id'] == spec['operation_id'] and capture['capture_complete'] is True, 'snapshot incomplete')
        result['capture_complete'] = True
        result['capture_sha256'] = sha(read(directory/'capture.json'))
    except (Exception, KeyboardInterrupt) as error:
        result.update(held=True, error=str(error))
    create(directory/'result.json', result)
    return result


def seal(args):
    directory = args.directory.absolute()
    require(not directory.exists(), 'existing operation')
    prior = private_dir(args.baseline.absolute())
    outcome_raw = read(prior/'outcome.json')
    outcome = json.loads(outcome_raw)
    require(outcome.get('capture_accepted') is True and outcome.get('udev_rule_defect_confirmed') is True, 'accepted prior capture')
    for name, digest in outcome['evidence_sha256'].items():
        require(Path(name).name == name and sha(read(prior/name)) == digest, 'prior evidence drift')
    prior_archive = read(prior/'execution.tar')
    require(sha(prior_archive) == outcome['archive_sha256'], 'prior archive drift')
    prior_files = unpack(prior_archive)
    draft = private_dir(args.draft.absolute())
    draft_raw = read(draft/'review.tar')
    require(sha(draft_raw) == args.draft_sha256, 'draft hash')
    draft_files = unpack(draft_raw)
    files = {n:p.read_bytes() for n,p in SOURCES.items()}
    proof = json.loads(read(args.qualification.absolute()))
    require(proof.get('sources') == {n:sha(v) for n,v in files.items()} and proof.get('tests_exit') == 0
              and proof.get('target_contact') is False
              and proof.get('checks', {}).get('native-baseline') == 1
              and proof.get('checks', {}).get('native-candidate') == 0, 'qualification binding')
    files.update({'qualification.json': encoded(proof), 'prior-outcome.json': outcome_raw,
                  'known_hosts': prior_files['known_hosts'], 'baseline.rules': draft_files['baseline.rules'],
                  'candidate.rules': draft_files['90-alsa-restore.rules']})
    require(re.fullmatch(rb'10\.1\.0\.137 ssh-ed25519 [A-Za-z0-9+/=]+\n?', files['known_hosts']), 'host pin')
    now = int(time.time())
    spec = {'schema': 1, 'purpose': 'maintenance-snapshot-native-parser', 'operation_id': directory.name,
            'directory': str(directory), 'prepared_epoch': now, 'expires_epoch': now+86400,
            'hostname': 'j2-svntp1', 'boot': outcome['boot'], 'kernel_release': '6.18.50+rpt-rpi-v8',
            'authentication': authentication(args.identity_file), 'draft_sha256': args.draft_sha256,
            'prior_archive_sha256': outcome['archive_sha256'], 'members': {n:sha(v) for n,v in files.items()}}
    require(re.fullmatch(r'base-os-maintenance-snapshot-[0-9]{8}-v[0-9]+', directory.name), 'operation identity')
    files.update({'spejson': encoded(spec), 'review.md': review(spec).encode()})
    directory.mkdir(mode=0o700)
    for name, raw in files.items():
        create(directory/name, raw)
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w', format=tarfile.USTAR_FORMAT) as archive:
        for name, raw in sorted(files.items()):
            info = tarfile.TarInfo(name); info.size = len(raw); info.mode = 0o600
            archive.addfile(info, io.BytesIO(raw))
    create(directory/'inspection.tar', buffer.getvalue())
    digest = sha(buffer.getvalue())
    check(directory, digest)
    result = {'sha256': digest, 'execution_ready': True, 'execution_approved': False,
              'target_contact': False, 'expires_epoch': spec['expires_epoch']}
    create(directory/'sealing.json', result)
    return result


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    p = sub.add_parser('seal')
    for name in ('directory', 'baseline', 'draft', 'qualification', 'identity-file'):
        p.add_argument('--'+name, type=Path, required=True)
    p.add_argument('--draft-sha256', required=True)
    for action in ('check', 'inspect'):
        p = sub.add_parser(action)
        p.add_argument('--directory', type=Path, required=True)
        p.add_argument('--sha256', required=True)
    args = parser.parse_args()
    if args.action == 'seal':
        result = seal(args)
    elif args.action == 'check':
        check(args.directory.absolute(), args.sha256)
        result = {'integrity': True, 'target_contact': False}
    else:
        result = inspect(args.directory.absolute(), args.sha256)
    print(json.dumps(result, sort_keys=True))
    if result.get('held'):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
