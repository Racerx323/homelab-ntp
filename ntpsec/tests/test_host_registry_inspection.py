#!/usr/bin/python3
"""Offline boundaries for registry inspection; never contact a target."""
import argparse
import base64
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1]/'scripts/run-host-registry-inspection.py'
spec = importlib.util.spec_from_file_location('registry_inspection', SCRIPT)
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
UUID = '12345678-1234-1234-1234-123456789abc'
OTHER = '22345678-1234-1234-1234-123456789abc'


class Registry(unittest.TestCase):
    def test_exact_identity_and_type(self):
        self.assertEqual(m.registry(UUID+':802-3-ethernet\n'), {UUID: '802-3-ethernet'})
        self.assertNotEqual(m.registry(UUID+':loopback\n'), m.registry(OTHER+':loopback\n'))

    def test_reject_ambiguous_unbounded_registry(self):
        for text in ('', 'bad:loopback', UUID+':loopback\n'+UUID+':loopback', UUID+':bad:type',
                     '\n'.join(f'{i:08x}-1234-1234-1234-123456789abc:loopback' for i in range(65))):
            with self.subTest(text=text[:50]), self.assertRaises(ValueError):
                m.registry(text)


class Bindings(unittest.TestCase):
    def setUp(self):
        old = {'stage': '/var/lib/ntp-host-fixture', 'operation': 'hardware', 'hostname': 'fixture',
               'kernel': 'fixture-kernel', 'ssh': {'fingerprint': 'fixture'}, 'old_ipv4': '192.0.2.2',
               'recipe': {'ipv4_address': '192.0.2.1/24', 'ipv6_address': '2001:db8::1/64'}}
        self.files = dict.fromkeys(m.INPUTS, b'fixture')
        self.files['hardware-spec.json'] = m.encoded(old)
        self.files['hardware-recovery.json'] = m.encoded({'bundle_sha256': 'a'*64,
                                                        'result': {'phase': 'recovery_files_restored'}})
        self.spec = {k: old[k] for k in ('hostname', 'kernel', 'ssh', 'old_ipv4')}
        self.spec.update(schema=1, operation='host-registry-inspection', operation_id='fixture',
                         stage='/var/lib/ntp-inspect-fixture', prepared_epoch=0, expires_epoch=86400,
                         hardware_bundle_sha256='a'*64, endpoints=['192.0.2.1', '2001:db8::1'],
                         members={n: m.sha(v) for n, v in self.files.items()})

    def test_exact_binding(self):
        self.assertEqual(m.validate(self.spec, self.files)['hostname'], 'fixture')

    def test_reference_or_receipt_substitution_rejected(self):
        for name in ('history.md', 'hardware-recovery.json'):
            changed = dict(self.files, **{name: b'{}'})
            with self.subTest(name=name), self.assertRaises((KeyError, ValueError)):
                m.validate(self.spec, changed)

    def test_stage_and_endpoint_substitution_rejected(self):
        for name, value in (('stage', '/tmp/unprotected'), ('endpoints', ['192.0.2.3'])):
            changed = dict(self.spec, **{name: value})
            with self.subTest(name=name), self.assertRaises(ValueError):
                m.validate(changed, self.files)

    def test_overlong_validity_rejected(self):
        self.spec['expires_epoch'] = 86401
        with self.assertRaises(ValueError):
            m.validate(self.spec, self.files)


