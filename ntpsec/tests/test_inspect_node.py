"""Offline only: import the embedded engine, use synthetic roots and fake commands."""
import contextlib
import io
import os
from pathlib import Path
import re
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/inspect-node.sh"
SOURCE = SCRIPT.read_text().split("<<'PYTHON'\n", 1)[1].rsplit("\nPYTHON", 1)[0]
ENGINE = {"__name__": "offline_test"}
exec(compile(SOURCE, str(SCRIPT), "exec"), ENGINE)  # Does not call main.


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "root"
        self.root.mkdir()
        self.output = Path(self.temp.name) / "evidence"
        self.output.mkdir(mode=0o700)
        self.put("/proc/sys/kernel/hostname", b"j1-svntp1\n")
        self.put("/etc/os-release", b'ID=debian\nVERSION_ID="11"\n')
        self.put("/etc/ntp.conf", b"leapfile /var/lib/ntp/leap-seconds.list\n")
        self.put("/var/lib/ntp/leap-seconds.list", b"#@ 4102444800\n")
        binary = self.put("/usr/local/bin/ntpq", b"synthetic executable; never executed\n")
        binary.chmod(0o755)
        self.put("/proc/42/comm", b"ntpd\n")
        self.put("/proc/42/stat", ("42 (ntpd) S " + "0 " * 18 + "100 0\n").encode())
        self.put("/proc/42/status", b"Name:\tntpd\nPPid:\t0\n")
        self.put("/proc/42/cgroup", b"0::/system.slice/rc-local.service\n")
        self.put("/proc/42/cmdline", b"/usr/local/sbin/ntpd\x00-g\x00")
        (self.root / "proc/42/exe").symlink_to("/usr/local/sbin/ntpd")
        self.calls = []
        self.collector = ENGINE["Collector"](self.root, self.output, self.fake)
        self.collector.trusted_uid = os.getuid()

    def put(self, name, data):
        path = self.root / name.lstrip("/")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def fake(self, argv):
        self.calls.append(argv)
        if argv[:2] == ["systemctl", "list-unit-files"]:
            return 0, b"ntpsec.service enabled\nntpleapfetch.timer enabled\n", b""
        if argv[:2] == ["systemctl", "show"]:
            return 0, b"LoadState=loaded\nActiveState=active\n", b""
        if "rv 1234" in argv:
            return 0, b"associd=1234 status=961a,\nsrcadr=127.127.28.1, refid=PPS\n", b""
        if "associations" in argv:
            return 0, b"ind assid status\n1 1234 961a\n", b""
        return 0, b"synthetic\n", b""

    def collect(self):
        with contextlib.redirect_stdout(io.StringIO()) as stdout:
            code = self.collector.collect()
        return code, stdout.getvalue()

    def test_success_byte_exact_capture_and_permissions(self):
        import json
        original_umask = os.umask(0o077)
        self.addCleanup(os.umask, original_umask)
        raw = b"# synthetic only\nserver 192.0.2.1\n\x00\xff"
        self.put("/etc/ntp.conf", raw)
        code, stdout = self.collect()
        self.assertEqual(code, 0)
        self.assertNotIn("server", stdout)
        report = json.loads((self.output / "report.json").read_text())
        self.assertFalse(report["baseline_accepted"])
        self.assertTrue(report["protected_unchanged"])
        before = json.loads((self.output / "protected-before.json").read_text())
        self.assertEqual((self.output / before["/etc/ntp.conf"]["capture"]).read_bytes(), raw)
        self.assertFalse((self.output / "INCOMPLETE.json").exists())
        self.assertTrue(report["operator_confirmation_required"])
        for path in self.output.rglob("*"):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700 if path.is_dir() else 0o600)

    def test_identity_privilege_and_os_rejections(self):
        gate = ENGINE["preflight"]
        gate(self.root, 0)
        with self.assertRaisesRegex(ValueError, "root"):
            gate(self.root, 1000)
        self.put("/proc/sys/kernel/hostname", b"j1-svntp\n")
        with self.assertRaisesRegex(ValueError, "hostname"):
            gate(self.root, 0)
        self.put("/proc/sys/kernel/hostname", b"j1-svntp1\n")
        for content in (b"ID=debian\nVERSION_ID=13\n", b"ID=debian\nID=debian\nVERSION_ID=11\n",
                        b"ID=ubuntu\nVERSION_ID=11\n", b"ID=debian\n"):
            self.put("/etc/os-release", content)
            with self.assertRaises(ValueError):
                gate(self.root, 0)

    def test_output_path_rejections_and_existing_output(self):
        for name in ("relative", "/tmp/ntp-baseline-j1-svntp1-a", "/var/tmp/other",
                     "/var/tmp/ntp-baseline-j1-svntp1-a/../b", "/var/tmp/ntp-baseline-j1-svntp1-"):
            with self.assertRaises(ValueError):
                ENGINE["output_path"](name)
        self.assertEqual(str(ENGINE["output_path"]("/var/tmp/ntp-baseline-j1-svntp1-20260916")),
                         "/var/tmp/ntp-baseline-j1-svntp1-20260916")
        # Main's mkdir must reject both pre-existing directories and links.
        for existing in (self.output, Path(self.temp.name) / "link"):
            if not existing.exists():
                existing.symlink_to(self.output)
            with mock.patch.dict(ENGINE, {"preflight": lambda root, uid: None,
                                         "output_path": lambda name: existing}), \
                 mock.patch.object(ENGINE["sys"], "argv", ["collector", "--collect", "--output", "fixture"]), \
                 mock.patch.object(Path, "lstat", return_value=SimpleNamespace(st_mode=stat.S_IFDIR | stat.S_ISVTX, st_uid=0)), \
                 contextlib.redirect_stderr(io.StringIO()) as stderr:
                self.assertEqual(ENGINE["main"](), 64)
                self.assertIn("File exists", stderr.getvalue())

    def test_preflight_failure_never_starts_collection(self):
        with mock.patch.dict(ENGINE, {"preflight": mock.Mock(side_effect=ValueError("fixture identity")),
                                     "Collector": mock.Mock(side_effect=AssertionError("must not collect"))}), \
             mock.patch.object(ENGINE["sys"], "argv", ["collector", "--collect", "--output", str(self.output)]), \
             contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(ENGINE["main"](), 64)
        self.assertFalse((self.output / "commands").exists())

    def test_leap_expiration_and_unknown_validity(self):
        import json
        self.collect()
        leap = json.loads((self.output / "leapfiles.json").read_text())["/var/lib/ntp/leap-seconds.list"]
        self.assertEqual(leap["expiration_utc"], "2030-01-01T00:00:00+00:00")
        self.assertEqual(leap["validity"], "requires installed-build review")

    def test_failures_preserve_both_streams_and_status(self):
        def fail(argv):
            if argv[0] == "ip":
                return 127, b"partial output\x00", b"unavailable\n"
            return self.fake(argv)
        self.collector.runner = fail
        code, _ = self.collect()
        self.assertEqual(code, 2)
        result = next(c for c in self.collector.commands if c["label"] == "addresses")
        self.assertEqual(result["exit_status"], 127)
        self.assertEqual((self.output / result["stdout"]).read_bytes(), b"partial output\x00")
        self.assertEqual((self.output / result["stderr"]).read_bytes(), b"unavailable\n")

    def test_mutation_and_new_file_rejected(self):
        def change(argv):
            if argv[0] == "uname":
                self.put("/etc/ntp.conf", b"changed\n")
                self.put("/etc/ntpsec/new.conf", b"new\n")
            return self.fake(argv)
        self.collector.runner = change
        code, _ = self.collect()
        self.assertEqual(code, 3)

    def test_symlink_capture_and_special_file_rejection(self):
        self.put("/run/resolvconf/resolv.conf", b"nameserver 192.0.2.53\n")
        (self.root / "etc/resolv.conf").symlink_to("/run/resolvconf/resolv.conf")
        before = self.collector.snapshot(False)
        self.assertEqual(before["/etc/resolv.conf"]["target"], "/run/resolvconf/resolv.conf")
        self.assertEqual(before["/run/resolvconf/resolv.conf"]["state"], "file")
        fifo = self.root / "etc/msmtprc"
        os.mkfifo(fifo)
        before = self.collector.snapshot(False)
        self.assertEqual(before["/etc/msmtprc"]["state"], "unsupported-type")
        self.assertTrue(self.collector.issues)

    def test_ntp_references_are_not_executed_or_guessed(self):
        self.put("/etc/ntp.conf", b'includefile /etc/ntp-extra.conf\nleapfile relative\n')
        self.put("/etc/ntp-extra.conf", b"# bytes\n")
        before = self.collector.snapshot(False)
        self.assertEqual(before["/etc/ntp-extra.conf"]["state"], "file")
        self.assertTrue(any(i["label"] == "ntp-reference" for i in self.collector.issues))

    def test_unreadable_file_and_oversize_are_not_absent(self):
        original = os.open
        def deny(path, flags):
            if str(path).endswith("ntp.conf"):
                raise PermissionError("fixture denied")
            return original(path, flags)
        with mock.patch.object(ENGINE["os"], "open", side_effect=deny):
            records = self.collector.snapshot(False)
        self.assertEqual(records["/etc/ntp.conf"]["state"], "error")
        with mock.patch.dict(ENGINE, {"LIMIT": 2}):
            records = self.collector.snapshot(False)
        self.assertEqual(records["/etc/ntp.conf"]["state"], "error")

    def test_missing_and_timeout_status(self):
        with mock.patch.object(ENGINE["subprocess"], "run", side_effect=FileNotFoundError("missing")):
            self.assertEqual(ENGINE["execute"](["fake"])[0], 127)
        error = ENGINE["subprocess"].TimeoutExpired(["fake"], 20, output=b"partial", stderr=b"error")
        with mock.patch.object(ENGINE["subprocess"], "run", side_effect=error):
            code, out, err = ENGINE["execute"](["fake"])
        self.assertEqual((code, out), (124, b"partial"))
        self.assertIn(b"error", err)

    def test_interrupt_leaves_incomplete_marker(self):
        def interrupt(argv):
            raise KeyboardInterrupt()
        self.collector.runner = interrupt
        with self.assertRaises(KeyboardInterrupt):
            self.collect()
        self.assertTrue((self.output / "INCOMPLETE.json").exists())
        self.assertFalse((self.output / "report.json").exists())

    def test_service_properties_and_network_boundary(self):
        self.collect()
        for argv in self.calls:
            self.assertNotIn(argv[0], ("ssh", "curl", "wget", "dig", "ntpleapfetch", "needrestart", "gpspipe", "i2cdetect", "wdctl"))
            self.assertNotIn(argv[0], ("nmcli", "networkctl", "resolvectl"))
            if argv[0] == "systemctl":
                self.assertIn(argv[1], ("show", "list-unit-files", "list-units", "list-timers"))
            if Path(argv[0]).name == "ntpq":
                self.assertIn(argv[-1], ("127.0.0.1", "::1"))
                self.assertIn("-n", argv)
            if argv[:2] == ["systemctl", "show"] and not argv[2].endswith(".service"):
                self.assertNotIn("MainPID", argv[-1])
                self.assertNotIn("NRestarts", argv[-1])
        self.assertTrue(any("rv 1234" in argv for argv in self.calls))
        self.assertTrue(any("cv 1234" in argv for argv in self.calls))

    def test_custom_ntpq_and_process_startup(self):
        import json
        code, _ = self.collect()
        self.assertEqual(code, 0)
        self.assertTrue(any(argv[0] == "/usr/local/bin/ntpq" for argv in self.calls))
        self.assertTrue(any(argv[:3] == ["systemctl", "show", "rc-local.service"] for argv in self.calls))
        process = json.loads((self.output / "startup-before.json").read_text())["42"]
        self.assertEqual(process["exe"], "/usr/local/sbin/ntpd")
        self.assertEqual(process["state"], "observed")

    def test_timeservice_guide_startup_is_captured_not_executed(self):
        self.put("/etc/init.d/timeservice", b"#!/bin/sh\n# synthetic startup definition\n")
        def guide(argv):
            if argv[:2] == ["systemctl", "list-unit-files"]:
                return 0, b"timeservice.service enabled\n", b""
            return self.fake(argv)
        self.collector.runner = guide
        code, _ = self.collect()
        self.assertEqual(code, 0)
        self.assertTrue(any(a[:3] == ["systemctl", "show", "timeservice.service"] for a in self.calls))
        self.assertTrue(any(a[:3] == ["journalctl", "-u", "timeservice.service"] for a in self.calls))
        self.assertFalse(any(a[0] == "/etc/init.d/timeservice" for a in self.calls))
        import json
        before = json.loads((self.output / "protected-before.json").read_text())
        self.assertEqual(before["/etc/init.d/timeservice"]["state"], "file")

    def test_ambiguous_ntpq_never_executed(self):
        other = self.put("/usr/bin/ntpq", b"other")
        other.chmod(0o755)
        code, _ = self.collect()
        self.assertEqual(code, 2)
        self.assertFalse(any(Path(a[0]).name == "ntpq" for a in self.calls))
        self.assertTrue(any(c["label"] == "peers4" and c["exit_status"] == 127 for c in self.collector.commands))

    def test_untrusted_and_missing_ntpq_remain_errors(self):
        (self.root / "usr/local/bin/ntpq").chmod(0o777)
        self.collector.discover_ntpq()
        self.assertIsNone(self.collector.ntpq)
        self.assertTrue(self.collector.issues)
        (self.root / "usr/local/bin/ntpq").unlink()
        self.collector.discover_ntpq()
        self.assertIsNone(self.collector.ntpq)

    def test_mask_fragment_is_not_opened(self):
        def mask(argv):
            if argv[:2] == ["systemctl", "show"]:
                return 0, b"LoadState=masked\nFragmentPath=/dev/null\n", b""
            return self.fake(argv)
        self.collector.runner = mask
        code, _ = self.collect()
        self.assertEqual(code, 0)
        self.assertNotIn("/dev/null", self.collector.extra)

    def test_runtime_mtime_only_is_reported_separately(self):
        compare = ENGINE["compare_snapshots"]
        old = {"state": "file", "uid": 0, "gid": 0, "mode": "0o644", "size": 2, "mtime_ns": 1, "sha256": "a"}
        name = "/run/resolvconf/metrics/0000202 eth0.ra"
        result = compare({name: old}, {name: dict(old, mtime_ns=2)})
        self.assertTrue(result["protected_unchanged"])
        self.assertEqual(len(result["resolver_runtime_mtime_changes"]), 1)
        for key, value in (("sha256", "b"), ("mode", "0o666"), ("uid", 1), ("state", "symlink")):
            self.assertFalse(compare({name: old}, {name: dict(old, mtime_ns=2, **{key:value})})["protected_unchanged"])
        self.assertFalse(compare({name: old}, {})["protected_unchanged"])
        self.assertFalse(compare({}, {name: old})["protected_unchanged"])
        self.assertFalse(compare({"/etc/resolv.conf": old}, {"/etc/resolv.conf": dict(old, mtime_ns=2)})["protected_unchanged"])
        link = {"state": "symlink", "target": "a"}
        self.assertFalse(compare({name: link}, {name: dict(link, target="b")})["protected_unchanged"])

    def test_process_disappearance_stays_unknown(self):
        (self.root / "proc/42/status").unlink()
        code, _ = self.collect()
        self.assertEqual(code, 2)
        self.assertTrue(any(i["label"] == "startup" for i in self.collector.issues))

    def test_ntpq_zero_exit_errors_are_preserved_and_rejected(self):
        for out, err in ((b"", b"***Request timed out\n"),
                         (b"***Server error code BADASSOC\n", b""),
                         (b"", b""), (b"response", b"unrecognized warning")):
            self.assertIsNotNone(ENGINE["ntpq_response_error"](out, err))
        def timeout(argv):
            if "::1" in argv:
                return 0, b"", b"***Request timed out\n"
            return self.fake(argv)
        self.collector.runner = timeout
        code, _ = self.collect()
        self.assertEqual(code, 2)
        entry = next(c for c in self.collector.commands if c["label"] == "peers6")
        self.assertEqual(entry["exit_status"], 0)
        self.assertTrue(entry["response_error"])
        self.assertEqual((self.output / entry["stderr"]).read_bytes(), b"***Request timed out\n")

    def test_network_pps_peer_does_not_receive_clock_query(self):
        def network(argv):
            if "rv 1234" in argv:
                return 0, b"associd=1234 status=961a,\nsrcadr=192.0.2.1, refid=PPS\n", b""
            return self.fake(argv)
        self.collector.runner = network
        self.assertEqual(self.collect()[0], 0)
        self.assertFalse(any("cv 1234" in a for a in self.calls))

    def test_refclock_classification_rejects_ambiguous_responses(self):
        classify = ENGINE["is_refclock"]
        for data in ("", "associd=2 status=0,\nsrcadr=127.127.28.1",
                     "associd=1 status=0,\nsrcadr=127.127.28.1, srcadr=192.0.2.1",
                     "associd=1 status=0,\nsrcadr=example.invalid"):
            with self.assertRaises(ValueError):
                classify(data, 1)
        self.assertTrue(classify("associd=1 status=0,\nsrcadr=127.127.28.1", 1))
        self.assertFalse(classify("associd=1 status=0,\nsrcadr=2001:db8::1", 1))

    def test_shell_readonly_local_collision_policy(self):
        for path in SCRIPT.parents[1].rglob("*.sh"):
            source = path.read_text()
            readonly = set(re.findall(r"\breadonly\s+(?:-[a-zA-Z]+\s+)?([a-zA-Z_][a-zA-Z0-9_]*)", source))
            local = set(re.findall(r"\blocal\s+(?:-[a-zA-Z]+\s+)?([a-zA-Z_][a-zA-Z0-9_]*)", source))
            self.assertFalse(readonly & local, str(path))


