#!/usr/bin/python3
"""Acceptance and cleanup only for the terminal, successful v4 package command."""
import copy
import json
import os
import time

PREFIX = 'acceptance-continuation-v1'
ORIGIN_STAGE = '/var/lib/ntp-foundation-v4'
ORIGIN_BUNDLE = '5d93117ed7433099b296325f4229d6efde4e02b7344176030552007cc65767a4'
ORIGIN_SPEC = '4a7caac7c360d69807da2c6ca1681a73f1bb7c203a86975fa12a59fbe8b788ec'
ADDITIONS = {
    '/etc/dpkg/dpkg.cfg.d/needrestart': 'a906969392a7a72cbe731718792a98c396f8aee414760b8b0c51fbc7477d5ca7',
    '/usr/lib/needrestart/dpkg-status': '54873b813a8eaefb516a221b6cb9c013f7a6396414028a692bc31b6e171acbaa',
}


def continued_spec(spec):
    if (spec['origin_bundle_sha256'] != ORIGIN_BUNDLE or spec['origin']['stage'] != ORIGIN_STAGE
            or spec['hostname'] != spec['origin']['hostname']
            or spec['kernel'] != spec['origin']['kernel']
            or spec['origin_spec_sha256'] != ORIGIN_SPEC
            or spec['package_additions'] != ADDITIONS
            or spec['origin']['directories']['/etc/dpkg/dpkg.cfg.d'] != []):
        raise ValueError('fixed original operation and exact packaged additions required')
    result = copy.deepcopy(spec['origin'])
    result['directories']['/etc/dpkg/dpkg.cfg.d'] = ['needrestart']
    result['package_created_inputs'].update(spec['package_additions'])
    return result


def continue_entry(spec, files, epoch, mode, worker):
    os.umask(0o077)
    worker.DEADLINE = time.monotonic() + 600
    if mode not in ('recover', 'readback') or str(worker.STAGE) != ORIGIN_STAGE:
        raise ValueError('acceptance/cleanup continuation only; no installation or configuration repair')
    if set(files) != {'worker.py'} or worker.sha(files['worker.py']) != spec['members']['worker.py']:
        raise ValueError('sealed continuation worker mismatch')
    if not spec['prepared_epoch'] - 300 <= time.time() < spec['expires_epoch']:
        raise ValueError('continuation approval window expired')
    origin = spec['origin']
    adjusted = continued_spec(spec)
    worker.validate_spec(origin)
    worker.identity(origin, epoch)
    worker.ancestors(worker.STAGE)
    if worker.sha(worker.read(worker.STAGE / 'spec.json')) != spec['origin_spec_sha256']:
        raise ValueError('original sealed specification drift')
    if json.loads(worker.read(worker.STAGE / 'spec.json')) != origin:
        raise ValueError('original specification differs from continuation binding')
    for name, checksum in origin['members'].items():
        if worker.sha(worker.read(worker.STAGE / name)) != checksum:
            raise ValueError('original protected member drift: ' + name)
    if worker.read(worker.STAGE / 'apt.conf') != worker.apt_config(origin):
        raise ValueError('original APT config drift')
    for operation in ('validate', 'listchanges', 'debconf', 'needrestart'):
        if worker.read(worker.STAGE / ('hook-' + operation)) != worker.hook_wrapper(operation):
            raise ValueError('original hook wrapper drift')
    if mode == 'readback':
        return {'state': 'continuation_readback_collected', 'stage': ORIGIN_STAGE}
    if (worker.STAGE / 'complete.json').exists() or (worker.STAGE / (PREFIX + '-complete.json')).exists():
        raise ValueError('accepted operation cannot be replayed')
    started = json.loads(worker.read(worker.STAGE / 'apt-install-started.json'))
    terminal = json.loads(worker.read(worker.STAGE / 'apt-install-terminal.json'))
    if (any(terminal[k] != started[k] for k in ('boot', 'pid', 'start_ticks', 'argv'))
            or started['boot'] != worker.boot() or worker.process_ticks(started['pid']) == started['start_ticks']
            or terminal['exit_status'] != 0 or terminal.get('failure')):
        raise ValueError('original package process not successful/terminal on unchanged boot')
    for mode in ('listchanges', 'debconf', 'needrestart'):
        record = json.loads(worker.read(worker.STAGE / ('hook-' + mode + '-terminal.json')))
        if record['exit_status'] != 0 or record.get('failure'):
            raise ValueError('original hook failure; no acceptance-only continuation')
    worker.read(worker.STAGE / 'hook-validate-accepted.json')
    worker.locks_free()
    worker.guard_controls()
    # Original control/payload bytes stay immutable. New evidence uses distinct labels.
    worker.record(PREFIX + '-claim', {'origin_bundle_sha256': ORIGIN_BUNDLE,
                                     'continuation_spec_sha256': worker.sha((json.dumps(spec, sort_keys=True) + '\n').encode()),
                                     'controller_epoch': epoch, 'boot': worker.boot()})
    try:
        worker.acceptance(adjusted, PREFIX)
        worker.restore_controls(adjusted, True, PREFIX)
    except BaseException as exc:
        worker.record(PREFIX + '-failure', {'state': 'continuation_held',
                      'error': type(exc).__name__ + ': ' + str(exc), 'automatic_replay_authorized': False})
        raise
    result = {'state': 'foundation_accepted_after_continuation', 'packages_installed': 44,
              'package_installation_repeated': False, 'package_configuration_repair': False,
              'temporary_controls_restored': True, 'final_needrestart_policy_retained': True}
    worker.record(PREFIX + '-complete', result)
    return result
