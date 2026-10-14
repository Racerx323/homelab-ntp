#!/usr/bin/python3
"""Exercise write-ahead grants, strict continuity and interrupted restoration."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import subprocess
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT/'scripts'/name)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


s = load('shm-access.py')
a = load('run-gpsd-acquisition.py')
BEFORE = dict(shmid=17, key=s.KEY, seq=0, size=96, cpid=123, cuid=0, cgid=0,
              uid=0, gid=0, mode=0o600, ctime=100, nattch=0)
INVENTORY = (b'key shmid perms size cpid uid gid cuid cgid nattch\n'
             b'1314148400 17 600 96 123 0 0 0 0 0\n'
             b'1314148402 19 666 96 123 0 0 0 0 0\n')


def transaction(root):
    spec = {'boot_id': 'boot', 'recipe': {'ntp_uid': 999, 'ntp_gid': 985}}
    return types.SimpleNamespace(root=root, s=spec, a=a, rf={'prior-shm-after.txt': INVENTORY},
        h=types.SimpleNamespace(read=lambda path, **kw: path.read_bytes()),
        write=lambda name, value: (root/name).write_text(json.dumps(value)))


def receipt(tx):
    return dict(boot_id='boot', spec_sha256=s.sha((json.dumps(tx.s, sort_keys=True)+'\n').encode()),
                before=copy.deepcopy(BEFORE), phase='prepared', ntp_gid=985, binary_sha256='fixture')


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.tx = transaction(Path(self.temp.name)); self.access = s.Access(self.tx)
        self.value = receipt(self.tx); self.access.save(self.value)
        self.kernel = copy.deepcopy(BEFORE); self.calls = []
        self.native = patch.object(self.access, 'native', side_effect=self.syscall)
        self.native.start(); self.addCleanup(self.native.stop)

    def syscall(self, value, operation='inspect', expected=None):
        # External kernel I/O only; Access validation and persistence are real.
        self.calls.append(operation)
        if operation != 'inspect':
            self.assertEqual(expected, self.kernel)
            self.assertEqual(self.access.read()['phase'], operation+'_pending')
            self.kernel.update(gid=985 if operation == 'grant' else 0,
                               mode=0o660 if operation == 'grant' else 0o600, ctime=self.kernel['ctime']+1)
        return copy.deepcopy(self.kernel)

    def test_grant_handoff_restore_and_idempotent_recovery(self):
        self.access.grant()
        self.kernel['nattch'] = 2
        inventory = self.access.expected_inventory()
        self.assertEqual(inventory['17']['gid'], '985'); self.assertEqual(inventory['17']['perms'], '660')
        self.assertEqual(inventory['19'], a.shm_inventory(INVENTORY)['19'])
        with self.assertRaisesRegex(ValueError, 'consumers'): self.access.restore()
        self.kernel['nattch'] = 0
        self.access.restore(); self.access.restore()
        self.assertEqual(self.calls.count('restore'), 1)
        self.assertEqual(self.access.read()['phase'], 'restored')
        self.assertEqual((self.kernel['gid'], self.kernel['mode']), (0, 0o600))
        with self.assertRaises(ValueError): self.access.grant()

    def test_interrupted_grant_before_and_after_set(self):
        for changed in (False, True):
            with self.subTest(changed=changed):
                self.kernel = copy.deepcopy(BEFORE)
                self.value['phase'] = 'grant_pending'; self.access.save(self.value)
                if changed: self.kernel.update(gid=985, mode=0o660, ctime=101)
                self.access.restore()
                self.assertEqual(self.access.read()['phase'], 'restored')
                self.assertEqual(self.kernel['mode'], 0o600)

    def test_interrupted_restore_before_and_after_set(self):
        self.access.grant(); granted = self.access.read()
        for changed in (False, True):
            self.kernel = copy.deepcopy(granted['after']); granted['phase'] = 'restore_pending'
            self.access.save(granted)
            if changed: self.kernel.update(gid=0, mode=0o600, ctime=102)
            self.access.restore(); self.assertEqual(self.access.read()['phase'], 'restored')

    def test_prepared_restore_never_grants(self):
        self.access.restore(); self.assertEqual(self.calls, ['inspect'])

    def test_drift_and_replacement_never_mutate(self):
        self.access.grant(); good = copy.deepcopy(self.kernel)
        for field in ('shmid', 'key', 'seq', 'size', 'cpid', 'cuid', 'cgid', 'uid', 'gid', 'mode', 'ctime'):
            for operation in ('expected_inventory', 'restore'):
                with self.subTest(field=field, operation=operation):
                    self.kernel = dict(good, **{field: good[field]+1}); count = self.calls.count('restore')
                    with self.assertRaises(ValueError): getattr(self.access, operation)()
                    self.assertEqual(self.calls.count('restore'), count)

    def test_boot_binding_and_disappeared_grant(self):
        self.access.grant(); self.kernel.update(gid=0, mode=0o600)
        with self.assertRaises(ValueError): self.access.restore()
        self.tx.s['boot_id'] = 'new'
        with self.assertRaisesRegex(ValueError, 'binding|mismatch'): self.access.restore()

    def test_pending_receipt_survives_mutation_or_receipt_failure(self):
        original = self.access.save
        def fail_after_set(value):
            if value['phase'] == 'granted': raise OSError('disk full')
            original(value)
        with patch.object(self.access, 'save', side_effect=fail_after_set):
            with self.assertRaises(OSError): self.access.grant()
        self.assertEqual(self.access.read()['phase'], 'grant_pending')
        self.access.restore(); self.assertEqual(self.kernel['mode'], 0o600)

    def test_no_mutation_if_write_ahead_fails(self):
        with patch.object(self.access, 'save', side_effect=OSError('disk full')):
            with self.assertRaises(OSError): self.access.grant()
        self.assertNotIn('grant', self.calls)

    def test_missing_receipt_only_safe_before_apply(self):
        self.access.path.unlink(); self.tx.state = lambda: {'phase': 'staged'}
        self.access.restore(); self.assertEqual(self.calls, [])
        self.tx.state = lambda: {'phase': 'applying'}
        with self.assertRaisesRegex(ValueError, 'missing'): self.access.restore()


class PreparationTests(unittest.TestCase):
    def test_preparation_binds_account_baseline_native_build_and_kernel_identity(self):
        for case in ('valid', 'uid', 'gid', 'owner', 'size', 'missing', 'duplicate', 'source', 'kernel', 'attached', 'compiler'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                tx = transaction(Path(temporary)); access = s.Access(tx)
                tx.f = {'shm-access.c': (ROOT/'scripts/shm-access.c').read_bytes()}
                (tx.root/'shm-access.c').write_bytes(tx.f['shm-access.c'])
                if case == 'source': tx.f['shm-access.c'] = b'changed'
                raw = INVENTORY
                if case == 'owner': raw = raw.replace(b'17 600 96 123 0 0 ', b'17 600 96 123 1 0 ')
                if case == 'size': raw = raw.replace(b'17 600 96 ', b'17 600 80 ')
                if case == 'missing': raw = raw.replace(b'1314148400 ', b'1314148399 ')
                if case == 'duplicate': raw += b'1314148400 21 600 96 123 0 0 0 0 0\n'
                tx.rf['prior-shm-after.txt'] = raw
                tx.h.ancestors = Mock(); tx.h.sync = Mock()
                def compile_native(argv, **kwargs):
                    self.assertEqual(argv[-1], str(access.binary))
                    if case == 'compiler': raise subprocess.CalledProcessError(1, argv)
                    access.binary.write_bytes(b'compiled fixture')
                tx.run = Mock(side_effect=compile_native)
                user = types.SimpleNamespace(pw_uid=998 if case == 'uid' else 999, pw_gid=985)
                group = types.SimpleNamespace(gr_gid=984 if case == 'gid' else 985)
                kernel = dict(BEFORE)
                if case == 'kernel': kernel['cpid'] += 1
                if case == 'attached': kernel['nattch'] = 1
                with patch.object(s.pwd, 'getpwnam', return_value=user), \
                        patch.object(s.grp, 'getgrnam', return_value=group), \
                        patch.object(access, 'native', return_value=kernel):
                    if case == 'valid':
                        access.prepare(); value = access.read()
                        self.assertEqual(value['phase'], 'prepared'); self.assertEqual(value['before'], BEFORE)
                        self.assertEqual(value['source_sha256'], s.sha(tx.f['shm-access.c']))
                        with self.assertRaisesRegex(ValueError, 'collision'): access.prepare()
                    else:
                        with self.assertRaises((ValueError, subprocess.CalledProcessError)): access.prepare()
                        self.assertFalse(access.path.exists())


class NativeCompilationTests(unittest.TestCase):
    def test_compile_native_headers_and_reject_invalid_invocation(self):
        with tempfile.TemporaryDirectory() as temporary:
            binary = Path(temporary)/'native'
            for source in (ROOT/'scripts/shm-access.c', ROOT/'tests/shm_access_fixture.c'):
                subprocess.run(['/usr/bin/cc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                                str(source), '-o', str(binary)], check=True, capture_output=True)
                if source.name == 'shm-access.c':
                    result = subprocess.run([str(binary)], capture_output=True)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(b'arguments', result.stderr)


if __name__ == '__main__': unittest.main()
