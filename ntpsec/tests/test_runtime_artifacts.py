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
from unittest.mock import patch

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
        spec_raw = a.encoded({'endpoints': ['192.0.2.1', '2001:db8::1']})
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
                patch.object(monitor, 'unpack', side_effect=lambda raw: old if raw == b'prerequisite' else files):
            monitor.revalidation(files)
            for name in a.CODE_PATHS:
                with self.subTest(member=name), self.assertRaisesRegex(ValueError, 'matching continuity'):
                    monitor.revalidation(dict(files, **{name: files[name]+b'\n# drift'}))

    def test_retired_sealer_cannot_create_new_legacy_trials(self):
        with self.assertRaisesRegex(ValueError, 'retired'): load('run-service-cutover.py').seal(None)


if __name__ == '__main__': unittest.main()
