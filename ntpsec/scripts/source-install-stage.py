#!/usr/bin/python3
"""First native installation from a verified target stage; retain mutation evidence."""
import base64
import fcntl
import hashlib
import importlib.util
import json
import os
import re
import signal
from pathlib import Path
import stat
import time
import types


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return (json.dumps(value, sort_keys=True) + '\n').encode()


def load(path):
    definition = importlib.util.spec_from_file_location('protected_install_' + path.stem, path)
    module = importlib.util.module_from_spec(definition)
    definition.loader.exec_module(module)
    return module


def source_identity(info):
    return tuple(getattr(info, name) for name in ('st_mode', 'st_uid', 'st_gid', 'st_dev',
        'st_ino', 'st_nlink', 'st_size', 'st_mtime_ns', 'st_ctime_ns'))


def source_bytes(path, kind, limit=64 * 1024**2):
    """Walk with directory descriptors; never follow user-owned source symlinks."""
    descriptor = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in path.parts[1:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor); descriptor = child
            info = os.fstat(descriptor)
            if info.st_uid not in (0, 1000) or info.st_gid not in (0, 1000) or info.st_mode & 0o022:
                raise ValueError('unsafe source ancestor')
        before = os.stat(path.name, dir_fd=descriptor, follow_symlinks=False)
        if (before.st_uid != 1000 or before.st_gid != 1000 or before.st_mode & 0o022
                or before.st_nlink != 1):
            # Symlink permission bits are not access controls.
            if kind != 'symlink' or not stat.S_ISLNK(before.st_mode) or before.st_uid != 1000 or before.st_gid != 1000:
                raise ValueError('unsafe source ownership/mode/links')
        if kind == 'symlink':
            if not stat.S_ISLNK(before.st_mode):
                raise ValueError('source link type mismatch')
            data = os.readlink(path.name, dir_fd=descriptor)
        else:
            if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
                raise ValueError('source type/size bound')
            fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
            try:
                if source_identity(os.fstat(fd)) != source_identity(before):
                    raise ValueError('source changed before open')
                with os.fdopen(fd, 'rb', closefd=False) as stream:
                    data = stream.read(limit + 1)
                if len(data) > limit or source_identity(os.fstat(fd)) != source_identity(before):
                    raise ValueError('source changed during read or exceeded bound')
            finally:
                os.close(fd)
        if source_identity(os.stat(path.name, dir_fd=descriptor, follow_symlinks=False)) != source_identity(before):
            raise ValueError('source changed during observation')
        return data
    finally:
        os.close(descriptor)


def parent_identity(record):
    return None if record is None else {k: record[k] for k in ('type', 'uid', 'gid', 'mode', 'device', 'inode')}


def stage_payload(root, spec, release, helper):
    destination = root / 'stage'
    destination.mkdir(mode=0o700)
    total = 0
    for name, record in sorted(release['files'].items()):
        source = Path(spec['source_stage']) / name
        data = source_bytes(source, record['type'])
        output = destination / name
        output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if record['type'] == 'file':
            total += len(data)
            if total > 512 * 1024**2 or sha(data) != record['sha256']:
                raise ValueError('accepted source payload hash/total bound mismatch')
            helper.create(output, data)
        else:
            if data != record['target']:
                raise ValueError('accepted source link changed')
            target = os.path.normpath(str(Path(name).parent / data))
            if Path(data).is_absolute() or target not in release['files']:
                raise ValueError('escaping source symlink')
            os.symlink(data, output)
    helper.sync(destination)


def verify_payload(root, release, helper):
    expected = set(release['files'])
    observed = set()
    expected_dirs = {str(p) for n in expected for p in Path(n).parents}
    actual_dirs = set()
    for directory, dirs, names in os.walk(root / 'stage', followlinks=False):
        helper.ancestors(Path(directory))
        actual_dirs.add(str(Path(directory).relative_to(root / 'stage')))
        for name in list(dirs):
            if (Path(directory) / name).is_symlink():
                names.append(name); dirs.remove(name)
        for name in names:
            observed.add(str((Path(directory) / name).relative_to(root / 'stage')))
    if observed != expected or actual_dirs != expected_dirs:
        raise ValueError('payload membership changed')
    for name, record in release['files'].items():
        path = root / 'stage' / name
        info = path.lstat()
        if info.st_uid != 0 or info.st_gid != 0:
            raise ValueError('payload ownership drift')
        if record['type'] == 'file':
            if sha(helper.read(path)) != record['sha256']:
                raise ValueError('payload hash drift')
        elif not stat.S_ISLNK(info.st_mode) or os.readlink(path) != record['target']:
            raise ValueError('payload link drift')


def verify_target(clock, inspector, release, expected, allow_absent=False):
    inspector.parents([clock.safe_destination(n) for n in release['files']])
    budget = [512 * 1024**2]
    current = {n: inspector.bounded_snapshot(clock.safe_destination(n), expected, budget)
               for n in release['files']}
    for name, record in current.items():
        if record is None and allow_absent:
            continue
        if (record is None or record['uid'] != 0 or record['gid'] != 0
                or any(record.get(k) != v for k, v in release['files'][name].items())):
            raise ValueError('installed artifact drift: ' + name)
    return current


