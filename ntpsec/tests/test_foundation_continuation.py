#!/usr/bin/python3
"""Offline acceptance-only continuation guards and preserved-stage regressions."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SEALED = (Path(__file__).parent / 'worker.py').is_file()


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


c = load('continuation', Path(__file__).parent / 'worker.py' if SEALED else ROOT / 'scripts/continue-foundation.py')
w = c.original_worker if SEALED else load('original', ROOT / 'scripts/foundation-install.py')


class Continuation(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.stage = Path(temporary.name)
        self.events = []
        self.patches = []
        self.mock('STAGE', self.stage, w)
        self.mock('OWNER', os.getuid(), w)
        self.mock('ancestors', lambda p: None, w)
        self.mock('identity', lambda s, e: None, w)
        self.mock('locks_free', lambda: None, w)
        self.mock('guard_controls', lambda: None, w)
        self.mock('ORIGIN_STAGE', str(self.stage), c)
        self.mock('acceptance', lambda s, l: self.events.append('acceptance'), w)
        self.mock('restore_controls', lambda s, ok, l: self.events.append('cleanup'), w)
        self.mock('run', lambda *a, **k: self.fail('continuation submitted a package/native command'), w)
        self.mock('install', lambda *a: self.fail('installation replay'), w)
        self.mock('recover', lambda *a: self.fail('configuration repair'), w)
        self.addCleanup(lambda: [p.stop() for p in reversed(self.patches)])
        self.origin = {'stage': str(self.stage), 'hostname': 'j2-svntp1', 'kernel': 'test-kernel',
                       'prepared_epoch': int(time.time()), 'expires_epoch': int(time.time()) + 3600,
                       'baseline': {}, 'directories': {'/etc/dpkg/dpkg.cfg.d': []},
                       'package_created_inputs': {}, 'members': {'worker.py': w.sha(b'original')},
                       'packages': [{'package': 'pkg' + str(i), 'version': '1', 'architecture': 'all',
                                     'binary_package': 'pkg' + str(i), 'file': 'archives/pkg' + str(i) + '_1_all.deb',
                                     'sha256': 'a' * 64} for i in range(44)] + [
                           {'package': 'pps-tools', 'version': '1', 'architecture': 'all', 'binary_package': 'pps-tools',
                            'file': 'archives/pps-tools_1_all.deb', 'sha256': 'a' * 64},
                           {'package': 'bc', 'version': '1', 'architecture': 'all', 'binary_package': 'bc',
                            'file': 'archives/bc_1_all.deb', 'sha256': 'b' * 64}]}
        raw = (json.dumps(self.origin, sort_keys=True) + '\n').encode()
        self.mock('ORIGIN_SPEC', w.sha(raw), c)
        self.spec = {'origin': self.origin, 'origin_bundle_sha256': c.ORIGIN_BUNDLE,
                     'origin_spec_sha256': w.sha(raw), 'package_additions': dict(c.ADDITIONS),
                     'hostname': self.origin['hostname'], 'kernel': self.origin['kernel'],
                     'prepared_epoch': int(time.time()), 'expires_epoch': int(time.time()) + 3600,
                     'members': {'worker.py': w.sha(b'continuation')}}
        w.create(self.stage / 'spec.json', raw)
        w.create(self.stage / 'worker.py', b'original')
        w.create(self.stage / 'apt.conf', w.apt_config(self.origin))
        for mode in ('validate', 'listchanges', 'debconf', 'needrestart'):
            w.create(self.stage / ('hook-' + mode), w.hook_wrapper(mode))
        started = {'boot': w.boot(), 'pid': 99999999, 'start_ticks': '1', 'argv': ['apt-get', 'install']}
        w.record('apt-install-started', started)
        w.record('apt-install-terminal', dict(started, exit_status=0, failure=None))
        for mode in ('listchanges', 'debconf', 'needrestart'):
            w.record('hook-' + mode + '-terminal', {'exit_status': 0, 'failure': None})
        w.record('hook-validate-accepted', {'accepted': True})

    def mock(self, name, value, module):
        p = patch.object(module, name, value)
        self.patches.append(p)
        p.start()

    def execute(self, mode='recover'):
        return c.continue_entry(self.spec, {'worker.py': b'continuation'}, int(time.time()), mode, w)

    def overwrite(self, name, value):
        w.replace(self.stage / name, (json.dumps(value) + '\n').encode(), 0o600)

    def test_success_accepts_before_cleanup_and_preserves_original(self):
        before = {p.name: p.read_bytes() for p in self.stage.iterdir()}
        result = self.execute()
        self.assertEqual(self.events, ['acceptance', 'cleanup'])
        self.assertFalse(result['package_installation_repeated'])
        self.assertFalse(result['package_configuration_repair'])
        for name, data in before.items():
            self.assertEqual((self.stage / name).read_bytes(), data)
        self.assertTrue((self.stage / (c.PREFIX + '-complete.json')).is_file())
        with self.assertRaises(ValueError):
            self.execute()

    def test_exact_additions_and_immutable_origin(self):
        original = copy.deepcopy(self.origin)
        adjusted = c.continued_spec(self.spec)
        self.assertEqual(adjusted['directories']['/etc/dpkg/dpkg.cfg.d'], ['needrestart'])
        self.assertEqual(adjusted['package_created_inputs'], c.ADDITIONS)
        self.assertEqual(self.origin, original)
        self.spec['package_additions']['/etc/dpkg/dpkg.cfg.d/unknown'] = 'a' * 64
        with self.assertRaises(ValueError):
            self.execute()
        self.assertEqual(self.events, [])

    def test_wrong_binding_and_changed_addition_hash(self):
        for key in ('origin_bundle_sha256', 'origin_spec_sha256', 'hostname', 'kernel'):
            with self.subTest(key=key), patch.dict(self.spec, {key: 'wrong'}), self.assertRaises(ValueError):
                self.execute()
        with patch.dict(self.spec['package_additions'], {'/usr/lib/needrestart/dpkg-status': 'a' * 64}):
            with self.assertRaises(ValueError):
                self.execute()

    def test_changed_original_member_or_spec(self):
        for name in ('worker.py', 'spec.json', 'apt.conf', 'hook-validate'):
            original = (self.stage / name).read_bytes()
            w.replace(self.stage / name, b'drift', 0o600)
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.execute()
            w.replace(self.stage / name, original, 0o600)
        self.assertEqual(self.events, [])

    def test_failed_live_or_mismatched_original_process(self):
        terminal = json.loads(w.read(self.stage / 'apt-install-terminal.json'))
        for changes in ({'exit_status': 100}, {'failure': 'timeout'}, {'pid': 123}, {'boot': 'other'}):
            self.overwrite('apt-install-terminal.json', dict(terminal, **changes))
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.execute()
        self.overwrite('apt-install-terminal.json', terminal)
        with patch.object(w, 'process_ticks', return_value='1'), self.assertRaises(ValueError):
            self.execute()
        with patch.object(w, 'boot', return_value='other'), self.assertRaises(ValueError):
            self.execute()
        self.assertEqual(self.events, [])

    def test_hook_failure_or_missing_terminal_holds(self):
        self.overwrite('hook-listchanges-terminal.json', {'exit_status': 1})
        with self.assertRaises(ValueError):
            self.execute()
        self.overwrite('hook-listchanges-terminal.json', {'exit_status': 0})
        (self.stage / 'apt-install-terminal.json').unlink()
        with self.assertRaises(FileNotFoundError):
            self.execute()
        self.assertEqual(self.events, [])

    def test_lock_or_control_drift_holds_without_claim(self):
        for name in ('locks_free', 'guard_controls'):
            with patch.object(w, name, side_effect=ValueError('drift')), self.assertRaises(ValueError):
                self.execute()
        self.assertFalse((self.stage / (c.PREFIX + '-claim.json')).exists())

    def test_acceptance_failure_keeps_controls_and_claim_blocks_replay(self):
        with patch.object(w, 'acceptance', side_effect=ValueError('unknown configuration')):
            with self.assertRaises(ValueError):
                self.execute()
        self.assertEqual(self.events, [])
        self.assertTrue((self.stage / (c.PREFIX + '-failure.json')).exists())
        with self.assertRaises(FileExistsError):
            self.execute()

    def test_cleanup_failure_is_unresolved(self):
        with patch.object(w, 'restore_controls', side_effect=ValueError('mask drift')):
            with self.assertRaises(ValueError):
                self.execute()
        self.assertEqual(self.events, ['acceptance'])
        self.assertFalse((self.stage / (c.PREFIX + '-complete.json')).exists())

    def test_readback_does_not_mutate_even_after_claim(self):
        w.record(c.PREFIX + '-claim', {})
        before = {p.name: p.read_bytes() for p in self.stage.iterdir()}
        self.assertEqual(self.execute('readback')['state'], 'continuation_readback_collected')
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.stage.iterdir()})
        self.assertEqual(self.events, [])

    def test_expired_or_wrong_mode_or_payload_holds(self):
        for mode in ('install', 'configure', 'unknown'):
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                self.execute(mode)
        with patch.dict(self.spec, expires_epoch=int(time.time()) - 1), self.assertRaises(ValueError):
            self.execute()
        with self.assertRaises(ValueError):
            c.continue_entry(self.spec, {'worker.py': b'drift'}, int(time.time()), 'recover', w)

    def test_real_input_guard_rejects_unknown_directory_members(self):
        directory = self.stage / 'dpkg.cfg.d'
        directory.mkdir()
        w.create(directory / 'needrestart', b'packaged hook')
        adjusted = c.continued_spec(self.spec)
        # Exercise the original filesystem guard on the corrected package effects.
        adjusted['directories'] = {str(directory): adjusted['directories']['/etc/dpkg/dpkg.cfg.d']}
        adjusted['inputs'] = []
        adjusted['package_created_inputs'] = {str(directory / 'needrestart'): w.sha(b'packaged hook')}
        w.check_inputs(adjusted, after=True)
        w.create(directory / 'unknown', b'unknown')
        with self.assertRaisesRegex(ValueError, 'config input set drift'):
            w.check_inputs(adjusted, after=True)
        (directory / 'unknown').unlink()
        w.replace(directory / 'needrestart', b'drift', 0o600)
        with self.assertRaisesRegex(ValueError, 'installed candidate policy/helper drift'):
            w.check_inputs(adjusted, after=True)


if __name__ == '__main__':
    unittest.main()
