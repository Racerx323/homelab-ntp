#!/usr/bin/python3
"""Non-mutating installed-script, hook, EEPROM and Connect inventory; injected m."""
import json
import os
from pathlib import Path
import signal
import socket
import stat
import sys
import time

m = None
ROOTS = ('/var/lib/dpkg/triggers', '/etc/initramfs-tools', '/usr/share/initramfs-tools', '/etc/kernel', '/etc/initramfs/post-update.d',
         '/etc/ca-certificates/update.d', '/etc/apt/listchanges.conf.d', '/etc/systemd/system/rpi-eeprom-update.service.d',
         '/run/systemd/system/rpi-eeprom-update.service.d', '/usr/lib/systemd/system/rpi-eeprom-update.service.d',
         '/etc/modprobe.d', '/usr/lib/modprobe.d', '/etc/ld.so.conf.d')
HELPERS = ('/usr/sbin/update-initramfs', '/usr/sbin/mkinitramfs', '/usr/sbin/flash-kernel',
           '/usr/sbin/update-ca-certificates', '/usr/bin/apt-listchanges', '/etc/apt/listchanges.conf',
           '/usr/lib/needrestart/apt-pinvoke', '/usr/sbin/needrestart', '/usr/bin/deb-systemd-invoke',
           '/usr/bin/deb-systemd-helper', '/usr/sbin/invoke-rc.d', '/usr/sbin/policy-rc.d',
           '/usr/share/initramfs-tools/hook-functions', '/usr/share/initramfs-tools/init',
           '/var/lib/systemd/deb-systemd-helper-enabled/rpi-eeprom-update.service.dsh-also',
           '/var/lib/systemd/deb-systemd-helper-masked/rpi-eeprom-update.service',
           '/etc/default/raspi-firmware', '/etc/ld.so.conf', '/usr/bin/linux-version',
           '/var/lib/dpkg/info/initramfs-tools.postinst', '/var/lib/dpkg/info/initramfs-tools.triggers',
           '/var/lib/dpkg/info/libc-bin.postinst', '/var/lib/dpkg/info/libc-bin.triggers',
           '/etc/default/flash-kernel', '/etc/flash-kernel/db', '/var/lib/dpkg/diversions',
           '/var/lib/dpkg/statoverride', '/etc/timezone', '/etc/localtime',
           '/run/rpi-eeprom-update-pending', '/run/systemd/sleep.conf.d/40-rpi-eeprom-update-pending.conf',
           '/usr/lib/systemd/user/rpi-connect.service', '/usr/lib/systemd/user/rpi-connect-signin.path',
           '/usr/lib/systemd/user/rpi-connect-signin.service')
SUFFIXES = ('preinst', 'postinst', 'prerm', 'postrm', 'triggers', 'conffiles')
DT = ('system/linux,revision', 'chosen/bootloader/build-timestamp', 'chosen/bootloader/capabilities',
      'chosen/rpi-min-boot-ver')


def tree(root, content=True):
    """Never follow links; bounded root-owned directories and regular files only."""
    root = Path(root)
    rows = {}
    def visit(path, depth):
        m.require(depth <= 5 and len(rows) < 768, 'tree bound')
        m.require(not any(p.is_symlink() for p in path.parents), 'indirect tree ancestor')
        try: info = path.lstat()
        except FileNotFoundError:
            rows[str(path)] = {'missing': True}; return
        if stat.S_ISDIR(info.st_mode):
            m.require(info.st_uid == 0 and not info.st_mode & 0o022, 'unprotected hook directory')
            children = sorted(path.iterdir())
            m.require(len(children) <= 256, 'directory bound')
            rows[str(path)] = {'members': [p.name for p in children]}
            for child in children: visit(child, depth+1)
        else:
            rows[str(path)] = m.record(path, content)
        m.require(len(json.dumps(rows)) <= 4*1024**2, 'tree output bound')
    visit(root, 0)
    return rows