def install(root, spec, helper, clock, inspector, release):
    state = json.loads(helper.read(root / 'installation-state.json'))
    if (release.get('operation') != 'build' or set(state['files']) != set(release['files'])
            or any(record is not None for record in state['files'].values())
            or state['obsolete'] or state['previous_sha256'] is not None):
        raise ValueError('first-install absent pre-state required')
    report = json.loads(helper.read(root / 'inspection.json'))
    build = json.loads(helper.read(root / 'build-spec.json'))
    before = inspector.observation()
    if before != report['observation'] or before['active_daemons']:
        raise ValueError('accepted observation/daemon state drift')
    paths = [clock.safe_destination(n) for n in release['files']]
    if inspector.parents(paths) != report['parents']:
        raise ValueError('accepted destination parent drift')
    if state != clock.inspect_install(root / 'release.json', spec['members']['release.json']):
        raise ValueError('accepted destination pre-state drift')
    helper.create(root / 'before.json', encoded({'observation': before, 'parents': report['parents'], 'state': state}))
    stage_payload(root, spec, release, helper)
    verify_payload(root, release, helper)
    if inspector.observation() != before or inspector.parents(paths) != report['parents']:
        raise ValueError('target drift during payload verification')
    # Precreate missing parents with explicit metadata and retain identities before native copying.
    created = {}
    helper.create(root / 'created-directories.json', encoded(created))
    for name in sorted(report['parents'], key=lambda n: (len(Path(n).parts), n)):
        if report['parents'][name] is not None:
            continue
        path = Path(name)
        helper.ancestors(path.parent)
        path.mkdir(mode=0o755); path.chmod(0o755)
        created[name] = parent_identity(inspector.metadata(path))
        replacement = root / 'directories-next.json'
        helper.create(replacement, encoded(created))
        os.replace(replacement, root / 'created-directories.json'); helper.sync(root)
    result = clock.install(root / 'release.json', spec['members']['release.json'],
        root / 'installation-state.json', spec['members']['installation-state.json'], root / 'journal')
    (root / 'journal/receipt.json').chmod(0o600)
    helper.sync(root / 'journal'); helper.sync(root)
    verify_target(clock, inspector, release, helper)
    post_parents = inspector.parents(paths)
    if any(parent_identity(record) != (created.get(name) if report['parents'][name] is None
           else parent_identity(report['parents'][name])) for name, record in post_parents.items()):
        raise ValueError('post-install directory identity drift')
    if inspector.observation() != before:
        raise ValueError('post-install target continuity failed')
    return {'state': 'installation_completed', 'native_state': result['state'],
            'installed_files': len(release['files']), 'continuity_unchanged': True,
            'services_activated': False, 'library_cache_changed': False}


def recover(root, spec, helper, clock, inspector, release, terminal):
    if (root / 'recovery-claim.json').exists():
        raise FileExistsError('recovery already registered; do not replay')
    if terminal['state'] != 'installation_held':
        raise ValueError('conditional recovery applies only to a held installation')
    clock.require_stopped_daemons()
    before = json.loads(helper.read(root / 'before.json'))
    if inspector.observation() != before['observation'] or before['observation']['active_daemons']:
        raise ValueError('recovery target/daemon drift')
    created = json.loads(helper.read(root / 'created-directories.json'))
    current_parents = inspector.parents([clock.safe_destination(n) for n in release['files']])
    for name, record in current_parents.items():
        old = before['parents'][name]
        expected = created.get(name) if old is None else parent_identity(old)
        if parent_identity(record) != expected:
            raise ValueError('unproved directory identity; recovery held')
    current = verify_target(clock, inspector, release, helper, allow_absent=True)
    allowed_children = {name: set() for name in created}
    for name in created:
        parent = str(Path(name).parent)
        if parent in allowed_children:
            allowed_children[parent].add(Path(name).name)
    for name, record in current.items():
        path = clock.safe_destination(name)
        if record is not None and str(path.parent) in allowed_children:
            allowed_children[str(path.parent)].add(path.name)
    if any({p.name for p in Path(name).iterdir()} != allowed for name, allowed in allowed_children.items()):
        raise ValueError('unexpected created-directory contents; recovery held')
    # Verify every removal before the first effect. A started recovery cannot be replayed.
    helper.create(root / 'recovery-claim.json', encoded({'terminal_sha256': sha(encoded(terminal)), 'files': current}))
    for name, record in current.items():
        if record is not None:
            path = clock.safe_destination(name)
            path.unlink(); helper.sync(path.parent)
    for name in sorted(created, key=lambda n: len(Path(n).parts), reverse=True):
        path = Path(name)
        if parent_identity(inspector.metadata(path)) != created[name] or any(path.iterdir()):
            raise ValueError('created directory changed; retain partial recovery')
        path.rmdir(); helper.sync(path.parent)
    if (clock.inspect_install(root / 'release.json', spec['members']['release.json']) != before['state']
            or inspector.observation() != before['observation']):
        raise ValueError('recovery post-state mismatch')
    result = {'state': 'installation_restored', 'services_activated': False}
    helper.create(root / 'recovery.json', encoded(result))
    return result


