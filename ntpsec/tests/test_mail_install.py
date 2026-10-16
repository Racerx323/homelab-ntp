#!/usr/bin/python3
"""Offline install ordering, recovery, exact-send and sealed input regression tests."""
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import time
import types
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
def load(path):
    s=importlib.util.spec_from_file_location(path.stem,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
r=load(ROOT/'scripts/run-mail-install.py')
w=load(ROOT/'scripts/mail-install.py')


class Fixture(w.Install):
    def __init__(self,root,fail=None):
        self.fail=fail;self.calls=[];self.package_installed=False
        spec={'operation_id':'fixture','packages_before':{'existing':['1','ii ']},
              'packages':[{'package':'msmtp','version':'1'}]}
        inputs={k:b'fixture\n' for k in w.FILES}
        inputs.update({'report.eml':b'report','failure.eml':b'failure'})
        super().__init__(spec,inputs,r.h);self.root=root/'state'
    def preflight(self):
        self.root.mkdir();self.created=True;self.package_paths=['/fixture/msmtp.deb'];self.save()
    def continuity(self): self.calls.append('continuity')
    def inventory(self):
        return {'existing':['1','ii '],'msmtp':['1','ii ']} if self.package_installed else self.spec['packages_before']
    def unit(self,name):return {'ActiveState':'inactive','UnitFileState':'masked'}
    def accept_files(self):
        self.calls.append('accept')
        for member,(name,mode) in w.FILES.items():
            assert Path(name).read_bytes()==self.inputs[member]
            assert Path(name).stat().st_mode & 0o777 == mode
    def cmd(self,argv,timeout=30,payload=None,accepted=(0,)):
        self.calls.append(argv)
        if argv[:2]==['/usr/bin/dpkg','--install']:
            assert w.MASK.is_symlink();self.package_installed=True
            if self.fail=='install':raise ValueError('fixture install failure')
        if argv[0]=='/usr/sbin/sendmail':
            assert 'accept' in self.calls
            member='report.eml' if payload==b'report' else 'failure.eml'
            saved=json.loads((self.root/'state.json').read_text())
            assert saved['messages'][member]['attempted']
            if self.fail==member:raise ValueError('fixture send failure')
        return ''


class Installation(unittest.TestCase):
    def fixture(self,fail=None):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);root=Path(tmp.name)
        files={k:(str(root/k),mode) for k,(_,mode) in w.FILES.items()}
        p=patch.object(w,'FILES',files);p.start();self.addCleanup(p.stop)
        p=patch.object(w,'MASK',root/'msmtpd.service');p.start();self.addCleanup(p.stop)
        return Fixture(root,fail)

    def test_success_masks_listener_before_install_and_submits_exactly_twice(self):
        job=self.fixture();state=job.run()
        self.assertTrue(state['accepted']);self.assertTrue(state['installed'])
        self.assertFalse(state['delivery_verified']);self.assertFalse(state['cron_active'])
        sends=[a for a in job.calls if isinstance(a,list) and a[0]=='/usr/sbin/sendmail']
        self.assertEqual(len(sends),2)
        self.assertTrue(all(m['smtp_accepted'] for m in state['messages'].values()))
        self.assertTrue(w.MASK.is_symlink())
        self.assertFalse(any(isinstance(a,list) and ('start' in a or 'enable' in a) for a in job.calls))

    def test_install_failure_retains_mask_and_never_sends(self):
        job=self.fixture('install');state=job.run()
        self.assertFalse(state['accepted']);self.assertEqual(state['messages'],{})
        self.assertTrue(w.MASK.is_symlink());self.assertTrue(job.package_installed)
        self.assertIn('packages and listener mask retained',state['recovery'])

    def test_send_failure_is_not_retried_and_files_withdrawn(self):
        job=self.fixture('report.eml');state=job.run()
        self.assertFalse(state['accepted']);self.assertEqual(set(state['messages']),{'report.eml'})
        self.assertFalse(state['messages']['report.eml']['smtp_accepted'])
        self.assertEqual(sum(isinstance(a,list) and a[0]=='/usr/sbin/sendmail' for a in job.calls),1)
        self.assertTrue(all(not Path(p).exists() for p,_ in w.FILES.values()))
        self.assertTrue(w.MASK.is_symlink())

    def test_second_message_failure_preserves_first_submission_without_retry(self):
        job=self.fixture('failure.eml');state=job.run()
        self.assertFalse(state['accepted']);self.assertFalse(state['installed'])
        self.assertTrue(state['messages']['report.eml']['smtp_accepted'])
        self.assertFalse(state['messages']['failure.eml']['smtp_accepted'])
        self.assertEqual(sum(isinstance(a,list) and a[0]=='/usr/sbin/sendmail' for a in job.calls),2)

    def test_exclusive_writes_reject_existing_file_or_symlink(self):
        job=self.fixture();path=job.root.parent/'destination';path.write_text('existing')
        with self.assertRaises(FileExistsError):job.write_new(path,b'new',0o600)
        self.assertEqual(path.read_text(),'existing')
        link=job.root.parent/'link';link.symlink_to(path)
        with self.assertRaises(FileExistsError):job.write_new(link,b'new',0o600)
        self.assertEqual(path.read_text(),'existing')

    def test_real_continuity_rejects_changed_ntp_identity(self):
        job=self.fixture();job.spec.update(boot_id='boot',service_identity={'MainPID':'814'})
        with patch.object(w,'Path') as path,patch.object(job,'unit',return_value={'MainPID':'999'}):
            path.return_value.read_text.return_value='boot'
            with self.assertRaisesRegex(ValueError,'NTP identity'):w.Install.continuity(job)

    def test_foreign_file_holds_recovery(self):
        job=self.fixture();job.apply()
        Path(w.FILES['cron.pending'][0]).write_text('foreign')
        with self.assertRaisesRegex(ValueError,'foreign'):job.recover()
        self.assertEqual(Path(w.FILES['cron.pending'][0]).read_text(),'foreign')

    def test_early_failure_never_mutates(self):
        job=self.fixture()
        with patch.object(job,'preflight',side_effect=ValueError('baseline changed')):
            state=job.run()
        self.assertFalse(state['accepted']);self.assertFalse(job.mutated)
        self.assertFalse(w.MASK.exists());self.assertEqual(state['messages'],{})

    def test_rendered_messages_match_policy_and_schedule_stays_pending(self):
        files={n:p.read_bytes() for n,p in r.SOURCES.items() if p.exists()}
        rendered=r.render(files,'mail-install-20261015-v1')
        self.assertIn(b'from j2-svntp1@local.theama.co\n',rendered['msmtprc'])
        self.assertNotIn(b'@MAIL',rendered['msmtprc'])
        self.assertIn(b'To: notify@mailrise.xyz\n',rendered['report.eml'])
        self.assertIn(b'To: notify.failure@mailrise.xyz\n',rendered['failure.eml'])
        self.assertIn(b'30 5 * * * root',rendered['cron.pending'])
        self.assertNotIn('/etc/cron.d',w.FILES['cron.pending'][0])

    def test_archive_binding_and_single_use(self):
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp);files={n:p.read_bytes() for n,p in r.SOURCES.items()}
            files.update(r.render(files,'fixture'));files['known_hosts']=b'fixture\n'
            now=int(time.time());spec={'operation_id':'fixture','hostname':'j2-svntp1','boot_id':'fixture',
                'packages':[],'prepared_epoch':now,'expires_epoch':now+86400}
            spec['members']={n:r.h.sha(v) for n,v in files.items()}
            files['spec.json']=r.h.encoded(spec);files['review.md']=r.review(spec,files).encode()
            for n,v in files.items():
                (d/n).write_bytes(v);(d/n).chmod(0o600)
            with tarfile.open(d/'mail-install.tar','w') as t:
                for n,v in files.items():
                    info=tarfile.TarInfo(n);info.size=len(v);t.addfile(info,io.BytesIO(v))
            (d/'mail-install.tar').chmod(0o600);digest=r.h.sha((d/'mail-install.tar').read_bytes())
            r.prepare(d,digest)
            args=types.SimpleNamespace(directory=d,sha256=digest)
            with patch.object(r.h,'bounded',return_value={'returncode':255,'stdout':'partial','stderr':'failed'}) as call:
                self.assertFalse(r.execute(args)['accepted'])
                compile(call.call_args.kwargs['payload'],'remote','exec')
                with self.assertRaises(FileExistsError):r.execute(args)
                self.assertEqual(call.call_count,1)
            (d/'report.eml').write_text('changed')
            with self.assertRaisesRegex(ValueError,'review drift'):r.prepare(d,digest)


if __name__=='__main__':unittest.main()
