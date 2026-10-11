#!/usr/bin/python3
"""Offline pinned downloads, source signature and cache rejection tests."""
import hashlib
import importlib.util
import io
import json
import subprocess
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
s = importlib.util.spec_from_file_location('fetcher', ROOT / 'scripts/fetch-installation-assets.py')
f = importlib.util.module_from_spec(s)
s.loader.exec_module(f)


class Assets(unittest.TestCase):
    def setUp(self):
        self.data = b'pinned archive'
        self.row = {'id': 'fixture', 'groups': ['sources'], 'filename': 'fixture.tar.gz',
                    'url': 'https://publisher.example/fixture.tar.gz', 'size': len(self.data),
                    'sha256': hashlib.sha256(self.data).hexdigest()}

    def test_repository_manifest_has_both_required_packages_and_authenticated_sources(self):
        manifest = json.loads((ROOT / 'configs/installation-assets.json').read_text())
        f.validate_manifest(manifest)
        foundation = [r for r in manifest['assets'] if 'foundation' in r['groups']]
        self.assertEqual(len(foundation), 46)
        self.assertTrue({'pps-tools', 'bc'}.issubset({r['package'] for r in foundation}))
        self.assertTrue(all('%' not in r['filename'] for r in foundation))
        self.assertEqual({r['id'] for r in manifest['assets'] if 'signature' in r},
                         {'source-gpsd', 'source-ntpsec'})

    def test_unsafe_url_path_duplicate_and_conflicting_package_rejected(self):
        for field, value in [('url', 'http://publisher.example/a'), ('url', 'https://user:secret@example/a'),
                             ('filename', '../escape'), ('sha256', 'wrong'), ('size', True), ('package', 'gpsd'),
                             ('groups', 'sources'), ('groups', ['']), ('filename', '..')]:
            row = dict(self.row, **{field: value})
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                f.validate_manifest({'schema': 1, 'assets': [row], 'public_keys': {}})
        with self.assertRaises(ValueError):
            f.validate_manifest({'schema': 1, 'assets': [self.row, self.row], 'public_keys': {}})

    def response(self, data, url='https://publisher.example/fixture.tar.gz'):
        result = io.BytesIO(data)
        result.geturl = lambda: url
        return result

    def test_valid_download_is_private_and_never_replaces_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / self.row['filename']
            with patch.object(f, 'urlopen', return_value=self.response(self.data)):
                f.fetch(self.row, path, 30)
            self.assertEqual(path.read_bytes(), self.data)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with patch.object(f, 'urlopen', return_value=self.response(self.data)), self.assertRaises(FileExistsError):
                f.fetch(self.row, path, 30)
            self.assertEqual(path.read_bytes(), self.data)

    def test_truncated_oversize_corrupt_or_http_redirect_is_not_published(self):
        for data, url in [(b'short', self.row['url']), (self.data+b'x', self.row['url']),
                          (b'x'*len(self.data), self.row['url']), (self.data, 'http://publisher.example/a')]:
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / self.row['filename']
                with patch.object(f, 'urlopen', return_value=self.response(data, url)), self.assertRaises(ValueError):
                    f.fetch(self.row, path, 30)
                self.assertFalse(path.exists())
                self.assertFalse(path.with_name(path.name+'.part').exists())

    def test_verification_does_not_download_and_rejects_file_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory);cache=root/'cache';cache.mkdir()
            manifest=root/'manifest.json'
            manifest.write_text(json.dumps({'schema': 1, 'assets': [self.row], 'public_keys': {}}))
            (cache/self.row['filename']).write_bytes(self.data)
            with patch.object(f, 'urlopen', side_effect=AssertionError('unexpected network')):
                self.assertEqual(f.run(manifest, cache, ['sources'], True)['verified_assets'], 1)
            path=cache/self.row['filename'];path.unlink();path.symlink_to(manifest)
            with self.assertRaises(OSError):
                f.verify_file(path, self.row)

    def test_existing_cache_and_unknown_group_are_rejected_before_download(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);manifest=root/'manifest.json';cache=root/'cache';cache.mkdir()
            manifest.write_text(json.dumps({'schema': 1, 'assets': [self.row], 'public_keys': {}}))
            with self.assertRaises(ValueError):
                f.run(manifest, cache, ['unknown'])
            with self.assertRaises(FileExistsError):
                f.run(manifest, cache, ['sources'])


    def test_signature_requires_pinned_key_bytes_and_exact_signing_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            key = root / 'signer.gpg'
            key.write_bytes(b'pinned public key fixture')
            keys = {'publisher': {'path': key.name,
                                  'sha256': hashlib.sha256(key.read_bytes()).hexdigest(),
                                  'signing_fingerprint': 'A' * 40}}
            row = dict(self.row, signature='signature', public_key='publisher')
            signature = {'filename': 'fixture.sig'}
            for status in (b'', ('[GNUPG:] VALIDSIG ' + 'B' * 40 + ' 2026\n').encode()):
                result = subprocess.CompletedProcess([], 0, stdout=status, stderr=b'')
                with patch.object(f.subprocess, 'run', return_value=result), self.assertRaises(ValueError):
                    f.verify_signature(row, {'signature': signature}, root, keys, root / 'manifest.json')
            key.write_bytes(b'changed public key')
            with patch.object(f.subprocess, 'run') as native, self.assertRaises(ValueError):
                f.verify_signature(row, {'signature': signature}, root, keys, root / 'manifest.json')
            native.assert_not_called()


if __name__ == '__main__':
    unittest.main()
