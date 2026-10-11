#!/usr/bin/python3
"""Fetch pinned installation data into a new private cache; never execute it."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
from urllib.parse import urlsplit
from urllib.request import urlopen

DEFAULT = Path(__file__).resolve().parents[1] / 'configs/installation-assets.json'


def validate_manifest(manifest):
    if (not isinstance(manifest, dict) or manifest.get('schema') != 1
            or not isinstance(manifest.get('assets'), list) or not manifest['assets']):
        raise ValueError('installation manifest schema/inputs required')
    names, identifiers = set(), set()
    for row in manifest['assets']:
        if not isinstance(row, dict) or not isinstance(row.get('id'), str):
            raise ValueError('asset object and string identity required')
        uri = urlsplit(row['url'])
        if (uri.scheme != 'https' or not uri.hostname or uri.username or uri.password
                or uri.query or uri.fragment
                or not re.fullmatch(r'[A-Za-z0-9_.+%~-]+', row['filename'])
                or row['filename'] in {'.', '..'}
                or row['filename'] in names or row['id'] in identifiers
                or not re.fullmatch(r'[0-9a-f]{64}', row['sha256'])
                or type(row['size']) is not int or not 0 < row['size'] <= 2 * 1024**3
                or not isinstance(row['groups'], list) or not row['groups']
                or not all(isinstance(g, str) and g for g in row['groups'])
                or row.get('package') in {'ntp', 'ntpsec', 'gpsd', 'gpsd-clients', 'python3-gps'}):
            raise ValueError('unsafe, duplicate or conflicting installation asset')
        names.add(row['filename'])
        identifiers.add(row['id'])
    keys = manifest.get('public_keys', {})
    if not isinstance(keys, dict):
        raise ValueError('public key map required')
    for key in keys.values():
        if (not isinstance(key, dict) or Path(key['path']).is_absolute()
                or '..' in Path(key['path']).parts
                or not re.fullmatch(r'[0-9a-f]{64}', key['sha256'])
                or not re.fullmatch(r'[A-F0-9]{40}', key['signing_fingerprint'])):
            raise ValueError('invalid pinned source verification key')
    for row in manifest['assets']:
        if 'signature' in row and (row['signature'] not in identifiers
                                   or row.get('public_key') not in keys
                                   or row['signature'] == row['id']):
            raise ValueError('source signature/key binding missing')


def verify_file(path, row):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size != row['size']:
            raise ValueError('asset file type/size mismatch: ' + row['id'])
        checksum = hashlib.sha256()
        for data in iter(lambda: stream.read(1024 * 1024), b''):
            checksum.update(data)
        if checksum.hexdigest() != row['sha256']:
            raise ValueError('asset digest mismatch: ' + row['id'])


def fetch(row, destination, timeout):
    temporary = destination.with_name(destination.name + '.part')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, 'wb') as output, urlopen(row['url'], timeout=timeout) as response:
            if urlsplit(response.geturl()).scheme != 'https':
                raise ValueError('non-HTTPS download redirect rejected')
            size = 0
            while True:
                data = response.read(min(1024 * 1024, row['size'] + 1 - size))
                if not data:
                    break
                size += len(data)
                if size > row['size']:
                    raise ValueError('download exceeds pinned size')
                output.write(data)
            output.flush()
            os.fsync(output.fileno())
        verify_file(temporary, row)
        os.link(temporary, destination, follow_symlinks=False)
    finally:
        temporary.unlink()


def verify_signature(row, by_id, cache, keys, manifest_path):
    key = keys[row['public_key']]
    relative = Path(key['path'])
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError('public key path escapes repository manifest')
    path = manifest_path.parent / relative
    if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != key['sha256']:
        raise ValueError('repository public key digest mismatch')
    result = subprocess.run(['/usr/bin/gpgv', '--status-fd=1', '--keyring', str(path.resolve()),
                             str(cache / by_id[row['signature']]['filename']), str(cache / row['filename'])],
                            capture_output=True, timeout=30, check=True)
    expected = '[GNUPG:] VALIDSIG ' + key['signing_fingerprint'] + ' '
    if not any(line.startswith(expected) for line in result.stdout.decode('ascii').splitlines()):
        raise ValueError('source signature does not match pinned signing identity')


def run(manifest_path, cache, groups, verify_only=False, timeout=30):
    raw = manifest_path.read_bytes()
    manifest = json.loads(raw)
    validate_manifest(manifest)
    known = {g for row in manifest['assets'] for g in row['groups']}
    if not groups or set(groups) - known:
        raise ValueError('choose explicit manifest groups')
    selected = [row for row in manifest['assets'] if set(groups) & set(row['groups'])]
    by_id = {row['id']: row for row in manifest['assets']}
    for row in selected[:]:
        if 'signature' in row and by_id[row['signature']] not in selected:
            selected.append(by_id[row['signature']])
    if any(p.is_symlink() for p in (cache, *cache.parents)):
        raise ValueError('symlink cache path rejected')
    if verify_only:
        if not cache.is_dir():
            raise ValueError('existing cache required for verification')
    else:
        cache.mkdir(mode=0o700)  # Never replace or merge another download attempt.
    for row in selected:
        path = cache / row['filename']
        if not verify_only:
            fetch(row, path, timeout)
        verify_file(path, row)
    signatures = 0
    for row in selected:
        if 'signature' in row:
            verify_signature(row, by_id, cache, manifest['public_keys'], manifest_path)
            signatures += 1
    report = {'manifest_sha256': hashlib.sha256(raw).hexdigest(), 'groups': sorted(set(groups)),
              'verified_assets': len(selected), 'verified_signatures': signatures,
              'cache': str(cache.absolute()), 'installation_performed': False}
    if not verify_only:
        with (cache / 'fetch-receipt.json').open('x') as stream:
            json.dump(report, stream, indent=2)
            stream.write('\n')
    return report


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=DEFAULT)
    parser.add_argument('--cache', type=Path, required=True)
    parser.add_argument('--group', action='append', required=True)
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    try:
        print(json.dumps(run(args.manifest, args.cache, args.group, args.verify_only)))
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        print('Installation asset verification failed: ' + type(exc).__name__, file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
