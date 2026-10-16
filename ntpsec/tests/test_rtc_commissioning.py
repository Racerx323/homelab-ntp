#!/usr/bin/python3
"""Offline install recovery, RTC gating and sealed transport regression checks."""
import base64
import copy
import importlib.util
import io
import json
import os
import shutil
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import tarfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
entry = importlib.util.spec_from_file_location('rtc_runner', ROOT/'scripts/run-rtc-commissioning.py')
c = importlib.util.module_from_spec(entry); entry.loader.exec_module(c)
w = c.worker


class Worker(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name, content in {'etc/os-release': 'VERSION_CODENAME=trixie\n',
                              'proc/sys/kernel/random/boot_id': 'a'*8+'-'+ 'b'*4+'-'+ 'c'*4+'-'+ 'd'*4+'-'+ 'e'*12,
                              'sys/class/rtc/rtc0/since_epoch': str(int(time.time()))}.items():
            p = self.root/name; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(content)
        (self.root/'var/lib').mkdir(parents=True)
        self.spec = {'hostname':'j2-svntp1', 'operation_id':'fixture', 'action':'install',
                     'boot_id':(self.root/'proc/sys/kernel/random/boot_id').read_text(),
                     'expires_epoch':int(time.time())+3600,'payload_paths':['/usr/sbin/hwclock']}
        self.packages = {k:[v[1],'ii '] for k,v in w.DEPENDENCIES.items()}
        self.calls = []; self.diversions = ''; self.install_fail = False; self.unrelated_change = False
        self.timing = 'leap=00, stratum=1, refid=PPS, offset=0.02, rootdisp=2.0'
        self.service = 'ActiveState=active\nSubState=running\nMainPID=123\nNRestarts=0\nInvocationID=abc\n'
        self.utility = False
        self.stack = []
        for obj,name,value in [(w,'Path',lambda p:self.root/str(p).lstrip('/')),
                               (w.socket,'gethostname',lambda:'j2-svntp1'),
                               (w.os,'geteuid',lambda:0),
                               (w.os,'uname',lambda:SimpleNamespace(machine='aarch64')),
                               (w,'helper',SimpleNamespace(bounded=self.command,LIMIT=1024*1024,file_record=self.file_record))]:
            context=patch.object(obj,name,value,create=True);context.start();self.addCleanup(context.stop)

    def file_record(self,path):
        if path == '/etc/adjtime': return {'missing':True}
        if path == '/usr/sbin/hwclock': return {'sha256':w.HWCLOCK_SHA}
        if path == '/usr/share/man/man8/hwclock.8.gz': return {'sha256':w.MANUAL_SHA}
        return {'sha256':'f'*64}

    def command(self,argv,**kwargs):
        for directory in ('/usr/sbin', '/sbin'):
            self.assertIn(directory, kwargs['env']['PATH'].split(':'))
        self.calls.append(argv);out='';rc=0
        if argv[:2] == ['/usr/bin/dpkg-query','-W']:
            out=''.join(f'{k}\t{v[0]}\t{v[1]}\n' for k,v in self.packages.items())
        elif argv[0] == '/usr/bin/dpkg-divert': out=self.diversions
        elif '--print-architecture' in argv: out='arm64\n'
        elif argv[0] == '/usr/bin/systemctl': out=self.service
        elif argv[0] == '/usr/bin/timedatectl':
            self.assertEqual(argv, ['/usr/bin/timedatectl', 'show'])
            out='Timezone=America/Chicago\nLocalRTC=no\nCanNTP=yes\nNTP=no\nNTPSynchronized=yes\n'
        elif argv[0] == '/usr/local/bin/ntpq': out=self.timing
        elif '--install' in argv:
            self.packages[w.PACKAGE]=[w.VERSION,'ii '];self.diversions='fixture new diversions\n'
            if self.unrelated_change:self.packages['unrelated']=['1','ii ']
            if self.install_fail:rc=1
        elif '--remove' in argv:
            self.packages.pop(w.PACKAGE,None);self.diversions=''
        elif '--systohc' in argv:
            (self.root/'sys/class/rtc/rtc0/since_epoch').write_text(str(int(time.time())))
        elif '--show' in argv:out='2026-10-15 18:00:00+00:00\n'
        return {'argv':argv,'returncode':rc,'stdout':out,'stderr':''}

    def run_install(self):
        raw=b'x'*290088
        with patch.object(w,'PACKAGE_SHA',c.helper.sha(raw)):
            return w.run(self.spec,base64.b64encode(raw).decode())

    def test_install_acceptance_and_no_clock_invocation(self):
        state=self.run_install()
        self.assertTrue(state['accepted'],state.get('error'))
        self.assertEqual(sum('--install' in a for a in self.calls),1)
        self.assertFalse(any(a[0].endswith('/hwclock') for a in self.calls))
        with self.assertRaises(FileExistsError):self.run_install()

    def test_package_command_environment_resolves_required_admin_tools(self):
        captured = []
        def execute(argv, **kwargs):
            captured.append(kwargs['env'])
            for tool in ('ldconfig', 'start-stop-daemon'):
                self.assertIsNotNone(shutil.which(tool, path=kwargs['env']['PATH']))
            return {'returncode': 0, 'stdout': '', 'stderr': ''}
        with patch.object(w.helper, 'bounded', side_effect=execute):
            w.command(['/usr/bin/dpkg', '--install', '/fixture.deb'], [])
            w.command(['/usr/bin/dpkg', '--remove', w.PACKAGE], [])
        self.assertEqual(captured[0], captured[1])
        self.assertEqual(captured[0]['DEBIAN_FRONTEND'], 'noninteractive')

    def test_missing_dependency_holds_before_install(self):
        del self.packages['libsmartcols1']
        state=self.run_install()
        self.assertFalse(state['mutation_started'])
        self.assertFalse(any('--install' in a for a in self.calls))

    def test_existing_payload_holds(self):
        p=self.root/'usr/sbin/hwclock';p.parent.mkdir(parents=True);p.write_text('existing')
        state=self.run_install()
        self.assertFalse(state['mutation_started'])
        self.assertIn('already exists',state['error'])

    def test_partial_install_recovers_only_new_package(self):
        self.install_fail=True
        state=self.run_install()
        self.assertFalse(state['accepted']);self.assertTrue(state['package_recovered'])
        self.assertEqual([a for a in self.calls if '--remove' in a],[['/usr/bin/dpkg','--remove',w.PACKAGE]])

    def test_unrelated_package_change_holds_recovery(self):
        self.unrelated_change=True
        state=self.run_install()
        self.assertIn('unrelated',state['recovery_error'])
        self.assertFalse(any('--remove' in a for a in self.calls))

    def setup_rtc(self):
        self.spec['action']='set-readback';self.packages[w.PACKAGE]=[w.VERSION,'ii ']

    def test_rtc_write_once_noadjfile_and_no_package_mutation(self):
        self.setup_rtc()
        with patch.object(w,'rtc_identity'):
            state=w.run(self.spec,'')
        self.assertTrue(state['accepted'],state.get('error'))
        writes=[a for a in self.calls if '--systohc' in a]
        self.assertEqual(writes,[['/usr/sbin/hwclock','--systohc','--utc','--noadjfile','--rtc=/dev/rtc0']])
        self.assertFalse(any('--install' in a or '--remove' in a or '--hctosys' in a for a in self.calls))

    def test_unsynchronized_rtc_holds_before_write(self):
        self.setup_rtc();self.timing='leap=11, stratum=16, refid=INIT, offset=0, rootdisp=0'
        with patch.object(w,'rtc_identity'):state=w.run(self.spec,'')
        self.assertFalse(state['mutation_started'])
        self.assertFalse(any('--systohc' in a for a in self.calls))

    def test_empty_clock_properties_hold_before_device_access(self):
        self.setup_rtc()
        original = self.command
        def empty_clock(argv, **kwargs):
            if argv[0] == '/usr/bin/timedatectl':
                return {'argv':argv,'returncode':0,'stdout':'','stderr':''}
            return original(argv, **kwargs)
        with patch.object(w, 'rtc_identity'), patch.object(w.helper, 'bounded', side_effect=empty_clock):
            state = w.run(self.spec, '')
        self.assertFalse(state['mutation_started'])
        self.assertFalse(any(a[0].endswith('/hwclock') for a in self.calls))

    def test_bad_rtc_readback_never_restores_stale_timestamp(self):
        self.setup_rtc()
        with patch.object(w,'rtc_identity'),patch.object(w,'check_readback',side_effect=ValueError('bad readback')):
            state=w.run(self.spec,'')
        self.assertFalse(state['accepted']);self.assertTrue(state['mutation_started'])
        self.assertEqual(sum('--systohc' in a for a in self.calls),1)
        self.assertFalse(any('--set' in a or '--hctosys' in a for a in self.calls))

    def test_wrong_rtc_identity_prevents_write(self):
        self.setup_rtc()
        with patch.object(w,'rtc_identity',side_effect=ValueError('RTC identity changed')):
            state=w.run(self.spec,'')
        self.assertFalse(state['mutation_started'])
        self.assertFalse(any(a[0].endswith('/hwclock') for a in self.calls))

    def test_timing_and_readback_limits(self):
        for text in ('',self.timing.replace('0.02','nan'),self.timing.replace('2.0','inf'),self.timing.replace('0.02','1.1')):
            with self.subTest(text=text),self.assertRaises(ValueError):w.timing_ready(text)
        w.check_readback({'before_epoch':100,'after_epoch':101,'rtc_epoch':99})
        with self.assertRaises(ValueError):w.check_readback({'before_epoch':100,'after_epoch':101,'rtc_epoch':90})


class Sealing(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.source=self.root/'source';self.source.mkdir(mode=0o700)
        os.umask(0o077)
        old={'hostname':'j2-svntp1','endpoints':['10.1.0.51','fd36:5aa8:6971:1::51'],
             'host_key_alias':'10.1.0.137','members':{'known_hosts':c.helper.sha(b'fixture')}}
        with tarfile.open(self.source/'production-inspection.tar','w') as t:
            for name,raw in {'spec.json':c.helper.encoded(old),'known_hosts':b'fixture'}.items():
                item=tarfile.TarInfo(name);item.size=len(raw);t.addfile(item,io.BytesIO(raw))
        digest=c.helper.sha((self.source/'production-inspection.tar').read_bytes())
        (self.source/'sealing.json').write_bytes(c.helper.encoded({'sha256':digest}))
        (self.source/'result.json').write_bytes(c.helper.encoded({'capture_complete':True,'bundle_sha256':digest}))
        boot='aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        (self.source/'stdout.txt').write_bytes(c.helper.encoded({'hostname':'j2-svntp1','boot_before':boot,'boot_after':boot,'spec_sha256':c.helper.sha(c.helper.encoded(old))}))
        args=SimpleNamespace(inspection_dir=self.source,inspection_sha256=digest,action_name='set-readback',operation_id='rtc-fixture',output=self.root/'bundle',package=None)
        self.sealed=c.seal(args);self.bundle=Path(self.sealed['bundle'])

    def test_flat_package_free_rtc_bundle_and_tamper_rejection(self):
        spec,files=c.prepare(self.bundle,self.sealed['sha256'])
        self.assertNotIn('package.deb',files)
        self.assertFalse(any(n.endswith('.tar') for n in files))
        with self.assertRaisesRegex(ValueError,'hash'):c.prepare(self.bundle,'0'*64)
        (self.bundle.parent/'review.md').write_text('tampered')
        with self.assertRaisesRegex(ValueError,'approval'):c.prepare(self.bundle,self.sealed['sha256'])

    def test_transport_compiles_registers_and_never_replays(self):
        def capture(argv,**kwargs):
            self.assertTrue((self.bundle.parent/'execution.json').exists())
            compile(kwargs['payload'],'remote','exec')
            return {'returncode':255,'stdout':'partial','stderr':'failure'}
        args=SimpleNamespace(bundle=self.bundle,sha256=self.sealed['sha256'])
        with patch.object(c.helper,'bounded',side_effect=capture) as call:
            result=c.execute(args);self.assertFalse(result['accepted'])
            with self.assertRaises(FileExistsError):c.execute(args)
            self.assertEqual(call.call_count,1)


if __name__=='__main__':
    unittest.main()
