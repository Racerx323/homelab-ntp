"""Offline isolation, byte/time bounds, trust and dependency-closure checks."""
import importlib.util
import base64
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import tarfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HELPER = load('inspect_trixie', 'inspect-trixie.py')
with patch.dict(sys.modules, {'inspect_trixie': HELPER}):
    ENGINE = load('resolve_trixie', 'resolve-trixie-packages.py')
CLIENT = load('resolution_client', 'run-package-resolution.py')


class ResolutionTests(unittest.TestCase):
    def test_remaining_modules_replay_retained_v3_listing(self):
        listing = (Path(__file__).parent / 'fixtures/remaining-module-listing.txt').read_text()
        with patch.object(HELPER, 'policy_files', return_value=[]):
            with self.assertRaisesRegex(ValueError, '128-file bound'):
                HELPER.keyring_hook_files(listing)
        paths = ENGINE.remaining_module_paths(listing + listing)
        self.assertEqual(len(paths), 13)
        self.assertTrue(all(str(p).startswith('/usr/lib/python3/dist-packages/apt_listchanges/')
                            and p.suffix == '.py' for p in paths))
        self.assertEqual(paths, sorted(set(paths)))

    def test_remaining_module_bound_and_traversal(self):
        prefix = '/usr/lib/python3/dist-packages/apt_listchanges/'
        listing = '\n'.join(prefix + str(i) + '.py' for i in range(128))
        self.assertEqual(len(ENGINE.remaining_module_paths(listing)), 128)
        for invalid in ('', '/usr/share/perl5/Debconf/Config.pm',
                        listing + '\n' + prefix + 'extra.py',
                        prefix + '../outside.py', prefix + 'ok.py\n/ignored/../escape'):
            with self.subTest(listing=invalid), self.assertRaises(ValueError):
                ENGINE.remaining_module_paths(invalid)

    def test_source_applications_rejected_before_solver(self):
        for package in ('ntpsec', 'ntpsec-ntpq:arm64', 'gpsd', 'gpsd-clients', 'python3-gps', 'ntp'):
            with self.assertRaises(ValueError):
                ENGINE.dependency_plan(None, [package], '', set())
        ENGINE.reject_package_applications(['pps-tools', 'i2c-tools', 'scons', 'libssl-dev'])

    def test_transitive_source_application_rejected(self):
        cache = self.make_cache()
        cache.get_changes()[0].candidate.package.shortname = 'gpsd'
        with self.assertRaisesRegex(ValueError, 'source-built application'):
            ENGINE.dependency_plan(cache, ['seed'], '', set())

    def test_isolated_configuration_excludes_real_state_and_hooks(self):
        text, values = ENGINE.apt_configuration(Path('/var/tmp/ntp-metadata-fixture'))
        ENGINE.verify_config(text, values)
        ENGINE.verify_config(text.replace('Acquire::Languages "none";',
                                          'Acquire::Languages "";\nAcquire::Languages:: "none";'), values)
        self.assertNotIn('/var/lib/apt', text)
        self.assertNotIn('/var/lib/dpkg', text)
        self.assertEqual(values['Dir::Bin::dpkg'], '/bin/false')
        self.assertEqual(values['APT::Sandbox::User'], '_apt')
        self.assertEqual(values['Acquire::Check-Valid-Until'], 'true')
        self.assertEqual(values['APT::Install-Recommends'], 'true')
        with self.assertRaises(ValueError):
            ENGINE.verify_config(text + 'APT::Update::Post-Invoke { "touch /tmp/unsafe"; };', values)
        with self.assertRaises(ValueError):
            ENGINE.verify_config(text + 'Acquire::Languages:: "en";', values)
        with self.assertRaises(ValueError):
            ENGINE.verify_config(text.replace('"/bin/false"', '"/usr/bin/dpkg"'), values)

    def test_process_output_and_timeout_bounds(self):
        env = {'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'}
        result = ENGINE.command(['/usr/bin/python3', '-I', '-B', '-c', 'print("complete")'],
                                env, time.monotonic() + 5)
        self.assertEqual((result['rc'], result['output'], result['error']), (0, 'complete\n', None))
        with patch.object(ENGINE, 'OUTPUT_LIMIT', 64):
            result = ENGINE.command(['/usr/bin/python3', '-I', '-B', '-c', 'print("x"*1000)'],
                                    env, time.monotonic() + 5)
        self.assertEqual(result['error'], 'output_limit')
        self.assertEqual(len(result['output']), 64)
        result = ENGINE.command(['/usr/bin/python3', '-I', '-B', '-c', 'import time; time.sleep(5)'],
                                env, time.monotonic() + 5, seconds=0.1)
        self.assertEqual(result['error'], 'timeout')

    def test_index_trust_completeness_and_path_boundaries(self):
        with tempfile.TemporaryDirectory() as directory:
            lists = Path(directory) / 'lists'
            lists.mkdir()
            spec = {'releases': [{'base_uri': 'http://repo.test/debian', 'suite': 'trixie',
                                 'codename': 'trixie', 'components': ['main']}]}
            blocks = []
            for arch in ('arm64', 'armhf'):
                path = lists / ('Packages-' + arch)
                path.write_bytes(b'authenticated-index-fixture')
                blocks.append('Identifier: Packages\nTrusted: yes\nCodename: trixie\n'
                              'Component: main\nArchitecture: ' + arch + '\nFilename: ' + str(path) +
                              '\nURI: http://repo.test/debian/dists/trixie/main/binary-' + arch + '/Packages')
            text = '\n\n'.join(blocks)
            self.assertEqual(len(ENGINE.authenticated_indexes(text, lists, spec)), 2)
            for invalid in (blocks[0], text.replace('Trusted: yes', 'Trusted: no'),
                            text.replace('Codename: trixie', 'Codename: other'),
                            text.replace(str(lists), directory)):
                with self.assertRaises(ValueError):
                    ENGINE.authenticated_indexes(invalid, lists, spec)

    def test_native_simulation_rejects_removals_and_unknown_shapes(self):
        self.assertEqual(ENGINE.simulated_changes('Inst seed (1.0 Debian:13/stable [all])\n'),
                         {('seed', '1.0', 'all')})
        self.assertEqual(ENGINE.simulated_changes('Inst libx:arm64 [0.9] (1.0 Debian:13/stable [arm64])'),
                         {('libx', '1.0', 'arm64')})
        for text in ('Remv time-daemon\n', 'Inst unparsed\n'):
            with self.assertRaises(ValueError):
                ENGINE.simulated_changes(text)

    def test_signed_release_shape_identity_and_expiry(self):
        with tempfile.TemporaryDirectory() as directory:
            lists = Path(directory)
            path = lists / 'repo.test_debian_dists_trixie_InRelease'
            spec = {'releases': [{'base_uri': 'http://repo.test/debian', 'suite': 'trixie',
                                 'codename': 'trixie', 'origin': 'Debian', 'release_suite': 'stable'}]}
            # Shape/date parser fixture only. Native APT authenticates real inputs.
            body = ('-----BEGIN PGP SIGNED MESSAGE-----\nHash: SHA256\n\n'
                    'Origin: Debian\nSuite: stable\nCodename: trixie\n'
                    'Date: Sat, 10 Oct 2026 00:00:00 UTC\n'
                    'Valid-Until: Sat, 17 Oct 2026 00:00:00 UTC\n'
                    '-----BEGIN PGP SIGNATURE-----\nfixture\n-----END PGP SIGNATURE-----\n')
            path.write_text(body)
            now = ENGINE.parsedate_to_datetime('Sat, 10 Oct 2026 12:00:00 UTC').timestamp()
            self.assertEqual(len(ENGINE.release_evidence(lists, spec, now)), 1)
            for invalid in (body.replace('Origin: Debian', 'Origin: other'),
                            body.replace('Codename: trixie', 'Codename: other'),
                            body.replace('17 Oct', '09 Oct'), body.replace('PGP SIGNED MESSAGE', 'unsigned')):
                path.write_text(invalid)
                with self.assertRaises(ValueError):
                    ENGINE.release_evidence(lists, spec, now)

    def make_cache(self, trusted=True, missing=False):
        def package(name, arch):
            p = SimpleNamespace(shortname=name, marked_delete=False, marked_install=False,
                                marked_upgrade=False, marked_downgrade=False, marked_reinstall=False)
            v = SimpleNamespace(package=p, version='1.0', architecture=arch,
                                origins=[SimpleNamespace(site='repo.test', origin='Debian', label='Debian',
                                                         archive='stable', component='main', trusted=trusted)],
                                sha256='a' * 64, uri='http://repo.test/debian/pool/' + name + '.deb',
                                record='Package: ' + name, get_dependencies=lambda *k: [])
            p.candidate = v
            p.installed = v
            return p
        seed = package('seed', 'all')
        seed.installed = None
        leaf = package('leaf', 'arm64')
        base = package('base', 'arm64')
        alternative = lambda v: SimpleNamespace(rawtype='Depends', rawstr=v.package.shortname,
                                               target_versions=[] if missing else [v])
        seed.candidate.get_dependencies = lambda *k: [SimpleNamespace(or_dependencies=[alternative(leaf.installed)])]
        leaf.installed.get_dependencies = lambda *k: [SimpleNamespace(or_dependencies=[alternative(base.installed)])]
        seed.mark_install = lambda: setattr(seed, 'marked_install', True)

        class Cache:
            broken_count = 0
            def clear(self):
                seed.marked_install = False
            def __getitem__(self, name):
                return {'seed:arm64': seed}[name]
            def get_changes(self):
                return [seed]
            def commit(self):
                raise AssertionError('installation forbidden')
        return Cache()

    def test_dependency_graph_retains_installed_transitive_satisfiers(self):
        plan = ENGINE.dependency_plan(self.make_cache(), ['seed'],
                                      'Inst seed (1.0 Debian:13/stable [all])', {'repo.test'})
        self.assertEqual({v['package'] for v in plan['versions']}, {'seed', 'leaf', 'base'})
        self.assertEqual(plan['changes'], [['seed', '1.0', 'all']])
        self.assertTrue(plan['recommends_enabled'])
        self.assertFalse(next(v for v in plan['versions'] if v['package'] == 'leaf')['changed'])

    def test_solver_disagreement_untrusted_archive_and_missing_dependencies_fail(self):
        for cache, native in ((self.make_cache(), 'Inst seed (2.0 Debian:13/stable [all])'),
                              (self.make_cache(trusted=False), 'Inst seed (1.0 Debian:13/stable [all])'),
                              (self.make_cache(missing=True), 'Inst seed (1.0 Debian:13/stable [all])')):
            with self.assertRaises(ValueError):
                ENGINE.dependency_plan(cache, ['seed'], native, {'repo.test'})

    def test_caller_rejection_precedes_queries_and_workspace(self):
        with patch.object(ENGINE.os, 'geteuid', return_value=1000), \
                patch.object(ENGINE, 'command') as command, \
                patch.object(ENGINE.tempfile, 'mkdtemp') as mkdir:
            with self.assertRaises(ValueError):
                ENGINE.run({'caller_uid': 1000}, int(time.time()))
        command.assert_not_called()
        mkdir.assert_not_called()

    def test_cleanup_requires_exact_owned_directory_and_never_follows_alias(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory) / 'owned'
            work.mkdir()
            (work / 'keep').write_text('fixture')
            st = work.stat()
            identity = (st.st_dev, st.st_ino, st.st_uid)
            alias = Path(directory) / 'alias'
            alias.symlink_to(work, target_is_directory=True)
            for path, expected in ((work, (st.st_dev, st.st_ino + 1, st.st_uid)), (alias, identity)):
                with self.assertRaises(ValueError):
                    ENGINE.owned_cleanup(path, expected)
            self.assertTrue((work / 'keep').exists())
            ENGINE.owned_cleanup(work, identity)
            self.assertFalse(work.exists())

    def test_pre_refresh_failure_cleans_only_the_new_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            work = base / 'workspace'
            status = base / 'status'; status.write_text('installed-state fixture')
            extended = base / 'extended_states'; extended.write_text('auto-state fixture')
            key = base / 'publisher.pgp'; key.write_bytes(b'public fixture')
            source = base / 'debian.sources'; source.write_text('Signed-By: ' + str(key))
            spec = {'caller_uid': 1000, 'kernel': 'fixture-v8', 'input_hashes': {}, 'input_metadata': {}, 'absent_inputs': [],
                    'expected_config_paths': [], 'groups': {}, 'verify_packages': ['fixture'],
                    'expected_version_lines': [], 'source_files': [str(source)]}
            calls = []

            def query(argv, env, deadline, seconds=60, on_spawn=None):
                calls.append(argv)
                output = ('arm64\n' if '--print-architecture' in argv else
                          'armhf\n' if '--print-foreign-architectures' in argv else
                          'ActiveState=inactive\nActiveState=inactive\n' if 'systemctl' in argv[0] else
                          '/usr/lib/python3/dist-packages/apt_listchanges/main.py\n' if '-L' in argv else '')
                return {'argv': argv, 'rc': 0, 'output': output, 'error': None}

            def mkdir(**kwargs):
                work.mkdir(mode=0o700)
                return str(work)

            real_read = HELPER.read_file
            real_lstat = Path.lstat
            def lstat(path):
                result = real_lstat(path)
                if str(path) == '/var/tmp':
                    fields = list(result); fields[4] = 0
                    return type(result)(fields)
                return result
            with patch.object(ENGINE.os, 'geteuid', return_value=0), \
                    patch.dict(ENGINE.os.environ, {'SUDO_USER': 'ama', 'SUDO_UID': '1000'}), \
                    patch.object(ENGINE.sys, 'dont_write_bytecode', True), \
                    patch.object(ENGINE.socket, 'gethostname', return_value='j2-svntp1'), \
                    patch.object(ENGINE.os, 'uname', return_value=SimpleNamespace(machine='aarch64', release='fixture-v8')), \
                    patch.object(HELPER, 'read_file', side_effect=lambda p:
                                 b'ID=debian\nVERSION_ID="13"\nVERSION_CODENAME=trixie\n'
                                 if str(p) == '/etc/os-release' else b'boot-fixture'
                                 if str(p).startswith('/proc/') else real_read(p)), \
                    patch.object(HELPER, 'keyring_hook_files', return_value=[]), \
                    patch.object(HELPER, 'policy_snapshot', return_value=[{'path': 'fixture', 'text': 'data only'}]), \
                    patch.object(HELPER, 'PUBLIC_KEYRINGS', (str(key),)), \
                    patch.object(ENGINE, 'STATE_FILES', (str(status), str(extended))), \
                    patch.object(ENGINE.shutil, 'disk_usage', return_value=SimpleNamespace(free=2**31)), \
                    patch.object(ENGINE.Path, 'lstat', lstat), \
                    patch.object(ENGINE.tempfile, 'mkdtemp', side_effect=mkdir), \
                    patch.object(ENGINE, 'command', side_effect=query):
                report = ENGINE.run(spec, int(time.time()))
                self.assertFalse(work.exists())
                with patch.object(ENGINE, 'owned_cleanup', side_effect=ValueError('ownership refusal')):
                    refused = ENGINE.run(spec, int(time.time()))
            self.assertEqual(report['state'], 'held')
            self.assertFalse(report['refresh_started'])
            self.assertTrue(report['workspace_cleaned'])
            self.assertFalse(refused['workspace_cleaned'])
            self.assertTrue(refused['manual_intervention_required'])
            self.assertTrue(work.exists())
            self.assertEqual(status.read_text(), 'installed-state fixture')
            self.assertFalse(any('update' in argv for argv in calls))

    def test_workstation_hash_and_paste_rejection_precede_submission(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            key = b'fixture-public-key'
            fingerprint = 'SHA256:' + base64.b64encode(hashlib.sha256(key).digest()).decode().rstrip('=')
            known = ('10.1.0.137 ssh-ed25519 ' + base64.b64encode(key).decode() + '\n').encode()
            members = {'operator-paste.txt': b'# offline fixture\n', 'known_hosts': known,
                       'spec.json': json.dumps({'groups': {'diagnostics': ['pps-tools']}}).encode(),
                       'run-package-resolution.py': (SCRIPTS / 'run-package-resolution.py').read_bytes()}
            argv = ['timeout', '--signal=TERM', '--kill-after=5s', '840s', 'ssh', '-T']
            for option in ('BatchMode=yes', 'StrictHostKeyChecking=yes', 'HostKeyAlgorithms=ssh-ed25519',
                           'UpdateHostKeys=no', 'ProxyCommand=none', 'ProxyJump=none', 'ControlMaster=no',
                           'ControlPath=none', 'ControlPersist=no', 'PermitLocalCommand=no',
                           'ClearAllForwardings=yes', 'ForwardAgent=no', 'ForwardX11=no',
                           'GlobalKnownHostsFile=/dev/null',
                           'UserKnownHostsFile=' + str(base / 'metadata-resolution-known-hosts')):
                argv += ['-o', option]
            argv += ['ama@10.1.0.137', 'cd / && sudo -n /usr/bin/python3 -I -B - --controller-epoch @CONTROLLER_EPOCH@']
            manifest = {'transport_argv': argv,
                        'members': {k: hashlib.sha256(v).hexdigest() for k, v in members.items()}}
            members['manifest.json'] = json.dumps(manifest).encode()
            bundle = base / 'fixture.tar'
            with tarfile.open(bundle, 'w') as archive:
                for name, data in members.items():
                    info = tarfile.TarInfo(name); info.size = len(data)
                    archive.addfile(info, io.BytesIO(data))
            digest = hashlib.sha256(bundle.read_bytes()).hexdigest()
            (base / 'metadata-resolution-paste.txt').write_bytes(members['operator-paste.txt'])
            (base / 'metadata-resolution-known-hosts').write_bytes(known)
            with patch.object(CLIENT.subprocess, 'run') as submit:
                self.assertEqual(CLIENT.prepare(bundle, digest, fingerprint)['transport_argv'], argv)
                with self.assertRaises(ValueError):
                    CLIENT.prepare(bundle, '0' * 64, fingerprint)
                (base / 'metadata-resolution-paste.txt').write_text('changed')
                with self.assertRaises(ValueError):
                    CLIENT.prepare(bundle, digest, fingerprint)
            submit.assert_not_called()


if __name__ == '__main__':
    unittest.main()
