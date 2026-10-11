#!/usr/bin/python3
"""Offline retained-candidate acceptance, replay and input-drift regressions."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SEALED = (Path(__file__).parent / 'source-build-stage.py').is_file()


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


c = load('continuation', Path(__file__).parent / 'source-build-stage.py' if SEALED
         else ROOT / 'scripts/continue-source-acceptance.py')
w = c.original_worker if SEALED else load('worker', ROOT / 'scripts/source-build-stage.py')


class Continuation(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / c.ORIGIN_STAGE
        self.root.mkdir(mode=0o700)
        (self.root / 'candidate').mkdir(mode=0o700)
        (self.root / 'candidate/stage').mkdir(mode=0o700)
        source = {'archive': 'source.tar', 'sha256': w.sha(b'source'), 'options':
                  ['timeservice=yes', 'sirf=yes', 'earthmate=yes', 'evermore=yes', 'control_socket=yes']}
        clock = b'def target_identity(h): pass\ndef require_no_package_applications(): pass\ndef build(*args): raise AssertionError("build replay")\n'
        helpers = {'clockmaker.py': clock, 'pinup.py': b'helper', 'timeservice.py': b'helper'}
        profile = {'hostname': w.HOSTNAME, 'prefix': '/usr/local', 'jobs': 2,
                   'python': {'version': [3, 13], 'module_directory': '/usr/local/lib/python3.13/dist-packages'},
                   'packages': {'bc': '1', 'pps-tools': '1'},
                   'sources': {'gpsd': source, 'ntpsec': source},
                   'helpers': {n: w.sha(b) for n, b in helpers.items()}}
        recipe = json.dumps({'sources': profile['sources']}).encode()
        profile['recipe_sha256'] = w.sha(recipe)
        original = dict(helpers, **{'source-build-stage.py': b'old worker',
                         'source.tar': b'source', 'recipe.json': recipe,
                         'profile.json': json.dumps(profile).encode()})
        self.origin = {'hostname': w.HOSTNAME, 'kernel': w.KERNEL, 'inventory': {'base': ['1', 'ii ']},
                       'python': {'version': [3, 13, 5], 'module_directory': profile['python']['module_directory'],
                                  'extension_suffix': '.cpython-313-aarch64-linux-gnu.so'},
                       'pps_header_sha256': w.sha(b'header'),
                       'members': {n: w.sha(b) for n, b in original.items()}}
        for n, data in original.items():
            self.write(n, data)
        self.write('spec.json', json.dumps(self.origin).encode())
        self.continuity = {'boot': 'same', 'services': 'same'}
        self.write('claim.json', json.dumps({'pid': 99999999, 'continuity': self.continuity,
                   'bundle_spec_sha256': w.sha((self.root / 'spec.json').read_bytes())}).encode())
        self.write('failure.json', b'original failure')
        self.write('candidate/build.log', b'upstream success')
        self.write('acceptance.log', b'original smoke failure')
        self.write('candidate/release.json', json.dumps({'files': {},
                   'profile_sha256': self.origin['members']['profile.json']}).encode())
        retained = ('spec.json', 'claim.json', 'failure.json', 'candidate/build.log',
                    'candidate/release.json', 'acceptance.log')
        self.spec = dict(self.origin, operation='source-acceptance-continuation',
                         origin_bundle_sha256=c.ORIGIN_BUNDLE,
                         prepared_epoch=int(time.time()), expires_epoch=int(time.time())+3600,
                         members={'source-build-stage.py': w.sha(b'new worker')},
                         retained={n: w.sha((self.root / n).read_bytes()) for n in retained})
        self.files = {'source-build-stage.py': b'new worker'}
        self.original = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}

    def write(self, name, data):
        p = self.root / name
        p.write_bytes(data)
        p.chmod(0o600)

    def execute(self, mode='accept', failure=False, inventories=None, continuities=None):
        previous = w.STAGE
        self.addCleanup(setattr, w, 'STAGE', previous)
        original_read = Path.read_bytes
        with patch.object(w, 'identity', return_value=self.root), \
                patch.object(w, 'packages', side_effect=inventories or [self.spec['inventory']]*2), \
                patch.object(w, 'continuity', side_effect=continuities or [self.continuity]*2), \
                patch.object(c.signal, 'signal'), patch.object(c.signal, 'alarm'), \
                patch.object(w, 'staged_acceptance', side_effect=ValueError('smoke failed') if failure else None,
                             return_value={'staged_files': 159, 'source_tests_passed': True}) as acceptance, \
                patch.object(Path, 'read_bytes', autospec=True, side_effect=lambda p:
                             b'header' if str(p) == '/usr/include/sys/timepps.h' else original_read(p)):
            result = c.continue_entry(self.spec, self.files, int(time.time()), mode, w)
            return result, acceptance.call_count

    def test_accepts_preserved_candidate_without_rebuild_or_overwrite(self):
        result, calls = self.execute()
        self.assertEqual(calls, 1)
        self.assertFalse(result['build_repeated'])
        self.assertFalse(result['live_installed'])
        self.assertTrue((self.root / (c.PREFIX + '-complete.json')).is_file())
        for p, data in self.original.items():
            self.assertEqual(p.read_bytes(), data)

    def test_readback_executes_no_acceptance_and_writes_no_receipts(self):
        result, calls = self.execute('readback')
        self.assertEqual(result['state'], 'source_acceptance_readback')
        self.assertEqual(calls, 0)
        self.assertFalse(list(self.root.glob(c.PREFIX + '*')))

    def test_replay_is_rejected_by_exclusive_claim(self):
        self.execute()
        (self.root / (c.PREFIX + '-complete.json')).unlink()
        with self.assertRaises(FileExistsError):
            self.execute()

    def test_smoke_failure_preserves_candidate_and_records_hold(self):
        with self.assertRaisesRegex(ValueError, 'smoke failed'):
            self.execute(failure=True)
        self.assertTrue((self.root / (c.PREFIX + '-failure.json')).exists())
        self.assertFalse((self.root / (c.PREFIX + '-complete.json')).exists())
        for p, data in self.original.items():
            self.assertEqual(p.read_bytes(), data)

    def test_retained_evidence_and_original_member_drift_rejected(self):
        for name in ('candidate/release.json', 'candidate/build.log', 'claim.json', 'failure.json',
                     'spec.json', 'profile.json', 'clockmaker.py', 'source.tar'):
            p = self.root / name
            before = p.read_bytes()
            self.write(name, b'drift')
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.execute()
            self.write(name, before)
        self.assertFalse(list(self.root.glob(c.PREFIX + '*')))

    def test_wrong_mode_binding_or_missing_evidence_rejected(self):
        with self.assertRaises(ValueError):
            self.execute('build')
        for name in ('operation', 'origin_bundle_sha256', 'hostname', 'pps_header_sha256'):
            with patch.dict(self.spec, {name: 'drift'}), self.assertRaises(ValueError):
                self.execute()
        with patch.dict(self.spec['retained'], clear=True), self.assertRaises(ValueError):
            self.execute()

    def test_inventory_or_continuity_drift_before_and_after_smoke_holds(self):
        for key, records in (('inventories', [{}, self.spec['inventory']]),
                             ('continuities', [{}, self.continuity])):
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.execute(**{key: records})
        with self.assertRaisesRegex(ValueError, 'during acceptance'):
            self.execute(inventories=[self.spec['inventory'], {}])
        self.assertFalse((self.root / (c.PREFIX + '-complete.json')).exists())

    def test_private_reader_rejects_symlinks_and_public_inputs(self):
        path = self.root / 'claim.json'
        link = self.root / 'link'
        link.symlink_to(path)
        with self.assertRaises(OSError):
            c.private_bytes(link)
        path.chmod(0o644)
        with self.assertRaises(ValueError):
            c.private_bytes(path)


if __name__ == '__main__':
    unittest.main()
