#!/bin/bash
# Single-file, hash-bound collector. Python is embedded to preserve arbitrary bytes
# and structured errors without shell-evaluating any host configuration.
set -Eeuo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
export LC_ALL=C
export SYSTEMD_PAGER=cat
export SYSTEMD_COLORS=0
umask 077
exec /usr/bin/python3 -I - "$@" <<'PYTHON'
import argparse
import datetime
import glob
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import shlex
import stat
import subprocess
import sys

SCHEMA = "ntp-baseline-v3"
TARGET = "j1-svntp1"
LIMIT = 16 * 1024 * 1024
UNIT_PATTERN = re.compile(
    r"(?:ntp|gps|pps|chrony|timesync|timeservice|webmin|munin|watchdog|wd_keepalive|"
    r"needrestart|msmtp|NetworkManager|networking|systemd-networkd|"
    r"systemd-resolved|dhcpcd|resolvconf|rc-local|cron|supervisor)", re.I)
COMMON = "Id,LoadState,ActiveState,SubState,UnitFileState,FragmentPath,DropInPaths"
SERVICE = ",Type,MainPID,NRestarts,ExecStart,User,Group,EnvironmentFiles"
CONFIG = (
    "/etc/passwd", "/etc/group", "/root/.msmtprc",
    "/etc/hostname", "/etc/machine-id", "/etc/os-release", "/etc/debian_version",
    "/etc/fstab", "/etc/ntp.conf", "/etc/ntpsec", "/etc/ntp.d",
    "/etc/default/ntp*", "/etc/default/gpsd", "/etc/gpsd*",
    "/etc/network", "/etc/NetworkManager/system-connections",
    "/run/NetworkManager/devices", "/run/NetworkManager/system-connections",
    "/run/NetworkManager/NetworkManager.state", "/run/systemd/netif/links",
    "/run/systemd/netif/leases", "/run/systemd/resolve", "/run/resolvconf",
    "/etc/NetworkManager/NetworkManager.conf", "/etc/NetworkManager/conf.d",
    "/etc/systemd/network", "/etc/systemd/resolved.conf*", "/etc/resolv.conf",
    "/etc/resolvconf", "/etc/dhcpcd.conf", "/etc/dhcp",
    "/etc/hosts", "/etc/nsswitch.conf", "/etc/apt/sources.list*",
    "/etc/apt/preferences*", "/etc/needrestart", "/etc/msmtprc",
    "/etc/msmtp*", "/etc/aliases", "/etc/mailname", "/etc/munin",
    "/etc/watchdog*", "/etc/default/watchdog", "/etc/default/munin-node",
    "/etc/webmin/config", "/etc/webmin/miniserv.conf", "/etc/webmin/version",
    "/usr/share/webmin/version", "/usr/libexec/webmin/version",
    "/etc/webmin/start", "/etc/webmin/stop", "/etc/default/webmin",
    "/etc/modules", "/etc/modules-load.d", "/etc/modprobe.d",
    "/etc/init.d/timeservice", "/usr/local/bin/pinup",
    "/etc/udev/rules.d", "/etc/default/cpufrequtils",
    "/etc/rc.local", "/etc/init.d", "/etc/rc[0-6S].d",
    "/var/spool/cron/crontabs/root", "/etc/supervisor", "/etc/supervisord.conf",
    "/usr/local/etc/ntp.conf", "/usr/local/etc/gpsd",
    "/usr/local/share/man/man[158]/ntp*", "/usr/local/share/man/man[158]/gpsd*",
    "/etc/cron.d", "/etc/crontab", "/etc/cron.daily/ntp*",
    "/etc/systemd/system", "/etc/systemd/system.conf*",
    "/boot/*.txt", "/boot/firmware/*.txt",
    "/boot/config.txt", "/boot/cmdline.txt", "/boot/firmware/config.txt",
    "/boot/firmware/cmdline.txt", "/boot/overlays/README",
    "/var/lib/ntp/leap*", "/var/lib/ntpsec/leap*", "/usr/share/zoneinfo/leap*",
    "/usr/sbin/ntpleapfetch", "/usr/bin/ntpleapfetch",
    "/usr/local/bin/ntpleapfetch", "/usr/local/sbin/ntpleapfetch",
    "/usr/share/doc/ntpsec", "/usr/share/man/man8/ntp*",
    "/usr/share/man/man5/ntp*", "/usr/share/man/man8/gpsd*",
)
PHYSICAL = (
    "GPS/RTC manufacturer, model, PCB revision, chipset and connection roles",
    "Antenna connection, location, PPS wiring and physical HAT stack order",
    "PoE+ HAT model/revision, IEEE class, negotiated power and switch budget",
    "Physical switch and port; controller DNAT role and address ownership",
    "Labelled original SD card identity matched to software media evidence",
    "Named operator, console access and independently verified media-swap recovery",
    "Historical manual ntpleapfetch command, source URL, success and exit status",
    "Approved Munin poller and intended address families; notification delivery",
)


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def ntpq_response_error(out, err):
    # ntpq can exit zero after protocol errors; preserve both raw streams and rc.
    text = out.decode("utf-8", "replace")
    if err.strip():
        return "nonempty diagnostic stream"
    if not text.strip():
        return "empty response"
    if re.search(r"(?im)^\s*\*\*\*|\b(?:timed out|BADASSOC|permission denied|connection refused)\b", text):
        return "protocol error or timeout in response"
    return None


