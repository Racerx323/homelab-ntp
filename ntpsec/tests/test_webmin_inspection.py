#!/usr/bin/python3
"""Read-only collection boundaries, sealed inputs and single-use transport."""
import importlib.util
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
entry = importlib.util.spec_from_file_location('webmin_inspection', ROOT/'scripts/run-webmin-inspection.py')
c = importlib.util.module_from_spec(entry); entry.loader.exec_module(c)
c.helper = c.load(ROOT/'scripts/run-production-inspection.py')


class Inspection(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.calls = []
        self.spec = {'schema': 1, 'purpose': 'webmin-inspection', 'hostname': 'j2-svntp1',
            'operation_id': 'leap-fixture', 'boot_id': 'a'*8+'-'+'b'*4+'-'+'c'*4+'-'+'d'*4+'-'+'e'*12,
            'endpoints': ['192.0.2.1','2001:db8::1'], 'host_key_alias': '192.0.2.2',
            'activation_sha256': 'a'*64, 'service_identity': {'MainPID':'814','InvocationID':'abc','NRestarts':'0','ActiveState':'active','SubState':'running','UnitFileState':'enabled'},
            'prepared_epoch': int(time.time()), 'expires_epoch': int(time.time())+3600}
        self.files = {n:(ROOT/p).read_bytes() for n,p in c.PATHS.items()}
        self.files.update({'known_hosts': b'fixture', 'baseline.json': b'{}\n'})
        self.spec['members'] = {n:c.helper.sha(raw) for n,raw in self.files.items()}
        self.files.update({'spec.json':c.helper.encoded(self.spec),'review.md':c.review(self.spec).encode()})
        self.bundle = self.root/c.BUNDLE
        self.pack()

    def pack(self):
        with tarfile.open(self.bundle,'w') as archive:
            for name,raw in self.files.items():
                item=tarfile.TarInfo(name);item.size=len(raw);archive.addfile(item,io.BytesIO(raw))
        self.bundle.chmod(0o600)
        for name in ('spec.json','review.md','known_hosts'):
            (self.root/name).write_bytes(self.files[name]);(self.root/name).chmod(0o600)
        self.digest=c.helper.sha(self.bundle.read_bytes())

    def run_capture(self,fail=False,changed=False):
        def bounded(argv):
            self.calls.append(argv)
            if fail and argv[0]=='/usr/bin/dpkg-query':raise FileNotFoundError('missing dpkg-query')
            return {'argv':argv,'returncode':0,'stdout':''.join(k+'='+v+'\n' for k,v in self.spec['service_identity'].items()),'stderr':''}
        with patch.object(c,'boot',side_effect=[self.spec['boot_id'],'other' if changed else self.spec['boot_id']]), \
                patch.object(c.socket,'gethostname',return_value='j2-svntp1'),patch.object(c.os,'geteuid',return_value=0), \
                patch.object(c,'Path',side_effect=lambda p:self.root/Path(p).name), \
                patch.object(c.helper,'file_record',return_value={'missing':True}), \
                patch.object(c.helper,'bounded',side_effect=bounded):
            return c.collect(self.spec)

    def test_reads_only_and_retains_missing_files(self):
        result=self.run_capture();self.assertTrue(result['capture_complete'])
        self.assertEqual(set(result['files']),set(c.FILES))
        self.assertTrue(all(r.get('missing') for r in result['files'].values()))
        for argv in self.calls:
            self.assertIn(argv[0],('/usr/bin/systemctl','/usr/bin/dpkg-query','/usr/bin/dpkg','/usr/bin/ss','/usr/sbin/ip','/usr/sbin/nft','/usr/bin/journalctl'))
            self.assertNotIn('start',argv);self.assertNotIn('enable',argv);self.assertNotIn('install',argv)
            if argv[0]=='/usr/bin/systemctl':self.assertIn(argv[1],('cat','show'))
            if 'ntpleapfetch.timer' in argv and argv[1]=='show':
                self.assertNotIn('MainPID',argv[-1]);self.assertNotIn('NRestarts',argv[-1])
        self.assertFalse(result['production_accepted'])

    def test_command_failure_and_boot_change_are_incomplete(self):
        self.assertFalse(self.run_capture(fail=True)['capture_complete'])
        self.assertFalse(self.run_capture(changed=True)['capture_complete'])

    def test_wrong_boot_stops_before_commands(self):
        with patch.object(c,'boot',return_value='changed'),patch.object(c.socket,'gethostname',return_value='j2-svntp1'), \
                patch.object(c.os,'geteuid',return_value=0),patch.object(c.helper,'bounded') as run:
            result=c.collect(self.spec)
        self.assertFalse(result['capture_complete']);run.assert_not_called()

    def test_archive_and_review_binding(self):
        spec,files=c.prepare(self.bundle,self.digest)
        compile(c.payload(spec,files),'payload','exec')
        with self.assertRaisesRegex(ValueError,'digest'):c.prepare(self.bundle,'0'*64)
        (self.root/'review.md').write_text('changed')
        with self.assertRaisesRegex(ValueError,'approval input'):c.prepare(self.bundle,self.digest)

    def test_single_use_and_partial_transport_retained(self):
        args=type('Args',(),{'bundle':self.bundle,'sha256':self.digest})()
        with patch.object(c.helper,'bounded',return_value={'returncode':255,'stdout':'partial','stderr':'SSH failed'}):
            result=c.execute(args)
            self.assertFalse(result['capture_complete'])
            self.assertEqual((self.root/'stdout.txt').read_text(),'partial')
            with self.assertRaises(FileExistsError):c.execute(args)

    def test_success_capture_identity_and_command_failure_distinguished(self):
        args=type('Args',(),{'bundle':self.bundle,'sha256':self.digest})()
        report={'hostname':self.spec['hostname'],'operation_id':self.spec['operation_id'],
                'spec_sha256':c.helper.sha(c.helper.encoded(self.spec)),'capture_complete':True}
        with patch.object(c.helper,'bounded',return_value={'returncode':0,'stdout':json.dumps(report),'stderr':''}):
            self.assertTrue(c.execute(args)['capture_complete'])

    def test_foreign_capture_is_not_complete(self):
        args=type('Args',(),{'bundle':self.bundle,'sha256':self.digest})()
        report={'hostname':'foreign','operation_id':self.spec['operation_id'],
                'spec_sha256':c.helper.sha(c.helper.encoded(self.spec)),'capture_complete':True}
        with patch.object(c.helper,'bounded',return_value={'returncode':0,'stdout':json.dumps(report),'stderr':''}):
            result=c.execute(args)
        self.assertFalse(result['capture_complete']);self.assertIn('binding',result['error'])

    def test_settings_exclude_credentials_and_keys(self):
        import base64
        raw=b'port=10000\nssl=1\nkeyfile=/private/key\npasswd=SECRET\nuserfile=/private/users\nallow=10.0.0.0/8\n'
        with patch.object(c.helper,'file_record',return_value={'base64':base64.b64encode(raw).decode(),'sha256':'fixture'}):
            result=c.settings()
        self.assertEqual(result['settings'],{'port':'10000','ssl':'1','allow':'10.0.0.0/8'})
        self.assertNotIn('base64',result);self.assertNotIn('SECRET',str(result));self.assertNotIn('/private',str(result))

    def test_duplicate_settings_rejected(self):
        import base64
        with patch.object(c.helper,'file_record',return_value={'base64':base64.b64encode(b'port=10000\nport=443\n').decode()}):
            with self.assertRaisesRegex(ValueError,'duplicate'):c.settings()

    def test_theme_handler_fields_are_retained_without_secrets(self):
        import base64
        raw=b'error_handler_401=401.cgi\nerror_handler_403=403.cgi\nerror_handler_404=404.cgi\npasswd=SECRET\nsession_key=SECRET\n'
        with patch.object(c.helper,'file_record',return_value={'base64':base64.b64encode(raw).decode()}):
            result=c.settings()
        self.assertEqual(result['settings'],{f'error_handler_{n}':f'{n}.cgi' for n in [401,403,404]})
        self.assertNotIn('SECRET',str(result));self.assertNotIn('base64',result)
        expected=b'passwd=SECRET\nsession_key=SECRET\n'
        self.assertEqual(result['without_default_handlers'],{'sha256':c.helper.sha(expected),'size':len(expected)})

    def test_handler_comparison_preserves_other_bytes_and_requires_exact_defaults(self):
        import base64
        prefix=b'# retained comment\nssl=0\n\n'
        defaults=b'error_handler_401=401.cgi\nerror_handler_403=403.cgi\nerror_handler_404=404.cgi\n'
        for data in [prefix+defaults, defaults+prefix, prefix+defaults.replace(b'401.cgi',b'custom.cgi')]:
            with patch.object(c.helper,'file_record',return_value={'base64':base64.b64encode(data).decode()}):
                result=c.settings()
            if b'custom.cgi' in data:self.assertNotIn('without_default_handlers',result)
            else:self.assertEqual(result['without_default_handlers']['sha256'],c.helper.sha(prefix))

    def test_timer_observation_does_not_invoke_fetch(self):
        self.run_capture()
        timer=next(a for a in self.calls if 'ntpleapfetch.timer' in a and a[1]=='show')
        self.assertIn('LastTriggerUSec',timer[-1]);self.assertIn('NextElapseUSecMonotonic',timer[-1])
        self.assertFalse(any(a[0]=='/usr/local/bin/ntpleapfetch' for a in self.calls))

    def test_changed_service_stops_capture(self):
        with patch.object(c,'boot',return_value=self.spec['boot_id']),patch.object(c.socket,'gethostname',return_value='j2-svntp1'), \
                patch.object(c.os,'geteuid',return_value=0),patch.object(c.helper,'bounded',return_value={'returncode':0,'stdout':'MainPID=99\n'}) as run:
            report=c.collect(self.spec)
        self.assertFalse(report['capture_complete']);self.assertEqual(run.call_count,1)

    def test_startup_diagnostic_is_read_only_and_excludes_unrelated_collection(self):
        self.spec.update(startup_diagnostic=True, installation_sha256='b'*64)
        report = self.run_capture()
        self.assertTrue(report['capture_complete'])
        self.assertEqual(set(report['files']), set(c.STARTUP_FILES))
        self.assertEqual(report['apt_sources'], {})
        self.assertEqual(set(report['commands']), {'service-before', 'timeservice.service', 'webmin.service',
            'packages', 'dpkg-audit', 'architecture', 'listeners', 'addresses', 'webmin-journal'})
        for argv in self.calls:
            self.assertNotIn('start', argv); self.assertNotIn('stop', argv)
            self.assertNotIn('enable', argv); self.assertNotIn('install', argv)
            if argv[0] == '/usr/bin/systemctl': self.assertEqual(argv[1], 'show')
        self.assertIn('sport = :10000', report['commands']['listeners']['argv'])
        self.assertIn('100', report['commands']['webmin-journal']['argv'])
        self.assertIn('No service start/restart/stop', c.review(self.spec))

    def test_diagnostic_payload_and_review_binding(self):
        self.spec.update(startup_diagnostic=True, installation_sha256='b'*64)
        self.files.update({'spec.json':c.helper.encoded(self.spec), 'review.md':c.review(self.spec).encode()})
        self.pack()
        spec, files = c.prepare(self.bundle, self.digest)
        compile(c.payload(spec, files), 'diagnostic-payload', 'exec')
        self.assertTrue(spec['startup_diagnostic'])
        self.assertNotIn('leap-timer inspection', files['review.md'].decode())

    def test_recovered_installation_baseline_rejects_uncertain_or_foreign_result(self):
        args = SimpleNamespace(installation_dir=self.root, installation_sha256='b'*64)
        old = {'operation_id':'install-fixture', 'service_identity':self.spec['service_identity']}
        result = {'accepted':False, 'returncode':0, 'bundle_sha256':'b'*64}
        state = {'operation_id':old['operation_id'], 'spec_sha256':c.helper.sha(c.helper.encoded(old)),
                 'recovery':'non-serving; packages retained', 'service_stopped':True}
        for name, value in [('result.json',result), ('stdout.txt',state)]:
            (self.root/name).write_bytes(c.helper.encoded(value)); (self.root/name).chmod(0o600)
        installer = SimpleNamespace(prepare=lambda path, digest: (old, {'known_hosts':b'fixture'}))
        with patch.object(c, 'load', return_value=installer):
            baseline = c.installation_baseline(args)
            self.assertEqual(baseline[2], self.spec['service_identity'])
            for field, value in [('recovery','held'), ('service_stopped',False), ('spec_sha256','foreign')]:
                broken = dict(state); broken[field] = value
                (self.root/'stdout.txt').write_bytes(c.helper.encoded(broken))
                with self.assertRaisesRegex(ValueError, 'completed non-serving'):
                    c.installation_baseline(args)

    def temp_capture(self, failed=False, link=False, changed=False):
        import base64
        self.spec.update(temp_storage=True, webmin_identity=self.spec['service_identity'],
                         installation_sha256='b'*64)
        def bounded(argv):
            self.calls.append(argv)
            return {'argv':argv, 'returncode':1 if failed and 'df' in argv[0] else 0,
                    'stdout':''.join(k+'='+v+'\n' for k,v in self.spec['service_identity'].items()), 'stderr':''}
        config = {'base64':base64.b64encode(b'tempdir=/tmp/.webmin\npassword=SECRET\n').decode()}
        with patch.object(c,'boot',side_effect=[self.spec['boot_id'], 'changed' if changed else self.spec['boot_id']]), \
                patch.object(c.socket,'gethostname',return_value='j2-svntp1'), \
                patch.object(c.os,'geteuid',return_value=0), \
                patch.object(c.helper,'file_record',return_value=config), \
                patch.object(c.Path,'lstat',return_value=SimpleNamespace(st_mode=0o120777 if link else 0o41777,st_uid=0,st_gid=0)), \
                patch.object(c.helper,'bounded',side_effect=bounded):
            return c.collect(self.spec)

    def test_temp_storage_is_scoped_and_excludes_secrets(self):
        report = self.temp_capture()
        self.assertTrue(report['capture_complete'])
        self.assertEqual(report['config']['settings'], {'tempdir':'/tmp/.webmin'})
        self.assertNotIn('SECRET', str(report))
        self.assertNotIn('base64', report['config'])
        self.assertEqual(set(report['paths']), {'/tmp','/var','/var/tmp','/tmp/.webmin','/var/tmp/.webmin'})
        for argv in self.calls:
            self.assertIn(argv[0], ['/usr/bin/systemctl','/usr/bin/df','/usr/bin/findmnt','/usr/bin/du'])
            if argv[0].endswith('systemctl'): self.assertEqual(argv[1], 'show')
        self.assertIn('No write probe', c.review(self.spec))

    def test_temp_storage_failure_boot_change_and_symlink_fail_closed(self):
        self.assertFalse(self.temp_capture(failed=True)['capture_complete'])
        self.assertFalse(self.temp_capture(changed=True)['capture_complete'])
        self.calls.clear()
        self.assertFalse(self.temp_capture(link=True)['capture_complete'])
        self.assertTrue(all(a[0].endswith('systemctl') for a in self.calls))

    def test_temp_storage_payload_binding(self):
        self.spec.update(temp_storage=True, webmin_identity=self.spec['service_identity'], installation_sha256='b'*64)
        self.files.update({'spec.json':c.helper.encoded(self.spec), 'review.md':c.review(self.spec).encode()})
        self.pack()
        spec, files = c.prepare(self.bundle,self.digest)
        compile(c.payload(spec,files),'temp-payload','exec')
        self.assertTrue(spec['temp_storage'])

    def test_temp_baseline_requires_accepted_installation(self):
        args = SimpleNamespace(installation_dir=self.root, installation_sha256='b'*64, temp_storage=True)
        old = {'operation_id':'install-fixture', 'service_identity':self.spec['service_identity']}
        result = {'accepted':True, 'returncode':0, 'bundle_sha256':'b'*64}
        state = {'operation_id':old['operation_id'], 'spec_sha256':c.helper.sha(c.helper.encoded(old)),
                 'installed':True, 'recovery':'not-needed', 'webmin_unit':self.spec['service_identity']}
        for name, value in [('result.json',result), ('stdout.txt',state)]:
            (self.root/name).write_bytes(c.helper.encoded(value)); (self.root/name).chmod(0o600)
        with patch.object(c, 'load', return_value=SimpleNamespace(prepare=lambda p,d:(old,{}))):
            self.assertEqual(c.installation_baseline(args)[3]['webmin_identity'], self.spec['service_identity'])
            state['installed'] = False
            (self.root/'stdout.txt').write_bytes(c.helper.encoded(state))
            with self.assertRaisesRegex(ValueError, 'accepted installation'):
                c.installation_baseline(args)

    def test_mail_scope_and_missing_configuration(self):
        self.spec.update(mail_reporting=True, installation_sha256='b'*64)
        report = self.run_capture()
        self.assertTrue(report['capture_complete'])
        self.assertEqual(set(report['mail_files']),set(c.MAIL_FILES))
        self.assertEqual(report['mail_settings']['selected_directives'], [])
        self.assertEqual(report['apt_sources'], {})
        self.assertEqual(report['webmin'], {'not_collected': True})
        for argv in self.calls:
            self.assertNotIn('start',argv); self.assertNotIn('restart',argv)
            self.assertNotIn('enable',argv); self.assertNotIn('install',argv)
            self.assertNotIn(argv[0], ['/usr/sbin/sendmail','/usr/bin/msmtp','/usr/sbin/needrestart'])
        self.assertNotIn('host-firewall',report['commands'])
        self.assertIn('timer-list',report['commands'])
        self.assertIn('timer-effective',report['commands'])
        self.assertIn('AccuracyUSec',report['commands']['ntpleapfetch.timer']['argv'][-1])
        self.assertFalse(self.run_capture(fail=True)['capture_complete'])
        self.assertFalse(self.run_capture(changed=True)['capture_complete'])

    def test_mail_settings_exclude_secrets_and_commands(self):
        import base64
        raw = b'account default\nhost relay.example\nport 8025\nauth off\npassword SECRET\npasswordeval cat /secret\nfrom $(cat /secret)\n'
        with patch.object(c.helper,'file_record',return_value={'base64':base64.b64encode(raw).decode()}):
            result = c.mail_settings()
        self.assertEqual(result['selected_directives'], [['account','default'],['host','relay.example'],
                         ['port','8025'],['auth','off'],['from','[unrecognized value omitted]']])
        self.assertNotIn('SECRET',str(result)); self.assertNotIn('/secret',str(result))
        self.assertNotIn('base64',result)

    def test_mail_payload_and_review_binding(self):
        self.spec.update(mail_reporting=True, installation_sha256='b'*64)
        self.files.update({'spec.json':c.helper.encoded(self.spec),'review.md':c.review(self.spec).encode()})
        self.pack()
        spec,files=c.prepare(self.bundle,self.digest)
        compile(c.payload(spec,files),'mail-payload','exec')
        self.assertIn('No SMTP connection',files['review.md'].decode())

    def test_timer_recurrence_scope(self):
        self.spec.update(timer_recurrence=True, installation_sha256='b'*64)
        report = self.run_capture()
        self.assertTrue(report['capture_complete'])
        self.assertNotIn('mail_settings',report)
        self.assertEqual(report['apt_sources'],{})
        self.assertIn('timer-manual',report['commands'])
        self.assertIn('--since=-4h',report['commands']['manager-journal']['argv'])
        self.assertIn('_PID=1',report['commands']['manager-journal']['argv'])
        for argv in self.calls:
            if argv[0]=='/usr/bin/systemctl':
                self.assertIn(argv[1],('show','cat','list-timers','--version'))
        self.assertFalse(self.run_capture(changed=True)['capture_complete'])

    def test_timer_recurrence_payload_binding(self):
        self.spec.update(timer_recurrence=True, installation_sha256='b'*64)
        self.files.update({'spec.json':c.helper.encoded(self.spec),'review.md':c.review(self.spec).encode()})
        self.pack()
        spec,files=c.prepare(self.bundle,self.digest)
        compile(c.payload(spec,files),'recurrence-payload','exec')
        self.assertIn('No relay contact',files['review.md'].decode())


if __name__ == '__main__': unittest.main()
