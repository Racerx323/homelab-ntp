#!/usr/bin/python3
"""One pre-reboot package transaction. Dependencies injected from the sealed bundle."""
import base64
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import time

m = w = r = f = None
ENV = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LC_ALL': 'C', 'HOME': '/root',
       'DEBIAN_FRONTEND': 'noninteractive', 'APT_LISTCHANGES_FRONTEND': 'none',
       'NEEDRESTART_MODE': 'l', 'PYTHONDONTWRITEBYTECODE': '1'}
UNITS = ('apt-daily.timer', 'apt-daily-upgrade.timer', 'apt-daily.service', 'apt-daily-upgrade.service')
ALSA = '/etc/udev/rules.d/90-alsa-restore.rules'


def validate_services(services):
    """The accepted supervisor owns GPSD; a standalone GPSD unit is absent."""
    for name in ('timeservice.service', 'munin-node.service', 'cron.service'):
        row = services[name]
        r.require(row['accepted'] and all(value + '\n' in row['stdout'] for value in
                  ('LoadState=loaded', 'ActiveState=active', 'SubState=running')),
                  'inactive service: ' + name)
    row = services['gpsd.service']
    r.require(row['accepted'] and all(value + '\n' in row['stdout'] for value in
              ('LoadState=not-found', 'ActiveState=inactive', 'SubState=dead', 'MainPID=0')),
              'standalone GPSD lifecycle drift')
    for name in ('apt-daily.service', 'apt-daily-upgrade.service', 'unattended-upgrades.service'):
        r.require(services[name]['accepted'] and 'ActiveState=inactive\n' in services[name]['stdout'],
                  'automatic package activity')
    updater = services['rpi-eeprom-update.service']['stdout']
    r.require(services['rpi-eeprom-update.service']['accepted'] and 'MainPID=0\n' in updater
              and any('SubState='+v+'\n' in updater for v in ('dead', 'exited')),
              'EEPROM updater active or transitional')


def preflight(spec, baseline, evidence=None):
    evidence = {} if evidence is None else evidence
    c = w.collect(spec, baseline['after'])
    evidence['inspection'] = c
    r.require(c.get('capture_complete') and c.get('protected_continuity'), 'inspection preflight failed')
    for group in ('helpers', 'scripts', 'trees', 'firmware', 'boot_artifacts'):
        r.require(c[group] == baseline[group], 'reviewed input drift: ' + group)
    r.require(c['other_connect'] == baseline['other_connect'], 'Connect state drift')
    validate_services(c['before']['services'])
    jobs = m.command(['/usr/bin/systemctl','--no-pager','--no-legend','list-jobs'])
    c['maintenance_jobs'] = jobs
    r.require(jobs['accepted'] and not any(name in jobs['stdout'] for name in (*UNITS,'rpi-eeprom-update.service')),
              'pending updater/package job')
    r.require(not os.path.lexists(ALSA), 'ALSA override now exists')
    r.require(not os.path.lexists('/var/lib/ntp-maintenance'), 'maintenance root already exists')
    proc = Path('/proc/cmdline').read_bytes()
    boot = r.boot_conditions(proc, r.read('/boot/firmware/config.txt')[0])
    evidence['boot_conditions'] = boot
    r.require(not boot['continuous_watchdog_requested'], 'unreviewed early-watchdog setting')
    for name in ('/boot/firmware/cmdline.txt', '/boot/firmware/config.txt'):
        r.require(r.sha(r.read(name)[0]) == spec['backup'][name]['sha256'], 'boot policy drift')
    root, firmware = os.statvfs('/'), os.statvfs('/boot/firmware')
    reserve = r.reserve(root.f_bavail * root.f_frsize, root.f_favail, root.f_files,
                        firmware.f_bavail * firmware.f_frsize, spec['backup'],
                        sum(p['size'] for p in spec['packages']))
    evidence['reserve'] = reserve
    evidence['unit_policy'] = {}
    for u in UNITS:
        r.require(not os.path.lexists('/etc/systemd/system/' + u), 'persistent unit control exists')
        row = m.command(['/usr/bin/systemctl', 'show', '--property=ActiveState,UnitFileState', u])
        evidence['unit_policy'][u] = row
        r.require(row['accepted'] and ('UnitFileState=enabled\n' in row['stdout'] or
                  'UnitFileState=static\n' in row['stdout']), 'automatic-update unit policy')
        r.require('ActiveState=' + ('active' if u.endswith('.timer') else 'inactive') + '\n'
                  in row['stdout'], 'automatic-update unit state')
    native = {}
    c['maintenance_native'] = {'initramfs': native}
    for name in spec['initramfs']:
        row = m.command(['/usr/bin/lsinitramfs', name], timeout=60)
        native[name] = row
        r.require(row['accepted'] and 'init\n' in row['stdout'], 'existing initramfs native listing')
    timing = m.command(['/usr/local/bin/ntpq','-n','-c','rv 0'])
    c['maintenance_native']['ntp'] = timing
    r.require(timing['accepted'] and re.search(r'\bleap=00\b',timing['stdout'])
              and re.search(r'\bstratum=1\b',timing['stdout']), 'pre-update NTP health')
    c['maintenance_native'] = {'initramfs':native,'ntp':timing}
    return c, reserve


