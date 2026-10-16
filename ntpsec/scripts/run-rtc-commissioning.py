#!/usr/bin/python3
"""Seal and execute separate utility-install and RTC-write operations."""
import argparse
import base64
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import tarfile
import time

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    entry = importlib.util.spec_from_file_location(name.replace('-', '_'), ROOT/'scripts'/name)
    result = importlib.util.module_from_spec(entry); entry.loader.exec_module(result)
    return result


helper = module('run-production-inspection.py')
worker = module('rtc-commissioning.py')


def review(spec):
    common = f"""Target: **{spec['hostname']}**, current boot `{spec['boot_id']}`.
Operation: `{spec['operation_id']}`; expires at epoch {spec['expires_epoch']}.
Pinned SSH endpoint `{spec['endpoints'][0]}`, alias `{spec['host_key_alias']}`.
One execution only, using current repository code and flat inputs.

Preflight requires the same Trixie arm64 host/boot, clean dpkg audit, running
timeservice, unchanged absent /etc/adjtime, and protected configuration readback.
Writes a root-private operation record under `/var/lib/ntp-rtc-{spec['operation_id']}`.
No automatic retry, service restart, reboot, fake-clock change or udev edit.
SSH transport is limited to 600 seconds; remote capture to 570 seconds. Partial
transport results require inspection of retained state before another action.
"""
    if spec['action'] == 'install':
        detail = f"""# RTC utility installation review

Install only util-linux-extra {worker.VERSION}, arm64, from the sealed 290088-byte
Debian payload SHA-256 `{worker.PACKAGE_SHA}`. No APT refresh/download, dependency
installation, upgrade or removal of existing packages is authorized.

Require existing libaudit1 >= 1:2.2.1, libc6 >= 2.38, libsmartcols1 = {worker.VERSION},
zlib1g >= 1:1.1.4, util-linux >= 2.40.4-4~; if installed, initscripts >= 3.08-2~.
Stop before mutation on missing/incompatible dependencies, dpkg invocation hooks,
existing payload files or relevant diversions. The package must be uninstalled.

The full package is installed, including its other interactive/filesystem tools
and manuals. Reviewed preinst adds six no-rename /sbin diversions: ctrlaltdel,
fsck.cramfs, fsck.minix, mkfs.bfs, mkfs.cramfs, mkfs.minix to .usr-is-merged names.
Reviewed postrm removes those diversions. Normal dpkg database/log updates and
installed trigger processing (including manual indexing) are within scope.
No package postinst or service units are supplied by this payload.

Run `/usr/bin/dpkg --install` on the root-private sealed payload. Accept only the
exact package version, verified package files and hwclock/manual SHA-256, clean
dpkg audit, unchanged other package states and time-service invocation, and
unchanged protected clock configuration. Do not invoke hwclock in this stage.
On installation/acceptance failure, remove only this newly introduced package
with dpkg if other package states remain unchanged; verify audit and original
diversions. If removal or continuity checks fail, retain state and hold.
Interrupted transport does not establish rollback; do not retry blindly.
"""
    else:
        detail = f"""# RTC set/readback review

Prerequisite: the utility installation must be accepted first. Independently
verify util-linux-extra {worker.VERSION} and exact hwclock/manual bytes before
opening a device. This operation does not install packages.

Require the accepted RV3028 node at I2C 1-0052, /dev/rtc0 character identity 251:0,
matching driver and device-tree ancestry, LocalRTC=no and NTPSynchronized=yes.
Immediately before writing, require ntpq leap=00, stratum=1, refid=PPS,
absolute offset <= 1 ms and root dispersion <= 10 ms. Otherwise stop untouched.

Retain a read-only before sample, then execute exactly once:
`/usr/sbin/hwclock --systohc --utc --noadjfile --rtc=/dev/rtc0`
Read back with `--show --utc --noadjfile --rtc=/dev/rtc0` and sysfs since_epoch.
Accept the RTC epoch within the system-time bracket plus/minus two seconds,
with a bracket no longer than ten seconds. Recheck synchronized PPS, unchanged
time-service invocation, boot and protected configuration. /etc/adjtime remains
absent: this operation uses explicit UTC and does not create a drift policy.

No hctosys/system-clock step, adjustment, calibration, battery-flag clearing,
service change or reboot. A failed verification retains evidence and holds;
do not restore an aging pre-write timestamp or automatically repeat a write.
Recovery is a separately reviewed resynchronization from valid system time.
A successful write does not establish battery retention or reboot acceptance.
"""
    return detail+'\n'+common+"""
Execution after approval, from the repository root:
`python3 -I -B ntpsec/scripts/run-rtc-commissioning.py execute --bundle ABSOLUTE_BUNDLE --sha256 APPROVED_SHA256`
"""


