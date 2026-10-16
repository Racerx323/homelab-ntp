#!/usr/bin/python3
"""Seal Webmin prerequisite or recovered-startup inspection without live changes."""
import argparse
import base64
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

ROOT = Path(__file__).resolve().parents[1]
PATHS = {'runner.py': 'scripts/run-webmin-inspection.py',
         'helper.py': 'scripts/run-production-inspection.py',
         'tests.py': 'tests/test_webmin_inspection.py'}
FILES = ('/usr/lib/os-release', '/etc/systemd/system/ntpleapfetch.service',
         '/etc/systemd/system/ntpleapfetch.timer', '/var/lib/ntpsec/leap-seconds.list')
UNITS = ('timeservice.service', 'webmin.service', 'ntpleapfetch.service', 'ntpleapfetch.timer')
STARTUP_FILES = ('/etc/systemd/system/webmin.service', '/usr/lib/systemd/system/webmin.service',
                 '/etc/systemd/system/webmin.service.d/10-first-start.conf',
                 '/etc/webmin/.installation-accepted', '/etc/webmin/start', '/etc/webmin/stop',
                 '/var/webmin/miniserv.error', '/var/webmin/miniserv.pid')
MAIL_FILES = ('/etc/msmtprc', '/etc/aliases', '/usr/local/sbin/needrestart.sh',
              '/etc/cron.d/needrestart_check', '/etc/needrestart/needrestart.conf',
              '/etc/needrestart/conf.d/zz-ntp-policy.conf',
              '/etc/needrestart/conf.d/rpi-kernel.conf')
BUNDLE = 'webmin-inspection.tar'
helper = None


def load(path):
    spec = importlib.util.spec_from_file_location(path.stem.replace('-', '_'), path)
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value)
    return value


def boot():
    return Path('/proc/sys/kernel/random/boot_id').read_text().strip()


def command(argv):
    try:
        return helper.bounded(argv)
    except OSError as error:
        return {'argv': argv, 'returncode': None, 'error': str(error)}


def settings():
    """Retain only management scope settings, never users, passwords or keys."""
    row = helper.file_record('/etc/webmin/miniserv.conf', content=True)
    raw = row.pop('base64', None)
    if raw is not None:
        data = base64.b64decode(raw, validate=True)
        allowed = {'port', 'listen', 'bind', 'sockets', 'ipv6', 'ssl', 'ssl_redirect', 'allow', 'deny',
                   'allowusers', 'sudo', 'session', 'atboot', 'pidfile', 'errorlog', 'logfile',
                   'error_handler_401', 'error_handler_403', 'error_handler_404'}
        selected = {}
        for line in data.decode('utf-8').splitlines():
            key, separator, value = line.partition('=')
            if separator and key in allowed:
                if key in selected: raise ValueError('duplicate selected Webmin setting')
                # Only numerical ports, IP networks, hostnames and separators.
                if not re.fullmatch(r'[A-Za-z0-9 .,:/*_-]*', value):
                    value = '[unrecognized value omitted]'
                selected[key] = value
        row['settings'] = selected
        # Test an exact additive change without exporting unselected values.
        defaults = {f'error_handler_{n}={n}.cgi\n'.encode() for n in (401,403,404)}
        lines = data.splitlines(keepends=True)
        if all(lines.count(line)==1 for line in defaults):
            remainder = b''.join(line for line in lines if line not in defaults)
            row['without_default_handlers'] = {'sha256':helper.sha(remainder),'size':len(remainder)}
    return row