def is_refclock(response, association):
    ids = re.findall(r"(?m)^associd=(\d+)\s+status=", response)
    sources = re.findall(r"(?:^|[,\n])\s*srcadr=([^,\s]+)", response)
    if ids != [str(association)] or len(sources) != 1:
        raise ValueError("missing, duplicate or mismatched association/source")
    try:
        source = ipaddress.ip_address(sources[0])
    except ValueError as exc:
        raise ValueError("non-numeric source") from exc
    # NTP's reserved reference-clock pseudo-address range, not refid=PPS:
    # real network peers may themselves have PPS refids.
    return source.version == 4 and source in ipaddress.ip_network("127.127.0.0/16")


def execute(argv):
    try:
        result = subprocess.run(argv, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                timeout=20, check=False,
                                env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
                                     "LC_ALL": "C", "SYSTEMD_PAGER": "cat",
                                     "SYSTEMD_COLORS": "0"})
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired as exc:
        return 124, exc.stdout or b"", (exc.stderr or b"") + b"\ncollector timeout\n"
    except OSError as exc:
        return 127, b"", str(exc).encode()


class Collector:
    def __init__(self, root, output, runner=execute):
        self.root = Path(root)
        self.output = Path(output)
        self.runner = runner
        self.commands = []
        self.issues = []
        self.extra = set()
        self.units = []
        self.leap_paths = set()
        self.ntpq = None
        self.process_units = set()
        self.trusted_uid = 0

    def path(self, name):
        return self.root / name.lstrip("/")

    def issue(self, label, detail):
        self.issues.append({"label": label, "detail": detail})

    def write_json(self, name, value):
        (self.output / name).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")

    def command(self, label, argv):
        is_ntpq = Path(argv[0]).name == "ntpq"
        index = len(self.commands)
        base = "commands/{:03d}-{}".format(index, label)
        if argv[0] == "ntpq":
            if self.ntpq is None:
                rc, out, err = 127, b"", b"No unique trusted ntpq executable discovered; see executables.json\n"
            else:
                argv = [self.ntpq] + argv[1:]
                rc, out, err = self.runner(argv)
        else:
            rc, out, err = self.runner(argv)
        (self.output / (base + ".stdout")).write_bytes(out)
        (self.output / (base + ".stderr")).write_bytes(err)
        response_error = ntpq_response_error(out, err) if is_ntpq and rc == 0 else None
        self.commands.append({"response_error": response_error, "label": label, "argv": argv, "exit_status": rc,
                              "stdout": base + ".stdout", "stderr": base + ".stderr"})
        # Persist progress even if the collection is subsequently interrupted.
        self.write_json("commands.json", self.commands)
        if rc:
            self.issue(label, "command failed; exit_status={}".format(rc))
        if response_error:
            self.issue(label, "ntpq response failed despite exit 0: " + response_error)
        return out.decode("utf-8", "replace") if rc == 0 and not response_error else ""

    def discover_ntpq(self):
        self.ntpq = None
        candidates = {}
        trusted = set()
        for directory in ("/usr/bin", "/usr/sbin", "/bin", "/sbin", "/usr/local/bin", "/usr/local/sbin"):
            name = directory + "/ntpq"
            path = self.path(name)
            try:
                resolved = path.resolve(strict=True)
                relative = resolved.relative_to(self.root.resolve())
                info = resolved.stat()
                if not stat.S_ISREG(info.st_mode) or not info.st_mode & 0o111:
                    raise ValueError("not an executable regular file")
                for ancestor in (resolved, *resolved.parents):
                    if ancestor == self.root.resolve().parent and self.root != Path("/"):
                        break
                    st = ancestor.stat()
                    if st.st_uid != self.trusted_uid or st.st_mode & 0o022:
                        raise ValueError("untrusted executable or ancestor ownership/mode")
                    if ancestor == self.root.resolve():
                        break
                logical = "/" + str(relative)
                candidates[name] = {"state": "trusted", "resolved": logical}
                trusted.add(logical)
                self.extra.add(name)
                self.extra.add(logical)
            except FileNotFoundError:
                candidates[name] = {"state": "absent"}
            except (OSError, ValueError, RuntimeError) as exc:
                candidates[name] = {"state": "rejected", "error": str(exc)}
                self.issue("ntpq-discovery", name + ": " + str(exc))
        if len(trusted) == 1:
            self.ntpq = next(iter(trusted))
        else:
            self.issue("ntpq-discovery", "expected one distinct trusted executable; found " + str(len(trusted)))
        self.write_json("executables.json", {"ntpq": {"selected": self.ntpq, "candidates": candidates}})

    def startup_evidence(self, phase):
        observations = {}
        pending = []
        for path in sorted(self.path("/proc").glob("[0-9]*/comm")):
            try:
                if path.read_text().strip() in ("ntpd", "gpsd"):
                    pending.append((path.parent.name, 0))
            except OSError as exc:
                self.issue("process-discovery", str(exc))
        if not pending:
            self.issue("startup", "no ntpd/gpsd comm entries observed")
        while pending:
            pid, depth = pending.pop(0)
            if pid in observations or depth > 8:
                continue
            entry = {}
            observations[pid] = entry
            try:
                base = self.path("/proc/" + pid)
                initial = (base / "stat").read_text()
                entry["exe"] = os.readlink(base / "exe")
                for field in ("comm", "status", "cgroup", "cmdline"):
                    entry[field] = (base / field).read_bytes().decode("utf-8", "replace")
                final = (base / "stat").read_text()
                # Field 22 starttime detects PID reuse; other stat fields are volatile.
                if initial.rsplit(")", 1)[1].split()[19] != final.rsplit(")", 1)[1].split()[19]:
                    raise ValueError("PID reused during observation")
                entry["state"] = "observed"
                for unit in re.findall(r"(?:^|/)([^/\n]+\.service)(?=/|$)", entry["cgroup"], re.M):
                    self.process_units.add(unit)
                parent = re.search(r"^PPid:\s+(\d+)$", entry["status"], re.M)
                if parent and int(parent.group(1)) > 0:
                    pending.append((parent.group(1), depth + 1))
            except (OSError, ValueError, IndexError) as exc:
                entry.update(state="error", error=str(exc))
                self.issue("startup", "pid " + pid + ": " + str(exc))
        self.write_json("startup-" + phase + ".json", observations)

    def discover_units(self):
        raw = self.command("unit-discovery", ["systemctl", "list-unit-files", "--no-pager", "--no-legend"])
        self.units = sorted({line.split()[0] for line in raw.splitlines()
                             if line.split() and UNIT_PATTERN.search(line.split()[0])
                             and line.split()[0].endswith((".service", ".timer", ".socket", ".path", ".target"))
                             and "@" not in line.split()[0]})
        active = self.command("loaded-units", ["systemctl", "list-units", "--all", "--plain", "--no-pager", "--no-legend"])
        self.units = sorted(set(self.units) | {line.split()[0] for line in active.splitlines()
                                             if line.split() and UNIT_PATTERN.search(line.split()[0])
                                             and "." in line.split()[0]})
        self.units = sorted(set(self.units) | self.process_units)
        for unit in self.units:
            props = COMMON + (SERVICE if unit.endswith(".service") else "")
            raw = self.command("unit-definition", ["systemctl", "show", unit, "--property=" + props])
            for line in raw.splitlines():
                key, sep, value = line.partition("=")
                if sep and key in ("FragmentPath", "DropInPaths"):
                    for name in value.split():
                        if name == "/dev/null" and key == "FragmentPath":
                            # A systemd mask is evidence, not a file to read.
                            continue
                        if name.startswith(("/etc/", "/lib/systemd/", "/usr/lib/systemd/", "/run/systemd/")) and "\\" not in name:
                            self.extra.add(name)
                        else:
                            self.issue("unit-path", "unresolved path: " + name)

    def record(self, name, records, capture, depth=0):
        if name in records:
            return
        if depth > 32:
            records[name] = {"state": "error", "error": "symlink/directory depth limit"}
            self.issue("capture", "depth limit: " + name)
            return
        path = self.path(name)
        try:
            info = path.lstat()
            entry = {"uid": info.st_uid, "gid": info.st_gid,
                     "mode": oct(stat.S_IMODE(info.st_mode)), "size": info.st_size,
                     "mtime_ns": info.st_mtime_ns}
            records[name] = entry
            if stat.S_ISLNK(info.st_mode):
                target = os.readlink(path)
                entry.update(state="symlink", target=target)
                resolved = os.path.normpath(target if target.startswith("/") else str(Path(name).parent / target))
                # Never follow configuration links into device or kernel pseudo-files.
                if resolved.startswith(("/etc/", "/run/", "/usr/", "/lib/", "/var/lib/", "/boot/")):
                    self.record(resolved, records, capture, depth + 1)
                elif resolved != "/dev/null":
                    self.issue("symlink", "target outside capture scope: " + name)
            elif stat.S_ISDIR(info.st_mode):
                entry["state"] = "directory"
                for child in sorted(path.iterdir()):
                    self.record(str(Path(name) / child.name), records, capture, depth + 1)
            elif stat.S_ISREG(info.st_mode):
                # O_NOFOLLOW rejects a final-component link swapped after lstat.
                fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                with os.fdopen(fd, "rb") as stream:
                    opened = os.fstat(stream.fileno())
                    if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                        raise OSError("file changed during open")
                    data = stream.read(LIMIT + 1)
                    after = os.fstat(stream.fileno())
                if len(data) > LIMIT or (after.st_size, after.st_mtime_ns) != (info.st_size, info.st_mtime_ns):
                    raise OSError("oversize or changing file")
                entry.update(state="file", sha256=digest(data))
                if capture:
                    blob = "captures/" + entry["sha256"]
                    (self.output / blob).write_bytes(data)
                    entry["capture"] = blob
                if name in ("/etc/ntp.conf", "/etc/ntpsec/ntp.conf", "/usr/local/etc/ntp.conf") or name in self.extra:
                    self.ntp_references(name, data, records, capture, depth)
            else:
                entry["state"] = "unsupported-type"
                self.issue("capture", "not a regular file/directory/link: " + name)
        except FileNotFoundError:
            records[name] = {"state": "absent"}
        except OSError as exc:
            records[name] = {"state": "error", "error": str(exc)}
            self.issue("capture", name + ": " + str(exc))

    def ntp_references(self, name, data, records, capture, depth):
        for line in data.decode("utf-8", "replace").splitlines():
            if not re.match(r"\s*(?:includefile|leapfile)\s", line):
                continue
            try:
                words = shlex.split(line, comments=True)
                if len(words) != 2 or not words[1].startswith(("/etc/", "/var/lib/", "/usr/share/")) or ".." in Path(words[1]).parts:
                    raise ValueError("relative, unsupported or ambiguous reference")
                ref = words[1]
                if words[0] == "leapfile":
                    self.leap_paths.add(ref)
                self.extra.add(ref)
                self.record(ref, records, capture, depth + 1)
                if records[ref]["state"] == "absent":
                    self.issue("ntp-reference", "missing: " + ref)
            except ValueError as exc:
                self.issue("ntp-reference", name + ": " + str(exc))

    def snapshot(self, capture):
        records = {}
        for pattern in sorted(set(CONFIG) | self.extra):
            matches = sorted(glob.glob(str(self.path(pattern))))
            if not matches:
                records[pattern] = {"state": "absent"}
            for match in matches:
                name = "/" + str(Path(match).relative_to(self.root))
                self.record(name, records, capture)
        return records

    def leap_evidence(self, before):
        evidence = {}
        for name, entry in before.items():
            if entry.get("state") != "file" or ("leap" not in name.lower() and name not in self.leap_paths):
                continue
            data = (self.output / entry["capture"]).read_bytes()
            expires = re.findall(rb"^#@\s+(\d+)\s*$", data, re.M)
            item = {"sha256": entry["sha256"], "validity": "requires installed-build review",
                    "expiration_state": "unknown"}
            if len(expires) == 1:
                try:
                    expiry = datetime.datetime(1900, 1, 1, tzinfo=datetime.timezone.utc) + datetime.timedelta(seconds=int(expires[0]))
                    item.update(expiration_utc=expiry.isoformat(),
                                expiration_state="expired" if expiry <= datetime.datetime.now(datetime.timezone.utc) else "not-expired")
                except (OverflowError, ValueError):
                    item["expiration_state"] = "invalid"
            evidence[name] = item
        self.write_json("leapfiles.json", evidence)

    def passive_files(self):
        patterns = (
            "/proc/cpuinfo", "/proc/meminfo", "/proc/cmdline", "/proc/uptime",
            "/proc/sys/kernel/random/boot_id", "/proc/device-tree/model",
            "/proc/device-tree/serial-number", "/proc/device-tree/hat/*",
            "/sys/class/block/mmcblk*/device/cid", "/sys/class/block/mmcblk*/device/name",
            "/sys/class/block/mmcblk*/device/serial", "/sys/class/pps/pps*/name",
            "/sys/class/pps/pps*/path", "/sys/class/pps/pps*/assert",
            "/sys/class/pps/pps*/clear", "/sys/class/rtc/rtc*/name",
            "/sys/class/rtc/rtc*/date", "/sys/class/rtc/rtc*/time",
            "/sys/class/watchdog/watchdog*/identity", "/sys/class/watchdog/watchdog*/state",
            "/sys/class/watchdog/watchdog*/timeout", "/sys/class/hwmon/hwmon*/name",
            "/sys/class/hwmon/hwmon*/fan*_input", "/sys/class/hwmon/hwmon*/temp*_input",
            "/sys/class/thermal/thermal_zone*/temp", "/sys/class/thermal/cooling_device*/type",
            "/sys/class/thermal/cooling_device*/cur_state", "/sys/bus/i2c/devices/*/name",
        )
        values = {}
        for pattern in patterns:
            matches = sorted(glob.glob(str(self.path(pattern))))
            if not matches:
                values[pattern] = {"state": "absent"}
            for match in matches:
                name = "/" + str(Path(match).relative_to(self.root))
                try:
                    with open(match, "rb") as stream:
                        data = stream.read(1024 * 1024)
                    values[name] = {"state": "observed", "text": data.decode("utf-8", "replace")}
                except OSError as exc:
                    values[name] = {"state": "error", "error": str(exc)}
                    self.issue("hardware-read", name + ": " + str(exc))
        self.write_json("passive-files.json", values)

    def diagnostics(self):
        commands = [
            ("kernel", ["uname", "-a"]), ("cpu", ["lscpu"]),
            ("boot-time", ["uptime", "-s"]), ("mounts", ["findmnt", "--json"]),
            ("media", ["lsblk", "--json", "--bytes", "--output", "NAME,PATH,TYPE,SIZE,FSTYPE,UUID,PARTUUID,MOUNTPOINT,MODEL,SERIAL,TRAN"]),
            ("packages", ["dpkg-query", "-W", "-f=${binary:Package}\t${Version}\t${Architecture}\t${db:Status-Abbrev}\n"]),
            ("package-origins", ["apt-cache", "-o", "Dir::Cache::pkgcache=", "-o", "Dir::Cache::srcpkgcache=", "policy", "ntpsec", "gpsd", "pps-tools", "webmin", "needrestart", "msmtp", "msmtp-mta", "munin-node", "watchdog"]),
            ("addresses", ["ip", "-details", "address", "show"]),
            ("routes4", ["ip", "-4", "route", "show", "table", "all"]),
            ("routes6", ["ip", "-6", "route", "show", "table", "all"]),
            ("rules4", ["ip", "-4", "rule", "show"]),
            ("rules6", ["ip", "-6", "rule", "show"]),
            ("listeners", ["ss", "-lntup"]),
            ("peers4", ["ntpq", "-4", "-n", "-c", "peers", "127.0.0.1"]),
            ("peers6", ["ntpq", "-6", "-n", "-c", "peers", "::1"]),
            ("ntp-variables", ["ntpq", "-n", "-c", "rv 0", "127.0.0.1"]),

            ("shared-memory", ["ipcs", "-m", "-p", "-t"]),
            ("devices", ["ls", "-l", "/dev/serial0", "/dev/serial1", "/dev/pps0", "/dev/rtc", "/dev/watchdog"]),
            ("processes", ["ps", "-eo", "pid,ppid,user,group,args"]),
            ("modules", ["lsmod"]),
            ("firmware", ["vcgencmd", "version"]),
            ("power-flags", ["vcgencmd", "get_throttled"]),
            ("bootloader", ["vcgencmd", "bootloader_version"]),
            ("kernel-journal", ["journalctl", "-k", "-b", "-n", "300", "--no-pager", "-o", "short-iso"]),
            ("timers", ["systemctl", "list-timers", "--all", "--no-pager"]),
            ("firewall-nft", ["nft", "list", "ruleset"]),
            ("firewall4", ["iptables-save"]), ("firewall6", ["ip6tables-save"]),
        ]
        for label, argv in commands:
            self.command(label, argv)
        associations = self.command("ntp-associations", ["ntpq", "-n", "-c", "associations", "127.0.0.1"])
        ids = []
        for line in associations.splitlines():
            fields = line.split()
            if len(fields) >= 2 and fields[0].isdigit() and fields[1].isdigit():
                ids.append(int(fields[1]))
        if not ids or len(ids) > 64 or len(ids) != len(set(ids)) or any(not 0 < i < 65536 for i in ids):
            self.issue("ntp-associations", "missing, duplicate or unsupported association set")
        else:
            for assoc in ids:
                variables = self.command("peer-variables", ["ntpq", "-n", "-c", "rv " + str(assoc), "127.0.0.1"])
                try:
                    if is_refclock(variables, assoc):
                        self.command("clock-variables", ["ntpq", "-n", "-c", "cv " + str(assoc), "127.0.0.1"])
                except ValueError as exc:
                    self.issue("refclock-classification", "association " + str(assoc) + ": " + str(exc))
        for unit in self.units:
            self.command("unit-journal", ["journalctl", "-u", unit, "-b", "-n", "100", "--no-pager", "-o", "short-iso"])
        self.passive_files()

    def collect(self):
        (self.output / "commands").mkdir(mode=0o700)
        (self.output / "captures").mkdir(mode=0o700)
        self.write_json("INCOMPLETE.json", {"schema": SCHEMA, "started": now()})
        self.discover_ntpq()
        self.startup_evidence("before")
        self.discover_units()
        before = self.snapshot(True)
        self.write_json("protected-before.json", before)
        self.leap_evidence(before)
        self.diagnostics()
        self.startup_evidence("after")
        # Repeat discovery so changes in installed unit paths also affect coverage.
        self.discover_units()
        after = self.snapshot(False)
        self.write_json("protected-after.json", after)
        comparison = compare_snapshots(before, after)
        self.write_json("integrity.json", comparison)
        unchanged = comparison["protected_unchanged"]
        if not unchanged:
            self.issue("protected-unchanged", "pre/post paths, metadata or content differ")
        code = 3 if not unchanged else (2 if self.issues else 0)
        report = {"schema": SCHEMA, "target": TARGET, "finished": now(),
                  "collection_status": "collected" if code == 0 else "incomplete",
                  "exit_status": code, "protected_unchanged": unchanged,
                  "baseline_accepted": False, "issues": self.issues,
                  "operator_confirmation_required": list(PHYSICAL),
                  "review_required": [
                      "All absent/error entries, unsupported paths and alternative installations",
                      "Effective network/DNS ownership and DHCP/RA resistance from profiles and state",
                      "NTP/GPSD startup paths, include closure, refclocks and configured leapfile",
                      "Leapfile validity, expiration and installed-build reload behavior",
                      "Boot include files, firmware version and EEPROM state if not evidenced",
                      "Per-user msmtp files and custom scripts referenced by captured settings",
                      "No mutation claim is limited to protected snapshots; review transport and journals",
                  ]}
        self.write_json("report.json", report)
        (self.output / "INCOMPLETE.json").unlink()
        print(json.dumps({"schema": SCHEMA, "exit_status": code,
                          "collection_status": report["collection_status"],
                          "output": str(self.output), "baseline_accepted": False}))
        return code


