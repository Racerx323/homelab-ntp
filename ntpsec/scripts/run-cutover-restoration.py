#!/usr/bin/python3
"""Seal a single restoration continuation; never replay the failed cutover."""
import argparse
import base64
from datetime import datetime, timezone
import fcntl
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import signal
import socket
import stat
import subprocess
import sys
import tarfile
import time

ROOT=Path(__file__).resolve().parents[1]
PATHS={'helper.py':'scripts/foundation-install.py',
       'inspector.py':'scripts/run-cutover-inspection.py',
       'reference.py':'scripts/run-gpsd-acquisition.py',
       'hardware-checker.py':'scripts/host-configuration-stage.py','pps-checker.py':'scripts/check-pps.py',
       'runtime-artifacts.py':'scripts/runtime-artifacts.py','host-network-stage.py':'scripts/host-network-stage.py',
       'inspect-source-destinations.py':'scripts/inspect-source-destinations.py',
       'clockmaker.py':'scripts/clockmaker.py','timeservice.py':'scripts/timeservice.py',
       'stage.py':'scripts/run-cutover-restoration.py',
       'controller.py':'scripts/run-service-cutover.py','transport.py':'scripts/run-foundation-preflight.py',
       'corrected-stage.py':'scripts/service-cutover-stage.py','tests.py':'tests/test_cutover_restoration.py',
       'cutover-tests.py':'tests/test_service_cutover.py',
       'diagnostic-tests.py':'tests/test_runtime_diagnostic.py','test-runner.sh':'tests/run.sh',
       'architecture.md':'docs/ntp-architecture-deployment-plan-v1.0.md',
       'operations.md':'docs/OPERATIONS.md','history.md':'HISTORY.md'}
EXTRA={'source.tar','inspection.tar','inspection-proof.json','known_hosts'}
ENV={'PATH':'/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin','LC_ALL':'C','PYTHONDONTWRITEBYTECODE':'1'}
LIMIT=32*1024**2
CHECKS={'files','uart','observation','network','native','accounts','loader','hardware','statistics','timer'}
EVIDENCE=('commands.jsonl','timer-before.json','continuity-before.json','continuity-after.json')


def encoded(value):return (json.dumps(value,sort_keys=True)+'\n').encode()
def sha(raw):
    import hashlib
    return hashlib.sha256(raw).hexdigest()


