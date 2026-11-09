#!/usr/bin/python3
"""Offline contracts for the actual bounded observation executor; no target contact."""
import importlib.util
import copy
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
def load(path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
r = load(ROOT/'scripts/observe-service-window.py')
h = load(ROOT/'scripts/run-production-inspection.py')
c = load(ROOT/'scripts/check-time-client.py')


class Observation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        shutil.copy2(ROOT/'scripts/run-production-inspection.py', self.root/'helper.py')

    def rows(self):
        return [{'due_monotonic': k*300, 'streams': {s: {'recorded': True,
                 'start_monotonic': k*300, 'complete': True} for s in r.STREAMS}}
                for k in range(r.SLOTS)]

    def test_full_window(self):
        self.assertTrue(all(v['completeness_pass'] for v in r.summarize(self.rows())['streams'].values()))

    def test_protected_binary_above_old_read_limit(self):
        path = self.root/'installed-binary'
        raw = bytes(range(256))*8192
        path.write_bytes(raw)
        self.assertEqual(r.protected_hash(path), r.digest(raw))

    def test_protected_oversized_file_names_path(self):
        path = self.root/'oversized'
        with path.open('wb') as stream: stream.truncate(r.PROTECTED_FILE_CAP+1)
        with self.assertRaisesRegex(ValueError, 'oversized.*64 MiB'):
            r.protected_hash(path)

    def test_protected_hash_rejects_symlink(self):
        path = self.root/'original'; path.write_bytes(b'content')
        link = self.root/'link'; link.symlink_to(path)
        with self.assertRaisesRegex(ValueError, 'protected file .*link'):
            r.protected_hash(link)

    def test_protected_hash_rejects_directory(self):
        with self.assertRaisesRegex(ValueError, 'protected file'):
            r.protected_hash(self.root)

    def test_protected_hash_rejects_change_during_read(self):
        path = self.root/'changing'; path.write_bytes(b'content')
        before = path.stat()
        after = types.SimpleNamespace(**{k:getattr(before,k) for k in
            ('st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns')})
        after.st_mtime_ns += 1
        with patch.object(r.os, 'fstat', side_effect=[before,after]):
            with self.assertRaisesRegex(ValueError, 'changing.*changed during read'):
                r.protected_hash(path)

    def test_missing_stream_at_boundary_fails(self):
        rows = self.rows()
        rows[-1]['streams']['node']['recorded'] = False
        self.assertFalse(r.summarize(rows)['streams']['node']['completeness_pass'])

    def test_five_separated_missing_slots_allowed(self):
        rows = self.rows()
        for k in (20,40,60,80,100): rows[k] = dict(rows[k], missing=True)
        self.assertEqual(r.summarize(rows)['streams']['node']['on_time'],572)
        self.assertTrue(r.summarize(rows)['streams']['node']['completeness_pass'])

    def test_six_missing_fails(self):
        rows = self.rows()
        for k in (20,40,60,80,100,120): rows[k] = dict(rows[k], missing=True)
        self.assertFalse(r.summarize(rows)['streams']['node']['completeness_pass'])

    def test_adjacent_missing_fails_gap(self):
        rows = self.rows(); rows[20]['missing'] = rows[21]['missing'] = True
        self.assertEqual(r.summarize(rows)['streams']['node']['max_gap'],900)
        self.assertFalse(r.summarize(rows)['streams']['node']['completeness_pass'])

    def test_boundary_missing_fails(self):
        for k in (0,576):
            rows = self.rows(); rows[k]['missing'] = True
            self.assertFalse(r.summarize(rows)['streams']['node']['completeness_pass'])

    def test_failed_client_response_is_recorded_evidence(self):
        rows = self.rows(); rows[10]['streams']['client4']['complete'] = False
        self.assertEqual(r.summarize(rows)['streams']['client4']['on_time'],577)
        self.assertIn('requires review',r.summarize(rows)['acceptance'])

    def test_late_and_future_records_not_on_time(self):
        rows = self.rows()
        rows[5]['streams']['node']['start_monotonic'] += 61
        rows[10]['streams']['node']['start_monotonic'] -= 1
        self.assertEqual(r.summarize(rows)['streams']['node']['on_time'],575)

    def test_duplicate_remote_record_rejected(self):
        with self.assertRaises(ValueError): r.parse_remote('{"key":"complete","data":true}\n'*2)

    def test_command_names_do_not_collide_with_observation_records(self):
        output = io.StringIO()
        commands = {name: [sys.executable, '-c', 'print("local output")']
                    for name in ('capacity', 'identity', 'complete')}
        with contextlib.redirect_stdout(output):
            r.emit('capacity', {'bytes': 'root', 'inodes': 'root'})
            r.emit('identity', {'host': 'local'})
            r.emit_command_records(commands, lambda argv: subprocess.check_output(argv, text=True))
            r.emit('complete', True)
        parsed = r.parse_remote(output.getvalue())
        self.assertEqual(parsed['capacity'], {'bytes': 'root', 'inodes': 'root'})
        for name in commands:
            self.assertEqual(parsed['passive_commands.' + name], 'local output\n')
        self.assertIs(parsed['complete'], True)

    def test_command_failure_preserves_completed_records(self):
        output = io.StringIO()
        commands = {'capacity': [sys.executable, '-c', 'print("local output")'],
                    'later': [sys.executable, '-c', 'raise SystemExit(7)']}
        with contextlib.redirect_stdout(output), self.assertRaises(subprocess.CalledProcessError):
            r.emit_command_records(commands, lambda argv: subprocess.check_output(argv, text=True))
        self.assertEqual(r.parse_remote(output.getvalue()), {'passive_commands.capacity': 'local output\n'})

    def test_partial_subprocess_failure_is_preserved(self):
        value = r.stream_record(self.root,self.root,'failed',
              [sys.executable,'-c','import sys;print("before failure",flush=True);sys.stderr.write("reason");sys.exit(7)'],None,2,1024)
        self.assertEqual(value['returncode'],7)
        self.assertIn('before failure',(self.root/'failed.stdout').read_text())
        self.assertEqual((self.root/'failed.stderr').read_text(),'reason')
        self.assertTrue((self.root/'failed.result.json').is_file())

    def test_timeout_retains_partial_output(self):
        value = r.stream_record(self.root,self.root,'timeout',
              [sys.executable,'-c','import time;print("partial",flush=True);time.sleep(30)'],None,.15,1024)
        self.assertIn('deadline',value['error'])
        self.assertIn('partial',(self.root/'timeout.stdout').read_text())

    def test_output_limit_preserves_bounded_prefix(self):
        value = r.stream_record(self.root,self.root,'limit',[sys.executable,'-c','print("x"*8192)'],None,2,100)
        self.assertIn('bound',value['error'])
        self.assertEqual((self.root/'limit.stdout').stat().st_size,100)

    def test_one_use_launch(self):
        r.write_new(self.root/'already.launch.json',{})
        with patch.object(h.subprocess,'Popen',side_effect=AssertionError('must not launch')):
            with self.assertRaises(FileExistsError):
                r.stream_record(self.root,self.root,'already',[sys.executable,'-c','pass'],None,2,100)

    def test_sink_interruption_preserves_and_kills(self):
        seen=[]
        def sink(stream,raw):
            seen.append(raw); raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            h.bounded([sys.executable,'-c','import time;print("partial",flush=True);time.sleep(30)'],timeout=2,sink=sink)
        self.assertIn(b'partial',b''.join(seen))

    def test_private_output_rejects_links_and_public_directory(self):
        other = self.root/'public'; other.mkdir(mode=0o755)
        with self.assertRaises(ValueError): r.private(other)
        link=self.root/'link';link.symlink_to(self.root,target_is_directory=True)
        with self.assertRaises(ValueError): r.private(link)

    def test_regular_client_probe_does_not_send_admin_request(self):
        class Socket:
            sent=[]
            def __enter__(self):return self
            def __exit__(self,*a):pass
            def settimeout(self,*a):pass
            def connect(self,*a):pass
            def send(self,raw):self.sent.append(raw)
            def recv(self,*a):return b'reply'
            def getsockname(self):return ('192.0.2.3',45000)
        sock=Socket()
        with patch.object(c.socket,'socket',return_value=sock),patch.object(c,'ntp_response',return_value={'leap':0}):
            c.client_ntp('192.0.2.5',administrative=False)
        self.assertEqual(len(sock.sent),1)

    def test_manifest_tamper_rejected(self):
        (self.root/'manifest.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'manifest approval'):
            r.check(self.root,'0'*64)

    def test_non_executable_manifest_rejected(self):
        raw=r.encoded({'execution_ready':False});(self.root/'manifest.json').write_bytes(raw)
        with self.assertRaisesRegex(ValueError,'not executable'):r.check(self.root,r.digest(raw))


    def test_unresolved_entry_cannot_start(self):
        import time
        now=time.time()
        r.write_new(self.root/'execution.json',{'manifest_sha256':'approved','epoch':now})
        r.write_new(self.root/'entry.json',{'manifest_sha256':'approved','epoch':now})
        raw=(self.root/'entry.json').read_bytes()
        grant=self.root/'grant.json'
        r.write_new(grant,{'manifest_sha256':'approved','entry_sha256':r.digest(raw),'checks':{}})
        spec={'not_after_epoch':now+100,'controller_hostname':r.socket.gethostname(),
              'windows':{'executable':sys.executable},'boundary_commands':[]}
        with patch.object(r,'check',return_value=spec),patch.object(r,'fingerprint'), \
             patch.object(r,'parallel_capture',side_effect=AssertionError('no contact')):
            with self.assertRaisesRegex(ValueError,'unresolved entry'):
                r.execute(self.root,self.root,'approved','observe',grant)
        self.assertFalse((self.root/'start.json').exists())

    def test_master_inspection_cannot_start_observation(self):
        with patch.object(r, 'check', return_value={'purpose':'master-selection'}), \
             patch.object(r, 'fingerprint', side_effect=AssertionError('scope first')):
            for phase in ('entry','observe'):
                with self.assertRaisesRegex(ValueError, 'outside sealed scope'):
                    r.execute(self.root,self.root,'approved',phase,None)

    def test_inspection_captures_only_master_once_without_entry(self):
        import time
        output = self.root/'output'; output.mkdir(mode=0o700)
        spec = {'purpose':'master-selection', 'not_after_epoch':time.time()+100,
                'controller_hostname':r.socket.gethostname(),'boundary_commands':[]}
        row = {'complete':True,'data':{'config':{'selected':{}}}}
        with patch.object(r,'check',return_value=spec), patch.object(r,'fingerprint'), \
             patch.object(r,'capture',return_value=row) as capture, \
             patch.object(r,'boundary',side_effect=AssertionError('no boundary probes')):
            r.execute(self.root,output,'approved','inspect-master',None)
            self.assertEqual(capture.call_count,1)
            self.assertEqual(capture.call_args.args[4:6],('master',False))
            with self.assertRaisesRegex(ValueError,'empty output'):
                r.execute(self.root,output,'approved','inspect-master',None)
            self.assertEqual(capture.call_count,1)
        self.assertFalse((output/'entry.json').exists())
        self.assertFalse((output/'start.json').exists())
        self.assertIs(json.loads((output/'inspection.json').read_text())['entry_accepted'],False)

    def test_rrd_membership_requires_available_inventory(self):
        graph = {'files': [{'filename': 'b'}, {'filename': 'a'}],
                 'missing': False, 'missing_expected_files': []}
        data = {'collection': {'rrd': {'aligned_end': 1800, 'resolution': 300,
                'data': {'j2': {'cpu': graph}}}}}
        self.assertEqual(r.rrd_membership(data), {'j2/cpu': ['a', 'b']})
        for envelope in ({}, {'data': {}}, {'data': {'j2': 1}},
                         {'data': {'j2': {'cpu': {'files': []}}}},
                         {'data': {'j2': {'cpu': dict(graph, missing_expected_files=['c'])}}},
                         {'data': {'j2': {'cpu': {'files': [{'filename': 'a'}]*2}}}}):
            with self.subTest(envelope=envelope), self.assertRaises(ValueError):
                r.rrd_membership({'collection': {'rrd': envelope}})

    @unittest.skipUnless(os.environ.get('OBS09_NATIVE_IMAGE'), 'optional installed Munin parser')
    def test_native_storable_multigraph_selection(self):
        # Native parser produces the tree: do not hand-build its nested hash.
        producer = r"""
use Munin::Master::Utils; use Storable qw(nstore_fd);
my @lines = ("[j2;j2]", "cpu.user.label user", "cpu.user.state ok",
             "diskstats_iops.mmcblk0.reads.label reads",
             "diskstats_iops.mmcblk0.reads.state ok");
my $d = Munin::Master::Utils::munin_parse_config(\@lines); nstore_fd($d, \*STDOUT);
"""
        program = """
import json, subprocess
p = json.loads(input())
raw = subprocess.check_output(['perl','-e',p['producer']])
for mode in ('config','limits'):
 result = json.loads(subprocess.check_output(['perl','-e',p['decoder'],mode,
     json.dumps([['j2','cpu'],['j2','diskstats_iops.mmcblk0'],['j2','absent']])],input=raw))
 field = 'label' if mode == 'config' else 'state'
 assert result['j2/cpu']['user'][field] == ('user' if mode == 'config' else 'ok')
 assert result['j2/diskstats_iops.mmcblk0']['reads'][field] == ('reads' if mode == 'config' else 'ok')
 assert result['j2/absent'] == {'missing':True}
print('native Storable config/limits: flat and multigraph selection passed')
"""
        command = ['podman','run','--rm','--pull=never','--network=none','--read-only',
                   '--cap-drop=all','--security-opt=no-new-privileges','-i',
                   '--entrypoint','/usr/bin/python3',os.environ['OBS09_NATIVE_IMAGE'],'-c',program]
        result = subprocess.run(command,input=json.dumps(dict(producer=producer,decoder=r.LIMITS_DECODER)),
                                text=True,capture_output=True,timeout=60)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)


@unittest.skipUnless(os.environ.get('OBS09_RETAINED_RUN'), 'optional private retained captures')
class RetainedCaptures(unittest.TestCase):
    """Exercise actual predicates without launching commands or changing old records."""
    @classmethod
    def setUpClass(cls):
        cls.capture_dir = Path(os.environ['OBS09_RETAINED_RUN'])
        cls.bundle = Path(os.environ['OBS09_RETAINED_BUNDLE'])
        cls.spec = json.loads((cls.bundle/'spec.json').read_text())
        cls.rows = {}
        for role in r.STREAMS:
            meta = json.loads((cls.capture_dir/('entry-'+role+'.json')).read_text())
            raw = (cls.capture_dir/('entry-'+role+'.stdout')).read_text()
            meta['data'] = r.parse_remote(raw) if role in ('node','master') else json.loads(raw)
            cls.rows[role] = meta
        cls.reference = {role: row['data'] for role, row in cls.rows.items()}

    def test_complete_entry_and_continuity_schemas(self):
        r.require_entry(self.rows, self.spec)
        r.require_continuity(self.rows, self.reference)

    def test_entry_rejects_missing_stream_check_graph_and_inventory(self):
        for mutate in (lambda x: x.pop('client6'),
                       lambda x: x['node']['data']['time']['checks'].pop('finite'),
                       lambda x: x['node']['data']['time']['checks'].update(offset=False),
                       lambda x: x['master']['data']['collection']['rrd']['data'].pop('J1-SVMF')):
            rows = copy.deepcopy(self.rows); mutate(rows)
            with self.assertRaises(ValueError): r.require_entry(rows, self.spec)

    def test_continuity_rejects_each_changed_input(self):
        def service(rows):
            rows['node']['data']['services']['timeservice.service']['stdout'] += '\nInvocationID=changed\n'
        for mutate in (lambda x: x['node']['data']['identity'].update(boot='changed'),
                       lambda x: x['master']['data']['hashes'].update(extra='changed'),
                       lambda x: x['master']['data']['config']['selected'].update(extra={}),
                       lambda x: x['master']['data']['collection']['rrd']['data'].pop('J1-SVMF'),
                       lambda x: x['client4']['data'].update(local_address='changed'), service,
                       lambda x: x['node'].update(returncode=255),
                       lambda x: x['master'].update(complete=False)):
            rows = copy.deepcopy(self.rows); mutate(rows)
            with self.assertRaises(ValueError): r.require_continuity(rows, self.reference)

    def test_start_predicates_without_writing_grant_or_start(self):
        receipt = json.loads((self.capture_dir/'execution.json').read_text())
        now = max(row['finished_epoch'] for row in self.rows.values()) + 1
        expected = receipt['manifest_sha256']
        entry = {'epoch': now, 'manifest_sha256': expected, 'streams': self.rows}
        raw = r.encoded(entry)
        names = ('identity_configuration wifi_hardware native_time master_fields_freshness_limits '
                 'jobs_leap_deadline client_dns_discovery webmin_both_families controller_capacity_awake '
                 'journal_dispositions obs02_storage_floors thermal_trip_policy').split()
        # Only predicate mechanics: these booleans are not an entry acceptance or authorization.
        grant = dict(manifest_sha256=expected, entry_sha256=r.digest(raw), operator='Aaron',
                     epoch=now, checks=dict.fromkeys(names, True),
                     obs05_due_epoch=now+1000, obs05_followup_epoch=now+87400)
        r.require_start_grant(grant, entry, receipt, expected, raw, now)
        for name in names:
            bad = copy.deepcopy(grant); bad['checks'][name] = False
            with self.assertRaisesRegex(ValueError, 'unresolved entry'):
                r.require_start_grant(bad, entry, receipt, expected, raw, now)
        for changes in ({'entry_sha256': 'changed'}, {'manifest_sha256': 'changed'},
                        {'operator': 'other'}, {'epoch': now+1}, {'obs05_due_epoch': now},
                        {'obs05_followup_epoch': now}, {'obs05_due_epoch': float('nan')}):
            with self.assertRaises(ValueError):
                r.require_start_grant(dict(grant, **changes), entry, receipt, expected, raw, now)
        with self.assertRaisesRegex(ValueError, 'stale'):
            r.require_start_grant(grant, entry, receipt, expected, raw, now+1801)

    def test_all_boundary_predicates_from_retained_results(self):
        def retained(bundle, output, name, *args):
            result = json.loads((self.capture_dir/(name+'.result.json')).read_text())
            result['stdout'] = (self.capture_dir/(name+'.stdout')).read_text(errors='replace')
            return result
        with patch.object(r, 'stream_record', side_effect=retained):
            r.boundary(self.bundle, self.spec, self.capture_dir, 'entry')


if __name__ == '__main__': unittest.main()
