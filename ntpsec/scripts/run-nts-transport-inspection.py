#!/usr/bin/python3
"""Seal scoped controller policy retrieval and target NTS TCP diagnostics offline."""
import argparse
from datetime import datetime,timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pwd
import shutil
import sys
import time
import types

ROOT=Path(__file__).resolve().parents[1]
PATHS={'stage.py':'scripts/run-nts-transport-inspection.py','base.py':'scripts/run-cutover-inspection.py',
       'network.py':'scripts/inspect-nts-network.py','recipe.json':'configs/nts-transport-inspection.json',
       'controller.py':'scripts/run-service-cutover.py','transport.py':'scripts/run-foundation-preflight.py',
       'tests.py':'tests/test_nts_transport_inspection.py','base-tests.py':'tests/test_cutover_inspection.py',
       'architecture.md':'docs/ntp-architecture-deployment-plan-v1.0.md','operations.md':'docs/OPERATIONS.md',
       'history.md':'HISTORY.md','network-access.md':'../../homelab-network/Ubiquiti/UNIFI_ACCESS.md'}
CAPTURE_FILES=('source-state.json','metadata.json','addresses.json','addresses.stdout','addresses.stderr',
               'services.json','services.stdout','services.stderr','resolve.json','resolve.stdout','resolve.stderr',
               'routes.json','root-probes.json','root-probes.stdout','root-probes.stderr',
               'ntp-probes.json','ntp-probes.stdout','ntp-probes.stderr')


def encoded(value):return (json.dumps(value,sort_keys=True)+'\n').encode()
def sha(raw):return hashlib.sha256(raw).hexdigest()


def module(raw,name):
    ns={'__name__':name,'__file__':str(ROOT/'scripts'/name)}
    exec(compile(raw,name,'exec'),ns);return types.SimpleNamespace(**ns)


def collect(h,spec,files,d):
    root=Path(spec['stage']);source=Path(spec['source_stage']);r=json.loads(files['recipe.json'])
    n=module(files['network.py'],'network.py');n.validate_recipe(r)
    lock=d.source_lock(h,spec,files)
    try:
        saved=h.read(source/'state.json');h.create(root/'source-state.json',saved)
        if d.metadata(Path('/etc/ntp.conf'))!={'exists':False}:raise ValueError('recovered configuration absence required')
        account=pwd.getpwnam('ntp')
        if (account.pw_uid,account.pw_gid)!=(r['ntp_uid'],r['ntp_gid']):raise ValueError('NTP account identity drift')
        ip=shutil.which('ip',path=d.ENV['PATH'])
        if ip not in ('/usr/sbin/ip','/usr/bin/ip','/sbin/ip','/bin/ip'):raise ValueError('reviewed iproute tool unavailable')
        h.create(root/'metadata.json',encoded({'ntp_conf_exists':False,'ntp_uid':account.pw_uid,'ntp_gid':account.pw_gid,
                    'boot_id':spec['boot_id'],'ip_executable':ip,'service_sandbox_reproduced':False}))
        d.command(h,root,'addresses',[ip,'-j','address','show'])
        services=d.command(h,root,'services',['/usr/bin/systemctl','show','--no-pager','--property=Id,LoadState,ActiveState,SubState',
                                             'timeservice.service','systemd-timesyncd.service'])
        first=services.decode().split('\n\n')[0]
        if 'Id=timeservice.service' not in first or 'ActiveState=inactive' not in first:raise ValueError('inactive trial service required')
        raw=d.command(h,root,'resolve',['/usr/bin/python3','-I','-B',str(root/'network.py'),'resolve',str(root/'recipe.json')])
        rows=json.loads(raw);routes=[]
        for index,row in enumerate(rows):
            if 'address' not in row:continue
            name='route-'+str(index)
            try:output=d.command(h,root,name,[ip,'-j','-'+str(row['family']),'route','get',row['address']])
            except ValueError:
                routes.append({'endpoint':row,'command':json.loads(h.read(root/(name+'.json'))),
                               'stdout':h.read(root/(name+'.stdout')).decode(errors='replace'),
                               'stderr':h.read(root/(name+'.stderr')).decode(errors='replace')})
                h.create(root/'routes.json',encoded(routes));raise
            routes.append({'endpoint':row,'route':json.loads(output)})
        h.create(root/'routes.json',encoded(routes))
        for context in ('root','ntp'):
            d.command(h,root,context+'-probes',['/usr/bin/python3','-I','-B',str(root/'network.py'),'probe',str(root/'recipe.json'),context,str(root/'resolve.stdout')])
        if h.read(source/'state.json')!=saved:raise ValueError('original recovered state changed')
        return {'connections_maximum':r['maximum_connections'],'contexts':['root','ntp'],
                'service_sandbox_reproduced':False,'nts_authentication_tested':False,'udp_probed':False}
    finally:os.close(lock)


