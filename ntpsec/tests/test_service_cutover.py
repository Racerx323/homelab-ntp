#!/usr/bin/python3
"""Offline input binding, early startup, client parsing and recovery boundaries."""
import base64
from contextlib import nullcontext
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import tarfile
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[1]


def load(path):
    s=importlib.util.spec_from_file_location(path.stem.replace('-','_'),path)
    m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m


c=load(ROOT/'scripts/run-service-cutover.py');stage=load(ROOT/'scripts/service-cutover-stage.py')
client=load(ROOT/'scripts/check-time-client.py');service=load(ROOT/'scripts/timeservice.py')
pairing=load(ROOT/'scripts/gpsd-pairing.py');acqtest=load(ROOT/'tests/test_gpsd_acquisition.py')


def network_fixture(spec):
    metadata=c.encoded({'boot_id':spec['boot_id'],'ntp_conf_exists':False})
    report={'phase':'captured','evidence':{'metadata.json':{
        'base64':base64.b64encode(metadata).decode(),'sha256':c.sha(metadata)}}}
    controller=c.encoded({'state':'captured'})
    response={'spec_sha256':'a'*64,'result':report}
    records={
        'apply/accepted.json':c.encoded({'state':'policy_and_tcp_accepted','time_service_accepted':False}),
        'after/inspection-acceptance.json':c.encoded({'node':{'report_sha256':c.sha(c.encoded(report)),
            'spec_sha256':'a'*64,'state':'diagnostics_captured'},'controller':{'report_sha256':c.sha(controller)}}),
        'after/readback-1-0-result.json':c.encoded(response),'after/readback-1-1-result.json':c.encoded(response),
        'after/cleanup-0-result.json':c.encoded({'spec_sha256':'a'*64,'result':{'phase':'cleaned'}}),
        'after/unifi-report.json':controller}
    return c.encoded({'outcome':{'state':'policy_and_tcp_accepted','time_service_accepted':False,
        'permits_remain_enabled':True,'counts':{'after':{'ipv4_successes':6,'ipv6_successes':6}},
        'evidence_sha256':{n:c.sha(v) for n,v in records.items()}},
        'records':{n:base64.b64encode(v).decode() for n,v in records.items()}})


def recovery_fixture(spec):
    old={k:spec[k] for k in ('hostname','kernel','boot_id','old_ipv4','endpoints','prepared_epoch')}
    old['operation_id']='prior-cutover'
    state={'phase':'recovered','recovered_epoch':old['prepared_epoch']}
    digest=c.sha(c.encoded(old));response={'spec_sha256':digest,'result':state}
    return c.encoded({'spec.json':old,'terminal-receipt.json':{'spec_sha256':digest,
        'state':'recovered','state_sha256':c.sha(c.encoded(state)),'bundle_sha256':'b'*64},
        'readback-1-0-result.json':response,'readback-1-1-result.json':response,
        'cleanup-0-result.json':{'spec_sha256':digest,'result':dict(state,transient_cleanup=True)}})


