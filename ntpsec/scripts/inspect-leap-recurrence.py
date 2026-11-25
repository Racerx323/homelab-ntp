#!/usr/bin/python3
"""One bounded, non-mutating recurrence capture; acceptance remains an operator decision."""
import argparse
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import time
import types


def load(path):
    spec = importlib.util.spec_from_file_location('inspection_helper', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def emit(name, value):
    print(json.dumps({'record': name, 'value': value}, sort_keys=True), flush=True)


def leap_facts(row, now):
    if row.get('missing') or row.get('error') or row.get('changed_during_read'):
        raise ValueError('leapfile unavailable or changed during read')
    raw = base64.b64decode(row['base64'], validate=True)
    expires = re.findall(rb'^#@\s+(\d+)\s*$', raw, re.M)
    if len(expires) != 1:
        raise ValueError('one leapfile expiry required')
    epoch = int(expires[0])-2208988800
    return {'expires_epoch': epoch, 'unexpired': epoch > now,
            'sha256': hashlib.sha256(raw).hexdigest(),
            'content_and_scheduled_provenance_require_review': True}


def boot():
    return Path('/proc/sys/kernel/random/boot_id').read_text().strip()


def collect(spec, helper):
    start = time.time()
    before = boot()
    emit('admission', {'epoch': start, 'hostname': socket.gethostname(), 'uid': os.geteuid(),
                       'boot': before, 'spec_sha256': helper.sha(helper.encoded(spec))})
    complete = False
    try:
        if socket.gethostname() != spec['hostname'] or os.geteuid() != 0:
            raise ValueError('wrong host/root identity')
        if not spec['not_before'] <= start <= spec['not_after']:
            raise ValueError('outside approved inspection window')
        # No preparation-time boot is an admission prerequisite.
        healthy = True
        for name, template in spec['commands'].items():
            argv = ['@'+str(int(start)) if x == '{end_epoch}' else x for x in template]
            try:
                row = helper.bounded(argv, timeout=15, limit=helper.LIMIT)
            except OSError as error:
                row = {'argv': argv, 'returncode': None, 'error': str(error)}
            emit(name, row)
            healthy &= row.get('returncode') == 0 and not row.get('error')
            if name == 'journal' and len(row.get('stdout', '').splitlines()) >= 1001:
                emit('journal_coverage', {'saturated': True, 'acceptance_available': False})
                healthy = False
        for path in spec['files']:
            row = helper.file_record(path, content=True)
            emit('file:'+path, row)
            healthy &= not any(row.get(k) for k in ('missing', 'error', 'changed_during_read'))
            if path == spec['leapfile']:
                try:
                    facts = leap_facts(row, start)
                    emit('leap_facts', facts)
                except (ValueError, KeyError) as error:
                    emit('leap_facts', {'error': str(error)})
                    healthy = False
        after = boot()
        emit('continuity', {'boot_before': before, 'boot_after': after})
        complete = healthy and before == after
    except BaseException as error:
        emit('failure', {'type': type(error).__name__, 'error': str(error)})
    finally:
        emit('terminal', {'epoch': time.time(), 'capture_complete': bool(complete),
                          'recurrence_accepted': False, 'retry_permitted': False})


def check(bundle, digest):
    raw = (bundle/'manifest.json').read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError('approved manifest mismatch')
    m = json.loads(raw)
    if m['execution_ready'] is not True:
        raise ValueError('not executable')
    for name, record in m['files'].items():
        if not re.fullmatch(r'[A-Za-z0-9_.-]+', name):
            raise ValueError('unsafe member name')
        p = bundle/name
        if p.is_symlink() or not p.is_file():
            raise ValueError('regular sealed input required')
        data = p.read_bytes()
        if len(data) != record['bytes'] or hashlib.sha256(data).hexdigest() != record['sha256']:
            raise ValueError('sealed member drift: '+name)
    return json.loads((bundle/'spec.json').read_text())


def payload(bundle, spec):
    return ("__name__='sealed_recurrence'\n__file__='/sealed/runner.py'\n" +
            (bundle/'runner.py').read_text() +
            "\nh=types.ModuleType('helper');h.__file__='/sealed/helper.py'\nexec(" +
            repr((bundle/'helper.py').read_text()) + ",h.__dict__)\n" +
            "signal.signal(signal.SIGALRM,h.expired);signal.alarm(180)\ncollect(" +
            repr(spec) + ',h)\n').encode()


def execute(bundle, digest):
    spec = check(bundle, digest)
    if socket.gethostname() != spec['controller_hostname']:
        raise ValueError('wrong controller')
    if not spec['not_before'] <= time.time() <= spec['not_after']:
        raise ValueError('outside approved inspection window')
    transport = spec['transport']
    fp = subprocess.check_output(['/usr/bin/ssh-keygen', '-lf', transport['identity_file']], timeout=5)
    if fp.decode().split()[1] != transport['identity_fingerprint']:
        raise ValueError('SSH identity mismatch')
    key = Path(transport['identity_file'])
    if key.resolve() != key.absolute() or key.stat().st_uid != os.getuid() or key.stat().st_mode & 0o077:
        raise ValueError('unsafe SSH identity')
    helper = load(bundle/'helper.py')
    argv = ['/usr/bin/ssh', '-F', '/dev/null', '-i', str(key)]
    for opt in transport['ssh_options']:
        argv += ['-o', opt]
    argv += ['-o', 'UserKnownHostsFile='+str(bundle/'known_hosts'), '-o',
             'HostKeyAlias='+spec['host_key_alias'], spec['target'],
             'sudo -n -- /usr/bin/timeout --kill-after=2s 185s /usr/bin/python3 -I -B -']
    os.umask(0o077)
    request = payload(bundle, spec)
    # Exclusive receipt precedes SSH. A second execution always fails here.
    with (bundle/'execution.json').open('x') as f:
        json.dump({'epoch': time.time(), 'manifest_sha256': digest,
                   'payload_sha256': helper.sha(request), 'argv': argv}, f)
        f.flush(); os.fsync(f.fileno())
    result = {'capture_complete': False}
    with (bundle/'stdout.jsonl').open('xb') as out, (bundle/'stderr.log').open('xb') as err:
        def sink(name, data):
            stream = out if name == 'stdout' else err
            stream.write(data); stream.flush()
        try:
            result = helper.bounded(argv, timeout=210, limit=16*helper.LIMIT,
                                    payload=request, env=os.environ.copy(), sink=sink)
            records = [json.loads(x) for x in result['stdout'].splitlines()]
            names = [x['record'] for x in records]
            if len(names) != len(set(names)):
                raise ValueError('duplicate capture record')
            terminal = next(x['value'] for x in records if x['record'] == 'terminal')
            admission = next(x['value'] for x in records if x['record'] == 'admission')
            result['capture_complete'] = bool(result['returncode'] == 0 and not result.get('error')
                and terminal['capture_complete'] and admission['hostname'] == spec['hostname']
                and admission['spec_sha256'] == helper.sha(helper.encoded(spec)))
        except BaseException as error:
            result.update(capture_complete=False, error=str(error), error_type=type(error).__name__)
        finally:
            result.pop('stdout', None); result.pop('stderr', None)
            result.update(manifest_sha256=digest, recurrence_accepted=False, retry_permitted=False)
            (bundle/'result.json').write_text(json.dumps(result, indent=2)+'\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('check', 'execute'))
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--sha256', required=True)
    a = parser.parse_args()
    if a.phase == 'check':
        check(a.bundle, a.sha256)
        print('sealed inputs verified; no contact')
    else:
        result = execute(a.bundle.absolute(), a.sha256)
        print(json.dumps(result))
        raise SystemExit(0 if result.get('capture_complete') else 1)


if __name__ == '__main__':
    main()
