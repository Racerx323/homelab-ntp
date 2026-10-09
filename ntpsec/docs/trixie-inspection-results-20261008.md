# Trixie inspection results: October 8, 2026

Ran the exact approved payload once as ama on j2-svntp1 at 10.1.0.137.
Approved bundle SHA-256:
`0e24687cf003dc20b72a8901f31bebf6a79b3a9ac5dccff77aacdbc05b0800e9`.

Later [P0 package-policy results](package-policy-results-20261008.md) resolve
the needrestart omission: the package is not installed, with cached candidate
3.11-1 and an existing kernel-hint suppression fragment. The unknown-state
statements below record the earlier inspection's coverage, not a contradiction
of that later observation. No packages have been installed by either inspection.

Aaron subsequently authorized agent-driven SSH after installing his public
key and verifying connectivity. That explicit instruction replaced the
operator-paste transport; the approved payload and mutation exclusions were
unchanged. Strict checking used the console-verified ED25519 key, key-only
authentication, one connection and the 330-second bound. The exact paste
entered /bin/bash through stdin; no script or staging file was written on
the node. No configuration, package, clock or service change was requested.

## Outcome and collection gaps

SSH transport status was 0, collector status 2, SSH stderr empty. Full stdout
(25,389 bytes), stderr, transport status and parsed result remain owner-private
in the existing historical j1-svntp1 evidence directory as trixie-inspection.*
and trixie-inspection-result.json. No retry occurred. The executed bundle and
matching paste remain unchanged.

The collector's gap flag is retained, not waived:

- The selected package query returned 1 and reported no installed matches for
  raspberrypi-kernel, raspberrypi-bootloader, ntpsec, gpsd, gpsd-clients,
  pps-tools, i2c-tools, fancontrol, watchdog, webmin and munin-node. These are
  package-query observations, not proof that every corresponding executable
  or service is absent. No packages were installed.
- dhcpcd5, lm-sensors and systemd-resolved appeared with un status, not ii.
- nmcli --help returned 0 and wrote ordinary help text to stderr. The
  conservative collector treats any command stderr as a gap; this is not
  evidence that help failed. Its raw status/output is preserved.
- needrestart was omitted from the v1 package query. Its installation,
  version and effective restart/reporting policy on this Trixie node are
  unknown, not confirmed present or absent. The
  [governing baseline-app requirements](ntp-architecture-deployment-plan-v1.0.md#per-node-baseline-and-acceptance)
  already require it. Historical Debian 11 evidence does not establish the
  replacement image's needrestart state. Current source adds the package for
  future inspections; the executed v1 artifact remains unchanged.

Identity passed: non-root UID 1000, j2-svntp1, Debian 13 Trixie and aarch64;
kernel 6.18.50+rpt-rpi-v8. Boot ID was unchanged and no sampled file-content
hash drift was detected. This does not prove that all system files or runtime
state were unchanged. Collection completion is not platform/service acceptance.

## Configuration ownership and network facts

NetworkManager 1.52.1 is active and enabled from
/usr/lib/systemd/system/NetworkManager.service. systemd-networkd is loaded,
inactive and disabled. dhcpcd.service and systemd-resolved.service report
not-found. SSH is active/enabled; ntpsec.service and gpsd.service report
not-found. These are the queried unit names only.

Active Ethernet profile: Wired connection 1, UUID
`30c72d67-6d27-3d62-8d4d-6ef2e477815b`, type 802-3-ethernet, interface eth0,
autoconnect yes. IPv4 and IPv6 methods are auto. Explicit address/gateway/DNS
profile fields are empty; both ignore-auto-dns fields are no. This is the
observed bootstrap profile, not a fixed-network deployment.

- eth0 is connected at 10.1.0.137/22 with DHCP default gateway 10.1.0.1.
- IPv6 ULA, global and link-local addresses and an RA default route are present.
- Effective DNS shown by NetworkManager is 10.1.0.55 and
  fd36:5aa8:6971:1::55; IPv4 search domain is local.theama.co. No secondary
  DNS endpoint is shown in this snapshot; none was added or inferred.
- wlan0 is DOWN/unavailable and NetworkManager's Wi-Fi radio getter says
  disabled. rfkill nevertheless reports WLAN soft blocked no and hard blocked
  no. Retain both observations; permanent Wi-Fi disablement is unverified.
- Listener snapshot includes SSH and UDP/5353; no UDP/123 listener is shown.
  This is a bootstrap socket snapshot, not an NTP acceptance test.

## Package sources and passive hardware

Installed queried package versions include apt 3.0.3, Python 3.13.5-1,
NetworkManager 1.52.1-1+rpt4, systemd 257.13-1~deb13u1, OpenSSH server
1:10.0p1-7+deb13u4, linux-image-rpi-v8 1:6.18.50-1+rpt1, raspi-firmware
1:1.20260915-1, raspi-utils 20260626-1 and rpi-eeprom 28.33-1.

The empty /etc/apt/sources.list and two Deb822 source files were captured by
hash and safe projection. debian.sources shows deb.debian.org, suites trixie,
trixie-updates and trixie-security, components main/contrib/non-free/
non-free-firmware, and the Debian archive keyring path. raspi.sources shows
archive.raspberrypi.com, trixie/main and the Raspberry Pi archive keyring path.
Their URIs use HTTP. URI credentials/paths were excluded. No apt refresh,
repository reachability, signature verification, keyring-content inspection
or update-candidate query occurred; source trust/availability is not accepted.

Device-tree model is Raspberry Pi 4 Model B Rev 1.4. vcgencmd returned
throttled=0x0 and temperature 55.5 C. Passive hwmon names were cpu_thermal,
rpi_volt and pwmfan; no fan-input file was returned. The bounded serial/PPS/
RTC/I2C entry projection was empty. That does not prove absence beyond the
queried patterns or establish hardware failure. No hardware setup, scan,
stress test or control operation occurred.

Boot settings were projected without evaluating conditionals or following
includes. They do not establish an active UART/PPS/RTC or complete overlay
configuration. The existing operator report of normal fan/power behavior
remains separate from full hardware acceptance.

## Next gate

Define the next stage from these observed facts, with rollback and exact
inputs before execution approval. Network changes must target the observed
NetworkManager profile; package/boot changes must use this Trixie build's
installed tools and manuals. Account for the required needrestart package and
verify its effective non-disruptive restart/reporting policy before package
mutation; the omitted query is not permission to assume a safe policy.
Preserve the old Debian 11 card and primary
power/shared antenna path. Do not treat this inspection approval as permission
for apt updates, installations, reboots, fixed addresses, DNS policy, Wi-Fi
changes, or NTP/GPSD/hardware setup. No broad rerun is needed to erase the
package/help gaps.
