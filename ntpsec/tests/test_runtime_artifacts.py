#!/usr/bin/python3
"""Historical packages provide facts, never executable implementations."""
import copy
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import types
import unittest
from unittest.mock import patch, MagicMock

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT/'scripts'/name)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


a = load('runtime-artifacts.py')


def bundle(change=None):
    files = {'stage.py': b'raise AssertionError("historical code executed")\n', 'data.json': b'{}'}
    spec = {'operation_id': 'fixture', 'stage': '/var/lib/ntp-acquire-fixture',
            'endpoints': ['192.0.2.1', '2001:db8::1'], 'prepared_epoch': 1,
            'expires_epoch': 86401, 'purpose': 'fixture',
            'members': {n: a.sha(v) for n, v in files.items()}}
    files['spec.json'] = a.encoded(spec)
    files['manifest.json'] = a.encoded({n: a.sha(v) for n, v in files.items()})
    if change: change(files)
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode='w') as tar:
        for name, raw in files.items():
            item = tarfile.TarInfo(name); item.size = len(raw)
            tar.addfile(item, io.BytesIO(raw))
    return stream.getvalue()


class ArtifactTests(unittest.TestCase):
    def test_member_and_aggregate_bounds_remain_unchanged(self):
        monitor = load('run-service-monitor.py')
        for name, size, extra, accepted in (
                ('monitor.tar', 60, 0, True), ('revalidation.tar', 60, 0, True),
                ('other.tar', 65, 0, False), ('monitor.tar', 97, 0, False),
                ('monitor.tar', 60, 37, False)):
            with self.subTest(name=name, size=size, extra=extra):
                # Mock archive I/O only; both real validators enforce the bounds.
                with tarfile.open(fileobj=io.BytesIO(bundle())) as archive:
                    files = {m.name: archive.extractfile(m).read() for m in archive.getmembers()}
                files[name] = b'archive'; files['extra.tar'] = b'extra'
                spec = json.loads(files['spec.json'])
                spec['members'] = {n: a.sha(v) for n, v in files.items() if n not in ('spec.json', 'manifest.json')}
                files['spec.json'] = a.encoded(spec)
                files['manifest.json'] = a.encoded({n: a.sha(v) for n, v in files.items() if n != 'manifest.json'})
                members = []
                for key, raw in files.items():
                    member = tarfile.TarInfo(key); member.size = len(raw)
                    if key == name: member.size = size*1024**2
                    if key == 'extra.tar': member.size = extra*1024**2
                    members.append(member)
                source = MagicMock(); source.__enter__.return_value = source
                source.getmembers.return_value = members
                source.extractfile.side_effect = lambda m: io.BytesIO(files[m.name])
                for reader in (a.archive, monitor.unpack):
                    with patch.object(tarfile, 'open', return_value=source):
                        if accepted: reader(b'fixture')
                        else:
                            with self.assertRaises(ValueError): reader(b'fixture')

    def test_archive_reads_manifest_without_executing_historical_code(self):
        spec, files = a.archive(bundle(), 'fixture')
        self.assertEqual(spec['operation_id'], 'fixture')
        self.assertIn(b'AssertionError', files['stage.py'])

    def test_archive_rejects_digest_identity_window_and_paths(self):
        for field, value in [('stage', '/wrong'), ('expires_epoch', 90000),
                             ('endpoints', ['same', 'same']), ('members', {}),
                             ('operation_id', '../escape')]:
            def change(files):
                spec = json.loads(files['spec.json']); spec[field] = value
                files['spec.json'] = a.encoded(spec)
                files['manifest.json'] = a.encoded({n: a.sha(v) for n, v in files.items() if n != 'manifest.json'})
            with self.subTest(field=field), self.assertRaises(ValueError): a.archive(bundle(change))
        with self.assertRaises(ValueError): a.archive(bundle(lambda f: f.update({'data.json': b'changed'})))
        with self.assertRaises(ValueError): a.archive(bundle(lambda f: f.update({'../escape': b'x'})))
        with self.assertRaises(ValueError): a.archive(bundle(), 'wrong')

    def test_runtime_replaces_all_code_and_preserves_explicit_data(self):
        code = {n: (ROOT/p).read_bytes() for n, p in a.CODE_PATHS.items()}
        old = {n: b'raise AssertionError("old code")' for n in a.RUNTIME_CODE}
        old['baseline.json'] = b'{"accepted":true}'
        runtime = {'stage': '/old', 'members': {n: a.sha(v) for n, v in old.items()}}
        before = copy.deepcopy((runtime, old))
        spec, files = a.runtime_inputs(runtime, old, code, '/new/runtime-check')
        self.assertEqual(files['baseline.json'], old['baseline.json'])
        for name, member in a.RUNTIME_CODE.items(): self.assertEqual(files[name], code[member])
        self.assertEqual(spec['members'], {n: a.sha(v) for n, v in files.items()})
        self.assertEqual((runtime, old), before)
        runtime['members']['unknown.py'] = a.sha(b'code')
        with self.assertRaisesRegex(ValueError, 'unmapped'): a.runtime_inputs(runtime, old, code, '/new')

    def test_active_manifests_pin_every_runtime_implementation(self):
        for name in ('run-runtime-revalidation.py', 'run-service-monitor.py'):
            paths = load(name).PATHS
            for member, path in a.CODE_PATHS.items(): self.assertEqual(paths[member], path)

    def test_monitor_rejects_each_code_change_since_accepted_revalidation(self):
        monitor = load('run-service-monitor.py')
        files = {n: (ROOT/p).read_bytes() for n, p in monitor.PATHS.items()}
        files.update({n: b'facts' for n in (*monitor.REFERENCE, 'restoration.tar', 'restoration-proof.json')})
        spec_raw = a.encoded({'schema': 1, 'endpoints': ['192.0.2.1', '2001:db8::1']})
        receipt = {'state': 'runtime_validated', 'report_sha256': a.sha(b'{}')}
        response = {'spec_sha256': a.sha(spec_raw), 'result': {}}
        files['revalidation.tar'] = b'prerequisite'
        files['revalidation-proof.json'] = a.encoded({'acceptance': receipt, 'readbacks': [response, response],
            'cleanup': {'spec_sha256': a.sha(spec_raw), 'result': {'phase': 'cleaned',
                'evidence_preserved': True, 'report_sha256': receipt['report_sha256']}}})
        old = {n: files[n] for n in a.CODE_PATHS}
        old.update({'spec.json': spec_raw, 'stage.py': files['revalidation-controller.py'],
                    'continuity.py': files['runtime-continuity.py'], 'monitor.tar': b'origin'})
        controller = types.SimpleNamespace(validate=lambda *args: None, terminal=lambda *args: receipt)
        # Isolate the cross-operation code equality contract; the real reader is used.
        with patch.object(monitor, 'frozen', side_effect=lambda raw: controller if raw == files['revalidation-controller.py'] else a), \
                patch.object(monitor, 'unpack', side_effect=lambda raw: old if raw == b'prerequisite' else files), \
                patch.object(a, 'monitor_source', return_value=({}, files, 'source')):
            monitor.revalidation(files)
            for name in a.CODE_PATHS:
                with self.subTest(member=name), self.assertRaisesRegex(ValueError, 'matching continuity'):
                    monitor.revalidation(dict(files, **{name: files[name]+b'\n# drift'}))

    def test_retired_sealer_cannot_create_new_legacy_trials(self):
        with self.assertRaisesRegex(ValueError, 'retired'): load('run-service-cutover.py').seal(None)


