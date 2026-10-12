#!/usr/bin/python3
"""Prepare a foundation transaction from a repo recipe and fresh bound evidence."""
import argparse
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile
import time

REPO = Path(__file__).resolve().parents[2]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def module(name, filename):
    definition = importlib.util.spec_from_file_location(name, REPO / 'ntpsec/scripts' / filename)
    result = importlib.util.module_from_spec(definition)
    definition.loader.exec_module(result)
    return result


worker = module('foundation_worker', 'foundation-install.py')
fetcher = module('foundation_assets', 'fetch-installation-assets.py')
answers = module('foundation_answers', 'read-debconf-answers.py')


def read_bytes(path, limit=4 * 1024 * 1024):
    if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file():
        raise ValueError('regular input without symlink ancestors required')
    with path.open('rb') as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError('preparation input exceeds bound')
    return data


def bound_json(path, expected):
    raw = read_bytes(path)
    if not re.fullmatch(r'[0-9a-f]{64}', expected) or sha(raw) != expected:
        raise ValueError('reviewed evidence hash mismatch')
    return json.loads(raw)


def validate_snapshot(snapshot, recipe, recipe_sha, epoch):
    if (snapshot['schema'] != 1 or snapshot['recipe_sha256'] != recipe_sha
            or type(snapshot['collected_epoch']) is not int
            or not -300 <= epoch - snapshot['collected_epoch'] <= recipe['maximum_snapshot_age_seconds']
            or snapshot['os'] != recipe['os'] or snapshot['architecture'] != recipe['architecture']
            or snapshot['machine'] != recipe['machine'] or snapshot['caller'] != recipe['caller']
            or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,62}', snapshot['hostname'])
            or not re.fullmatch(r'[A-Za-z0-9.+_-]+-v8', snapshot['kernel'])
            or not re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', snapshot['boot_id'])
            or snapshot['dpkg_audit'] != '' or snapshot['active_time_daemons'] != []):
        raise ValueError('fresh reviewed Pi 4 Trixie snapshot required')
    if (not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]*', snapshot['ssh']['host'])
            or not re.fullmatch(r'SHA256:[A-Za-z0-9+/]{43}', snapshot['ssh']['fingerprint'])):
        raise ValueError('observed SSH endpoint/key identity required')
    baseline = snapshot['baseline']
    if not isinstance(baseline, dict) or not baseline:
        raise ValueError('observed package inventory required')
    for name, value in baseline.items():
        if (not re.fullmatch(r'[a-z0-9][a-z0-9+.-]+(?::arm64|:armhf)?', name)
                or not isinstance(value, list) or len(value) != 2
                or not re.fullmatch(r'[A-Za-z0-9.+:~_-]+', value[0])
                or value[1] not in ('ii ', 'rc ')
                or name.split(':')[0] in recipe['prohibited_packages']
                or name.split(':')[0].startswith('ntpsec')):
            raise ValueError('unsupported, conflicting or unresolved package inventory')
    records = snapshot['inputs']
    inputs = {r['path']: r for r in records}
    if len(records) > 512 or len(inputs) != len(records) or not set(recipe['required_inputs']).issubset(inputs):
        raise ValueError('missing/duplicate protected observation')
    for path, record in inputs.items():
        if (not path.startswith('/') or str(Path(path)) != path or '..' in Path(path).parts
                or Path(path) == Path('/var/cache/debconf/passwords.dat')):
            raise ValueError('unsafe or password-database input')
        if record.get('absent') is True:
            if set(record) != {'path', 'absent'}:
                raise ValueError('ambiguous absent input')
        elif (set(record) != {'path', 'sha256', 'uid', 'gid', 'mode'}
              or record['uid'] != 0 or record['gid'] != 0
              or not re.fullmatch(r'[0-9a-f]{64}', record['sha256'])
              or not re.fullmatch(r'0o[0-7]{3,4}', record['mode'])
              or int(record['mode'], 8) & 0o022):
            raise ValueError('unprotected observed input')
    if any(inputs[p].get('absent') is not True for p in recipe['required_absent_inputs']):
        raise ValueError('unreviewed policy/helper present')
    for p in ('/etc/apt/listchanges.conf', '/var/lib/dpkg/status', '/etc/debconf.conf',
              '/usr/share/debconf/debconf.conf'):
        if inputs[p].get('absent'):
            raise ValueError('required protected state missing')
    directories = snapshot['directories']
    if set(directories) != set(recipe['required_directories']):
        raise ValueError('configuration directory coverage mismatch')
    for path, names in directories.items():
        if (not isinstance(names, list) or names != sorted(set(names))
                or any(not re.fullmatch(r'[A-Za-z0-9_.+~-]+', n) or n in ('.', '..') for n in names)
                or any(path + '/' + n not in inputs or inputs[path + '/' + n].get('absent') for n in names)):
            raise ValueError('configuration directory member lacks protected observation')
    coverage = snapshot['coverage']
    for key, prefixes in (('debconf_modules', ('/usr/share/perl5/Debconf/',)),
                          ('listchanges_modules', ('/usr/share/apt-listchanges/', '/usr/lib/python3/dist-packages/apt_listchanges/')),
                          ('keyrings', ('/usr/share/keyrings/', '/etc/apt/keyrings/', '/etc/apt/trusted.gpg')),
                          ('source_files', ('/etc/apt/sources.list',))):
        paths = coverage[key]
        if (not isinstance(paths, list) or not paths or len(set(paths)) != len(paths)
                or any(p not in inputs or inputs[p].get('absent') or not p.startswith(prefixes) for p in paths)):
            raise ValueError('hook/source/key coverage incomplete')
    source_paths = {'/etc/apt/sources.list.d/' + n for n in directories['/etc/apt/sources.list.d']}
    if not inputs['/etc/apt/sources.list'].get('absent'):
        source_paths.add('/etc/apt/sources.list')
    if set(coverage['source_files']) != source_paths:
        raise ValueError('source coverage differs from observed file set')
    answers.normal_database(snapshot['answers']['structure'])
    structure = snapshot['answers']['structure']
    template = {'driver': 'File', 'name': 'templatedb', 'filename': '/var/cache/debconf/templates.dat',
                'mode': '644', 'omitted_fields': []}
    if len(structure) != 5 or template not in structure:
        raise ValueError('reviewed normal template File backend required')
    if set(snapshot['answers']['expected']) != {'watchdog/run', 'watchdog/restart',
            'watchdog/run_keepalive', 'watchdog/module', 'msmtp/apparmor'}:
        raise ValueError('five reviewed non-secret Debconf answers required')
    if (snapshot['network']['boot'] != snapshot['boot_id']
            or set(snapshot['network']) != {'boot', 'units', 'addresses', 'routes'}
            or set(snapshot['automatic_updates']) != set((*worker.TIMERS, *worker.SERVICES))
            or not isinstance(snapshot['foreign_architectures'], list)
            or snapshot['foreign_architectures'] != sorted(set(snapshot['foreign_architectures']))
            or set(snapshot['foreign_architectures']) - {'armhf'}):
        raise ValueError('observed network/update/architecture state required')
    return inputs


