#!/usr/bin/python3
"""Correlate GPSD reports with independent SHM samples; gate startup."""
from decimal import Decimal
import json
from pathlib import Path
import re
import socket
import subprocess
import tempfile
import time


def pairing_evidence(gps_json, shm_text, minimum_samples=60):
    """Correlate explicit-device reports with independently sampled SHM timestamps."""
    rows = [json.loads(line) for line in gps_json.splitlines() if line.strip()]
    watches = [r for r in rows if r.get('class') == 'WATCH']
    if not watches or any(r.get('pps') is not True for r in watches):
        return {'observed':False,'reason':'PPS watch acknowledgement missing'}
    samples = set()
    for line in shm_text.splitlines():
        fields = line.split()
        if not fields or fields[0] != 'sample': continue
        if len(fields) != 7: raise ValueError('malformed SHM sample')
        if fields[5] == '0':
            samples.add((fields[1],int(Decimal(fields[3])*1000000000),int(Decimal(fields[4])*1000000000)))
    units = {}; matched = {}; summary = {}
    for kind,path in (('TOFF','/dev/serial0'),('PPS','/dev/pps0')):
        reports = [r for r in rows if r.get('class') == kind]
        if not reports or any(r.get('device') != path for r in reports):
            return {'observed':False,'reason':'missing or ambiguous '+kind+' device'}
        names = {r.get('shm') for r in reports}
        if len(names) != 1 or not re.fullmatch(r'NTP[0-9]+',next(iter(names)) or ''):
            return {'observed':False,'reason':'ambiguous '+kind+' SHM unit'}
        unit = next(iter(names)); units[kind] = unit; pairs = set()
        for r in reports:
            fields = ('clock_sec','clock_nsec','real_sec','real_nsec')
            if any(type(r.get(k)) is not int for k in fields): raise ValueError('integer JSON timestamps required')
            if not all(0 <= r[k] < 1000000000 for k in ('clock_nsec','real_nsec')): raise ValueError('nanosecond range')
            pair = (unit,r['clock_sec']*1000000000+r['clock_nsec'],r['real_sec']*1000000000+r['real_nsec'])
            if pair in samples: pairs.add(pair)
        matched[kind] = len(pairs)
        summary[kind] = {'device':path,'unit':unit,'matching_samples':len(pairs)}
    observed = len(set(units.values())) == 2 and all(n >= minimum_samples for n in matched.values())
    return {'observed':observed,'sources':summary,'reason':None if observed else 'insufficient or overlapping matched sources',
            'timing_accuracy_accepted':False}


def startup(gpsd, stopping, expected, directory):
    """One short startup check; stop both monitors before ntpd can consume SHM."""
    deadline=time.monotonic()+15
    while True:
        if stopping() or gpsd.poll() is not None: raise ValueError('GPSD stopped during readiness')
        try:
            with socket.create_connection(('127.0.0.1',2947),timeout=1): break
        except OSError:
            if time.monotonic()>=deadline: raise ValueError('GPSD readiness timeout')
            time.sleep(.25)
    with tempfile.TemporaryDirectory(prefix='gate-',dir=directory) as temporary:
        root=Path(temporary); children=[];streams=[]
        try:
            for name,argv in (
                ('json',['/usr/local/bin/gpspipe','-B','-w','-P','-x','30','127.0.0.1:2947']),
                ('shm',['/usr/local/bin/ntpshmmon','-t','30'])):
                stream=(root/name).open('xb');streams.append(stream)
                children.append(subprocess.Popen(argv,stdout=stream,stderr=subprocess.DEVNULL,
                    env={'PATH':'/usr/local/bin:/usr/bin:/bin','LC_ALL':'C'}))
            deadline=time.monotonic()+30
            while time.monotonic()<deadline:
                if stopping() or gpsd.poll() is not None or any(p.poll() is not None for p in children):
                    raise ValueError('startup child stopped')
                raw=[]
                for name in ('json','shm'):
                    with (root/name).open('rb') as source:data=source.read(131073)
                    if len(data)>131072:raise ValueError('startup sample bound exceeded')
                    raw.append(data[:data.rfind(b'\n')+1].decode())
                result=pairing_evidence(*raw,minimum_samples=5)
                if result['observed']:
                    if {k:v['unit'] for k,v in result['sources'].items()}!=expected:
                        raise ValueError('observed SHM assignments differ from configuration')
                    return result
                time.sleep(.25)
            raise ValueError('30-second serial/PPS functionality timeout')
        finally:
            for p in children:
                if p.poll() is None:p.terminate()
            for p in children:
                try:p.wait(timeout=2)
                except subprocess.TimeoutExpired:p.kill();p.wait(timeout=2)
            for stream in streams:stream.close()