class Capture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.root.chmod(0o700)
        self.old = {'stage': str(self.root), 'members': {}, 'network_candidate_uuid': UUID}
        self.state = {'phase': 'recovery_files_restored'}
        self.files = {'hardware-spec.json': m.encoded(self.old),
                      'hardware-recovery.json': m.encoded({'result': self.state})}
        for name, data in {'.lock': b'', 'spec.json': self.files['hardware-spec.json'],
                           'state.json': m.encoded(self.state), 'before.json': m.encoded({'registry': {OTHER: 'loopback'}}),
                           'commands.jsonl': b'{"argv":["nmcli"],"stdout":"retained"}\n'}.items():
            (self.root/name).write_bytes(data); (self.root/name).chmod(0o600)
        self.boot = []
        for name in ('config.txt', 'cmdline.txt'):
            path = self.root/name; path.write_text('original\n'); self.boot.append(str(path))
        self.h = m.module('foundation-install.py')
        self.h.OWNER = os.getuid()
        self.addCleanup(patch.stopall)
        patch.object(self.h, 'ancestors', lambda path: None).start()
        patch.object(m, 'validate', return_value=self.old).start()
        patch.object(m, 'BOOT', tuple(self.boot)).start()
        self.calls = []

    def command(self, argv, **kwargs):
        self.calls.append(argv)
        if argv[1:4] == ['-t', '-f', 'UUID,TYPE']:
            out = UUID+':802-3-ethernet\n'+OTHER+':loopback\n'
        else:
            out = '{}\n'
        return subprocess.CompletedProcess(argv, 0, out.encode(), b'')

    def test_complete_capture_preserves_source_and_exposes_difference(self):
        before = {p.name: p.read_bytes() for p in self.root.iterdir()}
        with patch.object(m.subprocess, 'run', side_effect=self.command):
            report = m.collect(self.h, {}, self.files)
        self.assertEqual(report['current_registry'][OTHER], 'loopback')
        self.assertEqual(base64.b64decode(report['retained']['commands.jsonl']), before['commands.jsonl'])
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir()})
        self.assertTrue(all(q['status'] == 0 for q in report['queries'].values()))
        self.assertFalse(any(set(a) & {'modify', 'up', 'down', 'delete', '--show-secrets', 'reboot'} for a in self.calls))
        result = {'phase': 'captured', 'report': report, 'terminal_sha256': m.sha(m.encoded(report))}
        binding = {'hostname': report['hostname'], 'kernel': report['kernel']}
        self.assertEqual(m.accept(binding, result)['state'], 'diagnostic_accepted')
        del report['queries']['cmdline']
        result['terminal_sha256'] = m.sha(m.encoded(report))
        with self.assertRaisesRegex(ValueError, 'complete bound'):
            m.accept(binding, result)

    def test_registry_drift_during_capture_holds(self):
        count = 0
        def changing(argv, **kwargs):
            nonlocal count
            result = self.command(argv, **kwargs)
            if argv[1:4] == ['-t', '-f', 'UUID,TYPE']:
                count += 1
                if count == 2:
                    result.stdout = (UUID+':802-3-ethernet\n').encode()
            return result
        with patch.object(m.subprocess, 'run', side_effect=changing), self.assertRaisesRegex(ValueError, 'registry changed'):
            m.collect(self.h, {}, self.files)

    def test_held_state_drift_prevents_queries(self):
        (self.root/'state.json').write_bytes(m.encoded({'phase': 'accepted'}))
        with patch.object(m.subprocess, 'run') as run, self.assertRaisesRegex(ValueError, 'state drift'):
            m.collect(self.h, {}, self.files)
        run.assert_not_called()

    def test_unknown_member_hash_prevents_queries(self):
        self.old['members'] = {'state.json': '0'*64}
        self.files['hardware-spec.json'] = m.encoded(self.old)
        (self.root/'spec.json').write_bytes(self.files['hardware-spec.json'])
        with patch.object(m.subprocess, 'run') as run, self.assertRaisesRegex(ValueError, 'member drift'):
            m.collect(self.h, {}, self.files)
        run.assert_not_called()

    def test_retained_symlink_rejected(self):
        (self.root/'commands.jsonl').unlink()
        (self.root/'commands.jsonl').symlink_to(self.root/'state.json')
        with self.assertRaises((OSError, ValueError)):
            m.collect(self.h, {}, self.files)

    def test_nonprivate_retained_state_rejected(self):
        (self.root/'state.json').chmod(0o644)
        with self.assertRaisesRegex(ValueError, 'private root'):
            m.collect(self.h, {}, self.files)

    def test_command_failure_does_not_accept(self):
        with patch.object(m.subprocess, 'run', return_value=subprocess.CompletedProcess([], 2, b'', b'error')):
            with self.assertRaisesRegex(ValueError, 'query failed'):
                m.collect(self.h, {}, self.files)

    def test_concurrent_operation_lock_holds(self):
        import fcntl
        with (self.root/'.lock').open('rb') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError):
                m.collect(self.h, {}, self.files)


