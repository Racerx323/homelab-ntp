#!/usr/bin/python3
"""Seal and execute separate guarded node and genuine-producer stages."""
import argparse
import base64
import hashlib
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
import tarfile
import time
import types
from zoneinfo import ZoneInfo
from datetime import datetime

ROOT=Path(__file__).resolve().parents[1]
FLEET=ROOT.parent.parent/'homelab-monitoring-observability/Munin'
MAXIMUM=32*1048576
STAGES=Path('/var/lib/ntp-munin-stages')
HELPER=ROOT/'scripts/run-production-inspection.py'


def encoded(x):return (json.dumps(x,sort_keys=True)+'\n').encode()
def sha(x):return hashlib.sha256(x).hexdigest()


def archive_files(raw,digest,reserve=900):
    if len(raw)>MAXIMUM or sha(raw)!=digest:raise ValueError('approved archive hash/size mismatch')
    with tarfile.open(fileobj=io.BytesIO(raw),mode='r:') as t:
        entries=t.getmembers()
        if len(entries)>40 or any(not m.isfile() or m.size>16*1048576 or m.name.startswith('/') or '..' in Path(m.name).parts
                                 or str(Path(m.name))!=m.name or '\\' in m.name for m in entries):
            raise ValueError('bounded regular member paths required')
        if len({m.name for m in entries})!=len(entries):raise ValueError('duplicate archive member')
        files={m.name:t.extractfile(m).read() for m in entries}
    manifest=json.loads(files['manifest.json'])
    if manifest!={n:sha(v) for n,v in files.items() if n!='manifest.json'}:raise ValueError('closed manifest mismatch')
    spec=json.loads(files['spec.json'])
    expected={'runner.py','helper.py','worker.py','spec.json','review.md','known_hosts','manifest.json'}|set(spec['input_members'])
    if spec['kind']=='resume':expected.add('base.py')
    if set(files)!=expected or spec['kind'] not in ('node','producers','resume') or not re.fullmatch(r'munin-[a-z0-9-]{1,55}',spec['operation_id']):
        raise ValueError('closed stage scope required')
    if not spec['prepared_epoch']<=time.time()<spec['expires_epoch']-reserve:raise ValueError('expired stage/reserve')
    return spec,files


def render_reporter(raw):
    marker=b'\nexit 0\n'
    if not raw.endswith(marker) or b'ntp-maintenance-success.py' in raw:raise ValueError('unexpected reporter source')
    hook=b'''\n# Test, lock-skip and failure paths never reach this real completion point.
if ! /usr/bin/python3 -I -B /usr/local/libexec/ntp-maintenance-success.py reporting; then
    report_failure 1 \\
        "Needrestart completion record failed on ${SYSTEM_ID}" \\
        "The real scan completed, but its protected success record could not be written."
    exit $?
fi
'''
    return raw[:-len(marker)]+hook+marker


def render_rule(raw):
    if raw.count(b'    firstaction\n')!=1 or raw.count(b'    endscript')!=1:raise ValueError('unexpected cleanup rule')
    a=raw.index(b'    firstaction\n');b=raw.index(b'    endscript',a)
    return raw[:a]+b'    firstaction\n        /usr/bin/python3 -I -B /usr/local/libexec/ntp-maintenance-success.py retention\n'+raw[b:]


def accepted_capture(path):
    raw=(path/'inspection.tar').read_bytes();r=json.loads((path/'result.json').read_text());data=(path/'stdout.txt').read_bytes();c=json.loads(data)
    with tarfile.open(fileobj=io.BytesIO(raw)) as t:
        s=json.loads(t.extractfile('spec.json').read());known=t.extractfile('known_hosts').read()
    if (r.get('bundle_sha256')!=sha(raw) or r.get('returncode')!=0 or not r.get('capture_complete') or not c.get('capture_complete')
            or c.get('operation_id')!=s['operation_id'] or c.get('spec_sha256')!=sha(encoded(s))):raise ValueError('accepted node readiness required')
    if s.get('mode')!='node' or s.get('hostname')!='j2-svntp1':raise ValueError('fixed node readiness identity')
    return s,c,known,sha(raw),sha(data)