def temp_storage(spec):
    """Fixed-path metadata and aggregate usage only; never retain temp contents."""
    report = {'operation_id': spec['operation_id'], 'hostname': spec['hostname'],
              'spec_sha256': helper.sha(helper.encoded(spec)), 'boot_before': boot(),
              'capture_complete': False, 'production_accepted': False,
              'commands': {}, 'paths': {}}
    if socket.gethostname().split('.')[0] != spec['hostname'] or os.geteuid() != 0:
        raise ValueError('target/root identity mismatch')
    if report['boot_before'] != spec['boot_id']:
        report['error'] = 'accepted boot changed'; return report
    props = 'ActiveState,SubState,UnitFileState,MainPID,InvocationID,NRestarts'
    def units():
        return {unit: command(['/usr/bin/systemctl', 'show', unit, '--property='+props])
                for unit in ('timeservice.service', 'webmin.service')}
    before = units(); report['units_before'] = before
    for unit, expected in [('timeservice.service', spec['service_identity']),
                           ('webmin.service', spec['webmin_identity'])]:
        row = before[unit]
        values = dict(line.split('=', 1) for line in row.get('stdout', '').splitlines() if '=' in line)
        if row.get('returncode') != 0 or any(values.get(k) != v for k,v in expected.items()):
            report['error'] = 'accepted service identity changed'; return report
    config = helper.file_record('/etc/webmin/config', content=True)
    raw = config.pop('base64', None)
    config['settings'] = {}
    if raw is not None:
        for line in base64.b64decode(raw, validate=True).decode('utf-8').splitlines():
            key, sep, value = line.partition('=')
            if sep and (key == 'tempdir' or key.startswith('tempdir_')):
                if key in config['settings']: raise ValueError('duplicate temp setting')
                config['settings'][key] = value
    report['config'] = config
    for name in ('/tmp', '/var', '/var/tmp', '/tmp/.webmin', '/var/tmp/.webmin'):
        try:
            meta = Path(name).lstat()
            report['paths'][name] = {'mode': oct(stat.S_IMODE(meta.st_mode)),
                'uid': meta.st_uid, 'gid': meta.st_gid, 'symlink': stat.S_ISLNK(meta.st_mode),
                'directory': stat.S_ISDIR(meta.st_mode)}
        except FileNotFoundError:
            report['paths'][name] = {'missing': True}
    # Do not follow an unexpected link or traverse temp-file contents.
    if any(r.get('symlink') or (not r.get('missing') and not r.get('directory'))
           for r in report['paths'].values()):
        report['error'] = 'unexpected temp path type'; return report
    for name in ('/tmp', '/var/tmp'):
        report['commands']['mount:'+name] = command(['/usr/bin/findmnt', '-T', name,
            '--json', '--output', 'TARGET,SOURCE,FSTYPE,OPTIONS'])
        report['commands']['space:'+name] = command(['/usr/bin/df', '-B1', '--', name])
        report['commands']['inodes:'+name] = command(['/usr/bin/df', '-i', '--', name])
    if report['paths']['/tmp/.webmin'].get('directory'):
        report['commands']['webmin-usage'] = command(['/usr/bin/du', '-s', '-x', '-B1', '--', '/tmp/.webmin'])
    report['units_after'] = units(); report['boot_after'] = boot()
    report['capture_complete'] = (report['boot_after'] == report['boot_before']
        and report['units_after'] == before and raw is not None
        and not config.get('error') and not config.get('changed_during_read')
        and all(r.get('returncode') == 0 and not r.get('error') for r in report['commands'].values()))
    return report


def mail_settings():
    """Keep only relay settings; never export passwords or passwordeval commands."""
    row = helper.file_record('/etc/msmtprc', content=True)
    raw = row.pop('base64', None)
    row['selected_directives'] = []
    if raw is not None:
        allowed = {'account', 'host', 'port', 'from', 'domain', 'aliases', 'auth',
                   'tls', 'tls_starttls', 'set_from_header', 'allow_from_override'}
        for line in base64.b64decode(raw, validate=True).decode('utf-8').splitlines():
            parts = line.strip().split(None, 1)
            if len(parts) == 2 and parts[0] in allowed:
                value = parts[1]
                if not re.fullmatch(r'[A-Za-z0-9 .,:/@%_+\[\]-]*', value):
                    value = '[unrecognized value omitted]'
                row['selected_directives'].append([parts[0], value])
    return row


