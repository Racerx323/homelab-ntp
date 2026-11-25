#!/usr/bin/python3
"""Qualify bounded evidence capture and admission; never contact a target."""
import base64
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
loader = importlib.util.spec_from_file_location('recurrence', ROOT/'scripts/inspect-leap-recurrence.py')
c = importlib.util.module_from_spec(loader)
loader.loader.exec_module(c)
h = c.load(ROOT/'scripts/run-production-inspection.py')


class RecurrenceTests(unittest.TestCase):
    def capture(self, boots=('fresh', 'fresh'), host='j2-svntp1', fail=False):
        spec = {'hostname': 'j2-svntp1', 'not_before': 0, 'not_after': time.time()+60,
                'commands': {'units': ['/usr/bin/systemctl', 'show', 'ntpleapfetch.timer']},
                'files': [], 'leapfile': '/var/lib/ntpsec/leap-seconds.list'}
        out = io.StringIO()
        def command(argv, **kwargs):
            if fail:
                raise FileNotFoundError('missing native tool')
            return {'argv': argv, 'returncode': 0, 'stdout': 'ActiveState=active\n', 'stderr': ''}
        with patch.object(c, 'boot', side_effect=boots), patch.object(c.socket, 'gethostname', return_value=host), \
                patch.object(c.os, 'geteuid', return_value=0), patch.object(h, 'bounded', side_effect=command), \
                contextlib.redirect_stdout(out):
            c.collect(spec, h)
        return {v['record']: v['value'] for v in map(json.loads, out.getvalue().splitlines())}

    def test_fresh_boot_admitted_but_never_auto_accepted(self):
        v = self.capture()
        self.assertTrue(v['terminal']['capture_complete'])
        self.assertFalse(v['terminal']['recurrence_accepted'])

    def test_wrong_host_and_midcapture_boot_change_rejected(self):
        v = self.capture(host='wrong')
        self.assertNotIn('units', v)
        self.assertFalse(v['terminal']['capture_complete'])
        self.assertFalse(self.capture(boots=('a', 'b'))['terminal']['capture_complete'])

    def test_failure_retains_admission_command_and_terminal(self):
        v = self.capture(fail=True)
        self.assertIn('missing native tool', v['units']['error'])
        self.assertIn('admission', v)
        self.assertFalse(v['terminal']['capture_complete'])

    def test_leap_expiry_and_ambiguous_content(self):
        row = {'base64': base64.b64encode(b'#@ 4023129600\n').decode()}
        v = c.leap_facts(row, 1795556808)
        self.assertTrue(v['unexpired'])
        self.assertFalse(c.leap_facts(row, 4023129600)['unexpired'])
        row['base64'] = base64.b64encode(b'#@ 1\n#@ 2\n').decode()
        with self.assertRaisesRegex(ValueError, 'one leapfile expiry'):
            c.leap_facts(row, 0)

    def test_real_timeout_and_output_cap_retain_partial_bytes(self):
        for program, limit in [('import time;print("before",flush=True);time.sleep(2)', 1024),
                               ('print("x"*4096,flush=True)', 100)]:
            retained = []
            v = h.bounded(['/usr/bin/python3', '-I', '-B', '-c', program], timeout=.2,
                          limit=limit, sink=lambda name, raw: retained.append((name, raw)))
            self.assertIn('error', v)
            self.assertTrue(v['stdout'])
            self.assertLessEqual(len(v['stdout']), limit)
            self.assertEqual(v['stdout'].encode(), b''.join(raw for name, raw in retained if name == 'stdout'))

    def test_consumed_receipt_prevents_contact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp);key = root/'key';key.write_text('test');key.chmod(0o600)
            (root/'execution.json').write_text('{}')
            spec = {'controller_hostname': c.socket.gethostname(), 'not_before': 0, 'not_after': time.time()+60,
                    'target': 'ama@10.1.0.51', 'host_key_alias': '10.1.0.137',
                    'transport': {'identity_file': str(key), 'identity_fingerprint': 'SHA256:test', 'ssh_options': []}}
            with patch.object(c, 'check', return_value=spec), patch.object(c, 'load', return_value=h), \
                    patch.object(c, 'payload', return_value=b''), \
                    patch.object(c.subprocess, 'check_output', return_value=b'256 SHA256:test test'), \
                    patch.object(h, 'bounded') as contact:
                with self.assertRaises(FileExistsError):c.execute(root, 'digest')
                contact.assert_not_called()

    def test_journal_saturation_is_incomplete(self):
        out = io.StringIO()
        spec = {'hostname': c.socket.gethostname(), 'not_before': 0, 'not_after': time.time()+60,
                'commands': {'journal': ['/usr/bin/journalctl']}, 'files': []}
        with patch.object(c.os, 'geteuid', return_value=0), \
                patch.object(h, 'bounded', return_value={'returncode': 0, 'stdout': '{}\n'*1001}), \
                contextlib.redirect_stdout(out):c.collect(spec, h)
        rows = {x['record']:x['value'] for x in map(json.loads, out.getvalue().splitlines())}
        self.assertTrue(rows['journal_coverage']['saturated'])
        self.assertFalse(rows['terminal']['capture_complete'])


if __name__ == '__main__':
    unittest.main()
