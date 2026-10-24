#!/usr/bin/python3
"""Dedicated one-use cron failure gate and bounded publication/withdrawal worker."""
import base64
import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pwd
import signal
import socket
import stat
import sys
import time
from zoneinfo import ZoneInfo

BASE = Path('/var/lib/ntp-obs04')
CRON = Path('/etc/cron.d/obs04_cron_failure')
h = None


def write_new(path, raw, mode=0o600):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    with os.fdopen(fd, 'wb') as stream:
        os.fchmod(stream.fileno(), mode)
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    sync_dir(path.parent)


def sync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def save(path, data):
    if os.path.lexists(path):
        regular(path)
    temp = path.with_name(path.name+'.'+str(os.getpid())+'.tmp')
    write_new(temp, h.encoded(data)); os.replace(temp, path); sync_dir(path.parent)


def regular(path, mode=0o600):
    row = h.file_record(path)
    if (row.get('uid') != 0 or row.get('gid') != 0 or row.get('mode') != mode
            or row.get('changed_during_read') or 'sha256' not in row
            or path.lstat().st_nlink != 1):
        raise ValueError('root-owned direct regular file required')
    return row


def directory(path):
    for p in (path, *path.parents):
        if p.is_symlink():
            raise ValueError('indirect stage path')
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_gid != 0 or stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError('private root stage required')


def stage(spec):
    return BASE/spec['operation_id']


def command(spec):
    return '/usr/bin/python3 -I -B '+str(stage(spec)/'worker.py')+' gate 2>/dev/null'


def cron_bytes(spec, due):
    local = datetime.datetime.fromtimestamp(due, ZoneInfo('America/Chicago'))
    return ("# OBS-04 one-use controlled test; receipt and expiry gate prevent repeats.\n"
        "SHELL=/bin/bash\nHOME=/root\nPATH=/usr/bin:/bin\n"
        "MAILTO=notify.failure@mailrise.xyz\nMAILFROM=j2-svntp1@local.theama.co\nRECIPIENT=notify@mailrise.xyz\n"
        "CONTENT_TYPE=text/plain; charset=UTF-8\nCONTENT_TRANSFER_ENCODING=8bit\n"
        f'{local.minute} {local.hour} {local.day} {local.month} * root {command(spec)}\n').encode()


