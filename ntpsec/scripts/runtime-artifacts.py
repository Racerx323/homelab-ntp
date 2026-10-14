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


def flat_pack(raw):
    """Store each byte object once, with hash-bound recipes for legacy data archives."""
    blobs = {}; nodes = {}
    def blob(data):
        digest = sha(data); blobs[digest] = data
        return {'blob': digest}
    def visit(data, depth=0):
        digest = sha(data)
        if digest in nodes: return {'archive': digest}
        if depth > 16 or len(data) > 64*1024**2: raise ValueError('flat archive expansion bound')
        parts = []; cursor = 0
        with tarfile.open(fileobj=io.BytesIO(data)) as archive:
            members = archive.getmembers()
            if len(members) > 100 or any(not m.isfile() for m in members):
                raise ValueError('regular bounded provenance archive required')
            for member in members:
                start = member.offset_data; end = start+member.size
                if start < cursor or end > len(data): raise ValueError('provenance archive offsets')
                parts.append(blob(data[cursor:start]))
                body = data[start:end]
                parts.append(visit(body, depth+1) if member.name.endswith('.tar') else blob(body))
                cursor = end
        parts.append(blob(data[cursor:]))
        nodes[digest] = {'bytes': len(data), 'parts': parts}
        return {'archive': digest}
    root = visit(raw)['archive']
    index = {'schema': 1, 'purpose': 'flat-operation-inputs', 'root': root, 'archives': nodes}
    files = dict(blobs, **{'artifact-index.json': encoded(index)})
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode='w') as archive:
        for name, data in sorted(files.items()):
            item = tarfile.TarInfo(name); item.size = len(data); item.mode = 0o600
            archive.addfile(item, io.BytesIO(data))
    result = stream.getvalue()
    if flat_unpack(result) != raw: raise ValueError('flat input round-trip mismatch')
    return result


def flat_unpack(raw):
    """Reconstruct bounded legacy validation inputs in memory; never extract or execute them."""
    if len(raw) > 64*1024**2: raise ValueError('flat storage bound')
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        members = archive.getmembers()
        if (not 1 <= len(members) <= 2049 or len({m.name for m in members}) != len(members)
                or any(not m.isfile() or m.size > 32*1024**2 or
                       (m.name != 'artifact-index.json' and not re.fullmatch(r'[0-9a-f]{64}', m.name)) for m in members)
                or sum(m.size for m in members) > 64*1024**2):
            raise ValueError('closed flat object store required')
        blobs = {m.name: archive.extractfile(m).read() for m in members}
    index_raw = blobs.pop('artifact-index.json')
    if len(index_raw) > 1024**2: raise ValueError('flat index bound')
    index = json.loads(index_raw)
    if (set(index) != {'schema', 'purpose', 'root', 'archives'} or index['schema'] != 1
            or index['purpose'] != 'flat-operation-inputs' or not isinstance(index['archives'], dict)
            or not 1 <= len(index['archives']) <= 128 or any(sha(v) != k for k, v in blobs.items())):
        raise ValueError('flat object digest/schema mismatch')
    nodes = index['archives']; cache = {}; active = set(); used = set(); expanded = 0
    def visit(digest):
        nonlocal expanded
        if digest in active or len(active) > 16: raise ValueError('flat archive cycle/depth')
        if digest in cache: return cache[digest]
        if not re.fullmatch(r'[0-9a-f]{64}', digest) or digest not in nodes:
            raise ValueError('missing flat archive')
        node = nodes[digest]
        if (set(node) != {'bytes', 'parts'} or type(node['bytes']) is not int
                or not 0 < node['bytes'] <= 64*1024**2 or not isinstance(node['parts'], list)
                or not 1 <= len(node['parts']) <= 201):
            raise ValueError('flat archive recipe bound')
        expanded += node['bytes']
        if expanded > 96*1024**2: raise ValueError('aggregate flat expansion bound')
        active.add(digest); parts = []; size = 0
        for part in node['parts']:
            if not isinstance(part, dict) or len(part) != 1 or not set(part) <= {'archive', 'blob'}:
                raise ValueError('flat part schema')
            if 'archive' in part: value = visit(part['archive'])
            else:
                key = part['blob']
                if key not in blobs: raise ValueError('missing flat object')
                used.add(key); value = blobs[key]
            size += len(value)
            if size > node['bytes']: raise ValueError('flat expansion size mismatch')
            parts.append(value)
        value = b''.join(parts)
        if size != node['bytes'] or sha(value) != digest: raise ValueError('flat reconstructed digest mismatch')
        active.remove(digest); cache[digest] = value
        return value
    result = visit(index['root'])
    if set(cache) != set(nodes) or used != set(blobs): raise ValueError('unreferenced flat objects')
    return result


