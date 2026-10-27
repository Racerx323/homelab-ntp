#!/usr/bin/python3
"""Offline accepted-installation bindings, static discovery and protected lifecycle tests."""
import base64
import copy
import importlib.util
import json
import os
import shutil
from pathlib import Path
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[1]


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result)
    return result


c=load('runtime_controller',ROOT/'scripts/run-runtime-discovery.py')
i=c.i;s=c.s
fixtures=load('native_install_fixtures',ROOT/'tests/test_source_install.py')


class RuntimeDiscovery(unittest.TestCase):
    def setUp(self):
        self.native=fixtures.Transport();self.native.setUp();self.addCleanup(self.native.doCleanups)
        result=fixtures.c.seal(self.native.args)
        self.installation=Path(result['bundle']).parent
        previous,files=fixtures.c.prepare(Path(result['bundle']),result['sha256'])
        report=self.native.completed_report(previous,files)
        evidence=fixtures.c.validate_acceptance(report,files,previous)
        acceptance={'state':'native_installation_accepted','bundle_sha256':result['sha256'],
            'release_sha256':c.c.sha(files['release.json']),'installed_files':report['installed_files'],
            'terminal_sha256':report['terminal_sha256'],'services_activated':False,'library_cache_changed':False,
            'evidence':evidence}
        readback={'bundle_sha256':result['sha256'],'worker_status':0,'transport_exit_status':0,'report':report}
        for name,value in (('acceptance.json',acceptance),('readback-result.json',readback),
                ('cleanup-result.json',{'bundle_sha256':result['sha256'],'worker_status':0,'transport_exit_status':0,
                    'report':{'state':'installation_payload_removed'}})):
            path=self.installation/name;path.write_bytes(c.c.encoded(value));path.chmod(0o600)
        self.args=SimpleNamespace(installation_dir=self.installation,installation_sha256=result['sha256'],
            operation_id='fixture-runtime-discovery',output=self.native.fixture.root/'runtime')
        # This chain uses a synthetic current-code release, not the production mirror.
        repository = self.native.fixture.root / 'repository'
        repository.mkdir()
        for name in ('scripts', 'tests', 'templates', 'docs', 'HISTORY.md'):
            (repository / name).symlink_to(ROOT / name)
        shutil.copytree(ROOT / 'configs', repository / 'configs')
        (repository / 'configs/accepted-source-release.json').write_bytes(files['release.json'])
        self.mirror = patch.object(c, 'ROOT', repository)
        self.mirror.start()
        self.addCleanup(self.mirror.stop)

    def seal(self):
        with patch.object(c.subprocess,'run') as run:
            result=c.seal(self.args);run.assert_not_called()
        spec,files=c.prepare(Path(result['bundle']),result['sha256'])
        return result,spec,files

    def report(self,spec,files):
        release,build,baseline,state=c.validate_bindings(files,spec)
        parents=json.loads(files['installation-acceptance.json'])['evidence']['before.json']['parents']
        queries={}
        for name in i.QUERIES:
            if name in ('accounts','groups'):
                queries[name]={'exit_status':2,'entries':{},'missing':sorted(i.QUERIES[name][4:])}
            else:
                queries[name]={'exit_status':0,'stdout':'[]' if name in ('addresses','ipv4_routes','ipv6_routes') else ''}
        queries['elf_dependencies']={n:{'exit_status':0,'stdout':''} for n,r in release['files'].items()
            if r['type']=='file' and (n in ('usr/local/sbin/gpsd','usr/local/sbin/ntpd') or i.re.search(r'\.so(?:\.[0-9.]+)?$',n))}
        queries['ethernet_profiles']={}
        return {'schema':1,'collected_epoch':spec['prepared_epoch'],'hostname':spec['hostname'],'kernel':spec['kernel'],
            'release_sha256':spec['members']['release.json'],'installation_acceptance_sha256':spec['members']['installation-acceptance.json'],
            'runtime_recipe_sha256':spec['members']['runtime-recipe.json'],'installed_state':state,'parents':parents,
            'observation':baseline,'protected_files':dict.fromkeys(i.FILE_PATHS),'devices':{'nodes':{},'sysfs':{}},
            'python_environment':i.python_environment(),
            'queries':queries,'continuity_unchanged':True,'configuration_ready':False,'application_mutation_authorized':False,
            'package_mutation_authorized':False,'activation_authorized':False,'receiver_io_authorized':False}

    def test_offline_seal_exact_bindings_and_payload_compilation(self):
        result,spec,files=self.seal()
        self.assertFalse(result['target_contact']);self.assertFalse(result['execution_authorized'])
        self.assertEqual(spec['operation'],'runtime-discovery');self.assertEqual(set(spec['members']),s.required_inputs('runtime-discovery'))
        self.assertEqual(set(files),c.INPUTS|c.EXTRAS)
        self.assertEqual(spec['installation_bundle_sha256'],self.args.installation_sha256)
        self.assertIn('-n',json.loads(files['timeservice.json.example'])['gpsd'])
        for mode in ('collect','readback','cleanup'):compile(c.c.payload(spec,files,spec['prepared_epoch'],mode),'fixture','exec')
        with self.assertRaisesRegex(ValueError,'hash mismatch'):c.prepare(Path(result['bundle']),'0'*64)
        for label,digest in spec['reference_hashes'].items():self.assertEqual(c.c.sha(files[label+'.md']),digest)

    def test_native_hash_or_held_cleanup_prevents_sealing(self):
        self.args.installation_sha256='0'*64
        with patch.object(c.subprocess,'run') as run:
            with self.assertRaisesRegex(ValueError,'archive hash'):c.seal(self.args)
            run.assert_not_called()
        self.assertFalse(self.args.output.exists())

    def test_native_receipt_hash_coverage_and_scope_rejected(self):
        _,spec,files=self.seal()
        for name,mutate in (
                ('installation-readback.json',lambda r:r['report'].update(spec_sha256='0'*64)),
                ('installation-acceptance.json',lambda r:r.update(services_activated=True)),
                ('installation-acceptance.json',lambda r:r['evidence']['journal/receipt.json']['after']['files'].pop(next(iter(r['evidence']['journal/receipt.json']['after']['files'])))),
                ('installation-spec.json',lambda r:r.update(hostname='wrong-target'))):
            changed=dict(files);value=json.loads(changed[name]);mutate(value);changed[name]=c.c.encoded(value)
            with self.assertRaises((ValueError,KeyError)):c.validate_bindings(changed,spec)

    def test_fixed_recipe_rejects_mutating_query_and_device_io(self):
        value=json.loads((ROOT/'configs/runtime-discovery-recipe.json').read_bytes())
        i.recipe(c.c.encoded(value))
        for mutate in (lambda r:r['queries'].append('restart'),lambda r:r.update(receiver_io_authorized=True),
                       lambda r:r['protected_files'].append('/etc/shadow')):
            changed=copy.deepcopy(value);mutate(changed)
            with self.assertRaisesRegex(ValueError,'fixed read-only'):i.recipe(c.c.encoded(changed))

    def test_real_native_receipt_shape_projects_to_canonical_inspection_state(self):
        _,spec,files=self.seal()
        native=json.loads(files['installation-acceptance.json'])['evidence']['journal/receipt.json']['after']
        self.assertEqual(set(native),{'hostname','files'})
        release,_,_,state=c.validate_bindings(files,spec)
        self.assertEqual(set(state),{'release_sha256','previous_sha256','hostname','obsolete','files'})
        self.assertEqual(state['files'],native['files']);self.assertEqual(state['hostname'],native['hostname'])
        self.assertEqual(state['release_sha256'],c.c.sha(files['release.json']))
        self.assertIsNone(state['previous_sha256']);self.assertEqual(state['obsolete'],[])

    def test_accepted_parent_identity_and_created_directory_coverage(self):
        _,spec,files=self.seal();expected=i.native_parents(files)
        changed=copy.deepcopy(expected);changed['/']['inode']+=1
        with self.assertRaisesRegex(ValueError,'parent identity drift'):i.verify_parents(changed,expected)
        value=json.loads(files['installation-acceptance.json']);value['evidence']['created-directories.json']['/extra']={}
        changed_files=dict(files);changed_files['installation-acceptance.json']=c.c.encoded(value)
        with self.assertRaisesRegex(ValueError,'created-directory coverage'):i.native_parents(changed_files)

    def test_report_validation_rejects_coverage_drift_and_forged_evidence(self):
        _,spec,files=self.seal();report=self.report(spec,files)
        release,build,_,_=c.validate_bindings(files,spec);i.validate(report,spec,release,build)
        mutations=(lambda r:r.update(configuration_ready=True),lambda r:r.update(receiver_io_authorized=True),
            lambda r:r['parents'].pop('/'),lambda r:r['installed_state']['files'].pop(next(iter(r['installed_state']['files']))),
            lambda r:r['observation'].update(boot_id='changed'),lambda r:r['queries'].pop('linker_cache'),
            lambda r:r['queries']['elf_dependencies'].clear(),lambda r:r['protected_files'].pop('/etc/ntp.conf'),
            lambda r:r['protected_files'].update({'/etc/shadow':None}),
            lambda r:r['protected_files'].update({'/etc/ntp.conf':{'sha256':'0'*64,'base64':base64.b64encode(b'forged').decode()}}),
            lambda r:r['queries']['accounts'].update(missing=[]),lambda r:r['devices']['nodes'].update({'/dev/random':{}}))
        for mutate in mutations:
            changed=copy.deepcopy(report);mutate(changed)
            with self.assertRaises((ValueError,KeyError)):i.validate(changed,spec,release,build)

    def test_queries_use_sanitized_environment_and_redact_password_fields(self):
        result=SimpleNamespace(returncode=2,stdout=b'ama:secret-field:1000:1000:User:/home/ama:/bin/bash\n',stderr=b'')
        with patch.object(i.subprocess,'run',return_value=result) as run:
            record=i.query(i.QUERIES['accounts'],'accounts')
            self.assertNotIn('secret-field',json.dumps(record));self.assertEqual(record['entries']['ama']['uid'],1000)
            self.assertIn('gpsd',record['missing']);self.assertIn('root',record['missing'])
            kwargs=run.call_args.kwargs
            self.assertNotIn('LD_PRELOAD',kwargs['env']);self.assertEqual(kwargs['timeout'],15)
        for result in (SimpleNamespace(returncode=1,stdout=b'',stderr=b''),
                       SimpleNamespace(returncode=0,stdout=b'',stderr=b'warning'),
                       SimpleNamespace(returncode=0,stdout=b'x'*(2*1024**2+1),stderr=b'')):
            with patch.object(i.subprocess,'run',return_value=result):
                with self.assertRaises(ValueError):i.query(i.QUERIES['linker_cache'])
        with patch.object(i.subprocess,'run',side_effect=subprocess.TimeoutExpired('query',15)):
            with self.assertRaises(subprocess.TimeoutExpired):i.query(i.QUERIES['addresses'])

    def test_ethernet_profile_scope_and_registry_rejection(self):
        uuid='30c72d67-6d27-3d62-8d4d-6ef2e477815b'
        registry={'exit_status':0,'stdout':uuid+':802-3-ethernet\n'+'00000000-0000-0000-0000-000000000001:802-11-wireless\n'}
        with patch.object(i,'query',return_value={'exit_status':0,'stdout':'ipv4.method:auto'}) as run:
            self.assertEqual(set(i.ethernet_profiles(registry)),{uuid})
            run.assert_called_once_with(['/usr/bin/nmcli','-t','-f',
                'connection,802-3-ethernet,ipv4,ipv6','connection','show','uuid',uuid])
        for text in ('invalid:802-3-ethernet\n',registry['stdout']+uuid+':802-3-ethernet\n',
                     '0'*65, (uuid+':802-3-ethernet\n')*65):
            with self.assertRaises(ValueError):i.ethernet_uuids({'exit_status':0,'stdout':text})
        _,spec,files=self.seal();report=self.report(spec,files)
        report['queries']['profile_registry']=registry
        release,build,_,_=c.validate_bindings(files,spec)
        with self.assertRaisesRegex(ValueError,'profile coverage'):i.validate(report,spec,release,build)
        report['queries']['ethernet_profiles']={uuid:{'exit_status':0,'stdout':'ipv4.method:auto'}}
        i.validate(report,spec,release,build)
        report['queries']['ethernet_profiles'][uuid]['exit_status']=1
        with self.assertRaisesRegex(ValueError,'status/bound'):i.validate(report,spec,release,build)

    def test_profile_drift_holds_collection(self):
        _,spec,files=self.seal();report=self.report(spec,files)
        helper=SimpleNamespace(read=lambda p:files[p.name])
        inspector=SimpleNamespace(accepted_inputs=c.module('inspect-source-destinations.py').accepted_inputs,
            observation=Mock(return_value=report['observation']))
        registry={'exit_status':0,'stdout':''}
        with patch.object(i,'load',return_value=inspector), \
             patch.object(i,'installed_state',return_value=(report['installed_state'],report['parents'])), \
             patch.object(i,'protected_files',return_value=report['protected_files']), \
             patch.object(i,'devices',return_value=report['devices']), \
             patch.object(i,'query',return_value=registry), \
             patch.object(i,'ethernet_profiles',side_effect=[{}, {'changed':{}}]):
            with self.assertRaisesRegex(ValueError,'continuity failed'):i.collect(Path('/fixture'),spec,helper,spec['prepared_epoch'])

    def test_static_file_bounds_and_optional_absence(self):
        helper=SimpleNamespace(read=Mock(side_effect=FileNotFoundError))
        with patch.object(i.glob,'glob',return_value=[]):
            self.assertEqual(i.protected_files(helper),dict.fromkeys(i.FILE_PATHS))
        with patch.object(i.glob,'glob',return_value=['/etc/ld.so.conf.d/'+str(n)+'.conf' for n in range(65)]):
            with self.assertRaisesRegex(ValueError,'count bound'):i.protected_files(helper)
        helper.read.side_effect=None;helper.read.return_value=b'content'
        with patch.object(i.glob,'glob',return_value=[]):
            values=i.protected_files(helper)
            self.assertEqual(values['/etc/ntp.conf']['sha256'],c.c.sha(b'content'))
            self.assertTrue(all(call.kwargs['limit']==256*1024 for call in helper.read.call_args_list[-10:]))

    def test_collect_verifies_installed_baseline_and_post_capture_continuity(self):
        _,spec,files=self.seal();report=self.report(spec,files)
        baseline=report['observation'];helper=SimpleNamespace(read=lambda p:files[p.name])
        inspector=SimpleNamespace(accepted_inputs=c.module('inspect-source-destinations.py').accepted_inputs,
            observation=Mock(return_value=baseline))
        state=(report['installed_state'],report['parents'])
        with patch.object(i,'load',return_value=inspector),patch.object(i,'installed_state',return_value=state), \
             patch.object(i,'protected_files',return_value=report['protected_files']),patch.object(i,'devices',return_value=report['devices']), \
             patch.object(i,'query',return_value={'exit_status':0,'stdout':''}) as query:
            observed=i.collect(Path('/fixture'),spec,helper,spec['prepared_epoch'])
            self.assertFalse(observed['configuration_ready']);self.assertTrue(observed['continuity_unchanged'])
            self.assertGreaterEqual(query.call_count,len(i.QUERIES)+2)
            inspector.observation.return_value=dict(baseline,boot_id='changed');query.reset_mock()
            with self.assertRaisesRegex(ValueError,'continuity'):i.collect(Path('/fixture'),spec,helper,spec['prepared_epoch'])
            query.assert_not_called()
            inspector.observation.side_effect=[baseline,dict(baseline,services='changed')]
            with self.assertRaisesRegex(ValueError,'continuity failed'):i.collect(Path('/fixture'),spec,helper,spec['prepared_epoch'])

    def test_controller_expiry_replay_and_held_readback_cleanup(self):
        result,spec,files=self.seal();args=SimpleNamespace(bundle=Path(result['bundle']),sha256=result['sha256'],mode='collect')
        with patch.object(c.time,'time',return_value=spec['expires_epoch']),patch.object(c.subprocess,'run') as run:
            with self.assertRaisesRegex(ValueError,'expired'):c.execute(args)
            run.assert_not_called()
        def submitted(argv,**kw):
            self.assertTrue((self.args.output/(args.mode+'-execution.json')).exists())
            report={'state':'inspection_held','terminal_sha256':'a'*64,'error':'drift'}
            kw['stdout'].write(c.c.encoded(report)+b'PREFLIGHT_EXIT_STATUS=2\n')
            return SimpleNamespace(returncode=2)
        with patch.dict(c.os.environ,{'SSH_AUTH_SOCK':'/fixture/agent'}),patch.object(c.subprocess,'run',side_effect=submitted):
            self.assertEqual(c.execute(args)['worker_status'],2)
            with self.assertRaises(FileExistsError):c.execute(args)
            args.mode='cleanup'
            with self.assertRaises(FileNotFoundError):c.execute(args)
            args.mode='readback';self.assertEqual(c.execute(args)['state'],'inspection_held')
            args.mode='cleanup';self.assertEqual(c.execute(args)['worker_status'],2)
        self.assertFalse((self.args.output/'acceptance.json').exists())

    def test_controller_accepts_only_bound_complete_readback(self):
        result,spec,files=self.seal();observed=self.report(spec,files);raw=c.c.encoded(observed)
        args=SimpleNamespace(bundle=Path(result['bundle']),sha256=result['sha256'],mode='readback')
        def submitted(argv,**kw):
            report={'state':'inspection_completed','inspection_base64':base64.b64encode(raw).decode(),
                    'inspection_sha256':c.c.sha(raw),'spec_sha256':c.c.sha(files['spec.json']),'terminal_sha256':'a'*64}
            kw['stdout'].write(c.c.encoded(report)+b'PREFLIGHT_EXIT_STATUS=0\n')
            return SimpleNamespace(returncode=0)
        with patch.dict(c.os.environ,{'SSH_AUTH_SOCK':'/fixture/agent'}),patch.object(c.subprocess,'run',side_effect=submitted):
            self.assertEqual(c.execute(args)['worker_status'],0)
        receipt=json.loads((self.args.output/'acceptance.json').read_bytes())
        self.assertEqual(receipt['state'],'runtime_discovery_accepted');self.assertFalse(receipt['configuration_ready'])

    def test_lost_terminal_preserves_streams_and_never_resubmits(self):
        result,_,_=self.seal();args=SimpleNamespace(bundle=Path(result['bundle']),sha256=result['sha256'],mode='collect')
        def submitted(argv,**kw):
            kw['stdout'].write(b'incomplete terminal');kw['stderr'].write(b'transport lost')
            return SimpleNamespace(returncode=255)
        with patch.dict(c.os.environ,{'SSH_AUTH_SOCK':'/fixture/agent'}),patch.object(c.subprocess,'run',side_effect=submitted) as run:
            with self.assertRaisesRegex(ValueError,'missing terminal'):c.execute(args)
            with self.assertRaises(FileExistsError):c.execute(args)
            run.assert_called_once()
        self.assertEqual((self.args.output/'collect.stderr').read_bytes(),b'transport lost')
        self.assertFalse((self.args.output/'acceptance.json').exists())

    def test_protected_stage_success_held_readback_and_unknown_cleanup_entry(self):
        _,original,files=self.seal()
        for held in (False,True):
            root=self.native.fixture.root/('held' if held else 'complete');spec=dict(original,stage=str(root))
            inputs={n:files[n] for n in spec['members']}
            worker=SimpleNamespace(ancestors=Mock(),sync=Mock(),read=lambda p:p.read_bytes())
            def create(path,data):
                with path.open('xb') as stream:stream.write(data)
                path.chmod(0o600)
            worker.create=create
            collector=SimpleNamespace(collect=Mock(return_value=self.report(spec,files)),validate=Mock())
            if held:collector.collect.side_effect=ValueError('observed drift')
            definition=SimpleNamespace(loader=SimpleNamespace(exec_module=Mock()))
            with patch.object(s,'identity'),patch.object(s.types,'ModuleType',return_value=worker),patch('builtins.exec'), \
                 patch.object(s.signal,'signal'),patch.object(s.importlib.util,'spec_from_file_location',return_value=definition), \
                 patch.object(s.importlib.util,'module_from_spec',return_value=collector):
                terminal=s.entry(spec,inputs,spec['prepared_epoch'],'collect')
                self.assertEqual(terminal['state'],'inspection_held' if held else 'inspection_completed')
                with self.assertRaises(FileExistsError):s.entry(spec,inputs,spec['prepared_epoch'],'collect')
                readback=s.entry(spec,inputs,spec['prepared_epoch'],'readback')
                extra=root/'unrelated';extra.write_bytes(b'keep')
                with self.assertRaisesRegex(ValueError,'unexpected stage'):s.entry(spec,inputs,spec['prepared_epoch'],'cleanup',readback['terminal_sha256'])
                self.assertTrue(extra.exists());extra.unlink()
                removed=s.entry(spec,inputs,spec['prepared_epoch'],'cleanup',readback['terminal_sha256'])
                self.assertEqual(removed['state'],'snapshot_stage_removed');self.assertFalse(root.exists())


if __name__=='__main__':unittest.main()