def metadata(path):
    """Existence/link metadata only, including user credential sentinel paths."""
    path = Path(path)
    for parent in path.parents:
        if parent.is_symlink(): return {'unresolved_indirect_parent': str(parent)}
    try: s = path.lstat()
    except FileNotFoundError: return {'missing': True}
    return {'uid': s.st_uid, 'gid': s.st_gid, 'mode': stat.S_IMODE(s.st_mode),
            'type': stat.S_IFMT(s.st_mode), 'size': s.st_size,
            'link': os.readlink(path) if stat.S_ISLNK(s.st_mode) else None}


def collect(spec, baseline):
    report = {'operation_id': spec['operation_id'], 'capture_complete': False,
              'started_epoch': time.time(), 'commands': {}, 'target_mutation': False}
    def alarm(*_): raise TimeoutError('240-second inspection bound')
    signal.signal(signal.SIGALRM, alarm); signal.signal(signal.SIGTERM, alarm)
    signal.alarm(240)
    def state():
        extras = [k for k in baseline['configuration']['files'] if '/systemd/' in k]
        services = {u:m.command(['/usr/bin/systemctl','--no-pager','show',
                    '--property=Id,LoadState,ActiveState,SubState,MainPID,InvocationID,NRestarts',u])
                    for u in m.SERVICES if u != 'gpsd.socket'}
        procs = m.command(['/usr/bin/ps','-eo','pid,ppid,comm'])
        m.require(procs['accepted'] and all(x['accepted'] for x in services.values()), 'state commands')
        return {'configuration': m.configuration(extras), 'apt_lists': m.list_metadata(),
                'services': services, 'runtime': m.runtime(procs['stdout']), 'locks': m.lock_state(),
                'boot': Path('/proc/sys/kernel/random/boot_id').read_text().strip()}
    try:
        m.require(os.geteuid() == 0 and os.environ.get('SUDO_USER') == 'ama' and
                  os.environ.get('SUDO_UID') == '1000' and socket.gethostname() == 'j2-svntp1', 'identity')
        m.require(sys.flags.isolated and sys.dont_write_bytecode, 'isolated Python')
        m.require(spec['prepared_epoch']-300 <= time.time() < spec['expires_epoch']-300, 'time window')
        m.require(os.uname().release == spec['kernel'], 'kernel drift')
        before = state(); report['before'] = before
        m.require(before['boot'] == spec['boot'] and before['configuration'] == baseline['configuration'], 'baseline drift')
        m.require(not before['locks']['held'], 'package lock held')
        report['scripts'] = {}
        for row in spec['packages']:
            for prefix in (row['package'], row['package']+':'+row['architecture']):
                for suffix in SUFFIXES:
                    path = '/var/lib/dpkg/info/'+prefix+'.'+suffix
                    report['scripts'][path] = m.record(path, True)
        report['trees'] = {}
        for root in ROOTS: report['trees'][root] = tree(root)
        report['helpers'] = {}
        for path in HELPERS: report['helpers'][path] = m.record(path, True)
        report['firmware'] = {}
        for path in ('/usr/lib/firmware/raspberrypi/bootloader-2711/default',
                     '/var/lib/raspberrypi/bootloader/backup'):
            report['firmware'][path] = tree(path, False)
        report['boot_artifacts'] = {}
        for parent in ('/boot','/boot/firmware'):
            for path in m.members(parent):
                if path.name.startswith(('initrd','initramfs','vmlinuz','kernel','pieeprom','vl805','recovery.')):
                    report['boot_artifacts'][str(path)] = m.record(path, False)
        report['device_tree'] = {}
        for name in DT:
            path = Path('/sys/firmware/devicetree/base')/name
            row = metadata(path)
            if not row.get('missing') and not row.get('unresolved_indirect_parent'):
                m.require(row['type'] == stat.S_IFREG and not path.is_symlink(), 'device-tree type')
                with path.open('rb') as f: raw = f.read(65)
                m.require(len(raw) <= 64, 'device-tree bound')
                row['hex'] = raw.hex()
            report['device_tree'][str(path)] = row
        import pwd
        user = pwd.getpwnam('ama'); m.require(user.pw_uid == 1000 and user.pw_dir == '/home/ama', 'user identity')
        paths = ['/var/lib/systemd/linger/ama','/run/user/1000/bus']
        paths += ['/home/ama/'+p for p in ('.config/systemd/user/default.target.wants/rpi-connect.service',
                  '.config/systemd/user/rpi-connect.service', '.config/systemd/user/rpi-connect.service.d',
                  '.config/systemd/user/rpi-connect.service.wants/rpi-connect-signin.path',
                  '.config/com.raspberrypi.connect/auth.key')]
        report['connect_metadata'] = {p:metadata(p) for p in paths}
        if report['connect_metadata']['/run/user/1000/bus'].get('type') == stat.S_IFSOCK:
            report['commands']['connect_show'] = m.command(['/usr/bin/systemctl','--user','--machine=ama@.host',
                '--no-pager','show','--property=Id,LoadState,ActiveState,SubState,UnitFileState,FragmentPath,DropInPaths',
                'rpi-connect.service','rpi-connect-signin.path','rpi-connect-signin.service'], (0,1))
        # Bound all existing user managers; never create a session or start a unit.
        managers = m.query(report['commands'], 'user_managers', ['/usr/bin/systemctl',
            '--no-pager', '--no-legend', 'list-units', '--all', 'user@*.service'])
        import re
        ids = sorted(set(re.findall(r'\buser@([0-9]+)\.service\b', managers)))
        m.require(len(ids) <= 16, 'user manager bound')
        report['other_connect'] = {}
        for uid in ids:
            bus = metadata('/run/user/'+uid+'/bus')
            row = {'bus': bus}
            if bus.get('type') == stat.S_IFSOCK:
                row['units'] = m.command(['/usr/bin/systemctl','--user','--machine='+uid+'@.host',
                    '--no-pager','show','--property=Id,LoadState,ActiveState,SubState,UnitFileState,FragmentPath,DropInPaths',
                    'rpi-connect.service','rpi-connect-signin.path','rpi-connect-signin.service'], (0,1))
            report['other_connect'][uid] = row
        for label,argv in (
            ('audit',['/usr/bin/dpkg','--audit']),
            ('eeprom_unit',['/usr/bin/systemctl','--no-pager','show',
              '--property=Id,UnitFileState,FragmentPath,DropInPaths,ExecStart,EnvironmentFiles','rpi-eeprom-update.service'])):
            m.query(report['commands'], label, argv)
        report['planned_control_metadata'] = {p:metadata(p) for p in ('/var/lib/ntp-maintenance', '/var/lib/ntp-maintenance/eeprom-inhibit')}
        report['capacity'] = {p:{'bytes':os.statvfs(p).f_bavail*os.statvfs(p).f_frsize,
                                'inodes':os.statvfs(p).f_favail} for p in ('/','/boot/firmware')}
        m.require(not report['commands']['audit']['stdout'].strip(), 'dpkg audit')
        report['capture_complete'] = True
    except BaseException as error: report.update(error=type(error).__name__+': '+str(error), held=True)
    finally:
        signal.alarm(0)
        if 'before' in report:
            signal.alarm(90)
            try:
                report['after'] = state()
                stable = all(report['before'][k] == report['after'][k] for k in ('configuration','apt_lists','services','runtime','boot'))
                report['inputs_after'] = {}
                for group in ('scripts', 'helpers'):
                    if group in report:
                        report['inputs_after'][group] = {p:m.record(p, True) for p in report[group]}
                        stable = stable and report['inputs_after'][group] == report[group]
                for group in ('trees', 'firmware'):
                    if group in report:
                        report['inputs_after'][group] = {p:tree(p, group == 'trees') for p in report[group]}
                        stable = stable and report['inputs_after'][group] == report[group]
                if 'boot_artifacts' in report:
                    report['inputs_after']['boot_artifacts'] = {p:m.record(p, False) for p in report['boot_artifacts']}
                    stable = stable and report['inputs_after']['boot_artifacts'] == report['boot_artifacts']
                report['protected_continuity'] = stable and not report['after']['locks']['held']
                if not report['protected_continuity']: report.update(capture_complete=False, held=True)
            except BaseException as error: report.update(capture_complete=False, held=True, continuity_error=str(error))
        signal.alarm(0)
        report['finished_epoch'] = time.time()
    return report