def fixture():
    old,ref=acqtest.fixture();old['purpose']='receiver-runtime-inputs'
    ref['recipe.json']=(ROOT/'configs/receiver-runtime-inputs.json').read_bytes()
    ref['worker.py']=(ROOT/'scripts/run-gpsd-acquisition.py').read_bytes()
    old['members']={n:c.sha(v) for n,v in ref.items()};ref['spec.json']=c.encoded(old)
    raw=acqtest.archive(ref)
    evidence={n:{'sha256':c.sha(v),'base64':base64.b64encode(v).decode()} for n,v in
              {'terminal.json':b'{"phase":"captured"}\n','receiver-runtime.json':b'{"runtime":{"files":{}}}\n'}.items()}
    report={'phase':'captured','restored':True,'continuity':True,'evidence':evidence}
    receipt=acqtest.a.terminal_receipt(old,ref,c.sha(raw),dict.fromkeys(old['endpoints'],report))
    files={n:(ROOT/p).read_bytes() for n,p in c.INPUT_PATHS.items()}
    recipe=json.loads(files['recipe.json']);recipe['hostname']='fixture';files['recipe.json']=c.encoded(recipe)
    files.update({'reference.tar':raw,'reference.py':ref['worker.py'],'reference-report.json':c.encoded(report),
        'reference-receipt.json':c.encoded(receipt),'reference-cleanup.json':c.encoded({'spec_sha256':c.sha(ref['spec.json']),
        'result':{'phase':'cleaned','evidence_preserved':True,'shm_preserved':True,'terminal_sha256':evidence['terminal.json']['sha256']}}),
        'receiver-runtime.json':base64.b64decode(evidence['receiver-runtime.json']['base64']),
        'known_hosts':ref['known_hosts'],'timeservice.json':c.encoded(recipe['timeservice'])})
    spec={k:old[k] for k in ('hostname','kernel','boot_id','old_ipv4','endpoints','prepared_epoch','expires_epoch')}
    spec.update(schema=1,operation_id='cutover-fixture',stage='/var/lib/ntp-acquire-cutover-fixture',
                apply_unit='ntp-cutover-cutover-fixture',recovery_unit='ntp-cutover-cutover-fixture-recovery',recipe=recipe)
    files['network-evidence.json']=network_fixture(spec)
    files['recovery-evidence.json']=recovery_fixture(spec)
    files['diagnostic-evidence.json']=c.encoded(None)
    bind(spec,files);return spec,files


def bind(spec,files):
    spec['members']={n:c.sha(files[n]) for n in set(c.INPUT_PATHS)|c.EXTRA}
    files['spec.json']=c.encoded(spec);files['review.md']=c.review(spec).encode()
    files['manifest.json']=c.encoded({n:c.sha(v) for n,v in files.items() if n!='manifest.json'})


class BindingTests(unittest.TestCase):
    def test_complete_frozen_inputs_and_payloads(self):
        spec,files=fixture();c.validate(spec,files)
        for mode in c.MODES:compile(c.payload(spec,files,mode),mode,'exec')
        self.assertEqual(c.unpack(acqtest.archive({n:v for n,v in files.items() if n!="manifest.json"})),files)

    def test_target_window_stage_and_input_drift_rejected(self):
        spec,files=fixture()
        for key,value in [('hostname','other'),('boot_id','other'),('stage','/tmp/unsafe'),
                          ('operation_id','../escape'),('expires_epoch',90000),('endpoints',['192.0.2.8'])]:
            with self.subTest(key=key),self.assertRaises(ValueError):c.validate(dict(spec,**{key:value}),files)
        changed=dict(files);changed['stage.py']+=b'# drift'
        with self.assertRaises(ValueError):c.validate(spec,changed)

    def test_rebound_bad_receipt_cleanup_receiver_writes_rejected(self):
        for name in ('reference-receipt.json','reference-cleanup.json','receiver-runtime.json','recipe.json'):
            spec,files=fixture();v=json.loads(files[name])
            if name=='reference-receipt.json':v['state']='pending'
            elif name=='reference-cleanup.json':v['result']['shm_preserved']=False
            elif name=='receiver-runtime.json':v['runtime']['changed']=True
            else:
                v['timeservice']['gpsd'].remove('-b');spec['recipe']=v;files['timeservice.json']=c.encoded(v['timeservice'])
            files[name]=c.encoded(v);bind(spec,files)
            with self.subTest(name=name),self.assertRaises(ValueError):c.validate(spec,files)

    def test_unsafe_archive_rejected(self):
        data=io.BytesIO()
        with tarfile.open(fileobj=data,mode='w') as out:
            item=tarfile.TarInfo('../stage.py');item.size=1;out.addfile(item,io.BytesIO(b'x'))
        with self.assertRaises(ValueError):c.unpack(data.getvalue())

    def test_terminal_receipt_requires_both_identical_endpoints(self):
        spec,files=fixture();states=dict.fromkeys(spec['endpoints'],{'phase':'accepted','gate':{'state':'passed'}})
        self.assertEqual(c.terminal_receipt(spec,'a'*64,states)['state'],'accepted')
        with self.assertRaises(ValueError):c.terminal_receipt(spec,'a'*64,{spec['endpoints'][0]:states[spec['endpoints'][0]]})
        states[spec['endpoints'][1]]={'phase':'recovered'}
        with self.assertRaises(ValueError):c.terminal_receipt(spec,'a'*64,states)

    def test_selected_config_and_no_leap_restart(self):
        config=(ROOT/'configs/j2-svntp1-ntp.conf').read_text()
        self.assertIn('refclock shm unit 0 refid NMEA\n',config);self.assertNotIn('noselect',config);self.assertNotIn('time1',config)
        self.assertIn('refclock shm unit 2 prefer refid PPS',config)
        recipe=json.loads((ROOT/'configs/service-cutover-recipe.json').read_text())
        self.assertEqual([l for l in config.splitlines() if l.startswith('server ')],['server '+n+' nts iburst' for n in recipe['nts_servers']])
        self.assertIn('restrict -6 default ignore',config)
        self.assertEqual([l for l in config.splitlines() if l.startswith('restrict ')],[
            'restrict -4 default ignore','restrict -6 default ignore','restrict source nomodify noquery',
            'restrict 127.0.0.1','restrict ::1','restrict 10.1.0.0/22 nomodify noquery limited kod',
            'restrict fd36:5aa8:6971:1::/64 nomodify noquery limited kod'])
        maintenance=(ROOT/'templates/ntpleapfetch-j2.service').read_text();self.assertNotIn(' -c ',maintenance)
        self.assertIn('-t /var/lib/ntpsec/leap-seconds.tmp',maintenance)


