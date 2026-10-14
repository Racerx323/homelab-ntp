#!/usr/bin/python3
"""PPS-first cold-start qualification, one-shot promotion and optional monitoring."""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import time

PPS = 'refclock shm unit 2 prefer refid PPS flag4 1'
NMEA = 'refclock shm unit 0 refid NMEA'
SERVERS = ('time.cloudflare.com', 'ohio.time.system76.com', 'oregon.time.system76.com')
COMMANDS = (NMEA,) + tuple('server '+host+' nts iburst' for host in SERVERS)
POLICY = {'version': 1, 'first_pps_seconds': 120, 'settling_seconds': 600,
          'bootstrap_seconds': 900, 'completion_seconds': 1500,
          'fresh_updates': 3, 'interval_seconds': 10}
MONITOR_POLICY = {'version': 2, 'settling_seconds': 600, 'fresh_updates': 3,
                  'interval_seconds': 30, 'stable_interval_seconds': 300,
                  'retained_samples': 120}
KEYID = 42
ENV = {'PATH': '/usr/local/bin:/usr/local/sbin:/usr/bin:/bin', 'LC_ALL': 'C'}


def protected_read(path):
    for parent in (path.parent, *path.parent.parents):
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid or info.st_mode & 0o022:
            raise ValueError('protected parent required')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid or info.st_mode & 0o022 or info.st_nlink != 1:
            raise ValueError('protected regular input required')
        raw = stream.read(65537)
        if len(raw) > 65536:
            raise ValueError('startup input bound')
        return raw


def create(path, raw):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())


def statistics_usage(root):
    """Bound retained ntpd statistics without reading or deleting their contents."""
    if not stat.S_ISDIR(root.lstat().st_mode):
        raise ValueError('regular statistics directory required')
    total = 0; seen = set(); count = 0
    for path in root.iterdir():
        count += 1; info = path.lstat()
        if (count > 128 or not stat.S_ISREG(info.st_mode)
                or not re.fullmatch(r'(?:loopstats|peerstats|clockstats)(?:\.\d{8})?', path.name)):
            raise ValueError('statistics membership/type bound')
        identity = (info.st_dev, info.st_ino)
        if identity not in seen: total += info.st_size; seen.add(identity)
        if total > 8*1024**2: raise ValueError('statistics storage bound exceeded')
    return {'files': count, 'unique_bytes': total}


def bootstrap(raw, keyfile):
    lines = raw.decode().splitlines()
    active = [line.split('#', 1)[0].strip() for line in lines]
    associations = [line for line in active if line.startswith(('refclock ', 'server ', 'pool ', 'peer '))]
    if sorted(associations) != sorted((PPS, *COMMANDS)):
        raise ValueError('exact final selectable profile required')
    if any(line.split(' ', 1)[0] in ('keys', 'controlkey', 'trustedkey', 'includefile', 'logconfig') for line in active):
        raise ValueError('unreviewed control key, include or log configuration')
    if (active.count('restrict 127.0.0.1') != 1 or active.count('restrict ::1') != 1
            or any(line.startswith('restrict ') and line not in ('restrict 127.0.0.1', 'restrict ::1')
                   and not any(flag in line.split() for flag in ('ignore', 'nomodify')) for line in active)):
        raise ValueError('only localhost may configure runtime associations')
    return ('\n'.join(line for line, directive in zip(lines, active) if directive not in COMMANDS)
            + '\nlogconfig +sysevents\nkeys '+str(keyfile)+'\ntrustedkey 42\ncontrolkey 42\n').encode()


