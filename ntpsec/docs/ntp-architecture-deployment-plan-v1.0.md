# Dual-stack NTP architecture and deployment

Plan version: `1.2` (stable filename retained for existing links).
For current status, operation history, and the next gate, see
[NTPsec history](../HISTORY.md).

## Purpose

This document governs the one-node-at-a-time clean rebuild of the two Raspberry
Pi NTPsec servers from Debian 11 to Raspberry Pi OS Lite (64-bit), Trixie
(Debian 13-based), on the Default LAN. The existing dual-stack and
network-policy work follows the rebuild. This plan records design decisions,
action boundaries, validation, rollback, and evidence requirements. Change it
for approved architecture decisions or deviations. Record operation outcomes
and the exact resume point in `ntpsec/HISTORY.md`.

The project covers:

- Trixie boot-media preparation, baseline applications, hardware bring-up,
  one-node acceptance, and recovery to Debian 11.
- A Munin endpoint on each NTP node, governed by the Munin component repo.
- Four-week leapfile maintenance with `ntpleapfetch` and systemd.
- Static dual-stack host networking and DHCP-resistant DNS settings.
- Exact mirrors and audits of each live `/etc/ntp.conf`.
- Local-zone A, AAAA, SRV, and PTR records.
- UniFi DHCP, IPv4 and IPv6 firewall policy, and active/standby DNAT.
- NTP host and service inventory.

## Architecture

### Network

| Item | Value |
| --- | --- |
| UniFi network | `Default LAN` on VLAN 1 |
| IPv4 subnet | `10.1.0.0/22` |
| IPv6 ULA subnet | `fd36:5aa8:6971:1::/64` |
| IPv4 gateway | `10.1.0.1` |
| IPv4 DNS VIP | `10.1.0.55` |
| IPv6 DNS VIP | `fd36:5aa8:6971:1::55` |
| DHCP NTP servers | `10.1.0.50`, `10.1.0.51` |

UniFi DHCP Option 42 supplies both IPv4 NTP servers. UniFi blocks outbound UDP
123 from other Default LAN clients and redirects hard-coded external NTP
destinations to the active local DNAT target.

### Servers

| Property | `j1-svntp` | `j1-svntp1` |
| --- | --- | --- |
| Service name | `ntp.local.theama.co` | `ntp1.local.theama.co` |
| IPv4 | `10.1.0.50/22` | `10.1.0.51/22` |
| Permanent ULA | `fd36:5aa8:6971:1::50/64` | `fd36:5aa8:6971:1::51/64` |
| Platform | Raspberry Pi 4B, 8 GB | Raspberry Pi 4B, 4 GB |
| GPS | Uputronics GPS/RTC expansion board | Uputronics GPS/RTC expansion board |
| Power | Raspberry Pi PoE+ HAT | Raspberry Pi PoE+ HAT |
| Reported current OS | Debian 11 | Debian 11 |
| Target OS | Raspberry Pi OS Lite (64-bit), Trixie | Raspberry Pi OS Lite (64-bit), Trixie |
| Reported current NTPsec | `1.2.1+82-g7abe7fba6` | `1.2.1+82-g7abe7fba6` |
| Target NTPsec | Record installed Trixie build; do not pin the old build | Record installed Trixie build; do not pin the old build |
| Rollout order | Second | First |

Both nodes act as independent authoritative time sources. The project will not
add Keepalived, VRRP, or another NTP HA layer.

## Locked decisions

### Addressing

- `j1-svntp` uses `fd36:5aa8:6971:1::50/64`.
- `j1-svntp1` uses `fd36:5aa8:6971:1::51/64`.
- Both nodes use `10.1.0.55` and `fd36:5aa8:6971:1::55` for DNS.
- Host profiles reject DNS values learned through DHCP or Router
  Advertisement.
- Host profiles retain router-advertised global IPv6 addresses and the IPv6
  default route.

### DNS service discovery

Publish equal-priority and equal-weight records:

```dns
_ntp._udp.local.theama.co. 180 IN SRV 0 50 123 ntp.local.theama.co.
_ntp._udp.local.theama.co. 180 IN SRV 0 50 123 ntp1.local.theama.co.
```

Each SRV target must have matching A and AAAA records. Each physical address
must have one canonical PTR that points to its service name.

