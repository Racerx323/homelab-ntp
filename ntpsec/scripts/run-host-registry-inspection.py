#!/usr/bin/python3
"""Seal and control one read-only inspection of a held hardware operation."""
import argparse
import base64
import fcntl
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import socket
import stat
import subprocess
import tarfile
import time

ROOT = Path(__file__).resolve().parents[1]
BOOT = ('/boot/firmware/config.txt', '/boot/firmware/cmdline.txt')
FIELDS = 'connection.id,connection.uuid,connection.type,connection.interface-name,connection.autoconnect,ipv4.method,ipv4.addresses,ipv4.gateway,ipv6.method,ipv6.addresses,ipv6.gateway'
INPUTS = {'worker.py', 'helper.py', 'hardware-spec.json', 'hardware-recovery.json',
          'architecture.md', 'operations.md', 'history.md'}
BASELINE_INPUTS = {'recovery.tar', 'recovery-acceptance.json', 'recovery-cleanup.json',
                   'inspect-runtime.py', 'inspect-source-destinations.py', 'runtime-recipe.json'}


def inputs(spec):
    return INPUTS | BASELINE_INPUTS if spec.get('operation') == 'host-baseline' else INPUTS


EXTRAS = {'spec.json', 'manifest.json', 'review.md', 'known_hosts', 'tests.py', 'transport.py'}


def encoded(value):
    return (json.dumps(value, sort_keys=True)+'\n').encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def module(name):
    spec = importlib.util.spec_from_file_location('registry_'+name.replace('-', '_'), ROOT/'scripts'/name)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def registry(text):
    result = {}
    for line in text.splitlines():
        key, kind = line.split(':', 1)
        if not re.fullmatch('[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}', key) or key in result:
            raise ValueError('unique canonical profile UUID required')
        if not re.fullmatch('[a-zA-Z0-9-]+', kind):
            raise ValueError('profile type required')
        result[key] = kind
    if not 1 <= len(result) <= 64:
        raise ValueError('bounded nonempty profile registry required')
    return result


def validate(spec, files):
    old = json.loads(files['hardware-spec.json'])
    receipt = json.loads(files['hardware-recovery.json'])
    uart = spec.get('operation') == 'host-uart-inspection'
    timing = spec.get('operation') == 'host-timing-inspection'
    if (spec['schema'] != 1 or spec['operation'] not in ('host-registry-inspection', 'host-baseline', 'host-uart-inspection', 'host-timing-inspection')
            or not re.fullmatch('[a-z][a-z0-9-]{0,47}', spec['operation_id'])
            or spec['stage'] != '/var/lib/ntp-inspect-'+spec['operation_id']
            or not re.fullmatch('/var/lib/ntp-host-[a-z][a-z0-9-]{0,47}', old['stage'])
            or old['operation'] != 'hardware' or spec['hostname'] != old['hostname']
            or spec['kernel'] != old['kernel'] or spec['ssh'] != old['ssh']
            or spec['old_ipv4'] != old['old_ipv4']
            or spec['endpoints'] != [old['recipe'][key].split('/')[0] for key in ('ipv4_address', 'ipv6_address')]
            or receipt['bundle_sha256'] != spec['hardware_bundle_sha256']
            or receipt['result']['phase'] != ('reboot_submitted' if timing else 'recovered' if uart else 'recovery_files_restored')
            or spec['members'].keys() != inputs(spec)
            or any(sha(files[n]) != v for n, v in spec['members'].items())
            or not 0 < spec['expires_epoch']-spec['prepared_epoch'] <= 86400):
        raise ValueError('held hardware/target/input binding required')
    if spec['operation'] == 'host-baseline':
        recovery_inputs(files, spec)
    if uart and (receipt['result'].get('transient_units_cleaned') is not True
                 or receipt['result'].get('recovered_boot_id') != spec['recovered_boot_id']
                 or not re.fullmatch('[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}', spec['recovered_boot_id'])):
        raise ValueError('completed hardware recovery/boot binding required')
    if timing and (receipt['result']['uart_observation']['boot_id'] != spec['candidate_boot_id']
                   or not re.fullmatch('[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}', spec['candidate_boot_id'])):
        raise ValueError('candidate hardware boot binding required')
    return old


def timing_metadata(sysroot=Path('/sys')):
    """Inspect PPS/RTC hierarchy and properties; exclude sample and clock reads."""
    def bounded(path):
        if path.is_symlink() or not path.is_file():
            raise ValueError('regular timing property required')
        with path.open('rb') as stream:
            raw = stream.read(4097)
        if len(raw) > 4096:
            raise ValueError('timing property bound exceeded')
        return base64.b64encode(raw).decode()

    def chain(path):
        node = path.resolve(strict=True)
        if not node.is_relative_to(sysroot/'devices'):
            raise ValueError('timing device escaped sysfs devices')
        result = []
        while node != sysroot/'devices':
            if len(result) >= 16:
                raise ValueError('timing ancestry depth exceeded')
            row = {'path': str(node), 'links': {}, 'properties': {}}
            for name in ('device', 'driver', 'subsystem', 'of_node'):
                link = node/name
                if not link.is_symlink():
                    continue
                target = link.resolve(strict=True)
                roots = {'device': [sysroot/'devices'], 'driver': [sysroot/'bus'],
                         'subsystem': [sysroot/'bus', sysroot/'class'],
                         'of_node': [sysroot/'firmware/devicetree/base']}[name]
                if not any(target.is_relative_to(root) for root in roots):
                    raise ValueError('timing link escaped approved tree')
                row['links'][name] = str(target)
                if name == 'of_node':
                    for prop in ('compatible','status','name','gpios','phandle','assert-falling-edge'):
                        if (target/prop).exists():
                            row['properties'][prop] = bounded(target/prop)
            result.append(row); node = node.parent
        return result

    result = {'classes': {}, 'pps_platform': {}, 'gpio_controller': {}}
    for kind, pattern in [('pps',r'pps[0-9]+'), ('rtc',r'rtc[0-9]+')]:
        directory = sysroot/'class'/kind
        entries = sorted(directory.iterdir()) if directory.exists() else []
        if len(entries) > 16:
            raise ValueError('timing class entry bound exceeded')
        for path in entries:
            if not re.fullmatch(pattern,path.name):
                raise ValueError('unexpected timing class entry')
            attrs = ('name','dev','path','mode') if kind == 'pps' else ('name','dev')
            result['classes'][path.name] = {'ancestors': chain(path), 'attributes':
                {n: bounded(path/n) for n in attrs if (path/n).exists()}}
    directory = sysroot/'bus/platform/drivers/pps-gpio'
    entries = sorted(directory.iterdir()) if directory.exists() else []
    if len(entries) > 32:
        raise ValueError('PPS driver entry bound exceeded')
    for path in entries:
        if path.name not in ('bind','unbind','uevent','module') and path.is_symlink():
            result['pps_platform'][path.name] = chain(path)
    gpio = sysroot/'firmware/devicetree/base/soc/gpio@7e200000'
    for prop in ('compatible','phandle'):
        if (gpio/prop).exists():
            result['gpio_controller'][prop] = bounded(gpio/prop)
    if len(encoded(result)) > 1024*1024:
        raise ValueError('timing metadata aggregate bound exceeded')
    return result


