#!/usr/bin/python3
"""Bounded read-only foundation preflight; requires a separately approved stage."""
import argparse
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import socket
import sys
import time


class Probe:
    """Use the worker's observation functions with an exclusively read-only runner."""
    def __init__(self, worker, inspection):
        self.worker = worker
        self.inspection = inspection
        self.deadline = time.monotonic() + 300
        self.commands = []
        worker.run = self.command
        worker.record = lambda *args: None  # Observation functions never write stage receipts.

    def command(self, argv, label, seconds=12, accepted=(0,), **kwargs):
        if not read_only_command(argv) or kwargs:
            raise ValueError('command outside read-only preflight scope')
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError('preflight deadline exceeded')
        self.worker.read(Path(argv[0]).resolve(strict=True), unique=False)
        result = self.inspection.run(argv, min(seconds, remaining))
        if (result['rc'] not in accepted or result['error'] or result['truncated']
                or result['stderr'].strip()):
            raise ValueError('read-only native observation failed: ' + label)
        self.commands.append({'label': label, 'argv': argv, 'rc': result['rc'],
                              'stdout_sha256': hashlib.sha256(result['stdout'].encode()).hexdigest()})
        return result['stdout']

    def record(self, path):
        path = Path(path)
        if path == Path('/var/cache/debconf/passwords.dat'):
            raise ValueError('password database outside preflight scope')
        observed = self.worker.protected_input_path(path)
        protected_parent(self.worker, observed)
        if not os.path.lexists(observed):
            return {'path': str(path), 'absent': True}
        data = self.worker.read(observed)
        info = observed.lstat()
        return {'path': str(path), 'sha256': hashlib.sha256(data).hexdigest(),
                'uid': info.st_uid, 'gid': info.st_gid, 'mode': oct(info.st_mode & 0o7777)}


def protected_parent(worker, path):
    parent = path.parent
    while not os.path.lexists(parent):
        parent = parent.parent
    worker.ancestors(parent)


def read_only_command(argv):
    fixed = [
        ['/usr/bin/id', '-u', 'ama'], ['/usr/bin/dpkg', '--audit'],
        ['/usr/bin/dpkg', '--print-architecture'], ['/usr/bin/dpkg', '--print-foreign-architectures'],
        ['/usr/bin/dpkg-query', '-L', 'debconf'],
        ['/usr/bin/dpkg-query', '-L', 'apt-listchanges'],
        ['/usr/bin/dpkg-query', '-W', '-f=${binary:Package}\t${Version}\t${db:Status-Abbrev}\n'],
        ['/usr/bin/pgrep', '-x', 'ntpd'], ['/usr/bin/pgrep', '-x', 'gpsd'],
        ['/usr/sbin/ip', '-j', 'address', 'show'],
        ['/usr/sbin/ip', '-4', '-j', 'route', 'show'], ['/usr/sbin/ip', '-6', '-j', 'route', 'show']]
    if argv in fixed:
        return True
    properties = {'Id', 'LoadState', 'ActiveState', 'SubState', 'UnitFileState',
                  'FragmentPath', 'DropInPaths', 'MainPID', 'NRestarts'}
    return (len(argv) >= 4 and argv[:2] == ['/usr/bin/systemctl', 'show']
            and argv[2].startswith('--property=')
            and set(argv[2].removeprefix('--property=').split(',')) <= properties
            and all(re.fullmatch(r'[A-Za-z0-9_-]+\.(?:service|timer|socket)', u) for u in argv[3:]))


def module(filename):
    path = Path(__file__).parent / filename
    # Privileged imports require root-owned, protected staging, never a user workspace.
    for parent in path.parents:
        info = parent.lstat()
        if parent.is_symlink() or info.st_uid != 0 or info.st_gid != 0 or info.st_mode & 0o022:
            raise ValueError('unprotected preflight helper parent')
    info = path.lstat()
    if path.is_symlink() or not path.is_file() or info.st_uid != 0 or info.st_gid != 0 or info.st_mode & 0o022:
        raise ValueError('unprotected preflight helper')
    definition = importlib.util.spec_from_file_location(filename.replace('-', '_'), path)
    result = importlib.util.module_from_spec(definition)
    definition.loader.exec_module(result)
    return result


