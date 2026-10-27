#!/usr/bin/python3
"""Owned file operations for the attended runbook, never packages/services/reboot."""
import importlib.util
import json
import os
from pathlib import Path
import sys


def main(root=Path('/'), owner=0):
    def at(name):
        return root / name.lstrip('/')
    spec = json.loads(Path('spec.json').read_text())
    if os.geteuid() != owner or str(Path.cwd()) != spec['stage']:
        raise ValueError('root private stage required')
    loader = importlib.util.spec_from_file_location('recovery', 'recovery.py')
    r = importlib.util.module_from_spec(loader)
    loader.loader.exec_module(r)
    r.directory(Path.cwd(), owner)
    action = sys.argv[1]
    control_operation = spec.get('control_operation_id', spec['operation_id'])
    masks = ('apt-daily.timer', 'apt-daily-upgrade.timer', 'apt-daily.service', 'apt-daily-upgrade.service')
    if action == 'publish':
        # Required only after both timers have been stopped by the operator.
        r.require(control_operation == spec['operation_id'], 'inherited controls cannot be republished')
        r.publish_inhibit(root, control_operation, owner)
        for unit in masks:
            path = at('/etc/systemd/system') / unit
            os.symlink('/dev/null', path)
            st = path.lstat()
            r.create(Path('mask-' + unit + '.json'), r.encoded({'device': st.st_dev, 'inode': st.st_ino}), owner=owner)
            r.sync(path.parent)
    elif action == 'check':
        r.check_inhibit(root, control_operation, owner)
        for unit in masks:
            path = at('/etc/systemd/system') / unit
            saved = json.loads(r.read(Path('mask-' + unit + '.json'), owner)[0])
            st = path.lstat()
            r.require(path.is_symlink() and os.readlink(path) == '/dev/null' and st.st_uid == owner
                      and (st.st_dev, st.st_ino) == (saved['device'], saved['inode']), 'mask changed')
    elif action == 'restore':
        # Validate all present masks before removing anything. Missing records hold cleanup.
        owned = []
        for unit in masks:
            path = at('/etc/systemd/system') / unit
            record = Path('mask-' + unit + '.json')
            if os.path.lexists(path):
                saved = json.loads(r.read(record, owner)[0]); st = path.lstat()
                r.require(path.is_symlink() and os.readlink(path) == '/dev/null' and st.st_uid == owner
                          and (st.st_dev, st.st_ino) == (saved['device'], saved['inode']), 'foreign mask')
                owned.append(path)
        if os.path.lexists(at(r.MARKER)):
            r.restore_inhibit(root, control_operation, owner)
        else:
            r.require(not os.path.lexists(at(r.DROPIN).parent), 'foreign inhibit residue')
        for path in owned:
            path.unlink(); r.sync(path.parent)
    elif action == 'publish-alsa-and-flags':
        raw = at('/var/lib/ntp-maintenance/base-os-update-20261027-v2/recovery.tar.gz').read_bytes()
        r.require(r.sha(raw) == spec['independent_backup_sha256'], 'backup SHA')
        members = r.verify_backup(raw, spec['backup'])
        target = at('/var/lib/apt/extended_states')
        before = r.read(target, owner)[1]
        original = members['var/lib/apt/extended_states']
        if r.sha(original) != before['sha256']:
            temporary = target.with_name('.extended_states.' + spec['operation_id'])
            r.create(temporary, original, spec['backup']['/var/lib/apt/extended_states']['mode'], owner)
            r.require(r.read(target, owner)[1] == before, 'extended-state race')
            os.replace(temporary, target); r.sync(target.parent)
        r.require(r.read(target, owner)[1] == spec['backup']['/var/lib/apt/extended_states'], 'extended-state restoration')
        target = at('/etc/udev/rules.d/90-alsa-restore.rules')
        temporary = target.with_name('.90-alsa-restore.rules.' + spec['operation_id'])
        r.create(temporary, r.read(Path('candidate.rules'), owner)[0], 0o644, owner)
        os.link(temporary, target, follow_symlinks=False)
        temporary.unlink(); r.sync(target.parent)
        r.require(r.read(target, owner)[0] == r.read(Path('candidate.rules'), owner)[0], 'ALSA publication')
    else:
        raise ValueError('unknown file action')


if __name__ == '__main__':
    main()
