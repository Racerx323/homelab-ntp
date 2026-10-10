#!/usr/bin/python3
"""Inspect or hash-bind a PPS GPIO edit; never reboot or select hardware blindly."""
import argparse
import hashlib
import os
from pathlib import Path
import re
import stat
import tempfile


def edit(text, gpio):
    if not isinstance(gpio, int) or not 0 <= gpio <= 27:
        raise ValueError('GPIO must be an explicit BCM GPIO 0..27')
    lines = text.splitlines(keepends=True)
    matches = []
    section = 'all'
    for index, line in enumerate(lines):
        value = line.split('#', 1)[0].strip()
        if value.startswith('include '):
            raise ValueError('included boot configuration requires an effective-config review')
        if value.startswith('['):
            section = value.strip('[]')
        if value.startswith('dtoverlay=pps-gpio'):
            if section != 'all' or not re.match(r'^dtoverlay=pps-gpio(?:,|$)', value):
                raise ValueError('conditional or ambiguous PPS overlay')
            matches.append((index, value))
    if len(matches) > 1:
        raise ValueError('duplicate PPS overlays')
    if not matches:
        return text + ('' if not text or text.endswith('\n') else '\n') + '[all]\ndtoverlay=pps-gpio,gpiopin=' + str(gpio) + '\n'
    index, value = matches[0]
    parameters = value.split(',')
    existing = [p for p in parameters if p.startswith('gpiopin=')]
    if len(existing) > 1 or (existing and not re.fullmatch(r'gpiopin=\d+', existing[0])):
        raise ValueError('ambiguous GPIO parameter')
    if existing and existing[0] == 'gpiopin=' + str(gpio):
        return text
    parameters = [p for p in parameters if not p.startswith('gpiopin=')]
    parameters.append('gpiopin=' + str(gpio))
    comment = lines[index].partition('#')[2].rstrip('\n')
    lines[index] = ','.join(parameters) + (' #' + comment if comment else '') + '\n'
    return ''.join(lines)


def inspect(text):
    # Use the same ambiguity checks without modifying the supplied text.
    edit(text, 18)
    active = [line.split('#', 1)[0].strip() for line in text.splitlines()
              if line.split('#', 1)[0].strip().startswith('dtoverlay=pps-gpio')]
    return active[0] if active else 'no explicit PPS overlay'


def require_target(path, hostname):
    if (path != Path('/boot/firmware/config.txt') or not hostname
            or os.uname().nodename != hostname or os.uname().machine != 'aarch64'):
        raise ValueError('requires the approved arm64 hostname and Trixie boot configuration path')


def update(path, expected, gpio, hostname):
    if os.geteuid() != 0:
        raise ValueError('boot configuration edit requires root')
    require_target(path, hostname)
    for parent in path.parents:
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError('unsafe boot configuration parent')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError('unsafe boot configuration')
        data = stream.read()
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError('boot configuration hash mismatch')
    candidate = edit(data.decode(), gpio).encode()
    if candidate == data:
        return False
    backup = path.with_name(path.name + '.pinup-' + expected)
    # The original bytes are preserved once; no backup clobber or automatic reboot.
    with backup.open('xb') as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    descriptor, name = tempfile.mkstemp(prefix='.pinup-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(candidate)
            os.fchown(stream.fileno(), info.st_uid, info.st_gid)
            os.fchmod(stream.fileno(), stat.S_IMODE(info.st_mode))
            stream.flush()
            os.fsync(stream.fileno())
        if path.is_symlink() or path.read_bytes() != data:
            raise ValueError('boot configuration changed during edit')
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True, help='observed boot config path')
    parser.add_argument('--gpio', type=int, help='explicit, observed PPS BCM GPIO')
    parser.add_argument('--expected-sha256')
    parser.add_argument('--hostname', help='approved target hostname, required for edits')
    args = parser.parse_args()
    try:
        if args.gpio is None:
            if args.config.is_symlink():
                raise ValueError('symlink boot configuration')
            print(inspect(args.config.read_text()))
        else:
            if args.expected_sha256 is None or args.hostname is None:
                parser.error('--expected-sha256 and --hostname required for edits')
            print('changed; reboot remains separately scoped' if update(
                args.config.absolute(), args.expected_sha256, args.gpio, args.hostname) else 'unchanged')
    except (OSError, ValueError) as exc:
        parser.exit(1, str(exc) + '\n')


if __name__ == '__main__':
    main()
