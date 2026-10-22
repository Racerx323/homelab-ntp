#!/usr/bin/python3
"""Offline checks of actual completion paths and guarded stage boundaries."""
import contextlib
import importlib.util
import io
import json
import os
import fcntl
from pathlib import Path
import subprocess
import tarfile
import tempfile
import time
import types
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]


def load(name):
    path=ROOT/'scripts'/name
    spec=importlib.util.spec_from_file_location(path.stem,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


r=load('run-munin-stage.py');p=load('install-maintenance-producers.py')
h=load('maintenance-success.py');mail=load('mail-reporting.py')


class CompletionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='.completion-test-',dir=ROOT)
        self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.state=self.root/'state';self.state.mkdir(mode=0o700)
        # This sandbox maps / and /home to nobody; model only their production
        # root ownership. All directory modes and private file writes are real.
        actual_lstat=Path.lstat
        def ownership(path):
            info=actual_lstat(path)
            if path in (Path('/'),Path('/home')):
                return types.SimpleNamespace(**{name:(0 if name=='st_uid' else getattr(info,name))
                                               for name in dir(info) if name.startswith('st_')})
            return info
        handle=patch.object(Path,'lstat',ownership);handle.start();self.addCleanup(handle.stop)

    def test_atomic_success_and_reader_schema(self):
        h.write_success(self.state,'reporting')
        path=self.state/'last-success.json';data=json.loads(path.read_text())
        self.assertEqual((data['schema'],data['job'],data['status']),(1,'reporting','success'))
        self.assertLess(abs(time.time()-data['completed_epoch']),2)
        self.assertEqual(path.stat().st_mode&0o777,0o600)
        original=path.read_bytes()
        with patch.object(h.os,'getegid',return_value=os.getegid()+1):
            with self.assertRaises(ValueError):h.write_success(self.state,'reporting')
        with patch.object(h.os,'replace',side_effect=OSError('interrupted')):
            with self.assertRaises(OSError):h.write_success(self.state,'reporting')
        self.assertEqual(path.read_bytes(),original)
        self.assertEqual(list(self.state.iterdir()),[path])

    def test_indirect_shared_mode_and_parent_rejected(self):
        target=self.root/'target';target.write_text('preserve');target.chmod(0o600)
        path=self.state/'last-success.json';path.symlink_to(target)
        with self.assertRaises(ValueError):h.write_success(self.state,'reporting')
        path.unlink();os.link(target,path)
        with self.assertRaises(ValueError):h.write_success(self.state,'reporting')
        path.unlink();path.touch(mode=0o644);path.chmod(0o644)
        with self.assertRaises(ValueError):h.write_success(self.state,'reporting')
        path.unlink();self.state.chmod(0o755)
        with self.assertRaises(ValueError):h.write_success(self.state,'reporting')

    def test_actual_cleanup_boundary_active_links_and_noop(self):
        stats=self.root/'stats';stats.mkdir()
        for stream in h.STREAMS:(stats/stream).touch()
        def dated(name,age):
            q=stats/name;q.write_text('data');stamp=time.time()-age*86400;os.utime(q,(stamp,stamp));return q
        expired=dated('protostats.20200101',30.01)
        keep=dated('peerstats.20200101',29.99)
        unrelated=dated('foreign.20200101',40)
        compressed=dated('clockstats.20200101.gz',40)
        linked=dated('loopstats.20200101',40);os.link(linked,stats/'other-link')
        active=stats/'protostats.20190101';os.link(stats/'protostats',active)
        with patch.object(h,'retention',side_effect=lambda:h.retention_original(stats)),patch.object(h,'DIRECTORIES',{'retention':self.state}):
            h.complete('retention');h.complete('retention')
        self.assertFalse(expired.exists());self.assertFalse(compressed.exists())
        for q in (keep,unrelated,linked,active):self.assertTrue(q.exists())
        old=(self.state/'last-success.json').read_bytes()
        (stats/'protostats').unlink()
        with patch.object(h,'retention',side_effect=lambda:h.retention_original(stats)),patch.object(h,'DIRECTORIES',{'retention':self.state}):
            with self.assertRaises(FileNotFoundError):h.complete('retention')
        self.assertEqual((self.state/'last-success.json').read_bytes(),old)

    def reporter(self,actionable=False,scan_failure=False,test=False,helper_failure=False):
        scanner=self.root/'scanner'
        scanner.write_text('#!/bin/bash\n'+('exit 7\n' if scan_failure else
            "printf 'NEEDRESTART-KSTA: 1\\n'\n"+("printf 'NEEDRESTART-SVC: example.service\\n'\n" if actionable else '')))
        scanner.chmod(0o700)
        capture=self.root/'capture';capture.write_bytes(mail.capture_program(self.root/'message'));capture.chmod(0o700)
        completion=self.root/'completion'
        completion.write_text('#!/bin/bash\n'+('exit 1\n' if helper_failure else 'touch '+str(self.root/'called')+'\n'))
        completion.chmod(0o700)
        raw=r.render_reporter((ROOT/'scripts/needrestart.sh').read_bytes())
        raw=mail.captured_reporter(raw,capture,scanner)
        raw=raw.replace(b'if ((EUID != 0)); then',b'if false; then')
        raw=raw.replace(b'/usr/bin/python3 -I -B /usr/local/libexec/ntp-maintenance-success.py reporting',str(completion).encode())
        reporter=self.root/'reporter';reporter.write_bytes(raw)
        return subprocess.run(['/bin/bash',str(reporter),*(['-t'] if test else [])],
            env={**os.environ,'RECIPIENT':'notify@mailrise.xyz'},capture_output=True,timeout=10)

    def test_quiet_reporter_records_genuine_completion(self):
        row=self.reporter();self.assertEqual(row.returncode,0,row.stderr)
        self.assertTrue((self.root/'called').exists());self.assertFalse((self.root/'message').exists())

    def test_actionable_reporter_records_after_captured_submission(self):
        row=self.reporter(actionable=True);self.assertEqual(row.returncode,0,row.stderr)
        self.assertTrue((self.root/'called').exists());self.assertIn('example.service',(self.root/'message').read_text())

    def test_test_does_not_record(self):
        row=self.reporter(test=True);self.assertEqual(row.returncode,0,row.stderr)
        self.assertFalse((self.root/'called').exists())

    def test_failed_scan_does_not_record(self):
        self.assertNotEqual(self.reporter(scan_failure=True).returncode,0)
        self.assertFalse((self.root/'called').exists())

    def test_cron_lock_skip_never_invokes_reporter(self):
        raw=(ROOT/'templates/needrestart.cron.example').read_bytes().replace(b'@CRON_RECIPIENT@',b'notify.failure@mailrise.xyz').replace(b'@ALERT_RECIPIENT@',b'notify@mailrise.xyz')
        command=mail.cron_command(raw)
        lock=self.root/'lock';lock.touch()
        reporter=self.root/'must-not-run';reporter.write_text('#!/bin/bash\ntouch '+str(self.root/'called')+'\n');reporter.chmod(0o700)
        command=command.replace('/run/lock/needrestart-check.lock',str(lock)).replace('/usr/local/sbin/needrestart.sh',str(reporter))
        with lock.open('r+') as held:
            fcntl.flock(held,fcntl.LOCK_EX|fcntl.LOCK_NB)
            row=subprocess.run(['/bin/bash','-c',command],capture_output=True,timeout=5)
        self.assertEqual(row.returncode,1,row.stderr);self.assertFalse((self.root/'called').exists())
        self.assertIn(b'lock may already be held',row.stdout)

    def test_writer_failure_propagates_existing_reporter_failure(self):
        row=self.reporter(helper_failure=True);self.assertNotEqual(row.returncode,0)
        self.assertIn('completion record failed',(self.root/'message').read_text())

    def test_retention_render_calls_only_real_helper(self):
        raw=r.render_rule((ROOT/'templates/ntpstats-retention.logrotate').read_bytes())
        self.assertIn(b'firstaction\n        /usr/bin/python3 -I -B /usr/local/libexec/ntp-maintenance-success.py retention\n',raw)
        self.assertNotIn(b'postrotate',raw);self.assertNotIn(b'find ',raw)
        with self.assertRaises(ValueError):r.render_reporter(b'unexpected')

    def test_real_logrotate_debug_does_not_advance_success(self):
        control=self.root/'control';control.mkdir(mode=0o700);(control/'trigger').touch(mode=0o600)
        raw=r.render_rule((ROOT/'templates/ntpstats-retention.logrotate').read_bytes())
        # Debug must not execute firstaction at all; this marker command has no job or transport.
        raw=raw.replace(b'/usr/bin/python3 -I -B /usr/local/libexec/ntp-maintenance-success.py retention',b'touch '+str(self.root/'called').encode())
        import pwd,grp
        user=pwd.getpwuid(os.getuid()).pw_name;group=grp.getgrgid(os.getgid()).gr_name
        raw=raw.replace(b'/var/lib/ntpstats-retention',str(control).encode()).replace(b'0600 root root',f'0600 {user} {group}'.encode()).replace(b'su root root',f'su {user} {group}'.encode())
        config=self.root/'rule';config.write_bytes(raw)
        row=subprocess.run(['/usr/sbin/logrotate','--debug','--state',str(control/'state'),str(config)],capture_output=True,timeout=5)
        self.assertEqual(row.returncode,0,row.stderr);self.assertFalse((self.root/'called').exists())


