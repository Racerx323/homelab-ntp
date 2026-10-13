#!/usr/bin/python3
"""Offline recovery continuation and loopback exception boundaries."""
import argparse
import copy
import importlib.util
import io
import os
from pathlib import Path
import tarfile
import tempfile
import types
import unittest
from unittest.mock import patch

SCRIPT=Path(__file__).resolve().parents[1]/'scripts/run-host-recovery-continuation.py'
s=importlib.util.spec_from_file_location('recovery',SCRIPT);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
OLD='11111111-1111-1111-1111-111111111111'
NEW='22222222-2222-2222-2222-222222222222'
ETH='33333333-3333-3333-3333-333333333333'


class Loopback(unittest.TestCase):
    def setUp(self):
        self.expected={OLD:'loopback',ETH:'802-3-ethernet'}
        self.actual={NEW:'loopback',ETH:'802-3-ethernet'}
        self.fields=dict(m.LOOPBACK,**{'connection.uuid':NEW})

    def test_only_uuid_replacement_normalized_without_mutating_inputs(self):
        before=copy.deepcopy((self.expected,self.actual,self.fields))
        self.assertEqual(m.loopback_registry(self.expected,self.actual,self.fields),self.expected)
        self.assertEqual((self.expected,self.actual,self.fields),before)

    def test_unchanged_uuid_allowed(self):
        fields=dict(self.fields,**{'connection.uuid':OLD})
        self.assertEqual(m.loopback_registry(self.expected,self.expected,fields),self.expected)

    def test_non_loopback_changes_rejected(self):
        for actual in ({NEW:'loopback'},dict(self.actual,extra='bridge'),{NEW:'loopback',ETH:'bridge'}):
            with self.subTest(actual=actual),self.assertRaises(ValueError):
                m.loopback_registry(self.expected,actual,self.fields)

    def test_one_loopback_on_both_sides_required(self):
        for expected,actual in (({ETH:'802-3-ethernet'},self.actual),(self.expected,{ETH:'802-3-ethernet'}),
                                (self.expected,dict(self.actual,extra='loopback'))):
            with self.assertRaises(ValueError):m.loopback_registry(expected,actual,self.fields)

    def test_each_observed_loopback_field_is_binding(self):
        for name in self.fields:
            with self.subTest(name=name),self.assertRaises(ValueError):
                m.loopback_registry(self.expected,self.actual,dict(self.fields,**{name:'changed'}))
        with self.assertRaises(ValueError):
            m.loopback_registry(self.expected,self.actual,dict(self.fields,extra='value'))


class Archive(unittest.TestCase):
    def archive(self,items):
        out=io.BytesIO()
        with tarfile.open(fileobj=out,mode='w') as archive:
            for name,data in items:
                item=tarfile.TarInfo(name);item.size=len(data);archive.addfile(item,io.BytesIO(data))
        return out.getvalue()

    def test_regular_manifest(self):
        data=b'original';raw=self.archive([('known_hosts',data),('manifest.json',m.encoded({'known_hosts':m.sha(data)}))])
        self.assertEqual(m.unpack(raw)['known_hosts'],data)

    def test_duplicates_paths_and_tampering_rejected(self):
        for items in ([('a.txt',b'one'),('a.txt',b'two')],[('../escape',b'bad')],
                      [('a.txt',b'changed'),('manifest.json',m.encoded({'a.txt':'0'*64}))]):
            with self.assertRaises(ValueError):m.unpack(self.archive(items))


