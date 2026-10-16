#!/usr/bin/python3
"""Install the reviewed statistics rule; no service changes or unpreviewed deletion."""
import json
import os
from pathlib import Path
import re
import signal
import socket
import stat
import time

STATS = Path('/var/log/ntpstats')
RULE = Path('/etc/logrotate.d/ntpstats-retention')
CONTROL = Path('/var/lib/ntpstats-retention')
STREAMS = ('loopstats', 'peerstats', 'clockstats', 'protostats')
CHECKS = ('preflight', 'target_fixtures', 'debug', 'empty_preview', 'first_run', 'continuity')


def properties(raw):
    result = {}
    for line in raw.splitlines():
        k, v = line.split('=', 1)
        if k in result:
            raise ValueError('duplicate unit property')
        result[k] = v
    return result


def identity(row):
    if row.get('error') or row.get('missing') or row.get('changed_during_read'):
        raise ValueError('unsafe file identity')
    return {k: row[k] for k in ('sha256', 'uid', 'gid', 'mode')}


def directory(path, owner=None, mode=None):
    for p in (path, *path.parents):
        if p.is_symlink():
            raise ValueError('indirect directory: '+str(path))
    meta = path.stat()
    if owner is not None and stat.S_IMODE(meta.st_mode) & 0o022:
        raise ValueError('writable trusted directory: '+str(path))
    if not stat.S_ISDIR(meta.st_mode) or (owner is not None and (meta.st_uid, meta.st_gid) != owner) or (mode is not None and stat.S_IMODE(meta.st_mode) != mode):
        raise ValueError('directory identity: '+str(path))
    return meta


def preview(now=None):
    """Same selection as find: at least 30 elapsed days, one link, no active inode."""
    now = time.time() if now is None else now
    directory(STATS)
    active = set()
    for name in STREAMS:
        p = STATS/name; meta = p.lstat()
        if not stat.S_ISREG(meta.st_mode) or p.is_symlink():
            raise ValueError('unsafe active base: '+name)
        active.add((meta.st_dev, meta.st_ino))
    rows = list(STATS.iterdir())
    if len(rows) > 5000:
        raise ValueError('statistics entry bound')
    result = []
    for p in sorted(rows):
        info = p.lstat()
        if (re.fullmatch(r'(loopstats|peerstats|clockstats|protostats)\.[0-9]{8}(\.gz)?', p.name)
                and stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                and (info.st_dev, info.st_ino) not in active and now-info.st_mtime >= 30*86400):
            result.append({'name': p.name, 'inode': info.st_ino, 'bytes': info.st_size, 'mtime': info.st_mtime})
    return result