def load(path):
    spec=importlib.util.spec_from_file_location('restoration_'+path.stem.replace('-','_'),path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def frozen(raw):
    import types
    ns={'__name__':'sealed_restoration_reference','__file__':'/sealed/reference.py'}
    exec(compile(raw,'sealed-reference','exec'),ns);return types.SimpleNamespace(**ns)


def evidence(report,name):
    row=report['evidence'][name];raw=base64.b64decode(row['base64'],validate=True)
    if sha(raw)!=row['sha256']:raise ValueError('inspection evidence digest')
    return raw


def normalized_observation(value):
    """Only the inspected unloaded timeservice failure is an allowed transition."""
    # The observer concatenates the final service and socket command outputs.
    result=dict(value);blocks=re.split(r'(\n\n|(?<=\n)(?=Id=gpsd\.socket\n))',result['services']);found=0
    for index in range(0,len(blocks),2):
        block=blocks[index]
        pairs=[line.split('=',1) for line in block.splitlines() if '=' in line];rows=dict(pairs)
        if len(pairs)!=len(rows):raise ValueError('duplicate observation properties')
        if rows.get('Id')!='timeservice.service':continue
        found+=1
        if (rows.get('LoadState')!='not-found' or rows.get('MainPID')!='0'
                or rows.get('FragmentPath')!='' or rows.get('DropInPaths')!=''
                or (rows.get('ActiveState'),rows.get('SubState')) not in (('failed','failed'),('inactive','dead'))):
            raise ValueError('unrelated timeservice state drift')
        blocks[index]=block.replace('ActiveState=failed','ActiveState=inactive').replace('SubState=failed','SubState=dead')
    if found!=1:raise ValueError('one timeservice observation required')
    result['services']=''.join(blocks);return result


def inputs(files):
    c=frozen(files['controller.py']);source=c.unpack(files['source.tar']);old=json.loads(source['spec.json'])
    inspected=c.unpack(files['inspection.tar']);ins=frozen(files['inspector.py']);ispec=json.loads(inspected['spec.json'])
    proof=json.loads(files['inspection-proof.json']);responses=proof['responses']
    ins.validate(ispec,inspected)
    if (len(responses)!=2 or responses[0]!=responses[1]
            or any(r['spec_sha256']!=sha(inspected['spec.json']) for r in responses)
            or inspected['source-spec.json']!=source['spec.json'] or ispec['source_bundle_sha256']!=sha(files['source.tar'])
            or files['known_hosts']!=source['known_hosts']
            or files['known_hosts']!=inspected['known_hosts']):raise ValueError('bound original/inspection inputs required')
    result=responses[0]['result']
    receipt=ins.terminal_receipt(ispec,inspected,sha(files['inspection.tar']),dict(zip(ispec['endpoints'],[result,result])))
    if receipt!=proof['acceptance'] or receipt['state']!='diagnostics_captured':raise ValueError('accepted inspection required')
    if proof['cleanup']!={'spec_sha256':sha(inspected['spec.json']),'result':{
            'phase':'cleaned','evidence_preserved':True,'source_unchanged':True,'report_sha256':receipt['report_sha256']}}:
        raise ValueError('inspection closure required')
    payload_hash=sha(c.payload(ispec,inspected,'readback'))
    for endpoint,submission in zip(ispec['endpoints'],proof['submissions']):
        if (submission['bundle_sha256']!=sha(files['inspection.tar']) or submission['payload_sha256']!=payload_hash
                or 'ama@'+endpoint not in submission['argv']):raise ValueError('inspection submission binding')
    if len(proof['submissions'])!=2:raise ValueError('two endpoint submissions required')
    ref=c.unpack(source['reference.tar']);runtime=c.unpack(ref['runtime.tar']);rs=json.loads(runtime['spec.json'])
    a=frozen(files['reference.py']);a.validate(json.loads(ref['spec.json']),ref,historical=True)
    observation=json.loads(evidence(result,'continuity.json'))
    stage=frozen(files['hardware-checker.py'])
    if (observation['baseline']!=json.loads(runtime['baseline.json'])['observation']
            or observation['current']['boot_id']!=old['boot_id']
            or not stage.observation_equal(normalized_observation(observation['current']),observation['baseline'],
                                           new_boot=old['boot_id']!=rs['boot_id'])):
        raise ValueError('inspection does not isolate the failed-unit mismatch')
    return c,ins,ispec,inspected,old,source,ref,runtime,result


def validate(spec,files):
    if set(files)!=set(PATHS)|EXTRA|{'spec.json','manifest.json','review.md'}:
        raise ValueError('closed restoration members required')
    c,ins,ispec,inspected,old,source,ref,runtime,result=inputs(files)
    if (spec['schema']!=1 or spec['purpose']!='cutover-restoration'
            or not re.fullmatch('[a-z][a-z0-9-]{0,47}',spec['operation_id'])
            or spec['stage']!='/var/lib/ntp-restore-'+spec['operation_id']
            or spec['source_stage']!=old['stage'] or not re.fullmatch('/var/lib/ntp-acquire-[a-z][a-z0-9-]{0,47}',old['stage'])
            or any(spec[k]!=old[k] for k in ('hostname','kernel','boot_id','endpoints','old_ipv4'))
            or spec['source_sha256']!=sha(files['source.tar']) or spec['inspection_sha256']!=sha(files['inspection.tar'])
            or type(spec['prepared_epoch']) is not int or type(spec['expires_epoch']) is not int
            or not 0<spec['expires_epoch']-spec['prepared_epoch']<=86400
            or spec['members']!={n:sha(files[n]) for n in set(PATHS)|EXTRA}):
        raise ValueError('restoration identity/input/window binding')
    return c,ins,ispec,inspected,old,source,ref,runtime,result


def write(h,root,name,value):
    temp=root/(name+'.new');h.create(temp,encoded(value));os.replace(temp,root/name);h.sync(root)


def source_lock(h,spec,old,source):
    root=Path(spec['source_stage']);h.ancestors(root)
    if stat.S_IMODE(root.stat().st_mode)!=0o700:raise ValueError('private source stage required')
    fd=os.open(root/'.lock',os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or (info.st_uid,info.st_gid,info.st_nlink,stat.S_IMODE(info.st_mode))!=(0,0,1,0o600):
            raise ValueError('protected source lock required')
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if h.read(root/'spec.json')!=source['spec.json']:raise ValueError('source specification drift')
        for name,digest in old['members'].items():
            if sha(h.read(root/name,limit=LIMIT))!=digest:raise ValueError('source member drift')
        return fd
    except BaseException:os.close(fd);raise


def command(h,root,argv,timeout=20):
    p=subprocess.run(argv,env=ENV,capture_output=True,timeout=timeout,check=False)
    if len(p.stdout)>2*1024**2 or len(p.stderr)>65536:raise ValueError('command output bound')
    raw=encoded({'argv':argv,'status':p.returncode,'stdout':p.stdout.decode(errors='replace'),'stderr':p.stderr.decode(errors='replace')})
    path=root/'commands.jsonl'
    fd=os.open(path,os.O_WRONLY|os.O_APPEND|os.O_CREAT|os.O_NOFOLLOW,0o600)
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or (info.st_uid,info.st_gid,info.st_nlink,stat.S_IMODE(info.st_mode))!=(0,0,1,0o600) or info.st_size+len(raw)>8*1024**2:
            raise ValueError('protected bounded command journal required')
        while raw:raw=raw[os.write(fd,raw):]
        os.fsync(fd)
    finally:os.close(fd)
    if p.returncode:raise ValueError('command failed: '+repr(argv))
    return p.stdout.decode()


def unit(run,name):
    raw=run(['/usr/bin/systemctl','show',name,'--no-pager',
             '--property=Id,LoadState,ActiveState,SubState,FragmentPath,DropInPaths'])
    rows=[line.split('=',1) for line in raw.splitlines() if '=' in line];result=dict(rows)
    if len(rows)!=len(result) or set(result)!={'Id','LoadState','ActiveState','SubState','FragmentPath','DropInPaths'} or result['Id']!=name:
        raise ValueError('complete unique unit properties required')
    return result


def timer_state(run,old):
    timer=unit(run,old['recovery_unit']+'.timer');service=unit(run,old['recovery_unit']+'.service')
    for value,suffix in ((timer,'.timer'),(service,'.service')):
        expected='/run/systemd/transient/'+old['recovery_unit']+suffix
        if value['DropInPaths'] or (value['LoadState'],value['FragmentPath']) not in (('loaded',expected),('not-found','')):
            raise ValueError('recovery unit identity drift')
    if (timer['ActiveState'],timer['SubState']) not in (('active','waiting'),('inactive','dead'),('failed','failed')):
        raise ValueError('unexpected recovery timer state')
    if (service['ActiveState'],service['SubState']) not in (('inactive','dead'),('failed','failed')):
        raise ValueError('recovery worker is active; release lock and inspect')
    return {'timer':timer,'service':service}


def restored_files(tx,before,state):
    if set(before['files'])!=set(tx.frozen_destinations):raise ValueError('closed destination backup set required')
    for name,record in before['files'].items():
        if tx.snapshot(name)!=record:raise ValueError('destination not restored: '+name)
    if not set(state['created_directories'])<=set(tx.frozen_directories):raise ValueError('unexpected created directory')
    if any(os.path.lexists(path) for path in state['created_directories']):raise ValueError('runtime directory still present')
    if tx.a.serial_identity()!=before['serial']:raise ValueError('UART identity drift')
    tx.a.idle()
    if tx.run(['/usr/bin/stty','-F','/dev/serial0','-g']).strip()!=before['termios']:raise ValueError('UART settings not restored')


def restore(h,spec,files):
    c,ins,ispec,inspected,old,source,ref,runtime,report=validate(spec,files)
    root=Path(spec['stage']);src=Path(old['stage']);fd=source_lock(h,spec,old,source)
    try:
        initial=json.loads(h.read(src/'state.json'));ins.held_state(ispec,inspected,initial)
        before_raw=h.read(src/'before.json');before=json.loads(before_raw)
        if before_raw!=evidence(report,'source-before.json'):raise ValueError('source backup drift')
        h.create(root/'source-state-before.json',encoded(initial));h.create(root/'source-before.json',before_raw)
        original=frozen(files['corrected-stage.py']);tx=original.Transaction(old,source,code_root=root)
        tx.run=lambda argv,timeout=20:command(h,root,argv,timeout)
        tx.a.run=tx.run
        tx.frozen_destinations=original.DESTINATIONS;tx.frozen_directories=original.DIRECTORIES
        restored_files(tx,before,initial)
        expected=json.loads(evidence(report,'continuity.json'))['current']
        # Clone accepted runtime inputs for checks; never change historical baseline bytes.
        a=tx.a;runtime_spec=json.loads(runtime['spec.json']);rfd,retained=a.source_guard(h,json.loads(ref['spec.json']),runtime)
        try:
            if json.loads(retained['state.json'])!=json.loads(ref['runtime-cleanup.json'])['result']:
                raise ValueError('accepted runtime state drift')
            sub=root/'runtime-check';sub.mkdir(mode=0o700)
            rs,current=frozen(files['runtime-artifacts.py']).runtime_inputs(runtime_spec,runtime,files,sub)
            for name,raw in current.items():h.create(sub/name,raw)
            for name,data in retained.items():h.create(sub/name,data)
            h.create(sub/'spec.json',encoded(rs))
            check=load(sub/'host-configuration-stage.py').Transaction(rs)
            check.run=tx.run;check.core.run=tx.run;check.core.i.command=tx.run
            current=check.core.i.observation()
            h.create(root/'continuity-before.json',encoded(current))
            if normalized_observation(current)!=normalized_observation(expected):raise ValueError('new observation drift since inspection')
            clocks=timer_state(tx.run,old);h.create(root/'timer-before.json',encoded(clocks))
            # Stop only the obsolete retry timer under the original operation lock.
            if clocks['timer']['LoadState']=='loaded':tx.systemctl('stop',old['recovery_unit']+'.timer')
            after_timer=timer_state(tx.run,old)
            if after_timer['timer']['ActiveState']!='inactive':raise ValueError('timer stop not confirmed')
            reset=frozen(files['corrected-stage.py']).clear_restored_failure(tx.systemctl)
            final_observation=check.core.i.observation()
            h.create(root/'continuity-after.json',encoded(final_observation))
            if final_observation!=normalized_observation(expected):raise ValueError('restored observation mismatch')
            check.network_checks()
            accepted=json.loads(retained['state.json'])
            if check.accounts()!=accepted['created_account'] or check.snapshot_file(Path('/etc/ld.so.cache'))!=accepted['cache_after']:
                raise ValueError('runtime account/loader drift')
            check.recipe=json.loads(runtime['hardware-spec.json'])['host_recipe']
            if check.hardware_metadata()!=accepted['hardware']:raise ValueError('hardware metadata drift')
            restored_files(tx,before,initial)
            if h.read(src/'state.json')!=encoded(initial):raise ValueError('source changed under lock')
            if ins.runtime_data(h,src)!=json.loads(evidence(report,'runtime-data.json')):raise ValueError('retained statistics drift')
            for name,data in retained.items():
                if h.read(Path(runtime_spec['stage'])/name)!=data:raise ValueError('original runtime evidence changed')
            final_timer=timer_state(tx.run,old)
            if final_timer['timer']['ActiveState']!='inactive':raise ValueError('timer reactivated')
            return {'phase':'restoration_verified','restoration_accepted':True,'time_service_accepted':False,
                    'source_preserved':True,'source_phase':initial['phase'],'failed_state_reset':reset,
                    'timer':final_timer,'checks':dict.fromkeys(('files','uart','observation','network','native',
                    'accounts','loader','hardware','statistics','timer'),True)}
        finally:os.close(rfd)
    finally:os.close(fd)


def entry(spec,files,mode,proofs=None):
    validate(spec,dict(files,**{'spec.json':encoded(spec),'manifest.json':b'','review.md':b''}))
    root=Path(spec['stage']);os.umask(0o077);ins=frozen(files['inspector.py'])
    if mode=='start':
        if (os.geteuid()!=0 or os.environ.get('SUDO_USER')!='ama' or os.environ.get('SUDO_UID')!='1000'
                or os.environ.get('SUDO_GID')!='1000' or socket.gethostname()!=spec['hostname']
                or os.uname().release!=spec['kernel'] or Path('/proc/sys/kernel/random/boot_id').read_text().strip()!=spec['boot_id']
                or not spec['prepared_epoch']-300<=time.time()<spec['expires_epoch']):raise ValueError('approved target/caller/window required')
        h=frozen(files['helper.py']);h.ancestors(root.parent);root.mkdir(mode=0o700)
        for name,raw in dict(files,**{'spec.json':encoded(spec)}).items():h.create(root/name,raw)
        h.create(root/'report.json',encoded({'phase':'running'}))
    h=ins.protected(spec,files)
    if mode=='start':
        try:
            with (root/'worker.stdout').open('xb') as out,(root/'worker.stderr').open('xb') as err:
                process=subprocess.Popen(['/usr/bin/python3','-I','-B',str(root/'stage.py'),'worker'],stdout=out,stderr=err,env=ENV,start_new_session=True)
                try:process.wait(timeout=190)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid,signal.SIGKILL);process.wait();raise ValueError('worker exceeded bound')
                if json.loads(h.read(root/'report.json',limit=LIMIT))['phase']=='running':raise ValueError('worker exited without a terminal report')
        except BaseException as error:
            write(h,root,'report.json',{'phase':'restoration_held','error':str(error)[:500],'source_preserved':True,'time_service_accepted':False})
    if mode in ('start','readback'):return json.loads(h.read(root/'report.json',limit=LIMIT))
    if mode=='cleanup':
        raw=h.read(root/'report.json',limit=LIMIT)
        if proofs!={'report_sha256':sha(raw)} or json.loads(raw)['phase'] not in ('restoration_verified','restoration_held'):
            raise ValueError('matching terminal restoration receipt required')
        result={'phase':'cleaned','evidence_preserved':True,'source_preserved':True,'report_sha256':sha(raw)}
        h.create(root/'cleanup.json',encoded(result));return result
    raise ValueError('closed continuation mode required')


def terminal(spec,checksum,results):
    if set(results)!=set(spec['endpoints']) or len({sha(encoded(r)) for r in results.values()})!=1:
        raise ValueError('matching dual-stack terminal readback required')
    result=next(iter(results.values()))
    if result['phase'] not in ('restoration_verified','restoration_held'):raise ValueError('terminal result required')
    for name in result.get('evidence',{}):
        if name not in EVIDENCE:raise ValueError('unexpected restoration evidence')
        evidence(result,name)
    if result['phase']=='restoration_verified' and (result.get('restoration_accepted') is not True
            or result.get('time_service_accepted') is not False or result.get('source_preserved') is not True
            or result.get('checks')!=dict.fromkeys(CHECKS,True) or set(result.get('evidence',{}))!=set(EVIDENCE)):
        raise ValueError('complete restoration checks and evidence required')
    return {'state':result['phase'],'bundle_sha256':checksum,'spec_sha256':sha(encoded(spec)),
            'report_sha256':sha(encoded(result)),'time_service_accepted':False}


def review(spec):
    return f'''# Restoration continuation: {spec['operation_id']}

Target **{spec['hostname']}**, kernel `{spec['kernel']}`, boot `{spec['boot_id']}`.
Endpoints: {', '.join(spec['endpoints'])}. Expires **{datetime.fromtimestamp(spec['expires_epoch'],timezone.utc).isoformat()}**.
Source archive: `{spec['source_sha256']}`. Inspection: `{spec['inspection_sha256']}`.

One start, in root-owned 0700 `{spec['stage']}` with 0600 inputs/evidence.
Verify pinned host keys, exact identity, source immutable members, accepted runtime
inputs, inspection receipt/readback/closure, preserved backups and allowed automatic
recovery transitions. Take the existing source lock exclusively and nonblocking.
Reject active recovery, unexpected unit definitions, new observation drift, or any
file/UART/directory not already restored. Never replay the trial or original recovery.

Read fresh retry-timer/service state. Stop only the source recovery timer, then
recheck that no recovery worker is active. Clear only the unloaded, PID-zero failed
`timeservice.service` state with a targeted reset-failed; verify inactive/dead.
The original reboot-aware continuity checker remains unchanged: the offline replay
shows it already permits boot/PID differences; only failed-unit state caused rejection.

Validate restored files, idle receiver/UART settings, exact current-boot observation,
original package/native/Python/network/protected-file checks, accounts, loader-cache
metadata and UART/PPS/RTC metadata. Check retained statistics and source records again.
Checks use a private copy of the original accepted runtime inputs. Historical input
age is provenance, not fresh installation acceptance; this separately bounded operation
requires the same accepted boot and live restoration checks. No clock service starts,
clock adjustment, configuration/receiver write, reboot or NTS traffic is authorized.
Network checks include the original bounded dual-stack gateway/egress probes.

A 180-second worker deadline holds failure and preserves logs. If a check fails after
stopping the obsolete retry timer or clearing failed state, those two changes remain;
do not rearm the known-failing recovery or retry start. Read back the held report and
review a separate repair. The original source stage, state, backups and logs stay intact.

Up to three numbered conditional readbacks through both pinned endpoints retrieve the
stored terminal report. Matching readbacks accept restoration only, never time service.
Conditional cleanup records closure only, retaining both stages and all evidence.
A lost result is resolved by readback, never another start.

Execution after separate approval:
`python3 -I -B ntpsec/scripts/run-cutover-restoration.py execute --bundle ABSOLUTE_BUNDLE --sha256 APPROVED_HASH --mode start`
Then `--mode readback --attempt N` and `--mode cleanup` with the same bundle/hash.
'''


def prepare(bundle,checksum):
    t=load(ROOT/'scripts/run-foundation-preflight.py');c=load(ROOT/'scripts/run-service-cutover.py')
    raw=t.private_file(bundle,LIMIT)
    if sha(raw)!=checksum:raise ValueError('approved restoration archive required')
    files=c.unpack(raw);spec=json.loads(files['spec.json']);validate(spec,files)
    if any(files[n]!=(ROOT/p).read_bytes() for n,p in PATHS.items()) or t.private_file(bundle.parent/'known_hosts',4096)!=files['known_hosts']:
        raise ValueError('current input/key drift; reseal required')
    for mode in ('start','readback','cleanup'):compile(c.payload(spec,files,mode),'sealed-restoration','exec')
    return spec,files


def seal(args):
    c=load(ROOT/'scripts/run-service-cutover.py');t=load(ROOT/'scripts/run-foundation-preflight.py')
    source_raw=t.private_file(args.source_dir/'service-cutover.tar',LIMIT)
    inspection_raw=t.private_file(args.inspection_dir/'cutover-inspection.tar',LIMIT)
    if sha(source_raw)!=args.source_sha256 or sha(inspection_raw)!=args.inspection_sha256:raise ValueError('approved prior archive digests required')
    source=c.unpack(source_raw);old=json.loads(source['spec.json']);inspected=c.unpack(inspection_raw)
    prefix=f'readback-{args.inspection_attempt}-'
    proof={'responses':[json.loads(t.private_file(args.inspection_dir/(prefix+str(i)+'-result.json'),LIMIT)) for i in (0,1)],
           'submissions':[json.loads(t.private_file(args.inspection_dir/(prefix+str(i)+'-submission.json'))) for i in (0,1)],
           'acceptance':json.loads(t.private_file(args.inspection_dir/'acceptance.json')),
           'cleanup':json.loads(t.private_file(args.inspection_dir/'cleanup-0-result.json'))}
    files={n:(ROOT/p).read_bytes() for n,p in PATHS.items()}
    files.update({'source.tar':source_raw,'inspection.tar':inspection_raw,'inspection-proof.json':encoded(proof),
                  'known_hosts':source['known_hosts']})
    epoch=int(time.time());spec={k:old[k] for k in ('hostname','kernel','boot_id','endpoints','old_ipv4')}
    spec.update(schema=1,purpose='cutover-restoration',operation_id=args.operation_id,stage='/var/lib/ntp-restore-'+args.operation_id,
                source_stage=old['stage'],source_sha256=sha(source_raw),inspection_sha256=sha(inspection_raw),
                prepared_epoch=epoch,expires_epoch=epoch+86400,members={n:sha(v) for n,v in files.items()})
    files['spec.json']=encoded(spec);files['review.md']=review(spec).encode();files['manifest.json']=encoded({n:sha(v) for n,v in files.items()})
    validate(spec,files);os.umask(0o077);args.output.mkdir(mode=0o700)
    for name in ('spec.json','review.md','known_hosts'):(args.output/name).write_bytes(files[name])
    bundle=args.output/'restoration.tar'
    with tarfile.open(bundle,'w',format=tarfile.USTAR_FORMAT) as archive:
        for name,raw in sorted(files.items()):
            item=tarfile.TarInfo(name);item.size=len(raw);item.mode=0o600;item.mtime=epoch;archive.addfile(item,io.BytesIO(raw))
    checksum=sha(bundle.read_bytes());prepare(bundle,checksum)
    result={'bundle':str(bundle),'sha256':checksum,'target':spec['hostname'],'expires_epoch':spec['expires_epoch'],'target_contact':False,'execution_authorized':False}
    t.write_new(args.output/'sealing.json',result);return result


def execute(args):
    os.umask(0o077);c=load(ROOT/'scripts/run-service-cutover.py');t=load(ROOT/'scripts/run-foundation-preflight.py')
    bundle=args.bundle.absolute();spec,files=prepare(bundle,args.sha256);root=bundle.parent;proofs=None
    if args.mode=='start':
        if not spec['prepared_epoch']-300<=time.time()<spec['expires_epoch']:raise ValueError('restoration window expired')
    elif json.loads(t.private_file(root/'start-execution.json'))['bundle_sha256']!=args.sha256:raise ValueError('registered start required')
    if args.mode=='cleanup':
        receipt=json.loads(t.private_file(root/'acceptance.json'))
        if receipt['bundle_sha256']!=args.sha256 or receipt['state'] not in ('restoration_verified','restoration_held'):raise ValueError('matching receipt required')
        proofs={'report_sha256':receipt['report_sha256']}
    label=args.mode+('-'+str(args.attempt) if args.mode=='readback' else '')
    t.write_new(root/(label+'-execution.json'),{'epoch':int(time.time()),'bundle_sha256':args.sha256})
    endpoints=spec['endpoints'] if args.mode=='readback' else spec['endpoints'][:1]
    results={e:c.request(t,root,spec,files,args.sha256,args.mode,label+'-'+str(i),e,proofs) for i,e in enumerate(endpoints)}
    if args.mode=='readback':
        receipt=terminal(spec,args.sha256,results);path=root/'acceptance.json'
        if path.exists():
            if json.loads(t.private_file(path))!=receipt:raise ValueError('terminal receipt changed')
        else:t.write_new(path,receipt)
    return {'mode':args.mode,'results':results}


def main():
    if len(sys.argv)==2 and sys.argv[1]=='worker':
        root=Path(__file__).parent;spec=json.loads((root/'spec.json').read_bytes());files={n:(root/n).read_bytes() for n in spec['members']}
        files.update({'spec.json':encoded(spec),'manifest.json':b'','review.md':b''})
        h=frozen(files['inspector.py']).protected(spec,files)
        def expired(*args):raise TimeoutError('restoration worker deadline')
        signal.signal(signal.SIGALRM,expired);signal.alarm(180)
        try:result=restore(h,spec,files)
        except BaseException as error:result={'phase':'restoration_held','error':str(error)[:500],'source_preserved':True,'time_service_accepted':False}
        finally:signal.alarm(0)
        result['evidence']={};total=0
        for name in EVIDENCE:
            if not (root/name).exists():continue
            raw=h.read(root/name,limit=8*1024**2);total+=len(raw)
            if total>8*1024**2:
                result.update(phase='restoration_held',error='readback evidence bound; retain staged logs',restoration_accepted=False);break
            result['evidence'][name]={'sha256':sha(raw),'base64':base64.b64encode(raw).decode()}
        write(h,root,'report.json',result);return
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='action',required=True)
    p=sub.add_parser('seal');p.add_argument('--source-dir',type=Path,required=True);p.add_argument('--source-sha256',required=True)
    p.add_argument('--inspection-dir',type=Path,required=True);p.add_argument('--inspection-sha256',required=True)
    p.add_argument('--inspection-attempt',type=int,choices=range(1,4),required=True)
    p.add_argument('--operation-id',required=True);p.add_argument('--output',type=Path,required=True)
    p=sub.add_parser('execute');p.add_argument('--bundle',type=Path,required=True);p.add_argument('--sha256',required=True)
    p.add_argument('--mode',choices=('start','readback','cleanup'),required=True);p.add_argument('--attempt',type=int,choices=range(1,4),default=1)
    args=parser.parse_args();print(json.dumps(seal(args) if args.action=='seal' else execute(args),sort_keys=True))


if __name__=='__main__':main()
