#!/usr/bin/python3
"""Seal offline, then run one separately approved, bounded GPSD observation."""
import argparse
import base64
from decimal import Decimal
import fcntl
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
import sys
import tarfile
import time

ROOT = Path(__file__).resolve().parents[1]
ENV = {'PATH': '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
       'LC_ALL': 'C', 'HOME': '/root', 'PYTHONDONTWRITEBYTECODE': '1'}
INPUTS = {'worker.py', 'runtime.tar', 'runtime-acceptance.json', 'runtime-cleanup.json',
          'recipe.json', 'architecture.md', 'operations.md', 'history.md', 'tests.py',
          'transport.py', 'known_hosts', 'prior.tar', 'prior-acceptance.json', 'prior-cleanup.json',
          'prior-terminal.json', 'prior-restoration.json', 'prior-shm-after.txt'}


def encoded(value):
    return (json.dumps(value, sort_keys=True)+'\n').encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def load(path):
    info = importlib.util.spec_from_file_location('acquisition_'+path.stem.replace('-', '_'), path)
    result = importlib.util.module_from_spec(info); info.loader.exec_module(result)
    return result


def unpack(raw):
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:') as archive:
        items = archive.getmembers()
        if (len(items) > 80 or len({x.name for x in items}) != len(items)
                or any(not x.isfile() or not re.fullmatch(r'[a-z][a-z0-9._-]+', x.name)
                       or x.size > 8*1024**2 for x in items)):
            raise ValueError('bounded regular archive required')
        files = {x.name: archive.extractfile(x).read() for x in items}
    if json.loads(files['manifest.json']) != {n: sha(v) for n, v in files.items() if n != 'manifest.json'}:
        raise ValueError('archive manifest mismatch')
    return files


def validate_recipe(r):
    if (r['schema'] != 2 or r.get('pairing_min_samples') != 60 or r['duration_seconds'] != 900 or r['runtime_max_seconds'] != 1080
            or r['log_limit_bytes'] != 8388608
            or r['gpsd'] != ['/usr/local/sbin/gpsd','-b','-N','-n','-D','3','-s','115200','/dev/serial0','/dev/pps0']
            or r['gpspipe'] != ['/usr/local/bin/gpspipe','-B','-w','-P','-x','900','127.0.0.1:2947']
            or r['ntpshmmon'] != ['/usr/local/bin/ntpshmmon','-t','900']):
        raise ValueError('closed bounded receiver-read-only acquisition recipe required')


def validate(spec, files):
    old = unpack(files['runtime.tar']); runtime = json.loads(old['spec.json'])
    receipt = json.loads(files['runtime-acceptance.json']); cleanup = json.loads(files['runtime-cleanup.json'])
    state = cleanup['result']; recipe = json.loads(files['recipe.json']); validate_recipe(recipe)
    if (spec['schema'] != 2 or not re.fullmatch('[a-z][a-z0-9-]{0,47}', spec['operation_id'])
            or spec['stage'] != '/var/lib/ntp-acquire-'+spec['operation_id']
            or spec['unit'] != 'ntp-acquire-'+spec['operation_id']+'.service'
            or runtime['operation'] != 'runtime' or runtime['hostname'] != spec['hostname']
            or runtime['kernel'] != spec['kernel'] or runtime['stage'] != spec['source_stage']
            or spec['runtime_sha256'] != sha(files['runtime.tar'])
            or receipt['state'] != 'runtime_configuration_accepted'
            or receipt['spec_sha256'] != sha(old['spec.json'])
            or receipt['bundle_sha256'] != spec['runtime_sha256']
            or receipt['boot_id'] != spec['boot_id'] or state['accepted_boot_id'] != spec['boot_id']
            or cleanup['bundle_sha256'] != spec['runtime_sha256'] or state['phase'] != 'accepted'
            or state.get('transient_units_cleaned') is not True
            or receipt['checks'] != state['checks'] or any(v is not True for v in state['checks'].values())
            or receipt['hardware'] != state['hardware']
            or set(state['ssh_proofs']) != set(spec['endpoints'])
            or spec['endpoints'] != [runtime['recipe'][k].split('/')[0] for k in ('ipv4_address','ipv6_address')]
            or spec['old_ipv4'] != runtime['old_ipv4']
            or not 0 < spec['expires_epoch']-spec['prepared_epoch'] <= 86400
            or spec['members'] != {n: sha(files[n]) for n in INPUTS}):
        raise ValueError('accepted runtime/identity/boot/input binding required')
    validate_prior(spec, files)
    return runtime, old


