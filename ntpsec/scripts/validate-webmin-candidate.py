#!/usr/bin/python3
"""Check pinned package assets and exercise their actual subnet matcher offline."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile

ROOT=Path(__file__).resolve().parents[1]


def validate(assets):
    manifest=json.loads((ROOT/'configs/webmin-installation-assets.json').read_text())
    for package in manifest['packages']:
        path=assets/Path(package['Filename']).name
        if path.stat().st_size!=int(package['Size']) or hashlib.sha256(path.read_bytes()).hexdigest()!=package['SHA256']:
            raise ValueError('candidate checksum/size mismatch')
    if hashlib.sha256((assets/'webmin-keyring.gpg').read_bytes()).hexdigest()!=manifest['keyring_sha256']:
        raise ValueError('keyring mismatch')
    package=next(p for p in manifest['packages'] if p['Package']=='webmin')
    raw=subprocess.run(['dpkg-deb','--fsys-tarfile',str(assets/Path(package['Filename']).name)],capture_output=True,check=True).stdout
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        library=archive.extractfile('./usr/share/webmin/miniserv-lib.pl').read()
        update=archive.extractfile('./usr/share/webmin/init/updateboot.pl').read()
        setup=archive.extractfile('./usr/share/webmin/setup.sh').read()
    # Guard is independent of unit files removed by the reviewed update script.
    if b'unlink("$p/$product.service")' not in update or b'.service.d' in update:
        raise ValueError('re-review package unit replacement behavior')
    if b'$systemctlcmd start $bootscript' not in setup:
        raise ValueError('re-review package start wrapper')
    policy=json.loads((ROOT/'configs/webmin-http-policy.json').read_text())
    cases={'10.1.0.1':1,'10.1.3.254':1,'10.1.4.1':0,'192.0.2.1':0,
           'fd36:5aa8:6971:1::1':1,'fd36:5aa8:6971:2::1':0,'2001:db8::1':0}
    with tempfile.TemporaryDirectory(prefix='webmin-candidate-') as directory:
        path=Path(directory)/'miniserv-lib.pl';path.write_bytes(library)
        code='require $ARGV[0]; my $ip=$ARGV[1]; my @allow=split(/ /,$ARGV[2]); print miniserv::ip_match($ip,$ip,@allow) ? "1" : "0";'
        for ip,expected in cases.items():
            result=subprocess.run(['perl','-e',code,str(path),ip,policy['allow']],capture_output=True,check=True,timeout=10)
            if result.stdout.decode()!=str(expected): raise ValueError('upstream allowlist mismatch: '+ip)
    return {'asset_hashes_verified':True,'upstream_subnet_cases':len(cases),
            'package_unit_replacement_reviewed':True,'full_arm64_installation_tested':False}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--assets',type=Path,required=True)
    print(json.dumps(validate(parser.parse_args().assets)))