def collect(spec):
    if spec.get('temp_storage'):
        return temp_storage(spec)
    if socket.gethostname().split('.')[0] != spec['hostname'] or os.geteuid() != 0:
        raise ValueError('target/root identity mismatch')
    report = {'operation_id': spec['operation_id'], 'hostname': spec['hostname'],
              'spec_sha256': helper.sha(helper.encoded(spec)), 'started_epoch': time.time(),
              'boot_before': boot(), 'files': {}, 'commands': {}, 'capture_complete': False,
              'production_accepted': False}
    if report['boot_before'] != spec['boot_id']:
        report['error'] = 'accepted boot changed'; return report
    commands = {
        'packages': ['/usr/bin/dpkg-query', '-W', '-f=${binary:Package}\t${Version}\t${Architecture}\t${db:Status-Abbrev}\n'],
        'dpkg-audit': ['/usr/bin/dpkg', '--audit'],
        'architecture': ['/usr/bin/dpkg', '--print-architecture'],
        'listeners': ['/usr/bin/ss', '-H', '-lnt'],
        'addresses': ['/usr/sbin/ip', '-j', 'address', 'show'],
        'routes4': ['/usr/sbin/ip', '-j', '-4', 'route', 'show'],
        'routes6': ['/usr/sbin/ip', '-j', '-6', 'route', 'show'],
        'host-firewall': ['/usr/sbin/nft', 'list', 'ruleset'],
        'leap-journal': ['/usr/bin/journalctl', '--boot=0', '--no-pager', '-o', 'json', '-n', '30',
                         '-u', 'ntpleapfetch.service', '-u', 'ntpleapfetch.timer']}
    diagnostic = spec.get('startup_diagnostic', False)
    mail = spec.get('mail_reporting', False)
    recurrence = spec.get('timer_recurrence', False)
    if diagnostic:
        commands = {k: commands[k] for k in ('packages', 'dpkg-audit', 'architecture', 'addresses')}
        commands['listeners'] = ['/usr/bin/ss', '-H', '-lntu', 'sport = :10000']
        commands['webmin-journal'] = ['/usr/bin/journalctl', '--boot=0', '--no-pager', '-o', 'json',
                                    '-n', '100', '-u', 'webmin.service']
    if mail:
        commands = {k: commands[k] for k in ('packages', 'dpkg-audit', 'architecture', 'leap-journal')}
        commands.update({
            'clock': ['/usr/bin/date', '--iso-8601=seconds'],
            'uptime': ['/usr/bin/cat', '/proc/uptime'],
            'timezone': ['/usr/bin/timedatectl', 'show', '--property=Timezone'],
            'timer-list': ['/usr/bin/systemctl', 'list-timers', '--all', '--no-pager', 'ntpleapfetch.timer'],
            'timer-effective': ['/usr/bin/systemctl', 'cat', 'ntpleapfetch.timer'],
            'sendmail-path': ['/usr/bin/readlink', '-f', '/usr/sbin/sendmail']})
    if recurrence:
        commands = {k: commands[k] for k in ('packages', 'leap-journal')}
        commands.update({
            'clock': ['/usr/bin/date', '--iso-8601=seconds'],
            'uptime': ['/usr/bin/cat', '/proc/uptime'],
            'systemd-version': ['/usr/bin/systemctl', '--version'],
            'timer-list': ['/usr/bin/systemctl', 'list-timers', '--all', '--no-pager', 'ntpleapfetch.timer'],
            'timer-effective': ['/usr/bin/systemctl', 'cat', 'ntpleapfetch.timer'],
            'timer-manual': ['/usr/bin/zcat', '/usr/share/man/man5/systemd.timer.5.gz'],
            'manager-journal': ['/usr/bin/journalctl', '--boot=0', '--since=-4h', '--no-pager',
                                '-o', 'json', '-n', '120', '_PID=1', '--grep=Reload|reload|ntpleapfetch']})
    for unit in (('timeservice.service', 'webmin.service') if diagnostic else UNITS):
        props = 'Id,LoadState,ActiveState,SubState,UnitFileState,FragmentPath,DropInPaths'
        if unit.endswith('.service'):
            props += ',MainPID,NRestarts,InvocationID,Result,ExecMainCode,ExecMainStatus,ExecMainStartTimestamp,ExecMainExitTimestamp'
        else:
            props += ',LastTriggerUSec,NextElapseUSecMonotonic,NextElapseUSecRealtime,TimersMonotonic,RandomizedDelayUSec'
            if mail or recurrence:
                props += ',AccuracyUSec,FixedRandomDelay,Persistent,ActiveEnterTimestamp'
            if recurrence:
                props += ',InactiveExitTimestamp,InactiveExitTimestampMonotonic,ActiveEnterTimestampMonotonic'
        commands[unit] = ['/usr/bin/systemctl', 'show', unit, '--property='+props]
    before = command(commands['timeservice.service'])
    report['commands']['service-before'] = before
    # The accepted supervisor must still be running before collecting other data.
    expected = spec['service_identity']
    values = dict(line.split('=', 1) for line in before.get('stdout', '').splitlines() if '=' in line)
    if before.get('returncode') != 0 or any(values.get(k) != v for k,v in expected.items()):
        report['error'] = 'accepted service identity changed'; return report
    for path in (STARTUP_FILES if diagnostic else FILES):
        report['files'][path] = helper.file_record(path, content=True)
    if mail:
        report['mail_files'] = {path: helper.file_record(path) for path in MAIL_FILES}
        try: report['mail_settings'] = mail_settings()
        except (OSError, ValueError, UnicodeError) as error: report['mail_settings'] = {'error': str(error)}
    if diagnostic:
        report['payload_fingerprints'] = {path: helper.file_record(path) for path in
            ('/usr/share/webmin/miniserv.pl', '/usr/share/webmin/miniserv-lib.pl',
             '/usr/share/webmin/authentic-theme/authentic-init.pl',
             '/usr/share/webmin/authentic-theme/login-lib.pl')}
    try: report['webmin'] = {'not_collected': True} if mail or recurrence else settings()
    except (OSError, ValueError, UnicodeError) as error: report['webmin'] = {'error': str(error)}
    # Filenames and hashes establish local provenance hints without collecting
    # APT URI credentials, auth.conf, private signing keys or arbitrary unit text.
    report['apt_sources'] = {}
    paths = [] if diagnostic or mail or recurrence else [Path('/etc/apt/sources.list')]
    source_dir = Path('/etc/apt/sources.list.d')
    if diagnostic or mail or recurrence:
        pass
    elif source_dir.is_symlink():
        report['apt_sources']['error'] = 'symlink source directory'
    else:
        paths += sorted(source_dir.glob('*.list')) + sorted(source_dir.glob('*.sources'))
    if len(paths) > 64: raise ValueError('source inventory bound exceeded')
    for path in paths: report['apt_sources'][str(path)] = helper.file_record(path)
    for name, argv in commands.items(): report['commands'][name] = command(argv)
    report['boot_after'] = boot(); report['completed_epoch'] = time.time()
    after = report['commands']['timeservice.service']
    essential = ('packages', 'dpkg-audit', 'architecture', 'addresses', 'routes4', 'routes6', 'listeners',
                 'leap-journal', 'ntpleapfetch.service', 'ntpleapfetch.timer', 'timeservice.service')
    if diagnostic:
        essential = ('packages', 'dpkg-audit', 'architecture', 'addresses', 'listeners',
                     'webmin-journal', 'webmin.service', 'timeservice.service')
    if mail:
        essential = tuple(n for n in commands if n != 'sendmail-path')
    if recurrence:
        essential = tuple(commands)
    report['capture_complete'] = (report['boot_after'] == report['boot_before']
        and before == after
        and all(report['commands'][n].get('returncode') == 0 and not report['commands'][n].get('error') for n in essential)
        and all('error' not in r and not r.get('changed_during_read') for r in report['files'].values())
        and all('error' not in r and not r.get('changed_during_read') for r in report.get('payload_fingerprints', {}).values())
        and 'error' not in report['webmin'])
    if mail:
        report['capture_complete'] = (report['capture_complete']
            and 'error' not in report['mail_settings']
            and not report['mail_settings'].get('changed_during_read')
            and all('error' not in r and not r.get('changed_during_read') for r in report['mail_files'].values()))
    # Absent Webmin/nft and source metadata failures remain explicit findings.
    return report