class StartupTests(unittest.TestCase):
    def test_failed_pairing_prevents_ntpd_and_stops_gpsd(self):
        config=json.loads((ROOT/'configs/service-cutover-recipe.json').read_text())['timeservice']
        process=Mock();process.poll.return_value=None
        with patch.object(service.subprocess,'run'),patch.object(service.subprocess,'Popen',return_value=process) as launch,patch.object(service,'check_startup',side_effect=ValueError('PPS missing')):
            with self.assertRaisesRegex(ValueError,'PPS missing'):service.supervise(config)
        launch.assert_called_once();process.terminate.assert_called_once()

    def test_missing_or_overlapping_gate_units_prevent_start(self):
        config=json.loads((ROOT/'configs/service-cutover-recipe.json').read_text())['timeservice']
        for gate in (None,dict(config['startup_gate'],units={'TOFF':'NTP0','PPS':'NTP0'})):
            with patch.object(service.subprocess,'run') as run,self.assertRaises(ValueError):service.supervise(dict(config,startup_gate=gate))
            run.assert_not_called()

    def run_gate(self,units,exit_early=False):
        # Use protocol samples directly: every reported timestamp has an independent leap-0 SHM match.
        rows=[{'class':'WATCH','pps':True}];lines=[]
        for kind,device,unit in [('TOFF','/dev/serial0','NTP0'),('PPS','/dev/pps0','NTP2')]:
            for sec in range(5):
                rows.append({'class':kind,'device':device,'shm':unit,'clock_sec':100+sec,'clock_nsec':0,'real_sec':100+sec,'real_nsec':0})
                lines.append(f'sample {unit} 100 {100+sec}.000000000 {100+sec}.000000000 0 -20')
        raws=[('\n'.join(map(json.dumps,rows))+'\n').encode(),('\n'.join(lines)+'\n').encode()];children=[]
        def launch(argv,stdout,**kwargs):
            stdout.write(raws[len(children)]);stdout.flush();p=Mock();p.poll.return_value=1 if exit_early else None;children.append(p);return p
        gpsd=Mock();gpsd.poll.return_value=None
        with tempfile.TemporaryDirectory() as d,patch.object(pairing.socket,'create_connection'),patch.object(pairing.subprocess,'Popen',side_effect=launch):
            try:return pairing.startup(gpsd,lambda:False,units,Path(d))
            finally:
                for p in children:p.wait.assert_called_once()
                if not exit_early:
                    for p in children:p.terminate.assert_called_once()

    def test_monitors_stop_before_gate_returns(self):
        self.assertTrue(self.run_gate({'TOFF':'NTP0','PPS':'NTP2'})['observed'])

    def test_wrong_mapping_or_dead_monitor_rejected_and_reaped(self):
        with self.assertRaises(ValueError):self.run_gate({'TOFF':'NTP0','PPS':'NTP1'})
        with self.assertRaises(ValueError):self.run_gate({'TOFF':'NTP0','PPS':'NTP2'},True)


