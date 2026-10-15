#!/usr/bin/python3
"""Seal and execute bounded workstation acceptance or mDNS diagnostic captures."""
import argparse
import hashlib
import importlib.util
import io
import ipaddress
import json
import os
from pathlib import Path
import re
import signal
import tarfile
import time

ROOT = Path(__file__).resolve().parents[1]
PATHS = {'runner.py': 'scripts/run-client-acceptance.py',
         'client.py': 'scripts/check-time-client.py',
         'diagnostic.py': 'scripts/diagnose-mdns.py',
         'diagnostic-tests.py': 'tests/test_mdns_diagnostic.py',
         'paired.py': 'scripts/compare-mdns.py',
         'windows.ps1': 'scripts/capture-mdns-windows.ps1',
         'paired-tests.py': 'tests/test_mdns_paired.py',
         'tests.py': 'tests/test_client_acceptance.py'}


def encoded(value): return (json.dumps(value, sort_keys=True)+'\n').encode()
def sha(raw): return hashlib.sha256(raw).hexdigest()


class CaptureTimeout(Exception):
    """Total deadline, distinct from socket.timeout so receive loops cannot swallow it."""


def module(raw):
    namespace = {'__name__': 'sealed_client'}
    exec(compile(raw, 'sealed-client', 'exec'), namespace)
    return namespace


