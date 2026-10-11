#!/usr/bin/python3
"""Render with the existing static parser; read only five non-secret answers."""
import os
from pathlib import Path
import pwd
import socket
import sys
import time


def normal_database(structure):
    """Accept only the observed Stack of normal/password File backends."""
    if structure[0] != {'config': 'configdb', 'templates': 'templatedb', 'omitted_fields': []}:
        raise ValueError('database selection drift')
    names = {row['name']: row for row in structure[1:]}
    if names.get('configdb') != {'driver': 'Stack', 'name': 'configdb',
                                  'stack': 'config, passwords', 'omitted_fields': []}:
        raise ValueError('Stack routing drift')
    if names.get('config') != {'driver': 'File', 'filename': '/var/cache/debconf/config.dat',
                               'mode': '644', 'name': 'config',
                               'reject_type': 'password', 'omitted_fields': []}:
        raise ValueError('normal File backend drift')
    if names.get('passwords') != {'accept_type': 'password', 'backup': 'false',
                                 'driver': 'File', 'filename': '/var/cache/debconf/passwords.dat',
                                 'mode': '600', 'name': 'passwords',
                                 'required': 'false', 'omitted_fields': []}:
        raise ValueError('password boundary drift')
    return '/var/cache/debconf/config.dat'


def collect_answers(spec, helper):
    now = int(time.time())
    if (os.geteuid() != 0 or not sys.flags.isolated or not sys.dont_write_bytecode
            or socket.gethostname() != spec['hostname']
            or os.uname().machine != 'aarch64' or os.uname().release != spec['kernel']
            or os.environ.get('SUDO_USER') != 'ama' or os.environ.get('SUDO_UID') != '1000'
            or pwd.getpwnam('ama').pw_uid != 1000
            or not spec['not_before'] <= now < spec['expires_epoch']):
        raise ValueError('approved identity/interpreter/window mismatch')
    if any(name in os.environ for name in helper.OVERRIDES):
        raise ValueError('unexpected environment override')
    home = Path(pwd.getpwuid(0).pw_dir)
    if home != Path('/root') or (home / '.debconfrc').exists() or (home / '.debconfrc').is_symlink():
        raise ValueError('root configuration selection drift')
    release, _ = helper.read_protected('/usr/lib/os-release', limit=65536)
    if not all(line in release.decode().splitlines() for line in
               ('ID=debian', 'VERSION_ID="13"', 'VERSION_CODENAME=trixie')):
        raise ValueError('OS identity drift')
    boot_path = Path('/proc/sys/kernel/random/boot_id')
    boot_before = boot_path.read_text().strip()
    config_path = '/etc/debconf.conf'
    before, metadata = helper.read_protected(config_path, limit=65536)
    structure = helper.debconf_structure(before.decode())
    if structure != spec['structure']:
        raise ValueError('observed Debconf configuration changed')
    filename = normal_database(structure)
    data, db_metadata = helper.read_protected(filename, limit=4 * 1024 * 1024)
    answers = helper.answer_subset(data.decode())
    # No database source, digest, unrelated names/values or credentials leave memory.
    del data
    repeated, repeated_metadata = helper.read_protected(filename, limit=4 * 1024 * 1024)
    if helper.answer_subset(repeated.decode()) != answers or repeated_metadata != db_metadata:
        raise ValueError('selected answer snapshot changed')
    del repeated
    after, after_metadata = helper.read_protected(config_path, limit=65536)
    if before != after or metadata != after_metadata:
        raise ValueError('Debconf configuration changed during read')
    if boot_path.read_text().strip() != boot_before:
        raise ValueError('boot changed during read')
    return {'state': 'collected', 'gaps': [], 'answers': answers,
            'identity': {'hostname': socket.gethostname(), 'kernel': os.uname().release,
                         'machine': os.uname().machine, 'euid': os.geteuid(),
                         'caller_uid': pwd.getpwnam('ama').pw_uid},
            'selected_config': config_path, 'normal_database': filename,
            'database_metadata': db_metadata, 'answer_snapshot_unchanged': True,
            'config_unchanged': True, 'boot_unchanged': True,
            'password_database_read': False, 'installation_authorized': False,
            'started_epoch': now, 'finished_epoch': int(time.time())}
