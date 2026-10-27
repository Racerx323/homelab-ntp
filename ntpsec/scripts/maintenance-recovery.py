#!/usr/bin/python3
"""File-level maintenance guards; no package, service, firmware or reboot commands."""
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import tarfile

MAX_FILE = 32 * 1024**2
MAX_BACKUP = 256 * 1024**2
DROPIN = '/etc/systemd/system/rpi-eeprom-update.service.d/90-maintenance-inhibit.conf'
MARKER = '/var/lib/ntp-maintenance/eeprom-inhibit'
DROPIN_BYTES = b'[Unit]\nConditionPathExists=!/var/lib/ntp-maintenance/eeprom-inhibit\n'


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return (json.dumps(value, sort_keys=True) + '\n').encode()


def directory(path, owner=0):
    path = Path(path).absolute()
    for parent in (path, *path.parents):
        st = parent.lstat()
        require(stat.S_ISDIR(st.st_mode) and st.st_uid in (0, owner)
                and not st.st_mode & 0o022, 'unsafe directory: ' + str(parent))
    return path


def read(path, owner=0, limit=MAX_FILE):
    path = Path(path)
    directory(path.parent, owner)
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as f:
        a = os.fstat(f.fileno())
        require(stat.S_ISREG(a.st_mode) and a.st_uid == owner and a.st_nlink == 1
                and not a.st_mode & 0o022 and a.st_size <= limit, 'unsafe file: ' + str(path))
        raw = f.read(limit + 1)
        b = os.fstat(f.fileno())
    require(len(raw) <= limit and (a.st_size, a.st_mtime_ns, a.st_ctime_ns) ==
            (b.st_size, b.st_mtime_ns, b.st_ctime_ns), 'file changed: ' + str(path))
    return raw, {'sha256': sha(raw), 'size': len(raw), 'mode': stat.S_IMODE(a.st_mode),
                 'uid': a.st_uid, 'gid': a.st_gid}


