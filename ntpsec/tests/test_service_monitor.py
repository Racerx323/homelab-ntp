#!/usr/bin/python3
"""Offline activation handoff, watchdog races, observation and recovery boundaries."""
import copy
import base64
from contextlib import nullcontext, ExitStack
import importlib.util
import io
import json
from pathlib import Path
import struct
import tarfile
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), ROOT/'scripts'/name)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


c = load('run-service-monitor.py'); stage = load('service-monitor-stage.py')
client = load('check-time-client.py')


def fixture():
    files = {n: (ROOT/path).read_bytes() for n, path in c.PATHS.items()}
    files.update({n: ('fixture '+n).encode() for n in c.REFERENCE})
    files.update({'restoration.tar': b'bound archive fixture', 'restoration-proof.json': b'{}',
                  'revalidation.tar': b'fresh fixture', 'revalidation-proof.json': b'{}'})
    restored = {'hostname': 'fixture', 'kernel': 'fixture', 'boot_id': 'a'*32,
                'endpoints': ['192.0.2.1', '2001:db8::1'], 'old_ipv4': '192.0.2.1',
                'prepared_epoch': 300, 'expires_epoch': 86700}
    spec = dict(restored, schema=2, purpose='service-monitor', operation_id='fixture',
                stage='/var/lib/ntp-acquire-fixture', apply_unit='ntp-monitor-fixture',
                recovery_unit='ntp-monitor-fixture-watchdog', prepared_epoch=400,
                restoration_sha256=c.sha(files['restoration.tar']))
    recipe = json.loads(files['recipe.json']); recipe['hostname'] = 'fixture'
    files['recipe.json'] = c.encoded(recipe)
    recipe, service, fault = c.rendered(spec, files); spec['recipe'] = recipe
    files.update({'timeservice.json': c.encoded(recipe['timeservice']), 'timeservice.service': service, 'fault.service': fault})
    bind(spec, files)
    return spec, files, (restored, {}, {}, {n: files[n] for n in c.REFERENCE})


def bind(spec, files):
    spec['members'] = {n: c.sha(files[n]) for n in set(c.PATHS)|c.EXTRA}
    files.update({'spec.json': c.encoded(spec), 'review.md': c.review(spec).encode()})
    files['manifest.json'] = c.encoded({n: c.sha(v) for n, v in files.items() if n != 'manifest.json'})