### DNAT

Maintain four DNAT rules:

| Family | Target | State |
| --- | --- | --- |
| IPv4 | `10.1.0.50` | Active |
| IPv4 | `10.1.0.51` | Disabled standby |
| IPv6 | `fd36:5aa8:6971:1::50` | Active |
| IPv6 | `fd36:5aa8:6971:1::51` | Disabled standby |

Do not enable both rules in one family. The project uses a manual DNAT
failover runbook and does not add NTP HA.

### Leapfile maintenance

Both nodes have working Internet access and can run the current
`ntpleapfetch` command. Preserve that egress behavior. Add a schedule through a
oneshot service and timer:

```ini
OnBootSec=15min
OnUnitActiveSec=4w
RandomizedDelaySec=30min
```

The initial live audit must confirm the executable path, options, source URL,
leapfile path, owner, group, mode, retry behavior, and installed NTPsec reload
behavior. Do not add an `ntpd` restart without evidence that this build needs
one.

## Repository ownership

| Information | Source of truth |
| --- | --- |
| NTPsec and client configuration | `homelab-ntp` |
| This governing plan | `homelab-ntp/ntpsec/docs` |
| Host membership, functions, components, and OS facts | `homelab-server-configs/inventory` |
| A, AAAA, PTR, and SRV records | `homelab-dns` |
| Addresses, DHCP, firewall policy, and DNAT | `homelab-network` |
| Munin endpoint configuration and plugins | `homelab-monitoring-observability/Munin` |
| Architecture diagrams | `homelab-docs` |
| Secrets and private keys | Approved secrets manager |

## Planned repository layout

```text
ntpsec/
├── HISTORY.md
├── configs/
│   ├── j1-svntp/
│   │   └── ntp.conf
│   └── j1-svntp1/
│       └── ntp.conf
├── docs/
│   ├── ntp-architecture-deployment-plan-v1.0.md
│   └── dual-node-deployment-runbook.md
├── scripts/
│   ├── inspect-node.sh
│   ├── install-node-config.sh
│   └── validate-node.sh
├── templates/
│   ├── ntpleapfetch.service
│   └── ntpleapfetch.timer
└── tests/
    └── run.sh
```

Create deployable files after the read-only captures establish their exact
paths and contracts. Do not create guessed `ntp.conf` files or systemd units.

## Change-control model

Repository changes and local validation do not require live authorization. A
scoped approval may cover one complete read-only collection on one target. A
persistent deployment approval may cover one node or controller stage from
preflight through mutation, convergence, acceptance, and rollback. Approve
each node or controller stage on its own exact deployment-bundle hash.

### Gate requirements

Each persistent live action must define:

- Scope and host or controller target.
- Exact SHA-256 deployment bundle containing the operation specification and
  every non-secret execution input, including privileged scripts.
- Preconditions and expected observations.
- Commands and permitted side effects.
- Evidence paths and sensitive-output handling.
- Success and rejection conditions.
- Cleanup and rollback.
- The next action that remains unauthorized.

Execution consumes the approved bundle. An edit or scope change requires a new
hash and authorization. After an interrupted or failed mutation, inspect live
state before proposing a retry. Unexecuted repository files use the normal
edit and review workflow.

### Evidence rules

- Capture SSH stdout and stderr in separate protected local files.
- Record command and SSH status without collapsing them into one value.
- Give fail-closed acceptance conditions distinct labels.
- Retain ordinary diagnostic output. Redact secrets and protect output that may
  contain credentials or private material.
- Compare pre-state and post-state hashes for read-only actions.
- Inspect cleanup and persistent state after an interrupted action.

## Trixie rebuild contract

This is a **clean install**, not an in-place Debian 11-to-13 upgrade. Each node
must have its own approved image, boot media, configuration bundle, preflight,
acceptance record, and recovery path. Rebuild `j1-svntp1` first. Do not begin
`j1-svntp` until the rebuilt standby has served real IPv4 and IPv6 clients,
selected GPS/PPS, survived a reboot, and completed the agreed observation
interval while `j1-svntp` remains available.

### Locked media choice and pre-imaging checks