class JournalTests(unittest.TestCase):
    def row(self):
        return {'MESSAGE':stage.MINSANE_MESSAGE,'PRIORITY':'3','_SYSTEMD_UNIT':'timeservice.service',
                '_EXE':'/usr/local/sbin/ntpd','_COMM':'ntpd','_TRANSPORT':'syslog',
                'SYSLOG_IDENTIFIER':'ntpd','_PID':'123','_BOOT_ID':'a'*32,'__MONOTONIC_TIMESTAMP':'110000000'}

    def check(self,rows):
        return stage.journal_health('\n'.join(json.dumps(r) for r in rows),'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',100,123)

    def test_one_exact_startup_advisory_or_no_errors(self):
        self.assertTrue(self.check([])['healthy'])
        result=self.check([self.row()]);self.assertTrue(result['healthy']);self.assertEqual(len(result['allowed']),1)
        old=dict(self.row(),__MONOTONIC_TIMESTAMP='99000000',MESSAGE='old failure')
        self.assertTrue(self.check([old])['healthy'])

    def test_other_errors_provenance_duplicates_late_and_bad_json_fail(self):
        for key,value in [('MESSAGE','unexpected failure'),('MESSAGE',stage.MINSANE_MESSAGE+' suffix'),
                          ('PRIORITY','2'),('_SYSTEMD_UNIT','avahi-daemon.service'),('_PID','124'),
                          ('_EXE','/usr/bin/other'),('_COMM','other'),('_TRANSPORT','stdout'),
                          ('SYSLOG_IDENTIFIER','python3'),('__MONOTONIC_TIMESTAMP','221000000')]:
            with self.subTest(key=key):self.assertFalse(self.check([dict(self.row(),**{key:value})])['healthy'])
        self.assertFalse(self.check([self.row(),self.row()])['healthy'])
        with self.assertRaises(ValueError):self.check([dict(self.row(),_BOOT_ID='b'*32)])
        with self.assertRaises(ValueError):stage.journal_health('not json','a'*32,100,123)

    def telemetry(self):
        messages=[stage.MINSANE_MESSAGE,'NTSc: read 816 bytes',
                  'NTSc: Got 8 cookies, length 96, aead=15.',
                  'NTSc: read 848 bytes','NTSc: Got 8 cookies, length 100, aead=15.',
                  'NTSc: read 848 bytes','NTSc: Got 8 cookies, length 100, aead=15.']
        return [dict(self.row(),MESSAGE=m,__MONOTONIC_TIMESTAMP=str(110000000+i)) for i,m in enumerate(messages)]

    def test_retained_message_sequence_and_source_bounds(self):
        result=self.check(self.telemetry());self.assertTrue(result['healthy'])
        self.assertEqual(result['startup_counts'],{'minsane':1,'read':3,'cookies':3})
        for count,length,aead,size in ((1,1,15,1),(8,192,17,2048),(4,100,16,848)):
            rows=self.telemetry()[1:3]
            rows[0]['MESSAGE']=f'NTSc: read {size} bytes'
            rows[1]['MESSAGE']=f'NTSc: Got {count} cookies, length {length}, aead={aead}.'
            self.assertTrue(self.check(rows)['healthy'])

    def test_nts_failures_invalid_values_incomplete_exchanges_and_excess_are_rejected(self):
        failures=['NTSc: read 0 bytes','NTSc: read 2049 bytes','NTSc: read -1 bytes',
                  'NTSc: read 816 bytes suffix','NTSc: Got 0 cookies, length 96, aead=15.',
                  'NTSc: Got 9 cookies, length 96, aead=15.',
                  'NTSc: Got 8 cookies, length 193, aead=15.',
                  'NTSc: Got 8 cookies, length 0, aead=15.',
                  'NTSc: Got 8 cookies, length 96, aead=1.',
                  'NTSc: No cookies.','NTSc: AEAD not negotiated.',
                  'NTSc: EOM not at end 8','NTSc: TLS handshake failed',
                  'NTSc: connect failed: Connection refused']
        for message in failures:
            with self.subTest(message=message):
                self.assertFalse(self.check(self.telemetry()+[dict(self.row(),MESSAGE=message)])['healthy'])
        self.assertFalse(self.check(self.telemetry()[:-1])['healthy'])
        self.assertFalse(self.check(self.telemetry()[2:])['healthy'])
        self.assertFalse(self.check(self.telemetry()+self.telemetry()[1:3])['healthy'])
        extra=[dict(r,__MONOTONIC_TIMESTAMP=str(115000000+i)) for i,r in enumerate(self.telemetry()[1:3])]
        self.assertFalse(self.check(self.telemetry()+extra)['healthy'])
        for key,value in (('_PID','other'),('_TRANSPORT','stdout'),('_SYSTEMD_UNIT','avahi-daemon.service'),
                          ('_EXE','/other'),('PRIORITY','2'),('__MONOTONIC_TIMESTAMP','221000000')):
            rows=self.telemetry();rows[1][key]=value
            with self.subTest(key=key):self.assertFalse(self.check(rows)['healthy'])

    def test_recovered_receipt_drift_is_rejected(self):
        for case in ('target','readback','cleanup','state','digest','future','reuse'):
            spec,files=fixture();proof=json.loads(files['recovery-evidence.json'])
            if case=='target':proof['spec.json']['boot_id']='other'
            elif case=='readback':proof['readback-1-1-result.json']['result']['phase']='observing'
            elif case=='cleanup':proof['cleanup-0-result.json']['result']['transient_cleanup']=False
            elif case=='state':proof['terminal-receipt.json']['state']='accepted'
            elif case=='digest':proof['terminal-receipt.json']['state_sha256']='0'*64
            elif case=='future':spec['prepared_epoch']-=1
            else:proof['spec.json']['operation_id']=spec['operation_id']
            files['recovery-evidence.json']=c.encoded(proof);bind(spec,files)
            with self.subTest(case=case),self.assertRaises(ValueError):c.validate(spec,files)

    def test_rebound_network_and_policy_failures(self):
        for case in ('digest','pending','boot','readback','cleanup','policy','config'):
            spec,files=fixture();proof=json.loads(files['network-evidence.json'])
            if case=='policy':
                spec['recipe']['minsane']=3;files['recipe.json']=c.encoded(spec['recipe'])
            elif case=='config':files['ntp.conf']=files['ntp.conf'].replace(b'tos minsane 1',b'tos minsane 3')
            elif case=='pending':proof['outcome']['permits_remain_enabled']=False
            elif case=='digest':proof['outcome']['evidence_sha256']['apply/accepted.json']='0'*64
            else:
                name='after/readback-1-1-result.json' if case in ('boot','readback') else 'after/cleanup-0-result.json'
                obj=json.loads(base64.b64decode(proof['records'][name]));obj['spec_sha256']='b'*64
                raw=c.encoded(obj);proof['records'][name]=base64.b64encode(raw).decode();proof['outcome']['evidence_sha256'][name]=c.sha(raw)
            files['network-evidence.json']=c.encoded(proof);bind(spec,files)
            with self.subTest(case=case),self.assertRaises(ValueError):c.validate(spec,files)


