#!/usr/bin/python3
"""Offline bounds, continuity and sealed destination lifecycle checks."""
import base64
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]


def load(name, filename):
    definition = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / filename)
    module = importlib.util.module_from_spec(definition)
    definition.loader.exec_module(module)
    return module


i = load('destination_inspector', 'inspect-source-destinations.py')
c = load('destination_controller', 'run-foundation-preflight.py')
s = load('destination_stage', 'foundation-preflight-stage.py')
f = load('observation_helpers', 'foundation-install.py')


class Destinations(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.known = self.root / 'known_hosts'
        self.known.write_bytes(b'fixture.example ssh-ed25519 ' + base64.b64encode(b'fixture key') + b'\n')
        self.known.chmod(0o600)
        release = json.loads((ROOT / 'configs/accepted-source-release.json').read_bytes())
        # This synthetic release exercises current code; do not change the accepted manifest.
        release['helpers']['clockmaker.py'] = c.sha((ROOT / 'scripts/clockmaker.py').read_bytes())
        inventory = {}
        for line in (ROOT / 'configs/accepted-packages.tsv').read_text().splitlines():
            name, version, status = line.split('\t')
            inventory[name] = [version, status]
        build = {'hostname': release['hostname'], 'kernel': release['kernel'],
                 'inventory': inventory, 'boot_id': 'fixture-boot', 'python': {'version': [3, 13, 5]}}
        raw = c.encoded(release)
        spec_raw = c.encoded(build)
        receipt = {'state': 'mdns_source_build_accepted', 'release_sha256': c.sha(raw),
            'spec_sha256': c.sha(spec_raw), 'profile_sha256': release['profile_sha256'],
            'staged_files': len(release['files']), 'inventory_records': len(inventory),
            'transport_exit_status': 0, 'worker_status': 0, 'live_installed': False, 'services_activated': False,
            'acceptance': {'ntpsec_mdns_registration': True, 'source_tests_passed': True,
                           **dict.fromkeys(('gpsd_selected_features', 'gpsd_ublox_driver',
                               'manuals_modules_versions_linkage', 'ntpsec_shm_nts_seccomp'), True),
                           'release_sha256': c.sha(raw)}}
        self.args = SimpleNamespace(action='seal-destinations', known_hosts=self.known,
                                    operation_id='fixture-destinations', output=self.root / 'sealed')
        for name, data in (('release', raw), ('build_spec', spec_raw), ('build_acceptance', c.encoded(receipt))):
            path = self.root / name
            path.write_bytes(data); path.chmod(0o600)
            setattr(self.args, name, path)
            setattr(self.args, name + '_sha256', c.sha(data))
        self.build = build
        self.release = release

    def seal(self):
        with patch.object(c.subprocess, 'run') as run:
            sealed = c.seal(self.args)
            run.assert_not_called()
        spec, files = c.prepare(Path(sealed['bundle']), sealed['sha256'])
        return sealed, spec, files

    def report(self, spec):
        safe = {'type': 'directory', 'uid': 0, 'gid': 0, 'mode': 0o755, 'device': 1,
                'inode': 1, 'links': 1, 'size': 0, 'mtime_ns': 1, 'ctime_ns': 1}
        parents = {str(p): dict(safe) for n in self.release['files'] for p in (Path('/') / n).parents}
        return {'schema': 1, 'collected_epoch': spec['prepared_epoch'], 'hostname': spec['hostname'],
            'kernel': spec['kernel'], 'release_sha256': spec['members']['release.json'],
            'build_spec_sha256': spec['members']['build-spec.json'],
            'installation_state': {'release_sha256': spec['members']['release.json'],
                'previous_sha256': None, 'hostname': spec['hostname'], 'obsolete': [],
                'files': dict.fromkeys(self.release['files'])}, 'parents': parents,
            'observation': {'inventory': self.build['inventory'], 'boot_id': self.build['boot_id'],
                'python': self.build['python'], 'services': '', 'active_daemons': []},
            'collisions': {}, 'continuity_unchanged': True, 'package_mutation_authorized': False,
            'application_mutation_authorized': False}

    def test_offline_seal_binds_release_receipt_helper_and_all_payloads(self):
        sealed, spec, files = self.seal()
        self.assertFalse(sealed['target_contact'])
        self.assertEqual(spec['operation'], 'source-destinations')
        self.assertEqual(set(spec['members']), s.INPUTS | s.DESTINATION_INPUTS)
        for mode in ('collect', 'readback', 'cleanup'):
            compile(c.payload(spec, files, int(time.time()), mode), 'fixture', 'exec')
        i.accepted_inputs(files)
        for member in ('release.json', 'build-spec.json', 'clockmaker.py'):
            changed = dict(files)
            changed[member] += b'\n'
            with self.assertRaisesRegex(ValueError, 'binding'):
                i.accepted_inputs(changed)
        self.args.release_sha256 = '0' * 64
        self.args.output = self.root / 'rejected'
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            c.seal(self.args)
        self.assertFalse(self.args.output.exists())

    def test_unsafe_parent_holds_before_any_destination_content(self):
        path = Path('/usr/local/bin/fixture')
        safe = {'type': 'directory', 'uid': 0, 'gid': 0, 'mode': 0o755}
        for unsafe in (dict(safe, type='symlink'), dict(safe, uid=1000), dict(safe, mode=0o777)):
            with patch.object(i, 'metadata', side_effect=lambda p: unsafe if p == path.parent else safe):
                with self.assertRaisesRegex(ValueError, 'unsafe destination ancestor'):
                    i.parents([path])

    def test_snapshot_absent_file_link_special_bounds_and_mid_read_drift(self):
        path = self.root / 'object'
        worker = SimpleNamespace(read=lambda p, **kwargs: p.read_bytes())
        self.assertIsNone(i.bounded_snapshot(path, worker, [100]))
        path.write_bytes(b'bounded')
        record = i.bounded_snapshot(path, worker, [100])
        self.assertEqual(record['sha256'], hashlib.sha256(b'bounded').hexdigest())
        with self.assertRaisesRegex(ValueError, 'byte bound'):
            i.bounded_snapshot(path, worker, [1])
        def changed(p, **kwargs):
            data = p.read_bytes(); p.write_bytes(b'changed'); return data
        with self.assertRaisesRegex(ValueError, 'changed while hashing'):
            i.bounded_snapshot(path, SimpleNamespace(read=changed), [100])
        path.unlink(); path.symlink_to('/must/not/read')
        worker.read = Mock(side_effect=AssertionError('followed final symlink'))
        self.assertEqual(i.bounded_snapshot(path, worker, [100])['target'], '/must/not/read')
        worker.read.assert_not_called()
        path.unlink(); path.mkdir()
        with self.assertRaisesRegex(ValueError, 'non-file'):
            i.bounded_snapshot(path, worker, [100])

    def test_protected_reader_rejects_hardlinks_and_writable_files(self):
        path = self.root / 'protected'
        path.write_bytes(b'data'); path.chmod(0o600)
        with patch.object(f, 'OWNER', os.getuid()), patch.object(f, 'ancestors'):
            os.link(path, self.root / 'other')
            with self.assertRaisesRegex(ValueError, 'unprotected file'):
                f.read(path)
            (self.root / 'other').unlink(); path.chmod(0o666)
            with self.assertRaisesRegex(ValueError, 'unprotected file'):
                f.read(path)

    def test_validator_requires_complete_records_classification_and_continuity(self):
        _, spec, _ = self.seal()
        report = self.report(spec)
        i.validate(report, spec, self.release, self.build)
        name = next(n for n, r in self.release['files'].items() if r['type'] == 'file')
        report['installation_state']['files'][name] = dict(self.release['files'][name], uid=0, gid=0)
        report['collisions'][name] = 'identical'
        i.validate(report, spec, self.release, self.build)
        report['installation_state']['files'][name]['sha256'] = '0' * 64
        report['collisions'][name] = 'different'
        i.validate(report, spec, self.release, self.build)
        mutations = [lambda r: r['installation_state']['files'].pop(name),
            lambda r: r['parents'].pop('/'), lambda r: r.update(collisions={}),
            lambda r: r['observation'].update(boot_id='changed'),
            lambda r: r['observation'].update(python={}), lambda r: r['observation'].update(inventory={}),
            lambda r: r.update(continuity_unchanged=False),
            lambda r: r.update(collected_epoch=spec['expires_epoch']),
            lambda r: r['installation_state']['files'][name].update(sha256='forged')]
        for mutate in mutations:
            changed = copy.deepcopy(report); mutate(changed)
            with self.assertRaises((ValueError, KeyError)):
                i.validate(changed, spec, self.release, self.build)

    def test_collect_parent_preflight_and_post_observation_drift(self):
        _, spec, files = self.seal()
        for name in ('build-spec.json', 'release.json'):
            (self.root / name).write_bytes(files[name])
        worker = SimpleNamespace(read=lambda p: p.read_bytes())
        clock = SimpleNamespace(read_release=Mock(return_value=self.release),
            safe_destination=lambda n: Path('/') / n, snapshot=Mock(),
            inspect_install=Mock(return_value=self.report(spec)['installation_state']))
        before = self.report(spec)['observation']
        original = clock.snapshot
        with patch.object(i, 'load', return_value=clock), patch.object(i, 'observation', return_value=before), \
                patch.object(i, 'parents', side_effect=ValueError('unsafe ancestor')):
            with self.assertRaisesRegex(ValueError, 'unsafe ancestor'):
                i.collect(self.root, spec, worker, spec['prepared_epoch'])
            clock.inspect_install.assert_not_called()
        with patch.object(i, 'load', return_value=clock), patch.object(i, 'parents', return_value={}), \
                patch.object(i, 'observation', side_effect=[before, dict(before, services='changed')]):
            with self.assertRaisesRegex(ValueError, 'continuity'):
                i.collect(self.root, spec, worker, spec['prepared_epoch'])
        self.assertIs(clock.snapshot, original)
        clock.inspect_install.reset_mock()
        with patch.object(i, 'load', return_value=clock), patch.object(i, 'parents', return_value={}), \
                patch.object(i, 'observation', return_value=before):
            report = i.collect(self.root, spec, worker, spec['prepared_epoch'])
        self.assertEqual(clock.inspect_install.call_count, 2)
        self.assertTrue(report['continuity_unchanged'])

    def test_stage_completed_held_readback_cleanup_and_unknown_entries(self):
        _, original_spec, files = self.seal()
        for outcome in ('completed', 'held'):
            root = self.root / outcome
            spec = dict(original_spec, stage=str(root))
            inputs = {n: files[n] for n in spec['members']}
            worker = SimpleNamespace(ancestors=Mock(), sync=Mock(), read=lambda p: p.read_bytes())
            def create(path, data):
                with path.open('xb') as stream:
                    stream.write(data)
                path.chmod(0o600)
            worker.create = create
            collector = SimpleNamespace(collect=Mock(return_value=self.report(spec)), validate=Mock())
            if outcome == 'held':
                collector.collect.side_effect = ValueError('unsafe collision')
            definition = SimpleNamespace(loader=SimpleNamespace(exec_module=Mock()))
            with patch.object(s, 'identity'), patch.object(s.types, 'ModuleType', return_value=worker), \
                    patch('builtins.exec'), patch.object(s.signal, 'signal'), \
                    patch.object(s.importlib.util, 'spec_from_file_location', return_value=definition), \
                    patch.object(s.importlib.util, 'module_from_spec', return_value=collector):
                result = s.entry(spec, inputs, int(time.time()), 'collect')
                self.assertEqual(result['state'], 'inspection_' + outcome)
                readback = s.entry(spec, inputs, int(time.time()), 'readback')
                collector.collect.assert_called_once()
                if outcome == 'completed':
                    self.assertEqual(base64.b64decode(readback['inspection_base64']), s.encoded(self.report(spec)))
                extra = root / 'preserve'
                extra.write_bytes(b'data')
                with self.assertRaisesRegex(ValueError, 'unexpected stage'):
                    s.entry(spec, inputs, int(time.time()), 'cleanup', readback['terminal_sha256'])
                self.assertTrue(extra.exists()); extra.unlink()
                s.entry(spec, inputs, int(time.time()), 'cleanup', readback['terminal_sha256'])
                self.assertFalse(root.exists())

    def test_queries_hold_on_error_and_never_request_socket_service_properties(self):
        with patch.object(i.subprocess, 'run', return_value=SimpleNamespace(
                returncode=1, stderr=b'', stdout=b'')):
            with self.assertRaisesRegex(ValueError, 'read-only query'):
                i.command(['/usr/bin/dpkg', '--audit'])
        calls = []
        def query(argv):
            calls.append(argv)
            return 'fixture\t1\tii \n' if argv[0].endswith('dpkg-query') else ''
        with patch.object(i, 'command', side_effect=query), patch.object(i.Path, 'glob', return_value=[]), \
                patch.object(i.Path, 'read_text', return_value='fixture-boot'):
            i.observation()
        self.assertEqual({a[0] for a in calls}, {'/usr/bin/dpkg-query', '/usr/bin/dpkg', '/usr/bin/systemctl'})
        sockets = [a for a in calls if 'gpsd.socket' in a]
        self.assertEqual(len(sockets), 1)
        self.assertNotIn('MainPID', ' '.join(sockets[0]))
        self.assertNotIn('NRestarts', ' '.join(sockets[0]))

    def test_controller_accepts_readback_and_cleanup_without_recollecting(self):
        sealed, spec, _ = self.seal()
        raw = c.encoded(self.report(spec))
        report = {'state': 'inspection_completed', 'inspection_base64': base64.b64encode(raw).decode(),
                  'inspection_sha256': c.sha(raw), 'spec_sha256': c.sha(c.encoded(spec)), 'terminal_sha256': 'a'*64}
        def submitted(argv, **kwargs):
            mode = 'cleanup' if (self.args.output / 'cleanup-execution.json').exists() else 'readback'
            value = report if mode == 'readback' else {'state': 'snapshot_stage_removed'}
            kwargs['stdout'].write(c.encoded(value) + b'PREFLIGHT_EXIT_STATUS=0\n')
            return SimpleNamespace(returncode=0)
        args = SimpleNamespace(bundle=Path(sealed['bundle']), sha256=sealed['sha256'], mode='readback')
        with patch.dict(c.os.environ, {'SSH_AUTH_SOCK': '/fixture/agent'}), \
                patch.object(c.subprocess, 'run', side_effect=submitted) as run:
            c.execute(args)
            receipt = json.loads((self.args.output / 'acceptance.json').read_bytes())
            self.assertEqual(receipt['state'], 'source_destinations_accepted')
            self.assertEqual(receipt['installation_state_sha256'], c.sha((self.args.output / 'installation-state.json').read_bytes()))
            args.mode = 'cleanup'; c.execute(args)
            self.assertEqual(run.call_count, 2)
            with self.assertRaises(FileExistsError):
                c.execute(args)
            self.assertEqual(run.call_count, 2)
        self.assertFalse((self.args.output / 'collect-execution.json').exists())


if __name__ == '__main__':
    unittest.main()