def validate_prior(spec, files):
    prior = unpack(files['prior.tar']); previous = json.loads(prior['spec.json'])
    receipt = json.loads(files['prior-acceptance.json']); cleanup = json.loads(files['prior-cleanup.json'])
    terminal = json.loads(files['prior-terminal.json']); restoration = json.loads(files['prior-restoration.json'])
    if (previous['schema'] != 1 or previous['stage'] == spec['stage']
            or any(previous[k] != spec[k] for k in ('hostname','kernel','boot_id','runtime_sha256','endpoints'))
            or receipt['state'] != 'acquisition_capture_accepted'
            or receipt['bundle_sha256'] != sha(files['prior.tar'])
            or receipt['spec_sha256'] != sha(prior['spec.json'])
            or not re.fullmatch('[a-f0-9]{64}', receipt['report_sha256'])
            or cleanup['spec_sha256'] != sha(prior['spec.json'])
            or cleanup['result'] != {'phase':'cleaned','evidence_preserved':True,'shm_preserved':True,
                                     'terminal_sha256':sha(files['prior-terminal.json'])}
            or terminal['phase'] != 'captured' or restoration['restored'] is not True
            or restoration['boot_id'] != spec['boot_id']):
        raise ValueError('accepted prior capture/restoration/cleanup required')
    return prior, previous


def shm_inventory(raw):
    lines = raw.decode().splitlines()
    if not lines: raise ValueError('SHM header required')
    columns = lines[0].split(); keys = ('key','shmid','perms','size','cpid','uid','gid','cuid','cgid')
    if any(k not in columns for k in (*keys,'nattch')): raise ValueError('SHM metadata schema required')
    result = {}
    for line in lines[1:]:
        values = line.split()
        if len(values) != len(columns): raise ValueError('complete SHM metadata required')
        row = dict(zip(columns,values))
        if row['nattch'] != '0' or row['shmid'] in result: raise ValueError('unattached unique SHM segments required')
        result[row['shmid']] = {k:row[k] for k in keys}
    return result


def prior_guard(h, spec, files):
    prior, previous = validate_prior(spec,files); root = Path(previous['stage']); h.ancestors(root)
    if stat.S_IMODE(root.stat().st_mode) != 0o700 or h.read(root/'spec.json') != prior['spec.json']:
        raise ValueError('prior protected stage/specification drift')
    for name,digest in previous['members'].items():
        if sha(h.read(root/name)) != digest: raise ValueError('prior executed input drift')
    for name in ('terminal.json','restoration.json','shm-after.txt'):
        if h.read(root/name) != files['prior-'+name]: raise ValueError('prior capture evidence drift')
    if shm_inventory(Path('/proc/sysvipc/shm').read_bytes()) != shm_inventory(files['prior-shm-after.txt']):
        raise ValueError('SHM ownership/membership/attachment drift since accepted capture')


def pairing_evidence(gps_json, shm_text):
    """Correlate explicit-device reports with independently sampled SHM timestamps."""
    rows = [json.loads(line) for line in gps_json.splitlines() if line.strip()]
    watches = [r for r in rows if r.get('class') == 'WATCH']
    if not watches or any(r.get('pps') is not True for r in watches):
        return {'observed':False,'reason':'PPS watch acknowledgement missing'}
    samples = set()
    for line in shm_text.splitlines():
        fields = line.split()
        if not fields or fields[0] != 'sample': continue
        if len(fields) != 7: raise ValueError('malformed SHM sample')
        if fields[5] == '0':
            samples.add((fields[1],int(Decimal(fields[3])*1000000000),int(Decimal(fields[4])*1000000000)))
    units = {}; matched = {}; summary = {}
    for kind,path in (('TOFF','/dev/serial0'),('PPS','/dev/pps0')):
        reports = [r for r in rows if r.get('class') == kind]
        if not reports or any(r.get('device') != path for r in reports):
            return {'observed':False,'reason':'missing or ambiguous '+kind+' device'}
        names = {r.get('shm') for r in reports}
        if len(names) != 1 or not re.fullmatch(r'NTP[0-9]+',next(iter(names)) or ''):
            return {'observed':False,'reason':'ambiguous '+kind+' SHM unit'}
        unit = next(iter(names)); units[kind] = unit; pairs = set()
        for r in reports:
            fields = ('clock_sec','clock_nsec','real_sec','real_nsec')
            if any(type(r.get(k)) is not int for k in fields): raise ValueError('integer JSON timestamps required')
            if not all(0 <= r[k] < 1000000000 for k in ('clock_nsec','real_nsec')): raise ValueError('nanosecond range')
            pair = (unit,r['clock_sec']*1000000000+r['clock_nsec'],r['real_sec']*1000000000+r['real_nsec'])
            if pair in samples: pairs.add(pair)
        matched[kind] = len(pairs)
        summary[kind] = {'device':path,'unit':unit,'matching_samples':len(pairs)}
    observed = len(set(units.values())) == 2 and all(n >= 60 for n in matched.values())
    return {'observed':observed,'sources':summary,'reason':None if observed else 'insufficient or overlapping matched sources',
            'timing_accuracy_accepted':False}


