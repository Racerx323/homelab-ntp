#!/usr/bin/python3
"""Offline Stack routing, redaction and fixed answer-read tests."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


reader = load('answer_reader', 'read-debconf-answers.py')
helper = load('answer_helper', 'hook-closure-preflight.py')
CONFIG = '''Config: configdb
Templates: templatedb

Name: config
Driver: File
Filename: /var/cache/debconf/config.dat
Mode: 644
Reject-Type: password

Name: passwords
Driver: File
Filename: /var/cache/debconf/passwords.dat
Mode: 600
Accept-Type: password
Backup: false
Required: false

Name: configdb
Driver: Stack
Stack: config, passwords

Name: templatedb
Driver: File
Filename: /var/cache/debconf/templates.dat
Mode: 644
'''


class Answers(unittest.TestCase):
    def test_exact_routing(self):
        structure = helper.debconf_structure(CONFIG)
        self.assertEqual(reader.normal_database(structure), '/var/cache/debconf/config.dat')
        for before, after in (('Stack: config, passwords', 'Stack: passwords, config'),
                              ('Reject-Type: password', 'Reject-Type: string'),
                              ('/var/cache/debconf/config.dat', '/var/cache/debconf/passwords.dat'),
                              ('Driver: File', 'Driver: LDAP')):
            with self.subTest(before=before), self.assertRaises(ValueError):
                reader.normal_database(helper.debconf_structure(CONFIG.replace(before, after, 1)))

    def run_fixture(self, db=b'Name: other/password\nValue: PRIVATE_VALUE\n\nName: watchdog/run\nValue: false\n', repeat=None, structure=None):
        reads = []
        databases = []
        def read(path, limit):
            reads.append(str(path))
            if str(path) == '/var/cache/debconf/passwords.dat':
                self.fail('password database must not be read')
            if str(path) == '/var/cache/debconf/config.dat':
                databases.append(True)
                return (repeat if repeat is not None and len(databases) == 2 else db), {'uid': 0, 'gid': 0, 'mode': '0o644'}
            if str(path) == '/usr/lib/os-release':
                return b'ID=debian\nVERSION_ID="13"\nVERSION_CODENAME=trixie\n', {}
            self.assertEqual(str(path), '/etc/debconf.conf')
            return CONFIG.encode(), {}
        spec = {'hostname': 'j2-svntp1', 'kernel': 'fixture', 'not_before': 0,
                'expires_epoch': 9999999999, 'structure': structure or helper.debconf_structure(CONFIG)}
        with patch.object(reader.os, 'geteuid', return_value=0), patch.object(reader.os, 'uname', return_value=SimpleNamespace(machine='aarch64', release='fixture')), patch.object(reader.socket, 'gethostname', return_value='j2-svntp1'), patch.object(reader.pwd, 'getpwnam', return_value=SimpleNamespace(pw_uid=1000)), patch.object(reader.pwd, 'getpwuid', return_value=SimpleNamespace(pw_dir='/root')), patch.dict(reader.os.environ, {'SUDO_USER': 'ama', 'SUDO_UID': '1000'}, clear=True), patch.object(Path, 'exists', return_value=False), patch.object(Path, 'is_symlink', return_value=False), patch.object(Path, 'read_text', return_value='fixture-boot'), patch.object(helper, 'read_protected', side_effect=read):
            result = reader.collect_answers(spec, helper)
        return result, reads

    def test_bounded_answers_and_absences(self):
        result, reads = self.run_fixture()
        self.assertEqual(set(result['answers']), helper.ANSWERS)
        self.assertEqual(result['answers']['watchdog/run']['value'], 'false')
        self.assertFalse(result['answers']['watchdog/restart']['present'])
        self.assertNotIn('PRIVATE_VALUE', json.dumps(result))
        self.assertNotIn('sha256', json.dumps(result))
        self.assertNotIn('/var/cache/debconf/passwords.dat', reads)
        self.assertEqual(reads.count('/var/cache/debconf/config.dat'), 2)

    def test_no_answers_is_evidence(self):
        result, _ = self.run_fixture(db=b'Name: unrelated\nValue: PRIVATE_VALUE\n')
        self.assertTrue(all(not answer['present'] for answer in result['answers'].values()))

    def test_answer_drift_rejected(self):
        with self.assertRaises(ValueError):
            self.run_fixture(repeat=b'Name: watchdog/run\nValue: true\n')

    def test_duplicate_and_unsafe_values_rejected(self):
        for db in (b'Name: watchdog/run\nValue: false\n\nName: watchdog/run\nValue: true\n',
                   b'Name: watchdog/module\nValue: unsafe;command\n'):
            with self.subTest(db=db), self.assertRaises(ValueError):
                self.run_fixture(db=db)

    def test_configuration_drift_rejected(self):
        changed = helper.debconf_structure(CONFIG)
        changed[0]['config'] = 'config'
        with self.assertRaises(ValueError):
            self.run_fixture(structure=changed)

    def test_identity_rejection_before_reads(self):
        with patch.object(reader.os, 'geteuid', return_value=1000), patch.object(helper, 'read_protected') as read:
            with self.assertRaises(ValueError):
                reader.collect_answers({}, helper)
            read.assert_not_called()


if __name__ == '__main__':
    unittest.main()
