#!/usr/bin/python3
"""Seal/check/execute an exact pre-reboot maintenance transaction."""
import argparse
import base64
import importlib.util
import io
import json
import os
import re
from pathlib import Path
import tarfile
import time

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {'runner.py': Path(__file__).resolve(), 'update.py': ROOT/'scripts/maintenance-update.py',
           'recovery.py': ROOT/'scripts/maintenance-recovery.py',
           'effects.py': ROOT/'scripts/inspect-maintenance-effects.py',
           'snapshot.py': ROOT/'scripts/maintenance-snapshot.py',
           'helper.py': ROOT/'scripts/run-production-inspection.py',
           'common.py': ROOT/'scripts/review-maintenance-snapshot.py',
           'command.py': ROOT/'scripts/foundation-install.py',
           'tests.py': ROOT/'tests/test_maintenance_update.py',
           'procedure.md': ROOT/'docs/MAINTENANCE-UPDATE-EXECUTION.md'}
loader = importlib.util.spec_from_file_location('maintenance_common', SOURCES['common.py'])
c = importlib.util.module_from_spec(loader); loader.loader.exec_module(c)


def unpack(raw):
    files = {}
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        for item in archive:
            c.require(item.isfile() and item.name not in files and '..' not in Path(item.name).parts
                      and not item.name.startswith('/') and item.size <= 32*1024**2, 'archive member')
            files[item.name] = archive.extractfile(item).read()
    return files


def check(directory, digest, live=False):
    directory = c.private_dir(directory)
    raw = c.read(directory/'update.tar', 128*1024**2)
    c.require(c.sha(raw) == digest, 'archive SHA-256')
    files = unpack(raw)
    spec = json.loads(files['spec.json'])
    c.require(spec['purpose'] == 'maintenance-update-pre-reboot' and spec['directory'] == str(directory)
              and spec['operation_id'] == directory.name, 'operation scope')
    c.require(spec['members'] == {n:c.sha(v) for n,v in files.items() if n != 'spec.json'}, 'member hashes')
    for n,p in SOURCES.items():
        c.require(files[n] == p.read_bytes(), 'source drift: ' + n)
    for n,v in files.items():
        c.require(c.read(directory/n, 32*1024**2) == v, 'frozen file drift: ' + n)
    c.require(re.fullmatch(r'base-os-update-\d{8}-v\d+', spec['operation_id']), 'operation identifier')
    c.require(len(spec['packages']) == 22 and len({p['package'] for p in spec['packages']}) == 22
              and not spec['reboot_authorized'], 'closed package/boot boundary')
    for p in spec['packages']:
        c.require(re.fullmatch(r'[a-z0-9][a-z0-9+.-]*', p['package']) and
                  p['file'] == 'archives/' + p['package'] + '.deb' and p['architecture'] in ('arm64','all'),
                  'package path/architecture')
    required = set(SOURCES) | {'spec.json','baseline.json','baseline.rules','candidate.rules','known_hosts',
                              'qualification.json','review.md','provenance.json'} | {p['file'] for p in spec['packages']}
    c.require(set(files) == required, 'closed update archive')
    baseline = json.loads(files['baseline.json'])
    worker = c.module('update_guard', files['update.py'])
    worker.r = c.module('recovery_guard', files['recovery.py'])
    worker.validate_services(baseline['before']['services'])
    worker.validate_services(baseline['after']['services'])
    expected_paths = set(baseline['boot_artifacts']) | {'/boot/firmware/config.txt','/boot/firmware/cmdline.txt',
        '/var/lib/dpkg/status','/var/lib/apt/extended_states','/usr/lib/udev/rules.d/90-alsa-restore.rules'}
    c.require(set(spec['backup']) == expected_paths, 'closed backup paths')
    if live:
        c.require(spec['prepared_epoch'] - 300 <= time.time() < spec['expires_epoch'] - 3600, 'execution window')
    return spec, files


