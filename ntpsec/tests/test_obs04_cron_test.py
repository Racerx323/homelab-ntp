#!/usr/bin/python3
"""Offline one-use cron release, containment, publication and message checks."""
import base64
import datetime
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import tarfile
import tempfile
import time
import types
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]


def load(path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


r = load(ROOT/'scripts/run-obs04-cron-test.py')
w = load(ROOT/'scripts/obs04-cron-test.py')
r.h = w.h = load(ROOT/'scripts/run-production-inspection.py')
RUNTIME = w.runtime


class Controls(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.fstat = os.fstat
        self.diagnostic = b"Error: unknown option '--obs04-controlled-failure'.\nUsage: needrestart.sh [OPTION]\n"
        self.body = b'!'
        (self.root/'body.txt').write_bytes(self.body)
        (self.root/'diagnostic.txt').write_bytes(self.diagnostic)
        now = time.time()
        self.spec = {'schema': 1, 'purpose': 'obs04-controlled-cron-failure',
            'operation_id': 'obs04-cron-failure-test', 'directory': str(self.root/'obs04-cron-failure-test'),
            'prepared_epoch': now, 'expires_epoch': now+86400,
            'schedule_rule': 'first whole minute strictly after install_now+180s',
            'boot_id': 'a'*36, 'fixed_units': {n: {'MainPID': '42', 'InvocationID': 'x', 'NRestarts': '0'}
                for n in ('cron.service', 'timeservice.service')},
            'protected_files': dict.fromkeys(r.PROTECTED, 'a'*64),
            'input_hashes': dict.fromkeys(('worker.py', 'helper.py', 'body.txt', 'diagnostic.txt'), 'b'*64),
            'body_sha256': r.h.sha(self.body), 'diagnostic_sha256': r.h.sha(self.diagnostic), 'wrapper_base64': base64.b64encode(
                b'/usr/bin/flock -n /run/lock/needrestart-check.lock /usr/local/sbin/needrestart.sh').decode(),
            'members': {}}
        self.runtime = {'due_epoch': now-1, 'expires_run_epoch': now+60,
                        'cron_sha256': w.h.sha(b'approved cron'), 'spec': self.spec}
        cron = self.root/'test-cron'; cron.write_bytes(b'approved cron'); cron.chmod(0o644)
        self.patch(w, 'CRON', cron)
        self.patch(w, 'runtime', lambda spec: (self.root, self.runtime))
        self.patch(w, 'preflight', lambda spec: {'cron.service': {'MainPID': '42'}})
        self.patch(w, 'cron_ancestry', lambda pid: [{'pid': 1, 'ppid': pid}])
        # Let the real file logic run as the controller's unprivileged user.
        self.patch(w, 'regular', lambda path, mode=0o600: w.h.file_record(path))
        self.env = patch.dict(os.environ, HOME='/root', LOGNAME='root'); self.env.start()
        self.addCleanup(self.env.stop)

    def patch(self, obj, name, value):
        p = patch.object(obj, name, value); p.start(); self.addCleanup(p.stop)

    def output_stat(self, fd):
        return types.SimpleNamespace(st_mode=stat.S_IFREG, st_nlink=0, st_size=0, st_uid=0) if fd == 1 else self.fstat(fd)

    def gate(self, response=None, writer=None):
        response = response or {'returncode': 2, 'stdout': self.diagnostic.decode(), 'stderr': ''}
        with patch.object(w.h, 'bounded', return_value=response) as run, \
                patch.object(w.os, 'fstat', side_effect=self.output_stat), \
                patch.object(w.os, 'lseek', return_value=0), \
                patch.object(w.os, 'write', side_effect=writer or (lambda fd, raw: len(raw))) as output:
            result = w.gate(self.spec)
            return result, run.call_count, output.call_count

    def test_release_once_and_second_entry_is_quiet(self):
        self.assertEqual(self.gate(), (2, 1, 1))
        self.assertTrue(json.loads((self.root/'gate.json').read_text())['released'])
        self.assertEqual(self.gate(), (0, 0, 0))

    def test_wrong_status_or_output_or_stderr_never_releases(self):
        response = {'returncode': 0, 'stdout': 'unapproved', 'stderr': 'unexpected'}
        self.assertEqual(self.gate(response), (0, 1, 0))
        self.assertFalse(json.loads((self.root/'gate.json').read_text())['released'])
        self.assertEqual(self.gate(), (0, 0, 0))

    def test_body_drift_never_releases(self):
        (self.root/'body.txt').write_bytes(b'foreign')
        self.assertEqual(self.gate(), (0, 1, 0))

    def test_manual_invocation_fails_cron_ancestry_before_reporter(self):
        with patch.object(w, 'cron_ancestry', side_effect=ValueError('manual')):
            self.assertEqual(self.gate(), (0, 0, 0))

    def test_changed_native_preflight_consumes_attempt_without_output(self):
        with patch.object(w, 'preflight', side_effect=ValueError('native options changed')):
            self.assertEqual(self.gate(), (0, 0, 0))
        self.assertEqual(self.gate(), (0, 0, 0))

    def test_withdrawn_or_changed_entry_cannot_release(self):
        w.CRON.unlink()
        self.assertEqual(self.gate(), (0, 0, 0))

    def test_expired_or_early_invocation_is_quiet(self):
        self.runtime['due_epoch'] = time.time()+60
        self.assertEqual(self.gate(), (0, 0, 0))
        self.runtime['due_epoch'] = time.time()-90; self.runtime['expires_run_epoch'] = time.time()-1
        self.assertEqual(self.gate(), (0, 0, 0))
        self.assertFalse((self.root/'attempt.json').exists())

    def test_interruption_at_release_retains_intent_and_cannot_retry(self):
        def interrupt(fd, raw): raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt): self.gate(writer=interrupt)
        record = json.loads((self.root/'gate.json').read_text())
        self.assertIn('release_intent_epoch', record); self.assertFalse(record['released'])
        self.assertEqual(self.gate(), (0, 0, 0))

    def test_pipe_or_named_output_is_quiet(self):
        with patch.object(w.h, 'bounded', return_value={'returncode': 2, 'stdout': self.diagnostic.decode(), 'stderr': ''}), \
                patch.object(w.os, 'fstat', side_effect=lambda fd: types.SimpleNamespace(st_mode=stat.S_IFIFO) if fd == 1 else self.fstat(fd)), \
                patch.object(w.os, 'write') as output:
            self.assertEqual(w.gate(self.spec), 0); output.assert_not_called()

    def test_real_anonymous_file_receives_exactly_one_marker_byte(self):
        with tempfile.TemporaryFile() as native_output:
            saved_stdout = os.dup(1)
            try:
                os.dup2(native_output.fileno(), 1)
                def owner_stat(fd):
                    row = self.fstat(fd)
                    if fd != 1: return row
                    return types.SimpleNamespace(st_mode=row.st_mode, st_nlink=row.st_nlink,
                                                 st_size=row.st_size, st_uid=0)
                with patch.object(w.h, 'bounded', return_value={'returncode': 2,
                        'stdout': self.diagnostic.decode(), 'stderr': ''}), \
                        patch.object(w.os, 'fstat', side_effect=owner_stat):
                    result = w.gate(self.spec)
            finally:
                os.dup2(saved_stdout, 1); os.close(saved_stdout)
            self.assertEqual(result, 2)
            native_output.seek(0)
            self.assertEqual(native_output.read(), b'!')

    def test_private_lock_and_rejected_argument_only(self):
        calls = []
        def capture(argv, **kwargs):
            calls.append(argv); return {'returncode': 2, 'stdout': self.diagnostic.decode(), 'stderr': ''}
        with patch.object(w.h, 'bounded', side_effect=capture), \
                patch.object(w.os, 'fstat', side_effect=self.output_stat), \
                patch.object(w.os, 'lseek', return_value=0), patch.object(w.os, 'write', return_value=len(self.body)):
            self.assertEqual(w.gate(self.spec), 2)
        self.assertIn('--obs04-controlled-failure', calls[0][2])
        self.assertNotIn('/run/lock/needrestart-check.lock', calls[0][2])
        self.assertNotIn('sendmail', calls[0][2])

    def test_explicit_file_mode_ignores_private_umask(self):
        previous = os.umask(0o077)
        try: w.write_new(self.root/'mode-test', b'x', 0o644)
        finally: os.umask(previous)
        self.assertEqual(stat.S_IMODE((self.root/'mode-test').stat().st_mode), 0o644)
        with self.assertRaises(FileExistsError): w.write_new(self.root/'mode-test', b'overwrite')

    def test_foreign_cron_is_preserved(self):
        cron = self.root/'foreign-cron'; cron.write_bytes(b'foreign')
        with patch.object(w, 'CRON', cron):
            with self.assertRaises(ValueError): w.withdraw(self.spec)
        self.assertEqual(cron.read_bytes(), b'foreign')

    def test_withdraw_only_matching_file_and_repeated_withdraw_is_safe(self):
        cron = self.root/'authored-cron'; cron.write_bytes(b'authored')
        self.runtime['cron_sha256'] = w.h.sha(b'authored')
        with patch.object(w, 'CRON', cron):
            self.assertTrue(w.withdraw(self.spec)['cron_absent'])
            self.assertFalse(w.withdraw(self.spec)['removed'])

    def test_interrupted_publication_companion_link_is_withdrawn(self):
        cron = w.CRON
        temp = cron.parent/('.'+self.spec['operation_id']+'.pending')
        os.link(cron, temp)
        original = Path.lstat
        def root_metadata(path):
            row = original(path)
            if path not in (cron, temp): return row
            return types.SimpleNamespace(st_mode=row.st_mode, st_dev=row.st_dev,
                st_ino=row.st_ino, st_nlink=row.st_nlink, st_uid=0, st_gid=0,
                st_size=row.st_size, st_mtime_ns=row.st_mtime_ns)
        with patch.object(Path, 'lstat', root_metadata):
            self.assertTrue(w.withdraw(self.spec)['removed'])
        self.assertFalse(temp.exists()); self.assertFalse(cron.exists())

    def test_schedule_has_lead_and_rejects_reporting_guard_and_expiry(self):
        now = datetime.datetime(2026, 10, 24, 18, 0, tzinfo=ZoneInfo('America/Chicago')).timestamp()
        due = w.choose_due(now, now+86400)
        self.assertGreater(due-now, 180); self.assertEqual(due % 60, 0)
        near = datetime.datetime(2026, 10, 25, 5, 27, tzinfo=ZoneInfo('America/Chicago')).timestamp()
        with self.assertRaises(ValueError): w.choose_due(near, near+86400)
        with self.assertRaises(ValueError): w.choose_due(now, now+300)

    def test_cron_subject_and_message_bind_native_command(self):
        self.assertEqual(w.command(self.spec), r.command(self.spec))
        contract = r.message(self.spec, self.body)
        self.assertEqual(contract['recipient'], 'notify.failure@mailrise.xyz')
        self.assertEqual(contract['attachments'], [])
        self.assertEqual(contract['subject'], 'Cron <root@j2-svntp1> '+w.command(self.spec))
        self.assertNotIn('(failed)', contract['subject'])
        self.assertTrue(r.preview(self.spec, self.body).endswith(b'\n\n'+self.body+b'\n'))

    def test_scope_and_remote_action_are_closed(self):
        r.validate(self.spec)
        with self.assertRaises(ValueError): r.validate(dict(self.spec, command='unapproved'))
        with self.assertRaises(ValueError): r.remote(self.spec, {}, 'send')
        self.spec['protected_files']['/etc/shadow'] = '0'*64
        with self.assertRaises(ValueError): r.validate(self.spec)

    def test_three_remote_payloads_compile_without_running(self):
        files = {n: path.read_bytes() for n, path in r.SOURCES.items()}
        files['body.txt'] = self.body
        files['diagnostic.txt'] = self.diagnostic
        for action in ('install', 'observe', 'withdraw'):
            compile(r.remote(self.spec, files, action), '<sealed-'+action+'>', 'exec')

    def test_native_process_rejects_subject_changing_options(self):
        proc = self.root/'proc'; pid = proc/'42'; pid.mkdir(parents=True)
        (pid/'exe').symlink_to('/usr/sbin/cron')
        (pid/'cmdline').write_bytes(b'/usr/sbin/cron\0-f\0')
        w.cron_process(42, proc)
        for argv in (b'/usr/sbin/cron\0-f\0-n\0', b'/usr/sbin/cron\0-f\0-L\05\0', b'other\0-f\0'):
            (pid/'cmdline').write_bytes(argv)
            with self.assertRaises(ValueError): w.cron_process(42, proc)

    def test_production_wrapper_is_not_an_arbitrary_shell_input(self):
        rendered, wrapper = r.production_wrapper(r.SOURCES['cron.template'].read_bytes())
        self.assertIn(b'MAILTO=notify.failure@mailrise.xyz', rendered)
        self.assertIn(b'/usr/local/sbin/needrestart.sh', wrapper)
        self.assertNotIn(b'\\%', wrapper)
        with self.assertRaises(ValueError): r.production_wrapper(b'30 5 * * * root echo %bad\n')

    def test_protected_hash_alone_does_not_allow_writable_or_foreign_inputs(self):
        row = {'sha256': 'a'*64, 'uid': 0, 'gid': 0, 'mode': 0o644}
        with patch.object(w.h, 'file_record', side_effect=lambda p: dict(row)):
            w.protected_file('/approved', 'a'*64)
            row['mode'] = 0o666
            with self.assertRaises(ValueError): w.protected_file('/approved', 'a'*64)
            row['mode'] = 0o644; row['uid'] = 1000
            with self.assertRaises(ValueError): w.protected_file('/approved', 'a'*64)

    def publication(self, timer_ok=True):
        base = self.root/'stages'; cron_dir = self.root/'cron.d'; cron_dir.mkdir()
        cron = cron_dir/'obs04_cron_failure'
        ordinary = cron_dir/'needrestart_check'; ordinary.write_bytes(b'ordinary unchanged')
        inputs = {'worker.py': b'worker bytes', 'helper.py': b'helper bytes', 'body.txt': self.body,
                  'diagnostic.txt': self.diagnostic}
        self.spec['input_hashes'] = {n: w.h.sha(raw) for n, raw in inputs.items()}
        response = {'returncode': 0 if timer_ok else 1,
                    'stdout': 'LoadState=loaded\nActiveState=active\nNextElapseUSecMonotonic=123\n', 'stderr': ''}
        with patch.object(w, 'BASE', base), patch.object(w, 'CRON', cron), \
                patch.object(w, 'directory'), patch.object(w, 'runtime', RUNTIME), \
                patch.object(w.h, 'bounded', return_value=response):
            if timer_ok:
                data = w.install(self.spec, inputs)
                self.assertTrue(cron.exists()); self.assertTrue(data['installed'])
                self.assertEqual(stat.S_IMODE(cron.stat().st_mode), 0o644)
                self.assertTrue(w.withdraw(self.spec)['removed'])
                self.assertFalse(cron.exists())
            else:
                with self.assertRaises(ValueError): w.install(self.spec, inputs)
                self.assertFalse(cron.exists())
        self.assertEqual(ordinary.read_bytes(), b'ordinary unchanged')

    def test_publish_and_withdraw_preserve_normal_cron(self):
        self.publication()

    def test_failed_independent_withdrawal_blocks_publication(self):
        self.publication(timer_ok=False)

    def test_uncertain_install_is_not_repeated_and_receipt_blocks_reexecution(self):
        directory = Path(self.spec['directory']); directory.mkdir()
        files = {n: path.read_bytes() for n, path in r.SOURCES.items()}
        files['body.txt'] = self.body
        files['diagnostic.txt'] = self.diagnostic
        args = types.SimpleNamespace(directory=directory, sha256='c'*64)
        failed = {'returncode': None, 'error': 'timeout', 'stdout': 'partial', 'stderr': 'retained'}
        with patch.object(r, 'prepare', return_value=(self.spec, files)), \
                patch.object(r.h, 'bounded', side_effect=lambda *a, **k: dict(failed)) as run:
            result = r.execute(args)
            self.assertFalse(result['obs04_accepted']); self.assertFalse(result['authored_cron_absent'])
            self.assertEqual([x['action'] for x in result['steps']], ['install', 'observe'])
            self.assertEqual(run.call_count, 2)
            with self.assertRaises(FileExistsError): r.execute(args)
            self.assertEqual(run.call_count, 2)


if __name__ == '__main__':
    unittest.main()