class BindingTests(unittest.TestCase):
    def test_missing_agent_does_not_register_an_execution(self):
        spec, files, _ = fixture()
        with tempfile.TemporaryDirectory() as temporary, patch.dict(c.os.environ, {}, clear=True), \
                patch.object(c, 'prepare', return_value=(spec, files)):
            root = Path(temporary)
            args = types.SimpleNamespace(bundle=root/'service-monitor.tar', sha256='bound', mode='start')
            with self.assertRaisesRegex(ValueError, 'SSH agent'): c.execute(args)
            self.assertEqual(list(root.iterdir()), [])

    def test_current_start_requires_local_review_and_spec_bytes(self):
        spec, files, _ = fixture()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); root.chmod(0o700)
            for name, path in c.PATHS.items():
                p = root/path; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(files[name])
            for name in ('review.md', 'spec.json', 'known_hosts'):
                (root/name).write_bytes(files[name]); (root/name).chmod(0o600)
            bundle = root/'service-monitor.tar'
            with tarfile.open(bundle, 'w') as archive:
                for name, raw in files.items():
                    item = tarfile.TarInfo(name); item.size = len(raw); archive.addfile(item, io.BytesIO(raw))
            bundle.chmod(0o600); digest = c.sha(bundle.read_bytes())
            transport = c.load(ROOT/'scripts/run-foundation-preflight.py')
            with patch.object(c, 'ROOT', root), patch.object(c, 'load', return_value=transport), \
                    patch.object(c, 'frozen', return_value=types.SimpleNamespace(validate=Mock())), patch.object(c.time, 'time', return_value=400):
                c.prepare(bundle, digest)
                for name in ('review.md', 'spec.json'):
                    (root/name).write_bytes(b'edited')
                    with self.assertRaisesRegex(ValueError, 'local monitor review/spec drift'): c.prepare(bundle, digest)
                    c.prepare(bundle, digest, require_current=False)
                    (root/name).write_bytes(files[name])

    def test_real_restoration_terminal_api_and_closure(self):
        # Exercise the frozen helper API rather than replacing restoration().
        helper = c.frozen((ROOT/'scripts/run-cutover-restoration.py').read_bytes())
        spec = {'endpoints': ['192.0.2.1', '2001:db8::1']}
        archive = {'stage.py': b'fixture helper', 'spec.json': c.encoded(spec), 'source.tar': b'source'}
        result = {'phase': 'restoration_verified', 'restoration_accepted': True,
                  'source_preserved': True, 'time_service_accepted': False,
                  'checks': dict.fromkeys(helper.CHECKS, True),
                  'evidence': {name: {'base64': base64.b64encode(b'{}').decode(),
                                    'sha256': c.sha(b'{}')} for name in helper.EVIDENCE}}
        receipt = helper.terminal(spec, c.sha(b'archive'), dict.fromkeys(spec['endpoints'], result))
        response = {'spec_sha256': c.sha(archive['spec.json']), 'result': result}
        proof = {'acceptance': receipt, 'readbacks': [response, copy.deepcopy(response)],
                 'cleanup': {'spec_sha256': response['spec_sha256'], 'result': {
                     'phase': 'cleaned', 'report_sha256': receipt['report_sha256'],
                     'source_preserved': True, 'evidence_preserved': True}}}
        for case in ('valid', 'closure', 'readback', 'evidence', 'receipt'):
            changed = copy.deepcopy(proof)
            if case == 'closure': changed['cleanup']['result']['evidence_preserved'] = False
            if case == 'readback': changed['readbacks'][1]['result']['phase'] = 'restoration_held'
            if case == 'evidence':
                for row in changed['readbacks']: row['result']['evidence']['commands.jsonl']['sha256'] = '0'*64
            if case == 'receipt': changed['acceptance']['state'] = 'restoration_held'
            files = {'restoration.tar': b'archive', 'restoration-proof.json': c.encoded(changed)}
            with self.subTest(case=case), patch.object(c, 'unpack', side_effect=[archive, {}]), \
                    patch.object(c, 'frozen', return_value=helper), patch.object(helper, 'validate'):
                if case == 'valid': self.assertEqual(c.restoration(files)[2], result)
                else:
                    with self.assertRaises(ValueError): c.restoration(files)

    def test_closed_profile_has_independent_watchdog_and_no_restart(self):
        spec, files, restored = fixture()
        with patch.object(c, 'restoration', return_value=restored), \
                patch.object(c, 'revalidation', return_value=(restored[0], {}, {'epoch': 400})):
            c.validate(spec, files)
        self.assertEqual(spec['recipe']['recovery_seconds'], 600)
        self.assertNotIn('completion_seconds', spec['recipe']['timeservice']['pps_startup'])
        self.assertIn(b'OnFailure=ntp-monitor-recovery.service', files['timeservice.service'])
        self.assertIn(b'Restart=no', files['timeservice.service'])
        self.assertIn(spec['stage'].encode()+b'/stage.py worker recover', files['fault.service'])
        self.assertIn('not timing acceptance', c.review(spec))

    def test_reject_identity_window_profile_and_manifest_drift(self):
        for case in ('window', 'host', 'path', 'hash', 'restart', 'receiver', 'monitor'):
            spec, files, restored = fixture()
            if case == 'window': spec['expires_epoch'] += 1
            elif case == 'host': spec['hostname'] = 'other'
            elif case == 'path': spec['stage'] = '/tmp/unprotected'
            elif case == 'hash': files['pps-startup.py'] += b'\n# changed'
            elif case == 'restart': files['timeservice.service'] = files['timeservice.service'].replace(b'Restart=no', b'Restart=always'); bind(spec, files)
            elif case == 'receiver':
                raw = json.loads(files['recipe.json']); raw['timeservice']['gpsd'].remove('-b'); files['recipe.json'] = c.encoded(raw)
                recipe, service, fault = c.rendered(spec, files); spec['recipe'] = recipe
                files['timeservice.json'] = c.encoded(recipe['timeservice']); bind(spec, files)
            else:
                raw = json.loads(files['timeservice.json']); raw['pps_monitor_evidence'] = '/tmp/status'
                files['timeservice.json'] = c.encoded(raw); bind(spec, files)
            with self.subTest(case=case), patch.object(c, 'restoration', return_value=restored), \
                    patch.object(c, 'revalidation', return_value=(restored[0], {}, {'epoch': 400})), self.assertRaises(ValueError):
                c.validate(spec, files)

    def test_flat_archive_rejects_manifest_and_member_abuse(self):
        for case in ('duplicate', 'path', 'manifest', 'symlink'):
            data = io.BytesIO()
            with tarfile.open(fileobj=data, mode='w') as tar:
                item = tarfile.TarInfo('../escape' if case == 'path' else 'record')
                item.size = 1
                if case == 'symlink': item.type = tarfile.SYMTYPE; item.linkname = '/tmp/x'; item.size = 0
                tar.addfile(item, io.BytesIO(b'x'))
                if case == 'duplicate': tar.addfile(item, io.BytesIO(b'x'))
                if case == 'manifest':
                    item = tarfile.TarInfo('manifest.json'); item.size = 2; tar.addfile(item, io.BytesIO(b'{}'))
            with self.subTest(case=case), self.assertRaises(ValueError): c.unpack(data.getvalue())

    def test_no_timing_acceptance_transport_mode(self):
        spec, files, _ = fixture()
        with self.assertRaises(ValueError): c.payload(spec, files, 'accept')
        for mode in c.MODES: self.assertIn(b'CUTOVER_EXIT_STATUS', c.payload(spec, files, mode))

    def test_recovery_uses_sealed_inputs_after_repository_drift(self):
        spec, files, restored = fixture()
        with tempfile.TemporaryDirectory() as temporary, patch.object(c, 'frozen', return_value=types.SimpleNamespace(validate=Mock())):
            root = Path(temporary); root.chmod(0o700); bundle = root/'service-monitor.tar'
            with tarfile.open(bundle, 'w') as tar:
                for name, raw in files.items():
                    item = tarfile.TarInfo(name); item.size = len(raw); tar.addfile(item, io.BytesIO(raw))
            bundle.chmod(0o600)
            (root/'known_hosts').write_bytes(files['known_hosts']); (root/'known_hosts').chmod(0o600)
            checksum = c.sha(bundle.read_bytes())
            with self.assertRaisesRegex(ValueError, 'input drift'): c.prepare(bundle, checksum)
            self.assertEqual(c.prepare(bundle, checksum, require_current=False)[0], spec)
            with self.assertRaisesRegex(ValueError, 'digest'): c.prepare(bundle, '0'*64, require_current=False)