def entry(spec, files, epoch, mode, terminal_sha=None):
    os.umask(0o077)
    # Use the sealed existing identity and protected-file primitives, never target build code.
    gate = types.ModuleType('sealed_install_identity')
    exec(compile(files['preflight-stage.py'], 'sealed-preflight-identity.py', 'exec'), gate.__dict__)
    gate.identity(spec, epoch, 'collect' if mode == 'collect' else 'readback')
    if (spec['operation'] != 'source-installation' or set(files) != set(spec['members'])
            or not re.fullmatch(r'/home/ama/\.ntp-source-build-[a-z0-9-]+/candidate/stage', spec['source_stage'])):
        raise ValueError('fixed sealed source installation inputs required')
    if any(sha(files[n]) != h for n, h in spec['members'].items()):
        raise ValueError('sealed source install input drift')
    helper = types.ModuleType('sealed_install_helpers')
    exec(compile(files['foundation-install.py'], 'sealed-install-helpers.py', 'exec'), helper.__dict__)
    root = Path(spec['stage'])
    helper.ancestors(root.parent)
    if mode == 'collect':
        root.mkdir(mode=0o700); helper.sync(root.parent)
        for name, data in {**files, 'spec.json': encoded(spec), 'lock': b''}.items():
            helper.create(root / name, data)
    helper.ancestors(root)
    if stat.S_IMODE(root.stat().st_mode) != 0o700:
        raise ValueError('private root installation stage required')
    for name, data in {**files, 'spec.json': encoded(spec), 'lock': b''}.items():
        if helper.read(root / name) != data or stat.S_IMODE((root / name).stat().st_mode) != 0o600:
            raise ValueError('protected installation input drift')
    fd = os.open(root / 'lock', os.O_RDONLY | os.O_NOFOLLOW)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        inspector = load(root / 'inspect-source-destinations.py')
        clock = load(root / 'clockmaker.py')
        clock.regular_bytes = helper.read
        clock.snapshot = lambda path: inspector.bounded_snapshot(path, helper, [64 * 1024**2])
        release = clock.read_release(root / 'release.json', spec['members']['release.json'])
        if mode == 'collect':
            helper.create(root / 'claim.json', encoded({'spec_sha256': sha(encoded(spec)), 'started_epoch': epoch}))
            def interrupted(signum, frame):
                raise RuntimeError('native installation interrupted by signal ' + str(signum))
            for signum in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
                signal.signal(signum, interrupted)
            try:
                result = install(root, spec, helper, clock, inspector, release)
            except BaseException as error:
                result = {'state': 'installation_held', 'error': type(error).__name__ + ': ' + str(error)}
            result.update(spec_sha256=sha(encoded(spec)), finished_epoch=int(time.time()))
            helper.create(root / 'terminal.json', encoded(result)); helper.sync(root)
            return result
        raw = helper.read(root / 'terminal.json'); terminal = json.loads(raw)
        if terminal['spec_sha256'] != sha(encoded(spec)):
            raise ValueError('terminal binding drift')
        if mode == 'readback':
            if terminal['state'] == 'installation_completed':
                verify_target(clock, inspector, release, helper)
                before = json.loads(helper.read(root / 'before.json'))
                created = json.loads(helper.read(root / 'created-directories.json'))
                parents = inspector.parents([clock.safe_destination(n) for n in release['files']])
                if any(parent_identity(record) != (created.get(name) if before['parents'][name] is None
                       else parent_identity(before['parents'][name])) for name, record in parents.items()):
                    raise ValueError('installed parent drift before terminal acceptance')
                if inspector.observation() != before['observation']:
                    raise ValueError('installed state drift before terminal acceptance')
            result = dict(terminal, terminal_sha256=sha(raw))
            evidence = {}
            for name in ('before.json', 'created-directories.json', 'journal/receipt.json', 'recovery.json'):
                if (root / name).exists():
                    data = helper.read(root / name)
                    evidence[name] = {'sha256': sha(data), 'base64': base64.b64encode(data).decode()}
            result['evidence'] = evidence
            return result
        if sha(raw) != terminal_sha:
            raise ValueError('retained terminal required before recovery/cleanup')
        if mode == 'rollback':
            return recover(root, spec, helper, clock, inspector, release, terminal)
        if mode != 'cleanup':
            raise ValueError('fixed installation action required')
        if terminal['state'] == 'installation_held' and not (root / 'recovery.json').exists():
            raise ValueError('held installation requires recovery review; retain payload/journal')
        verify_payload(root, release, helper)
        # Remove only verified temporary payload. Keep all executed privileged code, journals and backups.
        for directory, dirs, names in os.walk(root / 'stage', topdown=False, followlinks=False):
            for name in names:
                (Path(directory) / name).unlink()
            for name in dirs:
                path = Path(directory) / name
                path.unlink() if path.is_symlink() else path.rmdir()
        (root / 'stage').rmdir(); helper.sync(root)
        return {'state': 'installation_payload_removed', 'journal_retained': True, 'services_activated': False}
    finally:
        os.close(fd)
