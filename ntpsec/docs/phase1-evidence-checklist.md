# Phase 1 evidence review: j1-svntp1

Repository-only review of `baseline-v2.tar`, read directly without extraction.
The archive is in `/home/aaron/code/.local-evidence/homelab-ntp/j1-svntp1/`.
Its collection finished `2026-09-16T22:14:49 UTC`; these are snapshot facts,
not current-state guarantees or accepted Trixie inventory.

The governing [Phase 1 scope](ntp-architecture-deployment-plan-v1.0.md)
remains unchanged. The [execution summary](baseline-j1-svntp1-20260916.md)
records original statuses. The executed v2 source, streams, manifests and
errors remain intact. No v3 execution or new node contact occurred in review.

## Observed, unknown and operator-confirmation checklist

Evidence names below are members beneath `output/` in the archive. Command
labels map to exact stream filenames through `commands.json`; configuration
paths map to captured bytes through `protected-before.json`.

| Area | Observed evidence | Unknown / remaining gate |
| --- | --- | --- |
| Identity and release | Hostname gate passed; Debian 11.11, aarch64; package list, kernel and boot-time streams captured | Source-build provenance and complete build options; Trixie release remains a future image decision/verification |
| Pi/RAM | Model B Rev 1.4, Pi revision c03114, 3885384 kB usable RAM in passive files | Physical board/card labels require operator match |
| Boot/root media | `media` stream: mmcblk0, 64021856256 bytes; vfat boot partition at `/boot`, ext4 root at `/`; identifiers in protected archive | Operator must label/preserve the original card and verify independent media-swap recovery; no imaging authorized |
| Firmware and boot | Firmware/bootloader queries and boot text files captured; power flags 0x0 | Source/overlay compatibility on Trixie and post-reboot persistence unverified |
| GPS/RTC | Running `/usr/local/sbin/gpsd`; sysfs identifies rv3028 RTC at I2C 1-0052 | Aaron physically identifies Uputronics GPS/RTC board rev 5.9 (2020), antenna attached to GPS HAT; connector type, GPS chipset and exact PPS wiring remain unverified; see hardware table |
| PPS/SHM | PPS sysfs observation; SHM unit 1/PPS selected, unit 0/GPS observed; local NTP peer/clock variables captured | Sustained pulses, fix quality and post-reboot behavior need later acceptance; SHM metadata alone does not establish every segment's role |
| PoE/fan | gpio_fan, rpi_poe, pwmfan and temperature evidence; fan snapshot 5000 RPM | Aaron physically identifies Raspberry Pi PoE HAT (2018), beneath GPS HAT; retained under plan v1.3; PoE+ replacement upon failure. Exact PCB revision and per-port allocation remain open; switch/port and reported class are recorded below |
| IPv4 ownership | dhcpcd active; eth0 static 10.1.0.51/22 and router 10.1.0.1 in captured config and observed address | Persistence and cross-repository allocation reconciliation still open |
| IPv6 ownership | Two global-scope IPv6 address lines; planned permanent `fd36:5aa8:6971:1::51/64` absent from captured address output | No claim of accepted static ULA; preserve RA/global behavior for later design; no address change authorized |
| DNS ownership | dhcpcd config specifies IPv4 DNS VIP; resolv.conf contains both DNS VIPs; resolver runtime includes eth0 RA metadata | DHCP/RA resistance not established; config still requests DNS-related DHCP options. Current resolver contents do not prove future update behavior |
| NTP/GPSD launcher | Both cgroups under timeservice.service; enabled active/exited oneshot unit, init script and drop-in captured | Future replacement unit/config needs approved Trixie design; do not treat masked ntpd.service as daemon absence |
| NTP build/config | Running NTPsec 1.2.1+82-g7abe7fba6; `/etc/ntp.conf`, init arguments, UID/GID/modes and hashes captured | Source revision/build provenance beyond reported version; no accepted config mirror generated |
| Peer health | IPv4 loopback: PPS selected, reach 377; system stratum 1, leap 00; offset/jitter in raw streams | Snapshot only; no observation interval or external client test |
| IPv6 listener/control | UDP 123 listeners observed; ntpq control query timed out; separately authorized single loopback time request returned valid NTPv4, stratum 1, leap 0 | LAN client reachability and effective control restrictions remain separate; no configuration change is needed to establish loopback time response |
| Leapfile | Config path `/var/lib/ntp/leap-seconds.list`; captured bytes/hash/mode; file and daemon report expiration 2027-06-28 | Authenticity, local-build reload behavior and historical manual download command/source/success/status still open; no ntpleapfetch run |
| Firewall/competing daemons | nft list returned empty output/status 0; iptables-save tools unavailable; timesyncd inactive; full processes/units captured | Do not equate missing tooling with proof of no legacy policy; no installation needed for this review |
| Webmin | No Webmin package entry and sampled standard settings/version paths absent | Aaron confirms not currently installed; planned Trixie installation and later login acceptance remain pending |
| needrestart | Package 3.5-4+deb11u5 and config captured; kernel/ucode hint suppression explicitly set | Aaron confirms manual installation; effective restart policy and notification path/delivery not accepted; no needrestart execution |
| msmtp | No msmtp/msmtp-mta package entries; sampled system/root config absent | Aaron corrects earlier answer: not currently installed; consistent with sampled non-discovery; planned relay/configuration and delivery acceptance remain pending |
| munin-node | No package entry; standard `/etc/munin` and default file absent | Aaron confirms not currently installed; planned fresh installation and approved poller/families still need acceptance; no polling authorized |
| watchdog | No package entry or sampled config/sysfs watchdog state | Aaron confirms watchdog application not currently installed; driver/ownership/recovery and controlled reset test remain pending |
| Configuration integrity | 420 paths and 148 regular-file hashes stable; only three resolver mtimes separated as runtime telemetry | Does not cover every file on host or prove causes of runtime changes |
| Recovery/access | SSH worked as ama; archive verified; Aaron confirms physical access, future card-swap ability, previously working micro-HDMI KVM/laptop, spare 128 GB card and reader | Physical media identification/labels and tested independent recovery remain pending; operator confirmations below are not a newly performed recovery test |

