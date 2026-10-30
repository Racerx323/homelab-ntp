#!/usr/bin/python3
"""Offline contracts for the actual bounded observation executor; no target contact."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
def load(path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
r = load(ROOT/'scripts/observe-service-window.py')
h = load(ROOT/'scripts/run-production-inspection.py')
c = load(ROOT/'scripts/check-time-client.py')


class Observation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        shutil.copy2(ROOT/'scripts/run-production-inspection.py', self.root/'helper.py')

    def rows(self):
        return [{'due_monotonic': k*300, 'streams': {s: {'recorded': True,
                 'start_monotonic': k*300, 'complete': True} for s in r.STREAMS}}
                for k in range(r.SLOTS)]

    def test_full_window(self):
        self.assertTrue(all(v['completeness_pass'] for v in r.summarize(self.rows())['streams'].values()))

    def test_protected_binary_above_old_read_limit(self):
        path = self.root/'installed-binary'
        raw = bytes(range(256))*8192
        path.write_bytes(raw)
        self.assertEqual(r.protected_hash(path), r.digest(raw))

    def test_protected_oversized_file_names_path(self):
        path = self.root/'oversized'
        with path.open('wb') as stream: stream.truncate(r.PROTECTED_FILE_CAP+1)
        with self.assertRaisesRegex(ValueError, 'oversized.*64 MiB'):
            r.protected_hash(path)

    def test_protected_hash_rejects_symlink(self):
        path = self.root/'original'; path.write_bytes(b'content')
        link = self.root/'link'; link.symlink_to(path)
        with self.assertRaisesRegex(ValueError, 'protected file .*link'):
            r.protected_hash(link)

    def test_protected_hash_rejects_directory(self):
        with self.assertRaisesRegex(ValueError, 'protected file'):
            r.protected_hash(self.root)

    def test_protected_hash_rejects_change_during_read(self):
        path = self.root/'changing'; path.write_bytes(b'content')
        before = path.stat()
        after = types.SimpleNamespace(**{k:getattr(before,k) for k in
            ('st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns')})
        after.st_mtime_ns += 1
        with patch.object(r.os, 'fstat', side_effect=[before,after]):
            with self.assertRaisesRegex(ValueError, 'changing.*changed during read'):
                r.protected_hash(path)

    def test_missing_stream_at_boundary_fails(self):
        rows = self.rows()
        rows[-1]['streams']['node']['recorded'] = False
        self.assertFalse(r.summarize(rows)['streams']['node']['completeness_pass'])

    def test_five_separated_missing_slots_allowed(self):
        rows = self.rows()
        for k in (20,40,60,80,100): rows[k] = dict(rows[k], missing=True)
        self.assertEqual(r.summarize(rows)['streams']['node']['on_time'],572)
        self.assertTrue(r.summarize(rows)['streams']['node']['completeness_pass'])

    def test_six_missing_fails(self):
        rows = self.rows()
        for k in (20,40,60,80,100,120): rows[k] = dict(rows[k], missing=True)
        self.assertFalse(r.summarize(rows)['streams']['node']['completeness_pass'])

    def test_adjacent_missing_fails_gap(self):
        rows = self.rows(); rows[20]['missing'] = rows[21]['missing'] = True
        self.assertEqual(r.summarize(rows)['streams']['node']['max_gap'],900)
        self.assertFalse(r.summarize(rows)['streams']['node']['completeness_pass'])

    def test_boundary_missing_fails(self):
        for k in (0,576):
            rows = self.rows(); rows[k]['missing'] = True
            self.assertFalse(r.summarize(rows)['streams']['node']['completeness_pass'])

    def test_failed_client_response_is_recorded_evidence(self):
        rows = self.rows(); rows[10]['streams']['client4']['complete'] = False
        self.assertEqual(r.summarize(rows)['streams']['client4']['on_time'],577)
        self.assertIn('requires review',r.summarize(rows)['acceptance'])

    def test_late_and_future_records_not_on_time(self):
        rows = self.rows()
        rows[5]['streams']['node']['start_monotonic'] += 61
        rows[10]['streams']['node']['start_monotonic'] -= 1
        self.assertEqual(r.summarize(rows)['streams']['node']['on_time'],575)

    def test_duplicate_remote_record_rejected(self):
        with self.assertRaises(ValueError): r.parse_remote('{"key":"complete","data":true}\n'*2)

    def test_partial_subprocess_failure_is_preserved(self):
        value = r.stream_record(self.root,self.root,'failed',
              [sys.executable,'-c','import sys;print("before failure",flush=True);sys.stderr.write("reason");sys.exit(7)'],None,2,1024)
        self.assertEqual(value['returncode'],7)
        self.assertIn('before failure',(self.root/'failed.stdout').read_text())
        self.assertEqual((self.root/'failed.stderr').read_text(),'reason')
        self.assertTrue((self.root/'failed.result.json').is_file())

    def test_timeout_retains_partial_output(self):
        value = r.stream_record(self.root,self.root,'timeout',
              [sys.executable,'-c','import time;print("partial",flush=True);time.sleep(30)'],None,.15,1024)
        self.assertIn('deadline',value['error'])
        self.assertIn('partial',(self.root/'timeout.stdout').read_text())

    def test_output_limit_preserves_bounded_prefix(self):
        value = r.stream_record(self.root,self.root,'limit',[sys.executable,'-c','print("x"*8192)'],None,2,100)
        self.assertIn('bound',value['error'])
        self.assertEqual((self.root/'limit.stdout').stat().st_size,100)

    def test_one_use_launch(self):
        r.write_new(self.root/'already.launch.json',{})
        with patch.object(h.subprocess,'Popen',side_effect=AssertionError('must not launch')):
            with self.assertRaises(FileExistsError):
                r.stream_record(self.root,self.root,'already',[sys.executable,'-c','pass'],None,2,100)

    def test_sink_interruption_preserves_and_kills(self):
        seen=[]
        def sink(stream,raw):
            seen.append(raw); raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            h.bounded([sys.executable,'-c','import time;print("partial",flush=True);time.sleep(30)'],timeout=2,sink=sink)
        self.assertIn(b'partial',b''.join(seen))

    def test_private_output_rejects_links_and_public_directory(self):
        other = self.root/'public'; other.mkdir(mode=0o755)
        with self.assertRaises(ValueError): r.private(other)
        link=self.root/'link';link.symlink_to(self.root,target_is_directory=True)
        with self.assertRaises(ValueError): r.private(link)

    def test_regular_client_probe_does_not_send_admin_request(self):
        class Socket:
            sent=[]
            def __enter__(self):return self
            def __exit__(self,*a):pass
            def settimeout(self,*a):pass
            def connect(self,*a):pass
            def send(self,raw):self.sent.append(raw)
            def recv(self,*a):return b'reply'
            def getsockname(self):return ('192.0.2.3',45000)
        sock=Socket()
        with patch.object(c.socket,'socket',return_value=sock),patch.object(c,'ntp_response',return_value={'leap':0}):
            c.client_ntp('192.0.2.5',administrative=False)
        self.assertEqual(len(sock.sent),1)

    def test_manifest_tamper_rejected(self):
        (self.root/'manifest.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'manifest approval'):
            r.check(self.root,'0'*64)

    def test_non_executable_manifest_rejected(self):
        raw=r.encoded({'execution_ready':False});(self.root/'manifest.json').write_bytes(raw)
        with self.assertRaisesRegex(ValueError,'not executable'):r.check(self.root,r.digest(raw))


    def test_unresolved_entry_cannot_start(self):
        import time
        now=time.time()
        r.write_new(self.root/'execution.json',{'manifest_sha256':'approved','epoch':now})
        r.write_new(self.root/'entry.json',{'manifest_sha256':'approved','epoch':now})
        raw=(self.root/'entry.json').read_bytes()
        grant=self.root/'grant.json'
        r.write_new(grant,{'manifest_sha256':'approved','entry_sha256':r.digest(raw),'checks':{}})
        spec={'not_after_epoch':now+100,'controller_hostname':r.socket.gethostname(),
              'windows':{'executable':sys.executable},'boundary_commands':[]}
        with patch.object(r,'check',return_value=spec),patch.object(r,'fingerprint'), \
             patch.object(r,'parallel_capture',side_effect=AssertionError('no contact')):
            with self.assertRaisesRegex(ValueError,'unresolved entry'):
                r.execute(self.root,self.root,'approved','observe',grant)
        self.assertFalse((self.root/'start.json').exists())

    def test_rrd_membership_requires_available_inventory(self):
        with self.assertRaises(ValueError):
            r.rrd_membership({'collection':{'rrd':{'j2':{'cpu':{'finding':'missing'}}}}})
        self.assertEqual(r.rrd_membership({'collection':{'rrd':{'j2':{'cpu':{'files':[{'filename':'b'},{'filename':'a'}]}}}}}),
                         {'j2/cpu':['a','b']})


if __name__ == '__main__': unittest.main()
