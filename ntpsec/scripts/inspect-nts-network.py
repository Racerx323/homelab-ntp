#!/usr/bin/python3
"""Bounded account-context TCP probes and credential-safe local UniFi GETs."""
import hashlib
import http.client
import ipaddress
import json
import os
from pathlib import Path
import re
import signal
import socket
import ssl
import subprocess
import sys
import time
import uuid


def encoded(value):return (json.dumps(value,sort_keys=True)+'\n').encode()


def validate_recipe(r):
    expected=json.loads('''{"schema":1,"controller":"udmbt.local.theama.co","controller_ipv4":"10.1.0.1","site_id":"88f7af54-98f8-306a-a1c7-c9349722b1f6","network_name":"Default LAN","external_zone":"External","upstreams":["time.cloudflare.com","ohio.time.system76.com","oregon.time.system76.com"],"port":4460,"ntp_uid":999,"ntp_gid":985,"connect_timeout_seconds":2,"maximum_connections":12,"controller_request_limit":40,"controller_total_bytes":16777216,"controller_deadline_seconds":300}''')
    if r!=expected:raise ValueError('reviewed closed transport recipe required')


def public_address(value):
    address=ipaddress.ip_address(value)
    if not address.is_global or address.is_multicast:raise ValueError('public upstream address required')
    return address


def resolve(r):
    result=[]
    for host in r['upstreams']:
        for family in (socket.AF_INET,socket.AF_INET6):
            row={'hostname':host,'family':4 if family==socket.AF_INET else 6}
            try:
                addresses=sorted({x[4][0] for x in socket.getaddrinfo(host,r['port'],family,socket.SOCK_STREAM)})
                if not addresses:raise ValueError('no address')
                for address in addresses:public_address(address)
                row.update(address=addresses[0],answer_count=len(addresses))
            except (OSError,ValueError):row['error']='resolution failed or nonpublic answer'
            result.append(row)
    return result


def probes(r,rows,context):
    if len(rows)!=6 or {(x['hostname'],x['family']) for x in rows}!={(h,f) for h in r['upstreams'] for f in (4,6)}:
        raise ValueError('one address slot per approved hostname/family required')
    if context=='ntp':
        os.setgroups([]);os.setgid(r['ntp_gid']);os.setuid(r['ntp_uid'])
    elif context!='root' or os.geteuid()!=0:raise ValueError('closed account context')
    result=[]
    for row in rows:
        if row['hostname'] not in r['upstreams'] or row['family'] not in (4,6):raise ValueError('unexpected endpoint')
        record=dict(row,uid=os.geteuid(),gid=os.getegid(),context=context,port=r['port'])
        if 'address' not in row:result.append(record);continue
        address=public_address(row['address'])
        if address.version!=row['family']:raise ValueError('address family mismatch')
        started=time.monotonic()
        with socket.socket(socket.AF_INET if row['family']==4 else socket.AF_INET6,socket.SOCK_STREAM) as connection:
            connection.settimeout(r['connect_timeout_seconds'])
            try:connection.connect((str(address),r['port']));record['connected']=True
            except OSError as error:record.update(connected=False,errno=error.errno,error=type(error).__name__)
            record.update(local_address=connection.getsockname()[0],elapsed_ms=round((time.monotonic()-started)*1000,3))
        result.append(record)
    return result


def redact(value,key):
    if isinstance(value,dict):return {(k.replace(key,'[REDACTED]') if key else k):('[REDACTED]' if re.search('password|secret|token|private.?key|pre.?shared|credential|api.?key',k,re.I) else redact(v,key)) for k,v in value.items()}
    if isinstance(value,list):return [redact(v,key) for v in value]
    if isinstance(value,str):return value.replace(key,'[REDACTED]') if key else value
    return value


class Controller:
    def __init__(self,r):
        self.r=r;self.key=None;self.count=0;self.total=0;self.records=[];self.last_path=None
        self.context=ssl.create_default_context()

    def get(self,path,authenticated=True):
        if not path.startswith('/proxy/network/integration/v1/') and not (path=='/' and not authenticated):raise ValueError('closed GET scope')
        self.count+=1;self.last_path=path
        if self.count>self.r['controller_request_limit']:raise ValueError('request limit')
        connection=http.client.HTTPSConnection(self.r['controller'],timeout=10,context=self.context)
        # Pin the verified address without changing SNI or hostname verification.
        raw=socket.create_connection((self.r['controller_ipv4'],443),timeout=10)
        try:
            connection.sock=self.context.wrap_socket(raw,server_hostname=self.r['controller'])
            headers={'Accept':'application/json'}
            if authenticated:
                if not self.key:raise ValueError('credential unavailable')
                headers['X-API-KEY']=self.key
            connection.request('GET',path,headers=headers)
            response=connection.getresponse();data=response.read(2*1024**2+1)
            self.total+=len(data)
            if len(data)>2*1024**2 or self.total>self.r['controller_total_bytes']:raise ValueError('response limit')
            if authenticated and response.status!=200:
                self.records.append({'path':path,'status':response.status,'error':'non-success; body omitted'})
                raise ValueError('controller GET status '+str(response.status))
            if not authenticated:
                if response.status not in (200,301,302,303,307,308):raise ValueError('controller TLS precheck failed')
                return None
            value=redact(json.loads(data),self.key)
            self.records.append({'path':path,'status':response.status,'epoch':int(time.time()),'body':value})
            return value
        finally:connection.close();raw.close()

    def pages(self,path):
        rows=[]
        for offset in range(0,400,100):
            value=self.get(path+'?limit=100&offset='+str(offset));items=value['data']
            if value['offset']!=offset or len(items)>100:raise ValueError('pagination shape')
            rows.extend(items)
            if offset+len(items)==value['totalCount']:return rows
            if not items or offset+len(items)>value['totalCount']:raise ValueError('pagination mismatch')
        raise ValueError('pagination bound')


