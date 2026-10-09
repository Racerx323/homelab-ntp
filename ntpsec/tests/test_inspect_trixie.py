"""Offline identity, scope and partial-evidence checks; never contacts a node."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/inspect-trixie.py'
SPEC = importlib.util.spec_from_file_location('inspect_trixie', SCRIPT)
ENGINE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ENGINE)
RELEASE = 'ID=debian\nVERSION_ID="13"\nVERSION_CODENAME=trixie\n'
UUID = 'c531566d-83b0-4fe1-9582-9a4588f05916'


class InspectionTests(unittest.TestCase):
    def test_identity_success_and_rejections(self):
        self.assertEqual(ENGINE.check_identity('j2-svntp1', RELEASE, 'aarch64', 1000)['os']['ID'], 'debian')
        for host, release, arch, uid in (
                ('j1-svntp', RELEASE, 'aarch64', 1000),
                ('j2-svntp1', RELEASE.replace('13', '11'), 'aarch64', 1000),
                ('j2-svntp1', RELEASE.replace('trixie', 'bullseye'), 'aarch64', 1000),
                ('j2-svntp1', RELEASE, 'x86_64', 1000),
                ('j2-svntp1', RELEASE, 'aarch64', 0),
                ('j2-svntp1', RELEASE + 'ID=debian\n', 'aarch64', 1000)):
            with self.subTest(host=host, uid=uid), self.assertRaises(ValueError):
                ENGINE.check_identity(host, release, arch, uid)

    def test_wrong_host_runs_no_commands(self):
        with patch.object(ENGINE.socket, 'gethostname', return_value='j1-svntp'), \
                patch.object(ENGINE, 'read_file', return_value=RELEASE.encode()), \
                patch.object(ENGINE.os, 'uname') as uname, \
                patch.object(ENGINE.os, 'geteuid', return_value=1000), \
                patch.object(ENGINE.subprocess, 'run') as run:
            uname.return_value.machine = 'aarch64'
            for collector in (ENGINE.inspect, ENGINE.package_policy):
                with self.assertRaises(ValueError):
                    collector()
            run.assert_not_called()

    def test_policy_is_data_and_symlinks_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            policy = Path(directory) / 'policy.conf'
            source = "$nrconf{restart} = 'a';\nsystem('touch /tmp/never-execute-policy');\n"
            policy.write_text(source)
            link = Path(directory) / 'policy-link.conf'
            link.symlink_to(policy)
            with patch.object(ENGINE.subprocess, 'run') as run:
                records = ENGINE.policy_snapshot([policy, link, Path(directory) / 'missing'])
            run.assert_not_called()
            self.assertIn("system('touch", records[0]['text'])
            self.assertIn('error', records[1])
            self.assertTrue(records[2]['absent'])

    def test_policy_redacts_credentials_but_retains_restart_assignment(self):
        text = "Acquire::http::Proxy \"http://alice:credential@proxy.example/\";\n"
        text += "$nrconf{restart} = 'l';\nPassword \"private-value\";\n"
        text += 'Acquire::http::ProxyPassword "compound-field-value";\n'
        text += 'URI "https://example.org/?token=query-value";\n'
        result = ENGINE.redact_policy(text)
        self.assertNotIn('credential@', result)
        self.assertNotIn('private-value', result)
        self.assertNotIn('compound-field-value', result)
        self.assertNotIn('query-value', result)
        self.assertIn("$nrconf{restart} = 'l';", result)

    def test_package_policy_retains_drift_and_never_runs_needrestart_or_apt_get(self):
        calls = []

        def command(argv):
            calls.append(argv)
            return {'argv': argv, 'rc': 0, 'stdout': '', 'stderr': '',
                    'error': None, 'truncated': False}

        snapshots = [[{'path': '/etc/needrestart/needrestart.conf', 'sha256': 'before',
                       'text': "$nrconf{restart}='a';"}],
                     [{'path': '/etc/needrestart/needrestart.conf', 'sha256': 'after',
                       'text': "$nrconf{restart}='l';"}]]
        with patch.object(ENGINE.socket, 'gethostname', return_value='j2-svntp1'), \
                patch.object(ENGINE, 'read_file', side_effect=lambda path:
                    RELEASE.encode() if str(path)=='/etc/os-release' else b'boot-fixture'), \
                patch.object(ENGINE.os, 'uname', return_value=SimpleNamespace(
                    machine='aarch64', release='fixture-v8')), \
                patch.object(ENGINE.os, 'geteuid', return_value=1000), \
                patch.object(ENGINE, 'policy_files', return_value=[]), \
                patch.object(ENGINE, 'policy_snapshot', side_effect=snapshots), \
                patch.object(ENGINE, 'run', side_effect=command):
            report = ENGINE.package_policy()
        self.assertTrue(report['policy_drift'])
        self.assertTrue(report['collection_has_gaps'])
        self.assertFalse(report['effective_policy_accepted'])
        self.assertFalse(report['package_mutation_authorized'])
        self.assertIn("restart}='l'", report['policy_after'][0]['text'])
        self.assertTrue(all(argv[0] in ('dpkg-query', 'apt-cache', 'dpkg', 'systemctl', 'man')
                            for argv in calls))
        cached = next(argv for argv in calls if argv[0]=='apt-cache')
        self.assertIn('Dir::Cache::pkgcache=', cached)
        self.assertIn('Dir::Cache::srcpkgcache=', cached)
        self.assertIn('needrestart', cached)

    def test_command_results_missing_timeout_and_truncation(self):
        with patch.object(ENGINE.subprocess, 'run', return_value=subprocess.CompletedProcess(
                ['fixture'], 3, b'partial', b'permission denied')):
            result = ENGINE.run(['fixture'])
            self.assertEqual((result['rc'], result['stdout'], result['stderr']),
                             (3, 'partial', 'permission denied'))
        with patch.object(ENGINE.subprocess, 'run', side_effect=FileNotFoundError('missing')):
            self.assertEqual(ENGINE.run(['fixture'])['rc'], 127)
        timeout = subprocess.TimeoutExpired(['fixture'], 12, output=b'partial', stderr=b'error')
        with patch.object(ENGINE.subprocess, 'run', side_effect=timeout):
            self.assertEqual(ENGINE.run(['fixture'])['stdout'], 'partial')
            self.assertEqual(ENGINE.run(['fixture'])['rc'], 124)
        with patch.object(ENGINE.subprocess, 'run', return_value=subprocess.CompletedProcess(
                ['fixture'], 0, b'x' * (ENGINE.LIMIT + 1), b'')):
            result = ENGINE.run(['fixture'])
            self.assertTrue(result['truncated'])
            self.assertEqual(len(result['stdout']), ENGINE.LIMIT)

    def test_source_projection_never_retains_uri_credentials(self):
        text = 'URIs: https://alice:secret@example.org/private-token?password=secret#fragment\n'
        result = ENGINE.source_hosts(text)
        self.assertEqual(result, [{'scheme': 'https', 'hostname': 'example.org'}])
        self.assertNotIn('secret', str(result))
        self.assertNotIn('private-token', str(result))
        self.assertEqual(ENGINE.source_fields('Suites: trixie\nPassword: secret\n'),
                         ['Suites: trixie'])

    def test_collection_retains_missing_tool_and_file_drift(self):
        reads = {}
        manager_active = True

        def file_read(path):
            name = str(path)
            reads[name] = reads.get(name, 0) + 1
            if name == '/etc/os-release':
                return RELEASE.encode()
            if name == '/boot/firmware/config.txt':
                return b'enable_uart=1\n' if reads[name] == 1 else b'enable_uart=0\n'
            return b'fixture'

        def command(argv, seconds):
            if argv[0] == 'vcgencmd':
                return {'argv': argv, 'rc': 127, 'stdout': '', 'stderr': 'missing',
                        'error': 'unavailable', 'truncated': False}
            out = UUID + ':802-3-ethernet:eth0\n' if '--active' in argv else 'fixture'
            if argv[0] == 'systemctl' and 'show' in argv:
                out = 'Id=NetworkManager.service\nActiveState=' + (
                    'active' if manager_active else 'inactive') + '\n'
            return {'argv': argv, 'rc': 0, 'stdout': out, 'stderr': '',
                    'error': None, 'truncated': False}

        for manager_active in (True, False):
            reads.clear()
            with self.subTest(manager_active=manager_active), \
                    patch.object(ENGINE.socket, 'gethostname', return_value='j2-svntp1'), \
                    patch.object(ENGINE, 'read_file', side_effect=file_read), \
                    patch.object(ENGINE.os, 'uname', return_value=SimpleNamespace(
                        machine='aarch64', release='fixture')), \
                    patch.object(ENGINE.os, 'geteuid', return_value=1000), \
                    patch.object(ENGINE.Path, 'glob', return_value=[]), \
                    patch.object(ENGINE, 'run', side_effect=command) as runner:
                report = ENGINE.inspect()
            self.assertTrue(report['collection_has_gaps'])
            self.assertFalse(report['platform_or_service_accepted'])
            self.assertEqual(report['file_hash_drift'], ['/boot/firmware/config.txt'])
            self.assertTrue(any(r['rc'] == 127 for r in report['commands']))
            if manager_active:
                self.assertEqual(report['commands'][-1]['label'], 'ethernet_profile')
            else:
                self.assertIsNotNone(report['profile_error'])
                calls = [call.args[0] for call in runner.call_args_list]
                self.assertFalse(any('--active' in argv or 'device' in argv or 'radio' in argv
                                     for argv in calls))

    def test_active_profile_must_be_unambiguous_ethernet_uuid(self):
        record = {'rc': 0, 'stdout': UUID + ':802-3-ethernet:eth0\n', 'stderr': '', 'truncated': False}
        self.assertEqual(ENGINE.ethernet_uuid(record), UUID)
        for change in ({'rc': 1}, {'stdout': ''}, {'stdout': record['stdout'] * 2},
                       {'stdout': 'bad:802-3-ethernet:eth0'}, {'truncated': True},
                       {'stdout': UUID + ':802-11-wireless:eth0'}, {'stderr': 'warning'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                ENGINE.ethernet_uuid({**record, **change})

    def test_commands_avoid_remote_access_mutation_and_secret_exports(self):
        for label, argv in ENGINE.COMMANDS:
            with self.subTest(label=label):
                self.assertNotIn(argv[0], ('sudo', 'ssh', 'curl', 'wget', 'apt', 'apt-get'))
                self.assertNotIn('--show-secrets', argv)
                if argv[0] == 'nmcli':
                    self.assertNotIn('all', argv)
                    self.assertNotIn('on', argv)
                    self.assertNotIn('off', argv)
                if argv[0] == 'vcgencmd':
                    self.assertIn(argv[1], ('version', 'get_throttled', 'measure_temp'))
        self.assertNotIn('802-11-wireless-security', ENGINE.PROFILE_FIELDS)
        self.assertNotIn('802-1x', ENGINE.PROFILE_FIELDS)


if __name__ == '__main__':
    unittest.main()