def authenticated_session(keyfile):
    import ntp.packet
    # NTPsec 1.2.5 doquery retries a timed-out mutation. Never replay it.
    class Once(ntp.packet.ControlSession):
        def doquery(self, opcode, associd=0, qdata='', auth=False):
            self._authpass = True
            # Pinned ntp_control.c expects 4-byte request alignment but emits
            # 8-byte authenticated replies. This supervisor is single-threaded.
            original = ntp.packet.MODE_SIX_ALIGNMENT
            try:
                ntp.packet.MODE_SIX_ALIGNMENT = 4
                self.sendrequest(opcode, associd, qdata, True)
                ntp.packet.MODE_SIX_ALIGNMENT = 8
                self.getresponse(opcode, associd, True)
            finally:
                ntp.packet.MODE_SIX_ALIGNMENT = original
            if not self._authpass:
                raise ValueError('unauthenticated control response')
    session = Once()
    session.primary_timeout = 2000; session.secondary_timeout = 1000
    session.auth = ntp.packet.Authenticator(str(keyfile))
    session.keyid = KEYID
    session.keytype, session.passwd = session.auth[KEYID]
    session.openhost('127.0.0.1')
    return session


def measure(session):
    import ntp.control
    system = dict(session.readvar(0, ['leap', 'stratum', 'peer']))
    associations = session.readstat()
    if len(associations) > 5:
        raise ValueError('startup association bound')
    peers = []
    for peer in associations:
        values = dict(session.readvar(peer.associd, ['srcadr', 'srchost', 'refid', 'reach',
            'offset', 'jitter', 'received', 'rec', 'ntscookies']))
        row = {'associd': peer.associd, 'status': peer.status, 'variables': values}
        if values.get('srcadr') in ('SHM(2)', '127.127.28.2'):
            row['clock'] = dict(session.readvar(peer.associd, ['poll'], opcode=ntp.control.CTL_OP_READCLOCK))
        peers.append(row)
    return {'system': system, 'peers': peers}


def events(raw, boot, pid, started):
    result = []
    for line in raw.splitlines():
        row = json.loads(line)
        if (row.get('_BOOT_ID') != boot.replace('-', '') or row.get('_PID') != str(pid)
                or row.get('_EXE') != '/usr/local/sbin/ntpd'):
            raise ValueError('startup journal provenance mismatch')
        stamp = int(row['__MONOTONIC_TIMESTAMP']) / 1e6
        if stamp < started:
            continue
        match = re.fullmatch(r'PROTO: 0\.0\.0\.0 [0-9a-f]{4} ([0-9a-f]{2}) (freq_mode|freq_set|clock_sync|clock_step)(?: .*)?', row.get('MESSAGE', ''))
        if match:
            expected = {'freq_mode': '04', 'freq_set': '02', 'clock_sync': '05', 'clock_step': '0c'}
            if match[1] != expected[match[2]]:
                raise ValueError('startup event code mismatch')
            result.append((stamp, match[2]))
    if result != sorted(result):
        raise ValueError('startup journal order')
    return result


