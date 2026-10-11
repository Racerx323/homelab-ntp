#!/usr/bin/python3
"""Offline source/staging/install rejection, rollback, PPS and pair lifecycle tests."""
import copy
import importlib.util
import io
import json
import os
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import stat
import subprocess
import tarfile
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch


SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CLOCK = load('clockmaker')
PIN = load('pinup')
SERVICE = load('timeservice')


def write_json(path, data):
    path.write_text(json.dumps(data))
    return CLOCK.digest(path.read_bytes())


def source_tar(name='waf', link=False, commit='a' * 40):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w', format=tarfile.PAX_FORMAT,
                      pax_headers={'comment': commit}) as archive:
        item = tarfile.TarInfo(name)
        if link:
            item.type = tarfile.SYMTYPE
            item.linkname = '/etc/passwd'
            archive.addfile(item)
        else:
            item.size = 1
            archive.addfile(item, io.BytesIO(b'x'))
    return output.getvalue()


class ClockmakerTests(unittest.TestCase):
    def test_standard_os_release_symlink_is_supported_but_other_targets_are_rejected(self):
        with patch.object(CLOCK.Path, 'is_symlink', return_value=True), \
                patch.object(CLOCK.Path, 'resolve', return_value=Path('/usr/lib/os-release')), \
                patch.object(CLOCK, 'regular_bytes', return_value=b'VERSION_ID="13"\n') as read, \
                patch.object(CLOCK.os, 'uname', return_value=SimpleNamespace(nodename='fixture', machine='aarch64')):
            CLOCK.target_identity('fixture')
            read.assert_called_once_with(Path('/usr/lib/os-release'))
        with patch.object(CLOCK.Path, 'is_symlink', return_value=True), \
                patch.object(CLOCK.Path, 'resolve', return_value=Path('/tmp/untrusted-release')):
            with self.assertRaises(ValueError):
                CLOCK.target_identity('fixture')

    def test_all_retained_flags_dispatch_to_the_correct_operation(self):
        operations = {'build': 'build', 'update': 'build', 'configure': 'configure',
                      'inspect': 'inspect_install', 'install': 'install', 'rollback': 'rollback'}
        for mode, operation in operations.items():
            aliases = [mode, '--' + mode, '-' + mode]
            if mode == 'configure':
                aliases += ['--config', '-config']
            for alias in aliases:
                with self.subTest(flag=alias):
                    argv = [alias, '--input', 'input.json', '--sha256', 'a' * 64]
                    if mode in ('build', 'update', 'configure'):
                        argv += ['--output', 'candidate']
                    if mode == 'install':
                        argv += ['--state', 'state.json', '--state-sha256', 'b' * 64,
                                 '--journal', 'journal', '--previous', 'old.json', '--previous-sha256', 'c' * 64]
                    with patch.object(CLOCK, operation, return_value={'fixture': True}) as handler, \
                            redirect_stdout(io.StringIO()) as stdout:
                        CLOCK.main(argv)
                    handler.assert_called_once()
                    self.assertEqual(json.loads(stdout.getvalue()), {'fixture': True})
                    if mode in ('build', 'update'):
                        self.assertEqual(handler.call_args.args[-1], mode == 'update')
                    if mode == 'install':
                        self.assertEqual(handler.call_args.args[-2:], (Path('old.json'), 'c' * 64))

    def test_flag_requirements_removed_modes_and_wrong_scope_fail(self):
        cases = [['--build'], ['--install'], ['--mask'], ['--secure'], ['--strip'],
                 ['inspect', '--output', 'ignored'], ['build', '--output', 'candidate', '--journal', 'wrong'],
                 ['inspect', '--previous', 'old.json']]
        for argv in cases:
            with self.subTest(argv=argv), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as exc:
                    CLOCK.parse_arguments(argv + ['--input', 'input.json', '--sha256', 'a' * 64])
                self.assertEqual(exc.exception.code, 2)

    def profile(self, base):
        archive = base / 'source.tar'
        archive.write_bytes(source_tar())
        source = {'origin': 'https://example.test/reviewed-source', 'release_tag': 'v1.0',
                  'commit': 'a' * 40, 'archive': archive.name,
                  'sha256': CLOCK.digest(archive.read_bytes()), 'options': []}
        return {'schema': 1, 'hostname': 'fixture', 'prefix': '/usr/local',
                'packages': {'build-essential': '1'},
                'helpers': {n + '.py': CLOCK.digest((SCRIPTS / (n + '.py')).read_bytes())
                            for n in ('clockmaker', 'pinup', 'timeservice')},
                'sources': {'gpsd': dict(source), 'ntpsec': dict(source)}}

    def test_archive_identity_traversal_and_links_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            for data, commit in ((source_tar('../escape'), 'a' * 40),
                                 (source_tar(link=True), 'a' * 40),
                                 (source_tar(), 'b' * 40)):
                with self.assertRaises(ValueError):
                    CLOCK.unpack_source(data, {'commit': commit, 'sha256': CLOCK.digest(data)}, Path(directory))
            self.assertFalse((Path(directory) / 'waf').exists())
            CLOCK.unpack_source(source_tar(), {'commit': 'a' * 40,
                                'sha256': CLOCK.digest(source_tar())}, Path(directory))
            self.assertEqual((Path(directory) / 'waf').read_bytes(), b'x')

    def test_publisher_archive_root_and_internal_source_link(self):
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode='w') as archive:
            file = tarfile.TarInfo('release/PIVOT.h')
            file.size = 1
            archive.addfile(file, io.BytesIO(b'x'))
            link = tarfile.TarInfo('release/include/PIVOT.h')
            link.type = tarfile.SYMTYPE
            link.linkname = '../PIVOT.h'
            archive.addfile(link)
        data = output.getvalue()
        source = {'archive_format': 'publisher-release', 'archive_root': 'release',
                  'commit': 'a' * 40, 'sha256': CLOCK.digest(data)}
        with tempfile.TemporaryDirectory() as directory:
            root = CLOCK.unpack_source(data, source, Path(directory))
            self.assertEqual(root, Path(directory) / 'release')
            self.assertEqual((root / 'include/PIVOT.h').read_bytes(), b'x')
        source['archive_root'] = 'wrong'
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(ValueError):
            CLOCK.unpack_source(data, source, Path(directory))

    def test_source_hardlinks_and_nonmember_symlinks_rejected(self):
        for kind, target in ((tarfile.LNKTYPE, 'file'), (tarfile.SYMTYPE, 'missing')):
            output = io.BytesIO()
            with tarfile.open(fileobj=output, mode='w', format=tarfile.PAX_FORMAT,
                              pax_headers={'comment': 'a' * 40}) as archive:
                item = tarfile.TarInfo('link'); item.type = kind; item.linkname = target
                archive.addfile(item)
            data = output.getvalue()
            with tempfile.TemporaryDirectory() as directory, self.assertRaises(ValueError):
                CLOCK.unpack_source(data, {'sha256': CLOCK.digest(data), 'commit': 'a' * 40}, Path(directory))

    def test_build_failure_stops_before_install_and_preserves_log(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            profile = base / 'profile.json'
            expected = write_json(profile, self.profile(base))
            output = base / 'candidate'
            def fail(argv, cwd, env, log):
                log.write_text('compile failed')
                raise subprocess.CalledProcessError(2, argv)
            with patch.object(CLOCK.os, 'geteuid', return_value=1000), \
                    patch.object(CLOCK, 'target_identity'), \
                    patch.object(CLOCK, 'require_no_package_applications'), \
                    patch.object(CLOCK.subprocess, 'check_output', return_value=b'1\tii '), \
                    patch.object(CLOCK, 'run', side_effect=fail) as run:
                with self.assertRaises(subprocess.CalledProcessError):
                    CLOCK.build(profile, expected, output)
            self.assertEqual(run.call_count, 1)
            self.assertTrue((output / 'build.log').exists())
            self.assertFalse((output / 'release.json').exists())

    def test_build_native_staging_and_configuration_preservation(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            profile = base / 'profile.json'
            build_profile = self.profile(base)
            build_profile['jobs'] = 2
            build_profile['python'] = {'executable': '/usr/bin/python3',
                'version': list(CLOCK.sys.version_info[:2]),
                'module_directory': CLOCK.sysconfig.get_path('purelib')}
            expected = write_json(profile, build_profile)
            existing = base / 'ntp.conf'
            existing.write_text('local config')
            commands = []
            environments = []
            def native(argv, cwd, env, log):
                commands.append(argv)
                environments.append(dict(env))
                with log.open('a') as stream:
                    stream.write(json.dumps(argv) + '\n')
                if 'install' in argv:
                    stage = Path(env.get('DESTDIR') or next(a.split('=', 1)[1] for a in argv if a.startswith('--destdir=')))
                    required = ('sbin/gpsd',) if 'scons' in argv[0] else ('sbin/ntpd', 'bin/ntpq', 'bin/ntpleapfetch')
                    for filename in required:
                        path = stage / 'usr/local' / filename
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_bytes(b'binary fixture')
                        path.chmod(0o755)
                    if 'scons' in argv[0]:
                        package = stage / build_profile['python']['module_directory'].lstrip('/') / 'gps'
                        package.mkdir(parents=True)
                        (package / '__init__.py').write_text('GPSD package fixture')
            with patch.object(CLOCK.os, 'geteuid', return_value=1000), \
                    patch.object(CLOCK, 'target_identity'), \
                    patch.object(CLOCK, 'require_no_package_applications'), \
                    patch.object(CLOCK.subprocess, 'check_output', return_value=b'1\tii '), \
                    patch.object(CLOCK, 'run', side_effect=native):
                result = CLOCK.build(profile, expected, base / 'candidate', updating=True)
            manifest = CLOCK.bound_json(Path(result['manifest']), result['sha256'])
            self.assertEqual(manifest['operation'], 'update')
            self.assertIn('usr/local/libexec/timeservice.py', manifest['files'])
            self.assertTrue(any('check' in c for c in commands))
            self.assertTrue(all('-j2' in c for c in commands[3:]))
            self.assertFalse(any('git' in c[0] or 'apt' in c[0] or 'reboot' in c for c in commands))
            self.assertEqual(existing.read_text(), 'local config')
            self.assertFalse(any(p.startswith('etc/') for p in manifest['files']))
            self.assertIn('python_libdir=' + build_profile['python']['module_directory'], commands[3])
            self.assertTrue(any('--pythondir=' + build_profile['python']['module_directory'] in c for c in commands))
            self.assertIn('PYTHONPATH', environments[-1])
            dependency = base / 'candidate/ntpsec/build/main/tests/pylib/gps'
            self.assertTrue(dependency.is_symlink())

    def test_gpsd_dependency_is_available_to_isolated_binary_tests(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source, stage = base / 'ntpsec', base / 'stage'
            source.mkdir()
            module_directory = '/usr/local/lib/python3/dist-packages'
            package = stage / module_directory.lstrip('/') / 'gps'
            with self.assertRaisesRegex(ValueError, 'staged GPSD'):
                CLOCK.link_gpsd_test_dependency(source, stage, module_directory)
            package.mkdir(parents=True)
            (package / '__init__.py').write_text('fixture = 42\n')
            CLOCK.link_gpsd_test_dependency(source, stage, module_directory)
            library = source / 'build/main/tests/pylib'
            result = subprocess.run([CLOCK.sys.executable, '-B', '-c',
                                     'import gps; print(gps.fixture)'], cwd=source,
                                    env={'PATH': '/usr/bin:/bin', 'PYTHONPATH': str(library)},
                                    check=True, capture_output=True, text=True)
            self.assertEqual(result.stdout, '42\n')
            self.assertEqual((library / 'gps').resolve(), package.resolve())
            with self.assertRaisesRegex(ValueError, 'existing GPSD'):
                CLOCK.link_gpsd_test_dependency(source, stage, module_directory)
            (library / 'gps').unlink()
            (library / 'gps').symlink_to(base / 'missing')
            with self.assertRaisesRegex(ValueError, 'existing GPSD'):
                CLOCK.link_gpsd_test_dependency(source, stage, module_directory)

    def test_symlinked_gpsd_dependency_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            package = base / 'stage/usr/local/lib/gps'
            package.parent.mkdir(parents=True)
            package.symlink_to(base, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, 'staged GPSD'):
                CLOCK.link_gpsd_test_dependency(base / 'ntpsec', base / 'stage', '/usr/local/lib')

    def test_parallelism_is_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = self.profile(Path(directory))
            for jobs in (0, 5, True, '2'):
                profile['jobs'] = jobs
                with self.subTest(jobs=jobs), self.assertRaisesRegex(ValueError, 'build jobs'):
                    CLOCK.validate_profile(profile)

    def test_publisher_profile_requires_observed_python_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = self.profile(Path(directory))
            profile['sources']['ntpsec'].update(archive_format='publisher-release', archive_root='release')
            profile['packages'].update({'pps-tools':'1','bc':'1'})
            with self.assertRaisesRegex(ValueError, 'observed Python'):
                CLOCK.validate_profile(profile)
            profile['python'] = {'executable': '/usr/bin/python3',
                'version': list(CLOCK.sys.version_info[:2]),
                'module_directory': CLOCK.sysconfig.get_path('purelib')}
            CLOCK.validate_profile(profile)
            for dependency in ('bc','pps-tools'):
                missing=copy.deepcopy(profile)
                missing['packages'].pop(dependency)
                with self.subTest(dependency=dependency),self.assertRaisesRegex(ValueError,'publisher builds'):
                    CLOCK.validate_profile(missing)
            profile['sources']['ntpsec']['options'] = ['--pythondir=/usr/lib']
            with self.assertRaises(ValueError):
                CLOCK.validate_profile(profile)

    def test_profiles_do_not_allow_prefix_override_or_moving_commits(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = self.profile(Path(directory))
            for option in ('--prefix=/usr', '--destdir=/'):
                profile['sources']['ntpsec']['options'] = [option]
                with self.assertRaises(ValueError):
                    CLOCK.validate_profile(profile)
            profile['sources']['ntpsec']['options'] = []
            profile['sources']['gpsd']['commit'] = 'master'
            with self.assertRaises(ValueError):
                CLOCK.validate_profile(profile)

    def test_configuration_staging_keeps_live_inputs_and_binds_files(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            ntp = base / 'ntp.conf'
            ntp.write_text('refclock shm unit 1\n')
            unit = base / 'timeservice.service'
            unit.write_bytes((SCRIPTS.parent / 'templates/timeservice.service').read_bytes())
            profile = base / 'config-profile.json'
            sha = write_json(profile, {'schema': 1, 'hostname': 'fixture',
                'ntp_config': {'path': ntp.name, 'sha256': CLOCK.digest(ntp.read_bytes())},
                'unit': {'path': unit.name, 'sha256': CLOCK.digest(unit.read_bytes())},
                'timeservice': {'uart_device': '/dev/observed-gps',
                    'gpsd': ['/usr/local/sbin/gpsd', '-N', '-s', '115200', '/dev/observed-gps'],
                    'ntpd': ['/usr/local/sbin/ntpd', '-n', '-u', '123:123', '-c', '/etc/ntp.conf']}})
            result = CLOCK.configure(profile, sha, base / 'configuration')
            self.assertEqual(ntp.read_text(), 'refclock shm unit 1\n')
            self.assertEqual(CLOCK.bound_json(Path(result['manifest']), result['sha256'])['state'],
                             'configuration_staged_not_installed')
            self.assertTrue((base / 'configuration/ntpsec-timeservice.json').exists())
            invalid = json.loads(profile.read_text())
            invalid['timeservice']['gpsd'][3] = '9600'
            sha = write_json(profile, invalid)
            with self.assertRaises(ValueError):
                CLOCK.configure(profile, sha, base / 'invalid-configuration')

    def test_package_conflicts_and_live_daemons_hold(self):
        with patch.object(CLOCK.subprocess, 'check_output', return_value=b'gpsd\tii \n'):
            with self.assertRaises(ValueError):
                CLOCK.require_no_package_applications()
        with tempfile.TemporaryDirectory() as directory:
            comm = Path(directory) / 'comm'
            comm.write_text('ntpd\n')
            with patch.object(CLOCK.Path, 'glob', return_value=[comm]):
                with self.assertRaises(ValueError):
                    CLOCK.require_stopped_daemons()

    def test_staging_rejects_paths_outside_prefix_and_escaping_links(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'etc/ntp.conf'
            path.parent.mkdir()
            path.write_text('not permitted')
            with self.assertRaises(ValueError):
                CLOCK.inventory(root)
            path.unlink()
            path = root / 'usr/local/escape'
            path.parent.mkdir(parents=True)
            path.symlink_to('/etc/passwd')
            with self.assertRaises(ValueError):
                CLOCK.inventory(root)

    def test_install_rejects_path_traversal_and_changed_stage_before_writes(self):
        with self.assertRaises(ValueError):
            CLOCK.safe_destination('usr/local/../../etc/passwd')
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            record = {'type': 'file', 'mode': 0o755, 'sha256': CLOCK.digest(b'good')}
            release = base / 'release.json'
            sha = write_json(release, {'schema': 1, 'hostname': 'fixture', 'files': {'usr/local/bin/tool': record}})
            payload = base / 'stage/usr/local/bin/tool'
            payload.parent.mkdir(parents=True)
            payload.write_bytes(b'changed')
            state = base / 'state.json'
            state_sha = write_json(state, {'fixture': True})
            journal = base / 'journal'
            with patch.object(CLOCK.os, 'geteuid', return_value=0), \
                    patch.object(CLOCK, 'target_identity'), \
                    patch.object(CLOCK, 'require_no_package_applications'), \
                    patch.object(CLOCK, 'require_stopped_daemons'), \
                    patch.object(CLOCK, 'inspect_install', return_value={'fixture': True}):
                with self.assertRaisesRegex(ValueError, 'staged payload'):
                    CLOCK.install(release, sha, state, state_sha, journal)
            self.assertFalse(journal.exists())

    def test_native_install_obsolete_files_and_rollback(self):
        # Simulate protected root metadata for a private offline fixture only.
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            target = base / 'target'
            target.mkdir()
            old = target / 'old'
            old.write_bytes(b'old')
            old.chmod(0o644)
            release = base / 'release.json'
            new_record = {'type': 'file', 'mode': 0o755, 'sha256': CLOCK.digest(b'new')}
            sha = write_json(release, {'schema': 1, 'hostname': 'fixture', 'operation': 'update',
                            'files': {'usr/local/new': new_record}})
            previous = base / 'previous.json'
            old_sha = write_json(previous, {'schema': 1, 'hostname': 'fixture',
                'files': {'usr/local/old': {'type': 'file', 'mode': 0o644, 'sha256': CLOCK.digest(b'old')}}})
            staged = base / 'stage/usr/local/new'
            staged.parent.mkdir(parents=True)
            staged.write_bytes(b'new')
            state = base / 'state.json'
            journal = base / 'journal'
            real_lstat = Path.lstat
            def protected(path, *args, **kwargs):
                info = real_lstat(path, *args, **kwargs)
                fields = list(info)
                fields[4] = 0
                fields[5] = 0
                if stat.S_ISDIR(info.st_mode):
                    fields[0] &= ~0o022
                return os.stat_result(fields)
            def destination(relative):
                return target / Path(relative).name
            with patch.object(CLOCK.os, 'geteuid', return_value=0), \
                    patch.object(CLOCK, 'target_identity'), \
                    patch.object(CLOCK, 'require_no_package_applications'), \
                    patch.object(CLOCK, 'require_stopped_daemons'), \
                    patch.object(CLOCK, 'safe_destination', side_effect=destination), \
                    patch.object(Path, 'lstat', protected), \
                    patch.object(CLOCK.os, 'fchown'):
                state_sha = write_json(state, CLOCK.inspect_install(release, sha, previous, old_sha))
                CLOCK.install(release, sha, state, state_sha, journal, previous, old_sha)
                self.assertEqual((target / 'new').read_bytes(), b'new')
                self.assertFalse(old.exists())
                receipt = journal / 'receipt.json'
                receipt_sha = CLOCK.digest(receipt.read_bytes())
                (target / 'new').write_bytes(b'drifted')
                with self.assertRaisesRegex(ValueError, 'changed after install'):
                    CLOCK.rollback(receipt, receipt_sha)
                self.assertFalse((journal / 'rollback.json').exists())
                (target / 'new').write_bytes(b'new')
                result = CLOCK.rollback(receipt, CLOCK.digest(receipt.read_bytes()))
                self.assertEqual(result['state'], 'restored_not_activated')
                self.assertEqual(old.read_bytes(), b'old')
                self.assertFalse((target / 'new').exists())


class PinupTests(unittest.TestCase):
    def test_hash_mismatch_prevents_boot_edit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.txt'
            path.write_text('[all]\n')
            real_lstat = Path.lstat
            def protected(p, *args, **kwargs):
                info = list(real_lstat(p, *args, **kwargs))
                info[4] = 0
                info[0] &= ~0o022
                return os.stat_result(info)
            with patch.object(PIN.os, 'geteuid', return_value=0), \
                    patch.object(PIN, 'require_target'), patch.object(Path, 'lstat', protected), \
                    patch.object(PIN.os, 'fstat', return_value=os.stat_result([stat.S_IFREG | 0o644, 0, 0, 1, 0, 0, 6, 0, 0, 0])):
                with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                    PIN.update(path, '0' * 64, 18, 'fixture')
            self.assertEqual(path.read_text(), '[all]\n')
            self.assertEqual(list(path.parent.iterdir()), [path])

    def test_no_arbitrary_root_file_or_wrong_node_edit(self):
        with self.assertRaises(ValueError):
            PIN.require_target(Path('/etc/passwd'), 'fixture')

    def test_comments_parameters_and_noop(self):
        text = '#dtoverlay=pps-gpio,gpiopin=4\n[all]\ndtoverlay=pps-gpio,gpiopin=18,assert_falling_edge #checked\n'
        self.assertEqual(PIN.edit(text, 18), text)
        changed = PIN.edit(text, 4)
        self.assertIn('#dtoverlay=pps-gpio,gpiopin=4', changed)
        self.assertIn('assert_falling_edge,gpiopin=4 #checked', changed)
        self.assertEqual(PIN.inspect(text), 'dtoverlay=pps-gpio,gpiopin=18,assert_falling_edge')

    def test_first_overlay_and_ambiguity_rejections(self):
        self.assertIn('[all]\ndtoverlay=pps-gpio,gpiopin=18', PIN.edit('[pi4]\n', 18))
        for text in ('[pi4]\ndtoverlay=pps-gpio,gpiopin=18\n',
                     'dtoverlay=pps-gpio,gpiopin=18\ndtoverlay=pps-gpio,gpiopin=4\n',
                     'include usercfg.txt\n', 'dtoverlay=pps-gpio,gpiopin=x\n'):
            with self.assertRaises(ValueError):
                PIN.edit(text, 18)
        with self.assertRaises(ValueError):
            PIN.edit('', 40)


class TimeserviceTests(unittest.TestCase):
    def test_foreground_and_absolute_source_paths_required(self):
        SERVICE.validate({'uart_device': '/dev/observed-gps', 'gpsd': ['/usr/local/sbin/gpsd', '-N', '-s', '115200', '/dev/observed-gps'], 'ntpd': ['/usr/local/sbin/ntpd', '-n']})
        for config in ({'gpsd': ['/usr/sbin/gpsd', '-N'], 'ntpd': ['/usr/local/sbin/ntpd', '-n']},
                       {'gpsd': ['/usr/local/sbin/gpsd'], 'ntpd': ['/usr/local/sbin/ntpd', '-n']}):
            with self.assertRaises(ValueError):
                SERVICE.validate(config)

    def test_uart_speed_is_required_and_conflicting_overrides_rejected(self):
        for argv in (['-N', '/dev/observed-gps'],
                     ['-N', '-s', '9600', '/dev/observed-gps'],
                     ['-N', '-s', '115200', '--speed=9600', '/dev/observed-gps'],
                     ['-N', '-s', '115200', '-s', '9600', '/dev/observed-gps'],
                     ['-N', '-s', '115200', '/dev/other']):
            with self.subTest(argv=argv), self.assertRaises(ValueError):
                SERVICE.validate({'uart_device': '/dev/observed-gps',
                                  'gpsd': ['/usr/local/sbin/gpsd', *argv],
                                  'ntpd': ['/usr/local/sbin/ntpd', '-n']})

    def test_uart_initialization_failure_prevents_both_daemons(self):
        config = {'uart_device': '/dev/observed-gps',
                  'gpsd': ['/usr/local/sbin/gpsd', '-N', '-s', '115200', '/dev/observed-gps'],
                  'ntpd': ['/usr/local/sbin/ntpd', '-n']}
        for error in (subprocess.CalledProcessError(1, 'stty'),
                      subprocess.TimeoutExpired('stty', 10)):
            with patch.object(SERVICE.subprocess, 'run', side_effect=error) as stty, \
                    patch.object(SERVICE.subprocess, 'Popen') as launch:
                with self.assertRaises(subprocess.SubprocessError):
                    SERVICE.supervise(config)
                launch.assert_not_called()
                self.assertEqual(stty.call_args.args[0],
                                 ['/usr/bin/stty', '-F', '/dev/observed-gps', 'raw',
                                  '115200', 'cs8', '-parenb', 'clocal', '-cstopb', '-crtscts'])
                self.assertTrue(stty.call_args.kwargs['check'])

    def test_either_daemon_failure_stops_the_other(self):
        class Process:
            def __init__(self, exited): self.exited = exited; self.stopped = False
            def poll(self): return 2 if self.exited else None
            def terminate(self): self.stopped = True; self.exited = True
            def wait(self, timeout=None): return 0
        first, second = Process(False), Process(True)
        config = {'uart_device': '/dev/observed-gps', 'gpsd': ['/usr/local/sbin/gpsd', '-N', '-s', '115200', '/dev/observed-gps'], 'ntpd': ['/usr/local/sbin/ntpd', '-n']}
        with patch.object(SERVICE.subprocess, 'run') as stty:
            def launch(argv, **kwargs):
                stty.assert_called_once()
                return first if argv[0].endswith('/gpsd') else second
            with patch.object(SERVICE.subprocess, 'Popen', side_effect=launch):
                self.assertEqual(SERVICE.supervise(config), 1)
        self.assertTrue(first.stopped)

    def test_second_daemon_launch_error_cleans_up_first(self):
        process = unittest.mock.Mock()
        process.poll.return_value = None
        with patch.object(SERVICE.subprocess, 'run'), patch.object(SERVICE.subprocess, 'Popen', side_effect=[process, OSError('launch failed')]):
            with self.assertRaises(OSError):
                SERVICE.supervise({'uart_device': '/dev/observed-gps', 'gpsd': ['/usr/local/sbin/gpsd', '-N', '-s', '115200', '/dev/observed-gps'], 'ntpd': ['/usr/local/sbin/ntpd', '-n']})
        process.terminate.assert_called_once()


if __name__ == '__main__':
    unittest.main()