h.retention_original=h.retention


class ProducerInstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name);self.inputs=root/'inputs';self.inputs.mkdir()
        self.targets=[root/n for n in ('helper','reporter','rule')]
        files={}
        for index,q in enumerate(self.targets):
            old=None if index==0 else b'original'
            if old:q.write_bytes(old);q.chmod(0o644)
            source=str(index);(self.inputs/source).write_bytes(b'changed'+bytes([index]))
            files[str(q)]={'before_sha256':p.sha(old) if old else None,'after_sha256':p.sha((self.inputs/source).read_bytes()),'mode':0o644,'input':source}
        self.job=p.Installer({'state_root':str(root/'state'),'input_root':str(self.inputs),'files':files,'package_inventory_sha256':p.sha(b'inventory')},'digest')
        def local_read(q,**kwargs):return Path(q).read_bytes(),Path(q).stat()
        for obj,name,value in ((p,'read',local_read),(p,'TARGETS',tuple(map(str,self.targets))),(p,'DIRECTORIES',()),
                               (self.job,'continuity',lambda:None),(self.job,'locks',lambda:[]),(self.job,'command',lambda args:'inventory')):
            handle=patch.object(obj,name,value);handle.start();self.addCleanup(handle.stop)

    def test_install_and_conditional_reverse_restore(self):
        self.assertTrue(self.job.install()['accepted'])
        result=self.job.recover();self.assertEqual(result['recovery'],'restored')
        self.assertFalse(self.targets[0].exists())
        self.assertEqual(self.targets[1].read_bytes(),b'original')

    def test_foreign_change_held_and_preserved(self):
        self.job.install();self.targets[1].write_bytes(b'foreign')
        result=self.job.recover();self.assertEqual(result['recovery'],'held')
        self.assertEqual(self.targets[1].read_bytes(),b'foreign')

    def test_inventory_and_input_drift_before_hook_mutation(self):
        with patch.object(self.job,'command',return_value='changed'):
            with self.assertRaises(ValueError):self.job.install()
        self.assertFalse(self.job.root.exists())
        (self.inputs/'2').write_bytes(b'drift')
        with self.assertRaises(ValueError):self.job.install()
        self.assertFalse(self.targets[0].exists());self.assertEqual(self.targets[1].read_bytes(),b'original')

    def test_failure_after_atomic_write_before_state_save_recovers_intent(self):
        original=p.atomic
        def fail(path,data,mode):
            original(path,data,mode)
            if Path(path)==self.targets[1]:raise OSError('after replace')
        with patch.object(p,'atomic',side_effect=fail):
            with self.assertRaises(OSError):self.job.install()
        self.assertEqual(self.job.recover()['recovery'],'restored')
        self.assertEqual(self.targets[1].read_bytes(),b'original')


