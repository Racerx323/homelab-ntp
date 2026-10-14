#!/usr/bin/python3
"""Recheck accepted runtime facts without renewing historical acceptance dates."""
import json
import os
from pathlib import Path
import time
import types


def module(raw):
    result = types.ModuleType("runtime_data"); result.__file__ = "/sealed/runtime-artifacts.py"
    exec(compile(raw, result.__file__, "exec"), result.__dict__)
    return result


def checker(host_raw, pps_raw):
    """Load the two explicitly sealed current checkers, never a historical copy."""
    host = types.ModuleType('current_hardware'); pps = types.ModuleType('current_pps')
    for target, raw in ((host, host_raw), (pps, pps_raw)):
        target.__file__ = '/sealed/'+target.__name__+'.py'
        exec(compile(raw, target.__file__, 'exec'), target.__dict__)
    host.gpio_pps_metadata = pps.gpio_pps_metadata
    return host


def hardware_gate(tx, host):
    gate = tx.spec['hardware_prerequisite']; root = Path(gate['stage'])
    raw = tx.h.read(root/'spec.json', limit=2*1024**2)
    state = json.loads(tx.h.read(root/'state.json'))
    closure = json.loads(tx.h.read(tx.root/'hardware-cleanup.json'))
    receipt = json.loads(tx.h.read(tx.root/'hardware-acceptance.json'))
    if (tx.h.sha(raw) != gate['spec_sha256'] or closure['bundle_sha256'] != gate['bundle_sha256']
            or state != closure['result'] or state.get('phase') != 'accepted'
            or state.get('accepted_boot_id') != host.boot_id()
            or type(state.get('accepted_epoch')) is not int or not 0 < state['accepted_epoch'] <= time.time()+300
            or state.get('checks') != dict.fromkeys(host.HARDWARE_LABELS, True)
            or any(value is not True for value in state['checks'].values())
            or receipt is None or receipt['spec_sha256'] != gate['spec_sha256']
            or receipt['bundle_sha256'] != gate['bundle_sha256']
            or receipt['boot_id'] != state['accepted_boot_id'] or receipt['checks'] != state['checks']
            or receipt['hardware'] != state['hardware']):
        raise ValueError('immutable accepted hardware provenance/current boot required')
    for name, digest in gate['boot_hashes'].items():
        if tx.h.sha(tx.h.read(Path(name))) != digest:
            raise ValueError('current hardware boot-file drift')
    previous = tx.recipe; tx.recipe = json.loads(raw)['host_recipe']
    try: actual = host.Transaction.hardware_metadata(tx, state['hardware']['pps'])
    finally: tx.recipe = previous
    if actual != state['hardware']:
        raise ValueError('current hardware mapping/permission drift')
    # The historic epoch stays unchanged; callers record their own observation time.
    return state


def transaction(host, spec, checker):
    class CurrentRuntime(host.Transaction):
        def hardware_gate(self): return hardware_gate(self, checker)
    return CurrentRuntime(spec)


def context(tx, checker, create=False):
    """Check private runtime copies; preserve every original accepted source byte."""
    a, h, files, alias = tx.a, tx.h, tx.rf, tx.alias
    runtime, old = a.validate(alias, files, historical=True)
    fd, retained = a.source_guard(h, alias, old)
    try:
        if json.loads(retained['state.json']) != json.loads(files['runtime-cleanup.json'])['result']:
            raise ValueError('accepted runtime source state changed')
        sub = tx.root/'runtime-check'
        runtime, current = module(tx.f['runtime-artifacts.py']).runtime_inputs(runtime, old, tx.f, sub)
        if create:
            sub.mkdir(mode=0o700)
            for name in runtime['members']: h.create(sub/name, current[name])
            for name, raw in retained.items(): h.create(sub/name, raw)
            h.create(sub/'spec.json', a.encoded(runtime))
        else:
            for name, digest in runtime['members'].items():
                if a.sha(h.read(sub/name)) != digest: raise ValueError('runtime helper input drift')
            if json.loads(h.read(sub/'spec.json')) != runtime: raise ValueError('runtime copy spec drift')
        check = transaction(a.load(sub/'host-configuration-stage.py'), runtime, checker)
        check.run = tx.run; check.core.run = tx.run
        # Keep the frozen observer's own timeout/output/stderr rejection contract.
        result = check.probe()
        if any(h.read(Path(alias['source_stage'])/name) != raw for name, raw in retained.items()):
            raise ValueError('original runtime source changed')
        return {'epoch': int(time.time()), 'runtime': result, 'observation': check.core.i.observation()}
    finally: os.close(fd)