def review(spec):
    if spec.get('timer_recurrence'):
        return f'''# Read-only leap-timer recurrence diagnostic

Target **{spec['hostname']}**, operation `{spec['operation_id']}`.
Pinned boot `{spec['boot_id']}`, accepted installation archive
`{spec['installation_sha256']}`; expires at epoch {spec['expires_epoch']}.

One pinned-key SSH capture as ama, sudo Python through stdin. Require accepted
NTP identity before collection and compare afterwards. Capture installed package
inventory, systemctl version, OS release, wall time and uptime. Read leap units
and leapfile, effective timer unit, installed systemd.timer manual, timer list,
and NTP/Webmin/leap service/timer state. Include timer activation monotonic
timestamps, last/next trigger, accuracy, random delay and persistence settings.
Capture 30 current-boot leap journal records plus at most 120 PID-1 journal
records from the last four hours matching Reload, reload or ntpleapfetch.
Retain these operational logs privately; they may name unrelated reload jobs.

Compare initial-delay base timestamps with reload events. Missing/truncated
history cannot prove a cause; no debug logging or reproduction on the host.
No mail settings, credentials, HTTP/login, SMTP connection, sendmail invocation,
package action, service/timer change, daemon-reload, clock action or reboot.
No relay contact. SSH/sudo may create ordinary audit logs; no rollback needed.

Commands/files bounded at 10 seconds/1 MiB, remote deadline 180 seconds,
SSH 210 seconds and 16 MiB per stream. Preserve partial results without retry.
Flat archive contains current runner/helper/tests, baseline hashes and host key.

After exact archive execution approval, from the repository root:
`python3 -I -B ntpsec/scripts/run-webmin-inspection.py execute --bundle ABSOLUTE_BUNDLE --sha256 APPROVED_SHA256`
'''
    if spec.get('mail_reporting'):
        return f'''# Read-only mail, needrestart and leap-timer inspection

Target **{spec['hostname']}**, operation `{spec['operation_id']}`.
Pinned boot `{spec['boot_id']}` and accepted installation archive
`{spec['installation_sha256']}`. Expires at epoch {spec['expires_epoch']}.

One pinned-key SSH capture as ama, sudo Python through stdin. Verify accepted
NTP identity before collection and compare afterwards. Read installed package
inventory, dpkg audit, architecture, OS release, wall time, uptime and timezone.
Capture Webmin, NTP and leap service/timer states, timer list, effective timer
unit, installed leap units/file, and 30 current-boot leap journal records.
Use last trigger, service results and journal timestamps to distinguish the
manual maintenance run from scheduled execution; report the actual next trigger.

Hash and retain ownership/mode/missing status for /etc/msmtprc, /etc/aliases,
/usr/local/sbin/needrestart.sh, /etc/cron.d/needrestart_check,
/etc/needrestart/needrestart.conf, /etc/needrestart/conf.d/zz-ntp-policy.conf
and /etc/needrestart/conf.d/rpi-kernel.conf.
Read only msmtp account, host, port, from, domain, aliases, auth, tls,
tls_starttls, set_from_header and allow_from_override directives.
Do not export other msmtp settings or aliases/cron/script contents. Resolve the
sendmail path without executing it; absence is a finding. User mail settings,
root crontab, credentials and remote Mailrise/controller state are not collected.
Missing files remain explicit findings; unreadable required data prevents acceptance.

No SMTP connection, DNS probe, notification, needrestart invocation, package
action, service/timer change, configuration write, clock action or reboot.
No Webmin HTTP/login or unrelated journal collection. No APT source collection.
SSH/sudo may create ordinary audit logs; no rollback needed. This capture cannot
establish mail delivery, relay reachability, firewall policy or production readiness.

Commands/files are bounded at 10 seconds/1 MiB, remote deadline 180 seconds,
SSH 210 seconds and 16 MiB per stream. Preserve partial results; never retry a
consumed capture. Flat archive contains runner/helper/tests, baseline and host key.

After exact archive execution approval, from the repository root:
`python3 -I -B ntpsec/scripts/run-webmin-inspection.py execute --bundle ABSOLUTE_BUNDLE --sha256 APPROVED_SHA256`
'''
    if spec.get('temp_storage'):
        return f'''# Read-only Webmin temporary-storage inspection

Target **{spec['hostname']}**, operation `{spec['operation_id']}`.
Pinned boot `{spec['boot_id']}` and accepted Webmin installation archive
`{spec['installation_sha256']}`. Expires at epoch {spec['expires_epoch']}.

One pinned-key SSH capture as ama, sudo Python through stdin. Require accepted
NTP and Webmin PID/invocation/restart/state identities before collection and
compare afterwards. Read only tempdir and tempdir_* settings from /etc/webmin/config;
retain configuration hash/metadata, never its other values. User overrides and
process environment are not collected; custom paths are reported, not traversed.

Inspect ownership/mode/type of /tmp, /var, /var/tmp, /tmp/.webmin and /var/tmp/.webmin.
Reject unexpected symlinks or non-directories. Missing candidate directories are
findings, not permission to create them. Use findmnt for /tmp and /var/tmp backing
and mount options, df for byte and inode capacity/use, and du for aggregate
/tmp/.webmin usage only. Do not retain temp filenames or contents. No write probe.

No configuration, directory, mount, service, package, clock or reboot changes;
no HTTP/login, credential files or logs. Ordinary SSH/sudo audit logs may occur.
No rollback needed. Capture completion does not establish storage suitability
for an unknown upload/backup workload or authorize moving the temp directory.

Reuse bounded commands (10 seconds/1 MiB), remote deadline 180 seconds,
SSH deadline 210 seconds, 16 MiB per stream; preserve partial results without retry.
Flat bundle contains current runner/helper/tests, baseline hashes and pinned host key.

After exact archive execution approval, from the repository root:
`python3 -I -B ntpsec/scripts/run-webmin-inspection.py execute --bundle ABSOLUTE_BUNDLE --sha256 APPROVED_SHA256`
'''
    if spec.get('startup_diagnostic'):
        return f'''# Read-only Webmin startup and configuration diagnostic

Target **{spec['hostname']}**, operation `{spec['operation_id']}`.
Pinned boot `{spec['boot_id']}`; recovered installation archive
`{spec['installation_sha256']}`. Expires at epoch {spec['expires_epoch']}.

One pinned-key SSH capture as ama, using sudo Python through stdin. Require
the retained NTP process/invocation/restart identity before collection and
compare again afterwards. Read installed package inventory, dpkg audit,
architecture, interface addresses, TCP/UDP port-10000 sockets, Webmin and
timeservice unit states/results/timestamps. Capture the last 100 current-boot
Webmin journal records, its fixed miniserv.error and PID files, generated
unit/start/stop files, first-start guard and permit presence/content. Hash the
installed miniserv implementation files and Authentic Theme's authentic-init.pl
and login-lib.pl. Missing files remain explicit findings;
read errors or incomplete required commands prevent capture acceptance.

Read only selected miniserv settings: port/listen/bind/sockets/ipv6, ssl and
ssl_redirect, allow/deny/allowusers, sudo/session/atboot and log/PID paths.
Also read error_handler_401, error_handler_403 and error_handler_404. The reviewed
Webmin 2.670 theme login code can add these three settings and reload miniserv;
their expected lines total 78 bytes, matching the observed growth. This is a
source-backed hypothesis, not a confirmed historical diff. Compare installed
theme fingerprints with the reviewed package before attributing behavior.
If all three exact default lines occur once, also return the SHA-256 and size
of the file with only those lines removed, without exporting that file. A match
to the retained pre-start hash proves those three additions explain all byte
changes; a mismatch leaves other changes unresolved. Never write this derived
content back to the target or use it to relax an execution gate automatically.
Do not read passwords, shadow/user files, sessions, cookies, private keys,
certificates or access logs. Journal/error output is private operational evidence;
do not publish raw records. No APT source contents or leap-timer observation.

Compare the selected settings and full-file hash with retained pre-start evidence.
The full pre-start configuration was not retained: if the derived hash does not
match, an exact historical diff remains unavailable. Report unchanged access
settings separately from any unexplained full-file hash change; do not infer that
all other changes are harmless. No configuration check is relaxed by this review.

No service start/restart/stop, configuration change, package action, HTTP probe,
login, clock action, reboot or target staging. SSH/sudo may create ordinary logs.
No recovery needed. This capture cannot establish HTTP or login acceptance.

Commands/files are bounded at 10 seconds/1 MiB, remote deadline 180 seconds,
SSH 210 seconds and 16 MiB per stream. Register locally before connecting;
preserve partial results and never retry a consumed capture. The flat archive
contains current repository collector/helper/tests and selected baseline hashes,
not a copy of the failed installation bundle or its packages.

After exact archive execution approval, from the repository root:
`python3 -I -B ntpsec/scripts/run-webmin-inspection.py execute --bundle ABSOLUTE_BUNDLE --sha256 APPROVED_SHA256`
'''
    return f'''# Read-only Webmin prerequisite and leap-timer inspection

Target **{spec['hostname']}**, operation `{spec['operation_id']}`.
Pinned boot `{spec['boot_id']}` and accepted leap activation archive
`{spec['activation_sha256']}`. Expires at epoch {spec['expires_epoch']}.

One pinned-key SSH capture as ama, using sudo Python through stdin. Require the
accepted boot and time-service PID/invocation/restart count before collection;
compare time-service state again afterwards. Capture installed package inventory,
dpkg audit and architecture, OS release, listening TCP sockets, addresses,
IPv4/IPv6 routes and host nftables rules. Missing Webmin or nft is a finding.
These observations do not prove controller firewall policy or External exposure.

Read Webmin service state and only the port/listen/bind/sockets/ipv6/ssl/ssl_redirect/
allow/deny/allowusers/sudo/session/atboot/pidfile/errorlog/logfile and the three
error_handler_401/403/404 fields from
miniserv.conf, plus its hash/metadata. Do not collect
Webmin users, passwords, private keys, certificates or other configuration.
Retain APT source filenames/hashes/metadata only: no source contents, credential
files, apt update, repository changes, package downloads or install actions.
Repository/key/package provenance still needs separate review before installation.

Read leap service/timer files, current leapfile, unit results/timestamps, next
trigger and 30 current-boot leap journal entries. Distinguish the prior manual
service run from a scheduled run using LastTriggerUSec and service/journal times.
No trigger is reported as pending, not as failure or proof of a later run.
Do not invoke ntpleapfetch, start the timer or force another download.

No service changes, web requests/login, network probes beyond SSH, clock action,
reboot or target staging. SSH/sudo may create ordinary logs. No recovery needed.
Commands and files are bounded at 10 seconds/1 MiB; overall remote deadline
180 seconds, SSH 210 seconds and 16 MiB per stream. Register execution locally
before connecting. Preserve partial results and never retry a consumed capture.
The flat archive contains current repository collector/helper/tests and selected
accepted baseline data, with no nested archives or historical executable inputs.

After exact archive execution approval, from the repository root:
`python3 -I -B ntpsec/scripts/run-webmin-inspection.py execute --bundle ABSOLUTE_BUNDLE --sha256 APPROVED_SHA256`
'''


