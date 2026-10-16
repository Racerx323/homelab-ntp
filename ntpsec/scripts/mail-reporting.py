#!/usr/bin/python3
"""Exercise the pinned reporter with captured mail, then activate its cron file."""
import datetime
import fcntl
import os
from pathlib import Path
import pwd
import socket
from zoneinfo import ZoneInfo

CRON = Path('/etc/cron.d/needrestart_check')


def cron_command(raw):
    lines = [line for line in raw.decode().splitlines() if line.startswith('30 5 ')]
    if len(lines) != 1 or lines[0].split(None, 6)[:6] != ['30', '5', '*', '*', '*', 'root']:
        raise ValueError('daily root schedule mismatch')
    command = lines[0].split(None, 6)[6]
    if '%' in command.replace('\\%', ''):
        raise ValueError('unescaped cron percent')
    return command.replace('\\%', '%')


def captured_reporter(raw, sendmail, scanner=None):
    text = raw.decode()
    if text.count('/usr/sbin/sendmail') != 7 or text.count('/usr/sbin/needrestart') != 4:
        raise ValueError('reporter capture sites changed')
    text = text.replace('/usr/sbin/sendmail', str(sendmail))
    if scanner is not None:
        text = text.replace('/usr/sbin/needrestart', str(scanner))
    return text.encode()


def capture_program(destination):
    # Exclusive creation means an unexpected second send fails instead of
    # overwriting a captured message. This helper has no transport operation.
    return ("#!/usr/bin/python3 -I\nimport os,sys\nos.umask(0o077)\n"
            "data=sys.stdin.buffer.read(1048577)\n"
            "if len(data)>1048576: raise SystemExit(75)\n"
            f"with open({str(destination)!r},'xb') as stream: stream.write(data)\n").encode()


def make_worker(base):
    class Reporting(base.Install):
        def __init__(self, spec, inputs, helper):
            super().__init__(spec, inputs, helper)
            self.root = Path('/var/lib/ntp-mail-reporting-' + spec['operation_id'])
            self.state.update(runtime_capture_accepted=False, failure_capture_accepted=False,
                              overlap_accepted=False, cron_active=False, scheduled_run_observed=False)
            self.linked = False

        def preflight(self):
            if os.geteuid() != 0 or socket.gethostname().split('.')[0] != 'j2-svntp1':
                raise ValueError('target/root identity')
            self.continuity()
            if self.inventory() != self.spec['packages_before']:
                raise ValueError('package baseline changed')
            self.accept_files()
            if self.cmd(['/usr/bin/dpkg', '--audit']).strip():
                raise ValueError('dpkg audit')
            if self.cmd(['/usr/bin/timedatectl', 'show', '--property=Timezone', '--value']).strip() != 'America/Chicago':
                raise ValueError('timezone changed')
            cron = self.unit('cron.service')
            if any(cron.get(k) != v for k, v in {'ActiveState': 'active', 'SubState': 'running', 'UnitFileState': 'enabled'}.items()):
                raise ValueError('cron not already running/enabled')
            home = Path(pwd.getpwuid(0).pw_dir)
            if any(os.path.lexists(p) for p in (home/'.msmtprc', home/'.config/msmtp/config')):
                raise ValueError('root msmtp override appeared')
            self.protected = {p: self.h.file_record(p) for p in base.PROTECTED}
            if any(r.get('missing') or r.get('error') or r.get('changed_during_read') for r in self.protected.values()):
                raise ValueError('protected file unavailable')
            self.root.mkdir(mode=0o700)
            self.created = True
            self.save()

        def exercise(self):
            command = cron_command(self.inputs['cron.pending'])
            lock = self.root/'fixture.lock'
            for name, failure in [('runtime', False), ('failure', True)]:
                capture = self.root/(name + '.eml')
                stub = self.root/(name + '-sendmail')
                reporter = self.root/(name + '-reporter')
                scanner = None
                self.write_new(stub, capture_program(capture), 0o700)
                if failure:
                    scanner = self.root/'failed-scanner'
                    self.write_new(scanner, b'#!/bin/bash\nprintf "Synthetic scan failure for acceptance; no service failure.\\n"\nexit 23\n', 0o700)
                self.write_new(reporter, captured_reporter(self.inputs['reporter.sh'], stub, scanner), 0o700)
                invocation = command.replace('/run/lock/needrestart-check.lock', str(lock)).replace('/usr/local/sbin/needrestart.sh', str(reporter))
                output = self.cmd(['/usr/bin/env', 'RECIPIENT=notify@mailrise.xyz', '/bin/bash', '-c', invocation],
                                  timeout=370, accepted=(23,) if failure else (0,))
                if failure:
                    if 'Synthetic scan failure for acceptance' not in output or not capture.is_file():
                        raise ValueError('failure output/mail capture missing')
                    if b'Needrestart Scan Failed on ' not in capture.read_bytes():
                        raise ValueError('failure subject mismatch')
                    self.state['failure_capture_accepted'] = True
                else:
                    if output:
                        raise ValueError('successful cron wrapper was not quiet')
                    self.state['runtime_capture_accepted'] = True
                self.state[name+'_message_sha256'] = self.h.sha(capture.read_bytes()) if capture.exists() else None
            # A held private lock must skip the reporter and expose the cron
            # fallback, without touching the production lock or sending mail.
            with lock.open('a') as stream:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                output = self.cmd(['/bin/bash', '-c', invocation], accepted=(1,))
            if output != 'needrestart check failed with exit status 1 (the lock may already be held).\n':
                raise ValueError('overlap fallback mismatch')
            self.state['overlap_accepted'] = True
            self.save()

        def activate(self):
            self.continuity()
            self.accept_files()
            now = datetime.datetime.now(ZoneInfo('America/Chicago'))
            next_run = now.replace(hour=5, minute=30, second=0, microsecond=0)
            if next_run <= now:
                next_run += datetime.timedelta(days=1)
            if (next_run-now).total_seconds() < 900:
                raise ValueError('too close to scheduled run for activation acceptance')
            self.state['next_run_local'] = next_run.isoformat()
            hidden = CRON.parent/('.'+self.spec['operation_id'])
            self.write_new(hidden, self.inputs['cron.pending'], 0o644)
            self.state['recovery'] = 'activation pending'
            self.save()
            try:
                os.link(hidden, CRON, follow_symlinks=False)
                self.linked = True
            finally:
                hidden.unlink()
            record = self.h.file_record(str(CRON))
            if record.get('sha256') != self.h.sha(self.inputs['cron.pending']) or record.get('uid') != 0 or record.get('gid') != 0 or CRON.stat().st_mode & 0o777 != 0o644:
                raise ValueError('active cron file mismatch')
            self.continuity()
            if self.unit('cron.service')['ActiveState'] != 'active':
                raise ValueError('cron stopped')
            self.state.update(cron_active=True, accepted=True, recovery='not-needed')
            self.save()

        def run(self):
            try:
                self.preflight()
                self.exercise()
                self.activate()
            except Exception as error:
                self.state.update(accepted=False, error=str(error))
                if self.linked:
                    record = self.h.file_record(str(CRON))
                    if record.get('sha256') == self.h.sha(self.inputs['cron.pending']) and record.get('uid') == 0 and record.get('gid') == 0 and CRON.stat().st_mode & 0o777 == 0o644:
                        CRON.unlink()
                        self.state.update(cron_active=False, recovery='authored cron removed')
                    else:
                        self.state['cron_active'] = None
                        self.state['recovery'] = 'hold: active cron changed; manual inspection required'
                self.save()
            return self.state
    return Reporting