def sync(directory_path):
    fd = os.open(directory_path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def create(path, raw, mode=0o600, owner=0):
    path = Path(path)
    directory(path.parent, owner)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    with os.fdopen(fd, 'wb') as f:
        os.fchmod(f.fileno(), mode)
        f.write(raw)
        f.flush()
        os.fsync(f.fileno())
    sync(path.parent)


def boot_conditions(cmdline, config):
    """Classify only the captured hook guards; do not claim full firmware parsing."""
    text = cmdline.decode('ascii')
    require('\x00' not in text and len(text.splitlines()) == 1, 'one boot command line required')
    tokens = text.split()
    require(not any(t == 'resize' or t.startswith('systemd.run=') for t in tokens),
            'first-boot/resize request')
    active = [line.strip() for line in config.decode('ascii').splitlines()
              if line.strip() and not line.lstrip().startswith('#')]
    require(not any(re.match(r'(?:include\s|cmdline\s*=|kernel_watchdog_timeout\s*=)', x)
                    for x in active), 'unqualified included/alternate boot policy')
    require('auto_initramfs=1' in active, 'automatic initramfs selection changed')
    # This exactly reflects the captured rpi_wd guard, without executing its device write.
    continuous = bool(re.search(r'(^| )(watchdog\.open_timeout=[^ ]*|watchdog_disarm=0)( |$)',
                                text.rstrip('\n')))
    return {'firstboot_resize_requested': False, 'continuous_watchdog_requested': continuous,
            'early_boot_watchdog_proven': False}


def backup(root, expected, owner=0):
    """Create a deterministic closed archive; every input must match its pinned hash."""
    root = Path(root)
    files, manifest = {}, {}
    require(0 < len(expected) <= 64, 'backup membership bound')
    for name, row in sorted(expected.items()):
        require(name.startswith('/') and '..' not in Path(name).parts, 'backup path')
        raw, actual = read(root / name.lstrip('/'), owner)
        require(all(actual[k] == row[k] for k in ('sha256', 'size', 'mode', 'uid', 'gid')),
                'backup input drift: ' + name)
        files[name.lstrip('/')] = raw
        manifest[name] = actual
    require(sum(map(len, files.values())) <= MAX_BACKUP, 'backup total bound')
    files['manifest.json'] = encoded(manifest)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w', format=tarfile.USTAR_FORMAT) as archive:
        for name, raw in sorted(files.items()):
            item = tarfile.TarInfo(name)
            item.mode = 0o600
            item.size = len(raw)
            archive.addfile(item, io.BytesIO(raw))
    return gzip.compress(buf.getvalue(), mtime=0)


def verify_backup(raw, expected):
    """Verify all members without extractall or trusting archive paths/metadata."""
    require(len(raw) <= MAX_BACKUP, 'compressed backup bound')
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as zipped:
        expanded = zipped.read(MAX_BACKUP + 1024**2 + 1)
    require(len(expanded) <= MAX_BACKUP + 1024**2, 'expanded backup bound')
    files = {}
    with tarfile.open(fileobj=io.BytesIO(expanded)) as archive:
        for item in archive:
            require(item.isfile() and item.name not in files and item.size <= MAX_FILE
                    and item.name in {'manifest.json', *(n.lstrip('/') for n in expected)},
                    'untrusted backup member')
            files[item.name] = archive.extractfile(item).read()
    require(set(files) == {'manifest.json', *(n.lstrip('/') for n in expected)}, 'backup membership')
    manifest = json.loads(files.pop('manifest.json'))
    require(manifest == expected, 'backup metadata drift')
    for name, data in files.items():
        require(sha(data) == expected['/' + name]['sha256'] and len(data) == expected['/' + name]['size'],
                'backup bytes drift')
    return files


def reserve(bytes_available, inode_available, inode_total, boot_available, expected, package_bytes):
    total = sum(x['size'] for x in expected.values())
    firmware = sum(x['size'] for n, x in expected.items() if n.startswith('/boot/firmware/'))
    # Original + independent local backup + regenerated files + bounded package workspace.
    root_required = 10 * 1024**3 + 3 * total + 4 * package_bytes
    boot_required = 2 * firmware + 64 * 1024**2
    require(bytes_available >= root_required, 'root recovery reserve')
    require(inode_total > 0 and inode_available / inode_total >= .05 and inode_available >= 4096,
            'root inode reserve')
    require(boot_available >= boot_required, 'firmware recovery reserve')
    return {'root_required': root_required, 'firmware_required': boot_required,
            'fat_inode_count_is_not_a_gate': True}


def publish_inhibit(root, operation, owner=0):
    """Marker before drop-in. Retain partial publication on error for guarded cleanup."""
    require(re.fullmatch(r'base-os-update-\d{8}-v\d+', operation), 'operation identity')
    root = Path(root)
    marker, drop = root / MARKER.lstrip('/'), root / DROPIN.lstrip('/')
    directory(marker.parent, owner)
    directory(drop.parent.parent, owner)
    require(not os.path.lexists(marker) and not os.path.lexists(drop.parent), 'existing inhibit controls')
    create(marker, encoded({'operation_id': operation}), owner=owner)
    drop.parent.mkdir(mode=0o755)
    sync(drop.parent.parent)
    temporary = drop.with_name('.' + drop.name + '.' + operation)
    create(temporary, DROPIN_BYTES, 0o644, owner)
    os.link(temporary, drop, follow_symlinks=False)
    temporary.unlink()
    sync(drop.parent)
    return {'marker_sha256': sha(encoded({'operation_id': operation})), 'dropin_sha256': sha(DROPIN_BYTES)}


def check_inhibit(root, operation, owner=0):
    root = Path(root)
    for name, content, mode in ((MARKER, encoded({'operation_id': operation}), 0o600),
                                (DROPIN, DROPIN_BYTES, 0o644)):
        raw, record = read(root / name.lstrip('/'), owner)
        require(raw == content and record['mode'] == mode, 'inhibit changed')


def restore_inhibit(root, operation, owner=0):
    """Restore original absence only; refuse foreign files and never invoke an updater."""
    root = Path(root)
    marker, drop = root / MARKER.lstrip('/'), root / DROPIN.lstrip('/')
    raw, record = read(marker, owner)
    require(raw == encoded({'operation_id': operation}) and record['mode'] == 0o600, 'marker ownership')
    if os.path.lexists(drop.parent):
        directory(drop.parent, owner)
        require(set(x.name for x in drop.parent.iterdir()) <= {drop.name}, 'foreign drop-in residue')
        if os.path.lexists(drop):
            raw, record = read(drop, owner)
            require(raw == DROPIN_BYTES and record['mode'] == 0o644, 'drop-in ownership')
            drop.unlink()
            sync(drop.parent)
        drop.parent.rmdir()
        sync(drop.parent.parent)
    marker.unlink()
    sync(marker.parent)


def restore_boot_files(root, archive, expected, current, owner=0):
    """For a separately reviewed continuation: restore only exact /boot files.

    Never restore dpkg status or infer package/EEPROM rollback. Callers must bind
    the unchanged installed kernel/modules and prohibit reboot on partial failure.
    """
    files = verify_backup(archive, expected)
    selected = {n: row for n, row in expected.items() if n.startswith('/boot/')}
    require(set(current) == set(selected), 'closed boot restoration selection')
    root = Path(root)
    for name, row in current.items():
        _, actual = read(root/name.lstrip('/'), owner)
        require(actual == row, 'current boot state drift')
    for name, row in selected.items():
        path = root/name.lstrip('/')
        temporary = path.with_name('.' + path.name + '.ntp-restore')
        create(temporary, files[name.lstrip('/')], row['mode'], owner)
        _, actual = read(path, owner)
        require(actual == current[name], 'boot file changed during restore')
        os.replace(temporary, path)
        sync(path.parent)
        _, restored = read(path, owner)
        require(restored == row, 'restored boot identity differs')
    return {'restored_files': sorted(selected), 'package_rollback_proven': False,
            'eeprom_recovery_proven': False, 'reboot_authorized': False}