def payload(spec, files, mode, acknowledgement=None):
    source = 'import types,json,signal,base64\nsignal.signal(signal.SIGHUP,signal.SIG_IGN)\n'
    for name,member in [('h','helper.py'),('m','snapshot.py'),('w','effects.py'),('r','recovery.py'),('f','command.py'),('u','update.py')]:
        source += f'{name}=types.ModuleType({name!r});{name}.__file__="/sealed/{member}"\nexec(compile({files[member]!r},"{member}","exec"),{name}.__dict__)\n'
    source += 'm.h=h;w.m=m;u.m=m;u.w=w;u.r=r;u.f=f\n'
    baseline = json.loads(files['baseline.json'])
    if mode == 'backup':
        source += 'result=u.export_backup('+repr(spec)+','+repr(baseline)+')\n'
    else:
        selected = {n:files[n] for n in ['baseline.rules','candidate.rules',*[p['file'] for p in spec['packages']]]}
        encoded_selected = {n:base64.b64encode(raw).decode() for n,raw in selected.items()}
        source += 'selected={n:base64.b64decode(v) for n,v in '+repr(encoded_selected)+'.items()}\n'
        source += 'result=u.install('+repr(spec)+','+repr(baseline)+',selected,'+repr(acknowledgement)+')\n'
    source += 'print(json.dumps(result,sort_keys=True),flush=True)\n'
    source += 'raise SystemExit(1 if result.get("held") else 0)\n'
    return ('exec('+repr(source)+')\n').encode()


def execute(directory, digest, attendance):
    spec, files = check(directory, digest, True)
    c.require(c.authentication(spec['authentication']['identity_file']) == spec['authentication'], 'authentication drift')
    operator = json.loads(c.read(attendance))
    required = ('attending_kvm', 'peer_and_antenna_continuity', 'exclusive_recovery_card', 'no_other_package_or_reset_actions',
                'maintenance_window_90_minutes', 'pre_reboot_hold_accepted')
    c.require(operator.get('archive_sha256') == digest and all(operator.get(k) is True for k in required)
              and 0 <= time.time()-operator.get('confirmed_epoch',0) <= 1800, 'fresh operator confirmation')
    c.create(directory/'execution.json', {'sha256':digest,'epoch':time.time(),'operator':operator})
    result = {'package_stage_complete':False,'production_accepted':False,'no_retry':True}
    h = c.module('helper', files['helper.py'])
    recovery = c.module('recovery', files['recovery.py'])
    try:
        row = h.bounded(c.ssh(directory,spec),timeout=420,limit=192*1024**2,
                        payload=payload(spec,files,'backup'),env=c.ENV)
        c.create(directory/'backup-transport.json',row)
        try:
            capture = json.loads(row.get('stdout', ''))
        except ValueError:
            capture = {}
        c.create(directory/'backup-report.json', {k:v for k,v in capture.items() if k != 'backup_base64'})
        c.require(row.get('returncode') == 0 and not row.get('error'), 'backup transport incomplete')
        c.require(capture.get('operation_id') == spec['operation_id'] and capture.get('backup_complete') is True,
                  'backup operation incomplete')
        raw = base64.b64decode(capture.pop('backup_base64'),validate=True)
        c.require(c.sha(raw) == capture['backup_sha256'], 'backup transfer SHA-256')
        recovery.verify_backup(raw,spec['backup'])
        c.create(directory/'recovery.tar.gz',raw)
        recovery.verify_backup(c.read(directory/'recovery.tar.gz',256*1024**2),spec['backup'])
        c.create(directory/'backup-capture.json',capture)
        ack = {'operation_id':spec['operation_id'],'backup_sha256':c.sha(raw),'offnode_verified':True}
        c.create(directory/'offnode-ack.json',ack)
        row = h.bounded(c.ssh(directory,spec),timeout=1800,limit=16*1024**2,
                        payload=payload(spec,files,'install',ack),env=c.ENV)
        c.create(directory/'install-transport.json',row)
        try:
            report = json.loads(row.get('stdout',''));c.create(directory/'install-report.json',report)
        except ValueError:
            report = {}
        c.require(row.get('returncode') == 0 and not row.get('error'), 'install transport uncertain; never retry')
        c.require(report.get('operation_id') == spec['operation_id'] and report.get('package_stage_complete') is True
                  and report.get('evidence_export_complete') is True,
                  'package stage held; inspect retained report')
        result.update(package_stage_complete=True,phase='pre-reboot-held',controls_retained=True,
                      report_sha256=c.sha(c.read(directory/'install-report.json')))
    except (Exception,KeyboardInterrupt) as error:
        result.update(held=True,error=str(error))
    c.create(directory/'result.json',result)
    return result