def seal(args):
    old,c,known,baseline,capture=accepted_capture(args.baseline)
    now=int(time.time());operation=args.output.name;stage=STAGES/operation
    fields=('MainPID','InvocationID','NRestarts','ActiveState','SubState')
    identity={k:old['service_identity'][k] for k in fields}
    worker={'operation_id':operation,'hostname':'j2-svntp1','boot_id':old['boot_id'],'schema':1,
        'service_identity':identity,'protected_files':{p:c['files'][p]['sha256'] for p in ('/etc/ntp.conf','/usr/local/bin/ntpq')},
        'package_inventory_sha256':sha(c['commands']['packages']['stdout'].encode())}
    files={'runner.py':Path(__file__).read_bytes(),'helper.py':HELPER.read_bytes(),'known_hosts':known}
    files['inputs/stage-tests.py']=(ROOT/'tests/test_munin_stages.py').read_bytes()
    if args.kind=='node':
        worker.update(profile='ntp',architecture='arm64',fixture=False,source_root=str(stage/'profile'),package_root=str(stage/'packages'),
            listen_addresses=['10.1.0.51','fd36:5aa8:6971:1::51'],allow_addresses=['10.1.3.83','fd36:5aa8:6971:1::83'],policy_before_sha256=None)
        files['worker.py']=(FLEET/'scripts/install_ntp_node.py').read_bytes()
        release=json.loads(args.qualification.read_text())
        files['inputs/release-inputs.json']=args.qualification.read_bytes()
        if release.get('homelab-monitoring-observability/Munin/scripts/install_ntp_node.py')!=sha(files['worker.py']):raise ValueError('qualified installer bytes changed')
        names=['node/profiles/ntp/profile.json','node/plugin-conf.d/ntp.conf','node/plugins/ntp/ntp_metrics.py',
               *['node/plugins/ntp/'+n for n in ('ntp_health','ntp_storage','ntp_statistics','ntp_jobs')]]
        worker['artifacts']={}
        for n in names:
            raw=(FLEET/n).read_bytes()
            if release.get('homelab-monitoring-observability/Munin/'+n)!=sha(raw):raise ValueError('qualified profile input changed')
            worker['artifacts'][n]=sha(raw);files['profile/'+n]=raw
        packages=json.loads((ROOT/'configs/munin-package-review.json').read_text())['packages'];worker['packages']=packages
        for row in packages:
            if Path(row['filename']).name!=row['filename']:raise ValueError('package filename')
            raw=(args.packages/row['filename']).read_bytes()
            if sha(raw)!=row['sha256'] or len(raw)!=row['size']:raise ValueError('package archive hash/size')
            files['packages/'+row['filename']]=raw
        node=next(p for p in packages if p['package']=='munin-node')
        row=subprocess.run(['/usr/bin/dpkg-deb','--fsys-tarfile',str(args.packages/node['filename'])],capture_output=True,timeout=30,check=True)
        with tarfile.open(fileobj=io.BytesIO(row.stdout)) as t:
            worker['default_settings_sha256']=sha(t.extractfile('./etc/munin/plugin-conf.d/munin-node').read())
            worker['settings_readme_sha256']=sha(t.extractfile('./etc/munin/plugin-conf.d/README').read())
    else:
        files['worker.py']=(ROOT/'scripts/install-maintenance-producers.py').read_bytes()
        files['inputs/helper.py']=(ROOT/'scripts/maintenance-success.py').read_bytes()
        files['inputs/reporter.sh']=render_reporter((ROOT/'scripts/needrestart.sh').read_bytes())
        files['inputs/retention.conf']=render_rule((ROOT/'templates/ntpstats-retention.logrotate').read_bytes())
        worker.update(state_root=str(stage/'producer-state'),input_root=str(stage/'inputs'),files={},
                      job_inputs={path:{key:c['files'][path][key] for key in ('sha256','mode')}
                                  for path in ('/etc/cron.d/needrestart_check','/var/lib/ntpstats-retention/trigger')})
        for target,inputname,mode in [('/usr/local/libexec/ntp-maintenance-success.py','helper.py',0o644),('/usr/local/sbin/needrestart.sh','reporter.sh',0o755),('/etc/logrotate.d/ntpstats-retention','retention.conf',0o644)]:
            before=None if inputname=='helper.py' else c['files'][target]['sha256']
            if inputname!='helper.py':
                source=ROOT/('scripts/needrestart.sh' if inputname=='reporter.sh' else 'templates/ntpstats-retention.logrotate')
                if sha(source.read_bytes())!=before:raise ValueError('accepted producer source drift')
            worker['files'][target]={'input':inputname,'mode':mode,'before_sha256':before,'after_sha256':sha(files['inputs/'+inputname])}
    inventory=(ROOT.parent.parent/'homelab-server-configs/inventory/prod/hosts/j2-svntp1.yaml').read_bytes()
    files['inputs/inventory.yaml']=inventory
    if b'profile: ntp' not in inventory or b'deployment_status: selected_not_deployed' not in inventory:raise ValueError('explicit inventory selection required')
    spec={'kind':args.kind,'operation_id':operation,'prepared_epoch':now,'expires_epoch':now+86400,'worker':worker,
          'baseline_bundle_sha256':baseline,'baseline_capture_sha256':capture,'input_members':sorted(n for n in files if n.startswith(('inputs/','profile/','packages/')))}
    return finish(args.output,spec,files)


