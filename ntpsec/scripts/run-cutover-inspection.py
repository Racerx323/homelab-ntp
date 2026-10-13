#!/usr/bin/python3
"""Seal offline, then retrieve retained cutover diagnostics with separate approval."""
import argparse
import base64
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import resource
import signal
import socket
import stat
import subprocess
import sys
import tarfile
import time

ROOT=Path(__file__).resolve().parents[1]
PATHS={'stage.py':'scripts/run-cutover-inspection.py','controller.py':'scripts/run-service-cutover.py',
       'transport.py':'scripts/run-foundation-preflight.py','tests.py':'tests/test_cutover_inspection.py',
       'architecture.md':'docs/ntp-architecture-deployment-plan-v1.0.md','operations.md':'docs/OPERATIONS.md','history.md':'HISTORY.md'}
EXTRA={'helper.py','source-spec.json','source-cleanup.json','source-receipt.json','known_hosts','launch.sh'}
ENV={'PATH':'/usr/sbin:/usr/bin:/sbin:/bin','LC_ALL':'C','PYTHONDONTWRITEBYTECODE':'1'}
LIMIT=8*1024**2
FILE_LIMIT=8*1024**2
STATS_LIMIT=2*1024**2
JOURNAL_LINES=2000


def encoded(value):return (json.dumps(value,sort_keys=True)+'\n').encode()
def sha(raw):return hashlib.sha256(raw).hexdigest()


def journal_boot_id(value):
    """Keep canonical target UUIDs; journalctl boot descriptors use compact hex."""
    if not isinstance(value,str) or not re.fullmatch('[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}',value):
        raise ValueError('canonical boot UUID required')
    return value.replace('-','')


