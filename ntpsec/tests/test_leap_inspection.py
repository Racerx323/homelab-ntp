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
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
entry = importlib.util.spec_from_file_location('leap_inspection', ROOT/'scripts/run-leap-inspection.py')
c = importlib.util.module_from_spec(entry); entry.loader.exec_module(c)
c.helper = c.load(ROOT/'scripts/run-production-inspection.py')


class Inspection(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.calls = []
        self.spec = {'schema': 1, 'purpose': 'leap-inspection', 'hostname': 'j2-svntp1',
            'operation_id': 'leap-fixture', 'boot_id': 'a'*8+'-'+'b'*4+'-'+'c'*4+'-'+'d'*4+'-'+'e'*12,
            'endpoints': ['192.0.2.1','2001:db8::1'], 'host_key_alias': '192.0.2.2',
            'boot_sha256': 'a'*64, 'client_sha256': 'b'*64,
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
            if fail and argv[0]=='/usr/local/bin/ntpq':raise FileNotFoundError('missing ntpq')
            return {'argv':argv,'returncode':0,'stdout':'fixture','stderr':''}
        with patch.object(c,'boot',side_effect=[self.spec['boot_id'],'other' if changed else self.spec['boot_id']]), \
                patch.object(c.socket,'gethostname',return_value='j2-svntp1'),patch.object(c.os,'geteuid',return_value=0), \
                patch.object(c,'Path',return_value=self.root), \
                patch.object(c.helper,'file_record',return_value={'missing':True}), \
                patch.object(c.helper,'bounded',side_effect=bounded):
            return c.collect(self.spec)

    def test_reads_only_and_retains_missing_files(self):
        result=self.run_capture();self.assertTrue(result['capture_complete'])
        self.assertEqual(set(result['files']),set(c.FILES))
        self.assertTrue(all(r.get('missing') for r in result['files'].values()))
        for argv in self.calls:
            self.assertIn(argv[0],('/usr/bin/systemctl','/usr/local/bin/ntpq','/usr/bin/journalctl'))
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


if __name__ == '__main__': unittest.main()
