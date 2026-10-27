#!/usr/bin/python3
"""Real local signed APT metadata/solver checks plus resolution safety boundaries."""
from email.utils import formatdate
import hashlib
import importlib.util
import json
import io
import tarfile
import os
from pathlib import Path
import pwd
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]


def load(name,file):
    spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/file)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


inspection=load('inspect_trixie','inspect-trixie.py')
with patch.dict(sys.modules,{'inspect_trixie':inspection}):f=load('foundation','resolve-trixie-packages.py')
w=load('maintenance','resolve-maintenance.py');w.f=f
m=load('snapshot','maintenance-snapshot.py');m.h=load('helper','run-production-inspection.py');w.m=m
r=load('review','review-maintenance-resolution.py')


def call(argv,env=None,okay=True):
    proc=subprocess.run(argv,env=env,capture_output=True,text=True,timeout=45)
    if okay and proc.returncode:raise AssertionError(str(argv)+'\n'+proc.stdout+proc.stderr)
    return proc


def package(name,version,extra=''):
    return f'Package: {name}\nVersion: {version}\nArchitecture: arm64\nMaintainer: Offline test <test@example.invalid>\nDescription: local metadata qualification\nFilename: pool/{name}_{version}_arm64.deb\nSize: 1\nSHA256: '+('a'*64)+'\n'+extra+'\n'


def status(name,version):
    return f'Package: {name}\nStatus: install ok installed\nArchitecture: arm64\nVersion: {version}\nDescription: offline test\nMaintainer: Test <test@example.invalid>\n\n'