def package_requirements(recipe, manifest):
    fetcher.validate_manifest(manifest)
    assets = [r for r in manifest['assets'] if recipe['asset_group'] in r['groups']]
    rows = []
    for asset in assets:
        row = {k: asset[k] for k in ('package', 'version', 'architecture', 'size', 'sha256')}
        row['binary_package'] = row['package']
        row['file'] = worker.archive_file(row)
        rows.append(row)
    providers = manifest.get('root_providers', {})
    names = {r['package'] for r in rows}
    if (not isinstance(providers, dict) or any(not isinstance(k, str) or not isinstance(v, str)
            or v not in names for k, v in providers.items())):
        raise ValueError('root provider must name one pinned concrete package')
    if (not assets or len(names) != len(rows)
            or not {providers.get(n, n) for n in recipe['roots']}.issubset(names)
            or any(r['package'] in recipe['prohibited_packages'] or r['package'].startswith('ntpsec')
                   or r['architecture'] not in ('arm64', 'all') for r in rows)):
        raise ValueError('complete pinned foundation requirement set required')
    return rows, {r['package']: r for r in assets}


def delta(requirements, baseline):
    missing = []
    for row in requirements:
        matches = [(n, v) for n, v in baseline.items()
                   if n in (row['package'], row['package']+':'+row['architecture'])]
        if not matches:
            missing.append(row)
        elif len(matches) != 1 or matches[0][1] != [row['version'], 'ii ']:
            raise ValueError('installed prerequisite version/status conflict; no implicit upgrade')
    return missing


