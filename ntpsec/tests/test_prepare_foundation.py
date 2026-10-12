#!/usr/bin/python3
"""Fresh-node preparation, independent assets, closure and drift regressions."""
import base64
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
definition = importlib.util.spec_from_file_location('prepare', ROOT/'scripts/prepare-foundation.py')
w = importlib.util.module_from_spec(definition)
definition.loader.exec_module(w)


def write_json(path, value):
    path.write_text(json.dumps(value, sort_keys=True)+'\n')
    return w.sha(path.read_bytes())


class Prepare(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.archive_root = tempfile.TemporaryDirectory(prefix='ntp-foundation-packages-')
        cls.cache = Path(cls.archive_root.name)/'cache'
        cls.cache.mkdir()
        cls.effects = {'pps-tools': ['/usr/include/sys/timepps.h'],
                       'bc': ['/usr/bin/bc'],
                       'needrestart': ['/usr/lib/needrestart/apt-pinvoke']}
        cls.assets = []
        for name in ('pps-tools', 'bc', 'needrestart', 'extra-tool'):
            root = Path(cls.archive_root.name)/name
            (root/'DEBIAN').mkdir(parents=True)
            # dpkg requires a traversable control directory even under umask 077.
            # The enclosing TemporaryDirectory remains owner-private.
            (root/'DEBIAN').chmod(0o755)
            version = '3.11' if name == 'needrestart' else '1'
            architecture = 'all' if name == 'needrestart' else 'arm64'
            (root/'DEBIAN/control').write_text('Package: '+name+'\nVersion: '+version+
                '\nArchitecture: '+architecture+'\n'+('Multi-Arch: same\n' if name == 'extra-tool' else '')+
                'Maintainer: Offline Fixture <fixture@example.invalid>\nDescription: offline fixture\n')
            for path in cls.effects.get(name, []):
                target = root/path.lstrip('/')
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(('fixture '+name).encode())
            filename = name+'_'+version+'_'+architecture+'.deb'
            result = subprocess.run(['/usr/bin/dpkg-deb', '--root-owner-group', '--build', str(root),
                                     str(cls.cache/filename)], capture_output=True, check=False)
            if result.returncode:
                raise RuntimeError('fixture package build failed: ' + result.stderr.decode(errors='replace'))
            data = (cls.cache/filename).read_bytes()
            cls.assets.append({'id': 'package-'+name, 'groups': ['foundation'], 'package': name,
                'version': version, 'architecture': architecture, 'size': len(data),
                'sha256': w.sha(data), 'filename': filename, 'url': 'https://publisher.example/'+filename})

    @classmethod
    def tearDownClass(cls):
        cls.archive_root.cleanup()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='ntp-fresh-foundation-')
        self.root = Path(self.temporary.name)
        self.recipe = json.loads((ROOT/'configs/foundation-recipe.json').read_text())
        self.recipe['roots'] = ['pps-tools', 'bc', 'needrestart']
        self.recipe['package_effects'] = copy.deepcopy(self.effects)
        self.manifest = {'schema': 1, 'assets': copy.deepcopy(self.assets), 'public_keys': {}}
        self.recipe_path = self.root/'recipe.json'
        recipe_sha = write_json(self.recipe_path, self.recipe)
        self.manifest_path = self.root/'assets.json'
        manifest_sha = write_json(self.manifest_path, self.manifest)
        paths = set(self.recipe['required_inputs']) | {p for rows in self.effects.values() for p in rows}
        paths |= {'/usr/share/perl5/Debconf/Config.pm', '/usr/share/keyrings/fixture.gpg',
                  '/usr/share/apt-listchanges/ALCApt.py',
                  '/etc/apt/sources.list.d/fixture.sources'}
        present = {'/etc/apt/listchanges.conf', '/var/lib/dpkg/status', '/etc/debconf.conf',
                   '/usr/share/debconf/debconf.conf', '/usr/share/perl5/Debconf/Config.pm',
                   '/usr/share/keyrings/fixture.gpg', '/etc/apt/sources.list.d/fixture.sources'}
        present.add('/usr/share/apt-listchanges/ALCApt.py')
        inputs = [self.file_record(p) if p in present else {'path': p, 'absent': True} for p in sorted(paths)]
        structure = [{'config': 'configdb', 'templates': 'templatedb', 'omitted_fields': []},
            {'driver': 'Stack', 'name': 'configdb', 'stack': 'config, passwords', 'omitted_fields': []},
            {'driver': 'File', 'name': 'config', 'filename': '/var/cache/debconf/config.dat',
             'mode': '644', 'reject_type': 'password', 'omitted_fields': []},
            {'driver': 'File', 'name': 'passwords', 'filename': '/var/cache/debconf/passwords.dat',
             'mode': '600', 'accept_type': 'password', 'backup': 'false', 'required': 'false', 'omitted_fields': []},
            {'driver': 'File', 'name': 'templatedb', 'filename': '/var/cache/debconf/templates.dat',
             'mode': '644', 'omitted_fields': []}]
        key = base64.b64encode(b'fixture SSH public key').decode()
        fingerprint = 'SHA256:'+base64.b64encode(hashlib.sha256(base64.b64decode(key)).digest()).decode().rstrip('=')
        self.known_hosts = self.root/'known_hosts'
        self.known_hosts.write_text('fresh-node.example ssh-ed25519 '+key+'\n')
        self.epoch = int(time.time())
        self.snapshot = {'schema': 1, 'recipe_sha256': recipe_sha, 'collected_epoch': self.epoch,
            'os': self.recipe['os'], 'architecture': 'arm64', 'machine': 'aarch64',
            'caller': self.recipe['caller'], 'hostname': 'fresh-node', 'kernel': '6.18.50+rpt-rpi-v8',
            'boot_id': '12345678-1234-1234-1234-123456789abc', 'dpkg_audit': '', 'active_time_daemons': [],
            'ssh': {'host': 'fresh-node.example', 'fingerprint': fingerprint},
            'baseline': {'base-tool': ['1', 'ii ']}, 'inputs': inputs,
            'directories': {p: ['fixture.sources'] if p == '/etc/apt/sources.list.d' else []
                            for p in self.recipe['required_directories']},
            'coverage': {'debconf_modules': ['/usr/share/perl5/Debconf/Config.pm'],
                         'listchanges_modules': ['/usr/share/apt-listchanges/ALCApt.py'],
                         'keyrings': ['/usr/share/keyrings/fixture.gpg'],
                         'source_files': ['/etc/apt/sources.list.d/fixture.sources']},
            'answers': {'structure': structure, 'expected': {p: {'present': False} for p in
                ('watchdog/run', 'watchdog/restart', 'watchdog/run_keepalive', 'watchdog/module', 'msmtp/apparmor')}},
            'foreign_architectures': [],
            'network': {'boot': '12345678-1234-1234-1234-123456789abc', 'units': 'observed',
                        'addresses': [], 'routes': []},
            'automatic_updates': {n: {} for n in (*w.worker.TIMERS, *w.worker.SERVICES)}}
        self.snapshot_path = self.root/'snapshot.json'
        self.resolution_path = self.root/'resolution.json'
        self.output = self.root/'prepared'
        self.refresh_evidence()
        self.addCleanup(self.temporary.cleanup)

    @staticmethod
    def file_record(path):
        return {'path': path, 'sha256': 'a'*64, 'uid': 0, 'gid': 0, 'mode': '0o644'}

    def refresh_evidence(self):
        self.snapshot_sha = write_json(self.snapshot_path, self.snapshot)
        requirements, _ = w.package_requirements(self.recipe, self.manifest)
        missing = w.delta(requirements, self.snapshot['baseline'])
        changed = {r['package'] for r in missing}
        versions = [dict(r, changed=r['package'] in changed, archive_sha256=r['sha256'],
                         dependencies=[], record='Package: '+r['package']+'\nVersion: '+r['version']+
                         '\nArchitecture: '+r['architecture']+'\n'+('Multi-Arch: same\n' if r['package'] == 'extra-tool' else ''))
                    for r in requirements]
        versions[0]['dependencies'] = [{'type': 'Depends', 'selected_satisfiers': [['extra-tool', '1', 'arm64']]}]
        changes = [[r['package'], r['version'], r['architecture']] for r in missing]
        simulation = '\n'.join('Inst '+r['package']+' ('+r['version']+' Fixture ['+r['architecture']+']) []' for r in missing)
        self.resolution = {'schema': 1, 'snapshot_sha256': self.snapshot_sha,
            'asset_manifest_sha256': w.sha(self.manifest_path.read_bytes()),
            'report': {'identity': {'hostname': 'fresh-node'}, 'state': 'completed',
                'snapshot_sha256': self.snapshot_sha, 'controller_epoch': self.epoch,
                'metadata_accepted': True, 'metadata_unchanged': True, 'installed_state_unchanged': True,
                'boot_unchanged': True, 'approved_inputs_unchanged': True,
                'groups': {'foundation': {'accepted': True, 'plan': {'roots': self.recipe['roots'],
                    'changes': changes, 'versions': versions, 'recommends_enabled': True}}},
                'commands': [{'label': 'simulate_foundation', 'rc': 0, 'error': None, 'output': simulation}]}}
        self.resolution_sha = write_json(self.resolution_path, self.resolution)

    def prepare(self, **kwargs):
        arguments = {'recipe_path': self.recipe_path, 'manifest_path': self.manifest_path,
            'snapshot_path': self.snapshot_path, 'snapshot_sha': self.snapshot_sha,
            'resolution_path': self.resolution_path, 'resolution_sha': self.resolution_sha,
            'cache': self.cache, 'known_hosts': self.known_hosts, 'output': self.output,
            'operation_id': 'fresh-fixture', 'epoch': self.epoch}
        arguments.update(kwargs)
        return w.prepare(**arguments)

    def install_in_snapshot(self, name):
        row = next(r for r in self.assets if r['package'] == name)
        self.snapshot['baseline'][name+':arm64' if name == 'extra-tool' else name] = [row['version'], 'ii ']
        for path in self.effects.get(name, []):
            self.snapshot['inputs'] = [r for r in self.snapshot['inputs'] if r['path'] != path]
            self.snapshot['inputs'].append(self.file_record(path))
        self.refresh_evidence()

    def test_independent_recipe_and_different_inventory_sizes(self):
        for count in (1, 37, 701):
            with self.subTest(count=count):
                self.snapshot['baseline'] = {'base'+str(i): ['1', 'ii '] for i in range(count)}
                self.refresh_evidence()
                output = self.root/('prepared-'+str(count))
                with patch.object(w.fetcher, 'urlopen', side_effect=AssertionError('network forbidden')):
                    result = self.prepare(output=output)
                spec = json.loads((output/'spec.json').read_text())
                self.assertEqual(result['packages'], 4)
                self.assertEqual(len(spec['expected_inventory']), count+4)
                self.assertIn('extra-tool:arm64', spec['expected_inventory'])
                self.assertNotIn('/home/aaron/code/.local-evidence', (output/'provenance.json').read_text())
                self.assertIn(b"APPROVED_HOSTNAME = 'fresh-node'", (output/'worker.py').read_bytes())

    def test_already_installed_prerequisite_is_excluded_and_unchanged(self):
        self.install_in_snapshot('pps-tools')
        self.prepare()
        spec = json.loads((self.output/'spec.json').read_text())
        self.assertEqual(len(spec['packages']), 3)
        self.assertNotIn('pps-tools', [r['package'] for r in spec['packages']])
        self.assertEqual(spec['expected_inventory']['pps-tools'], ['1', 'ii '])
        self.assertNotIn('/usr/include/sys/timepps.h', spec['package_created_inputs'])

    def test_satisfied_inventory_prepares_zero_package_changes(self):
        for row in self.assets:
            self.install_in_snapshot(row['package'])
        self.prepare(cache=self.root/'nonexistent-cache')
        spec = json.loads((self.output/'spec.json').read_text())
        self.assertEqual(spec['packages'], [])
        self.assertEqual(spec['expected_inventory'], self.snapshot['baseline'])

    def test_pinned_version_and_half_installed_conflicts_rejected(self):
        for value in (['0', 'ii '], ['1', 'rc ']):
            self.snapshot['baseline']['pps-tools'] = value
            self.snapshot_sha = write_json(self.snapshot_path, self.snapshot)
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'conflict'):
                self.prepare()
            self.assertFalse(self.output.exists())

    def test_stale_identity_missing_inputs_and_unsafe_stage_rejected_before_writes(self):
        original = copy.deepcopy(self.snapshot)
        for key, value in (('collected_epoch', self.epoch-86401), ('kernel', '6.18-rpi-2712'),
                           ('dpkg_audit', 'unconfigured package'), ('active_time_daemons', ['ntpd'])):
            self.snapshot = dict(copy.deepcopy(original), **{key: value})
            self.refresh_evidence()
            with self.subTest(key=key), self.assertRaises(ValueError): self.prepare()
            self.assertFalse(self.output.exists())
        self.snapshot = original
        self.snapshot['inputs'].pop()
        self.refresh_evidence()
        with self.assertRaises(ValueError): self.prepare()
        self.snapshot = original
        with self.assertRaises(ValueError): self.prepare(operation_id='../escape')

    def test_hash_state_origin_and_native_plan_drift_rejected(self):
        original = copy.deepcopy(self.resolution)
        mutators = [lambda d: d.update(snapshot_sha256='f'*64),
                    lambda d: d['report'].update(boot_unchanged=False),
                    lambda d: d['report'].update(metadata_accepted=False),
                    lambda d: d['report']['groups']['foundation']['plan']['changes'].pop(),
                    lambda d: d['report']['commands'][0].update(output='Inst unexpected (1 Fixture [arm64])'),
                    lambda d: d['report']['groups']['foundation']['plan']['versions'][0].update(
                        record='Package: pps-tools\nVersion: 1\nArchitecture: arm64\nMulti-Arch: same\n'),
                    lambda d: d['report']['groups']['foundation']['plan']['versions'][0].update(archive_sha256='f'*64)]
        for change in mutators:
            self.resolution = copy.deepcopy(original)
            change(self.resolution)
            self.resolution_sha = write_json(self.resolution_path, self.resolution)
            with self.assertRaises(ValueError): self.prepare()
            self.assertFalse(self.output.exists())
        self.snapshot_path.write_bytes(b'{}')
        with self.assertRaisesRegex(ValueError, 'hash mismatch'): self.prepare()

    def test_dependency_closure_conflicts_and_unknown_package_rejected(self):
        plan = self.resolution['report']['groups']['foundation']['plan']
        plan['versions'][0]['dependencies'][0]['selected_satisfiers'] = [['missing', '1', 'arm64']]
        self.resolution_sha = write_json(self.resolution_path, self.resolution)
        with self.assertRaisesRegex(ValueError, 'closure'): self.prepare()
        self.refresh_evidence()
        plan = self.resolution['report']['groups']['foundation']['plan']
        plan['versions'].append({'package': 'gpsd', 'version': '1', 'architecture': 'arm64',
                                'changed': False, 'dependencies': []})
        self.resolution_sha = write_json(self.resolution_path, self.resolution)
        with self.assertRaisesRegex(ValueError, 'source application'): self.prepare()

    def test_cache_integrity_symlink_and_exclusive_output(self):
        cache = self.root/'cache'
        shutil.copytree(self.cache, cache)
        first = cache/self.assets[0]['filename']
        first.write_bytes(b'corrupt')
        with self.assertRaises(ValueError): self.prepare(cache=cache)
        self.assertFalse(self.output.exists())
        first.unlink()
        first.symlink_to(self.cache/self.assets[0]['filename'])
        with self.assertRaisesRegex(ValueError, 'symlink'): self.prepare(cache=cache)
        self.prepare()
        with self.assertRaises(FileExistsError): self.prepare()

    def test_native_inspection_uses_bundled_bytes_despite_later_cache_change(self):
        cache = self.root/'cache'
        shutil.copytree(self.cache, cache)
        original = w.candidate_effects
        def change_cache(archives, paths):
            (cache/self.assets[0]['filename']).write_bytes(b'changed after verification')
            return original(archives, paths)
        with patch.object(w, 'candidate_effects', side_effect=change_cache):
            self.prepare(cache=cache)
        spec = json.loads((self.output/'spec.json').read_text())
        for row in spec['packages']:
            self.assertEqual(w.sha((self.output/row['file']).read_bytes()), row['sha256'])

    def test_new_package_existing_file_collision_and_missing_effect_rejected(self):
        path = '/usr/bin/bc'
        self.snapshot['inputs'] = [self.file_record(path) if r['path'] == path else r for r in self.snapshot['inputs']]
        self.refresh_evidence()
        with self.assertRaisesRegex(ValueError, 'replace'): self.prepare()
        self.recipe['package_effects']['bc'].append('/usr/bin/missing-effect')
        self.snapshot['inputs'].append({'path': '/usr/bin/missing-effect', 'absent': True})
        self.snapshot['recipe_sha256'] = write_json(self.recipe_path, self.recipe)
        self.refresh_evidence()
        with self.assertRaisesRegex(ValueError, 'effects missing'): self.prepare()

    def test_cli_in_isolated_repository_without_historical_evidence(self):
        isolated = self.root/'repository'
        for name in ('scripts/prepare-foundation.py', 'scripts/foundation-install.py',
                     'scripts/fetch-installation-assets.py', 'scripts/read-debconf-answers.py',
                     'scripts/hook-closure-preflight.py', 'scripts/run-foundation-install.py',
                     'templates/apt-listchanges-transaction.conf', 'templates/needrestart-pi4.conf',
                     'tests/test_foundation_install.py', 'tests/fixtures/native-foundation-protocol-v1.txt'):
            target = isolated/'ntpsec'/name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((ROOT/name).read_bytes())
        command = [sys.executable, '-I', '-B', str(isolated/'ntpsec/scripts/prepare-foundation.py'),
            '--recipe', str(self.recipe_path), '--asset-manifest', str(self.manifest_path),
            '--snapshot', str(self.snapshot_path), '--snapshot-sha256', self.snapshot_sha,
            '--resolution', str(self.resolution_path), '--resolution-sha256', self.resolution_sha,
            '--asset-cache', str(self.cache), '--known-hosts', str(self.known_hosts),
            '--operation-id', 'isolated-fixture', '--output', str(self.output)]
        process = subprocess.run(command, cwd=isolated, capture_output=True, text=True, timeout=30)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(json.loads(process.stdout)['packages'], 4)
        self.assertFalse((isolated/'.local-evidence').exists())
        self.assertEqual((self.output/'spec.json').stat().st_mode & 0o777, 0o600)

    def test_bundle_manifest_and_private_launcher_binding(self):
        self.prepare()
        (self.output/'review.md').write_text('Offline fixture review; no execution approved.\n')
        manifest_path = self.output/'manifest.json'
        manifest = json.loads(manifest_path.read_text())
        manifest['review.md'] = w.sha((self.output/'review.md').read_bytes())
        write_json(manifest_path, manifest)
        bundle = self.output/'foundation-install.tar'
        with tarfile.open(bundle, 'w') as archive:
            for name in [*manifest, 'manifest.json']:
                archive.add(self.output/name, arcname=name)
        bundle.chmod(0o600)
        (self.output/'known_hosts').chmod(0o600)
        definition = importlib.util.spec_from_file_location('rendered_launcher', self.output/'launcher.py')
        launcher = importlib.util.module_from_spec(definition)
        definition.loader.exec_module(launcher)
        spec, files = launcher.prepare(bundle, w.sha(bundle.read_bytes()))
        self.assertEqual(spec['hostname'], 'fresh-node')
        self.assertEqual(set(files), set(spec['members']))
        self.assertEqual(launcher.TARGET, 'ama@fresh-node.example')
        for name, digest in manifest.items():
            self.assertEqual(w.sha((self.output/name).read_bytes()), digest)


if __name__ == '__main__':
    unittest.main()
