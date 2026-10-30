#!/usr/bin/python3
"""Bounded workstation NTP and link-local discovery checks for a sealed cutover."""
import ipaddress
import json
import secrets
import socket
import struct
import time


def ntp_response(raw, nonce, structural=False):
    if structural:
        if (len(raw)!=48 or raw[0]&7!=4 or (raw[0]>>3)&7 not in (3,4)
                or not 1<=raw[1]<=16 or raw[24:32]!=nonce or not any(raw[40:48])):
            raise ValueError('matching NTP protocol response required')
        return {'stratum':raw[1],'leap':raw[0]>>6,'refid_hex':raw[12:16].hex(),
                'time_service_accepted':False}
    if len(raw)!=48 or raw[0]&7!=4 or (raw[0]>>3)&7 not in (3,4) or raw[0]>>6!=0 or raw[1]!=1:
        raise ValueError('synchronized stratum-1 NTP response required')
    if raw[24:32]!=nonce or raw[12:16].rstrip(b'\0')!=b'PPS' or not any(raw[32:40]) or not any(raw[40:48]):
        raise ValueError('NTP nonce/PPS/timestamps mismatch')
    # Reject stale or implausible transmit time, without claiming calibrated UTC accuracy.
    seconds,fraction=struct.unpack('!II',raw[40:48])
    if abs(seconds-2208988800+fraction/2**32-time.time())>10:
        raise ValueError('client/server time discrepancy exceeds trial bound')
    return {'stratum':raw[1],'leap':raw[0]>>6,'refid':'PPS'}


def client_ntp(endpoint, structural=False, administrative=True):
    family=socket.AF_INET6 if ':' in endpoint else socket.AF_INET
    with socket.socket(family,socket.SOCK_DGRAM) as sock:
        sock.settimeout(3);sock.connect((endpoint,123))
        nonce=secrets.token_bytes(8);packet=bytearray(48);packet[0]=0x23;packet[40:48]=nonce
        sock.send(packet);result=ntp_response(sock.recv(512),nonce,structural)
        result['local_address']=sock.getsockname()[0]
        if not administrative:
            return result
        # A mode-6 READVAR response, including permission errors, violates localhost-only queries.
        sock.send(struct.pack('!BBHHHHH',0x26,2,1,0,0,0,0))
        try:sock.recv(512)
        except socket.timeout:result['queries_denied']=True
        else:raise ValueError('external administrative query received a response')
        return result


def dns_name(data, offset):
    labels=[];seen=set();end=None
    for _ in range(128):
        if offset>=len(data) or offset in seen:raise ValueError('invalid DNS name')
        seen.add(offset);length=data[offset];offset+=1
        if length&0xc0==0xc0:
            if offset>=len(data):raise ValueError('short DNS pointer')
            if end is None:end=offset+1
            offset=((length&63)<<8)|data[offset];continue
        if length&0xc0 or offset+length>len(data):raise ValueError('invalid DNS label')
        if not length:return '.'.join(labels).lower(),end if end is not None else offset
        labels.append(data[offset:offset+length].decode('utf-8'));offset+=length
    raise ValueError('DNS name bound')


def dns_records(data):
    if len(data)<12 or len(data)>9000:raise ValueError('bounded DNS packet required')
    _,flags,qd,an,ns,ar=struct.unpack('!6H',data[:12])
    if not flags&0x8000 or flags&15 or qd+an+ns+ar>128:raise ValueError('DNS response required')
    offset=12;records=[]
    for _ in range(qd):
        _,offset=dns_name(data,offset);offset+=4
    for _ in range(an+ns+ar):
        name,offset=dns_name(data,offset)
        if offset+10>len(data):raise ValueError('short DNS RR')
        kind,cls,ttl,size=struct.unpack('!HHIH',data[offset:offset+10]);offset+=10;end=offset+size
        if end>len(data):raise ValueError('short DNS data')
        value=None
        if kind==12:value,_=dns_name(data,offset)
        elif kind==33:
            if size<7:raise ValueError('short SRV')
            port=struct.unpack('!H',data[offset+4:offset+6])[0];target,_=dns_name(data,offset+6);value=(port,target)
        elif kind in (1,28):value=str(ipaddress.ip_address(data[offset:end]))
        if cls&0x7fff==1 and ttl and value is not None:records.append((name,kind,value))
        offset=end
    return records


def discovery_matches(records,endpoints,hostname):
    instances={v for n,k,v in records if n=='_ntp._udp.local' and k==12}
    targets={v[1] for n,k,v in records if n in instances and k==33 and v[0]==123}
    # Bind advertisement to the accepted host identity and both fixed addresses.
    target=hostname.lower()+'.local'
    addresses={v for n,k,v in records if n==target and k in (1,28)}
    return target in targets and set(endpoints)<=addresses


def query(name,kind):
    labels=name.encode().split(b'.')
    return struct.pack('!6H',0,0,1,0,0,0)+b''.join(bytes([len(p)])+p for p in labels)+b'\0'+struct.pack('!HH',kind,0x8001)


def browse(endpoints,hostname):
    records=[];packets=0
    with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sock:
        sock.settimeout(1);sock.setsockopt(socket.IPPROTO_IP,socket.IP_MULTICAST_TTL,255)
        # Ephemeral source requests legacy-unicast mDNS replies, without altering workstation services.
        sock.bind(('',0))
        for name,kind in (('_ntp._udp.local',12),(hostname+'.local',1),(hostname+'.local',28)):
            sock.sendto(query(name,kind),('224.0.0.251',5353))
            until=time.monotonic()+3
            while time.monotonic()<until and packets<64:
                try:raw,source=sock.recvfrom(9001)
                except socket.timeout:continue
                packets+=1
                if source[0]!=endpoints[0] or source[1]!=5353:continue
                records.extend(dns_records(raw))
        if not discovery_matches(records,endpoints,hostname):raise ValueError('workstation mDNS target/SRV/dual-address acceptance missing')
    return {'packets':packets,'matched':True}


def check(spec,spec_sha256,structural=False):
    v4,v6=[client_ntp(e,structural) for e in spec['endpoints']]
    if structural:
        return {'target':spec['hostname'],'spec_sha256':spec_sha256,'epoch':int(time.time()),
                'checks':{'ipv4':True,'ipv6':True,'queries_denied':True},
                'observations':{'ipv4':v4,'ipv6':v6},'time_service_accepted':False}
    mdns=browse(spec['endpoints'],spec['hostname'])
    return {'target':spec['hostname'],'spec_sha256':spec_sha256,'epoch':int(time.time()),
            'checks':{'ipv4':True,'ipv6':True,'queries_denied':True,'mdns':True},
            'observations':{'ipv4':v4,'ipv6':v6,'mdns':mdns},'absolute_accuracy_accepted':False}


if __name__=='__main__':raise SystemExit('Use the sealed cutover controller')
