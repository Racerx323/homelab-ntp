#!/usr/bin/python3
"""Offline boundaries for a one-shot acquisition and UART recovery."""
import copy
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch, Mock

ROOT=Path(__file__).resolve().parents[1]
info=importlib.util.spec_from_file_location('acq',ROOT/'scripts/run-gpsd-acquisition.py')
a=importlib.util.module_from_spec(info);info.loader.exec_module(a)
receiver=a.load(ROOT/'scripts/inspect-receiver-runtime.py')


def archive(files):
    files=dict(files);files['manifest.json']=a.encoded({n:a.sha(v) for n,v in files.items()})
    result=io.BytesIO()
    with tarfile.open(fileobj=result,mode='w') as t:
        for n,v in files.items():
            item=tarfile.TarInfo(n);item.size=len(v);t.addfile(item,io.BytesIO(v))
    return result.getvalue()


def fixture():
    old={'operation':'runtime','hostname':'fixture','kernel':'test','stage':'/var/lib/ntp-host-runtime',
         'old_ipv4':'192.0.2.1','recipe':{'ipv4_address':'192.0.2.2/24','ipv6_address':'fd00::2/64'}}
    raw=archive({'spec.json':a.encoded(old)})
    state={'accepted_boot_id':'boot','phase':'accepted','transient_units_cleaned':True,
           'checks':{'native':True},'hardware':{'uart':'accepted'},'ssh_proofs':{'192.0.2.2':{},'fd00::2':{}}}
    receipt={'state':'runtime_configuration_accepted','spec_sha256':a.sha(a.encoded(old)),
             'bundle_sha256':a.sha(raw),'boot_id':'boot','checks':state['checks'],'hardware':state['hardware']}
    files={n:b'fixture' for n in a.INPUTS}
    files.update({'runtime.tar':raw,'runtime-acceptance.json':a.encoded(receipt),
        'runtime-cleanup.json':a.encoded({'result':state,'bundle_sha256':a.sha(raw)}),
        'recipe.json':(ROOT/'configs/gpsd-acquisition-recipe.json').read_bytes()})
    spec={'schema':3,'purpose':'acquisition','operation_id':'fixture','stage':'/var/lib/ntp-acquire-fixture',
          'unit':'ntp-acquire-fixture.service','hostname':'fixture','kernel':'test','boot_id':'boot',
          'source_stage':old['stage'],'runtime_sha256':a.sha(raw),'old_ipv4':old['old_ipv4'],
          'endpoints':['192.0.2.2','fd00::2'],'prepared_epoch':1,'expires_epoch':86401}
    previous=dict(spec,schema=1,operation_id='prior',stage='/var/lib/ntp-acquire-prior')
    prior=archive({'spec.json':a.encoded(previous)})
    terminal=a.encoded({'phase':'captured'})
    files.update({'prior.tar':prior,'prior-terminal.json':terminal,
                  'prior-restoration.json':a.encoded({'restored':True,'boot_id':'boot'}),
                  'prior-shm-after.txt':b'key shmid perms size cpid uid gid cuid cgid nattch\n',
                  'prior-acceptance.json':a.encoded({'state':'acquisition_capture_accepted',
                      'bundle_sha256':a.sha(prior),'spec_sha256':a.sha(a.encoded(previous)),
                      'report_sha256':'a'*64}),
                  'prior-cleanup.json':a.encoded({'spec_sha256':a.sha(a.encoded(previous)),
                      'result':{'phase':'cleaned','evidence_preserved':True,'shm_preserved':True,
                                'terminal_sha256':a.sha(terminal)}})})
    spec['members']={n:a.sha(v) for n,v in files.items()}
    return spec,files