def export_backup(spec, baseline):
    report = {'operation_id': spec['operation_id'], 'backup_complete': False,
              'target_mutation': False, 'preflight_evidence': {}}
    try:
        capture, reserve = preflight(spec, baseline, report['preflight_evidence'])
        raw = r.backup('/', spec['backup'])
        r.verify_backup(raw, spec['backup'])
        report.update(backup_complete=True, backup_sha256=r.sha(raw),
                      backup_base64=base64.b64encode(raw).decode(), reserve=reserve, capture=capture)
    except BaseException as error:
        report.update(error=type(error).__name__ + ': ' + str(error), held=True)
    return report


def inventory(text):
    rows = {}
    for line in text.splitlines():
        package, arch, version, status = line.split('\t')
        r.require(status in ('installed', 'config-files'), 'unconfigured package state')
        key = package + ':' + arch
        r.require(key not in rows, 'duplicate inventory')
        rows[key] = (version, status)
    return rows


def validate_simulation(text, packages):
    rows = {}
    for line in text.splitlines():
        r.require(not line.startswith(('Remv ', 'Purg ')), 'solver removal')
        if not line.startswith('Inst '):
            continue
        match = re.match(r'^Inst ([^ ]+) \[([^]]+)\] \(([^ ]+)', line)
        r.require(match is not None, 'solver addition/unparsed change')
        name, old, new = match.groups()
        name = name.split(':')[0]
        r.require(name not in rows, 'duplicate solver change')
        rows[name] = (old, new)
    r.require(rows == {p['package']: (p['installed'], p['version']) for p in packages}, 'solver delta drift')


def apt_configuration(stage):
    return (f'Dir::Etc::parts "{stage}/empty"; Dir::Etc::main "{stage}/absent";\n'
            f'Dir::Etc::sourcelist "{stage}/absent"; Dir::Etc::sourceparts "{stage}/empty";\n'
            f'Dir::State::lists "{stage}/lists"; Dir::State::status "/var/lib/dpkg/status";\n'
            f'Dir::Cache::archives "{stage}/archives"; Dir::Cache::pkgcache ""; Dir::Cache::srcpkgcache "";\n'
            f'Dir::Log "{stage}/apt-logs";\n'
            'APT::Architecture "arm64"; APT::Architectures { "arm64"; };\n'
            'APT::Install-Recommends "false"; APT::Install-Suggests "false";\n'
            'APT::Get::AllowUnauthenticated "false"; DPkg::Lock::Timeout "0";\n'
            'DPkg::Options { "--force-confdef"; "--force-confold"; };\n').encode()