- Use **Raspberry Pi OS Lite (64-bit), Trixie** in Raspberry Pi Imager for the
  Raspberry Pi 4B. This is the Raspberry Pi-supported headless image based on
  Debian 13, **not pure Debian 13**. Record Imager version, exact image
  release/build, architecture, and the write verification result. Verify a
  published image digest when a separately downloaded image is used.
- Use spare SD cards for both nodes. Label and retain each working Debian 11
  card unmodified for a physical media-swap rollback; record the old and new
  cards' capacities and identities before writing either new card.
- Confirm console or hands-on access, maintenance window, acceptable client
  impact, and a named operator for power, media, and PoE recovery.
- Identify exact GPS/RTC board revision, antenna and PPS wiring, PoE+ HAT
  revision, physical stack order, and the network switch port for each node.
  Board revision controls the RTC chip, UART settings, and boot overlay choice.

### Per-node baseline and acceptance

For **each** Trixie node, install only from approved Raspberry Pi OS/Debian
repositories and an explicitly approved Webmin repository. Record package
origin and installed version. Configure and validate:

| Area | Required evidence before accepting the node |
| --- | --- |
| Base OS and access | Raspberry Pi OS Lite Trixie release and arm64 architecture; boot firmware and kernel; correct hostname, SSH access, package sources, updates, users and administrative access; persistent boot and root filesystems |
| Network and DNS | Stable node IPv4 and ULA, retained Router Advertisement global IPv6 and default route, both DNS VIPs with DHCP/RA DNS replacement disabled; dual-stack reachability and reboot persistence |
| `webmin` | Package provenance, service health, authenticated management access from an approved LAN path, intended bind/firewall scope, and no unintended External exposure; restore required settings from observed Debian 11 state only after review |
| `needrestart` | Trixie package, non-disruptive reporting policy, actual kernel/service report, and notification through the accepted mail path; do not allow an unattended restart of `ntpsec` during acceptance |
| `msmtp` | `msmtp` plus a sendmail-compatible transport if required by the notification workflow; protected relay configuration, successful test delivery through Mailrise, and no committed credentials |
| `munin-node` endpoint | Installed package and enabled service; observed listener and client allowlist; collection from the approved Munin poller over each intended address family; usable host metrics and no unintended External exposure. The Munin component owns endpoint configuration and plugin choices |
| `watchdog` | Observed `/dev/watchdog` owner/driver and service configuration, reboot behavior and recovery path; enable only after the node can be recovered independently and a controlled acceptance test is approved |
| GPS/RTC HAT | Verified board revision, antenna/fix, UART device and baud, I2C RTC identity and sane time, PPS GPIO and `/dev/pps*` pulses, `gpsd` feed and permissions, and persistence after reboot; choose boot overlays for the selected image and observed hardware |
| PoE+ HAT | Correct switch PoE class and power budget, boot and sustained power without undervoltage, fan detection/control and thermal behavior, and no GPIO/I2C conflict with the GPS/RTC HAT |
| `ntpsec` | Installed Trixie package/build and actual config path, GPS/PPS and sanity-source selection, leapfile and four-week timer, no competing time daemon, IPv4/IPv6 UDP 123 listeners and client responses, NTS/IPv4/IPv6 upstream behavior as configured |

Use the existing NTPsec/GPSD arrangement as input evidence, not as an
installable Trixie artifact. Keep byte-exact Debian 11 `/etc/ntp.conf`
captures for audit. Derive a separate Trixie configuration from the installed
package's unit, config path, default files, man pages, user/group, device
names, and live hardware; validate it on `j1-svntp1` before reusing the design
on `j1-svntp`. Do not copy old boot overlays, `/etc/ntp.conf`, GPSD unit
assumptions, Webmin settings, or network-manager profiles blindly.

The Uputronics datasheet describes GPS UART, PPS, I2C RTC, and different
settings by board revision. Its Raspberry Pi OS examples are reference inputs,
not proof of a Trixie boot configuration. The older NTPsec microserver
HOWTO is likewise a conceptual reference, not a Trixie installation script.
The Raspberry Pi PoE+ HAT includes I2C-controlled fan hardware; prove fan and
power operation on the selected image rather than assuming that a successful
boot proves full HAT support.

### Inventory contract

