#!/usr/bin/python3
"""Protected monitor activation, structural handoff, observations and restoration."""
import json
import os
from pathlib import Path
import sys
import time
import types


def encoded(value): return (json.dumps(value, sort_keys=True)+'\n').encode()


def sha(raw):
    import hashlib
    return hashlib.sha256(raw).hexdigest()


def module(raw, name):
    result = types.ModuleType(name); result.__file__ = '/sealed/'+name+'.py'
    exec(compile(raw, result.__file__, 'exec'), result.__dict__)
    return result


def transaction_class(base, controller):
    class Transaction(base.Transaction):
        def runtime_context(self, create=False):
            helper = module(self.f['runtime-continuity.py'], 'current_runtime')
            checker = helper.checker(self.f['hardware-checker.py'], self.f['pps-checker.py'])
            return helper.context(self, checker, create)

        def hardware_gate(self, transaction):
            helper = module(self.f['runtime-continuity.py'], 'current_runtime')
            host = helper.checker(self.f['hardware-checker.py'], self.f['pps-checker.py'])
            try:
                return helper.hardware_gate(transaction, host)
            finally:
                # Keep the observation in the operation readback before recovery.
                observed = transaction.state().get('pps_observation')
                if observed is not None:
                    state = self.state(); state['pps_handoff_observation'] = observed
                    self.write('state.json', state)

        def continuity_observation(self, transaction):
            _, _, report = controller.revalidation(self.f)
            fresh = json.loads(self.h.read(self.root/'fresh-preflight.json', limit=32*1024**2))
            actual = fresh['observation']
            if (sha(encoded(actual)) != report['observation_sha256']
                    or actual['boot_id'] != self.s['boot_id']
                    or fresh['checks'] != 'passed'
                    or fresh['restoration_sha256'] != self.s['restoration_sha256']):
                raise ValueError('operation preflight/revalidation binding drift')
            return actual

        def preflight(self):
            fresh, fresh_files, fresh_report = controller.revalidation(self.f)
            fresh_root = Path(fresh['stage']); self.h.ancestors(fresh_root)
            for name, digest in fresh['members'].items():
                if sha(self.h.read(fresh_root/name, limit=64*1024**2)) != digest:
                    raise ValueError('accepted revalidation input drift')
            if (json.loads(self.h.read(fresh_root/'report.json', limit=32*1024**2)) != fresh_report
                    or json.loads(self.h.read(fresh_root/'cleanup.json')) != json.loads(self.f['revalidation-proof.json'])['cleanup']['result']):
                raise ValueError('accepted revalidation report/closure drift')
            checker = module(fresh_files['stage.py'], 'accepted_revalidation')
            prior, prior_files, *_ = checker.validate(fresh, fresh_files)
            prior_proof = json.loads(fresh_files['monitor-proof.json'])
            checker.failed_stage(self.h, prior, prior_files, self.run, prior_proof)
            rspec, archive, report, source = controller.validate(self.s, dict(self.f,
                **{'spec.json': encoded(self.s), 'manifest.json': b'', 'review.md': b''}))
            restored = Path(rspec['stage']); self.h.ancestors(restored)
            for name, digest in rspec['members'].items():
                if sha(self.h.read(restored/name, limit=64*1024**2)) != digest:
                    raise ValueError('restoration stage input drift')
            proof = json.loads(self.f['restoration-proof.json'])
            if (json.loads(self.h.read(restored/'report.json', limit=32*1024**2)) != report
                    or json.loads(self.h.read(restored/'cleanup.json')) != proof['cleanup']['result']):
                raise ValueError('retained restoration report/closure drift')
            validator = module(archive['stage.py'], 'restoration')
            old = json.loads(source['spec.json'])
            fd = validator.source_lock(self.h, rspec, old, source)
            try:
                if self.h.read(Path(old['stage'])/'state.json') != self.h.read(restored/'source-state-before.json'):
                    raise ValueError('historical held source changed')
                timers = validator.timer_state(self.run, old)
                if timers['timer']['ActiveState'] != 'inactive':
                    raise ValueError('old recovery timer not inactive')
                if self.systemctl('show', controller.FAULT_UNIT, '--property=LoadState', '--value').strip() != 'not-found':
                    raise ValueError('monitor fault unit collision')
                if self.systemctl('show', controller.FAULT_UNIT, '--property=DropInPaths', '--value').strip():
                    raise ValueError('monitor fault unit drop-ins')
                if list(Path('/etc/systemd/system/'+controller.FAULT_UNIT+'.d').glob('*')):
                    raise ValueError('monitor fault unit drop-in directory')
                super().preflight()
                root = self.root/'runtime-check'
                check = base.load(root/'host-configuration-stage.py').Transaction(json.loads(self.h.read(root/'spec.json')))
                actual = check.core.i.observation()
                if sha(encoded(actual)) != fresh_report['observation_sha256']:
                    raise ValueError('fresh restored-state continuity drift')
                self.write('fresh-preflight.json', {'epoch': int(time.time()), 'observation': actual,
                    'restoration_sha256': self.s['restoration_sha256'], 'checks': 'passed'})
            finally:
                os.close(fd)

        def arm(self):
            self.run(['/usr/bin/systemd-run', '--quiet', '--unit='+self.s['recovery_unit'],
                      '--on-active=600s', '--timer-property=AccuracySec=1s',
                      '--property=WorkingDirectory='+str(self.root), '--property=RuntimeMaxSec=240',
                      '--property=TimeoutStopSec=20', '--property=UMask=0077',
                      '/usr/bin/python3', '-I', '-B', str(self.root/'stage.py'), 'worker', 'watchdog'])
            if self.systemctl('is-active', self.s['recovery_unit']+'.timer').strip() != 'active':
                raise ValueError('installation watchdog not armed')

        def monitor_record(self):
            raw = self.h.read(self.root/'startup-monitor.json', limit=512*1024)
            value = json.loads(raw)
            if (value.get('boot_id') != self.s['boot_id'] or value.get('supervisor_pid') != self.state()['supervisor_pid']
                    or value.get('final_sha256') != sha(self.f['ntp.conf'])):
                raise ValueError('operation monitor identity/configuration mismatch')
            return value

        def accept(self, proofs):
            # Structural handoff is intentionally separate from timing acceptance.
            with self.lock():
                state = self.state()
                if state['phase'] != 'observing' or state['deadline']-time.monotonic() < 60:
                    raise ValueError('one observing installation and recovery reserve required')
                if not proofs or set(proofs) != {*self.s['endpoints'], 'client'}:
                    raise ValueError('dual-stack and structural client proof required')
                for endpoint in self.s['endpoints']:
                    proof = proofs[endpoint]
                    if (proof.get('phase') != 'observing' or proof.get('supervisor_pid') != state['supervisor_pid']
                            or proof.get('apply_monotonic') != state['apply_monotonic']):
                        raise ValueError('same installation on both endpoints required')
                client = proofs['client']
                if (client.get('target') != self.s['hostname'] or client.get('spec_sha256') != sha(encoded(self.s))
                        or client.get('checks') != {'ipv4': True, 'ipv6': True, 'queries_denied': True}
                        or client.get('time_service_accepted') is not False
                        or not 0 <= time.time()-client.get('epoch', 0) < 120):
                    raise ValueError('fresh structural-only client proof required')
                self.unchanged()
                state = self.state()
                value = self.measure()
                if not all(value['checks'].get(k) is True for k in controller.SAFETY):
                    raise ValueError('structural service safety failed')
                record = self.monitor_record()
                if (record.get('running') is not True or record.get('phase') not in ('bootstrap', 'promoted', 'settling', 'ready')
                        or not 0 <= time.monotonic()-record['started_monotonic']-record['elapsed_seconds'] <= 60):
                    raise ValueError('live monitor required for handoff')
                if state['deadline']-time.monotonic() < 60:
                    raise ValueError('installation watchdog reserve exhausted')
                state.update(phase='monitoring', handoff_epoch=int(time.time()), time_service_accepted=False,
                             handoff_proofs=proofs, handoff_measurement=value, observations=0)
                self.write('state.json', state)
                try:
                    self.cancel_timer()
                    if self.systemctl('show', self.s['recovery_unit']+'.timer', '--property=ActiveState', '--value').strip() not in ('inactive', ''):
                        raise ValueError('watchdog cancellation not confirmed')
                except BaseException:
                    state['phase'] = 'handoff_held'; self.write('state.json', state)
                    self.recover(locked=True)
                    raise
                return state

        def observe(self, proof):
            with self.lock():
                state = self.state(); attempt = proof.get('attempt') if isinstance(proof, dict) else None
                if (state['phase'] != 'monitoring' or type(attempt) is not int
                        or attempt != state['observations']+1 or not 1 <= attempt <= 60):
                    raise ValueError('one sequential bounded monitoring capture required')
                now = time.monotonic(); prior = state.get('observation', {})
                interval = 300 if prior.get('monitor', {}).get('phase') == 'ready' else 30
                if now-state.get('observed_monotonic', -interval) < interval:
                    raise ValueError('monitor observation interval')
                value = self.monitor_record()
                active = self.systemctl('show', 'timeservice.service', '--property=ActiveState', '--value').strip()
                result = {'epoch': int(time.time()), 'monotonic': now, 'monitor': value,
                          'service_state': active, 'time_service_accepted': False}
                self.h.create(self.root/f'observation-{attempt}.json', encoded(result))
                state.update(observations=attempt, observed_monotonic=now, observation=result)
                self.write('state.json', state)
                return state

        def watchdog(self):
            with self.lock():
                if self.state()['phase'] in ('monitoring', 'recovered'): return self.state()
                return self.recover(locked=True)

        def recover(self, locked=False):
            if not locked:
                with self.lock(): return self.recover(locked=True)
            self.recovering = True
            result = super().recover(locked=True)
            # RuntimeDirectory is gone after stop; retain the durable terminal record.
            if (self.root/'startup-monitor.json').exists():
                result['startup_promotion'] = json.loads(self.h.read(self.root/'startup-monitor.json', limit=512*1024))
                self.write('state.json', result)
            return result

    return Transaction


