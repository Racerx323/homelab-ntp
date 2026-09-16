#!/bin/bash
# One numeric-loopback NTP mode-3 request; never sets the clock or writes files.
set -Eeuo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
export LC_ALL=C
umask 077
exec /usr/bin/python3 -I - "$@" <<'PYTHON'
import datetime
import json
import os
from pathlib import Path
import socket
import struct
import sys
import time


def request_packet(wall_time):
    seconds = wall_time + 2208988800
    stamp = struct.pack("!II", int(seconds) & 0xffffffff,
                        int((seconds % 1) * (1 << 32)))
    return bytes([0x23]) + bytes(39) + stamp


def validate_response(packet, request):
    if len(packet) < 48 or len(packet) > 512:
        raise ValueError("invalid packet length")
    if packet[0] & 7 != 4 or (packet[0] >> 3) & 7 not in (3, 4):
        raise ValueError("not an NTP server response")
    if packet[24:32] != request[40:48]:
        raise ValueError("originate timestamp does not match this request")
    if packet[0] >> 6 == 3 or not 1 <= packet[1] <= 15:
        raise ValueError("unsynchronized response or kiss-of-death")
    if packet[32:40] == bytes(8) or packet[40:48] == bytes(8):
        raise ValueError("missing receive/transmit timestamp")
    return {"stratum": packet[1], "leap": packet[0] >> 6,
            "version": (packet[0] >> 3) & 7}


def probe(socket_factory=socket.socket, wall_clock=time.time):
    result = {"schema": "ntp-ipv6-time-v1", "target": "j1-svntp1",
              "endpoint": "[::1]:123", "request_count": 0,
              "scope": "IPv6 loopback time response only", "baseline_accepted": False}
    request = request_packet(wall_clock())
    try:
        with socket_factory(socket.AF_INET6, socket.SOCK_DGRAM, socket.IPPROTO_UDP) as sock:
            sock.settimeout(5)
            sock.connect(("::1", 123, 0, 0))
            sock.send(request)
            result["request_count"] = 1
            response = sock.recv(513)
        result["request_hex"] = request.hex()
        result["response_hex"] = response.hex()
        result.update(validate_response(response, request))
        result.update(status="response_verified", exit_status=0)
    except ValueError as exc:
        result.update(status="invalid_response", exit_status=3, error=str(exc))
    except (OSError, TimeoutError) as exc:
        result.update(status="unresolved", exit_status=2, error=str(exc))
    result["finished"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    return result


def main():
    if sys.argv[1:] != ["--probe"]:
        print("usage: inspect-ipv6-time.sh --probe", file=sys.stderr)
        return 64
    try:
        if os.uname().nodename != "j1-svntp1":
            raise ValueError("wrong kernel hostname")
        release = {}
        for line in Path("/etc/os-release").read_text().splitlines():
            key, sep, value = line.partition("=")
            if sep:
                if key in release:
                    raise ValueError("duplicate release key")
                release[key] = value.strip().strip('"')
        if release.get("ID") != "debian" or release.get("VERSION_ID") != "11":
            raise ValueError("expected observed Debian 11 host")
    except (OSError, ValueError) as exc:
        print("preflight rejected: " + str(exc), file=sys.stderr)
        return 64
    result = probe()
    print(json.dumps(result, sort_keys=True))
    return result["exit_status"]


if __name__ == "__main__":
    sys.exit(main())
PYTHON
