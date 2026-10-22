#!/usr/bin/python3
"""Focused offline bounds, redaction, source scope and approval-gate checks."""
import ast
import importlib.util
import contextlib
import io
import json
from pathlib import Path
import signal
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


r = load(ROOT/'scripts/run-munin-readiness.py')
r.h = load(ROOT/'scripts/run-production-inspection.py')
r.support = load(ROOT/'scripts/run-munin-prerequisites.py'); r.support.h = r.h


class ReadinessTests(unittest.TestCase):
    def test_statistic_directory_never_reads_contents(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp); (p/'loopstats').write_text('PRIVATE RAW STATISTICS')
            with patch.object(r.h, 'file_record', side_effect=AssertionError('content read')):
                row = r.metadata_directory(p)
            self.assertIn('inode', row['entries']['loopstats'])
            self.assertNotIn('PRIVATE', json.dumps(row))

    def test_links_are_reported_without_following(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp); (p/'secret').write_text('SECRET'); (p/'link').symlink_to(p/'secret')
            self.assertTrue(r.record(p/'link')['indirect_or_special'])
            directory = p/'indirect'; directory.symlink_to(p, target_is_directory=True)
            self.assertTrue(r.record(directory/'secret')['indirect_ancestor'])

    def test_directory_count_is_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            for i in range(4): (p/str(i)).touch()
            self.assertTrue(r.metadata_directory(p, limit=2)['over_limit'])

    def test_cron_structure_omits_environment_and_body(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'cron'; p.write_text('MAILTO=SECRET\n30 5 * * * root echo SECRET\n')
            row = r.cron(p)
            self.assertEqual(row['schedule'][0]['schedule'], ['30', '5', '*', '*', '*'])
            self.assertNotIn('SECRET', json.dumps(row))

    def test_installed_manual_excerpt_is_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'manual'; p.write_text('address 192.0.2.1\n'*100)
            row = r.installed_excerpt(p)
            self.assertEqual(row['matches'], 100); self.assertEqual(len(row['excerpts']), 80)

    def test_wrong_root_does_not_run_commands(self):
        spec = {'operation_id': 'readiness', 'mode': 'node', 'hostname': 'j2-svntp1', 'boot_id': 'unused'}
        with patch.object(r.os, 'geteuid', return_value=1000), patch.object(r.h, 'bounded') as command:
            row = r.collect(spec)
        command.assert_not_called(); self.assertFalse(row['capture_complete'])

    def test_review_is_explicit_about_unaccepted_work(self):
        for mode in r.TARGETS:
            endpoint, user, alias, hostname = r.TARGETS[mode]
            text = r.review({'mode': mode, 'operation_id': 'review', 'endpoint': endpoint,
                'user': user, 'host_key_alias': alias, 'hostname': hostname, 'boot_id': 'boot',
                'expires_epoch': 1792681585})
            for marker in ('read-only', 'No new HA fixtures', 'execution.json', 'capture_complete=true'):
                self.assertIn(marker, text)

    def test_readiness_source_has_no_mutating_commands(self):
        source = (ROOT/'scripts/run-munin-readiness.py').read_text()
        tree = ast.parse(source)
        commands = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name) and node.func.id == 'cmd']
        self.assertTrue(commands)
        for node in commands:
            tokens = {n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
            self.assertFalse(tokens & {'restart', 'reload', 'start', 'enable', 'update', 'download', 'munin-run'})
            if '/usr/bin/apt-get' in tokens:
                self.assertIn('--simulate', tokens)
        self.assertNotIn('socket.create_connection', source)

    def test_archive_tamper_and_one_use_rejected_before_transport(self):
        # A real prepared bundle is checked separately; this is a local exclusivity guard.
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp); (p/'inspection.tar').write_bytes(b'changed'); (p/'inspection.tar').chmod(0o600)
            with self.assertRaisesRegex(ValueError, 'archive hash'):
                r.prepare(p, '0'*64)
            spec = {'endpoint': '192.0.2.1', 'host_key_alias': 'test', 'user': 'test'}
            files = {n: b'' for n in ('runner.py', 'helper.py', 'support.py')}
            (p/'execution.json').write_text('{}')
            with patch.object(r, 'prepare', return_value=(spec, files)), patch.object(r.h, 'bounded') as command:
                with self.assertRaises(FileExistsError):
                    r.execute(types.SimpleNamespace(directory=p, sha256='0'*64))
                command.assert_not_called()

    def test_actual_stdin_bootstrap_reaches_collection_without_host_commands(self):
        spec = {'operation_id': 'bootstrap-test', 'mode': 'node', 'endpoint': '192.0.2.1',
                'host_key_alias': 'test', 'user': 'test', 'hostname': 'j2-svntp1', 'boot_id': 'unused'}
        files = {name: r.SOURCES[name].read_bytes() for name in ('runner.py', 'helper.py', 'support.py')}

        def transport(argv, **kwargs):
            output = io.StringIO()
            previous = signal.getsignal(signal.SIGALRM)
            try:
                with contextlib.redirect_stdout(output), patch.object(r.os, 'geteuid', return_value=1000), \
                     patch('subprocess.Popen', side_effect=AssertionError('unexpected host command')):
                    exec(compile(kwargs['payload'], '<sealed-stdin>', 'exec'), {})
            finally:
                signal.alarm(0)
                signal.signal(signal.SIGALRM, previous)
            return {'argv': argv, 'returncode': 0, 'stdout': output.getvalue(), 'stderr': ''}

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(r, 'prepare', return_value=(spec, files)), patch.object(r.h, 'bounded', side_effect=transport):
                row = r.execute(types.SimpleNamespace(directory=Path(tmp), sha256='0'*64))
            self.assertFalse(row['capture_complete'])
            capture = json.loads((Path(tmp)/'stdout.txt').read_text())
            self.assertEqual(capture['error'], 'root/host/boot mismatch')
            self.assertEqual(capture['commands'], {})

    def test_master_qualification_bootstrap_binds_canonical_config(self):
        spec = {'operation_id':'master-config-test', 'mode':'master-config',
                'endpoint':'192.0.2.1', 'host_key_alias':'test', 'user':'test'}
        files = {name:r.SOURCES[name].read_bytes() for name in (
            'runner.py','helper.py','support.py','qualification.py',
            'repository-master.conf','contact-example.conf')}
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(r, 'prepare', return_value=(spec,files)), \
                 patch.object(r.h, 'bounded', return_value={'returncode':1,'stdout':'','stderr':''}) as transport:
                r.execute(types.SimpleNamespace(directory=Path(tmp),sha256='0'*64))
            payload = transport.call_args.kwargs['payload']
            self.assertIn(b'frozen_inputs=',payload)
            self.assertIn(repr(files['repository-master.conf']).encode(),payload)
            self.assertIn(repr(files['qualification.py']).encode(),payload)


if __name__ == '__main__':
    unittest.main()
