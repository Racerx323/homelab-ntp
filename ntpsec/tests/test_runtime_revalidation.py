#!/usr/bin/python3
"""Offline historical-expiry, live-drift, recovery and read-only receipt checks."""
import base64
import copy
from contextlib import ExitStack, nullcontext
import importlib.util
import json
import os
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
                observer = Mock(return_value='strict observer')
                check = types.SimpleNamespace(probe=Mock(return_value={'hardware': {}}), core=types.SimpleNamespace(i=types.SimpleNamespace(command=observer, observation=lambda: {'boot': 'same'})))
                with patch.object(continuity, 'transaction', return_value=check), patch.object(continuity.os, 'close') as close:
                    if changed:
                        with self.assertRaisesRegex(ValueError, 'source changed'): continuity.context(tx)
                    else: self.assertEqual(continuity.context(tx)['observation'], {'boot': 'same'})
                    close.assert_called_once_with(17); check.probe.assert_called_once()
                    self.assertIs(check.core.i.command, observer)


class CaptureTests(unittest.TestCase):
    """Real alias validation, constructor, preflight and context; host I/O is simulated."""

    def test_capture_crosses_real_preflight_and_rejects_drift(self):
        info = importlib.util.spec_from_file_location('acquisition_fixture', ROOT/'tests/test_gpsd_acquisition.py')
        fixtures = importlib.util.module_from_spec(info); info.loader.exec_module(fixtures)
        acquisition = load('run-gpsd-acquisition.py'); restoration = load('run-cutover-restoration.py')
        for case in ('valid', 'recovered', 'recovered_state', 'old_path', 'runtime_drift', 'continuity_drift', 'worker_active', 'source_changed'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
                sandbox = Path(temporary)
                def mapped(value):
                    p = Path(value)
                    return p if p.is_relative_to(sandbox) else sandbox/str(p).lstrip('/')
                def read(path, **kwargs): return mapped(path).read_bytes()
                def create(path, raw):
                    p = mapped(path); p.parent.mkdir(parents=True, exist_ok=True)
                    with p.open('xb') as stream: stream.write(raw)
                    p.chmod(0o600)
                h = types.SimpleNamespace(read=read, create=create, ancestors=Mock(), sync=Mock(), sha=c.sha)
                refspec, reference = fixtures.fixture()
                runtime_files = acquisition.unpack(reference['runtime.tar'])
                runtime = json.loads(runtime_files['spec.json']); runtime['members'] = {}
                reference['runtime.tar'] = fixtures.archive({'spec.json': c.encoded(runtime)})
                refspec['runtime_sha256'] = c.sha(reference['runtime.tar'])
                receipt = json.loads(reference['runtime-acceptance.json'])
                receipt.update(bundle_sha256=refspec['runtime_sha256'], spec_sha256=c.sha(c.encoded(runtime)))
                reference['runtime-acceptance.json'] = c.encoded(receipt)
                receipt = json.loads(reference['runtime-cleanup.json']); receipt['bundle_sha256'] = refspec['runtime_sha256']
                reference['runtime-cleanup.json'] = c.encoded(receipt)
                prior = acquisition.unpack(reference['prior.tar']); previous = json.loads(prior['spec.json'])
                previous['runtime_sha256'] = refspec['runtime_sha256']
                reference['prior.tar'] = fixtures.archive({'spec.json': c.encoded(previous)})
                for name in ('prior-acceptance.json', 'prior-cleanup.json'):
                    receipt = json.loads(reference[name]); receipt['spec_sha256'] = c.sha(c.encoded(previous))
                    if 'bundle_sha256' in receipt: receipt['bundle_sha256'] = c.sha(reference['prior.tar'])
                    reference[name] = c.encoded(receipt)
                refspec['members'] = {n: c.sha(v) for n, v in reference.items()}
                reference['spec.json'] = c.encoded(refspec)
                reference_raw = fixtures.archive(reference)
                old = dict(refspec, operation_id='failed', stage='/var/lib/ntp-acquire-failed',
                           apply_unit='apply', recovery_unit='watchdog', recipe={'recovery_seconds': 600})
                observed = {'boot_id': 'boot', 'active_daemons': []}
                monitor_files = {'reference.tar': reference_raw, 'reference.py': (ROOT/'scripts/run-gpsd-acquisition.py').read_bytes(),
                                 'receiver-runtime.json': c.encoded({'runtime': {'files': {}}}),
                                 'reference-report.json': c.encoded({'evidence': {}}),
                                 'restoration-proof.json': c.encoded({'cleanup': {'result': {'phase': 'cleaned'}}})}
                old['members'] = {n: c.sha(v) for n, v in monitor_files.items()}
                monitor_files['spec.json'] = c.encoded(old)
                rspec = {'stage': '/var/lib/restoration', 'members': {}}
                report = {'evidence': {'continuity-after.json': {
                    'base64': base64.b64encode(c.encoded(observed)).decode(), 'sha256': c.sha(c.encoded(observed))}}}
                source = {'spec.json': c.encoded({'stage': '/var/lib/held', 'recovery_unit': 'old-recovery'})}
                for name, raw in monitor_files.items(): create(Path(old['stage'])/name, raw)
                mapped(old['stage']).chmod(0o700)
                create(Path(refspec['stage'])/'spec.json', c.encoded(refspec))
                for name, raw in reference.items():
                    if name != 'spec.json': create(Path(refspec['stage'])/name, raw)
                create(Path(rspec['stage'])/'report.json', c.encoded(report))
                create(Path(rspec['stage'])/'cleanup.json', c.encoded({'phase': 'cleaned'}))
                create(Path(rspec['stage'])/'source-state-before.json', b'{}')
                create(Path('/var/lib/held/state.json'), b'{}')
                runtime_state = c.encoded(json.loads(reference['runtime-cleanup.json'])['result'])
                create(Path(refspec['source_stage'])/'state.json', runtime_state)
                files = {n: (ROOT/path).read_bytes() for n, path in c.PATHS.items()}
                files.update({n: b'fixture' for n in c.EXTRA})
                files['monitor-proof.json'] = b'{}'
                files['reference.py'] = monitor_files['reference.py']
                if case in ('recovered', 'recovered_state'):
                    state = {'phase': 'recovered', 'recovered_epoch': 900}
                    response = {'spec_sha256': c.sha(monitor_files['spec.json']), 'result': state}
                    proof = {'recovered': {'state': 'recovered', 'bundle_sha256': c.sha(files['monitor.tar']),
                        'spec_sha256': response['spec_sha256'], 'state_sha256': c.sha(c.encoded(state)), 'time_service_accepted': False},
                        'readbacks': [response, copy.deepcopy(response)],
                        'cleanup': {'spec_sha256': response['spec_sha256'], 'result': dict(state, transient_cleanup=True)}}
                    files['monitor-proof.json'] = c.encoded(proof)
                    create(Path(old['stage'])/'state.json', c.encoded(proof['cleanup']['result'] if case == 'recovered' else state))
                spec = {k: old[k] for k in ('hostname', 'boot_id', 'kernel', 'endpoints', 'old_ipv4')}
                spec.update(schema=1, purpose='runtime-revalidation', operation_id='replacement',
                    stage='/var/lib/ntp-acquire-replacement', source_stage=old['stage'],
                    source_sha256=c.sha(files['monitor.tar']), prepared_epoch=1, expires_epoch=86401)
                if case == 'old_path': spec['stage'] = '/var/lib/ntp-revalidate-replacement'
                spec['members'] = {n: c.sha(v) for n, v in files.items()}
                files.update({'spec.json': c.encoded(spec), 'manifest.json': b'', 'review.md': b''})
                create(Path(spec['stage'])/'spec.json', files['spec.json'])
                mapped(spec['stage']).chmod(0o700)
                def bootstrap(alias, raw):
                    acquisition.validate(alias, raw)
                    return h
                def source_guard(*args):
                    return os.open(sandbox/'lock', os.O_CREAT | os.O_RDWR, 0o600), {'state.json': runtime_state}
                def run(tx, argv, **kwargs):
                    if argv[:2] == ['/usr/bin/systemctl', 'show']:
                        if '--property=DropInPaths' in argv: return ''
                        if argv[-1] == '--value': return 'loaded' if case == 'worker_active' else 'not-found'
                        return ('Id='+argv[2]+'\nLoadState=not-found\nActiveState=inactive\nSubState=dead\nFragmentPath=\nDropInPaths=\n')
                    if argv == ['/usr/bin/stty', '-F', '/dev/serial0', '-g']: return 'saved'
                    raise AssertionError('unexpected command: '+repr(argv))
                def probe():
                    if case == 'runtime_drift': raise ValueError('fixture native drift')
                    if case == 'source_changed': mapped('/var/lib/held/state.json').write_bytes(b'changed')
                    return {'phase': 'ready', 'boot_id': 'boot', 'hardware': {'uart': 'verified'}}
                check = types.SimpleNamespace(probe=Mock(side_effect=probe), core=types.SimpleNamespace(i=types.SimpleNamespace(
                    observation=lambda: {'boot_id': 'changed'} if case == 'continuity_drift' else observed)))
                original_frozen = c.frozen
                def frozen(raw):
                    if raw == files['base.py']: return base
                    if raw == files['continuity.py']: return continuity
                    if raw == b'restoration': return restoration
                    return original_frozen(raw)
                for module, name, value in (
                    (c, 'inputs', lambda _: (old, monitor_files, rspec, {'stage.py': b'restoration'}, report, source)),
                    (c, 'Path', mapped), (base, 'Path', mapped), (continuity, 'Path', mapped),
                    (c, 'frozen', frozen), (base, 'load', lambda _: acquisition),
                    (acquisition, 'bootstrap', bootstrap), (acquisition, 'source_guard', source_guard),
                    (acquisition, 'idle', Mock()), (acquisition, 'prior_guard', Mock()),
                    (acquisition, 'serial_identity', lambda: {'target': '/dev/ttyAMA0'}),
                    (acquisition, 'load', Mock()), (restoration, 'source_lock', lambda *a: os.open(sandbox/'source-lock', os.O_CREAT | os.O_RDWR, 0o600)),
                    (continuity, 'transaction', lambda *a: check), (base.Transaction, 'run', run),
                    (base.Transaction, 'snapshot', lambda *a: None), (c.time, 'time', lambda: 1000)):
                    stack.enter_context(patch.object(module, name, value))
                if case not in ('valid', 'recovered'):
                    with self.assertRaisesRegex(ValueError, {'old_path': 'identity/window/member', 'runtime_drift': 'native drift',
                            'continuity_drift': 'continuity drift', 'worker_active': 'worker/unit', 'source_changed': 'held source changed',
                            'recovered_state': 'recovered source state drift'}[case]):
                        c.capture(h, spec, files)
                    continue
                result = c.capture(h, spec, files)
                self.assertEqual(result['phase'], 'runtime_validated')
                self.assertEqual(check.probe.call_count, 2)
                self.assertTrue(mapped(Path(spec['stage'])/'before.json').is_file())
                self.assertEqual(read('/var/lib/held/state.json'), b'{}')
                self.assertEqual(read(Path(refspec['source_stage'])/'state.json'), runtime_state)
                self.assertEqual(read(Path(old['stage'])/'spec.json'), monitor_files['spec.json'])
                if case == 'recovered': self.assertEqual(json.loads(read(Path(old['stage'])/'state.json')), proof['cleanup']['result'])
                else: self.assertFalse(mapped(Path(old['stage'])/'state.json').exists())


class ControllerTests(unittest.TestCase):
    def test_prepare_rejects_local_review_or_spec_drift_before_start(self):
        info = importlib.util.spec_from_file_location('acquisition_fixture', ROOT/'tests/test_gpsd_acquisition.py')
        fixture = importlib.util.module_from_spec(info); info.loader.exec_module(fixture)
        files = {n: (ROOT/path).read_bytes() for n, path in c.PATHS.items()}
        files.update({'spec.json': b'{}', 'review.md': b'review', 'known_hosts': b'pinned'})
        raw = fixture.archive(files)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); bundle = root/'bundle.tar'
            bundle.write_bytes(raw); bundle.chmod(0o600)
            for name in ('review.md', 'spec.json', 'known_hosts'):
                (root/name).write_bytes(files[name]); (root/name).chmod(0o600)
            with patch.object(c, 'frozen', return_value=types.SimpleNamespace(validate=Mock())):
                c.prepare(bundle, c.sha(raw), current=True)
                for name in ('review.md', 'spec.json'):
                    (root/name).write_bytes(files[name]+b'\n')
                    with self.assertRaisesRegex(ValueError, 'local revalidation review/spec drift'):
                        c.prepare(bundle, c.sha(raw), current=True)
                    c.prepare(bundle, c.sha(raw), current=False)
                    (root/name).write_bytes(files[name])

    def test_one_shot_transport_loss_then_expired_dual_readback_and_closure(self):
        spec, report = ReceiptTests().fixture()
        spec.update(old_ipv4=spec['endpoints'][0], members={}, stage='/var/lib/ntp-acquire-fixture')
        files = {n: (ROOT/path).read_bytes() for n, path in c.PATHS.items()}
        files['spec.json'] = c.encoded(spec)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); args = types.SimpleNamespace(bundle=root/'bundle.tar', sha256='digest', mode='start', attempt=1)
            calls = []
            def transport(argv, **kwargs):
                calls.append(argv)
                compile(kwargs['input'], 'sealed-payload', 'exec')
                self.assertIn('StrictHostKeyChecking=yes', argv)
                self.assertIn('HostKeyAlias='+spec['old_ipv4'], argv)
                if args.mode == 'start': return types.SimpleNamespace(returncode=255)
                value = report if args.mode == 'readback' else {'phase': 'cleaned', 'evidence_preserved': True,
                                                              'report_sha256': c.sha(c.encoded(report))}
                kwargs['stdout'].write(c.encoded({'spec_sha256': c.sha(files['spec.json']), 'result': value})+b'CUTOVER_EXIT_STATUS=0\n')
                return types.SimpleNamespace(returncode=0)
            with patch.object(c, 'prepare', return_value=(spec, files)), patch.dict(os.environ, {'SSH_AUTH_SOCK': ''}), \
                    patch('subprocess.run', side_effect=transport), patch.object(c.time, 'time', return_value=1100):
                with self.assertRaisesRegex(ValueError, 'SSH agent'): c.execute(args)
                self.assertFalse((root/'start-execution.json').exists()); self.assertEqual(calls, [])
                with patch.dict(os.environ, {'SSH_AUTH_SOCK': '/fixture-agent'}):
                    with self.assertRaisesRegex(ValueError, 'terminal lost'): c.execute(args)
                    with self.assertRaises(FileExistsError): c.execute(args)
                    self.assertEqual(len(calls), 1)
                    args.mode = 'readback'
                    with patch.object(c.time, 'time', return_value=spec['expires_epoch']+86400):
                        self.assertEqual(set(c.execute(args)['phases'].values()), {'runtime_validated'})
                        args.mode = 'cleanup'
                        self.assertEqual(set(c.execute(args)['phases'].values()), {'cleaned'})
            self.assertEqual(len(calls), 4)
            self.assertTrue((root/'start-0-transport.json').is_file())
            self.assertEqual(json.loads((root/'acceptance.json').read_bytes())['state'], 'runtime_validated')

    def test_sealer_validates_alias_with_frozen_acquisition_validator(self):
        info = importlib.util.spec_from_file_location('acquisition_fixture', ROOT/'tests/test_gpsd_acquisition.py')
        fixture = importlib.util.module_from_spec(info); info.loader.exec_module(fixture)
        reference, inputs = fixture.fixture(); inputs['spec.json'] = c.encoded(reference)
        raw = fixture.archive(inputs)
        files = {n: b'fixture' for n in set(c.PATHS)|c.EXTRA}
        files['monitor-proof.json'] = b'{}'
        files['reference.py'] = (ROOT/'scripts/run-gpsd-acquisition.py').read_bytes()
        spec = {k: reference[k] for k in ('hostname', 'boot_id', 'kernel', 'endpoints', 'old_ipv4')}
        old = dict(spec, stage='/var/lib/ntp-acquire-failed')
        spec.update(schema=1, purpose='runtime-revalidation', operation_id='fresh', stage='/var/lib/ntp-acquire-fresh',
                    source_stage=old['stage'], source_sha256=c.sha(files['monitor.tar']), prepared_epoch=1000, expires_epoch=87400,
                    members={n: c.sha(v) for n, v in files.items()})
        files.update({'spec.json': c.encoded(spec), 'manifest.json': b'', 'review.md': b''})
        monitor_files = {'reference.tar': raw}
        with patch.object(c, 'inputs', return_value=(old, monitor_files, {}, {}, {}, {})):
            c.validate(spec, files)
            bad = dict(spec, stage='/var/lib/ntp-revalidate-fresh')
            with self.assertRaisesRegex(ValueError, 'identity/window/member'): c.validate(bad, files)
            receipt = json.loads(inputs['runtime-acceptance.json']); receipt['boot_id'] = 'different'
            inputs['runtime-acceptance.json'] = c.encoded(receipt)
            monitor_files['reference.tar'] = fixture.archive(inputs)
            with self.assertRaisesRegex(ValueError, 'runtime/identity/boot/input'): c.validate(spec, files)