Draft `homelab-server-configs/inventory/prod` entries after read-only capture
and finalize each host's accepted facts after its rebuild. Add an `ntp` group,
host membership, `ntp` function, and components for the installed NTP,
hardware-interface, Munin endpoint, and baseline app bundles. Reuse
`groups/all.yaml` common `needrestart`/`watchdog` policy and notification
defaults where applicable;
record only NTP-specific or host-specific differences in the new files.

Both host files must have observed, non-secret specifications: exact Pi model
and revision, CPU architecture/cores, installed RAM, boot/root storage type,
capacity and filesystem, boot firmware/kernel and Raspberry Pi OS release,
GPS/RTC HAT manufacturer/model/PCB revision/chipset and connection roles,
PoE+ HAT model
and IEEE class/power characteristics, physical switch-port reference where
inventory convention permits it, and permanent-management ULA with
`address_authority: homelab-network`. Record service role (independent NTP
node), no virtual-IP ownership, and the current manual DNAT target/standby
role as service metadata, not as HA ownership. Include package/component
versions only where the inventory's version policy calls for actual installed
facts; never guess from a candidate package list. If a detail cannot be
observed, mark it unverified and leave inventory acceptance open rather than
inventing a value. IP allocation, DNS zones, credentials, raw controller
exports, and volatile performance measurements remain outside inventory.

## Work plan

### Phase 0: repository foundation

1. Replace the generic `AGENTS.md` with NTP-specific repository and live-action
   rules.
2. Create this governing plan under `ntpsec/docs`.
3. Link the governing plan and architecture summary from the repository
   `README.md`.
4. Run Markdown, whitespace, secret, and pre-commit validation.
5. Record validation, artifact hashes, operation outcomes, and the exact
   resume point in `ntpsec/HISTORY.md`.

Phase 0 makes no live-system or controller contact.

### Phase 1: define and execute read-only baselines

Create a fail-closed collector, then run it against `j1-svntp1` before
`j1-svntp`. Capture:

- Host identity, Debian release, boot time, and package/build provenance.
- Pi model/revision, RAM, boot/root media capacity and filesystem, bootloader,
  kernel, boot configuration, board/HAT revisions, antenna, HAT stack, PoE
  switch port and power class, and available console/recovery access.
- Active network manager, interface, connection profile, addresses, routes,
  DNS sources, and `/etc/resolv.conf` ownership.
- `/etc/ntp.conf`, defaults, drop-ins, startup options, ownership, modes, and
  SHA-256 values.
- NTPsec unit type, state, PID, restart count, listeners, and recent journal.
- GPSD state, serial device, PPS device, SHM units, and refclock observations.
- `ntpq` peers, reach, selection, stratum, leap state, offset, and jitter.
- Leapfile path, validity, expiration, ownership, mode, and hash.
- Current `ntpleapfetch` command, source URL, manual success, and exit status.
- Competing time daemons, local firewall state, and UDP 123 ownership.
- Webmin package/source and settings, needrestart behavior, msmtp relay,
  `munin-node` package/service, listener, client allowlist, and current plugin
  set, watchdog driver/configuration, notification path, and enabled services.
- Existing boot-media identity and a verified way to restore that node without
  depending on the other node's rebuild.

Create a separate read-only UniFi audit for DHCP Option 42, address objects,
zone membership, firewall rule order, IP-family selectors, counters, and all
four planned DNAT rules. Export or capture enough state for exact rollback.

Acceptance requires complete evidence with no mutation and identical pre-state
and post-state hashes for protected host artifacts.

### Phase 2: prepare image, preserve rollback, and build candidates

1. Select Raspberry Pi 4B and Raspberry Pi OS Lite (64-bit), Trixie in
   Raspberry Pi Imager. Record Imager version, exact image release/build,
   verified write result, and boot-media ID. This is Raspberry Pi OS based on
   Debian 13, not pure Debian.
2. Keep each current Debian 11 SD card untouched and labelled by host. Prepare
   separate replacement cards; verify each card's identity before Raspberry Pi
   Imager writes it. Maintain a protected, tested backup of node-specific
   configuration and a known-working media-swap procedure.
3. Mirror each live `/etc/ntp.conf` byte for byte for audit. Review GPS, PPS,
   upstream sources, NTS, restrictions, interfaces, IPv6, driftfile,
   statistics, and leapfile directives. Produce a separate Trixie candidate
   against observed installed package paths and units.
