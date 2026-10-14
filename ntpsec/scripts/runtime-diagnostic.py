#!/usr/bin/python3
"""Bounded libpcap header observations; never persist NTS cookies or payloads."""
import ctypes as C
import ipaddress
import json
import os
from pathlib import Path
import signal
import socket
import stat
import struct
import sys
import time


class Header(C.Structure):
    _fields_=[('seconds',C.c_long),('microseconds',C.c_long),('caplen',C.c_uint32),('length',C.c_uint32)]


class Program(C.Structure):
    _fields_=[('length',C.c_uint),('instructions',C.c_void_p)]


class Stats(C.Structure):
    _fields_=[('received',C.c_uint),('dropped',C.c_uint),('interface_dropped',C.c_uint)]


def library():
    lib=C.CDLL('libpcap.so.0.8')
    definitions={
        'pcap_lib_version':([],C.c_char_p),
        'pcap_fileno':([C.c_void_p],C.c_int),
        'pcap_create':([C.c_char_p,C.c_char_p],C.c_void_p),
        'pcap_set_snaplen':([C.c_void_p,C.c_int],C.c_int),
        'pcap_set_promisc':([C.c_void_p,C.c_int],C.c_int),
        'pcap_set_timeout':([C.c_void_p,C.c_int],C.c_int),
        'pcap_set_buffer_size':([C.c_void_p,C.c_int],C.c_int),
        'pcap_activate':([C.c_void_p],C.c_int),
        'pcap_setnonblock':([C.c_void_p,C.c_int,C.c_char_p],C.c_int),
        'pcap_datalink':([C.c_void_p],C.c_int),
        'pcap_compile':([C.c_void_p,C.POINTER(Program),C.c_char_p,C.c_int,C.c_uint32],C.c_int),
        'pcap_setfilter':([C.c_void_p,C.POINTER(Program)],C.c_int),
        'pcap_freecode':([C.POINTER(Program)],None),
        'pcap_next_ex':([C.c_void_p,C.POINTER(C.POINTER(Header)),C.POINTER(C.POINTER(C.c_ubyte))],C.c_int),
        'pcap_stats':([C.c_void_p,C.POINTER(Stats)],C.c_int),
        'pcap_close':([C.c_void_p],None)}
    for name,(args,result) in definitions.items():
        fn=getattr(lib,name);fn.argtypes=args;fn.restype=result
    return lib


def packet(raw,wire_length,addresses):
    """Decode only plain Ethernet IPv4/IPv6 UDP. Unsupported headers are counted."""
    if len(raw)<14:return None
    kind=struct.unpack('!H',raw[12:14])[0]
    if kind==0x86dd:
        if len(raw)<62 or raw[14]>>4!=6 or raw[20]!=17:return None
        start=54;length=struct.unpack('!H',raw[18:20])[0]
        source=socket.inet_ntop(socket.AF_INET6,raw[22:38]);dest=socket.inet_ntop(socket.AF_INET6,raw[38:54])
    elif kind==0x0800:
        if len(raw)<34 or raw[14]>>4!=4 or raw[23]!=17:return None
        size=(raw[14]&15)*4
        if size<20 or len(raw)<14+size+8 or struct.unpack('!H',raw[20:22])[0]&0x3fff:return None
        start=14+size;length=struct.unpack('!H',raw[16:18])[0]-size
        source=socket.inet_ntop(socket.AF_INET,raw[26:30]);dest=socket.inet_ntop(socket.AF_INET,raw[30:34])
    else:return None
    sport,dport,udp_length=struct.unpack('!HHH',raw[start:start+6])
    if 123 not in (sport,dport) or not ({source,dest}&set(addresses)):return None
    if udp_length<56 or udp_length>length or len(raw)<start+56:return None
    ntp=raw[start+8:start+56]
    return {'source':source,'destination':dest,'source_port':sport,'destination_port':dport,
            'direction':'response' if source in addresses else 'request',
            'wire_bytes':wire_length,'udp_bytes':udp_length,
            'leap':ntp[0]>>6,'version':(ntp[0]>>3)&7,'mode':ntp[0]&7,'stratum':ntp[1],
            'origin':ntp[24:32].hex(),'receive':ntp[32:40].hex(),'transmit':ntp[40:48].hex()}


def protected_write(root,name,value):
    raw=(json.dumps(value,sort_keys=True)+'\n').encode()
    if len(raw)>512*1024:raise ValueError('capture evidence size bound')
    path=root/(name+'.new')
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb') as stream:
        stream.write(raw);stream.flush();os.fsync(stream.fileno())
    os.replace(path,root/name)