def install(spec, baseline, files, acknowledgement):
    """No reboot, firmware tool invocation, retry or general dpkg repair branch."""
    report = {'operation_id': spec['operation_id'], 'package_stage_complete': False,
              'production_accepted': False, 'reboot_authorized': False, 'phase': 'preflight'}
    stage = Path('/var/lib/ntp-maintenance') / spec['operation_id']
    command_index, masked, package_intent = 0, [], False
    deadline = time.monotonic() + 1500
    created = False
    before = None
    def save():
        if not created:
            return
        name = stage / ('state-' + str(time.time_ns()) + '.json')
        r.create(name, r.encoded(report))
    def run(argv, timeout=30, accepted=(0,), env=None):
        nonlocal command_index
        command_index += 1
        # Reuse only the qualified durable command/logging primitive, not its installer.
        f.STAGE = stage
        f.DEADLINE = deadline
        return f.run(argv, 'command-%03d' % command_index, seconds=timeout,
                     accepted=accepted, env=env or ENV)
    try:
        report['preflight_evidence'] = {}
        before, reserve = preflight(spec, baseline, report['preflight_evidence'])
        backup = r.backup('/', spec['backup'])
        r.require(acknowledgement == {'operation_id': spec['operation_id'],
                  'backup_sha256': r.sha(backup), 'offnode_verified': True}, 'independent backup acknowledgement')
        backup_files = r.verify_backup(backup, spec['backup'])
        stage.parent.mkdir(mode=0o700); r.sync(stage.parent.parent)
        stage.mkdir(mode=0o700); r.sync(stage.parent); created = True
        r.create(stage/'spec.json', r.encoded(spec))
        r.create(stage/'offnode-ack.json', r.encoded(acknowledgement))
        r.create(stage/'recovery.tar.gz', backup)
        r.create(stage/'before.json', r.encoded(before))
        report.update(phase='staged', reserve=reserve); save()
        for name in ('empty', 'lists', 'archives', 'apt-logs'):
            (stage/name).mkdir(mode=0o700)
        for package in spec['packages']:
            raw = files[package['file']]
            r.require(len(raw) == package['size'] and r.sha(raw) == package['payload_sha256'], 'payload drift')
            r.create(stage/package['file'], raw)
            actual = run(['/usr/bin/dpkg-deb', '-f', str(stage/package['file']), 'Package', 'Version', 'Architecture'])
            r.require(dict(line.split(': ', 1) for line in actual.splitlines()) ==
                      {k.title(): package[k] for k in ('package', 'version', 'architecture')}, 'package identity')
        old = inventory(run(['/usr/bin/dpkg-query', '-W', '-f=${Package}\t${Architecture}\t${Version}\t${db:Status-Status}\n']))
        expected = dict(old)
        for p in spec['packages']:
            key = p['package'] + ':' + p['architecture']
            r.require(expected.get(key) == (p['installed'], 'installed'), 'installed version drift')
            expected[key] = (p['version'], 'installed')
        r.create(stage/'apt.conf', apt_configuration(stage))
        env = dict(ENV, APT_CONFIG=str(stage/'apt.conf'))
        args = ['/usr/bin/apt-get', '--no-download', '--no-remove', '--no-install-recommends',
                '--no-install-suggests', '-y', 'install', *[str(stage/p['file']) for p in spec['packages']]]
        validate_simulation(run([args[0], '--simulate', *args[1:]], env=env), spec['packages'])
        native = m.native_verify(stage/'alsa-parser', files['baseline.rules'], files['candidate.rules'])
        r.create(stage/'alsa-parser.json', r.encoded(native))
        r.require(native.get('cleaned') and native.get('candidate.rules', {}).get('returncode') == 0
                  and not native['candidate.rules']['stderr'], 'native ALSA parser')
        report.update(phase='control-intent', planned_masks=list(UNITS)); save()
        for unit in UNITS:
            if unit.endswith('.timer'):
                run(['/usr/bin/systemctl', 'stop', unit])
            path = Path('/etc/systemd/system')/unit
            os.symlink('/dev/null', path); masked.append(unit); r.sync(path.parent)
        run(['/usr/bin/systemctl', 'daemon-reload'])
        r.require(not m.lock_state()['held'], 'package lock held')
        r.publish_inhibit('/', spec['operation_id'])
        run(['/usr/bin/systemctl', 'daemon-reload'])
        conditions = run(['/usr/bin/systemctl', 'show', '--property=Conditions', 'rpi-eeprom-update.service'])
        r.require(r.MARKER in conditions, 'effective EEPROM condition absent')
        run(['/usr/bin/systemd-analyze', 'condition', 'ConditionPathExists=!' + r.MARKER], accepted=(1,))
        r.check_inhibit('/', spec['operation_id'])
        r.require(r.sha(r.read('/var/lib/dpkg/status')[0]) == spec['backup']['/var/lib/dpkg/status']['sha256'],
                  'package state changed before mutation')
        for unit in ('apt-daily.service', 'apt-daily-upgrade.service'):
            r.require('ActiveState=inactive\n' in run(['/usr/bin/systemctl','show','--property=ActiveState',unit]),
                      'package service raced preflight')
        r.require(time.time() < spec['expires_epoch'], 'approval expired before package mutation')
        report.update(phase='package-intent', masked=masked); save(); package_intent = True
        run(args, timeout=1200, env=env)
        r.check_inhibit('/', spec['operation_id'])
        r.require(not run(['/usr/bin/dpkg', '--audit']).strip(), 'dpkg audit not empty')
        r.require(inventory(run(['/usr/bin/dpkg-query', '-W', '-f=${Package}\t${Architecture}\t${Version}\t${db:Status-Status}\n'])) == expected,
                  'complete package inventory differs')
        # Explicit local APT arguments can change automatic/manual flags. Preserve them.
        extended = Path('/var/lib/apt/extended_states')
        original = backup_files['var/lib/apt/extended_states']
        current, identity = r.read(extended)
        if current != original:
            temporary = extended.with_name('.extended_states.ntp-maintenance')
            r.create(temporary, original, spec['backup'][str(extended)]['mode'])
            r.require(r.read(extended)[1] == identity, 'extended-state race')
            os.replace(temporary, extended); r.sync(extended.parent)
        r.require(r.read(extended)[1] == spec['backup'][str(extended)], 'automatic/manual flag restoration')
        for path, previous in baseline['before']['configuration']['files'].items():
            if path.startswith(('/boot/firmware/', '/etc/apt/sources', '/etc/apt/preferences', '/etc/apt/keyrings')):
                r.require(m.record(path, 'text' in previous) == previous, 'protected policy/staging changed: ' + path)
        for path in ('/etc/localtime','/etc/timezone'):
            previous = baseline['helpers'][path]
            actual = m.record(path, False)
            keys = ('sha256','link','uid','gid','mode','missing')
            r.require({k:actual.get(k) for k in keys} == {k:previous.get(k) for k in keys}, 'timezone policy changed')
        unit = run(['/usr/bin/systemctl', 'show', '--property=ActiveState,ConditionResult,ExecMainStartTimestampMonotonic',
                    'rpi-eeprom-update.service'])
        r.require('ActiveState=inactive\n' in unit and 'ConditionResult=no\n' in unit,
                  'EEPROM skip not established; no reboot')
        boot_names = {str(path) for parent in ('/boot','/boot/firmware') for path in m.members(parent)
                      if path.name.startswith(('initrd','initramfs','vmlinuz','kernel','pieeprom','vl805','recovery.'))}
        r.require(boot_names == set(baseline['boot_artifacts']), 'unexpected boot/staging artifact')
        postboot = {name: r.read(name)[1] for name in boot_names}
        for name, row in postboot.items():
            if 'kernel' in name or '/vmlinuz-' in name:
                r.require(all(row[k] == baseline['boot_artifacts'][name][k] for k in ('sha256','size','uid','gid','mode')),
                          'kernel artifact changed')
        for target, source in spec['boot_pairs'].items():
            r.require(postboot[target]['sha256'] == postboot[source]['sha256'], 'boot-copy mismatch')
        for name in spec['initramfs']:
            listing = run(['/usr/bin/lsinitramfs', name], timeout=60)
            r.require('scripts/init-top/rpi_wd' in listing and 'init\n' in listing, 'initramfs structure')
        r.create(stage/'boot-after.json', r.encoded(postboot))
        alsa = Path(ALSA)
        temporary_rule = alsa.with_name('.' + alsa.name + '.' + spec['operation_id'])
        r.create(temporary_rule, files['candidate.rules'], 0o644)
        os.link(temporary_rule, alsa, follow_symlinks=False)
        temporary_rule.unlink(); r.sync(alsa.parent)
        run(['/usr/bin/udevadm', 'verify', ALSA])
        managers = run(['/usr/bin/systemctl','--no-pager','--no-legend','list-units','--all','user@*.service'])
        r.require(managers == baseline['commands']['user_managers']['stdout'], 'user-manager membership changed')
        for uid, previous in baseline['other_connect'].items():
            actual = run(['/usr/bin/systemctl','--user','--machine='+uid+'@.host','--no-pager','show',
                          '--property=Id,LoadState,ActiveState,SubState,UnitFileState,FragmentPath,DropInPaths',
                          'rpi-connect.service','rpi-connect-signin.path','rpi-connect-signin.service'])
            r.require(actual == previous['units']['stdout'], 'Connect state changed')
        timing = run(['/usr/local/bin/ntpq', '-n', '-c', 'rv 0'])
        r.require(re.search(r'\bleap=00\b', timing) and re.search(r'\bstratum=1\b', timing),
                  'NTP leap/stratum health')
        # Explicit list-only scanner; isolated APT does not run its regular hooks.
        run(['/usr/sbin/needrestart', '-r', 'l', '-b'], timeout=120)
        for unit in ('timeservice.service', 'gpsd.service', 'cron.service', 'munin-node.service'):
            actual = run(['/usr/bin/systemctl', '--no-pager', 'show',
                          '--property=Id,LoadState,ActiveState,SubState,MainPID,InvocationID,NRestarts', unit])
            r.require(actual == before['before']['services'][unit]['stdout'], 'service continuity: ' + unit)
        report.update(phase='pre-reboot-held', package_stage_complete=True,
                      controls_retained=True, independent_recovery_sha256=r.sha(backup))
        save()
    except BaseException as error:
        report.update(error=str(error), phase='held-after-package-intent' if package_intent else 'pre-package-failure',
                      controls_retained=package_intent)
        if created and not package_intent:
            deadline = time.monotonic() + 120
            try:
                if os.path.lexists(r.MARKER):
                    r.restore_inhibit('/', spec['operation_id'])
                for u in reversed(masked):
                    p = Path('/etc/systemd/system')/u
                    r.require(p.is_symlink() and os.readlink(p) == '/dev/null', 'foreign mask')
                    p.unlink(); r.sync(p.parent)
                run(['/usr/bin/systemctl', 'daemon-reload'])
                for u in UNITS:
                    if u.endswith('.timer'):
                        run(['/usr/bin/systemctl', 'start', u])
                report['pre_package_controls_restored'] = True
            except BaseException as cleanup:
                report['restoration_error'] = str(cleanup)
        save()
    if created:
        evidence, used = {}, 0
        report['evidence_export_complete'] = True
        for path in sorted(stage.iterdir()):
            if path.is_file() and (path.name.startswith('command-') or path.name in ('before.json','boot-after.json','alsa-parser.json')):
                raw, meta = r.read(path)
                row = {'sha256':meta['sha256'], 'size':meta['size']}
                if used + (len(raw)+2)//3*4 <= 12*1024**2:
                    row['base64'] = base64.b64encode(raw).decode()
                    used += len(row['base64'])
                else:
                    row['retained_on_target'] = True
                    report['evidence_export_complete'] = False
                evidence[path.name] = row
        report['evidence'] = evidence
    return report
