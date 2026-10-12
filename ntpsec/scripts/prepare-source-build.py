#!/usr/bin/python3
"""Prepare a pinned source profile from reviewed foundation and Python evidence."""
import argparse
import ast
import base64
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import tarfile
import time

REPO = Path(__file__).resolve().parents[2]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def bound_json(path, checksum):
    data = path.read_bytes()
    if sha(data) != checksum:
        raise ValueError('reviewed input hash mismatch: ' + str(path))
    return json.loads(data)


def render_transport(stage, launcher, foundation, known_hosts, operation_id):
    if (not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,62}', operation_id)
            or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,62}', foundation['hostname'])
            or not re.fullmatch(r'[A-Za-z0-9.+_-]+-v8', foundation['kernel'])):
        raise ValueError('safe unique operation and target identity required')
    fields = known_hosts.decode('ascii').split()
    if (len(fields) != 3 or fields[1] != 'ssh-ed25519'
            or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]*', fields[0])):
        raise ValueError('single observed SSH host key required')
    fingerprint = 'SHA256:' + base64.b64encode(hashlib.sha256(
        base64.b64decode(fields[2], validate=True)).digest()).decode().rstrip('=')
    stage_name = '.ntp-source-build-' + operation_id
    replacements = ((stage, (
        ("STAGE_NAME = '.ntp-source-build-v5'", 'STAGE_NAME = ' + repr(stage_name)),
        ("HOSTNAME = 'j2-svntp1'", 'HOSTNAME = ' + repr(foundation['hostname'])),
        ("KERNEL = '6.18.50+rpt-rpi-v8'", 'KERNEL = ' + repr(foundation['kernel'])))),
        (launcher, (
        ("FINGERPRINT = 'SHA256:yXiID8RObBoIejVpvr2KesaqIlocbSORyemD5dKrEys'", 'FINGERPRINT = ' + repr(fingerprint)),
        ("TARGET = 'ama@10.1.0.137'", 'TARGET = ' + repr('ama@' + fields[0])),
        ("['10.1.0.137', 'ssh-ed25519']", repr(fields[:2])))))
    rendered = []
    for source, bindings in replacements:
        for before, after in bindings:
            if source.count(before.encode()) != 1:
                raise ValueError('canonical source template binding missing or ambiguous')
            source = source.replace(before.encode(), after.encode())
        compile(source, 'rendered-source-input.py', 'exec')
        rendered.append(source)
    return stage_name, rendered[0], rendered[1]


def profile_inputs(recipe, foundation, python, helpers):
    if recipe['schema'] != 1 or recipe['prefix'] != '/usr/local' or recipe['jobs'] != 2:
        raise ValueError('fixed source recipe required')
    if set(recipe['sources']) != {'gpsd', 'ntpsec'}:
        raise ValueError('both pinned sources required')
    gps_options = recipe['sources']['gpsd']['options']
    # Explicit driver arguments preserve test coverage with the time preset.
    if ('timeservice=yes' not in gps_options
            or any(a.split('=')[0] == 'minimal' for a in gps_options)
            or not {'sirf=yes', 'earthmate=yes', 'evermore=yes', 'control_socket=yes'}.issubset(gps_options)
            or len({a.split('=')[0] for a in gps_options}) != len(gps_options)):
        raise ValueError('time-service GPSD and explicit test protocols required')
    if not {'pps-tools', 'bc'}.issubset(recipe['build_roots']):
        raise ValueError('PPS and bc prerequisites required')
    ntp_options = recipe['sources']['ntpsec']['options']
    if ('--refclock=shm' not in ntp_options
            or sum(a.startswith('--refclock=') for a in ntp_options) != 1
            or '--disable-mdns-registration' in ntp_options
            or not {'libavahi-compat-libdnssd-dev', 'avahi-daemon'}.issubset(recipe['build_roots'])):
        raise ValueError('GPSD SHM refclock and mDNS build/runtime prerequisites required')
    inventory = copy.deepcopy(foundation['baseline'])
    for row in foundation['packages']:
        inventory[row['binary_package']] = [row['version'], 'ii ']
    packages = {}
    roots = set(recipe['build_roots']) | {'python3', 'libc6', 'binutils', 'gcc', 'g++', 'make'}
    for name in sorted(roots):
        keys = [k for k in inventory if k.split(':')[0] == name]
        if len(keys) != 1 or inventory[keys[0]][1] != 'ii ':
            raise ValueError('missing or ambiguous prerequisite: ' + name)
        packages[keys[0]] = inventory[keys[0]][0]
    if set(helpers) != {'clockmaker.py', 'pinup.py', 'timeservice.py'}:
        raise ValueError('maintained helpers required')
    profile = {'schema': 1, 'hostname': foundation['hostname'], 'prefix': recipe['prefix'],
               'jobs': recipe['jobs'], 'sources': copy.deepcopy(recipe['sources']),
               'packages': packages, 'helpers': {n:sha(b) for n,b in helpers.items()},
               'python': {'executable': '/usr/bin/python3', 'version': python['version'][:2],
                          'module_directory': python['purelib']}}
    return profile, inventory