class FakeTransaction:
    def __init__(self, root):
        self.root = root; self.s, self.f, _ = fixture()
        self.s['stage'] = str(root)
        self.current = {'phase': 'observing', 'deadline': 1600, 'supervisor_pid': 42, 'apply_monotonic': 900}
        self.writes = []; self.calls = []
        self.h = types.SimpleNamespace(create=lambda path, raw: path.write_bytes(raw))
        self.unchanged = Mock(); self.cancel_timer = Mock()
        self.measure = Mock(return_value={'checks': dict.fromkeys(c.SAFETY, True)})
        self.monitor_record = Mock(return_value={'running': True, 'phase': 'bootstrap', 'started_monotonic': 900, 'elapsed_seconds': 100})
        self.systemctl = Mock(return_value='inactive\n')

    def state(self): return copy.deepcopy(self.current)
    def lock(self): return nullcontext()
    def write(self, name, value):
        if name == 'state.json': self.current = copy.deepcopy(value); self.writes.append(value['phase'])
    def recover(self, locked=False):
        self.calls.append('recover'); self.current['phase'] = 'recovered'; return self.state()


MonitorTransaction = stage.transaction_class(types.SimpleNamespace(Transaction=FakeTransaction), c)


def proofs(tx):
    result = {e: tx.state() for e in tx.s['endpoints']}
    result['client'] = {'target': tx.s['hostname'], 'spec_sha256': c.sha(c.encoded(tx.s)), 'epoch': 1000,
                        'checks': {'ipv4': True, 'ipv6': True, 'queries_denied': True}, 'time_service_accepted': False}
    return result