def uuid_text(value):
    if str(uuid.UUID(value))!=value:raise ValueError('canonical object ID required')
    return value


def validate_ordering(ordering,policies):
    groups=ordering['orderedFirewallPolicyIds']
    if set(groups)!={'beforeSystemDefined','afterSystemDefined'}:raise ValueError('unknown ordering schema')
    if any(not isinstance(group,list) for group in groups.values()):raise ValueError('ordering lists required')
    actual=groups['beforeSystemDefined']+groups['afterSystemDefined']
    if any(x['metadata']['origin'] not in ('USER_DEFINED','SYSTEM_DEFINED') for x in policies):raise ValueError('unknown policy origin')
    expected={x['id'] for x in policies if x['metadata']['origin']=='USER_DEFINED'}
    if len(actual)!=len(set(actual)) or set(actual)!=expected:raise ValueError('policy ordering completeness mismatch')


def controller_collect(r):
    validate_recipe(r)
    def deadline(*unused):raise TimeoutError('controller deadline')
    previous=signal.signal(signal.SIGALRM,deadline);signal.alarm(r['controller_deadline_seconds'])
    client=Controller(r)
    try:
        resolved={a[4][0] for a in socket.getaddrinfo(r['controller'],443,socket.AF_INET,socket.SOCK_STREAM)}
        if resolved!={r['controller_ipv4']}:raise ValueError('controller DNS identity drift')
        client.get('/',False)
        secret=subprocess.run(['doppler','secrets','get','AUDIT_LOCAL','--project','homelab-dev','--config','prd_unifi','--plain','--no-check-version'],capture_output=True,timeout=30,check=False)
        if secret.returncode:raise ValueError('credential retrieval failed')
        client.key=secret.stdout.decode().strip()
        if not client.key or '\n' in client.key or '\r' in client.key:raise ValueError('invalid credential')
        base='/proxy/network/integration/v1/sites/'+uuid_text(r['site_id'])
        client.get('/proxy/network/integration/v1/info')
        sites=client.pages('/proxy/network/integration/v1/sites')
        if sum(x['id']==r['site_id'] for x in sites)!=1:raise ValueError('site identity missing or ambiguous')
        zones=client.pages(base+'/firewall/zones');networks=client.pages(base+'/networks')
        network=[x for x in networks if x['name']==r['network_name'] and x['enabled']]
        external=[x for x in zones if x['name']==r['external_zone']]
        if len(network)!=1 or len(external)!=1:raise ValueError('network or zone identity ambiguous')
        source=uuid_text(network[0]['zoneId']);dest=uuid_text(external[0]['id'])
        policies=client.pages(base+'/firewall/policies')
        selected=[x for x in policies if (x['source']['zoneId'],x['destination']['zoneId']) in ((source,dest),(dest,source))]
        referenced=set()
        def refs(value):
            if isinstance(value,dict):
                for k,v in value.items():
                    if k=='trafficMatchingListId':referenced.add(uuid_text(v))
                    else:refs(v)
            elif isinstance(value,list):
                for item in value:refs(item)
        refs(selected)
        if len(referenced)>16:raise ValueError('referenced list bound')
        for pair in ((source,dest),(dest,source)):
            ordering=client.get(base+'/firewall/policies/ordering?sourceFirewallZoneId='+pair[0]+'&destinationFirewallZoneId='+pair[1])
            validate_ordering(ordering,[x for x in selected if (x['source']['zoneId'],x['destination']['zoneId'])==pair])
        for identifier in sorted(referenced):client.get(base+'/traffic-matching-lists/'+identifier)
        # Second policy/order pass is deliberately omitted: this is a timestamped snapshot,
        # not proof of atomic controller state or an actual rule hit.
        return {'phase':'captured','controller':r['controller'],'site_id':r['site_id'],'records':client.records,
                'selected_policy_ids':[x['id'] for x in selected],'request_count':client.count,'rule_hit_proven':False}
    except BaseException as error:
        return {'phase':'held','controller':r['controller'],'site_id':r['site_id'],
                'error':type(error).__name__,'last_request_path':client.last_path,'records':client.records,'rule_hit_proven':False}
    finally:
        client.key=None;signal.alarm(0);signal.signal(signal.SIGALRM,previous)


def main():
    r=json.loads(Path(sys.argv[2]).read_bytes());validate_recipe(r)
    if sys.argv[1]=='resolve':result=resolve(r)
    elif sys.argv[1]=='probe':result=probes(r,json.loads(Path(sys.argv[4]).read_bytes()),sys.argv[3])
    else:raise ValueError('closed helper mode')
    print(json.dumps(result,sort_keys=True))


if __name__=='__main__':main()