def prepare(path, expected):
    raw = helper.private(path, 4*helper.LIMIT)
    if helper.sha(raw) != expected:
        raise ValueError('approved bundle hash mismatch')
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        members = archive.getmembers()
        if (len({m.name for m in members}) != len(members)
                or any(not m.isfile() or m.size > helper.LIMIT for m in members)):
            raise ValueError('bounded regular archive required')
        files = {m.name: archive.extractfile(m).read() for m in members}
    spec = json.loads(files['spec.json'])
    names = {'runner.py', 'worker.py', 'helper.py', 'tests.py', 'spec.json', 'review.md', 'known_hosts'}
    if spec['action'] == 'install':
        names.add('package.deb')
    if set(files) != names or spec['action'] not in ('install', 'set-readback'):
        raise ValueError('closed operation scope required')
    if (spec['hostname'] != 'j2-svntp1' or spec['endpoints'] != ['10.1.0.51', 'fd36:5aa8:6971:1::51']
            or spec['host_key_alias'] != '10.1.0.137'
            or not re.fullmatch('[a-z][a-z0-9-]{0,47}', spec['operation_id'])
            or not re.fullmatch('[a-f0-9-]{36}', spec['boot_id'])
            or not 0 < spec['expires_epoch']-spec['prepared_epoch'] <= 86400):
        raise ValueError('target/window scope mismatch')
    if spec['members'] != {n: helper.sha(v) for n, v in files.items() if n not in ('spec.json', 'review.md')}:
        raise ValueError('member manifest mismatch')
    if files['review.md'] != review(spec).encode():
        raise ValueError('review mismatch')
    current = {'runner.py': Path(__file__), 'worker.py': ROOT/'scripts/rtc-commissioning.py',
               'helper.py': ROOT/'scripts/run-production-inspection.py', 'tests.py': ROOT/'tests/test_rtc_commissioning.py'}
    if any(files[n] != p.read_bytes() for n, p in current.items()):
        raise ValueError('current repository input drift')
    for name in ('review.md', 'spec.json', 'known_hosts'):
        if helper.private(path.parent/name) != files[name]:
            raise ValueError('external approval input drift')
    if not spec['prepared_epoch']-300 <= time.time() < spec['expires_epoch']-600:
        raise ValueError('execution window closed')
    if spec['action'] == 'install' and helper.sha(files['package.deb']) != worker.PACKAGE_SHA:
        raise ValueError('package payload mismatch')
    return spec, files


def seal(args):
    source = args.inspection_dir
    old_seal = json.loads(helper.private(source/'sealing.json'))
    old_raw = helper.private(source/'production-inspection.tar', 4*helper.LIMIT)
    if helper.sha(old_raw) != args.inspection_sha256 or old_seal['sha256'] != args.inspection_sha256:
        raise ValueError('inspection baseline hash mismatch')
    result = json.loads(helper.private(source/'result.json'))
    if result.get('capture_complete') is not True or result.get('bundle_sha256') != args.inspection_sha256:
        raise ValueError('accepted inspection required')
    capture_raw = helper.private(source/'stdout.txt', 24*helper.LIMIT)
    capture = json.loads(capture_raw)
    with tarfile.open(fileobj=io.BytesIO(old_raw)) as archive:
        old = json.load(archive.extractfile('spec.json'))
        known = archive.extractfile('known_hosts').read()
    if (capture['spec_sha256'] != helper.sha(helper.encoded(old))
            or capture['hostname'] != old['hostname']
            or capture['boot_before'] != capture['boot_after']
            or old['members']['known_hosts'] != helper.sha(known)):
        raise ValueError('inspection identity binding mismatch')
    now = int(time.time())
    spec = {'schema': 1, 'action': args.action_name, 'operation_id': args.operation_id,
            'hostname': old['hostname'], 'endpoints': old['endpoints'], 'host_key_alias': old['host_key_alias'],
            'boot_id': capture['boot_after'], 'inspection_sha256': args.inspection_sha256,
            'capture_sha256': helper.sha(capture_raw), 'prepared_epoch': now, 'expires_epoch': now+86400}
    files = {'runner.py': Path(__file__).read_bytes(), 'worker.py': (ROOT/'scripts/rtc-commissioning.py').read_bytes(),
             'helper.py': (ROOT/'scripts/run-production-inspection.py').read_bytes(),
             'tests.py': (ROOT/'tests/test_rtc_commissioning.py').read_bytes(), 'known_hosts': known}
    if args.action_name == 'install':
        raw = helper.private(args.package, helper.LIMIT)
        if helper.sha(raw) != worker.PACKAGE_SHA:
            raise ValueError('package digest mismatch')
        files['package.deb'] = raw
        # Read package contents locally, without running any ARM64 executable or maintainer script.
        import subprocess
        listing = subprocess.run(['/usr/bin/dpkg-deb', '--fsys-tarfile', str(args.package)], capture_output=True, check=True)
        with tarfile.open(fileobj=io.BytesIO(listing.stdout)) as archive:
            spec['payload_paths'] = ['/'+m.name.removeprefix('./') for m in archive.getmembers() if not m.isdir()]
        if any(not p.startswith('/usr/') or '..' in Path(p).parts for p in spec['payload_paths']):
            raise ValueError('unexpected package payload path')
    spec['members'] = {n: helper.sha(v) for n, v in files.items()}
    files.update({'spec.json': helper.encoded(spec), 'review.md': review(spec).encode()})
    os.umask(0o077); args.output.mkdir(mode=0o700)
    for name in ('spec.json', 'review.md', 'known_hosts'):
        (args.output/name).write_bytes(files[name])
    bundle = args.output/'rtc-commissioning.tar'
    with tarfile.open(bundle, 'w') as archive:
        for name, raw in sorted(files.items()):
            item = tarfile.TarInfo(name); item.size = len(raw); item.mode = 0o600
            archive.addfile(item, io.BytesIO(raw))
    digest = helper.sha(bundle.read_bytes()); prepare(bundle, digest)
    result = {'sha256': digest, 'bundle': str(bundle), 'expires_epoch': spec['expires_epoch'],
              'execution_authorized': False, 'target_contact': False}
    (args.output/'sealing.json').write_bytes(helper.encoded(result))
    return result


