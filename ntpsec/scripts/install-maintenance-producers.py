#!/usr/bin/python3
"""Install only the two genuine completion hooks and their fixed helper."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import socket
import tempfile

TARGETS = ('/usr/local/libexec/ntp-maintenance-success.py', '/usr/local/sbin/needrestart.sh',
           '/etc/logrotate.d/ntpstats-retention')
DIRECTORIES = (('/usr/local/libexec', 0o755), ('/var/lib/needrestart-reporting', 0o700))


def sha(raw): return hashlib.sha256(raw).hexdigest()


def read(path, lock=False):
    path = Path(path)
    for parent in path.parents:
        m = parent.lstat()
        sticky_lock = lock and parent == Path('/run/lock') and stat.S_IMODE(m.st_mode) == 0o1777
        if not stat.S_ISDIR(m.st_mode) or m.st_uid != 0 or (m.st_mode & 0o022 and not sticky_lock):
            raise ValueError('unprotected file ancestor')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as f:
        m = os.fstat(f.fileno())
        if not stat.S_ISREG(m.st_mode) or m.st_uid != 0 or m.st_gid != 0 or m.st_mode & 0o022 or m.st_nlink != 1 or m.st_size > 1048576:
            raise ValueError('unprotected regular file')
        data = f.read(1048577)
        after = os.fstat(f.fileno())
    if len(data) > 1048576 or (m.st_ino,m.st_size,m.st_mtime_ns) != (after.st_ino,after.st_size,after.st_mtime_ns):
        raise ValueError('file changed during read')
    return data, m


def atomic(path, data, mode):
    path = Path(path)
    fd, name = tempfile.mkstemp(prefix='.completion-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            os.fchmod(f.fileno(), mode); f.write(data); f.flush(); os.fsync(f.fileno())
        os.replace(name, path)
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try: os.fsync(fd)
        finally: os.close(fd)
    finally:
        if os.path.exists(name): os.unlink(name)


class Installer:
    def __init__(self, spec, digest):
        self.spec = spec; self.digest = digest; self.root = Path(spec['state_root'])
        self.state = {'spec_sha256': digest, 'accepted': False, 'phase': 'new', 'written': []}
        self.owns_root = False

    def command(self, argv):
        p = subprocess.run(argv, capture_output=True, text=True, timeout=30,
                           env={'PATH':'/usr/sbin:/usr/bin:/sbin:/bin','LC_ALL':'C'})
        if p.returncode: raise RuntimeError('read-only prerequisite failed: '+argv[0])
        return p.stdout

    def continuity(self):
        s = self.spec
        if os.geteuid() != 0 or os.getegid() != 0 or socket.gethostname() != s['hostname'] or Path('/proc/sys/kernel/random/boot_id').read_text().strip() != s['boot_id']:
            raise ValueError('root/host/boot mismatch')
        fields = ','.join(s['service_identity'])
        raw = self.command(['/usr/bin/systemctl','show','timeservice.service','--property='+fields])
        if dict(line.split('=',1) for line in raw.splitlines()) != s['service_identity']:
            raise ValueError('NTP service continuity changed')
        for path,digest in s['protected_files'].items():
            if path not in ('/etc/ntp.conf','/usr/local/bin/ntpq') or sha(read(path)[0]) != digest:
                raise ValueError('protected NTP file drift')
        for path,item in s['job_inputs'].items():
            if path not in ('/etc/cron.d/needrestart_check','/var/lib/ntpstats-retention/trigger'):
                raise ValueError('job input scope')
            data,meta=read(path)
            if sha(data)!=item['sha256'] or stat.S_IMODE(meta.st_mode)!=item['mode']:
                raise ValueError('job schedule/trigger drift')

    def save(self): atomic(self.root/'state.json', (json.dumps(self.state,sort_keys=True)+'\n').encode(), 0o600)

    def locks(self):
        handles = []
        try:
            for path in ('/run/lock/needrestart-check.lock','/var/lib/logrotate/status'):
                # Open existing only, do not create production lock files or invoke a job.
                data,meta = read(path, lock=True)
                fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK)
                handles.append(fd)
                current = os.fstat(fd)
                if (current.st_dev, current.st_ino) != (meta.st_dev, meta.st_ino): raise ValueError('lock identity changed')
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return handles
        except BaseException:
            for fd in handles: os.close(fd)
            raise

    def install(self):
        self.continuity()
        inventory=self.command(['/usr/bin/dpkg-query','-W','-f=${binary:Package}\t${Version}\t${Architecture}\t${db:Status-Abbrev}\n'])
        if sha(inventory.encode())!=self.spec['package_inventory_sha256']:raise ValueError('package inventory drift')
        if set(self.spec['files']) != set(TARGETS): raise ValueError('closed producer target set')
        self.root.mkdir(mode=0o700); self.owns_root=True; self.save()
        handles = self.locks()
        try:
            for path, item in self.spec['files'].items():
                p = Path(path)
                if item['before_sha256'] is None:
                    if os.path.lexists(p): raise ValueError('new helper path already exists')
                else:
                    raw,info = read(p)
                    if sha(raw) != item['before_sha256'] or stat.S_IMODE(info.st_mode) != item['mode']:
                        raise ValueError('producer before-state drift')
                    atomic(self.root/(p.name+'.before'), raw, 0o600)
                data = read(Path(self.spec['input_root'])/item['input'])[0]
                if sha(data) != item['after_sha256']: raise ValueError('producer source hash')
            for directory, mode in DIRECTORIES:
                p = Path(directory)
                if not p.exists():
                    p.mkdir(mode=mode);p.chmod(mode)
                m = p.lstat()
                if not stat.S_ISDIR(m.st_mode) or m.st_uid != 0 or m.st_gid != 0 or m.st_mode & 0o022:
                    raise ValueError('producer directory unsafe')
                if mode == 0o700 and stat.S_IMODE(m.st_mode) != 0o700:
                    raise ValueError('success record directory must be private')
            for path,item in self.spec['files'].items():
                self.state['write_intent'] = path; self.save()
                data = read(Path(self.spec['input_root'])/item['input'])[0]
                # Recheck immediately before replacing an existing authored source.
                if item['before_sha256'] is None:
                    if os.path.lexists(path): raise ValueError('late helper drift')
                else:
                    original, meta = read(path)
                    if sha(original) != item['before_sha256'] or stat.S_IMODE(meta.st_mode) != item['mode']:
                        raise ValueError('late producer drift')
                atomic(path, data, item['mode'])
                self.state['written'].append(path); self.save()
            self.continuity()
            for path,item in self.spec['files'].items():
                actual, meta = read(path)
                if sha(actual) != item['after_sha256'] or stat.S_IMODE(meta.st_mode) != item['mode']: raise ValueError('producer readback failed')
            self.state.update(phase='installed', accepted=True, scheduled_success_accepted=False)
            self.save(); return self.state
        finally:
            for fd in handles: os.close(fd)

    def recover(self):
        self.continuity(); errors=[]
        handles = self.locks()
        try:
            paths = list(self.state.get('written',[]))
            intent = self.state.get('write_intent')
            if intent and intent not in paths: paths.append(intent)
            for path in reversed(paths):
                item=self.spec['files'][path];p=Path(path)
                if not os.path.lexists(p):
                    if item['before_sha256'] is not None: errors.append(path+': missing')
                    continue
                actual=sha(read(p)[0])
                if actual==item['before_sha256']: continue
                if actual!=item['after_sha256']: errors.append(path+': foreign change');continue
                if item['before_sha256'] is None:
                    p.unlink()
                    fd=os.open(p.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
                    try:os.fsync(fd)
                    finally:os.close(fd)
                else:
                    original=read(self.root/(p.name+'.before'))[0]
                    if sha(original)!=item['before_sha256']: errors.append(path+': backup changed');continue
                    atomic(p,original,item['mode'])
            self.continuity()
            self.state.update(accepted=False,recovery='held' if errors else 'restored',recovery_errors=errors)
            self.save();return self.state
        finally:
            for fd in handles:os.close(fd)
