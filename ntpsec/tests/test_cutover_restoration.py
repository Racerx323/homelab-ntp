#!/usr/bin/python3
"""Offline restoration guards, original-comparator replay and mutation boundaries."""
import base64
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[1]


def load(name):
    s=importlib.util.spec_from_file_location(name.replace('-','_'),ROOT/'scripts'/name)
    m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m


m=load('run-cutover-restoration.py');stage=load('service-cutover-stage.py');host=load('host-configuration-stage.py')
c=load('run-service-cutover.py');ins=load('run-cutover-inspection.py')
BOOT='12345678-1234-5678-9abc-123456789abc'
BASE='aaaaaaaa-1234-5678-9abc-123456789abc'
UNIT={'Id':'timeservice.service','LoadState':'not-found','ActiveState':'inactive','SubState':'dead',
      'MainPID':'0','FragmentPath':'','DropInPaths':''}


def text(value):return '\n'.join(k+'='+v for k,v in value.items())+'\n'


def observation(failed=False):
    return {'boot_id':BOOT,'services':text(dict(UNIT,**({'ActiveState':'failed','SubState':'failed'} if failed else {}))),
            'inventory':{'fixture':['1','ii ']},'python':{'version':'fixture'},'active_daemons':[]}


def archive(files):
    files=dict(files);files['manifest.json']=m.encoded({n:m.sha(v) for n,v in files.items() if n!='manifest.json'})
    stream=io.BytesIO()
    with tarfile.open(fileobj=stream,mode='w') as t:
        for n,v in files.items():
            item=tarfile.TarInfo(n);item.size=len(v);t.addfile(item,io.BytesIO(v))
    return stream.getvalue()


def record(raw):return {'sha256':m.sha(raw),'base64':base64.b64encode(raw).decode()}