def private(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 4*1024**2:
        raise ValueError('bounded regular input required')
    if path.stat().st_mode & 0o077: raise ValueError('private input required')
    return path.read_bytes()


def write_new(path, value):
    with path.open('xb') as stream: stream.write(encoded(value))


def review(spec):
    if spec['purpose'] == 'client-native-discovery':
        return f'''# Client timing acceptance with native Windows discovery

Target **{spec['hostname']}**, operation `{spec['operation_id']}`.
Bound monitor archive: `{spec['monitor_sha256']}`.
Execution expires at epoch `{spec['expires_epoch']}`; reserve 60 seconds.

One workstation-only capture. From WSL, send one NTP request and one
administrative READVAR probe to each fixed endpoint, {', '.join(spec['endpoints'])},
UDP 123. Require synchronized stratum-1 PPS responses, matching nonce/timestamps,
plausible server transmit time and no administrative response.

Then use native Windows PowerShell/.NET for mDNS, binding source IPv4
{spec['source_ipv4']} and its multicast interface, TTL 255. Send three queries to
224.0.0.251:5353: _ntp._udp.local PTR and {spec['hostname']}.local A/AAAA. Retain
raw replies and parse them with the same repository matcher proven by the paired
diagnostic. Require completed queries in the expected order, their pinned bytes
and source address, target-source replies, PTR/SRV port 123, accepted hostname
and both fixed addresses. This verifies IPv6 address advertisement over IPv4
multicast, not IPv6 multicast transport. No WSL multicast retry is included.

Three seconds per discovery query, at most 64 replies with 9,001 retained bytes
each; native subprocess bound 20 seconds, total bound 60 seconds. Retain native
stdout/stderr up to 1 MiB each and per-family partial results on failure. Register
execution before sending packets; never replay a consumed or uncertain capture.
No SSH, service/configuration changes, clock adjustment, restart, reboot, cleanup
or unicast DNS deployment. The running service is preserved; nothing needs
restoration. Passing accepts these client checks only, not calibrated UTC
accuracy, sustained timing, persistence or overall production readiness.
No historical archives are embedded; all executable bytes are repository-owned.

Execute from the repository root:
`python3 -I -B ntpsec/scripts/run-client-acceptance.py execute --bundle ABSOLUTE_BUNDLE --sha256 APPROVED_HASH`
'''
    if spec['purpose'] == 'mdns-paired':
        return f'''# Paired Windows/WSL mDNS diagnostic

Target **{spec['hostname']}**, operation `{spec['operation_id']}`.
Monitor provenance: `{spec['monitor_sha256']}`; source IPv4 **{spec['source_ipv4']}**.
Execution expires at epoch `{spec['expires_epoch']}`; reserve 60 seconds.

One sequential native Windows then WSL comparison. Both sockets bind the observed
source IPv4 on ephemeral ports and explicitly select that IPv4 multicast
interface with TTL 255. Send the same three pinned query byte strings in the same
order: _ntp._udp.local PTR and {spec['hostname']}.local A/AAAA, destination
224.0.0.251 UDP 5353. At most six datagrams total. Allow three seconds per query
and at most 64 replies per environment; retain up to 9,001 raw bytes per reply,
sources, receive-window context, parsed records and parser failures. Use the same
repository parser/matcher for both results, including its target-source filter.

Windows uses native PowerShell/.NET UDP sockets; WSL uses Python sockets. Launch
only the bundled Windows function through -EncodedCommand, with a 20-second
subprocess bound. Total capture bound is 60 seconds. Retain stdout/stderr up to
1 MiB each and partial evidence on failure. A failed native process stops the
comparison; an ordinary native capture error is retained for comparison with WSL.
Never replay a consumed or uncertain action. Sequential timing and different
ephemeral ports remain differences; results alone cannot locate a packet drop.

No new interface collection, unicast DNS or NTP probes, SSH, receiver writes,
configuration/firewall/route changes, service restart, reboot or cleanup.
No installation of Windows Python or other software. No client/timing/production
acceptance. No historical archives embedded; preserve the running NTP service.
There are no configuration changes to restore. All response evidence stays private.

Execute from the repository root:
`python3 -I -B ntpsec/scripts/run-client-acceptance.py execute --bundle ABSOLUTE_BUNDLE --sha256 APPROVED_HASH`
'''
    if spec['purpose'] == 'mdns-diagnostic':
        return f'''# Workstation mDNS diagnostic

Target **{spec['hostname']}**, operation `{spec['operation_id']}`.
Bound monitor archive: `{spec['monitor_sha256']}`.
Execution expires at epoch `{spec['expires_epoch']}`; reserve 60 seconds.

One workstation-only capture with a 60-second total bound. Record local interface
addresses and kernel route selection for the target IPv4/IPv6 addresses and
224.0.0.251 using read-only ip commands. Each command has a five-second bound and
retains at most 64 KiB per output stream, including failure details.

Send exactly three mDNS query datagrams, at most: _ntp._udp.local PTR and
{spec['hostname']}.local A/AAAA, to 224.0.0.251:5353 from one ephemeral IPv4 UDP
socket. Use the existing default multicast route, without forcing an interface.
Allow three seconds per query and at most 64 replies across all queries. Retain
up to 9,001 raw bytes per reply as base64, source address/port, query association,
decoded records or parser rejection, and whether the original checker would
accept the source. Preserve mismatched-source replies as diagnostic evidence.
This is socket-response capture, not promiscuous packet capture. Other responders
may appear; all evidence stays private.

Reuse the original checker's parsing and matching logic without changing its
acceptance contract. Record matching as diagnostic information only; no timing,
client or production acceptance. Missing replies do not prove absent advertising.
No unicast DNS resolver queries, NTP probes, SSH, target service/configuration
changes, route changes, firewall changes, restart, reboot or cleanup.

Register execution before collection; retain partial results on failure/timeout.
Never replay an uncertain capture. No restoration is needed because this action
does not modify target or workstation configuration. No historical archives are
embedded. Execute from the repository root:
`python3 -I -B ntpsec/scripts/run-client-acceptance.py execute --bundle ABSOLUTE_BUNDLE --sha256 APPROVED_HASH`
'''
    return f'''# Workstation client timing/mDNS acceptance

Target **{spec['hostname']}**, operation `{spec['operation_id']}`.
Bound monitor archive: `{spec['monitor_sha256']}`.
Execution expires at epoch `{spec['expires_epoch']}`; reserve 60 seconds.

One workstation-only capture: one NTP request and one administrative READVAR
probe to each fixed endpoint, {', '.join(spec['endpoints'])}, UDP 123; then three
bounded legacy-unicast mDNS queries via 224.0.0.251:5353. Require synchronized
stratum-1 PPS responses, matching nonces and plausible timestamps, no external
administrative replies, and _ntp._udp PTR/SRV port 123 resolving to the accepted
hostname and both fixed addresses. mDNS browsing uses IPv4 multicast; this does
not establish IPv6 multicast discovery. No absolute/calibrated accuracy claim.

The process has a 60-second total bound. Register execution before sending any
packet and retain partial per-family results on rejection or timeout. Never
replay an uncertain capture. No SSH, daemon/configuration changes, restart,
reboot, clock adjustment or cleanup. A failure leaves the running service intact;
recovery is unnecessary because this capture changes no target configuration.
Overall production acceptance remains pending even if these client checks pass.
The bundle contains pinned repository code and explicit identity/provenance data,
with no historical archives or executable imports from earlier operations.

Execute from the repository root with:
`python3 -I -B ntpsec/scripts/run-client-acceptance.py execute --bundle ABSOLUTE_BUNDLE --sha256 APPROVED_HASH`
'''


def prepare(bundle, checksum):
    raw = private(bundle)
    if sha(raw) != checksum: raise ValueError('approved bundle digest')
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        members = archive.getmembers()
        names = set(PATHS) | {'spec.json', 'review.md'}
        if (len(members) != len(names) or {m.name for m in members} != names
                or any(not m.isfile() or m.size > 1024**2 for m in members)):
            raise ValueError('closed bounded bundle required')
        files = {m.name: archive.extractfile(m).read() for m in members}
    spec = json.loads(files['spec.json'])
    if (spec['schema'] != 1 or spec['purpose'] not in ('client-acceptance', 'mdns-diagnostic', 'mdns-paired', 'client-native-discovery')
            or not re.fullmatch(r'[a-z][a-z0-9-]{0,47}', spec['operation_id'])
            or not re.fullmatch(r'[a-z][a-z0-9-]{0,62}', spec['hostname'])
            or len(spec['endpoints']) != 2
            or [ipaddress.ip_address(e).version for e in spec['endpoints']] != [4, 6]
            or spec['members'] != {n: sha(files[n]) for n in PATHS}
            or files['review.md'] != review(spec).encode()):
        raise ValueError('client input binding')
    if spec['purpose'] in ('mdns-paired', 'client-native-discovery'):
        source = ipaddress.ip_address(spec['source_ipv4'])
        if source.version != 4 or source.is_multicast or source.is_unspecified or source.is_loopback:
            raise ValueError('explicit unicast workstation source required')
    if any(files[n] != (ROOT / path).read_bytes() for n, path in PATHS.items()):
        raise ValueError('current source drift')
    if any(private(bundle.parent/n) != files[n] for n in ('spec.json', 'review.md')):
        raise ValueError('local review drift')
    if not spec['prepared_epoch']-300 <= time.time() < spec['expires_epoch']-60:
        raise ValueError('execution window expired')
    return spec, files


def seal(args):
    path = ROOT/'scripts/run-service-monitor.py'
    loader = importlib.util.spec_from_file_location('monitor_sealer', path)
    monitor = importlib.util.module_from_spec(loader); loader.loader.exec_module(monitor)
    spec, _ = monitor.prepare(args.monitor_dir/'service-monitor.tar', args.monitor_sha256, require_current=False)
    observed = private(args.monitor_dir/f'observe-{args.observation}-0-result.json')
    observation = json.loads(observed)
    state = observation['result']; record = state['observation']; status = record['monitor']
    now = int(time.time())
    if (observation['spec_sha256'] != sha(private(args.monitor_dir/'spec.json'))
            or state['phase'] != 'monitoring' or state['observations'] != args.observation
            or record['service_state'] != 'active' or status['phase'] != 'ready'
            or status['running'] is not True or not 0 <= now-record['epoch'] < 86400):
        raise ValueError('recent ready monitor observation required')
    files = {n: (ROOT/path).read_bytes() for n, path in PATHS.items()}
    purpose = ('client-native-discovery' if args.native_discovery else 'mdns-paired' if args.paired
               else 'mdns-diagnostic' if args.diagnostic else 'client-acceptance')
    target = {'schema': 1, 'purpose': purpose, 'operation_id': args.operation_id,
              'hostname': spec['hostname'], 'endpoints': spec['endpoints'],
              'monitor_sha256': args.monitor_sha256, 'monitor_spec_sha256': observation['spec_sha256'],
              'observation_sha256': sha(observed), 'observation_number': args.observation,
              'prepared_epoch': now, 'expires_epoch': min(now+86400, record['epoch']+86400),
              'members': {n: sha(v) for n, v in files.items()}}
    if args.paired or args.native_discovery:
        if not args.source_ipv4: raise ValueError('native capture requires observed source IPv4')
        target['source_ipv4'] = args.source_ipv4
    files.update({'spec.json': encoded(target), 'review.md': review(target).encode()})
    os.umask(0o077); args.output.mkdir(mode=0o700)
    for n in ('spec.json', 'review.md'): (args.output/n).write_bytes(files[n])
    bundle = args.output/(target['purpose']+'.tar')
    with tarfile.open(bundle, 'w') as archive:
        for name, raw in sorted(files.items()):
            item = tarfile.TarInfo(name); item.size = len(raw); item.mode = 0o600
            archive.addfile(item, io.BytesIO(raw))
    digest = sha(bundle.read_bytes()); prepare(bundle, digest)
    result = {'bundle': str(bundle), 'sha256': digest, 'target': target['hostname'],
              'expires_epoch': target['expires_epoch'], 'execution_authorized': False}
    write_new(args.output/'sealing.json', result)
    return result


def execute(args):
    os.umask(0o077); spec, files = prepare(args.bundle, args.sha256)
    root = args.bundle.parent
    write_new(root/'execution.json', {'bundle_sha256': args.sha256, 'epoch': int(time.time())})
    result = {'bundle_sha256': args.sha256, 'spec_sha256': sha(files['spec.json']),
              'target': spec['hostname'], 'checks': {}, 'observations': {},
              'client_accepted': False, 'production_accepted': False, 'absolute_accuracy_accepted': False}
    client = module(files['client.py'])
    def expired(*unused): raise CaptureTimeout('client capture exceeded 60 seconds')
    previous = signal.signal(signal.SIGALRM, expired); signal.alarm(60)
    try:
        if spec['purpose'] == 'mdns-paired':
            module(files['paired.py'])['capture'](spec, client, module(files['diagnostic.py']), files['windows.ps1'], result['observations'])
            result['diagnostic_complete'] = True
        elif spec['purpose'] == 'mdns-diagnostic':
            module(files['diagnostic.py'])['capture'](spec, client, result['observations'])
            result['diagnostic_complete'] = True
        else:
            for family, endpoint in zip(('ipv4', 'ipv6'), spec['endpoints']):
                result['observations'][family] = client['client_ntp'](endpoint)
                result['checks'][family] = True
            if spec['purpose'] == 'client-native-discovery':
                native = module(files['paired.py'])
                value = native['native_capture'](spec, client, files['windows.ps1'], result['observations'])
                expected = native['queries'](spec, client)
                actual = [{k: q[k] for k in ('name', 'type', 'query_base64')} for q in value['queries']]
                if (value.get('completed') is not True or value.get('matched') is not True
                        or actual != expected or any(q['socket_address'][0] != spec['source_ipv4'] for q in value['queries'])):
                    raise ValueError('native discovery completion/source/query/mapping acceptance missing')
                result['observations']['mdns'] = {'matched': True, 'transport': 'native-windows-ipv4',
                                                 'packets': len(value['replies'])}
            else:
                result['observations']['mdns'] = client['browse'](spec['endpoints'], spec['hostname'])
            result['checks'].update(mdns=True, queries_denied=True)
            result['client_accepted'] = True
    except Exception as error:
        result['error'] = str(error)[:500]
    finally:
        signal.alarm(0); signal.signal(signal.SIGALRM, previous)
        result['epoch'] = int(time.time()); write_new(root/'result.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__); sub = parser.add_subparsers(dest='action', required=True)
    p = sub.add_parser('seal'); p.add_argument('--monitor-dir', type=Path, required=True)
    p.add_argument('--monitor-sha256', required=True); p.add_argument('--observation', type=int, required=True)
    p.add_argument('--operation-id', required=True); p.add_argument('--output', type=Path, required=True)
    mode = p.add_mutually_exclusive_group()
    mode.add_argument('--diagnostic', action='store_true'); mode.add_argument('--paired', action='store_true')
    mode.add_argument('--native-discovery', action='store_true')
    p.add_argument('--source-ipv4')
    p = sub.add_parser('execute'); p.add_argument('--bundle', type=Path, required=True); p.add_argument('--sha256', required=True)
    args = parser.parse_args(); print(json.dumps(seal(args) if args.action == 'seal' else execute(args), sort_keys=True))


if __name__ == '__main__': main()