class AcquisitionTests(unittest.TestCase):
    def test_bound_runtime(self):
        spec,files=fixture();a.validate(spec,files)
        for key,value in [('boot_id','different'),('source_stage','/tmp/untrusted'),
                          ('runtime_sha256','0'*64),('expires_epoch',999999),
                          ('endpoints',['192.0.2.99','fd00::2']),('operation_id','../bad')]:
            with self.subTest(key=key),self.assertRaises(ValueError):a.validate(dict(spec,**{key:value}),files)

    def test_missing_cleanup_and_input_drift(self):
        spec,files=fixture()
        bad=copy.deepcopy(files);state=json.loads(bad['runtime-cleanup.json'])
        state['result']['transient_units_cleaned']=False;bad['runtime-cleanup.json']=a.encoded(state)
        with self.assertRaises(ValueError):a.validate(spec,bad)
        bad=copy.deepcopy(files);bad['tests.py']+=b'changed'
        with self.assertRaises(ValueError):a.validate(spec,bad)

    def test_receiver_write_or_network_exposure_rejected(self):
        r=json.loads((ROOT/'configs/gpsd-acquisition-recipe.json').read_bytes())
        for argv in ([x for x in r['gpsd'] if x!='-b'],r['gpsd']+['-G'],r['gpsd']+['-F','/tmp/control']):
            with self.assertRaises(ValueError):a.validate_recipe(dict(r,gpsd=argv))
        with self.assertRaises(ValueError):a.validate_recipe(dict(r,ntpshmmon=r['ntpshmmon']+['-s']))
        with self.assertRaises(ValueError):a.validate_recipe(dict(r,duration_seconds=0))

    def test_archive_path_and_manifest_rejected(self):
        with self.assertRaises(ValueError):a.unpack(archive({'../escape':b'x'}))
        with self.assertRaises(ValueError):a.unpack(archive({'x':b'x'}).replace(b'"x":',b'"y":',1))

    def test_unit_has_independent_recovery(self):
        spec,_=fixture();cmd=a.unit_command(spec)
        self.assertIn('--property=RuntimeMaxSec=1080',cmd)
        self.assertIn('--property=KillMode=control-group',cmd)
        self.assertIn('--property=Restart=no',cmd)
        stop=[x for x in cmd if x.startswith('--property=ExecStopPost=')]
        self.assertEqual(len(stop),1);self.assertTrue(stop[0].endswith(' worker restore'))
        self.assertNotIn('--collect',cmd)

    def test_capture_failure_stops_children_and_retains_terminal(self):
        spec,files=fixture()
        with tempfile.TemporaryDirectory() as directory:
            spec['stage']=directory;root=Path(directory)
            h=Mock();h.create.side_effect=lambda path,data:path.write_bytes(data)
            process=Mock();process.pid=__import__('os').getpid();process.poll.return_value=None
            process.wait.side_effect=[subprocess.TimeoutExpired('gpspipe',930),0,0,0]
            connection=Mock();connection.__enter__=Mock();connection.__exit__=Mock()
            with patch.object(a,'idle'),patch.object(a,'prior_guard'),patch.object(a,'run',return_value=''),patch.object(a.signal,'signal'),\
                    patch.object(a.socket,'create_connection',return_value=connection),\
                    patch.object(a.subprocess,'Popen',return_value=process):
                a.capture(h,spec,files)
            terminal=json.loads((root/'terminal.json').read_bytes())
            self.assertEqual(terminal['phase'],'held');self.assertFalse(terminal['receiver_timing_accepted'])
            self.assertTrue(process.terminate.called)
            self.assertFalse((root/'restoration.json').exists())

    def test_restore_refuses_device_drift_before_write(self):
        spec,_=fixture();h=Mock();h.read.return_value=a.encoded({'identity':{'rdev':1},'termios':'abc'})
        with patch.object(a.Path,'read_text',return_value='boot'),patch.object(a,'serial_identity',return_value={'rdev':2}),\
                patch.object(a,'run') as run:
            with self.assertRaises(ValueError):a.restore(h,spec)
            run.assert_not_called()

    def test_restore_checks_idle_and_exact_termios(self):
        spec,_=fixture();h=Mock();h.read.return_value=a.encoded({'identity':{'rdev':1},'termios':'abc'})
        with patch.object(a.Path,'read_text',return_value='boot'),patch.object(a.Path,'exists',return_value=False),\
                patch.object(a,'serial_identity',return_value={'rdev':1}),patch.object(a,'idle') as idle,\
                patch.object(a,'run',side_effect=['','abc\n']) as run:
            a.restore(h,spec)
            idle.assert_called_once();self.assertEqual(run.call_args_list[0].args[0][-1],'abc')
            self.assertEqual(json.loads(h.create.call_args.args[1])['restored'],True)

    def test_rendered_remote_modes_compile(self):
        spec,files=fixture();files['worker.py']=(ROOT/'scripts/run-gpsd-acquisition.py').read_bytes()
        for mode in ('start','readback','recover','cleanup'):compile(a.payload(spec,files,mode),'payload','exec')

    def test_explicit_one_serial_one_pps_and_watch_required(self):
        r=json.loads((ROOT/'configs/gpsd-acquisition-recipe.json').read_bytes())
        for bad in (r['gpsd'][:-1],r['gpsd']+['/dev/ttyAMA1'],r['gpsd']+['/dev/pps1']):
            with self.assertRaises(ValueError):a.validate_recipe(dict(r,gpsd=bad))
        with self.assertRaises(ValueError):a.validate_recipe(dict(r,gpspipe=[x for x in r['gpspipe'] if x!='-P']))

    def test_prior_receipt_and_boot_cannot_be_replaced(self):
        spec,files=fixture()
        receipt=json.loads(files['prior-cleanup.json']);receipt['result']['terminal_sha256']='0'*64
        files['prior-cleanup.json']=a.encoded(receipt);spec['members']['prior-cleanup.json']=a.sha(files['prior-cleanup.json'])
        with self.assertRaises(ValueError):a.validate(spec,files)

    def test_inventory_rejects_attachments_and_retains_ownership(self):
        header=b'key shmid perms size cpid uid gid cuid cgid nattch lpid\n'
        before=header+b'1 2 600 96 3 0 0 0 0 0 7\n'
        self.assertEqual(a.shm_inventory(before),a.shm_inventory(before.replace(b'0 7',b'0 8')))
        self.assertNotEqual(a.shm_inventory(before),a.shm_inventory(before.replace(b'600',b'666')))
        with self.assertRaises(ValueError):a.shm_inventory(before.replace(b'0 7',b'1 7'))

    def paired_samples(self, count=60):
        reports=[{'class':'WATCH','pps':True}];samples=[]
        for kind,path,unit in [('TOFF','/dev/serial0','NTP4'),('PPS','/dev/pps0','NTP7')]:
            for n in range(count):
                sec=1700000000+n
                reports.append({'class':kind,'device':path,'shm':unit,'real_sec':sec,'real_nsec':0,
                                'clock_sec':sec,'clock_nsec':12345})
                samples.append(f'sample {unit} {sec}.1 {sec}.000012345 {sec}.000000000 0 -20')
        return reports,'\n'.join(samples)

    def test_pairing_observes_units_without_assuming_numbers(self):
        rows,samples=self.paired_samples()
        result=a.pairing_evidence('\n'.join(map(json.dumps,rows)),samples)
        self.assertTrue(result['observed']);self.assertEqual(result['sources']['PPS']['unit'],'NTP7')
        self.assertFalse(result['timing_accuracy_accepted'])

    def test_pairing_rejects_missing_ambiguous_or_uncorrelated_data(self):
        rows,samples=self.paired_samples()
        for change in ('watch','path','unit','timestamp','leap','duplicates'):
            bad=copy.deepcopy(rows);shm=samples
            if change=='watch':bad[0]['pps']=False
            elif change=='path':bad[-1]['device']='/dev/pps1'
            elif change=='unit':bad[-1]['shm']='NTP9'
            elif change=='timestamp':
                for row in bad[1:]:row['clock_nsec']+=1
            elif change=='leap':shm=shm.replace(' 0 -20',' 3 -20')
            else:
                bad=[rows[0],*([rows[1]]*60),*([rows[-1]]*60)]
            with self.subTest(change=change):
                self.assertFalse(a.pairing_evidence('\n'.join(map(json.dumps,bad)),shm)['observed'])

    def test_gate_limits_cannot_be_relaxed(self):
        r=json.loads((ROOT/'configs/gpsd-acquisition-recipe.json').read_bytes())
        for gate in ({'timeout_seconds':900,'matching_samples_per_source':5},
                     {'timeout_seconds':30,'matching_samples_per_source':0},None):
            with self.assertRaises(ValueError):a.validate_recipe(dict(r,functional_gate=gate))

    def test_live_pairing_ignores_only_unfinished_lines(self):
        rows,samples=self.paired_samples(5)
        gps=('\n'.join(map(json.dumps,rows))+'\n{"class":').encode()
        h=Mock();h.read.side_effect=[gps,(samples+'\nsample unfinished').encode()]
        self.assertTrue(a.live_pairing(h,Path('/fixture'),5)['observed'])
        h.read.side_effect=[b'{bad}\n',b'']
        with self.assertRaises(ValueError):a.live_pairing(h,Path('/fixture'),5)

    def test_gate_reports_success_without_waiting_full_window(self):
        rows,samples=self.paired_samples(5);h=Mock()
        h.read.side_effect=[('\n'.join(map(json.dumps,rows))+'\n').encode(),(samples+'\n').encode()]
        processes=[Mock() for _ in range(3)]
        for p in processes:p.poll.return_value=None
        with patch.object(a.time,'monotonic',side_effect=[0,1,2]),patch.object(a.time,'sleep') as sleep:
            gate=a.functional_gate(h,Path('/fixture'),processes,{'timeout_seconds':30,'matching_samples_per_source':5})
        self.assertEqual(gate['state'],'passed');sleep.assert_not_called()
        self.assertFalse(gate['pairing']['timing_accuracy_accepted'])

    def test_gate_missing_pps_times_out_and_child_exit_fails(self):
        processes=[Mock() for _ in range(3)]
        for p in processes:p.poll.return_value=None
        for reason in ('missing','malformed','exited'):
            with self.subTest(reason=reason),patch.object(a.time,'monotonic',side_effect=[0,1,31,32]),\
                    patch.object(a.time,'sleep'),patch.object(a,'live_pairing') as pairing:
                pairing.return_value={'observed':False,'reason':'missing PPS'}
                if reason=='malformed':pairing.side_effect=ValueError('invalid sample')
                if reason=='exited':processes[0].poll.return_value=1
                gate=a.functional_gate(Mock(),Path('/fixture'),processes,{'timeout_seconds':30,'matching_samples_per_source':5})
                self.assertEqual(gate['state'],'failed')

    def test_capture_gate_failure_never_waits_full_observation(self):
        spec,files=fixture()
        with tempfile.TemporaryDirectory() as directory:
            spec['stage']=directory;root=Path(directory)
            h=Mock();h.create.side_effect=lambda path,data:path.write_bytes(data)
            processes=[Mock() for _ in range(3)]
            for p in processes:p.poll.return_value=None;p.wait.return_value=0
            connection=Mock();connection.__enter__=Mock();connection.__exit__=Mock()
            with patch.object(a,'idle'),patch.object(a,'prior_guard'),patch.object(a,'run',return_value=''),\
                    patch.object(a.signal,'signal'),patch.object(a.socket,'create_connection',return_value=connection),\
                    patch.object(a.subprocess,'Popen',side_effect=processes),\
                    patch.object(a,'functional_gate',return_value={'state':'failed','error':'missing PPS'}):
                a.capture(h,spec,files)
            for p in processes:
                p.terminate.assert_called_once();p.wait.assert_called_once_with(timeout=5)
            self.assertEqual(json.loads((root/'terminal.json').read_bytes())['phase'],'held')
            self.assertEqual(json.loads((root/'functional-gate.json').read_bytes())['state'],'failed')

    def test_startup_result_is_visible_or_explicitly_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);h=Mock();h.create.side_effect=lambda p,b:p.write_bytes(b);h.read.side_effect=lambda p:p.read_bytes()
            a.publish_gate(h,root,{'state':'passed'})
            self.assertEqual(a.startup_result(h,root),{'state':'passed'})
            self.assertFalse((root/'functional-gate.tmp').exists())
        with patch.object(a.time,'monotonic',side_effect=[0,51]):
            self.assertEqual(a.startup_result(Mock(),Path('/fixture'))['state'],'unavailable')

    def test_long_capture_follows_gate_and_requires_final_pairing(self):
        for paired in (True,False):
            with self.subTest(paired=paired),tempfile.TemporaryDirectory() as directory:
                spec,files=fixture();spec['stage']=directory;root=Path(directory);events=[]
                h=Mock();h.create.side_effect=lambda path,data:path.write_bytes(data)
                processes=[Mock() for _ in range(3)]
                for p in processes:
                    p.pid=__import__('os').getpid();p.poll.return_value=None;p.wait.return_value=0
                processes[1].wait.side_effect=lambda **kw:events.append(('wait',kw['timeout'])) or 0
                connection=Mock();connection.__enter__=Mock();connection.__exit__=Mock()
                def gate(*args):events.append(('gate',0));return {'state':'passed'}
                with patch.object(a,'idle'),patch.object(a,'prior_guard'),patch.object(a,'run',return_value=''),\
                        patch.object(a.signal,'signal'),patch.object(a.socket,'create_connection',return_value=connection),\
                        patch.object(a.subprocess,'Popen',side_effect=processes),patch.object(a,'functional_gate',side_effect=gate),\
                        patch.object(a,'live_pairing',return_value={'observed':paired}),\
                        patch.object(a.time,'monotonic',side_effect=[0,1,901,902]):
                    a.capture(h,spec,files)
                self.assertEqual(events[:2],[('gate',0),('wait',930)])
                self.assertEqual(json.loads((root/'terminal.json').read_bytes())['phase'],'captured' if paired else 'held')

    def test_terminal_acceptance_requires_functionality_and_both_endpoints(self):
        spec,files=fixture();files['spec.json']=a.encoded(spec)
        report={'phase':'captured','restored':True,'continuity':True,
                'functional_gate':{'state':'passed'},'pairing':{'observed':True}}
        results={k:copy.deepcopy(report) for k in spec['endpoints']}
        self.assertEqual(a.terminal_receipt(spec,files,'x',results)['state'],'acquisition_capture_accepted')
        for field in ('restored','continuity','functional_gate','pairing'):
            bad=copy.deepcopy(report);bad[field]=False if field in ('restored','continuity') else {}
            with self.assertRaises(ValueError):a.terminal_receipt(spec,files,'x',{k:bad for k in results})
        with self.assertRaises(ValueError):a.terminal_receipt(spec,files,'x',{spec['endpoints'][0]:report})
        held=dict(report,phase='held',functional_gate={'state':'failed'},pairing={'observed':False})
        receipt=a.terminal_receipt(spec,files,'x',{k:held for k in results})
        self.assertEqual(receipt['state'],'acquisition_held_restored')
        self.assertFalse(receipt['receiver_timing_accepted'])

    def test_held_readback_preserves_partial_logs_and_allows_diagnostic_cleanup(self):
        spec,files=fixture()
        with tempfile.TemporaryDirectory() as directory:
            spec.update(stage=directory,members={});root=Path(directory);root.chmod(0o700)
            documents={'spec.json':spec,'restoration.json':{'restored':True},
                       'serial-before.json':{'identity':{},'termios':'saved'},
                       'terminal.json':{'phase':'held','functional_gate':{'state':'failed'}},
                       'functional-gate.json':{'state':'failed'}}
            for name,value in documents.items():(root/name).write_bytes(a.encoded(value))
            (root/'shm-after.txt').write_bytes(files['prior-shm-after.txt'])
            h=Mock();h.read.side_effect=lambda p,**kw:p.read_bytes()
            with patch.object(a,'identity'),patch.object(a,'bootstrap',return_value=h),patch.object(a,'context'),\
                    patch.object(a,'prior_guard'),patch.object(a,'idle'),patch.object(a,'serial_identity',return_value={}),\
                    patch.object(a,'run',side_effect=['inactive','saved','inactive','saved']):
                report=a.entry(spec,files,'readback')
                cleanup=a.entry(spec,files,'cleanup')
            self.assertEqual(report['phase'],'held');self.assertTrue(report['restored'])
            self.assertNotIn('gpsd-process.txt',report['evidence'])
            self.assertEqual(cleanup['phase'],'cleaned');self.assertTrue((root/'terminal.json').exists())

    def version_packet(self):
        body=b'ROM CORE 3.01'.ljust(30,b'\0')+b'00080000'.ljust(10,b'\0')+b'PROTVER=18.00'.ljust(30,b'\0')
        payload=b'\x0a\x04'+len(body).to_bytes(2,'little')+body
        first=second=0
        for byte in payload:first=(first+byte)&255;second=(second+first)&255
        return b'\xb5\x62'+payload+bytes((first,second))

    def test_receiver_version_parser_rejects_corruption_and_partial_response(self):
        packet=self.version_packet()
        self.assertEqual(receiver.version_response(b'$GPGGA,...\r\n'+packet)['extensions'],['PROTVER=18.00'])
        self.assertIsNone(receiver.version_response(packet[:-1]))
        for bad in (packet[:-1]+bytes((packet[-1]^1,)),b'\xb5\x62\x0a\x04\xff\xff'):
            with self.assertRaises(ValueError):receiver.version_response(bad)

    def test_receiver_query_is_single_and_never_retries_short_write(self):
        identity={'target':'/dev/ttyAMA0','rdev':1,'ino':2};api=Mock()
        api.serial_identity.return_value=identity;api.encoded=a.encoded;h=Mock()
        h.read.return_value=a.encoded({'identity':identity})
        import stat
        for short in (False,True):
            with self.subTest(short=short),patch.object(receiver.os,'open',return_value=123),\
                    patch.object(receiver.os,'fstat',return_value=Mock(st_mode=stat.S_IFCHR,st_rdev=1,st_ino=2)),\
                    patch.object(receiver.os,'write',return_value=7 if short else 8) as write,\
                    patch.object(receiver.os,'read',return_value=self.version_packet()),\
                    patch.object(receiver.os,'close') as close,\
                    patch.object(receiver.select,'select',return_value=([123],[],[])):
                if short:
                    with self.assertRaises(ValueError):receiver.poll_version(api,h,Path('/fixture'))
                else:self.assertEqual(receiver.poll_version(api,h,Path('/fixture'))['hardware'],'00080000')
                write.assert_called_once_with(123,receiver.QUERY);close.assert_called_once_with(123)

    def test_receiver_query_timeout_retains_evidence_without_retry(self):
        import stat
        api=Mock();api.encoded=a.encoded
        api.serial_identity.return_value={'target':'/dev/ttyAMA0','rdev':1,'ino':2};h=Mock()
        h.read.return_value=a.encoded({'identity':api.serial_identity.return_value})
        with patch.object(receiver.os,'open',return_value=123),\
                patch.object(receiver.os,'fstat',return_value=Mock(st_mode=stat.S_IFCHR,st_rdev=1,st_ino=2)),\
                patch.object(receiver.os,'write',return_value=8) as write,patch.object(receiver.os,'close'),\
                patch.object(receiver.time,'monotonic',side_effect=[0,11]):
            with self.assertRaisesRegex(ValueError,'timeout'):receiver.poll_version(api,h,Path('/fixture'))
        write.assert_called_once();self.assertEqual(h.create.call_args.args[0].name,'receiver-response.bin')

    def test_receiver_device_drift_is_rejected_before_open_or_write(self):
        api=Mock();api.serial_identity.return_value={'rdev':2};h=Mock()
        h.read.return_value=a.encoded({'identity':{'rdev':1}})
        with patch.object(receiver.os,'open') as opened,patch.object(receiver.os,'write') as write:
            with self.assertRaisesRegex(ValueError,'identity changed'):receiver.poll_version(api,h,Path('/fixture'))
        opened.assert_not_called();write.assert_not_called()

    def test_identity_recipe_cannot_enable_writes_or_extend_timeout(self):
        recipe=json.loads((ROOT/'configs/receiver-runtime-inputs.json').read_bytes())
        a.validate_recipe(recipe)
        for field,value in [('query_hex','b562060000000618'),('query_timeout_seconds',900),('receiver_configuration_writes',True)]:
            with self.assertRaises(ValueError):a.validate_recipe(dict(recipe,**{field:value}))
        spec,files=fixture();spec['purpose']='receiver-runtime-inputs';files['recipe.json']=a.encoded(recipe)
        spec['members']={n:a.sha(v) for n,v in files.items()};a.validate(spec,files)
        self.assertIn('--property=RuntimeMaxSec=120',a.unit_command(spec))
        self.assertIn('exactly one UBX MON-VER',a.review(spec))

    def test_receiver_inspection_records_failure_and_uses_no_acquisition(self):
        for succeeds in (False,True):
            with self.subTest(succeeds=succeeds),tempfile.TemporaryDirectory() as directory:
                root=Path(directory);spec,files=fixture();spec['stage']=directory
                api=Mock();api.encoded=a.encoded;api.publish_gate=lambda h,r,g:a.publish_gate(h,r,g)
                h=Mock();h.create.side_effect=lambda p,b:p.write_bytes(b)
                with patch.object(receiver,'poll_version',return_value={'software':'fixture'}) as poll,\
                        patch.object(receiver,'runtime_metadata',return_value={'files':{}}) as metadata:
                    if not succeeds:poll.side_effect=ValueError('no response')
                    receiver.capture(api,h,spec,files)
                terminal=json.loads((root/'terminal.json').read_bytes())
                self.assertEqual(terminal['phase'],'captured' if succeeds else 'held')
                self.assertFalse(terminal['receiver_timing_accepted'])
                self.assertEqual(metadata.called,succeeds)
                api.run.assert_called_once()
                self.assertEqual(api.run.call_args.args[0][0],'/usr/bin/stty')
                self.assertIn('-echo',api.run.call_args.args[0])
                self.assertIn('-ixoff',api.run.call_args.args[0])

    def test_runtime_metadata_retains_missing_paths_and_rejects_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);regular=root/'leap';regular.write_text('fixture')
            missing=root/'missing';api=Mock();api.sha=a.sha;api.run.return_value='fixture'
            h=Mock();h.read.side_effect=lambda p,**kw:p.read_bytes()
            with patch.object(receiver,'FILES',(str(regular),str(missing))),patch.object(receiver,'DIRECTORIES',(str(root),)):
                report=receiver.runtime_metadata(api,h)
                self.assertIsNone(report['files'][str(missing)])
                self.assertEqual(report['files'][str(regular)]['sha256'],a.sha(b'fixture'))
                missing.symlink_to(regular)
                with self.assertRaisesRegex(ValueError,'file type'):receiver.runtime_metadata(api,h)


if __name__=='__main__':unittest.main()
