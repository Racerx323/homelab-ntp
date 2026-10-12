#!/usr/bin/python3
"""Protected snapshot staging, one collection, terminal readback and scoped cleanup."""
import base64
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import socket
import stat
import sys
import time
import types

INPUTS = {'capture-foundation-snapshot.py', 'foundation-install.py', 'inspect-trixie.py',
          'hook-closure-preflight.py', 'read-debconf-answers.py', 'recipe.json'}
RESOLUTION_INPUTS = {'resolver.py', 'resolver-spec.json', 'snapshot.json',
                     'installation-assets.json', 'resolution-policy.json'}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return (json.dumps(value, sort_keys=True) + '\n').encode()


def identity(spec, epoch, mode):
    if (spec['schema'] != 1 or spec['operation'] not in ('foundation-snapshot', 'foundation-resolution')
            or not re.fullmatch(r'[a-z][a-z0-9-]{0,63}', spec['operation_id'])
            or spec['stage'] != '/var/lib/ntp-preflight-' + spec['operation_id']
            or os.geteuid() != 0 or os.getegid() != 0
            or os.environ.get('SUDO_USER') != 'ama' or os.environ.get('SUDO_UID') != '1000'
            or not sys.flags.isolated or not sys.dont_write_bytecode
            or socket.gethostname() != spec['hostname'] or os.uname().release != spec['kernel']
            or os.uname().machine != 'aarch64' or abs(time.time() - epoch) > 300
            or (mode == 'collect' and not spec['prepared_epoch'] - 300 <= epoch < spec['expires_epoch'])):
        raise ValueError('approved operation/target/isolated caller/clock required')


def verify_inputs(worker, root, spec, files):
    worker.ancestors(root)
    if stat.S_IMODE(root.stat().st_mode) != 0o700:
        raise ValueError('private root staging required')
    for name, data in {**files, 'spec.json': encoded(spec)}.items():
        if worker.read(root / name) != data or stat.S_IMODE((root / name).stat().st_mode) != 0o600:
            raise ValueError('staged input drift: ' + name)


def terminal(worker, root, spec):
    claim = json.loads(worker.read(root / 'claim.json'))
    raw_result = worker.read(root / 'terminal.json')
    result = json.loads(raw_result)
    if (claim['spec_sha256'] != sha(encoded(spec)) or result['spec_sha256'] != claim['spec_sha256']
            or result['state'] not in ('snapshot_completed', 'snapshot_held', 'resolution_completed', 'resolution_held')):
        raise ValueError('bound terminal receipt required; preserve unresolved stage')
    result['terminal_sha256'] = sha(raw_result)
    if result['state'] == 'snapshot_completed':
        raw = worker.read(root / 'snapshot.json')
        if sha(raw) != result['snapshot_sha256']:
            raise ValueError('snapshot receipt hash mismatch')
        snapshot = json.loads(raw)
        if (snapshot['recipe_sha256'] != spec['members']['recipe.json']
                or snapshot['hostname'] != spec['hostname'] or snapshot['kernel'] != spec['kernel']
                or snapshot['ssh'] != spec['ssh'] or snapshot['password_database_read']
                or snapshot['package_mutation_authorized']):
            raise ValueError('snapshot identity/scope mismatch')
        result['snapshot_base64'] = base64.b64encode(raw).decode()
    if result['state'] in ('resolution_completed', 'resolution_held') and 'resolution_sha256' in result:
        raw = worker.read(root / 'resolution.json')
        if sha(raw) != result['resolution_sha256']:
            raise ValueError('resolution receipt hash mismatch')
        result['resolution_base64'] = base64.b64encode(raw).decode()
    return result


def resolution(collector, root, spec, worker, epoch):
    expected = json.loads(worker.read(root / 'snapshot.json'))
    fields = set(expected) - {'collected_epoch', 'commands'}
    started = time.monotonic()
    def continuity():
        observed = collector.collect(root / 'recipe.json', spec['members']['recipe.json'],
            spec['hostname'], spec['kernel'], spec['ssh']['host'], epoch + int(time.monotonic() - started))
        if any(observed[k] != expected[k] for k in fields):
            raise ValueError('fresh snapshot state drift; no resolution accepted')
    continuity()
    inspector = collector.module('inspect-trixie.py')
    previous = sys.modules.get('inspect_trixie')
    sys.modules['inspect_trixie'] = inspector
    try:
        resolver = collector.module('resolver.py')
    finally:
        if previous is None:
            del sys.modules['inspect_trixie']
        else:
            sys.modules['inspect_trixie'] = previous
    resolver_spec = json.loads(worker.read(root / 'resolver-spec.json'))
    report = resolver.run(resolver_spec, epoch)
    result = {}
    if report.get('workspace_retained') or report.get('workspace_cleaned') is False:
        worker.create(root / 'workspace.json', encoded({'path': resolver_spec['workspace'],
                                                     'identity': report['workspace_identity']}))
    try:
        continuity()
        if (report['state'] != 'completed' or report['groups']['foundation']['accepted'] is not True
                or any(report.get(k) is not True for k in ('metadata_accepted', 'metadata_unchanged',
                    'installed_state_unchanged', 'boot_unchanged', 'approved_inputs_unchanged'))):
            raise ValueError('authenticated resolution or continuity held')
        result['state'] = 'resolution_completed'
    except (OSError, ValueError) as error:
        result.update(state='resolution_held', error=type(error).__name__ + ': ' + str(error))
        report.update(state='held', metadata_accepted=False, full_snapshot_unchanged=False,
                      error=result['error'])
        for group in report.get('groups', {}).values():
            group['accepted'] = False
    else:
        report['full_snapshot_unchanged'] = True
    # Persist complete query/metadata evidence after the complete continuity decision.
    wrapped = {'schema': 1, 'snapshot_sha256': spec['members']['snapshot.json'],
        'asset_manifest_sha256': spec['members']['installation-assets.json'], 'report': report}
    raw = encoded(wrapped)
    worker.create(root / 'resolution.json', raw)
    result['resolution_sha256'] = sha(raw)
    return result


