#!/usr/bin/python3
"""Paired capture uses actual parser/socket logic with simulated external I/O."""
import base64
from contextlib import ExitStack
import importlib.util
import itertools
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]


def load(path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


fixtures = load(ROOT/'tests/test_mdns_diagnostic.py')
p = load(ROOT/'scripts/compare-mdns.py'); d = fixtures.d; client = fixtures.client
SPEC = dict(fixtures.SPEC, source_ipv4='192.0.2.10')
WINDOWS = (ROOT/'scripts/capture-mdns-windows.ps1').read_bytes()


class PairedTests(unittest.TestCase):
    def test_equivalent_wire_queries_and_real_matching(self):
        output = {}; sock = fixtures.Socket([(fixtures.packet(), ('192.0.2.1', 5353))])
        clock = itertools.count(0, .01)
        native = {'completed': True, 'queries': p.queries(SPEC, client), 'replies': [
            {'source': ['192.0.2.1', 5353], 'base64': base64.b64encode(fixtures.packet()).decode()}]}
        def run(argv, stdout, stderr, timeout, check):
            self.assertEqual(timeout, 20)
            command = base64.b64decode(argv[-1]).decode('utf-16-le')
            self.assertTrue(command.startswith(WINDOWS.decode()))
            payload = command.split('Invoke-MdnsCapture -SpecBase64 "')[-1].split('"')[0]
            data = json.loads(base64.b64decode(payload)); self.assertEqual(data['source_ipv4'], SPEC['source_ipv4'])
            self.assertEqual(data['queries'], native['queries'])
            stdout.write(json.dumps(native).encode()); return subprocess.CompletedProcess(argv, 0)
        with ExitStack() as stack:
            stack.enter_context(patch.object(p.shutil, 'which', return_value='/windows/powershell.exe'))
            stack.enter_context(patch.object(p.subprocess, 'run', side_effect=run))
            stack.enter_context(patch.object(d.socket, 'socket', return_value=sock))
            stack.enter_context(patch.object(d.time, 'monotonic', side_effect=lambda: next(clock)))
            stack.enter_context(patch.object(d, 'command', side_effect=AssertionError('metadata collection forbidden')))
            p.capture(SPEC, client, vars(d), WINDOWS, output)
        self.assertEqual(sock.bound, (SPEC['source_ipv4'], 0))
        self.assertTrue(output['identical_queries'])
        self.assertTrue(output['windows']['capture']['matched']); self.assertTrue(output['wsl']['mdns']['matched'])
        self.assertEqual([base64.b64encode(raw).decode() for raw, _ in sock.sent], [q['query_base64'] for q in native['queries']])

    def test_native_timeout_stops_wsl_and_keeps_output(self):
        output = {}; diagnostic = {'capture': Mock()}
        def run(argv, stdout, **kwargs):
            stdout.write(b'partial'); raise subprocess.TimeoutExpired(argv, 20)
        with patch.object(p.shutil, 'which', return_value='/windows/powershell.exe'), patch.object(p.subprocess, 'run', side_effect=run):
            with self.assertRaisesRegex(ValueError, 'native capture failed'):
                p.capture(SPEC, client, diagnostic, WINDOWS, output)
        diagnostic['capture'].assert_not_called(); self.assertEqual(output['windows']['stdout'], 'partial')

    def test_parser_keeps_unexpected_source_and_malformed_packet(self):
        value = {'replies': [{'source': ['192.0.2.9', 5353], 'base64': base64.b64encode(fixtures.packet()).decode()},
                             {'source': ['192.0.2.1', 5353], 'base64': 'YmFk'}]}
        p.decode(value, SPEC, client)
        self.assertFalse(value['matched']); self.assertFalse(value['replies'][0]['accepted_source'])
        self.assertIn('parse_error', value['replies'][1])

    def test_native_output_bounds(self):
        with self.assertRaisesRegex(ValueError, 'count bound'): p.decode({'replies': [{}]*65}, SPEC, client)
        with self.assertRaisesRegex(ValueError, 'size bound'):
            p.decode({'replies': [{'base64': base64.b64encode(b'x'*9002).decode()}]}, SPEC, client)


if __name__ == '__main__': unittest.main()
