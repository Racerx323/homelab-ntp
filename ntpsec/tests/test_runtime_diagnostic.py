#!/usr/bin/python3
"""Offline diagnostic scope, evidence, observer and mandatory-recovery tests."""
import base64
import copy
import ctypes
import importlib.util
import json
import os
from pathlib import Path
import socket
import struct
import tempfile
import time
import types
import unittest
from unittest.mock import Mock,patch

ROOT=Path(__file__).resolve().parents[1]


def load(path):
    spec=importlib.util.spec_from_file_location(path.stem.replace('-','_'),path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


base=load(ROOT/'tests/test_service_cutover.py');c=base.c;stage=base.stage
d=load(ROOT/'scripts/runtime-diagnostic.py')


def fixture():
    spec,files=base.fixture();spec['purpose']='runtime-diagnostic'
    files['timeservice.service']=c.current_inputs(True)['timeservice.service']
    spec['recipe']['diagnostic']=json.loads(files['diagnostic-recipe.json'])
    recovery=json.loads(files['recovery-evidence.json'])
    old={k:spec[k] for k in ('hostname','boot_id','kernel','endpoints')}
    old['source_bundle_sha256']=recovery['terminal-receipt.json']['bundle_sha256']
    archived=base.acqtest.archive({'spec.json':c.encoded(old),'source-spec.json':c.encoded(recovery['spec.json'])})
    peers=[{'variables':{'srchost':name,'srcadr':address}} for name,address in
           zip(spec['recipe']['nts_servers'],spec['recipe']['diagnostic']['upstream_addresses'])]
    source=c.encoded({'last_measurement':{'measurement':{'peers':peers}}})
    report={'phase':'captured','source_preserved':True,'evidence':{'source-state.json':{
        'sha256':c.sha(source),'base64':base64.b64encode(source).decode()}}}
    digest=c.sha(c.encoded(old));report_digest=c.sha(c.encoded(report))
    response={'spec_sha256':digest,'result':report}
    proof={'archive':base64.b64encode(archived).decode(),'readback-1-0-result.json':response,
        'readback-1-1-result.json':copy.deepcopy(response),
        'acceptance.json':{'bundle_sha256':c.sha(archived),'report_sha256':report_digest,
                          'spec_sha256':digest,'state':'diagnostics_captured','time_service_accepted':False},
        'cleanup-0-result.json':{'spec_sha256':digest,'result':{
            'phase':'cleaned','report_sha256':report_digest,'evidence_preserved':True,'source_unchanged':True}}}
    files['diagnostic-evidence.json']=c.encoded(proof);base.bind(spec,files)
    return spec,files


class BindingTests(unittest.TestCase):
    def test_diagnostic_profile_and_retained_receipts(self):
        spec,files=fixture();c.validate(spec,files)
        self.assertIn('mandatory recovery',c.review(spec).lower())
        self.assertIn('No service acceptance',c.review(spec))

    def test_changed_evidence_endpoints_scope_and_bounds_rejected(self):
        for case in ('readback','source','receipt','cleanup','address','duration'):
            spec,files=fixture();proof=json.loads(files['diagnostic-evidence.json'])
            if case=='readback':proof['readback-1-1-result.json']['result']['phase']='held'
            if case=='source':proof['readback-1-0-result.json']['result']['source_preserved']=False
            if case=='receipt':proof['acceptance.json']['bundle_sha256']='f'*64
            if case=='cleanup':proof['cleanup-0-result.json']['result']['source_unchanged']=False
            if case in ('address','duration'):
                recipe=spec['recipe']['diagnostic']
                if case=='address':recipe['upstream_addresses'][0]='2606:4700:f1::2'
                else:recipe['observation_seconds']=901
                files['diagnostic-recipe.json']=c.encoded(recipe)
            files['diagnostic-evidence.json']=c.encoded(proof);base.bind(spec,files)
            with self.subTest(case=case),self.assertRaises(ValueError):c.validate(spec,files)

    def test_latest_diagnostic_preserves_retained_anchor(self):
        spec,files=fixture();raw=files['diagnostic-evidence.json']
        recovery=json.loads(files['recovery-evidence.json'])
        recovery['spec.json'].update(purpose='runtime-diagnostic',members={'diagnostic-evidence.json':c.sha(raw)})
        c.diagnostic_evidence(raw,spec,recovery)
        recovery['spec.json']['members']['diagnostic-evidence.json']='0'*64
        with self.assertRaises(ValueError):c.diagnostic_evidence(raw,spec,recovery)
        recovery['spec.json']['members']['diagnostic-evidence.json']=c.sha(raw)
        bad=copy.deepcopy(spec);bad['boot_id']='0'*36
        with self.assertRaises(ValueError):c.diagnostic_evidence(raw,bad,recovery)

    def test_receipt_requires_recovery_and_marks_partial_diagnostics(self):
        spec,_=fixture();state={'phase':'recovered','observation_completed':True,
            'diagnostic_samples':[{}],'packet_observation':{'complete':True},'diagnostic_statistics':{'loopstats':{}},
            'diagnostic_journal':{'complete':True}}
        receipt=c.terminal_receipt(spec,'a'*64,dict.fromkeys(spec['endpoints'],state))
        self.assertTrue(receipt['diagnostic_accepted']);self.assertFalse(receipt['time_service_accepted'])
        for key in ('observation_completed','diagnostic_samples','packet_observation','diagnostic_statistics','diagnostic_journal'):
            bad=dict(state);bad.pop(key)
            self.assertFalse(c.terminal_receipt(spec,'a'*64,dict.fromkeys(spec['endpoints'],bad))['diagnostic_accepted'])
        with self.assertRaises(ValueError):c.terminal_receipt(spec,'a'*64,dict.fromkeys(spec['endpoints'],{'phase':'accepted'}))


class PacketTests(unittest.TestCase):
    def frame(self,version=6,response=False):
        remote='2606:4700:f1::1' if version==6 else '192.0.2.1'
        local='2001:db8::1' if version==6 else '192.0.2.2'
        source,dest=(remote,local) if response else (local,remote)
        ntp=bytes([(4<<3)|(4 if response else 3),1])+bytes(22)+bytes.fromhex('1122334455667788')*3
        payload=struct.pack('!HHHH',123,123,56,0)+ntp
        if version==6:
            ip=struct.pack('!IHBB',6<<28,len(payload),17,64)+socket.inet_pton(socket.AF_INET6,source)+socket.inet_pton(socket.AF_INET6,dest)
            kind=0x86dd
        else:
            ip=struct.pack('!BBHHHBBH',0x45,0,20+len(payload),0,0,64,17,0)+socket.inet_aton(source)+socket.inet_aton(dest)
            kind=0x0800
        return bytes(12)+struct.pack('!H',kind)+ip+payload,remote

    def test_headers_only_both_directions_and_families(self):
        for version in (4,6):
            for response in (False,True):
                frame,remote=self.frame(version,response)
                row=d.packet(frame+b'SECRET_COOKIE',len(frame)+13,[remote])
                self.assertEqual(row['direction'],'response' if response else 'request')
                self.assertEqual(row['mode'],4 if response else 3)
                self.assertEqual(row['origin'],'1122334455667788')
                self.assertNotIn('SECRET',json.dumps(row))

    def test_scope_truncation_fragments_and_extension_headers(self):
        frame,remote=self.frame()
        self.assertIsNone(d.packet(frame,len(frame),['2001:db8::9']))
        for size in (0,13,30,61,len(frame)-1):self.assertIsNone(d.packet(frame[:size],len(frame),[remote]))
        changed=bytearray(frame);changed[20]=44
        self.assertIsNone(d.packet(changed,len(frame),[remote]))
        frame,remote=self.frame(4);changed=bytearray(frame);changed[20:22]=struct.pack('!H',0x2000)
        self.assertIsNone(d.packet(changed,len(frame),[remote]))

    def capture(self,root,limit=1,status=1):
        lib=Mock();lib.pcap_create.return_value=1
        for name in ('pcap_set_snaplen','pcap_set_promisc','pcap_set_timeout','pcap_set_buffer_size',
                     'pcap_activate','pcap_setnonblock','pcap_compile','pcap_setfilter','pcap_stats'):
            getattr(lib,name).return_value=0
        lib.pcap_datalink.return_value=1
        frame,remote=self.frame();header=d.Header(0,0,len(frame),len(frame));data=(ctypes.c_ubyte*len(frame)).from_buffer_copy(frame)
        def next_packet(handle,h,p):
            ctypes.cast(h,ctypes.POINTER(ctypes.POINTER(d.Header)))[0]=ctypes.pointer(header)
            ctypes.cast(p,ctypes.POINTER(ctypes.POINTER(ctypes.c_ubyte)))[0]=ctypes.cast(data,ctypes.POINTER(ctypes.c_ubyte))
            return status
        lib.pcap_next_ex.side_effect=next_packet
        info=types.SimpleNamespace(st_mode=0o40700,st_uid=0,st_gid=0)
        recipe={'upstream_addresses':[remote],'interface':'eth0','capture_seconds':1,'maximum_packets':limit}
        with patch.object(d,'library',return_value=lib),patch.object(d.os,'geteuid',return_value=0),patch.object(d.Path,'lstat',return_value=info),patch.object(d.signal,'signal'):
            if status<0:
                with self.assertRaises(ValueError):d.capture(root,recipe)
            else:d.capture(root,recipe)
        return lib,json.loads((root/'packet-report.json').read_text())

    def test_capacity_is_incomplete_and_capture_is_nonpromiscuous_filtered(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);lib,report=self.capture(root)
            self.assertTrue(report['capacity_reached']);self.assertFalse(report['complete'])
            lib.pcap_set_promisc.assert_called_once_with(1,0);lib.pcap_setfilter.assert_called_once();lib.pcap_close.assert_called_once()
            self.assertEqual(len(report['packets']),1);self.assertEqual((root/'packet-report.json').stat().st_mode&0o777,0o600)

    def test_capture_failure_retained_and_handle_closed(self):
        with tempfile.TemporaryDirectory() as name:
            lib,report=self.capture(Path(name),status=-1)
            self.assertEqual(report['phase'],'held');self.assertFalse(report['complete']);lib.pcap_close.assert_called_once()

    def test_real_libpcap_filter_offline_when_available(self):
        try:lib=d.library()
        except OSError:self.skipTest('local libpcap absent; target readiness is independently required')
        lib.pcap_open_dead.argtypes=[ctypes.c_int,ctypes.c_int];lib.pcap_open_dead.restype=ctypes.c_void_p
        lib.pcap_offline_filter.argtypes=[ctypes.POINTER(d.Program),ctypes.POINTER(d.Header),ctypes.POINTER(ctypes.c_ubyte)]
        lib.pcap_offline_filter.restype=ctypes.c_uint
        handle=lib.pcap_open_dead(1,128);self.assertTrue(handle);program=d.Program()
        frame,remote=self.frame();expression=('udp port 123 and host '+remote).encode()
        try:
            self.assertEqual(lib.pcap_compile(handle,ctypes.byref(program),expression,1,0xffffffff),0)
            for allowed in (True,False):
                value=frame if allowed else frame.replace(socket.inet_pton(socket.AF_INET6,remote),socket.inet_pton(socket.AF_INET6,'2001:db8::9'))
                header=d.Header(0,0,len(value),len(value));raw=(ctypes.c_ubyte*len(value)).from_buffer_copy(value)
                self.assertEqual(bool(lib.pcap_offline_filter(ctypes.byref(program),ctypes.byref(header),raw)),allowed)
        finally:lib.pcap_freecode(ctypes.byref(program));lib.pcap_close(handle)


class LifecycleTests(unittest.TestCase):
    def transaction(self,elapsed=100):
        tx=base.TransactionTests().transaction({'phase':'observing','supervisor_pid':100,
            'apply_monotonic':time.monotonic()-elapsed,'stable':0,'diagnostic_samples':[],
            'journal_cursor':'s=abc;i=1','early_ntpd':{'counters':{'nts_client_send':0}}})
        tx.s,tx.f=fixture();tx.network_observation=Mock(return_value={'addresses':[]})
        checks=dict.fromkeys(('bootstrap_stopped','pair_running','same_supervisor','no_restarts','no_overrides','credentials','journal_health','nts','offset','jitter'),True)
        measurement={'peers':[{'variables':{'srchost':tx.s['recipe']['nts_servers'][0],
            'srcadr':tx.s['recipe']['diagnostic']['upstream_addresses'][0]}}], 'counters':{'nts_client_send':1}}
        tx.measure.return_value={'checks':checks,'measurement':measurement};return tx

    def test_timing_success_before_settling_is_not_convergence(self):
        tx=self.transaction();self.assertTrue(tx.diagnostic_sample())
        self.assertEqual(tx.current['stable'],0)
        self.assertFalse(tx.current['diagnostic_samples'][0]['settling_window_elapsed'])
        tx.current['apply_monotonic']=time.monotonic()-650
        self.assertTrue(tx.diagnostic_sample());self.assertTrue(tx.diagnostic_sample());self.assertFalse(tx.diagnostic_sample())
        self.assertEqual(tx.current['stable'],3)

    def test_zero_nts_reach_or_startup_offset_is_observed_not_accepted(self):
        tx=self.transaction(650);tx.measure.return_value['checks'].update(nts=False,offset=False,jitter=False)
        self.assertTrue(tx.diagnostic_sample());self.assertEqual(tx.current['stable'],0)
        for mode in ('accept','probe'):
            with self.assertRaises(ValueError):getattr(tx,mode)(None) if mode=='accept' else tx.probe()

    def test_drift_restart_counter_reset_and_observer_failure_stop(self):
        for case in ('address','restart','counter','observer'):
            tx=self.transaction()
            if case=='address':tx.measure.return_value['measurement']['peers'][0]['variables']['srcadr']='2001:db8::1'
            elif case=='restart':tx.measure.return_value['checks']['no_restarts']=False
            elif case=='counter':tx.current['early_ntpd']['counters']['nts_client_send']=5
            else:tx.systemctl.return_value='inactive'
            with self.subTest(case=case),self.assertRaises(ValueError):tx.diagnostic_sample()

    def test_pending_setup_grace_and_retained_timeout(self):
        for elapsed,allowed in ((20,True),(61,False)):
            tx=self.transaction(elapsed)
            peer=tx.measure.return_value['measurement']['peers'][0]['variables']
            peer.update(srcadr=None,refid='NTS')
            if allowed:self.assertTrue(tx.diagnostic_sample())
            else:
                with self.assertRaisesRegex(ValueError,'setup deadline'):tx.diagnostic_sample()
            sample=tx.current['diagnostic_samples'][0]
            self.assertEqual(sample['pending_upstreams'],[peer])
            self.assertEqual('error' in sample,not allowed)
            self.assertEqual(tx.current['stable'],0)

    def test_rejecting_and_ancillary_failures_preserve_sample(self):
        for case in ('address','counter','network'):
            tx=self.transaction()
            if case=='address':tx.measure.return_value['measurement']['peers'][0]['variables']['srcadr']='2001:db8::1'
            elif case=='counter':tx.current['early_ntpd']['counters']['nts_client_send']=5
            else:tx.network_observation.side_effect=ValueError('network failed')
            with self.assertRaises(ValueError):tx.diagnostic_sample()
            self.assertEqual(len(tx.current['diagnostic_samples']),1)
            self.assertIn('error',tx.current['diagnostic_samples'][0])
            self.assertIn('measurement',tx.current['diagnostic_samples'][0]['result'])

    def test_journal_cursor_is_boot_bound_and_scopes_queries(self):
        tx=self.transaction()
        row={'__CURSOR':'s=abc;i=1','_BOOT_ID':tx.s['boot_id'].replace('-',''),
             '__MONOTONIC_TIMESTAMP':str(int(time.monotonic()*1_000_000))}
        tx.run=Mock(return_value=json.dumps(row))
        self.assertEqual(tx.journal_cursor(),row['__CURSOR'])
        self.assertIn('--lines=1',tx.run.call_args.args[0])
        self.assertIn('--after-cursor='+row['__CURSOR'],tx.journal_scope())
        for change in ({'__CURSOR':None},{'__CURSOR':'bad\nvalue'},{'_BOOT_ID':'0'*32},
                       {'__MONOTONIC_TIMESTAMP':'9999999999999999999'}):
            tx.run.return_value=json.dumps(dict(row,**change))
            with self.assertRaises(ValueError):tx.journal_cursor()
        tx.run.return_value=''
        with self.assertRaises(ValueError):tx.journal_cursor()
        tx.current.pop('journal_cursor')
        with self.assertRaises(ValueError):tx.journal_scope()

    def test_lifetime_and_sample_bounds(self):
        tx=self.transaction(901);self.assertFalse(tx.diagnostic_sample());tx.measure.assert_not_called()
        tx=self.transaction();tx.current['diagnostic_samples']=[{}]*30
        self.assertFalse(tx.diagnostic_sample());tx.measure.assert_not_called()

    def test_expired_command_budget_cannot_launch_another_query(self):
        tx=self.transaction();tx.command_deadline=time.monotonic()-1
        with patch.object(stage.subprocess,'run') as run,self.assertRaisesRegex(ValueError,'observation deadline'):
            tx.run(['ip','-json','address'])
        run.assert_not_called()

    def test_full_observation_log_does_not_block_recovery_commands(self):
        with tempfile.TemporaryDirectory() as name:
            tx=self.transaction();tx.root=Path(name)
            with (tx.root/'commands.jsonl').open('wb') as stream:stream.truncate(8*1024**2)
            fstat=os.fstat
            def owned(fd):
                info=fstat(fd)
                return types.SimpleNamespace(st_mode=info.st_mode,st_uid=0,st_gid=0,st_size=info.st_size,st_nlink=1)
            result=types.SimpleNamespace(returncode=0,stdout=b'ok',stderr=b'')
            with patch.object(stage.os,'fstat',side_effect=owned),patch.object(stage.subprocess,'run',return_value=result):
                with self.assertRaisesRegex(ValueError,'command journal'):tx.run(['/usr/bin/true'])
                tx.recovering=True
                self.assertEqual(tx.run(['/usr/bin/true']),'ok')
            self.assertEqual((tx.root/'commands.jsonl').stat().st_size,8*1024**2)
            self.assertIn('/usr/bin/true',(tx.root/'recovery-commands.jsonl').read_text())

    def test_worker_always_recovers_and_distinguishes_error(self):
        for fail in (False,True):
            tx=self.transaction();tx.recover=Mock();tx.diagnostic_sample=Mock(side_effect=ValueError('fixture') if fail else [False])
            tx.diagnose();tx.recover.assert_called_once()
            self.assertEqual(tx.current.get('observation_completed',False),not fail)
            self.assertEqual('diagnostic_error' in tx.current,fail)

    def test_apply_orders_observer_then_gate_then_bounded_worker(self):
        for failure in ('none','cursor','observer','gate'):
            tx=self.transaction();tx.current={'phase':'staged','created_directories':[],'installed':[]}
            tx.root=Path('/fixture');tx.replace=Mock();tx.recover=Mock();events=[]
            gate={'state':'failed' if failure=='gate' else 'passed','supervisor_pid':100}
            tx.h=types.SimpleNamespace(ancestors=Mock(),read=Mock(return_value=stage.encoded(gate)))
            tx.systemctl=Mock(side_effect=lambda *a:(events.append(a) or '100'))
            def observer():
                events.append(('observer',))
                if failure=='observer':raise ValueError('observer failed')
            tx.start_packet_capture=observer
            def cursor():
                events.append(('cursor',))
                if failure=='cursor':raise ValueError('cursor failed')
                return 's=abc;i=1'
            tx.journal_cursor=cursor
            tx.run=Mock(return_value=json.dumps({'system':{'leap':3},'counters':{'nts_client_send':0}}))
            with patch.dict(stage.DIRECTORIES,{},clear=True),patch.object(stage.Path,'exists',return_value=True),patch.object(stage.time,'sleep'):
                if failure!='none':
                    with self.assertRaises(ValueError):tx.apply()
                    tx.recover.assert_called_once_with(locked=True)
                    self.assertFalse(any('worker' in call.args[0] and 'diagnose' in call.args[0] for call in tx.run.call_args_list))
                else:
                    self.assertEqual(tx.apply()['phase'],'observing')
                    self.assertLess(events.index(('cursor',)),events.index(('observer',)))
                    self.assertLess(events.index(('observer',)),events.index(('start','timeservice.service')))
                    worker=tx.run.call_args.args[0]
                    self.assertIn('--property=RuntimeMaxSec=1200',worker)
                    self.assertTrue(any('ExecStopPost=' in a and a.endswith('worker recover') for a in worker))
                    self.assertEqual(worker[-1],'diagnose');tx.recover.assert_not_called()

    def test_packet_or_journal_evidence_failure_does_not_block_restoration(self):
        for fault in ('packet','journal'):
            with tempfile.TemporaryDirectory() as name:
                tx=self.transaction();tx.root=Path(name)
                tx.current.update(installed=[],created_directories=[])
                tx.command_deadline=time.monotonic()-1
                before={'files':{},'serial':{},'termios':'saved'}
                (tx.root/'packet-report.json').write_text('broken' if fault=='packet' else '{"complete":true}')
                tx.h=types.SimpleNamespace(read=lambda path,**kw:stage.encoded(before) if path.name=='before.json' else path.read_bytes())
                tx.a=types.SimpleNamespace(idle=Mock(),serial_identity=lambda:{},context=Mock());tx.alias={};tx.rf={}
                tx.systemctl=Mock(return_value='not-found')
                def run(argv,**kw):
                    if argv[0]=='/usr/bin/stty':return 'saved'
                    if fault=='journal':raise ValueError('journal unavailable')
                    return json.dumps({'_BOOT_ID':tx.s['boot_id'].replace('-',''),
                        '__MONOTONIC_TIMESTAMP':str(int(time.monotonic()*1_000_000))})
                tx.run=Mock(side_effect=run)
                self.assertEqual(tx.recover()['phase'],'recovered')
                self.assertIsNone(tx.command_deadline)
                self.assertIn(unittest.mock.call('enable','--now','systemd-timesyncd.service'),tx.systemctl.call_args_list)
                if fault=='packet':self.assertFalse(tx.current['packet_observation']['complete'])
                else:self.assertIn('journal unavailable',tx.current['diagnostic_error'])


class MeasurementTests(unittest.TestCase):
    def test_counters_and_peer_fields_are_required(self):
        fake=types.ModuleType('ntp');fake.packet=types.ModuleType('ntp.packet')
        session=Mock();fake.packet.ControlSession=Mock(return_value=session)
        import sys
        with patch.dict(sys.modules,{'ntp':fake,'ntp.packet':fake.packet}):
            measure=load(ROOT/'scripts/measure-time-service.py')
        session.readstat.return_value=[types.SimpleNamespace(associd=1,status=0)]
        fields={'dstadr':'::1','flash':0,'sent':2,'received':1}
        counters=dict.fromkeys(measure.COUNTERS,0)
        for bad in ('none','missing','negative','peer'):
            values=dict(counters);peer=dict(fields)
            if bad=='missing':values.pop('nts_client_recv_bad')
            if bad=='negative':values['nts_client_send']=-1
            if bad=='peer':peer.pop('dstadr')
            session.readvar.side_effect=[{'leap':0},peer,values]
            if bad=='none':self.assertEqual(measure.measure(True)['counters'],values)
            else:
                with self.subTest(bad=bad),self.assertRaises(ValueError):measure.measure(True)


if __name__=='__main__':unittest.main()