PROBE_SCRIPT = SCRIPT.with_name("inspect-ipv6-time.sh")
PROBE_SOURCE = PROBE_SCRIPT.read_text().split("<<'PYTHON'\n", 1)[1].rsplit("\nPYTHON", 1)[0]
PROBE = {"__name__": "offline_probe_test"}
exec(compile(PROBE_SOURCE, str(PROBE_SCRIPT), "exec"), PROBE)


class IPv6ProbeTests(unittest.TestCase):
    def packet(self):
        request = PROBE["request_packet"](1700000000.25)
        response = bytearray(48)
        response[0] = 0x24
        response[1] = 1
        response[24:32] = request[40:48]
        response[32:40] = request[40:48]
        response[40:48] = request[40:48]
        return request, response

    def test_response_rejections(self):
        request, response = self.packet()
        self.assertEqual(PROBE["validate_response"](response, request)["stratum"], 1)
        for index, value in ((0, 0x23), (0, 0xe4), (1, 0), (24, response[24] ^ 1)):
            altered = bytearray(response)
            altered[index] = value
            with self.assertRaises(ValueError):
                PROBE["validate_response"](altered, request)
        for malformed in (response[:47], response + bytes(465)):
            with self.assertRaises(ValueError):
                PROBE["validate_response"](malformed, request)

    def test_one_numeric_loopback_request_and_no_retry(self):
        request, response = self.packet()
        for reply in (bytes(response), TimeoutError("fixture timeout")):
            sock = mock.MagicMock()
            sock.__enter__.return_value = sock
            if isinstance(reply, Exception):
                sock.recv.side_effect = reply
            else:
                sock.recv.return_value = reply
            factory = mock.Mock(return_value=sock)
            result = PROBE["probe"](factory, lambda: 1700000000.25)
            sock.connect.assert_called_once_with(("::1", 123, 0, 0))
            sock.send.assert_called_once_with(request)
            sock.settimeout.assert_called_once_with(5)
            factory.assert_called_once_with(PROBE["socket"].AF_INET6, PROBE["socket"].SOCK_DGRAM, PROBE["socket"].IPPROTO_UDP)
            self.assertEqual(result["request_count"], 1)
            self.assertEqual(result["exit_status"], 2 if isinstance(reply, Exception) else 0)

    def test_wrong_host_never_probes(self):
        with mock.patch.object(PROBE["sys"], "argv", ["probe", "--probe"]), \
             mock.patch.object(PROBE["os"], "uname", return_value=SimpleNamespace(nodename="wrong")), \
             mock.patch.dict(PROBE, {"probe": mock.Mock(side_effect=AssertionError("no probe"))}), \
             contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(PROBE["main"](), 64)


if __name__ == "__main__":
    unittest.main(verbosity=2)