def package_fields(text):
    fields = {}
    for line in text.splitlines():
        name, separator, value = line.partition(':')
        if separator and name in ('Package', 'Version', 'Architecture', 'Multi-Arch'):
            if name in fields:
                raise ValueError('duplicate package control field')
            fields[name] = value.strip()
    if not {'Package', 'Version', 'Architecture'}.issubset(fields):
        raise ValueError('complete package control identity required')
    if fields.get('Multi-Arch', 'no') not in ('no', 'same', 'foreign', 'allowed'):
        raise ValueError('unsupported Multi-Arch field')
    return fields


def validate_resolution(resolution, snapshot_sha, manifest_sha, snapshot, recipe, requirements, missing):
    report = resolution['report']
    if (resolution['schema'] != 1 or resolution['snapshot_sha256'] != snapshot_sha
            or resolution['asset_manifest_sha256'] != manifest_sha
            or report['snapshot_sha256'] != snapshot_sha
            or report['identity']['hostname'] != snapshot['hostname']
            or type(report['controller_epoch']) is not int
            or not snapshot['collected_epoch'] - 300 <= report['controller_epoch'] < snapshot['collected_epoch'] + recipe['maximum_snapshot_age_seconds']
            or report['state'] != 'completed'
            or any(report.get(k) is not True for k in ('metadata_accepted', 'metadata_unchanged',
                'installed_state_unchanged', 'boot_unchanged', 'approved_inputs_unchanged'))
            or report['groups']['foundation']['accepted'] is not True):
        raise ValueError('accepted fresh signed-resolution/continuity evidence required')
    plan = report['groups']['foundation']['plan']
    expected = {(r['package'], r['version'], r['architecture']) for r in missing}
    changes = [tuple(r) for r in plan['changes']]
    if (set(plan['roots']) != set(recipe['roots']) or len(plan['roots']) != len(set(plan['roots']))
            or plan['recommends_enabled'] is not True or len(changes) != len(set(changes))
            or set(changes) != expected):
        raise ValueError('resolved changes differ from exact missing prerequisites')
    versions = {(r['package'], r['version'], r['architecture']): r for r in plan['versions']}
    if len(versions) != len(plan['versions']) or not 0 < len(versions) <= 1024:
        raise ValueError('duplicate or unbounded selected dependency graph')
    pins = {r['package']: r for r in requirements}
    for identity, row in versions.items():
        name, version, architecture = identity
        if name in recipe['prohibited_packages'] or name.startswith('ntpsec'):
            raise ValueError('source application selected as dependency')
        if row['changed'] is not (identity in expected):
            raise ValueError('selected dependency change flag mismatch')
        if name in pins:
            fields = package_fields(row['record'])
            if (fields['Package'], fields['Version'], fields['Architecture']) != identity:
                raise ValueError('selected Packages record identity mismatch')
            binary = name+':'+architecture if fields.get('Multi-Arch') == 'same' else name
            if fields.get('Multi-Arch') == 'same' and architecture != 'arm64':
                raise ValueError('unsupported Multi-Arch prerequisite')
            pins[name]['binary_package'] = binary
        if identity in expected:
            if row['archive_sha256'] != pins[name]['sha256']:
                raise ValueError('resolved archive digest differs from pinned asset')
        else:
            matches = [v for n, v in snapshot['baseline'].items() if n in (name, name+':'+architecture)]
            if matches != [[version, 'ii ']]:
                raise ValueError('dependency not satisfied by exact observed inventory')
        for edge in row['dependencies']:
            selected = [tuple(v) for v in edge['selected_satisfiers']]
            if (edge['type'] not in ('PreDepends', 'Depends', 'Recommends')
                    or any(v not in versions for v in selected)
                    or (not selected and edge['type'] != 'Recommends')):
                raise ValueError('incomplete selected dependency closure')
    if any((r['package'], r['version'], r['architecture']) not in versions for r in requirements):
        raise ValueError('required pinned prerequisite absent from selected closure')
    commands = [r for r in report['commands'] if r.get('label') == 'simulate_foundation']
    if len(commands) != 1 or commands[0]['rc'] != 0 or commands[0].get('error') is not None:
        raise ValueError('one successful combined native simulation required')
    worker.validate_simulation(commands[0]['output'], {'packages': missing, 'baseline': snapshot['baseline']})


