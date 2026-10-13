#!/usr/bin/python3
"""Offline configuration/reboot gates, recovery and sealed controller regressions."""
import argparse
import base64
import copy
from contextlib import nullcontext
import importlib.util
import json
import os
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[1]


def module(name):
    spec=importlib.util.spec_from_file_location('test_'+name.replace('-','_'),ROOT/'scripts'/name)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result


s=module('host-configuration-stage.py');c=module('run-host-configuration.py');n=c.n


class Recipes(unittest.TestCase):
    def test_recipes_and_no_activation_boundary(self):
        for kind in ('hardware','runtime'):
            recipe=json.loads((ROOT/'configs'/('host-'+kind+'-recipe.json')).read_bytes())
            s.validate_recipe(kind,recipe)
            recipe['receiver_io_authorized']=True
            with self.assertRaises(ValueError):s.validate_recipe(kind,recipe)
        recipe=json.loads((ROOT/'configs/host-runtime-recipe.json').read_bytes())
        recipe['service_activation_authorized']=True
        with self.assertRaises(ValueError):s.validate_recipe('runtime',recipe)

    def test_preserve_unrelated_boot_and_storage_settings(self):
        config='# Existing\narm_boost=1\n[pi5]\ndtoverlay=nospi10\n[all]\n'
        command='console=serial0,115200 console=tty1 root=PARTUUID=fixture rootwait\n'
        a,b=s.render_boot(config,command)
        self.assertTrue(a.startswith(config.encode()));self.assertIn(b'dtoverlay=pps-gpio,gpiopin=18',a)
        self.assertIn(b'dtoverlay=i2c-rtc,rv3028',a)
        self.assertEqual(b,b'console=tty1 root=PARTUUID=fixture rootwait\n')

    def test_ambiguous_boot_inputs_hold(self):
        command='console=serial0,115200 root=PARTUUID=fixture'
        for config in ('include usercfg.txt\n','enable_uart=0\n','[pi4]\ndtoverlay=pps-gpio,gpiopin=4\n',
                       'dtoverlay=i2c-rtc,ds3231\n','dtoverlay=miniuart-bt\n'):
            with self.subTest(config=config),self.assertRaises(ValueError):s.render_boot(config,command)
        for line in (command+'\nroot=other',command+' console=serial0,115200',command+' console=ttyAMA0,115200',
                     command.replace('root=PARTUUID=fixture',''),command+'\r\n'):
            with self.subTest(line=line),self.assertRaises(ValueError):s.render_boot('',line)

    def test_pps_controller_gpio_polarity_not_assumed(self):
        controller=struct.pack('>I',12)
        s.pps_mapping(struct.pack('>III',12,18,0),controller,False)
        for cells,falling in ((struct.pack('>III',13,18,0),False),(struct.pack('>III',12,4,0),False),
                              (struct.pack('>III',12,18,1),False),(struct.pack('>III',12,18,0),True),(b'',False)):
            with self.assertRaises(ValueError):s.pps_mapping(cells,controller,falling)

    def test_console_cannot_stage_a_new_operation_or_use_an_arbitrary_directory(self):
        with self.assertRaisesRegex(ValueError,'retained'):s.console_inputs(Path('/tmp/arbitrary-stage'))
        with patch.object(s.sys,'argv',['worker','--root','/var/lib/ntp-host-fixture','--mode','start']),patch.object(s,'console_inputs') as inputs:
            with self.assertRaises(SystemExit) as caught:s.main()
            self.assertEqual(caught.exception.code,2);inputs.assert_not_called()

    def test_reboot_observation_ignores_only_boot_pid_restart_counters(self):
        before={'boot_id':'old','services':'Id=example\nMainPID=123\nNRestarts=1\nActiveState=active',
                'inventory':{'example':['1','ii ']},'python':{},'active_daemons':[]}
        after=copy.deepcopy(before);after.update(boot_id='new',services='Id=example\nMainPID=456\nNRestarts=0\nActiveState=active')
        self.assertFalse(s.observation_equal(after,before));self.assertTrue(s.observation_equal(after,before,True))
        same_boot=copy.deepcopy(after);same_boot['boot_id']='old'
        self.assertFalse(s.observation_equal(same_boot,before))
        after['inventory']['example'][0]='2';self.assertFalse(s.observation_equal(after,before,True))
        after=copy.deepcopy(before);after['services']=before['services'].replace('active','inactive')
        self.assertFalse(s.observation_equal(after,before,True))

    def test_time_units_ignore_execstart_timestamps_but_keep_ownership_state(self):
        text='Id=systemd-timesyncd.service\nActiveState=active\nUser=systemd-timesync\nExecStart=start_time=old\n'
        self.assertEqual(s.unit_states(text),s.unit_states(text.replace('start_time=old','start_time=new')))
        self.assertNotEqual(s.unit_states(text),s.unit_states(text.replace('active','inactive')))
        with self.assertRaises(ValueError):s.unit_states(text+'\n'+text)