class UartBindings(Bindings):
    def setUp(self):
        super().setUp()
        self.spec.update(operation='host-uart-inspection', recovered_boot_id=UUID)
        self.state = {'phase': 'recovered', 'transient_units_cleaned': True, 'recovered_boot_id': UUID}
        self.bind()

    def bind(self):
        self.files['hardware-recovery.json'] = m.encoded({'bundle_sha256': 'a'*64, 'result': self.state})
        self.spec['members'] = {n: m.sha(v) for n, v in self.files.items()}

    def test_incomplete_recovery_rejected(self):
        for field, value in [('phase', 'recovery_files_restored'), ('transient_units_cleaned', False),
                             ('recovered_boot_id', OTHER)]:
            with self.subTest(field=field):
                old = self.state[field]; self.state[field] = value; self.bind()
                with self.assertRaises(ValueError):
                    m.validate(self.spec, self.files)
                self.state[field] = old; self.bind()


class UartMetadata(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.sys = self.root/'sys'; self.dev = self.root/'dev'
        self.dev.mkdir()
        for name in ('devices', 'class/tty', 'bus/amba/drivers', 'bus/amba/devices', 'firmware/devicetree/base'):
            (self.sys/name).mkdir(parents=True, exist_ok=True)

    def fixture(self):
        driver = self.sys/'bus/amba/drivers/uart-pl011'; driver.mkdir()
        node = self.sys/'devices/platform/uart'; node.mkdir(parents=True)
        (node/'driver').symlink_to(driver)
        dt = self.sys/'firmware/devicetree/base/uart'; dt.mkdir()
        (dt/'compatible').write_bytes(b'arm,pl011\0arm,primecell\0')
        (node/'of_node').symlink_to(dt)
        tty = node/'serial/tty/ttyAMA0'; tty.mkdir(parents=True)
        serial_driver = self.sys/'bus/serial-base/drivers/port'; serial_driver.mkdir(parents=True)
        (tty.parent.parent/'driver').symlink_to(serial_driver)
        (self.sys/'class/tty/ttyAMA0').symlink_to(tty)
        (self.sys/'bus/amba/devices/uart').symlink_to(node)
        return node, dt

    def test_parent_driver_chain_without_device_io(self):
        self.fixture()
        original = Path.open
        def guarded(path, *args, **kwargs):
            if path.is_relative_to(self.dev):
                raise AssertionError('device opened')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'open', guarded):
            result = m.uart_metadata(self.sys, self.dev)
        drivers = [p['driver'] for p in result['ttys']['ttyAMA0'] if p['driver']]
        self.assertEqual([Path(d).name for d in drivers], ['port', 'uart-pl011'])
        self.assertEqual(result['amba_drivers'], ['uart-pl011'])
        self.assertIsNone(result['serial0'])
        self.assertIn('compatible', result['amba_devices']['uart']['properties'])

    def test_absent_devices_are_observations(self):
        self.assertEqual(m.uart_metadata(self.sys, self.dev),
                         {'serial0': None, 'ttys': {}, 'amba_drivers': [], 'amba_devices': {}})

    def test_escaped_link_rejected(self):
        (self.sys/'class/tty/ttyAMA0').symlink_to(self.dev)
        with self.assertRaisesRegex(ValueError, 'escaped'):
            m.uart_metadata(self.sys, self.dev)

    def test_property_size_bound(self):
        node, dt = self.fixture()
        (dt/'compatible').write_bytes(b'x'*4097)
        with self.assertRaisesRegex(ValueError, 'property bound'):
            m.uart_metadata(self.sys, self.dev)

    def test_property_symlink_rejected(self):
        node, dt = self.fixture()
        (dt/'compatible').unlink(); (dt/'compatible').symlink_to('/dev/zero')
        with self.assertRaisesRegex(ValueError, 'regular device-tree'):
            m.uart_metadata(self.sys, self.dev)

    def test_entry_bound(self):
        for i in range(33):
            (self.sys/f'bus/amba/drivers/driver{i}').mkdir()
        with self.assertRaisesRegex(ValueError, 'entry bound'):
            m.uart_metadata(self.sys, self.dev)


