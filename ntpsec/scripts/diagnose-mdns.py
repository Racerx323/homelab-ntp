#!/usr/bin/python3
"""Bounded local routing metadata and raw replies for the existing mDNS checker."""
import base64
import shutil
import socket
import subprocess
import tempfile
import time


def command(argv):
    result = {'argv': argv}
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        try:
            proc = subprocess.run(argv, stdout=out, stderr=err, timeout=5, check=False)
            result['returncode'] = proc.returncode
        except (OSError, subprocess.TimeoutExpired) as error:
            result['error'] = str(error)[:500]
        for name, stream in (('stdout', out), ('stderr', err)):
            stream.seek(0); raw = stream.read(65537)
            result[name] = raw[:65536].decode('utf-8', errors='replace')
            result[name+'_truncated'] = len(raw) > 65536
    return result


def capture(spec, client, output):
    output['network'] = []
    executable = shutil.which('ip')
    if spec.get('skip_network_metadata'):
        output['network_note'] = 'Paired capture uses the separately retained interface comparison.'
    elif executable is None:
        output['network_error'] = 'ip executable unavailable'
    else:
        commands = ([executable, '-j', 'address', 'show'],
                    [executable, '-j', '-4', 'route', 'get', spec['endpoints'][0]],
                    [executable, '-j', '-6', 'route', 'get', spec['endpoints'][1]],
                    [executable, '-j', '-4', 'route', 'get', '224.0.0.251'])
        for argv in commands: output['network'].append(command(argv))
    mdns = {'queries': [], 'replies': [], 'matched': False, 'accepted_source_records': []}
    output['mdns'] = mdns
    records = mdns['accepted_source_records']
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(1); sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 255)
        source = spec.get('source_ipv4', '')
        sock.bind((source, 0))
        if source: sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(source))
        for name, kind in (('_ntp._udp.local', 12), (spec['hostname']+'.local', 1), (spec['hostname']+'.local', 28)):
            item = {'name': name, 'type': kind, 'epoch': time.time()}
            mdns['queries'].append(item)
            packet = client['query'](name, kind)
            item['query_base64'] = base64.b64encode(packet).decode()
            item['bytes_sent'] = sock.sendto(packet, ('224.0.0.251', 5353))
            item['socket_address'] = sock.getsockname()
            until = time.monotonic()+3
            while time.monotonic() < until and len(mdns['replies']) < 64:
                try: raw, source = sock.recvfrom(9001)
                except socket.timeout: continue
                reply = {'query_index': len(mdns['queries'])-1, 'source': source,
                         'epoch': time.time(), 'bytes': len(raw),
                         'possibly_truncated': len(raw) >= 9001,
                         'base64': base64.b64encode(raw).decode(),
                         'accepted_source': source[0] == spec['endpoints'][0] and source[1] == 5353}
                mdns['replies'].append(reply)
                try:
                    reply['records'] = client['dns_records'](raw)
                except (ValueError, IndexError) as error:
                    reply['parse_error'] = str(error)[:500]
                else:
                    if reply['accepted_source']: records.extend(reply['records'])
        mdns['reply_limit_reached'] = len(mdns['replies']) == 64
        mdns['matched'] = client['discovery_matches'](records, spec['endpoints'], spec['hostname'])


if __name__ == '__main__': raise SystemExit('Use the sealed workstation controller')
