#!/usr/bin/python3
"""Local file-transaction tests; systemd/hardware seams are not native acceptance."""
import copy
from contextlib import nullcontext
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('service', ROOT / 'scripts/clockmaker-service.py')
s = importlib.util.module_from_spec(spec); spec.loader.exec_module(s)


def write(path, value):
    path.write_text(json.dumps(value))
    return s.c.digest(path.read_bytes())


class ServiceLifecycle(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.calls = []; self.owners = {}; self.fail = None
        self.destinations = {n: str(self.root / p.lstrip('/')) for n, p in s.DESTINATIONS.items()}
        self.directories = tuple(str(self.root / p.lstrip('/')) for p in s.DIRECTORIES)
        for target in self.destinations.values():
            if '/var/lib/' not in target: Path(target).parent.mkdir(parents=True, exist_ok=True)
        (self.root / 'var/lib').mkdir(parents=True); (self.root / 'var/log').mkdir()
        self.add_patch(s, 'DESTINATIONS', self.destinations)
        self.add_patch(s, 'DIRECTORIES', self.directories)
        self.add_patch(s, 'lifecycle_lock', lambda **kwargs: nullcontext())
        self.add_patch(s.os, 'geteuid', lambda: 0)
        real_lstat = Path.lstat
        def metadata(path, *args, **kwargs):
            fields = list(real_lstat(path, *args, **kwargs))
            fields[4], fields[5] = self.owners.get(str(path), (0, 0))
            if stat.S_ISDIR(fields[0]): fields[0] &= ~0o022
            return os.stat_result(fields)
        self.add_patch(Path, 'lstat', metadata)
        self.add_patch(s.os, 'chown', lambda path, uid, gid: self.owners.update({str(path): (uid, gid)}))
        self.add_patch(s.os, 'fchown', lambda *args: None)
        self.add_patch(s.c, 'target_identity', lambda name: self.assertEqual(name, 'ntp-west.example.test'))
        self.add_patch(s.c, 'require_no_package_applications', lambda: None)
        self.add_patch(s.c, 'require_stopped_daemons', self.stopped)
        self.add_patch(s.c, 'safe_destination', lambda p: self.root / p)
        self.add_patch(s, 'unit', self.unit)
        self.add_patch(s, 'command', self.command)
        self.add_patch(s, 'hardware', lambda config: {'uart': 'isolated-character-device-seam'})
        self.active = False; self.enabled = False; self.bootstrap_active = True; self.bootstrap_enabled = True
        self.override = ''
        ntp = self.root / 'ntp.conf'
        ntp.write_text('driftfile /var/lib/ntpsec/drift/ntp.drift\nleapfile /var/lib/ntpsec/leap-seconds.list\nstatsdir /var/log/ntpstats/\n')
        unit = self.root / 'timeservice.service'; unit.write_bytes((ROOT / 'templates/timeservice.service').read_bytes())
        leap = self.root / 'leap-seconds.list'; leap.write_text('#@ ' + str(int(time.time()) + 2208988800 + 86400) + '\n')
        config = {'schema': 1, 'hostname': 'ntp-west.example.test',
            'timeservice': {'uart_device': '/dev/serial0',
                'gpsd': ['/usr/local/sbin/gpsd', '-N', '-n', '-s', '115200', '/dev/serial0', '/dev/pps0'],
                'ntpd': ['/usr/local/sbin/ntpd', '-n', '-m', '-u', str(os.getuid()) + ':' + str(os.getgid()), '-c', '/etc/ntp.conf'],
                'startup_gate': {'timeout_seconds': 30, 'matching_samples_per_source': 5,
                                 'units': {'TOFF': 'NTP0', 'PPS': 'NTP2'}}}}
        for name, path in [('ntp_config', ntp), ('unit', unit), ('leapfile', leap)]:
            config[name] = {'path': path.name, 'sha256': s.c.digest(path.read_bytes())}
        self.config = self.root / 'config.json'; config_sha = write(self.config, config)
        names = ['usr/local/sbin/ntpd', 'usr/local/sbin/gpsd', 'usr/local/bin/gpspipe',
                 'usr/local/bin/ntpshmmon', 'usr/local/libexec/timeservice.py',
                 'usr/local/libexec/gpsd-pairing.py', 'usr/local/libexec/measure-time-service.py',
                 'usr/local/libexec/check-time-client.py']
        files = {}
        for name in names:
            path = self.root / name; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'isolated release payload'); path.chmod(0o755)
            files[name] = {'type': 'file', 'mode': 0o755, 'sha256': s.c.digest(path.read_bytes())}
        release = self.root / 'release.json'
        release_sha = write(release, {'schema': 1, 'hostname': config['hostname'], 'files': files})
        self.profile = self.root / 'deployment.json'
        self.profile_sha = write(self.profile, {'schema': 1, 'hostname': config['hostname'],
            'release': {'path': release.name, 'sha256': release_sha},
            'configuration': {'path': self.config.name, 'sha256': config_sha},
            'client': {'hostname': 'client.example.test', 'ipv4': '192.0.2.10', 'ipv6': '2001:db8::10'},
            'health': {'timeout_seconds': 90, 'interval_seconds': 30, 'consecutive_samples': 3,
                       'offset_ms': 5, 'jitter_ms': 1, 'peers': ['SHM(0)', 'SHM(2)', 'nts-a', 'nts-b', 'nts-c'],
                       'credentials': {'gpsd': {'uid': [0]*4, 'gid': [0]*4},
                                       'ntpd': {'uid': [os.getuid()]*4, 'gid': [os.getgid()]*4}},
                       'ipv4': '192.0.2.51', 'ipv6': '2001:db8::51'}})

    def add_patch(self, obj, name, value):
        binding = patch.object(obj, name, value); binding.start(); self.addCleanup(binding.stop)

    def unit(self, name, journal=None):
        if name.startswith('clockmaker-recovery-'):
            return {'ActiveState': 'active' if getattr(self, 'guard', False) else 'inactive'}
        loaded = name == s.BOOTSTRAP or (name == s.UNIT and Path(self.destinations['timeservice.service']).exists())
        active = self.active if name == s.UNIT else self.bootstrap_active if name == s.BOOTSTRAP else False
        enabled = self.enabled if name == s.UNIT else self.bootstrap_enabled if name == s.BOOTSTRAP else False
        return {'LoadState': 'loaded' if loaded else 'not-found', 'ActiveState': 'active' if active else 'inactive',
                'SubState': 'running' if active else 'dead', 'UnitFileState': 'enabled' if enabled else 'disabled' if loaded else '',
                'MainPID': '42' if active else '0', 'NRestarts': '0', 'InvocationID': 'same-invocation' if active else '',
                'FragmentPath': self.destinations['timeservice.service'] if name == s.UNIT and loaded else '',
                'DropInPaths': self.override if name == s.UNIT else ''}

    def command(self, argv, journal=None, timeout=20, allowed=(0,)):
        self.calls.append(argv)
        if self.fail and self.fail(argv): raise ValueError('injected native failure')
        if argv[0] == '/usr/bin/systemd-run': self.guard = True
        if argv[0] == '/usr/bin/systemctl' and len(argv) == 3 and argv[2].startswith('clockmaker-recovery-'):
            self.guard = False
            return ''
        if argv[0] == '/usr/bin/systemctl' and len(argv) == 3:
            action, unit = argv[1:]
            attr = 'active' if action in ('start', 'stop') else 'enabled'
            if unit == s.BOOTSTRAP: attr = 'bootstrap_' + attr
            if action in ('start', 'stop', 'enable', 'disable'):
                setattr(self, attr, action in ('start', 'enable'))
        return ''

    def stopped(self):
        if self.active: raise ValueError('daemons remain running')

    def execute(self, phase):
        state = self.root / (phase + '-state.json')
        checksum = write(state, s.preflight(self.profile, self.profile_sha, phase))
        return s.execute(self.profile, self.profile_sha, phase, state, checksum, self.root / (phase + '-journal'))

    def good_health(self, spec, journal):
        return {'service': self.unit(s.UNIT), 'measurement': {'local_fixture': True}, 'epoch': time.time()}

    def accept_trial(self):
        journal = self.root / 'activate-journal'
        challenge_path = journal / 'client-challenge.json'
        challenge = json.loads(challenge_path.read_text())
        result = {'target': challenge['hostname'], 'client': challenge['client'],
                  'nonce': challenge['nonce'], 'boot_id': challenge['boot_id'],
                  'invocation': challenge['invocation'], 'epoch': time.time(),
                  'spec_sha256': s.c.digest(challenge_path.read_bytes()),
                  'checks': {'ipv4': True, 'ipv6': True, 'queries_denied': True, 'mdns': True},
                  'observations': {k: {'local_address': challenge['client'][k]} for k in ('ipv4', 'ipv6')}}
        output = self.root / 'client-result.json'; checksum = write(output, result)
        plan = journal / 'recovery.json'
        return s.accept(plan, s.c.digest(plan.read_bytes()), output, checksum)

    def test_apply_keeps_bootstrap_active_and_no_service_start(self):
        result = self.execute('apply-configuration')
        self.assertEqual(result['state'], 'configured_inactive')
        self.assertTrue(self.bootstrap_active); self.assertFalse(self.active); self.assertFalse(self.enabled)
        for name, target in self.destinations.items(): self.assertTrue(Path(target).is_file(), name)
        self.assertFalse(any(c[1:2] == ['start'] for c in self.calls))
        self.assertTrue(any(c[:2] == ['/usr/bin/systemd-analyze', 'verify'] for c in self.calls))
        with self.assertRaises(FileExistsError): self.execute('apply-configuration')

    def test_health_then_boot_enable_and_no_predecessor_input(self):
        self.execute('apply-configuration')
        self.add_patch(s, 'health_sample', self.good_health)
        self.add_patch(s.time, 'sleep', lambda _: None)
        result = self.execute('activate')
        self.assertEqual(result['state'], 'awaiting_acceptance')
        self.assertTrue(self.active and self.guard); self.assertFalse(self.enabled)
        result = self.accept_trial()
        self.assertEqual(result['state'], 'active_enabled'); self.assertFalse(self.guard)
        self.assertTrue(self.active and self.enabled)
        self.assertFalse(self.bootstrap_active or self.bootstrap_enabled)
        self.assertEqual(len(result['samples']), 3)
        journal = self.root / 'activate-journal'
        plan = journal / 'recovery.json'
        with self.assertRaisesRegex(ValueError, 'completed'):
            s.recover(plan, s.c.digest(plan.read_bytes()))
        self.assertFalse((self.root / '.local-evidence').exists())

    def test_enable_failure_restores_bootstrap_and_preserves_configuration(self):
        self.execute('apply-configuration')
        before = {n: Path(p).read_bytes() for n, p in self.destinations.items()}
        self.add_patch(s, 'health_sample', self.good_health); self.add_patch(s.time, 'sleep', lambda _: None)
        self.fail = lambda argv: argv == ['/usr/bin/systemctl', 'enable', s.UNIT]
        self.execute('activate')
        with self.assertRaisesRegex(ValueError, 'injected'): self.accept_trial()
        self.assertFalse(self.active or self.enabled); self.assertTrue(self.bootstrap_active and self.bootstrap_enabled)
        self.assertEqual(before, {n: Path(p).read_bytes() for n, p in self.destinations.items()})
        status = json.loads((self.root / 'activate-journal/status.json').read_text())
        self.assertEqual(status['state'], 'restored'); self.assertIn('error', status)

    def test_apply_failure_restores_old_bytes_and_retains_runtime_data(self):
        target = Path(self.destinations['ntp.conf']); target.write_bytes(b'old'); target.chmod(0o640)
        calls = 0
        def failure(argv):
            nonlocal calls
            if argv == ['/usr/bin/systemctl', 'daemon-reload']:
                calls += 1
                return calls == 1
            return False
        self.fail = failure
        with self.assertRaises(ValueError): self.execute('apply-configuration')
        self.assertEqual(target.read_bytes(), b'old')
        self.assertFalse(Path(self.destinations['timeservice.service']).exists())
        status = json.loads((self.root / 'apply-configuration-journal/status.json').read_text())
        self.assertEqual(status['state'], 'restored'); self.assertTrue(status['retained_runtime_directories'])

    def test_preflight_rejects_missing_helpers_overrides_and_config_drift(self):
        helper = self.root / 'usr/local/libexec/gpsd-pairing.py'; helper.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'release drift'): self.execute('apply-configuration')
        self.assertFalse((self.root / 'apply-configuration-journal').exists())
        helper.write_bytes(b'isolated release payload')
        self.override = '/foreign.conf'
        with self.assertRaisesRegex(ValueError, 'overrides'): self.execute('apply-configuration')
        self.override = ''; self.execute('apply-configuration')
        Path(self.destinations['ntp.conf']).write_bytes(b'drift')
        with self.assertRaisesRegex(ValueError, 'applied'): self.execute('activate')
        self.assertFalse((self.root / 'activate-journal').exists())

    def test_interruption_recovers_and_recovery_failure_is_explicit(self):
        self.execute('apply-configuration')
        self.add_patch(s, 'health_sample', lambda *args: (_ for _ in ()).throw(KeyboardInterrupt()))
        self.fail = lambda argv: argv == ['/usr/bin/systemctl', 'stop', s.UNIT]
        with self.assertRaises(KeyboardInterrupt): self.execute('activate')
        journal = self.root / 'activate-journal'
        self.assertEqual(json.loads((journal / 'status.json').read_text())['state'], 'manual_recovery_required')
        self.fail = None
        plan = journal / 'recovery.json'
        self.assertEqual(s.recover(plan, s.c.digest(plan.read_bytes()))['state'], 'restored')
        self.assertTrue(self.bootstrap_active); self.assertFalse(self.active)

    def test_timeout_does_not_enable_and_records_failed_samples(self):
        self.execute('apply-configuration')
        clock = [0]
        def not_converged(*args):
            clock[0] = 91
            raise ValueError('not converged')
        self.add_patch(s, 'health_sample', not_converged)
        self.add_patch(s.time, 'monotonic', lambda: clock[0]); self.add_patch(s.time, 'sleep', lambda _: None)
        with self.assertRaisesRegex(ValueError, 'deadline'): self.execute('activate')
        status = json.loads((self.root / 'activate-journal/status.json').read_text())
        self.assertEqual(status['state'], 'restored'); self.assertTrue(status['samples'])
        self.assertNotIn(['/usr/bin/systemctl', 'enable', s.UNIT], self.calls)

    def test_recovery_refuses_unrelated_configuration_and_corrupt_backup(self):
        self.execute('apply-configuration')
        self.add_patch(s, 'health_sample', lambda *args: (_ for _ in ()).throw(KeyboardInterrupt()))
        self.fail = lambda argv: argv == ['/usr/bin/systemctl', 'stop', s.UNIT]
        with self.assertRaises(KeyboardInterrupt): self.execute('activate')
        journal = self.root / 'activate-journal'; plan = journal / 'recovery.json'
        original = Path(self.destinations['ntp.conf']).read_bytes()
        Path(self.destinations['ntp.conf']).write_bytes(b'foreign change')
        self.fail = None; count = len(self.calls)
        with self.assertRaisesRegex(ValueError, 'drift'): s.recover(plan, s.c.digest(plan.read_bytes()))
        self.assertEqual(len(self.calls), count)
        Path(self.destinations['ntp.conf']).write_bytes(original)
        (journal / 'before/ntp.conf').write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError, 'backup hash'): s.recover(plan, s.c.digest(plan.read_bytes()))
        self.assertTrue(self.active); self.assertFalse(self.bootstrap_active)

    def test_installed_layout_uses_libexec_supervisor(self):
        original_exists = Path.exists
        original_load = s.load
        loaded = []
        def exists(path):
            if path == Path(s.__file__).with_name('timeservice.py'): return False
            return original_exists(path)
        def loader(path):
            loaded.append(str(path))
            if path == Path('/usr/local/libexec/timeservice.py'):
                return original_load(ROOT / 'scripts/timeservice.py')
            return original_load(path)
        with patch.object(Path, 'exists', exists), patch.object(s, 'load', loader):
            self.execute('apply-configuration')
        self.assertIn('/usr/local/libexec/timeservice.py', loaded)

    def pending(self):
        self.execute('apply-configuration')
        self.add_patch(s, 'health_sample', self.good_health)
        self.add_patch(s.time, 'sleep', lambda _: None)
        self.execute('activate')
        plan = self.root / 'activate-journal/recovery.json'
        return plan, s.c.digest(plan.read_bytes())

    def test_independent_expiry_restores_abandoned_trial_without_replaying(self):
        plan, checksum = self.pending()
        deadline = json.loads(plan.read_text())['deadline_monotonic']
        with self.assertRaisesRegex(ValueError, 'deadline'):
            s.recover(plan, checksum, automatic=True)
        with patch.object(s.time, 'monotonic', return_value=deadline + 1):
            result = s.recover(plan, checksum, automatic=True)
            self.assertEqual(result['state'], 'restored')
            count = len(self.calls)
            s.recover(plan, checksum, automatic=True)
            self.assertEqual(len(self.calls), count + 1)  # only stale timer cleanup
        self.assertFalse(self.active or self.enabled or self.guard)
        self.assertTrue(self.bootstrap_active and self.bootstrap_enabled)

    def test_completed_restoration_preserves_completion_and_timer_cannot_undo_commit(self):
        plan, checksum = self.pending(); self.accept_trial()
        completion = (plan.parent / 'completion.json').read_bytes()
        self.assertEqual(s.recover(plan, checksum, automatic=True)['state'], 'active_enabled')
        self.assertTrue(self.active and self.enabled)
        self.assertEqual(s.recover(plan, checksum, completed=True)['state'], 'restored')
        self.assertEqual((plan.parent / 'completion.json').read_bytes(), completion)
        self.assertTrue((plan.parent / 'restoration.json').exists())
        self.assertTrue(self.bootstrap_active and self.bootstrap_enabled)
        self.assertFalse(self.active or self.enabled)

    def test_completed_configuration_cannot_be_restored_under_running_service(self):
        self.pending()
        plan = self.root / 'apply-configuration-journal/recovery.json'
        before = {n: Path(p).read_bytes() for n, p in self.destinations.items()}
        with self.assertRaisesRegex(ValueError, 'restore activation'):
            s.recover(plan, s.c.digest(plan.read_bytes()), completed=True)
        self.assertEqual(before, {n: Path(p).read_bytes() for n, p in self.destinations.items()})
        self.assertTrue(self.active)

    def test_client_check_binds_identity_and_observed_source_addresses(self):
        self.pending()
        path = self.root / 'activate-journal/client-challenge.json'
        challenge = json.loads(path.read_text()); digest = s.c.digest(path.read_bytes())
        class Checker:
            def check(inner, spec, checksum):
                return {'target': spec['hostname'], 'spec_sha256': checksum,
                        'observations': {k: {'local_address': spec['client'][k]} for k in ('ipv4', 'ipv6')}}
        real_bytes = s.c.regular_bytes
        def reader(p):
            return b'isolated release payload' if p.name == 'check-time-client.py' else real_bytes(p)
        with patch.object(s.c, 'regular_bytes', reader), patch.object(s, 'load', return_value=Checker()), patch.object(s.c, 'target_identity') as identity:
            result = s.check_client(path, digest)
            identity.assert_called_once_with(challenge['client']['hostname'])
        self.assertEqual(result['nonce'], challenge['nonce'])
        self.assertEqual(result['invocation'], challenge['invocation'])

    def test_missing_guard_or_bad_external_result_never_enables(self):
        plan, checksum = self.pending()
        self.guard = False
        with self.assertRaisesRegex(ValueError, 'protection'): self.accept_trial()
        self.assertFalse(self.enabled)
        self.assertEqual(json.loads((plan.parent / 'status.json').read_text())['state'], 'awaiting_acceptance')

    def test_late_acceptance_holds_without_enabling_or_cancelling_recovery(self):
        plan, checksum = self.pending()
        deadline = json.loads(plan.read_text())['deadline_monotonic']
        with patch.object(s.time, 'monotonic', return_value=deadline - 299), self.assertRaisesRegex(ValueError, 'margin'):
            self.accept_trial()
        self.assertFalse(self.enabled); self.assertTrue(self.guard)

    def test_replayed_external_result_cannot_accept_new_trial(self):
        plan, checksum = self.pending()
        real_bound = s.c.bound_json
        def changed(path, digest):
            result = real_bound(path, digest)
            if path.name == 'client-result.json': result['nonce'] = 'different trial'
            return result
        with patch.object(s.c, 'bound_json', changed), self.assertRaisesRegex(ValueError, 'bound external'):
            self.accept_trial()
        self.assertFalse(self.enabled); self.assertTrue(self.guard)

    def test_failure_to_arm_prevents_configuration_effects(self):
        self.fail = lambda argv: argv[0] == '/usr/bin/systemd-run'
        with self.assertRaisesRegex(ValueError, 'injected'): self.execute('apply-configuration')
        self.assertFalse(any(Path(p).exists() for p in self.destinations.values()))
        self.assertTrue(self.bootstrap_active)

    def test_partial_source_install_restores_even_if_progress_write_was_interrupted(self):
        root = self.root / 'source'; root.mkdir()
        names = ['usr/local/bin/example-a', 'usr/local/bin/example-b']
        old = self.root / names[0]; old.parent.mkdir(parents=True, exist_ok=True)
        old.write_bytes(b'old'); old.chmod(0o755)
        files = {}
        for name in names:
            stage = root / 'stage' / name; stage.parent.mkdir(parents=True, exist_ok=True)
            stage.write_bytes(b'new'); stage.chmod(0o755)
            files[name] = {'type': 'file', 'sha256': s.c.digest(b'new'), 'mode': 0o755}
        release = root / 'release.json'
        release_hash = write(release, {'schema': 1, 'hostname': 'ntp-west.example.test', 'files': files})
        state = root / 'before.json'; state_hash = write(state, s.c.inspect_install(release, release_hash))
        real_replace = os.replace
        def interrupted(source, destination):
            real_replace(source, destination)
            if Path(destination) == old: raise KeyboardInterrupt('after first file, before progress')
        journal = root / 'journal'
        with patch.object(s.c.os, 'replace', interrupted), self.assertRaises(KeyboardInterrupt):
            s.c.install(release, release_hash, state, state_hash, journal)
        receipt = journal / 'receipt.json'
        row = json.loads(receipt.read_text())
        self.assertEqual(row['installed'], []); self.assertTrue(row['backups_complete'])
        self.assertEqual(old.read_bytes(), b'new')
        restored = s.c.rollback(receipt, s.c.digest(receipt.read_bytes()))
        self.assertEqual(restored['state'], 'restored_not_activated')
        self.assertEqual(old.read_bytes(), b'old'); self.assertFalse((self.root / names[1]).exists())

    def test_parser_and_device_failures_hold_before_journal(self):
        self.fail = lambda argv: argv[0] == '/usr/bin/systemd-analyze'
        with self.assertRaisesRegex(ValueError, 'native'): self.execute('apply-configuration')
        self.assertFalse((self.root / 'apply-configuration-journal').exists())
        self.fail = None
        self.add_patch(s, 'hardware', lambda _: (_ for _ in ()).throw(ValueError('missing device')))
        with self.assertRaisesRegex(ValueError, 'missing device'): self.execute('apply-configuration')
        self.assertFalse((self.root / 'apply-configuration-journal').exists())