class StageTests(unittest.TestCase):
    def archive(self,extra=None):
        spec={'kind':'producers','operation_id':'munin-test','prepared_epoch':time.time()-1,'expires_epoch':time.time()+86400,'input_members':[]}
        files={n:b'' for n in ('helper.py','worker.py','review.md','known_hosts')}
        files.update({'runner.py':Path(r.__file__).read_bytes(),'spec.json':r.encoded(spec)})
        if extra:files.update(extra)
        files['manifest.json']=r.encoded({k:r.sha(v) for k,v in files.items()})
        out=io.BytesIO()
        with tarfile.open(fileobj=out,mode='w') as archive:
            for n,raw in files.items():
                entry=tarfile.TarInfo(n);entry.size=len(raw);archive.addfile(entry,io.BytesIO(raw))
        raw=out.getvalue();return raw,r.sha(raw),files

    def test_closed_archive_tamper_path_and_expiry(self):
        raw,digest,_=self.archive();self.assertEqual(r.archive_files(raw,digest)[0]['kind'],'producers')
        with self.assertRaises(ValueError):r.archive_files(raw+b'x',digest)
        for name in ('../bad','/bad','a//b','extra'):
            raw,digest,_=self.archive({name:b'x'})
            with self.assertRaises(ValueError):r.archive_files(raw,digest)
        raw,digest,_=self.archive()
        with patch.object(r.time,'time',return_value=time.time()+86000):
            with self.assertRaises(ValueError):r.archive_files(raw,digest)
            self.assertEqual(r.archive_files(raw,digest,0)[0]['kind'],'producers')
        with patch.object(r.time,'time',return_value=time.time()+86400):
            with self.assertRaises(ValueError):r.archive_files(raw,digest)
            with self.assertRaises(ValueError):r.archive_files(raw,digest,0)

    def test_actual_stdin_bootstrap_reaches_root_guard_and_consumes_once(self):
        raw,digest,files=self.archive()
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp);(d/'deployment.tar').write_bytes(raw)
            for n,data in files.items():(d/n).write_bytes(data)
            def bounded(argv,**kw):
                # Execute actual submitted bootstrap in a non-root namespace: no host contact.
                ns={'__name__':'__main__'}
                with patch.object(os,'geteuid',return_value=1000):
                    with self.assertRaisesRegex(ValueError,'root required'):exec(kw['payload'],ns)
                return {'returncode':1,'stdout':'','stderr':'root required'}
            helper=types.SimpleNamespace(private=lambda path,*args:Path(path).read_bytes(),ssh_argv=lambda *args:['denied'],bounded=bounded)
            args=types.SimpleNamespace(directory=d,sha256=digest,action='execute')
            self.assertEqual(r.execute(args,helper)['returncode'],1)
            with self.assertRaises(FileExistsError):r.execute(args,helper)

    def test_root_dispatch_success_early_failure_and_authored_recovery(self):
        # Exercise the outer transaction with inert worker methods. The real
        # installer first-start/recovery suite is retained separately, unchanged.
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);events=root/'events'
            code=f'''from pathlib import Path
PACKAGE_PLUGINS=['cpu','load','memory','uptime','processes']
CUSTOM_PLUGINS=['ntp_health','ntp_storage','ntp_statistics','ntp_jobs']
EVENTS=Path({str(events)!r})
class Installer:
 def __init__(self,spec,digest):self.spec=spec;self.root=Path({str(root/'state')!r});self.owns_root=False;self.state={{'phase':'installed'}}
 def continuity(self):pass
 def command(self,args):
  if 'dpkg-query' in args[0]:return 'inventory'
  if self.spec.get('bad_fetch'):raise ValueError('bad fetch')
  return 'graph_title test\\nx.value 1\\nquery_ok.value 1\\nsynced.value 1\\npps_selected.value 1'
 def install(self):self.owns_root=True;EVENTS.write_text('installed')
 def recover(self):EVENTS.write_text(EVENTS.read_text()+' recovered');return {{'recovery':'contained'}}
'''.encode()
            pins={'hostname':'node','boot_id':'boot','package_inventory_sha256':r.sha(b'inventory')}
            spec={'kind':'node','operation_id':'munin-outer','worker':pins}
            real_lstat=Path.lstat;real_read=Path.read_text
            def metadata(path):
                info=real_lstat(path)
                return types.SimpleNamespace(**{n:(0 if n=='st_uid' else (info.st_mode&~0o022 if n=='st_mode' else getattr(info,n))) for n in dir(info) if n.startswith('st_')})
            def read_text(path,*args,**kwargs):
                return 'boot' if str(path)=='/proc/sys/kernel/random/boot_id' else real_read(path,*args,**kwargs)
            with contextlib.ExitStack() as stack:
                for obj,name,value in ((r,'archive_files',lambda *args:(spec,{'worker.py':code})),(r,'STAGES',root/'stages'),
                        (r.os,'geteuid',lambda:0),(r.os,'getegid',lambda:0),(r.socket,'gethostname',lambda:'node'),
                        (Path,'lstat',metadata),(Path,'read_text',read_text),(r.signal,'alarm',lambda *args:None)):
                    stack.enter_context(patch.object(obj,name,value))
                self.assertTrue(r.root_action(b'','digest','apply')['accepted'])
                self.assertEqual(events.read_text(),'installed')
                pins['bad_fetch']=True;spec['operation_id']='munin-fail'
                with self.assertRaisesRegex(ValueError,'bad fetch'):r.root_action(b'','digest','apply')
                self.assertEqual(events.read_text(),'installed recovered')
                pins['boot_id']='foreign';spec['operation_id']='munin-early'
                with self.assertRaisesRegex(ValueError,'host/boot'):r.root_action(b'','digest','apply')
                self.assertFalse((root/'stages/munin-early').exists())


if __name__=='__main__':unittest.main()