def uart_metadata(sysroot=Path('/sys'), devroot=Path('/dev')):
    """Read bounded sysfs metadata only; never open a device node."""
    def inside(path, parent):
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(parent) or resolved == parent:
            raise ValueError('UART metadata path escaped approved tree')
        return resolved

    def names(path, pattern):
        entries = sorted(p for p in path.iterdir() if re.fullmatch(pattern, p.name)) if path.exists() else []
        if len(entries) > 32:
            raise ValueError('UART metadata entry bound exceeded')
        return entries

    result = {'serial0': None, 'ttys': {}, 'amba_drivers': [], 'amba_devices': {}}
    alias = devroot/'serial0'
    if alias.is_symlink():
        target = inside(alias, devroot)
        if not re.fullmatch('tty(?:AMA|S)[0-9]+', target.name) or not stat.S_ISCHR(target.stat().st_mode):
            raise ValueError('unexpected serial0 character-device alias')
        result['serial0'] = str(target)
    elif alias.exists():
        raise ValueError('serial0 must be an alias')

    def metadata(node):
        entry = {'path': str(node), 'driver': None, 'of_node': None, 'properties': {}}
        if (node/'driver').is_symlink():
            entry['driver'] = str(inside(node/'driver', sysroot/'bus'))
        if (node/'of_node').is_symlink():
            dt = inside(node/'of_node', sysroot/'firmware/devicetree/base')
            entry['of_node'] = str(dt)
            for name in ('compatible', 'status', 'name'):
                path = dt/name
                if path.exists():
                    if path.is_symlink() or not path.is_file():
                        raise ValueError('regular device-tree property required')
                    with path.open('rb') as stream:
                        data = stream.read(4097)
                    if len(data) > 4096:
                        raise ValueError('device-tree property bound exceeded')
                    entry['properties'][name] = base64.b64encode(data).decode()
        return entry

    for tty in names(sysroot/'class/tty', r'tty(?:AMA|S)[0-9]+'):
        node = inside(tty, sysroot/'devices')
        chain = []
        while node != sysroot/'devices':
            if len(chain) >= 16:
                raise ValueError('UART parent depth bound exceeded')
            chain.append(metadata(node))
            node = node.parent
        result['ttys'][tty.name] = chain
    for driver in names(sysroot/'bus/amba/drivers', r'[a-zA-Z0-9_.:-]+'):
        inside(driver, sysroot/'bus/amba/drivers')
        result['amba_drivers'].append(driver.name)
    for device in names(sysroot/'bus/amba/devices', r'[a-zA-Z0-9_.:@-]+'):
        result['amba_devices'][device.name] = metadata(inside(device, sysroot/'devices'))
    if len(encoded(result)) > 1024*1024:
        raise ValueError('UART metadata aggregate bound exceeded')
    return result


def private_root_file(h, path, limit=8*1024**2):
    data = h.read(path, limit=limit)
    if stat.S_IMODE(path.lstat().st_mode) != 0o600:
        raise ValueError('private root evidence required')
    return data