class HandoffTests(unittest.TestCase):
    def test_preflight_revalidates_restoration_and_releases_source_lock(self):
        for case in ('valid', 'source', 'timer', 'collision', 'continuity'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                base = types.SimpleNamespace(Transaction=FakeTransaction, load=Mock())
                cls = stage.transaction_class(base, c); tx = cls(root)
                rspec = {'stage': str(root/'restored'), 'members': {}}
                old = {'stage': str(root/'source')}; source = {'spec.json': c.encoded(old)}
                report = {'phase': 'restoration_verified'}; cleanup = {'phase': 'cleaned'}
                tx.f['restoration-proof.json'] = c.encoded({'cleanup': {'result': cleanup}})
                tx.f['revalidation-proof.json'] = tx.f['restoration-proof.json']
                fresh = {'stage': str(root/'fresh'), 'members': {}}
                fresh_report = {'observation_sha256': c.sha(c.encoded({'identity': 'expected'}))}
                data = {'report.json': c.encoded(report), 'cleanup.json': c.encoded(cleanup),
                        'state.json': b'held', 'source-state-before.json': b'held', 'spec.json': b'{}'}
                if case == 'source': data['state.json'] = b'changed'
                tx.h.ancestors = Mock()
                tx.h.read = lambda path, **kw: c.encoded(fresh_report) if path.parent.name == 'fresh' and path.name == 'report.json' else data[path.name]
                tx.run = Mock(); tx.systemctl = Mock(side_effect=['loaded' if case == 'collision' else 'not-found', ''])
                validator = types.SimpleNamespace(source_lock=Mock(return_value=17),
                    timer_state=Mock(return_value={'timer': {'ActiveState': 'active' if case == 'timer' else 'inactive'}}),
                    evidence=Mock(return_value=b'{"identity":"expected"}'),
                    validate=Mock(return_value=(old, {}, None)), failed_stage=Mock())
                observed = {'identity': 'changed' if case == 'continuity' else 'expected'}
                checker = types.SimpleNamespace(Transaction=lambda spec: types.SimpleNamespace(
                    core=types.SimpleNamespace(i=types.SimpleNamespace(observation=lambda: observed))))
                base.load.return_value = checker
                with patch.object(c, 'validate', return_value=(rspec, {'stage.py': b''}, report, source)), \
                        patch.object(c, 'revalidation', return_value=(fresh, {'stage.py': b'', 'monitor-proof.json': b'{}'}, fresh_report)), \
                        patch.object(stage, 'module', return_value=validator), patch.object(stage.os, 'close') as close, \
                        patch.object(FakeTransaction, 'preflight', create=True) as preflight:
                    if case == 'valid':
                        cls.preflight(tx); preflight.assert_called_once()
                    else:
                        with self.assertRaises(ValueError): cls.preflight(tx)
                    close.assert_called_once_with(17)

    def test_structural_handoff_does_not_require_quality_or_enable_boot(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(stage.time, 'monotonic', return_value=1000), patch.object(stage.time, 'time', return_value=1000):
            tx = MonitorTransaction(Path(temporary)); result = tx.accept(proofs(tx))
            self.assertEqual(result['phase'], 'monitoring'); self.assertFalse(result['time_service_accepted'])
            tx.cancel_timer.assert_called_once(); tx.unchanged.assert_called_once()
            self.assertNotIn('enable', str(tx.systemctl.call_args_list))
            self.assertNotIn('recover', tx.calls)

    def test_invalid_handoff_never_cancels_watchdog(self):
        for case in ('endpoint', 'client', 'age', 'safety', 'monitor', 'reserve', 'phase'):
            with tempfile.TemporaryDirectory() as temporary, patch.object(stage.time, 'monotonic', return_value=1000), patch.object(stage.time, 'time', return_value=1000):
                tx = MonitorTransaction(Path(temporary)); proof = proofs(tx)
                if case == 'endpoint': proof[tx.s['endpoints'][1]]['supervisor_pid'] = 99
                elif case == 'client': proof['client']['time_service_accepted'] = True
                elif case == 'age': proof['client']['epoch'] = 800
                elif case == 'safety': tx.measure.return_value['checks']['credentials'] = False
                elif case == 'monitor': tx.monitor_record.return_value['running'] = False
                elif case == 'reserve': tx.current['deadline'] = 1059
                else: tx.current['phase'] = 'monitoring'
                with self.subTest(case=case), self.assertRaises(ValueError): tx.accept(proof)
                tx.cancel_timer.assert_not_called()

    def test_cancellation_failure_restores_and_queued_watchdog_is_safe(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(stage.time, 'monotonic', return_value=1000), patch.object(stage.time, 'time', return_value=1000):
            tx = MonitorTransaction(Path(temporary)); tx.cancel_timer.side_effect = OSError('timer failure')
            with self.assertRaises(OSError): tx.accept(proofs(tx))
            self.assertIn('handoff_held', tx.writes); self.assertEqual(tx.current['phase'], 'recovered')
            self.assertEqual(tx.calls, ['recover'])
            tx.watchdog(); self.assertEqual(tx.calls, ['recover'])

    def test_watchdog_after_handoff_is_noop_but_operator_recovery_works(self):
        with tempfile.TemporaryDirectory() as temporary:
            tx = MonitorTransaction(Path(temporary)); tx.current['phase'] = 'monitoring'
            self.assertEqual(tx.watchdog()['phase'], 'monitoring'); self.assertEqual(tx.calls, [])
            self.assertEqual(tx.recover()['phase'], 'recovered'); self.assertEqual(tx.calls, ['recover'])
            tx.current['phase'] = 'applying'; tx.watchdog(); self.assertEqual(tx.calls, ['recover', 'recover'])


class ObservationTests(unittest.TestCase):
    def test_numbered_snapshots_survive_readback_without_repeated_capture(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(stage.time, 'monotonic', return_value=1000):
            tx = MonitorTransaction(Path(temporary)); tx.current.update(phase='monitoring', observations=0)
            first = tx.observe({'attempt': 1})
            self.assertTrue((tx.root/'observation-1.json').is_file())
            self.assertEqual(first, tx.state())
            for attempt in (1, 3):
                with self.assertRaises(ValueError): tx.observe({'attempt': attempt})
            with self.assertRaisesRegex(ValueError, 'interval'): tx.observe({'attempt': 2})
            self.assertEqual(tx.current['phase'], 'monitoring')

    def test_ready_cadence_and_capture_budget_do_not_stop_server(self):
        with tempfile.TemporaryDirectory() as temporary:
            tx = MonitorTransaction(Path(temporary)); tx.current.update(phase='monitoring', observations=0)
            tx.monitor_record.return_value['phase'] = 'ready'
            with patch.object(stage.time, 'monotonic', return_value=1000): tx.observe({'attempt': 1})
            with patch.object(stage.time, 'monotonic', return_value=1299), self.assertRaises(ValueError): tx.observe({'attempt': 2})
            with patch.object(stage.time, 'monotonic', return_value=1300): tx.observe({'attempt': 2})
            tx.current['observations'] = 60
            with self.assertRaises(ValueError): tx.observe({'attempt': 61})
            self.assertEqual(tx.calls, []); self.assertEqual(tx.current['phase'], 'monitoring')

    def test_recovery_reads_terminal_evidence_after_pair_stop(self):
        with tempfile.TemporaryDirectory() as temporary:
            tx = MonitorTransaction(Path(temporary)); raw = c.encoded({'phase': 'failed', 'running': False})
            (tx.root/'startup-monitor.json').write_bytes(raw); tx.h.read = Mock(return_value=raw)
            result = tx.recover()
            self.assertFalse(result['startup_promotion']['running'])
            self.assertEqual(tx.calls, ['recover'])


class RealHandoffTests(unittest.TestCase):
    def test_inherited_handoff_uses_fresh_identity_and_rejects_drift(self):
        base = load('service-cutover-stage.py'); acquisition = load('run-gpsd-acquisition.py')
        for case in ('valid', 'journal_reader', 'reader_exits', 'boot', 'inventory', 'python',
                     'preflight', 'native', 'candidate', 'extra_child', 'reader_args', 'reader_uid',
                     'missing_daemon', 'competing_daemon', 'credentials', 'journal', 'pps_extra',
                     'pps_missing', 'pps_duplicate', 'pps_identity', 'pps_mapping'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
                root = Path(temporary)
                def mapped(value):
                    p = Path(value)
                    return p if p.is_relative_to(root) else root/str(p).lstrip('/')
                def put(path, raw):
                    p = mapped(path); p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(raw)
                cls = stage.transaction_class(base, c); tx = cls.__new__(cls)
                tx.root = root; tx.s, tx.f, _ = fixture(); tx.s['boot_id'] = 'current-boot'
                state = {'phase': 'observing', 'deadline': 1600, 'supervisor_pid': 42, 'apply_monotonic': 900}
                tx.state = lambda: copy.deepcopy(state); tx.lock = lambda: nullcontext()
                tx.write = lambda name, value: state.update(value) if name == 'state.json' else put(root/name, c.encoded(value))
                tx.h = types.SimpleNamespace(read=lambda path, **kw: mapped(path).read_bytes())
                tx.retained = Mock(); tx.cancel_timer = Mock()
                expected = {'boot_id': 'current-boot', 'inventory': {'gpsd': 'pinned'}, 'python': {'version': [3, 13]},
                            'active_daemons': [], 'services': 'baseline'}
                put(root/'fresh-preflight.json', c.encoded({'observation': expected, 'checks': 'passed',
                    'restoration_sha256': tx.s['restoration_sha256']}))
                if case == 'preflight': put(root/'fresh-preflight.json', b'{}')
                observed = copy.deepcopy(expected)
                observed['active_daemons'] = [{'pid': 51}, {'pid': 52}]
                if case == 'competing_daemon': observed['active_daemons'].append({'pid': 90})
                if case in ('boot', 'inventory', 'python'):
                    observed[{'boot': 'boot_id'}.get(case, case)] = 'drift'
                native = {'files': {'usr/local/bin/ntpq': {'sha256': 'pinned'}}}
                old_native = copy.deepcopy(native)
                if case == 'native': native['files']['usr/local/bin/ntpq']['sha256'] = 'drift'
                check = types.SimpleNamespace(spec={'hardware_prerequisite': {'boot_hashes': {}}, 'members': {'release.json': 'digest'}},
                    baseline={'observation': dict(expected, boot_id='historical-boot'), 'installed_state': old_native,
                              'protected_files': {}, 'queries': {'time_units': {'stdout': ''}}},
                    accounts=lambda: {}, state=lambda: {'created_account': {}, 'cache_after': {}}, snapshot_file=lambda p: {},
                    core=types.SimpleNamespace(i=types.SimpleNamespace(observation=lambda: observed),
                        cm=types.SimpleNamespace(inspect_install=lambda *a: native)), network_checks=Mock())
                helper = load('runtime-continuity.py')
                current = helper.checker(tx.f['hardware-checker.py'], tx.f['pps-checker.py'])
                fixture_spec = importlib.util.spec_from_file_location('pps_fixture', ROOT/'tests/pps_fixture.py')
                fixture_module = importlib.util.module_from_spec(fixture_spec); fixture_spec.loader.exec_module(fixture_module)
                tree = fixture_module.HardwareTree(stack, current)
                accepted, hardware_data = tree.bind(check)
                original_hardware_data = copy.deepcopy(hardware_data)
                # Stopped preflight uses real immutable receipt and metadata validation.
                self.assertEqual(helper.hardware_gate(check, current), accepted)
                if case == 'pps_extra': tree.add_class()
                if case == 'pps_missing': tree.remove_class('pps0')
                if case == 'pps_duplicate': tree.add_class(name='pps@12.-1')
                if case == 'pps_identity': tree.put('/sys/devices/virtual/pps/pps0/dev', b'250:0')
                if case == 'pps_mapping':
                    tree.remove_class('pps0'); tree.add_class('pps2', 'pps@12.-1', '249:0')
                    tree.devices['/dev/pps2'] = tree.devices['/dev/pps0']; tree.put('/dev/pps2', b'')
                original_module = stage.module
                stack.enter_context(patch.object(helper, 'checker', return_value=current))
                stack.enter_context(patch.object(stage, 'module', side_effect=lambda raw, name:
                    helper if name == 'current_runtime' else original_module(raw, name)))
                host = types.SimpleNamespace(Transaction=lambda spec: check, unit_states=lambda text: {})
                put(root/'runtime-check/spec.json', b'{}')
                tx.f['receiver-runtime.json'] = b'{"runtime":{"files":{}}}'
                shm = b'key shmid perms size cpid uid gid cuid cgid nattch\n'
                put('/proc/sysvipc/shm', shm); tx.rf = {'prior-shm-after.txt': shm}; tx.a = acquisition
                def snapshot(name):
                    member, mode = base.DESTINATIONS[name]
                    return {'sha256': 'drift' if case == 'candidate' else c.sha(tx.f[member]), 'mode': mode, 'uid': 0, 'gid': 0}
                tx.snapshot = snapshot
                children = ['51', '52']; executable = {'51': '/usr/local/sbin/gpsd', '52': '/usr/local/sbin/ntpd'}
                put('/proc/51/status', b'Uid: 65534 65534 65534 65534\nGid: 20 20 20 20\n')
                put('/proc/52/status', b'Uid: 999 999 999 999\nGid: 985 985 985 985\n')
                if case == 'credentials': put('/proc/52/status', b'Uid: 0 0 0 0\nGid: 0 0 0 0\n')
                if case == 'missing_daemon': children.remove('52')
                if case in ('journal_reader', 'reader_exits', 'reader_args', 'reader_uid', 'extra_child'):
                    children.append('53'); executable['53'] = '/usr/bin/journalctl' if case != 'extra_child' else '/usr/bin/sh'
                    put('/proc/53/status', b'Uid: 0 0 0 0\nGid: 0 0 0 0\n')
                    argv = ['/usr/bin/journalctl', '--quiet', '--no-pager', '--output=json', '--boot=currentboot',
                            '_PID=52', '_EXE=/usr/local/sbin/ntpd', '--lines=1000', '--after-cursor=s=cursor']
                    if case == 'reader_args': argv[5] = '_PID=99'
                    if case == 'reader_uid': put('/proc/53/status', b'Uid: 1 1 1 1\nGid: 0 0 0 0\n')
                    put('/proc/53/cmdline', ('\0'.join(argv)+'\0').encode())
                put('/proc/42/task/42/children', ' '.join(children).encode())
                original_readlink = base.os.readlink
                def readlink(path, *args, **kwargs):
                    if not str(path).startswith('/proc/'):
                        return original_readlink(path, *args, **kwargs)
                    child = Path(path).parent.name
                    if child == '53' and case == 'reader_exits': raise FileNotFoundError(path)
                    return executable[child]
                values = {'--property=MainPID': '42', '--property=NRestarts': '0', '--property=DropInPaths': ''}
                def systemctl(*args):
                    if args[1] == tx.s['recovery_unit']+'.timer': return 'inactive'
                    for key, value in values.items():
                        if key in args: return value
                    if args[1] == 'systemd-timesyncd.service': return 'inactive'
                    if args[1] == 'timeservice.service': return 'active'
                    return ''
                tx.systemctl = systemctl
                journal = []
                for i, message in enumerate(('AUTH: authreadkeys: reading /run/ntpsec-startup/control.key', 'AUTH: authreadkeys: added 1 keys')):
                    journal.append(json.dumps({'_BOOT_ID': 'currentboot', '__MONOTONIC_TIMESTAMP': str((901+i)*1000000),
                        'PRIORITY': '3', '_SYSTEMD_UNIT': 'timeservice.service', '_EXE': '/usr/local/sbin/ntpd',
                        '_COMM': 'ntpd', '_TRANSPORT': 'syslog', 'SYSLOG_IDENTIFIER': 'ntpd', '_PID': '52', 'MESSAGE': message}))
                if case == 'journal': journal = []
                measurement = {'system': {'leap': 3, 'stratum': 16}, 'peers': [
                    {'status': 0, 'variables': {'srcadr': 'SHM(2)', 'reach': 0}}]}
                tx.run = lambda argv, **kw: c.encoded(measurement).decode() if argv[0] == '/usr/bin/python3' else '\n'.join(journal)
                put('/run/ntpsec-startup/promotion.json', c.encoded({'phase': 'bootstrap', 'supervisor_pid': 42, 'ntpd_pid': 52}))
                put(root/'startup-monitor.json', c.encoded({'boot_id': tx.s['boot_id'], 'supervisor_pid': 42,
                    'final_sha256': c.sha(tx.f['ntp.conf']), 'running': True, 'phase': 'bootstrap',
                    'started_monotonic': 900, 'elapsed_seconds': 100}))
                for obj, name, value in ((base, 'Path', mapped), (base, 'load', lambda p: host),
                    (base.os, 'readlink', readlink), (c, 'revalidation', lambda f: ({}, {}, {'observation_sha256': c.sha(c.encoded(expected))})),
                    (stage.time, 'time', lambda: 1000), (stage.time, 'monotonic', lambda: 1000)):
                    stack.enter_context(patch.object(obj, name, value))
                stack.enter_context(patch.dict(base.DIRECTORIES, {}, clear=True))
                if case in ('valid', 'journal_reader', 'reader_exits', 'pps_extra'):
                    result = tx.accept(proofs(tx))
                    self.assertEqual(result['phase'], 'monitoring'); self.assertFalse(result['time_service_accepted'])
                    self.assertFalse(result['handoff_measurement']['checks']['pps_selected'])
                    tx.cancel_timer.assert_called_once(); check.network_checks.assert_called_once()
                    self.assertEqual(result['pps_handoff_observation']['selected']['name'], 'pps@12.-1')
                    if case == 'pps_extra':
                        self.assertEqual(len(result['pps_handoff_observation']['classes']), 2)
                        # Actual recovery restores its file and then invokes real current hardware validation.
                        dest = root/'candidate'; dest.write_bytes(b'candidate')
                        state.update(installed=[str(dest)], created_directories=[])
                        before = {'files': {str(dest): {'sha256': c.sha(b'old'),
                            'base64': base64.b64encode(b'old').decode(), 'mode': 0o644, 'uid': 0, 'gid': 0}},
                            'serial': {}, 'termios': 'saved'}
                        tx.h.read = lambda path, **kw: c.encoded(before)
                        tx.h.sync = Mock(); tx.run = Mock(return_value='saved')
                        tx.a = types.SimpleNamespace(idle=Mock(), serial_identity=lambda: {})
                        tx.replace = lambda name, raw, *args: Path(name).write_bytes(raw)
                        tx.snapshot = lambda name: {'sha256': c.sha(Path(name).read_bytes())}
                        def restore_systemctl(*args):
                            if args[:2] == ('show', 'timeservice.service'):
                                return 'loaded'
                            if args[:2] == ('stop', 'timeservice.service'):
                                tree.remove_class()
                            return 'not-found'
                        tx.systemctl = restore_systemctl
                        tx.runtime_context = lambda *args: helper.hardware_gate(check, current)
                        with patch.dict(base.DESTINATIONS, {str(dest): ('candidate', 0o644)}, clear=True), \
                                patch.object(base, 'clear_restored_failure'):
                            tx.f['candidate'] = b'candidate'
                            self.assertEqual(tx.recover()['phase'], 'recovered')
                        self.assertEqual(dest.read_bytes(), b'old')
                        self.assertEqual(len(check.state()['pps_observation']['classes']), 1)
                        self.assertEqual(len(tx.state()['pps_handoff_observation']['classes']), 2)
                else:
                    with self.assertRaises((ValueError, KeyError)): tx.accept(proofs(tx))
                    tx.cancel_timer.assert_not_called(); self.assertEqual(state['phase'], 'observing')
                    if case.startswith('pps_'):
                        observation = state['pps_handoff_observation']
                        self.assertIn('classes', observation)
                        self.assertIn('error', observation)
                self.assertEqual(hardware_data, original_hardware_data)


class ClientTests(unittest.TestCase):
    def test_unsynchronized_response_proves_protocol_only(self):
        nonce = b'12345678'; raw = bytearray(48); raw[0] = 0xe4; raw[1] = 16
        raw[24:32] = nonce; raw[40:48] = struct.pack('!II', 1, 1)
        value = client.ntp_response(raw, nonce, structural=True)
        self.assertFalse(value['time_service_accepted']); self.assertEqual(value['leap'], 3)
        with self.assertRaises(ValueError): client.ntp_response(raw, nonce)
        for broken in (bytes(raw[:47]), bytes(raw[:24])+b'badnonce'+bytes(raw[32:])):
            with self.assertRaises(ValueError): client.ntp_response(broken, nonce, structural=True)

    def test_structural_checks_never_claim_mdns_or_timing(self):
        spec = {'hostname': 'fixture', 'endpoints': ['192.0.2.1', '2001:db8::1']}
        with patch.object(client, 'client_ntp', return_value={'queries_denied': True}) as ntp, patch.object(client, 'browse') as browse:
            result = client.check(spec, 'digest', structural=True)
        self.assertEqual(ntp.call_count, 2); browse.assert_not_called()
        self.assertFalse(result['time_service_accepted']); self.assertNotIn('mdns', result['checks'])


if __name__ == '__main__': unittest.main()