def tar_bytes(files):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode='w') as archive:
        for name, raw in sorted(files.items()):
            item = tarfile.TarInfo(name); item.size = len(raw)
            archive.addfile(item, io.BytesIO(raw))
    return stream.getvalue()


def tar_files(raw):
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        return {m.name: archive.extractfile(m).read() for m in archive.getmembers()}


def monitor_bundle():
    files = {n: bundle() if n.endswith('.tar') else b'facts' for n in a.MONITOR_DATA}
    files.update({'revalidation.tar': bundle(), 'obsolete.py': b'raise AssertionError("old code ran")'})
    spec = {'operation_id': 'fixture', 'stage': '/var/lib/ntp-acquire-fixture',
            'endpoints': ['192.0.2.1', '2001:db8::1'], 'prepared_epoch': 1,
            'expires_epoch': 86401, 'purpose': 'service-monitor',
            'members': {n: a.sha(v) for n, v in files.items()}}
    files.update({'spec.json': a.encoded(spec), 'review.md': b'review'})
    files['manifest.json'] = a.encoded({n: a.sha(v) for n, v in files.items()})
    return tar_bytes(files)


class FlatInputsTests(unittest.TestCase):
    def test_selected_inputs_preserve_original_identity_without_old_trial_subtree(self):
        raw = monitor_bundle(); old = tar_files(raw)
        packed = a.project_monitor(raw, a.sha(raw))
        spec, files, digest = a.monitor_source(packed)
        self.assertEqual(digest, a.sha(raw)); self.assertEqual(files['spec.json'], old['spec.json'])
        self.assertEqual(files['source-manifest.json'], old['manifest.json'])
        self.assertNotIn('revalidation.tar', files); self.assertNotIn('obsolete.py', files)
        for name in a.MONITOR_DATA: self.assertEqual(files[name], old[name])
        store = tar_files(packed); index = json.loads(store['artifact-index.json'])
        self.assertEqual({n for n in store if n != 'artifact-index.json'}, {a.sha(v) for n, v in store.items() if n != 'artifact-index.json'})
        self.assertEqual(len(index['archives']), 2)  # Repeated identical nested archive stored once.
        self.assertEqual(a.project_monitor(raw, a.sha(raw)), packed)
        self.assertEqual(a.monitor_source(raw)[2], a.sha(raw))  # Retained legacy facts remain readable.
        with self.assertRaisesRegex(ValueError, 'digest'): a.project_monitor(raw, '0'*64)

    def test_flat_object_recipe_failures(self):
        packed = a.project_monitor(monitor_bundle(), a.sha(monitor_bundle()))
        original = tar_files(packed)
        for case in ('missing', 'changed', 'unreferenced_blob', 'unreferenced_archive', 'cycle',
                     'size', 'oversize', 'aggregate', 'reconstructed', 'index', 'path', 'part', 'root'):
            with self.subTest(case=case):
                files = dict(original); index = json.loads(files['artifact-index.json'])
                node = index['archives'][index['root']]
                blob = next(n for n in files if n != 'artifact-index.json')
                if case == 'missing': del files[blob]
                if case == 'changed': files[blob] += b'changed'
                if case == 'unreferenced_blob': files[a.sha(b'unused')] = b'unused'
                if case == 'unreferenced_archive': index['archives']['0'*64] = copy.deepcopy(node)
                if case == 'cycle': node['parts'] = [{'archive': index['root']}]
                if case == 'size': node['bytes'] += 1
                if case == 'oversize': node['bytes'] = 64*1024**2+1
                if case == 'aggregate':
                    node.update(bytes=60*1024**2, parts=[{'archive': '1'*64}])
                    index['archives']['1'*64] = {'bytes': 40*1024**2, 'parts': [{'blob': blob}]}
                if case == 'reconstructed':
                    index['archives']['0'*64] = copy.deepcopy(node); index['root'] = '0'*64
                if case == 'index': index['schema'] = 2
                if case == 'path': files['../escape'] = b'x'
                if case == 'part': node['parts'] = [{'file': '/etc/passwd'}]
                if case == 'root': index['root'] = '0'*64
                files['artifact-index.json'] = a.encoded(index)
                with self.assertRaises((ValueError, KeyError)): a.monitor_source(tar_bytes(files))

    def test_projection_binds_retained_data_original_manifest_and_closed_membership(self):
        raw = monitor_bundle(); packed = a.project_monitor(raw, a.sha(raw))
        original = tar_files(a.flat_unpack(packed))
        for case in ('data', 'source_manifest', 'identity', 'extra', 'source_digest'):
            with self.subTest(case=case):
                files = dict(original)
                if case == 'data': files['known_hosts'] += b'changed'
                if case == 'source_manifest':
                    manifest = json.loads(files['source-manifest.json']); manifest['obsolete.py'] = '0'*64
                    files['source-manifest.json'] = a.encoded(manifest)
                if case == 'identity': files['spec.json'] = b'{}'
                if case == 'extra': files['obsolete.py'] = b'code'
                if case == 'source_digest':
                    origin = json.loads(files['projection.json']); origin['source_sha256'] = 'invalid'
                    files['projection.json'] = a.encoded(origin)
                files['manifest.json'] = a.encoded({n: a.sha(v) for n, v in files.items() if n != 'manifest.json'})
                with self.assertRaises((ValueError, KeyError)): a.monitor_source(a.flat_pack(tar_bytes(files)))


if __name__ == '__main__': unittest.main()
