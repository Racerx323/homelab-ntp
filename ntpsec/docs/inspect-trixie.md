# Trixie target-state inspection proposal

Prepared October 8, 2026. Status: repository preparation only; not executed.
This is the next stage after accepted first boot. Preparing this definition
does not authorize commands on the new node.

Revision note: the initial immutable v1 bundle was subsequently approved and
executed; see the [recorded results](trixie-inspection-results-20261008.md).
The current repository collector adds needrestart to the package query because
v1 omitted it. This source revision requires a new bundle and approval before
execution; it does not alter or authorize a repeat of the retained v1 payload.
The separate [package-policy preflight](trixie-package-stage.md) uses the
--package-policy mode and its own scope/bundle; it does not repeat this
bootstrap inspection.

## Target, identity and execution boundary

Target is the rebuilt j2-svntp1, observed at Ethernet DHCP 10.1.0.137, Debian
13 Trixie, aarch64. DHCP is not the later fixed address. Aaron operates the
existing trusted KVM console or already-open SSH session as ama. The prior
console/SSH ED25519 comparison matched:
`SHA256:yXiID8RObBoIejVpvr2KesaqIlocbSORyemD5dKrEys`.

The interpreter must already exist at /usr/bin/python3. If unavailable, stop;
no installation, privilege escalation or alternate runner is included. The
collector rejects root, another hostname, another architecture, or an OS
identity other than ID=debian, VERSION_ID=13, VERSION_CODENAME=trixie before
any subprocess command. It does not infer these facts from the SSH address.

Run once by pasting the complete immutable bundle's operator-paste.txt into
that verified session. The artifact invokes:

```sh
/usr/bin/python3 -I - --inspect <<'TRIXIE_INSPECTION_PY'
# Exact bundled inspect-trixie.py source is inserted here by the bundle builder.
TRIXIE_INSPECTION_PY
```

The block above explains the invocation; it is not the runnable paste artifact.
Use operator-paste.txt, which contains the full approved source. It streams the
script through stdin and writes no script, report, staging directory or logs
on the target. Output is JSON on stdout. Aaron may retain the output locally
as owner-private evidence. Do not open another SSH session, change known_hosts,
collect a password in chat, or execute against a guessed DHCP address.

This scope permits passive reads and fixed status queries only. It excludes
sudo, clock queries to other nodes, controller access, network probes, package
refresh/download/install, reboots, firmware/EEPROM updates, I2C/GPS transactions,
fan or GPIO control, and any network, service or configuration mutation.
Preserve the primary, antenna/splitter wiring and original-card rollback.

## Exact evidence collection

The executable command allowlist is COMMANDS in inspect-trixie.py. It covers:

| Area | Evidence and limits |
| --- | --- |
| Identity | Hostname, Debian release fields, architecture, effective UID, kernel and boot ID |
| Packages | Version/status queries for the explicit package list; missing packages remain reported, without installation |
| Sources | Hashes, scheme/hostname-only repository inventory and allowlisted single-line Deb822 hints; URI credentials, paths, queries and fragments omitted |
| Service ownership | Selected unit load/active/substate, fragment path and unit-file state; no ExecStart/environment or credential exports |
| NetworkManager | Installed version/help; device GENERAL/IP4/IP6 properties, active UUID/type/device and Wi-Fi radio status only when the unit is observed active |
| Ethernet profile | One validated active eth0 Ethernet UUID; explicit connection/IPv4/IPv6 properties only, excluding wireless-security and 802.1x fields |
| Networking | Interface addresses, IPv4/IPv6 routes, listening sockets and rfkill state; no packets sent or connection changes |
| Storage/platform | Root mount, block-device summary, loaded modules, device-tree model, selected boot settings and config hashes |
| Hardware | vcgencmd version/get_throttled/measure_temp, passive thermal/hwmon files and serial/PPS/RTC/I2C device-entry metadata; no device I/O scans, stress tests or sensor writes |
| Local authority | Locations of installed relevant manual pages; unavailable manuals remain gaps |