def collect(h, spec, files):
    old = validate(spec, files)
    root = Path(old['stage'])
    h.ancestors(root)
    if stat.S_IMODE(root.stat().st_mode) != 0o700:
        raise ValueError('private retained stage required')
    # Share the existing operation lock; never create or rewrite its files.
    private_root_file(h, root/'.lock')
    fd = os.open(root/'.lock', os.O_RDONLY | os.O_NOFOLLOW)
    try:
        fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        if private_root_file(h, root/'spec.json') != files['hardware-spec.json']:
            raise ValueError('retained specification drift')
        for name, digest in old['members'].items():
            if not re.fullmatch('[a-z][a-z0-9.-]+', name) or sha(private_root_file(h, root/name)) != digest:
                raise ValueError('retained member drift')
        retained = {name: private_root_file(h, root/name) for name in ('state.json', 'before.json', 'commands.jsonl')}
        if spec.get('operation') == 'host-baseline':
            recovery, recovery_files = recovery_inputs(files, spec)
            verify_recovery_stage(h, recovery, recovery_files, files)
            state = json.loads(retained['state.json'])
            if (state['phase'] != 'recovered' or state.get('transient_units_cleaned') is not True
                    or state['recovered_boot_id'] != spec['recovered_boot_id']):
                raise ValueError('completed original recovery required')
        elif json.loads(retained['state.json']) != json.loads(files['hardware-recovery.json'])['result']:
            raise ValueError('recovered state drift; inspect scope needs review')
        boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        if spec.get('operation') == 'host-uart-inspection' and boot != spec['recovered_boot_id']:
            raise ValueError('recovered UART inspection boot changed')
        if spec.get('operation') == 'host-timing-inspection' and boot != spec['candidate_boot_id']:
            raise ValueError('candidate timing inspection boot changed')
        report = {'schema': 1, 'hostname': socket.gethostname(), 'kernel': os.uname().release,
                  'boot_id': boot, 'collected_epoch': int(time.time()),
                  'retained': {n: base64.b64encode(v).decode() for n, v in retained.items()},
                  'retained_sha256': {n: sha(v) for n, v in retained.items()}, 'boot_files': {}, 'queries': {}}
        for name in BOOT:
            data = h.read(Path(name), limit=256*1024)
            info = Path(name).lstat()
            report['boot_files'][name] = {'sha256': sha(data), 'base64': base64.b64encode(data).decode(),
                                        'mode': stat.S_IMODE(info.st_mode), 'uid': info.st_uid, 'gid': info.st_gid}
        deadline = time.monotonic()+90
        def query(label, argv):
            remaining = deadline-time.monotonic()
            if remaining <= 0:
                raise ValueError('capture deadline exceeded')
            p = subprocess.run(argv, capture_output=True, timeout=min(10, remaining), check=False,
                               env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LC_ALL': 'C', 'HOME': '/root'})
            if len(p.stdout)+len(p.stderr) > 512*1024:
                raise ValueError('query output exceeds bound')
            report['queries'][label] = {'argv': argv, 'status': p.returncode,
                                       'stdout': p.stdout.decode(), 'stderr': p.stderr.decode()}
            if len(encoded(report['queries'])) > 2*1024**2:
                raise ValueError('aggregate query output exceeds bound')
            if p.returncode:
                raise ValueError('read-only query failed: '+label)
            return p.stdout.decode()
        current = registry(query('registry', ['/usr/bin/nmcli', '-t', '-f', 'UUID,TYPE', 'connection', 'show']))
        report['expected_registry'] = dict(json.loads(retained['before.json'])['registry'])
        report['expected_registry'][old['network_candidate_uuid']] = '802-3-ethernet'
        report['current_registry'] = current
        for uuid in sorted(current):
            query('profile-'+uuid, ['/usr/bin/nmcli', '-t', '-f', FIELDS, 'connection', 'show', 'uuid', uuid])
        query('active', ['/usr/bin/nmcli', '-t', '-f', 'UUID,TYPE,DEVICE', 'connection', 'show', '--active'])
        query('addresses', ['/usr/sbin/ip', '-j', 'address', 'show'])
        for family in ('-4', '-6'):
            query('routes'+family, ['/usr/sbin/ip', '-j', family, 'route', 'show'])
        query('cmdline', ['/usr/bin/cat', '/proc/cmdline'])
        if spec.get('operation') == 'host-timing-inspection':
            report['timing'] = timing_metadata()
            if report['timing'] != timing_metadata():
                raise ValueError('timing metadata changed during capture')
            for path, name in zip(BOOT, ('config-candidate.txt','cmdline-candidate.txt')):
                if report['boot_files'][path]['sha256'] != old['members'][name]:
                    raise ValueError('candidate boot-file drift')
        if spec.get('operation') == 'host-uart-inspection':
            report['uart'] = uart_metadata()
            if report['uart'] != uart_metadata():
                raise ValueError('UART metadata changed during capture')
            before = json.loads(retained['before.json'])
            if report['boot_files'] != before['boot_files']:
                raise ValueError('restored boot files drift')
        if registry(query('registry-end', ['/usr/bin/nmcli', '-t', '-f', 'UUID,TYPE', 'connection', 'show'])) != current:
            raise ValueError('registry changed during capture')
        if boot != Path('/proc/sys/kernel/random/boot_id').read_text().strip():
            raise ValueError('boot changed during capture')
        if any(private_root_file(h, root/n) != data for n, data in retained.items()):
            raise ValueError('retained state changed during capture')
        if spec.get('operation') == 'host-baseline':
            report['baseline'] = fresh_baseline(h, spec, files, old)
            if any(private_root_file(h, root/n) != data for n, data in retained.items()):
                raise ValueError('retained operation changed during baseline')
        report['checks'] = {'read_only_capture': True, 'retained_state_stable': True, 'registry_stable': True}
        return report
    finally:
        os.close(fd)


def worker(spec, files, mode, terminal_sha=None):
    validate(spec, files)
    if (os.geteuid() != 0 or os.environ.get('SUDO_USER') != 'ama'
            or os.environ.get('SUDO_UID') != '1000' or os.environ.get('SUDO_GID') != '1000'
            or socket.gethostname() != spec['hostname'] or os.uname().release != spec['kernel']):
        raise ValueError('approved sudo target identity required')
    ns = {'__name__': 'registry_helper'}
    exec(compile(files['helper.py'], 'sealed-helper', 'exec'), ns)
    h = type('Helper', (), ns)
    root = Path(spec['stage'])
    os.umask(0o077)
    if mode == 'capture':
        if not spec['prepared_epoch']-300 <= time.time() < spec['expires_epoch']:
            raise ValueError('inspection expired')
        h.ancestors(root.parent)
        root.mkdir(mode=0o700)
        h.sync(root.parent)
        for name, data in {**files, 'spec.json': encoded(spec)}.items():
            h.create(root/name, data)
        h.create(root/'started.json', encoded({'phase': 'capture_started'}))
        report = collect(h, spec, files)
        terminal = encoded(report)
        if len(terminal) > 16*1024**2:
            raise ValueError('terminal exceeds bound; preserve stage')
        h.create(root/'terminal.json', terminal)
    elif mode not in ('readback', 'cleanup'):
        raise ValueError('closed inspection mode required')
    h.ancestors(root)
    expected = inputs(spec) | {'spec.json', 'started.json', 'terminal.json'}
    if stat.S_IMODE(root.stat().st_mode) != 0o700 or {p.name for p in root.iterdir()} != expected:
        raise ValueError('incomplete or unknown inspection entries; preserve stage')
    for name, data in {**files, 'spec.json': encoded(spec)}.items():
        if private_root_file(h, root/name) != data:
            raise ValueError('inspection input drift')
    private_root_file(h, root/'started.json')
    terminal = private_root_file(h, root/'terminal.json', limit=16*1024**2)
    result = {'phase': 'captured', 'terminal_sha256': sha(terminal), 'report': json.loads(terminal)}
    if mode == 'cleanup':
        if terminal_sha != sha(terminal):
            raise ValueError('accepted terminal hash required before cleanup')
        for name in expected:
            (root/name).unlink()
        root.rmdir()
        h.sync(root.parent)
        result = {'phase': 'cleaned', 'terminal_sha256': terminal_sha}
    return result


def prepare(bundle, checksum):
    c = module('run-foundation-preflight.py')
    raw = c.private_file(bundle, 32*1024**2)
    if sha(raw) != checksum:
        raise ValueError('approved archive hash mismatch')
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:') as archive:
        members = archive.getmembers()
        if (len({m.name for m in members}) != len(members) or len(members) > 64
                or any(not m.isfile() or m.size > 16*1024**2 for m in members)):
            raise ValueError('closed bounded archive required')
        files = {m.name: archive.extractfile(m).read() for m in members}
    manifest = json.loads(files['manifest.json'])
    if (manifest != {n: sha(v) for n, v in files.items() if n != 'manifest.json'}
            or files['worker.py'] != Path(__file__).read_bytes()
            or files['helper.py'] != (ROOT/'scripts/foundation-install.py').read_bytes()
            or files['transport.py'] != (ROOT/'scripts/run-foundation-preflight.py').read_bytes()
            or files['known_hosts'] != c.private_file(bundle.parent/'known_hosts', 4096)
            or bundle.parent.stat().st_uid != os.getuid() or bundle.parent.stat().st_mode & 0o077):
        raise ValueError('manifest/launcher/transport/private path drift')
    spec = json.loads(files['spec.json'])
    if set(files) != inputs(spec) | EXTRAS:
        raise ValueError('closed baseline/inspection membership required')
    validate(spec, files)
    if c.host_key(files['known_hosts'], spec['old_ipv4']) != spec['ssh']['fingerprint']:
        raise ValueError('pinned host key mismatch')
    return spec, files


def seal(args):
    c = module('run-foundation-preflight.py')
    prior = module('run-host-configuration.py')
    timing = getattr(args, 'timing', False)
    if timing:
        raw = c.private_file(args.hardware_dir/'host-configuration.tar',32*1024**2)
        if sha(raw) != args.hardware_sha256:
            raise ValueError('exact candidate hardware archive required')
        previous = archive_inputs(raw); old = json.loads(previous['spec.json'])
    else:
        old, previous = prior.prepare(args.hardware_dir/'host-configuration.tar', args.hardware_sha256)
    uart = getattr(args, 'uart', False)
    recovery = c.private_file(args.hardware_dir/('readback-result.json' if timing else 'cleanup-result.json' if uart else 'recover-result.json'))
    files = {'worker.py': Path(__file__).read_bytes(), 'helper.py': (ROOT/'scripts/foundation-install.py').read_bytes(),
             'hardware-spec.json': previous['spec.json'], 'hardware-recovery.json': recovery,
             'known_hosts': previous['known_hosts'], 'tests.py': (ROOT/'tests/test_host_registry_inspection.py').read_bytes(),
             'transport.py': (ROOT/'scripts/run-foundation-preflight.py').read_bytes()}
    for label, path in (('architecture', 'docs/ntp-architecture-deployment-plan-v1.0.md'),
                        ('operations', 'docs/OPERATIONS.md'), ('history', 'HISTORY.md')):
        files[label+'.md'] = (ROOT/path).read_bytes()
    epoch = int(time.time())
    spec = {k: old[k] for k in ('hostname', 'kernel', 'ssh', 'old_ipv4')}
    spec.update(schema=1, operation='host-timing-inspection' if timing else 'host-uart-inspection' if uart else 'host-registry-inspection', operation_id=args.operation_id,
                stage='/var/lib/ntp-inspect-'+args.operation_id, prepared_epoch=epoch, expires_epoch=epoch+86400,
                endpoints=[old['recipe'][k].split('/')[0] for k in ('ipv4_address', 'ipv6_address')],
                hardware_bundle_sha256=args.hardware_sha256, members={n: sha(files[n]) for n in INPUTS})
    if uart:
        spec['recovered_boot_id'] = json.loads(recovery)['result']['recovered_boot_id']
    if timing:
        spec['candidate_boot_id'] = json.loads(recovery)['result']['uart_observation']['boot_id']
    validate(spec, files)
    files['spec.json'] = encoded(spec)
    files['review.md'] = (f'# Read-only registry inspection\n\nTarget: {spec["hostname"]}. Operation: {args.operation_id}.\n'
        f'Protected root staging: `{spec["stage"]}`. Expires epoch: {spec["expires_epoch"]}.\n'
        f'Hardware bundle: `{args.hardware_sha256}`.\n\n'
        'One capture via pinned-key IPv4 SSH, with conditional terminal readback via either fixed endpoint. '
        'Bind the exact retained hardware specification, all sealed member hashes and recovered state. '
        'Hold the existing operation lock shared while reading; preserve every original operation file. '
        'Read the retained state, before-state and command journal; current boot ID, kernel command line, '
        'both boot files and ownership/modes; NetworkManager UUID/type registry, public connection settings '
        'for at most 64 profiles, active connections, addresses and routes. No secrets, raw keyfiles, '
        'receiver/device I/O, profile writes, service changes or reboot.\n\n'
        'Only the new root-owned 0700 diagnostic stage and its 0600 inputs/report are created. '
        'Accept a complete report bound to this specification, stable boot/registry/retained state and '
        'successful queries. This is diagnostic acceptance, not hardware or network acceptance. '
        'Conditional readback recovers a completed terminal without rerunning capture; interrupted captures '
        'remain preserved and require a new review. Conditional cleanup requires the accepted terminal hash '
        'and removes only the closed set of new diagnostic stage files. Preserve local evidence and the '
        'original hardware stage. Cleanup uncertainty is held; never replay a consumed mode.\n\n'
        'Use this script execute --bundle ABSOLUTE_BUNDLE --sha256 APPROVED_HASH --mode capture; '
        'conditional modes are readback and cleanup. Each is registered locally before target contact. '
        'Fixed queries have 10-second bounds and a 90-second aggregate deadline; SSH is bounded to 180 seconds. '
        'Preparation is offline. Recovery continuation requires these findings and separate approval.\n').encode()
    if uart:
        files['review.md'] = files['review.md'].replace(b'Read-only registry inspection', b'Read-only UART/sysfs inspection')
        files['review.md'] = files['review.md'].replace(
            b'Recovery continuation requires these findings and separate approval.',
            b'Any corrected hardware stage requires these findings, fresh evidence and separate approval.')
        files['review.md'] += (
            '\nUART scope: bind the completed hardware recovery/cleanup and exact recovered boot. '
            'Require both boot files to match retained originals. Capture /dev/serial0 link/character-node metadata '
            '(never open it), ttyAMA/ttyS sysfs parent chains, driver links, and device-tree compatible/status/name '
            'properties; list AMBA driver names and AMBA device driver/device-tree metadata. '
            'Two matching metadata passes are required; at most 32 entries per collection, 16 parents per tty, '
            '4096 bytes per property and 1 MiB total UART metadata. Sysfs links must resolve within their approved trees. '
            'Do not bind/unbind drivers, load modules, write sysfs, read receiver data or change boot settings. '
            'Missing UART aliases/drivers are reportable observations, not hardware acceptance. '
            'This is the restored boot, not the failed candidate boot: it cannot establish the earlier live mapping. '
            'No corrective mutation or reboot is included. Incomplete captures remain preserved; recovery consists '
            'only of conditional terminal readback and hash-bound cleanup after diagnostic acceptance.\n').encode()
    if timing:
        files['review.md'] = files['review.md'].replace(b'Read-only registry inspection',b'Read-only candidate PPS/RTC inspection')
        files['review.md'] = files['review.md'].replace(b'and recovered state.',b'and held candidate state.')
        files['review.md'] = files['review.md'].replace(
            b'Recovery continuation requires these findings and separate approval.',
            b'The retained hardware recovery modes remain covered only by their original approval.')
        files['review.md'] += (
            '\nTiming scope: bind the exact candidate boot from hardware readback and require both boot files '
            'to match the sealed candidates. Capture PPS/RTC class paths, parent chains, driver/subsystem/device '
            'links, device-tree compatible/status/name/gpios/phandle/edge properties, PPS name/dev/path/mode '
            'and RTC name/dev metadata, bound pps-gpio platform devices and the fixed Pi 4 GPIO controller '
            'compatible/phandle. Read twice and require stable metadata. No device opens, PPS assert/clear '
            'samples, RTC date/time/since_epoch reads, driver binding, module loading, service changes or reboot. '
            'Limit 16 class entries, 32 driver entries, 16 ancestors, 4096 bytes per property and 1 MiB timing metadata. '
            'The existing candidate boot remains unaccepted; this stage does not accept hardware or recover it. '
            'Recovery here means conditional terminal readback; incomplete captures remain preserved. '
            'Cleanup removes only this diagnostic stage after acceptance. Original hardware recovery modes '
            'remain separately retained under their existing approval.\n').encode()
    files['manifest.json'] = encoded({n: sha(v) for n, v in files.items()})
    os.umask(0o077)
    args.output.mkdir(mode=0o700)
    for n in ('spec.json', 'review.md', 'known_hosts'):
        (args.output/n).write_bytes(files[n])
    bundle = args.output/'registry-inspection.tar'
    with tarfile.open(bundle, 'w', format=tarfile.USTAR_FORMAT) as archive:
        for n, data in sorted(files.items()):
            info = tarfile.TarInfo(n); info.size = len(data); info.mode = 0o600; info.mtime = epoch
            archive.addfile(info, io.BytesIO(data))
    result = {'bundle': str(bundle), 'sha256': sha(bundle.read_bytes()), 'target': spec['hostname'],
              'expires_epoch': spec['expires_epoch'], 'execution_authorized': False, 'target_contact': False}
    prepare(bundle, result['sha256'])
    c.write_new(args.output/'sealing.json', result)
    return result


def payload(spec, files, mode, terminal_sha):
    return ('import base64,json,hashlib\n'
        'spec=json.loads('+repr(json.dumps(spec))+')\n'
        'files={n:base64.b64decode(v,validate=True) for n,v in json.loads('+repr(json.dumps(
            {n: base64.b64encode(files[n]).decode() for n in inputs(spec)}))+').items()}\n'
        'ns={"__name__":"sealed_registry","__file__":spec["stage"]+"/worker.py"}\n'
        'exec(compile(files["worker.py"],"sealed-registry","exec"),ns)\n'
        'status=0\ntry:\n result=ns["worker"](spec,files,'+repr(mode)+','+repr(terminal_sha)+')\n'
        'except BaseException as e:\n status=2\n result={"phase":"held","error":str(e)[:500]}\n'
        'print(json.dumps({"spec_sha256":ns["sha"](ns["encoded"](spec)),"result":result}))\n'
        'print("INSPECT_EXIT_STATUS="+str(status))\nraise SystemExit(status)\n').encode()


def accept(spec, result):
    report = result['report']
    queries = {'registry', 'registry-end', 'active', 'addresses', 'routes-4', 'routes-6', 'cmdline'}
    queries |= {'profile-'+key for key in report['current_registry']}
    if (result['phase'] != 'captured' or sha(encoded(report)) != result['terminal_sha256']
            or report['hostname'] != spec['hostname'] or report['kernel'] != spec['kernel']
            or report['checks'] != {'read_only_capture': True, 'retained_state_stable': True, 'registry_stable': True}
            or set(report['queries']) != queries
            or set(report['boot_files']) != set(BOOT)
            or set(report['retained']) != {'state.json', 'before.json', 'commands.jsonl'}
            or report['retained_sha256'] != {n: sha(base64.b64decode(v, validate=True)) for n, v in report['retained'].items()}
            or any(q['status'] != 0 for q in report['queries'].values())):
        raise ValueError('complete bound diagnostic report required')
    if spec.get('operation') == 'host-timing-inspection':
        if (report['boot_id'] != spec['candidate_boot_id']
                or set(report['timing']) != {'classes','pps_platform','gpio_controller'}
                or len(encoded(report['timing'])) > 1024*1024):
            raise ValueError('complete candidate timing metadata required')
    if spec.get('operation') == 'host-uart-inspection':
        if (report['boot_id'] != spec['recovered_boot_id']
                or set(report['uart']) != {'serial0', 'ttys', 'amba_drivers', 'amba_devices'}
                or len(encoded(report['uart'])) > 1024*1024):
            raise ValueError('complete recovered UART metadata required')
    if spec.get('operation') == 'host-baseline':
        baseline = report['baseline']
        if (baseline['observation']['boot_id'] != spec['recovered_boot_id']
                or baseline['observation']['boot_id'] != report['boot_id']
                or baseline['hostname'] != spec['hostname'] or baseline['kernel'] != spec['kernel']
                or baseline['continuity_unchanged'] is not True
                or baseline['queries']['profile_registry']['exit_status'] != 0
                or registry(baseline['queries']['profile_registry']['stdout']) != report['current_registry']
                or baseline['recovery_bundle_sha256'] != spec['recovery_bundle_sha256']):
            raise ValueError('fresh recovered baseline binding required')
    receipt = {'state': 'diagnostic_accepted', 'terminal_sha256': result['terminal_sha256'],
               'spec_sha256': sha(encoded(spec)), 'boot_id': report['boot_id']}
    if spec.get('operation') == 'host-baseline':
        receipt['baseline_sha256'] = sha(encoded(report['baseline']))
    return receipt


def execute(args):
    c = module('run-foundation-preflight.py')
    bundle = args.bundle.absolute(); directory = bundle.parent
    spec, files = prepare(bundle, args.sha256)
    if args.mode == 'capture' and not spec['prepared_epoch']-300 <= time.time() < spec['expires_epoch']:
        raise ValueError('capture window expired')
    if args.mode != 'capture':
        if json.loads(c.private_file(directory/'capture-execution.json'))['bundle_sha256'] != args.sha256:
            raise ValueError('registered capture required')
    terminal_sha = None
    if args.mode == 'cleanup':
        receipt = json.loads(c.private_file(directory/'acceptance.json'))
        if receipt['bundle_sha256'] != args.sha256 or receipt['spec_sha256'] != sha(files['spec.json']):
            raise ValueError('bound acceptance required')
        terminal_sha = receipt['terminal_sha256']
    agent = os.environ.get('SSH_AUTH_SOCK')
    if not agent:
        raise ValueError('existing SSH agent required')
    c.write_new(directory/(args.mode+'-execution.json'), {'bundle_sha256': args.sha256, 'registered_epoch': int(time.time())})
    # Only readback may try the second endpoint. Never retry capture or cleanup.
    endpoints = spec['endpoints'] if args.mode == 'readback' else spec['endpoints'][:1]
    for index, host in enumerate(endpoints):
        label = args.mode+'-'+str(index)
        argv = c.transport(directory, host); argv[3] = '180s'
        argv[argv.index('ama@'+host):argv.index('ama@'+host)] = ['-o', 'HostKeyAlias='+spec['old_ipv4']]
        data = payload(spec, files, args.mode, terminal_sha)
        c.write_new(directory/(label+'-submission.json'), {'argv': argv, 'payload_sha256': sha(data)})
        with (directory/(label+'.stdout')).open('xb') as out, (directory/(label+'.stderr')).open('xb') as err:
            p = subprocess.run(argv, input=data, stdout=out, stderr=err, check=False,
                               env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C', 'SSH_AUTH_SOCK': agent})
        c.write_new(directory/(label+'-transport.json'), {'exit_status': p.returncode})
        raw = c.private_file(directory/(label+'.stdout'), 20*1024**2)
        match = re.fullmatch(rb'(.*)\nINSPECT_EXIT_STATUS=([02])\n', raw, re.S)
        if match and p.returncode == int(match[2]):
            response = json.loads(match[1])
            if response['spec_sha256'] != sha(files['spec.json']):
                raise ValueError('terminal specification mismatch')
            c.write_new(directory/(label+'-result.json'), response)
            if p.returncode:
                raise ValueError('capture held: '+response['result'].get('error', 'unknown'))
            result = response['result']
            if args.mode == 'cleanup':
                if result != {'phase': 'cleaned', 'terminal_sha256': terminal_sha}:
                    raise ValueError('cleanup terminal mismatch')
            else:
                receipt = dict(accept(spec, result), bundle_sha256=args.sha256)
                path = directory/'acceptance.json'
                if path.exists():
                    if c.private_file(path) != encoded(receipt):
                        raise ValueError('conflicting acceptance')
                else:
                    c.write_new(path, receipt)
            if spec['operation'] == 'host-baseline' and args.mode != 'cleanup':
                baseline_path = directory/'baseline.json'
                raw_baseline = encoded(result['report']['baseline'])
                if baseline_path.exists():
                    if c.private_file(baseline_path) != raw_baseline:
                        raise ValueError('baseline conflict')
                else:
                    with baseline_path.open('xb') as out: out.write(raw_baseline)
            c.write_new(directory/(args.mode+'-result.json'), result)
            return {'mode': args.mode, 'phase': result['phase'], 'target': spec['hostname']}
    raise ValueError('terminal unavailable; preserve evidence and do not replay capture/cleanup')


def archive_inputs(raw):
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:') as archive:
        members = archive.getmembers()
        if (len(members) > 64 or len({m.name for m in members}) != len(members)
                or any(not m.isfile() or not re.fullmatch('[a-z][a-z0-9._-]+', m.name)
                       or m.size > 16*1024**2 for m in members)):
            raise ValueError('bounded closed provenance archive required')
        files = {m.name: archive.extractfile(m).read() for m in members}
    if json.loads(files['manifest.json']) != {n: sha(v) for n, v in files.items() if n != 'manifest.json'}:
        raise ValueError('provenance manifest mismatch')
    return files


def recovery_inputs(files, spec):
    if sha(files['recovery.tar']) != spec['recovery_bundle_sha256']:
        raise ValueError('accepted recovery archive required')
    recovered = archive_inputs(files['recovery.tar']); recovery = json.loads(recovered['spec.json'])
    receipt = json.loads(files['recovery-acceptance.json']); cleanup = json.loads(files['recovery-cleanup.json'])
    if recovery['operation'] == 'hardware':
        if (spec['recovery_bundle_sha256'] != spec['hardware_bundle_sha256']
                or recovered['spec.json'] != files['hardware-spec.json']
                or not re.fullmatch('/var/lib/ntp-host-[a-z][a-z0-9-]{0,47}', recovery['stage'])
                or any(recovery[k] != spec[k] for k in ('hostname','kernel','ssh','old_ipv4',
                                                       'network_bundle_sha256','network_spec_sha256'))
                or spec['endpoints'] != [recovery['recipe'][k].split('/')[0] for k in ('ipv4_address','ipv6_address')]
                or receipt['bundle_sha256'] != spec['hardware_bundle_sha256']
                or receipt['result'] != {'phase':'recovered','boot_id':spec['recovered_boot_id']}
                or cleanup['bundle_sha256'] != spec['hardware_bundle_sha256']
                or cleanup['result']['phase'] != 'recovered'
                or cleanup['result'].get('recovered_boot_id') != spec['recovered_boot_id']
                or cleanup['result'].get('transient_units_cleaned') is not True):
            raise ValueError('completed hardware recovery/cleanup provenance mismatch')
        return recovery, recovered
    hardware = archive_inputs(recovered['hardware.tar'])
    if (recovery['operation'] != 'host-recovery-continuation'
            or not re.fullmatch('/var/lib/ntp-recovery-[a-z][a-z0-9-]{0,47}', recovery['stage'])
            or any(recovery[k] != spec[k] for k in ('hostname', 'kernel', 'ssh', 'old_ipv4', 'endpoints'))
            or receipt['bundle_sha256'] != spec['recovery_bundle_sha256']
            or receipt['spec_sha256'] != sha(recovered['spec.json']) or receipt['state'] != 'recovery_accepted'
            or receipt['proof']['boot_id'] != spec['recovered_boot_id']
            or receipt['proof']['checks'] != {'original_boot_files': True, 'new_boot': True, 'network_and_native_continuity': True}
            or set(receipt['endpoint_proofs']) != set(spec['endpoints'])
            or any(v != receipt['proof'] for v in receipt['endpoint_proofs'].values())
            or cleanup['phase'] != 'accepted' or cleanup['transient_units_cleaned'] is not True
            or cleanup['proof'] != receipt['proof'] or cleanup['endpoint_proofs'] != receipt['endpoint_proofs']
            or recovery['hardware_sha256'] != spec['hardware_bundle_sha256']
            or sha(recovered['hardware.tar']) != spec['hardware_bundle_sha256']
            or hardware['spec.json'] != files['hardware-spec.json']
            or any(spec[k] != json.loads(hardware['spec.json'])[k] for k in ('network_bundle_sha256','network_spec_sha256'))):
        raise ValueError('accepted recovery/cleanup/boot/hardware provenance mismatch')
    return recovery, recovered


def verify_recovery_stage(h, recovery, recovered, files):
    root = Path(recovery['stage']); h.ancestors(root)
    if stat.S_IMODE(root.stat().st_mode) != 0o700:
        raise ValueError('protected recovery stage required')
    if private_root_file(h, root/'spec.json') != recovered['spec.json']:
        raise ValueError('recovery specification drift')
    for name, digest in recovery['members'].items():
        if not re.fullmatch('[a-z][a-z0-9._-]+', name) or sha(private_root_file(h, root/name, 32*1024**2)) != digest:
            raise ValueError('recovery source drift')
    cleanup = files['recovery-cleanup.json']
    if recovery['operation'] == 'hardware':
        cleanup = encoded(json.loads(cleanup)['result'])
    if private_root_file(h, root/'state.json') != cleanup:
        raise ValueError('accepted recovery state drift')


def load_path(path):
    info = importlib.util.spec_from_file_location('baseline_'+path.stem.replace('-', '_'), path)
    result = importlib.util.module_from_spec(info); info.loader.exec_module(result); return result


def fresh_baseline(h, spec, files, old):
    if Path('/proc/sys/kernel/random/boot_id').read_text().strip() != spec['recovered_boot_id']:
        raise ValueError('accepted recovered boot required')
    root = Path(old['stage']); local = Path(spec['stage'])
    inspector = load_path(local/'inspect-runtime.py'); inspector.recipe(files['runtime-recipe.json'])
    stage = load_path(root/'host-configuration-stage.py')
    source = load_path(root/'inspect-source-destinations.py')
    previous = json.loads(private_root_file(h, root/'baseline.json'))
    release = json.loads(private_root_file(h, root/'release.json'))
    observed = source.observation()
    if not stage.observation_equal(observed, previous['observation'], new_boot=True) or observed['active_daemons']:
        raise ValueError('post-recovery package/service/Python drift')
    installed, parents = inspector.installed_state(root, old, h, source, release)
    if installed != previous['installed_state']:
        raise ValueError('installed release drift')
    inspector.verify_parents(parents, previous['parents'])
    configs = inspector.protected_files(h); devices = inspector.devices(h)
    if configs != previous['protected_files']:
        raise ValueError('post-recovery protected configuration drift')
    queries = {n: inspector.query(argv, n if n in ('accounts', 'groups') else None) for n, argv in inspector.QUERIES.items()}
    queries['ethernet_profiles'] = inspector.ethernet_profiles(queries['profile_registry'])
    elf = [n for n, r in release['files'].items() if r['type'] == 'file' and
           (n in ('usr/local/sbin/gpsd', 'usr/local/sbin/ntpd') or re.search(r'\.so(?:\.[0-9.]+)?$', n))]
    if not 2 <= len(elf) <= 16:
        raise ValueError('bounded ELF set required')
    queries['elf_dependencies'] = {n: inspector.query(['/usr/bin/readelf', '-d', '--', '/'+n]) for n in sorted(elf)}
    if len(encoded(queries)) > 2*1024**2:
        raise ValueError('baseline query bound exceeded')
    if (source.observation() != observed or inspector.protected_files(h) != configs or inspector.devices(h) != devices
            or inspector.installed_state(root, old, h, source, release) != (installed, parents)
            or inspector.query(inspector.QUERIES['profile_registry']) != queries['profile_registry']
            or inspector.ethernet_profiles(queries['profile_registry']) != queries['ethernet_profiles']):
        raise ValueError('fresh baseline changed during capture')
    return dict(previous, collected_epoch=int(time.time()), observation=observed, installed_state=installed,
                parents=parents, protected_files=configs, devices=devices, queries=queries,
                python_environment=inspector.python_environment(), runtime_recipe_sha256=sha(files['runtime-recipe.json']),
                recovery_bundle_sha256=spec['recovery_bundle_sha256'], continuity_unchanged=True)


def seal_baseline(args):
    c = module('run-foundation-preflight.py')
    direct = getattr(args, 'hardware_recovery', False)
    raw = c.private_file(args.recovery_dir/('host-configuration.tar' if direct else 'recovery-continuation.tar'), 32*1024**2)
    if sha(raw) != args.recovery_sha256:
        raise ValueError('exact accepted recovery bundle required')
    recovered = archive_inputs(raw); recovery = json.loads(recovered['spec.json'])
    hardware = recovered if direct else archive_inputs(recovered['hardware.tar'])
    old = json.loads(hardware['spec.json'])
    receipt = c.private_file(args.recovery_dir/('verify-recovery-result.json' if direct else 'acceptance.json'))
    cleanup = c.private_file(args.recovery_dir/'cleanup-result.json')
    files = {'worker.py': Path(__file__).read_bytes(), 'helper.py': (ROOT/'scripts/foundation-install.py').read_bytes(),
             'hardware-spec.json': hardware['spec.json'],
             'hardware-recovery.json': c.private_file(args.recovery_dir.parent/old['operation_id']/'recover-result.json'),
             'known_hosts': hardware['known_hosts'], 'tests.py': (ROOT/'tests/test_host_registry_inspection.py').read_bytes(),
             'transport.py': (ROOT/'scripts/run-foundation-preflight.py').read_bytes(),
             'recovery.tar': raw, 'recovery-acceptance.json': receipt, 'recovery-cleanup.json': cleanup,
             'inspect-runtime.py': (ROOT/'scripts/inspect-runtime.py').read_bytes(),
             'inspect-source-destinations.py': (ROOT/'scripts/inspect-source-destinations.py').read_bytes(),
             'runtime-recipe.json': (ROOT/'configs/runtime-discovery-recipe.json').read_bytes()}
    for label, path in (('architecture', 'docs/ntp-architecture-deployment-plan-v1.0.md'),
                        ('operations', 'docs/OPERATIONS.md'), ('history', 'HISTORY.md')):
        files[label+'.md'] = (ROOT/path).read_bytes()
    epoch = int(time.time()); spec = {k: old[k] for k in ('hostname', 'kernel', 'ssh', 'old_ipv4')}
    spec.update(schema=1, operation='host-baseline', operation_id=args.operation_id,
                stage='/var/lib/ntp-inspect-'+args.operation_id, prepared_epoch=epoch, expires_epoch=epoch+86400,
                endpoints=[old['recipe'][k].split('/')[0] for k in ('ipv4_address','ipv6_address')],
                hardware_bundle_sha256=args.recovery_sha256 if direct else recovery['hardware_sha256'],
                recovery_bundle_sha256=args.recovery_sha256,
                recovered_boot_id=json.loads(receipt)['result' if direct else 'proof']['boot_id'],
                network_bundle_sha256=old['network_bundle_sha256'], network_spec_sha256=old['network_spec_sha256'])
    spec['members'] = {n: sha(files[n]) for n in inputs(spec)}
    validate(spec, files); files['spec.json'] = encoded(spec)
    files['review.md'] = (f'# Fresh post-recovery baseline\n\nTarget: {spec["hostname"]}. Operation: {args.operation_id}.\n'
        f'Protected stage: `{spec["stage"]}`. Capture expires epoch {spec["expires_epoch"]}.\n'
        f'Accepted recovery SHA-256: `{args.recovery_sha256}`.\n\n'
        'One read-only capture, bound to the exact accepted recovery boot, source archive, receipt, cleanup '
        'and retained protected stages. Reuse the registry inspector: preserve the original journals and '
        'before-state under its shared lock; capture registry/profile identities, addresses/routes and boot files. '
        'Additionally verify all installed native entries and parent identities twice; capture fresh package, '
        'Python and service observations, protected boot/time/loader files, account/group identifiers without '
        'password fields, UART/PPS/RTC metadata, static ELF dependencies and isolated Python search paths. '
        'Only boot ID and service PID/restart counters may differ from the old observation; bind the new boot '
        'to the accepted recovery receipt. Other drift holds acceptance. No application imports, device I/O, '
        'profile changes, account changes, boot edits, service activation or reboot.\n\n'
        'Create only a separate root-owned 0700 stage with 0600 inputs and terminal evidence. '
        'Conditional readback may use either pinned fixed endpoint and never repeats capture. '
        'Accept only stable complete source/boot/registry observations and a bound fresh baseline. '
        'Conditional cleanup removes only this new diagnostic stage after accepted terminal hashing; '
        'preserve both original hardware/recovery stages and every local execution record. '
        'Incomplete captures remain preserved for a new review. SSH transport is bounded to 180 seconds; '
        'fixed subprocesses retain their existing bounded timeouts.\n\n'
        'Use run-host-registry-inspection.py execute --bundle ABSOLUTE_BUNDLE --sha256 APPROVED_HASH '
        '--mode capture once; conditional modes are readback and cleanup. '
        'Hardware/boot replacement can be sealed only after this baseline is executed, accepted and cleaned. '
        'That later mutation requires separate execution approval.\n').encode()
    files['manifest.json'] = encoded({n: sha(v) for n, v in files.items()})
    os.umask(0o077); args.output.mkdir(mode=0o700)
    for n in ('spec.json', 'review.md', 'known_hosts'):
        (args.output/n).write_bytes(files[n])
    bundle = args.output/'registry-inspection.tar'
    with tarfile.open(bundle, 'w', format=tarfile.USTAR_FORMAT) as archive:
        for n, data in sorted(files.items()):
            item = tarfile.TarInfo(n); item.size=len(data); item.mode=0o600; item.mtime=epoch
            archive.addfile(item, io.BytesIO(data))
    result = {'bundle': str(bundle), 'sha256': sha(bundle.read_bytes()), 'target': spec['hostname'],
              'expires_epoch': spec['expires_epoch'], 'execution_authorized': False, 'target_contact': False}
    prepare(bundle, result['sha256']); c.write_new(args.output/'sealing.json', result)
    return result


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    p = sub.add_parser('seal')
    kind = p.add_mutually_exclusive_group()
    kind.add_argument('--uart', action='store_true', help='Inspect UART/sysfs after completed hardware recovery')
    kind.add_argument('--timing', action='store_true', help='Inspect PPS/RTC on a held candidate boot')
    p.add_argument('--hardware-dir', type=Path, required=True); p.add_argument('--hardware-sha256', required=True)
    p.add_argument('--operation-id', required=True); p.add_argument('--output', type=Path, required=True)
    p = sub.add_parser('execute')
    p.add_argument('--bundle', type=Path, required=True); p.add_argument('--sha256', required=True)
    p.add_argument('--mode', choices=('capture', 'readback', 'cleanup'), required=True)
    p = sub.add_parser('seal-baseline')
    p.add_argument('--hardware-recovery', action='store_true', help='Bind completed recovery in a hardware stage')
    p.add_argument('--recovery-dir', type=Path, required=True); p.add_argument('--recovery-sha256', required=True)
    p.add_argument('--operation-id', required=True); p.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(seal_baseline(args) if args.action == 'seal-baseline' else seal(args) if args.action == 'seal' else execute(args)))


if __name__ == '__main__':
    main()