class ClientTests(unittest.TestCase):
    def packet(self):
        raw=bytearray(48);raw[0]=0x24;raw[1]=1;raw[12:16]=b'PPS\0';raw[24:32]=b'nonce123';raw[32:40]=b'x'*8
        raw[40:48]=struct.pack('!II',int(time.time())+2208988800,0);return raw

    def test_ntp_nonce_leap_stratum_and_freshness(self):
        raw=self.packet();self.assertEqual(client.ntp_response(raw,b'nonce123')['stratum'],1)
        for offset,value in ((0,0xe4),(1,16),(24,0),(40,0)):
            changed=raw.copy();changed[offset]=value
            with self.subTest(offset=offset),self.assertRaises(ValueError):client.ntp_response(changed,b'nonce123')
        with self.assertRaises(ValueError):client.ntp_response(raw+b'extra',b'nonce123')

    def test_mdns_requires_ptr_srv_and_both_target_addresses(self):
        records=[('_ntp._udp.local',12,'clock._ntp._udp.local'),('clock._ntp._udp.local',33,(123,'fixture.local')),
                 ('fixture.local',1,'192.0.2.2'),('fixture.local',28,'fd00::2')]
        self.assertTrue(client.discovery_matches(records,['192.0.2.2','fd00::2'],'fixture'))
        for index in range(len(records)):
            self.assertFalse(client.discovery_matches(records[:index]+records[index+1:],['192.0.2.2','fd00::2'],'fixture'))
        with self.assertRaises(ValueError):client.dns_name(b'\xc0\x00',0)
        with self.assertRaises(ValueError):client.dns_records(b'short')
        self.assertEqual(client.dns_name(b'\x03ntp\x05local\x00\xc0\x00',11),('ntp.local',13))

    def test_query_response_is_not_accepted_as_denied(self):
        sock=Mock();sock.__enter__=Mock(return_value=sock);sock.__exit__=Mock(return_value=False)
        sock.recv.side_effect=[bytes(self.packet()),b'control reply']
        sock.getsockname.return_value=('192.0.2.3',10000)
        with patch.object(client.socket,'socket',return_value=sock),patch.object(client.secrets,'token_bytes',return_value=b'nonce123'),self.assertRaisesRegex(ValueError,'administrative'):
            client.client_ntp('192.0.2.2')


