#!/usr/bin/python3
"""Offline historical-expiry, live-drift, recovery and read-only receipt checks."""
import base64
import copy
from contextlib import nullcontext
import importlib.util
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), ROOT/'scripts'/name)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


c = load('run-runtime-revalidation.py'); continuity = load('runtime-continuity.py')
host = load('host-configuration-stage.py'); base = load('service-cutover-stage.py')
monitor = load('service-monitor-stage.py')


def hardware_fixture():
    raw = c.encoded({'host_recipe': {'board': 'fixture'}})
    hardware = {'uart': '/dev/ttyAMA0', 'pps': {'device': '/dev/pps0'}, 'rtc': {'device': '/dev/rtc0'}}
    state = {'phase': 'accepted', 'accepted_boot_id': 'fixture-boot', 'accepted_epoch': 1000,
             'checks': dict.fromkeys(host.HARDWARE_LABELS, True), 'hardware': hardware}
    gate = {'stage': '/hardware', 'spec_sha256': c.sha(raw), 'bundle_sha256': 'bound',
            'boot_hashes': {'/boot/config': c.sha(b'boot')}}
    receipt = {'spec_sha256': gate['spec_sha256'], 'bundle_sha256': 'bound', 'boot_id': 'fixture-boot',
               'checks': state['checks'], 'hardware': hardware}
    data = {'/hardware/spec.json': raw, '/hardware/state.json': c.encoded(state),
            '/runtime/hardware-cleanup.json': c.encoded({'bundle_sha256': 'bound', 'result': state}),
            '/runtime/hardware-acceptance.json': c.encoded(receipt), '/boot/config': b'boot'}
    tx = types.SimpleNamespace(spec={'hardware_prerequisite': gate}, root=Path('/runtime'),
        recipe={'original': True}, hardware_metadata=Mock(return_value=hardware),
        h=types.SimpleNamespace(read=lambda p, **kw: data[str(p)], sha=c.sha))
    return tx, data, state


class HardwareTests(unittest.TestCase):
    def test_frozen_age_rejection_becomes_fresh_fact_check_without_rewriting_history(self):
        tx, data, state = hardware_fixture(); original = copy.deepcopy(data)
        with patch.object(host, 'boot_id', return_value='fixture-boot'), patch.object(continuity.time, 'time', return_value=1000+7*86400):
            with self.assertRaisesRegex(ValueError, 'hardware/reboot'): host.Transaction.hardware_gate(tx)
            self.assertEqual(continuity.hardware_gate(tx, host), state)
        self.assertEqual(data, original); self.assertEqual(tx.recipe, {'original': True})
        tx.hardware_metadata.assert_called_once()

    def test_expiry_never_masks_live_or_provenance_drift(self):
        for case in ('boot', 'bytes', 'receipt', 'closure', 'state', 'future', 'metadata', 'boolean'):
            tx, data, state = hardware_fixture()
            if case == 'bytes': data['/boot/config'] = b'changed'
            if case == 'receipt': data['/runtime/hardware-acceptance.json'] = b'null'
            if case == 'closure':
                value = json.loads(data['/runtime/hardware-cleanup.json']); value['bundle_sha256'] = 'other'
                data['/runtime/hardware-cleanup.json'] = c.encoded(value)
            if case in ('state', 'future'):
                state['accepted_epoch'] = 999999999 if case == 'future' else 900
                data['/hardware/state.json'] = c.encoded(state)
                if case == 'future': data['/runtime/hardware-cleanup.json'] = c.encoded({'bundle_sha256': 'bound', 'result': state})
            if case == 'metadata': tx.hardware_metadata.return_value = {'wrong': 'device'}
            if case == 'boolean':
                state['checks'][next(iter(state['checks']))] = 1
                data['/hardware/state.json'] = c.encoded(state)
            with self.subTest(case=case), patch.object(host, 'boot_id', return_value='other' if case == 'boot' else 'fixture-boot'), \
                    patch.object(continuity.time, 'time', return_value=200000), self.assertRaises(ValueError):
                continuity.hardware_gate(tx, host)
            self.assertEqual(tx.recipe, {'original': True})

    def test_recovery_restores_before_expiry_safe_check_and_still_holds_on_drift(self):
        for drift in (False, True):
            hw, data, historic = hardware_fixture()
            if drift: data['/boot/config'] = b'changed'
            with self.subTest(drift=drift), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary); dest = root/'config'; dest.write_bytes(b'candidate')
                cls = monitor.transaction_class(base, types.SimpleNamespace())
                tx = cls.__new__(cls); tx.root = root; tx.s = {'recipe': {'timeservice': {}}, 'operation_id': 'fixture', 'recovery_unit': 'fixture', 'purpose': 'service-monitor'}
                tx.f = {'candidate': b'candidate', 'runtime-continuity.py': b'fixture'}
                tx.current = {'phase': 'monitoring', 'installed': [str(dest)], 'created_directories': []}
                tx.state = lambda: copy.deepcopy(tx.current); tx.lock = lambda: nullcontext()
                def write(name, value):
                    if name == 'state.json': tx.current = copy.deepcopy(value)
                tx.write = write
                before = {'files': {str(dest): {'sha256': c.sha(b'old'), 'base64': base64.b64encode(b'old').decode(),
                          'mode': 0o644, 'uid': 0, 'gid': 0}}, 'serial': {}, 'termios': 'saved'}
                tx.h = types.SimpleNamespace(read=lambda p, **kw: c.encoded(before), sync=Mock())
                tx.a = types.SimpleNamespace(idle=Mock(), serial_identity=lambda: {}, context=Mock(side_effect=ValueError('expired legacy gate')))
                tx.run = Mock(return_value='saved'); tx.systemctl = Mock(return_value='not-found')
                tx.snapshot = lambda name: {'sha256': c.sha(Path(name).read_bytes())}
                tx.replace = lambda name, raw, *args: Path(name).write_bytes(raw)
                helper = types.SimpleNamespace(context=lambda *args: continuity.hardware_gate(hw, host))
                with patch.dict(base.DESTINATIONS, {str(dest): ('candidate', 0o644)}, clear=True), \
                        patch.object(base, 'clear_restored_failure'), patch.object(monitor, 'module', return_value=helper), \
                        patch.object(host, 'boot_id', return_value='fixture-boot'), patch.object(continuity.time, 'time', return_value=9*86400):
                    if drift:
                        with self.assertRaisesRegex(ValueError, 'boot-file drift'): tx.recover()
                        self.assertEqual(tx.current['phase'], 'recovery_held')
                    else: self.assertEqual(tx.recover()['phase'], 'recovered')
                self.assertEqual(dest.read_bytes(), b'old'); tx.a.context.assert_not_called()
                self.assertEqual(historic['accepted_epoch'], 1000)