def compare_snapshots(before, after):
    changes = []
    runtime_timestamps = []
    for name in sorted(set(before) | set(after)):
        old = {k: v for k, v in before.get(name, {}).items() if k != "capture"}
        new = after.get(name, {})
        fields = sorted(k for k in set(old) | set(new) if old.get(k) != new.get(k))
        # Only resolver runtime mtime is volatile. Never waive content, mode,
        # owner, link target, file type, or path membership differences.
        if (name == "/run/resolvconf" or name.startswith("/run/resolvconf/")) and "mtime_ns" in fields and old.get("state") == new.get("state") and old.get("state") in ("file", "directory"):
            runtime_timestamps.append({"path": name, "before": old["mtime_ns"], "after": new["mtime_ns"]})
            fields.remove("mtime_ns")
        if fields:
            changes.append({"path": name, "fields": fields})
    return {"protected_unchanged": not changes, "protected_changes": changes,
            "resolver_runtime_mtime_changes": runtime_timestamps}


def preflight(root, uid):
    if uid != 0:
        raise ValueError("root is required for complete protected reads")
    node = (root / "proc/sys/kernel/hostname").read_text().strip()
    if node != TARGET:
        raise ValueError("kernel hostname does not match authorized target")
    release = {}
    for line in (root / "etc/os-release").read_text().splitlines():
        key, sep, value = line.partition("=")
        if sep:
            if key in release:
                raise ValueError("duplicate os-release key")
            release[key] = value.strip().strip('"')
    if release.get("ID") not in ("debian", "raspbian") or release.get("VERSION_ID") != "11":
        raise ValueError("expected Debian/Raspbian 11 baseline")