def run(argv, timeout=20):
    return subprocess.run(argv, check=True, capture_output=True, timeout=timeout, env=ENV).stdout.decode()


def serial_identity():
    path = Path('/dev/serial0'); target = path.resolve(strict=True); info = target.stat()
    if not path.is_symlink() or str(target) != '/dev/ttyAMA0' or not stat.S_ISCHR(info.st_mode):
        raise ValueError('accepted serial0/PL011 character device required')
    return {'target': str(target), 'rdev': info.st_rdev, 'ino': info.st_ino,
            'uid': info.st_uid, 'gid': info.st_gid, 'mode': stat.S_IMODE(info.st_mode)}


def idle():
    # An unrelated client/device user makes termios restoration unsafe.
    for p in Path('/proc').iterdir():
        if not p.name.isdecimal() or int(p.name) == os.getpid():
            continue
        try:
            if (p/'comm').read_text().strip() in ('gpsd','ntpd','chronyd'):
                raise ValueError('competing time process')
            for fd in (p/'fd').iterdir():
                try: target = os.readlink(fd)
                except FileNotFoundError: continue
                if target in ('/dev/ttyAMA0','/dev/serial0','/dev/pps0'):
                    raise ValueError('device already in use')
        except FileNotFoundError:
            continue
    if run(['/usr/bin/ss','-H','-ltn','sport = :2947']).strip():
        raise ValueError('GPSD TCP port already bound')
    for path in ('/etc/gpsd/device-hook','/usr/local/etc/gpsd/device-hook'):
        if os.path.lexists(path):
            raise ValueError('unreviewed GPSD device hook')


def source_guard(h, spec, old):
    root = Path(spec['source_stage']); h.ancestors(root)
    if stat.S_IMODE(root.stat().st_mode) != 0o700:
        raise ValueError('private runtime source required')
    fd = os.open(root/'.lock', os.O_RDONLY | os.O_NOFOLLOW)
    try:
        fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        runtime = json.loads(old['spec.json'])
        for name, digest in runtime['members'].items():
            if sha(h.read(root/name)) != digest:
                raise ValueError('retained runtime member drift')
        if h.read(root/'spec.json') != old['spec.json']:
            raise ValueError('retained runtime specification drift')
        retained = {name: h.read(root/name) for name in
                    ('state.json','before.json','commands.jsonl','timeservice-candidate.json','timeservice.service')}
        return fd, retained
    except BaseException:
        os.close(fd); raise


def context(h, spec, files, create=False):
    runtime, old = validate(spec, files); root = Path(spec['stage'])
    fd, retained = source_guard(h, spec, old)
    try:
        expected = json.loads(files['runtime-cleanup.json'])['result']
        if json.loads(retained['state.json']) != expected:
            raise ValueError('accepted runtime state changed')
        sub = root/'runtime-check'; runtime = dict(runtime, stage=str(sub))
        if create:
            sub.mkdir(mode=0o700)
            for name in runtime['members']:
                h.create(sub/name, old[name])
            for name, raw in retained.items():
                h.create(sub/name, raw)
            h.create(sub/'spec.json', encoded(runtime))
        else:
            for name, digest in runtime['members'].items():
                if sha(h.read(sub/name)) != digest:
                    raise ValueError('runtime validation helper drift')
        stage = load(sub/'host-configuration-stage.py')
        transaction = stage.Transaction(runtime)
        transaction.probe()
        if any(h.read(Path(spec['source_stage'])/n) != raw for n, raw in retained.items()):
            raise ValueError('original accepted source changed')
    finally:
        os.close(fd)


def unit_command(spec):
    script = spec['stage']+'/worker.py'
    return ['/usr/bin/systemd-run','--quiet','--unit='+spec['unit'],
            '--property=Type=exec','--property=Restart=no','--property=UMask=0077',
            '--property=RuntimeMaxSec=1080','--property=TimeoutStopSec=20',
            '--property=KillMode=control-group','--property=LimitFSIZE=8388608',
            '--property=WorkingDirectory='+spec['stage'],
            '--property=ExecStopPost=/usr/bin/python3 -I -B '+script+' worker restore',
            '/usr/bin/python3','-I','-B',script,'worker','capture']


