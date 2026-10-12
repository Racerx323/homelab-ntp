#!/usr/bin/python3
"""Offline native copy, recovery, payload and sealed transport regression checks."""
import base64
import copy
import importlib.util
import json
import os
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    definition = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(definition); definition.loader.exec_module(module)
    return module


s = load('native_stage', ROOT / 'scripts/source-install-stage.py')
c = load('native_controller', ROOT / 'scripts/run-source-install.py')
i = load('native_inspector', ROOT / 'scripts/inspect-source-destinations.py')
f = load('native_helpers', ROOT / 'scripts/foundation-install.py')
clock = load('native_clock', ROOT / 'scripts/clockmaker.py')
fixtures = load('destination_fixtures', ROOT / 'tests/test_source_destinations.py')


class NativeInstall(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'protected'; self.root.mkdir(mode=0o700)
        self.target = Path(self.temp.name) / 'target'; self.target.mkdir()
        self.release = {'schema': 1, 'hostname': 'fixture', 'operation': 'build', 'files': {
            'usr/local/bin/tool': {'type': 'file', 'mode': 0o755, 'sha256': s.sha(b'fixture native')},
            'usr/local/bin/tool-link': {'type': 'symlink', 'target': 'tool'}}}
        self.spec = {'source_stage': '/home/ama/.ntp-source-build-fixture/candidate/stage', 'members': {}}
        self.helper = SimpleNamespace(read=lambda p, **kw: p.read_bytes(), ancestors=Mock(), sync=Mock())
        def create(path, data):
            with path.open('xb') as stream: stream.write(data)
            path.chmod(0o600)
        self.helper.create = create
        self.observation = {'inventory': {'fixture': ['1','ii ']}, 'boot_id': 'fixture',
                            'python': {}, 'services': '', 'active_daemons': []}
        self.source = lambda p, kind: b'fixture native' if kind == 'file' else 'tool'
        self.original_lstat = Path.lstat
        def root_metadata(path, *args, **kwargs):
            info = self.original_lstat(path, *args, **kwargs)
            fields = list(info); fields[4] = fields[5] = 0
            if stat.S_ISDIR(info.st_mode): fields[0] &= ~0o022
            return os.stat_result(fields)
        self.patches = [patch.object(Path, 'lstat', root_metadata), patch.object(clock.os, 'geteuid', return_value=0),
            patch.object(clock.os, 'fchown'), patch.object(clock.os, 'lchown'),
            patch.object(clock, 'target_identity'), patch.object(clock, 'require_no_package_applications'),
            patch.object(clock, 'require_stopped_daemons'), patch.object(i, 'observation', return_value=self.observation),
            patch.object(clock, 'safe_destination', side_effect=lambda n: self.target / n),
            patch.object(s, 'source_bytes', side_effect=self.source)]
        for p in self.patches: p.start(); self.addCleanup(p.stop)
        raw = s.encoded(self.release); self.spec['members']['release.json'] = s.sha(raw)
        (self.root / 'release.json').write_bytes(raw)
        self.state = clock.inspect_install(self.root / 'release.json', s.sha(raw))
        state_raw = s.encoded(self.state); self.spec['members']['installation-state.json'] = s.sha(state_raw)
        (self.root / 'installation-state.json').write_bytes(state_raw)
        self.parents = i.parents([clock.safe_destination(n) for n in self.release['files']])
        (self.root / 'inspection.json').write_bytes(s.encoded({'parents': self.parents, 'observation': self.observation}))
        (self.root / 'build-spec.json').write_bytes(b'{}')

    def install(self):
        return s.install(self.root, self.spec, self.helper, clock, i, self.release)

    def test_native_install_exact_bytes_modes_links_and_retained_journal(self):
        result = self.install()
        self.assertEqual(result['state'], 'installation_completed')
        self.assertEqual((self.target / 'usr/local/bin/tool').read_bytes(), b'fixture native')
        self.assertEqual(stat.S_IMODE((self.target / 'usr/local/bin/tool').stat().st_mode), 0o755)
        self.assertEqual(os.readlink(self.target / 'usr/local/bin/tool-link'), 'tool')
        self.assertEqual(stat.S_IMODE((self.target / 'usr/local/bin').stat().st_mode), 0o755)
        self.assertTrue((self.root / 'journal/before').is_dir())
        self.assertEqual(list((self.root / 'journal/before').iterdir()), [])
        self.assertEqual(stat.S_IMODE((self.root / 'journal/receipt.json').stat().st_mode), 0o600)
        self.assertFalse(result['services_activated'])
        self.assertFalse(result['library_cache_changed'])

    def test_bad_payload_or_changed_prestate_precedes_application_effects(self):
        s.source_bytes.side_effect = lambda p, kind: b'wrong' if kind == 'file' else 'tool'
        with self.assertRaisesRegex(ValueError, 'payload hash'):
            self.install()
        self.assertFalse((self.target / 'usr').exists())
        self.assertFalse((self.root / 'journal').exists())

    def test_prestate_and_observation_drift_hold_without_copying(self):
        with patch.object(i, 'observation', return_value=dict(self.observation, boot_id='changed')):
            with self.assertRaisesRegex(ValueError, 'observation'):
                self.install()
        self.assertFalse((self.root / 'stage').exists())
        self.target.joinpath('usr/local/bin').mkdir(parents=True)
        self.target.joinpath('usr/local/bin/tool').write_bytes(b'unrelated')
        with self.assertRaisesRegex(ValueError, 'parent drift|pre-state drift'):
            self.install()
        self.assertEqual((self.target / 'usr/local/bin/tool').read_bytes(), b'unrelated')

    def test_partial_native_failure_recovery_restores_absence_and_new_directories(self):
        original = clock.os.replace
        def fail_second(source, destination):
            if str(destination).endswith('tool-link'):
                raise OSError('injected native rename failure')
            return original(source, destination)
        with patch.object(clock.os, 'replace', side_effect=fail_second):
            with self.assertRaisesRegex(OSError, 'injected'):
                self.install()
        self.assertTrue((self.target / 'usr/local/bin/tool').exists())
        result = s.recover(self.root, self.spec, self.helper, clock, i, self.release, {'state': 'installation_held'})
        self.assertEqual(result['state'], 'installation_restored')
        self.assertEqual(clock.inspect_install(self.root / 'release.json', self.spec['members']['release.json']), self.state)
        self.assertFalse((self.target / 'usr').exists())
        self.assertTrue((self.root / 'journal/receipt.json').exists())
        with self.assertRaises(FileExistsError):
            s.recover(self.root, self.spec, self.helper, clock, i, self.release, {'state': 'installation_held'})

    def test_recovery_unknown_file_or_directory_retains_everything(self):
        self.install()
        path = self.target / 'usr/local/bin/tool'; path.write_bytes(b'drift')
        with self.assertRaisesRegex(ValueError, 'artifact drift'):
            s.recover(self.root, self.spec, self.helper, clock, i, self.release, {'state': 'installation_held'})
        self.assertEqual(path.read_bytes(), b'drift')
        self.assertFalse((self.root / 'recovery-claim.json').exists())
        path.write_bytes(b'fixture native')
        (self.target / 'usr/local/bin').chmod(0o700)
        with self.assertRaisesRegex(ValueError, 'directory identity'):
            s.recover(self.root, self.spec, self.helper, clock, i, self.release, {'state': 'installation_held'})
        self.assertTrue(path.exists())

    def test_recovery_unknown_directory_contents_hold_before_removing_installed_files(self):
        self.install()
        extra=self.target/'usr/local/bin/unrelated';extra.write_bytes(b'preserve')
        with self.assertRaisesRegex(ValueError,'unexpected created-directory contents'):
            s.recover(self.root,self.spec,self.helper,clock,i,self.release,{'state':'installation_held'})
        self.assertTrue((self.target/'usr/local/bin/tool').exists())
        self.assertEqual(extra.read_bytes(),b'preserve')
        self.assertFalse((self.root/'recovery-claim.json').exists())

    def test_worker_one_install_terminal_readback_and_payload_only_cleanup(self):
        files = {name:b'pass\n' for name in c.INPUTS}
        for name in ('release.json','installation-state.json','inspection.json','build-spec.json'):
            files[name]=(self.root/name).read_bytes()
        gate=SimpleNamespace(identity=Mock())
        for outcome in ('completed','held'):
            root=self.root/outcome
            spec=dict(self.spec,operation='source-installation',stage=str(root),
                members={name:s.sha(data) for name,data in files.items()})
            with patch.object(s.types,'ModuleType',side_effect=lambda name:gate if name=='sealed_install_identity' else self.helper), \
                    patch('builtins.exec'),patch.object(s.signal,'signal'), \
                    patch.object(s,'load',side_effect=lambda path:i if path.name=='inspect-source-destinations.py' else clock), \
                    patch.object(clock,'regular_bytes',clock.regular_bytes),patch.object(clock,'snapshot',clock.snapshot):
                if outcome=='held':
                    with patch.object(s,'install',side_effect=ValueError('injected early hold')):
                        result=s.entry(spec,files,1,'collect')
                else:
                    result=s.entry(spec,files,1,'collect')
                self.assertEqual(result['state'],'installation_'+outcome)
                with self.assertRaises(FileExistsError):s.entry(spec,files,1,'collect')
                readback=s.entry(spec,files,1,'readback')
                self.assertEqual(readback['state'],result['state'])
                with self.assertRaisesRegex(ValueError,'retained terminal'):
                    s.entry(spec,files,1,'cleanup','0'*64)
                if outcome=='completed':
                    self.assertIn('journal/receipt.json',readback['evidence'])
                    cleanup=s.entry(spec,files,1,'cleanup',readback['terminal_sha256'])
                    self.assertEqual(cleanup['state'],'installation_payload_removed')
                    self.assertTrue((root/'journal/receipt.json').exists())
                    self.assertTrue((root/'clockmaker.py').exists())
                    self.assertFalse((root/'stage').exists())
                else:
                    with self.assertRaisesRegex(ValueError,'held installation'):
                        s.entry(spec,files,1,'cleanup',readback['terminal_sha256'])
                    self.assertTrue((root/'terminal.json').exists())

    def test_payload_membership_and_link_drift_hold_cleanup(self):
        self.install()
        extra = self.root / 'stage/extra'; extra.mkdir()
        with self.assertRaisesRegex(ValueError, 'membership'):
            s.verify_payload(self.root, self.release, self.helper)
        extra.rmdir()
        link = self.root / 'stage/usr/local/bin/tool-link'; link.unlink(); link.symlink_to('/etc/passwd')
        with self.assertRaisesRegex(ValueError, 'link drift'):
            s.verify_payload(self.root, self.release, self.helper)
        self.assertTrue((self.root / 'journal').exists())


class Transport(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.Destinations(); self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        build = dict(self.fixture.build, stage_name='.ntp-source-build-fixture')
        self.fixture.build = build
        self.fixture.args.build_spec.write_bytes(c.c.encoded(build))
        self.fixture.args.build_spec_sha256 = c.c.sha(self.fixture.args.build_spec.read_bytes())
        receipt = json.loads(self.fixture.args.build_acceptance.read_bytes())
        receipt['spec_sha256'] = self.fixture.args.build_spec_sha256
        self.fixture.args.build_acceptance.write_bytes(c.c.encoded(receipt))
        self.fixture.args.build_acceptance_sha256 = c.c.sha(self.fixture.args.build_acceptance.read_bytes())
        _, spec, files = self.fixture.seal()
        root = self.fixture.root / 'inputs'; root.mkdir(mode=0o700)
        report = self.fixture.report(spec)
        state = c.c.encoded(report['installation_state']); raw = c.c.encoded(report)
        additions = {'inspection.json': raw, 'inspection-spec.json': files['spec.json'],
            'installation-state.json': state, 'inspection-acceptance.json': c.c.encoded({
                'state':'source_destinations_accepted','inspection_sha256':c.c.sha(raw),
                'installation_state_sha256':c.c.sha(state), 'release_sha256':c.c.sha(files['release.json']),
                'collision_count':0,'destination_count':len(report['installation_state']['files']),
                'live_installed':False,'services_activated':False})}
        hashes = {}
        for name in c.INPUTS - {'foundation-install.py','preflight-stage.py','stage.py','clockmaker.py','inspect-source-destinations.py'}:
            data = additions.get(name,files.get(name)); (root/name).write_bytes(data); (root/name).chmod(0o600)
            hashes[name] = c.c.sha(data)
        self.args = SimpleNamespace(inputs=root, input_hashes=hashes, known_hosts=self.fixture.known,
            operation_id='fixture-native-install',output=self.fixture.root/'installation')

    def test_offline_seal_exact_inputs_and_payload_modes(self):
        with patch.object(c.subprocess, 'run') as run:
            result = c.seal(self.args); run.assert_not_called()
        spec, files = c.prepare(Path(result['bundle']),result['sha256'])
        self.assertFalse(result['target_contact']); self.assertFalse(result['execution_authorized'])
        self.assertEqual(spec['operation'],'source-installation')
        self.assertEqual(spec['source_stage'],'/home/ama/.ntp-source-build-fixture/candidate/stage')
        for mode in ('collect','readback','rollback','cleanup'):
            compile(c.c.payload(spec,files,spec['prepared_epoch'],mode),'fixture','exec')
        self.assertIn('installation_held', c.c.payload(spec,files,spec['prepared_epoch'],'collect').decode())
        self.assertEqual(set(files),c.INPUTS|c.EXTRAS)
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            c.prepare(Path(result['bundle']),'0'*64)

    def test_hash_mismatch_never_seals_or_contacts_target(self):
        self.args.input_hashes['inspection.json']='0'*64
        with patch.object(c.subprocess, 'run') as run:
            with self.assertRaisesRegex(ValueError,'input hash'):
                c.seal(self.args)
            run.assert_not_called()
        self.assertFalse(self.args.output.exists())

    def completed_report(self, spec, files):
        release = json.loads(files['release.json'])
        state = json.loads(files['installation-state.json'])
        observation = json.loads(files['inspection.json'])
        receipt = {'state':'copied_not_activated','release_sha256':c.c.sha(files['release.json']),
            'before':state,'installed':list(release['files']),'removed':[],
            'after':{'hostname':spec['hostname'],'files':{n:dict(r,uid=0,gid=0,mode=r.get('mode',0o777))
                for n,r in release['files'].items()}}}
        evidence = {'journal/receipt.json':receipt,'created-directories.json':{},
            'before.json':{'state':state,'observation':observation['observation'],'parents':observation['parents']}}
        report = {'state':'installation_completed','spec_sha256':c.c.sha(files['spec.json']),
            'native_state':'copied_not_activated','installed_files':len(release['files']),
            'continuity_unchanged':True,'services_activated':False,'library_cache_changed':False,
            'terminal_sha256':'a'*64,'evidence':{}}
        for name,value in evidence.items():
            raw=c.c.encoded(value)
            report['evidence'][name]={'sha256':c.c.sha(raw),'base64':base64.b64encode(raw).decode()}
        return report

    def test_complete_acceptance_rejects_forged_hash_metadata_or_coverage(self):
        result=c.seal(self.args);spec,files=c.prepare(Path(result['bundle']),result['sha256'])
        report=self.completed_report(spec,files)
        c.validate_acceptance(report,files,spec)
        for mutate in (lambda r:r.update(services_activated=True),
                       lambda r:r.update(continuity_unchanged=False),
                       lambda r:r.update(installed_files=0),
                       lambda r:r['evidence']['journal/receipt.json'].update(sha256='0'*64)):
            changed=copy.deepcopy(report);mutate(changed)
            with self.assertRaises(ValueError):c.validate_acceptance(changed,files,spec)
        record=json.loads(base64.b64decode(report['evidence']['journal/receipt.json']['base64']))
        name=next(iter(record['after']['files']));record['after']['files'][name]['uid']=1000
        raw=c.c.encoded(record)
        report['evidence']['journal/receipt.json']={'sha256':c.c.sha(raw),'base64':base64.b64encode(raw).decode()}
        with self.assertRaisesRegex(ValueError,'manifest mismatch'):c.validate_acceptance(report,files,spec)

    def test_terminal_acceptance_cleanup_and_success_rollback_hold(self):
        result=c.seal(self.args);spec,files=c.prepare(Path(result['bundle']),result['sha256'])
        report=self.completed_report(spec,files)
        args=SimpleNamespace(bundle=Path(result['bundle']),sha256=result['sha256'],mode='readback')
        def submitted(argv,**kw):
            value=report if args.mode=='readback' else {'state':'installation_payload_removed','journal_retained':True}
            kw['stdout'].write(c.c.encoded(value)+b'PREFLIGHT_EXIT_STATUS=0\n')
            return SimpleNamespace(returncode=0)
        with patch.dict(c.os.environ,{'SSH_AUTH_SOCK':'/fixture/agent'}), patch.object(c.subprocess,'run',side_effect=submitted) as run:
            c.execute(args)
            acceptance=json.loads((self.args.output/'acceptance.json').read_bytes())
            self.assertEqual(acceptance['state'],'native_installation_accepted')
            args.mode='rollback'
            with self.assertRaisesRegex(ValueError,'bound terminal'):c.execute(args)
            self.assertEqual(run.call_count,1)
            args.mode='cleanup';c.execute(args)
            self.assertEqual(run.call_count,2)
            with self.assertRaises(FileExistsError):c.execute(args)
            self.assertEqual(run.call_count,2)
        self.assertFalse((self.args.output/'collect-execution.json').exists())

    def test_expired_installation_never_registers_or_contacts_target(self):
        result=c.seal(self.args);spec,files=c.prepare(Path(result['bundle']),result['sha256'])
        args=SimpleNamespace(bundle=Path(result['bundle']),sha256=result['sha256'],mode='collect')
        with patch.object(c.time,'time',return_value=spec['expires_epoch']),patch.object(c.subprocess,'run') as run:
            with self.assertRaisesRegex(ValueError,'window expired'):c.execute(args)
            run.assert_not_called()
        self.assertFalse((self.args.output/'collect-execution.json').exists())

    def test_controller_registers_once_and_preserves_held_result(self):
        result=c.seal(self.args)
        args=SimpleNamespace(bundle=Path(result['bundle']),sha256=result['sha256'],mode='collect')
        def submitted(argv,**kw):
            self.assertTrue((self.args.output/'collect-execution.json').exists())
            kw['stdout'].write(b'{"state":"installation_held","error":"drift"}\nPREFLIGHT_EXIT_STATUS=2\n')
            return SimpleNamespace(returncode=2)
        with patch.dict(c.os.environ,{'SSH_AUTH_SOCK':'/fixture/agent'}), patch.object(c.subprocess,'run',side_effect=submitted) as run:
            self.assertEqual(c.execute(args)['worker_status'],2)
            with self.assertRaises(FileExistsError):c.execute(args)
            run.assert_called_once()
        self.assertFalse((self.args.output/'acceptance.json').exists())
        args.mode='cleanup'
        with patch.object(c.subprocess,'run') as run:
            with self.assertRaises(FileNotFoundError):c.execute(args)
            run.assert_not_called()


class SourceReaders(unittest.TestCase):
    def test_source_identity_ignores_atime_but_detects_content_metadata_drift(self):
        fields = dict.fromkeys(('st_mode','st_uid','st_gid','st_dev','st_ino','st_nlink',
                              'st_size','st_mtime_ns','st_ctime_ns'),1)
        before=SimpleNamespace(**fields,st_atime_ns=1)
        changed=SimpleNamespace(**fields,st_atime_ns=2)
        self.assertEqual(s.source_identity(before),s.source_identity(changed))
        changed.st_mtime_ns=2
        self.assertNotEqual(s.source_identity(before),s.source_identity(changed))

    def test_source_symlink_ancestor_and_final_type_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory); (base/'file').write_bytes(b'data'); (base/'link').symlink_to(base)
            real_fstat, real_stat = os.fstat, os.stat
            source_owner = 1000
            def target_metadata(info):
                # Preserve nanosecond fields while simulating target ownership.
                fields = {name: getattr(info, name) for name in dir(info) if name.startswith('st_')}
                if stat.S_ISDIR(info.st_mode):
                    fields.update(st_mode=info.st_mode & ~0o022, st_uid=0, st_gid=0)
                else:
                    fields.update(st_uid=source_owner, st_gid=source_owner)
                return SimpleNamespace(**fields)
            with patch.object(s.os, 'fstat', side_effect=lambda fd: target_metadata(real_fstat(fd))), \
                 patch.object(s.os, 'stat', side_effect=lambda *a, **kw: target_metadata(real_stat(*a, **kw))):
                self.assertEqual(s.source_bytes(base/'file','file'), b'data')
                source_owner = 1001
                with self.assertRaisesRegex(ValueError, 'unsafe source ownership'):
                    s.source_bytes(base/'file','file')
                source_owner = 1000
                with self.assertRaisesRegex(ValueError, 'source type/size'):
                    s.source_bytes(base/'file','file',limit=1)
                os.link(base/'file',base/'hardlink')
                with self.assertRaisesRegex(ValueError,'unsafe source'):
                    s.source_bytes(base/'file','file')
            with self.assertRaises((ValueError,OSError)):
                s.source_bytes(base/'link/file','file')
            with self.assertRaises((ValueError,OSError)):
                s.source_bytes(base/'link','file')
            with self.assertRaisesRegex(ValueError,'source type/size|unsafe source'):
                s.source_bytes(base/'file','file',limit=1)


if __name__ == '__main__':
    unittest.main()