def seal(directory, inputs):
    """Inputs are prepared locally from accepted outcomes and authenticated payloads."""
    c.require(not directory.exists(), 'existing operation')
    inputs = c.private_dir(inputs)
    spec = json.loads(c.read(inputs/'spec.json'))
    c.require(spec['operation_id'] == directory.name and spec['directory'] == str(directory), 'destination binding')
    proof = json.loads(c.read(inputs/'qualification.json'))
    files = {n:p.read_bytes() for n,p in SOURCES.items()}
    worker = c.module('update_guard', files['update.py'])
    worker.r = c.module('recovery_guard', files['recovery.py'])
    baseline = json.loads(c.read(inputs/'baseline.json'))
    for side in ('before', 'after'):
        worker.validate_services(baseline[side]['services'])
    c.require(proof['sources'] == {n:c.sha(v) for n,v in files.items()} and proof['tests_exit'] == 0
              and proof['native_containment_passed'] and proof['retained_native_solver_passed'], 'qualification binding')
    for name in ['baseline.json','baseline.rules','candidate.rules','known_hosts','qualification.json','review.md',
                 'provenance.json',*[p['file'] for p in spec['packages']]]:
        files[name] = c.read(inputs/name,32*1024**2)
    c.require(all(c.sha(files[p['file']]) == p['payload_sha256'] and len(files[p['file']]) == p['size']
                  for p in spec['packages']), 'payload binding')
    spec['members'] = {n:c.sha(v) for n,v in files.items()}
    files['spec.json'] = c.encoded(spec)
    directory.mkdir(mode=0o700)
    (directory/'archives').mkdir(mode=0o700)
    for n,v in files.items():
        c.create(directory/n,v)
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream,mode='w',format=tarfile.USTAR_FORMAT) as archive:
        for n,v in sorted(files.items()):
            item = tarfile.TarInfo(n);item.size=len(v);item.mode=0o600;archive.addfile(item,io.BytesIO(v))
    c.create(directory/'update.tar',stream.getvalue());digest=c.sha(stream.getvalue())
    check(directory,digest)
    result={'sha256':digest,'execution_ready':True,'execution_approved':False,'target_contact':False,
            'reboot_authorized':False,'expires_epoch':spec['expires_epoch']}
    c.create(directory/'sealing.json',result)
    return result


def main():
    os.umask(0o077)
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='action',required=True)
    for action in ('seal','check','execute'):
        p=sub.add_parser(action);p.add_argument('--directory',type=Path,required=True)
        if action=='seal':p.add_argument('--inputs',type=Path,required=True)
        else:p.add_argument('--sha256',required=True)
        if action=='execute':p.add_argument('--attendance',type=Path,required=True)
    a=parser.parse_args()
    if a.action=='seal':result=seal(a.directory.absolute(),a.inputs.absolute())
    elif a.action=='check':check(a.directory,a.sha256);result={'integrity':True,'target_contact':False}
    else:result=execute(a.directory,a.sha256,a.attendance)
    print(json.dumps(result))
    if result.get('held'):raise SystemExit(1)

if __name__=='__main__':main()