def restore(h, spec):
    root = Path(spec['stage'])
    before = json.loads(h.read(root/'serial-before.json'))
    if Path('/proc/sys/kernel/random/boot_id').read_text().strip() != spec['boot_id'] or serial_identity() != before['identity']:
        raise ValueError('UART identity/boot drift; preserve recovery evidence')
    idle()
    run(['/usr/bin/stty','-F','/dev/serial0',before['termios']])
    if run(['/usr/bin/stty','-F','/dev/serial0','-g']).strip() != before['termios']:
        raise ValueError('UART settings not restored')
    result = {'restored': True, 'boot_id': spec['boot_id'], 'identity': before['identity']}
    if (root/'restoration.json').exists():
        if json.loads(h.read(root/'restoration.json')) != result:
            raise ValueError('restoration record conflict')
    else:
        h.create(root/'restoration.json', encoded(result))


def capture(h, spec, files):
    root = Path(spec['stage']); recipe = json.loads(files['recipe.json'])
    h.create(root/'capture-claim.json', encoded({'started_epoch': int(time.time())}))
    processes = []; logs = []; statuses = {}; failure = None
    def interrupted(signum, frame):
        raise InterruptedError('bounded acquisition interrupted')
    for sig in (signal.SIGINT, signal.SIGTERM): signal.signal(sig, interrupted)
    started = time.monotonic()
    try:
        idle(); prior_guard(h,spec,files)
        h.create(root/'shm-before.txt', Path('/proc/sysvipc/shm').read_bytes())
        run(['/usr/bin/stty','-F','/dev/serial0','raw','115200','cs8','-parenb','clocal','-cstopb','-crtscts'])
        for name in ('gpsd','gpspipe','ntpshmmon'):
            if name == 'gpspipe':
                deadline = time.monotonic()+15
                while True:
                    if processes[0].poll() is not None: raise ValueError('GPSD exited before collection')
                    try:
                        with socket.create_connection(('127.0.0.1',2947),timeout=1): break
                    except OSError:
                        if time.monotonic() >= deadline: raise ValueError('GPSD loopback readiness timeout')
                        time.sleep(0.25)
            out = (root/(name+'.stdout')).open('xb'); err = (root/(name+'.stderr')).open('xb')
            logs.extend((out,err))
            processes.append(subprocess.Popen(recipe[name],stdout=out,stderr=err,env=ENV))
        listeners = run(['/usr/bin/ss','-H','-ltn','sport = :2947'])
        h.create(root/'listeners.txt', listeners.encode())
        for line in listeners.splitlines():
            if line.split()[3] not in ('127.0.0.1:2947','[::1]:2947','::1:2947'):
                raise ValueError('non-loopback GPSD listener')
        statuses['gpspipe'] = processes[1].wait(timeout=930)
        statuses['ntpshmmon'] = processes[2].wait(timeout=20)
        if any(statuses.values()) or processes[0].poll() is not None:
            raise ValueError('acquisition child failure')
        h.create(root/'gpsd-process.txt', Path('/proc/'+str(processes[0].pid)+'/status').read_bytes())
        if time.monotonic()-started < recipe['duration_seconds']:
            raise ValueError('incomplete acquisition window')
    except BaseException as error:
        failure = str(error)[:500]
    finally:
        for sig in (signal.SIGINT, signal.SIGTERM): signal.signal(sig, signal.SIG_IGN)
        for p in processes:
            if p.poll() is None: p.terminate()
        for p in processes:
            try: p.wait(timeout=5)
            except subprocess.TimeoutExpired: p.kill(); p.wait(timeout=5)
        for stream in logs: stream.close()
        h.create(root/'shm-after.txt', Path('/proc/sysvipc/shm').read_bytes())
        h.create(root/'terminal.json', encoded({'phase': 'captured' if failure is None else 'held',
                 'error': failure, 'child_statuses': statuses, 'elapsed_seconds': time.monotonic()-started,
                 'receiver_timing_accepted': False, 'shm_mapping_accepted': False}))
    # ExecStopPost owns restoration, including process crash and timeout paths.


def bootstrap(spec, files):
    _, old = validate(spec, files)
    ns = {'__name__': 'protected_helper'}
    exec(compile(old['foundation-install.py'],'sealed-helper','exec'), ns)
    import types
    return types.SimpleNamespace(**ns)


def identity(spec):
    if (os.geteuid() != 0 or socket.gethostname() != spec['hostname'] or os.uname().release != spec['kernel']
            or Path('/proc/sys/kernel/random/boot_id').read_text().strip() != spec['boot_id']):
        raise ValueError('approved root/target/kernel/boot required')