def prepare(bundle, digest):
    raw = helper.private(bundle, 4*helper.LIMIT)
    if helper.sha(raw) != digest: raise ValueError('approved archive digest mismatch')
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        members = archive.getmembers(); names = set(PATHS) | {'spec.json', 'review.md', 'baseline.json', 'known_hosts'}
        if (len(members) != len(names) or {m.name for m in members} != names
                or any(not m.isfile() or m.size > helper.LIMIT for m in members)):
            raise ValueError('closed flat inspection archive required')
        files = {m.name: archive.extractfile(m).read() for m in members}
    spec = json.loads(files['spec.json'])
    if (spec['schema'] != 1 or spec['purpose'] != 'webmin-inspection' or spec['hostname'] != 'j2-svntp1'
            or not re.fullmatch(r'[a-z][a-z0-9-]{0,47}', spec['operation_id'])
            or not re.fullmatch(r'[a-f0-9-]{36}', spec['boot_id'])
            or spec['members'] != {n: helper.sha(files[n]) for n in set(PATHS) | {'baseline.json', 'known_hosts'}}
            or files['review.md'] != review(spec).encode()
            or not spec['prepared_epoch']-300 <= time.time() < spec['expires_epoch']-210
            or not 0 < spec['expires_epoch']-spec['prepared_epoch'] <= 86400):
        raise ValueError('inspection input binding/window')
    for name, path in PATHS.items():
        if files[name] != (ROOT/path).read_bytes(): raise ValueError('current repository input drift')
    for name in ('spec.json', 'review.md', 'known_hosts'):
        if helper.private(bundle.parent/name) != files[name]: raise ValueError('local approval input drift')
    return spec, files