def fixture():
    old={'purpose':'runtime-diagnostic','hostname':'fixture','kernel':'fixture','boot_id':BOOT,'endpoints':['192.0.2.1','2001:db8::1'],
         'old_ipv4':'192.0.2.1','stage':'/var/lib/ntp-acquire-trial','operation_id':'trial',
         'apply_unit':'ntp-cutover-trial','recovery_unit':'ntp-cutover-trial-recovery','members':{}}
    baseline=observation();baseline['boot_id']=BASE
    fixture_spec=importlib.util.spec_from_file_location('acquisition_fixture',ROOT/'tests/test_gpsd_acquisition.py')
    fixtures=importlib.util.module_from_spec(fixture_spec);fixture_spec.loader.exec_module(fixtures)
    refspec,ref=fixtures.fixture()
    old.update({k:refspec[k] for k in ('hostname','kernel','endpoints','old_ipv4')})
    refspec['boot_id']=BOOT
    rs=json.loads(c.unpack(ref['runtime.tar'])['spec.json']);rs['boot_id']=BASE
    runtime=archive({'spec.json':m.encoded(rs),'baseline.json':m.encoded({'observation':baseline}),
                     'host-configuration-stage.py':b'raise AssertionError("historical hardware code executed")'})
    ref['runtime.tar']=runtime;refspec['runtime_sha256']=m.sha(runtime)
    accepted=json.loads(ref['runtime-acceptance.json']);accepted.update(bundle_sha256=m.sha(runtime),spec_sha256=m.sha(m.encoded(rs)),boot_id=BOOT)
    ref['runtime-acceptance.json']=m.encoded(accepted)
    closure=json.loads(ref['runtime-cleanup.json']);closure['bundle_sha256']=m.sha(runtime);closure['result']['accepted_boot_id']=BOOT
    ref['runtime-cleanup.json']=m.encoded(closure)
    prior=json.loads(c.unpack(ref['prior.tar'])['spec.json']);prior.update(runtime_sha256=m.sha(runtime),boot_id=BOOT)
    ref['prior.tar']=archive({'spec.json':m.encoded(prior)})
    for name in ('prior-acceptance.json','prior-cleanup.json'):
        value=json.loads(ref[name]);value['spec_sha256']=m.sha(m.encoded(prior))
        if 'bundle_sha256' in value:value['bundle_sha256']=m.sha(ref['prior.tar'])
        ref[name]=m.encoded(value)
    value=json.loads(ref['prior-restoration.json']);value['boot_id']=BOOT;ref['prior-restoration.json']=m.encoded(value)
    refspec['members']={n:m.sha(v) for n,v in ref.items()};ref['spec.json']=m.encoded(refspec)
    source={'spec.json':m.encoded(old),'known_hosts':b'fixture key',
            'reference.py':b'raise AssertionError("historical acquisition code executed")',
            'reference.tar':archive(ref)}
    rawsource=archive(source)
    ispec={k:old[k] for k in ('hostname','kernel','boot_id','endpoints','old_ipv4')}
    ispec.update(schema=1,purpose='recovery-inspection',operation_id='inspection-fixture',
                 stage='/var/lib/ntp-inspect-inspection-fixture',source_stage=old['stage'],
                 source_bundle_sha256=m.sha(rawsource),prepared_epoch=200,expires_epoch=86600,journal_since=100,journal_until=3700)
    state={'phase':'recovery_held','apply_epoch':100}
    response={'spec_sha256':m.sha(source['spec.json']),'result':state}
    inspected={n:(ROOT/p).read_bytes() for n,p in ins.PATHS.items()}
    inspected.update({'helper.py':b'# helper fixture','source-spec.json':source['spec.json'],
                      'source-proof.json':m.encoded({'responses':[response,response],'attempt':1,'bundle_sha256':m.sha(rawsource)}),
                      'source-baseline.json':m.encoded({'observation':baseline}),'observation.py':b'# observer fixture',
                      'known_hosts':source['known_hosts'],'launch.sh':ins.launcher(ispec['stage'])})
    ispec['members']={n:m.sha(v) for n,v in inspected.items()}
    inspected.update({'spec.json':m.encoded(ispec),'review.md':ins.review(ispec).encode()})
    rawinspection=archive(inspected);inspected=c.unpack(rawinspection);ispec=json.loads(inspected['spec.json']);ins.validate(ispec,inspected)
    evidence={n:record(b'fixture') for n in ins.HELD_CAPTURE_FILES}
    evidence['continuity.json']=record(m.encoded({'baseline':baseline,'current':observation(True)}))
    report={'phase':'captured','source_preserved':True,'evidence':evidence}
    receipt=ins.terminal_receipt(ispec,inspected,m.sha(rawinspection),dict.fromkeys(old['endpoints'],report))
    proof={'responses':[{'spec_sha256':m.sha(inspected['spec.json']),'result':report}]*2,'acceptance':receipt,
           'cleanup':{'spec_sha256':m.sha(inspected['spec.json']),'result':{'phase':'cleaned','evidence_preserved':True,
                 'source_unchanged':True,'report_sha256':receipt['report_sha256']}},
           'submissions':[{'bundle_sha256':m.sha(rawinspection),'payload_sha256':m.sha(c.payload(ispec,inspected,'readback')),
                           'argv':['ssh','ama@'+e]} for e in old['endpoints']]}
    files={n:(ROOT/p).read_bytes() for n,p in m.PATHS.items()}
    files.update({'source.tar':rawsource,'inspection.tar':rawinspection,'inspection-proof.json':m.encoded(proof),
                  'known_hosts':source['known_hosts']})
    spec={k:old[k] for k in ('hostname','kernel','boot_id','endpoints','old_ipv4')}
    spec.update(schema=1,purpose='cutover-restoration',operation_id='restore-fixture',stage='/var/lib/ntp-restore-restore-fixture',
                source_stage=old['stage'],source_sha256=m.sha(rawsource),inspection_sha256=m.sha(rawinspection),
                prepared_epoch=300,expires_epoch=86700)
    bind(spec,files);return spec,files


def bind(spec,files):
    spec['members']={n:m.sha(files[n]) for n in set(m.PATHS)|m.EXTRA}
    files['spec.json']=m.encoded(spec);files['review.md']=m.review(spec).encode()
    files['manifest.json']=m.encoded({n:m.sha(v) for n,v in files.items() if n!='manifest.json'})


