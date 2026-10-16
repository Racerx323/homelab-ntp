#!/usr/bin/python3
"""Offline scope, confidentiality and archive checks for mail inspection."""
import importlib.util
import importlib.metadata
import json
import subprocess
import sys
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
def load(path):
    s=importlib.util.spec_from_file_location(path.stem,path)
    m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
c=load(ROOT/'scripts/run-mail-prerequisites.py')
c.helper=load(ROOT/'scripts/run-production-inspection.py')

class MailTests(unittest.TestCase):
    def route(self,raw,dist_error=None):
        class Meta:
            st_mode=0o100600;st_size=len(raw);st_ino=1;st_mtime_ns=1;st_mtime=1
        fake=types.SimpleNamespace(lstat=lambda:Meta(),read_bytes=lambda:raw)
        source=types.SimpleNamespace(is_file=lambda:True,stat=lambda:types.SimpleNamespace(st_size=1),read_bytes=lambda:b'# fixture parser')
        output=[]
        with patch.object(sys,'path',sys.path.copy()),patch('os.path.isdir',return_value=True), \
                patch('pathlib.Path',side_effect=[fake,source]),patch('builtins.print',side_effect=output.append), \
                patch('importlib.metadata.distribution',side_effect=dist_error,return_value=types.SimpleNamespace(version='fixture',locate_file=lambda p:p)):
            try: exec(c.ROUTES, {'__name__':'fixture'})
            except SystemExit: pass
        return json.loads(output[-1])

    def test_routes_hide_destinations(self):
        r=self.route(b'configs:\n  notify:\n    urls: ["https://SECRET/token"]\n  notify.failure:\n    urls: "https://SECRET2/token"\n')
        self.assertTrue(all(x['exact_key_present'] and x['nonempty_urls'] for x in r['routes'].values()))
        self.assertNotIn('SECRET',json.dumps(r));self.assertFalse(r['delivery_verified'])
        self.assertTrue(r['notify_is_first_config'])

    def test_observed_directory_import_under_isolation_without_pth_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);app=base/'application';app.mkdir()
            (app/'yaml.py').write_text('fixture=True\n')
            marker=base/'pth-executed'
            (app/'unwanted.pth').write_text('import pathlib; pathlib.Path('+repr(str(marker))+').touch()\n')
            prefix=c.ROUTES.split("    stage = 'metadata_import'",1)[0]
            probe=prefix+"    print(yaml.__file__)\nexcept Exception as error:\n    print(type(error).__name__)\n    raise SystemExit(1)\n"
            probe=probe.replace('/home/mailrise/.local/lib/python3.14/site-packages',str(app))
            result=subprocess.run([sys.executable,'-I','-S','-B','-'],input=probe,text=True,capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(result.stdout.strip(),str(app/'yaml.py'))
            self.assertFalse(marker.exists())
            missing=probe.replace(str(app),str(base/'missing'))
            result=subprocess.run([sys.executable,'-I','-S','-B','-'],input=missing,text=True,capture_output=True)
            self.assertEqual(result.returncode,1)
            self.assertEqual(result.stdout.strip(),'FileNotFoundError')

    def test_missing_route_is_finding(self):
        r=self.route(b'configs:\n  notify:\n    urls: []\n')
        self.assertFalse(self.route(b'configs: {}\n')['routes']['notify@mailrise.xyz']['exact_key_present'])
        self.assertFalse(r['routes']['notify@mailrise.xyz']['nonempty_urls'])

    def test_custom_duplicate_and_secret_parse_errors_rejected(self):
        for raw in (b'import_code: SECRET.py\n', b'configs: {}\nconfigs: {}\n',
                    b'configs: !SECRET x\n', b'configs: [SECRET\n'):
            r=self.route(raw);self.assertTrue(r['routes_unverified']);self.assertNotIn('SECRET',json.dumps(r))

    def test_failure_stage_and_class_survive_without_message(self):
        parsed=self.route(b'configs: [SECRET\n')
        self.assertEqual(parsed['stage'],'yaml_parse')
        missing=self.route(b'configs: {}\n',importlib.metadata.PackageNotFoundError('SECRET'))
        self.assertEqual(missing['stage'],'distribution_lookup')
        self.assertEqual(missing['error_type'],'PackageNotFoundError')
        for result in (parsed,missing):
            row={'returncode':1,'stdout':json.dumps(result),'stderr':'SECRET error text'}
            safe=c.reader_diagnostic(row)
            self.assertEqual(safe['stage'],result['stage'])
            self.assertEqual(safe['returncode'],1)
            self.assertNotIn('SECRET',json.dumps(safe))

    def test_unclassified_reader_output_is_not_exported(self):
        for stdout in ('SECRET traceback',json.dumps({'routes_unverified':True,'stage':['SECRET'],'error_type':'SECRET'})):
            safe=c.reader_diagnostic({'returncode':127,'stdout':stdout,'stderr':'SECRET'})
            self.assertEqual(safe['stage'],'reader_not_classified')
            self.assertEqual(safe['error_type'],'Unclassified')
            self.assertNotIn('SECRET',json.dumps(safe))
            self.assertEqual(safe['stderr_bytes'],6)

    def test_failed_reader_keeps_diagnostic_and_checks_continuity(self):
        row={'returncode':1,'stdout':json.dumps({'routes_unverified':True,
             'stage':'configuration_read','error_type':'FileNotFoundError'}),'stderr':'SECRET'}
        with patch.object(c.os,'geteuid',return_value=0),patch.object(c,'Path') as path, \
                patch.object(c,'container',side_effect=[['a'],['b'],['a'],['b']]) as containers, \
                patch.object(c,'command',return_value=row):
            path.return_value.read_text.return_value='boot'
            result=c.collect({'mode':'relay','operation_id':'fixture'})
            self.assertFalse(result['capture_complete'])
            self.assertEqual(containers.call_count,4)
            self.assertEqual(result['reader_diagnostic']['error_type'],'FileNotFoundError')
            self.assertNotIn('SECRET',json.dumps(result))

    def test_package_collection_is_simulated_and_continuity_bound(self):
        calls=[]
        def run(argv,**kwargs):
            calls.append(argv);return {'returncode':0,'stdout':'','stderr':''}
        spec={'mode':'packages','operation_id':'fixture','boot_id':'boot','service_identity':{'MainPID':'1'}}
        with patch.object(c.os,'geteuid',return_value=0),patch.object(c,'Path') as path, \
                patch.object(c,'identity',return_value={'MainPID':'1'}),patch.object(c,'command',side_effect=run), \
                patch.object(c.helper,'file_record',return_value={'missing':True}):
            path.return_value.read_text.return_value='boot'
            self.assertTrue(c.collect(spec)['capture_complete'])
        apt=[a for a in calls if a[0]=='/usr/bin/apt-get']
        self.assertEqual(len(apt),1);self.assertIn('--simulate',apt[0]);self.assertIn('--no-install-recommends',apt[0])
        self.assertFalse(any('update' in a or 'sendmail' in a or 'start' in a for a in calls))
        with patch.object(c.os,'geteuid',return_value=0),patch.object(c,'Path') as path, \
                patch.object(c,'identity',return_value={'MainPID':'2'}),patch.object(c,'command') as run:
            path.return_value.read_text.return_value='boot'
            with self.assertRaisesRegex(ValueError,'identity changed'):c.collect(spec)
            run.assert_not_called()

    def test_relay_changed_identity_fails(self):
        row={'returncode':0,'stdout':'{"routes": {}}'}
        with patch.object(c.os,'geteuid',return_value=0),patch.object(c,'Path') as path, \
                patch.object(c,'container',side_effect=[['a'],['b'],['changed'],['b']]), \
                patch.object(c,'command',return_value=row) as run:
            path.return_value.read_text.return_value='boot'
            self.assertFalse(c.collect({'mode':'relay','operation_id':'fixture'})['capture_complete'])
            argv=run.call_args.args[0]
            self.assertEqual(argv[:5],['/usr/bin/podman','exec','-i','mailrise','python3'])

    def test_environment_reader_uses_stdlib_and_hides_launcher_arguments(self):
        with tempfile.TemporaryDirectory() as tmp:
            launcher=Path(tmp)/'mailrise'
            launcher.write_text('#!/opt/app/bin/python3 SECRET_ARGUMENT\nSECRET_BODY\n')
            output=[]
            with patch('shutil.which',side_effect=lambda n:str(launcher) if n=='mailrise' else None), \
                    patch('importlib.util.find_spec',return_value=None), \
                    patch('os.readlink',return_value='/usr/bin/python3'), \
                    patch('builtins.print',side_effect=output.append):
                exec(c.ENVIRONMENT,{'__name__':'fixture'})
            result=json.loads(output[-1])
            self.assertEqual(result['launchers']['mailrise']['shebang_interpreter'],'/opt/app/bin/python3')
            self.assertFalse(result['modules']['yaml']['found'])
            self.assertNotIn('SECRET',json.dumps(result))
            self.assertNotIn('mailrise.conf',c.ENVIRONMENT)
            self.assertNotIn('os.environ',c.ENVIRONMENT)
            self.assertNotIn('cmdline',c.ENVIRONMENT)

    def test_environment_scope_retains_continuity_without_route_claim(self):
        row={'returncode':0,'stdout':json.dumps({'modules':{'yaml':{'found':False}}}),'stderr':''}
        with patch.object(c.os,'geteuid',return_value=0),patch.object(c,'Path') as path, \
                patch.object(c,'container',side_effect=[['a'],['b'],['a'],['b']]), \
                patch.object(c,'command',return_value=row) as run:
            path.return_value.read_text.return_value='boot'
            result=c.collect({'mode':'relay-environment','operation_id':'fixture'})
            self.assertTrue(result['capture_complete'])
            self.assertFalse(result['delivery_verified'])
            self.assertIn('python_environment',result)
            self.assertNotIn('route_configuration',result)
            self.assertEqual(run.call_args.kwargs['payload'],c.ENVIRONMENT.encode())

    def test_seal_binding_and_single_use(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp)/'relay-fixture'
            args=types.SimpleNamespace(mode='relay',output=directory)
            with patch.object(c.subprocess,'run',return_value=types.SimpleNamespace(stdout='host ssh-ed25519 AAAATEST\n')):
                sealed=c.seal(args)
            spec,files=c.prepare(directory,sealed['sha256'])
            self.assertEqual(spec['user'],'pi')
            with self.assertRaisesRegex(ValueError,'digest'):c.prepare(directory,'0'*64)
            execution=types.SimpleNamespace(directory=directory,sha256=sealed['sha256'])
            with patch.object(c.helper,'bounded',return_value={'returncode':255,'stdout':'partial','stderr':'failed'}) as run:
                self.assertFalse(c.execute(execution)['capture_complete'])
                compile(run.call_args.kwargs['payload'],'remote','exec')
                self.assertIn('pi@10.1.3.83',run.call_args.args[0])
                with self.assertRaises(FileExistsError):c.execute(execution)
                self.assertEqual(run.call_count,1)
            self.assertEqual((directory/'stdout.txt').read_text(),'partial')
            (directory/'review.md').write_text('changed')
            with self.assertRaisesRegex(ValueError,'input drift'):c.prepare(directory,sealed['sha256'])

if __name__=='__main__':unittest.main()