def installation_baseline(args):
    installation = load(ROOT/'scripts/run-webmin-install.py')
    old, files = installation.prepare(args.installation_dir/'webmin-install.tar', args.installation_sha256)
    result_raw = helper.private(args.installation_dir/'result.json')
    state_raw = helper.private(args.installation_dir/'stdout.txt', 16*helper.LIMIT)
    result, state = json.loads(result_raw), json.loads(state_raw)
    accepted = any(getattr(args, mode, False) for mode in ('temp_storage', 'mail_reporting', 'timer_recurrence'))
    if (result.get('accepted') is not accepted or result.get('returncode') != 0 or result.get('error')
            or result.get('bundle_sha256') != args.installation_sha256
            or state.get('operation_id') != old['operation_id']
            or state.get('spec_sha256') != helper.sha(helper.encoded(old))
            or (accepted and (state.get('installed') is not True or state.get('recovery') != 'not-needed'))
            or (not accepted and (state.get('recovery') != 'non-serving; packages retained'
                                 or state.get('service_stopped') is not True))):
        raise ValueError('completed non-serving recovery or accepted installation required')
    identity = {k: state['webmin_unit'][k] for k in old['service_identity']} if accepted else None
    return old, files, old['service_identity'], {
        'installation_result_sha256': helper.sha(result_raw),
        'installation_state_sha256': helper.sha(state_raw),
        'pre_start_configuration_sha256': state.get('configuration_sha256'),
        'webmin_identity': identity}


