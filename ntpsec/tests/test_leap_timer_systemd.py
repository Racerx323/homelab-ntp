#!/usr/bin/python3
"""Opt-in integration fixture: run only inside an isolated Podman systemd container.

Mount ntpsec read-only at /work. Run with 'initial', restart that same container,
then run with 'reboot'. No host or production service is used. Accelerated
intervals exercise real systemd scheduling, not a mock timer implementation.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

UNITS = Path('/etc/systemd/system')
STATE = Path('/var/lib/leap-timer-fixture.json')


def run(*args):
    return subprocess.check_output(args, text=True, timeout=15).strip()


def ctl(*args):
    return run('systemctl', *args)


def last(name):
    return int(ctl('show', name+'.service', '--property=ExecMainStartTimestampMonotonic', '--value') or '0')


def await_run(name, previous=0, timeout=30):
    deadline = time.monotonic()+timeout
    while time.monotonic() < deadline:
        value = last(name)
        if value > previous:
            assert ctl('show', name+'.service', '--property=Result', '--value') == 'success'
            return value
        time.sleep(0.2)
    raise AssertionError('timer did not fire: '+name)


def install(name, text):
    (UNITS/(name+'.timer')).write_text(text.replace('Unit=ntpleapfetch.service', 'Unit='+name+'.service'))
    (UNITS/(name+'.service')).write_text('[Service]\nType=oneshot\nExecStart=/bin/true\n')


def main():
    assert Path('/run/.containerenv').exists(), 'isolated Podman container required'
    assert Path('/proc/1/comm').read_text().strip() == 'systemd', 'systemd PID 1 required'
    assert sys.argv[1:] in (['initial'], ['reboot'], ['upgrade'], ['transaction'])
    template = Path('/work/templates/ntpleapfetch.timer').read_text()
    assert 'OnBootSec=15min' in template and 'OnUnitActiveSec=4w' in template
    assert 'OnActiveSec=' not in template
    version = ctl('--version').splitlines()[0]
    print(version, flush=True)
    print('template SHA256', hashlib.sha256(template.encode()).hexdigest(), flush=True)
    if sys.argv[1] == 'transaction':
        import importlib.util
        import socket
        # Exercise the real worker against harmless services and container files.
        entry = importlib.util.spec_from_file_location('correction', '/work/scripts/run-leap-timer-correction.py')
        runner = importlib.util.module_from_spec(entry); entry.loader.exec_module(runner)
        # Shorten only the boot wait: retain the production four-week interval
        # and jitter while testing the unmodified transaction implementation.
        transaction_timer = template.replace('15min','3s')
        original = transaction_timer.replace('OnBootSec=', 'OnActiveSec=')
        previous = last('ntpleapfetch')
        ctl('stop','ntpleapfetch.timer')
        install('ntpleapfetch', original.replace('3s','1s').replace('30min','0'))
        ctl('daemon-reload'); ctl('enable','--now','ntpleapfetch.timer')
        await_run('ntpleapfetch',previous,timeout=10)
        ctl('stop','ntpleapfetch.timer'); install('ntpleapfetch',original)
        (UNITS/'timeservice.service').write_text('[Service]\nExecStart=/bin/sleep infinity\n')
        ctl('daemon-reload'); ctl('start','timeservice.service'); ctl('start','ntpleapfetch.timer')
        leap = Path(runner.base.LEAP); leap.parent.mkdir(parents=True,exist_ok=True)
        leap.write_text('#@ '+str(int(time.time())+2208988800+180*86400)+'\n')
        spec = {'operation_id':'container-timer-transaction-v2','hostname':socket.gethostname().split('.')[0],
                'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip()}
        baseline = {'files':{p:runner.h.file_record(p,content=True) for p in
                            (runner.base.SERVICE,runner.base.TIMER,runner.base.LEAP)}}
        operation = runner.worker.TimerCorrection(spec,baseline,transaction_timer.encode(),runner.h)
        baseline['service'] = operation.unit('timeservice.service')
        result = operation.run()
        Path('/var/lib/leap-timer-transaction-v2-result.json').write_text(json.dumps(result,indent=2)+'\n')
        assert result['accepted'], result
        assert result['checks'] == dict.fromkeys(runner.worker.CHECKS,True)
        ctl('stop','ntpleapfetch.timer'); ctl('stop','timeservice.service')
        print('PASS real correction worker: prior run preserved, production four-week schedule, reload, continuity', flush=True)
        return
    if sys.argv[1] == 'upgrade':
        accelerated = template.replace('15min', '3s').replace('4w', '20s').replace('30min', '1s')
        accelerated = accelerated.replace('[Timer]', '[Timer]\nAccuracySec=100ms')
        install('leap-upgrade', accelerated.replace('OnBootSec=', 'OnActiveSec='))
        ctl('daemon-reload'); ctl('enable', '--now', 'leap-upgrade.timer')
        first = await_run('leap-upgrade', timeout=10)
        trigger = ctl('show', 'leap-upgrade.timer', '--property=LastTriggerUSec', '--value')
        ctl('stop', 'leap-upgrade.timer')
        install('leap-upgrade', accelerated)
        ctl('daemon-reload'); ctl('start', 'leap-upgrade.timer')
        assert last('leap-upgrade') == first
        assert ctl('show', 'leap-upgrade.timer', '--property=LastTriggerUSec', '--value') == trigger
        ctl('daemon-reload'); time.sleep(7)
        assert last('leap-upgrade') == first, 'upgrade/reload repeated initial run'
        second = await_run('leap-upgrade', first, timeout=30)
        elapsed = (second-first)/1_000_000
        assert 19.5 <= elapsed <= 24, elapsed
        ctl('stop', 'leap-upgrade.timer')
        print('PASS same-unit upgrade preserves prior trigger, survives reload, recurs:', elapsed, flush=True)
        return
    if sys.argv[1] == 'reboot':
        old = json.loads(STATE.read_text())
        first = await_run('leap-candidate')
        assert ctl('is-enabled', 'leap-candidate.timer') == 'enabled'
        ctl('daemon-reload')
        time.sleep(7)
        assert last('leap-candidate') == first, 'reboot then reload retriggered initial expression'
        print('PASS fresh container boot: enabled timer fires, reload does not repeat initial run', flush=True)
        print('prior phase:', old['result'], flush=True)
        return

    assert not STATE.exists(), 'single-use fixture; retain failed container for diagnosis'
    # Validate the unchanged production-duration unit with a harmless service.
    install('ntpleapfetch', template)
    run('systemd-analyze', 'verify', str(UNITS/'ntpleapfetch.timer'), str(UNITS/'ntpleapfetch.service'))
    ctl('daemon-reload')
    props = ctl('show', 'ntpleapfetch.timer', '--property=TimersMonotonic')
    assert 'OnBootUSec=15min' in props and 'OnUnitActiveUSec=4w' in props, props
    print('PASS production-duration unit parses: boot 15min, recurrence 4w', flush=True)

    accelerated = template.replace('15min', '3s').replace('4w', '20s').replace('30min', '1s')
    accelerated = accelerated.replace('[Timer]', '[Timer]\nAccuracySec=100ms')
    install('leap-candidate', accelerated)
    install('leap-control', accelerated.replace('OnBootSec=', 'OnActiveSec='))
    ctl('daemon-reload')
    # Enable after the boot-relative deadline: it must still receive an initial run.
    time.sleep(4)
    ctl('enable', '--now', 'leap-candidate.timer')
    ctl('start', 'leap-control.timer')
    first = await_run('leap-candidate', timeout=10)
    control = await_run('leap-control', timeout=10)
    print('PASS late enable: candidate and old-profile control both fired', flush=True)
    ctl('daemon-reload')
    await_run('leap-control', control, timeout=10)
    assert last('leap-candidate') == first, 'reload retriggered candidate initial expression'
    ctl('stop', 'leap-control.timer')
    print('PASS reload: old-profile control repeats early; corrected timer does not', flush=True)
    second = await_run('leap-candidate', first, timeout=30)
    elapsed = (second-first)/1_000_000
    assert 19.5 <= elapsed <= 24, ('recurrence interval', elapsed)
    ctl('daemon-reload')
    time.sleep(7)
    assert last('leap-candidate') == second, 'reload after recurrence triggered extra run'
    print('PASS recurring interval and reload after recurrence:', elapsed, flush=True)
    STATE.write_text(json.dumps({'result':'passed', 'systemd':version, 'recurrence_seconds':elapsed}))
    print('Restart this isolated container, then run reboot phase.', flush=True)


if __name__ == '__main__':
    main()