4. Define node baseline configuration and validation for Webmin, needrestart,
   msmtp/sendmail, the Munin endpoint, watchdog, GPS/RTC/PPS, PoE+ power and
   fan, GPSD, NTPsec, dual-stack networking, and the four-week
   `ntpleapfetch` timer. Reuse established `homelab-server-configs` baseline
   app artifacts only after checking them against Trixie and the node's actual
   package versions. Define the NTP Munin endpoint in its governing component
   after confirming the approved poller and plugin set. The existing
   Caddy-specific Munin files are deferred Caddy deployment work, not an
   accepted endpoint or an NTP configuration template.
5. Create node inspection, installation, recovery, and acceptance scripts or
   runbooks with host-specific inputs. Test success and rejection paths for
   parsers, fail-closed validators, and mutation scripts; give simple
   collectors a focused dry run or self-test.
6. Draft the NTP inventory group and host entries from captured facts, clearly
   marking any unverified hardware detail. Do not declare the entries complete
   until each rebuilt node has confirmed its final OS, media, and HAT facts.
7. Validate shell, systemd, Markdown, YAML, secret scanning, and the relevant
   repository suites. Verify units and application settings again on the
   selected Trixie image before installation.

Repository tests provide artifact evidence, not evidence that the replacement
card boots or that its GPS, PPS, fan, mail, and NTP paths work.

### Phase 3: rebuild and accept `j1-svntp1`

1. Confirm `j1-svntp` serves clients and the reported active IPv4 DNAT target
   remains reachable. Capture a pre-rebuild client and NTP health baseline;
   identify clients that use only `j1-svntp1` and their retry/failover behavior.
   One healthy node does not guarantee zero client impact.
2. Under the approved maintenance window, power down only `j1-svntp1` and
   preserve its labelled Debian 11 SD card. Insert its verified Trixie card;
   do not reuse `j1-svntp` media or identity.
3. Boot with console access available. Confirm image, release, architecture,
   hostname, unique host identity, package sources, kernel, boot firmware,
   storage, switch link, PoE power, fan, and no undervoltage or thermal faults.
   Complete security updates and any required reboot while the primary serves.
4. Check `fd36:5aa8:6971:1::51` for ownership/DAD conflicts. Configure
   `10.1.0.51/22`, gateway `10.1.0.1`, permanent ULA, retained RA global IPv6
   and default route, and the two DNS VIPs without DHCP/RA DNS replacement.
   Validate addresses, source selection, routes, DNS, egress and reboot
   persistence before service cutover.
5. Install and validate the baseline apps, then bring up GPS UART, RTC, PPS,
   GPSD, and NTPsec with the Trixie candidate configuration. Activate the
   leapfile timer after verifying its command and path. Do not enable watchdog
   resets until recovery is proven.
6. Query `j1-svntp1` directly from controlled clients over IPv4 and IPv6;
   confirm GPS/PPS selection, upstream reachability, leap state, Webmin
   management scope, approved Munin polling, delivered mail, needrestart
   reporting, PoE fan/thermal behavior, and a second successful boot. After
   recovery is proven, enable watchdog and run its separately approved
   controlled acceptance test. Record package and hardware facts.
7. Only if the rebuilt node passes all gates, observe it for an agreed interval
   and finish its inventory record. Keep the existing primary DNAT active; do
   not switch DNAT merely to prove the standby rebuild.

If boot, network, GPS/PPS, or client acceptance fails, remove the new card and
reinstall that node's preserved Debian 11 card. Validate the old node's NTP
health and client responses. A media swap is the recovery action; copying the
old network profile or NTP config onto the new image is not a rollback.

### Phase 4: rebuild and accept `j1-svntp`

Repeat the Phase 3 controls with `10.1.0.50` and
`fd36:5aa8:6971:1::50`. First prove that rebuilt `j1-svntp1` serves clients
independently. For each family with an existing active `j1-svntp` DNAT rule,
disable that rule and promote the matching `j1-svntp1` standby rule under a
separately approved UniFi action before taking the primary down; verify one
active rule per affected family and client traffic through the standby. If
the current UniFi rules do not support this exact transition, stop and revise
the controller runbook before the primary outage. The planned Phase 6 final
policy is **not** a prerequisite for this interim, separately audited primary
rebuild transition. If no standby DNAT exists and one cannot be prepared, get
an explicit decision on hard-coded-client outage before taking the primary
down. After primary acceptance, restore primary-target rules one family at a
time and verify client traffic.

