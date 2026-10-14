#!/usr/bin/python3
"""Maintained readers for archived facts; archived executable bytes are never loaded."""
import base64
import hashlib
import io
import json
import re
import tarfile


# New operation manifests bind these repository sources alongside their data inputs.
CODE_PATHS = {
    'hardware-checker.py': 'scripts/host-configuration-stage.py',
    'pps-checker.py': 'scripts/check-pps.py',
    'reference.py': 'scripts/run-gpsd-acquisition.py',
    'helper.py': 'scripts/foundation-install.py',
    'restoration-controller.py': 'scripts/run-cutover-restoration.py',
    'runtime-artifacts.py': 'scripts/runtime-artifacts.py',
    'host-network-stage.py': 'scripts/host-network-stage.py',
    'inspect-source-destinations.py': 'scripts/inspect-source-destinations.py',
    'clockmaker.py': 'scripts/clockmaker.py',
    'timeservice.py': 'scripts/timeservice.py',
}
RUNTIME_CODE = {
    'foundation-install.py': 'helper.py',
    'host-configuration-stage.py': 'hardware-checker.py',
    'check-pps.py': 'pps-checker.py',
    'host-network-stage.py': 'host-network-stage.py',
    'inspect-source-destinations.py': 'inspect-source-destinations.py',
    'clockmaker.py': 'clockmaker.py',
    'timeservice.py': 'timeservice.py',
}


def encoded(value): return (json.dumps(value, sort_keys=True)+'\n').encode()
def sha(raw): return hashlib.sha256(raw).hexdigest()


def archive(raw, purpose=None):
    """Verify a historical manifest and identity as data, without importing its validator."""
    with tarfile.open(fileobj=io.BytesIO(raw)) as source:
        members = source.getmembers()
        if (not 0 < len(members) <= 100 or len({m.name for m in members}) != len(members)
                or any(not m.isfile() or not re.fullmatch(r'[A-Za-z0-9_.-]+', m.name)
                       or m.name in ('.', '..') or m.size > 64*1024**2 for m in members)
                or sum(m.size for m in members) > 96*1024**2):
            raise ValueError('bounded regular historical archive required')
        files = {m.name: source.extractfile(m).read() for m in members}
    manifest = json.loads(files['manifest.json']); spec = json.loads(files['spec.json'])
    if manifest != {n: sha(v) for n, v in files.items() if n != 'manifest.json'}:
        raise ValueError('historical manifest mismatch')
    if (spec['members'] != {n: sha(v) for n, v in files.items() if n not in ('spec.json', 'manifest.json', 'review.md')}
            or not re.fullmatch(r'[a-z][a-z0-9-]{0,47}', spec['operation_id'])
            or len(spec['endpoints']) != 2 or len(set(spec['endpoints'])) != 2
            or type(spec['prepared_epoch']) is not int or type(spec['expires_epoch']) is not int
            or not 0 < spec['expires_epoch']-spec['prepared_epoch'] <= 86400
            or not re.fullmatch(r'/var/lib/ntp-(?:acquire|restore)-'+re.escape(spec['operation_id']), spec['stage'])):
        raise ValueError('historical specification/member identity mismatch')
    if purpose is not None and spec.get('purpose') != purpose:
        raise ValueError('historical purpose mismatch')
    return spec, files


def restoration(files, validator):
    spec, old = archive(files['restoration.tar'], 'cutover-restoration')
    source_spec, source = archive(old['source.tar'], 'runtime-diagnostic')
    if (spec['schema'] != 1 or spec['source_sha256'] != sha(old['source.tar'])
            or spec['source_stage'] != source_spec['stage']
            or any(spec[k] != source_spec[k] for k in ('hostname', 'kernel', 'boot_id', 'endpoints', 'old_ipv4'))):
        raise ValueError('restoration source identity mismatch')
    proof = json.loads(files['restoration-proof.json'])
    if set(proof) != {'acceptance', 'readbacks', 'cleanup'} or len(proof['readbacks']) != 2:
        raise ValueError('closed restoration proof required')
    first, second = proof['readbacks']
    if first != second or first['spec_sha256'] != sha(old['spec.json']):
        raise ValueError('matching restoration readbacks required')
    result = first['result']
    receipt = validator.terminal(spec, sha(files['restoration.tar']), dict.fromkeys(spec['endpoints'], result))
    if receipt != proof['acceptance'] or receipt['state'] != 'restoration_verified':
        raise ValueError('accepted restoration continuation required')
    if proof['cleanup'] != {'spec_sha256': sha(old['spec.json']), 'result': {
            'phase': 'cleaned', 'report_sha256': receipt['report_sha256'],
            'source_preserved': True, 'evidence_preserved': True}}:
        raise ValueError('accepted restoration closure required')
    return spec, old, result, source


def receiver(files, acquisition):
    """Validate receiver observations with the maintained data parser and receipt schema."""
    old, archive_files = archive(files['reference.tar'], 'receiver-runtime-inputs')
    acquisition.validate(old, archive_files, historical=True)
    report = json.loads(files['reference-report.json'])
    receipt = acquisition.terminal_receipt(old, archive_files, sha(files['reference.tar']), dict.fromkeys(old['endpoints'], report))
    if receipt != json.loads(files['reference-receipt.json']) or receipt['state'] != 'receiver_runtime_inputs_captured':
        raise ValueError('accepted receiver/runtime capture required')
    for row in report['evidence'].values():
        if sha(base64.b64decode(row['base64'], validate=True)) != row['sha256']:
            raise ValueError('receiver evidence digest')
    if files['receiver-runtime.json'] != base64.b64decode(report['evidence']['receiver-runtime.json']['base64'], validate=True):
        raise ValueError('runtime evidence mismatch')
    cleanup = json.loads(files['reference-cleanup.json'])
    if cleanup != {'spec_sha256': sha(archive_files['spec.json']), 'result': {
            'phase': 'cleaned', 'evidence_preserved': True, 'shm_preserved': True,
            'terminal_sha256': report['evidence']['terminal.json']['sha256']}}:
        raise ValueError('receiver cleanup mismatch')
    if files['known_hosts'] != archive_files['known_hosts']:
        raise ValueError('receiver host key drift')
    return old, archive_files


def runtime_inputs(runtime, old, code, stage):
    """Keep baseline data; replace every executable member with an explicit current input."""
    unknown = {n for n in runtime['members'] if n.endswith('.py')} - set(RUNTIME_CODE)
    if unknown:
        raise ValueError('unmapped historical runtime executable: '+','.join(sorted(unknown)))
    files = {n: old[n] for n in runtime['members'] if not n.endswith('.py')}
    files.update({name: code[member] for name, member in RUNTIME_CODE.items()})
    spec = dict(runtime, stage=str(stage), members={n: sha(v) for n, v in files.items()})
    return spec, files