def review(spec):
    return f'''# UniFi policy and NTS transport inspection: {spec['operation_id']}

Targets: **{spec['hostname']}**, pinned IPv4/IPv6 management endpoints and boot
`{spec['boot_id']}`; **udmbt.local.theama.co** at 10.1.0.1 over verified HTTPS.
Expires {datetime.fromtimestamp(spec['expires_epoch'],timezone.utc).isoformat()}. One controller collection and one target
capture only. Separate execution approval binds this whole archive's SHA-256.

Controller first: verify DNS and TLS hostname/chain, then retrieve AUDIT_LOCAL
from Doppler homelab-dev/prd_unifi in process memory. Never write the credential
or raw authentication output. Only HTTPS GETs to the local Network integration
API: info, sites, zones, networks, policies, both Default LAN-zone/External-zone
orderings, and at most 16 referenced traffic matching lists. At most 40 requests,
400 rows per paginated endpoint, 2 MiB per response, 16 MiB total, 300 seconds.
Policy listing necessarily includes other site policies; keep sanitized results
private. No clients, cloud API, gateway SSH, policy writes or credential bypass.
A missing endpoint, permission failure, ambiguous site/network/zone, pagination
or ordering mismatch holds the stage. No fallback API or authentication retry.
This timestamped configuration snapshot does not prove a live rule hit; traffic
logs/counters are unavailable unless present in the returned policy metadata.

Only after controller capture succeeds, stage one root-owned 0700 node capture
at `{spec['stage']}`. Recheck the approved boot, recovered source state and inputs;
read interface/address metadata and six route selections. Resolve the three
configured upstreams, choose at most one public A and one public AAAA answer per
name, and attempt TCP 4460 once per address under root and once under uid 999/gid
985 with supplementary groups removed: maximum 12 connections, 2 seconds each.
Record actual local source address, outcome/errno and timing. No retries, TLS
handshakes, NTS cookies, UDP packets, ntpd/GPSD start or clock/receiver writes.
NTP-account probes do not reproduce ntpd seccomp or systemd sandboxing; a success
there does not prove the original service can connect. Missing DNS/routes hold
or record incomplete coverage rather than switching families silently.

The node worker remains bounded to 90 seconds with 20-second commands and 8 MiB
retrieval bounds. Conditional terminal readback through both pinned management
endpoints, at most three numbered attempts, must match before node diagnostic
closure. Preserve all original and new evidence. Cleanup only records closure;
there is no firewall/service rollback because no settings change. Failed TCP
attempts are diagnostic observations, not a failed collector. Acceptance proves
collection, never rule attribution, NTS authentication or time service.

Controller and node commands, in order, after approval:
`python3 -I -B ntpsec/scripts/run-nts-transport-inspection.py execute --bundle <archive> --sha256 <approved-hash> --mode unifi`
Then the same command with `--mode start`, `--mode readback --attempt 1`, and
`--mode cleanup`. Never repeat a submitted collection after transport loss.
Hold on incomplete evidence and obtain a new review for any changed scope.
'''


def base(files=None):
    raw=files['base.py'] if files else (ROOT/'scripts/run-cutover-inspection.py').read_bytes()
    # Use a real module namespace so function-global overrides are effective.
    d=types.ModuleType('nts_diagnostic_base');d.__file__=str(ROOT/'scripts/run-cutover-inspection.py')
    exec(compile(raw,d.__file__,'exec'),d.__dict__)
    d.ROOT=ROOT;d.PATHS=PATHS;d.CAPTURE_FILES=CAPTURE_FILES;d.review=review
    d.collect=lambda h,s,f:collect(h,s,f,d)
    original=d.validate
    def validate(s,f):
        original(s,f);module(f['network.py'],'network.py').validate_recipe(json.loads(f['recipe.json']))
    d.validate=validate
    return d


def entry(spec,files,mode,proofs=None):return base(files).entry(spec,files,mode,proofs)


def execute(args):
    d=base();spec,files=d.prepare(args.bundle,args.sha256);r=json.loads(files['recipe.json'])
    t=d.load(ROOT/'scripts/run-foundation-preflight.py');directory=args.bundle.parent;os.umask(0o077)
    if args.mode=='unifi':
        if not spec['prepared_epoch']-300<=time.time()<spec['expires_epoch']:raise ValueError('inspection expired')
        t.write_new(directory/'unifi-execution.json',{'bundle_sha256':args.sha256,'epoch':int(time.time())})
        report=module(files['network.py'],'network.py').controller_collect(r)
        t.write_new(directory/'unifi-report.json',report)
        receipt={'bundle_sha256':args.sha256,'report_sha256':sha(encoded(report)),'state':report['phase']}
        t.write_new(directory/'unifi-receipt.json',receipt)
        return {'mode':'unifi','phase':report['phase'],'error':report.get('error')}
    if args.mode=='start':
        receipt=json.loads(t.private_file(directory/'unifi-receipt.json'))
        raw=t.private_file(directory/'unifi-report.json',32*1024**2)
        if receipt!={'bundle_sha256':args.sha256,'report_sha256':sha(raw),'state':'captured'}:raise ValueError('successful bound controller capture required')
    result=d.execute(args)
    if args.mode=='readback':
        combined={'bundle_sha256':args.sha256,'node':json.loads(t.private_file(directory/'acceptance.json')),
                  'controller':json.loads(t.private_file(directory/'unifi-receipt.json')),'time_service_accepted':False}
        path=directory/'inspection-acceptance.json'
        if path.exists():
            if json.loads(t.private_file(path))!=combined:raise ValueError('combined receipt changed')
        else:t.write_new(path,combined)
    return result


def main():
    if sys.argv[1:]==['worker']:
        root=Path(__file__).resolve().parent;spec=json.loads((root/'spec.json').read_bytes())
        files={n:(root/n).read_bytes() for n in spec['members']};d=base(files);h=d.protected(spec,files);d.capture(h,spec,files);return
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='action',required=True)
    s=sub.add_parser('seal');s.add_argument('--source-dir',type=Path,required=True);s.add_argument('--source-sha256',required=True)
    s.add_argument('--operation-id',required=True);s.add_argument('--output',type=Path,required=True)
    e=sub.add_parser('execute');e.add_argument('--bundle',type=Path,required=True);e.add_argument('--sha256',required=True)
    e.add_argument('--mode',choices=('unifi','start','readback','cleanup'),required=True);e.add_argument('--attempt',type=int,choices=range(1,4),default=1)
    args=p.parse_args();print(json.dumps(base().seal(args) if args.action=='seal' else execute(args),sort_keys=True))


if __name__=='__main__':main()