def contents(raw):
    """Read bounded manifest-checked data without importing executable members."""
    with tarfile.open(fileobj=io.BytesIO(raw)) as source:
        members = source.getmembers()
        if (not 0 < len(members) <= 100 or len({m.name for m in members}) != len(members)
                or any(not m.isfile() or not re.fullmatch(r'[A-Za-z0-9_.-]+', m.name)
                       or m.name in ('.', '..') or m.size > 64*1024**2 for m in members)
                or sum(m.size for m in members) > 96*1024**2):
            raise ValueError('bounded regular historical archive required')
        files = {m.name: source.extractfile(m).read() for m in members}
    manifest = json.loads(files['manifest.json'])
    if manifest != {n: sha(v) for n, v in files.items() if n != 'manifest.json'}:
        raise ValueError('historical manifest mismatch')
    return files


def specification(spec, members):
    if (spec['members'] != members
            or not re.fullmatch(r'[a-z][a-z0-9-]{0,47}', spec['operation_id'])
            or len(spec['endpoints']) != 2 or len(set(spec['endpoints'])) != 2
            or type(spec['prepared_epoch']) is not int or type(spec['expires_epoch']) is not int
            or not 0 < spec['expires_epoch']-spec['prepared_epoch'] <= 86400
            or not re.fullmatch(r'/var/lib/ntp-(?:acquire|restore)-'+re.escape(spec['operation_id']), spec['stage'])):
        raise ValueError('historical specification/member identity mismatch')


def archive(raw, purpose=None):
    """Verify a historical manifest and identity as data, without importing its validator."""
    files = contents(raw); spec = json.loads(files['spec.json'])
    specification(spec, {n: sha(v) for n, v in files.items() if n not in ('spec.json', 'manifest.json', 'review.md')})
    if purpose is not None and spec.get('purpose') != purpose:
        raise ValueError('historical purpose mismatch')
    return spec, files


MONITOR_DATA = {'reference.tar', 'reference-report.json', 'reference-receipt.json',
                'reference-cleanup.json', 'receiver-runtime.json', 'known_hosts',
                'restoration.tar', 'restoration-proof.json'}


def project_monitor(raw, checksum):
    """Verify the complete executed archive once; carry only consumed data forward."""
    if sha(raw) != checksum: raise ValueError('executed monitor archive digest')
    _, source = archive(raw, 'service-monitor')
    files = {n: source[n] for n in MONITOR_DATA | {'spec.json'}}
    files['source-manifest.json'] = source['manifest.json']
    files['projection.json'] = encoded({'schema': 1, 'purpose': 'monitor-revalidation-inputs',
                                      'source_sha256': checksum, 'source_bytes': len(raw)})
    files['manifest.json'] = encoded({n: sha(v) for n, v in files.items()})
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode='w') as target:
        for name, data in sorted(files.items()):
            item = tarfile.TarInfo(name); item.size = len(data); item.mode = 0o600
            target.addfile(item, io.BytesIO(data))
    result = flat_pack(stream.getvalue()); monitor_source(result)
    return result


def monitor_source(raw):
    """Return original identity and required inputs; projections are not original archives."""
    with tarfile.open(fileobj=io.BytesIO(raw)) as container:
        flat = 'artifact-index.json' in container.getnames()
    files = contents(flat_unpack(raw) if flat else raw)
    if 'projection.json' not in files:
        spec, files = archive(raw, 'service-monitor')
        return spec, files, sha(raw)
    if not flat or set(files) != MONITOR_DATA | {'spec.json', 'source-manifest.json', 'projection.json', 'manifest.json'}:
        raise ValueError('closed monitor data projection required')
    origin = json.loads(files['projection.json']); spec = json.loads(files['spec.json'])
    manifest = json.loads(files['source-manifest.json'])
    if (set(origin) != {'schema', 'purpose', 'source_sha256', 'source_bytes'}
            or origin['schema'] != 1 or origin['purpose'] != 'monitor-revalidation-inputs'
            or not re.fullmatch(r'[0-9a-f]{64}', origin['source_sha256'])
            or type(origin['source_bytes']) is not int or not 0 < origin['source_bytes'] <= 96*1024**2
            or set(manifest) != set(spec['members']) | {'spec.json', 'review.md'}
            or any(not re.fullmatch(r'[A-Za-z0-9_.-]+', name) or name in ('.', '..') for name in manifest)
            or any(not re.fullmatch(r'[0-9a-f]{64}', value) for value in manifest.values())
            or any(manifest.get(n) != sha(files[n]) for n in MONITOR_DATA | {'spec.json'})):
        raise ValueError('monitor projection provenance/retained data mismatch')
    specification(spec, {n: v for n, v in manifest.items() if n not in ('spec.json', 'review.md')})
    if spec.get('purpose') != 'service-monitor': raise ValueError('historical purpose mismatch')
    return spec, files, origin['source_sha256']


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
