#!/usr/bin/python3
"""Offline bundle integrity, one-shot execution and partial-result retention."""
import importlib.util
import io
import base64
import socket
import struct
import subprocess
import json
import os
from pathlib import Path
import tarfile
import tempfile
import time
import types
import copy
import unittest
from unittest.mock import Mock, patch
from contextlib import ExitStack

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('client_acceptance', ROOT/'scripts/run-client-acceptance.py')
c = importlib.util.module_from_spec(spec); spec.loader.exec_module(c)


class ClientAcceptanceTests(unittest.TestCase):
    def test_boot_observation_seals_flat_client_bundle_and_rejects_invalid_persistence(self):
        def load(path):
            spec=importlib.util.spec_from_file_location(path.stem.replace('-','_'),path)
            value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value
        fixtures=load(ROOT/'tests/test_production_transition.py')
        boot=load(ROOT/'scripts/run-production-boot.py')
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);folder,bundle,digest=fixtures.Controller().fixture(root)
            old,prior=fixtures.controller.prepare(bundle,digest)
            baseline=json.loads(prior['baseline.json'])
            for name,member in fixtures.stage.CHANGES.items():
                baseline['files'][name].update(sha256=c.sha(prior[member]),base64=base64.b64encode(prior[member]).decode())
            baseline['boot_units']=dict.fromkeys(('gpsd.service','gpsd.socket','ntpsec.service','avahi-daemon.service','ntpleapfetch.timer'),{})
            baseline['rtc_commissioning']={'bundle_sha256':'a'*64,'result_sha256':'b'*64,'readback':{}}
            baseline['final_client_sha256']='c'*64
            files={n:(ROOT/path).read_bytes() for n,path in boot.PATHS.items()}
            files.update({n:prior[n] for n in boot.EXTRA});files['baseline.json']=c.encoded(baseline)
            old.update(purpose='production-boot',action='restart',operation_id='boot-fixture',stage='/var/lib/ntp-boot-boot-fixture',
                       rtc_persistence=True,start_before_epoch=old['expires_epoch']-900,
                       restart_sha256=digest,observation_sha256='d'*64,hardware_receipt_sha256='e'*64)
            old['members']={n:c.sha(raw) for n,raw in files.items()}
            files.update({'spec.json':c.encoded(old),'review.md':boot.review(old).encode()})
            bundle=folder/'production-boot.tar'
            with tarfile.open(bundle,'w') as archive:
                for name,raw in files.items():
                    item=tarfile.TarInfo(name);item.size=len(raw);archive.addfile(item,io.BytesIO(raw))
            bundle.chmod(0o600);digest=c.sha(bundle.read_bytes())
            for n in ('spec.json','review.md'):(folder/n).write_bytes(files[n])
            measurement=fixtures.peers(['a','b','c'])
            measurement['system']={'leap':0,'stratum':1,'refid':'PPS','offset':0.01}
            for row in measurement['peers']:row['variables'].update(reach=255,jitter=0.01,ntscookies=8)
            epoch=int(time.time());state={'phase':'monitoring','boot_id':'old','new_boot_id':'new','drift_seed_observed':True,
                'rtc_after':{'accepted':True},'health':{'epoch':epoch,'pair':{'fixture':'same'},'measurement':measurement,
                'unit':{'ActiveState':'active','NRestarts':'0','UnitFileState':'enabled'}}}
            observation={k:copy.deepcopy(state[k]) for k in ('phase','new_boot_id','health')}
            def receipts(observation,persistence=None):
                values={'observe-6-outcome.json':{'bundle_sha256':digest,'state':observation,'timing_ready':True},
                    'observe-6-observe-result.json':observation,'observe-6-observe-transport.json':{'returncode':0},
                    'observe-6-execution.json':{'sha256':digest,'mode':'observe','epoch':epoch},
                    'apply-outcome.json':{'bundle_sha256':digest,'error':'SSH unavailable during reboot'},
                    'resume-1-outcome.json':{'bundle_sha256':digest,'state':state if persistence is None else persistence}}
                for name,value in values.items():
                    (folder/name).write_bytes(c.encoded(value));(folder/name).chmod(0o600)
            receipts(observation)
            args=types.SimpleNamespace(monitor_dir=folder,monitor_sha256=digest,observation=6,production_boot=True,
                native_discovery=True,paired=False,diagnostic=False,operation_id='postboot-client',
                source_ipv4='192.0.2.10',output=root/'client')
            sealed=c.seal(args);spec,parts=c.prepare(Path(sealed['bundle']),sealed['sha256'])
            self.assertEqual(spec['monitor_sha256'],digest)
            self.assertEqual(spec['observation_number'],6)
            self.assertFalse(any(name.endswith('.tar') for name in parts))
            for fault in ('old_boot','other_boot','drift','rtc','disabled'):
                changed=copy.deepcopy(observation);persistence=copy.deepcopy(state)
                if fault=='old_boot':changed['new_boot_id']='old'
                if fault=='other_boot':changed['new_boot_id']='other'
                if fault=='drift':persistence['drift_seed_observed']=False
                if fault=='rtc':persistence['rtc_after']['accepted']=False
                if fault=='disabled':changed['health']['unit']['UnitFileState']='disabled'
                receipts(changed,persistence)
                with self.subTest(fault=fault),self.assertRaisesRegex(ValueError,'new-boot persistence'):
                    c.transition_observation(args)

    def test_seal_from_real_transition_archive_and_reject_invalid_observations(self):
        loader=importlib.util.spec_from_file_location('transition_fixtures',ROOT/'tests/test_production_transition.py')
        fixtures=importlib.util.module_from_spec(loader);loader.loader.exec_module(fixtures)
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);folder,bundle,digest=fixtures.Controller().fixture(root)
            measurement=fixtures.peers(['a','b','c'])
            measurement['system']={'leap':0,'stratum':1,'refid':'PPS','offset':0.01}
            for row in measurement['peers']:row['variables'].update(reach=255,jitter=0.01,ntscookies=8)
            epoch=int(time.time())
            health={'epoch':epoch,'pair':{'fixture':'same'},'unit':{'ActiveState':'active','NRestarts':'0'},'measurement':measurement}
            state={'phase':'monitoring','health':health}
            values={'observe-10-outcome.json':{'bundle_sha256':digest,'state':state,'timing_ready':True},
                    'observe-10-result.json':state,'observe-10-transport.json':{'returncode':0},
                    'observe-10-execution.json':{'sha256':digest,'mode':'observe','epoch':epoch},
                    'apply-outcome.json':{'bundle_sha256':digest,'state':state}}
            def write(rows):
                for name,value in rows.items():
                    (folder/name).write_bytes(c.encoded(value));(folder/name).chmod(0o600)
            write(values)
            args=types.SimpleNamespace(monitor_dir=folder,monitor_sha256=digest,observation=10,
                production_transition=True,native_discovery=True,paired=False,diagnostic=False,
                operation_id='native-transition-fixture',source_ipv4='192.0.2.10',output=root/'client')
            sealed=c.seal(args)
            accepted,files=c.prepare(Path(sealed['bundle']),sealed['sha256'])
            self.assertEqual(accepted['monitor_sha256'],digest)
            self.assertEqual(accepted['observation_sha256'],c.sha(c.encoded(values['observe-10-outcome.json'])))
            self.assertEqual(set(files),set(c.PATHS)|{'spec.json','review.md'})
            pending=copy.deepcopy(values['apply-outcome.json'])
            pending['state']={'phase':'acquiring'}
            write({'apply-outcome.json':pending,'resume-1-outcome.json':values['apply-outcome.json']})
            self.assertEqual(c.transition_observation(args)[0]['hostname'],accepted['hostname'])
            (folder/'resume-1-outcome.json').unlink();write(values)
            for fault in ('transport','receipt','handoff','quality','future','stale','restart'):
                rows=copy.deepcopy(values)
                if fault=='transport':rows['observe-10-transport.json']['returncode']=1
                if fault=='receipt':rows['observe-10-outcome.json']['bundle_sha256']='0'*64
                if fault=='handoff':rows['apply-outcome.json']=copy.deepcopy(rows['apply-outcome.json']);rows['apply-outcome.json']['state']['health']['pair']={'fixture':'other'}
                if fault=='quality':rows['observe-10-result.json']['health']['measurement']['system']['offset']=10
                if fault=='future':rows['observe-10-execution.json']['epoch']=epoch+60
                if fault=='stale':rows['observe-10-result.json']['health']['epoch']=epoch-86401
                if fault=='restart':rows['observe-10-result.json']['health']['unit']['NRestarts']='1'
                write(rows)
                with self.subTest(fault=fault),self.assertRaisesRegex(ValueError,'fresh ready'):
                    c.transition_observation(args)

    def test_real_native_acceptance_and_rejections(self):
        loader = importlib.util.spec_from_file_location('dns_fixtures', ROOT/'tests/test_mdns_diagnostic.py')
        fixtures = importlib.util.module_from_spec(loader); loader.loader.exec_module(fixtures)
        client = c.module((ROOT/'scripts/check-time-client.py').read_bytes())
        native = c.module((ROOT/'scripts/compare-mdns.py').read_bytes())
        self.spec.update(purpose='client-native-discovery', source_ipv4='192.0.2.10')
        self.files['spec.json'] = c.encoded(self.spec)
        self.files['review.md'] = c.review(self.spec).encode(); self.pack()

        class NtpSocket:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def settimeout(self, timeout): pass
            def connect(self, endpoint): self.endpoint = endpoint
            def getsockname(self): return ('192.0.2.10' if ':' not in self.endpoint[0] else '2001:db8::10', 40000)
            def send(self, packet): self.packet = packet
            def recv(self, size):
                if len(self.packet) == 12: raise socket.timeout()
                reply = bytearray(48); reply[0] = 0x24; reply[1] = 1; reply[12:16] = b'PPS\0'
                reply[24:32] = self.packet[40:48]
                reply[32:40] = reply[40:48] = struct.pack('!II', int(time.time())+2208988800, 0)
                return bytes(reply)

        for scenario in ('pass', 'missing_mapping', 'wrong_source', 'wrong_query', 'incomplete', 'native_timeout'):
            with self.subTest(scenario=scenario):
                folder = self.root/scenario; folder.mkdir(mode=0o700)
                bundle = folder/'client-native-discovery.tar'; bundle.write_bytes(self.bundle.read_bytes()); bundle.chmod(0o600)
                for name in ('spec.json', 'review.md'):
                    (folder/name).write_bytes(self.files[name]); (folder/name).chmod(0o600)
                args = types.SimpleNamespace(bundle=bundle, sha256=c.sha(bundle.read_bytes()))
                q = native['queries'](self.spec, client)
                for query in q: query['socket_address'] = ['192.0.2.10', 45000]
                result = {'completed': scenario != 'incomplete', 'queries': q, 'replies': [
                    {'source': ['192.0.2.1', 5353], 'base64': base64.b64encode(fixtures.packet()).decode()}]}
                if scenario == 'missing_mapping': result['replies'] = []
                if scenario == 'wrong_source': q[0]['socket_address'][0] = '192.0.2.11'
                if scenario == 'wrong_query': q[0]['query_base64'] = 'AAAA'
                def run(argv, stdout, stderr, **kwargs):
                    if scenario == 'native_timeout':
                        stdout.write(b'partial'); raise subprocess.TimeoutExpired(argv, 20)
                    stdout.write(json.dumps(result).encode()); return subprocess.CompletedProcess(argv, 0)
                with ExitStack() as stack:
                    stack.enter_context(patch.object(socket, 'socket', side_effect=lambda *args: NtpSocket()))
                    stack.enter_context(patch('shutil.which', return_value='/windows/powershell.exe'))
                    stack.enter_context(patch.object(subprocess, 'run', side_effect=run))
                    outcome = c.execute(args)
                self.assertEqual(outcome['client_accepted'], scenario == 'pass')
                self.assertFalse(outcome['production_accepted'])
                self.assertTrue(outcome['checks']['ipv4']); self.assertTrue(outcome['checks']['ipv6'])
                self.assertIn('windows', outcome['observations'])
                self.assertEqual(json.loads((folder/'result.json').read_text()), json.loads(json.dumps(outcome)))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        files = {n: (ROOT/path).read_bytes() for n, path in c.PATHS.items()}
        self.spec = {'schema': 1, 'purpose': 'client-acceptance', 'operation_id': 'client-fixture',
                     'hostname': 'fixture', 'endpoints': ['192.0.2.1', '2001:db8::1'],
                     'monitor_sha256': 'a'*64, 'prepared_epoch': int(time.time()),
                     'expires_epoch': int(time.time())+3600, 'members': {n: c.sha(v) for n, v in files.items()}}
        files.update({'spec.json': c.encoded(self.spec), 'review.md': c.review(self.spec).encode()})
        self.files = files; self.bundle = self.root/'client-acceptance.tar'
        self.pack()
        for n in ('spec.json', 'review.md'):
            (self.root/n).write_bytes(files[n]); (self.root/n).chmod(0o600)
        self.args = types.SimpleNamespace(bundle=self.bundle, sha256=c.sha(self.bundle.read_bytes()))

    def pack(self):
        with tarfile.open(self.bundle, 'w') as archive:
            for name, raw in self.files.items():
                item = tarfile.TarInfo(name); item.size = len(raw); archive.addfile(item, io.BytesIO(raw))
        self.bundle.chmod(0o600)

    def test_real_prepare_and_digest_drift(self):
        self.assertEqual(c.prepare(self.bundle, self.args.sha256)[0], self.spec)
        with self.assertRaisesRegex(ValueError, 'digest'): c.prepare(self.bundle, 'b'*64)
        (self.root/'review.md').write_text('changed')
        with self.assertRaisesRegex(ValueError, 'local review'): c.prepare(self.bundle, self.args.sha256)

    def test_source_drift_and_expiry(self):
        self.files['client.py'] += b'\n'
        self.spec['members']['client.py'] = c.sha(self.files['client.py'])
        self.files['spec.json'] = c.encoded(self.spec); self.pack()
        with self.assertRaisesRegex(ValueError, 'source drift'): c.prepare(self.bundle, c.sha(self.bundle.read_bytes()))
        self.files['client.py'] = (ROOT/'scripts/check-time-client.py').read_bytes()
        self.spec['members']['client.py'] = c.sha(self.files['client.py'])
        self.spec['expires_epoch'] = int(time.time())-1
        self.files['spec.json'] = c.encoded(self.spec); self.files['review.md'] = c.review(self.spec).encode(); self.pack()
        for n in ('spec.json', 'review.md'): (self.root/n).write_bytes(self.files[n])
        with self.assertRaisesRegex(ValueError, 'expired'): c.prepare(self.bundle, c.sha(self.bundle.read_bytes()))

    def test_partial_capture_and_no_replay(self):
        network = {'client_ntp': Mock(side_effect=[{'stratum': 1, 'queries_denied': True}, TimeoutError('IPv6 timeout')]), 'browse': Mock()}
        with patch.object(c, 'module', return_value=network):
            result = c.execute(self.args)
            self.assertFalse(result['client_accepted'])
            self.assertEqual(result['checks'], {'ipv4': True})
            network['browse'].assert_not_called()
            with self.assertRaises(FileExistsError): c.execute(self.args)
            self.assertEqual(network['client_ntp'].call_count, 2)
        self.assertEqual(json.loads((self.root/'result.json').read_text()), result)

    def test_success_keeps_production_and_accuracy_unaccepted(self):
        network = {'client_ntp': Mock(return_value={'stratum': 1, 'queries_denied': True}), 'browse': Mock(return_value={'matched': True})}
        with patch.object(c, 'module', return_value=network): result = c.execute(self.args)
        self.assertTrue(result['client_accepted']); self.assertFalse(result['production_accepted'])
        self.assertFalse(result['absolute_accuracy_accepted'])
        self.assertEqual(network['client_ntp'].call_args_list[0].args, ('192.0.2.1',))
        self.assertEqual(network['client_ntp'].call_args_list[1].args, ('2001:db8::1',))
        self.assertEqual((self.root/'result.json').stat().st_mode & 0o777, 0o600)

    def test_timeout_retains_hold(self):
        network = {'client_ntp': Mock(side_effect=TimeoutError('client capture exceeded 60 seconds'))}
        with patch.object(c, 'module', return_value=network): result = c.execute(self.args)
        self.assertFalse(result['client_accepted']); self.assertIn('60 seconds', result['error'])

    def test_diagnostic_dispatch_never_calls_ntp_or_accepts_client(self):
        self.spec['purpose'] = 'mdns-diagnostic'
        self.files['spec.json'] = c.encoded(self.spec)
        self.files['review.md'] = c.review(self.spec).encode(); self.pack()
        for n in ('spec.json', 'review.md'): (self.root/n).write_bytes(self.files[n])
        self.args.sha256 = c.sha(self.bundle.read_bytes())
        client = {'client_ntp': Mock(side_effect=AssertionError('NTP forbidden'))}
        def capture(spec, parser, output):
            output['mdns'] = {'replies': [{'base64': 'retained'}]}
            raise TimeoutError('total diagnostic bound')
        with patch.object(c, 'module', side_effect=[client, {'capture': capture}]): result = c.execute(self.args)
        client['client_ntp'].assert_not_called()
        self.assertFalse(result['client_accepted']); self.assertFalse(result['production_accepted'])
        self.assertIn('mdns', result['observations']); self.assertIn('error', result)


if __name__ == '__main__': unittest.main()