def collect(recipe_path, recipe_sha, hostname, kernel, ssh_host, controller_epoch):
    if (os.geteuid() != 0 or os.getegid() != 0 or not sys.flags.isolated or not sys.dont_write_bytecode
            or os.environ.get('SUDO_USER') != 'ama' or os.environ.get('SUDO_UID') != '1000'
            or socket.gethostname() != hostname or os.uname().machine != 'aarch64'
            or os.uname().release != kernel or abs(time.time() - controller_epoch) > 300
            or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]*', ssh_host)):
        raise ValueError('approved isolated root/target/caller/clock required')
    worker = module('foundation-install.py')
    inspection = module('inspect-trixie.py')
    helper = module('hook-closure-preflight.py')
    answer_reader = module('read-debconf-answers.py')
    raw = worker.read(recipe_path, limit=1024*1024)
    if not re.fullmatch(r'[0-9a-f]{64}', recipe_sha) or hashlib.sha256(raw).hexdigest() != recipe_sha:
        raise ValueError('approved recipe drift')
    recipe = json.loads(raw)
    if recipe['caller'] != {'user': 'ama', 'uid': 1000} or recipe['schema'] != 1:
        raise ValueError('unsupported reviewed recipe/caller')
    os_fields = {}
    for line in worker.read(Path('/usr/lib/os-release')).decode().splitlines():
        name, separator, value = line.partition('=')
        if separator and name in recipe['os']:
            if name in os_fields:
                raise ValueError('duplicate OS identity')
            words = shlex.split(value)
            if len(words) != 1:
                raise ValueError('malformed OS identity')
            os_fields[name] = words[0]
    if os_fields != recipe['os']:
        raise ValueError('OS identity drift')
    probe = Probe(worker, inspection)
    if probe.command(['/usr/bin/id', '-u', 'ama'], 'caller').strip() != '1000':
        raise ValueError('caller account drift')
    boot_id = worker.boot()
    baseline = worker.package_rows(probe.command(['/usr/bin/dpkg-query', '-W',
        '-f=${binary:Package}\t${Version}\t${db:Status-Abbrev}\n'], 'packages'))
    architecture = probe.command(['/usr/bin/dpkg', '--print-architecture'], 'architecture').strip()
    foreign = sorted(probe.command(['/usr/bin/dpkg', '--print-foreign-architectures'], 'foreign').splitlines())
    worker.clean_dpkg('audit')
    worker.forbidden_units('forbidden-units')
    active_time_daemons = []
    for name in ('ntpd', 'gpsd'):
        if probe.command(['/usr/bin/pgrep', '-x', name], 'process-'+name, accepted=(0, 1)).strip():
            active_time_daemons.append(name)
    directories = {}
    paths = set(recipe['required_inputs']) | {p for rows in recipe['package_effects'].values() for p in rows}
    for name in recipe['required_directories']:
        path = Path(name)
        protected_parent(worker, path)
        if path.is_symlink():
            raise ValueError('configuration directory link')
        if path.exists():
            worker.ancestors(path)
        names = sorted(p.name for p in path.iterdir()) if path.exists() else []
        directories[name] = names
        paths.update(name+'/'+n for n in names)
    installed_files = probe.command(['/usr/bin/dpkg-query', '-L', 'debconf'], 'debconf-files').splitlines()
    modules = sorted(p for p in installed_files if p.startswith('/usr/share/perl5/Debconf/') and p.endswith('.pm'))
    listing = probe.command(['/usr/bin/dpkg-query', '-L', 'apt-listchanges'], 'listchanges-files')
    discovered = inspection.keyring_hook_files('')
    paths.update(str(p) for p in discovered)
    listchanges = sorted(p for p in listing.splitlines() if p.startswith(
        ('/usr/share/apt-listchanges/', '/usr/lib/python3/dist-packages/apt_listchanges/')) and p.endswith('.py'))
    keyrings = {str(p) for p in discovered if str(p).startswith('/usr/share/keyrings/')}
    for directory in ('/etc/apt/keyrings', '/etc/apt/trusted.gpg.d'):
        keyrings.update(directory+'/'+name for name in directories[directory])
    if Path('/etc/apt/trusted.gpg').exists():
        keyrings.add('/etc/apt/trusted.gpg')
    keyrings = sorted(keyrings)
    sources = sorted('/etc/apt/sources.list.d/'+n for n in directories['/etc/apt/sources.list.d'])
    if Path('/etc/apt/sources.list').exists():
        sources.append('/etc/apt/sources.list')
    paths.update(modules)
    paths.update(listchanges)
    paths.update(keyrings)
    if len(paths) > 512:
        raise ValueError('preflight input count exceeds scope')
    records = [probe.record(p) for p in sorted(paths)]
    structure = helper.debconf_structure(worker.read(Path('/etc/debconf.conf')).decode())
    answer_spec = {'hostname': hostname, 'kernel': kernel, 'structure': structure,
                   'not_before': controller_epoch-300, 'expires_epoch': controller_epoch+300}
    answer_report = answer_reader.collect_answers(answer_spec, helper)
    public_key = worker.read(Path('/etc/ssh/ssh_host_ed25519_key.pub')).decode().split()
    if len(public_key) < 2 or public_key[0] != 'ssh-ed25519':
        raise ValueError('observed ED25519 host key required')
    fingerprint = 'SHA256:'+base64.b64encode(hashlib.sha256(
        base64.b64decode(public_key[1], validate=True)).digest()).decode().rstrip('=')
    network = worker.network('network')
    automatic = worker.auto_snapshot()
    if (worker.boot() != boot_id or worker.inventory('packages-after') != baseline
            or [probe.record(p) for p in sorted(paths)] != records
            or worker.network('network-after') != network or worker.auto_snapshot() != automatic
            or any((sorted(p.name for p in Path(name).iterdir()) if Path(name).exists() else []) != names
                   for name, names in directories.items())):
        raise ValueError('preflight package/input/boot/network drift')
    snapshot = {'schema': 1, 'recipe_sha256': recipe_sha, 'collected_epoch': int(time.time()),
        'hostname': hostname, 'kernel': kernel, 'boot_id': boot_id, 'os': os_fields,
        'architecture': architecture, 'machine': os.uname().machine, 'caller': recipe['caller'],
        'ssh': {'host': ssh_host, 'fingerprint': fingerprint}, 'baseline': baseline,
        'inputs': records, 'directories': directories,
        'coverage': {'debconf_modules': modules, 'listchanges_modules': listchanges,
                     'keyrings': keyrings, 'source_files': sorted(sources)},
        'answers': {'structure': structure, 'expected': answer_report['answers']},
        'network': network, 'automatic_updates': automatic, 'foreign_architectures': foreign,
        'dpkg_audit': '', 'active_time_daemons': active_time_daemons, 'commands': probe.commands,
        'password_database_read': False, 'package_mutation_authorized': False}
    return snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recipe', type=Path, required=True)
    parser.add_argument('--recipe-sha256', required=True)
    parser.add_argument('--hostname', required=True)
    parser.add_argument('--kernel', required=True)
    parser.add_argument('--ssh-host', required=True)
    parser.add_argument('--controller-epoch', type=int, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(collect(args.recipe, args.recipe_sha256, args.hostname,
            args.kernel, args.ssh_host, args.controller_epoch), sort_keys=True))
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({'state': 'held', 'error': type(error).__name__+': '+str(error),
                          'package_mutation_authorized': False}, sort_keys=True))
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
