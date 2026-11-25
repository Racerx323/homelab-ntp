#!/usr/bin/python3
"""Offline contracts for the actual bounded observation executor; no target contact."""
import importlib.util
import copy
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
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
readiness = load(ROOT/'scripts/inspect-observer-readiness.py')
hosted = load(ROOT/'scripts/host-service-observation.py')


class Observation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        shutil.copy2(ROOT/'scripts/run-production-inspection.py', self.root/'helper.py')

    def rows(self):
        return [{'due_monotonic': k*300, 'streams': {s: {'recorded': True,
                 'start_monotonic': k*300, 'complete': True} for s in r.STREAMS}}
                for k in range(r.SLOTS)]

    def test_hosted_gateway_closed_samples_and_real_cli_rejection(self):
        self.assertTrue(hosted.sample('entry'))
        self.assertTrue(hosted.sample('slot-576'))
        self.assertFalse(hosted.sample('slot-001'))
        for value in ('', 'sh', 'entry;id', 'entry\n', 'slot-577', 'slot--01', 'slot-000 extra'):
            with self.assertRaises(ValueError): hosted.sample(value)
        env = dict(os.environ, SSH_ORIGINAL_COMMAND='sh -c id')
        result = subprocess.run([sys.executable, '-I', '-B', str(ROOT/'scripts/host-service-observation.py'),
                                 'node', '--bundle', str(self.root), '--sha256', 'irrelevant'],
                                env=env, capture_output=True, text=True, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('named sample required', result.stderr)
        self.assertNotIn('sudo:', result.stderr)

    def test_dedicated_key_line_and_atomic_preservation(self):
        subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(self.root/'identity')],
                       check=True, timeout=5)
        spec = {'gateway_path': '/usr/local/libexec/obs09-test.py',
                'deployment_root': '/var/lib/ntp-observation/test', 'operation': 'obs09-test'}
        line = hosted.key_line((self.root/'identity.pub').read_text(), spec, 'a'*64)
        self.assertTrue(line.startswith(b'restrict,from="10.1.3.83",command="'))
        self.assertIn(b' node --bundle ', line)
        self.assertNotIn(b'permitopen', line)
        with self.assertRaises(ValueError): hosted.key_line('ssh-ed25519 not-a-key', spec, 'a'*64)
        target = self.root/'authorized_keys'; target.write_bytes(b'existing key\n'); target.chmod(0o600)
        before, meta = hosted.key_file(target, os.getuid())
        hosted.replace_key_file(target, before, before+line, meta)
        self.assertEqual(target.read_bytes(), before+line)
        with self.assertRaisesRegex(ValueError, 'concurrent key edit'):
            hosted.replace_key_file(target, before, b'do not publish', meta)
        self.assertEqual(target.read_bytes(), before+line)
        current, meta = hosted.key_file(target, os.getuid())
        hosted.replace_key_file(target, current, before, meta)
        self.assertEqual(target.read_bytes(), before)
        self.assertFalse(target.with_name('authorized_keys.obs09-new').exists())

    def test_owned_authorization_revokes_without_losing_unrelated_new_keys(self):
        subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(self.root/'identity')],
                       check=True, timeout=5)
        shutil.copyfile(self.root/'identity.pub', self.root/'public.pub')
        directory = self.root/'.ssh'; directory.mkdir(mode=0o700)
        path = directory/'authorized_keys'; original = b'original-key\n'
        path.write_bytes(original); path.chmod(0o600)
        account = types.SimpleNamespace(pw_dir=str(self.root), pw_uid=os.getuid())
        spec = {'gateway_path': '/usr/local/libexec/obs09-test.py',
                'deployment_root': '/var/lib/ntp-observation/test', 'operation': 'obs09-test'}
        with patch.object(hosted.pwd, 'getpwnam', return_value=account):
            hosted.authorize(self.root, spec, 'a'*64, r)
            with self.assertRaisesRegex(ValueError, 'already consumed'):
                hosted.authorize(self.root, spec, 'a'*64, r)
            path.write_bytes(path.read_bytes()+b'unrelated-new-key\n')
            hosted.authorize(self.root, spec, 'a'*64, r, remove=True)
            hosted.authorize(self.root, spec, 'a'*64, r, remove=True)
        self.assertEqual(path.read_bytes(), original+b'unrelated-new-key\n')
        self.assertTrue((self.root/'revoked.json').exists())

    def test_boundary_time_binding_and_unavailable_boundary(self):
        value = {'manifest_sha256': 'seal', 'complete': True,
                 'started_epoch': 100, 'finished_epoch': 120}
        hosted.validate_boundary(value, 'seal', 200)
        hosted.validate_boundary(value, 'seal', 90, finish=True)
        for other, endpoint in ((dict(value, complete=False), 200),
                                (dict(value, manifest_sha256='other'), 200),
                                (value, 2000), (value, 110)):
            with self.assertRaises(ValueError): hosted.validate_boundary(other, 'seal', endpoint)

    def test_hosted_admission_uses_current_boot_then_rejects_transition_and_expiry(self):
        boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        value = {'manifest_sha256': 'seal', 'role': 'node', 'epoch': 100, 'deadline': 180100, 'boot': boot}
        path = self.root/'admission.json'; path.write_text(json.dumps(value))
        with patch.object(hosted, 'trusted'):
            hosted.admission(self.root, 'seal', 'node', 200)
            for change in ({'boot': 'previous-operation'}, {'manifest_sha256': 'other'},
                           {'deadline': 180101}, {'deadline': 150}, {'role': 'master'}):
                path.write_text(json.dumps(dict(value, **change)))
                with self.assertRaises(ValueError): hosted.admission(self.root, 'seal', 'node', 200)

    def test_hosted_unit_has_no_restart_and_independent_bounds(self):
        unit = (ROOT/'templates/obs09-master.service.in').read_text()
        for control in ('Restart=no', 'RuntimeMaxSec=49h', 'KillMode=control-group',
                        'TimeoutStopSec=15s', 'MemoryMax=1G', ' retire-key ', 'UMask=0077'):
            self.assertIn(control, unit)
        self.assertNotIn('WantedBy=', unit)

    def test_hosted_review_wait_does_not_invent_grant_or_extend_deadline(self):
        with patch.object(hosted.time, 'monotonic', return_value=200):
            with self.assertRaisesRegex(ValueError, 'review deadline'):
                hosted.wait_for_grant(self.root, 199)
        self.assertFalse((self.root/'grant.json').exists())
        (self.root/'grant.json').write_text('{}')
        hosted.wait_for_grant(self.root, 999999999999)

    def test_hosted_run_uses_same_process_for_entry_and_observation_and_retires_key(self):
        import time
        root = self.root; bundle = root/'inputs'; bundle.mkdir(); (root/'results').mkdir()
        identity = root/'identity'; identity.write_text('temporary test credential')
        spec = {'master': {'hostname': r.socket.gethostname()}, 'identity_file': str(identity)}
        boundary_raw = r.encoded({'complete': True, 'manifest_sha256': 'seal',
                                  'started_epoch': time.time()-10, 'finished_epoch': time.time()-5})
        (root/'start-boundary.json').write_bytes(boundary_raw)
        (root/'grant.json').write_text(json.dumps({'start_boundary_sha256': r.digest(boundary_raw)}))
        calls = []
        def execute(bundle, output, expected, phase, grant): calls.append(phase)
        observer = types.SimpleNamespace(write_new=r.write_new, execute=execute, digest=r.digest)
        argv = ['hosted', 'run', '--bundle', str(bundle), '--sha256', 'seal']
        with patch.object(sys, 'argv', argv), patch.object(hosted.os, 'geteuid', return_value=0), \
             patch.object(hosted, 'load', return_value=(observer, spec)), patch.object(hosted, 'admission'), \
             patch.object(hosted, 'trusted'), patch('signal.signal'):
            hosted.main()
            with self.assertRaises(FileExistsError): hosted.main()
        self.assertEqual(calls, ['entry', 'observe'])
        self.assertFalse(identity.exists())

    def test_hosted_entry_failure_retains_evidence_and_retires_key_without_observing(self):
        root = self.root; bundle = root/'inputs'; bundle.mkdir(); (root/'results').mkdir()
        identity = root/'identity'; identity.write_text('temporary test credential')
        spec = {'master': {'hostname': r.socket.gethostname()}, 'identity_file': str(identity)}
        def execute(bundle, output, expected, phase, grant):
            self.assertEqual(phase, 'entry')
            r.write_new(output/'execution.json', {'partial': True})
            raise ValueError('actual entry failed')
        observer = types.SimpleNamespace(write_new=r.write_new, execute=execute)
        argv = ['hosted', 'run', '--bundle', str(bundle), '--sha256', 'seal']
        with patch.object(sys, 'argv', argv), patch.object(hosted.os, 'geteuid', return_value=0), \
             patch.object(hosted, 'load', return_value=(observer, spec)), patch.object(hosted, 'admission'), \
             patch.object(hosted, 'trusted'), patch('signal.signal'):
            with self.assertRaisesRegex(ValueError, 'actual entry failed'): hosted.main()
        self.assertFalse(identity.exists())
        self.assertTrue((root/'results/execution.json').exists())
        self.assertEqual(json.loads((root/'results/hosted-error.json').read_text())['error'], 'actual entry failed')

    def test_hosted_named_sample_consumes_receipt_before_collecting(self):
        requests = self.root/'requests'; requests.mkdir()
        for name in ('helper.py', 'passive.py', 'measure.py', 'checks.py', 'munin.py'):
            (self.root/name).write_text('# test')
        bundle = self.root/'inputs'; bundle.mkdir()
        for name in ('helper.py', 'passive.py', 'measure.py', 'checks.py', 'munin.py'):
            shutil.copy2(self.root/name, bundle/name)
        spec = {'node': {'hostname': r.socket.gethostname()}}
        observer = types.SimpleNamespace(write_new=r.write_new, remote=lambda *args: None)
        argv = ['hosted', 'node-root', '--bundle', str(bundle), '--sha256', 'seal', '--sample', 'entry']
        with patch.object(sys, 'argv', argv), patch.object(hosted.os, 'geteuid', return_value=0), \
             patch.object(hosted, 'load', return_value=(observer, spec)), patch.object(hosted, 'admission'):
            hosted.main()
            with self.assertRaises(FileExistsError): hosted.main()
        self.assertEqual(json.loads((requests/'entry.json').read_text())['label'], 'entry')

    def test_bound_client_uses_real_loopback_source_and_rejects_unavailable(self):
        import socket
        import struct
        import threading
        import time
        real_socket = socket.socket
        with real_socket(socket.AF_INET, socket.SOCK_DGRAM) as server:
            server.bind(('127.0.0.1', 0)); server.settimeout(5)
            port = server.getsockname()[1]; observed = []
            def respond():
                packet, peer = server.recvfrom(512); observed.append(peer[0])
                response = bytearray(48); response[0] = 0x24; response[1] = 1
                response[12:16] = b'PPS\0'; response[24:32] = packet[40:48]
                response[32:40] = struct.pack('!II', int(time.time())+2208988800, 1)
                response[40:48] = response[32:40]; server.sendto(response, peer)
            thread = threading.Thread(target=respond); thread.start()
            class LocalPort(real_socket):
                def connect(self, destination):
                    self.assert_destination = destination
                    return super().connect((destination[0], port))
            try:
                with patch.object(c.socket, 'socket', LocalPort):
                    result = c.client_ntp('127.0.0.1', source='127.0.0.2', administrative=False)
                    with self.assertRaises(OSError):
                        c.client_ntp('127.0.0.1', source='192.0.2.199', administrative=False)
            finally: thread.join(6)
        self.assertEqual(observed, ['127.0.0.2'])
        self.assertEqual(result['local_address'], '127.0.0.2')
        with self.assertRaisesRegex(ValueError, 'family mismatch'):
            c.client_ntp('127.0.0.1', source='::1')

    def test_hosted_capture_local_master_and_fixed_node_command(self):
        for name in ('passive.py', 'measure.py', 'checks.py', 'munin.py', 'observer.py'):
            (self.root/name).write_text('# test input')
        spec = {'hosting': 'master', 'identity_file': '/owned/identity', 'ssh_options': ['BatchMode=yes'],
                'probe_sources': {'client4': '10.1.3.83'},
                'node': {'target': 'ama@10.1.0.51', 'host_key_alias': '10.1.0.137'}}
        result = {'returncode': 0, 'stdout': '{"key":"complete","data":true}\n', 'error': None}
        with patch.object(r, 'stream_record', return_value=result) as stream:
            r.capture(self.root, spec, self.root, 'entry', 'node', True, 0)
            args = stream.call_args.args
            self.assertIsNone(args[4])
            self.assertEqual(args[3][-1], 'entry')
            self.assertIn('-n', args[3]); self.assertIn('10.1.3.83', args[3])
            r.capture(self.root, spec, self.root, 'entry', 'master', True, 0)
            self.assertEqual(stream.call_args.args[3], ['/usr/bin/python3', '-I', '-B', '-'])

    def test_controller_readiness_scope_cannot_observe(self):
        with patch.object(r, 'check', return_value={'purpose': 'controller-readiness'}), \
             patch.object(r, 'fingerprint', side_effect=AssertionError('no authentication')):
            for phase in ('entry', 'observe', 'inspect-master'):
                with self.assertRaisesRegex(ValueError, 'outside sealed scope'):
                    r.execute(self.root, self.root, 'approved', phase, None)

    def test_actual_readiness_payload_imports_before_wrong_host_rejection(self):
        shutil.copy2(ROOT/'scripts/inspect-observer-readiness.py', self.root/'controller-readiness.py')
        program = r.readiness_payload(self.root, 'master', 'deliberately-wrong-host.invalid')
        result = subprocess.run([sys.executable, '-I', '-B', '-'], input=program,
                                text=True, capture_output=True, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('root/host mismatch', result.stderr)
        self.assertNotIn('NameError', result.stderr)
        rows = r.parse_remote(result.stdout)
        self.assertEqual(set(rows), {'identity'})
        self.assertEqual(rows['identity']['hostname'], r.socket.gethostname())

    def test_controller_readiness_runs_two_reads_once_and_retains_status(self):
        import time
        output = self.root/'result'; output.mkdir(mode=0o700)
        (self.root/'controller-readiness.py').write_text('# sealed input')
        spec = {'purpose': 'controller-readiness', 'not_after_epoch': time.time()+100,
                'controller_hostname': r.socket.gethostname(), 'boundary_commands': [],
                'master': {'hostname': 'J1-SVMF'}, 'node': {'hostname': 'j2-svntp1'}}
        result = {'stdout': json.dumps({'key': 'complete', 'data': True})+'\n',
                  'returncode': 0, 'error': None}
        with patch.object(r, 'check', return_value=spec), patch.object(r, 'fingerprint'), \
             patch.object(r, 'target_argv', return_value=['approved-read']), \
             patch.object(r, 'stream_record', return_value=result) as stream:
            r.execute(self.root, output, 'approved', 'inspect-controller', None)
            self.assertEqual(stream.call_count, 2)
            with self.assertRaisesRegex(ValueError, 'empty output'):
                r.execute(self.root, output, 'approved', 'inspect-controller', None)
            self.assertEqual(stream.call_count, 2)
        self.assertIs(json.loads((output/'inspection.json').read_text())['accepted'], False)
        self.assertFalse((output/'start.json').exists())

    def test_readiness_public_metadata_never_reads_private_key(self):
        import base64
        kind = b'ssh-ed25519'
        raw = len(kind).to_bytes(4, 'big')+kind+b'public test bytes'
        public = 'ssh-ed25519 '+base64.b64encode(raw).decode()
        directory = self.root/'.ssh'; directory.mkdir()
        (directory/'id_ed25519').mkdir()  # Opening as a file would fail.
        (directory/'id_ed25519.pub').write_text(public+' sensitive-comment\n')
        account = types.SimpleNamespace(pw_dir=str(self.root), pw_uid=os.getuid())
        with patch.object(readiness.pwd, 'getpwnam', return_value=account):
            result = readiness.ssh_metadata('pi')
        self.assertNotIn('sensitive-comment', json.dumps(result))
        keys = result['entries']['id_ed25519.pub']['public_keys']
        restricted = readiness.public_fingerprints('command="secret command",restrict '+public+' comment')
        self.assertEqual(keys[0]['fingerprint'], restricted[0]['fingerprint'])
        self.assertTrue(restricted[0]['has_options'])
        self.assertNotIn('secret', json.dumps(restricted))
        (directory/'linked.pub').symlink_to(directory/'id_ed25519.pub')
        with self.assertRaisesRegex(ValueError, 'indirect'):
            readiness.read_public(directory/'linked.pub')

    def test_readiness_source_binding_uses_real_local_sockets_without_send(self):
        with patch.object(readiness, 'SOURCES', ('127.0.0.1', '::1')):
            rows = readiness.bind_sources()
        self.assertEqual(rows, [{'expected_source': '127.0.0.1', 'actual_source': '127.0.0.1'},
                                {'expected_source': '::1', 'actual_source': '::1'}])

    def test_readiness_source_binding_preserves_failure(self):
        with patch.object(readiness.socket, 'socket', side_effect=OSError('source unavailable')):
            rows = readiness.bind_sources()
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(x['error'] == 'source unavailable' for x in rows))

    def test_readiness_admits_current_boot_and_rejects_mid_capture_change(self):
        helper = types.SimpleNamespace(bounded=lambda *a, **kw: {'returncode': 0, 'stdout': '', 'stderr': ''})
        for after, fails in [('fresh-boot', False), ('changed-boot', True)]:
            output = io.StringIO()
            with patch.object(readiness.socket, 'gethostname', return_value='j2-svntp1'), \
                 patch.object(readiness.os, 'geteuid', return_value=0), \
                 patch.object(readiness.Path, 'read_text', side_effect=['fresh-boot', after]), \
                 patch.object(readiness, 'ssh_metadata', return_value={}), \
                 patch.object(readiness, 'read_public', return_value=''), \
                 contextlib.redirect_stdout(output):
                if fails:
                    with self.assertRaisesRegex(ValueError, 'boot/identity changed'):
                        readiness.collect('node', 'j2-svntp1', helper)
                else:
                    readiness.collect('node', 'j2-svntp1', helper)
            rows = r.parse_remote(output.getvalue())
            self.assertEqual(rows['identity']['boot'], 'fresh-boot')
            self.assertEqual(rows.get('complete', False), not fails)

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

    def test_command_names_do_not_collide_with_observation_records(self):
        output = io.StringIO()
        commands = {name: [sys.executable, '-c', 'print("local output")']
                    for name in ('capacity', 'identity', 'complete')}
        with contextlib.redirect_stdout(output):
            r.emit('capacity', {'bytes': 'root', 'inodes': 'root'})
            r.emit('identity', {'host': 'local'})
            r.emit_command_records(commands, lambda argv: subprocess.check_output(argv, text=True))
            r.emit('complete', True)
        parsed = r.parse_remote(output.getvalue())
        self.assertEqual(parsed['capacity'], {'bytes': 'root', 'inodes': 'root'})
        for name in commands:
            self.assertEqual(parsed['passive_commands.' + name], 'local output\n')
        self.assertIs(parsed['complete'], True)

    def test_command_failure_preserves_completed_records(self):
        output = io.StringIO()
        commands = {'capacity': [sys.executable, '-c', 'print("local output")'],
                    'later': [sys.executable, '-c', 'raise SystemExit(7)']}
        with contextlib.redirect_stdout(output), self.assertRaises(subprocess.CalledProcessError):
            r.emit_command_records(commands, lambda argv: subprocess.check_output(argv, text=True))
        self.assertEqual(r.parse_remote(output.getvalue()), {'passive_commands.capacity': 'local output\n'})

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

    def test_master_inspection_cannot_start_observation(self):
        with patch.object(r, 'check', return_value={'purpose':'master-selection'}), \
             patch.object(r, 'fingerprint', side_effect=AssertionError('scope first')):
            for phase in ('entry','observe'):
                with self.assertRaisesRegex(ValueError, 'outside sealed scope'):
                    r.execute(self.root,self.root,'approved',phase,None)

    def test_inspection_captures_only_master_once_without_entry(self):
        import time
        output = self.root/'output'; output.mkdir(mode=0o700)
        spec = {'purpose':'master-selection', 'not_after_epoch':time.time()+100,
                'controller_hostname':r.socket.gethostname(),'boundary_commands':[]}
        row = {'complete':True,'data':{'config':{'selected':{}}}}
        with patch.object(r,'check',return_value=spec), patch.object(r,'fingerprint'), \
             patch.object(r,'capture',return_value=row) as capture, \
             patch.object(r,'boundary',side_effect=AssertionError('no boundary probes')):
            r.execute(self.root,output,'approved','inspect-master',None)
            self.assertEqual(capture.call_count,1)
            self.assertEqual(capture.call_args.args[4:6],('master',False))
            with self.assertRaisesRegex(ValueError,'empty output'):
                r.execute(self.root,output,'approved','inspect-master',None)
            self.assertEqual(capture.call_count,1)
        self.assertFalse((output/'entry.json').exists())
        self.assertFalse((output/'start.json').exists())
        self.assertIs(json.loads((output/'inspection.json').read_text())['entry_accepted'],False)

    def test_rrd_membership_requires_available_inventory(self):
        graph = {'files': [{'filename': 'b'}, {'filename': 'a'}],
                 'missing': False, 'missing_expected_files': []}
        data = {'collection': {'rrd': {'aligned_end': 1800, 'resolution': 300,
                'data': {'j2': {'cpu': graph}}}}}
        self.assertEqual(r.rrd_membership(data), {'j2/cpu': ['a', 'b']})
        for envelope in ({}, {'data': {}}, {'data': {'j2': 1}},
                         {'data': {'j2': {'cpu': {'files': []}}}},
                         {'data': {'j2': {'cpu': dict(graph, missing_expected_files=['c'])}}},
                         {'data': {'j2': {'cpu': {'files': [{'filename': 'a'}]*2}}}}):
            with self.subTest(envelope=envelope), self.assertRaises(ValueError):
                r.rrd_membership({'collection': {'rrd': envelope}})

    @unittest.skipUnless(os.environ.get('OBS09_NATIVE_IMAGE'), 'optional installed Munin parser')
    def test_native_storable_multigraph_selection(self):
        # Native parser produces the tree: do not hand-build its nested hash.
        producer = r"""
use Munin::Master::Utils; use Storable qw(nstore_fd);
my @lines = ("[j2;j2]", "cpu.user.label user", "cpu.user.state ok",
             "diskstats_iops.mmcblk0.reads.label reads",
             "diskstats_iops.mmcblk0.reads.state ok");
my $d = Munin::Master::Utils::munin_parse_config(\@lines); nstore_fd($d, \*STDOUT);
"""
        program = """
import json, subprocess
p = json.loads(input())
raw = subprocess.check_output(['perl','-e',p['producer']])
for mode in ('config','limits'):
 result = json.loads(subprocess.check_output(['perl','-e',p['decoder'],mode,
     json.dumps([['j2','cpu'],['j2','diskstats_iops.mmcblk0'],['j2','absent']])],input=raw))
 field = 'label' if mode == 'config' else 'state'
 assert result['j2/cpu']['user'][field] == ('user' if mode == 'config' else 'ok')
 assert result['j2/diskstats_iops.mmcblk0']['reads'][field] == ('reads' if mode == 'config' else 'ok')
 assert result['j2/absent'] == {'missing':True}
print('native Storable config/limits: flat and multigraph selection passed')
"""
        command = ['podman','run','--rm','--pull=never','--network=none','--read-only',
                   '--cap-drop=all','--security-opt=no-new-privileges','-i',
                   '--entrypoint','/usr/bin/python3',os.environ['OBS09_NATIVE_IMAGE'],'-c',program]
        result = subprocess.run(command,input=json.dumps(dict(producer=producer,decoder=r.LIMITS_DECODER)),
                                text=True,capture_output=True,timeout=60)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)