def output_path(name):
    output = Path(name)
    if output.parent != Path("/var/tmp") or not re.fullmatch(r"ntp-baseline-j1-svntp1-[A-Za-z0-9_-]+", output.name):
        raise ValueError("output must be a new /var/tmp/ntp-baseline-j1-svntp1-NAME directory")
    return output


def main():
    parser = argparse.ArgumentParser(description="Authorized Debian 11 baseline only; see inspect-node.md")
    parser.add_argument("--collect", action="store_true", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    os.umask(0o077)
    try:
        preflight(Path("/"), os.geteuid())
        output = output_path(args.output)
        # A new direct child of root-owned /var/tmp; no recursive mkdir or overwrite.
        parent = output.parent.lstat()
        if not stat.S_ISDIR(parent.st_mode) or parent.st_uid != 0 or not parent.st_mode & stat.S_ISVTX:
            raise ValueError("/var/tmp must be a root-owned sticky directory")
        output.mkdir(mode=0o700)
    except (OSError, ValueError) as exc:
        print("preflight rejected: " + str(exc), file=sys.stderr)
        return 64
    try:
        return Collector(Path("/"), output).collect()
    except KeyboardInterrupt:
        print("interrupted; retain protected partial output", file=sys.stderr)
        return 130
    except Exception as exc:
        print("collection aborted: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
PYTHON