class FailureResetTests(unittest.TestCase):
    def test_original_comparator_already_allows_reboot_metadata(self):
        before=observation();before['boot_id']=BASE
        before['services']='Id=ssh.service\nMainPID=123\nNRestarts=0\n\n'+before['services']
        after=observation(True);after['services']='Id=ssh.service\nMainPID=456\nNRestarts=0\n\n'+after['services']
        self.assertFalse(host.observation_equal(after,before,new_boot=True))
        corrected=m.normalized_observation(after)
        self.assertTrue(host.observation_equal(corrected,before,new_boot=True))
        self.assertFalse(host.observation_equal(corrected,before,new_boot=False))
        for key,value in [('inventory',{}),('python',{}),('active_daemons',[{'pid':1}])]:
            with self.subTest(key=key):self.assertFalse(host.observation_equal(dict(corrected,**{key:value}),before,True))

    def test_reset_is_exact_and_rechecks(self):
        run=Mock(side_effect=[text(dict(UNIT,ActiveState='failed',SubState='failed')),'',text(UNIT)])
        self.assertTrue(stage.clear_restored_failure(run))
        self.assertEqual(run.call_args_list[1].args,('reset-failed','timeservice.service'))
        run=Mock(return_value=text(UNIT));self.assertFalse(stage.clear_restored_failure(run));self.assertEqual(run.call_count,1)

    def test_running_loaded_changed_or_incomplete_unit_never_reset(self):
        for changes in ({'LoadState':'loaded'},{'MainPID':'12'},{'ActiveState':'active','SubState':'running'},
                        {'FragmentPath':'/etc/unexpected'},{'DropInPaths':'/tmp/override'},{'Id':'other'}):
            run=Mock(return_value=text(dict(UNIT,**changes)))
            with self.subTest(changes=changes),self.assertRaises(ValueError):stage.clear_restored_failure(run)
            self.assertEqual(run.call_count,1)
        for raw in (text(UNIT)+'MainPID=0\n',text({k:v for k,v in UNIT.items() if k!='MainPID'})):
            with self.assertRaises(ValueError):stage.clear_restored_failure(Mock(return_value=raw))

    def test_failed_reset_does_not_accept(self):
        failed=text(dict(UNIT,ActiveState='failed',SubState='failed'))
        with self.assertRaises(ValueError):stage.clear_restored_failure(Mock(side_effect=[failed,'',failed]))

    def test_normalization_cannot_hide_other_services_or_unit_changes(self):
        value=observation(True);self.assertEqual(m.normalized_observation(value),observation())
        self.assertEqual(value,observation(True))
        joined=dict(value,services=value['services']+'Id=gpsd.socket\nLoadState=not-found\nActiveState=inactive\n')
        self.assertEqual(m.normalized_observation(joined)['services'],observation()['services']+'Id=gpsd.socket\nLoadState=not-found\nActiveState=inactive\n')
        for raw in ('',value['services']+'MainPID=9\n',value['services'].replace('not-found','loaded')):
            with self.assertRaises(ValueError):m.normalized_observation(dict(value,services=raw))
        modified=dict(value,services='Id=ssh.service\nActiveState=failed\n\n'+value['services'])
        self.assertIn('Id=ssh.service\nActiveState=failed',m.normalized_observation(modified)['services'])


class BindingTests(unittest.TestCase):
    def test_bound_archive_and_all_payload_modes(self):
        spec,files=fixture();m.validate(spec,files)
        for mode in ('start','readback','cleanup'):compile(c.payload(spec,files,mode),mode,'exec')

    def test_identity_scope_and_member_changes_rejected(self):
        spec,files=fixture()
        for k,v in [('boot_id',BASE),('source_sha256','0'*64),('inspection_sha256','0'*64),('operation_id','../bad'),
                    ('source_stage','/tmp/source'),('stage','/tmp/stage'),('expires_epoch',90000),('prepared_epoch',True),
                    ('endpoints',['192.0.2.99'])]:
            with self.subTest(k=k),self.assertRaises(ValueError):m.validate(dict(spec,**{k:v}),files)
        bad=dict(files);bad['corrected-stage.py']+=b'#changed'
        with self.assertRaises(ValueError):m.validate(spec,bad)

    def test_unaccepted_mismatched_or_unbound_inspection_rejected(self):
        for field in ('acceptance','response','cleanup','submission','evidence'):
            spec,files=fixture();p=json.loads(files['inspection-proof.json'])
            if field=='acceptance':p['acceptance']['state']='diagnostics_held'
            elif field=='response':p['responses'][1]['result']['phase']='held'
            elif field=='cleanup':p['cleanup']['result']['source_unchanged']=False
            elif field=='submission':p['submissions'][0]['payload_sha256']='0'*64
            else:p['responses'][0]['result']['evidence']['continuity.json']['sha256']='0'*64
            files['inspection-proof.json']=m.encoded(p);bind(spec,files)
            with self.subTest(field=field),self.assertRaises(ValueError):m.validate(spec,files)

    def test_receipt_requires_matching_terminal_endpoints(self):
        spec,files=fixture();r={'phase':'restoration_verified','restoration_accepted':True,'source_preserved':True,
                              'time_service_accepted':False,'checks':dict.fromkeys(m.CHECKS,True),
                              'evidence':{n:record(b'fixture') for n in m.EVIDENCE}}
        receipt=m.terminal(spec,'a'*64,dict.fromkeys(spec['endpoints'],r));self.assertFalse(receipt['time_service_accepted'])
        for results in ({spec['endpoints'][0]:r},dict(zip(spec['endpoints'],[r,{'phase':'restoration_held'}])),
                        dict.fromkeys(spec['endpoints'],{'phase':'running'}),
                        dict.fromkeys(spec['endpoints'],dict(r,checks={}))):
            with self.assertRaises(ValueError):m.terminal(spec,'a'*64,results)