def finish(output,spec,files):
    files['spec.json']=encoded(spec);files['review.md']=review(spec).encode()
    files['manifest.json']=encoded({n:sha(v) for n,v in files.items()})
    os.umask(0o077);output.mkdir(mode=0o700)
    for n,data in files.items():
        p=output/n;p.parent.mkdir(parents=True,exist_ok=True,mode=0o700);p.write_bytes(data)
    stream=io.BytesIO()
    with tarfile.open(fileobj=stream,mode='w') as t:
        for n,data in sorted(files.items()):
            m=tarfile.TarInfo(n);m.size=len(data);m.mode=0o600;t.addfile(m,io.BytesIO(data))
    raw=stream.getvalue();digest=sha(raw);archive_files(raw,digest);(output/'deployment.tar').write_bytes(raw)
    result={'sha256':digest,'expires_epoch':spec['expires_epoch'],'target_contact':False};(output/'sealing.json').write_bytes(encoded(result));return result


def seal_resume(args):
    raw=(args.source_stage/'deployment.tar').read_bytes()
    if sha(raw)!=args.source_sha256:raise ValueError('consumed source archive hash')
    with tarfile.open(fileobj=io.BytesIO(raw),mode='r:') as t:
        original=json.loads(t.extractfile('spec.json').read());known=t.extractfile('known_hosts').read()
        qualified_base=t.extractfile('worker.py').read()
    result=json.loads((args.source_stage/'inspect-result.json').read_text())
    if (original['kind']!='node' or result.get('archive_sha256')!=args.source_sha256 or result.get('returncode')!=0
            or result['result'].get('recovery')!='contained' or result['result'].get('recovery_errors')):
        raise ValueError('confirmed consumed node containment required')
    capture=(args.selection/'stdout.txt').read_bytes();selection=json.loads(capture)
    retained=json.loads((args.retained/'stdout.txt').read_text())
    for directory,data in ((args.selection,selection),(args.retained,retained)):
        if json.loads((directory/'result.json').read_text()).get('returncode')!=0 or not data.get('capture_complete'):
            raise ValueError('complete successful diagnostic required')
    old=original['worker']
    before=selection['after']['file_hashes']
    if (not selection.get('selection_stable') or selection['before']!=selection['after']
            or selection['after']['timeservice']!=old['service_identity']
            or retained['source_archive_sha256']!=args.source_sha256
            or retained['state']['spec_sha256']!=sha(encoded(old))):raise ValueError('diagnostic continuity/provenance')
    operation=args.output.name;stage=STAGES/operation
    current_base=(FLEET/'scripts/install_ntp_node.py').read_bytes()
    if current_base!=qualified_base:raise ValueError('unchanged qualified base required')
    files={'runner.py':Path(__file__).read_bytes(),'helper.py':HELPER.read_bytes(),
           'worker.py':(FLEET/'scripts/resume_ntp_node.py').read_bytes(),'base.py':current_base,'known_hosts':known,
           'inputs/selection.json':capture,'inputs/retained.json':encoded(retained),
           'inputs/stage-tests.py':(ROOT/'tests/test_munin_stages.py').read_bytes(),
           'inputs/resume-tests.py':(FLEET/'tests/test_ntp_resume.py').read_bytes(),
           'inputs/parser-tests.py':(FLEET/'tests/test_ntp_metrics.py').read_bytes(),
           'inputs/ntpq-shm2-selected.txt':(FLEET/'tests/fixtures/ntpq-shm2-selected.txt').read_bytes()}
    artifacts={}
    for name,old_hash in old['artifacts'].items():
        data=(FLEET/name).read_bytes();artifacts[name]=sha(data);files['profile/'+name]=data
        if name!='node/plugins/ntp/ntp_metrics.py' and sha(data)!=old_hash:raise ValueError('unrelated profile change')
    metric='node/plugins/ntp/ntp_metrics.py'
    if before['/usr/local/munin/lib/plugins/ntp_metrics.py']!=old['artifacts'][metric]:raise ValueError('deployed classifier drift')
    ns={'__name__':'candidate_metrics'};exec(compile(files['profile/'+metric],'candidate_metrics','exec'),ns)
    metrics=ns['parse_ntpq'](selection['raw']['stdout'])
    if any(metrics[key]!=1 for key in ('query_ok','synced','pps_selected')):raise ValueError('real-output candidate replay failed')
    inventory=(ROOT.parent.parent/'homelab-server-configs/inventory/prod/hosts/j2-svntp1.yaml').read_bytes()
    if b'profile: ntp' not in inventory or b'deployment_status: installed_contained_not_accepted' not in inventory:
        raise ValueError('inventory must describe contained node')
    files['inputs/inventory.yaml']=inventory
    worker={key:old[key] for key in ('hostname','boot_id','service_identity','protected_files')}
    worker.update(installation=old,artifacts=artifacts,input_root=str(stage/'profile'),
        state_root='/var/lib/munin-ntp-resume/'+operation,
        original_state_path='/var/lib/munin-ntp-install/'+old['operation_id']+'/state.json',
        original_state_sha256=retained['state_file_sha256'],original_spec_sha256=sha(encoded(old)),
        before_sha256=old['artifacts'][metric])
    now=int(time.time());spec={'kind':'resume','operation_id':operation,'prepared_epoch':now,
        'expires_epoch':min(now+86400,int(selection['captured_epoch'])+86400),'worker':worker,
        'source_archive_sha256':args.source_sha256,'selection_sha256':sha(capture),
        'input_members':sorted(n for n in files if n.startswith(('inputs/','profile/')))}
    return finish(args.output,spec,files)