def candidate_effects(archives, paths):
    found = {}
    for filename in archives:
        raw = subprocess.check_output(['/usr/bin/dpkg-deb', '--fsys-tarfile', str(filename)], timeout=30)
        with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
            for entry in archive.getmembers():
                name = '/' + entry.name.removeprefix('./')
                if name in paths:
                    if (name in found or not entry.isfile() or entry.uid != 0 or entry.gid != 0
                            or entry.mode & 0o022):
                        raise ValueError('unique protected candidate file required')
                    found[name] = sha(archive.extractfile(entry).read())
    if set(found) != set(paths):
        raise ValueError('declared package effects missing from verified archives')
    return found


def render(source, replacements):
    for before, after in replacements:
        if source.count(before) != 1:
            raise ValueError('canonical template binding missing or ambiguous')
        source = source.replace(before, after)
    return source


def prepare(recipe_path, manifest_path, snapshot_path, snapshot_sha, resolution_path, resolution_sha,
            cache, known_hosts, output, operation_id, epoch=None):
    epoch = int(time.time()) if epoch is None else epoch
    recipe_raw, manifest_raw = read_bytes(recipe_path), read_bytes(manifest_path)
    recipe, manifest = json.loads(recipe_raw), json.loads(manifest_raw)
    if (recipe['schema'] != 1 or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,47}', operation_id)
            or type(recipe['approval_window_seconds']) is not int
            or not 0 < recipe['approval_window_seconds'] <= 86400
            or type(recipe['maximum_snapshot_age_seconds']) is not int
            or not 0 < recipe['maximum_snapshot_age_seconds'] <= 86400
            or recipe['architecture'] != 'arm64' or recipe['machine'] != 'aarch64'
            or not set(worker.PROHIBITED).issubset(recipe['prohibited_packages'])
            or recipe['caller'] != {'user': 'ama', 'uid': 1000}):
        raise ValueError('reviewed recipe and safe exclusive operation ID required')
    snapshot = bound_json(snapshot_path, snapshot_sha)
    inputs = validate_snapshot(snapshot, recipe, sha(recipe_raw), epoch)
    requirements, assets = package_requirements(recipe, manifest)
    missing = delta(requirements, snapshot['baseline'])
    resolution = bound_json(resolution_path, resolution_sha)
    validate_resolution(resolution, snapshot_sha, sha(manifest_raw), snapshot, recipe, requirements, missing)
    host_data = read_bytes(known_hosts, 4096)
    fields = host_data.decode('ascii').split()
    if len(fields) != 3 or fields[:2] != [snapshot['ssh']['host'], 'ssh-ed25519']:
        raise ValueError('observed single SSH host key required')
    import base64
    fingerprint = 'SHA256:' + base64.b64encode(hashlib.sha256(base64.b64decode(fields[2], validate=True)).digest()).decode().rstrip('=')
    if fingerprint != snapshot['ssh']['fingerprint']:
        raise ValueError('observed SSH key fingerprint mismatch')
    stage = '/var/lib/ntp-foundation-' + operation_id
    data = {'worker.py': render(read_bytes(REPO/'ntpsec/scripts/foundation-install.py'), [
        (b"STAGE = Path('/var/lib/ntp-foundation-v6')", ('STAGE = Path(' + repr(stage) + ')').encode()),
        (b"APPROVED_HOSTNAME = 'j2-svntp1'", ('APPROVED_HOSTNAME = ' + repr(snapshot['hostname'])).encode())]),
        'hook-helper.py': read_bytes(REPO/'ntpsec/scripts/hook-closure-preflight.py'),
        'answer-helper.py': read_bytes(REPO/'ntpsec/scripts/read-debconf-answers.py'),
        'listchanges.conf': read_bytes(REPO/'ntpsec/templates/apt-listchanges-transaction.conf'),
        'needrestart.conf': read_bytes(REPO/'ntpsec/templates/needrestart-pi4.conf')}
    for row in missing:
        asset = assets[row['package']]
        path = cache / asset['filename']
        if any(p.is_symlink() for p in (path, *path.parents)):
            raise ValueError('symlink archive/cache rejected')
        fetcher.verify_file(path, asset)
        value = read_bytes(path, 40 * 1024 * 1024)
        if sha(value) != row['sha256'] or len(value) != row['size']:
            raise ValueError('archive changed during preparation')
        data[row['file']] = value
    effect_paths = {p for row in missing for p in recipe['package_effects'].get(row['package'], [])}
    # Declare both existing and absent effect destinations in the reviewed snapshot.
    all_effects = {p for paths in recipe['package_effects'].values() for p in paths}
    if not all_effects.issubset(inputs):
        raise ValueError('package effect pre-state coverage missing')
    # Native inspection uses the verified bytes that will be bundled, never a
    # reopened mutable cache. The private temporary copies are always removed.
    with tempfile.TemporaryDirectory(prefix='ntp-foundation-inspection-') as directory:
        archives = []
        for row in missing:
            path = Path(directory)/Path(row['file']).name
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(data[row['file']])
            fields = package_fields(subprocess.check_output(['/usr/bin/dpkg-deb', '--field', str(path),
                'Package', 'Version', 'Architecture', 'Multi-Arch'], timeout=30).decode())
            binary = fields['Package']+':'+fields['Architecture'] if fields.get('Multi-Arch') == 'same' else fields['Package']
            if ((fields['Package'], fields['Version'], fields['Architecture']) !=
                    (row['package'], row['version'], row['architecture']) or binary != row['binary_package']):
                raise ValueError('verified archive control differs from signed package record')
            archives.append(path)
        effects = candidate_effects(archives, effect_paths)
    missing_names = {r['package'] for r in missing}
    for name, paths in recipe['package_effects'].items():
        if name not in missing_names and name in assets and any(inputs[p].get('absent') for p in paths):
            raise ValueError('installed prerequisite packaged input missing')
    for path, checksum in effects.items():
        if not inputs[path].get('absent') and inputs[path]['sha256'] != checksum:
            raise ValueError('new package would replace an unreviewed existing input')
    expected = copy.deepcopy(snapshot['baseline'])
    expected.update({r['binary_package']: [r['version'], 'ii '] for r in missing})
    spec = {'schema': 2, 'scope': 'foundation', 'stage': stage,
        'hostname': snapshot['hostname'], 'kernel': snapshot['kernel'], 'boot_id': snapshot['boot_id'],
        'prepared_epoch': epoch, 'expires_epoch': min(epoch + recipe['approval_window_seconds'],
            snapshot['collected_epoch'] + recipe['maximum_snapshot_age_seconds']),
        'baseline': snapshot['baseline'], 'requirements': requirements, 'packages': missing,
        'expected_inventory': expected, 'inputs': snapshot['inputs'], 'directories': snapshot['directories'],
        'answers': snapshot['answers'], 'foreign_architectures': snapshot['foreign_architectures'],
        'network': snapshot['network'], 'automatic_updates': snapshot['automatic_updates'],
        'minimum_free_bytes': recipe['minimum_free_bytes'], 'package_created_inputs': effects,
        'needrestart_version': recipe['needrestart_report_version'],
        'members': {name: sha(value) for name, value in data.items()}}
    policy = inputs[str(worker.NRPOLICY)]
    if not policy.get('absent'):
        spec['prior_needrestart_sha256'] = policy['sha256']
    validation = {'__name__': 'prepared_foundation'}
    exec(compile(data['worker.py'], 'prepared-worker.py', 'exec'), validation)
    validation['validate_spec'](spec)
    launcher = render(read_bytes(REPO/'ntpsec/scripts/run-foundation-install.py'), [
        (b"FINGERPRINT = 'SHA256:yXiID8RObBoIejVpvr2KesaqIlocbSORyemD5dKrEys'", ('FINGERPRINT = ' + repr(fingerprint)).encode()),
        (b"TARGET = 'ama@10.1.0.137'", ('TARGET = ' + repr('ama@' + snapshot['ssh']['host'])).encode()),
        (b"['10.1.0.137', 'ssh-ed25519']", repr([snapshot['ssh']['host'], 'ssh-ed25519']).encode())])
    for name, value in data.items():
        if name.endswith('.py'):
            compile(value, name, 'exec')
    compile(launcher, 'launcher.py', 'exec')
    provenance = {'recipe_sha256': sha(recipe_raw), 'asset_manifest_sha256': sha(manifest_raw),
        'snapshot_sha256': snapshot_sha, 'resolution_sha256': resolution_sha,
        'preparation_script_sha256': sha(Path(__file__).read_bytes()), 'target_contact': False,
        'required_packages': len(requirements), 'package_changes': len(missing)}
    spec['preparation'] = {k: provenance[k] for k in ('recipe_sha256', 'asset_manifest_sha256',
                                                   'snapshot_sha256', 'resolution_sha256')}
    data.update({'spec.json': (json.dumps(spec, sort_keys=True) + '\n').encode(),
        'known_hosts': host_data, 'launcher.py': launcher,
        'recipe.json': recipe_raw, 'installation-assets.json': manifest_raw,
        'snapshot.json': read_bytes(snapshot_path), 'resolution.json': read_bytes(resolution_path),
        'tests.py': read_bytes(REPO/'ntpsec/tests/test_foundation_install.py'),
        'native-protocol.txt': read_bytes(REPO/'ntpsec/tests/fixtures/native-foundation-protocol-v1.txt'),
        'provenance.json': (json.dumps(provenance, sort_keys=True, indent=2) + '\n').encode()})
    if sha(data['snapshot.json']) != snapshot_sha or sha(data['resolution.json']) != resolution_sha:
        raise ValueError('evidence changed during preparation')
    data['manifest.json'] = (json.dumps({n: sha(v) for n, v in data.items()}, sort_keys=True) + '\n').encode()
    if any(p.is_symlink() for p in (output, *output.parents)):
        raise ValueError('symlink output path rejected')
    output.mkdir(mode=0o700)  # Validation completes before the first persistent write.
    for name, value in data.items():
        path = output / name
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(value)
    return {'output': str(output), 'stage': stage, 'packages': len(missing),
            'state': 'prepared_for_review', 'target_contact': False, 'execution_authorized': False}


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recipe', type=Path, default=REPO/'ntpsec/configs/foundation-recipe.json')
    parser.add_argument('--asset-manifest', type=Path, default=REPO/'ntpsec/configs/installation-assets.json')
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--snapshot-sha256', required=True)
    parser.add_argument('--resolution', type=Path, required=True)
    parser.add_argument('--resolution-sha256', required=True)
    parser.add_argument('--asset-cache', type=Path, required=True)
    parser.add_argument('--known-hosts', type=Path, required=True)
    parser.add_argument('--operation-id', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.recipe, args.asset_manifest, args.snapshot, args.snapshot_sha256,
        args.resolution, args.resolution_sha256, args.asset_cache, args.known_hosts,
        args.output, args.operation_id), sort_keys=True))


if __name__ == '__main__':
    main()