class Transaction(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)/'stage';self.root.mkdir(mode=0o700)
        self.tx=s.Transaction.__new__(s.Transaction);self.tx.root=self.root
        self.tx.spec={'operation':'hardware','operation_id':'fixture-hardware','hostname':'j2-svntp1','boot_id':'old',
                      'prepared_epoch':1,'expires_epoch':9999999999,'members':{},
                      'recipe':{'ipv4_address':'10.1.0.51/22','ipv6_address':'fd36:5aa8:6971:1::51/64'}}
        self.tx.recipe={};self.calls=[]
        self.tx.h=SimpleNamespace(read=lambda p,**kw:p.read_bytes(),sha=c.c.sha,sync=Mock(),OWNER=os.getuid())
        def create(path,data,mode=0o600):
            with path.open('xb') as f:f.write(data)
            path.chmod(mode)
        self.tx.h.create=create
        self.tx.h.replace=lambda p,data,mode:p.write_bytes(data)
        self.core=n.s.Transaction.__new__(n.s.Transaction);self.core.root=self.root;self.core.h=self.tx.h
        self.core.lock=lambda:nullcontext();self.tx.core=self.core
        self.tx.state=self.core.state;self.tx.write=self.core.write
        self.tx.write('state.json',{'phase':'staged','boot_id':'old'});self.tx.write('before.json',{'registry':{}})
        self.tx.preflight=Mock();self.tx.network_checks=Mock();self.tx.continuity=Mock();self.tx.run=self.run_command
        self.boot={p:{'sha256':'before-'+str(i),'base64':base64.b64encode(('original'+str(i)).encode()).decode(),
                        'uid':0,'gid':0,'mode':0o644} for i,p in enumerate(s.BOOT_PATHS)}

    def run_command(self,argv,**kwargs):
        self.calls.append(argv)
        if argv[0]=='/usr/bin/systemd-run':
            self.assertIn(self.tx.state()['phase'],('reboot_submitted','recovery_reboot_submitted'))
        return ''

    def test_preflight_failure_never_replaces_boot_files(self):
        self.tx.preflight.side_effect=ValueError('drift');self.tx.h.replace=Mock()
        with self.assertRaisesRegex(ValueError,'drift'):self.tx.apply()
        self.tx.h.replace.assert_not_called();self.assertEqual(self.tx.state()['phase'],'apply_held')

    def test_one_apply_preserves_before_state_and_requires_reboot(self):
        self.tx.write('before.json',{'registry':{},'boot_files':self.boot})
        for i,name in enumerate(('config-candidate.txt','cmdline-candidate.txt')):
            (self.root/name).write_bytes(('candidate'+str(i)).encode());self.tx.spec['members'][name]='candidate-'+str(i)
        self.tx.h.read=lambda p,**kw:p.read_bytes() if p.parent==self.root else ('original'+str(s.BOOT_PATHS.index(str(p)))).encode()
        self.tx.h.sha=lambda data:'before-'+data.decode()[-1] if data.startswith(b'original') else 'candidate-'+data.decode()[-1]
        self.tx.h.replace=Mock()
        with patch.object(s,'boot_id',return_value='old'):self.tx.apply()
        self.assertEqual(self.tx.h.replace.call_count,2);self.assertEqual(self.tx.state()['phase'],'boot_files_prepared')
        with self.assertRaisesRegex(ValueError,'consumed'):self.tx.apply()

    def test_reboot_requires_console_and_is_one_shot_even_lost_response(self):
        self.tx.write('state.json',{'phase':'boot_files_prepared','boot_id':'old'})
        with self.assertRaisesRegex(ValueError,'console'):self.tx.schedule_reboot(False)
        with patch.object(s,'boot_id',return_value='old'):self.tx.schedule_reboot(True)
        self.assertEqual(len(self.calls),1)
        with self.assertRaisesRegex(ValueError,'eligible'):self.tx.schedule_reboot(True)
        self.tx.write('state.json',{'phase':'boot_files_prepared','boot_id':'old'});self.tx.run=Mock(side_effect=ValueError('lost'))
        with patch.object(s,'boot_id',return_value='old'),self.assertRaisesRegex(ValueError,'lost'):self.tx.schedule_reboot(True)
        self.assertEqual(self.tx.state()['phase'],'reboot_submitted')

    def test_boot_recovery_checks_both_before_restoring_either(self):
        self.tx.write('state.json',{'phase':'apply_held','boot_id':'old'})
        self.tx.write('before.json',{'registry':{},'boot_files':self.boot})
        self.tx.spec['members']={'config-candidate.txt':'after0','cmdline-candidate.txt':'after1'}
        self.tx.snapshot_file=lambda p:dict(self.boot[str(p)],sha256='after0' if str(p)==s.BOOT_PATHS[0] else 'unrelated')
        self.tx.restore_file=Mock()
        with self.assertRaisesRegex(ValueError,'drift'):self.tx.recover()
        self.tx.restore_file.assert_not_called()

    def test_interrupted_two_file_edit_recovers_without_reboot(self):
        self.tx.write('state.json',{'phase':'apply_held','boot_id':'old'})
        self.tx.write('before.json',{'registry':{},'boot_files':self.boot})
        self.tx.spec['members']={'config-candidate.txt':'after0','cmdline-candidate.txt':'after1'}
        self.tx.snapshot_file=lambda p:dict(self.boot[str(p)],sha256='after0') if str(p)==s.BOOT_PATHS[0] else self.boot[str(p)]
        self.tx.restore_file=Mock()
        with patch.object(s,'boot_id',return_value='old'):self.tx.recover()
        self.assertEqual(self.tx.restore_file.call_count,2);self.assertEqual(self.tx.state()['phase'],'recovered')
        self.assertFalse(self.calls)

    def test_recovery_after_reboot_requires_another_explicit_console_gate(self):
        self.tx.write('state.json',{'phase':'apply_held','boot_id':'old'})
        self.tx.write('before.json',{'registry':{},'boot_files':self.boot})
        self.tx.spec['members']={'config-candidate.txt':'after0','cmdline-candidate.txt':'after1'}
        self.tx.snapshot_file=lambda p:self.boot[str(p)];self.tx.restore_file=Mock()
        with patch.object(s,'boot_id',return_value='new'):self.tx.recover()
        self.assertEqual(self.tx.state()['phase'],'recovery_files_restored')
        with self.assertRaisesRegex(ValueError,'console'):self.tx.schedule_reboot(False,True)
        with patch.object(s,'boot_id',return_value='new'):self.tx.schedule_reboot(True,True)
        self.assertEqual(self.tx.state()['phase'],'recovery_reboot_submitted')
        self.tx.recover()
        self.assertEqual(self.tx.state()['phase'],'recovery_reboot_submitted')
        with self.assertRaisesRegex(ValueError,'eligible'):self.tx.schedule_reboot(True,True)

    def proof(self):
        return {'phase':'ready','hostname':'j2-svntp1','boot_id':'new','spec_sha256':c.c.sha(s.encoded(self.tx.spec)),
                'checks':dict.fromkeys(s.HARDWARE_LABELS,True),'hardware':{'uart_alias':'/dev/serial0'}}

    def test_accept_requires_both_bound_endpoints_and_true_labels(self):
        self.tx.write('state.json',{'phase':'reboot_submitted','boot_id':'old'});self.tx.probe=Mock(return_value=self.proof())
        proofs={host:self.proof() for host in ('10.1.0.51','fd36:5aa8:6971:1::51')}
        for altered in ({'10.1.0.51':self.proof()},dict(proofs,**{'10.1.0.51':dict(self.proof(),boot_id='wrong')})):
            with self.assertRaises(ValueError):self.tx.accept(altered)
        altered=copy.deepcopy(proofs);altered['10.1.0.51']['checks']['pps']=1
        with self.assertRaises(ValueError):self.tx.accept(altered)
        with patch.object(s,'boot_id',return_value='new'):self.tx.accept(proofs)
        self.assertEqual(self.tx.state()['phase'],'accepted')
        with self.assertRaisesRegex(ValueError,'consumed'):self.tx.accept(proofs)

    def test_probe_requires_new_boot_and_correct_phase(self):
        self.tx.write('state.json',{'phase':'reboot_submitted','boot_id':'old'})
        with patch.object(s,'boot_id',return_value='old'),self.assertRaisesRegex(ValueError,'new boot'):self.tx.probe()
        self.tx.hardware_metadata=Mock(return_value={'uart_alias':'/dev/serial0'})
        with patch.object(s,'boot_id',return_value='new'):self.assertEqual(self.tx.probe()['checks'].keys(),s.HARDWARE_LABELS)

    def test_runtime_requires_exact_accepted_hardware_and_boot(self):
        raw=s.encoded({'host_recipe':{'fixture':'hardware'}})
        self.tx.spec['hardware_prerequisite']={'stage':str(self.root),'spec_sha256':c.c.sha(raw)}
        (self.root/'spec.json').write_bytes(raw)
        state={'phase':'accepted','accepted_boot_id':'new','accepted_epoch':int(s.time.time()),'checks':dict.fromkeys(s.HARDWARE_LABELS,True),'hardware':{'uart':'fixture'}}
        self.tx.hardware_metadata=Mock(return_value=state['hardware'])
        self.tx.write('state.json',state)
        with patch.object(s,'boot_id',return_value='new'):self.assertEqual(self.tx.hardware_gate(),state)
        with patch.object(s,'boot_id',return_value='old'),self.assertRaisesRegex(ValueError,'hardware'):self.tx.hardware_gate()
        state['checks']['rtc']=False;self.tx.write('state.json',state)
        with patch.object(s,'boot_id',return_value='new'),self.assertRaises(ValueError):self.tx.hardware_gate()

    def test_runtime_recovery_holds_unrecorded_account_or_cache_mutation(self):
        self.tx.spec['operation']='runtime';self.tx.recipe={'cache_path':'/etc/ld.so.cache'}
        before={'registry':{},'cache':{'sha256':'before'},'accounts':{'users':{},'groups':{}}}
        self.tx.write('before.json',before);self.tx.accounts=Mock(return_value={'users':{'ntp':{}},'groups':{}})
        with self.assertRaisesRegex(ValueError,'unrecorded account'):self.tx.recover()
        self.tx.accounts.return_value=before['accounts'];self.tx.snapshot_file=Mock(return_value={'sha256':'unrelated'})
        with self.assertRaisesRegex(ValueError,'unrecorded cache'):self.tx.recover()
        self.assertFalse(self.calls)

    def test_accepted_reversal_and_early_cleanup_hold(self):
        with self.assertRaisesRegex(ValueError,'terminal'):self.tx.cleanup()
        self.tx.write('state.json',{'phase':'accepted'})
        with self.assertRaisesRegex(ValueError,'new review'):self.tx.recover()
        self.tx.cleanup();self.assertTrue(self.tx.state()['transient_units_cleaned'])

    def test_runtime_success_only_creates_account_cache_and_private_candidates(self):
        self.tx.spec['operation']='runtime';self.tx.recipe={'cache_path':'/etc/ld.so.cache','cache_refresh':['/usr/sbin/ldconfig','-X']}
        account={'users':{'ntp':{'uid':123,'gid':123,'home':'/nonexistent','shell':'/usr/sbin/nologin'}},
                 'groups':{'ntp':{'gid':123,'members':[]}}}
        self.tx.accounts=Mock(return_value=account);self.tx.snapshot_file=Mock(return_value={'sha256':'after'})
        self.tx.hardware_gate=Mock(return_value={'hardware':{'uart_alias':'/dev/serial0'}})
        (self.root/'timeservice-template.json').write_bytes((ROOT/'templates/timeservice.json.example').read_bytes())
        (self.root/'timeservice-template.service').write_bytes((ROOT/'templates/timeservice.service').read_bytes())
        self.tx.spec['members']['timeservice.py']='fixture';self.tx.runtime_validation=Mock()
        with patch.object(s,'load_module',return_value=module('timeservice.py')):self.tx.apply_runtime()
        self.assertEqual(self.tx.state()['phase'],'runtime_prepared')
        self.assertEqual(self.calls[1],['/usr/sbin/ldconfig','-X'])
        candidate=json.loads((self.root/'timeservice-candidate.json').read_bytes())
        self.assertIn('ntp:ntp',candidate['ntpd']);self.assertIn('-m',candidate['ntpd']);self.assertIn('-n',candidate['gpsd'])
        self.assertEqual(candidate['uart_device'],'/dev/serial0')
        self.assertFalse(any('/etc/ntp.conf' in argv or 'start' in argv or 'enable' in argv for argv in self.calls))

    def test_runtime_recovery_restores_cache_and_removes_only_recorded_idle_identity(self):
        self.tx.spec['operation']='runtime';self.tx.recipe={'cache_path':'/etc/ld.so.cache'}
        account={'users':{'ntp':{'uid':987654321}},'groups':{'ntp':{'gid':987654321,'members':[]}}}
        before={'registry':{},'cache':{'sha256':'before'},'accounts':{'users':{},'groups':{}}}
        self.tx.write('before.json',before);self.tx.write('state.json',{'phase':'apply_held','created_account':account,'cache_after':{'sha256':'after'}})
        self.tx.accounts=Mock(side_effect=[account,{'users':{},'groups':account['groups']},before['accounts']]);self.tx.restore_file=Mock()
        self.tx.recover()
        self.tx.restore_file.assert_called_once_with(Path('/etc/ld.so.cache'),before['cache'],{'before','after'})
        self.assertEqual(self.calls,[['/usr/sbin/userdel','ntp'],['/usr/sbin/groupdel','ntp']])
        self.assertEqual(self.tx.state()['phase'],'recovered')