def resume_review(s):
    expiry=datetime.fromtimestamp(s['expires_epoch'],ZoneInfo('America/Chicago')).isoformat()
    return f'''# Classifier correction and guarded node start

Operation {s['operation_id']}, expires {expiry}; begin with 900 seconds remaining.
Approve deployment.tar's exact SHA-256 in sealing.json before execution. Target
ama@10.1.0.51, key alias 10.1.0.137, captured j2-svntp1 boot/service identity.
This preparation makes no target contact. The consumed first installation is
data provenance only; neither its apply nor inspect is replayed.

## Exact change and preflight

Replace only /usr/local/munin/lib/plugins/ntp_metrics.py from the captured old
hash with the tested classifier: recognize selected local stratum-0 SHM unit 2
with refid PPS under either normal selected tally, preserving native o PPS
support and rejecting network/refid/wrong-unit impostors. Every other profile
artifact, link, settings file, node config and original startup guard must match.
Pin NTP config, source-built ntpq, hostname/boot and time-service identity.
Require disabled/inactive node, no TCP4949 listener, absent original permit and
unchanged original consumed state/hash. Require the exact 15 installed node
package versions/architectures, clean dpkg audit; record current full inventory.
The obsolete 701-package pre-install pin is not reused. No package mutation.

## Ordered activation and acceptance

Create exclusive root-private resume state/backups, replace only the classifier
atomically, then exercise all nine installed config/fetch paths before startup.
Require query_ok, synced and pps_selected each equal 1; identify a failed field
explicitly. Missing real job records remain faults and are never fabricated.
Publish the empty original guard permit without clobbering, by linking a durable
root-private proof inode. Enable/start only munin-node. Verify exact dual literal
listeners (no wildcard), all nine real installed plugin paths, source/settings
readback, unchanged consumed original state and NTP continuity. Independent
controller TCP connections must pass both .51 and ::51. No master contact,
registration, schedule, graph or delivery acceptance. Original installation state
remains archival; accepted continuation gets separate resume state.

## Failure, inspection and recovery

On caught failure or known independent TCP failure, remove only our proven permit
inode, stop/disable only munin-node, and restore the classifier only when its hash
is the authored after hash and its backup matches before. Verify containment,
original artifacts and NTP continuity. Preserve foreign drift, packages, original
guard, private evidence and genuine job records; report held if recovery fails.
No original policy wrapper or package hooks are installed/restored. No NTP/GPSD,
clock, DNS, network, Apache, master, producer, job or mail change. No cleanup/purge.

Execute frozen runner.py execute --directory DIRECTORY --sha256 APPROVED_SHA256
only after this archive is authorized. One execution.json is consumed before SSH.
Remote alarm 600 seconds; transport 780 seconds; no retry/replay. For an uncertain
outcome, the same consumed bundle permits one read-only inspect (no new start
reserve, within expiry). Later manual recover requires explicit authorization.
After expiry, prepare a fresh scoped review. Final monitoring, scheduled jobs,
OBS-02/OBS-07, graphs, alerts and ntpviz remain separate gates.
'''