def execute(args):
    spec, files = prepare(args.bundle, args.sha256)
    # Reuse the already exercised bounded stdin transport; import only pinned repository bytes.
    payload = ("import types,signal,json\nhelper=types.ModuleType('helper')\n"
               "helper.__file__='/sealed/helper.py'\nexec("+repr(files['helper.py'])+",helper.__dict__)\n"
               "space={'__name__':'rtc_worker','helper':helper}\nexec("+repr(files['worker.py'])+",space)\n"
               "signal.signal(signal.SIGALRM,helper.expired)\nsignal.alarm(570)\n"
               "print(json.dumps(space['run']("+repr(spec)+","+repr(base64.b64encode(files.get('package.deb', b'')).decode())+")))\n").encode()
    argv = helper.ssh_argv(spec, args.bundle.parent)
    with (args.bundle.parent/'execution.json').open('xb') as stream:
        stream.write(helper.encoded({'epoch': int(time.time()), 'sha256': args.sha256,
                                     'payload_sha256': helper.sha(payload), 'argv': argv}))
        stream.flush(); os.fsync(stream.fileno())
    try:
        result = helper.bounded(argv, timeout=600, limit=24*helper.LIMIT, payload=payload, env=os.environ.copy())
    except OSError as error:
        result = {'returncode': None, 'error': str(error), 'stdout': '', 'stderr': ''}
    for name in ('stdout', 'stderr'):
        (args.bundle.parent/(name+'.txt')).write_text(result.pop(name))
    result['accepted'] = False
    if result.get('returncode') == 0 and 'error' not in result:
        try:
            state = json.loads((args.bundle.parent/'stdout.txt').read_text())
            result['accepted'] = state.get('accepted') is True and state['operation_id'] == spec['operation_id'] and state['action'] == spec['action']
        except (ValueError, KeyError) as error:
            result['error'] = str(error)
    result['bundle_sha256'] = args.sha256
    (args.bundle.parent/'result.json').write_bytes(helper.encoded(result))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    s = sub.add_parser('seal'); s.add_argument('--action-name', choices=['install', 'set-readback'], required=True)
    s.add_argument('--inspection-dir', type=Path, required=True); s.add_argument('--inspection-sha256', required=True)
    s.add_argument('--operation-id', required=True); s.add_argument('--output', type=Path, required=True)
    s.add_argument('--package', type=Path)
    s = sub.add_parser('execute'); s.add_argument('--bundle', type=Path, required=True); s.add_argument('--sha256', required=True)
    args = parser.parse_args(); result = seal(args) if args.command == 'seal' else execute(args)
    print(json.dumps(result))
    if args.command == 'execute' and not result['accepted']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