class ContextTests(unittest.TestCase):
    def test_private_context_preserves_sources_and_unlocks_on_drift(self):
        for changed in (False, True):
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary); sub = root/'runtime-check'; sub.mkdir()
                runtime = {'stage': '/source', 'members': {'code.py': c.sha(b'code')}}
                state = {'phase': 'accepted'}; retained = {'state.json': c.encoded(state)}
                data = {str(sub/'code.py'): b'code', str(sub/'spec.json'): c.encoded(dict(runtime, stage=str(sub))),
                        '/source/state.json': b'changed' if changed else retained['state.json']}
                a = types.SimpleNamespace(validate=Mock(return_value=(runtime, {})), source_guard=Mock(return_value=(17, retained)),
                    load=Mock(), sha=c.sha, encoded=c.encoded)
                tx = types.SimpleNamespace(a=a, h=types.SimpleNamespace(read=lambda p, **kw: data[str(p)]),
                    rf={'runtime-cleanup.json': c.encoded({'result': state})}, alias={'source_stage': '/source'}, root=root, run=Mock())
                check = types.SimpleNamespace(probe=Mock(return_value={'hardware': {}}), core=types.SimpleNamespace(i=types.SimpleNamespace(observation=lambda: {'boot': 'same'})))
                with patch.object(continuity, 'transaction', return_value=check), patch.object(continuity.os, 'close') as close:
                    if changed:
                        with self.assertRaisesRegex(ValueError, 'source changed'): continuity.context(tx)
                    else: self.assertEqual(continuity.context(tx)['observation'], {'boot': 'same'})
                    close.assert_called_once_with(17); check.probe.assert_called_once()


