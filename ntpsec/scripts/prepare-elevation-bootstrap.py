#!/usr/bin/python3
"""Verify an approved bootstrap archive and write a timestamped operator paste."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import tarfile
import time


def prepare(bundle, expected, mode, epoch):
    if bundle.is_symlink() or hashlib.sha256(bundle.read_bytes()).hexdigest() != expected:
        raise ValueError('bootstrap archive hash mismatch')
    with tarfile.open(bundle) as archive:
        names = archive.getnames()
        if len(set(names)) != len(names) or not all(m.isfile() for m in archive):
            raise ValueError('invalid bootstrap members')
        manifest = json.load(archive.extractfile('manifest.json'))
        if set(manifest['members']) != set(names) - {'manifest.json'}:
            raise ValueError('bootstrap manifest member set mismatch')
        for name, digest in manifest['members'].items():
            if hashlib.sha256(archive.extractfile(name).read()).hexdigest() != digest:
                raise ValueError('bootstrap member hash mismatch: ' + name)
        if archive.extractfile('prepare-elevation-bootstrap.py').read() != Path(__file__).read_bytes():
            raise ValueError('bootstrap preparation helper differs from approved input')
        if mode not in ('install', 'remove', 'rollback'):
            raise ValueError('unknown bootstrap operation')
        if mode == 'install' and epoch >= manifest['expires_epoch']:
            raise ValueError('bootstrap approval window expired')
        template = archive.extractfile('operator-' + mode + '.txt').read().decode('utf-8')
        if template.count('@CONTROLLER_EPOCH@') != 1:
            raise ValueError('one declared timestamp substitution required')
        return template.replace('@CONTROLLER_EPOCH@', str(epoch)).encode('utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--mode', choices=('install', 'remove', 'rollback'), required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    if (args.output.parent.is_symlink() or args.output.parent.stat().st_uid != os.getuid()
            or args.output.parent.stat().st_mode & 0o077):
        raise ValueError('operator paste output directory must be owner-private')
    epoch = int(time.time())
    data = prepare(args.bundle, args.sha256, args.mode, epoch)
    with args.output.open('xb') as stream:
        stream.write(data); stream.flush(); os.fsync(stream.fileno())
    print(json.dumps({'state': 'operator_paste_prepared_not_executed', 'mode': args.mode,
                      'controller_epoch': epoch, 'output': str(args.output),
                      'sha256': hashlib.sha256(data).hexdigest()}))


if __name__ == '__main__':
    main()