Preserve the primary's Debian 11 card. Re-run all hardware, package, network,
GPS/PPS, power, fan, NTP, mail, watchdog, and reboot checks on the primary;
standby success does not prove primary hardware or boot behavior. If the
primary rebuild fails, restore its old card while keeping standby DNAT active,
then validate old primary service before restoring primary DNAT. Never take
both nodes down in the same maintenance action.

### Phase 5: deploy local-zone DNS records

Add and audit:

```dns
ntp.local.theama.co. IN A 10.1.0.50
ntp.local.theama.co. IN AAAA fd36:5aa8:6971:1::50
ntp1.local.theama.co. IN A 10.1.0.51
ntp1.local.theama.co. IN AAAA fd36:5aa8:6971:1::51
_ntp._udp.local.theama.co. 180 IN SRV 0 50 123 ntp.local.theama.co.
_ntp._udp.local.theama.co. 180 IN SRV 0 50 123 ntp1.local.theama.co.
```

Retain the existing IPv4 PTR records and add:

```dns
fd36:5aa8:6971:1::50 PTR ntp.local.theama.co.
fd36:5aa8:6971:1::51 PTR ntp1.local.theama.co.
```

Reject duplicates and incomplete forward/reverse pairs. Validate the candidate
with the target `unbound-checkconf`. Install and query the standby DNS node,
exercise DNS failover, then install the primary DNS node. Query A, AAAA, SRV,
IPv4 PTR, and IPv6 PTR from both nodes and both DNS VIPs.

### Phase 6: audit and enforce UniFi policy

1. Reconcile DHCP Option 42 with `10.1.0.50` and `10.1.0.51`.
2. Place NTP-server allow policy above the Default LAN deny policy.
3. Allow both NTP devices to External over IPv4 and IPv6 UDP 123 and TCP 4460.
4. Deny other Default LAN clients access to External UDP 123 over both
   families.
5. Preserve the working `ntpleapfetch` download path.
6. Reconcile active and disabled standby DNAT rules with the locked table.
7. Validate rule counters, connection state, return traffic, and unrelated
   traffic.

For IPv6 External traffic, match a verified device object or the source address
observed on the wire. A rule that matches only the ULA may miss packets sourced
from the router-advertised global address.

Test DNAT from a controlled VLAN 1 client with a hard-coded external
destination. Pair the client observation with UniFi counters and a capture on
the selected NTP node. Test standby promotion and restoration for one family
at a time. Leave the primary target active after acceptance.

### Phase 7: add inventory

In `homelab-server-configs/inventory/prod`:

1. Add group `ntp` and `groups/ntp.yaml`.
2. Record function `ntp` and the installed NTP, GPSD/PPS, Webmin,
   `munin-node`, needrestart, msmtp, and watchdog components. Do not duplicate
   the existing all-host needrestart/watchdog policy unless a node needs an
   override.
3. Add host keys `j1-svntp` and `j1-svntp1` with their management FQDNs.
4. Add host files that satisfy the complete observed hardware, storage, OS,
   HAT, address-authority, and no-HA inventory contract above. Preserve the
   exact per-host differences; do not fill missing fields with assumptions.
5. Keep IP allocation and authoritative DNS records out of inventory.
6. Run strict YAML and inventory repository validation. Compare each final
   host record with accepted live readback before marking it complete.

### Phase 8: end-to-end acceptance

Acceptance requires:

- Both nodes boot the selected Trixie arm64 image from separately
  identified replacement media, and their labelled Debian 11 cards remain
  available for recovery through the agreed retention period.
- Webmin, needrestart, msmtp, `munin-node`, watchdog, GPS/RTC, PPS, GPSD,
  NTPsec, and PoE+ HAT checks in the per-node acceptance table pass on each
  host.
