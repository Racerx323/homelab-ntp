#!/usr/bin/python3
"""Reproducible full foundation and missing-dependency supplement regressions."""
import copy
import importlib.util
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
s=importlib.util.spec_from_file_location('prepare',ROOT/'scripts/prepare-foundation.py')
w=importlib.util.module_from_spec(s);s.loader.exec_module(w)


class Prepare(unittest.TestCase):
    def setUp(self):
        self.origin={'packages':[{'package':'pkg'+str(i)} for i in range(44)],
                     'directories':{'/etc/dpkg/dpkg.cfg.d':[], '/etc/needrestart/conf.d':['rpi-kernel.conf']},
                     'package_created_inputs':{},'inputs':[{'path':'/var/lib/dpkg/status','sha256':'old'}]}
        self.pps={'package':'pps-tools','version':'1.0.2-2+b1','architecture':'arm64',
                  'sha256':w.sha(b'archive'),'size':7,'archive_file':'retained'}
        self.bc={'package':'bc','version':'1.07.1-4+b1','architecture':'arm64','sha256':w.sha(b'bc'),'size':2}
        self.files={'worker.py':b"STAGE = Path('/var/lib/ntp-foundation-v6')\n",'prior-needrestart.conf':b'old',
                    'needrestart.conf':b'new'}
        self.effects={p:{'path':p,'sha256':'a'*64,'uid':0,'gid':0,'mode':'0o644'} for p in
                      ['/usr/include/sys/timepps.h','/etc/dpkg/dpkg.cfg.d/needrestart','/usr/bin/bc']}
        self.inventory={'base'+str(i):['1','ii '] for i in range(677)}

    def prepare(self,scope='foundation',pps=None,data=b'archive',inventory=None):
        return w.construct(self.origin,pps or self.pps,data,self.files,self.effects,scope,1000,
                           inventory if inventory is not None else self.inventory,self.bc,b'bc')

    def test_full_adds_pps_and_header_without_changing_original(self):
        original=copy.deepcopy(self.origin)
        spec,files=self.prepare()
        self.assertEqual(len(spec['packages']),46)
        self.assertEqual([r['package'] for r in spec['packages'][-2:]],['pps-tools','bc'])
        self.assertEqual(spec['package_created_inputs']['/usr/include/sys/timepps.h'],'a'*64)
        self.assertEqual(self.origin,original)
        self.assertNotIn('prior-needrestart.conf',files)

    def test_supplement_only_pps_with_post_foundation_state(self):
        spec,files=self.prepare('pps-supplement')
        self.assertEqual([r['package'] for r in spec['packages']],['pps-tools'])
        self.assertEqual(spec['baseline'],self.inventory)
        self.assertEqual(spec['directories']['/etc/dpkg/dpkg.cfg.d'],['needrestart'])
        self.assertIn('zz-ntp-policy.conf',spec['directories']['/etc/needrestart/conf.d'])
        status=next(i for i in spec['inputs'] if i['path']=='/var/lib/dpkg/status')
        self.assertNotIn('sha256',status)
        self.assertEqual(spec['prior_needrestart_sha256'],w.sha(b'old'))
        self.assertIn(b'/var/lib/ntp-foundation-pps-v3',files['worker.py'])

    def test_bc_supplement_requires_pps_and_adds_only_bc(self):
        current=dict(self.inventory);current['pps-tools']=['1.0.2-2+b1','ii ']
        spec,files=self.prepare('bc-supplement',inventory=current)
        self.assertEqual([r['package'] for r in spec['packages']],['bc'])
        self.assertEqual(spec['baseline'],current)
        self.assertEqual(spec['package_created_inputs'],{'/usr/bin/bc':'a'*64})
        self.assertTrue(any(r['path']=='/usr/include/sys/timepps.h' and r['sha256']=='a'*64 for r in spec['inputs']))
        self.assertIn({'path':'/usr/bin/update-menus','absent':True},spec['inputs'])
        self.assertIn(b'/var/lib/ntp-foundation-bc-v1',files['worker.py'])
        self.assertNotIn('archives/pps-tools_1.0.2-2+b1_arm64.deb',files)
        for inv in (self.inventory,dict(current,bc=['1','ii '])):
            with self.assertRaises(ValueError):self.prepare('bc-supplement',inventory=inv)

    def test_missing_or_changed_bc_archive_rejected(self):
        for record,data in ((None,None),(self.bc,b'drift'),(dict(self.bc,version='../2'),b'bc')):
            with self.assertRaises(ValueError):
                w.construct(self.origin,self.pps,b'archive',self.files,self.effects,'foundation',1000,
                            self.inventory,record,data)

    def test_archive_drift_wrong_architecture_version_and_scope_rejected(self):
        for key,value in [('architecture','amd64'),('version','2'),('sha256','b'*64),('size',8)]:
            with self.subTest(key=key),self.assertRaises(ValueError):self.prepare(pps=dict(self.pps,**{key:value}))
        with self.assertRaises(ValueError):self.prepare('unknown')

    def test_supplement_rejects_already_installed_pps_and_wrong_baseline(self):
        current=dict(self.inventory);current.pop('base0');current['pps-tools']=['1','ii ']
        for inv in [current,{}]:
            with self.assertRaises(ValueError):self.prepare('pps-supplement',inventory=inv)

    def test_unknown_canonical_stage_cannot_be_rendered(self):
        self.files['worker.py']=b'wrong stage'
        with self.assertRaises(ValueError):self.prepare()

    def test_full_rejects_changed_original_scope(self):
        self.origin['packages'][0]['package']='pps-tools'
        with self.assertRaises(ValueError):self.prepare()


if __name__=='__main__':unittest.main()