class TransactionTests(unittest.TestCase):
    def transaction(self,state=None):
        spec,files=fixture();tx=stage.Transaction.__new__(stage.Transaction);tx.s=spec;tx.f=files
        tx.lock=lambda:nullcontext();tx.retained=Mock();tx.unchanged=Mock();tx.systemctl=Mock(return_value='active\n')
        tx.current=state or {'phase':'ready','supervisor_pid':100,'deadline':time.monotonic()+500}
        tx.state=lambda:copy.deepcopy(tx.current)
        def write(name,value):
            if name=='state.json':tx.current=copy.deepcopy(value)
        tx.write=Mock(side_effect=write);tx.measure=Mock(return_value={'checks':{'all':True}})
        return tx

    def proofs(self,tx):
        p=dict.fromkeys(tx.s['endpoints'],{'phase':'ready','supervisor_pid':100})
        p['client']={'target':tx.s['hostname'],'spec_sha256':stage.sha(stage.encoded(tx.s)),
                     'epoch':time.time(),'checks':dict.fromkeys(('ipv4','ipv6','queries_denied','mdns'),True)}
        return p

    def test_accept_commits_before_canceling_recovery(self):
        tx=self.transaction();events=[]
        tx.systemctl.side_effect=lambda *a:(events.append(('systemctl',a)) or 'active')
        write=tx.write.side_effect
        tx.write.side_effect=lambda n,v:(events.append(('write',v['phase'])),write(n,v))
        self.assertEqual(tx.accept(self.proofs(tx))['phase'],'accepted')
        self.assertLess(events.index(('write','accepted')),events.index(('systemctl',('stop',tx.s['recovery_unit']+'.timer'))))

    def test_bad_client_stale_boot_proofs_or_reserve_prevent_acceptance(self):
        for case in ('mdns','digest','stale','endpoint','reserve','drift','lost'):
            tx=self.transaction();p=self.proofs(tx)
            if case=='mdns':p['client']['checks']['mdns']=False
            elif case=='digest':p['client']['spec_sha256']='0'*64
            elif case=='stale':p['client']['epoch']-=121
            elif case=='endpoint':p.pop(tx.s['endpoints'][1])
            elif case=='reserve':tx.current['deadline']=time.monotonic()+1
            elif case=='drift':tx.unchanged.side_effect=ValueError('drift')
            else:tx.measure.return_value={'checks':{'all':False}}
            with self.subTest(case=case),self.assertRaises(ValueError):tx.accept(p)
            tx.systemctl.assert_not_called();self.assertEqual(tx.current['phase'],'ready')

    def test_cancel_failure_preserves_durable_acceptance(self):
        tx=self.transaction();tx.systemctl.side_effect=lambda *a: (_ for _ in ()).throw(ValueError('lost timer reply')) if a[0]=='stop' else ''
        with self.assertRaises(ValueError):tx.accept(self.proofs(tx))
        self.assertEqual(tx.current['phase'],'accepted');self.assertEqual(tx.recover()['phase'],'accepted')

    def test_probes_require_three_consecutive_successes_and_are_bounded(self):
        tx=self.transaction({'phase':'observing','stable':0,'probe_count':0})
        with patch.object(stage.time,'monotonic',side_effect=[100,130,160,190,220]):
            self.assertEqual(tx.probe()['phase'],'observing')
            tx.measure.return_value={'checks':{'pps':False}};self.assertEqual(tx.probe()['stable'],0)
            tx.measure.return_value={'checks':{'pps':True}}
            tx.probe();tx.probe();self.assertEqual(tx.probe()['phase'],'ready')
        tx.current['probe_count']=40
        with self.assertRaises(ValueError):tx.probe()

    def test_apply_failure_claims_change_then_recovers_without_replay(self):
        tx=self.transaction({'phase':'staged','created_directories':[],'installed':[]});tx.h=SimpleNamespace(ancestors=Mock())
        tx.replace=Mock(side_effect=OSError('disk full'));tx.recover=Mock()
        with patch.dict(stage.DIRECTORIES,{},clear=True),self.assertRaises(OSError):tx.apply()
        self.assertEqual(tx.current['phase'],'apply_held');self.assertEqual(tx.current['installed'],[next(iter(stage.DESTINATIONS))])
        tx.recover.assert_called_once_with(locked=True)
        with self.assertRaises(ValueError):tx.apply()
        tx.replace.assert_called_once()

    def test_real_measurement_rejects_missing_authentication_selection_and_jitter(self):
        recipe=json.loads((ROOT/'configs/service-cutover-recipe.json').read_text())
        value={'system':{'leap':0,'stratum':1},'peers':[
            {'status':6<<8,'variables':{'srcadr':'127.127.28.2','reach':377,'offset':0.01,'jitter':0.002}},
            {'status':0,'variables':{'srcadr':'SHM(0)','reach':377}},
            *[{'status':0x60<<8,'variables':{'srcadr':'192.0.2.'+str(i),'srchost':host,'reach':377,'ntscookies':8}} for i,host in enumerate(recipe['nts_servers'])]]}
        self.assertTrue(all(stage.measurement_checks(value,recipe).values()))
        for case in ('leap','stratum','select','nts','cookie','jitter','serial','missing'):
            v=copy.deepcopy(value)
            if case in ('leap','stratum'):v['system'][case]=16
            elif case=='select':v['peers'][0]['status']=0
            elif case=='nts':v['peers'][2]['status']=0x40<<8
            elif case=='cookie':v['peers'][2]['variables']['ntscookies']=0
            elif case=='jitter':v['peers'][0]['variables']['jitter']=-1
            elif case=='serial':v['peers'][1]['variables']['reach']=0
            else:v['peers'].pop()
            with self.subTest(case=case):self.assertFalse(all(stage.measurement_checks(v,recipe).values()))

    def test_apply_success_requires_gate_and_early_control_response(self):
        for passed in (True,False):
            tx=self.transaction({'phase':'staged','created_directories':[],'installed':[]})
            tx.replace=Mock();tx.recover=Mock();tx.root=Path('/fixture')
            gate={'state':'passed' if passed else 'failed','supervisor_pid':100}
            tx.h=SimpleNamespace(ancestors=Mock(),read=Mock(return_value=stage.encoded(gate)))
            tx.run=Mock(return_value='{"system":{"leap":3}}');tx.systemctl=Mock(return_value='100')
            with patch.dict(stage.DIRECTORIES,{},clear=True),patch.object(stage.Path,'exists',return_value=True),patch.object(stage.time,'sleep'):
                if passed:
                    self.assertEqual(tx.apply()['phase'],'observing');tx.recover.assert_not_called()
                    self.assertEqual(tx.current['early_ntpd']['system']['leap'],3)
                    self.assertEqual(tx.replace.call_count,len(stage.DESTINATIONS))
                else:
                    with self.assertRaisesRegex(ValueError,'early GPSD'):tx.apply()
                    tx.recover.assert_called_once_with(locked=True)

    def test_measure_uses_json_compact_boot_and_retains_journal(self):
        tx=self.transaction({'supervisor_pid':100,'apply_monotonic':100});tx.root=Path('/fixture')
        tx.s['boot_id']='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
        row=JournalTests().row();tx.run=Mock(side_effect=['{}',json.dumps(row)])
        tx.systemctl.side_effect=['inactive','active','100','0','']
        texts=['122 123','Uid: 65534 65534 65534 65534\nGid: 20 20 20 20',
               'Uid: 999 999 999 999\nGid: 985 985 985 985']
        with patch.object(stage,'measurement_checks',return_value={}),patch.object(stage.Path,'read_text',side_effect=texts),patch.object(stage.os,'readlink',side_effect=['/usr/local/sbin/gpsd','/usr/local/sbin/ntpd']):
            result=stage.Transaction.measure(tx)
        self.assertTrue(all(result['checks'].values()));self.assertEqual(result['journal']['allowed'],[row])
        argv=tx.run.call_args.args[0]
        self.assertIn('--boot='+'a'*32,argv);self.assertIn('--output=json',argv)
        self.assertFalse(any(arg.startswith('--since') for arg in argv))

    def test_arm_timer_precedes_mutation_and_has_fixed_lifetime(self):
        tx=self.transaction();tx.root=Path('/var/lib/fixture');tx.run=Mock()
        tx.arm();argv=tx.run.call_args.args[0];self.assertIn('--on-active=1800s',argv)
        self.assertEqual(argv[-1],'recover')
        tx.systemctl.return_value='inactive'
        with self.assertRaises(ValueError):tx.arm()

    def test_recovery_restores_original_files_and_rejects_foreign_edits(self):
        for drift in (False,True):
            with tempfile.TemporaryDirectory() as d:
                root=Path(d);dest=root/'config';dest.write_bytes(b'candidate' if not drift else b'foreign')
                tx=self.transaction({'phase':'observing','installed':[str(dest)],'created_directories':[]});tx.root=root;tx.f['fixture']=b'candidate'
                before={'files':{str(dest):{'sha256':stage.sha(b'original'),'base64':base64.b64encode(b'original').decode(),'mode':0o644,'uid':0,'gid':0}},'serial':{'ok':True},'termios':'saved'}
                tx.h=SimpleNamespace(read=lambda p,**kw:stage.encoded(before),sync=Mock())
                tx.a=SimpleNamespace(idle=Mock(),serial_identity=lambda:{'ok':True},context=Mock());tx.alias={};tx.rf={}
                tx.snapshot=lambda n:{'sha256':stage.sha(Path(n).read_bytes())}
                tx.replace=lambda n,raw,*args:Path(n).write_bytes(raw);tx.run=Mock(return_value='saved')
                with patch.dict(stage.DESTINATIONS,{str(dest):('fixture',0o644)},clear=True):
                    if drift:
                        with self.assertRaisesRegex(ValueError,'destination drift'):tx.recover()
                        self.assertEqual(dest.read_bytes(),b'foreign');self.assertEqual(tx.current['phase'],'recovery_held')
                    else:
                        self.assertEqual(tx.recover()['phase'],'recovered');self.assertEqual(dest.read_bytes(),b'original')
                        tx.a.context.assert_called_once();self.assertIn(unittest.mock.call('enable','--now','systemd-timesyncd.service'),tx.systemctl.call_args_list)


if __name__=='__main__':unittest.main()