class EntryTests(unittest.TestCase):
    def test_protected_revalidation_binds_identity_modes_and_large_archive_limit(self):
        import socket
        for case in ('valid', 'mode', 'boot', 'spec', 'member'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary); root.chmod(0o755 if case == 'mode' else 0o700)
                spec = {'stage': str(root), 'hostname': socket.gethostname(), 'kernel': os.uname().release,
                    'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                    'members': {'monitor.tar': c.sha(b'archive'), 'stage.py': c.sha(b'stage')}}
                if case == 'boot': spec['boot_id'] = 'wrong'
                limits = {}
                def read(path, limit=0):
                    limits[path.name] = limit
                    if path.name == 'spec.json': return b'wrong' if case == 'spec' else c.encoded(spec)
                    if path.name == 'monitor.tar': return b'wrong' if case == 'member' else b'archive'
                    return b'stage'
                h = types.SimpleNamespace(ancestors=Mock(), read=read)
                with patch.object(c.os, 'geteuid', return_value=0), patch.object(c, 'frozen', return_value=h):
                    if case == 'valid':
                        self.assertIs(c.protected(spec, {'helper.py': b'helper'}), h)
                        self.assertEqual(limits['monitor.tar'], 64*1024**2)
                        self.assertEqual(limits['stage.py'], 32*1024**2)
                        h.ancestors.assert_called_once_with(root)
                    else:
                        with self.assertRaises(ValueError): c.protected(spec, {'helper.py': b'helper'})

    def test_timeout_and_missing_report_keep_partial_evidence_for_readback(self):
        import socket
        import subprocess
        for timed_out in (False, True):
            with self.subTest(timed_out=timed_out), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)/'stage'
                spec = {'stage': str(root), 'hostname': socket.gethostname(), 'kernel': os.uname().release,
                        'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                        'prepared_epoch': 1000, 'expires_epoch': 87400}
                def create(path, raw):
                    with path.open('xb') as stream: stream.write(raw)
                h = types.SimpleNamespace(ancestors=Mock(), create=create, read=lambda p, **kw: p.read_bytes(), sync=Mock())
                files = {'helper.py': b'helper', 'inspector.py': b'inspector', 'base.py': b'base'}
                modules = {b'helper': h, b'inspector': types.SimpleNamespace(protected=lambda *a: h), b'base': base}
                process = Mock(pid=98765)
                count = 0
                def wait(**kwargs):
                    nonlocal count
                    count += 1
                    if count == 1:
                        (root/'commands.jsonl').write_bytes(b'{"partial":true}\n')
                        if timed_out: raise subprocess.TimeoutExpired('fixture', 190)
                    return 0
                process.wait.side_effect = wait
                with patch.object(c, 'validate'), patch.object(c, 'protected', return_value=h), patch.object(c, 'frozen', side_effect=lambda raw: modules[raw]), \
                        patch.object(c.os, 'geteuid', return_value=0), patch.dict(os.environ, {'SUDO_USER': 'ama'}), \
                        patch.object(c.time, 'time', return_value=1100), patch.object(c.subprocess, 'Popen', return_value=process), \
                        patch.object(c.os, 'killpg') as kill:
                    result = c.entry(spec, files, 'start')
                    self.assertEqual(result['phase'], 'validation_held')
                    self.assertIn('commands.jsonl', result['evidence'])
                    self.assertEqual(c.entry(spec, files, 'readback'), result)
                    closure = c.entry(spec, files, 'cleanup', {'report_sha256': c.sha(c.encoded(result))})
                    self.assertTrue(closure['evidence_preserved'])
                    self.assertEqual(kill.call_count, int(timed_out))
                    self.assertEqual(process.wait.call_count, 2 if timed_out else 1)

    def test_unreadable_evidence_does_not_leave_running_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); (root/'before.json').symlink_to(root/'missing')
            (root/'commands.jsonl').write_bytes(b'partial')
            h = types.SimpleNamespace(read=lambda p, **kw: p.read_bytes(), create=lambda p, raw: p.write_bytes(raw), sync=Mock())
            with patch.object(c, 'frozen', return_value=base):
                c.write_report(h, root, {'base.py': b''}, {'phase': 'runtime_validated'})
            report = json.loads((root/'report.json').read_bytes())
            self.assertEqual(report['phase'], 'validation_held'); self.assertFalse(report['time_service_accepted'])
            self.assertIn('commands.jsonl', report['evidence']); self.assertIn('before.json', report['error'])


