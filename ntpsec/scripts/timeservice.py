#!/usr/bin/python3
"""Supervise the source-built GPSD/ntpd pair as one foreground systemd service."""
import argparse
import importlib.util
import json
import os
import re
from pathlib import Path
import signal
import stat
import subprocess
import sys
import time


def validate(config):
    for name in ('gpsd', 'ntpd'):
        argv = config[name]
        if not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
            raise ValueError('daemon argument arrays required')
        if argv[0] != '/usr/local/sbin/' + name:
            raise ValueError('source-built absolute daemon path required')
    if '-N' not in config['gpsd'][1:] or '-n' not in config['ntpd'][1:]:
        raise ValueError('both daemons must remain in foreground')
    if not any(a in ('-m', '--mdns') for a in config['ntpd'][1:]):
        raise ValueError('NTPsec mDNS registration requires -m or --mdns')
    device = config['uart_device']
    if not isinstance(device, str) or not device.startswith('/dev/') or '..' in Path(device).parts:
        raise ValueError('explicit observed UART device required')
    gpsd = config['gpsd'][1:]
    if (gpsd.count('-s') != 1 or
            gpsd[gpsd.index('-s') + 1:gpsd.index('-s') + 2] != ['115200'] or
            any(a.startswith('--speed') or (a.startswith('-s') and a != '-s') for a in gpsd) or
            device not in gpsd):
        raise ValueError('GPSD requires one explicit -s 115200 and the observed UART device')


def stop(children):
    for process in children:
        if process.poll() is None:
            process.terminate()
    deadline = time.monotonic() + 10
    for process in children:
        try:
            process.wait(timeout=max(0.01, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def validate_startup_gate(config):
    gate=config.get('startup_gate')
    if (not isinstance(gate,dict) or set(gate) not in ({'timeout_seconds','matching_samples_per_source','units'},
                                                 {'timeout_seconds','matching_samples_per_source','units','acquisition_policy'})
            or gate.get('acquisition_policy','bounded') not in ('bounded','wait')
            or gate['timeout_seconds']!=30 or gate['matching_samples_per_source']!=5
            or set(gate['units'])!={'TOFF','PPS'} or len(set(gate['units'].values()))!=2
            or any(not isinstance(v,str) or not re.fullmatch(r'NTP[0-9]+',v) for v in gate['units'].values())):
        raise ValueError('reviewed bounded startup gate and observed units required')
    return gate


def supervise(config):
    validate(config)
    gate = validate_startup_gate(config)
    stopping = False

    def requested_stop(signum, frame):
        nonlocal stopping
        stopping = True

    previous = {sig: signal.signal(sig, requested_stop) for sig in (signal.SIGTERM, signal.SIGINT)}
    children = []
    startup = None
    stop_reason = 'startup interrupted'
    try:
        subprocess.run(['/usr/bin/stty', '-F', config['uart_device'], 'raw',
                        '115200', 'cs8', '-parenb', 'clocal', '-cstopb', '-crtscts'],
                       check=True, timeout=10, env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'})
        if stopping:
            return 0
        for name in ('gpsd', 'ntpd'):
            if name=='ntpd':
                check_startup(children[0],lambda:stopping,gate)
                if stopping:return 0
                if 'pps_startup' in config:
                    path = Path(__file__).resolve().parent/'pps-startup.py'
                    spec = importlib.util.spec_from_file_location('pps_startup', path)
                    helper = importlib.util.module_from_spec(spec); spec.loader.exec_module(helper)
                    startup = helper.Startup(config)
            argv = startup.argv if name == 'ntpd' and startup else config[name]
            children.append(subprocess.Popen(argv, env={
                'PATH': '/usr/local/bin:/usr/local/sbin:/usr/bin:/bin', 'LC_ALL': 'C'}))
            if stopping or children[-1].poll() is not None:
                stop_reason = 'requested stop' if stopping else 'daemon exited during startup'
                return 0 if stopping else 1
        while not stopping:
            if any(process.poll() is not None for process in children):
                stop_reason = 'daemon exited'
                return 1
            if startup:
                startup.tick(children[1])
            time.sleep(0.1)
        stop_reason = 'requested stop'
        return 0
    except BaseException:
        stop_reason = 'supervisor failure'
        raise
    finally:
        try:
            stop(children)
        finally:
            try:
                if startup:
                    try:
                        startup.finish(stop_reason)
                    except BaseException:
                        print('terminal startup evidence write failed', file=sys.stderr)
                    finally:
                        startup.close()
            finally:
                for sig, handler in previous.items():
                    signal.signal(sig, handler)


def check_startup(gpsd, stopping, gate):
    path=Path(__file__).resolve().parent/'gpsd-pairing.py'
    spec=importlib.util.spec_from_file_location('gpsd_pairing',path)
    helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
    root=Path('/run/ntpsec-startup');info=root.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid!=0 or stat.S_IMODE(info.st_mode)!=0o700:
        raise ValueError('protected startup directory required')
    result={'supervisor_pid':os.getpid(),'gpsd_pid':gpsd.pid,'started_epoch':time.time(),
            'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
            'started_monotonic':time.monotonic(),
            'gpsd_start_ticks':Path(f'/proc/{gpsd.pid}/stat').read_text().rpartition(')')[2].split()[19]}
    def publish(update=None):
        result['updated_monotonic']=time.monotonic()
        if update is not None:
            result.update(state='acquiring',pairing=update,updated_epoch=time.time())
        tmp=root/'gate.json.new'
        fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'w') as stream:
            json.dump(result,stream);stream.write('\n');stream.flush();os.fsync(stream.fileno())
        tmp.chmod(0o600);os.replace(tmp,root/'gate.json')
    try:
        options={'acquisition_wait':True,'progress':publish} if gate.get('acquisition_policy')=='wait' else {}
        result.update(state='passed',pairing=helper.startup(gpsd,stopping,gate['units'],root,**options))
    except BaseException as error:
        result.update(state='failed',error=str(error)[:500]);raise
    finally:
        publish()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    args = parser.parse_args()
    try:
        for path in (args.config, *args.config.absolute().parents):
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
                raise ValueError('service configuration must be root-owned and protected')
        if not args.config.is_file():
            raise ValueError('regular service configuration required')
        config = json.loads(args.config.read_text())
        raise SystemExit(supervise(config))
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        parser.exit(1, str(exc) + '\n')


if __name__ == '__main__':
    main()
