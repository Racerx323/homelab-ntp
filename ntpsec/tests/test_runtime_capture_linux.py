#!/usr/bin/python3
"""Opt-in real libpcap fixture; requires an isolated rootless network namespace.

Run via `podman unshare unshare --net`, never on a target. Supply libpcap through
LD_LIBRARY_PATH if it is not installed. No packages or host routes are changed.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import socket
import struct
import subprocess
import sys
import time

COLLECTOR=Path(__file__).resolve().parents[1]/'scripts/runtime-diagnostic.py'
ADDRESSES={4:['198.18.0.2','198.18.0.3','198.18.0.4'],
           6:['2001:db8::2','2001:db8::3','2001:db8::4']}


def run(*args):
    return subprocess.check_output(args,text=True,timeout=10)


def frame(source_mac,dest_mac,remote,sequence,response):
    local='2001:db8::1' if ':' in remote else '198.18.0.1'
    source,dest=(remote,local) if response else (local,remote)
    ntp=bytearray(48);ntp[0]=(4<<3)|(4 if response else 3);ntp[1]=2 if response else 0
    ntp[24 if response else 40:32 if response else 48]=sequence.to_bytes(8,'big')
    udp=struct.pack('!HHHH',123,123,56,0)+ntp
    if ':' in remote:
        source_bytes=socket.inet_pton(socket.AF_INET6,source);dest_bytes=socket.inet_pton(socket.AF_INET6,dest)
        pseudo=source_bytes+dest_bytes+struct.pack('!I3xB',len(udp),17)
        checksum=sum(struct.unpack('!'+str((len(pseudo)+len(udp))//2)+'H',pseudo+udp))
        while checksum>>16:checksum=(checksum&65535)+(checksum>>16)
        udp=udp[:6]+struct.pack('!H',((~checksum)&65535) or 65535)+udp[8:]
        ip=struct.pack('!IHBB16s16s',6<<28,len(udp),17,64,source_bytes,dest_bytes)
        return dest_mac+source_mac+b'\x86\xdd'+ip+udp
    ip=bytearray(struct.pack('!BBHHHBBH4s4s',0x45,0,76,sequence,0,64,17,0,
                            socket.inet_aton(source),socket.inet_aton(dest)))
    checksum=sum(struct.unpack('!10H',ip))
    while checksum>>16:checksum=(checksum&65535)+(checksum>>16)
    ip[10:12]=struct.pack('!H',(~checksum)&65535)
    return dest_mac+source_mac+b'\x08\x00'+ip+udp


def worker(stage):
    spec=importlib.util.spec_from_file_location('capture',COLLECTOR)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    module.capture(stage,json.loads((stage/'recipe.json').read_text()))


def case(root,buffer_bytes,pattern,repeat,macs,family):
    stage=root/f'{pattern}-{buffer_bytes}-{repeat}';stage.mkdir(mode=0o700)
    recipe={'upstream_addresses':ADDRESSES[family],'interface':'eth0','capture_seconds':30,
            'maximum_packets':512,'buffer_bytes':buffer_bytes}
    (stage/'recipe.json').write_text(json.dumps(recipe))
    process=None
    try:
        with (stage/'worker.log').open('wb') as log:
            process=subprocess.Popen([sys.executable,'-I','-B',str(Path(__file__).resolve()),
                                      '--worker',str(stage)],stdout=log,stderr=subprocess.STDOUT)
            deadline=time.monotonic()+5
            while not (stage/'packet-ready.json').exists():
                if process.poll() is not None or time.monotonic()>=deadline:
                    raise ValueError('capture readiness failed; inspect retained worker.log')
                time.sleep(.01)
            count=60 if pattern=='spaced' else 180
            with socket.socket(socket.AF_PACKET,socket.SOCK_RAW) as request, socket.socket(socket.AF_PACKET,socket.SOCK_RAW) as response:
                request.bind(('eth0',0));response.bind(('peer0',0))
                for i in range(count):
                    sequence=i+1;remote=ADDRESSES[family][i%3]
                    request.send(frame(macs[0],macs[1],remote,sequence,False))
                    time.sleep((.005,.033,.05)[i%3] if pattern=='spaced' else .001)
                    response.send(frame(macs[1],macs[0],remote,sequence,True))
                    if pattern=='spaced':time.sleep(.075)
            # Allow the last buffered block to retire before stopping.
            time.sleep(.4);process.send_signal(signal.SIGTERM)
            if process.wait(timeout=10)!=0:raise ValueError('capture worker failed')
        report=json.loads((stage/'packet-report.json').read_text())
        requests=[p['transmit'] for p in report['packets'] if p['direction']=='request']
        responses=[p['origin'] for p in report['packets'] if p['direction']=='response']
        expected={n.to_bytes(8,'big').hex() for n in range(1,count+1)}
        exact=(len(requests)==count and len(responses)==count
               and set(requests)==set(responses)==expected)
        result={'pattern':pattern,'buffer_bytes':buffer_bytes,'repeat':repeat,
                'sent_pairs':count,'captured_requests':len(requests),'captured_responses':len(responses),
                'exact_packet_ids':exact,'complete':report['complete'],'stats':report['stats'],
                'backend':report['backend']}
        print(json.dumps(result),flush=True)
        return result
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--family',type=int,choices=(4,6),default=6)
    parser.add_argument('--output',type=Path);parser.add_argument('--worker',type=Path)
    args=parser.parse_args()
    os.umask(0o077)
    if args.worker:worker(args.worker);return
    if not args.output:parser.error('--output is required')
    if os.geteuid()!=0:raise ValueError('isolated namespace root required')
    links=json.loads(run('ip','-j','link','show'))
    if [link['ifname'] for link in links]!=['lo']:
        raise ValueError('refuse existing interfaces; use a fresh isolated network namespace')
    root=args.output.resolve();root.mkdir(mode=0o700)
    digest=hashlib.sha256(COLLECTOR.read_bytes()).hexdigest()
    run('ip','link','set','lo','up')
    run('ip','link','add','eth0','type','veth','peer','name','peer0')
    try:
        for name in ('eth0','peer0'):run('ip','link','set',name,'up')
        macs=[bytes.fromhex(json.loads(run('ip','-j','link','show',name))[0]['address'].replace(':',''))
              for name in ('eth0','peer0')]
        results=[case(root,size,pattern,repeat,macs,args.family) for repeat in range(3)
                 for pattern in ('spaced','burst') for size in (262144,2097152)]
        assert hashlib.sha256(COLLECTOR.read_bytes()).hexdigest()==digest
        summary={'family':args.family,'fixture_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'collector_sha256':digest,'kernel':os.uname().release,'machine':os.uname().machine,
                 'network_scope':'isolated veth pair; no external routes','results':results}
        (root/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
        if not all(r['complete'] and r['exact_packet_ids'] for r in results if r['buffer_bytes']==2097152):
            raise ValueError('larger-buffer candidate failed complete capture')
    finally:run('ip','link','delete','eth0')


if __name__=='__main__':main()
