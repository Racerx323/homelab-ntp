#!/usr/bin/python3
"""Operation-bound, write-ahead NTP0 permission grant and stopped-consumer restore."""
import hashlib
import json
import os
from pathlib import Path
import pwd
import grp
import stat

KEY = 0x4e545030
FIELDS = ('key', 'seq', 'size', 'cpid', 'cuid', 'cgid', 'uid', 'gid', 'mode', 'ctime')
IDENTITY = ('shmid', 'key', 'seq', 'size', 'cpid', 'cuid', 'cgid')


def sha(raw): return hashlib.sha256(raw).hexdigest()


class Access:
    def __init__(self, tx):
        self.tx = tx
        self.path = tx.root/'shm-access-state.json'
        self.binary = tx.root/'shm-access-native'

    def read(self):
        value = json.loads(self.tx.h.read(self.path))
        if value['boot_id'] != self.tx.s['boot_id'] or value['spec_sha256'] != sha(
                (json.dumps(self.tx.s, sort_keys=True)+'\n').encode()):
            raise ValueError('SHM receipt operation/boot mismatch')
        return value

    def save(self, value):
        self.tx.write(self.path.name, value)

    def native(self, value, operation='inspect', expected=None):
        raw = self.tx.h.read(self.binary)
        info = self.binary.lstat()
        if (sha(raw) != value['binary_sha256'] or not stat.S_ISREG(info.st_mode)
                or info.st_uid or info.st_gid or stat.S_IMODE(info.st_mode) != 0o700):
            raise ValueError('SHM native helper drift')
        argv = [str(self.binary), operation, str(value['before']['shmid'])]
        if expected is not None:
            argv.extend(str(expected[k]) for k in FIELDS)
            argv.append(str(value['ntp_gid']))
        row = json.loads(self.tx.run(argv, timeout=5))
        if set(row) != {'shmid', 'nattch', *FIELDS} or any(type(v) is not int or v < 0 for v in row.values()):
            raise ValueError('SHM native metadata schema')
        return row

    def prepare(self):
        if self.path.exists() or self.binary.exists():
            raise ValueError('SHM preparation collision')
        recipe = self.tx.s['recipe']
        user, group = pwd.getpwnam('ntp'), grp.getgrnam('ntp')
        if (user.pw_uid != recipe['ntp_uid'] or user.pw_gid != recipe['ntp_gid']
                or group.gr_gid != recipe['ntp_gid'] or user.pw_uid == 0 or group.gr_gid == 0):
            raise ValueError('validated ntp account/group required')
        inventory = self.tx.a.shm_inventory(self.tx.rf['prior-shm-after.txt'])
        rows = [r for r in inventory.values() if int(r['key']) == KEY]
        if len(rows) != 1:
            raise ValueError('one accepted NTP0 segment required')
        row = rows[0]
        if any(row[k] != v for k, v in {'size': '96', 'uid': '0', 'gid': '0',
                                      'cuid': '0', 'cgid': '0', 'perms': '600'}.items()):
            raise ValueError('accepted root:root 0600 NTP0 required')
        source = self.tx.root/'shm-access.c'
        if self.tx.h.read(source) != self.tx.f['shm-access.c']:
            raise ValueError('SHM source drift')
        compiler = Path('/usr/bin/cc').resolve(strict=True)
        self.tx.h.ancestors(compiler.parent)
        compiler_hash = sha(self.tx.h.read(compiler, limit=16*1024**2))
        self.tx.run([str(compiler), '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                     str(source), '-o', str(self.binary)], timeout=30)
        if sha(self.tx.h.read(compiler, limit=16*1024**2)) != compiler_hash:
            raise ValueError('SHM compiler changed during build')
        os.chmod(self.binary, 0o700)
        with self.binary.open('rb') as stream: os.fsync(stream.fileno())
        self.tx.h.sync(self.tx.root)
        value = {'boot_id': self.tx.s['boot_id'], 'spec_sha256': sha(
            (json.dumps(self.tx.s, sort_keys=True)+'\n').encode()),
            'ntp_gid': group.gr_gid, 'compiler': str(compiler), 'compiler_sha256': compiler_hash,
            'source_sha256': sha(self.tx.f['shm-access.c']),
            'binary_sha256': sha(self.tx.h.read(self.binary)), 'before': {'shmid': int(row['shmid'])},
            'phase': 'prepared'}
        actual = self.native(value)
        if (actual['nattch'] or any(actual[k] != int(row[k]) for k in row if k != 'perms')
                or actual['mode'] != int(row['perms'], 8)):
            raise ValueError('fresh NTP0 differs from accepted metadata')
        value['before'] = actual
        self.save(value)

    def identity(self, value, actual):
        if any(actual[k] != value['before'][k] for k in IDENTITY):
            raise ValueError('NTP0 segment replaced')

    def grant(self):
        value = self.read()
        if value['phase'] != 'prepared': raise ValueError('one SHM grant required')
        actual = self.native(value)
        if actual != value['before']: raise ValueError('SHM pre-grant drift')
        value['phase'] = 'grant_pending'; self.save(value)
        after = self.native(value, 'grant', actual)
        self.identity(value, after)
        if (after['uid'], after['gid'], after['mode'], after['nattch']) != (0, value['ntp_gid'], 0o660, 0):
            raise ValueError('SHM grant postcondition')
        value.update(phase='granted', after=after); self.save(value)

    def expected_inventory(self):
        value = self.read()
        if value['phase'] != 'granted': raise ValueError('confirmed SHM grant required')
        actual = self.native(value)
        value['last_observed'] = actual; self.save(value)
        if any(actual[k] != value['after'][k] for k in ('shmid', *FIELDS)):
            raise ValueError('granted SHM drift')
        inventory = self.tx.a.shm_inventory(self.tx.rf['prior-shm-after.txt'])
        inventory[str(actual['shmid'])].update(gid=str(value['ntp_gid']), perms='660')
        return inventory

    def restore(self):
        # Invoked only after the stage's daemon-idle check. Kernel also requires nattch=0.
        if not self.path.exists():
            if self.tx.state()['phase'] != 'staged':
                raise ValueError('missing SHM recovery receipt')
            return  # Preparation failed before any grant.
        value = self.read(); actual = self.native(value)
        value['last_observed'] = actual; self.save(value)
        self.identity(value, actual)
        if actual['nattch']: raise ValueError('SHM consumers still attached')
        if value['phase'] not in ('prepared', 'grant_pending', 'granted', 'restore_pending', 'restored'):
            raise ValueError('SHM recovery phase')
        original = (actual['uid'], actual['gid'], actual['mode']) == (0, 0, 0o600)
        if original:
            expected = value.get('restored', value['before'])
            # Interrupted IPC_SET may have restored perms before its receipt was saved.
            if value['phase'] not in ('restore_pending',) and actual['ctime'] != expected['ctime']:
                raise ValueError('SHM original metadata drift')
            if value['phase'] == 'granted': raise ValueError('SHM grant disappeared')
        else:
            if value['phase'] not in ('grant_pending', 'granted', 'restore_pending'):
                raise ValueError('unexpected SHM grant')
            if (actual['uid'], actual['gid'], actual['mode']) != (0, value['ntp_gid'], 0o660):
                raise ValueError('SHM recovery permission drift')
            if 'after' in value and actual['ctime'] != value['after']['ctime']:
                raise ValueError('SHM recovery change-time drift')
            value['phase'] = 'restore_pending'; self.save(value)
            actual = self.native(value, 'restore', actual)
            self.identity(value, actual)
        if (actual['uid'], actual['gid'], actual['mode'], actual['nattch']) != (0, 0, 0o600, 0):
            raise ValueError('SHM restoration postcondition')
        value.update(phase='restored', restored=actual); self.save(value)