def entry(spec, files, mode):
    identity(spec); h = bootstrap(spec, files); root = Path(spec['stage']); os.umask(0o077)
    if mode == 'start':
        if (os.environ.get('SUDO_USER') != 'ama' or os.environ.get('SUDO_UID') != '1000'
                or os.environ.get('SUDO_GID') != '1000'
                or not spec['prepared_epoch']-300 <= time.time() < spec['expires_epoch']):
            raise ValueError('approved caller/window required')
        h.ancestors(root.parent); root.mkdir(mode=0o700)
        for name, raw in {**files, 'spec.json': encoded(spec)}.items(): h.create(root/name, raw)
        context(h,spec,files,create=True); idle(); prior_guard(h,spec,files)
        h.create(root/'serial-before.json', encoded({'identity': serial_identity(),
                 'termios': run(['/usr/bin/stty','-F','/dev/serial0','-g']).strip()}))
        h.create(root/'start.json', encoded({'submitted_epoch': int(time.time())}))
        run(unit_command(spec))
        return {'phase': 'started', 'unit': spec['unit']}
    h.ancestors(root)
    if stat.S_IMODE(root.stat().st_mode) != 0o700 or h.read(root/'spec.json') != encoded(spec):
        raise ValueError('protected stage/specification required')
    for name, digest in spec['members'].items():
        if sha(h.read(root/name)) != digest: raise ValueError('stage input drift')
    if mode == 'recover':
        # No acquisition replay: stop only the exact operation unit, then restore.
        run(['/usr/bin/systemctl','stop',spec['unit']],timeout=45)
        restore(h,spec)
        return {'phase': 'restored', 'acquisition_replayed': False}
    active = run(['/usr/bin/systemctl','show','--property=ActiveState','--value',spec['unit']]).strip()
    if active not in ('inactive','failed'):
        return {'phase': 'pending', 'unit_state': active}
    if mode not in ('readback','cleanup'): raise ValueError('closed mode required')
    restoration = json.loads(h.read(root/'restoration.json'))
    before = json.loads(h.read(root/'serial-before.json'))
    idle()
    if (restoration.get('restored') is not True or serial_identity() != before['identity']
            or run(['/usr/bin/stty','-F','/dev/serial0','-g']).strip() != before['termios']):
        raise ValueError('restored idle UART required')
    context(h,spec,files)
    prior_guard(h,spec,files)
    if shm_inventory(h.read(root/'shm-after.txt')) != shm_inventory(files['prior-shm-after.txt']):
        raise ValueError('retained SHM segment identity or ownership changed')
    terminal = json.loads(h.read(root/'terminal.json'))
    pairing = pairing_evidence(h.read(root/'gpspipe.stdout').decode(), h.read(root/'ntpshmmon.stdout').decode())
    evidence = {}
    for name in ('gpsd.stdout','gpsd.stderr','gpspipe.stdout','gpspipe.stderr','ntpshmmon.stdout',
                 'ntpshmmon.stderr','gpsd-process.txt','listeners.txt','shm-before.txt','shm-after.txt','terminal.json','restoration.json','serial-before.json'):
        raw = h.read(root/name,limit=8388608)
        evidence[name] = {'sha256': sha(raw), 'base64': base64.b64encode(raw).decode()}
    if mode == 'cleanup':
        # Evidence and IPC remain. Only operation-owned transient unit state is retired.
        if active == 'failed': run(['/usr/bin/systemctl','reset-failed',spec['unit']])
        return {'phase': 'cleaned', 'evidence_preserved': True, 'shm_preserved': True,
                'terminal_sha256': evidence['terminal.json']['sha256']}
    return {'phase': terminal['phase'], 'hostname':spec['hostname'], 'boot_id':spec['boot_id'],
            'restored':True, 'continuity':True, 'evidence':evidence, 'pairing':pairing}


def payload(spec, files, mode):
    return ('import base64,json\nfiles={n:base64.b64decode(v) for n,v in '+repr(
        {n:base64.b64encode(v).decode() for n,v in files.items() if n in INPUTS})+'.items()}\n'
        'spec=json.loads('+repr(json.dumps(spec))+')\nns={"__name__":"sealed_acquisition","__file__":spec["stage"]+"/worker.py"}\n'
        'exec(compile(files["worker.py"],"sealed-acquisition","exec"),ns)\n'
        'status=0\ntry: result=ns["entry"](spec,files,'+repr(mode)+')\n'
        'except BaseException as e: status=2; result={"phase":"held","error":str(e)[:500]}\n'
        'print(json.dumps({"spec_sha256":ns["sha"](ns["encoded"](spec)),"result":result},sort_keys=True))\n'
        'print("ACQUISITION_EXIT_STATUS="+str(status))\nraise SystemExit(status)\n').encode()


