#!/usr/bin/python3
"""Opt-in real pinned ntpd Mode 6 test in isolated user/network/IPC namespaces.

Run via podman unshare unshare --net --ipc; supply a private NTPsec 1.2.5
build tree and fresh private output. No clock adjustment or outside network.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--build', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if os.geteuid() != 0 or [name for _, name in socket.if_nameindex()] != ['lo']:
        raise ValueError('isolated rootless network namespace required')
    if Path('/proc/sysvipc/shm').read_text().splitlines()[1:]:
        raise ValueError('empty isolated IPC namespace required')
    # User namespace must exclude host capabilities, especially clock adjustment.
    if Path('/proc/self/uid_map').read_text().split()[1] == '0':
        raise ValueError('rootless user namespace required')
    subprocess.run(['ip', 'link', 'set', 'lo', 'up'], check=True)
    sys.path.insert(0, str(args.build/'build/main/tests/pylib'))
    import ntp.packet
    helper = Path(__file__).resolve().parents[1]/'scripts/pps-startup.py'
    spec = importlib.util.spec_from_file_location('startup', helper)
    startup = importlib.util.module_from_spec(spec); spec.loader.exec_module(startup)
    binary = args.build/'build/main/ntpd/ntpd'
    version = subprocess.check_output([str(binary), '--version'], text=True).strip()
    if 'ntpsec-1.2.5' not in version:
        raise ValueError('pinned 1.2.5 required')
    os.umask(0o077); args.output.mkdir(mode=0o700)
    key = args.output/'key'; key.write_text('42 AES '+secrets.token_hex(16)+'\n')
    config = args.output/'ntp.conf'
    config.write_text('disable ntp kernel\ninterface ignore all\ninterface listen lo\n'
        'restrict default ignore\nrestrict 127.0.0.1\nrestrict ::1\n'
        'keys '+str(key)+'\ntrustedkey 42\ncontrolkey 42\nlogconfig +sysevents\n'
        +startup.PPS+'\n')
    result = {'version': version, 'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
              'helper_sha256': hashlib.sha256(helper.read_bytes()).hexdigest(), 'commands': []}
    with (args.output/'daemon.log').open('w') as log:
        daemon = subprocess.Popen([str(binary), '-n', '-c', str(config)], stdout=log, stderr=subprocess.STDOUT)
        session = None
        try:
            time.sleep(2)
            if daemon.poll() is not None:
                raise ValueError('fixture daemon exited')
            session = startup.authenticated_session(key)
            before = startup.measure(session)
            if len(before['peers']) != 1:
                raise ValueError('one bootstrap PPS peer required')
            result['before'] = before; result['pid'] = daemon.pid
            for command in startup.COMMANDS:
                if not session.config(command):
                    raise ValueError('pinned runtime command rejected: '+command)
                result['commands'].append(command)
            after = startup.measure(session); result['after'] = after
            if (len(after['peers']) != 5 or daemon.poll() is not None
                    or before['peers'][0]['associd'] not in [p['associd'] for p in after['peers']]):
                raise ValueError('promotion membership/PID continuity')
            badkey = args.output/'bad-key'; badkey.write_text('42 AES '+secrets.token_hex(16)+'\n')
            bad = startup.authenticated_session(badkey)
            try:
                bad.config('refclock shm unit 3 refid BAD')
            except ntp.packet.ControlException:
                result['wrong_key_rejected'] = True
            else:
                raise ValueError('wrong control key accepted')
            finally:
                bad.sock.close(); badkey.unlink()
            if len(startup.measure(session)['peers']) != 5:
                raise ValueError('rejected command changed associations')
            original = session.sock
            class CorruptedReply:
                def __getattr__(self, name): return getattr(original, name)
                def recv(self, size):
                    raw = original.recv(size)
                    return raw[:-1]+bytes([raw[-1] ^ 1])
            session.sock = CorruptedReply()
            try:
                session.readvar(0, ['leap'])
            except ValueError as error:
                if str(error) != 'unauthenticated control response': raise
                result['corrupted_mac_rejected'] = True
            else:
                raise ValueError('corrupted response MAC accepted')
            finally:
                session.sock = original
            result['passed'] = True
        finally:
            if session: session.sock.close()
            if daemon.poll() is None:
                daemon.terminate()
            try: daemon.wait(timeout=5)
            except subprocess.TimeoutExpired: daemon.kill(); daemon.wait()
            key.unlink()
            result['daemon_reaped'] = True
            (args.output/'result.json').write_text(json.dumps(result, indent=2)+'\n')


if __name__ == '__main__':
    main()