Only the named OS/boot/source files are hashed. Source-file enumeration is
limited to /etc/apt/sources.list and .list/.sources files in
/etc/apt/sources.list.d, with at most 24 total hashed paths. Boot include
directives are recorded without following them. Settings in conditional blocks
and source hints are not treated as effective configuration. NetworkManager
password-bearing profile files, SSH keys and credential files are not opened.
The collector does not dump complete config files, command lines or journals.

Passive file reads are restricted to the device-tree model and the named
thermal/hwmon patterns, at most 64 paths. It also records lstat
ownership/type and symlink targets for at most 32 device entries matching
`serial[0-9]*`, `ttyAMA[0-9]*`, `ttyS[0-9]*`, `pps[0-9]*`, `rtc[0-9]*` and `i2c-[0-9]*`
under /dev, without opening the devices. The 32-entry ceiling is a coverage
limit; absence from this bounded projection is not proof that a device is absent.
The collector retains up to 64 KiB
per file input and per command stdout/stderr stream. Command capture is cut
for retention after execution; this is not a streaming memory-limit claim.
Every subprocess has at most 12 seconds, within a 300-second command budget.
Aaron interrupts the complete invocation after 330 seconds if it has not
returned and retains any output/error. Do not retry an interrupted run to
erase gaps. Read-only queries may produce ordinary OS audit/activity records;
no zero-write claim is made for the operating system itself.

## Retention, interpretation and acceptance

Use the existing owner-private historical j1-svntp1 evidence directory. That
name is archival; current identity is j2-svntp1. Retain one new
trixie-inspection-result.json or an equivalent complete operator transcript,
plus bundle hash, command/status, operator and receipt time. Never overwrite
existing evidence or create another evidence tree. Do not retain passwords.

The JSON preserves command arguments, statuses, stdout/stderr, timeouts,
missing tools, truncation, safe file projections, before/after content-hash
drift and boot continuity. It does not compare volatile file mtimes. Inspect
errors and incomplete output before considering another run.

- Exit 0: requested evidence captured without detected collection gaps.
- Exit 2: evidence captured with missing/unsupported/permission/error,
  truncation, deadline or drift gaps; keep and review it.
- Exit 1: identity/usage/inspection failure; no complete collection claimed.
  Inspect the error and any transcript rather than assuming commands ran or
  did not run.

These statuses are collection outcomes, not platform/service acceptance.
Review source suites and trust, actual configuration owners, Ethernet profile
and automatic DNS/IPv6 behavior before defining later changes. A missing
NetworkManager profile is not permission to substitute another network tool.
Do not infer permanent Wi-Fi disablement from wlan0 DOWN or an idle radio.
Distinguish current vcgencmd throttle bits from historical occurrence bits.
No NTP/GPSD, full HAT/sensor/thermal or sustained primary-health acceptance is
implied. If identity/boot changes, hashes drift, hardware symptoms appear or
relevant ownership remains unknown, hold later mutations and preserve evidence.

## Documentation and offline validation

Current NetworkManager documentation was fetched through Context7 for
[nmcli read-only fields and connection inspection](https://networkmanager.dev/docs/api/latest/nmcli.html).
The same workflow fetched official Raspberry Pi documentation for
[vcgencmd status, temperature and throttle flags](https://github.com/raspberrypi/documentation/blob/master/documentation/asciidoc/computers/os/graphics-utilities.adoc).
These sources support the proposed queries; installed target versions and
local manuals remain authoritative. Unsupported syntax is retained as a gap.

Offline tests cover identity/root rejection before commands, missing tools,
timeouts, truncation, URI credential omission, ambiguous/malformed profile
rejection, retained configuration drift and the fixed read-only command scope.
The shared test runner and existing CI job include these tests. None contacts
the target or proves target tool availability.

Approval must bind this specification, exact collector, runnable paste artifact
and first-boot reference to one SHA-256 bundle. It authorizes one operator-run
inspection only, ending after output retention and review. It does not authorize
updates, fixed networking, Wi-Fi changes or NTP/GPSD setup.