def prepare(bundle, checksum):
    c = load(ROOT/'scripts/run-foundation-preflight.py')
    raw = c.private_file(bundle,32*1024**2)
    if sha(raw) != checksum: raise ValueError('approved acquisition archive required')
    files = unpack(raw); spec = json.loads(files['spec.json'])
    if (set(files) != INPUTS|{'spec.json','manifest.json','review.md'}
            or files['worker.py'] != Path(__file__).read_bytes()
            or files['transport.py'] != (ROOT/'scripts/run-foundation-preflight.py').read_bytes()
            or c.private_file(bundle.parent/'known_hosts',4096) != files['known_hosts']):
        raise ValueError('closed current controller/transport/key inputs required')
    validate(spec,files)
    for mode in ('start','readback','recover','cleanup'): compile(payload(spec,files,mode),'sealed-payload','exec')
    return spec,files


def prior_inputs(c, args):
    directory = args.prior_dir
    raw = c.private_file(directory/'gpsd-acquisition.tar',32*1024**2)
    if sha(raw) != args.prior_sha256: raise ValueError('exact prior acquisition archive required')
    prior = unpack(raw); old = json.loads(prior['spec.json'])
    receipt = c.private_file(directory/'acceptance.json')
    accepted = json.loads(receipt); reports = {}
    for path in sorted(directory.glob('readback-*-result.json')):
        response = json.loads(c.private_file(path,96*1024**2))
        report = response.get('result',{})
        if sha(encoded(report)) == accepted['report_sha256']:
            if response['spec_sha256'] != sha(prior['spec.json']): raise ValueError('prior report spec mismatch')
            submitted = json.loads(c.private_file(directory/(path.name.replace('-result.json','-submission.json'))))
            endpoint = next(x[4:] for x in submitted['argv'] if x.startswith('ama@'))
            if endpoint in old['endpoints']: reports[endpoint] = report
    if set(reports) != set(old['endpoints']): raise ValueError('prior dual-endpoint accepted evidence required')
    report = next(iter(reports.values()))
    files = {'prior.tar':raw,'prior-acceptance.json':receipt,
             'prior-cleanup.json':c.private_file(directory/'cleanup-0-result.json')}
    for name in ('terminal.json','restoration.json','shm-after.txt'):
        row = report['evidence'][name]; data = base64.b64decode(row['base64'],validate=True)
        if sha(data) != row['sha256']: raise ValueError('prior evidence hash mismatch')
        files['prior-'+name] = data
    return files


def seal(args):
    c = load(ROOT/'scripts/run-foundation-preflight.py'); host = load(ROOT/'scripts/run-host-configuration.py')
    raw = c.private_file(args.runtime_dir/'host-configuration.tar',32*1024**2)
    if sha(raw) != args.runtime_sha256: raise ValueError('runtime archive hash mismatch')
    old = unpack(raw); runtime = json.loads(old['spec.json']); host.validate(old,runtime)
    cleanup = c.private_file(args.runtime_dir/'cleanup-result.json')
    receipt = c.private_file(args.runtime_dir/'acceptance.json')
    if json.loads(receipt) != host.acceptance_receipt(runtime,args.runtime_sha256,json.loads(cleanup)['result']):
        raise ValueError('complete runtime acceptance receipt required')
    files = {'worker.py':Path(__file__).read_bytes(),'runtime.tar':raw,'runtime-acceptance.json':receipt,
             'runtime-cleanup.json':cleanup,'known_hosts':old['known_hosts'],
             'transport.py':(ROOT/'scripts/run-foundation-preflight.py').read_bytes(),
             'tests.py':(ROOT/'tests/test_gpsd_acquisition.py').read_bytes(),
             'recipe.json':(ROOT/'configs/gpsd-acquisition-recipe.json').read_bytes()}
    for n,p in [('architecture.md','docs/ntp-architecture-deployment-plan-v1.0.md'),
                ('operations.md','docs/OPERATIONS.md'),('history.md','HISTORY.md')]: files[n]=(ROOT/p).read_bytes()
    files.update(prior_inputs(c,args))
    epoch=int(time.time()); spec={'schema':2,'operation_id':args.operation_id,
        'stage':'/var/lib/ntp-acquire-'+args.operation_id,'unit':'ntp-acquire-'+args.operation_id+'.service',
        'hostname':runtime['hostname'],'kernel':runtime['kernel'],'boot_id':json.loads(receipt)['boot_id'],
        'old_ipv4':runtime['old_ipv4'],'source_stage':runtime['stage'],'runtime_sha256':args.runtime_sha256,
        'endpoints':[runtime['recipe'][k].split('/')[0] for k in ('ipv4_address','ipv6_address')],
        'prepared_epoch':epoch,'expires_epoch':min(epoch+86400,json.loads(cleanup)['result']['accepted_epoch']+86400,
             json.loads(old['hardware-cleanup.json'])['result']['accepted_epoch']+86400),
        'members':{n:sha(v) for n,v in files.items()}}
    validate(spec,files)
    files['spec.json']=encoded(spec)
    files['review.md']=review(spec).encode()
    files['manifest.json']=encoded({n:sha(v) for n,v in files.items()})
    os.umask(0o077);args.output.mkdir(mode=0o700)
    for n in ('spec.json','review.md','known_hosts'): (args.output/n).write_bytes(files[n])
    bundle=args.output/'gpsd-acquisition.tar'
    with tarfile.open(bundle,'w',format=tarfile.USTAR_FORMAT) as archive:
        for n,data in sorted(files.items()):
            item=tarfile.TarInfo(n);item.mode=0o600;item.size=len(data);item.mtime=epoch
            archive.addfile(item,io.BytesIO(data))
    digest=sha(bundle.read_bytes());prepare(bundle,digest)
    result={'bundle':str(bundle),'sha256':digest,'target':spec['hostname'],'expires_epoch':spec['expires_epoch'],
            'target_contact':False,'execution_authorized':False}
    c.write_new(args.output/'sealing.json',result);return result