class UartCapture(Capture):
    def uart_spec(self):
        boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        self.state.update(phase='recovered', transient_units_cleaned=True, recovered_boot_id=boot)
        (self.root/'state.json').write_bytes(m.encoded(self.state))
        self.files['hardware-recovery.json'] = m.encoded({'result': self.state})
        before = json.loads((self.root/'before.json').read_bytes())
        before['boot_files'] = {}
        for name in self.boot:
            path = Path(name); info = path.stat(); raw = path.read_bytes()
            before['boot_files'][name] = {'sha256': m.sha(raw), 'base64': base64.b64encode(raw).decode(),
                                         'uid': info.st_uid, 'gid': info.st_gid, 'mode': info.st_mode & 0o777}
        (self.root/'before.json').write_bytes(m.encoded(before))
        return {'operation': 'host-uart-inspection', 'recovered_boot_id': boot}

    def test_stable_uart_capture_and_acceptance(self):
        binding = self.uart_spec()
        uart = {'serial0': None, 'ttys': {}, 'amba_drivers': [], 'amba_devices': {}}
        with patch.object(m, 'uart_metadata', return_value=uart) as capture, patch.object(m.subprocess, 'run', side_effect=self.command):
            report = m.collect(self.h, binding, self.files)
        self.assertEqual(capture.call_count, 2)
        binding.update(hostname=report['hostname'], kernel=report['kernel'])
        result = {'phase': 'captured', 'report': report, 'terminal_sha256': m.sha(m.encoded(report))}
        self.assertEqual(m.accept(binding, result)['state'], 'diagnostic_accepted')
        binding['recovered_boot_id'] = OTHER
        with self.assertRaisesRegex(ValueError, 'recovered UART'):
            m.accept(binding, result)

    def test_uart_drift_holds(self):
        binding = self.uart_spec()
        with patch.object(m, 'uart_metadata', side_effect=[{'a': 1}, {'a': 2}]), patch.object(m.subprocess, 'run', side_effect=self.command):
            with self.assertRaisesRegex(ValueError, 'UART metadata changed'):
                m.collect(self.h, binding, self.files)

    def test_restored_boot_drift_holds(self):
        binding = self.uart_spec(); Path(self.boot[0]).write_text('drift')
        with patch.object(m, 'uart_metadata', return_value={}), patch.object(m.subprocess, 'run', side_effect=self.command):
            with self.assertRaisesRegex(ValueError, 'restored boot files drift'):
                m.collect(self.h, binding, self.files)

    def test_changed_recovered_boot_holds_before_queries(self):
        binding = self.uart_spec(); binding['recovered_boot_id'] = OTHER
        with patch.object(m.subprocess, 'run') as query, self.assertRaisesRegex(ValueError, 'boot changed'):
            m.collect(self.h, binding, self.files)
        query.assert_not_called()