def verify_options(data, source, application):
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        root = source['archive_root'] + '/'
        if application == 'gpsd':
            construct = ast.parse(archive.extractfile(root + 'SConstruct').read().decode())
            assignments = {n.targets[0].id:n.value for n in construct.body if isinstance(n, ast.Assign)
                           and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)}
            version = assignments.get('gpsd_version')
            layout = assignments.get('variantdir')
            expected = ast.parse("'gpsd-' + gpsd_version", mode='eval').body
            if (not isinstance(version, ast.Constant) or version.value != source['version']
                    or layout is None or ast.dump(layout) != ast.dump(expected)):
                raise ValueError('pinned GPSD version/build directory layout mismatch')
            text = archive.extractfile(root + 'SConscript').read().decode()
            declared = set()
            script = ast.parse(text)
            constants = {n.targets[0].id: n.value.value for n in script.body
                         if isinstance(n, ast.Assign) and len(n.targets) == 1
                         and isinstance(n.targets[0], ast.Name) and isinstance(n.value, ast.Constant)}
            defaults = {}
            for node in script.body:
                if (isinstance(node, ast.Assign) and isinstance(node.value, (ast.Tuple, ast.List))
                        and any(isinstance(n, ast.Name) and n.id in ('boolopts', 'nonboolopts', 'pathopts')
                                for n in node.targets)):
                    for row in node.value.elts:
                        if isinstance(row, (ast.Tuple, ast.List)) and isinstance(row.elts[0], ast.Constant):
                            declared.add(row.elts[0].value)
                            if any(isinstance(n, ast.Name) and n.id == 'boolopts' for n in node.targets):
                                default = row.elts[1]
                                defaults[row.elts[0].value] = (default.value if isinstance(default, ast.Constant)
                                                             else constants.get(default.id) if isinstance(default, ast.Name) else None)
            if any(a.split('=')[0] not in declared for a in source['options']):
                raise ValueError('GPSD option not declared by pinned source')
            arguments = dict(a.split('=', 1) for a in source['options'])
            if arguments.get('timeservice') == 'yes':
                # Keep upstream defaults unless an explicit option chooses otherwise.
                timerelated = {'gpsd', 'ipv6', 'magic_hat', 'ncurses', 'oscillator'}
                stripped = [n for n, v in defaults.items() if v is True and n not in timerelated and n not in arguments]
                if stripped:
                    raise ValueError('time-service test profile would strip default options: ' + ', '.join(stripped))
        else:
            helper = archive.extractfile(root + 'wafhelpers/bin_test.py').read().decode()
            layout = ast.parse(archive.extractfile(root + 'wscript').read().decode())
            outputs = [n.value for n in layout.body if isinstance(n, ast.Assign)
                       and any(isinstance(x, ast.Name) and x.id == 'out' for x in n.targets)]
            if (len(outputs) != 1 or not isinstance(outputs[0], ast.Constant)
                    or outputs[0].value != 'build' or "'%s/main/tests/pylib'" not in helper):
                raise ValueError('pinned NTPsec isolated binary-test library layout mismatch')
            text = '\n'.join(archive.extractfile(m).read().decode() for m in archive.getmembers()
                             if m.isfile() and m.name.endswith(('wafhelpers/options.py', 'wafhelpers/asciidoc.py')))
            for option in source['options']:
                flag = option.split('=')[0]
                if repr(flag) not in text and '"' + flag + '"' not in text:
                    raise ValueError('NTPsec option not declared by pinned source')


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument('--recipe', type=Path, default=REPO/'ntpsec/configs/source-build-recipe.json')
    parser.add_argument('--foundation', type=Path, required=True)
    parser.add_argument('--foundation-sha256', required=True)
    parser.add_argument('--python-evidence', type=Path, required=True)
    parser.add_argument('--python-evidence-sha256', required=True)
    parser.add_argument('--sources', type=Path, required=True)
    parser.add_argument('--known-hosts', type=Path, required=True)
    parser.add_argument('--operation-id', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    foundation = bound_json(args.foundation, args.foundation_sha256)
    epoch = int(time.time())
    if not foundation['prepared_epoch'] - 300 <= epoch < foundation['expires_epoch']:
        raise ValueError('accepted foundation preparation window expired')
    observed = bound_json(args.python_evidence, args.python_evidence_sha256)
    python = observed['collector_report']['python_environment']
    recipe_data = args.recipe.read_bytes()
    recipe = json.loads(recipe_data)
    helpers = {n:(REPO/'ntpsec/scripts'/n).read_bytes() for n in ('clockmaker.py', 'pinup.py', 'timeservice.py')}
    profile, inventory = profile_inputs(recipe, foundation, python, helpers)
    profile['recipe_sha256'] = sha(recipe_data)
    files = dict(helpers, **{'recipe.json':recipe_data})
    for application, source in profile['sources'].items():
        name = source['archive']
        if Path(name).name != name:
            raise ValueError('one archive filename required')
        data = (args.sources/name).read_bytes()
        if sha(data) != source['sha256']:
            raise ValueError('pinned publisher archive mismatch')
        verify_options(data, source, application)
        files[name] = data
    files['profile.json'] = (json.dumps(profile, sort_keys=True)+'\n').encode()
    known_hosts = args.known_hosts.read_bytes()
    stage_name, stage, launcher = render_transport(
        (REPO/'ntpsec/scripts/source-build-stage.py').read_bytes(),
        (REPO/'ntpsec/scripts/run-source-build.py').read_bytes(), foundation, known_hosts, args.operation_id)
    files['source-build-stage.py'] = stage
    header = '/usr/include/sys/timepps.h'
    expected_header = foundation.get('package_created_inputs', {}).get(header)
    if expected_header is None:
        expected_header = next((r.get('sha256') for r in foundation['inputs'] if r['path'] == header), None)
    if expected_header is None:
        raise ValueError('installed PPS header binding required')
    spec = {'schema':1, 'hostname':foundation['hostname'], 'kernel':foundation['kernel'],
            'operation_id':args.operation_id, 'stage_name':stage_name, 'boot_id':foundation['boot_id'],
            'prepared_epoch':epoch, 'expires_epoch':foundation['expires_epoch'],
            'inventory':inventory, 'foundation_spec_sha256':args.foundation_sha256,
            'python_evidence_sha256':args.python_evidence_sha256,
            'python': {'version':python['version'], 'module_directory':python['purelib'],
                       'extension_suffix':python['extension_suffix']},
            'pps_header_sha256':expected_header, 'members':{n:sha(b) for n,b in files.items()}}
    args.output.mkdir(mode=0o700)  # Never reuse a failed or executed workspace.
    loader = importlib.util.spec_from_file_location('clock', REPO/'ntpsec/scripts/clockmaker.py')
    clock = importlib.util.module_from_spec(loader)
    loader.loader.exec_module(clock)
    for application, source in profile['sources'].items():
        destination = args.output/(application+'-unpack-check')
        destination.mkdir(mode=0o700)
        clock.unpack_source(files[source['archive']], source, destination)
    files.update({'spec.json':(json.dumps(spec, sort_keys=True)+'\n').encode(),
                  'launcher.py':launcher,
                  'known_hosts':known_hosts,
                  'tests.py':(REPO/'ntpsec/tests/test_source_build_stage.py').read_bytes()})
    for name, data in files.items():
        with (args.output/name).open('xb') as stream:
            stream.write(data)
    (args.output/'manifest.json').write_text(json.dumps({n:sha(b) for n,b in files.items()}, sort_keys=True)+'\n')
    (args.output/'provenance.json').write_text(json.dumps({
        'recipe_sha256':sha(recipe_data), 'foundation_spec_sha256':args.foundation_sha256,
        'python_evidence_sha256':args.python_evidence_sha256, 'inventory_records':len(inventory),
        'operation_id':args.operation_id, 'stage_name':stage_name,
        'native_options_declared':True, 'archives_safely_unpacked':True,
        'target_contact':False, 'execution_authorized':False}, indent=2)+'\n')
    print(json.dumps({'output':str(args.output), 'inventory_records':len(inventory), 'target_contact':False}))


if __name__ == '__main__':
    main()