class HealthAndCommands(unittest.TestCase):
    def test_timing_rejects_false_selection_nonfinite_and_wrong_peers(self):
        health = {'peers': ['SHM(0)', 'SHM(2)', 'nts-a', 'nts-b', 'nts-c'], 'pps_peer': 'SHM(2)', 'offset_ms': 5, 'jitter_ms': 1}
        measurement = {'system': {'leap': 0, 'stratum': 1, 'offset': .1},
            'peers': [{'status': 6 << 8, 'variables': {'srchost': 'SHM(2)', 'refid': '.PPS.',
                'reach': 377, 'offset': .2, 'jitter': .1}}]}
        measurement['peers'].append({'status': 0, 'variables': {'srchost': 'SHM(0)', 'reach': 377}})
        measurement['peers'].extend({'status': 0x6000, 'variables': {'srchost': name, 'reach': 377, 'ntscookies': 8}} for name in ('nts-a', 'nts-b', 'nts-c'))
        self.assertTrue(s.timing_ok(measurement, health))
        for key, value in [('jitter', float('nan')), ('offset', 10), ('refid', 'OTHER'), ('reach', 0)]:
            altered = copy.deepcopy(measurement); altered['peers'][0]['variables'][key] = value
            self.assertFalse(s.timing_ok(altered, health))
        for key, value in [('ntscookies', 0), ('reach', 0)]:
            altered = copy.deepcopy(measurement); altered['peers'][2]['variables'][key] = value
            self.assertFalse(s.timing_ok(altered, health))
        altered = copy.deepcopy(measurement); altered['peers'][2]['status'] = 0
        self.assertFalse(s.timing_ok(altered, health))
        measurement['peers'][0]['status'] = 5 << 8
        self.assertFalse(s.timing_ok(measurement, health))

    def test_native_health_rejects_restart_or_missing_pair_before_queries(self):
        service = {'ActiveState': 'active', 'NRestarts': '1', 'MainPID': '12',
                   'InvocationID': 'one', 'FragmentPath': s.DESTINATIONS['timeservice.service']}
        with patch.object(s, 'unit', return_value=service), patch.object(s, 'command') as commands:
            with self.assertRaisesRegex(ValueError, 'restarted'): s.health_sample({}, None)
            commands.assert_not_called()
        service['NRestarts'] = '0'
        with patch.object(s, 'unit', side_effect=[service, {'ActiveState': 'inactive'}]), patch.object(s, 'command', return_value=''):
            with self.assertRaisesRegex(ValueError, 'pair mismatch'): s.health_sample({'health': {'credentials': {'gpsd': {}, 'ntpd': {}}}}, None)

    def test_timer_properties_do_not_require_service_only_pid(self):
        raw = 'LoadState=loaded\nActiveState=active\nUnitFileState=transient\n'
        with patch.object(s, 'command', return_value=raw):
            self.assertEqual(s.unit('example.timer')['ActiveState'], 'active')
            with self.assertRaisesRegex(ValueError, 'incomplete'): s.unit('example.service')

    def test_journal_boundary_uses_monotonic_time_and_rejects_errors(self):
        with patch.object(s, 'command', return_value='{"__MONOTONIC_TIMESTAMP":"99"}\n'):
            s.journal_errors('boot', 100)
        for raw in ('{"__MONOTONIC_TIMESTAMP":"100"}\n', '{"MESSAGE":"missing timestamp"}\n'):
            with patch.object(s, 'command', return_value=raw), self.assertRaises((ValueError, KeyError)):
                s.journal_errors('boot', 100)

    def test_native_command_failure_retains_both_streams(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)
            with self.assertRaisesRegex(ValueError, 'native command failed'):
                s.command(['/usr/bin/python3', '-c', 'import sys; print("out"); print("err",file=sys.stderr); sys.exit(3)'], journal)
            row = json.loads((journal / 'commands.jsonl').read_text())
            self.assertEqual((row['returncode'], row['stdout'], row['stderr']), (3, 'out\n', 'err\n'))

    def test_timeout_retains_partial_output(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)
            failure = subprocess.TimeoutExpired(['native'], 1, output=b'partial out', stderr=b'partial err')
            with patch.object(s.subprocess, 'run', side_effect=failure), self.assertRaises(subprocess.TimeoutExpired):
                s.command(['native'], journal)
            record = json.loads((journal / 'commands.jsonl').read_text())
            self.assertEqual((record['stdout'], record['stderr']), ('partial out', 'partial err'))
            self.assertIsNone(record['returncode']); self.assertTrue(record['error'])


if __name__ == '__main__': unittest.main()