def review(s):
    if s['kind']=='resume':return resume_review(s)
    node=s['kind']=='node';expiry=datetime.fromtimestamp(s['expires_epoch'],ZoneInfo('America/Chicago')).isoformat()
    scope='''Install exactly 15 pinned ARM64/all package archives via the unchanged qualified
installer. Suppress package autoconfiguration and first start through its scoped
PATH helper, policy wrapper, native systemd condition and exclusive permit. Install
only the nine selected plugins/settings; bind only .51/::51 TCP 4949 and allow
only master .83/::83. Preserve NTP/GPSD, package expectations and protected files.
Execute nine installed munin-run config/fetch pairs locally (bounded); missing
job records remain faults, never synthetic successes. Require native literal
listeners, exact installed sources/settings/links and NTP continuity. Independent
controller TCP-connect checks use both literal families; application protocol
collection from the allowed master is a separate master stage. No master contact,
registration, scheduler or notification. Failed local or TCP acceptance invokes
only authored service containment; packages/guard/backups remain.''' if node else '''Install only the fixed root-owned helper and rendered reporter/retention rule.
Acquire existing reporter and global logrotate locks nonblocking; do not create
lock files, run jobs, rotate logs or acquire unrelated locks. Save exact original
bytes privately; install helper first and then hooks through atomic replace/fsync.
Provision /var/lib/needrestart-reporting root:root 0700; preserve retention state.
The rule invokes real four-stream 30-day cleanup before success recording; the
reporter records only after a real quiet/actionable scan succeeds, after any
required mail submission. Tests, lock skips and failures do not advance records.
No synthetic records, package action, schedule/service restart, real scan or mail.
Use actual scheduled completions to accept each record later. Restore only
matching authored hooks/helper on failure, retaining genuine records/evidence.'''
    return f'''# Guarded {s['kind']} deployment review

Operation `{s['operation_id']}`. Expires **{expiry}**; start with at least
900 seconds remaining. Approve deployment.tar's exact SHA-256 in sealing.json.
Within the same expiry, consumed-state inspect/recover actions require no new
900-second installation reserve. After expiry, stop for a fresh scoped review.
Target ama@10.1.0.51, pinned Ed25519 alias 10.1.0.137; j2-svntp1 boot
{s['worker']['boot_id']}. Every executable, configuration, inventory/package input,
specification and this review is inside the closed archive. The baseline capture
hash is {s['baseline_capture_sha256']}. Preparation makes no target contact.

## Scope and ordered acceptance

{scope}

Recheck root/host/boot, exact 701-package inventory, time-service identity and
protected NTP hashes before mutations. Drift stops; do not refresh pins silently.
Root-private staging /var/lib/ntp-munin-stages/{s['operation_id']} is exclusive.
The worker records durable intent/state and exact backups. Remote 600-second
alarm, bounded subprocesses and outer 780-second transport apply; no automatic
retry. Unknown transport outcome is held for read-only inspection, never replay.
Node independent TCP checks do not prove master-origin scheduled collection or
fresh graphs. Producer installation does not prove a successful scheduled job.

## Execution and recovery

Use the frozen controller after exact-hash approval:

```bash
python3 -I -B DIRECTORY/runner.py execute --directory DIRECTORY --sha256 APPROVED_SHA256
```

One local execution.json is consumed before strict-key SSH; no proxy/forwarding,
TOFU, host-key updates or connection sharing. Caught apply/acceptance failures
attempt only the reviewed conditional worker recovery and stop. For node recovery,
remove only the authored permit, stop/disable munin-node and restore only matching
policy bytes; retain installed packages and guard. For producers restore matching
before hashes/metadata; preserve foreign drift and genuine success records.
Recovery must report contained/restored plus unchanged NTP identity, otherwise
hold. Missing/foreign state or unverified recovery never authorizes overwrite.
If the connection is lost, the same consumed operation permits one bounded
read-only `inspect` action; it cannot apply/clear guards or confirm success.
A later manual `recover` action needs explicit scoped authorization of the same
archive and known state; do not infer restoration from timeout or service exit.
No reboot, firewall/controller/DNS/network/Apache/master change, package purge,
notification test or cleanup. Ordinary logs/caches may be written. Retain all
private output/backups and consumed receipts. Stage health does not close
OBS-02/OBS-07, actual records, scheduled dual-family polling/graphs, downstream
alert delivery, physical persistence or later mandatory separate-host ntpviz.

Deploy producers before node if using both captured 701-package inventories;
producer changes no package inventory. The node's package installation would
invalidate the producer's original inventory pin, requiring a new review.
'''