class Preparation(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name);self.root.chmod(0o700)
        self.network_dir=self.root/'network';self.network_dir.mkdir(mode=0o700)
        epoch=int(s.time.time());recipe=json.loads((ROOT/'configs/host-network-recipe.json').read_bytes())
        self.baseline={'collected_epoch':epoch,'observation':{'boot_id':'fixture-boot'},'queries':{},
                       'protected_files':{p:{'base64':base64.b64encode(data).decode(),'sha256':c.c.sha(data)}
                          for p,data in zip(s.BOOT_PATHS,(b'[all]\n',b'console=serial0,115200 root=PARTUUID=fixture rootwait\n'))}}
        self.old={'baseline.json':c.c.encoded(self.baseline),'release.json':(ROOT/'configs/accepted-source-release.json').read_bytes(),
                  'known_hosts':b'fixture'}
        self.network={'schema':1,'operation_id':'fixture-network','stage':'/var/lib/ntp-network-fixture-network',
                      'hostname':recipe['hostname'],'kernel':'fixture-kernel','boot_id':'fixture-boot','ssh':{'host':'10.1.0.137','fingerprint':'fixture'},
                      'old_ipv4':'10.1.0.137','mac':'e4:5f:01:31:fa:d9','original_uuid':'00000000-0000-0000-0000-000000000001',
                      'candidate_name':'ntp-static-fixture-network','recipe':recipe,'snapshot_bundle_sha256':'b'*64,
                      'prepared_epoch':epoch,'expires_epoch':epoch+86400,'reference_hashes':{},
                      'members':{name:c.c.sha(data) for name,data in self.old.items() if name!='known_hosts'}}
        self.old['spec.json']=c.c.encoded(self.network)
        checks=dict.fromkeys(n.s.LABELS,True);uuid='00000000-0000-0000-0000-000000000051';digest=c.c.sha(self.old['spec.json'])
        proof={'hostname':recipe['hostname'],'boot_id':'fixture-boot','spec_sha256':digest,'candidate_uuid':uuid,'checks':checks}
        self.result={'phase':'accepted','candidate_uuid':uuid,'checks':checks,'transient_units_cleaned':True,
                     'ssh_proofs':{recipe[k].split('/')[0]:proof for k in ('ipv4_address','ipv6_address')}}
        receipt={'state':'host_network_accepted','bundle_sha256':'a'*64,'spec_sha256':digest,'snapshot_sha256':'b'*64,
                 'hostname':recipe['hostname'],'candidate_uuid':uuid,'checks':checks,
                 'reboot_persistence_accepted':False,'application_activation_authorized':False}
        for name,record in (('acceptance.json',receipt),('cleanup-result.json',{'bundle_sha256':'a'*64,'result':self.result})):
            path=self.network_dir/name;path.write_bytes(c.c.encoded(record));path.chmod(0o600)
        self.args=argparse.Namespace(kind='hardware',network_dir=self.network_dir,network_sha256='a'*64,
                                    operation_id='fixture-hardware',output=self.root/'hardware')

    def test_seal_both_offline_and_bind_runtime_to_exact_hardware(self):
        with patch.object(n,'prepare',return_value=(self.network,self.old)),patch.object(c.c,'host_key',return_value='fixture'),patch.object(c.subprocess,'run',side_effect=AssertionError('offline preparation contacted a process')):
            hardware=c.seal(self.args);spec,files=c.prepare(Path(hardware['bundle']),hardware['sha256'])
            self.assertEqual(spec['operation'],'hardware');self.assertFalse(hardware['target_contact'])
            self.assertIn(b'root=PARTUUID=fixture',files['cmdline-candidate.txt'])
            runtime_args=argparse.Namespace(**vars(self.args));runtime_args.kind='runtime';runtime_args.operation_id='fixture-runtime'
            runtime_args.output=self.root/'runtime';runtime_args.hardware_dir=self.args.output;runtime_args.hardware_sha256=hardware['sha256']
            runtime=c.seal(runtime_args);rspec,rfiles=c.prepare(Path(runtime['bundle']),runtime['sha256'])
            self.assertEqual(rspec['hardware_prerequisite']['bundle_sha256'],hardware['sha256'])
            self.assertEqual(rspec['hardware_prerequisite']['spec_sha256'],c.c.sha(files['spec.json']))
            self.assertFalse(rspec['host_recipe']['service_activation_authorized'])
            with self.assertRaisesRegex(ValueError,'hash mismatch'):c.prepare(Path(runtime['bundle']),'0'*64)
            rspec['hardware_prerequisite']['spec_sha256']='0'*64
            with self.assertRaisesRegex(ValueError,'conditional hardware'):c.validate(rfiles,rspec)

    def test_fresh_recovered_baseline_binds_new_boot_without_rewriting_network(self):
        baseline=dict(self.baseline,observation={'boot_id':'recovered-boot'},
                      recovery_bundle_sha256='d'*64,release_sha256=c.c.sha(self.old['release.json']))
        raw=c.c.encoded(baseline)
        source={'operation':'host-baseline','hostname':self.network['hostname'],'kernel':self.network['kernel'],
                'recovered_boot_id':'recovered-boot','recovery_bundle_sha256':'d'*64,
                'network_bundle_sha256':'a'*64,'network_spec_sha256':c.c.sha(self.old['spec.json'])}
        rawsource=c.c.encoded(source)
        receipt={'state':'diagnostic_accepted','bundle_sha256':'e'*64,'boot_id':'recovered-boot',
                 'spec_sha256':c.c.sha(rawsource),'baseline_sha256':c.c.sha(raw),'terminal_sha256':'f'*64}
        fresh={'fresh-baseline-spec.json':rawsource,'fresh-baseline-acceptance.json':c.c.encoded(receipt),
               'fresh-baseline-cleanup.json':c.c.encoded({'phase':'cleaned','terminal_sha256':'f'*64})}
        self.args.baseline_dir=self.root/'snapshot';self.args.baseline_sha256='e'*64
        with patch.object(n,'prepare',return_value=(self.network,self.old)),patch.object(c.c,'host_key',return_value='fixture'),patch.object(c,'fresh_baseline_inputs',return_value=(fresh,raw)):
            result=c.seal(self.args);spec,files=c.prepare(Path(result['bundle']),result['sha256'])
            self.assertEqual(spec['schema'],2);self.assertEqual(spec['boot_id'],'recovered-boot')
            self.assertEqual(json.loads(files['network-spec.json'])['boot_id'],'fixture-boot')
            self.assertEqual(files['baseline.json'],raw)
            changed=dict(files,**{'fresh-baseline-cleanup.json':c.c.encoded({'phase':'held'})})
            with self.assertRaisesRegex(ValueError,'fresh baseline'):c.validate_fresh_baseline(changed,spec)
            changed=dict(files,**{'baseline.json':self.old['baseline.json']})
            with self.assertRaises((KeyError,ValueError)):c.validate_fresh_baseline(changed,spec)

    def test_old_baseline_or_failed_network_cleanup_holds_sealing(self):
        self.baseline['collected_epoch']=int(s.time.time())-90000
        self.old['baseline.json']=c.c.encoded(self.baseline)
        with patch.object(n,'prepare',return_value=(self.network,self.old)),self.assertRaisesRegex(ValueError,'fresh'):
            c.seal(self.args)
        self.baseline['collected_epoch']=int(s.time.time());self.old['baseline.json']=c.c.encoded(self.baseline)
        self.result['transient_units_cleaned']=False
        path=self.network_dir/'cleanup-result.json';path.write_bytes(c.c.encoded({'bundle_sha256':'a'*64,'result':self.result}))
        with patch.object(n,'prepare',return_value=(self.network,self.old)),self.assertRaisesRegex(ValueError,'binding'):
            c.seal(self.args)