def load(path):
    spec=importlib.util.spec_from_file_location('diagnostic_'+path.stem.replace('-','_'),path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def launcher(stage):
    return ('#!/bin/bash\nset -Eeuo pipefail\ncd /\nexec /usr/bin/python3 -I -B '+stage+'/stage.py worker\n').encode()


def validate(spec,files):
    journal_boot_id(spec['boot_id'])
    old=json.loads(files['source-spec.json']);cleanup=json.loads(files['source-cleanup.json']);receipt=json.loads(files['source-receipt.json'])
    state=cleanup['result'];prior=dict(state);prior.pop('transient_cleanup',None)
    if any(type(spec[k]) is not int or spec[k]<=0 for k in ('journal_since','journal_until','prepared_epoch','expires_epoch')):
        raise ValueError('positive integer time bounds required')
    if not re.fullmatch('[0-9a-f]{64}',spec['source_bundle_sha256']):raise ValueError('source archive digest required')
    if (set(files)!=set(PATHS)|EXTRA|{'spec.json','manifest.json','review.md'} or spec['schema']!=1
            or not re.fullmatch('[a-z][a-z0-9-]{0,47}',spec['operation_id'])
            or spec['stage']!='/var/lib/ntp-inspect-'+spec['operation_id']
            or spec['source_stage']!=old['stage'] or not re.fullmatch('/var/lib/ntp-acquire-[a-z][a-z0-9-]{0,47}',old['stage'])
            or any(spec[k]!=old[k] for k in ('hostname','kernel','boot_id','endpoints','old_ipv4'))
            or cleanup['spec_sha256']!=sha(files['source-spec.json']) or state['phase']!='recovered'
            or state.get('transient_cleanup') is not True or receipt['state']!='recovered'
            or receipt['spec_sha256']!=sha(files['source-spec.json']) or receipt['state_sha256']!=sha(encoded(prior))
            or receipt['bundle_sha256']!=spec['source_bundle_sha256']
            or spec['journal_since']!=state['apply_epoch'] or spec['journal_until']!=state['recovered_epoch']+1
            or not 0<spec['journal_until']-spec['journal_since']<=3600
            or not 0<spec['expires_epoch']-spec['prepared_epoch']<=86400
            or files['launch.sh']!=launcher(spec['stage'])
            or spec['members']!={n:sha(files[n]) for n in set(PATHS)|EXTRA}):
        raise ValueError('closed diagnostic/recovered target/input binding required')


def source_lock(h,spec,files):
    root=Path(spec['source_stage']);h.ancestors(root)
    fd=os.open(root/'.lock',os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or (info.st_uid,info.st_gid,info.st_nlink,stat.S_IMODE(info.st_mode))!=(0,0,1,0o600):raise ValueError('protected existing source lock required')
        fcntl.flock(fd,fcntl.LOCK_SH|fcntl.LOCK_NB)
        if stat.S_IMODE(root.stat().st_mode)!=0o700 or h.read(root/'spec.json')!=files['source-spec.json']:
            raise ValueError('original protected specification drift')
        if json.loads(h.read(root/'state.json'))!=json.loads(files['source-cleanup.json'])['result']:
            raise ValueError('original recovered/cleaned state drift')
        old=json.loads(files['source-spec.json'])
        for name,digest in old['members'].items():
            if not re.fullmatch('[a-z][a-z0-9._-]+',name) or sha(h.read(root/name,limit=32*1024**2))!=digest:raise ValueError('original execution input drift')
        return fd
    except BaseException:
        os.close(fd);raise


def metadata(path):
    try:info=path.lstat()
    except FileNotFoundError:return {'exists':False}
    result={'exists':True,'mode':stat.S_IMODE(info.st_mode),'uid':info.st_uid,'gid':info.st_gid}
    if stat.S_ISLNK(info.st_mode):result.update(type='symlink',target=os.readlink(path))
    elif stat.S_ISREG(info.st_mode):result['type']='regular'
    else:result['type']='other'
    return result


def command(h,root,name,argv):
    def bound():resource.setrlimit(resource.RLIMIT_FSIZE,(2*1024**2,2*1024**2))
    with (root/(name+'.stdout')).open('xb') as out,(root/(name+'.stderr')).open('xb') as err:
        try:
            p=subprocess.run(argv,stdout=out,stderr=err,env=ENV,cwd='/',timeout=20,check=False,preexec_fn=bound)
            status=p.returncode
        except subprocess.TimeoutExpired:status='timeout'
    h.create(root/(name+'.json'),encoded({'argv':argv,'status':status}))
    if status!=0:raise ValueError('bounded diagnostic command failed: '+name)
    return h.read(root/(name+'.stdout'),limit=2*1024**2)


def retained_journals(commands,spec):
    journals=[row for row in commands if row['argv'][:1]==['/usr/bin/journalctl']]
    legacy=['/usr/bin/journalctl','--quiet','--no-pager','--output=short-unix','--since=@'+str(spec['journal_since']),
            '--unit=timeservice.service','--unit=avahi-daemon.service','--priority=0..3']
    current=['/usr/bin/journalctl','--quiet','--no-pager','--output=json','--boot='+journal_boot_id(spec['boot_id']),
             '--unit=timeservice.service','--unit=avahi-daemon.service','--priority=0..3']
    if len(commands)>512 or not 1<=len(journals)<=41:raise ValueError('bounded retained journal probes required')
    if any(row['argv'] not in (legacy,current) for row in journals):raise ValueError('retained journal scope mismatch')
    return journals


def runtime_data(h,source):
    directory=source/'runtime-data'
    try:info=directory.lstat()
    except FileNotFoundError:return {'exists':False,'files':{}}
    h.ancestors(directory)
    if not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode)!=0o700:raise ValueError('protected runtime evidence directory required')
    paths=sorted(directory.iterdir());records={};total=0
    if len(paths)>12:raise ValueError('runtime evidence file-count bound')
    for path in paths:
        if not re.fullmatch(r'(?:ntpstats-(?:loopstats|peerstats|clockstats)(?:\.\d{8})?|drift-ntp\.drift(?:\.TEMP)?|ntpsec-leap-seconds\.tmp)',path.name):
            raise ValueError('unexpected runtime evidence filename')
        info=path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1:raise ValueError('regular single-link runtime evidence required')
        raw=h.read(path,limit=STATS_LIMIT);total+=len(raw)
        if total>STATS_LIMIT:raise ValueError('runtime evidence total bound')
        records[path.name]={'sha256':sha(raw),'base64':base64.b64encode(raw).decode(),'bytes':len(raw)}
    return {'exists':True,'files':records}


def collect(h,spec,files):
    root=Path(spec['stage']);source=Path(spec['source_stage']);fd=source_lock(h,spec,files)
    try:
        # Read saved evidence without appending to or rewriting the executed stage.
        saved={n:h.read(source/n,limit=FILE_LIMIT) for n in ('before.json','state.json','commands.jsonl')}
        before=json.loads(saved['before.json'])
        if before['files']['/etc/ntp.conf'] is not None:raise ValueError('expected pre-cutover ntp.conf absence not established')
        commands=[json.loads(line) for line in saved['commands.jsonl'].splitlines()]
        journals=retained_journals(commands,spec)
        for n,raw in saved.items():h.create(root/('source-'+n),raw)
        h.create(root/'retained-journal.json',encoded(journals))
        stats=runtime_data(h,source);h.create(root/'runtime-data.json',encoded(stats))
        raw=command(h,root,'journal',['/usr/bin/journalctl','--quiet','--no-pager','--output=json','--lines='+str(JOURNAL_LINES),
                  '--boot='+journal_boot_id(spec['boot_id']),'--since=@'+str(spec['journal_since']),'--until=@'+str(spec['journal_until']),
                  '--unit=timeservice.service','--unit=avahi-daemon.service'])
        records=[json.loads(line) for line in raw.splitlines()]
        if len(records)>=JOURNAL_LINES:raise ValueError('journal line limit reached; completeness unproven')
        command(h,root,'services',['/usr/bin/systemctl','show','--no-pager',
                  '--property=Id,LoadState,ActiveState,SubState,UnitFileState,FragmentPath,DropInPaths',
                  'timeservice.service','systemd-timesyncd.service','avahi-daemon.service','ntpleapfetch.timer'])
        info={'ntp_conf':metadata(Path('/etc/ntp.conf')),'pre_cutover_ntp_conf_absent':True,'journal_records':len(records),
              'retained_journal_probes':len(journals),'runtime_files':len(stats['files']),
              'packet_counters_retrieved':False,'packet_path_established':False}
        h.create(root/'current-metadata.json',encoded(info))
        for name,raw in saved.items():
            if h.read(source/name,limit=LIMIT)!=raw:raise ValueError('original evidence changed during capture')
        if runtime_data(h,source)!=stats:raise ValueError('runtime evidence changed during capture')
        return info
    finally:os.close(fd)


CAPTURE_FILES=('source-before.json','source-state.json','source-commands.jsonl','retained-journal.json','runtime-data.json',
               'journal.json','journal.stdout','journal.stderr','services.json','services.stdout','services.stderr','current-metadata.json')


def capture(h,spec,files):
    root=Path(spec['stage'])
    try:
        summary=collect(h,spec,files);terminal={'phase':'captured','summary':summary,'source_preserved':True}
    except BaseException as error:
        terminal={'phase':'held','error':str(error)[:500],'source_preserved':None}
    evidence={};total=0
    for name in CAPTURE_FILES:
        if (root/name).exists():
            data=h.read(root/name,limit=FILE_LIMIT);total+=len(data)
            if total>LIMIT:
                terminal.update(phase='held',error='aggregate retrieval limit exceeded; staged evidence retained');break
            evidence[name]={'sha256':sha(data),'base64':base64.b64encode(data).decode()}
    terminal['evidence']=evidence;h.create(root/'report.json',encoded(terminal))
    return terminal


def protected(spec,files):
    root=Path(spec['stage'])
    if os.geteuid()!=0 or socket.gethostname()!=spec['hostname'] or os.uname().release!=spec['kernel'] or Path('/proc/sys/kernel/random/boot_id').read_text().strip()!=spec['boot_id']:
        raise ValueError('approved target/kernel/boot identity required')
    ns={'__name__':'sealed_helper'};exec(compile(files['helper.py'],'sealed-helper','exec'),ns)
    import types
    h=types.SimpleNamespace(**ns);h.ancestors(root)
    if stat.S_IMODE(root.stat().st_mode)!=0o700 or h.read(root/'spec.json')!=encoded(spec):raise ValueError('protected diagnostic stage mismatch')
    for name,digest in spec['members'].items():
        if sha(h.read(root/name,limit=32*1024**2))!=digest:raise ValueError('sealed diagnostic input drift')
    return h


def entry(spec,files,mode,proofs=None):
    root=Path(spec['stage']);os.umask(0o077)
    if mode=='start':
        if (os.geteuid()!=0 or os.environ.get('SUDO_USER')!='ama' or socket.gethostname()!=spec['hostname']
                or os.uname().release!=spec['kernel'] or Path('/proc/sys/kernel/random/boot_id').read_text().strip()!=spec['boot_id']
                or not spec['prepared_epoch']-300<=time.time()<spec['expires_epoch']):raise ValueError('approved caller/target/window required')
        for p in (root.parent,*root.parent.parents):
            st=p.lstat()
            if not stat.S_ISDIR(st.st_mode) or st.st_uid or st.st_gid or st.st_mode&0o022:raise ValueError('protected stage parent required')
        root.mkdir(mode=0o700)
        for n,raw in {**files,'spec.json':encoded(spec)}.items():
            with (root/n).open('xb') as f:f.write(raw)
    h=protected(spec,files)
    if mode=='start':
        # One bounded local worker process group; no system service changes or live observation.
        with (root/'worker.stdout').open('xb') as out,(root/'worker.stderr').open('xb') as err:
            p=subprocess.Popen(['/bin/bash',str(root/'launch.sh')],cwd='/',env=ENV,stdout=out,stderr=err,start_new_session=True)
            try:status=p.wait(timeout=90)
            except subprocess.TimeoutExpired:
                os.killpg(p.pid,signal.SIGKILL);p.wait(timeout=5);status='timeout'
        h.create(root/'worker-status.json',encoded({'status':status}))
        if not (root/'report.json').exists():h.create(root/'report.json',encoded({'phase':'held','error':'worker failed or timed out','evidence':{},'source_preserved':None}))
    if mode in ('start','readback'):return json.loads(h.read(root/'report.json',limit=32*1024**2))
    if mode=='cleanup':
        raw=h.read(root/'report.json',limit=32*1024**2)
        if proofs!={'report_sha256':sha(raw)}:raise ValueError('matching terminal readback receipt required')
        result={'phase':'cleaned','evidence_preserved':True,'source_unchanged':json.loads(raw)['source_preserved'],'report_sha256':sha(raw)}
        # No service, timer, configuration or original evidence is removed.
        h.create(root/'cleanup.json',encoded(result));return result
    raise ValueError('closed diagnostic mode required')


def prepare(bundle,checksum):
    c=load(ROOT/'scripts/run-service-cutover.py');t=load(ROOT/'scripts/run-foundation-preflight.py')
    raw=t.private_file(bundle,16*1024**2)
    if sha(raw)!=checksum:raise ValueError('approved diagnostic archive required')
    files=c.unpack(raw);spec=json.loads(files['spec.json']);validate(spec,files)
    if any(files[n]!=(ROOT/p).read_bytes() for n,p in PATHS.items()) or t.private_file(bundle.parent/'known_hosts',4096)!=files['known_hosts']:
        raise ValueError('reviewed controller/input drift; reseal required')
    for mode in ('start','readback','cleanup'):compile(c.payload(spec,files,mode),'sealed-diagnostic-payload','exec')
    return spec,files


def review(spec):
    return f'''# Retained NTS/PPS cutover diagnostics: {spec['operation_id']}

Target **{spec['hostname']}**, boot `{spec['boot_id']}`. Expires {datetime.fromtimestamp(spec['expires_epoch'],timezone.utc).isoformat()}.
Source: recovered and cleaned cutover `{spec['source_bundle_sha256']}`.
One capture into root-owned 0700 `{spec['stage']}` with 0600 evidence.
Verify immutable source specification/members and exact recovered/cleaned state;
acquire the existing source lock read-only. Preserve the source stage and backups.

Copy bounded source before-state, terminal state and command journal (8 MiB per
source file); extract 1..41 saved journal-health commands and stdout/stderr/status.
Recognize only the exact legacy time-window or current compact-boot command profiles.
Copy retained runtime-data: loopstats, peerstats, clockstats, drift and leap temporary
files under closed names, at most 12 regular single-link files and 2 MiB combined.
Record absent/empty statistics explicitly; do not claim they existed or were complete.
Retain bytes and hashes, and compare file membership/content again before closure.
Retrieval is capped at 8 MiB raw evidence; exceeding it holds acceptance and retains
the staged files. Run one retrospective
journalctl query for timeservice/Avahi in boot {spec['boot_id']}, from epoch
{spec['journal_since']} through {spec['journal_until']}, at most 1999 complete records
and 2 MiB,
using the compact boot filter `{journal_boot_id(spec['boot_id'])}` while retaining
the canonical UUID for target identity checks.
A 2000-record response is incomplete and holds acceptance. Also inspect
metadata for /etc/ntp.conf without following links or reading unexpected contents,
and fixed timeservice/bootstrap/Avahi/leap-timer unit states. Compare original saved
files again after capture. No service/configuration change, daemon start, clock
change, NTS retry, upstream access, receiver/device I/O or reboot.

Purpose: reconstruct startup selection/frequency discipline and any logged NTS
response/rejection information before a new trial. Earlier localhost probes did
not retain NTS packet counters; stopped-daemon counters cannot be recreated here.
No packet capture, network probe, controller access or service restart is covered.
Missing historical records remain gaps; this capture alone does not establish the
UDP packet path, loss location, calibration or steady-state PPS accuracy.

The staged /bin/bash launcher has a 90-second process-group lifetime; commands
have 20-second and 2-MiB output bounds. One start only; do not repeat after transport
loss. Up to three numbered conditional readbacks through both pinned-key management
endpoints establish matching terminal evidence. Capture acceptance means diagnostic
retrieval, not restored-state or time-service acceptance. Current configuration facts
remain observations. A terminal held capture may be closed diagnostically without
accepting its findings. No configuration rollback is needed for this read-only scope.
Cleanup records closure while retaining all staged inputs, output and source evidence.
No systemd unit/timer or original file is created, changed or deleted by cleanup.

Execute only after separate approval of the archive SHA-256:
`python3 -I -B ntpsec/scripts/run-cutover-inspection.py execute --bundle <archive> --sha256 <approved-hash> --mode start`
Then `--mode readback --attempt 1` and `--mode cleanup` with the same archive/hash.
'''


def seal(args):
    c=load(ROOT/'scripts/run-service-cutover.py');t=load(ROOT/'scripts/run-foundation-preflight.py')
    raw=t.private_file(args.source_dir/'service-cutover.tar',64*1024**2)
    if sha(raw)!=args.source_sha256:raise ValueError('exact executed cutover archive required')
    source=c.unpack(raw);old=json.loads(source['spec.json']);c.validate(old,source)
    cleanup=t.private_file(args.source_dir/'cleanup-0-result.json');receipt=t.private_file(args.source_dir/'terminal-receipt.json')
    results={}
    for index,endpoint in enumerate(old['endpoints']):
        response=json.loads(t.private_file(args.source_dir/('readback-1-'+str(index)+'-result.json')))
        submitted=json.loads(t.private_file(args.source_dir/('readback-1-'+str(index)+'-submission.json')))
        expected=t.transport(args.source_dir,endpoint);expected[3]='240s'
        expected[expected.index('ama@'+endpoint):expected.index('ama@'+endpoint)]=['-o','HostKeyAlias='+old['old_ipv4']]
        if (submitted['argv']!=expected or submitted['bundle_sha256']!=args.source_sha256
                or submitted['payload_sha256']!=sha(c.payload(old,source,'readback'))):raise ValueError('recovery endpoint/submission binding')
        if response['spec_sha256']!=sha(source['spec.json']):raise ValueError('recovery readback binding')
        results[endpoint]=response['result']
    if c.terminal_receipt(old,args.source_sha256,results)!=json.loads(receipt):raise ValueError('matching recovered readbacks required')
    ref=c.unpack(source['reference.tar']);runtime=c.unpack(ref['runtime.tar'])
    files={n:(ROOT/p).read_bytes() for n,p in PATHS.items()}
    operation_stage='/var/lib/ntp-inspect-'+args.operation_id
    files.update({'helper.py':runtime['foundation-install.py'],'source-spec.json':source['spec.json'],
                  'source-cleanup.json':cleanup,'source-receipt.json':receipt,'known_hosts':source['known_hosts'],'launch.sh':launcher(operation_stage)})
    now=int(time.time());state=json.loads(cleanup)['result']
    spec={k:old[k] for k in ('hostname','kernel','boot_id','endpoints','old_ipv4')}
    spec.update(schema=1,operation_id=args.operation_id,stage=operation_stage,source_stage=old['stage'],source_bundle_sha256=args.source_sha256,
                prepared_epoch=now,expires_epoch=now+86400,journal_since=state['apply_epoch'],journal_until=state['recovered_epoch']+1,
                members={n:sha(v) for n,v in files.items()})
    files['spec.json']=encoded(spec);files['review.md']=review(spec).encode();files['manifest.json']=encoded({n:sha(v) for n,v in files.items()})
    validate(spec,files);os.umask(0o077);args.output.mkdir(mode=0o700)
    for name in ('spec.json','known_hosts','review.md'):(args.output/name).write_bytes(files[name])
    bundle=args.output/'cutover-inspection.tar'
    with tarfile.open(bundle,'w',format=tarfile.USTAR_FORMAT) as archive:
        for name,raw in sorted(files.items()):
            item=tarfile.TarInfo(name);item.mode=0o600;item.size=len(raw);item.mtime=now;archive.addfile(item,io.BytesIO(raw))
    digest=sha(bundle.read_bytes());prepare(bundle,digest)
    result={'bundle':str(bundle),'sha256':digest,'target':spec['hostname'],'expires_epoch':spec['expires_epoch'],'target_contact':False,'execution_authorized':False}
    t.write_new(args.output/'sealing.json',result);return result


def terminal_receipt(spec,files,checksum,results):
    if set(results)!=set(spec['endpoints']) or len({sha(encoded(v)) for v in results.values()})!=1:raise ValueError('matching dual-endpoint diagnostic evidence required')
    report=next(iter(results.values()))
    if report['phase'] not in ('captured','held'):raise ValueError('terminal diagnostic capture required')
    for row in report['evidence'].values():
        if sha(base64.b64decode(row['base64'],validate=True))!=row['sha256']:raise ValueError('evidence digest mismatch')
    if report['phase']=='captured' and (set(report['evidence'])!=set(CAPTURE_FILES) or report['source_preserved'] is not True):raise ValueError('complete preserved capture required')
    return {'state':'diagnostics_captured' if report['phase']=='captured' else 'diagnostics_held',
            'bundle_sha256':checksum,'spec_sha256':sha(files['spec.json']),'report_sha256':sha(encoded(report)),'time_service_accepted':False}


def execute(args):
    os.umask(0o077);c=load(ROOT/'scripts/run-service-cutover.py');t=load(ROOT/'scripts/run-foundation-preflight.py')
    bundle=args.bundle.absolute();spec,files=prepare(bundle,args.sha256);directory=bundle.parent
    proofs=None
    if args.mode=='start':
        if not spec['prepared_epoch']-300<=time.time()<spec['expires_epoch']:raise ValueError('diagnostic execution window expired')
    elif json.loads(t.private_file(directory/'start-execution.json'))['bundle_sha256']!=args.sha256:raise ValueError('registered start required')
    if args.mode=='cleanup':
        receipt=json.loads(t.private_file(directory/'acceptance.json'))
        if receipt['bundle_sha256']!=args.sha256 or receipt['state'] not in ('diagnostics_captured','diagnostics_held'):raise ValueError('terminal receipt required')
        proofs={'report_sha256':receipt['report_sha256']}
    label=args.mode+('-'+str(args.attempt) if args.mode=='readback' else '')
    t.write_new(directory/(label+'-execution.json'),{'epoch':int(time.time()),'bundle_sha256':args.sha256})
    endpoints=spec['endpoints'] if args.mode=='readback' else spec['endpoints'][:1]
    results={e:c.request(t,directory,spec,files,args.sha256,args.mode,label+'-'+str(i),e,proofs) for i,e in enumerate(endpoints)}
    if args.mode=='readback':
        receipt=terminal_receipt(spec,files,args.sha256,results);path=directory/'acceptance.json'
        if path.exists():
            if json.loads(t.private_file(path))!=receipt:raise ValueError('terminal receipt changed')
        else:t.write_new(path,receipt)
    return {'mode':args.mode,'results':{e:{k:v[k] for k in ('phase','summary','error','evidence_preserved') if k in v} for e,v in results.items()}}


def main():
    if sys.argv[1:]==['worker']:
        root=Path(__file__).resolve().parent;spec=json.loads((root/'spec.json').read_bytes())
        files={n:(root/n).read_bytes() for n in spec['members']};h=protected(spec,files);capture(h,spec,files);return
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='action',required=True)
    p=sub.add_parser('seal');p.add_argument('--source-dir',type=Path,required=True);p.add_argument('--source-sha256',required=True)
    p.add_argument('--operation-id',required=True);p.add_argument('--output',type=Path,required=True)
    p=sub.add_parser('execute');p.add_argument('--bundle',type=Path,required=True);p.add_argument('--sha256',required=True)
    p.add_argument('--mode',choices=('start','readback','cleanup'),required=True);p.add_argument('--attempt',type=int,choices=range(1,4),default=1)
    args=parser.parse_args();print(json.dumps(seal(args) if args.action=='seal' else execute(args),sort_keys=True))


if __name__=='__main__':main()