def root_action(raw,digest,action):
    if os.geteuid()!=0:raise ValueError('root required')
    s,files=archive_files(raw,digest,900 if action=='apply' else 0);stage=STAGES/s['operation_id']
    if action not in ('apply','inspect','recover'):raise ValueError('stage action')
    def timeout(signum,frame):raise TimeoutError('stage alarm expired')
    signal.signal(signal.SIGALRM,timeout);signal.signal(signal.SIGTERM,timeout);signal.alarm(600)
    pins=s['worker']
    if (os.getegid()!=0 or socket.gethostname()!=pins['hostname']
            or Path('/proc/sys/kernel/random/boot_id').read_text().strip()!=pins['boot_id']):raise ValueError('stage host/boot mismatch')
    ns={'__name__':'stage_worker','__file__':str(stage/'worker.py')};exec(compile(files['worker.py'],ns['__file__'],'exec'),ns)
    if s['kind']=='resume':
        base_ns={'__name__':'resume_base','__file__':str(stage/'base.py')}
        exec(compile(files['base.py'],base_ns['__file__'],'exec'),base_ns)
        base=types.SimpleNamespace(**base_ns)
        ns.update(Installer=ns['make_worker'](base),PACKAGE_PLUGINS=base.PACKAGE_PLUGINS,
                  CUSTOM_PLUGINS=base.CUSTOM_PLUGINS,read=base.secure)
    w=types.SimpleNamespace(**ns);wd=sha(encoded(pins));obj=w.Installer(pins,wd)
    if action!='recover':obj.continuity()
    if action=='apply':
        if s['kind']!='resume':
            inventory=obj.command(['/usr/bin/dpkg-query','-W','-f=${binary:Package}\t${Version}\t${Architecture}\t${db:Status-Abbrev}\n'])
            if sha(inventory.encode())!=pins['package_inventory_sha256']:raise ValueError('stage package inventory drift')
        for parent in STAGES.parents:
            meta=parent.lstat()
            if not stat.S_ISDIR(meta.st_mode) or meta.st_uid!=0 or meta.st_mode&0o022:raise ValueError('unsafe staging ancestry')
        if not STAGES.exists():STAGES.mkdir(mode=0o700)
        m=STAGES.lstat()
        if not stat.S_ISDIR(m.st_mode) or m.st_uid!=0 or stat.S_IMODE(m.st_mode)!=0o700:raise ValueError('unsafe staging parent')
        stage.mkdir(mode=0o700)
        for n,data in files.items():
            p=stage/n;p.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
            with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
        directories={stage,STAGES,STAGES.parent}
        for n in files:
            directories.update(parent for parent in (stage/n).parents if parent==stage or stage in parent.parents)
        for directory in sorted(directories,key=lambda path:len(path.parts),reverse=True):
            fd=os.open(directory,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
            try:os.fsync(fd)
            finally:os.close(fd)
    else:
        for parent in (stage,STAGES,*STAGES.parents):
            meta=parent.lstat()
            if not stat.S_ISDIR(meta.st_mode) or meta.st_uid!=0 or meta.st_mode&0o022:raise ValueError('unsafe staged ancestry')
        for n,data in files.items():
            p=stage/n
            if p.is_symlink() or p.read_bytes()!=data:raise ValueError('staged source drift')
    if action in ('inspect','recover'):
        obj.state=json.loads(w.secure(obj.root/'state.json')[0] if s['kind']=='node' else w.read(obj.root/'state.json')[0])
        if obj.state['spec_sha256']!=wd:raise ValueError('state digest drift')
        if action=='inspect':
            obj.continuity();signal.alarm(0)
            return {k:obj.state.get(k) for k in ('phase','accepted','recovery','recovery_errors')}
        recovered=obj.recover()
        signal.alarm(0)
        return {k:recovered.get(k) for k in ('phase','accepted','recovery','recovery_errors')}
    try:
        obj.install()
        if s['kind']=='node':
            for name in (*w.PACKAGE_PLUGINS,*w.CUSTOM_PLUGINS):
                for args in ([name,'config'],[name]):
                    output=obj.command(['/usr/sbin/munin-run',*args])
                    if ('graph_title ' if len(args)==2 else '.value ') not in output:raise ValueError('installed plugin output invalid')
                    if len(args)==1 and name=='ntp_health':
                        for field in ('query_ok','synced','pps_selected'):
                            if field+'.value 1' not in output.splitlines():raise ValueError('live time parser/health acceptance failed')
            obj.continuity()
        return {'accepted':True,'phase':obj.state['phase'],'kind':s['kind'],'operation_id':s['operation_id'],
                'archive_sha256':digest,'polling_accepted':False,'delivery_accepted':False}
    except BaseException:
        if obj.owns_root:obj.recover()
        raise
    finally:signal.alarm(0)


def execute(args,h):
    d=args.directory.absolute();raw=h.private(d/'deployment.tar',MAXIMUM)
    s,files=archive_files(raw,args.sha256,900 if args.action=='execute' else 0)
    if files['runner.py']!=Path(__file__).read_bytes():raise ValueError('frozen runner required')
    for n,data in files.items():
        if h.private(d/n,16*1048576)!=data:raise ValueError('local frozen input drift')
    action={'execute':'apply','inspect':'inspect','recover':'recover'}[args.action]
    if action!='apply':
        if json.loads(h.private(d/'execution.json'))['sha256']!=args.sha256:raise ValueError('same consumed stage required')
    receipt=d/('execution.json' if action=='apply' else action+'.json')
    payload=b"__name__='sealed_stage'\n__file__='/sealed/runner.py'\n"+files['runner.py']+b'\nprint(json.dumps(root_action('+repr(raw).encode()+b','+repr(args.sha256).encode()+b','+repr(action).encode()+b')))\n'
    argv=h.ssh_argv({'endpoints':['10.1.0.51'],'host_key_alias':'10.1.0.137'},d)
    with receipt.open('xb') as f:f.write(encoded({'sha256':args.sha256,'argv':argv,'payload_sha256':sha(payload),'epoch':time.time()}));f.flush();os.fsync(f.fileno())
    try:row=h.bounded(argv,timeout=780,limit=16*1048576,payload=payload,env=os.environ.copy())
    except OSError as error:row={'returncode':None,'error':str(error),'stdout':'','stderr':''}
    for n in ('stdout','stderr'):(d/(action+'-'+n+'.txt')).write_text(row.pop(n))
    row['archive_sha256']=args.sha256
    if row.get('returncode')==0 and not row.get('error'):
        try:row['result']=json.loads((d/(action+'-stdout.txt')).read_text())
        except (ValueError,TypeError):
            row.update(error='invalid remote result; inspect consumed state',returncode=2)
            (d/(action+'-result.json')).write_bytes(encoded(row));return row
        if action=='apply' and (not isinstance(row['result'],dict) or row['result'].get('accepted') is not True
                or row['result'].get('kind')!=s['kind'] or row['result'].get('operation_id')!=s['operation_id']
                or row['result'].get('archive_sha256')!=args.sha256):
            row.update(error='unaccepted remote result; inspect consumed state',returncode=2)
            (d/(action+'-result.json')).write_bytes(encoded(row));return row
        if action=='apply' and s['kind'] in ('node','resume'):
            try:
                for family,address in ((socket.AF_INET,'10.1.0.51'),(socket.AF_INET6,'fd36:5aa8:6971:1::51')):
                    with socket.socket(family,socket.SOCK_STREAM) as connection:connection.settimeout(5);connection.connect((address,4949))
                row['independent_tcp_families']=[4,6]
            except OSError:
                row['independent_tcp_families_failed']=True
                # This is a known post-install acceptance failure, not an ambiguous apply replay.
                payload=b"__name__='sealed_stage'\n__file__='/sealed/runner.py'\n"+files['runner.py']+b'\nprint(json.dumps(root_action('+repr(raw).encode()+b','+repr(args.sha256).encode()+b",'recover')))\n"
                recovery=h.bounded(argv,timeout=180,limit=1048576,payload=payload,env=os.environ.copy())
                (d/'tcp-recovery.json').write_bytes(encoded(recovery));row['returncode']=2
    (d/(action+'-result.json')).write_bytes(encoded(row));return row


def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='action',required=True)
    q=sub.add_parser('seal');q.add_argument('--kind',choices=('node','producers'),required=True);q.add_argument('--baseline',type=Path,required=True);q.add_argument('--output',type=Path,required=True)
    q.add_argument('--packages',type=Path);q.add_argument('--qualification',type=Path)
    q=sub.add_parser('seal-resume');q.add_argument('--source-stage',type=Path,required=True)
    q.add_argument('--source-sha256',required=True);q.add_argument('--selection',type=Path,required=True)
    q.add_argument('--retained',type=Path,required=True);q.add_argument('--output',type=Path,required=True)
    for action in ('check','execute','inspect','recover'):
        q=sub.add_parser(action);q.add_argument('--directory',type=Path,required=True);q.add_argument('--sha256',required=True)
    a=p.parse_args();os.umask(0o077)
    if a.action=='seal':result=seal(a)
    elif a.action=='seal-resume':result=seal_resume(a)
    else:
        raw=(a.directory/'deployment.tar').read_bytes()
        _,files=archive_files(raw,a.sha256,0 if a.action in ('inspect','recover') else 900)
        if a.action=='check':
            for n,data in files.items():
                if (a.directory/n).is_symlink() or (a.directory/n).read_bytes()!=data:raise ValueError('local frozen input drift')
            result={'verified':True,'target_contact':False}
        else:
            ns={'__name__':'helper','__file__':'/sealed/helper.py'};exec(compile(files['helper.py'],ns['__file__'],'exec'),ns)
            result=execute(a,types.SimpleNamespace(**ns))
    print(json.dumps(result))
    if a.action in ('execute','inspect','recover') and (result.get('returncode')!=0 or result.get('result',{}).get('recovery')=='held'):raise SystemExit(1)


if __name__=='__main__':main()
