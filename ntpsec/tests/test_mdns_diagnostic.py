#!/usr/bin/python3
"""Real DNS parser/matcher with bounded simulated socket and process I/O."""
import base64
from contextlib import ExitStack
import importlib.util
import ipaddress
import itertools
from pathlib import Path
import socket
import struct
import subprocess
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT/'scripts'/name)
    result = importlib.util.module_from_spec(spec); spec.loader.exec_module(result)
    return result


d = load('diagnose-mdns.py'); client = vars(load('check-time-client.py'))
SPEC = {'hostname': 'fixture', 'endpoints': ['192.0.2.1', '2001:db8::1']}


def name(value): return b''.join(bytes([len(p)])+p.encode() for p in value.split('.'))+b'\0'


def packet():
    instance = 'clock._ntp._udp.local'; host = 'fixture.local'
    records = [('_ntp._udp.local', 12, name(instance)),
               (instance, 33, struct.pack('!HHH', 0, 0, 123)+name(host)),
               (host, 1, ipaddress.ip_address(SPEC['endpoints'][0]).packed),
               (host, 28, ipaddress.ip_address(SPEC['endpoints'][1]).packed)]
    return struct.pack('!6H', 0, 0x8400, 0, len(records), 0, 0)+b''.join(
        name(owner)+struct.pack('!HHIH', kind, 1, 120, len(raw))+raw for owner, kind, raw in records)


class Socket:
    def __init__(self, replies): self.replies = iter(replies); self.sent = []
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def settimeout(self, value): pass
    def setsockopt(self, *args): pass
    def bind(self, value): self.bound = value
    def getsockname(self): return ('0.0.0.0', 45000)
    def sendto(self, packet, endpoint): self.sent.append((packet, endpoint)); return len(packet)
    def recvfrom(self, size):
        assert size == 9001
        try: return next(self.replies)
        except StopIteration: raise socket.timeout()


class DiagnosticTests(unittest.TestCase):
    def capture(self, replies):
        output = {}; sock = Socket(replies); clock = itertools.count(0, .01)
        with ExitStack() as stack:
            stack.enter_context(patch.object(d.socket, 'socket', return_value=sock))
            stack.enter_context(patch.object(d.time, 'monotonic', side_effect=lambda: next(clock)))
            stack.enter_context(patch.object(d.shutil, 'which', return_value='/usr/bin/ip'))
            commands = stack.enter_context(patch.object(d, 'command', side_effect=lambda argv: {'argv': argv, 'returncode': 0}))
            d.capture(SPEC, client, output)
        self.assertEqual(commands.call_count, 4)
        self.assertEqual(len(sock.sent), 3)
        self.assertTrue(all(endpoint == ('224.0.0.251', 5353) for _, endpoint in sock.sent))
        return output

    def test_matching_raw_reply_and_routes(self):
        raw = packet(); result = self.capture([(raw, ('192.0.2.1', 5353))])
        self.assertTrue(result['mdns']['matched'])
        self.assertEqual(base64.b64decode(result['mdns']['replies'][0]['base64']), raw)
        self.assertEqual(result['network'][-1]['argv'][-1], '224.0.0.251')
        self.assertEqual(result['network'][2]['argv'][-1], '2001:db8::1')

    def test_other_source_is_retained_without_acceptance(self):
        result = self.capture([(packet(), ('192.0.2.2', 5353))])['mdns']
        self.assertFalse(result['matched']); self.assertFalse(result['replies'][0]['accepted_source'])
        self.assertEqual(len(result['replies'][0]['records']), 4)

    def test_malformed_and_oversize_retained(self):
        result = self.capture([(b'bad', ('192.0.2.1', 5353)), (b'x'*9001, ('192.0.2.1', 5353))])['mdns']
        self.assertFalse(result['matched'])
        self.assertTrue(all('parse_error' in x for x in result['replies']))
        self.assertTrue(result['replies'][1]['possibly_truncated'])

    def test_empty_capture_is_not_missing_advertisement_proof(self):
        result = self.capture([])['mdns']
        self.assertFalse(result['matched']); self.assertEqual(result['replies'], [])
        self.assertEqual(len(result['queries']), 3)

    def test_reply_limit(self):
        result = self.capture([(packet(), ('192.0.2.1', 5353))]*100)['mdns']
        self.assertEqual(len(result['replies']), 64); self.assertTrue(result['reply_limit_reached'])

    def test_command_output_bounded_and_timeout_retained(self):
        def run(argv, stdout, stderr, **kwargs):
            self.assertEqual(kwargs['timeout'], 5)
            stdout.write(b'x'*70000); stderr.write(b'partial')
            raise subprocess.TimeoutExpired(argv, 5)
        with patch.object(d.subprocess, 'run', side_effect=run): result = d.command(['/usr/bin/ip', '-j', 'address', 'show'])
        self.assertEqual(len(result['stdout']), 65536); self.assertTrue(result['stdout_truncated'])
        self.assertEqual(result['stderr'], 'partial'); self.assertIn('error', result)

    def test_total_timeout_preserves_prior_replies(self):
        output = {}; sock = Socket([(packet(), ('192.0.2.1', 5353))]); clock = itertools.count(0, .01)
        original = sock.recvfrom
        def receive(size):
            if output['mdns']['replies']: raise RuntimeError('total bound')
            return original(size)
        sock.recvfrom = receive
        with patch.object(d.shutil, 'which', return_value=None), patch.object(d.socket, 'socket', return_value=sock), patch.object(d.time, 'monotonic', side_effect=lambda: next(clock)):
            with self.assertRaises(RuntimeError): d.capture(SPEC, client, output)
        self.assertIn('network_error', output); self.assertEqual(len(output['mdns']['replies']), 1)


if __name__ == '__main__': unittest.main()
