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
    def test_explicit_fresh_target_identity_remains_bound(self):
        self.assertEqual(ENGINE.check_identity('fresh-node', RELEASE, 'aarch64', 1000,
                                             expected_hostname='fresh-node')['hostname'], 'fresh-node')
        with self.assertRaises(ValueError):
            ENGINE.check_identity('other-node', RELEASE, 'aarch64', 1000, expected_hostname='fresh-node')

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


class KeyringHookTests(unittest.TestCase):
    def test_binary_keys_and_compressed_manual_are_data(self):
        with tempfile.TemporaryDirectory() as directory:
            key = Path(directory) / 'archive.pgp'
            key.write_bytes(b'public-key-fixture')
            manual = Path(directory) / 'manual.gz'
            manual.write_bytes(ENGINE.gzip.compress(b'Never execute system("touch /tmp/unsafe")'))
            alias = Path(directory) / 'alias.pgp'
            alias.symlink_to(key)
            with patch.object(ENGINE.subprocess, 'run') as run:
                records = ENGINE.policy_snapshot([key, manual, alias], (str(key),), True)
            run.assert_not_called()
            self.assertEqual(ENGINE.base64.b64decode(records[0]['public_keyring_base64']),
                             b'public-key-fixture')
            self.assertIn('Never execute system', records[1]['text'])
            self.assertIn('error', records[2])
            manual.write_bytes(ENGINE.gzip.compress(b'x' * 262145))
            self.assertIn('error', ENGINE.policy_snapshot([manual], compressed_documents=True)[0])
            manual.write_bytes(ENGINE.gzip.compress(b'fixture')[:12])
            self.assertIn('error', ENGINE.policy_snapshot([manual], compressed_documents=True)[0])

    def test_package_modules_have_a_fixed_path_boundary(self):
        listing = ('/usr/share/apt-listchanges/frontend.py\n'
                   '/usr/lib/python3/dist-packages/apt_listchanges/apt_listchanges.py\n'
                   '/usr/share/perl5/Debconf/Config.pm\n'
                   '/tmp/credentials.py\n/etc/shadow\n')
        with patch.object(ENGINE, 'policy_files', return_value=[]), \
                patch.object(ENGINE.Path, 'glob', return_value=[]):
            paths = list(map(str, ENGINE.keyring_hook_files(listing)))
            with self.assertRaises(ValueError):
                ENGINE.keyring_hook_files('/usr/share/apt-listchanges/../secret.py')
        self.assertIn('/usr/share/apt-listchanges/frontend.py', paths)
        self.assertIn('/usr/lib/python3/dist-packages/apt_listchanges/apt_listchanges.py', paths)
        self.assertIn('/usr/share/perl5/Debconf/Config.pm', paths)
        self.assertNotIn('/tmp/credentials.py', paths)
        self.assertNotIn('/etc/shadow', paths)
        self.assertTrue(set(ENGINE.PUBLIC_KEYRINGS).issubset(paths))

    def test_wrong_host_precedes_queries_and_key_capture(self):
        with patch.object(ENGINE.socket, 'gethostname', return_value='j1-svntp'), \
                patch.object(ENGINE, 'read_file', return_value=RELEASE.encode()), \
                patch.object(ENGINE.os, 'uname', return_value=SimpleNamespace(machine='aarch64')), \
                patch.object(ENGINE.os, 'geteuid', return_value=1000), \
                patch.object(ENGINE, 'policy_snapshot') as snapshot, \
                patch.object(ENGINE, 'run') as run:
            with self.assertRaises(ValueError):
                ENGINE.keyring_hooks()
        run.assert_not_called()
        snapshot.assert_not_called()

    def test_collection_scope_success_and_drift_keep_acceptance_false(self):
        for changed in (False, True):
            calls = []
            keys = [{'path': p, 'sha256': 'fixture', 'public_keyring_base64': 'Zml4dHVyZQ=='}
                    for p in ENGINE.PUBLIC_KEYRINGS]

            def query(argv):
                calls.append(argv)
                return {'argv': argv, 'rc': 0, 'stdout': '', 'stderr': '',
                        'error': None, 'truncated': False}

            with self.subTest(changed=changed), \
                    patch.object(ENGINE.socket, 'gethostname', return_value='j2-svntp1'), \
                    patch.object(ENGINE, 'read_file', side_effect=lambda path:
                                 RELEASE.encode() if str(path) == '/etc/os-release' else b'boot-fixture'), \
                    patch.object(ENGINE.os, 'uname', return_value=SimpleNamespace(
                        machine='aarch64', release='fixture-v8')), \
                    patch.object(ENGINE.os, 'geteuid', return_value=1000), \
                    patch.object(ENGINE, 'keyring_hook_files', return_value=[]), \
                    patch.object(ENGINE, 'policy_snapshot', side_effect=[keys,
                                 [{**k, 'sha256': 'changed'} for k in keys] if changed
                                 else [dict(k) for k in keys]]), \
                    patch.object(ENGINE, 'run', side_effect=query):
                report = ENGINE.keyring_hooks()
            self.assertEqual(report['collection_has_gaps'], changed)
            self.assertEqual(report['input_drift'], changed)
            self.assertFalse(report['signature_trust_accepted'])
            self.assertFalse(report['effective_hook_policy_accepted'])
            self.assertFalse(report['package_mutation_authorized'])
            self.assertEqual(len(calls), 9)
            self.assertTrue(all(argv[0] in ('dpkg-query', 'dpkg', 'apt-get', 'systemctl')
                                for argv in calls))
            self.assertTrue(all(argv == ['apt-get', '--version']
                                for argv in calls if argv[0] == 'apt-get'))
            self.assertTrue(all('--verify' in argv or '--audit' in argv
                                for argv in calls if argv[0] == 'dpkg'))


