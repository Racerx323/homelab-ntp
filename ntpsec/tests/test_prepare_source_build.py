#!/usr/bin/python3
"""Offline source recipe, dependency closure and native option regressions."""
import copy
import base64
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
s=importlib.util.spec_from_file_location('prepare_source',ROOT/'scripts/prepare-source-build.py')
w=importlib.util.module_from_spec(s);s.loader.exec_module(w)


class PrepareSource(unittest.TestCase):
    def test_expired_foundation_rejected_before_other_inputs_or_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);foundation=root/'foundation.json';output=root/'output'
            foundation.write_text(json.dumps({'prepared_epoch':int(time.time())-86400,
                                              'expires_epoch':int(time.time())-1}))
            args=['prepare-source-build.py','--foundation',str(foundation),
                  '--foundation-sha256',w.sha(foundation.read_bytes()),
                  '--python-evidence',str(root/'missing-python'), '--python-evidence-sha256','0'*64,
                  '--sources',str(root/'missing-sources'), '--known-hosts',str(root/'missing-key'),
                  '--operation-id','fixture-v6','--output',str(output)]
            with patch('sys.argv',args),self.assertRaisesRegex(ValueError,'window expired'):
                w.main()
            self.assertFalse(output.exists())

    def test_transport_renders_unique_stage_and_observed_target(self):
        worker=(ROOT/'scripts/source-build-stage.py').read_bytes()
        launcher=(ROOT/'scripts/run-source-build.py').read_bytes()
        known=b'fixture.example ssh-ed25519 '+base64.b64encode(b'fixture key')+b'\n'
        target={'hostname':'fixture-node','kernel':'6.18.51-fixture-v8'}
        name,stage,transport=w.render_transport(worker,launcher,target,known,'fixture-v6')
        ns={};exec(compile(stage,'worker','exec'),ns)
        ls={};exec(compile(transport,'launcher','exec'),ls)
        self.assertEqual(name,'.ntp-source-build-fixture-v6')
        self.assertEqual((ns['STAGE_NAME'],ns['HOSTNAME'],ns['KERNEL']),
                         (name,target['hostname'],target['kernel']))
        self.assertEqual(ls['TARGET'],'ama@fixture.example')
        self.assertEqual(ls['FINGERPRINT'],'SHA256:'+base64.b64encode(
            hashlib.sha256(b'fixture key').digest()).decode().rstrip('='))
        for operation in ('../v6','v6;id','', 'x'*64):
            with self.subTest(operation=operation),self.assertRaises(ValueError):
                w.render_transport(worker,launcher,target,known,operation)
        with self.assertRaisesRegex(ValueError,'template'):
            w.render_transport(worker+worker,launcher,target,known,'fixture-v6')
        with self.assertRaisesRegex(ValueError,'host key'):
            w.render_transport(worker,launcher,target,known+known,'fixture-v6')

    def test_ntpsec_isolated_test_layout_is_bound(self):
        def archive(output, library):
            data=io.BytesIO()
            with tarfile.open(fileobj=data, mode='w') as t:
                for name,text in {'wscript': 'out = ' + repr(output) + '\n',
                                  'wafhelpers/bin_test.py': 'path = ' + repr(library) + '\n',
                                  'wafhelpers/options.py': ''}.items():
                    content=text.encode();m=tarfile.TarInfo('release/'+name)
                    m.size=len(content);t.addfile(m,io.BytesIO(content))
            return data.getvalue()
        source={'archive_root':'release','options':[]}
        w.verify_options(archive('build','%s/main/tests/pylib'),source,'ntpsec')
        for output,library in (('other','%s/main/tests/pylib'),('build','%s/other')):
            with self.subTest(output=output,library=library),self.assertRaisesRegex(ValueError,'layout mismatch'):
                w.verify_options(archive(output,library),source,'ntpsec')

    def setUp(self):
        self.recipe=json.loads((ROOT/'configs/source-build-recipe.json').read_text())
        names=set(self.recipe['build_roots'])|{'python3','libc6','binutils','gcc','g++','make'}
        self.foundation={'hostname':'fixture','baseline':{n:['1','ii '] for n in names},'packages':[]}
        self.python={'version':[3,13,5],'purelib':'/usr/local/lib/python3.13/dist-packages'}
        self.helpers={n:b'helper' for n in ('clockmaker.py','pinup.py','timeservice.py')}

    def test_canonical_profile_binds_dependencies_sources_and_default_protocols(self):
        profile,inventory=w.profile_inputs(self.recipe,self.foundation,self.python,self.helpers)
        self.assertEqual(profile['sources'],self.recipe['sources'])
        self.assertIn('bc',profile['packages']);self.assertIn('pps-tools',profile['packages'])
        self.assertIn('timeservice=yes',profile['sources']['gpsd']['options'])
        self.assertTrue({'sirf=yes','earthmate=yes','evermore=yes'}.issubset(profile['sources']['gpsd']['options']))
        self.assertEqual(profile['python']['version'],[3,13])
        self.assertEqual(inventory,self.foundation['baseline'])

    def test_pending_supplement_changes_only_its_bound_record(self):
        self.foundation['baseline'].pop('bc')
        self.foundation['packages']=[{'binary_package':'bc','version':'2'}]
        profile,inventory=w.profile_inputs(self.recipe,self.foundation,self.python,self.helpers)
        self.assertEqual(profile['packages']['bc'],'2')
        self.assertNotIn('bc',self.foundation['baseline'])
        self.assertEqual(inventory['bc'],['2','ii '])

    def test_missing_ambiguous_or_unconfigured_prerequisite_rejected(self):
        for state in ('missing','duplicate','unconfigured'):
            foundation=copy.deepcopy(self.foundation)
            if state=='missing':foundation['baseline'].pop('bc')
            elif state=='duplicate':foundation['baseline']['bc:armhf']=['1','ii ']
            else:foundation['baseline']['bc']=['1','iU ']
            with self.subTest(state=state),self.assertRaises(ValueError):
                w.profile_inputs(self.recipe,foundation,self.python,self.helpers)

    def test_stripped_or_duplicate_protocol_option_rejected(self):
        for options in (['timeservice=yes'],['timeservice=no'],['timeservice=false'],
                        ['timeservice=0'],['minimal=no'],['minimal=yes'],
                        ['shared=yes','shared=yes']):
            recipe=copy.deepcopy(self.recipe);recipe['sources']['gpsd']['options']=options
            with self.assertRaises(ValueError):w.profile_inputs(recipe,self.foundation,self.python,self.helpers)

    def test_recipe_cannot_omit_pps_or_bc(self):
        for name in ('bc','pps-tools'):
            recipe=copy.deepcopy(self.recipe);recipe['build_roots'].remove(name)
            with self.assertRaises(ValueError):w.profile_inputs(recipe,self.foundation,self.python,self.helpers)

    def test_mdns_and_gpsd_shm_requirements_cannot_be_disabled(self):
        for name in ('libavahi-compat-libdnssd-dev', 'avahi-daemon'):
            recipe=copy.deepcopy(self.recipe);recipe['build_roots'].remove(name)
            with self.subTest(name=name),self.assertRaisesRegex(ValueError,'mDNS'):
                w.profile_inputs(recipe,self.foundation,self.python,self.helpers)
            foundation=copy.deepcopy(self.foundation);foundation['baseline'].pop(name)
            with self.subTest(missing=name),self.assertRaisesRegex(ValueError,'prerequisite'):
                w.profile_inputs(self.recipe,foundation,self.python,self.helpers)
        for options in (['--refclock=shm', '--disable-mdns-registration'],
                        ['--refclock=nmea,pps'], ['--refclock=shm,nmea,pps'],
                        ['--refclock=shm', '--refclock=pps']):
            recipe=copy.deepcopy(self.recipe);recipe['sources']['ntpsec']['options']=options
            with self.subTest(options=options),self.assertRaisesRegex(ValueError,'SHM'):
                w.profile_inputs(recipe,self.foundation,self.python,self.helpers)

    def test_time_service_and_packet_test_drivers_required(self):
        for name in ('timeservice','sirf','earthmate','evermore','control_socket'):
            recipe=copy.deepcopy(self.recipe)
            recipe['sources']['gpsd']['options']=[a for a in recipe['sources']['gpsd']['options']
                                                if a.split('=')[0]!=name]
            with self.subTest(name=name),self.assertRaises(ValueError):
                w.profile_inputs(recipe,self.foundation,self.python,self.helpers)

    def test_unknown_native_option_rejected(self):
        data=io.BytesIO()
        with tarfile.open(fileobj=data,mode='w') as t:
            construct=b'gpsd_version="3.27.5"\nvariantdir="gpsd-"+gpsd_version\n'
            m=tarfile.TarInfo('release/SConstruct');m.size=len(construct);t.addfile(m,io.BytesIO(construct))
            text=(b'imloads=True\nboolopts = (("timeservice", False, "description"),'
                  b'("sirf", True, "driver"),("implicit_link",imloads,"library"))\n')
            m=tarfile.TarInfo('release/SConscript');m.size=len(text);t.addfile(m,io.BytesIO(text))
        source={'archive_root':'release','version':'3.27.5','options':['timeservice=yes','sirf=yes','implicit_link=yes']}
        w.verify_options(data.getvalue(),source,'gpsd')
        for option in ('sirf=yes','implicit_link=yes'):
            with self.subTest(option=option),self.assertRaisesRegex(ValueError,'strip default options'):
                w.verify_options(data.getvalue(),dict(source,options=[a for a in source['options'] if a!=option]),'gpsd')
        with self.assertRaises(ValueError):w.verify_options(data.getvalue(),dict(source,options=['unknown=yes']),'gpsd')
        with self.assertRaises(ValueError):w.verify_options(data.getvalue(),dict(source,version='3.28'),'gpsd')


if __name__=='__main__':unittest.main()
