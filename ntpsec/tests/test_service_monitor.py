#!/usr/bin/python3
"""Offline activation handoff, watchdog races, observation and recovery boundaries."""
import copy
import base64
from contextlib import nullcontext
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
                    evidence=Mock(return_value=b'{"identity":"expected"}'))
                observed = {'identity': 'changed' if case == 'continuity' else 'expected'}
                checker = types.SimpleNamespace(Transaction=lambda spec: types.SimpleNamespace(
                    core=types.SimpleNamespace(i=types.SimpleNamespace(observation=lambda: observed))))
                base.load.return_value = checker
                with patch.object(c, 'validate', return_value=(rspec, {'stage.py': b''}, report, source)), \
                        patch.object(c, 'revalidation', return_value=(fresh, {}, fresh_report)), \
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