- Both hosts retain their static IPv4 and permanent ULA after reboot.
- Both hosts retain global IPv6 and a Router Advertisement default route.
- Each resolver view contains only the two DNS VIPs for its address family.
- DHCP and Router Advertisement updates do not replace host DNS settings.
- GPS, PPS, and external sanity sources report the accepted selection and
  reach state on both nodes.
- NTP clients receive time over each node's IPv4 and IPv6 address.
- Each leapfile validates, and each timer reports a four-week next trigger.
- Both DNS nodes and both DNS VIPs return the agreed A, AAAA, PTR, and SRV data.
- Both NTP nodes reach approved IPv4 and IPv6 upstreams over UDP 123 and TCP
  4460.
- Other Default LAN clients cannot send UDP 123 to the External zone.
- Active IPv4 and IPv6 DNAT reach `j1-svntp`; the disabled standby rules can be
  promoted one family at a time to `j1-svntp1` and restored.
- Inventory names, functions, components, hardware, and OS facts match live
  observations, including exact Pi and HAT revisions and boot/root media.
- Each repository passes its focused tests, full baseline, secret scan, and
  whitespace checks.

Run an observation interval after the last change. Review offsets, jitter,
reach, leap state, systemd failures, DNS errors, and UniFi counters before
declaring acceptance.

## Rollback policy

- Roll back one node or one controller policy surface at a time.
- Keep the other NTP node serving throughout host rollback.
- For a failed Trixie rebuild, restore only that host's preserved Debian 11
  SD card and verify boot and NTP client service. Do not overwrite the old
  card. After Trixie acceptance, restore individual files or network
  profiles by accepted path and hash only for later configuration changes.
- Restore DNS on the node changed last, validate it, then decide whether the
  other DNS node needs rollback.
- Disable the promoted standby DNAT rule before restoring the primary rule for
  that family. Verify that one rule remains enabled.
- Restore UniFi objects and rule order from the pre-change export.
- After rollback, run a new read-only acceptance action. A successful rollback
  command does not prove restored service.

## Risks and controls

| Risk | Control |
| --- | --- |
| SSH loss during profile activation | Use console or an access path that tolerates interruption; verify a rollback profile before activation |
| Duplicate ULA | Check neighbor ownership and Duplicate Address Detection before acceptance |
| Loss of global IPv6 | Keep `ipv6.method auto`, Router Advertisement routes, and source-selection checks |
| DHCP replaces host DNS | Set and validate automatic-DNS ignore flags for both families |
| NTPsec accepts config but loses PPS | Check refclock variables, peer selection, reach, and journal after deployment |
| Leapfile timer disrupts service | Confirm installed reload behavior and omit restart unless required |
| Firewall allow does not match IPv6 source | Match a verified device object or observed global source and inspect counters |
| Both DNAT rules become active | Validate enabled-state cardinality before and after each controller action |
| DNS records precede listeners | Deploy records after both nodes serve NTP on their permanent addresses |
| Repository validation overstates live acceptance | Require target-node and client evidence for each runtime claim |
| New image boots but misses RTC/PPS or fan drivers | Prove UART, GPIO PPS, RTC, fan and PoE behavior on the selected image before declaring node acceptance |
| Watchdog masks a boot or network failure with restart loops | Keep watchdog resets off until console/media recovery and a controlled test are ready |
| Primary rebuild interrupts hard-coded NTP clients | Before primary outage, verify family-specific DNAT transition to the accepted standby and a surviving direct-client path |
| Incomplete or invented inventory facts | Capture exact per-host hardware/media facts; leave an unverified field and open gate when evidence is missing |

## Reference documentation

- [Raspberry Pi OS editions and Trixie release](https://www.raspberrypi.com/documentation/computers/os.html)
- [Raspberry Pi Imager and headless setup](https://www.raspberrypi.com/documentation/computers/getting-started.html)
- [Uputronics GPS/RTC board and revision-specific datasheet](https://store.uputronics.com/products/raspberry-pi-gps-rtc-expansion-board)
- [Raspberry Pi PoE+ HAT](https://www.raspberrypi.com/products/poe-plus-hat/)
- [NTPsec Stratum-1 Microserver HOWTO](https://www.ntpsec.org/white-papers/stratum-1-microserver-howto/)
- [Webmin installation and repository](https://webmin.com/download/)