def review(spec):
    return f'''# Bounded GPSD acquisition: {spec['operation_id']}

Target: **{spec['hostname']}**; boot `{spec['boot_id']}`.
Accepted runtime bundle: `{spec['runtime_sha256']}`.
Prior acquisition capture, restoration, cleanup and SHM inventory are bound as inputs.
Expires at Unix epoch {spec['expires_epoch']}. Preparation contacts no target.

Scope: one foreground GPSD acquisition, receiver read-only (-b), 115200 UART,
one serial source /dev/serial0 and explicit GPIO PPS /dev/pps0, loopback TCP
2947 only, JSON (-P) and SHM monitoring for 900 seconds. This is temporary
GPSD activation and device I/O, not a read-only host snapshot. The only temporary
hardware change is UART termios. No receiver reconfiguration, ntpd, clock step,
bootstrap service change, package/file installation, network change or reboot.
No NTS server is contacted by acquisition. Shared antenna/primary stays untouched.

Root-owned 0700 unique stage and 0600 inputs/logs; accepted source stage is shared
locked and verified, never modified. Native/network/hardware/account/loader
checks run using a private copy before and after observation. A systemd transient
unit bounds worker lifetime to 1080 seconds, with 20-second stop grace and 8 MiB
per-file limit. ExecStopPost restores saved termios after all unit children stop,
including timeout/failure. Power loss or boot/identity drift requires inspection;
there is no automatic recovery across reboot. Preserve all executed evidence.

One start only. Up to 26 numbered readbacks, at least 45 seconds apart, on the two
pinned management endpoints. Complete captures require both endpoints, stopped
GPSD, restored UART and unchanged runtime/network/bootstrap state. Capture acceptance
is not receiver timing or SHM assignment acceptance. Review private JSON, GPSD logs
and SHM samples/ownership before deriving ntp.conf; missing/ambiguous observations
hold final cutover. Correlate TOFF(/dev/serial0) and PPS(/dev/pps0) JSON unit names
and timestamps with at least 60 unique leap-0 SHM samples per source, requiring
distinct units. Pairing observation is not timing-accuracy acceptance. Reject
changed prior SHM membership/ownership or attachments before starting; GPSD may
reuse its retained segments. No guessed unit numbers or explicit IPC reset; normal GPSD writes may reuse
its retained segments. The pinned
GPSD source propagates serial time to PPS-only devices; one serial source keeps
that relationship unambiguous.

Conditional recovery stops only this operation's unit and restores the bound UART
settings. Cleanup retires only its transient unit state; logs, original stages,
and all SHM segments remain. No explicit IPC deletion, blanket process kill, or replay.

Use `python3 -I -B ntpsec/scripts/run-gpsd-acquisition.py execute --bundle
ABSOLUTE_BUNDLE --sha256 APPROVED_HASH --mode start` once. Conditional modes:
`readback --attempt N` (1 through 26), `recover`, and `cleanup`. Each local action
is registered before transport; lost output never authorizes repeating start.
Final NTP configuration/service cutover requires a later separately sealed review.
'''