No package-list entry plus absent sampled paths is evidence of non-discovery,
not proof that a custom application does not exist. Operator confirmation can
resolve intentional absence without another general-purpose collection.

## Operator confirmations: recovery access

Aaron supplied these facts for **j1-svntp1 only** on `2026-09-16`:

| Item | Operator-confirmed fact |
| --- | --- |
| Hands-on operator | Aaron; can physically access the node |
| Future maintenance | Aaron can swap its SD card during a future maintenance window |
| Console equipment | Micro-HDMI KVM with laptop |
| Console history | This console has previously worked with this node |
| Spare media | SanDisk Max Endurance microSDXC, 128 GB |
| Reader | USB card reader available |
| Old-card retention | Current Debian 11 card can be kept untouched for rollback |

These are operator statements, not newly performed tests. The spare's physical
identity/label and correct write target must be verified at the later media
preparation gate. The original card must be matched to this node and labelled
when safe to do so; do not remove it now for identification. No new console,
media-swap, restore or reboot test has occurred. Recovery planning still needs
an explicit procedure and its separately authorized verification.

## Operator confirmations: hardware

Aaron supplied these facts for **j1-svntp1 only** on `2026-09-16` and
explicitly confirmed their source as **physical observation**:

| Item | Physically observed by operator |
| --- | --- |
| GPS/RTC board | Uputronics GPS/RTC Expansion Board for Raspberry Pi |
| GPS/RTC markings | Rev 5.9; date 2020 |
| PoE board | Raspberry Pi PoE HAT; date 2018; separate PCB revision not supplied |
| Stack, bottom to top | Raspberry Pi, PoE HAT, GPS HAT |
| Antenna attachment | GPS HAT; exact connector not supplied |
| Inter-board connection | 40-pin GPIO only; Aaron confirms no separate jumper wires |

