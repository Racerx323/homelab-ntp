#!/usr/bin/python3
"""One MON-VER poll and bounded runtime metadata; no receiver configuration."""
import json
import os
from pathlib import Path
import select
import stat
import time

QUERY = bytes.fromhex('b5620a0400000e34')
FILES = ('/usr/local/bin/ntpleapfetch', '/usr/share/zoneinfo/leap-seconds.list',
         '/etc/ntp.conf', '/etc/ntpsec-timeservice.json', '/etc/avahi/avahi-daemon.conf',
         '/etc/systemd/system/timeservice.service')
DIRECTORIES = ('/var/lib/ntp', '/var/lib/ntpsec', '/var/log/ntpstats')
UNITS = ('timeservice.service','gpsd.service','gpsd.socket','ntpsec.service',
         'systemd-timesyncd.service','avahi-daemon.service')


def version_response(raw):
    """Decode a checksum-valid UBX MON-VER response amid the existing NMEA stream."""
    offset = 0
    while True:
        start = raw.find(b'\xb5\x62\x0a\x04',offset)
        if start < 0 or len(raw)-start < 6: return None
        size = int.from_bytes(raw[start+4:start+6],'little')
        if size < 40 or size > 1024 or (size-40) % 30:
            raise ValueError('invalid MON-VER payload length')
        end = start+6+size
        if len(raw) < end+2: return None
        first = second = 0
        for byte in raw[start+2:end]:
            first = (first+byte) & 255; second = (second+first) & 255
        if raw[end:end+2] != bytes((first,second)):
            raise ValueError('MON-VER checksum mismatch')
        body = raw[start+6:end]
        def field(data):
            value = data.split(b'\0',1)[0].decode('ascii').strip()
            if any(ord(c) < 32 or ord(c) > 126 for c in value):
                raise ValueError('nonprintable MON-VER identity')
            return value
        sw,hw = field(body[:30]),field(body[30:40])
        if not sw or not hw: raise ValueError('MON-VER software/hardware identity missing')
        return {'software':sw,'hardware':hw,
                'extensions':[field(body[n:n+30]) for n in range(40,size,30)]}


def poll_version(a, h, root):
    identity = a.serial_identity()
    if identity != json.loads(h.read(root/'serial-before.json'))['identity']:
        raise ValueError('UART identity changed since saved pre-state')
    fd = os.open(identity['target'],os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK | os.O_NOFOLLOW)
    raw = bytearray()
    try:
        info = os.fstat(fd)
        if not stat.S_ISCHR(info.st_mode) or (info.st_rdev,info.st_ino) != (identity['rdev'],identity['ino']):
            raise ValueError('opened UART differs from accepted identity')
        # Record intent before the single write. Never retry a short/lost query.
        h.create(root/'receiver-query.json',a.encoded({'query_hex':QUERY.hex(),'writes':1}))
        if os.write(fd,QUERY) != len(QUERY): raise ValueError('short receiver query; no retry')
        deadline = time.monotonic()+10
        while time.monotonic() < deadline:
            if not select.select([fd],[],[],min(0.25,max(0,deadline-time.monotonic())))[0]: continue
            if len(raw) >= 65536: raise ValueError('receiver response bound exceeded')
            chunk = os.read(fd,min(4096,65536-len(raw)))
            if not chunk: raise ValueError('UART EOF during identity query')
            raw.extend(chunk)
            result = version_response(raw)
            if result is not None: return result
        raise ValueError('MON-VER response timeout; no retry or protocol change')
    finally:
        os.close(fd)
        h.create(root/'receiver-response.bin',bytes(raw))


def runtime_metadata(a, h):
    result = {'files':{},'directories':{},'units':{}}
    for name in (*FILES,*DIRECTORIES):
        path = Path(name); h.ancestors(path.parent)
        try: info = path.lstat()
        except FileNotFoundError:
            result['files' if name in FILES else 'directories'][name] = None; continue
        row = {'uid':info.st_uid,'gid':info.st_gid,'mode':stat.S_IMODE(info.st_mode)}
        if name in DIRECTORIES:
            if not stat.S_ISDIR(info.st_mode): raise ValueError('runtime directory type drift')
            result['directories'][name] = row
        else:
            if not stat.S_ISREG(info.st_mode): raise ValueError('runtime file type drift')
            raw = h.read(path,limit=1024**2)
            row.update(sha256=a.sha(raw),text=raw.decode())
            result['files'][name] = row
    for unit in UNITS:
        result['units'][unit] = a.run(['/usr/bin/systemctl','show',unit,
            '--property=Id,LoadState,ActiveState,SubState,UnitFileState'],timeout=10)
    result['ntp_account'] = a.run(['/usr/bin/getent','passwd','ntp'],timeout=10)
    result['udp123_listeners'] = a.run(['/usr/bin/ss','-H','-lun','sport = :123'],timeout=10)
    return result


def capture(a, h, spec, files):
    root = Path(spec['stage']); failure = None; started = time.monotonic()
    h.create(root/'capture-claim.json',a.encoded({'started_epoch':int(time.time())}))
    try:
        a.idle(); a.prior_guard(h,spec,files)
        h.create(root/'shm-before.txt',Path('/proc/sysvipc/shm').read_bytes())
        a.run(['/usr/bin/stty','-F','/dev/serial0','raw','115200','cs8','-parenb','clocal','-cstopb','-crtscts',
               '-echo','-echoe','-echok','-echonl','-ixon','-ixoff'])
        version = poll_version(a,h,root)
        report = {'receiver':version,'runtime':runtime_metadata(a,h),
                  'receiver_configuration_changed':False,'time_service_started':False}
        h.create(root/'receiver-runtime.json',a.encoded(report))
    except BaseException as error:
        failure = str(error)[:500]
    finally:
        gate = {'state':'not_applicable','reason':'identity query only; no long acquisition'}
        a.publish_gate(h,root,gate)
        h.create(root/'shm-after.txt',Path('/proc/sysvipc/shm').read_bytes())
        h.create(root/'terminal.json',a.encoded({'phase':'captured' if failure is None else 'held',
            'error':failure,'elapsed_seconds':time.monotonic()-started,'functional_gate':gate,
            'receiver_timing_accepted':False,'shm_mapping_accepted':False}))
    # The same sealed ExecStopPost restores UART settings, including on worker failure.