class Transport(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.root.chmod(0o700)
        self.args=argparse.Namespace(bundle=self.root/'recovery-continuation.tar',sha256='a'*64,mode='reboot',console_ready=True)
        self.spec={'prepared_epoch':0,'expires_epoch':9999999999,'endpoints':['192.0.2.1','2001:db8::1'],
                   'hostname':'fixture','diagnosed_boot_id':'before'}
        self.files={'spec.json':m.encoded(self.spec)}
        self.real_module=m.module
        self.transport=types.SimpleNamespace(remote=unittest.mock.Mock())
        self.addCleanup(patch.stopall)
        patch.object(m,'prepare',return_value=(self.spec,self.files)).start()
        patch.object(m,'module',side_effect=lambda n:self.transport if n=='run-host-configuration.py' else self.real_module(n)).start()
        patch.object(m.time,'sleep').start()
        self.mask=os.umask(0o077);self.addCleanup(os.umask,self.mask)

    def registered(self):
        self.real_module('run-foundation-preflight.py').write_new(self.root/'reboot-execution.json',{'bundle_sha256':self.args.sha256})

    def test_reboot_uncertainty_consumes_local_mode(self):
        self.transport.remote.side_effect=ValueError('lost response')
        with self.assertRaisesRegex(ValueError,'lost response'):m.execute(self.args)
        with self.assertRaises(FileExistsError):m.execute(self.args)
        self.assertEqual(self.transport.remote.call_count,1)

    def test_console_readiness_required_before_registration(self):
        self.args.console_ready=False
        with self.assertRaises(ValueError):m.execute(self.args)
        self.transport.remote.assert_not_called()
        self.assertFalse((self.root/'reboot-execution.json').exists())

    def test_expiry_prevents_registration(self):
        self.spec['expires_epoch']=1
        with self.assertRaises(ValueError):m.execute(self.args)
        self.transport.remote.assert_not_called()

    def test_no_accept_after_failed_endpoint(self):
        self.registered();self.args.mode='verify';calls=[]
        def remote(*args):
            calls.append(args[4])
            if args[3]=='2001:db8::1':raise ValueError('IPv6 proof failed')
            return {'phase':'recovery_ready'}
        self.transport.remote.side_effect=remote
        with self.assertRaisesRegex(ValueError,'IPv6'):m.execute(self.args)
        self.assertNotIn('accept',calls)

    def test_lost_acceptance_is_not_retried(self):
        self.registered();self.args.mode='verify';calls=[]
        def remote(*args):
            calls.append(args[4])
            if args[4]=='accept':raise ValueError('lost acceptance')
            return {'phase':'recovery_ready'}
        self.transport.remote.side_effect=remote
        with self.assertRaisesRegex(ValueError,'lost acceptance'):m.execute(self.args)
        with self.assertRaises(FileExistsError):m.execute(self.args)
        self.assertEqual(calls.count('accept'),1)

    def test_readback_falls_back_without_reboot(self):
        self.registered();self.args.mode='readback'
        self.transport.remote.side_effect=[ValueError('IPv4 unavailable'),{'phase':'reboot_submitted'}]
        self.assertEqual(m.execute(self.args)['phase'],'reboot_submitted')
        self.assertEqual([c.args[4] for c in self.transport.remote.call_args_list],['readback','readback'])


FAKE_WORKER = b"""
import json,os,types
from pathlib import Path
def identity(spec): pass
def boot_id(): return os.environ['TEST_RECOVERY_BOOT']
class Transaction:
    def __init__(self,spec):
        self.spec=spec;self.root=Path(spec['stage'])
        self.core=types.SimpleNamespace(registry=lambda:spec['actual'])
    def verify(self,files): pass
    def state(self): return json.loads((self.root/'oldstate').read_text())
    def write(self,value): (self.root/'oldstate').write_text(json.dumps(value))
    def before(self): return {'boot_files':{}}
    def run(self,argv): return self.spec['loopback_text']
    def schedule_reboot(self,ready,recovery=False):
        assert ready and recovery
        assert self.core.registry()==self.spec['expected']
        self.write({'phase':'recovery_reboot_submitted'})
        return self.state()
    def probe(self,recovery=False):
        assert recovery and self.core.registry()==self.spec['expected']
        self.write({'phase':'recovered'})
        return {'phase':'recovered','boot_id':boot_id()}
    def cleanup(self):
        assert self.state()['phase']=='recovered'
        return {'transient_units_cleaned':True}
"""


class Worker(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.parent=Path(self.temp.name);self.oldroot=self.parent/'original';self.oldroot.mkdir(mode=0o700)
        (self.oldroot/'oldstate').write_bytes(m.encoded({'phase':'recovery_files_restored'}))
        (self.oldroot/'oldstate').chmod(0o600)
        self.expected={OLD:'loopback',ETH:'802-3-ethernet'}
        self.actual={NEW:'loopback',ETH:'802-3-ethernet'}
        fields=dict(m.LOOPBACK,**{'connection.uuid':NEW})
        self.old={'stage':str(self.oldroot),'members':{},'expected':self.expected,'actual':self.actual,
                  'loopback_text':'\n'.join(k+':'+v for k,v in fields.items())}
        self.diag={'expected_registry':self.expected,'retained_sha256':{'oldstate':m.sha((self.oldroot/'oldstate').read_bytes())}}
        self.spec={'stage':str(self.parent/'continuation'),'prepared_epoch':0,'expires_epoch':9999999999,
                   'diagnosed_boot_id':'diagnosed','endpoints':['v4','v6']}
        self.files=dict.fromkeys(m.INPUTS,b'fixture')
        self.files['helper.py']=(SCRIPT.parent/'foundation-install.py').read_bytes()+b'\nOWNER=os.getuid()\nancestors=lambda path: None\n'
        self.addCleanup(patch.stopall)
        patch.object(m,'bindings',return_value=(self.old,{'host-configuration-stage.py':FAKE_WORKER},self.diag)).start()
        patch.dict(os.environ,{'TEST_RECOVERY_BOOT':'diagnosed'}).start()
        self.mask=os.umask(0o077);self.addCleanup(os.umask,self.mask)

    def test_reboot_new_boot_two_proofs_and_cleanup(self):
        state=m.worker(self.spec,self.files,'reboot',console_ready=True)
        self.assertEqual(state['phase'],'reboot_submitted')
        with self.assertRaisesRegex(ValueError,'new recovery boot'):
            m.worker(self.spec,self.files,'probe')
        os.environ['TEST_RECOVERY_BOOT']='recovered'
        proof=m.worker(self.spec,self.files,'probe')
        result=m.worker(self.spec,self.files,'accept',{'v4':proof,'v6':proof})
        self.assertEqual(result['phase'],'accepted')
        self.assertTrue(m.worker(self.spec,self.files,'cleanup')['transient_units_cleaned'])
        self.assertTrue(self.oldroot.exists())
        self.assertTrue(Path(self.spec['stage']).exists())

    def test_no_second_reboot(self):
        m.worker(self.spec,self.files,'reboot',console_ready=True)
        with self.assertRaises(FileExistsError):m.worker(self.spec,self.files,'reboot',console_ready=True)

    def test_retained_evidence_drift_blocks_submission(self):
        (self.oldroot/'oldstate').write_text('{}')
        with self.assertRaisesRegex(ValueError,'evidence drift'):
            m.worker(self.spec,self.files,'reboot',console_ready=True)
        self.assertEqual((self.oldroot/'oldstate').read_text(),'{}')

    def test_ethernet_drift_stops_reboot_and_preserves_hold(self):
        self.actual[ETH]='bridge'
        with self.assertRaisesRegex(ValueError,'non-loopback'):
            m.worker(self.spec,self.files,'reboot',console_ready=True)
        result=m.worker(self.spec,self.files,'readback')
        self.assertEqual(result['phase'],'reboot_submitting')
        self.assertEqual(result['original']['phase'],'recovery_files_restored')


class Acceptance(unittest.TestCase):
    def test_both_endpoints_same_new_boot_required(self):
        spec={'endpoints':['v4','v6'],'diagnosed_boot_id':'old'}
        proof={'boot_id':'new','checks':{'original_boot_files':True,'new_boot':True,'network_and_native_continuity':True}}
        result={'phase':'accepted','proof':proof,'endpoint_proofs':{'v4':proof,'v6':proof}}
        self.assertEqual(m.acceptance(spec,result),result)
        for key in ('v4','v6'):
            broken=copy.deepcopy(result);del broken['endpoint_proofs'][key]
            with self.assertRaises(ValueError):m.acceptance(spec,broken)
        broken=copy.deepcopy(result);broken['proof']['boot_id']='old'
        with self.assertRaises(ValueError):m.acceptance(spec,broken)


if __name__=='__main__':unittest.main()