def entry(spec, files, mode, proofs=None):
    controller = module(files['controller.py'], 'monitor_controller')
    controller.validate(spec, dict(files, **{'spec.json': encoded(spec), 'manifest.json': b'', 'review.md': b''}))
    base = module(files['base-stage.py'], 'monitor_base')
    base.DESTINATIONS = dict(base.DESTINATIONS, **{'/etc/systemd/system/'+controller.FAULT_UNIT: ('fault.service', 0o644)})
    base.Transaction = transaction_class(base, controller)
    if mode in ('handoff', 'observe', 'watchdog'):
        # Reuse the complete identity/staging/member checks before dispatch.
        base.entry(spec, files, 'readback')
        tx = base.Transaction(spec, files)
        if mode == 'handoff': return tx.accept(proofs)
        if mode == 'observe': return tx.observe(proofs)
        return tx.watchdog()
    if mode == 'accept': raise ValueError('timing acceptance is not in this operation')
    if mode == 'cleanup':
        base.entry(spec, files, 'readback')
        tx = base.Transaction(spec, files)
        if tx.state()['phase'] != 'recovered': raise ValueError('recovery required before monitor cleanup')
        if tx.systemctl('show', controller.FAULT_UNIT, '--property=ActiveState', '--value').strip() in ('active', 'activating', 'deactivating'):
            raise ValueError('monitor recovery worker still running')
        if tx.systemctl('show', controller.FAULT_UNIT, '--property=LoadState', '--value').strip() != 'not-found':
            tx.systemctl('reset-failed', controller.FAULT_UNIT)
    return base.entry(spec, files, mode, proofs)


if __name__ == '__main__':
    if len(sys.argv) != 3 or sys.argv[1] != 'worker': raise SystemExit('sealed worker only')
    root = Path(__file__).resolve().parent; spec = json.loads((root/'spec.json').read_bytes())
    files = {n: (root/n).read_bytes() for n in spec['members']}
    entry(spec, files, sys.argv[2])