class Controller(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.directory=Path(tmp.name)
        self.spec={'operation':'hardware','hostname':'j2-svntp1','prepared_epoch':1,'expires_epoch':9999999999,
                   'recipe':{'ipv4_address':'10.1.0.51/22','ipv6_address':'fd36:5aa8:6971:1::51/64'}}
        self.args=argparse.Namespace(bundle=self.directory/'host-configuration.tar',sha256='a'*64,mode='start',console_ready=False)

    def test_start_is_registered_before_submission_and_cannot_replay(self):
        def submit(*args,**kwargs):
            self.assertTrue((self.directory/'start-execution.json').exists());raise ValueError('lost response')
        with patch.object(c,'prepare',return_value=(self.spec,{})),patch.object(c,'remote',side_effect=submit) as remote:
            with self.assertRaisesRegex(ValueError,'lost'):c.execute(self.args)
            with self.assertRaises(FileExistsError):c.execute(self.args)
            self.assertEqual(remote.call_count,1)

    def test_reboot_registration_requires_console_before_contact(self):
        self.args.mode='reboot'
        with patch.object(c,'prepare',return_value=(self.spec,{})),patch.object(c,'remote') as remote:
            with self.assertRaisesRegex(ValueError,'console'):c.execute(self.args)
            remote.assert_not_called();self.assertFalse((self.directory/'reboot-execution.json').exists())

    def test_acceptance_not_retried_after_lost_response(self):
        (self.directory/'start-execution.json').write_bytes(c.c.encoded({'bundle_sha256':'a'*64}))
        (self.directory/'start-execution.json').chmod(0o600)
        self.args.mode='verify';calls=[]
        def remote(*args,**kwargs):
            mode=args[4];calls.append(mode)
            if mode=='accept':raise ValueError('lost acceptance')
            return {'phase':'ready'}
        with patch.object(c,'prepare',return_value=(self.spec,{})),patch.object(c,'remote',side_effect=remote):
            with self.assertRaisesRegex(ValueError,'lost acceptance'):c.execute(self.args)
        self.assertEqual(calls.count('accept'),1)

    def test_failed_endpoint_proof_never_submits_acceptance(self):
        (self.directory/'start-execution.json').write_bytes(c.c.encoded({'bundle_sha256':'a'*64}))
        (self.directory/'start-execution.json').chmod(0o600)
        self.args.mode='verify';calls=[]
        def remote(*args,**kwargs):
            calls.append(args[4])
            if args[5]=='probe-1':raise ValueError('v6 unavailable')
            return {'phase':'ready'}
        with patch.object(c,'prepare',return_value=(self.spec,{})),patch.object(c,'remote',side_effect=remote):
            with self.assertRaisesRegex(ValueError,'v6 unavailable'):c.execute(self.args)
        self.assertNotIn('accept',calls)

    def test_expiry_prevents_registration(self):
        self.spec['expires_epoch']=2
        with patch.object(c,'prepare',return_value=(self.spec,{})),patch.object(c,'remote') as remote:
            with self.assertRaisesRegex(ValueError,'expired'):c.execute(self.args)
            remote.assert_not_called();self.assertFalse((self.directory/'start-execution.json').exists())


if __name__=='__main__':unittest.main()
