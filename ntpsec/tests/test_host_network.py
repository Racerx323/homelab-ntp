#!/usr/bin/python3
"""Offline network transaction faults, recovery, endpoint gates and immutable sealing."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch, create_autospec

ROOT=Path(__file__).resolve().parents[1]


def load(name,path):
    d=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(d);d.loader.exec_module(m);return m


c=load('network_runner',ROOT/'scripts/run-host-network.py');s=c.s
rfixtures=load('network_runtime_fixtures',ROOT/'tests/test_runtime_discovery.py')


def original():
    values={'connection.id':'Wired connection 1','connection.uuid':'30c72d67-6d27-3d62-8d4d-6ef2e477815b',
        'connection.type':'802-3-ethernet','connection.interface-name':'eth0','connection.autoconnect':'yes',
        'connection.autoconnect-priority':'-999','connection.timestamp':'1',
        'ipv4.method':'auto','ipv6.method':'auto','ipv4.addresses':'','ipv4.gateway':'','ipv4.dns':'',
        'ipv4.ignore-auto-dns':'no','ipv4.dad-timeout':'-1','ipv4.may-fail':'yes',
        'ipv6.addresses':'','ipv6.dns':'','ipv6.ignore-auto-dns':'no','ipv6.may-fail':'yes'}
    return values


def profile_text(values):
    return '\n'.join(k+':'+v.replace('\\','\\\\').replace(':','\\:') for k,v in values.items())+'\n'


class Transaction(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);root=Path(temp.name)/'stage';root.mkdir(mode=0o700)
        self.recipe=json.loads((ROOT/'configs/host-network-recipe.json').read_bytes())
        self.old=original();self.uuid=self.old['connection.uuid'];self.new='00000000-0000-0000-0000-000000000051'
        self.spec={'operation_id':'fixture-network','stage':str(root),'recipe':self.recipe,'original_uuid':self.uuid,
            'candidate_name':'ntp-static-fixture-network','hostname':'j2-svntp1','boot_id':'fixture','mac':'e4:5f:01:31:fa:d9',
            'old_ipv4':'10.1.0.137','prepared_epoch':1,'expires_epoch':9999999999,'members':{}}
        self.tx=s.Transaction.__new__(s.Transaction);self.tx.spec=self.spec;self.tx.root=root;self.tx.r=self.recipe
        self.tx.original=self.old;self.tx.h=SimpleNamespace(OWNER=os.getuid(),read=lambda p,**kw:p.read_bytes(),sync=Mock())
        self.tx.baseline={'queries':{'profile_registry':{'stdout':self.uuid+':802-3-ethernet\n'}}}
        def create(path,data):
            with path.open('xb') as stream:stream.write(data)
            path.chmod(0o600)
        self.tx.h.create=create;self.tx.verify=Mock();self.tx.continuity=Mock()
        self.tx.write('state.json',{'phase':'staged','candidate_uuid':None})
        self.tx.write('before.json',{'registry':{self.uuid:'802-3-ethernet'}})
        self.profiles={self.uuid:copy.deepcopy(self.old)};self.active=self.uuid;self.calls=[];self.failure=None
        self.tx.run=self.run_command;self.tx.profile=lambda uuid:copy.deepcopy(self.profiles[uuid])
        self.tx.registry=lambda:{uuid:'802-3-ethernet' for uuid in self.profiles}
        self.tx.active_uuid=lambda:self.active;self.tx.network=lambda:{'addresses':[]}
        self.tx.preflight=Mock(return_value={'registry':{self.uuid:'802-3-ethernet'}})
        self.tx.resolver=Mock(return_value={'nameservers':[self.recipe['ipv4_dns'],self.recipe['ipv6_dns']]})
        self.tx.checks=Mock(return_value=dict.fromkeys(s.LABELS,True))

    def run_command(self,argv,**kwargs):
        self.calls.append(argv)
        if self.failure and self.failure(argv):raise ValueError('injected command failure')
        if argv[:3]==[s.SYSTEMCTL,'is-active',self.tx.unit('recovery')+'.timer']:return 'active\n'
        if argv[:3]==[s.NM,'connection','clone']:
            state=self.tx.state();self.assertEqual(state['phase'],'armed')
            self.profiles[self.new]=dict(self.old,**{'connection.id':self.spec['candidate_name'],'connection.uuid':self.new})
        elif argv[:3]==[s.NM,'-g','connection.uuid']:
            return self.new+'\n' if self.new in self.profiles else ''
        elif argv[:3]==[s.NM,'connection','modify']:
            self.profiles[argv[4]].update(dict(zip(argv[5::2],argv[6::2])))
        elif argv[:4]==[s.NM,'--wait','45','connection']:
            self.active=argv[6]
        elif argv[:3]==[s.NM,'connection','delete']:
            del self.profiles[argv[4]]
        return ''

    def apply(self):
        with patch.object(s.time,'monotonic',return_value=100):self.tx.apply()

    def test_timer_precedes_profile_mutations_and_candidate_is_separate(self):
        self.apply();self.assertEqual(self.tx.state()['phase'],'applied');self.assertEqual(self.active,self.new)
        self.assertEqual(self.profiles[self.uuid]['connection.autoconnect'],'no')
        candidate=self.profiles[self.new]
        self.assertEqual(candidate['ipv6.method'],'auto');self.assertEqual(candidate['ipv6.addresses'],self.recipe['ipv6_address'])
        self.assertEqual(candidate['ipv4.dad-timeout'],'3000');self.assertEqual(candidate['ipv6.ignore-auto-dns'],'yes')
        with self.assertRaisesRegex(ValueError,'consumed'):self.tx.apply()

    def test_preflight_or_timer_failure_creates_no_profile(self):
        self.tx.preflight.side_effect=ValueError('drift')
        with self.assertRaisesRegex(ValueError,'drift'):self.apply()
        self.assertEqual(self.profiles,{self.uuid:self.old});self.assertFalse(self.calls)
        self.tx.preflight.side_effect=None
        self.failure=lambda a:a[0]=='/usr/bin/systemd-run'
        with self.assertRaises(ValueError):self.tx.arm()
        self.assertEqual(self.profiles,{self.uuid:self.old})

    def test_failures_after_clone_modify_and_activation_restore_original(self):
        for point in ('clone','candidate','original','up'):
            with self.subTest(point=point):
                self.setUp()
                self.failure=lambda a: (point=='clone' and a[:3]==[s.NM,'connection','clone']) or (
                    point=='candidate' and a[:3]==[s.NM,'connection','modify'] and a[4]==self.new) or (
                    point=='original' and a[:3]==[s.NM,'connection','modify'] and a[4]==self.uuid) or (
                    point=='up' and a[:3]==[s.NM,'--wait','45'])
                with self.assertRaises(ValueError):self.apply()
                self.failure=None;state=self.tx.recover()
                self.assertEqual(state['phase'],'recovered');self.assertEqual(self.active,self.uuid)
                self.assertEqual(self.profiles,{self.uuid:self.old})

    def test_crash_after_clone_before_uuid_journal_and_partial_atomic_write(self):
        self.apply();state=self.tx.state();state.update(phase='armed',candidate_uuid=None);self.tx.write('state.json',state)
        self.tx.h.create(self.tx.root/'state.json.new',b'partial atomic write')
        self.assertEqual(self.tx.recover()['phase'],'recovered')
        self.assertEqual(self.profiles,{self.uuid:self.old});self.assertFalse((self.tx.root/'state.json.new').exists())

    def test_unrelated_original_or_candidate_drift_holds_recovery(self):
        for which in (self.uuid,self.new):
            self.setUp();self.apply();self.profiles[which]['ipv4.dns']='10.1.0.99';calls=len(self.calls)
            with self.assertRaisesRegex(ValueError,'drift|outside'):self.tx.recover()
            self.assertEqual(self.tx.state()['phase'],'recovery_held');self.assertEqual(len(self.calls),calls)

    def proofs(self):
        report={'phase':'applied','hostname':self.spec['hostname'],'boot_id':self.spec['boot_id'],
            'spec_sha256':s.sha(s.encoded(self.spec)),'candidate_uuid':self.new,'checks':dict.fromkeys(s.LABELS,True)}
        return {self.recipe[k].split('/')[0]:copy.deepcopy(report) for k in ('ipv4_address','ipv6_address')}

    def test_accept_requires_both_endpoints_all_boolean_checks_and_time_reserve(self):
        self.apply();valid=self.proofs()
        for proofs in ({next(iter(valid)):next(iter(valid.values()))},
                       {k:dict(v,checks=dict(v['checks'],dns=1)) for k,v in valid.items()},
                       {k:dict(v,boot_id='drift') for k,v in valid.items()}):
            with patch.object(s.time,'monotonic',return_value=150):
                with self.assertRaises(ValueError):self.tx.accept(proofs)
        with patch.object(s.time,'monotonic',return_value=360):
            with self.assertRaisesRegex(ValueError,'deadline'):self.tx.accept(valid)
        self.assertEqual(self.tx.state()['phase'],'applied')

    def test_durable_acceptance_precedes_timer_stop_and_suppresses_recovery(self):
        self.apply()
        def stop(argv,**kw):
            if argv[:2]==[s.SYSTEMCTL,'stop']:
                self.assertEqual(self.tx.state()['phase'],'accepted');raise ValueError('lost cancellation response')
            return self.run_command(argv,**kw)
        self.tx.run=stop
        with patch.object(s.time,'monotonic',return_value=150):
            with self.assertRaises(ValueError):self.tx.accept(self.proofs())
        self.assertEqual(self.tx.recover()['phase'],'accepted');self.assertEqual(self.active,self.new)

    def test_profile_unescaping_duplicate_rejection_and_snapshot_stability(self):
        value=original();value['ipv6.addresses']='fd36:5aa8:6971:1::51/64'
        self.assertEqual(s.properties(profile_text(value)),value)
        with self.assertRaisesRegex(ValueError,'unique'):s.properties(profile_text(value)+'ipv4.method:manual\n')
        self.assertEqual(s.stable(value),s.stable(dict(value,**{'connection.timestamp':'999'})))

    def live_network(self):
        return {'addresses':[{'address':self.spec['mac'],'flags':['UP'],'addr_info':[
            {'family':'inet','local':'10.1.0.51','prefixlen':22},
            {'family':'inet6','local':'fd36:5aa8:6971:1::51','prefixlen':64},
            {'family':'inet6','local':'2600:1702:7370:2f40::1234','prefixlen':64}]}],
            'v4_routes':[{'dst':'default','gateway':'10.1.0.1','dev':'eth0'}],
            'v6_routes':[{'dst':'default','protocol':'ra','dev':'eth0'}]}

    def test_real_acceptance_gates_addresses_dad_ra_dns_sources_and_egress(self):
        self.apply();net=self.live_network();self.tx.network=lambda:net
        def command(argv,**kwargs):
            self.calls.append(argv)
            if argv[:3]==[s.NM,'-t','-f']:return 'IP4.DNS[1]:10.1.0.55\nIP6.DNS[1]:fd36\\:5aa8\\:6971\\:1\\:\\:55\n'
            if argv[0]=='/usr/sbin/ip':return json.dumps([{'dev':'eth0','from':argv[-1]}])
            return ''
        self.tx.run=command
        self.assertEqual(s.Transaction.checks(self.tx,self.tx.state()),dict.fromkeys(s.LABELS,True))
        curls=[a for a in self.calls if a[0]=='/usr/bin/curl']
        self.assertEqual(len(curls),2);self.assertTrue(all(a[1]=='--disable' and '--noproxy' in a for a in curls))
        for change in (lambda n:n['addresses'][0]['addr_info'][1].update(tentative=True),
                       lambda n:n['addresses'][0]['addr_info'][0].update(dadfailed=True),
                       lambda n:n['addresses'][0]['addr_info'].pop(),
                       lambda n:n['v6_routes'].clear(),lambda n:n['v4_routes'].clear()):
            net=self.live_network();change(net)
            with self.assertRaises(ValueError):s.Transaction.checks(self.tx,self.tx.state())
        net=self.live_network()
        self.tx.run=lambda a,**kw:'IP4.DNS[1]:10.1.0.99\n'
        with self.assertRaisesRegex(ValueError,'DNS VIP'):s.Transaction.checks(self.tx,self.tx.state())

    def test_verify_rejects_unexpected_entries_changed_modes_and_hashes(self):
        self.tx.spec['members']={'fixture.json':s.sha(b'fixture')}
        self.tx.h.ancestors=Mock();self.tx.h.create(self.tx.root/'fixture.json',b'fixture')
        self.tx.h.create(self.tx.root/'spec.json',s.encoded(self.tx.spec))
        self.tx.h.create(self.tx.root/'manifest.json',s.encoded(self.tx.spec['members']))
        s.Transaction.verify(self.tx)
        self.tx.h.create(self.tx.root/'unexpected',b'preserve')
        with self.assertRaisesRegex(ValueError,'unexpected'):s.Transaction.verify(self.tx)
        (self.tx.root/'unexpected').unlink();(self.tx.root/'fixture.json').chmod(0o644)
        with self.assertRaisesRegex(ValueError,'modes'):s.Transaction.verify(self.tx)
        (self.tx.root/'fixture.json').chmod(0o600);(self.tx.root/'fixture.json').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'drift'):s.Transaction.verify(self.tx)

    def test_native_helper_api_and_absent_boot_file_continuity(self):
        baseline={'observation':{'boot_id':'fixture'},'installed_state':{'accepted':'state'},'protected_files':{}}
        self.tx.baseline=baseline;self.tx.spec['members']['release.json']='a'*64
        self.tx.i=SimpleNamespace(observation=Mock(return_value=baseline['observation']))
        self.tx.cm=SimpleNamespace(inspect_install=create_autospec(c.module('clockmaker.py').inspect_install,
            return_value=baseline['installed_state']))
        s.Transaction.continuity(self.tx)
        self.tx.cm.inspect_install.assert_called_once_with(self.tx.root/'release.json','a'*64)
        self.tx.baseline['protected_files']['/boot/firmware/usercfg.txt']=None
        self.tx.h.read=Mock(return_value=b'new boot include')
        with self.assertRaisesRegex(ValueError,'boot input drift'):s.Transaction.continuity(self.tx)

    def test_command_failure_timeout_streams_and_environment_are_retained(self):
        self.tx.h.ancestors=Mock()
        for process in (SimpleNamespace(returncode=2,stdout=b'partial',stderr=b'error'),
                        subprocess.TimeoutExpired('fixture',1,output=b'timeout output',stderr=b'timeout error')):
            with patch.object(s.subprocess,'run',side_effect=process if isinstance(process,Exception) else None,
                              return_value=process) as run:
                with self.assertRaises(ValueError):s.Transaction.run(self.tx,['/usr/bin/true'])
                self.assertNotIn('HTTP_PROXY',run.call_args.kwargs['env'])
        records=[json.loads(line) for line in (self.tx.root/'commands.jsonl').read_text().splitlines()]
        self.assertEqual([r['exit_status'] for r in records],[2,-124])
        self.assertEqual(records[0]['stdout_base64'],'cGFydGlhbA==')

    def test_recipe_addresses_match_governing_plan(self):
        plan=(ROOT/'docs/ntp-architecture-deployment-plan-v1.0.md').read_text()
        for field in ('ipv4_address','ipv4_gateway','ipv4_dns','ipv6_address','ipv6_dns'):
            self.assertIn(self.recipe[field],plan)

    def test_direct_resolver_view_rejects_stub_extra_or_missing_servers(self):
        self.enterContext(patch.object(s.Path,'lstat',return_value=SimpleNamespace(st_uid=0,st_gid=0)))
        self.enterContext(patch.object(s.Path,'resolve',return_value=s.Path('/run/NetworkManager/resolv.conf')))
        self.tx.h.ancestors=Mock()
        self.tx.h.read=Mock(return_value=b'nameserver 10.1.0.55\nnameserver fd36:5aa8:6971:1::55\n')
        self.assertEqual(len(s.Transaction.resolver(self.tx)['nameservers']),2)
        for data in (b'nameserver 127.0.0.53\n',b'nameserver 10.1.0.55\n',
                     b'nameserver 10.1.0.55\nnameserver fd36:5aa8:6971:1::55\nnameserver 1.1.1.1\n'):
            self.tx.h.read.return_value=data
            with self.assertRaisesRegex(ValueError,'resolver VIP'):s.Transaction.resolver(self.tx)


class Sealing(unittest.TestCase):
    def setUp(self):
        self.fixture=rfixtures.RuntimeDiscovery();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        result,spec,files=self.fixture.seal();self.snapshot=Path(result['bundle']).parent
        report=self.fixture.report(spec,files);uuid=original()['connection.uuid']
        report['queries']['profile_registry']={'exit_status':0,'stdout':uuid+':802-3-ethernet\n'}
        report['queries']['ethernet_profiles']={uuid:{'exit_status':0,'stdout':profile_text(original())}}
        report['queries']['addresses']['stdout']=json.dumps([{'ifname':'eth0','address':'e4:5f:01:31:fa:d9',
            'addr_info':[{'family':'inet','local':spec['ssh']['host'],'prefixlen':22}]}])
        raw=c.c.encoded(report);acceptance={'state':'runtime_discovery_accepted','bundle_sha256':result['sha256'],
            'runtime_sha256':c.c.sha(raw),'release_sha256':c.c.sha(files['release.json']),
            'configuration_ready':False,'activation_authorized':False}
        for name,value in (('runtime.json',report),('acceptance.json',acceptance),
                ('readback-result.json',{'bundle_sha256':result['sha256'],'worker_status':0,'transport_exit_status':0,
                    'report':{'inspection_sha256':c.c.sha(raw),'spec_sha256':c.c.sha(files['spec.json'])}}),
                ('cleanup-result.json',{'bundle_sha256':result['sha256'],'worker_status':0,'transport_exit_status':0,
                    'report':{'state':'snapshot_stage_removed'}})):
            path=self.snapshot/name;path.write_bytes(c.c.encoded(value));path.chmod(0o600)
        recipe=json.loads((ROOT/'configs/host-network-recipe.json').read_bytes());recipe['hostname']=spec['hostname']
        self.recipe=self.snapshot/'network-recipe.json';self.recipe.write_bytes(c.c.encoded(recipe))
        self.args=SimpleNamespace(snapshot_dir=self.snapshot,snapshot_sha256=result['sha256'],recipe=self.recipe,
            operation_id='fixture-network',output=self.snapshot/'network')

    def seal(self):
        with patch.object(c.subprocess,'run') as run:
            result=c.seal(self.args);run.assert_not_called()
        spec,files=c.prepare(Path(result['bundle']),result['sha256']);return result,spec,files

    def test_offline_sealing_hash_identity_reference_binding_and_closed_payloads(self):
        result,spec,files=self.seal();self.assertFalse(result['target_contact'])
        self.assertEqual(set(spec['members']),c.INPUTS)
        for mode in ('start','probe','accept','readback','recover','cleanup'):compile(c.payload(spec,files,mode),'fixture','exec')
        with self.assertRaisesRegex(ValueError,'hash mismatch'):c.prepare(Path(result['bundle']),'0'*64)
        for label in ('architecture','operations','history'):
            self.assertEqual(spec['reference_hashes'][label],c.c.sha(files[label+'.md']))

    def test_unaccepted_snapshot_or_stale_inputs_prevent_sealing(self):
        receipt=json.loads((self.snapshot/'acceptance.json').read_bytes());receipt['activation_authorized']=True
        (self.snapshot/'acceptance.json').write_bytes(c.c.encoded(receipt))
        with self.assertRaisesRegex(ValueError,'binding'):c.seal(self.args)
        self.assertFalse(self.args.output.exists())

    def test_stale_snapshot_and_wrong_recipe_target_prevent_sealing(self):
        with patch.object(c.time,'time',return_value=int(c.time.time())+86401):
            with self.assertRaisesRegex(ValueError,'fresh'):c.seal(self.args)
        recipe=json.loads(self.recipe.read_bytes());recipe['hostname']='wrong-target';self.recipe.write_bytes(c.c.encoded(recipe))
        with self.assertRaises(ValueError):c.seal(self.args)

    def test_lost_acceptance_is_recovered_by_bound_readback_not_resubmission(self):
        result,spec,files=self.seal();args=SimpleNamespace(bundle=Path(result['bundle']),sha256=result['sha256'],mode='readback')
        c.c.write_new(self.args.output/'start-execution.json',{'mode':'start','bundle_sha256':result['sha256']})
        checks=dict.fromkeys(s.LABELS,True);uuid='00000000-0000-0000-0000-000000000051'
        proof={'phase':'applied','hostname':spec['hostname'],'boot_id':spec['boot_id'],
            'spec_sha256':c.c.sha(files['spec.json']),'candidate_uuid':uuid,'checks':checks}
        state={'phase':'accepted','candidate_uuid':uuid,'checks':checks,
            'ssh_proofs':{spec['recipe'][key].split('/')[0]:proof for key in ('ipv4_address','ipv6_address')}}
        with patch.object(c,'remote',return_value=state) as remote:
            c.execute(args);remote.assert_called_once();self.assertEqual(remote.call_args.args[4],'readback')
        self.assertEqual(json.loads((self.args.output/'acceptance.json').read_bytes())['state'],'host_network_accepted')

    def test_start_expiry_lost_terminal_and_replay_never_resubmit(self):
        result,spec,files=self.seal();args=SimpleNamespace(bundle=Path(result['bundle']),sha256=result['sha256'],mode='start')
        with patch.object(c.time,'time',return_value=spec['expires_epoch']),patch.object(c.subprocess,'run') as run:
            with self.assertRaisesRegex(ValueError,'expired'):c.execute(args)
            run.assert_not_called()
        with patch.dict(c.os.environ,{'SSH_AUTH_SOCK':'/fixture/agent'}),patch.object(c.subprocess,'run',return_value=SimpleNamespace(returncode=255)) as run:
            with self.assertRaisesRegex(ValueError,'lost terminal'):c.execute(args)
            with self.assertRaises(FileExistsError):c.execute(args)
            run.assert_called_once()
        self.assertFalse((self.args.output/'acceptance.json').exists())

    def test_recovery_locates_readonly_then_submits_once_despite_lost_response(self):
        result,spec,files=self.seal();args=SimpleNamespace(bundle=Path(result['bundle']),sha256=result['sha256'],mode='recover')
        c.c.write_new(self.args.output/'start-execution.json',{'mode':'start','bundle_sha256':result['sha256']})
        with patch.object(c,'remote',side_effect=[{'phase':'applied'},ValueError('lost terminal')]) as remote:
            with self.assertRaisesRegex(ValueError,'lost terminal'):c.execute(args)
            self.assertEqual(remote.call_count,2)
            self.assertEqual([x.args[4] for x in remote.call_args_list],['readback','recover'])
        with patch.object(c,'remote') as remote:
            with self.assertRaises(FileExistsError):c.execute(args)
            remote.assert_not_called()

    def test_full_verify_probes_both_endpoints_before_acceptance(self):
        result,spec,files=self.seal();args=SimpleNamespace(bundle=Path(result['bundle']),sha256=result['sha256'],mode='verify')
        c.c.write_new(self.args.output/'start-execution.json',{'mode':'start','bundle_sha256':result['sha256']})
        proof={'phase':'applied','hostname':spec['hostname'],'boot_id':spec['boot_id'],
            'spec_sha256':c.c.sha(files['spec.json']),'candidate_uuid':'00000000-0000-0000-0000-000000000051',
            'checks':dict.fromkeys(s.LABELS,True)}
        endpoints=[spec['recipe'][key].split('/')[0] for key in ('ipv4_address','ipv6_address')]
        accepted={'phase':'accepted','checks':proof['checks'],'candidate_uuid':proof['candidate_uuid'],
            'ssh_proofs':dict.fromkeys(endpoints,proof)}
        with patch.object(c,'remote',side_effect=[{'phase':'applied'},proof,proof,accepted]) as remote:
            c.execute(args)
            self.assertEqual([r.args[4] for r in remote.call_args_list],['readback','probe','probe','accept'])
            self.assertEqual([r.args[3] for r in remote.call_args_list[1:3]],endpoints)
        self.assertTrue((self.args.output/'acceptance.json').exists())




class LoopbackRecoveryPolicy(unittest.TestCase):
    def test_only_loopback_uuid_may_change(self):
        expected={'old':'loopback','ethernet':'802-3-ethernet'}
        current={'new':'loopback','ethernet':'802-3-ethernet'}
        fields=dict(s.LOOPBACK_SETTINGS,**{'connection.uuid':'new'})
        self.assertIsNone(s.verify_loopback_registry(expected,current,fields))
        for key in fields:
            with self.subTest(key=key),self.assertRaises(ValueError):
                s.verify_loopback_registry(expected,current,dict(fields,**{key:'changed'}))
        for changed in ({'new':'loopback'},dict(current,extra='bridge'),dict(current,second='loopback')):
            with self.assertRaises(ValueError):s.verify_loopback_registry(expected,changed,fields)

    def test_hardware_calls_opt_in_gate(self):
        hardware=load('loopback_hardware',ROOT/'scripts/host-configuration-stage.py')
        tx=hardware.Transaction.__new__(hardware.Transaction)
        tx.spec={'network_candidate_uuid':'candidate'};tx.net=s
        tx.core=SimpleNamespace(checks=Mock(return_value=dict.fromkeys(s.LABELS,True)))
        tx.network_checks()
        tx.core.checks.assert_called_once_with({'candidate_uuid':'candidate'},allow_loopback_uuid_change=True)


if __name__=='__main__':unittest.main()