class ResolutionTests(unittest.TestCase):
    def test_isolation_and_hooks(self):
        text,values=w.configuration(Path('/var/tmp/isolated'),['armhf'])
        self.assertEqual(values['Dir::Etc::preferences'],'/var/tmp/isolated/preferences')
        self.assertEqual(values['Dir::Etc::netrc'],'/var/tmp/isolated/no-auth')
        self.assertEqual(values['Dir::Bin::dpkg'],'/bin/false')
        self.assertIn('#clear APT::Architectures',text)
        # Test the actual installed apt-config parser with no live config parts.
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory);(p/'empty').mkdir()
            text,values=w.configuration(p,['armhf'])
            (p/'apt.conf').write_text(text)
            env=dict(os.environ,APT_CONFIG=str(p/'apt.conf'),LC_ALL='C')
            dump=call(['/usr/bin/apt-config','dump'],env).stdout
            w.verify_config(dump,values)
            with self.assertRaisesRegex(ValueError,'hook'):
                w.verify_config(dump+'\nAptCli::Hooks::install.pre "bad";\n',values)

    def test_native_removal_parser(self):
        installs,removals=w.native_changes('Inst one [1] (2 Test:stable [arm64])\nRemv old [1]\n')
        self.assertEqual(installs,{('one','2','arm64')});self.assertEqual(removals,{('old','1')})
        with self.assertRaises(ValueError):w.native_changes('Remv unparseable\n')

    def test_cleanup_refuses_replaced_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'stage';p.mkdir();st=p.stat()
            with self.assertRaises(ValueError):w.cleanup(p,(st.st_dev,st.st_ino+1,st.st_uid))
            self.assertTrue(p.exists())
            w.cleanup(p,(st.st_dev,st.st_ino,st.st_uid));self.assertFalse(p.exists())

    def test_wrong_hash_before_ssh_and_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory);r.c.create(p/'resolution.tar',b'invalid')
            with patch.object(r.c,'ssh',side_effect=AssertionError('network contact')):
                with self.assertRaisesRegex(ValueError,'archive SHA'):r.execute(p,'0'*64)
            self.assertFalse((p/'execution.json').exists())

    def test_expired_review_stops_before_authentication(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary)/'base-os-metadata-resolution-20261026-v1';directory.mkdir(mode=0o700)
            files={n:p.read_bytes() for n,p in r.SOURCES.items()}
            files.update({'known_hosts':b'not-used','snapshot.json':b'{}','snapshot-outcome.json':b'{}','qualification.json':b'{}','package-event.json':b'{}','package-outcome.json':b'{}'})
            spec={'purpose':'isolated-maintenance-resolution','hostname':'j2-svntp1','operation_id':directory.name,
                  'directory':str(directory),'workspace':'/var/tmp/'+directory.name,'snapshot_sha256':'0'*64,
                  'boot':'offline','kernel':'offline','prepared_epoch':int(time.time())-90000,'expires_epoch':int(time.time())-1,
                  'authentication':{'identity_file':'/not-used','public_fingerprint':'not-used'},
                  'members':{n:r.c.sha(v) for n,v in files.items()}}
            files.update({'spec.json':r.c.encoded(spec),'review.md':r.review(spec).encode()})
            buffer=io.BytesIO()
            with tarfile.open(fileobj=buffer,mode='w') as archive:
                for name,raw in files.items():
                    entry=tarfile.TarInfo(name);entry.size=len(raw);archive.addfile(entry,io.BytesIO(raw))
                    r.c.create(directory/name,raw)
            r.c.create(directory/'resolution.tar',buffer.getvalue())
            with patch.object(r.c,'authentication',side_effect=AssertionError('authentication attempted')):
                with self.assertRaisesRegex(ValueError,'window'):r.execute(directory,r.c.sha(buffer.getvalue()))
            self.assertFalse((directory/'execution.json').exists())

    def test_payload_bootstrap_and_identity_failure(self):
        files={name:path.read_bytes() for name,path in r.SOURCES.items()}
        files['snapshot.json']=b'{}'
        raw=r.payload({'operation_id':'offline','workspace':'/not-used'},files)
        proc=subprocess.run(['/usr/bin/python3','-I','-B','-'],input=raw.decode(),capture_output=True,text=True,timeout=10)
        self.assertEqual(proc.returncode,0,proc.stderr)
        row=json.loads(proc.stdout);self.assertFalse(row['resolution_complete']);self.assertFalse(row['workspace_created'])

    def test_index_tampering_and_scope_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)
            source={'base_uri':'https://example.invalid/','suite':'stable','codename':'stable','components':['main']}
            spec={'releases':[source],'foreign_architectures':[]}
            release=[{'uri':'https://example.invalid/dists/stable/InRelease','package_checksums':{'main/binary-arm64/Packages':{'sha256':'0'*64,'size':1}}}]
            index=p/'index';index.write_bytes(b'x')
            text=f'Identifier: Packages\nURI: https://example.invalid/dists/stable/main/binary-arm64/Packages\nArchitecture: arm64\nComponent: main\nTrusted: yes\nCodename: stable\nFilename: {index}\n'
            with self.assertRaisesRegex(ValueError,'signed Release'):w.verify_indexes(text,p,spec,release)
            with self.assertRaisesRegex(ValueError,'untrusted'):w.verify_indexes(text.replace('Trusted: yes','Trusted: no'),p,spec,release)

    def test_real_signed_metadata_full_solver_pin_and_rejection(self):
        # Real apt-get, gpg/gpgv and Python APT; no package installation or remote endpoint.
        import apt_pkg
        import apt
        previous=os.environ.get('APT_CONFIG')
        with tempfile.TemporaryDirectory(prefix='maintenance-native-') as directory:
            root=Path(directory);home=root/'gnupg';home.mkdir(mode=0o700)
            try:
                call(['/usr/bin/gpg','--homedir',str(home),'--batch','--pinentry-mode','loopback','--passphrase','',
                      '--quick-generate-key','Resolution qualification <test@example.invalid>','ed25519','sign','0'])
                public=call(['/usr/bin/gpg','--homedir',str(home),'--batch','--export-options','export-minimal','--armor','--export']).stdout
                key=root/'key.asc';key.write_text(public)
                repos=[]
                for name,origin,packages in [('base','BaseTest',package('base','2','Depends: added\nConflicts: old\n')+package('added','1')+package('kept','2','Depends: unavailable\n')+package('rpi-eeprom','2')+package('ntpsec','2')),
                                              ('vendor','VendorTest',package('webmin','2')+package('base','99'))]:
                    repo=root/name;release=repo/'dists/stable';(release/'main/binary-arm64').mkdir(parents=True)
                    (release/'main/binary-armhf').mkdir()
                    content=packages.encode();(release/'main/binary-arm64/Packages').write_bytes(content)
                    (release/'main/binary-armhf/Packages').write_bytes(b'')
                    body=f'Origin: {origin}\nLabel: {origin}\nSuite: stable\nCodename: stable\nDate: {formatdate(time.time(),usegmt=True)}\nValid-Until: {formatdate(time.time()+86400,usegmt=True)}\nArchitectures: arm64 armhf\nComponents: main\nSHA256:\n {hashlib.sha256(content).hexdigest()} {len(content)} main/binary-arm64/Packages\n {hashlib.sha256(b"").hexdigest()} 0 main/binary-armhf/Packages\n'
                    (release/'Release').write_text(body)
                    call(['/usr/bin/gpg','--homedir',str(home),'--batch','--yes','--pinentry-mode','loopback','--passphrase','',
                          '--clearsign','--output',str(release/'InRelease'),str(release/'Release')])
                    # gpgv consumes binary keyrings; export one for both gpgv and APT.
                    raw=subprocess.run(['/usr/bin/gpg','--homedir',str(home),'--batch','--export'],capture_output=True,check=True).stdout
                    binary=root/'key.gpg';binary.write_bytes(raw)
                    verify=call(['/usr/bin/gpgv','--homedir',str(home),'--keyring',str(binary),'--status-fd','1',str(release/'InRelease')])
                    self.assertIn('VALIDSIG',verify.stdout)
                    repos.append((repo,release))
                work=root/'work';work.mkdir()
                for name in ('empty','sources','state','lists','cache','cache/archives','log'):(work/name).mkdir()
                (work/'state/status').write_text(status('base','1')+status('webmin','1')+status('old','1')+status('kept','1')+status('rpi-eeprom','1')+status('ntpsec','1'))
                (work/'state/extended_states').write_text('')
                (work/'sources.list').write_text(''.join(f'deb [signed-by={binary}] file:{repo} stable main\n' for repo,_ in repos))
                (work/'preferences').write_text('Package: webmin\nPin: release o=VendorTest\nPin-Priority: 500\n\nPackage: *\nPin: release o=VendorTest\nPin-Priority: -1\n')
                text,values=w.configuration(work,['armhf'],pwd.getpwuid(os.geteuid()).pw_name)
                (work/'apt.conf').write_text(text)
                env=dict(os.environ,APT_CONFIG=str(work/'apt.conf'),LC_ALL='C');os.environ['APT_CONFIG']=env['APT_CONFIG']
                w.verify_config(call(['/usr/bin/apt-config','dump'],env).stdout,values)
                call(['/usr/bin/apt-get','--error-on=any','update'],env)
                native=call(['/usr/bin/apt-get','--simulate','dist-upgrade'],env).stdout
                apt_pkg.config.clear('');apt_pkg.init_config();apt_pkg.init_system()
                with apt.Cache() as cache:plan=w.full_plan(cache,native,{''},[])
                changes={p['package']:p for p in plan['changes']}
                self.assertEqual(changes['base']['version'],'2')
                self.assertEqual(changes['webmin']['version'],'2')
                self.assertEqual(changes['added']['action'],'install')
                self.assertEqual(changes['old']['action'],'remove')
                self.assertTrue(any(p['package']=='kept' for p in plan['kept_back']),json.dumps(plan)+'\n'+native)
                self.assertIn('boot-kernel-firmware-effects:rpi-eeprom',plan['findings'])
                self.assertIn('source-built-service-conflict:ntpsec',plan['findings'])
                with apt.Cache() as cache:
                    with self.assertRaisesRegex(ValueError,'held package'):w.full_plan(cache,native,{''},['base'])
                with apt.Cache() as cache:
                    with self.assertRaisesRegex(ValueError,'disagreement'):w.full_plan(cache,'',{''},[])
                bad=repos[0][1]/'InRelease';bad.write_text(bad.read_text().replace('Origin: BaseTest','Origin: BadActor'))
                rejected=call(['/usr/bin/apt-get','--error-on=any','update'],env,okay=False)
                self.assertNotEqual(rejected.returncode,0,'tampered signed metadata accepted')
                self.assertEqual((work/'state/status').read_text(),status('base','1')+status('webmin','1')+status('old','1')+status('kept','1')+status('rpi-eeprom','1')+status('ntpsec','1'))
            finally:
                call(['/usr/bin/gpgconf','--homedir',str(home),'--kill','gpg-agent'],okay=False)
                if previous is None:os.environ.pop('APT_CONFIG',None)
                else:os.environ['APT_CONFIG']=previous
                apt_pkg.config.clear('')


if __name__=='__main__':unittest.main()
