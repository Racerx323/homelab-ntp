#!/usr/bin/python3
"""Timer-only transaction; base is the bundled leap-activation implementation."""
import base64
import os
from pathlib import Path
import re
import time

CHECKS = ('prior_scheduled_run', 'four_week_schedule', 'reload_schedule', 'continuity')


def seconds(value):
    """Parse systemctl's monotonic timespan; reject unknown or partial output."""
    units = {'us':1e-6, 'ms':1e-3, 's':1, 'min':60, 'h':3600, 'd':86400, 'w':604800}
    parts = re.findall(r'(\d+(?:\.\d+)?)(us|ms|min|s|h|d|w)', value)
    if not parts or ''.join(n+u for n,u in parts) != ''.join(value.split()):
        raise ValueError('unrecognized monotonic timespan: '+value)
    return sum(float(n)*units[u] for n,u in parts)


class TimerCorrection(base.Activation):
    def unit(self, name):
        extra = (',MainPID,NRestarts,InvocationID,Result,ExecMainCode,ExecMainStatus,ExecMainStartTimestampMonotonic'
                 if name.endswith('.service') else ',LastTriggerUSec,NextElapseUSecMonotonic')
        return base.properties(self.cmd(['/usr/bin/systemctl','show',name,'--property='+base.PROPS+extra]))

    def files_match(self, candidate=False, either=False):
        for path, row in self.baseline['files'].items():
            expected = base.identity(row)
            allowed = [expected]
            if path == base.TIMER and (candidate or either):
                updated = dict(expected, sha256=self.h.sha(self.candidate))
                allowed = [expected, updated] if either else [updated]
            if base.identity(self.h.file_record(path)) not in allowed:
                raise ValueError('protected file drift: '+path)

    def leap_units(self, active):
        service, timer = self.unit('ntpleapfetch.service'), self.unit('ntpleapfetch.timer')
        for row, path in ((service,base.SERVICE),(timer,base.TIMER)):
            if row['LoadState'] != 'loaded' or row['DropInPaths'] or row['FragmentPath'] != path:
                raise ValueError('unexpected effective leap unit')
        if (service['ActiveState'],service['SubState'],service['UnitFileState'],service['Result']) != ('inactive','dead','static','success'):
            raise ValueError('leap service not idle/successful')
        desired = ('active','waiting') if active else ('inactive','dead')
        if (timer['ActiveState'],timer['SubState']) != desired or timer['UnitFileState'] != 'enabled':
            raise ValueError('unexpected timer state/enablement')
        return service,timer

    def replace(self, raw):
        path = Path(base.TIMER)
        before = base.identity(self.h.file_record(path))
        original = base.identity(self.baseline['files'][base.TIMER])
        if before not in (original, dict(original,sha256=self.h.sha(self.candidate))):
            raise ValueError('foreign timer file; hold')
        temp = path.with_name('.ntpleapfetch-'+self.spec['operation_id']+'.tmp')
        fd = os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        try:
            with os.fdopen(fd,'wb') as stream:
                stream.write(raw); stream.flush(); os.fchown(stream.fileno(),0,0)
                os.fchmod(stream.fileno(),0o644); os.fsync(stream.fileno())
            if base.identity(self.h.file_record(path)) != before:
                raise ValueError('timer changed during replacement')
            os.replace(temp,path)
        finally:
            if temp.exists(): temp.unlink()

    def schedule(self, service, timer):
        start = int(service['ExecMainStartTimestampMonotonic'])/1_000_000
        delta = seconds(timer['NextElapseUSecMonotonic'])-start
        if not 2419200 <= delta <= 2419200+1800+60+5:
            raise ValueError('next trigger is not four weeks plus permitted jitter')
        return delta

    def recover(self):
        self.continuity(); self.files_match(either=True)
        for name,path in (('ntpleapfetch.service',base.SERVICE),('ntpleapfetch.timer',base.TIMER)):
            row=self.unit(name)
            if row['DropInPaths'] or row['FragmentPath'] != path:
                raise ValueError('foreign effective unit; recovery held')
        self.cmd(['/usr/bin/systemctl','stop','ntpleapfetch.timer'],30)
        self.cmd(['/usr/bin/systemctl','stop','ntpleapfetch.service'],30)
        self.replace(base64.b64decode(self.baseline['files'][base.TIMER]['base64'],validate=True))
        self.cmd(['/usr/bin/systemctl','daemon-reload'],30)
        self.cmd(['/usr/bin/systemctl','reset-failed','ntpleapfetch.service'])
        self.cmd(['/usr/bin/systemctl','start','ntpleapfetch.timer'],30)
        self.files_match(); self.continuity(); self.leap_units(True)
        self.state['rollback']='restored original enabled timer; previous recurrence issue remains'

    def apply(self):
        self.continuity(); self.files_match(); before,previous_timer=self.leap_units(True)
        if not previous_timer['LastTriggerUSec'] or before['ExecMainStatus']!='0' or int(before['ExecMainStartTimestampMonotonic'])<=0:
            raise ValueError('successful prior scheduled maintenance required')
        original=base64.b64decode(self.baseline['files'][base.TIMER]['base64'],validate=True)
        if original.count(b'OnActiveSec=') != 1 or original.replace(b'OnActiveSec=',b'OnBootSec=') != self.candidate:
            raise ValueError('candidate must be exactly the reviewed initial-trigger correction')
        raw=base64.b64decode(self.baseline['files'][base.LEAP]['base64'],validate=True)
        if base.expiry(raw) <= time.time()+61*86400:
            raise ValueError('live leapfile is inside prefetch safety window')
        self.root.mkdir(mode=0o700); self.created=True
        (self.root/'original.timer').write_bytes(original)
        candidate=self.root/'ntpleapfetch.timer'; candidate.write_bytes(self.candidate)
        self.save()
        self.cmd(['/usr/bin/systemd-analyze','verify',str(candidate)],30)
        self.continuity(); self.files_match(); self.leap_units(True)
        self.state['rollback']='pending'; self.save(); self.changed=True
        self.cmd(['/usr/bin/systemctl','stop','ntpleapfetch.timer'],30)
        self.leap_units(False)
        self.replace(self.candidate)
        self.cmd(['/usr/bin/systemctl','daemon-reload'],30)
        self.cmd(['/usr/bin/systemctl','start','ntpleapfetch.timer'],30)
        service,timer=self.leap_units(True)
        if (service['InvocationID']!=before['InvocationID']
                or service['ExecMainStartTimestampMonotonic']!=before['ExecMainStartTimestampMonotonic']
                or timer['LastTriggerUSec']!=previous_timer['LastTriggerUSec']):
            raise ValueError('upgrade did not preserve prior scheduled invocation')
        self.state['checks']['prior_scheduled_run']=True
        self.state['prior_service']=service
        self.state['schedule_seconds']=self.schedule(service,timer)
        self.state['checks']['four_week_schedule']=True
        self.files_match(candidate=True); self.continuity()
        self.cmd(['/usr/bin/systemctl','daemon-reload'],30)
        after,timer=self.leap_units(True)
        if after['InvocationID']!=service['InvocationID'] or after['ExecMainStartTimestampMonotonic']!=service['ExecMainStartTimestampMonotonic']:
            raise ValueError('reload unexpectedly invoked maintenance')
        self.state['reload_schedule_seconds']=self.schedule(after,timer)
        self.state['timer']=timer
        self.files_match(candidate=True); self.continuity()
        self.state['checks'].update(reload_schedule=True,continuity=True)
        self.state.update(accepted=True,rollback='not-needed')


def run(spec,baseline,candidate,helper):
    import signal
    for sig in (signal.SIGTERM,signal.SIGHUP,signal.SIGINT):
        signal.signal(sig,base.interrupted)
    return TimerCorrection(spec,baseline,candidate,helper).run()
