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
    spec={'schema':2,'operation_id':'fixture','stage':'/var/lib/ntp-acquire-fixture',
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


if __name__=='__main__':unittest.main()