def activation_baseline(args):
    activation = load(ROOT/'scripts/run-leap-activation.py')
    old, old_files = activation.prepare(args.activation_dir/'leap-activation.tar', args.activation_sha256)
    result_raw = helper.private(args.activation_dir/'result.json'); result = json.loads(result_raw)
    state_raw = helper.private(args.activation_dir/'stdout.txt', 24*helper.LIMIT); state = json.loads(state_raw)
    if (not result.get('accepted') or result.get('returncode') != 0 or result.get('error')
            or result['bundle_sha256'] != args.activation_sha256 or not state.get('accepted') or state.get('error')
            or state['operation_id'] != old['operation_id'] or state['spec_sha256'] != helper.sha(helper.encoded(old))
            or state['checks'] != dict.fromkeys(('isolated_fetch', 'maintenance_service', 'timer', 'continuity'), True)):
        raise ValueError('accepted activation prerequisite required')
    baseline = json.loads(old_files['baseline.json'])
    identity = {k: baseline['service'][k] for k in ('MainPID', 'InvocationID', 'NRestarts', 'ActiveState', 'SubState', 'UnitFileState')}
    return old, old_files, identity, {'activation_result_sha256': helper.sha(result_raw),
                                    'activation_state_sha256': helper.sha(state_raw)}