class RecoveryGuards(unittest.TestCase):
    def test_timer_gate_rejects_running_worker_and_foreign_definition(self):
        old={'recovery_unit':'ntp-cutover-fixture-recovery'}
        def row(suffix,active,sub):
            n=old['recovery_unit']+suffix
            return {'Id':n,'LoadState':'loaded','ActiveState':active,'SubState':sub,
                    'FragmentPath':'/run/systemd/transient/'+n,'DropInPaths':''}
        timer=row('.timer','active','waiting');service=row('.service','inactive','dead')
        self.assertEqual(m.timer_state(Mock(side_effect=[text(timer),text(service)]),old)['timer'],timer)
        for changed in (dict(service,ActiveState='activating',SubState='start'),dict(service,FragmentPath='/etc/foreign'),dict(service,DropInPaths='/tmp/x')):
            with self.assertRaises(ValueError):m.timer_state(Mock(side_effect=[text(timer),text(changed)]),old)

    def test_unrestored_files_or_uart_hold_without_commands_that_change_state(self):
        before={'files':{'/fixture':None},'serial':{'identity':1},'termios':'saved'}
        tx=SimpleNamespace(frozen_destinations={'/fixture':None},frozen_directories={},snapshot=Mock(return_value=None),
                           a=SimpleNamespace(serial_identity=Mock(return_value={'identity':1}),idle=Mock()),run=Mock(return_value='saved\n'))
        m.restored_files(tx,before,{'created_directories':[]})
        tx.snapshot.return_value={'sha256':'foreign'}
        with self.assertRaises(ValueError):m.restored_files(tx,before,{'created_directories':[]})
        tx.snapshot.return_value=None;tx.run.return_value='different'
        with self.assertRaises(ValueError):m.restored_files(tx,before,{'created_directories':[]})
        for call in tx.run.call_args_list:self.assertEqual(call.args[0],['/usr/bin/stty','-F','/dev/serial0','-g'])

    def test_restoration_sequence_and_fail_closed_boundaries(self):
        for failure in (None,'observation','network','files','active-worker'):
            with self.subTest(failure=failure),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);src=root/'source';src.mkdir();dest=root/'continuation';dest.mkdir();runtime_root=root/'runtime';runtime_root.mkdir()
                initial={'phase':'recovery_held','created_directories':[]}
                before={'files':{},'serial':{},'termios':'saved'}
                (src/'state.json').write_bytes(m.encoded(initial));(src/'before.json').write_bytes(m.encoded(before))
                accepted={'created_account':{'ok':True},'cache_after':{'ok':True},'hardware':{'ok':True}}
                retained={'state.json':m.encoded(accepted),'before.json':b'{}'}
                for n,v in retained.items():(runtime_root/n).write_bytes(v)
                rs={'stage':str(runtime_root),'members':{}}
                runtime={'spec.json':m.encoded(rs),'hardware-spec.json':b'{"host_recipe":{}}'}
                ref={'spec.json':b'{}','runtime-cleanup.json':m.encoded({'result':accepted})}
                report={'evidence':{'source-before.json':record(m.encoded(before)),
                    'continuity.json':record(m.encoded({'current':observation(True)})),
                    'runtime-data.json':record(b'{}')}}
                spec={'stage':str(dest),'source_stage':str(src)};old={'stage':str(src),'recovery_unit':'source-recovery'}
                helper=SimpleNamespace(read=lambda p,**kw:p.read_bytes(),create=lambda p,b:p.write_bytes(b))
                events=[];state={'failed':True}
                def systemctl(*args):
                    if args[0]=='show':return text(dict(UNIT,**({'ActiveState':'failed','SubState':'failed'} if state['failed'] else {})))
                    events.append(args)
                    if args[0]=='reset-failed':state['failed']=False
                    return ''
                fake_a=SimpleNamespace(source_guard=lambda *a:(os.open('/dev/null',os.O_RDONLY),retained))
                tx=SimpleNamespace(a=fake_a,systemctl=systemctl)
                original=SimpleNamespace(Transaction=lambda *a,**kw:tx,DESTINATIONS={},DIRECTORIES={},clear_restored_failure=stage.clear_restored_failure)
                observed=observation(True)
                if failure=='observation':observed['inventory']={}
                checker=SimpleNamespace(core=SimpleNamespace(i=SimpleNamespace(observation=Mock(side_effect=[observed,observation()]))),
                    network_checks=Mock(side_effect=ValueError('network drift') if failure=='network' else None),
                    accounts=lambda:accepted['created_account'],snapshot_file=lambda p:accepted['cache_after'],hardware_metadata=lambda:accepted['hardware'])
                inspector=SimpleNamespace(held_state=Mock(),runtime_data=lambda *a:{})
                files={n:(ROOT/path).read_bytes() for n,path in m.PATHS.items()};files['corrected-stage.py']=b'corrected';source={'stage.py':b'raise AssertionError("old stage")'}
                values=(None,inspector,{}, {},old,source,ref,runtime,report)
                clocks={'timer':{'LoadState':'loaded','ActiveState':'active'}}
                stopped={'timer':{'LoadState':'loaded','ActiveState':'inactive'}}
                with patch.object(m,'validate',return_value=values),patch.object(m,'source_lock',side_effect=lambda *a:os.open('/dev/null',os.O_RDONLY)), \
                     patch.object(m,'frozen',side_effect=lambda raw:original if raw==b'corrected' else load('runtime-artifacts.py')), \
                     patch.object(m,'load',return_value=SimpleNamespace(Transaction=lambda s:checker)), \
                     patch.object(m,'restored_files',side_effect=ValueError('file drift') if failure=='files' else None), \
                     patch.object(m,'timer_state',side_effect=ValueError('active worker') if failure=='active-worker' else [clocks,stopped,stopped]):
                    if failure:
                        with self.assertRaises(ValueError):m.restore(helper,spec,files)
                        if failure!='network':self.assertEqual(events,[])
                        else:self.assertEqual(events,[('stop','source-recovery.timer'),('reset-failed','timeservice.service')])
                    else:
                        result=m.restore(helper,spec,files)
                        self.assertEqual(result['phase'],'restoration_verified');self.assertFalse(result['time_service_accepted'])
                        self.assertEqual(events,[('stop','source-recovery.timer'),('reset-failed','timeservice.service')])
                self.assertEqual((src/'state.json').read_bytes(),m.encoded(initial))
                self.assertEqual((src/'before.json').read_bytes(),m.encoded(before))

    def test_readback_and_cleanup_only_use_matching_stored_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);raw=m.encoded({'phase':'restoration_held','error':'fixture'});(root/'report.json').write_bytes(raw)
            helper=SimpleNamespace(read=lambda p,**kw:p.read_bytes(),create=lambda p,b:p.write_bytes(b))
            with patch.object(m,'validate'),patch.object(m,'frozen',return_value=SimpleNamespace(protected=lambda *a:helper)),patch.object(m,'restore') as restore:
                spec={'stage':str(root)};files={'inspector.py':b'fixture'}
                self.assertEqual(m.entry(spec,files,'readback'),json.loads(raw))
                with self.assertRaises(ValueError):m.entry(spec,files,'cleanup',{'report_sha256':'0'*64})
                self.assertEqual(m.entry(spec,files,'cleanup',{'report_sha256':m.sha(raw)})['phase'],'cleaned')
                restore.assert_not_called();self.assertEqual((root/'report.json').read_bytes(),raw)


if __name__=='__main__':unittest.main()
