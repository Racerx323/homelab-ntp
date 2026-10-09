#!/bin/bash
# Read-only, explicit execution modes; no clock/configuration/service changes.
set -Eeuo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
export LC_ALL=C
exec /usr/bin/python3 -I - "$@" <<'PYTHON'
import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
import socket
import stat
import struct
import subprocess
import sys
import time


def system_health(text):
    if not text.strip() or re.search(r'\*\*\*|timed?\s*out|refused|no response', text, re.I):
        raise ValueError('ntpq response error or empty output')
    values = {}
    for key, value in re.findall(r'\b(leap|stratum|peer|offset|rootdisp)\s*=\s*([^,\s]+)', text):
        if key in values:
            raise ValueError('duplicate system variable: ' + key)
        values[key] = value
    if set(values) != {'leap', 'stratum', 'peer', 'offset', 'rootdisp'}:
        raise ValueError('missing required system variables')
    if values['leap'] != '00' or int(values['stratum']) != 1 or int(values['peer']) <= 0:
        raise ValueError('primary is not selected stratum-1 leap-00')
    for key in ('offset', 'rootdisp'):
        if not math.isfinite(float(values[key])):
            raise ValueError('nonfinite ' + key)
    return values


def trusted_ntpq():
    matches = []
    for name in ('/usr/local/bin/ntpq', '/usr/bin/ntpq', '/usr/local/sbin/ntpq', '/usr/sbin/ntpq'):
        path = Path(name)
        if not path.exists():
            continue
        for part in (path, *path.parents):
            st = part.lstat()
            if stat.S_ISLNK(st.st_mode) or st.st_uid != 0 or st.st_mode & 0o022:
                raise ValueError('untrusted ntpq path: ' + str(part))
        if not path.is_file() or not os.access(path, os.X_OK):
            raise ValueError('ntpq candidate not executable regular file')
        matches.append(name)
    if len(matches) != 1:
        raise ValueError('ntpq missing or ambiguous: ' + str(matches))
    return matches[0]


def run(argv):
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=12, check=False)
        return {'argv': argv, 'rc': p.returncode, 'stdout': p.stdout, 'stderr': p.stderr}
    except subprocess.TimeoutExpired as exc:
        def decode(value):
            return value.decode(errors='replace') if isinstance(value, bytes) else value or ''
        return {'argv': argv, 'rc': 124, 'stdout': decode(exc.stdout),
                'stderr': decode(exc.stderr), 'error': 'timeout'}
    except OSError as exc:
        return {'argv': argv, 'rc': 127, 'stdout': '', 'stderr': str(exc)}


def file_hash():
    path = Path('/etc/ntp.conf')
    try:
        if path.is_symlink() or not path.is_file():
            raise ValueError('default config absent or symlink')
        return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    except (OSError, ValueError) as exc:
        return {'path': str(path), 'error': str(exc)}


def primary():
    if socket.gethostname() != 'j1-svntp':
        raise ValueError('wrong host; primary mode requires j1-svntp')
    ntpq = trusted_ntpq()
    before = file_hash()
    records = [run([ntpq, '-n', '-c', 'rv 0 leap,stratum,peer,offset,rootdisp', '127.0.0.1']),
               run([ntpq, '-n', '-c', 'peers', '127.0.0.1']),
               run(['/usr/bin/uptime']), run(['/usr/bin/ss', '-H', '-lun'])]
    after = file_hash()
    checks = {'commands_ok': all(r['rc'] == 0 and not r['stderr'].strip() for r in records),
              'default_config_unchanged': 'sha256' in before and before == after}
    try:
        values = system_health(records[0]['stdout'])
        checks['system_sync'] = records[0]['rc'] == 0 and not records[0]['stderr'].strip()
    except (ValueError, OverflowError) as exc:
        values = {'error': str(exc)}
        checks['system_sync'] = False
    peers = records[1]['stdout']
    checks['selected_peer_present'] = bool(re.search(r'(?m)^[*o]\S+', peers)) and not re.search(
        r'\*\*\*|timed?\s*out|refused|no response', peers, re.I)
    return {'records': records, 'pre_hash': before, 'post_hash': after,
            'system': values, 'checks': checks,
            'limitations': ['PPS identity/reach/quality and UDP listener bindings require review',
                            'default config hash does not establish effective config path',
                            'single snapshot does not prove sustained health or client failover']}


def response_health(packet, request):
    if not 48 <= len(packet) <= 512:
        raise ValueError('invalid NTP response length')
    if packet[0] & 7 != 4 or (packet[0] >> 3) & 7 not in (3, 4):
        raise ValueError('not an NTP server response')
    if packet[24:32] != request[40:48]:
        raise ValueError('originate mismatch')
    if packet[0] >> 6 == 3 or not 1 <= packet[1] <= 15:
        raise ValueError('unsynchronized or kiss-of-death')
    if not any(packet[32:40]) or not any(packet[40:48]):
        raise ValueError('zero server timestamp')
    return {'stratum': packet[1], 'leap': packet[0] >> 6}


def client(socket_factory=socket.socket):
    records = []
    for target in ('10.1.0.50', '10.1.0.51'):
        record = {'target': target, 'port': 123, 'attempted_packets': 0}
        try:
            seconds = time.time() + 2208988800
            stamp = struct.pack('!II', int(seconds) & 0xffffffff,
                                int((seconds % 1) * (1 << 32)))
            request = bytes([0x23]) + bytes(39) + stamp
            with socket_factory(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP) as sock:
                sock.settimeout(5)
                sock.connect((target, 123))
                record['source'] = sock.getsockname()
                record['attempted_packets'] = 1
                sock.send(request)
                packet = sock.recv(513)
            record.update(request_hex=request.hex(), response_hex=packet.hex())
            record.update(response_health(packet, request))
            record['ok'] = True
        except (OSError, ValueError) as exc:
            record.update(ok=False, error=str(exc))
        records.append(record)
    return {'records': records, 'checks': {'direct_ipv4_responses': all(r['ok'] for r in records)},
            'limitations': ['workstation source path only; not a UDM client-daemon or DNAT test',
                            'no clock adjustment, no loss/failover injection, no IPv6 claim']}


def main():
    args = sys.argv[1:]
    if args not in (['--primary'], ['--client-ipv4']):
        print('usage: pre-rebuild-health.sh --primary | --client-ipv4', file=sys.stderr)
        return 64
    result = {'schema': 'ntp-pre-rebuild-v1', 'mode': args[0],
              'host': socket.gethostname(), 'rebuild_authorized': False,
              'started': datetime.datetime.now(datetime.timezone.utc).isoformat()}
    try:
        result.update(primary() if args == ['--primary'] else client())
        result['exit_status'] = 0 if all(result['checks'].values()) else 2
    except (OSError, ValueError) as exc:
        result.update(error=str(exc), exit_status=2)
    result['finished'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    print(json.dumps(result, sort_keys=True))
    return result['exit_status']


if __name__ == '__main__':
    sys.exit(main())
PYTHON