def seal(args):
    diagnostic = getattr(args, 'installation_dir', None) is not None
    if any(getattr(args, mode, False) for mode in ('temp_storage', 'mail_reporting', 'timer_recurrence')) and not diagnostic:
        raise ValueError('focused inspection requires accepted installation')
    if diagnostic:
        if not args.installation_sha256 or args.activation_sha256:
            raise ValueError('installation hash required without activation hash')
        old, old_files, identity, baseline = installation_baseline(args)
    else:
        if not args.activation_sha256 or args.installation_sha256:
            raise ValueError('activation hash required without installation hash')
        old, old_files, identity, baseline = activation_baseline(args)
    now = int(time.time())
    spec = {k: old[k] for k in ('hostname', 'boot_id', 'endpoints', 'host_key_alias')}
    spec.update(schema=1, purpose='webmin-inspection', operation_id=args.operation_id,
                service_identity=identity,
                prepared_epoch=now, expires_epoch=min(now+86400, old['expires_epoch']))
    if diagnostic:
        spec.update(startup_diagnostic=True, installation_sha256=args.installation_sha256)
        if getattr(args, 'temp_storage', False):
            spec.update(startup_diagnostic=False, temp_storage=True, webmin_identity=baseline['webmin_identity'])
        if getattr(args, 'mail_reporting', False):
            spec.update(startup_diagnostic=False, mail_reporting=True)
        if getattr(args, 'timer_recurrence', False):
            spec.update(startup_diagnostic=False, timer_recurrence=True)
    else:
        spec['activation_sha256'] = args.activation_sha256
    files = {n: (ROOT/p).read_bytes() for n,p in PATHS.items()}
    files['known_hosts'] = old_files['known_hosts']
    files['baseline.json'] = helper.encoded(baseline)
    spec['members'] = {n: helper.sha(raw) for n,raw in files.items()}
    files.update({'spec.json': helper.encoded(spec), 'review.md': review(spec).encode()})
    os.umask(0o077); args.output.mkdir(mode=0o700)
    for name in ('spec.json', 'review.md', 'known_hosts'): (args.output/name).write_bytes(files[name])
    bundle = args.output/BUNDLE
    with tarfile.open(bundle, 'w') as archive:
        for name,raw in sorted(files.items()):
            item = tarfile.TarInfo(name); item.size = len(raw); item.mode = 0o600
            archive.addfile(item, io.BytesIO(raw))
    digest = helper.sha(bundle.read_bytes()); prepare(bundle, digest)
    result = {'sha256': digest, 'bundle': str(bundle), 'expires_epoch': spec['expires_epoch'],
              'target_contact': False, 'execution_authorized': False}
    (args.output/'sealing.json').write_bytes(helper.encoded(result)); return result


def payload(spec, files):
    return ("__name__='sealed_webmin'\n__file__='/sealed/runner.py'\n".encode()+files['runner.py']
        + b"\nnamespace={'__name__':'sealed_helper','__file__':'/sealed/helper.py'}\nexec(compile("
        + repr(files['helper.py']).encode()+b", '/sealed/helper.py', 'exec'),namespace)\nhelper=types.SimpleNamespace(**namespace)\n"
        + b'signal.signal(signal.SIGALRM,helper.expired)\nsignal.alarm(180)\nprint(json.dumps(collect('
        + repr(spec).encode()+b')))\n')


def execute(args):
    os.umask(0o077); root = args.bundle.absolute().parent
    spec, files = prepare(args.bundle.absolute(), args.sha256); request = payload(spec, files)
    argv = helper.ssh_argv(spec, root)
    with (root/'execution.json').open('xb') as stream:
        stream.write(helper.encoded({'sha256': args.sha256, 'argv': argv,
            'payload_sha256': helper.sha(request), 'epoch': int(time.time())})); stream.flush(); os.fsync(stream.fileno())
    try:
        result = helper.bounded(argv, timeout=210, limit=16*helper.LIMIT, payload=request, env=os.environ.copy())
    except OSError as error:
        result = {'returncode': None, 'error': str(error), 'stdout': '', 'stderr': ''}
    for name in ('stdout', 'stderr'): (root/(name+'.txt')).write_text(result.pop(name))
    result.update(bundle_sha256=args.sha256, capture_complete=False, production_accepted=False)
    if result.get('returncode') == 0 and not result.get('error'):
        try:
            capture = json.loads((root/'stdout.txt').read_text())
            if (capture['spec_sha256'] != helper.sha(helper.encoded(spec))
                    or capture['operation_id'] != spec['operation_id'] or capture['hostname'] != spec['hostname']):
                raise ValueError('capture identity binding')
            result['capture_complete'] = capture.get('capture_complete') is True
        except (ValueError, KeyError, TypeError) as error: result['error'] = str(error)
    (root/'result.json').write_bytes(helper.encoded(result)); return result


def main():
    global helper
    helper = load(ROOT/'scripts/run-production-inspection.py')
    parser = argparse.ArgumentParser(description=__doc__); sub = parser.add_subparsers(dest='action', required=True)
    p = sub.add_parser('seal'); baseline = p.add_mutually_exclusive_group(required=True)
    baseline.add_argument('--activation-dir', type=Path)
    baseline.add_argument('--installation-dir', type=Path)
    p.add_argument('--activation-sha256'); p.add_argument('--installation-sha256')
    mode = p.add_mutually_exclusive_group()
    mode.add_argument('--temp-storage', action='store_true')
    mode.add_argument('--mail-reporting', action='store_true')
    mode.add_argument('--timer-recurrence', action='store_true')
    p.add_argument('--operation-id', required=True); p.add_argument('--output', type=Path, required=True)
    p = sub.add_parser('execute'); p.add_argument('--bundle', type=Path, required=True); p.add_argument('--sha256', required=True)
    args = parser.parse_args(); result = seal(args) if args.action == 'seal' else execute(args)
    print(json.dumps(result))
    if args.action == 'execute' and not result.get('capture_complete'): raise SystemExit(1)


if __name__ == '__main__': main()
