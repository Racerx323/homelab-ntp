#!/usr/bin/python3
"""Offline parser, bounds, and one-shot launcher regression checks."""
import importlib.util
import io
import base64
import hashlib
import json
import os
from pathlib import Path
import tarfile
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


collector = load('hook_collector', 'hook-closure-preflight.py')
launcher = load('hook_launcher', 'run-hook-closure-preflight.py')
CONFIG = 'Config: config\nTemplates: templates\n\nName: config\nDriver: File\nFilename: /var/cache/debconf/config.dat\nReject-Type: password\n'


class Parsing(unittest.TestCase):
    def test_static_file_backend(self):
        records = collector.debconf_structure(CONFIG)
        self.assertEqual(records[0]['config'], 'config')
        self.assertEqual(records[1]['driver'], 'File')
        self.assertEqual(records[1]['reject_type'], 'password')

    def test_credentials_omitted_for_other_backend(self):
        text = CONFIG.replace('Driver: File', 'Driver: LDAP\nPassword: PRIVATE_VALUE\nServer: PRIVATE_SERVER')
        result = collector.debconf_structure(text)
        self.assertNotIn('PRIVATE', json.dumps(result))
        self.assertEqual(result[1]['omitted_fields'], ['password', 'server'])

    def test_config_rejections(self):
        for text in (CONFIG.replace('config.dat', '${SECRET}'),
                     CONFIG + '\nName: config\nDriver: File\n',
                     'Config: config\n', CONFIG.replace('Driver: File', 'Driver: File\nDriver: Stack')):
            with self.subTest(text=text), self.assertRaises(ValueError):
                collector.debconf_structure(text)

    def test_selected_answers_only(self):
        data = ('Name: other/password\nValue: PRIVATE\n\nName: watchdog/run\nValue: false\n'
                '\nName: watchdog/module\nValue: bcm2835_wdt\n')
        result = collector.answer_subset(data)
        self.assertNotIn('PRIVATE', json.dumps(result))
        self.assertEqual(result['watchdog/run']['value'], 'false')
        self.assertFalse(result['watchdog/restart']['present'])

    def test_answer_rejections(self):
        for data in ('Name: watchdog/run\nValue: PRIVATE\n',
                     'Name: watchdog/module\nValue: a; command\n',
                     'Name: watchdog/run\nValue: true\n\nName: watchdog/run\nValue: false\n',
                     'Name: watchdog/run\nName: other\nValue: true\n',
                     'Name: watchdog/run\nValue: true\n continuation\n'):
            with self.subTest(data=data), self.assertRaises(ValueError):
                collector.answer_subset(data)

    def test_redaction(self):
        result, changed = collector.redact('Password PRIVATE\nAuthorization PRIVATE\nURL https://x/y?PRIVATE\nSAFE=yes')
        self.assertTrue(changed)
        self.assertNotIn('PRIVATE', result)
        self.assertIn('SAFE=yes', result)

    def test_command_success_and_bounds(self):
        result = collector.command(['/usr/bin/python3', '-I', '-B', '-c', 'print("fixture")'])
        self.assertEqual((result['rc'], result['stdout']), (0, 'fixture\n'))
        with self.assertRaises(ValueError):
            collector.command(['/usr/bin/python3', '-I', '-B', '-c', 'print("x"*10000)'], limit=10)
        with self.assertRaises(ValueError):
            collector.command(['/usr/bin/python3', '-I', '-B', '-c', 'import time; time.sleep(10)'], seconds=.05)

    def test_protected_file_rejections(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'file'
            path.write_text('fixture')
            # Root ownership/ancestor checks must reject a workstation fixture.
            with self.assertRaises(ValueError):
                collector.read_protected(path)
            link = Path(tmp) / 'link'
            link.symlink_to(path)
            with self.assertRaises((ValueError, OSError)):
                collector.read_protected(link)


class Collection(unittest.TestCase):
    def test_identity_rejection_before_commands(self):
        with patch.object(collector.os, 'geteuid', return_value=1000), patch.object(collector, 'command') as run:
            with self.assertRaises(ValueError):
                collector.collect({})
            run.assert_not_called()

    def test_complete_synthetic_collection_and_state_drift(self):
        files = {'/usr/lib/os-release': b'ID=debian\nVERSION_ID="13"\nVERSION_CODENAME=trixie\n',
                 '/proc/sys/kernel/random/boot_id': b'fixture-boot',
                 '/etc/debconf.conf': CONFIG.encode(),
                 '/var/cache/debconf/config.dat': b'Name: watchdog/run\nValue: false\n',
                 '/var/lib/dpkg/status': b'Package: apt\nStatus: install ok installed\n',
                 '/var/lib/dpkg/triggers/Unincorp': b'',
                 '/usr/bin/dpkg': b'tool', '/usr/bin/dpkg-query': b'tool',
                 '/usr/bin/systemctl': b'tool'}

        class FixturePath:
            def __init__(self, name): self.name = str(name)
            def __str__(self): return self.name
            def __truediv__(self, name): return FixturePath(self.name + '/' + name)
            def exists(self): return self.name in files
            def is_symlink(self): return False
            def resolve(self, strict=False): return self
            def iterdir(self): return iter(())
            def lstat(self): raise FileNotFoundError
            def read_text(self): return files[self.name].decode()

        def read(path, limit=collector.FILE_LIMIT):
            if str(path) not in files: raise FileNotFoundError
            return files[str(path)], {'uid': 0, 'gid': 0, 'mode': '0o644'}

        calls = []
        def run(argv, **kwargs):
            calls.append(argv)
            output = 'apt\t3.0.3\tii \npasswd\t1.0\tii \n' if argv[:2] == ['/usr/bin/dpkg-query', '-W'] else ''
            return {'argv': argv, 'rc': 0, 'stdout': output, 'stderr': ''}

        spec = {'hostname': 'j2-svntp1', 'kernel': 'fixture-kernel', 'not_before': 0,
                'expires_epoch': 9999999999, 'input_hashes': {}, 'input_metadata': {},
                'absent_inputs': [], 'version_lines': ['apt\t3.0.3\tii '],
                'unchanged_packages': {'apt': '3.0.3'}, 'new_packages': ['watchdog']}
        with patch.object(collector, 'Path', FixturePath), patch.object(collector, 'read_protected', side_effect=read), patch.object(collector, 'command', side_effect=run), patch.object(collector.os, 'geteuid', return_value=0), patch.object(collector.socket, 'gethostname', return_value='j2-svntp1'), patch.object(collector.os, 'uname', return_value=SimpleNamespace(machine='aarch64', release='fixture-kernel')), patch.object(collector.pwd, 'getpwuid', return_value=SimpleNamespace(pw_dir='/root')), patch.object(collector.pwd, 'getpwnam', return_value=SimpleNamespace(pw_uid=1000)), patch.dict(collector.os.environ, {'SUDO_USER': 'ama', 'SUDO_UID': '1000'}, clear=True):
            report = collector.collect(spec)
            self.assertEqual(report['state'], 'collected')
            self.assertTrue(report['debconf_answer_snapshot_unchanged'])
            self.assertTrue(report['package_snapshot_unchanged'])
            self.assertFalse(report['installation_ready'])
            self.assertNotIn('config.dat', json.dumps([r for r in report['files'] if 'sha256' in r]))
            spec['new_packages'] = ['apt']
            report = collector.collect(spec)
            self.assertIn('v6 package plan continuity failed', report['gaps'])
            self.assertEqual(report['state'], 'collected_with_gaps')
        self.assertTrue(all(argv[0] in ('/usr/bin/dpkg-query', '/usr/bin/dpkg', '/usr/bin/systemctl') for argv in calls))


class Launcher(unittest.TestCase):
    def test_agent_forwarded_without_unrelated_environment(self):
        with patch.dict(launcher.os.environ, {'SSH_AUTH_SOCK': '/fixture/agent', 'PRIVATE': 'omitted'}, clear=True):
            self.assertEqual(launcher.ssh_environment(), {'PATH': '/usr/bin:/bin', 'LC_ALL': 'C', 'SSH_AUTH_SOCK': '/fixture/agent'})
        with patch.dict(launcher.os.environ, {}, clear=True), self.assertRaises(ValueError):
            launcher.ssh_environment()

    def test_submission_receives_agent_and_records_terminal_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            def run(argv, **kwargs):
                self.assertEqual(kwargs['env']['SSH_AUTH_SOCK'], '/fixture/agent')
                self.assertNotIn('PRIVATE', kwargs['env'])
                kwargs['stdout'].write(b'{"state":"collected","gaps":[]}\nHOOK_CLOSURE_EXIT_STATUS=0\n')
                return SimpleNamespace(returncode=0)
            argv = ['launcher', '--bundle', str(directory / 'bundle.tar'), '--sha256', 'fixture']
            with patch('sys.argv', argv), patch.object(launcher, 'prepare', return_value=(b'fixture', {'not_before': 0, 'expires_epoch': 9999999999})), patch.dict(launcher.os.environ, {'SSH_AUTH_SOCK': '/fixture/agent', 'PRIVATE': 'omitted'}, clear=True), patch.object(launcher.subprocess, 'run', side_effect=run):
                self.assertEqual(launcher.main(), 0)
            self.assertTrue((directory / 'execution.json').exists())
            self.assertEqual(json.loads((directory / 'result.json').read_text())['transport_exit_status'], 0)

    def test_transport_is_fixed(self):
        argv = launcher.transport(Path('/private/evidence'))
        self.assertEqual(argv[-1], 'cd / && sudo -n -k /usr/bin/python3 -I -B -')
        self.assertIn('StrictHostKeyChecking=yes', argv)
        self.assertIn('/dev/null', argv)
        self.assertNotIn('sudoers', ' '.join(argv))

    def test_registration_blocks_resubmission(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            bundle = directory / 'bundle.tar'
            (directory / 'execution.json').write_text('{}')
            argv = ['launcher', '--bundle', str(bundle), '--sha256', 'fixture']
            with patch('sys.argv', argv), patch.object(launcher, 'prepare', return_value=(b'fixture', {'not_before': 0, 'expires_epoch': 9999999999})), patch.object(launcher.subprocess, 'run') as run, patch.dict(launcher.os.environ, {'SSH_AUTH_SOCK': '/fixture/agent'}):
                with self.assertRaises(FileExistsError):
                    launcher.main()
                run.assert_not_called()

    def test_hash_rejected_before_transport(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp) / 'bundle.tar'
            bundle.write_bytes(b'fixture')
            bundle.chmod(0o600)
            with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                launcher.prepare(bundle, 'wrong')

    def test_bundle_success_then_rendering_rejection(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            spec = {'hostname': 'j2-svntp1', 'expires_epoch': 9999999999}
            key = b'fixture-key'
            known = b'10.1.0.137 ssh-ed25519 ' + base64.b64encode(key) + b'\n'
            files = {'collector.py': b'', 'launcher.py': Path(launcher.__file__).read_bytes(),
                     'spec.json': json.dumps(spec).encode(), 'known_hosts': known,
                     'review.md': b'fixture', 'tests.py': b'fixture'}
            files['payload.py'] = launcher.render_payload(files['collector.py'], spec)
            self.assertEqual(files['payload.py'], launcher.render_payload(files['collector.py'], dict(reversed(list(spec.items())))))
            (directory / 'known_hosts').write_bytes(known)
            (directory / 'known_hosts').chmod(0o600)
            bundle = directory / 'bundle.tar'
            def seal():
                files['manifest.json'] = json.dumps({'members': {k: launcher.digest(v) for k, v in files.items() if k != 'manifest.json'}}).encode()
                with tarfile.open(bundle, 'w') as archive:
                    for name, data in files.items():
                        info = tarfile.TarInfo(name); info.size = len(data)
                        archive.addfile(info, io.BytesIO(data))
                bundle.chmod(0o600)
                return launcher.digest(bundle.read_bytes())
            fingerprint = 'SHA256:' + base64.b64encode(hashlib.sha256(key).digest()).decode().rstrip('=')
            with patch.object(launcher, 'FINGERPRINT', fingerprint):
                payload, returned = launcher.prepare(bundle, seal())
                self.assertEqual(payload, files['payload.py'])
                self.assertEqual(returned, spec)
                files['payload.py'] += b'print("extra")\n'
                with self.assertRaisesRegex(ValueError, 'rendering mismatch'):
                    launcher.prepare(bundle, seal())

    def test_archive_members_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp) / 'bundle.tar'
            with tarfile.open(bundle, 'w') as archive:
                member = tarfile.TarInfo('../escape')
                member.size = 1
                archive.addfile(member, io.BytesIO(b'x'))
            bundle.chmod(0o600)
            with self.assertRaisesRegex(ValueError, 'archive members'):
                launcher.prepare(bundle, launcher.digest(bundle.read_bytes()))


if __name__ == '__main__':
    unittest.main()