def capture(root,recipe):
    """One non-promiscuous capture; independent systemd lifetime bounds this worker."""
    os.umask(0o077)
    info=root.lstat()
    if os.geteuid()!=0 or not stat.S_ISDIR(info.st_mode) or (info.st_uid,info.st_gid,stat.S_IMODE(info.st_mode))!=(0,0,0o700):
        raise ValueError('protected root-owned capture stage required')
    addresses=recipe['upstream_addresses']
    for address in addresses:ipaddress.ip_address(address)
    expression='udp port 123 and ('+' or '.join('host '+a for a in addresses)+')'
    lib=library();error=C.create_string_buffer(256);handle=lib.pcap_create(recipe['interface'].encode(),error)
    if not handle:raise ValueError('pcap_create failed')
    report={'phase':'capturing','filter':expression,'interface':recipe['interface'],'packets':[],
            'unsupported':0,'capacity_reached':False,'complete':False,'started_monotonic':time.monotonic()}
    stopped=False
    def stop(signum,frame):
        nonlocal stopped
        stopped=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    try:
        for name,value in [('snaplen',128),('promisc',0),('timeout',100),('buffer_size',recipe['buffer_bytes'])]:
            if getattr(lib,'pcap_set_'+name)(handle,value)!=0:raise ValueError('pcap setup failed: '+name)
        if lib.pcap_activate(handle)!=0 or lib.pcap_datalink(handle)!=1:raise ValueError('plain Ethernet capture required')
        if lib.pcap_setnonblock(handle,1,error)!=0:raise ValueError('nonblocking capture required')
        # Linux PACKET_VERSION is read-only and identifies the actual backend.
        with socket.fromfd(lib.pcap_fileno(handle),socket.AF_PACKET,socket.SOCK_RAW) as fd:
            version=fd.getsockopt(263,10)  # SOL_PACKET, PACKET_VERSION (linux/if_packet.h)
        report['backend']={'libpcap':lib.pcap_lib_version().decode('ascii'),
                           'packet_version':version,'requested_buffer_bytes':recipe['buffer_bytes']}
        program=Program()
        if lib.pcap_compile(handle,C.byref(program),expression.encode(),1,0xffffffff)!=0:raise ValueError('BPF compilation failed')
        try:
            if lib.pcap_setfilter(handle,C.byref(program))!=0:raise ValueError('BPF installation failed')
        finally:lib.pcap_freecode(C.byref(program))
        protected_write(root,'packet-ready.json',{'ready':True,'filter':expression,'pid':os.getpid(),'backend':report['backend']})
        deadline=time.monotonic()+recipe['capture_seconds']
        header=C.POINTER(Header)();data=C.POINTER(C.c_ubyte)()
        while not stopped and time.monotonic()<deadline:
            status=lib.pcap_next_ex(handle,C.byref(header),C.byref(data))
            if status==0:time.sleep(.05);continue
            if status!=1:raise ValueError('packet capture read failed')
            if header.contents.caplen>128:raise ValueError('snap length exceeded')
            row=packet(C.string_at(data,header.contents.caplen),header.contents.length,addresses)
            if row is None:report['unsupported']+=1
            else:
                row['monotonic']=time.monotonic()
                row['pcap_timestamp']={'seconds':header.contents.seconds,'microseconds':header.contents.microseconds}
                report['packets'].append(row)
            if len(report['packets'])+report['unsupported']>=recipe['maximum_packets']:
                report['capacity_reached']=True;break
        stats=Stats()
        if lib.pcap_stats(handle,C.byref(stats))!=0:raise ValueError('capture drop counters unavailable')
        report['stats']={name:getattr(stats,name) for name,_ in Stats._fields_}
        report['complete']=not report['capacity_reached'] and not report['unsupported'] and not stats.dropped and not stats.interface_dropped
        report['phase']='stopped' if stopped else 'expired'
    except BaseException as exc:
        report.update(phase='held',error=str(exc)[:300]);raise
    finally:
        lib.pcap_close(handle);report['ended_monotonic']=time.monotonic()
        protected_write(root,'packet-report.json',report)


if __name__=='__main__':
    if len(sys.argv)!=2 or sys.argv[1]!='capture':raise SystemExit('sealed capture worker only')
    root=Path(__file__).resolve().parent
    capture(root,json.loads((root/'spec.json').read_bytes())['recipe']['diagnostic'])