def choose_due(now, expiry):
    due = (int(now+180)//60+1)*60
    local = datetime.datetime.fromtimestamp(due, ZoneInfo('America/Chicago'))
    distance = abs((local.hour*3600+local.minute*60)-5.5*3600)
    distance = min(distance, 86400-distance)
    if due+600 >= expiry or distance <= 900:
        raise ValueError('publication window or daily reporting guard')
    return due


def properties(name):
    result = h.bounded(['/usr/bin/systemctl', 'show', name,
        '--property=Id,LoadState,ActiveState,SubState,MainPID,InvocationID,NRestarts,DropInPaths'])
    if result.get('returncode') != 0 or result.get('error'):
        raise ValueError('unit state unavailable')
    return dict(line.split('=', 1) for line in result['stdout'].splitlines() if '=' in line)


def cron_process(pid, proc=Path('/proc')):
    if pid <= 1:
        raise ValueError('cron PID unavailable')
    args = (proc/str(pid)/'cmdline').read_bytes().rstrip(b'\0').split(b'\0')
    if args != [b'/usr/sbin/cron', b'-f']:
        raise ValueError('cron runtime options differ from subject contract')
    if (proc/str(pid)/'exe').resolve() != Path('/usr/sbin/cron'):
        raise ValueError('cron executable changed')


def protected_file(path, digest):
    row = h.file_record(path)
    if (row.get('sha256') != digest or row.get('changed_during_read')
            or row.get('uid') != 0 or row.get('gid') != 0
            or row.get('mode', 0o777) & 0o022):
        raise ValueError('protected input identity/permissions changed')


def preflight(spec):
    if os.geteuid() != 0 or socket.gethostname() != 'j2-svntp1':
        raise ValueError('root/exact hostname required')
    if pwd.getpwuid(0).pw_dir != '/root':
        raise ValueError('root home changed')
    timezone = h.bounded(['/usr/bin/timedatectl', 'show', '--property=Timezone', '--value'])
    if (timezone.get('returncode') != 0 or timezone.get('error')
            or timezone['stdout'].strip() != 'America/Chicago'):
        raise ValueError('scheduler timezone changed')
    if Path('/proc/sys/kernel/random/boot_id').read_text().strip() != spec['boot_id']:
        raise ValueError('boot changed')
    cron_dir = CRON.parent.lstat()
    if CRON.parent.is_symlink() or cron_dir.st_uid != 0 or cron_dir.st_mode & 0o022:
        raise ValueError('cron directory ownership/mode')
    for name, digest in spec['protected_files'].items():
        protected_file(name, digest)
    for name in ('/usr/sbin/sendmail', '/usr/lib/sendmail'):
        if Path(name).resolve() != Path('/usr/bin/msmtp'):
            raise ValueError('native mail path changed')
    if any(os.path.lexists(p) for p in ('/root/.msmtprc', '/root/.config/msmtp/config')):
        raise ValueError('root transport override')
    units = {n: properties(n) for n in ('cron.service', 'timeservice.service', 'munin-node.service')}
    for name, row in units.items():
        if row.get('ActiveState') != 'active' or row.get('SubState') != 'running':
            raise ValueError('required service not running')
        if name in spec['fixed_units'] and any(row.get(k) != v for k, v in spec['fixed_units'][name].items()):
            raise ValueError('fixed service identity changed')
    if units['cron.service'].get('DropInPaths'):
        raise ValueError('unqualified cron drop-in')
    pid = int(units['cron.service']['MainPID'])
    cron_process(pid)
    return units


def runtime(spec):
    root = stage(spec); directory(BASE); directory(root)
    row = regular(root/'runtime.json')
    raw = h.file_record(root/'runtime.json', True)
    if raw.get('sha256') != row['sha256']:
        raise ValueError('runtime changed while reading')
    data = json.loads(base64.b64decode(raw['base64'], validate=True))
    if data['spec'] != spec or data['cron_sha256'] != h.sha(cron_bytes(spec, data['due_epoch'])):
        raise ValueError('runtime/spec binding')
    for name, digest in spec['input_hashes'].items():
        if regular(root/name)['sha256'] != digest:
            raise ValueError('authored source drift')
    if data['due_epoch']+600 >= spec['expires_epoch']:
        raise ValueError('runtime expiry outside approved window')
    return root, data


def install(spec, inputs):
    os.umask(0o077)
    units = preflight(spec)
    if time.time() < spec['prepared_epoch']-300:
        raise ValueError('preparation clock boundary')
    due = choose_due(time.time(), spec['expires_epoch'])
    if os.path.lexists(CRON) or os.path.lexists(stage(spec)):
        raise ValueError('test path already exists')
    if not BASE.exists():
        BASE.mkdir(mode=0o700)
    directory(BASE); root = stage(spec); root.mkdir(mode=0o700)
    for name, raw in inputs.items():
        if h.sha(raw) != spec['input_hashes'].get(name):
            raise ValueError('sealed input hash mismatch')
        write_new(root/name, raw)
    data = {'spec': spec, 'installed_epoch': time.time(), 'due_epoch': due,
            'expires_run_epoch': due+90, 'cron_sha256': h.sha(cron_bytes(spec, due)),
            'units_before': units, 'published': False}
    save(root/'runtime.json', data)
    # Independent withdrawal precedes publication; loss of the controller must
    # not leave a recurring active test entry. A reboot changes the boot guard.
    cleanup = 'ntp-obs04-withdraw-'+spec['operation_id']
    response = h.bounded(['/usr/bin/systemd-run', '--quiet', '--collect', '--unit='+cleanup,
        '--on-active='+str(int(due-time.time()+180))+'s', '--timer-property=AccuracySec=1s',
        '--property=RuntimeMaxSec=30s', '--property=UMask=0077',
        '/usr/bin/python3', '-I', '-B', str(root/'worker.py'), 'withdraw'])
    if response.get('returncode') != 0 or response.get('error'):
        raise ValueError('independent withdrawal not registered; cron unpublished')
    timer = h.bounded(['/usr/bin/systemctl', 'show', cleanup+'.timer',
        '--property=LoadState,ActiveState,NextElapseUSecMonotonic'])
    if (timer.get('returncode') != 0 or timer.get('error')
            or 'ActiveState=active\n' not in timer['stdout']
            or 'LoadState=loaded\n' not in timer['stdout']):
        raise ValueError('independent withdrawal timer not active; cron unpublished')
    data['withdrawal_unit'] = cleanup
    temp = CRON.parent/('.'+spec['operation_id']+'.pending')
    raw = cron_bytes(spec, due)
    write_new(temp, raw, 0o644)
    try:
        if time.time() >= due-90:
            raise ValueError('insufficient publication lead time')
        os.link(temp, CRON, follow_symlinks=False)
        sync_dir(CRON.parent)
    finally:
        if h.file_record(temp).get('sha256') == h.sha(raw):
            temp.unlink()
    data['published'] = True
    save(root/'runtime.json', data)
    return {'installed': True, 'due_epoch': due, 'expires_run_epoch': due+90,
            'cron_sha256': data['cron_sha256'], 'withdrawal_unit': cleanup,
            'obs04_accepted': False, 'notification_sent_by_worker': False}


def cron_ancestry(pid):
    result = []
    for _ in range(12):
        current = os.getpid() if not result else result[-1]['ppid']
        if current <= 1:
            break
        text = Path(f'/proc/{current}/stat').read_text()
        fields = text[text.rindex(')')+2:].split()
        result.append({'pid': current, 'ppid': int(fields[1])})
        if current == pid:
            return result
    raise ValueError('not a descendant of the pinned cron daemon')


def gate(spec):
    root, data = runtime(spec)
    now = time.time()
    if not data['due_epoch'] <= now <= data['expires_run_epoch']:
        return 0
    try:
        write_new(root/'attempt.json', h.encoded({'epoch': now, 'pid': os.getpid()}))
    except FileExistsError:
        return 0
    evidence = {'attempt_epoch': now, 'released': False, 'obs04_accepted': False}
    try:
        if regular(CRON, 0o644)['sha256'] != data['cron_sha256']:
            raise ValueError('authored cron entry changed or withdrawn')
        units = preflight(spec)
        evidence['ancestry'] = cron_ancestry(int(units['cron.service']['MainPID']))
        if os.environ.get('HOME') != '/root' or os.environ.get('LOGNAME') != 'root':
            raise ValueError('scheduled root environment changed')
        # Execute the inspected failure wrapper, changing only the test argument
        # and its private lock. No independent sender exists in this worker.
        invocation = base64.b64decode(spec['wrapper_base64'], validate=True).decode()
        invocation = invocation.replace('/run/lock/needrestart-check.lock', str(root/'job.lock'))
        invocation = invocation.replace('/usr/local/sbin/needrestart.sh',
            '/usr/local/sbin/needrestart.sh --obs04-controlled-failure')
        response = h.bounded(['/bin/bash', '-c', invocation], timeout=15, limit=4096)
        diagnostic = (root/'diagnostic.txt').read_bytes()
        body = (root/'body.txt').read_bytes()
        evidence.update(wrapper_returncode=response.get('returncode'),
            output_sha256=h.sha(response['stdout'].encode()), stderr_bytes=len(response['stderr'].encode()))
        if (response.get('returncode') != 2 or response.get('error')
                or response['stdout'].encode() != diagnostic or response['stderr']
                or h.sha(diagnostic) != spec['diagnostic_sha256']
                or body != b'!' or h.sha(body) != spec['body_sha256']):
            raise ValueError('unapproved failure output/status; no release')
        preflight(spec)
        if regular(CRON, 0o644)['sha256'] != data['cron_sha256']:
            raise ValueError('cron withdrawn before release')
        if time.time() > data['expires_run_epoch']:
            raise ValueError('release deadline exceeded')
        sink = os.fstat(1)
        if (not stat.S_ISREG(sink.st_mode) or sink.st_nlink != 0 or sink.st_size != 0
                or sink.st_uid != 0 or os.lseek(1, 0, os.SEEK_CUR) != 0):
            raise ValueError('empty anonymous native cron output file required')
        evidence['release_intent_epoch'] = time.time()
        save(root/'gate.json', evidence)
        # Native cron uses an anonymous regular file, not a pipe. A single
        # approved byte has no nonempty partial prefix. Intent remains uncertain
        # if we die before saving the release result; the attempt cannot repeat.
        written = os.write(1, body)
        if written != len(body):
            raise ValueError('uncertain short output release')
        evidence.update(released=True, released_epoch=time.time(), body_sha256=h.sha(body))
        save(root/'gate.json', evidence)
        return 2
    except Exception as error:
        evidence['held_error_type'] = type(error).__name__
        save(root/'gate.json', evidence)
        return 0


def withdraw(spec):
    root, data = runtime(spec)
    result = {'withdrawn_epoch': time.time(), 'removed': False,
              'inflight_mail_cancellation_claimed': False, 'obs04_accepted': False}
    if os.path.lexists(CRON):
        temp = CRON.parent/('.'+spec['operation_id']+'.pending')
        # Interrupted link publication can leave the two authored names for
        # one inode. Remove only that proven companion before enforcing nlink=1.
        if CRON.lstat().st_nlink == 2 and os.path.lexists(temp):
            left, right = CRON.lstat(), temp.lstat()
            if ((left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)
                    and h.file_record(temp).get('sha256') == data['cron_sha256']
                    and left.st_uid == right.st_uid == 0
                    and left.st_gid == right.st_gid == 0
                    and stat.S_IMODE(left.st_mode) == 0o644):
                temp.unlink(); sync_dir(CRON.parent)
        if regular(CRON, 0o644)['sha256'] != data['cron_sha256']:
            raise ValueError('foreign cron drift preserved')
        CRON.unlink(); result['removed'] = True
        sync_dir(CRON.parent)
    result['cron_absent'] = not os.path.lexists(CRON)
    save(root/('withdraw-'+str(os.getpid())+'.json'), result)
    return result


def observe(spec):
    root, data = runtime(spec)
    result = {'epoch': time.time(), 'runtime': data, 'records': {}, 'obs04_accepted': False}
    for name in ('attempt.json', 'gate.json'):
        if (root/name).exists():
            regular(root/name); result['records'][name] = json.loads((root/name).read_text())
    result['cron_record'] = h.file_record(CRON)
    result['units'] = {n: properties(n) for n in ('cron.service', 'timeservice.service', 'munin-node.service')}
    log = h.bounded(['/usr/bin/journalctl', '--no-pager', '-o', 'json', '-n', '150',
        '--since=@'+str(int(data['installed_epoch'])), '-t', 'CRON', '-t', 'cron', '-t', 'msmtp'])
    selected = []
    if log.get('returncode') == 0 and not log.get('error'):
        for line in log['stdout'].splitlines():
            row = json.loads(line); message = row.get('MESSAGE', '')
            if not isinstance(message, str):
                continue
            if command(spec) in message or ('recipients=notify.failure@mailrise.xyz' in message
                    and 'from=j2-svntp1@local.theama.co' in message):
                selected.append({k: row.get(k) for k in
                    ('__REALTIME_TIMESTAMP', '_PID', 'SYSLOG_IDENTIFIER', 'MESSAGE')})
    result['selected_journal'] = selected
    result['journal_query_complete'] = log.get('returncode') == 0 and not log.get('error')
    result['native_mail_delivery_requires_operator_receipt'] = True
    return result


def main():
    global h
    os.umask(0o077)
    if len(sys.argv) != 2 or sys.argv[1] not in ('gate', 'withdraw', 'observe'):
        raise SystemExit(2)
    action = sys.argv[1]
    root = Path(__file__).absolute().parent
    # Stage ancestors and files are checked before importing the authored helper.
    for p in (root, *root.parents):
        if p.is_symlink():
            raise SystemExit(2)
    for p in (root, BASE):
        info = p.lstat()
        if p.is_symlink() or info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o700:
            raise SystemExit(2)
    helper = root/'helper.py'
    info = helper.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o600:
        raise SystemExit(2)
    runtime_file = root/'runtime.json'
    info = runtime_file.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_gid != 0
            or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600):
        raise SystemExit(2)
    data = json.loads(runtime_file.read_text()); spec = data['spec']
    for name in ('helper.py', 'worker.py'):
        info = (root/name).lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_gid != 0
                or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600
                or hashlib.sha256((root/name).read_bytes()).hexdigest() != spec['input_hashes'][name]):
            raise SystemExit(2)
    module = importlib.util.spec_from_file_location('obs04_helper', helper)
    h = importlib.util.module_from_spec(module); module.loader.exec_module(h)
    regular(root/'runtime.json')
    if root != stage(spec):
        raise SystemExit(2)
    signal.signal(signal.SIGALRM, h.expired); signal.alarm(45)
    if action == 'gate':
        try:
            raise SystemExit(gate(spec))
        except Exception:
            # A bootstrap/validation error must not cause unapproved cron mail.
            raise SystemExit(0)
    print(json.dumps(withdraw(spec) if action == 'withdraw' else observe(spec)))


if __name__ == '__main__':
    main()