class InstallationInputTests(unittest.TestCase):
    def test_pgp_keyrings_are_captured_without_following_gpg_aliases(self):
        with tempfile.TemporaryDirectory() as directory:
            keydir = Path(directory) / 'keyrings'
            keydir.mkdir()
            key = keydir / 'archive.pgp'
            key.write_bytes(b'public-key-fixture')
            alias = keydir / 'archive.gpg'
            alias.symlink_to(key)

            def glob(path, pattern):
                if str(path) == '/usr/share/keyrings':
                    return [key] if pattern == '*.pgp' else [alias] if pattern == '*.gpg' else []
                return []

            with patch.object(ENGINE.Path, 'glob', glob), \
                    patch.object(ENGINE, 'read_file', return_value=b'public-key-fixture'):
                records = {p['path']: p for p in ENGINE.input_metadata()}
            self.assertEqual(records[str(key)]['sha256'],
                             ENGINE.hashlib.sha256(b'public-key-fixture').hexdigest())
            self.assertIn('error', records[str(alias)])

    def test_mail_fields_omit_credentials_and_executable_directives(self):
        text = ('defaults\naccount apprise\nhost relay.example\nport 8025\n'
                'password sensitive-value\npasswordeval /tmp/never-execute\n'
                'include /tmp/never-read\nauth off\ntls off\n')
        with patch.object(ENGINE.subprocess, 'run') as run:
            result = ENGINE.mail_account_fields(text)
        run.assert_not_called()
        self.assertIn('host relay.example', result)
        self.assertNotIn('sensitive-value', str(result))
        self.assertNotIn('/tmp/never-', str(result))
        self.assertEqual(result.count('[unreviewed directive value omitted]'), 3)

    def test_baseline_and_reviewed_needrestart_dependencies_are_in_scope(self):
        required = {'apt', 'ntpsec', 'gpsd', 'gpsd-clients', 'pps-tools', 'i2c-tools',
                    'webmin', 'munin-node', 'watchdog', 'needrestart', 'msmtp',
                    'msmtp-mta', 'cron', 'coreutils', 'util-linux', 'ca-certificates',
                    'perl', 'dpkg', 'gettext-base', 'libintl-perl',
                    'libproc-processtable-perl', 'libsort-naturally-perl',
                    'libterm-readkey-perl', 'libmodule-find-perl', 'procps', 'xz-utils'}
        self.assertTrue(required.issubset(ENGINE.BASELINE_PACKAGES))

    def test_identity_rejection_precedes_input_reads(self):
        with patch.object(ENGINE.socket, 'gethostname', return_value='j1-svntp'), \
                patch.object(ENGINE, 'read_file', return_value=RELEASE.encode()), \
                patch.object(ENGINE.os, 'uname', return_value=SimpleNamespace(machine='aarch64')), \
                patch.object(ENGINE.os, 'geteuid', return_value=1000), \
                patch.object(ENGINE, 'installation_input_files') as files, \
                patch.object(ENGINE, 'input_metadata') as metadata, \
                patch.object(ENGINE, 'run') as run:
            with self.assertRaises(ValueError):
                ENGINE.package_policy(input_review=True)
        files.assert_not_called()
        metadata.assert_not_called()
        run.assert_not_called()

    def test_metadata_drift_and_query_failure_are_retained(self):
        calls = []

        def query(argv):
            calls.append(argv)
            return {'argv': argv, 'rc': 1 if argv[:2] == ['dpkg-query', '-S'] else 0,
                    'stdout': '', 'stderr': '', 'error': None, 'truncated': False}

        with patch.object(ENGINE.socket, 'gethostname', return_value='j2-svntp1'), \
                patch.object(ENGINE, 'read_file', side_effect=lambda path:
                             RELEASE.encode() if str(path) == '/etc/os-release' else b'boot-fixture'), \
                patch.object(ENGINE.os, 'uname', return_value=SimpleNamespace(
                    machine='aarch64', release='fixture-v8')), \
                patch.object(ENGINE.os, 'geteuid', return_value=1000), \
                patch.object(ENGINE, 'installation_input_files', return_value=[]), \
                patch.object(ENGINE, 'policy_snapshot', return_value=[]), \
                patch.object(ENGINE, 'input_metadata', side_effect=[
                    [{'path': '/boot/vmlinuz-fixture-v8', 'size': 1}], []]), \
                patch.object(ENGINE, 'run', side_effect=query):
            report = ENGINE.package_policy(input_review=True)
        self.assertEqual(report['mode'], 'installation_inputs')
        self.assertTrue(report['input_metadata_drift'])
        self.assertTrue(report['collection_has_gaps'])
        self.assertFalse(report['package_mutation_authorized'])
        self.assertFalse(report['effective_policy_accepted'])
        self.assertEqual(len(calls), 14)
        self.assertTrue(all(argv[0] in ('dpkg-query', 'dpkg', 'apt-cache', 'systemctl', 'man')
                            for argv in calls))
        for argv in calls:
            if argv[0] == 'apt-cache':
                self.assertIn('Dir::Cache::pkgcache=', argv)
                self.assertIn('Dir::Cache::srcpkgcache=', argv)
                self.assertTrue('policy' in argv or 'depends' in argv)
        self.assertFalse(any('sudo' in argv or 'apt-get' == argv[0] for argv in calls))


if __name__ == '__main__':
    unittest.main()