class Lifecycle(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)/'inspection'
        self.spec = {'stage': str(self.root), 'hostname': m.socket.gethostname(),
                     'kernel': os.uname().release, 'prepared_epoch': 0, 'expires_epoch': 9999999999}
        helper = (SCRIPT.parent/'foundation-install.py').read_bytes()
        # Preserve real file checks; test ancestry is owned by the fixture user.
        helper += b'\nOWNER=os.getuid()\nancestors=lambda path: None\n'
        self.files = dict.fromkeys(m.INPUTS, b'fixture')
        self.files['helper.py'] = helper
        self.addCleanup(patch.stopall)
        patch.object(m, 'validate', return_value={}).start()
        patch.object(m.os, 'geteuid', return_value=0).start()
        patch.dict(os.environ, {'SUDO_USER': 'ama', 'SUDO_UID': '1000', 'SUDO_GID': '1000'}).start()
        self.collect = patch.object(m, 'collect', return_value={'evidence': 'complete'}).start()
        self.mask = os.umask(0o077); self.addCleanup(os.umask, self.mask)

    def test_capture_readback_and_closed_cleanup(self):
        result = m.worker(self.spec, self.files, 'capture')
        self.assertEqual(m.worker(self.spec, self.files, 'readback'), result)
        self.assertEqual(self.collect.call_count, 1)
        self.assertEqual(m.worker(self.spec, self.files, 'cleanup', result['terminal_sha256'])['phase'], 'cleaned')
        self.assertFalse(self.root.exists())

    def test_capture_cannot_be_replayed(self):
        m.worker(self.spec, self.files, 'capture')
        with self.assertRaises(FileExistsError):
            m.worker(self.spec, self.files, 'capture')
        self.assertEqual(self.collect.call_count, 1)

    def test_cleanup_unknown_entry_preserves_everything(self):
        result = m.worker(self.spec, self.files, 'capture')
        (self.root/'unexpected').write_bytes(b'preserve')
        original = set(self.root.iterdir())
        with self.assertRaisesRegex(ValueError, 'unknown inspection'):
            m.worker(self.spec, self.files, 'cleanup', result['terminal_sha256'])
        self.assertEqual(set(self.root.iterdir()), original)

    def test_cleanup_wrong_receipt_preserves_terminal(self):
        m.worker(self.spec, self.files, 'capture')
        with self.assertRaisesRegex(ValueError, 'accepted terminal hash'):
            m.worker(self.spec, self.files, 'cleanup', '0'*64)
        self.assertTrue((self.root/'terminal.json').exists())

    def test_failed_capture_is_preserved_not_retried(self):
        self.collect.side_effect = ValueError('failure')
        with self.assertRaisesRegex(ValueError, 'failure'):
            m.worker(self.spec, self.files, 'capture')
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            m.worker(self.spec, self.files, 'readback')
        with self.assertRaises(FileExistsError):
            m.worker(self.spec, self.files, 'capture')
        self.assertEqual(self.collect.call_count, 1)

    def test_terminal_symlink_rejected(self):
        m.worker(self.spec, self.files, 'capture')
        (self.root/'terminal.json').unlink()
        (self.root/'terminal.json').symlink_to(self.root/'started.json')
        with self.assertRaises(OSError):
            m.worker(self.spec, self.files, 'readback')