class Machine:
    """Pure bounded state transitions; caller persists before each mutation."""
    def __init__(self, policy=POLICY):
        if policy not in (POLICY, MONITOR_POLICY):
            raise ValueError('closed PPS policy required')
        self.monitoring = policy == MONITOR_POLICY
        self.phase = 'bootstrap'
        self.pps_id = None
        self.last_update = None
        self.stable = 0
        self.first_pps = None
        self.promoted_at = None
        self.qualified_at = None
        self.final_ids = None
        self.initialized = False
        self.init_stage = 0

    def observe(self, elapsed, value, journal):
        if not self.monitoring and elapsed >= POLICY['completion_seconds']:
            raise ValueError('startup completion deadline')
        peers = value['peers']
        pps = [p for p in peers if p['variables'].get('srcadr') in ('SHM(2)', '127.127.28.2')]
        if len(pps) != 1:
            raise ValueError('one PPS association required')
        pps = pps[0]; v = pps['variables']
        if self.pps_id is None:
            self.pps_id = pps['associd']
        if pps['associd'] != self.pps_id:
            raise ValueError('PPS association replaced')
        if (not self.monitoring or self.phase == 'bootstrap') and any(p['associd'] != self.pps_id and ((p['status'] >> 8) & 7) in (6, 7) for p in peers):
            raise ValueError('unexpected disciplined source during PPS startup')
        selected = ((pps['status'] >> 8) & 7) in (6, 7)
        if self.first_pps is None:
            if selected and (self.monitoring or elapsed < POLICY['first_pps_seconds']):
                self.first_pps = elapsed
            elif not self.monitoring and elapsed >= POLICY['first_pps_seconds']:
                raise ValueError('first PPS selection deadline')
        if self.phase == 'bootstrap' and len(peers) != 1:
            raise ValueError('association before promotion')
        if not self.monitoring and self.phase == 'bootstrap' and elapsed >= POLICY['bootstrap_seconds']:
            raise ValueError('PPS qualification deadline')
        stepped = any(e == 'clock_step' and (self.monitoring or
                      self.qualified_at is not None and t >= self.qualified_at) for t, e in journal)
        if stepped:
            if not self.monitoring:
                raise ValueError('clock step after qualification began')
            self.stable = 0; self.qualified_at = None
        sequence = [e for _, e in journal]
        initialized = False
        if 'freq_mode' in sequence:
            after = sequence[sequence.index('freq_mode') + 1:]
            if 'freq_set' in after:
                initialized = 'clock_sync' in after[after.index('freq_set') + 1:]
        if self.monitoring:
            # Monitor journal reads are incremental; retain ordered initialization.
            for event in sequence:
                if self.init_stage < 3 and event == ('freq_mode', 'freq_set', 'clock_sync')[self.init_stage]:
                    self.init_stage += 1
            self.initialized = self.initialized or self.init_stage == 3
            initialized = self.initialized
        offset, jitter = float(v['offset']), float(v['jitter'])
        good = (selected and int(v['reach']) > 0 and int(value['system']['leap']) == 0
                and int(value['system']['stratum']) == 1 and math.isfinite(offset) and abs(offset) <= 5
                and math.isfinite(jitter) and 0 <= jitter <= 1 and not stepped)
        update = (int(v['received']), int(pps['clock']['poll']), v['rec'])
        if self.last_update and (update[0] < self.last_update[0] or update[1] < self.last_update[1]):
            raise ValueError('PPS counters reset')
        fresh = self.last_update is not None and update[0] > self.last_update[0] and update[1] > self.last_update[1] and update[2] != self.last_update[2]
        if self.last_update is None or fresh:
            self.last_update = update
        if self.phase == 'bootstrap':
            good = good and initialized and elapsed >= POLICY['settling_seconds']
            if good and self.qualified_at is None:
                self.qualified_at = elapsed
        else:
            nmea = [p for p in peers if p['variables'].get('srcadr') in ('SHM(0)', '127.127.28.0')]
            upstream = [p for p in peers if p['variables'].get('srchost') in SERVERS]
            membership = (len(peers) == 5 and len(nmea) == 1 and len(upstream) == 3
                          and {p['variables']['srchost'] for p in upstream} == set(SERVERS))
            if not membership:
                raise ValueError('partial or unexpected promotion membership')
            ids = sorted(p['associd'] for p in peers)
            if len(set(ids)) != 5 or self.final_ids is not None and self.final_ids != ids:
                raise ValueError('promoted associations replaced')
            self.final_ids = ids
            good = good and int(nmea[0]['variables']['reach']) > 0 and all(
                ((p['status'] >> 8) & 0x60) == 0x60 and int(p['variables']['reach']) > 0
                and int(p['variables'].get('ntscookies', 0)) > 0 for p in upstream)
        if not good:
            self.stable = 0
        elif fresh:
            self.stable = min(self.stable + 1, POLICY['fresh_updates'])
        if self.stable >= POLICY['fresh_updates'] and (not self.monitoring or fresh):
            return 'promote' if self.phase == 'bootstrap' else 'ready'
        return 'wait'

    def promoted(self, elapsed):
        if self.phase != 'bootstrap' or self.stable < POLICY['fresh_updates']:
            raise ValueError('unqualified or repeated promotion')
        self.phase = 'promoted'; self.promoted_at = elapsed; self.stable = 0


