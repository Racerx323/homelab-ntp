#!/usr/bin/python3
"""Seal an acceptance-only continuation from verified v5 bundle/readback evidence."""
import argparse
import base64
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tarfile
import time

ROOT = Path(__file__).resolve().parents[1]
RETAINED = {'spec.json', 'claim.json', 'failure.json', 'candidate/build.log',
            'candidate/release.json', 'acceptance.log'}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def render(worker, continuation):
    header = ('import base64,types\noriginal_worker=types.ModuleType("sealed_acceptance_worker")\n'
              'exec(compile(base64.b64decode(' + repr(base64.b64encode(worker).decode())
              + ',validate=True),"sealed-acceptance-worker.py","exec"),original_worker.__dict__)\n')
    adapter = ('\ndef entry(spec,files,epoch,mode):\n'
               '    return continue_entry(spec,files,epoch,mode,original_worker)\n'
               'def evidence():\n    return original_worker.evidence()\n')
    result = header.encode() + continuation + adapter.encode()
    compile(result, 'sealed-source-acceptance.py', 'exec')
    return result


def prepare(args):
    continuation = load('continuation', ROOT / 'scripts/continue-source-acceptance.py')
    if args.origin_sha256 != continuation.ORIGIN_BUNDLE:
        raise ValueError('only the retained v5 candidate is eligible')
    bundle_data = (args.origin / 'source-build.tar').read_bytes()
    if sha(bundle_data) != args.origin_sha256:
        raise ValueError('original bundle hash mismatch')
    with tarfile.open(fileobj=io.BytesIO(bundle_data), mode='r:') as archive:
        if archive.extractfile('launcher.py').read() != (args.origin / 'launcher.py').read_bytes():
            raise ValueError('original launcher differs from bound archive')
    origin_launcher = load('origin_launcher', args.origin / 'launcher.py')
    origin, _ = origin_launcher.prepare(args.origin / 'source-build.tar', args.origin_sha256)
    raw = origin_launcher.private_file(args.readback, 64 * 1024 * 1024)
    if sha(raw) != args.readback_sha256:
        raise ValueError('readback evidence hash mismatch')
    report = json.loads(raw)
    if (report['bundle_sha256'] != args.origin_sha256 or report['mode'] != 'readback'
            or report['state'] != 'transport_terminal' or report['transport_exit_status'] != 0
            or report['worker_status'] != 0
            or report['report']['stage'] != '/home/ama/' + continuation.ORIGIN_STAGE):
        raise ValueError('successful original-attempt readback required')
    evidence = {}
    for name, item in report['report']['evidence'].items():
        data = base64.b64decode(item['base64'], validate=True)
        if sha(data) != item['sha256']:
            raise ValueError('retained evidence content/hash mismatch')
        evidence[name] = data
    expected_spec = (json.dumps(origin, sort_keys=True) + '\n').encode()
    if evidence['spec.json'] != expected_spec or not RETAINED.issubset(evidence):
        raise ValueError('original specification/evidence binding mismatch')
    release = json.loads(evidence['candidate/release.json'])
    claim = json.loads(evidence['claim.json'])
    failure = json.loads(evidence['failure.json'])
    if (release['profile_sha256'] != origin['members']['profile.json']
            or claim['bundle_spec_sha256'] != sha(expected_spec)
            or failure['state'] != 'source_build_held' or not failure['candidate_preserved']
            or '/usr/local/bin/ntpq' not in failure['error']
            or b"No module named 'ntp'" not in evidence['acceptance.log']
            or b"'check' finished successfully" not in evidence['candidate/build.log']
            or b"'install' finished successfully" not in evidence['candidate/build.log']):
        raise ValueError('completed v5 build and known standalone acceptance defect required')
    prepared = int(time.time())
    if prepared >= origin['expires_epoch']:
        raise ValueError('original prerequisite approval window expired')
    worker_data = (ROOT / 'scripts/source-build-stage.py').read_bytes()
    continuation_data = (ROOT / 'scripts/continue-source-acceptance.py').read_bytes()
    worker = render(worker_data, continuation_data)
    spec = {k: origin[k] for k in ('schema', 'hostname', 'kernel', 'python', 'inventory', 'pps_header_sha256')}
    spec.update(operation='source-acceptance-continuation', origin_bundle_sha256=args.origin_sha256,
                prepared_epoch=prepared, expires_epoch=origin['expires_epoch'],
                readback_result_sha256=args.readback_sha256,
                acceptance_worker_sha256=sha(worker_data), continuation_source_sha256=sha(continuation_data),
                retained={n: sha(evidence[n]) for n in sorted(RETAINED)},
                members={'source-build-stage.py': sha(worker)})
    files = {'source-build-stage.py': worker, 'spec.json': (json.dumps(spec, sort_keys=True)+'\n').encode(),
             'launcher.py': (ROOT / 'scripts/run-source-build.py').read_bytes(),
             'known_hosts': origin_launcher.private_file(args.origin / 'known_hosts', 4096),
             'tests.py': (ROOT / 'tests/test_source_acceptance_continuation.py').read_bytes(),
             'review.md': args.review.read_bytes()}
    files['manifest.json'] = (json.dumps({n: sha(b) for n, b in files.items()}, sort_keys=True)+'\n').encode()
    args.output.mkdir(mode=0o700)
    for name, data in files.items():
        with (args.output / name).open('xb') as stream:
            stream.write(data)
    bundle = args.output / 'source-build.tar'
    with tarfile.open(bundle, 'w', format=tarfile.USTAR_FORMAT) as archive:
        for name, data in sorted(files.items()):
            member = tarfile.TarInfo(name)
            member.mode = 0o600
            member.size = len(data)
            member.mtime = prepared
            archive.addfile(member, io.BytesIO(data))
    launcher = load('continuation_launcher', args.output / 'launcher.py')
    checksum = sha(bundle.read_bytes())
    bound, inputs = launcher.prepare(bundle, checksum)
    for mode in ('accept', 'readback'):
        compile(launcher.payload(bound, inputs, prepared, mode), 'payload', 'exec')
    result = {'bundle_sha256': checksum, 'members': len(files), 'bytes': bundle.stat().st_size,
              'expires_epoch': spec['expires_epoch'], 'staged_entries': len(release['files']),
              'strict_launcher_verified': True, 'both_payloads_compile': True, 'target_contact': False}
    (args.output / 'sealing.json').write_text(json.dumps(result, indent=2)+'\n')
    return result


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument('--origin', type=Path, required=True)
    parser.add_argument('--origin-sha256', required=True)
    parser.add_argument('--readback', type=Path, required=True)
    parser.add_argument('--readback-sha256', required=True)
    parser.add_argument('--review', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    print(json.dumps(prepare(parser.parse_args())))


if __name__ == '__main__':
    main()