class Deployment:
    def __init__(self, spec, baseline, files, helper):
        self.spec, self.baseline, self.files, self.h = spec, baseline, files, helper
        self.root = Path('/var/lib/ntpstats-'+spec['operation_id'])
        self.state = {'operation_id': spec['operation_id'], 'spec_sha256': helper.sha(helper.encoded(spec)),
                      'installed': False, 'retention_accepted': False, 'checks': {}, 'commands': [],
                      'rollback': 'not-needed'}
        self.created = False
        self.control_created = False
        self.rule_created = False

    def save(self):
        if self.created:
            temp = self.root/'state.tmp'
            with temp.open('wb') as stream:
                stream.write(self.h.encoded(self.state)); stream.flush(); os.fsync(stream.fileno())
            os.replace(temp, self.root/'state.json')

    def command(self, argv, timeout=20, env=None):
        row = self.h.bounded(argv, timeout=timeout, env=env)
        self.state['commands'].append(row)
        if row.get('returncode') != 0 or row.get('error'):
            raise ValueError('command failed: '+repr(argv))
        return row['stdout']

    def continuity(self):
        if (os.geteuid() != 0 or socket.gethostname().split('.')[0] != self.spec['hostname']
                or Path('/proc/sys/kernel/random/boot_id').read_text().strip() != self.spec['boot_id']):
            raise ValueError('host/root/boot mismatch')
        current = properties(self.command(['/usr/bin/systemctl', 'show', 'timeservice.service',
            '--property=LoadState,MainPID,InvocationID,NRestarts,ActiveState,SubState,UnitFileState']))
        if current != self.baseline['service']:
            raise ValueError('NTP service continuity changed')
        p = Path('/proc')/self.baseline['writer']['pid']
        if ((p/'comm').read_text().strip() != 'ntpd'
                or (p/'stat').read_text().rsplit(')', 1)[1].split()[19] != self.baseline['writer']['start_ticks']
                or os.readlink(p/'exe') != self.baseline['writer']['exe']):
            raise ValueError('NTP writer continuity changed')

    def guards(self):
        for name, expected in self.baseline['guards'].items():
            if identity(self.h.file_record(name)) != expected:
                raise ValueError('guarded maintenance/configuration drift: '+name)
        directory(RULE.parent, (0, 0))
        names = {p.name for p in RULE.parent.iterdir()}
        expected = set(self.baseline['rule_names']) | ({RULE.name} if self.rule_created else set())
        if names != expected:
            raise ValueError('logrotate include membership drift')
        meta = directory(STATS)
        if (meta.st_uid, meta.st_gid, stat.S_IMODE(meta.st_mode)) != tuple(self.baseline['stats_directory']):
            raise ValueError('statistics directory drift')
        fs = os.statvfs(STATS)
        self.state['storage'] = {'available_bytes': fs.f_bavail*fs.f_frsize, 'available_inodes': fs.f_favail,
                                 'inode_free_fraction': fs.f_favail/fs.f_files if fs.f_files else 0}
        if self.state['storage']['available_bytes'] < self.spec['minimum_free_bytes'] or self.state['storage']['inode_free_fraction'] < self.spec['minimum_free_inode_fraction']:
            raise ValueError('storage review threshold crossed; do not shorten retention')
        timer = properties(self.command(['/usr/bin/systemctl', 'show', 'logrotate.timer',
            '--property=LoadState,ActiveState,SubState,UnitFileState,NextElapseUSecRealtime']))
        if any(timer.get(k) != v for k,v in {'LoadState':'loaded','ActiveState':'active','SubState':'waiting','UnitFileState':'enabled'}.items()) or timer.get('NextElapseUSecRealtime') in (None, '', 'n/a'):
            raise ValueError('daily scheduler unavailable')
        self.state['timer'] = timer
        unit = properties(self.command(['/usr/bin/systemctl', 'show', 'logrotate.service',
                                       '--property=ActiveState,SubState']))
        if unit != {'ActiveState':'inactive','SubState':'dead'}:
            raise ValueError('logrotate service not idle')

    def active(self):
        p = Path('/proc')/self.baseline['writer']['pid']
        open_files = set()
        for fd in (p/'fd').iterdir():
            try:
                meta = fd.stat()
                flags = next(line.split()[1] for line in (p/'fdinfo'/fd.name).read_text().splitlines() if line.startswith('flags:'))
                if int(flags, 8) & os.O_ACCMODE in (os.O_WRONLY, os.O_RDWR):
                    open_files.add((meta.st_dev, meta.st_ino))
            except FileNotFoundError:
                continue
        rows = {}
        for name in STREAMS:
            path = STATS/name; meta = path.lstat()
            if (not stat.S_ISREG(meta.st_mode) or meta.st_nlink < 2
                    or (meta.st_dev, meta.st_ino) not in open_files):
                raise ValueError('active statistics association missing: '+name)
            rows[name] = {'inode':meta.st_ino,'bytes':meta.st_size,'mtime_ns':meta.st_mtime_ns}
        return rows

    def empty_preview(self):
        rows = preview()
        self.state['deletion_preview'] = rows
        if rows != self.spec['approved_deletion_preview']:
            raise ValueError('deletion preview changed; fresh review required')

    def recover(self):
        # Disable only our exact rule; do not touch a foreign edit or NTP services.
        if self.rule_created:
            if identity(self.h.file_record(RULE)) != {'sha256':self.h.sha(self.files['candidate']), 'uid':0,'gid':0,'mode':0o644}:
                raise ValueError('foreign rule; recovery held')
            RULE.unlink(); self.rule_created = False
        if self.control_created:
            directory(CONTROL, (0,0), 0o700)
            for p in CONTROL.iterdir():
                if p.name != 'trigger' or identity(self.h.file_record(p)) != {'sha256':self.h.sha(b''),'uid':0,'gid':0,'mode':0o600}:
                    raise ValueError('foreign control state; recovery held')
                p.unlink()
            CONTROL.rmdir(); self.control_created = False
        self.state['rollback'] = 'rule disabled; original absence restored; operation evidence retained'

    def apply(self):
        self.continuity(); self.guards()
        if RULE.exists() or RULE.is_symlink() or CONTROL.exists() or CONTROL.is_symlink():
            raise ValueError('retention paths already exist')
        directory(Path('/var/lib'), (0,0))
        self.empty_preview(); self.state['active_before'] = self.active()
        self.state['checks']['preflight'] = True
        self.root.mkdir(mode=0o700); self.created = True; self.save()
        # Run the exact retention fixture against target tools in a private tree.
        fixture = self.root/'fixture/ntpsec'
        (fixture/'tests').mkdir(parents=True, mode=0o700)
        (fixture/'templates').mkdir(mode=0o700)
        (fixture/'tests/test_stats_retention.py').write_bytes(self.files['fixtures.py'])
        (fixture/'templates/ntpstats-retention.logrotate').write_bytes(self.files['candidate'])
        tmp = self.root/'tmp'; tmp.mkdir(mode=0o700)
        self.command(['/usr/bin/python3','-I','-B',str(fixture/'tests/test_stats_retention.py')],90,
                     {'PATH':'/usr/sbin:/usr/bin:/sbin:/bin','LC_ALL':'C','TMPDIR':str(tmp)})
        self.state['checks']['target_fixtures'] = True
        self.continuity(); self.guards(); self.empty_preview()
        self.state['rollback'] = 'pending'; self.save()
        CONTROL.mkdir(mode=0o700); self.control_created = True
        trigger = CONTROL/'trigger'
        with trigger.open('xb'):
            pass
        trigger.chmod(0o600)
        candidate = self.root/'candidate'; candidate.write_bytes(self.files['candidate']); candidate.chmod(0o644)
        self.command(['/usr/sbin/logrotate','--debug','--state',str(self.root/'initial.state'),str(candidate)])
        self.state['checks']['debug'] = True
        self.continuity(); self.guards(); self.empty_preview(); self.active()
        # The inspected preview is empty, so the first real run may not delete data.
        self.state['checks']['empty_preview'] = True
        os.link(candidate, RULE); self.rule_created = True; candidate.unlink()
        self.save()
        self.command(['/usr/sbin/logrotate','--force','--state',str(self.root/'initial.state'),str(RULE)])
        if identity(self.h.file_record(RULE)) != {'sha256':self.h.sha(self.files['candidate']),'uid':0,'gid':0,'mode':0o644}:
            raise ValueError('installed rule differs')
        self.state['active_after'] = self.active()
        self.empty_preview(); self.continuity(); self.guards()
        self.state['checks'].update(first_run=True,continuity=True)
        self.state.update(installed=True, rollback='not-needed',
                          pending=['subsequent daily execution','continued statistics growth',
                                   'ongoing free-space alert integration','maintenance failure reporting'])

    def run(self):
        os.umask(0o077)
        try:
            self.apply()
        except Exception as error:
            self.state['error'] = str(error)
            signal.alarm(0)
            if self.control_created or self.rule_created:
                try:
                    self.recover()
                except Exception as failure:
                    self.state.update(rollback='held', recovery_error=str(failure))
        finally:
            self.save()
        return self.state


def interrupted(signum, frame):
    raise RuntimeError('interrupted: '+str(signum))


def run(spec, baseline, files, helper):
    for sig in (signal.SIGTERM,signal.SIGHUP,signal.SIGINT,signal.SIGALRM):
        signal.signal(sig, interrupted)
    signal.alarm(210)
    return Deployment(spec, baseline, files, helper).run()
