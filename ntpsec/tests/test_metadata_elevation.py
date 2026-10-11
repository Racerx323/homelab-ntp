#!/usr/bin/python3
"""Offline sealed-input, one-shot, bootstrap/removal and transport regressions."""
import base64
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, redirect_stdout
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RUNNER = load('metadata-elevation-runner')
BOOT = load('bootstrap-metadata-elevation')
CLIENT = load('run-sealed-package-resolution')
PASTE = load('prepare-elevation-bootstrap')


def sha(data):
    return hashlib.sha256(data).hexdigest()


@contextmanager
def fixture_ownership(module):
    original = os.fstat
    def owned(fd):
        values = list(original(fd)); values[4:6] = [0, 0]
        return os.stat_result(values)
    with patch.object(module, 'ancestors'), patch.object(module.os, 'fstat', side_effect=owned):
        yield


class RunnerTests(unittest.TestCase):
    def read(self, data):
        r, w = os.pipe()
        try:
            os.write(w, data); os.close(w); w = None
            return RUNNER.read_epoch(r, seconds=0.1)
        finally:
            os.close(r)
            if w is not None: os.close(w)

    def test_timestamp_only_with_eof_and_size_bound(self):
        self.assertEqual(self.read(b'1000\n'), 1000)
        for data in (b'', b'-1\n', b'1', b'1\n2', b'1\nexec(code)', b'1' * 21 + b'\n', b'\xff\n'):
            with self.subTest(data=data), self.assertRaises(ValueError): self.read(data)

    def test_open_input_stream_times_out(self):
        r, w = os.pipe()
        try:
            os.write(w, b'1000\n')
            with self.assertRaisesRegex(ValueError, 'deadline'): RUNNER.read_epoch(r, seconds=0.02)
        finally:
            os.close(r); os.close(w)

    def fixture(self, root, code=None):
        root.mkdir(mode=0o700)
        payload = (code or "import os\nassert 'APT_CONFIG' not in os.environ\nassert 'PYTHONPATH' not in os.environ\nprint('{\"state\": \"completed\", \"groups\": {\"fixture\": {\"accepted\": true}}}')\nprint('METADATA_RESOLUTION_EXIT_STATUS=0')\nraise SystemExit(0)\n").encode()
        sealed = (json.dumps({'payload_sha256': sha(payload), 'expires_epoch': 2000,
                              'attempt_dir': str(root)}) + '\n').encode()
        config = {'attempt_dir': str(root), 'hostname': 'fixture', 'expires_epoch': 2000,
                  'payload_sha256': sha(payload), 'manifest_sha256': sha(sealed)}
        receipt = {'state': 'installed_pending_operator_policy_review', 'attempt_dir': str(root),
                   'expires_epoch': 2000, 'claim_present': False,
                   'files': {'payload.py': {'sha256': sha(payload)}, 'runner.py': {'sha256': sha(b'fixture runner')}}}
        for name, data in (('payload.py', payload), ('sealed.json', sealed),
                           ('runner.py', b'fixture runner'),
                           ('bootstrap-receipt.json', json.dumps(receipt).encode())):
            (root / name).write_bytes(data); (root / name).chmod(0o600)
        return config

    @contextmanager
    def runtime(self):
        with fixture_ownership(RUNNER), patch.object(RUNNER.os, 'geteuid', return_value=0), \
                patch.object(RUNNER.socket, 'gethostname', return_value='fixture'), \
                patch.object(RUNNER.time, 'time', return_value=1000), \
                patch.dict(os.environ, {'SUDO_USER': 'ama', 'SUDO_UID': '1000',
                                       'APT_CONFIG': '/untrusted', 'PYTHONPATH': '/untrusted'}, clear=True), \
                patch.object(RUNNER.sys, 'argv', ['fixture']), redirect_stdout(io.StringIO()):
            yield

    def test_environment_cleared_and_duplicate_claim_rejected(self):
        with tempfile.TemporaryDirectory() as d, self.runtime():
            root = Path(d) / 'attempt'; config = self.fixture(root)
            self.assertEqual(RUNNER.execute(config, 1000), 0)
            self.assertEqual(json.loads((root / 'claim.json').read_text())['state'], 'completed')
            with self.assertRaises(FileExistsError): RUNNER.execute(config, 1000)

    def test_concurrent_invocations_claim_once(self):
        with tempfile.TemporaryDirectory() as d, self.runtime():
            config = self.fixture(Path(d) / 'attempt')
            def invoke(_):
                try: return RUNNER.execute(config, 1000)
                except FileExistsError: return 'already_claimed'
            with ThreadPoolExecutor(max_workers=2) as pool:
                self.assertCountEqual(list(pool.map(invoke, range(2))), [0, 'already_claimed'])

    def test_changed_sealed_input_missing_receipt_expiry_and_identity_hold(self):
        for change in ('payload', 'manifest', 'receipt', 'expiry', 'identity', 'clock'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as d, self.runtime():
                root = Path(d) / 'attempt'; config = self.fixture(root)
                epoch = 1000
                if change == 'payload': (root / 'payload.py').write_text('unapproved')
                if change == 'manifest': (root / 'sealed.json').write_text('{}')
                if change == 'receipt': (root / 'bootstrap-receipt.json').unlink()
                if change == 'expiry': config['expires_epoch'] = 1000
                if change == 'identity': os.environ['SUDO_UID'] = '1001'
                if change == 'clock': epoch = 100
                with self.assertRaises((ValueError, FileNotFoundError)): RUNNER.execute(config, epoch)
                self.assertFalse((root / 'claim.json').exists())

    def test_interrupted_collector_keeps_consumed_claim(self):
        with tempfile.TemporaryDirectory() as d, self.runtime():
            root = Path(d) / 'attempt'; config = self.fixture(root, 'raise KeyboardInterrupt()\n')
            with self.assertRaises(KeyboardInterrupt): RUNNER.execute(config, 1000)
            self.assertEqual(json.loads((root / 'claim.json').read_text())['state'], 'interrupted_or_failed')
            with self.assertRaises(FileExistsError): RUNNER.execute(config, 1000)

    def test_file_ownership_mode_symlink_and_parent_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'input'; p.write_bytes(b'data'); p.chmod(0o600)
            with patch.object(RUNNER, 'ancestors'), self.assertRaises(ValueError): RUNNER.protected_bytes(p)
            with fixture_ownership(RUNNER):
                p.chmod(0o644)
                with self.assertRaises(ValueError): RUNNER.protected_bytes(p)
                link = Path(d) / 'link'; link.symlink_to(p)
                with self.assertRaises(OSError): RUNNER.protected_bytes(link)
        bad = type('Info', (), {'st_mode': stat.S_IFDIR | 0o777, 'st_uid': 0, 'st_gid': 0})()
        with patch.object(Path, 'lstat', return_value=bad), self.assertRaises(ValueError):
            RUNNER.ancestors(Path('/fixture'))


class BootstrapTests(unittest.TestCase):
    def fixture(self, directory):
        base = Path(directory); policy_parent = base / 'sudoers.d'; policy_parent.mkdir()
        root = base / 'elevation' / 'attempt'
        data = {'runner.py': b'reviewed runner', 'payload.py': b'reviewed payload',
                'sealed.json': b'{}', 'policy.sudoers': b'fixture exact policy\n'}
        config = {'hostname': 'fixture', 'attempt_dir': str(root),
                  'policy_path': str(policy_parent / 'rule'), 'prepared_epoch': 900, 'expires_epoch': 2000,
                  'files': {n: {'sha256': sha(v), 'mode': 0o440 if n == 'policy.sudoers' else 0o600}
                            for n, v in data.items()}}
        encoded = {n: base64.b64encode(v).decode() for n, v in data.items()}
        return config, encoded

    @contextmanager
    def runtime(self, config, fail_effective=False):
        original = BOOT.read_file
        policy = Path(config['policy_path'])
        def read(path, mode=None, limit=2 * 1024 * 1024):
            if str(path).startswith('/usr/') or str(path) == '/etc/sudoers': return b'fixture trusted tool'
            return original(path, mode, limit)
        def native(argv):
            if argv[0] == '/usr/bin/id': return '1000\n'
            if argv == ['/usr/sbin/visudo', '-c']:
                if policy.exists() and fail_effective: raise subprocess.CalledProcessError(1, argv)
                return str(policy) + ': parsed OK\n' if policy.exists() else 'before parsed OK\n'
            return 'fixture native inspection\n'
        with fixture_ownership(BOOT), patch.object(BOOT, 'identity'), \
                patch.object(BOOT, 'read_file', side_effect=read), \
                patch.object(BOOT, 'native', side_effect=native), \
                patch.object(BOOT.time, 'time', return_value=1000):
            yield

    def test_bootstrap_and_terminal_removal_preserve_claim_and_payload(self):
        with tempfile.TemporaryDirectory() as d:
            config, data = self.fixture(d)
            with self.runtime(config):
                report = BOOT.install(config, data, 1000)
                self.assertEqual(report['state'], 'installed_pending_operator_policy_review')
                root = Path(config['attempt_dir']); claim = root / 'claim.json'
                claim.write_text('{"state":"completed"}\n'); claim.chmod(0o600)
                BOOT.remove(config)
                self.assertFalse(Path(config['policy_path']).exists())
                self.assertTrue(claim.exists()); self.assertTrue((root / 'payload.py').exists())

    def test_unclaimed_rollback_removes_only_bound_inputs_and_policy(self):
        with tempfile.TemporaryDirectory() as d:
            config, data = self.fixture(d)
            with self.runtime(config):
                BOOT.install(config, data, 1000); root = Path(config['attempt_dir'])
                BOOT.remove(config, rollback=True)
                self.assertFalse(Path(config['policy_path']).exists())
                self.assertTrue((root / 'bootstrap-receipt.json').exists())
                self.assertFalse((root / 'runner.py').exists())

    def test_input_drift_existing_policy_and_expiry_reject_before_staging(self):
        for change in ('input', 'existing', 'expiry', 'clock'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as d:
                config, data = self.fixture(d)
                if change == 'input': data['payload.py'] = base64.b64encode(b'changed').decode()
                if change == 'existing': Path(config['policy_path']).write_bytes(b'existing policy')
                if change == 'expiry': config['expires_epoch'] = 1000
                with self.runtime(config), self.assertRaises(ValueError):
                    BOOT.install(config, data, 100 if change == 'clock' else 1000)
                self.assertFalse(Path(config['attempt_dir']).exists())
                if change == 'existing': self.assertEqual(Path(config['policy_path']).read_bytes(), b'existing policy')

    def test_effective_policy_failure_removes_own_fragment_and_retains_failure(self):
        with tempfile.TemporaryDirectory() as d:
            config, data = self.fixture(d)
            with self.runtime(config, fail_effective=True), self.assertRaises(subprocess.CalledProcessError):
                BOOT.install(config, data, 1000)
            self.assertFalse(Path(config['policy_path']).exists())
            self.assertTrue((Path(config['attempt_dir']) / 'bootstrap-failure.json').exists())

    def test_policy_drift_and_running_claim_block_cleanup(self):
        for change in ('policy', 'claim'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as d:
                config, data = self.fixture(d)
                with self.runtime(config):
                    BOOT.install(config, data, 1000); root = Path(config['attempt_dir'])
                    if change == 'policy':
                        policy = Path(config['policy_path']); policy.chmod(0o600)
                        policy.write_bytes(b'other policy'); policy.chmod(0o440)
                    else:
                        claim = root / 'claim.json'
                        claim.write_text('{"state":"registered_before_collector"}'); claim.chmod(0o600)
                    with self.assertRaises(ValueError): BOOT.remove(config, rollback=change == 'policy')
                    self.assertTrue(Path(config['policy_path']).exists())
                    self.assertFalse((root / 'removal-started.json').exists())


class LauncherTests(unittest.TestCase):
    def bundle(self, root, sealed=True):
        payload = b'reviewed metadata payload'
        key = b'fixture key'
        hosts = ('10.1.0.137 ssh-ed25519 ' + base64.b64encode(key).decode() + '\n').encode()
        fingerprint = 'SHA256:' + base64.b64encode(hashlib.sha256(key).digest()).decode().rstrip('=')
        argv = ['timeout', '--signal=TERM', '--kill-after=5s', '840s', 'ssh', '-T']
        for option in ('BatchMode=yes', 'StrictHostKeyChecking=yes', 'HostKeyAlgorithms=ssh-ed25519',
                       'UpdateHostKeys=no', 'ProxyCommand=none', 'ProxyJump=none', 'ControlMaster=no',
                       'ControlPath=none', 'ControlPersist=no', 'PermitLocalCommand=no',
                       'ClearAllForwardings=yes', 'ForwardAgent=no', 'ForwardX11=no',
                       'GlobalKnownHostsFile=/dev/null', 'UserKnownHostsFile=' + str(root / 'metadata-resolution-known-hosts')):
            argv += ['-o', option]
        argv += ['ama@10.1.0.137', 'cd / && sudo -n /usr/bin/python3 -I -B /var/lib/ntp-metadata-elevation/attempt-v6/runner.py']
        members = {'payload.py': payload, 'spec.json': b'{"groups":{"source_build":["scons"]}}',
                   'sealed.json': json.dumps({'attempt_dir': '/var/lib/ntp-metadata-elevation/attempt-v6',
                       'expires_epoch': 2000, 'payload_sha256': sha(payload)}).encode(),
                   'operator-paste.txt': b'@CONTROLLER_EPOCH@\n', 'known_hosts': hosts,
                   'run-sealed-package-resolution.py': Path(CLIENT.__file__).read_bytes()} if sealed else {
                       'prepare-elevation-bootstrap.py': Path(PASTE.__file__).read_bytes(),
                       **{'operator-' + m + '.txt': ('fixture ' + m + ' @CONTROLLER_EPOCH@\n').encode()
                          for m in ('install', 'remove', 'rollback')}}
        manifest = {'mode': 'sealed_source_prerequisites_metadata_resolution', 'expires_epoch': 2000,
                    'transport_argv': argv, 'members': {n: sha(v) for n, v in members.items()}}
        members['manifest.json'] = json.dumps(manifest).encode()
        bundle = root / 'fixture.tar'
        with tarfile.open(bundle, 'w') as archive:
            for name, data in members.items():
                info = tarfile.TarInfo(name); info.size = len(data); archive.addfile(info, io.BytesIO(data))
        (root / 'metadata-resolution-epoch-template.txt').write_bytes(b'@CONTROLLER_EPOCH@\n')
        (root / 'metadata-resolution-known-hosts').write_bytes(hosts)
        return bundle, sha(bundle.read_bytes()), fingerprint

    def test_real_prepare_checks_all_members_hashes_key_and_external_template(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); bundle, digest, fingerprint = self.bundle(root)
            CLIENT.prepare(bundle, digest, fingerprint)
            with self.assertRaises(ValueError): CLIENT.prepare(bundle, '0' * 64, fingerprint)
            with self.assertRaises(ValueError): CLIENT.prepare(bundle, digest, 'SHA256:wrong')
            (root / 'metadata-resolution-epoch-template.txt').write_bytes(b'code instead of clock\n')
            with self.assertRaises(ValueError): CLIENT.prepare(bundle, digest, fingerprint)

    def test_operator_paste_verifies_bundle_and_binds_only_timestamp(self):
        with tempfile.TemporaryDirectory() as d:
            bundle, digest, _ = self.bundle(Path(d), sealed=False)
            self.assertEqual(PASTE.prepare(bundle, digest, 'install', 1000), b'fixture install 1000\n')
            with self.assertRaises(ValueError): PASTE.prepare(bundle, '0' * 64, 'install', 1000)
            with self.assertRaises(ValueError): PASTE.prepare(bundle, digest, 'install', 2000)
            self.assertEqual(PASTE.prepare(bundle, digest, 'remove', 2000), b'fixture remove 2000\n')

    def manifest(self):
        return {'expires_epoch': 2000, 'transport_argv': ['fixture transport']}

    def test_runtime_stdin_is_only_epoch_and_registration_prevents_replay(self):
        with tempfile.TemporaryDirectory() as d:
            bundle = Path(d) / 'fixture.tar'
            def submit(argv, **kwargs):
                self.assertEqual(kwargs['input'], b'1000\n')
                self.assertTrue((bundle.parent / 'metadata-resolution-execution.json').exists())
                kwargs['stdout'].write(b'{"state":"preflight_rejected"}\nMETADATA_RESOLUTION_EXIT_STATUS=2\n')
                return subprocess.CompletedProcess(argv, 2)
            with patch.object(CLIENT, 'prepare', return_value=self.manifest()), \
                    patch.object(sys, 'argv', ['client', '--bundle', str(bundle), '--sha256', 'a' * 64]), \
                    patch.object(CLIENT.time, 'time', return_value=1000), \
                    patch.object(CLIENT.subprocess, 'run', side_effect=submit) as transport, \
                    redirect_stdout(io.StringIO()):
                self.assertEqual(CLIENT.main(), 0)
                with self.assertRaises(FileExistsError): CLIENT.main()
                transport.assert_called_once()
            self.assertEqual(json.loads((Path(d) / 'metadata-resolution-result.json').read_text())['state'],
                             'completed_with_gaps')

    def test_expiry_prevents_registration_and_transport(self):
        with tempfile.TemporaryDirectory() as d:
            bundle = Path(d) / 'fixture.tar'
            with patch.object(CLIENT, 'prepare', return_value=self.manifest()), \
                    patch.object(sys, 'argv', ['client', '--bundle', str(bundle), '--sha256', 'a' * 64]), \
                    patch.object(CLIENT.time, 'time', return_value=2000), \
                    patch.object(CLIENT.subprocess, 'run') as transport:
                with self.assertRaises(ValueError): CLIENT.main()
                transport.assert_not_called()
                self.assertFalse((Path(d) / 'metadata-resolution-execution.json').exists())


if __name__ == '__main__':
    unittest.main()