def entry(spec, files, epoch, mode, terminal_sha=None):
    os.umask(0o077)
    required = INPUTS | (RESOLUTION_INPUTS if spec['operation'] == 'foundation-resolution' else set())
    if mode not in ('collect', 'readback', 'cleanup') or set(files) != required:
        raise ValueError('fixed preflight operation and inputs required')
    if set(spec['members']) != required or any(sha(files[n]) != h for n, h in spec['members'].items()):
        raise ValueError('bound input hash mismatch')
    identity(spec, epoch, mode)
    worker = types.ModuleType('protected_observation_helpers')
    exec(compile(files['foundation-install.py'], 'sealed-observation-helpers.py', 'exec'), worker.__dict__)
    root = Path(spec['stage'])
    worker.ancestors(root.parent)
    if mode == 'collect':
        root.mkdir(mode=0o700)  # Exclusive claim; never reuse an earlier collection.
        worker.sync(root.parent)
        for name, data in {**files, 'spec.json': encoded(spec)}.items():
            worker.create(root / name, data)
        worker.create(root / 'lock', b'')
    verify_inputs(worker, root, spec, files)
    # Read validates ownership, links, type and ancestors before opening the lock.
    if worker.read(root / 'lock') != b'':
        raise ValueError('staging lock drift')
    fd = os.open(root / 'lock', os.O_RDONLY | os.O_NOFOLLOW)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if mode == 'collect':
            worker.create(root / 'claim.json', encoded({'spec_sha256': sha(encoded(spec)),
                'started_epoch': epoch, 'pid': os.getpid()}))
            def interrupted(signum, frame):
                raise RuntimeError('preflight interrupted by signal ' + str(signum))
            for signum in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
                signal.signal(signum, interrupted)
            result = {'spec_sha256': sha(encoded(spec)), 'package_mutation_authorized': False}
            try:
                definition = importlib.util.spec_from_file_location('protected_snapshot', root / 'capture-foundation-snapshot.py')
                collector = importlib.util.module_from_spec(definition)
                definition.loader.exec_module(collector)
                if spec['operation'] == 'foundation-resolution':
                    result.update(resolution(collector, root, spec, worker, epoch))
                else:
                    snapshot = collector.collect(root / 'recipe.json', spec['members']['recipe.json'],
                        spec['hostname'], spec['kernel'], spec['ssh']['host'], epoch)
                    if snapshot['ssh'] != spec['ssh'] or snapshot['active_time_daemons']:
                        raise ValueError('SSH key drift or active time daemon; acceptance held')
                    raw = encoded(snapshot)
                    worker.create(root / 'snapshot.json', raw)
                    result.update(state='snapshot_completed', snapshot_sha256=sha(raw))
                verify_inputs(worker, root, spec, files)
            except BaseException as error:
                result.update(state='resolution_held' if spec['operation'] == 'foundation-resolution' else 'snapshot_held',
                              error=type(error).__name__ + ': ' + str(error))
            result['finished_epoch'] = int(time.time())
            worker.create(root / 'terminal.json', encoded(result))
            return result
        result = terminal(worker, root, spec)
        if mode == 'readback':
            return result
        if result['terminal_sha256'] != terminal_sha:
            raise ValueError('terminal differs from retained readback; cleanup held')
        expected = required | {'spec.json', 'lock', 'claim.json', 'terminal.json'}
        if result['state'] == 'snapshot_completed':
            expected.add('snapshot.json')
        if 'resolution_sha256' in result:
            expected.add('resolution.json')
        if (root / 'workspace.json').exists():
            expected.add('workspace.json')
        if set(p.name for p in root.iterdir()) != expected:
            raise ValueError('unexpected stage entries; cleanup held')
        # Validate all removable files before deleting anything; retain on drift.
        for name in expected:
            worker.read(root / name)
        if 'workspace.json' in expected:
            workspace = json.loads(worker.read(root / 'workspace.json'))
            resolver_spec = json.loads(worker.read(root / 'resolver-spec.json'))
            if workspace['path'] != resolver_spec['workspace']:
                raise ValueError('workspace binding mismatch; cleanup held')
            # Native APT output and selected records have been retained by readback.
            inspector = types.ModuleType('cleanup_inspection')
            sys.modules['inspect_trixie'] = inspector
            resolver = types.ModuleType('cleanup_resolver')
            try:
                exec(compile(files['resolver.py'], 'sealed-cleanup-resolver.py', 'exec'), resolver.__dict__)
            finally:
                del sys.modules['inspect_trixie']
            resolver.owned_cleanup(Path(workspace['path']), tuple(workspace['identity']))
        for name in sorted(expected):
            (root / name).unlink()
        root.rmdir()
        worker.sync(root.parent)
        return {'state': 'snapshot_stage_removed', 'stage': str(root),
                'terminal_state': result['state'], 'package_mutation_authorized': False}
    finally:
        os.close(fd)
