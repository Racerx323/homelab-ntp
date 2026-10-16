#!/usr/bin/python3
"""Activate reviewed leap maintenance without restarting time service."""
import base64
import json
import os
from pathlib import Path
import re
import signal
import socket
import stat
import time

SERVICE = '/etc/systemd/system/ntpleapfetch.service'
TIMER = '/etc/systemd/system/ntpleapfetch.timer'
LEAP = '/var/lib/ntpsec/leap-seconds.list'
FETCH = '/usr/local/bin/ntpleapfetch'
SOURCE = 'https://data.iana.org/time-zones/tzdb/leap-seconds.list'
PROPS = 'LoadState,ActiveState,SubState,UnitFileState,FragmentPath,DropInPaths'


def properties(raw):
    result = {}
    for line in raw.splitlines():
        key, value = line.split('=', 1)
        if key in result:
            raise ValueError('duplicate unit property')
        result[key] = value
    return result


def identity(row):
    if row.get('error') or row.get('missing') or row.get('changed_during_read'):
        raise ValueError('missing/unsafe file')
    return {k: row[k] for k in ('sha256', 'uid', 'gid', 'mode')}


def expiry(raw):
    values = re.findall(rb'^#@\s+(\d+)\s*$', raw, re.M)
    if len(values) != 1:
        raise ValueError('one leap expiry required')
    return int(values[0])-2208988800