The operator supplied the [Uputronics product reference](https://store.uputronics.com/products/raspberry-pi-gps-rtc-expansion-board).
Current product specifications do not establish this historical board's chipset
or revision-specific wiring. The header connection alone does not prove the
PPS pin assignment.

The governing plan v1.3 now retains this working **PoE HAT**. Aaron reports
that it is no longer available and selects **PoE+ HAT** replacement upon
failure. This resolves the plan discrepancy for j1-svntp1, without establishing
j1-svntp's hardware model or Trixie compatibility. A printed year is not an
exact PCB revision.
Switch/port and reported PoE class are recorded below; exact per-port power
allocation remains unknown. No disassembly,
rewiring, powered-stack removal or live verification is requested here.

## Operator confirmations: shared antenna and applications

On `2026-09-16`, Aaron reported one GPS Source `L1G1A-STD` antenna shared by
**both NTP nodes** through a Uputronics two-output GPS antenna signal splitter
with SMA connections. Aaron subsequently confirmed by visual inspection that
**j1-svntp supplies antenna power** through its GPS board. Aaron corrected
the original three-output description to two outputs, one for each NTP node;
there is no unused third receiver output to document.
This refines the earlier GPS-HAT antenna attachment statement: the receivers
connect through the shared splitter, not to separate antennas.

The [manufacturer's splitter description](https://store.uputronics.com/products/gps-antenna-signal-splitter-with-sma)
states that one receiver connection passes DC to the antenna and the others
block DC. This is product documentation, not verification of the installed
unit's markings or connections. The powering node and two-receiver topology
are now operator-confirmed. Exact printed port labels have not been transcribed;
no connection change or further unused-port question is needed for this correction.

The antenna and splitter are shared GPS failure dependencies. If the node
supplying antenna power is shut down, both receivers could lose GPS reception;
continued NTP service from upstreams or holdover is not proven by this topology.
The independent-server design does not establish independent GPS reception.
For the planned first rebuild of j1-svntp1, preserve the running j1-svntp and
its antenna-power path. Before the later j1-svntp outage, define and approve
how antenna power and the surviving node's time service will be maintained
and verified. Visual inspection is not a power-loss or failover test.
Plan v1.3 incorporates this dependency and requires antenna-power continuity
before j1-svntp's outage. No shutdown, cable disconnection or power-loss test is authorized.

Application answers are recorded for **j1-svntp1**, the node under review:

| Application | Operator report | Evidence reconciliation |
| --- | --- | --- |
| Webmin | Not currently installed | Consistent with sampled non-discovery |
| msmtp | Not currently installed (operator correction) | Consistent with package and sampled system/root configuration non-discovery |
| munin-node | Not currently installed | Consistent with sampled non-discovery |
| watchdog | Not currently installed | Consistent with sampled application non-discovery; no claim that kernel watchdog facilities are absent |
| needrestart | Manually installed | Package and configuration already captured; behavior and notification acceptance remain open |

Aaron corrected the initial msmtp answer to **not currently installed**.
This resolves the apparent mismatch with the snapshot without further host
inspection. Future Trixie application requirements remain unchanged.

## Authorized UniFi switch/port lookup

At Aaron's request, read-only controller GET queries on `2026-09-16`
correlated the captured eth0 MAC with the UniFi client, its upstream switch
MAC and port index. TLS hostname and chain verification passed using the
[network-owned access procedure](../../../homelab-network/Ubiquiti/UNIFI_ACCESS.md).
The final port snapshot was taken at `22:57:48 UTC`.

| Field | Controller observation |
| --- | --- |
| Switch | P-D1-SW8LPOE; USW Lite 8 PoE (legacy model code USL8LP) |
| Port | 3; label `J1-SVNTP1:1` |
| Link | Up, 1000 Mbps, full duplex |
| PoE | Enabled, auto mode, good status; reported Class 3 |
| Measured draw | 2.88 W; 53.33 V; 54.00 mA at the snapshot |
| Switch-wide maximum | API `total_max_power`: 52; not a per-port allocation |
| Per-port allocation | Not exposed in selected port fields; unknown |

The integration API identified the switch but omitted the client port mapping;
the legacy read-only status API supplied that mapping and port telemetry.
Port capability does not establish the attached HAT model or negotiated IEEE
type. Plan v1.3 resolves the PoE versus PoE+ designation for j1-svntp1;
these measurements do not establish sustained power margin.

One bounded sanitized file, `unifi-port.json`, was retained with mode `0600`
in the existing host evidence directory. Credentials remained in process
memory. No new evidence directory, NTP-node access or controller configuration
change occurred. This lookup does not constitute the broader UniFi policy audit.

## IPv6 timeout assessment

The captured init script starts the custom ntpd without an alternate `-c`
configuration argument. `/etc/ntp.conf` has default IPv6 `noquery` and an IPv4
loopback exception, but no `::1` exception. Together with the successful IPv4
query, this is consistent with the IPv6 ntpq control timeout. It is an inference
from the configured policy, not a live readback of effective restrictions.

NTP control queries and ordinary client time requests are different protocol
modes. Removing `noquery` or adding a rule is unnecessary for this diagnostic
and is not authorized. A loopback time response would answer the remaining
local-service question without relaxing management access. It would not prove
LAN client reachability, firewall policy, permanent IPv6 addressing or rebuild
acceptance.

## Corrected collector validation

Unexecuted collector schema v3 preserves raw stdout, stderr and process exit
status, and adds `response_error`. Empty responses, diagnostic stderr and
recognized ntpq errors block success even when the process exits zero.
Association `rv` replies must match the requested ID and contain exactly one
numeric source address. Only the reserved reference-clock pseudo-address range
`127.127.0.0/16` permits a `cv` query; a remote peer's `refid=PPS` does not.
Missing/ambiguous identity remains an error and suppresses the clock query.

Offline replay against v2 detected all seven zero-exit response errors and
classified two refclocks versus six network peers. No recorded result was
rewritten. Missing firewall-tool errors remain errors. A full v3 collection is
not proposed merely to obtain a cleaner report.

## Completed IPv6 loopback diagnostic

The user authorized the hash-bound probe. At `2026-09-16T22:31:01 UTC`, one
request to `[::1]:123` returned a verified NTPv4 server response, stratum `1`,
leap `0`. Both SSH and probe statuses were `0`. Source hash was verified
locally and in remote memory; the returned packet was revalidated locally
against its request. No retry, sudo, remote file creation, clock adjustment,
configuration change, cleanup or other-node access occurred.

Executed SHA-256:
`1802267547ed5cadc865da86eb95d5da6ff90ad39825f0e0abdfeafc29b12573`.

Only the three specified `ipv6-time-v1.*` files were created in the existing
host evidence directory, all operator-owned with mode `0600`. The status
record contains exact executed source/hash, SSH command, separate statuses,
response and stdout/stderr hashes. No new local directory was created.

This resolves the ordinary IPv6 loopback response question at that instant.
It supports distinguishing the earlier control-query timeout from time
service, but does not prove LAN reachability, persistence or the exact cause
of the control timeout. Full baseline acceptance remains open. Do not repeat
this completed probe or relax restrictions just to obtain successful ntpq
output.

## Executed diagnostic scope (historical)

Artifact: [inspect-ipv6-time.sh](../scripts/inspect-ipv6-time.sh). Its final
SHA-256 is recorded above. **Executed once; authorization consumed.**

- Target: SSH `ama@10.1.0.51`, numeric address, existing trusted host key,
  strict checking, no DNS lookup or connection multiplexing.
- Privilege: ordinary `ama`; no sudo. Requires Bash and `/usr/bin/python3`.
- Verify source hash locally and again in remote memory before execution.
  Execute from `/` as `/bin/bash -s -- --probe`, feeding only the verified
  script bytes on stdin. No script installation or remote evidence files.
- Gate on kernel hostname `j1-svntp1` and observed Debian 11 release.
- Send exactly one 48-byte NTP mode-3 request to `[::1]:123`; wait at most
  five seconds for a response, with no retry. Never set or estimate system time.
- Validate response length, version, server mode, matching originate timestamp,
  synchronized leap/stratum and nonzero receive/transmit timestamps. Retain
  received packet hex and rejection reason; a valid reply is only local IPv6
  time-service evidence.
- Output: one JSON record on stdout, startup diagnostics on stderr. Exit `0`
  means verified reply, `2` unresolved transport/timeout, `3` invalid or
  unsynchronized reply, `64` preflight rejection. Shell/SSH failures retain
  their native status. Record probe and SSH statuses separately.
- Reuse the existing local host evidence directory. Exclusively create only
  `ipv6-time-v1.stdout`, `ipv6-time-v1.stderr`, `ipv6-time-v1.status.json` with
  mode `0600`; validate existing directory ownership/mode and reject symlinks.
  The status record retains exact executed source/hash, transport command and
  statuses, avoiding a separate script copy or directory. Retain failed output.
- No external NTP, DNS/controller access, package installation, configuration
  capture, service change, clock adjustment, reboot, cleanup or second node.
  No rollback is needed because no persistent remote mutation is permitted.

The antenna topology and installed j1-svntp1 PoE HAT are reconciled in plan
v1.3. The [candidate/recovery plan](trixie-candidate-recovery-plan.md) now
defines repository candidates, unknown target inputs and recovery gates.
Next, define its bounded image/media and bootstrap specification.
Do not repeat recorded operator questions. Actual media identification,
recovery verification and any remaining live inspection need separate scopes.
The later j1-svntp outage requires the plan's antenna-power continuity gate;
no alternative power arrangement has yet been selected or tested. Baseline
acceptance remains open.