class ReceiptTests(unittest.TestCase):
    def test_recovered_source_requires_matching_readbacks_receipt_and_cleanup(self):
        old = {'stage': '/var/lib/ntp-acquire-prior'}; files = {'spec.json': c.encoded(old)}
        state = {'phase': 'recovered', 'supervisor_pid': 42}
        first = {'spec_sha256': c.sha(files['spec.json']), 'result': state}
        proof = {'recovered': {'state': 'recovered', 'bundle_sha256': 'archive',
            'spec_sha256': first['spec_sha256'], 'state_sha256': c.sha(c.encoded(state)), 'time_service_accepted': False},
            'readbacks': [first, copy.deepcopy(first)],
            'cleanup': {'spec_sha256': first['spec_sha256'], 'result': dict(state, transient_cleanup=True)}}
        for case in ('valid', 'readback', 'receipt', 'cleanup', 'phase', 'extra'):
            value = copy.deepcopy(proof)
            if case == 'readback': value['readbacks'][1]['result']['supervisor_pid'] = 43
            if case == 'receipt': value['recovered']['state_sha256'] = 'wrong'
            if case == 'cleanup': value['cleanup']['result']['transient_cleanup'] = False
            if case == 'phase':
                for row in value['readbacks']: row['result']['phase'] = 'recovery_held'
            if case == 'extra': value['start'] = {}
            with self.subTest(case=case):
                if case == 'valid': self.assertEqual(c.recovered_source(old, files, value), proof['cleanup']['result'])
                else:
                    with self.assertRaises(ValueError): c.recovered_source(old, files, value)

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
        for case in ('missing_check', 'evidence', 'epoch', 'boot', 'timing', 'endpoint', 'observation', 'hardware', 'integer_check', 'float_epoch', 'current_epoch'):
            other = copy.deepcopy(report)
            if case == 'missing_check': other['checks'].pop('hardware')
            if case == 'evidence': other['evidence']['commands.jsonl']['sha256'] = 'changed'
            if case == 'epoch': other['epoch'] = 999999
            if case == 'boot': other['boot_id'] = 'other'
            if case == 'timing': other['time_service_accepted'] = True
            if case == 'observation': other['observation_sha256'] = 'changed'
            if case == 'hardware': other['hardware'] = {'wrong': True}
            if case == 'integer_check': other['checks']['runtime'] = 1
            if case == 'float_epoch': other['epoch'] = 1100.0
            if case == 'current_epoch':
                current = json.loads(base64.b64decode(other['evidence']['current-runtime.json']['base64']))
                current['epoch'] = 1100.0; raw = c.encoded(current)
                other['evidence']['current-runtime.json'] = {'sha256': c.sha(raw), 'base64': base64.b64encode(raw).decode()}
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
            with patch.object(c, 'validate'), patch.object(c, 'protected', return_value=h):
                with self.assertRaises(ValueError): c.entry(spec, {'inspector.py': b''}, 'cleanup', {'report_sha256': 'wrong'})
                result = c.entry(spec, {'inspector.py': b''}, 'cleanup', {'report_sha256': c.sha(report)})
            self.assertTrue(result['evidence_preserved']); self.assertEqual(sorted(p.name for p in root.iterdir()), ['cleanup.json'])


if __name__ == '__main__': unittest.main()