class ReceiptTests(unittest.TestCase):
    def fixture(self):
        spec = {'endpoints': ['192.0.2.1', '2001:db8::1'], 'boot_id': 'boot', 'prepared_epoch': 1000, 'expires_epoch': 87400}
        evidence = {n: {'sha256': c.sha(b'{}'), 'base64': base64.b64encode(b'{}').decode()} for n in c.EVIDENCE}
        current = {'epoch': 1100, 'runtime': {'phase': 'ready', 'boot_id': 'boot', 'hardware': {}}, 'observation': {'boot_id': 'boot'}}
        evidence['current-runtime.json'] = {'sha256': c.sha(c.encoded(current)), 'base64': base64.b64encode(c.encoded(current)).decode()}
        report = {'phase': 'runtime_validated', 'epoch': 1100, 'boot_id': 'boot', 'checks': dict.fromkeys(c.CHECKS, True),
                  'source_preserved': True, 'time_service_accepted': False, 'evidence': evidence,
                  'hardware': {}, 'observation_sha256': c.sha(c.encoded(current['observation']))}
        return spec, report

    def test_matching_readbacks_accept_prerequisites_only(self):
        spec, report = self.fixture(); result = c.terminal(spec, 'digest', dict.fromkeys(spec['endpoints'], report))
        self.assertEqual(result['state'], 'runtime_validated'); self.assertFalse(result['time_service_accepted'])
        for case in ('missing_check', 'evidence', 'epoch', 'boot', 'timing', 'endpoint', 'observation', 'hardware'):
            other = copy.deepcopy(report)
            if case == 'missing_check': other['checks'].pop('hardware')
            if case == 'evidence': other['evidence']['commands.jsonl']['sha256'] = 'changed'
            if case == 'epoch': other['epoch'] = 999999
            if case == 'boot': other['boot_id'] = 'other'
            if case == 'timing': other['time_service_accepted'] = True
            if case == 'observation': other['observation_sha256'] = 'changed'
            if case == 'hardware': other['hardware'] = {'wrong': True}
            results = dict.fromkeys(spec['endpoints'], other)
            if case == 'endpoint': results[spec['endpoints'][1]] = report | {'phase': 'validation_held'}
            with self.subTest(case=case), self.assertRaises(ValueError): c.terminal(spec, 'digest', results)

    def test_successor_binds_real_validation_receipt_closure_and_checker(self):
        successor = load('run-service-monitor.py'); spec, report = self.fixture()
        raw = (ROOT/'scripts/run-runtime-revalidation.py').read_bytes()
        archive = {'spec.json': c.encoded(spec), 'continuity.py': b'checker', 'stage.py': raw, 'monitor.tar': b'origin'}
        receipt = c.terminal(spec, c.sha(b'archive'), dict.fromkeys(spec['endpoints'], report))
        response = {'spec_sha256': c.sha(archive['spec.json']), 'result': report}
        proof = {'readbacks': [response, copy.deepcopy(response)], 'acceptance': receipt, 'cleanup': {
            'spec_sha256': response['spec_sha256'], 'result': {'phase': 'cleaned', 'evidence_preserved': True,
                'report_sha256': receipt['report_sha256']}}}
        origin = {name: name.encode() for name in (*successor.REFERENCE, 'restoration.tar', 'restoration-proof.json')}
        for case in ('valid', 'closure', 'checker', 'readback', 'origin'):
            files = dict(origin, **{'revalidation-controller.py': raw, 'runtime-continuity.py': b'checker', 'revalidation.tar': b'archive'})
            value = copy.deepcopy(proof)
            if case == 'closure': value['cleanup']['result']['evidence_preserved'] = False
            if case == 'checker': files['runtime-continuity.py'] = b'other'
            if case == 'readback': value['readbacks'][1]['result']['epoch'] += 1
            if case == 'origin': files['reference.tar'] = b'other'
            files['revalidation-proof.json'] = c.encoded(value)
            with self.subTest(case=case), patch.object(successor, 'frozen', return_value=c), \
                    patch.object(c, 'validate'), patch.object(successor, 'unpack', side_effect=[archive, origin]):
                if case == 'valid': self.assertEqual(successor.revalidation(files)[2], report)
                else:
                    with self.assertRaises(ValueError): successor.revalidation(files)

    def test_failed_stage_rejects_progress_and_any_worker(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); spec = {'stage': str(root), 'members': {}, 'apply_unit': 'apply', 'recovery_unit': 'recovery'}
            files = {'spec.json': c.encoded(spec)}
            h = types.SimpleNamespace(ancestors=Mock(), read=lambda p, **kw: files[p.name])
            run = Mock(return_value='not-found\n')
            self.assertTrue(c.failed_stage(h, spec, files, run)['state_absent'])
            run.return_value = 'loaded'
            with self.assertRaisesRegex(ValueError, 'worker/unit'): c.failed_stage(h, spec, files, run)
            (root/'state.json').write_text('{}')
            with self.assertRaisesRegex(ValueError, 'progressed'): c.failed_stage(h, spec, files, run)

    def test_closure_requires_terminal_digest_and_preserves_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); spec = {'stage': str(root)}; report = c.encoded({'phase': 'validation_held'})
            h = types.SimpleNamespace(read=lambda *args, **kw: report, create=lambda p, raw: p.write_bytes(raw))
            with patch.object(c, 'validate'), patch.object(c, 'frozen', return_value=types.SimpleNamespace(protected=lambda *args: h)):
                with self.assertRaises(ValueError): c.entry(spec, {'inspector.py': b''}, 'cleanup', {'report_sha256': 'wrong'})
                result = c.entry(spec, {'inspector.py': b''}, 'cleanup', {'report_sha256': c.sha(report)})
            self.assertTrue(result['evidence_preserved']); self.assertEqual(sorted(p.name for p in root.iterdir()), ['cleanup.json'])


if __name__ == '__main__': unittest.main()
