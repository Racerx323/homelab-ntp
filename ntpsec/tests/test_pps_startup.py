#!/usr/bin/python3
"""Offline promotion timing, authentication, interrupted mutation and recovery tests."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]


def load(path):
    spec = importlib.util.spec_from_file_location(path.stem.replace('-', '_'), path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


s = load(ROOT/'scripts/pps-startup.py')
c = load(ROOT/'scripts/run-service-cutover.py')
base = load(ROOT/'tests/test_service_cutover.py')


def observation(n=1, final=False):
    pps = {'associd': 7, 'status': 0x9600, 'clock': {'poll': n},
           'variables': {'srcadr': 'SHM(2)', 'refid': 'PPS', 'offset': .1, 'jitter': .01,
                         'reach': 255, 'received': n, 'rec': str(n)}}
    peers = [pps]
    if final:
        peers += [{'associd': 8, 'status': 0x9400, 'variables': {'srcadr': 'SHM(0)', 'reach': 255}}]
        peers += [{'associd': i, 'status': 0xe400, 'variables': {'srchost': host, 'reach': 255,
                   'ntscookies': 7}} for i, host in enumerate(s.SERVERS, 9)]
    return {'system': {'leap': 0, 'stratum': 1, 'peer': 7}, 'peers': peers}


JOURNAL = [(0, 'freq_set'), (30, 'freq_mode'), (390, 'freq_set'), (391, 'clock_sync')]


def qualified():
    m = s.Machine()
    m.observe(10, observation(1), [])
    for i, elapsed in enumerate((600, 664, 728), 2):
        action = m.observe(elapsed, observation(i), JOURNAL)
    assert action == 'promote'
    return m


class PolicyTests(unittest.TestCase):
    def test_fresh_updates_then_promotion_without_pps_replacement(self):
        m = qualified(); m.promoted(730)
        for n in range(5, 8):
            action = m.observe(730+(n-4)*64, observation(n, True), JOURNAL)
        self.assertEqual(action, 'ready')
        self.assertEqual(m.pps_id, 7)
        with self.assertRaises(ValueError): m.promoted(1000)

    def test_repeated_queries_do_not_count_and_initial_freq_set_is_insufficient(self):
        for journal in ([], [(0, 'freq_set'), (20, 'clock_sync')], [(20, 'freq_mode')]):
            m = s.Machine(); m.observe(10, observation(), [])
            for n in range(2, 6):
                self.assertEqual(m.observe(600+n*10, observation(n), journal), 'wait')
        m = s.Machine(); m.observe(10, observation(), [])
        m.observe(600, observation(2), JOURNAL)
        for elapsed in (610, 620, 630):
            self.assertEqual(m.observe(elapsed, observation(2), JOURNAL), 'wait')
        self.assertEqual(m.stable, 1)

    def test_distinct_poll_and_receive_updates_are_both_required(self):
        m = s.Machine(); m.observe(10, observation(), [])
        row = observation(2); row['peers'][0]['clock']['poll'] = 1
        m.observe(600, row, JOURNAL)
        self.assertEqual(m.stable, 0)
        row['peers'][0]['clock']['poll'] = 2
        m.observe(601, row, JOURNAL)
        self.assertEqual(m.stable, 1)

    def test_deadlines_bad_samples_resets_steps_and_membership(self):
        for case in ('first', 'bootstrap', 'total', 'reset', 'step', 'replace', 'partial'):
            with self.subTest(case=case), self.assertRaises(ValueError):
                m = qualified()
                if case == 'first':
                    m = s.Machine(); m.observe(120, observation(), [])
                elif case == 'bootstrap': m.observe(900, observation(5), JOURNAL)
                elif case == 'total': m.promoted(730); m.observe(1500, observation(5, True), JOURNAL)
                elif case == 'reset': m.observe(750, observation(1), JOURNAL)
                elif case == 'step': m.observe(750, observation(5), JOURNAL+[(740, 'clock_step')])
                elif case == 'replace':
                    row = observation(5); row['peers'][0]['associd'] = 99; m.observe(750, row, JOURNAL)
                else: m.promoted(730); m.observe(750, observation(5), JOURNAL)
        for value in (6, float('nan'), float('inf')):
            m = qualified(); row = observation(5); row['peers'][0]['variables']['offset'] = value
            self.assertEqual(m.observe(750, row, JOURNAL), 'wait'); self.assertEqual(m.stable, 0)

    def test_final_nts_authentication_and_nmea_reach_required(self):
        for case in ('nts', 'nmea', 'cookie'):
            m = qualified(); m.promoted(730)
            for n in range(5, 9):
                row = observation(n, True)
                if case == 'nts': row['peers'][2]['status'] = 0x8400
                if case == 'nmea': row['peers'][1]['variables']['reach'] = 0
                if case == 'cookie': row['peers'][2]['variables']['ntscookies'] = 0
                self.assertEqual(m.observe(740+n*20, row, JOURNAL), 'wait')
        m = qualified(); m.promoted(730); row = observation(5, True)
        row['peers'][1]['status'] = 0x9600
        with self.assertRaisesRegex(ValueError, 'unexpected disciplined source'):
            m.observe(750, row, JOURNAL)

    def test_exact_configuration_and_local_admin_boundary(self):
        raw = (ROOT/'configs/j2-svntp1-ntp.conf').read_bytes()
        rendered = s.bootstrap(raw, Path('/run/ntpsec-startup/control.key')).decode()
        self.assertIn(s.PPS, rendered)
        for cmd in s.COMMANDS: self.assertNotIn(cmd, rendered)
        self.assertNotIn('noselect', rendered)
        for extra in (b'\nrestrict 192.0.2.5\n', b'\nkeys /tmp/other\n', b'\nincludefile /tmp/x\n', b'\nserver extra\n'):
            with self.assertRaises(ValueError): s.bootstrap(raw+extra, Path('/run/key'))

    def test_event_identity_and_pinned_codes(self):
        row = {'_BOOT_ID': 'a'*32, '_PID': '45', '_EXE': '/usr/local/sbin/ntpd',
               '__MONOTONIC_TIMESTAMP': '12000000', 'MESSAGE': 'PROTO: 0.0.0.0 c014 04 freq_mode'}
        self.assertEqual(s.events(json.dumps(row), 'a'*32, 45, 10), [(12, 'freq_mode')])
        for field, value in (('_PID', '46'), ('_BOOT_ID', 'b'*32), ('MESSAGE', 'PROTO: 0.0.0.0 c014 02 freq_mode')):
            with self.assertRaises(ValueError): s.events(json.dumps(dict(row, **{field: value})), 'a'*32, 45, 10)


class MutationTests(unittest.TestCase):
    def test_cold_trial_refuses_saved_drift_before_creating_credentials(self):
        config = json.loads((ROOT/'configs/service-cutover-recipe.json').read_text())['timeservice']
        config['pps_startup'] = s.POLICY
        with patch.object(s.Path, 'lstat', return_value=types.SimpleNamespace(st_mode=0o40700, st_uid=0)), \
                patch.object(s, 'protected_read', return_value=(ROOT/'configs/j2-svntp1-ntp.conf').read_bytes()), \
                patch.object(s.os.path, 'lexists', return_value=True), patch.object(s, 'create') as create:
            with self.assertRaisesRegex(ValueError, 'absent drift file'): s.Startup(config)
        create.assert_not_called()

    def test_successful_promotion_checks_membership_and_preserves_process(self):
        with tempfile.TemporaryDirectory() as temporary:
            runner = object.__new__(s.Startup); runner.root = Path(temporary)
            runner.session = Mock(); runner.session.config.return_value = True
            runner.machine = qualified(); runner.started = 0; runner.next_poll = 0
            runner.pid = None; runner.boot = 'a'*32
            runner.status = {'phase': 'bootstrap', 'commands': []}
            process = Mock(pid=45); process.poll.return_value = None
            with patch.object(s.time, 'monotonic', return_value=740), \
                    patch.object(s, 'measure', side_effect=[observation(5), observation(5, True)]), \
                    patch.object(s, 'events', return_value=JOURNAL), \
                    patch.object(s.subprocess, 'run', return_value=types.SimpleNamespace(stdout=b'')):
                runner.tick(process)
            self.assertEqual(runner.status['phase'], 'promoted')
            self.assertEqual(runner.status['ntpd_pid'], 45)
            self.assertEqual(runner.machine.pps_id, 7)
            self.assertEqual(runner.machine.stable, 0)
            self.assertEqual([call.args[0] for call in runner.session.config.call_args_list], list(s.COMMANDS))
            process.terminate.assert_not_called()

    def test_supervisor_stops_both_and_cleans_key_on_promotion_failure(self):
        service = load(ROOT/'scripts/timeservice.py')
        config = json.loads((ROOT/'configs/service-cutover-recipe.json').read_text())['timeservice']
        config['pps_startup'] = s.POLICY
        startup = Mock(argv=config['ntpd']); startup.tick.side_effect = ValueError('promotion failed')
        startup.finish.side_effect = OSError('retention failed')
        helper = types.SimpleNamespace(Startup=Mock(return_value=startup))
        gpsd, ntpd = Mock(), Mock()
        gpsd.poll.return_value = ntpd.poll.return_value = None
        with patch.object(service, 'check_startup'), patch.object(service.subprocess, 'run'), \
                patch.object(service.subprocess, 'Popen', side_effect=[gpsd, ntpd]), \
                patch.object(service.importlib.util, 'spec_from_file_location', return_value=Mock()), \
                patch.object(service.importlib.util, 'module_from_spec', return_value=helper):
            with self.assertRaisesRegex(ValueError, 'promotion failed'): service.supervise(config)
        gpsd.terminate.assert_called_once(); ntpd.terminate.assert_called_once()
        startup.finish.assert_called_once_with('supervisor failure')
        startup.close.assert_called_once()

    def test_close_removes_only_private_credentials_and_keeps_status(self):
        with tempfile.TemporaryDirectory() as temporary:
            runner = object.__new__(s.Startup); runner.root = Path(temporary); runner.session = Mock()
            for name in ('control.key', 'bootstrap.conf', 'promotion.json'):
                (runner.root/name).write_text('private fixture')
            with patch.object(s, 'protected_read', side_effect=lambda p: p.read_bytes()): runner.close()
            self.assertEqual([p.name for p in runner.root.iterdir()], ['promotion.json'])
            runner.session.sock.close.assert_called_once()

    def test_authenticated_client_never_retries_or_accepts_bad_mac(self):
        class Session:
            def __init__(self): self.sock = Mock()
            def openhost(self, host): assert host == '127.0.0.1'
            sendrequest = Mock()
            getresponse = Mock()
        packet = types.ModuleType('ntp.packet'); packet.ControlSession = Session
        packet.MODE_SIX_ALIGNMENT = 4
        packet.Authenticator = lambda _: {42: ('AES-128', b'key')}
        ntp = types.ModuleType('ntp'); ntp.packet = packet
        with patch.dict('sys.modules', {'ntp': ntp, 'ntp.packet': packet}):
            client = s.authenticated_session(Path('/unused'))
            client.getresponse.side_effect = TimeoutError('uncertain mutation')
            with self.assertRaises(TimeoutError): client.doquery(8, qdata=s.NMEA)
            client.sendrequest.assert_called_once()
            self.assertEqual(packet.MODE_SIX_ALIGNMENT, 4)
            client.getresponse.side_effect = lambda *a: setattr(client, '_authpass', False)
            with self.assertRaisesRegex(ValueError, 'unauthenticated'): client.doquery(8, qdata=s.NMEA)

    def test_partial_promotion_is_recorded_and_not_replayed(self):
        with tempfile.TemporaryDirectory() as temporary:
            runner = object.__new__(s.Startup); runner.root = Path(temporary)
            runner.session = Mock(); runner.session.config.side_effect = [True, TimeoutError('uncertain')]
            runner.machine = qualified(); runner.started = 0; runner.next_poll = 0
            runner.pid = None; runner.boot = 'a'*32
            runner.status = {'phase': 'bootstrap', 'commands': []}
            process = Mock(pid=45); process.poll.return_value = None
            with patch.object(s.time, 'monotonic', return_value=740), patch.object(s, 'measure', return_value=observation(5)), patch.object(s, 'events', return_value=JOURNAL), patch.object(s.subprocess, 'run', return_value=types.SimpleNamespace(stdout=b'')):
                with self.assertRaises(TimeoutError): runner.tick(process)
            record = json.loads((runner.root/'promotion.json').read_text())
            self.assertEqual(record['phase'], 'failed')
            self.assertEqual([c['state'] for c in record['commands']], ['authenticated_ack', 'submitted'])
            self.assertEqual(runner.session.config.call_count, 2)
            with self.assertRaisesRegex(ValueError, 'terminal'): runner.tick(process)
            self.assertEqual(runner.session.config.call_count, 2)


class MonitorTests(unittest.TestCase):
    def runner(self, root):
        runner = object.__new__(s.Startup)
        runner.root = root/'runtime'; runner.root.mkdir()
        runner.evidence = root/'startup-monitor.json'
        runner.policy = s.MONITOR_POLICY; runner.cursor = None
        runner.session = Mock(); runner.session.config.return_value = True
        runner.machine = s.Machine(s.MONITOR_POLICY)
        runner.started = 0; runner.next_poll = 0; runner.pid = None; runner.boot = 'a'*32
        runner.status = {'phase': 'bootstrap', 'commands': [], 'samples': [], 'sample_count': 0}
        return runner

    def tick(self, runner, elapsed, value, journal=JOURNAL):
        process = Mock(pid=45); process.poll.return_value = None
        with patch.object(s.time, 'monotonic', return_value=elapsed), \
                patch.object(s, 'measure', return_value=value), \
                patch.object(s, 'events', return_value=journal), \
                patch.object(s.subprocess, 'run', return_value=types.SimpleNamespace(stdout=b'')):
            runner.tick(process)

    def test_monitor_policy_matches_reproducible_candidate(self):
        self.assertEqual(json.loads((ROOT/'configs/pps-monitor-policy.json').read_text()), s.MONITOR_POLICY)
        self.assertNotIn('bootstrap_seconds', s.MONITOR_POLICY)
        self.assertNotIn('completion_seconds', s.MONITOR_POLICY)

    def test_slow_start_has_no_selection_or_quality_deadline(self):
        m = s.Machine(s.MONITOR_POLICY)
        row = observation(); row['peers'][0]['status'] = 0x9400
        self.assertEqual(m.observe(3600, row, JOURNAL), 'wait')
        for n, elapsed in enumerate((3664, 3728, 3792), 2):
            action = m.observe(elapsed, observation(n), [])
        self.assertEqual(action, 'promote')
        m.promoted(3792)
        for n in range(5, 8):
            action = m.observe(4000+n*64, observation(n, True), [])
        self.assertEqual(action, 'ready')

    def test_initialization_survives_incremental_journal_batches(self):
        m = s.Machine(s.MONITOR_POLICY)
        m.observe(10, observation(), [(0, 'freq_set'), (1, 'freq_mode')])
        m.observe(300, observation(2), [(300, 'freq_set')])
        self.assertFalse(m.initialized)
        m.observe(600, observation(3), [(301, 'clock_sync')])
        self.assertTrue(m.initialized)
        self.assertEqual(m.stable, 1)

    def test_monitor_reads_journal_incrementally_with_process_provenance(self):
        with tempfile.TemporaryDirectory() as temporary:
            runner = self.runner(Path(temporary))
            row = {'_BOOT_ID': 'a'*32, '_PID': '45', '_EXE': '/usr/local/sbin/ntpd',
                   '__MONOTONIC_TIMESTAMP': '1000000', '__CURSOR': 's=test;i=1',
                   'MESSAGE': 'PROTO: 0.0.0.0 c014 04 freq_mode'}
            process = Mock(pid=45); process.poll.return_value = None
            with patch.object(s.time, 'monotonic', return_value=30), \
                    patch.object(s, 'measure', return_value=observation()), \
                    patch.object(s.subprocess, 'run', return_value=types.SimpleNamespace(stdout=json.dumps(row).encode())) as run:
                runner.tick(process)
                self.assertNotIn('--after-cursor=s=test;i=1', run.call_args.args[0])
            with patch.object(s.time, 'monotonic', return_value=60), \
                    patch.object(s, 'measure', return_value=observation(2)), \
                    patch.object(s.subprocess, 'run', return_value=types.SimpleNamespace(stdout=b'')) as run:
                runner.tick(process)
                self.assertIn('--after-cursor=s=test;i=1', run.call_args.args[0])
                self.assertIn('_PID=45', run.call_args.args[0])
                self.assertIn('--boot='+'a'*32, run.call_args.args[0])
            self.assertEqual(runner.machine.init_stage, 1)

    def test_quality_degradation_and_clock_step_do_not_stop_or_repromote(self):
        m = s.Machine(s.MONITOR_POLICY)
        m.observe(10, observation(), [])
        for n in range(2, 5): m.observe(600+n*64, observation(n), JOURNAL)
        m.promoted(900)
        for n in range(5, 8): m.observe(900+n*64, observation(n, True), [])
        self.assertEqual(m.observe(1450, observation(7, True), []), 'wait')
        row = observation(8, True); row['peers'][0]['variables']['jitter'] = 2
        self.assertEqual(m.observe(1500, row, [(1499, 'clock_step')]), 'wait')
        self.assertEqual(m.stable, 0)
        row['peers'][0]['status'] = 0x9400; row['peers'][2]['status'] = 0xe600
        row['system']['stratum'] = 2
        self.assertEqual(m.observe(1800, row, []), 'wait')
        self.assertEqual(m.phase, 'promoted')

    def test_stable_monitor_continues_then_resumes_fast_cadence_on_degradation(self):
        with tempfile.TemporaryDirectory() as temporary:
            runner = self.runner(Path(temporary))
            self.tick(runner, 10, observation())
            for n in range(2, 5):
                # The promotion tick performs a second membership read.
                if n == 4:
                    with patch.object(s, 'measure', side_effect=[observation(n), observation(n, True)]), \
                            patch.object(s.time, 'monotonic', return_value=856), \
                            patch.object(s, 'events', return_value=JOURNAL), \
                            patch.object(s.subprocess, 'run', return_value=types.SimpleNamespace(stdout=b'')):
                        process = Mock(pid=45); process.poll.return_value = None
                        runner.tick(process)
                else: self.tick(runner, 600+n*64, observation(n))
            for n in range(5, 8): self.tick(runner, 900+(n-5)*64, observation(n, True), [])
            self.assertEqual(runner.status['phase'], 'ready')
            self.assertEqual(runner.next_poll, 1328)
            self.tick(runner, 1328, observation(8, True), [])
            self.assertEqual(runner.status['sample_count'], 8)
            row = observation(9, True); row['peers'][0]['variables']['jitter'] = 2
            self.tick(runner, 1628, row, [])
            self.assertEqual(runner.status['phase'], 'settling')
            self.assertEqual(runner.next_poll, 1658)
            self.assertEqual(runner.session.config.call_count, 4)

    def test_terminal_rejecting_sample_survives_runtime_directory_removal(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); runner = self.runner(root)
            self.tick(runner, 10, observation())
            row = observation(2); row['peers'][0]['associd'] = 99
            with self.assertRaisesRegex(ValueError, 'association replaced'):
                self.tick(runner, 40, row)
            runner.finish('supervisor failure'); runner.close()
            (runner.root/'promotion.json').unlink(); runner.root.rmdir()
            saved = json.loads(runner.evidence.read_text())
            self.assertEqual(saved['phase'], 'failed')
            self.assertEqual(saved['measurement']['peers'][0]['associd'], 99)
            self.assertEqual(saved['elapsed_seconds'], 40)
            self.assertEqual(saved['stop_reason'], 'supervisor failure')
            self.assertFalse(saved['running'])
            self.assertEqual(saved['sample_count'], 2)
            self.assertEqual(runner.evidence.stat().st_mode & 0o777, 0o600)

    def test_retention_is_bounded_and_does_not_capture_credentials(self):
        with tempfile.TemporaryDirectory() as temporary:
            runner = self.runner(Path(temporary))
            for n in range(1, 130):
                row = observation(n); row['peers'][0]['variables']['jitter'] = 2
                self.tick(runner, n*30, row)
            raw = runner.evidence.read_text(); saved = json.loads(raw)
            self.assertEqual(saved['sample_count'], 129)
            self.assertEqual(len(saved['samples']), 120)
            self.assertEqual(saved['samples'][0]['elapsed_seconds'], 300)
            self.assertLess(len(raw), 512*1024)
            self.assertNotIn('AES', raw)
            self.assertNotIn('control.key', raw)

    def test_failed_evidence_write_preserves_failure_and_credential_cleanup(self):
        with tempfile.TemporaryDirectory() as temporary:
            runner = self.runner(Path(temporary)); runner.session.sock.close.side_effect = OSError('socket close')
            for name in ('control.key', 'bootstrap.conf'): (runner.root/name).write_text('secret')
            with patch.object(runner, 'save', side_effect=OSError('disk full')), \
                    patch.object(s, 'protected_read', side_effect=lambda p: p.read_bytes()):
                row = observation(); row['peers'] = []
                with self.assertRaisesRegex(ValueError, 'one PPS association'):
                    self.tick(runner, 10, row)
                with self.assertRaisesRegex(OSError, 'socket close'): runner.close()
            self.assertFalse((runner.root/'control.key').exists())
            self.assertFalse((runner.root/'bootstrap.conf').exists())

    def test_operation_evidence_path_and_ownership_are_required(self):
        config = json.loads((ROOT/'configs/service-cutover-recipe.json').read_text())['timeservice']
        config['pps_startup'] = s.MONITOR_POLICY
        for path in ('', '/tmp/status.json', '/var/lib/ntp-acquire-x/../startup-monitor.json'):
            config['pps_monitor_evidence'] = path
            with self.assertRaisesRegex(ValueError, 'operation-bound'): s.Startup(config)
        config['pps_monitor_evidence'] = '/var/lib/ntp-acquire-test/startup-monitor.json'
        with patch.object(s.Path, 'lstat', return_value=types.SimpleNamespace(st_mode=0o40700, st_uid=1000)):
            with self.assertRaisesRegex(ValueError, 'protected monitor'): s.Startup(config)
        with patch.object(s.Path, 'lstat', return_value=types.SimpleNamespace(st_mode=0o40700, st_uid=0)), \
                patch.object(s.os.path, 'lexists', return_value=True):
            with self.assertRaisesRegex(ValueError, 'prior monitor evidence'): s.Startup(config)


class RecoveryTests(unittest.TestCase):
    def test_journal_allowance_moves_to_promotion_and_stays_bounded(self):
        row = base.JournalTests().row()
        row['__MONOTONIC_TIMESTAMP'] = '810000000'
        raw = json.dumps(row)
        self.assertFalse(base.stage.journal_health(raw, row['_BOOT_ID'], 100, int(row['_PID']))['healthy'])
        self.assertTrue(base.stage.journal_health(raw, row['_BOOT_ID'], 100, int(row['_PID']), 800)['healthy'])
        self.assertFalse(base.stage.journal_health(raw, row['_BOOT_ID'], 100, int(row['_PID']), 820)['healthy'])

    def test_terminal_attempt_selected_by_receipt_without_relabeling(self):
        spec, files = base.fixture(); original = json.loads(files['recovery-evidence.json'])
        proof = {n.replace('readback-1-', 'readback-11-'): v for n, v in original.items()}
        c.recovery_evidence(c.encoded(proof), spec)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name, value in proof.items(): (root/name).write_bytes(c.encoded(value))
            (root/'readback-1-0-result.json').write_bytes(c.encoded({'spec_sha256': 'stale', 'result': {}}))
            reader = types.SimpleNamespace(private_file=lambda p, *args: p.read_bytes())
            self.assertEqual(c.select_recovery(reader, root), proof)
            self.assertTrue((root/'readback-1-0-result.json').exists())
            for name, value in original.items():
                if name.startswith('readback-'): (root/name).write_bytes(c.encoded(value))
            with self.assertRaises(ValueError): c.select_recovery(reader, root)
        bad = copy.deepcopy(proof); bad['readback-11-1-result.json']['result']['phase'] = 'held'
        with self.assertRaises(ValueError): c.recovery_evidence(c.encoded(bad), spec)


if __name__ == '__main__':
    unittest.main()