class Activation:
    def __init__(self, spec, baseline, candidate, helper):
        self.spec, self.baseline, self.candidate, self.h = spec, baseline, candidate, helper
        self.root = Path('/var/lib/ntp-leap-'+spec['operation_id'])
        self.state = {'operation_id': spec['operation_id'], 'spec_sha256': helper.sha(helper.encoded(spec)),
                      'accepted': False, 'rollback': 'not-needed', 'commands': [], 'checks': {}}
        self.changed = False
        self.created = False

    def cmd(self, argv, timeout=10):
        row = self.h.bounded(argv, timeout=timeout)
        self.state['commands'].append(row)
        if row.get('returncode') != 0 or row.get('error'):
            raise ValueError('command failed: '+repr(argv))
        return row['stdout']

    def unit(self, name):
        extra = ',MainPID,NRestarts,InvocationID,Result' if name.endswith('.service') else ',NextElapseUSecMonotonic'
        return properties(self.cmd(['/usr/bin/systemctl', 'show', name, '--property='+PROPS+extra]))

    def continuity(self):
        if (socket.gethostname().split('.')[0] != self.spec['hostname'] or os.geteuid() != 0
                or Path('/proc/sys/kernel/random/boot_id').read_text().strip() != self.spec['boot_id']):
            raise ValueError('host/root/boot changed')
        current = self.unit('timeservice.service')
        expected = self.baseline['service']
        keys = ('MainPID', 'InvocationID', 'NRestarts', 'ActiveState', 'SubState', 'UnitFileState', 'DropInPaths', 'FragmentPath')
        if any(current[k] != expected[k] for k in keys) or current['ActiveState'] != 'active' or current['SubState'] != 'running':
            raise ValueError('timeservice continuity changed')

    def files_match(self, candidate=False):
        for path, expected in self.baseline['files'].items():
            wanted = identity(expected)
            if candidate and path == SERVICE:
                wanted = dict(wanted, sha256=self.h.sha(self.candidate))
            if identity(self.h.file_record(path)) != wanted:
                raise ValueError('file drift: '+path)

    def idle(self):
        service, timer = self.unit('ntpleapfetch.service'), self.unit('ntpleapfetch.timer')
        for row, path in ((service, SERVICE), (timer, TIMER)):
            if row['LoadState'] != 'loaded' or row['ActiveState'] != 'inactive' or row['SubState'] != 'dead' or row['DropInPaths'] or row['FragmentPath'] != path:
                raise ValueError('leap unit not idle or overridden')
        if service['UnitFileState'] != 'static' or service['Result'] != 'success' or timer['UnitFileState'] != 'disabled':
            raise ValueError('unexpected leap enablement/result')

    def replace(self, raw):
        path = Path(SERVICE)
        # No symlinks, unexpected type, owner or concurrent file replacement.
        before = identity(self.h.file_record(path))
        allowed = (identity(self.baseline['files'][SERVICE]),
                   dict(identity(self.baseline['files'][SERVICE]), sha256=self.h.sha(self.candidate)))
        if before not in allowed:
            raise ValueError('foreign service file; hold')
        temp = path.with_name('.ntpleapfetch-'+self.spec['operation_id']+'.tmp')
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(raw); stream.flush(); os.fchown(stream.fileno(), 0, 0)
                os.fchmod(stream.fileno(), 0o644); os.fsync(stream.fileno())
            if identity(self.h.file_record(path)) != before:
                raise ValueError('service changed during replacement')
            os.replace(temp, path)
        finally:
            if temp.exists(): temp.unlink()

    def save(self):
        (self.root/'state.json').write_bytes(self.h.encoded(self.state))

    def recover(self):
        self.continuity(); self.files_match(candidate=True)
        for name, path in (('ntpleapfetch.service', SERVICE), ('ntpleapfetch.timer', TIMER)):
            row = self.unit(name)
            if row['DropInPaths'] or row['FragmentPath'] != path:
                raise ValueError('foreign effective unit; recovery held')
        self.cmd(['/usr/bin/systemctl', 'disable', '--now', 'ntpleapfetch.timer'], 30)
        self.cmd(['/usr/bin/systemctl', 'stop', 'ntpleapfetch.service'], 30)
        self.replace(base64.b64decode(self.baseline['files'][SERVICE]['base64'], validate=True))
        self.cmd(['/usr/bin/systemctl', 'daemon-reload'], 30)
        self.cmd(['/usr/bin/systemctl', 'reset-failed', 'ntpleapfetch.service'])
        self.files_match(); self.continuity(); self.idle()
        self.state['rollback'] = 'restored'

    def apply(self):
        self.continuity(); self.files_match(); self.idle()
        raw = base64.b64decode(self.baseline['files'][LEAP]['base64'], validate=True)
        if expiry(raw) <= time.time()+61*86400:
            raise ValueError('live leapfile no longer outside prefetch window')
        directory = Path('/var/lib/ntpsec')
        info = directory.lstat()
        if directory.is_symlink() or (info.st_mode, info.st_uid, info.st_gid) != (stat.S_IFDIR | 0o755, 0, 0):
            raise ValueError('leap directory drift')
        # mkdir is exclusive: an interrupted operation cannot be blindly repeated.
        self.root.mkdir(mode=0o700)
        self.created = True
        (self.root/'original.service').write_bytes(base64.b64decode(self.baseline['files'][SERVICE]['base64'], validate=True))
        candidate = self.root/'ntpleapfetch.service'; candidate.write_bytes(self.candidate)
        self.save()
        self.cmd(['/usr/bin/systemd-analyze', 'verify', str(candidate)], 30)
        destination = self.root/'downloaded.list'
        self.cmd([FETCH, '-F', '-s', SOURCE, '-f', '/etc/ntp.conf', '-t', str(self.root/'download.tmp'),
                  '-r', '3', '-i', '0', '-e', '60 days', str(destination)], 120)
        downloaded = self.h.file_record(destination, content=True)
        identity(downloaded)
        if (downloaded['uid'], downloaded['gid'], downloaded['mode']) != (0, 0, self.baseline['files']['/etc/ntp.conf']['mode']):
            raise ValueError('download ownership/mode mismatch')
        if expiry(base64.b64decode(downloaded['base64'], validate=True)) <= time.time():
            raise ValueError('download expired')
        self.state['download'] = downloaded
        self.continuity(); self.files_match(); self.idle()
        self.state['checks']['isolated_fetch'] = True
        # Persist intent before the first persistent configuration mutation.
        self.state['rollback'] = 'pending'; self.save(); self.changed = True
        self.replace(self.candidate)
        self.cmd(['/usr/bin/systemctl', 'daemon-reload'], 30)
        self.cmd(['/usr/bin/systemctl', 'start', 'ntpleapfetch.service'], 135)
        self.files_match(candidate=True); self.continuity(); self.idle()
        self.state['checks']['maintenance_service'] = True
        self.cmd(['/usr/bin/systemctl', 'enable', '--now', 'ntpleapfetch.timer'], 30)
        timer = self.unit('ntpleapfetch.timer')
        if (timer['ActiveState'], timer['SubState'], timer['UnitFileState'], timer['DropInPaths'], timer['FragmentPath']) != ('active', 'waiting', 'enabled', '', TIMER):
            raise ValueError('timer activation failed')
        if timer['NextElapseUSecMonotonic'] in ('', '0', 'infinity'):
            raise ValueError('timer has no scheduled trigger')
        self.state['timer'] = timer
        self.files_match(candidate=True); self.continuity()
        self.state['checks'].update(timer=True, continuity=True)
        self.state.update(accepted=True, rollback='not-needed')

    def run(self):
        os.umask(0o077)
        try:
            self.apply()
        except Exception as error:
            self.state['error'] = str(error)
            signal.alarm(0)
            if self.changed:
                try: self.recover()
                except Exception as failure:
                    self.state.update(rollback='held', recovery_error=str(failure))
        finally:
            if self.created: self.save()
        return self.state


def interrupted(signum, frame):
    raise RuntimeError('operation interrupted by signal '+str(signum))


def run(spec, baseline, candidate, helper):
    for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
        signal.signal(sig, interrupted)
    return Activation(spec, baseline, candidate, helper).run()