class Startup:
    def __init__(self, config, root=Path('/run/ntpsec-startup')):
        if config.get('pps_startup') not in (POLICY, MONITOR_POLICY):
            raise ValueError('closed PPS startup policy required')
        self.policy = config['pps_startup']
        self.evidence = None
        self.cursor = None
        self.statistics = Path('/var/log/ntpstats')
        if self.policy == MONITOR_POLICY:
            # Each operation owns a distinct protected destination; never reuse it.
            self.evidence = Path(config.get('pps_monitor_evidence', ''))
            if not re.fullmatch(r'/var/lib/ntp-acquire-[a-z0-9][a-z0-9-]*/startup-monitor\.json', str(self.evidence)):
                raise ValueError('operation-bound monitor evidence path required')
            parent = self.evidence.parent.lstat()
            if not stat.S_ISDIR(parent.st_mode) or parent.st_uid or stat.S_IMODE(parent.st_mode) != 0o700:
                raise ValueError('protected monitor evidence directory required')
            for path in self.evidence.parents:
                info = path.lstat()
                if not stat.S_ISDIR(info.st_mode) or info.st_uid or info.st_mode & 0o022:
                    raise ValueError('protected monitor evidence ancestors required')
            if os.path.lexists(self.evidence):
                raise ValueError('prior monitor evidence must be preserved')
        self.root = root
        info = root.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid or stat.S_IMODE(info.st_mode) != 0o700:
            raise ValueError('protected runtime directory required')
        argv = list(config['ntpd'])
        if argv.count('-c') != 1:
            raise ValueError('one final config path required')
        raw = protected_read(Path(argv[argv.index('-c') + 1]))
        # This first trial is explicitly cold-start only; never fake freq_mode on warm starts.
        if os.path.lexists('/var/lib/ntpsec/drift/ntp.drift'):
            raise ValueError('cold-start trial requires absent drift file')
        self.keyfile = root/'control.key'
        candidate = bootstrap(raw, self.keyfile)
        create(self.keyfile, ('42 AES '+secrets.token_hex(16)+'\n').encode())
        try:
            create(root/'bootstrap.conf', candidate)
        except BaseException:
            self.keyfile.unlink(); raise
        argv[argv.index('-c') + 1] = str(root/'bootstrap.conf')
        self.argv = argv; self.session = None; self.machine = Machine(self.policy)
        self.started = time.monotonic(); self.next_poll = self.started + 1
        self.pid = None; self.boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        self.status = {'phase': 'bootstrap', 'supervisor_pid': os.getpid(),
                       'final_sha256': hashlib.sha256(raw).hexdigest(), 'commands': [],
                       'boot_id': self.boot, 'started_monotonic': self.started, 'running': True}
        if self.evidence:
            self.status.update(samples=[], sample_count=0)
        try:
            self.save()
        except BaseException:
            self.close(); raise

    def save(self):
        raw = (json.dumps(self.status, sort_keys=True)+'\n').encode()
        if getattr(self, 'policy', POLICY) == MONITOR_POLICY:
            while len(raw) > 512*1024 and len(self.status['samples']) > 1:
                self.status['samples'].pop(0)
                raw = (json.dumps(self.status, sort_keys=True)+'\n').encode()
        if len(raw) > 512*1024:
            raise ValueError('startup status size bound')
        targets = [self.root/'promotion.json']
        if getattr(self, 'evidence', None):
            targets.insert(0, self.evidence)
        for target in targets:
            path = target.with_name(target.name+'.new')
            create(path, raw)
            os.replace(path, target)

    def remember(self):
        if getattr(self, 'policy', POLICY) == MONITOR_POLICY:
            self.status['sample_count'] += 1
            self.status['samples'].append({key: self.status.get(key) for key in
                ('elapsed_seconds', 'machine', 'measurement', 'events', 'phase', 'error', 'statistics')})
            self.status['samples'] = self.status['samples'][-MONITOR_POLICY['retained_samples']:]

    def tick(self, process):
        if self.status['phase'] == 'failed':
            raise ValueError('failed promotion is terminal; recovery required')
        monitoring = getattr(self, 'policy', POLICY) == MONITOR_POLICY
        if time.monotonic() < self.next_poll or self.status['phase'] == 'ready' and not monitoring:
            return
        now = time.monotonic()
        self.next_poll = now + (MONITOR_POLICY['interval_seconds'] if monitoring else POLICY['interval_seconds'])
        self.status.update(elapsed_seconds=now-self.started, measurement=None, events=[])
        try:
            if monitoring:
                self.status['statistics'] = None
                self.status['statistics'] = statistics_usage(self.statistics)
            if process.poll() is not None or self.pid is not None and self.pid != process.pid:
                raise ValueError('ntpd process continuity failed')
            self.pid = process.pid; self.status['ntpd_pid'] = self.pid
            if self.session is None:
                self.session = authenticated_session(self.keyfile)
            value = measure(self.session)
            self.status['measurement'] = value
            argv = ['/usr/bin/journalctl', '--quiet', '--no-pager', '--output=json',
                '--boot='+self.boot.replace('-', ''), '_PID='+str(self.pid), '_EXE=/usr/local/sbin/ntpd',
                '--lines=1000']
            if monitoring and self.cursor:
                argv.append('--after-cursor='+self.cursor)
            result = subprocess.run(argv, capture_output=True, timeout=5, check=True, env=ENV)
            if len(result.stdout) > 1024*1024 or len(result.stdout.splitlines()) >= 1000:
                raise ValueError('startup journal bound')
            journal = [(stamp-self.started, name) for stamp, name in events(result.stdout, self.boot, self.pid, self.started)]
            if monitoring and result.stdout.strip():
                cursor = json.loads(result.stdout.splitlines()[-1]).get('__CURSOR')
                if not isinstance(cursor, str) or not re.fullmatch(r'[A-Za-z0-9;=:_-]{1,1024}', cursor):
                    raise ValueError('startup journal cursor required')
                self.cursor = cursor
            self.status['events'] = journal
            action = self.machine.observe(now-self.started, value, journal)
            self.status.update(elapsed_seconds=now-self.started, machine=vars(self.machine).copy(), measurement=value, events=journal)
            self.save()
            if action == 'promote':
                self.status.update(phase='promoting', promoted_monotonic=time.monotonic())
                self.save()
                for command in COMMANDS:
                    self.status['commands'].append({'command': command, 'state': 'submitted'})
                    self.save()  # An uncertain command is never resubmitted, including after interruption.
                    if not self.session.config(command):
                        raise ValueError('runtime configuration rejected')
                    self.status['commands'][-1]['state'] = 'authenticated_ack'
                    self.save()
                self.machine.promoted(time.monotonic()-self.started)
                self.status.update(phase='promoted')
                followup = measure(self.session)
                self.status.update(measurement=followup, elapsed_seconds=time.monotonic()-self.started)
                self.machine.observe(self.status['elapsed_seconds'], followup, journal)
            elif action == 'ready':
                self.status['phase'] = 'ready'
            elif monitoring and self.machine.phase == 'promoted':
                self.status['phase'] = 'settling'
            self.status['machine'] = vars(self.machine).copy()
            if monitoring and self.status['phase'] == 'ready':
                self.next_poll = time.monotonic() + MONITOR_POLICY['stable_interval_seconds']
            self.remember(); self.save()
        except BaseException as error:
            self.status.update(phase='failed', error=str(error)[:400], machine=vars(self.machine).copy())
            self.remember()
            try:
                self.save()
            except BaseException:
                pass  # Preserve the original failure; supervisor cleanup must still run.
            raise

    def finish(self, reason):
        self.status.update(stopped_monotonic=time.monotonic(), stop_reason=reason, running=False)
        self.save()

    def close(self):
        error = None
        try:
            if self.session is not None:
                self.session.sock.close()
        except BaseException as failure:
            error = failure
        for name in ('control.key', 'bootstrap.conf'):
            try:
                path = self.root/name
                if path.exists():
                    protected_read(path); path.unlink()
            except BaseException as failure:
                error = error or failure
        if error:
            raise error
