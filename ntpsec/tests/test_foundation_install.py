#!/usr/bin/python3
"""Offline protocol, transaction, recovery, filesystem and transport regressions."""
import copy
import importlib.util
import itertools
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SEALED = (Path(__file__).resolve().parent / 'worker.py').is_file()
if SEALED:
    ROOT = Path(__file__).resolve().parent


def load(name, path):
    source = ROOT / ('worker.py' if path == 'foundation-install.py' else 'launcher.py') if SEALED else ROOT / 'scripts' / path
    spec = importlib.util.spec_from_file_location(name, source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


w = load('foundation', 'foundation-install.py')
l = load('launcher', 'run-foundation-install.py')


def specification():
    return {'stage': str(w.STAGE), 'hostname': w.APPROVED_HOSTNAME,
            'expires_epoch': int(time.time()) + 3600,
            'baseline': {'base': ['1', 'ii ']},
            'packages': [{'package': 'pkg' + str(i), 'version': '2:1.0-1',
                          'architecture': 'arm64', 'binary_package': 'pkg' + str(i),
                          'file': 'archives/pkg' + str(i) + '_2%3a1.0-1_arm64.deb', 'size': 1,
                          'sha256': 'a' * 64} for i in range(44)] + [
                {'package': 'pps-tools', 'version': '1', 'architecture': 'arm64', 'binary_package': 'pps-tools',
                 'file': 'archives/pps-tools_1_arm64.deb', 'size': 1, 'sha256': 'a' * 64},
                {'package': 'bc', 'version': '1', 'architecture': 'arm64', 'binary_package': 'bc',
                 'file': 'archives/bc_1_arm64.deb', 'size': 1, 'sha256': 'b' * 64}]}


def actions(spec, configure=True):
    rows = ['VERSION 2', 'APT::Architecture=arm64', '']
    for row in spec['packages']:
        prefix = row['package'] + ' - < ' + row['version'] + ' '
        rows.append(prefix + str(w.STAGE / row['file']))
        if configure:
            rows.append(prefix + '**CONFIGURE**')
    return ('\n'.join(rows) + '\n').encode()


class Protocol(unittest.TestCase):
    def setUp(self):
        self.spec = specification()

    def test_exact_union_with_configure_rows(self):
        w.validate_spec(self.spec)
        self.assertEqual(len(w.protocol(actions(self.spec), self.spec)), 46)

    def test_foundation_requires_pps_and_supplement_allows_only_pps(self):
        with self.assertRaises(ValueError):
            w.validate_spec(dict(self.spec, packages=self.spec['packages'][:-1]))
        supplement = dict(self.spec, scope='pps-supplement', packages=self.spec['packages'][-2:-1])
        w.validate_spec(supplement)
        w.validate_spec(dict(supplement, scope='bc-supplement', packages=self.spec['packages'][-1:]))
        with self.assertRaises(ValueError):
            w.validate_spec(dict(supplement, packages=self.spec['packages'][:1]))
        with self.assertRaises(ValueError):
            w.validate_spec(dict(supplement, scope='unknown'))

    def test_retained_native_protocol(self):
        fixture = ROOT / 'native-protocol.txt' if SEALED else ROOT / 'tests/fixtures/native-foundation-protocol-v1.txt'
        data = fixture.read_bytes()
        data = data.replace(b'/var/lib/ntp-foundation-v1', str(w.STAGE).encode())
        rows = []
        for line in data.decode().partition('\n\n')[2].splitlines():
            name, old, direction, version, action = line.split()
            if action == '**CONFIGURE**':
                continue
            rows.append({'package': name, 'version': version, 'architecture': Path(action).stem.rsplit('_', 1)[1],
                         'file': str(Path(action).relative_to(w.STAGE)), 'binary_package': name, 'sha256': 'a' * 64})
        self.assertEqual(len(w.protocol(data, dict(self.spec, packages=rows))), len(rows))

    def test_needrestart_distinct_kernel_acceptance(self):
        spec = {'kernel': '6.18.50+rpt-rpi-v8'}
        text = ('NEEDRESTART-VER: 3.11\nNEEDRESTART-KCUR: ' + spec['kernel']
                + '\nNEEDRESTART-KEXP: ' + spec['kernel'] + '\nNEEDRESTART-KSTA: 1\n')
        w.validate_needrestart_report(text, spec)
        for bad in (text.replace('KSTA: 1', 'KSTA: 0'), text.replace('KEXP:', 'MISSING:'),
                    text + 'NEEDRESTART-KSTA: 1\n', text.replace('-v8', '-2712')):
            with self.assertRaises(ValueError):
                w.validate_needrestart_report(bad, spec)

    def test_archive_only_protocol(self):
        self.assertEqual(len(w.protocol(actions(self.spec, False), self.spec)), 46)

    def test_unknown_remove_upgrade_path_version_rejected(self):
        data = actions(self.spec)
        for old, new in [(b'pkg0 - <', b'unknown - <'), (b' - < ', b' 1 < '),
                         (b'**CONFIGURE**', b'**REMOVE**'), (b'2:1.0-1', b'2:1.0-2'),
                         (b'archives/pkg0_', b'archives/other_')]:
            with self.subTest(new=new), self.assertRaises(ValueError):
                w.protocol(data.replace(old, new, 1), self.spec)

    def test_duplicate_missing_and_order_rejected(self):
        data = actions(self.spec)
        for bad in (data + data.splitlines()[3] + b'\n',
                    b'\n'.join(data.splitlines()[:-2]) + b'\n',
                    data.replace(data.splitlines()[3] + b'\n', b'', 1)):
            with self.assertRaises(ValueError):
                w.protocol(bad, self.spec)

    def test_bad_header_framing_encoding(self):
        for data in (b'VERSION 3\n\n', b'VERSION 2\ninvalid\n\n', b'\xff', b'VERSION 2\n'):
            with self.assertRaises((ValueError, UnicodeError)):
                w.protocol(data, self.spec)

    def test_simulation_real_style_and_trailing_empty_brackets(self):
        rows = ['Inst ' + r['package'] + ' (' + r['version'] + ' local [arm64]) []'
                for r in self.spec['packages']]
        w.validate_simulation('\n'.join(rows), self.spec)
        for bad in ('Remv base [1]\n' + '\n'.join(rows),
                    '\n'.join(rows).replace('Inst pkg0 (', 'Inst pkg0 [1] ('),
                    '\n'.join(rows[:-1]), '\n'.join(rows + [rows[0]]),
                    '\n'.join(rows).replace('[arm64]', '[armhf]', 1)):
            with self.assertRaises(ValueError):
                w.validate_simulation(bad, self.spec)

    def test_scope_and_architecture_rejected(self):
        for field, value in [('package', 'gpsd'), ('architecture', 'amd64'),
                             ('file', '../../evil'), ('sha256', 'x')]:
            spec = copy.deepcopy(self.spec)
            spec['packages'][0][field] = value
            with self.assertRaises(ValueError):
                w.validate_spec(spec)

    def test_expected_binary_architecture_suffix(self):
        self.spec['packages'][0]['binary_package'] = 'pkg0:arm64'
        expected = w.expected_inventory(self.spec)
        self.assertEqual(expected['pkg0:arm64'], ['2:1.0-1', 'ii '])
        self.assertNotIn('pkg0', expected)

    def test_recovery_only_configures_bound_pending_packages(self):
        current = {'base': ['1', 'ii '], 'pkg0': ['2:1.0-1', 'iU '], 'pkg1': ['2:1.0-1', 'ii ']}
        self.assertEqual(w.recovery_packages(current, self.spec), ['pkg0'])
        for change in ({'base': ['2', 'ii ']}, {'evil': ['1', 'iU ']},
                       {'pkg0': ['9', 'iU ']}, {'pkg0': ['2:1.0-1', 'iHR']}):
            with self.assertRaises(ValueError):
                w.recovery_packages(dict(current, **change), self.spec)

    def test_package_rows_reject_duplicates_and_malformed(self):
        self.assertEqual(w.package_rows('base\t1\tii \n'), {'base': ['1', 'ii ']})
        for text in ('base\t1\tii \nbase\t1\tii \n', 'missing\n', 'a;evil\t1\tii \n'):
            with self.assertRaises(ValueError):
                w.package_rows(text)

    def test_fresh_requirements_allow_partial_inventory_and_reject_delta_tampering(self):
        spec = copy.deepcopy(self.spec)
        needrestart = dict(spec['packages'][-1], package='needrestart', binary_package='needrestart',
                          version='3.11-1', file='archives/needrestart_3.11-1_arm64.deb')
        spec.update(schema=2, requirements=copy.deepcopy(spec['packages'])+[needrestart])
        spec['baseline']['needrestart'] = ['3.11-1', 'ii ']
        pps = next(r for r in spec['packages'] if r['package'] == 'pps-tools')
        spec['baseline']['pps-tools'] = [pps['version'], 'ii ']
        spec['packages'] = [r for r in spec['packages'] if r['package'] != 'pps-tools']
        spec['expected_inventory'] = w.expected_inventory(spec)
        w.validate_spec(spec)
        changed = copy.deepcopy(spec)
        changed['packages'].pop()
        with self.assertRaisesRegex(ValueError, 'delta'): w.validate_spec(changed)
        changed = copy.deepcopy(spec)
        changed['expected_inventory']['unplanned'] = ['1', 'ii ']
        with self.assertRaisesRegex(ValueError, 'inventory'): w.validate_spec(changed)

    def test_fresh_boot_change_rejected_before_mutation(self):
        spec = dict(self.spec, schema=2, kernel='6.18.50+rpt-rpi-v8',
                    prepared_epoch=int(time.time()), boot_id='observed-boot')
        with patch.object(w.os, 'geteuid', return_value=0), patch.object(w.os, 'getegid', return_value=0), \
             patch.dict(w.os.environ, {'SUDO_USER': 'ama', 'SUDO_UID': '1000'}), \
             patch.object(w.socket, 'gethostname', return_value=w.APPROVED_HOSTNAME), \
             patch.object(w.os, 'uname', return_value=type('Uname', (), {'machine': 'aarch64', 'release': spec['kernel']})()), \
             patch.object(w, 'read', return_value=b'ID=debian\nVERSION_ID="13"\nVERSION_CODENAME=trixie\n'), \
             patch.object(w, 'boot', return_value='different-boot'):
            with self.assertRaisesRegex(ValueError, 'boot drift'):
                w.identity(spec, int(time.time()))


class Transaction(unittest.TestCase):
    def setUp(self):
        self.spec = specification()
        self.events = []
        self.patches = []
        for name in ('preflight', 'pause_updates', 'install_controls', 'check_inputs',
                     'clean_dpkg', 'validate_simulation', 'acceptance', 'restore_controls'):
            p = patch.object(w, name, side_effect=lambda *a, _name=name, **k: self.events.append((_name, a)))
            self.patches.append(p)
            p.start()
        for name in ('auto_snapshot', 'backup_policies'):
            p = patch.object(w, name, return_value={})
            self.patches.append(p)
            p.start()
        p = patch.object(w, 'record', side_effect=lambda name, value: self.events.append((name, value)))
        self.patches.append(p)
        p.start()
        p = patch.object(w, 'read', return_value=b'{"exit_status":0,"failure":null}')
        self.patches.append(p)
        p.start()
        self.addCleanup(lambda: [p.stop() for p in reversed(self.patches)])

    def test_success_orders_acceptance_before_cleanup(self):
        with patch.object(w, 'inventory', return_value=self.spec['baseline']), patch.object(w, 'run', return_value=''):
            w.install(self.spec)
        names = [e[0] for e in self.events]
        self.assertLess(names.index('pause_updates'), names.index('install_controls'))
        self.assertLess(names.index('validate_simulation'), names.index('unpack-authorized'))
        self.assertLess(names.index('acceptance'), names.index('restore_controls'))
        self.assertEqual(self.events[-1][0], 'complete')
        w.check_inputs.assert_called_once_with(self.spec, controls=True)

    def test_satisfied_requirements_do_not_invoke_apt(self):
        spec = dict(self.spec, schema=2, packages=[], automatic_updates={})
        with patch.object(w, 'inventory', return_value=spec['baseline']), \
             patch.object(w, 'run', side_effect=AssertionError('APT must not run without package changes')):
            w.install(spec)
        self.assertIn('no-package-changes', [event[0] for event in self.events])
        self.assertEqual(self.events[-1][0], 'complete')

    def test_fresh_automatic_update_state_drift_precedes_controls(self):
        spec = dict(self.spec, schema=2, automatic_updates={'observed': 'different'})
        with self.assertRaisesRegex(ValueError, 'automatic-update state drift'):
            w.install(spec)
        w.backup_policies.assert_not_called()
        self.assertNotIn('pause_updates', [event[0] for event in self.events])

    def test_real_validator_hook_checks_the_controlled_input_phase(self):
        data = actions(self.spec)
        with patch.dict(os.environ, {'APT_HOOK_INFO_FD': '20'}), patch.object(w.os, 'read', side_effect=[data, b'']), \
                patch.object(w, 'guard_controls'), patch.object(w, 'inventory', return_value=self.spec['baseline']), \
                patch.object(w, 'verify_archives'):
            w.hook(self.spec, 'validate')
        w.check_inputs.assert_called_once_with(self.spec, controls=True)
        self.assertIn('hook-validate-accepted', [event[0] for event in self.events])

    def test_listchanges_forwards_information_without_stdio_override(self):
        data = actions(self.spec)
        with patch.dict(os.environ, {'APT_HOOK_INFO_FD': '20'}), patch.object(w.os, 'read', side_effect=[data, b'']), \
                patch.object(w, 'guard_controls'), patch.object(w, 'inventory', return_value=self.spec['baseline']), \
                patch.object(w, 'verify_archives'), patch.object(w, 'run') as run:
            w.hook(self.spec, 'listchanges')
        run.assert_called_once_with(['/usr/bin/apt-listchanges', '--apt'], 'hook-listchanges', seconds=120,
                                    information=data)

    def test_early_apt_failure_restores_controls(self):
        def command(args, label, **kwargs):
            if label == 'apt-install':
                raise RuntimeError('APT terminal failure')
            return ''
        with patch.object(w, 'inventory', return_value=self.spec['baseline']), patch.object(w, 'run', side_effect=command):
            with self.assertRaises(RuntimeError):
                w.install(self.spec)
        restored = next(args for name, args in self.events if name == 'restore_controls')
        self.assertFalse(restored[1])

    def test_partial_install_retains_controls(self):
        def command(args, label, **kwargs):
            if label == 'apt-install':
                raise RuntimeError('partial failure')
            return ''
        def inventory(label):
            return dict(self.spec['baseline'], pkg0=['2:1.0-1', 'iU ']) if label == 'failure-packages' else self.spec['baseline']
        with patch.object(w, 'inventory', side_effect=inventory), patch.object(w, 'run', side_effect=command):
            with self.assertRaises(RuntimeError):
                w.install(self.spec)
        self.assertNotIn('restore_controls', [e[0] for e in self.events])
        self.assertEqual(self.events[-1][1]['state'], 'package_recovery_required')

    def test_swallowed_hook_error_does_not_accept_apt_success(self):
        with patch.object(w, 'inventory', return_value=dict(self.spec['baseline'], pkg0=['2:1.0-1', 'ii '])), \
                patch.object(w, 'run', return_value=''), \
                patch.object(w, 'read', return_value=b'{"exit_status":9,"failure":null}'):
            # Paused baseline must still match; final failure inventory contains changes.
            with patch.object(w, 'inventory', side_effect=[self.spec['baseline'], {'base': ['1', 'ii '], 'pkg0': ['2:1.0-1', 'ii ']}]):
                with self.assertRaises(ValueError):
                    w.install(self.spec)
        self.assertNotIn('acceptance', [e[0] for e in self.events])


class FilesAndProcesses(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.stage = Path(self.temp.name)
        self.patchers = [patch.object(w, 'STAGE', self.stage), patch.object(w, 'OWNER', os.getuid()),
                         patch.object(w, 'ancestors', return_value=None)]
        for p in self.patchers:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in reversed(self.patchers)])

    def test_exclusive_claim_and_read_symlink_hardlink_mode_limit(self):
        path = self.stage / 'input'
        w.create(path, b'bound')
        self.assertEqual(w.read(path), b'bound')
        with self.assertRaises(FileExistsError):
            w.create(path, b'replayed')
        link = self.stage / 'link'
        link.symlink_to(path)
        with self.assertRaises(OSError):
            w.read(link)
        os.link(path, self.stage / 'hardlink')
        with self.assertRaises(ValueError):
            w.read(path)
        self.assertEqual(w.read(path, unique=False), b'bound')
        (self.stage / 'hardlink').unlink()
        path.chmod(0o666)
        with self.assertRaises(ValueError):
            w.read(path)
        with self.assertRaises(ValueError):
            w.read(path, unique=False)
        path.chmod(0o600)
        with self.assertRaises(ValueError):
            w.read(path, limit=3)

    def test_cleanup_drift_holds_before_timer_restore(self):
        lc, policy, nr = [self.stage / n for n in ('live-listchanges', 'live-deny', 'live-needrestart')]
        for path, data in ((lc, b'drift'), (policy, w.DENY), (nr, b'nr'),
                           (self.stage / 'listchanges.conf', b'new'), (self.stage / 'needrestart.conf', b'nr')):
            w.create(path, data)
        w.record('policy-before', {str(lc): {'sha256': w.sha(b'old')}, str(policy): {'absent': True},
                                  str(nr): {'absent': True}, 'created_dirs': []})
        with patch.object(w, 'LISTCHANGES', lc), patch.object(w, 'POLICY', policy), patch.object(w, 'NRPOLICY', nr), \
                patch.object(w, 'run') as run:
            with self.assertRaises(ValueError):
                w.restore_controls({}, True, 'cleanup')
            run.assert_not_called()
        self.assertTrue(policy.exists())

    def test_live_original_process_rejects_repair(self):
        w.record('apt-install-started', {'pid': os.getpid(), 'start_ticks': w.process_ticks(os.getpid()), 'boot': w.boot()})
        with patch.object(w, 'run') as run:
            with self.assertRaises(ValueError):
                w.recover(specification())
            run.assert_not_called()

    def test_missing_terminal_evidence_rejects_repair(self):
        w.record('apt-install-started', {'pid': 99999999, 'start_ticks': '1', 'boot': w.boot()})
        with patch.object(w, 'run') as run:
            with self.assertRaises(FileNotFoundError):
                w.recover(specification())
            run.assert_not_called()

    def test_accepted_attempt_rejects_repair(self):
        w.record('complete', {'state': 'foundation_accepted'})
        with self.assertRaises(ValueError):
            w.recover(specification())

    def test_configuration_repair_is_bounded_and_not_install_replay(self):
        spec = specification()
        current = w.expected_inventory(spec)
        current['pkg0'] = ['2:1.0-1', 'iU ']
        w.record('apt-install-started', {'pid': 99999999, 'start_ticks': '1', 'boot': w.boot()})
        w.record('apt-install-terminal', {'exit_status': 100})
        w.record('policy-before', {})
        with patch.object(w, 'locks_free'), patch.object(w, 'inventory', return_value=current), \
                patch.object(w, 'guard_controls'), patch.object(w, 'acceptance') as accepted, \
                patch.object(w, 'restore_controls') as restored, patch.object(w, 'run') as run:
            w.recover(spec)
            run.assert_called_once_with(['/usr/bin/dpkg', '--configure', 'pkg0'], 'recovery-configure', seconds=600)
            accepted.assert_called_once_with(spec, 'recovery')
            restored.assert_called_once_with(spec, True, 'recovery')
            with self.assertRaises(FileExistsError):
                w.recover(spec)

    def test_failed_configuration_preserves_controls(self):
        spec = specification()
        current = dict(spec['baseline'], pkg0=['2:1.0-1', 'iU '])
        w.record('policy-before', {})
        with patch.object(w, 'locks_free'), patch.object(w, 'inventory', return_value=current), \
                patch.object(w, 'guard_controls'), patch.object(w, 'acceptance') as accepted, \
                patch.object(w, 'restore_controls') as restored, patch.object(w, 'run', side_effect=RuntimeError('configure failed')):
            with self.assertRaises(RuntimeError):
                w.recover(spec)
            restored.assert_not_called()
            accepted.assert_not_called()

    def test_partial_control_install_restores_original_policy(self):
        lc, deny, nr = [self.stage / n for n in ('live-listchanges', 'live-deny', 'live-nr')]
        runtime = self.stage / 'runtime'
        runtime.mkdir()
        for path, data in ((lc, b'new'), (deny, w.DENY), (self.stage / 'listchanges.conf', b'new'),
                           (self.stage / 'needrestart.conf', b'nr'), (self.stage / 'backup', b'original')):
            w.create(path, data)
        states = {str(lc): {'file': 'backup', 'sha256': w.sha(b'original'), 'mode': 0o644},
                  str(deny): {'absent': True}, str(nr): {'absent': True}, 'created_dirs': []}
        before = {u: {'LoadState': 'loaded', 'UnitFileState': 'enabled' if u in w.TIMERS else 'static',
                      'FragmentPath': '/vendor/' + u, 'DropInPaths': '',
                      'ActiveState': 'active' if u in w.TIMERS else 'inactive'} for u in (*w.TIMERS, *w.SERVICES)}
        w.record('policy-before', states)
        w.record('automatic-update-before', before)
        for unit in before:
            (runtime / unit).symlink_to('/dev/null')
            w.record('mask-intent-' + unit, {'unit': unit})
        def command(argv, label, **kwargs):
            if argv[1] == 'unmask':
                (runtime / argv[-1]).unlink()
            if argv[1] == 'show':
                return '\n'.join(k + '=' + v for k, v in before[argv[-1]].items()) + '\n'
            return ''
        with patch.object(w, 'LISTCHANGES', lc), patch.object(w, 'POLICY', deny), patch.object(w, 'NRPOLICY', nr), \
                patch.object(w, 'SYSTEMD_RUNTIME', runtime), patch.object(w, 'run', side_effect=command):
            w.restore_controls({}, False, 'partial-cleanup')
        self.assertEqual(w.read(lc), b'original')
        self.assertEqual(lc.stat().st_mode & 0o777, 0o644)
        self.assertFalse(deny.exists())
        self.assertEqual(list(runtime.iterdir()), [])

    def test_real_control_files_follow_all_input_phases_then_restore(self):
        lc, deny = self.stage / 'live-listchanges', self.stage / 'live-deny'
        nrdir = self.stage / 'needrestart' / 'conf.d'
        nrdir.mkdir(parents=True)
        nr = nrdir / 'zz-ntp-policy.conf'
        w.create(nrdir / 'rpi-kernel.conf', b'vendor-kernelhints-zero')
        w.create(lc, b'original', 0o644)
        w.create(self.stage / 'listchanges.conf', b'transaction-profile')
        w.create(self.stage / 'needrestart.conf', b'final-kernel-policy')
        spec = {'inputs': [{'path': str(lc), 'sha256': w.sha(b'original')}],
                'directories': {str(nrdir): ['rpi-kernel.conf']}, 'package_created_inputs': {}}
        runtime = self.stage / 'runtime'
        runtime.mkdir()
        before = {u: {'LoadState': 'loaded', 'UnitFileState': 'enabled' if u in w.TIMERS else 'static',
                      'FragmentPath': '/vendor/' + u, 'DropInPaths': '',
                      'ActiveState': 'active' if u in w.TIMERS else 'inactive'} for u in (*w.TIMERS, *w.SERVICES)}
        w.record('automatic-update-before', before)
        def command(argv, label, **kwargs):
            return '\n'.join(k + '=' + v for k, v in before[argv[-1]].items()) + '\n' if argv[1] == 'show' else ''
        with patch.object(w, 'LISTCHANGES', lc), patch.object(w, 'POLICY', deny), patch.object(w, 'NRPOLICY', nr), \
                patch.object(w, 'SYSTEMD_RUNTIME', runtime), patch.object(w, 'run', side_effect=command):
            w.check_inputs(spec)
            saved = w.backup_policies(spec)
            w.install_controls(spec, saved)
            w.guard_controls()
            w.check_inputs(spec, controls=True)
            # The original phase must reject the installed transaction fragment.
            with self.assertRaises(ValueError):
                w.check_inputs(spec)
            w.create(nrdir / 'README.needrestart', b'package-data')
            w.check_inputs(spec, after=True)
            w.create(nrdir / 'unexpected.conf', b'unapproved')
            with self.assertRaises(ValueError):
                w.check_inputs(spec, after=True)
            (nrdir / 'unexpected.conf').unlink()
            (nrdir / 'README.needrestart').unlink()
            w.restore_controls(spec, False, 'phase-test')
            w.check_inputs(spec)
        self.assertEqual(w.read(lc), b'original')
        self.assertFalse(nr.exists())
        self.assertFalse(deny.exists())

    def test_supplement_backs_up_existing_policy_and_restores_each_phase(self):
        for scope, (installed, success) in itertools.product(('pps-supplement', 'bc-supplement'),
                                                           ((False, False), (True, False), (True, True))):
            with self.subTest(scope=scope, installed=installed, success=success):
                stage = self.stage / (scope + '-' + str(installed) + '-' + str(success))
                stage.mkdir()
                lc, deny, nr = (stage / name for name in ('listchanges', 'deny', 'nr'))
                runtime = stage / 'runtime'
                runtime.mkdir()
                before = {u: {'LoadState': 'loaded', 'UnitFileState': 'enabled' if u in w.TIMERS else 'static',
                              'FragmentPath': '/vendor/' + u, 'DropInPaths': '',
                              'ActiveState': 'active' if u in w.TIMERS else 'inactive'} for u in (*w.TIMERS, *w.SERVICES)}
                spec = {'scope': scope, 'prior_needrestart_sha256': w.sha(b'prior-policy'),
                        'inputs': [{'path': str(lc), 'sha256': w.sha(b'original')}],
                        'directories': {}, 'package_created_inputs': {}}
                def command(argv, label, **kwargs):
                    return '\n'.join(k + '=' + v for k, v in before[argv[-1]].items()) + '\n' if argv[1] == 'show' else ''
                with patch.object(w, 'STAGE', stage), patch.object(w, 'LISTCHANGES', lc), \
                        patch.object(w, 'POLICY', deny), patch.object(w, 'NRPOLICY', nr), \
                        patch.object(w, 'SYSTEMD_RUNTIME', runtime), patch.object(w, 'run', side_effect=command):
                    w.create(lc, b'original', 0o644)
                    w.create(nr, b'prior-policy', 0o640)
                    w.create(stage / 'listchanges.conf', b'transaction-profile')
                    w.create(stage / 'needrestart.conf', b'new-policy')
                    w.record('automatic-update-before', before)
                    states = w.backup_policies(spec)
                    self.assertEqual(w.read(stage / states[str(nr)]['file']), b'prior-policy')
                    self.assertEqual(states[str(nr)]['mode'], 0o640)
                    if installed:
                        w.install_controls(spec, states)
                        w.guard_controls()
                    w.restore_controls(spec, success, 'supplement-cleanup')
                    self.assertEqual(w.read(nr), b'new-policy' if success else b'prior-policy')
                    self.assertEqual(nr.stat().st_mode & 0o777, 0o644 if success else 0o640)
                    self.assertEqual(w.read(lc), b'original')
                    self.assertFalse(deny.exists())

    def test_existing_policy_rejected_for_wrong_hash_or_fresh_foundation(self):
        for scope in ('pps-supplement', 'bc-supplement', 'foundation'):
            with self.subTest(scope=scope):
                stage = self.stage / scope
                stage.mkdir()
                lc, deny, nr = (stage / name for name in ('listchanges', 'deny', 'nr'))
                with patch.object(w, 'STAGE', stage), patch.object(w, 'LISTCHANGES', lc), \
                        patch.object(w, 'POLICY', deny), patch.object(w, 'NRPOLICY', nr):
                    w.create(lc, b'original')
                    w.create(nr, b'drift')
                    spec = {'scope': scope, 'prior_needrestart_sha256': w.sha(b'prior-policy'),
                            'inputs': [{'path': str(lc), 'sha256': w.sha(b'original')}]}
                    with self.assertRaises(ValueError):
                        w.backup_policies(spec)
                    self.assertEqual(w.read(nr), b'drift')
                    self.assertFalse((stage / 'policy-before.json').exists())

    def test_archive_hash_failure_before_native_command(self):
        row = specification()['packages'][0]
        (self.stage / 'archives').mkdir()
        w.create(self.stage / row['file'], b'wrong')
        with patch.object(w, 'run') as run:
            with self.assertRaises(ValueError):
                w.verify_archives({'packages': [row]}, 'hash-rejected')
            run.assert_not_called()

    @unittest.skipUnless(shutil.which('perl'), 'Perl needed for native policy evaluation')
    def test_native_perl_policy_result_and_load_override(self):
        config = self.stage / 'perl-config'
        config.write_text("$nrconf{kernelhints}=0;\n$nrconf{restart}='l';\n$nrconf{sendnotify}=0;\n"
                          "$nrconf{ucodehints}=0;\n"
                          "$nrconf{kernelhints}=1;\n$nrconf{kernel_linux_glob}='/boot/vmlinuz-*-v8';\n"
                          "$nrconf{kernelfilter}=qr{^/boot/vmlinuz-[A-Za-z0-9.+~_-]+-v8$};\n")
        def command(argv, label):
            return subprocess.run([v.replace('/etc/needrestart/needrestart.conf', str(config)) for v in argv],
                                  capture_output=True, check=True).stdout.decode()
        with patch.object(w, 'run', side_effect=command):
            w.effective_needrestart('perl-fixture')
            valid = config.read_text()
            for override in ('$nrconf{ucodehints}=1;\n', 'delete $nrconf{ucodehints};\n'):
                config.write_text(valid + override)
                with self.subTest(override=override), self.assertRaises(subprocess.CalledProcessError):
                    w.effective_needrestart('microcode-policy-drift')
            config.write_text(valid)
            config.write_text(config.read_text() + '$nrconf{kernelhints}=0;\n')
            with self.assertRaises(subprocess.CalledProcessError):
                w.effective_needrestart('bad-perl-fixture')

    def test_bounded_command_preserves_nonzero_exit(self):
        original_read = w.read
        def read(path, *a, **kwargs):
            return Path(path).read_bytes() if str(path).startswith('/usr/') else original_read(path, *a)
        with patch.object(w, 'read', side_effect=read):
            with self.assertRaises(RuntimeError):
                w.run(['/usr/bin/python3', '-I', '-B', '-c', 'import sys; print("hook error"); sys.exit(9)'], 'failed-hook')
        result = json.loads(w.read(self.stage / 'failed-hook-terminal.json'))
        self.assertEqual(result['exit_status'], 9)
        self.assertEqual(w.read(self.stage / 'failed-hook.stdout'), b'hook error\n')

    def test_readonly_native_hardlinks_can_execute_but_writable_links_cannot(self):
        tool = self.stage / 'native-tool'
        w.create(tool, b'#!/bin/sh\nprintf native-ok\n', 0o700)
        os.link(tool, self.stage / 'native-versioned-alias')
        self.assertEqual(w.run([str(tool)], 'native-hardlink'), 'native-ok')
        tool.chmod(0o722)
        with self.assertRaises(ValueError):
            w.run([str(tool)], 'native-writable-hardlink')
        self.assertFalse((self.stage / 'native-writable-hardlink-started.json').exists())

    def test_native_child_information_fd_is_inherited_above_stdio(self):
        data = actions(specification())
        code = ('import os,sys\nfd=int(os.environ["APT_HOOK_INFO_FD"])\n'
                'assert fd>2\nf=os.fdopen(fd,"rb")\nb=f.read()\nf.close()\n'
                'assert b.startswith(b"VERSION 2\\n")\n'
                'assert b"**CONFIGURE**" in b\n'
                'assert sys.stdin.buffer.read()==b""\nprint(len(b))\n')
        original_read = w.read
        def read(path, *args, **kwargs):
            return Path(path).read_bytes() if str(path).startswith('/usr/') else original_read(path, *args, **kwargs)
        with patch.object(w, 'read', side_effect=read):
            result = w.run(['/usr/bin/python3', '-I', '-B', '-c', code], 'native-info-fd', information=data)
        self.assertEqual(int(result), len(data))
        self.assertEqual(w.read(self.stage / 'native-info-fd.input'), data)
        terminal = json.loads(w.read(self.stage / 'native-info-fd-terminal.json'))
        self.assertGreater(terminal['information_fd'], 2)
        self.assertEqual(terminal['information_sha256'], w.sha(data))

    def test_deadline_reaps_only_owned_command(self):
        with patch.object(w, 'read', side_effect=lambda path, *a, **k: Path(path).read_bytes()):
            with self.assertRaises(RuntimeError):
                w.run(['/usr/bin/python3', '-I', '-B', '-c', 'import time; time.sleep(10)'], 'deadline', seconds=0.1)
        terminal = json.loads((self.stage / 'deadline-terminal.json').read_text())
        self.assertIsNotNone(terminal['exit_status'])
        self.assertIn('TimeoutError', terminal['failure'])
        self.assertIsNone(w.process_ticks(terminal['pid']))


