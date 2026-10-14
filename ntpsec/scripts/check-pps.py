#!/usr/bin/python3
"""Read-only GPIO PPS identity check against an explicit, digest-bound baseline."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import struct


def pps_mapping(cells, controller, falling):
    if len(cells)!=12 or len(controller)!=4 or struct.unpack('>III',cells)!=(struct.unpack('>I',controller)[0],18,0) or falling:
        raise ValueError('BCM18 rising PPS device-tree mapping required')


def gpio_pps_metadata(sysroot=Path('/sys'), devroot=Path('/dev'), observation=None):
    observation = {} if observation is None else observation
    observation.update(platforms=[], classes=[], selected=None)
    gpio = sysroot/'firmware/devicetree/base/soc/gpio@7e200000'
    if b'brcm,bcm2711-gpio' not in (gpio/'compatible').read_bytes().split(b'\0'):
        raise ValueError('Pi 4 GPIO controller required')
    platforms = []
    driver = sysroot/'bus/platform/drivers/pps-gpio'
    entries = sorted(driver.iterdir())
    observation['platform_entry_count'] = len(entries)
    if len(entries) > 32:
        raise ValueError('bounded PPS platform registry required')
    for link in entries:
        if link.name in ('module','bind','unbind','uevent') or not link.is_symlink():
            continue
        platform = link.resolve(strict=True)
        observation['platforms'].append({'entry': str(link), 'path': str(platform)})
        if (not platform.is_relative_to(sysroot/'devices/platform')
                or (platform/'driver').resolve(strict=True) != driver
                or (platform/'subsystem').resolve(strict=True) != sysroot/'bus/platform'):
            raise ValueError('bound PPS platform identity required')
        node = (platform/'of_node').resolve(strict=True)
        if not node.is_relative_to(sysroot/'firmware/devicetree/base'):
            raise ValueError('PPS device-tree path escaped')
        if b'pps-gpio' not in (node/'compatible').read_bytes().split(b'\0'):
            raise ValueError('PPS GPIO compatibility required')
        pps_mapping((node/'gpios').read_bytes(),(gpio/'phandle').read_bytes(),(node/'assert-falling-edge').exists())
        platforms.append((platform,node))
    classes = sorted((sysroot/'class/pps').glob('pps[0-9]*'))
    observation['class_count'] = len(classes)
    if len(classes) > 32:
        raise ValueError('bounded PPS class registry required')
    for path in classes:
        row = {'class': str(path), 'path': str(path.resolve(strict=True))}
        observation['classes'].append(row)
        if not path.is_symlink() or not Path(row['path']).is_relative_to(sysroot/'devices'):
            raise ValueError('PPS class escaped sysfs devices: '+str(path))
        for key in ('name', 'dev'):
            prop = path/key
            if prop.is_symlink() or not prop.is_file():
                raise ValueError('regular PPS class property required: '+str(prop))
            with prop.open('rb') as stream:
                raw = stream.read(257)
            if len(raw) > 256:
                raise ValueError('bounded PPS class property required: '+str(path/key))
            row[key] = raw.decode().strip()
    if len(platforms) != 1:
        raise ValueError(f'one GPIO PPS platform required; observed {len(platforms)}')
    platform,node = platforms[0]
    matching = [row for row in observation['classes'] if row['name'] == platform.name+'.-1']
    if len(matching) != 1:
        raise ValueError(f'one GPIO PPS source identity required; matched {len(matching)} of {len(classes)} classes')
    row = matching[0]; path = Path(row['class']); name = row['name']
    observation['selected'] = row
    if sum(item['dev'] == row['dev'] for item in observation['classes']) != 1:
        raise ValueError('duplicate GPIO PPS character-device mapping')
    dev = devroot/path.name; info = dev.stat()
    if (not stat.S_ISCHR(info.st_mode) or dev.is_symlink() or
            row['dev'] != f'{os.major(info.st_rdev)}:{os.minor(info.st_rdev)}'):
        raise ValueError('PPS character-device identity mismatch: '+str(dev))
    return {'device':str(dev),'of_node':str(node),'name':name,'platform':str(platform)}


def check(expected, sysroot=Path('/sys'), devroot=Path('/dev')):
    observation = {}
    try:
        actual = gpio_pps_metadata(sysroot, devroot, observation)
        observation['actual'] = actual
        if actual != expected:
            raise ValueError('accepted GPIO PPS mapping drift')
        observation['accepted'] = True
    except (OSError, ValueError) as error:
        observation.update(accepted=False, error=str(error)[:500])
    return observation


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--baseline-sha256', required=True)
    args = parser.parse_args()
    try:
        with args.baseline.open('rb') as stream:
            raw = stream.read(65537)
        if len(raw) > 65536 or hashlib.sha256(raw).hexdigest() != args.baseline_sha256:
            raise ValueError('bounded baseline with matching SHA-256 required')
        expected = json.loads(raw)
        if not isinstance(expected, dict) or set(expected) != {'device','of_node','name','platform'}:
            raise ValueError('explicit accepted GPIO PPS mapping required')
        result = check(expected)
    except (OSError, ValueError) as error:
        result = {'accepted': False, 'error': str(error)[:500]}
    print(json.dumps(result, sort_keys=True))
    return 0 if result['accepted'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
