#!/usr/bin/python3
"""Prepare the 46-package foundation and bounded PPS/bc supplements offline."""
import argparse
import base64
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile
import time

ORIGIN_SHA = '5d93117ed7433099b296325f4229d6efde4e02b7344176030552007cc65767a4'
REPO = Path(__file__).resolve().parents[2]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def candidate_effects(archives, paths):
    found = {}
    for filename in archives:
        raw = subprocess.check_output(['/usr/bin/dpkg-deb', '--fsys-tarfile', str(filename)])
        with tarfile.open(fileobj=io.BytesIO(raw)) as t:
            for m in t.getmembers():
                name = '/' + m.name.removeprefix('./')
                if name in paths:
                    if not m.isfile() or m.uid != 0 or m.gid != 0:
                        raise ValueError('protected candidate file required')
                    found[name] = {'path': name, 'sha256': sha(t.extractfile(m).read()),
                                   'uid': 0, 'gid': 0, 'mode': oct(m.mode)}
    if set(found) != set(paths):
        raise ValueError('declared package effects missing from verified archives')
    return found


def construct(origin, pps, pps_data, repo_files, effects, scope, epoch, inventory=None,
              bc=None, bc_data=None):
    spec = copy.deepcopy(origin)
    row = dict(pps)
    row.pop('archive_file', None)
    row.update(binary_package='pps-tools', file='archives/pps-tools_' + row['version'] + '_arm64.deb')
    if row['architecture'] != 'arm64' or sha(pps_data) != row['sha256'] or len(pps_data) != row['size']:
        raise ValueError('bound PPS archive mismatch')
    if row['version'] != '1.0.2-2+b1':
        raise ValueError('reviewed PPS version required')
    bc_row = None
    if scope in ('foundation', 'bc-supplement'):
        if (bc is None or bc_data is None or bc['package'] != 'bc' or bc['architecture'] != 'arm64'
                or not re.fullmatch(r'[A-Za-z0-9.+:~_-]+', bc['version'])
                or sha(bc_data) != bc['sha256'] or len(bc_data) != bc['size']):
            raise ValueError('bound bc archive required')
        bc_row = {k:bc[k] for k in ('package', 'version', 'architecture', 'sha256', 'size')}
        bc_row.update(binary_package='bc', file='archives/bc_' + bc['version'].replace(':', '%3a') + '_arm64.deb')
    spec.update(scope=scope, prepared_epoch=epoch, expires_epoch=epoch + 86400)
    stages = {'foundation': '/var/lib/ntp-foundation-v6', 'pps-supplement': '/var/lib/ntp-foundation-pps-v3',
              'bc-supplement': '/var/lib/ntp-foundation-bc-v1'}
    if scope not in stages:
        raise ValueError('foundation, PPS supplement or bc supplement only')
    stage = stages[scope]
    spec['stage'] = stage
    data = dict(repo_files)
    expected = b"STAGE = Path('/var/lib/ntp-foundation-v6')"
    if data['worker.py'].count(expected) != 1:
        raise ValueError('canonical stage marker missing')
    data['worker.py'] = data['worker.py'].replace(expected, ('STAGE = Path(' + repr(stage) + ')').encode())
    if scope == 'foundation':
        if len(spec['packages']) != 44 or {'pps-tools', 'bc'} & {r['package'] for r in spec['packages']}:
            raise ValueError('fixed historical foundation required')
        spec['packages'].extend((row, bc_row))
        for path, info in effects.items():
            spec['package_created_inputs'][path] = info['sha256']
    else:
        count = 677 if scope == 'pps-supplement' else 678
        names = {n.split(':')[0] for n in inventory or {}}
        if (inventory is None or len(inventory) != count
                or ('pps-tools' in names if scope == 'pps-supplement' else 'bc' in names or 'pps-tools' not in names)):
            raise ValueError('accepted foundation inventory required for supplement')
        spec['baseline'] = inventory
        spec['packages'] = [row if scope == 'pps-supplement' else bc_row]
        spec['prior_needrestart_sha256'] = sha(repo_files['prior-needrestart.conf'])
        data.pop('prior-needrestart.conf')
        # Expected package effects become protected pre-state, without changing
        # the immutable original specification or its executed artifacts.
        new_path = '/usr/include/sys/timepps.h' if scope == 'pps-supplement' else '/usr/bin/bc'
        additions = {p:r for p,r in effects.items() if p not in (new_path, '/usr/bin/bc')}
        inputs = {r['path']:r for r in spec['inputs']}
        inputs.update(additions)
        # Dpkg inventory/status cleanliness binds the post-foundation database;
        # no original pre-install database hash is reused as current evidence.
        inputs['/var/lib/dpkg/status'].pop('sha256', None)
        spec['inputs'] = list(inputs.values())
        for directory in spec['directories']:
            names = set(spec['directories'][directory])
            names.update(Path(p).name for p in additions if str(Path(p).parent) == directory)
            if directory == '/etc/needrestart/conf.d':
                names.add('zz-ntp-policy.conf')
            spec['directories'][directory] = sorted(names)
        spec['package_created_inputs'] = {new_path: effects[new_path]['sha256']}
    if scope != 'pps-supplement':
        # bc's generated postinst/postrm calls update-menus if present. That
        # helper is outside this transaction; reject it before changing controls.
        for directory in ('/usr/bin', '/usr/sbin', '/bin', '/sbin'):
            spec['inputs'].append({'path': directory + '/update-menus', 'absent': True})
    data.pop('prior-needrestart.conf', None)
    if scope != 'bc-supplement':
        data[row['file']] = pps_data
    if bc_row is not None:
        data[bc_row['file']] = bc_data
    spec['members'] = {name:sha(value) for name,value in data.items()}
    return spec, data


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--scope', choices=('foundation', 'pps-supplement', 'bc-supplement'), required=True)
    parser.add_argument('--bc-manifest', type=Path)
    parser.add_argument('--bc-manifest-sha256')
    args = parser.parse_args()
    base = args.evidence
    original = base / 'foundation-install-v4'
    raw = (original / 'foundation-install.tar').read_bytes()
    if sha(raw) != ORIGIN_SHA:
        raise ValueError('original sealed foundation drift')
    with tarfile.open(fileobj=io.BytesIO(raw)) as t:
        files = {m.name:t.extractfile(m).read() for m in t.getmembers()}
    manifest = json.loads(files['manifest.json'])
    if set(manifest) != set(files) - {'manifest.json'} or any(sha(files[n]) != h for n,h in manifest.items()):
        raise ValueError('original sealed member mismatch')
    origin = json.loads(files['spec.json'])
    plan = json.loads((base/'installation-plan-v1/plan.json').read_text())
    pps = next(r for p in plan['phase_candidates'] for r in p.get('changed_packages',[]) if r['package']=='pps-tools')
    pps_data = Path(pps['archive_file']).read_bytes()
    if sha(pps_data) != pps['sha256']:
        raise ValueError('retained PPS archive drift')
    bc = bc_data = None
    if args.scope != 'pps-supplement':
        if args.bc_manifest is None or args.bc_manifest_sha256 is None:
            raise ValueError('authenticated bc package manifest required')
        raw_bc = args.bc_manifest.read_bytes()
        if sha(raw_bc) != args.bc_manifest_sha256:
            raise ValueError('bc package manifest drift')
        bc = json.loads(raw_bc)
        bc_data = Path(bc['archive_file']).read_bytes()
        if sha(bc_data) != bc['sha256'] or len(bc_data) != bc['size']:
            raise ValueError('retained bc archive drift')
    candidate_paths = set(origin['package_created_inputs']) | {'/etc/dpkg/dpkg.cfg.d/needrestart',
                       '/usr/lib/needrestart/dpkg-status', '/usr/include/sys/timepps.h'}
    archives = [original/r['file'] for r in origin['packages']] + [Path(pps['archive_file'])]
    if bc is not None:
        archives.append(Path(bc['archive_file']))
        candidate_paths.add('/usr/bin/bc')
    effects = candidate_effects(archives, candidate_paths)
    common = {'hook-helper.py': (REPO/'ntpsec/scripts/hook-closure-preflight.py').read_bytes(),
              'answer-helper.py': (REPO/'ntpsec/scripts/read-debconf-answers.py').read_bytes(),
              'listchanges.conf': (REPO/'ntpsec/templates/apt-listchanges-transaction.conf').read_bytes()}
    common.update({'worker.py':(REPO/'ntpsec/scripts/foundation-install.py').read_bytes(),
                   'needrestart.conf':(REPO/'ntpsec/templates/needrestart-pi4.conf').read_bytes(),
                   'prior-needrestart.conf':files['needrestart.conf']})
    current = None
    if args.scope == 'foundation':
        common.update({r['file']:files[r['file']] for r in origin['packages']})
    else:
        result = json.loads((base/'foundation-acceptance-v1/recover-result.json').read_text())
        if result['worker_status'] != 0 or result['report']['state'] != 'foundation_accepted_after_continuation':
            raise ValueError('accepted original completion required')
        ev = result['report']['evidence']['acceptance-continuation-v1-packages.stdout']
        inventory = base64.b64decode(ev['base64'], validate=True)
        if sha(inventory) != ev['sha256']:
            raise ValueError('accepted inventory evidence drift')
        current = {n:[v,s] for n,v,s in (line.split('\t') for line in inventory.decode().splitlines())}
        expected = dict(origin['baseline'])
        expected.update({r['binary_package']:[r['version'],'ii '] for r in origin['packages']})
        if current != expected:
            raise ValueError('accepted original package delta mismatch')
        if args.scope == 'bc-supplement':
            accepted = base / 'foundation-pps-v2'
            result = json.loads((accepted / 'install-result.json').read_text())
            if (result['worker_status'] != 0 or result['transport_exit_status'] != 0
                    or result['report']['state'] != 'foundation_accepted'):
                raise ValueError('accepted PPS completion required')
            ev = result['report']['evidence']
            cleanup = ev['installation-cleanup.json']
            raw_cleanup = base64.b64decode(cleanup['base64'], validate=True)
            if sha(raw_cleanup) != cleanup['sha256'] or not all(json.loads(raw_cleanup).values()):
                raise ValueError('accepted PPS cleanup required')
            captured = ev['installation-packages.stdout']
            raw_inventory = base64.b64decode(captured['base64'], validate=True)
            if sha(raw_inventory) != captured['sha256']:
                raise ValueError('accepted PPS inventory drift')
            current = {n:[v,s] for n,v,s in (l.split('\t') for l in raw_inventory.decode().splitlines())}
            expected[pps['package']] = [pps['version'], 'ii ']
            if current != expected:
                raise ValueError('accepted PPS package delta mismatch')
            common['prior-needrestart.conf'] = (accepted/'needrestart.conf').read_bytes()
    spec,data = construct(origin,pps,pps_data,common,effects,args.scope,int(time.time()),current,bc,bc_data)
    args.output.mkdir(mode=0o700)  # Never overwrite a prepared or executed candidate.
    for name,value in data.items():
        path=args.output/name
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(value)
    (args.output/'spec.json').write_text(json.dumps(spec,sort_keys=True)+'\n')
    for name in ('known_hosts','native-alcapt.py'):
        (args.output/name).write_bytes(files[name])
    (args.output/'launcher.py').write_bytes(files['launcher.py'])
    (args.output/'provenance.json').write_text(json.dumps({'origin_bundle_sha256':ORIGIN_SHA,'scope':args.scope,
         'package_count':len(spec['packages']),'pps_archive_sha256':pps['sha256'],
         'bc_archive_sha256':bc['sha256'] if bc else None,'package_effects':effects,
         'bc_manifest_sha256':args.bc_manifest_sha256,
         'preparation_script_sha256':sha(Path(__file__).read_bytes()),
         'target_contact':False},sort_keys=True,indent=2)+'\n')
    names = [*data, 'spec.json', 'known_hosts', 'native-alcapt.py', 'launcher.py', 'provenance.json']
    (args.output/'manifest.json').write_text(json.dumps(
        {n:sha((args.output/n).read_bytes()) for n in names}, sort_keys=True)+'\n')
    print(json.dumps({'output':str(args.output),'scope':args.scope,'packages':len(spec['packages'])}))


if __name__=='__main__':main()