@unittest.skipUnless(os.environ.get('OBS09_RETAINED_RUN'), 'optional private retained captures')
class RetainedCaptures(unittest.TestCase):
    """Exercise actual predicates without launching commands or changing old records."""
    @classmethod
    def setUpClass(cls):
        cls.capture_dir = Path(os.environ['OBS09_RETAINED_RUN'])
        cls.bundle = Path(os.environ['OBS09_RETAINED_BUNDLE'])
        cls.spec = json.loads((cls.bundle/'spec.json').read_text())
        cls.rows = {}
        for role in r.STREAMS:
            meta = json.loads((cls.capture_dir/('entry-'+role+'.json')).read_text())
            raw = (cls.capture_dir/('entry-'+role+'.stdout')).read_text()
            meta['data'] = r.parse_remote(raw) if role in ('node','master') else json.loads(raw)
            cls.rows[role] = meta
        cls.reference = {role: row['data'] for role, row in cls.rows.items()}

    def test_complete_entry_and_continuity_schemas(self):
        r.require_entry(self.rows, self.spec)
        r.require_continuity(self.rows, self.reference)

    def test_entry_rejects_missing_stream_check_graph_and_inventory(self):
        for mutate in (lambda x: x.pop('client6'),
                       lambda x: x['node']['data']['time']['checks'].pop('finite'),
                       lambda x: x['node']['data']['time']['checks'].update(offset=False),
                       lambda x: x['master']['data']['collection']['rrd']['data'].pop('J1-SVMF')):
            rows = copy.deepcopy(self.rows); mutate(rows)
            with self.assertRaises(ValueError): r.require_entry(rows, self.spec)

    def test_continuity_rejects_each_changed_input(self):
        def service(rows):
            rows['node']['data']['services']['timeservice.service']['stdout'] += '\nInvocationID=changed\n'
        for mutate in (lambda x: x['node']['data']['identity'].update(boot='changed'),
                       lambda x: x['master']['data']['hashes'].update(extra='changed'),
                       lambda x: x['master']['data']['config']['selected'].update(extra={}),
                       lambda x: x['master']['data']['collection']['rrd']['data'].pop('J1-SVMF'),
                       lambda x: x['client4']['data'].update(local_address='changed'), service,
                       lambda x: x['node'].update(returncode=255),
                       lambda x: x['master'].update(complete=False)):
            rows = copy.deepcopy(self.rows); mutate(rows)
            with self.assertRaises(ValueError): r.require_continuity(rows, self.reference)

    def test_start_predicates_without_writing_grant_or_start(self):
        receipt = json.loads((self.capture_dir/'execution.json').read_text())
        now = max(row['finished_epoch'] for row in self.rows.values()) + 1
        expected = receipt['manifest_sha256']
        entry = {'epoch': now, 'manifest_sha256': expected, 'streams': self.rows}
        raw = r.encoded(entry)
        names = ('identity_configuration wifi_hardware native_time master_fields_freshness_limits '
                 'jobs_leap_deadline client_dns_discovery webmin_both_families controller_capacity_awake '
                 'journal_dispositions obs02_storage_floors thermal_trip_policy').split()
        # Only predicate mechanics: these booleans are not an entry acceptance or authorization.
        grant = dict(manifest_sha256=expected, entry_sha256=r.digest(raw), operator='Aaron',
                     epoch=now, checks=dict.fromkeys(names, True),
                     obs05_due_epoch=now+1000, obs05_followup_epoch=now+87400)
        r.require_start_grant(grant, entry, receipt, expected, raw, now)
        for name in names:
            bad = copy.deepcopy(grant); bad['checks'][name] = False
            with self.assertRaisesRegex(ValueError, 'unresolved entry'):
                r.require_start_grant(bad, entry, receipt, expected, raw, now)
        for changes in ({'entry_sha256': 'changed'}, {'manifest_sha256': 'changed'},
                        {'operator': 'other'}, {'epoch': now+1}, {'obs05_due_epoch': now},
                        {'obs05_followup_epoch': now}, {'obs05_due_epoch': float('nan')}):
            with self.assertRaises(ValueError):
                r.require_start_grant(dict(grant, **changes), entry, receipt, expected, raw, now)
        with self.assertRaisesRegex(ValueError, 'stale'):
            r.require_start_grant(grant, entry, receipt, expected, raw, now+1801)

    def test_all_boundary_predicates_from_retained_results(self):
        def retained(bundle, output, name, *args):
            result = json.loads((self.capture_dir/(name+'.result.json')).read_text())
            result['stdout'] = (self.capture_dir/(name+'.stdout')).read_text(errors='replace')
            return result
        with patch.object(r, 'stream_record', side_effect=retained):
            r.boundary(self.bundle, self.spec, self.capture_dir, 'entry')


if __name__ == '__main__': unittest.main()
