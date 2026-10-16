#!/usr/bin/python3
"""Offline reporter capture, cron wrapper, activation and sealing tests."""
import datetime
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import tarfile
import time
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


r = load(ROOT/'scripts/run-mail-reporting.py')
w = load(ROOT/'scripts/mail-reporting.py')
base = load(ROOT/'scripts/mail-install.py')
Worker = w.make_worker(base)
REPORTER = r.SOURCES['reporter.sh'].read_bytes()
CRON = (ROOT/'templates/needrestart.cron.example').read_bytes().replace(b'@CRON_RECIPIENT@', b'notify.failure@mailrise.xyz').replace(b'@ALERT_RECIPIENT@', b'notify@mailrise.xyz')


class Clock(datetime.datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 10, 15, 21, 0, tzinfo=tz)


class Fixture(Worker):
    def __init__(self, root):
        super().__init__({'operation_id': 'fixture'}, {'reporter.sh': REPORTER, 'cron.pending': CRON}, r.h)
        self.root = root/'state'
        self.checks = 0

    def preflight(self):
        self.root.mkdir(mode=0o700)
        self.created = True
        self.save()

    def accept_files(self):
        if os.path.lexists(w.CRON):
            raise ValueError('cron preexists')

    def continuity(self):
        self.checks += 1

    def unit(self, name):
        return {'ActiveState': 'active'}


class ReportingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.job = Fixture(self.root)
        self.job.preflight()
        self.patch(w, 'CRON', self.root/'cron')
        self.patch(w.datetime, 'datetime', Clock)
        actual_record = r.h.file_record

        def root_record(path):
            result = actual_record(path)
            if 'uid' in result:
                result.update(uid=0, gid=0)
            return result

        self.patch(r.h, 'file_record', root_record)

    def patch(self, obj, name, value):
        p = patch.object(obj, name, value)
        p.start()
        self.addCleanup(p.stop)

    def exercise(self, actionable=False):
        scanner = self.root/'normal-scanner'
        scanner.write_text('#!/bin/bash\nprintf "NEEDRESTART-KSTA: 1\\n"\n' + ('printf "NEEDRESTART-SVC: example.service\\n"\n' if actionable else ''))
        scanner.chmod(0o700)
        original = w.captured_reporter

        def local_capture(raw, sendmail, failed_scanner=None):
            # Fixture only: allow the real reporter to exercise its scan path as
            # an unprivileged test user. Production performs the root check.
            self.assertEqual(raw.count(b'if ((EUID != 0)); then'), 1)
            raw = raw.replace(b'if ((EUID != 0)); then', b'if false; then')
            return original(raw, sendmail, failed_scanner or scanner)

        with patch.object(w, 'captured_reporter', local_capture):
            self.job.exercise()

    def test_real_reporter_quiet_scan_failure_and_overlap_without_transport(self):
        self.exercise()
        self.assertIsNone(self.job.state['runtime_message_sha256'])
        self.assertTrue(self.job.state['failure_capture_accepted'])
        self.assertTrue(self.job.state['overlap_accepted'])
        message = (self.job.root/'failure.eml').read_text()
        self.assertIn('To: notify@mailrise.xyz', message)
        self.assertIn('Synthetic scan failure for acceptance', message)
        self.assertNotIn('/usr/sbin/sendmail', (self.job.root/'runtime-reporter').read_text())

    def test_real_reporter_actionable_scan_is_captured_and_cron_stays_quiet(self):
        self.exercise(actionable=True)
        message = (self.job.root/'runtime.eml').read_text()
        self.assertIn('example.service', message)
        self.assertTrue(self.job.state['runtime_capture_accepted'])
        self.assertFalse(w.CRON.exists())

    def test_capture_helper_refuses_second_submission(self):
        stub = self.root/'capture'
        stub.write_bytes(w.capture_program(self.root/'message'))
        stub.chmod(0o700)
        first = r.h.bounded([str(stub)], payload=b'first')
        second = r.h.bounded([str(stub)], payload=b'second')
        self.assertEqual(first['returncode'], 0)
        self.assertNotEqual(second['returncode'], 0)
        self.assertEqual((self.root/'message').read_bytes(), b'first')

    def test_cron_percent_translation_and_source_drift_rejection(self):
        self.assertNotIn('\\%', w.cron_command(CRON))
        with self.assertRaises(ValueError):
            w.cron_command(CRON.replace(b'\\%', b'%'))
        with self.assertRaises(ValueError):
            w.captured_reporter(REPORTER.replace(b'/usr/sbin/sendmail', b'/different/path', 1), self.root/'capture')

    def test_success_publishes_exact_file_and_records_next_local_run(self):
        self.job.activate()
        self.assertEqual(w.CRON.read_bytes(), CRON)
        self.assertEqual(w.CRON.stat().st_mode & 0o777, 0o644)
        self.assertTrue(self.job.state['cron_active'])
        self.assertEqual(self.job.state['next_run_local'], '2026-10-16T05:30:00-05:00')
        self.assertFalse(self.job.state['scheduled_run_observed'])

    def run_after_fixture(self):
        with patch.object(self.job, 'preflight'), patch.object(self.job, 'exercise'):
            return self.job.run()

    def test_failed_postcondition_removes_only_authored_cron(self):
        with patch.object(self.job, 'unit', return_value={'ActiveState': 'inactive'}):
            state = self.run_after_fixture()
        self.assertFalse(state['accepted'])
        self.assertFalse(w.CRON.exists())
        self.assertEqual(state['recovery'], 'authored cron removed')

    def test_foreign_file_after_publication_is_preserved(self):
        def drift(name):
            w.CRON.write_bytes(b'foreign\n')
            return {'ActiveState': 'inactive'}
        with patch.object(self.job, 'unit', side_effect=drift):
            state = self.run_after_fixture()
        self.assertFalse(state['accepted'])
        self.assertEqual(w.CRON.read_bytes(), b'foreign\n')
        self.assertIn('hold:', state['recovery'])

    def test_preexisting_cron_and_failed_capture_block_activation(self):
        w.CRON.write_bytes(b'foreign\n')
        with self.assertRaisesRegex(ValueError, 'preexists'):
            self.job.activate()
        w.CRON.unlink()
        with patch.object(self.job, 'preflight'), patch.object(self.job, 'exercise', side_effect=ValueError('scan failed')):
            state = self.job.run()
        self.assertFalse(state['accepted'])
        self.assertFalse(w.CRON.exists())

    def test_near_scheduled_run_rejected(self):
        class Near(Clock):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 10, 16, 5, 25, tzinfo=tz)
        with patch.object(w.datetime, 'datetime', Near):
            with self.assertRaisesRegex(ValueError, 'too close'):
                self.job.activate()
        self.assertFalse(w.CRON.exists())

    def test_execute_single_use_and_no_transport_on_consumed_receipt(self):
        d = self.root/'execution'
        d.mkdir()
        (d/'execution.json').write_text('{}')
        spec = {'operation_id': 'fixture'}
        files = {k: p.read_bytes() for k, p in r.SOURCES.items()}
        files.update(msmtprc=b'', aliases=b'', **{'cron.pending': CRON})
        with patch.object(r, 'prepare', return_value=(spec, files)), patch.object(r.h, 'bounded') as transport:
            with self.assertRaises(FileExistsError):
                r.execute(types.SimpleNamespace(directory=d, sha256='a'*64))
            transport.assert_not_called()

    def test_sealed_archive_review_and_source_binding(self):
        d = self.root/'sealed'
        d.mkdir(mode=0o700)
        files = {name: path.read_bytes() for name, path in r.SOURCES.items()}
        files.update({'known_hosts': b'fixture\n', 'msmtprc': b'fixture\n',
                      'aliases': b'fixture\n', 'cron.pending': CRON, 'delivery.json': b'{}\n'})
        now = int(time.time())
        spec = {'operation_id': 'fixture', 'hostname': 'j2-svntp1', 'boot_id': 'fixture',
                'prepared_epoch': now, 'expires_epoch': now+86400,
                'members': {name: r.h.sha(raw) for name, raw in files.items()}}
        files.update({'spec.json': r.h.encoded(spec), 'review.md': r.review(spec).encode()})
        for name, raw in files.items():
            (d/name).write_bytes(raw)
            (d/name).chmod(0o600)
        with tarfile.open(d/'mail-reporting.tar', 'w') as archive:
            for name, raw in files.items():
                member = tarfile.TarInfo(name)
                member.size = len(raw)
                archive.addfile(member, io.BytesIO(raw))
        (d/'mail-reporting.tar').chmod(0o600)
        digest = r.h.sha((d/'mail-reporting.tar').read_bytes())
        self.assertEqual(r.prepare(d, digest)[0], spec)
        with self.assertRaisesRegex(ValueError, 'digest'):
            r.prepare(d, '0'*64)
        (d/'review.md').write_text('changed review')
        with self.assertRaisesRegex(ValueError, 'local review drift'):
            r.prepare(d, digest)


if __name__ == '__main__':
    unittest.main()