class Controller(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.root.chmod(0o700)
        self.args = argparse.Namespace(bundle=self.root/'registry-inspection.tar', sha256='a'*64, mode='capture')
        self.spec = {'prepared_epoch': 0, 'expires_epoch': 9999999999, 'endpoints': ['192.0.2.1', '2001:db8::1'],
                     'old_ipv4': '192.0.2.2', 'hostname': 'test'}
        self.files = {'spec.json': m.encoded(self.spec)}
        self.addCleanup(patch.stopall)
        patch.object(m, 'prepare', return_value=(self.spec, self.files)).start()
        patch.object(m, 'payload', return_value=b'sealed test payload').start()
        patch.dict(os.environ, {'SSH_AUTH_SOCK': '/test-agent'}).start()
        self.mask = os.umask(0o077); self.addCleanup(os.umask, self.mask)

    def test_lost_capture_is_not_replayed(self):
        with patch.object(m.subprocess, 'run', return_value=subprocess.CompletedProcess([], 255)) as run:
            with self.assertRaisesRegex(ValueError, 'terminal unavailable'):
                m.execute(self.args)
            with self.assertRaises(FileExistsError):
                m.execute(self.args)
        self.assertEqual(run.call_count, 1)
        self.assertTrue((self.root/'capture-execution.json').exists())

    def test_readback_only_can_try_second_endpoint(self):
        c = m.module('run-foundation-preflight.py')
        c.write_new(self.root/'capture-execution.json', {'bundle_sha256': self.args.sha256})
        self.args.mode = 'readback'
        with patch.object(m.subprocess, 'run', return_value=subprocess.CompletedProcess([], 255)) as run:
            with self.assertRaisesRegex(ValueError, 'terminal unavailable'):
                m.execute(self.args)
        self.assertEqual(run.call_count, 2)

    def test_cleanup_requires_bound_acceptance(self):
        c = m.module('run-foundation-preflight.py')
        c.write_new(self.root/'capture-execution.json', {'bundle_sha256': self.args.sha256})
        self.args.mode = 'cleanup'
        with patch.object(m.subprocess, 'run') as run, self.assertRaises(FileNotFoundError):
            m.execute(self.args)
        run.assert_not_called()

    def test_expired_capture_never_registers_or_contacts(self):
        self.spec['expires_epoch'] = 1
        with patch.object(m.subprocess, 'run') as run, self.assertRaisesRegex(ValueError, 'expired'):
            m.execute(self.args)
        run.assert_not_called()
        self.assertFalse((self.root/'capture-execution.json').exists())


class FreshBaseline(unittest.TestCase):
    def setUp(self):
        import types
        self.boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        self.spec = {'stage': '/fixture/new', 'recovered_boot_id': self.boot, 'recovery_bundle_sha256': 'a'*64}
        self.observed = {'boot_id': self.boot, 'active_daemons': [], 'inventory': {'fixture': ['1','installed']},
                         'python': {}, 'services': ''}
        previous = dict(self.observed, boot_id='old')
        self.baseline = {'observation': previous, 'installed_state': {'files': {}}, 'parents': {},
                         'protected_files': {'boot': None}, 'hostname': 'fixture'}
        release = {'files': {n: {'type': 'file'} for n in ('usr/local/sbin/gpsd', 'usr/local/sbin/ntpd')}}
        self.raw = {'baseline.json': m.encoded(self.baseline), 'release.json': m.encoded(release)}
        self.helper = types.SimpleNamespace(read=lambda path, **kw: self.raw[path.name])
        self.source = types.SimpleNamespace(observation=unittest.mock.Mock(return_value=self.observed))
        self.inspector = types.SimpleNamespace(recipe=unittest.mock.Mock(),
            installed_state=unittest.mock.Mock(return_value=({'files': {}}, {})),
            verify_parents=unittest.mock.Mock(), protected_files=unittest.mock.Mock(return_value={'boot':None}),
            devices=unittest.mock.Mock(return_value={'nodes': {}, 'sysfs': {}}),
            QUERIES={'profile_registry':['registry']},
            query=unittest.mock.Mock(return_value={'exit_status':0,'stdout':UUID+':802-3-ethernet\n'}),
            ethernet_profiles=unittest.mock.Mock(return_value={UUID:{}}),
            python_environment=unittest.mock.Mock(return_value={'context':'isolated_root'}))
        self.stage = m.module('host-configuration-stage.py')
        self.addCleanup(patch.stopall)
        patch.object(m,'private_root_file',side_effect=lambda h,p,**kw:self.raw[p.name]).start()
        patch.object(m,'load_path',side_effect=lambda p:{'inspect-runtime.py':self.inspector,
            'inspect-source-destinations.py':self.source,'host-configuration-stage.py':self.stage}[p.name]).start()

    def capture(self):
        return m.fresh_baseline(self.helper,self.spec,{'runtime-recipe.json':b'{}'},
                                {'stage':'/fixture/original','members':{}})

    def test_new_boot_is_explicit_not_rewritten_historical_evidence(self):
        result=self.capture()
        self.assertEqual(result['observation']['boot_id'],self.boot)
        self.assertEqual(result['recovery_bundle_sha256'],'a'*64)
        self.assertEqual(self.baseline['observation']['boot_id'],'old')
        self.assertEqual(self.inspector.installed_state.call_count,2)

    def test_changed_recovery_boot_holds(self):
        self.spec['recovered_boot_id']='different'
        with self.assertRaisesRegex(ValueError,'recovered boot'):self.capture()
        self.source.observation.assert_not_called()

    def test_package_drift_holds(self):
        self.observed['inventory']={'unexpected':['2','installed']}
        with self.assertRaisesRegex(ValueError,'package/service'):self.capture()

    def test_native_drift_holds(self):
        self.inspector.installed_state.return_value=({'files':{'unexpected':{}}},{})
        with self.assertRaisesRegex(ValueError,'installed release'):self.capture()

    def test_protected_configuration_drift_holds(self):
        self.inspector.protected_files.return_value={'boot':'changed'}
        with self.assertRaisesRegex(ValueError,'protected configuration'):self.capture()

    def test_changes_during_capture_hold(self):
        self.source.observation.side_effect=[self.observed,dict(self.observed,boot_id='changed')]
        with self.assertRaisesRegex(ValueError,'changed during capture'):self.capture()


class RecoveredBindings(unittest.TestCase):
    def archive(self,files):
        import io,tarfile
        files=dict(files,**{'manifest.json':m.encoded({n:m.sha(v) for n,v in files.items()})})
        out=io.BytesIO()
        with tarfile.open(fileobj=out,mode='w') as t:
            for name,data in files.items():
                info=tarfile.TarInfo(name);info.size=len(data);t.addfile(info,io.BytesIO(data))
        return out.getvalue()

    def setUp(self):
        hardware=m.encoded({'network_bundle_sha256':'a'*64,'network_spec_sha256':'b'*64})
        rawhardware=self.archive({'spec.json':hardware})
        recovery={'operation':'host-recovery-continuation','stage':'/var/lib/ntp-recovery-fixture',
                  'hostname':'fixture','kernel':'fixture','ssh':{},'old_ipv4':'192.0.2.2','endpoints':['v4','v6'],
                  'hardware_sha256':m.sha(rawhardware)}
        rawspec=m.encoded(recovery);rawrecovery=self.archive({'spec.json':rawspec,'hardware.tar':rawhardware})
        proof={'boot_id':'recovered','checks':{'original_boot_files':True,'new_boot':True,'network_and_native_continuity':True}}
        receipt={'state':'recovery_accepted','bundle_sha256':m.sha(rawrecovery),'spec_sha256':m.sha(rawspec),
                 'proof':proof,'endpoint_proofs':{'v4':proof,'v6':proof}}
        cleanup={'phase':'accepted','transient_units_cleaned':True,'proof':proof,'endpoint_proofs':receipt['endpoint_proofs']}
        self.files={'recovery.tar':rawrecovery,'hardware-spec.json':hardware,'recovery-acceptance.json':m.encoded(receipt),
                    'recovery-cleanup.json':m.encoded(cleanup)}
        self.spec={k:recovery[k] for k in ('hostname','kernel','ssh','old_ipv4','endpoints')}
        self.spec.update(recovery_bundle_sha256=m.sha(rawrecovery),hardware_bundle_sha256=m.sha(rawhardware),
                         recovered_boot_id='recovered',network_bundle_sha256='a'*64,network_spec_sha256='b'*64)

    def test_exact_completed_recovery_provenance(self):
        self.assertEqual(m.recovery_inputs(self.files,self.spec)[0]['hostname'],'fixture')

    def test_incomplete_cleanup_rejected(self):
        cleanup=json.loads(self.files['recovery-cleanup.json']);cleanup['transient_units_cleaned']=False
        self.files['recovery-cleanup.json']=m.encoded(cleanup)
        with self.assertRaisesRegex(ValueError,'provenance'):m.recovery_inputs(self.files,self.spec)

    def test_boot_network_or_archive_substitution_rejected(self):
        for name in ('recovered_boot_id','network_bundle_sha256','recovery_bundle_sha256'):
            with self.subTest(name=name),self.assertRaises(ValueError):
                m.recovery_inputs(self.files,dict(self.spec,**{name:'changed'}))

    def test_missing_endpoint_proof_rejected(self):
        receipt=json.loads(self.files['recovery-acceptance.json']);del receipt['endpoint_proofs']['v6']
        self.files['recovery-acceptance.json']=m.encoded(receipt)
        with self.assertRaisesRegex(ValueError,'provenance'):m.recovery_inputs(self.files,self.spec)


class HardwareRecoveryBindings(unittest.TestCase):
    archive=RecoveredBindings.archive

    def setUp(self):
        old={'operation':'hardware','stage':'/var/lib/ntp-host-fixture','hostname':'fixture','kernel':'fixture',
             'ssh':{},'old_ipv4':'192.0.2.2','network_bundle_sha256':'a'*64,'network_spec_sha256':'b'*64,
             'recipe':{'ipv4_address':'192.0.2.1/24','ipv6_address':'2001:db8::1/64'}}
        rawspec=m.encoded(old);raw=self.archive({'spec.json':rawspec})
        self.spec={k:old[k] for k in ('hostname','kernel','ssh','old_ipv4','network_bundle_sha256','network_spec_sha256')}
        self.spec.update(endpoints=['192.0.2.1','2001:db8::1'],recovered_boot_id=UUID,
                         recovery_bundle_sha256=m.sha(raw),hardware_bundle_sha256=m.sha(raw))
        self.receipt={'bundle_sha256':m.sha(raw),'result':{'phase':'recovered','boot_id':UUID}}
        self.cleanup={'bundle_sha256':m.sha(raw),'result':{'phase':'recovered','recovered_boot_id':UUID,
                                                        'transient_units_cleaned':True}}
        self.files={'recovery.tar':raw,'hardware-spec.json':rawspec,
                    'recovery-acceptance.json':m.encoded(self.receipt),'recovery-cleanup.json':m.encoded(self.cleanup)}

    def test_completed_hardware_recovery(self):
        self.assertEqual(m.recovery_inputs(self.files,self.spec)[0]['operation'],'hardware')

    def test_cleanup_and_boot_substitution_rejected(self):
        for key,value in [('phase','recovery_files_restored'),('transient_units_cleaned',False),('recovered_boot_id',OTHER)]:
            changed=json.loads(m.encoded(self.cleanup));changed['result'][key]=value
            files=dict(self.files,**{'recovery-cleanup.json':m.encoded(changed)})
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'provenance'):
                m.recovery_inputs(files,self.spec)

    def test_wrong_archive_network_endpoint_or_boot_rejected(self):
        for key,value in [('recovery_bundle_sha256','c'*64),('network_spec_sha256','c'*64),
                          ('endpoints',['192.0.2.3']),('recovered_boot_id',OTHER)]:
            with self.subTest(key=key),self.assertRaises(ValueError):
                m.recovery_inputs(self.files,dict(self.spec,**{key:value}))

    def test_recovery_receipt_required(self):
        changed=dict(self.receipt,result={'phase':'recovery_reboot_submitted','boot_id':UUID})
        with self.assertRaisesRegex(ValueError,'provenance'):
            m.recovery_inputs(dict(self.files,**{'recovery-acceptance.json':m.encoded(changed)}),self.spec)


if __name__ == '__main__':
    unittest.main()