class Launcher(unittest.TestCase):
    def test_agent_preserved_without_forwarding(self):
        with patch.dict(os.environ, {'SSH_AUTH_SOCK': '/private/existing-agent'}, clear=True):
            self.assertEqual(l.ssh_environment()['SSH_AUTH_SOCK'], '/private/existing-agent')
        argv = l.transport(Path('/private/evidence'))
        for option in ('ForwardAgent=no', 'StrictHostKeyChecking=yes', 'ProxyCommand=none', 'ControlPath=none'):
            self.assertIn(option, argv)

    def test_missing_agent_rejected(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(ValueError):
            l.ssh_environment()

    def test_payload_compiles_and_does_not_execute_when_rendering(self):
        payload = l.payload(specification(), {'worker.py': b'raise RuntimeError("never run while rendering")'}, 1, 'install')
        compile(payload, 'test-payload', 'exec')
        self.assertIn(b'FOUNDATION_EXIT_STATUS', payload)

    def test_registration_is_exclusive(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'registration.json'
            l.save(path, {'state': 'submitted'})
            with self.assertRaises(FileExistsError):
                l.save(path, {'state': 'replayed'})
            self.assertEqual(json.loads(path.read_text())['state'], 'submitted')

    def test_private_inputs_reject_links_and_shared_modes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'bundle'
            path.write_bytes(b'test')
            path.chmod(0o600)
            self.assertEqual(l.private_file(path, 8), b'test')
            link = path.with_name('link')
            link.symlink_to(path)
            with self.assertRaises(ValueError):
                l.private_file(link, 8)
            path.chmod(0o644)
            with self.assertRaises(ValueError):
                l.private_file(path, 8)

    def test_no_global_suspend_and_explicit_hook_protocol(self):
        self.assertNotIn('NEEDRESTART_SUSPEND', w.ENV)
        with patch.object(w, 'read', return_value=b'{}'):
            config = w.apt_config(specification()).decode()
        self.assertEqual(config.count('::InfoFD "20"'), 3)
        self.assertEqual(config.count('::Version "2"'), 3)
        self.assertIn('Dir::Etc::parts', config)
        self.assertIn('/hook-validate', config)


if __name__ == '__main__':
    unittest.main()
