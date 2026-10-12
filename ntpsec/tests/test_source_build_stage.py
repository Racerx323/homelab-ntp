#!/usr/bin/python3
"""Offline source-stage binding, rejection, retention and transport regressions."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
SEALED = (Path(__file__).parent / 'source-build-stage.py').is_file()
BASE = Path(__file__).parent if SEALED else ROOT / 'scripts'


def load(name, filename):
    s = importlib.util.spec_from_file_location(name, BASE / filename)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


w = load('worker', 'source-build-stage.py')
l = load('launcher', 'launcher.py' if SEALED else 'run-source-build.py')


class SourceStage(unittest.TestCase):
    def test_mdns_optional_configure_detection_must_succeed(self):
        header='#define CLOCK_SHM 1\n#define HAVE_SECCOMP_H 1\n#define HAVE_DNS_SD_H 1\n'
        w.validate_ntpsec_features(header, True)
        without_mdns=header.replace('#define HAVE_DNS_SD_H 1\n', '')
        with self.assertRaisesRegex(ValueError,'mDNS'):
            w.validate_ntpsec_features(without_mdns, True)
        # Historical disabled candidates remain inspectable using their bound profile.
        w.validate_ntpsec_features(without_mdns, False)
        for missing in ('CLOCK_SHM', 'HAVE_SECCOMP_H'):
            with self.subTest(missing=missing),self.assertRaises(ValueError):
                w.validate_ntpsec_features(header.replace('#define '+missing+' 1\n', ''), True)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.stage = self.home / w.STAGE_NAME
        self.profile = {'schema': 1, 'hostname': w.HOSTNAME, 'prefix': '/usr/local', 'jobs': 2,
                        'python': {'version': [3,13], 'module_directory': '/usr/local/lib/python3.13/dist-packages'},
                        'packages': {'bc':'1','pps-tools':'1'},
                        'helpers': {'clockmaker.py': w.sha(b'helper'), 'pinup.py': w.sha(b'helper'), 'timeservice.py': w.sha(b'helper')},
                        'sources': {n: {'archive': n+'.tar.gz', 'sha256': w.sha(b'source'),
                                       'options':['timeservice=yes','sirf=yes','earthmate=yes','evermore=yes','control_socket=yes'] if n=='gpsd' else []} for n in ('gpsd','ntpsec')}}
        recipe=json.dumps({'sources':self.profile['sources']}).encode()
        self.profile['recipe_sha256']=w.sha(recipe)
        self.files = {'source-build-stage.py': b'worker', 'profile.json': json.dumps(self.profile).encode(),
                      'recipe.json':recipe,
                      'clockmaker.py': b'helper', 'pinup.py': b'helper', 'timeservice.py': b'helper',
                      'gpsd.tar.gz': b'source', 'ntpsec.tar.gz': b'source'}
        self.spec = {'hostname': w.HOSTNAME, 'kernel': w.KERNEL,
                     'pps_header_sha256': w.sha(b'header'),
                     'prepared_epoch': int(time.time()), 'expires_epoch': int(time.time())+3600,
                     'python': {'version':[3,13,5], 'module_directory': '/usr/local/lib/python3.13/dist-packages',
                                'extension_suffix': '.cpython-313-aarch64-linux-gnu.so'},
                     'inventory': {'base':['1','ii ']}, 'members': {n:w.sha(b) for n,b in self.files.items()}}

    def test_exact_input_set_and_hashes(self):
        self.assertEqual(w.verify_files(self.spec,self.files), self.profile)
        for files in (dict(self.files, extra=b'drift'), dict(self.files, **{'gpsd.tar.gz':b'drift'})):
            with self.assertRaises(ValueError): w.verify_files(self.spec,files)

    def test_staged_acceptance_imports_only_candidate_python_modules(self):
        candidate=self.home/'candidate';stage=candidate/'stage'
        module=stage/self.spec['python']['module_directory'].lstrip('/')
        for package, children in (('gps',('client',)),('ntp',('packet','ntpc'))):
            root=module/package;root.mkdir(parents=True)
            for name in ('__init__',*children):(root/(name+'.py')).write_text('')
        for binary in ('sbin/gpsd','sbin/ntpd','bin/ntpq'):
            path=stage/'usr/local'/binary;path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text('#!'+sys.executable+'\nimport ntp\nprint("fixture")\n')
            path.chmod(0o700)
        profile=copy.deepcopy(self.profile)
        profile['sources']['ntpsec']['archive_root']='release'
        profile['sources']['gpsd'].update(archive_root='release',version='1')
        ntpheader=candidate/'ntpsec/release/build/config.h'
        ntpheader.parent.mkdir(parents=True);ntpheader.write_text('#define CLOCK_SHM 1\n#define HAVE_SECCOMP_H 1\n#define HAVE_DNS_SD_H 1\n')
        gpsheader=candidate/'gpsd/release/gpsd-1/include/gpsd_config.h'
        gpsheader.parent.mkdir(parents=True);gpsheader.write_text('fixture')
        real_run=subprocess.run
        def native(argv,**kwargs):
            if '--drivers' in argv:return SimpleNamespace(stdout=b'driver u-blox\n',stderr=b'')
            if argv[0]=='/usr/bin/ldd':return SimpleNamespace(stdout=b'',stderr=b'')
            return real_run(argv,**kwargs)
        def smoke(argv,cwd,env,log):
            result=subprocess.run(argv,cwd=cwd,env=env,capture_output=True,check=True)
            if '-c' in argv:
                self.assertIn(str(module).encode(),result.stdout)
        clock=SimpleNamespace(bound_json=Mock(return_value={'files':{}}),
                              inventory=Mock(return_value={}),run=smoke)
        self.stage.mkdir();old=w.STAGE;w.STAGE=self.stage
        (self.stage/'acceptance.log').write_text('original failure')
        try:
            with patch.object(w.subprocess,'run',side_effect=native), \
                    patch.object(w,'validate_artifacts'),patch.object(w,'validate_gpsd_features'):
                accepted=w.staged_acceptance(clock,candidate,profile,self.spec,
                    {'manifest':'fixture','sha256':'a'*64},'acceptance-continuation-v1.log')
            self.assertTrue(accepted['manuals_modules_versions_linkage'])
            self.assertTrue(accepted['ntpsec_mdns_registration'])
            self.assertEqual((self.stage/'acceptance.log').read_text(),'original failure')
            self.assertTrue((self.stage/'acceptance-continuation-v1.log').is_file())
        finally:w.STAGE=old
        self.assertIsNone(w.verify_files(self.spec, {'source-build-stage.py':b'worker'},True))

    def test_profile_mismatch_rejected(self):
        for k,v in [('jobs',4),('hostname','wrong'),('prefix','/usr')]:
            bad=copy.deepcopy(self.profile);bad[k]=v
            files=dict(self.files, **{'profile.json':json.dumps(bad).encode()})
            spec=copy.deepcopy(self.spec);spec['members']['profile.json']=w.sha(files['profile.json'])
            with self.subTest(key=k), self.assertRaises(ValueError):w.verify_files(spec,files)

    def test_recipe_or_dependency_regression_rejected(self):
        for change in ('recipe','bc','pps-tools','protocol','protocol-no','minimal-no','control-socket'):
            bad=copy.deepcopy(self.profile)
            if change=='recipe':bad['recipe_sha256']='a'*64
            elif change=='protocol':bad['sources']['gpsd']['options']=['timeservice=yes']
            elif change=='protocol-no':bad['sources']['gpsd']['options']=['timeservice=no']
            elif change=='minimal-no':bad['sources']['gpsd']['options']=['minimal=no']
            elif change=='control-socket':bad['sources']['gpsd']['options'].remove('control_socket=yes')
            else:bad['packages'].pop(change)
            files=dict(self.files,**{'profile.json':json.dumps(bad).encode()})
            spec=copy.deepcopy(self.spec);spec['members']['profile.json']=w.sha(files['profile.json'])
            with self.subTest(change=change),self.assertRaises(ValueError):w.verify_files(spec,files)

    def test_generated_gpsd_features_require_protocols_and_pps(self):
        header='#define HAVE_SYS_TIMEPPS_H 1\n#define TIMESERVICE_ENABLE 1\n'+''.join('#define '+f+'_ENABLE 1\n' for f in
            ('SHM_EXPORT','MAGIC_HAT','GPSDCLIENTS','PYTHON','SHARED','NCURSES','CONTROL_SOCKET','SIRF','EARTHMATE','EVERMORE'))
        w.validate_gpsd_features(header)
        for feature in ('SIRF','EARTHMATE','EVERMORE','CONTROL_SOCKET'):
            with self.subTest(feature=feature),self.assertRaises(ValueError):
                w.validate_gpsd_features(header.replace('#define '+feature+'_ENABLE 1',''))
        with self.assertRaises(ValueError):w.validate_gpsd_features(header.replace('#define TIMESERVICE_ENABLE 1\n',''))

    def test_reported_ublox_receiver_requires_compiled_driver(self):
        w.validate_gpsd_drivers(' n b c * u-blox\n n b * MTK-3301\n')
        for output in ('', ' n b * MTK-3301\n', 'u-blox-disabled\n'):
            with self.subTest(output=output),self.assertRaises(ValueError):w.validate_gpsd_drivers(output)

    def test_create_is_exclusive_and_no_symlink_follow(self):
        p=self.home/'file';w.create(p,b'bound')
        with self.assertRaises(FileExistsError):w.create(p,b'replay')
        link=self.home/'link';link.symlink_to(p)
        with self.assertRaises(FileExistsError):w.create(link,b'drift')
        self.assertEqual(p.read_bytes(),b'bound')

    def execute(self, clock=None, accepted=None, packages=None):
        clock=clock or SimpleNamespace(build=Mock(return_value={'manifest':'release','sha256':'a'*64}))
        spec_loader=SimpleNamespace(loader=SimpleNamespace(exec_module=lambda m:None))
        with patch.object(w,'identity',return_value=self.stage), patch.object(w,'packages',side_effect=packages or [self.spec['inventory']]*2), \
             patch.object(w.Path,'is_symlink',return_value=False), patch.object(w.Path,'is_file',return_value=True), \
             patch.object(w.Path,'read_bytes',return_value=b'header'), \
             patch.object(w,'continuity',return_value={'boot':'same','services':'same'}), \
             patch.object(w.os,'statvfs',return_value=SimpleNamespace(f_bavail=3*1024**3,f_frsize=1)), \
             patch.object(w.signal,'signal'),patch.object(w.signal,'alarm'), \
             patch.object(w.importlib.util,'spec_from_file_location',return_value=spec_loader), \
             patch.object(w.importlib.util,'module_from_spec',return_value=clock), \
             patch.object(w,'staged_acceptance',return_value=accepted or {'source_tests_passed':True}):
            return w.entry(self.spec,self.files,int(time.time()),'build')

    def test_success_creates_new_private_stage_without_live_install(self):
        report=self.execute()
        self.assertEqual(report['state'],'source_build_staged_accepted')
        self.assertFalse(report['live_installed']);self.assertFalse(report['services_activated'])
        self.assertTrue((self.stage/'complete.json').is_file())
        self.assertEqual(self.stage.stat().st_mode & 0o777,0o700)
        with self.assertRaises(FileExistsError):self.execute()

    def test_build_failure_retains_inputs_and_claim_no_success(self):
        clock=SimpleNamespace(build=Mock(side_effect=subprocess.CalledProcessError(1,['scons','check'])))
        with self.assertRaises(subprocess.CalledProcessError):self.execute(clock)
        self.assertTrue((self.stage/'claim.json').is_file())
        self.assertTrue((self.stage/'failure.json').is_file())
        self.assertFalse((self.stage/'complete.json').exists())
        self.assertEqual((self.stage/'gpsd.tar.gz').read_bytes(),b'source')

    def test_package_drift_before_build_does_not_stage(self):
        with self.assertRaisesRegex(ValueError,'inventory changed'):self.execute(packages=[{}])
        self.assertFalse(self.stage.exists())

    def test_package_drift_after_build_holds_candidate(self):
        with self.assertRaisesRegex(ValueError,'continuity changed'):self.execute(packages=[self.spec['inventory'],{}])
        self.assertTrue((self.stage/'failure.json').exists())
        self.assertFalse((self.stage/'complete.json').exists())

    def test_wrong_mode_never_runs(self):
        with self.assertRaises(ValueError):w.entry(self.spec,self.files,int(time.time()),'install')

    def test_root_identity_rejected(self):
        with patch.object(w.os,'getuid',return_value=0),self.assertRaises(ValueError):
            w.identity(self.spec,int(time.time()))

    def test_readback_performs_no_build(self):
        self.stage.mkdir(mode=0o700);w.create(self.stage/'claim.json',b'{}')
        with patch.object(w,'identity',return_value=self.stage):
            # Only the owner lookup is simulated; original inode bytes remain real.
            original=self.stage.lstat()
            info=SimpleNamespace(st_mode=original.st_mode,st_uid=1000)
            with patch.object(w.Path,'lstat',return_value=info):
                r=w.entry(self.spec,{'source-build-stage.py':b'worker'},int(time.time()),'readback')
        self.assertEqual(r['state'],'source_build_readback')
        self.assertEqual(list(self.stage.iterdir()),[self.stage/'claim.json'])

    def test_missing_manual_module_or_shared_library_rejected(self):
        names=['usr/local/sbin/gpsd','usr/local/sbin/ntpd','usr/local/bin/ntpq','usr/local/bin/ntpleapfetch',
               'usr/local/bin/ntploggps','usr/local/bin/cgps','usr/local/bin/gpspipe']
        module=self.spec['python']['module_directory'];suffix=self.spec['python']['extension_suffix']
        names += [module.lstrip('/')+'/'+n for n in ['gps/__init__.py','ntp/__init__.py','ntp/ntpc'+suffix]]
        names += ['usr/local/share/man/'+n for n in ['man8/gpsd.8','man8/ntpd.8','man1/ntpq.1','man1/gpspipe.1']]
        names += ['usr/local/lib/libgps.so.30.0.0']
        files={n:{'type':'file'} for n in names};w.validate_artifacts({'files':files},module,suffix)
        for n in names:
            bad=dict(files);bad.pop(n)
            with self.subTest(path=n),self.assertRaises(ValueError):w.validate_artifacts({'files':bad},module,suffix)

    def test_transport_is_unprivileged_pinned_without_agent_forwarding(self):
        argv=l.transport(self.home)
        self.assertEqual(argv[-1],'cd / && /usr/bin/python3 -I -B -')
        self.assertIn('ForwardAgent=no',argv);self.assertIn('StrictHostKeyChecking=yes',argv)
        self.assertIn('ProxyCommand=none',argv);self.assertNotIn('sudo',' '.join(argv))

    def test_payload_build_and_readback_compile(self):
        for mode in ('build','accept','readback'):
            payload=l.payload(self.spec,self.files,int(time.time()),mode)
            compile(payload,'payload','exec')
            self.assertNotIn(b'sudo',payload)
        self.assertNotIn(b'c291cmNl', l.payload(self.spec,self.files,int(time.time()),'readback'))

    def test_bundle_hash_rejection_before_transport(self):
        path=self.home/'source.tar';path.write_bytes(b'not bundle');path.chmod(0o600);self.home.chmod(0o700)
        with self.assertRaisesRegex(ValueError,'bundle hash mismatch'):l.prepare(path,'a'*64)


if __name__=='__main__':unittest.main()