def execute(args):
    c=load(ROOT/'scripts/run-foundation-preflight.py');bundle=args.bundle.absolute()
    spec,files=prepare(bundle,args.sha256);directory=bundle.parent
    label=args.mode+('-'+str(args.attempt) if args.mode=='readback' else '')
    if args.mode!='start':
        if json.loads(c.private_file(directory/'start-execution.json'))['bundle_sha256']!=args.sha256:
            raise ValueError('registered start required')
    if args.mode=='readback':
        previous=directory/('readback-'+str(args.attempt-1)+'-execution.json')
        if args.attempt>1 and time.time()-json.loads(c.private_file(previous))['epoch']<45:
            raise ValueError('readback interval must be at least 45 seconds')
    if args.mode=='cleanup':
        receipt=json.loads(c.private_file(directory/'acceptance.json'))
        if (receipt['state']!='acquisition_capture_accepted' or receipt['bundle_sha256']!=args.sha256
                or receipt['spec_sha256']!=sha(files['spec.json'])):
            raise ValueError('bound accepted capture required before cleanup')
    c.write_new(directory/(label+'-execution.json'),{'bundle_sha256':args.sha256,'epoch':int(time.time())})
    results={}
    for index,endpoint in enumerate(spec['endpoints'] if args.mode=='readback' else spec['endpoints'][:1]):
        argv=c.transport(directory,endpoint);argv[3]='180s'
        argv[argv.index('ama@'+endpoint):argv.index('ama@'+endpoint)]=['-o','HostKeyAlias='+spec['old_ipv4']]
        data=payload(spec,files,args.mode); stem=label+'-'+str(index)
        c.write_new(directory/(stem+'-submission.json'),{'argv':argv,'payload_sha256':sha(data)})
        with (directory/(stem+'.stdout')).open('xb') as out,(directory/(stem+'.stderr')).open('xb') as err:
            p=subprocess.run(argv,input=data,stdout=out,stderr=err,check=False,
                env={'PATH':'/usr/bin:/bin','LC_ALL':'C','SSH_AUTH_SOCK':os.environ['SSH_AUTH_SOCK']})
        c.write_new(directory/(stem+'-transport.json'),{'status':p.returncode})
        raw=c.private_file(directory/(stem+'.stdout'),96*1024**2)
        match=re.fullmatch(rb'(.*)\nACQUISITION_EXIT_STATUS=([02])\n',raw,re.S)
        if not match:raise ValueError('terminal lost; retain evidence, never repeat start')
        response=json.loads(match[1])
        if p.returncode!=int(match[2]) or response['spec_sha256']!=sha(files['spec.json']):
            raise ValueError('transport/spec mismatch')
        c.write_new(directory/(stem+'-result.json'),response)
        if p.returncode:raise ValueError(response['result'].get('error','acquisition held'))
        results[endpoint]=response['result']
    if args.mode=='readback' and all(r['phase']=='captured' for r in results.values()):
        if len(results)!=2 or len({sha(encoded(r)) for r in results.values()})!=1:
            raise ValueError('matching dual-stack terminal evidence required')
        receipt={'state':'acquisition_capture_accepted','bundle_sha256':args.sha256,'spec_sha256':sha(files['spec.json']),
                 'receiver_timing_accepted':False,'shm_mapping_accepted':False,'report_sha256':sha(encoded(next(iter(results.values()))))}
        path=directory/'acceptance.json'
        if path.exists():
            if json.loads(c.private_file(path))!=receipt:raise ValueError('acceptance conflict')
        else:c.write_new(path,receipt)
    return {'mode':args.mode,'results':{k:v['phase'] for k,v in results.items()}}


def main():
    os.umask(0o077)
    if sys.argv[1:2]==['worker']:
        root=Path(__file__).resolve().parent; spec=json.loads((root/'spec.json').read_bytes())
        identity(spec);files={n:(root/n).read_bytes() for n in INPUTS}
        if any(sha(files[n])!=v for n,v in spec['members'].items()):raise ValueError('worker input drift')
        h=bootstrap(spec,files)
        if sys.argv[2:] == ['capture']:capture(h,spec,files)
        elif sys.argv[2:] == ['restore']:restore(h,spec)
        else:raise ValueError('closed worker mode required')
        return
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='action',required=True)
    p=sub.add_parser('seal');p.add_argument('--runtime-dir',type=Path,required=True)
    p.add_argument('--prior-dir',type=Path,required=True);p.add_argument('--prior-sha256',required=True)
    p.add_argument('--runtime-sha256',required=True);p.add_argument('--operation-id',required=True);p.add_argument('--output',type=Path,required=True)
    p=sub.add_parser('execute');p.add_argument('--bundle',type=Path,required=True);p.add_argument('--sha256',required=True)
    p.add_argument('--mode',choices=('start','readback','recover','cleanup'),required=True)
    p.add_argument('--attempt',type=int,choices=range(1,27),default=1)
    args=parser.parse_args();print(json.dumps(seal(args) if args.action=='seal' else execute(args)))


if __name__=='__main__':main()
