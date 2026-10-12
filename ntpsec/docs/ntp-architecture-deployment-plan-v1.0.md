# Dual-stack NTP architecture and deployment

Plan version: `1.5` (stable filename retained for existing links).
For current status, operation history, and the next gate, see
[NTPsec history](../HISTORY.md).

## Approved rebuild identity change

On `2026-10-08`, Aaron approved renaming the existing j1-svntp1 to
**j2-svntp1** during its Trixie rebuild. This is the same physical node, not
an additional server. Operational references below use the target name.
The current Debian 11 hostname, baseline filenames, captured configurations
and protected evidence directory retain j1-svntp1 as historical identity.
Old-card recovery restores that original hostname.

The rename alone changes neither IP assignments nor the existing service FQDN
ntp1.local.theama.co. Before acceptance, reconcile the target hostname in the
owning inventory, monitoring and management records; review DNS/PTR references
with homelab-dns and update only under their separate approved scope. No DNS,
controller, inventory or live-host mutation is authorized by this plan update.
Keep the primary j1-svntp and its antenna-power role unchanged.

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

| Property | `j1-svntp` | `j2-svntp1` |
| --- | --- | --- |
| Service name | `ntp.local.theama.co` | `ntp1.local.theama.co` |
| IPv4 | `10.1.0.50/22` | `10.1.0.51/22` |
| Permanent ULA | `fd36:5aa8:6971:1::50/64` | `fd36:5aa8:6971:1::51/64` |
| Platform | Raspberry Pi 4B, 8 GB | Raspberry Pi 4B, 4 GB |
| GPS | Uputronics GPS/RTC expansion board | Uputronics GPS/RTC expansion board |
| Power | HAT model pending per-node confirmation | Working Raspberry Pi PoE HAT (2018), retained |
| Pre-rebuild observed OS | Debian 11 | Debian 11 |
| Target OS | Raspberry Pi OS Lite (64-bit), Trixie | Raspberry Pi OS Lite (64-bit), Trixie |
| Pre-rebuild reported NTPsec | `1.2.1+82-g7abe7fba6` | `1.2.1+82-g7abe7fba6` |
| Target NTPsec | Build pinned source on this target; record revision and installed-file manifest | Build pinned source on this target; record revision and installed-file manifest |
| Rollout order | Second | First |

Both nodes run independent NTP services. They share a GPS antenna and its
power path, so they are not independent GPS failure domains. The project will
not add Keepalived, VRRP, or another NTP HA layer.

### Existing hardware and replacement policy

Retain j2-svntp1's working Raspberry Pi PoE HAT through the OS rebuild. Aaron
identified its 2018 marking and confirmed that it is in use and works. He
reports that this model is no longer available and selected the Raspberry Pi
PoE+ HAT as its replacement **upon failure**, not as a rebuild prerequisite.
The prior PoE+ description is not accepted evidence for j1-svntp's HAT;
confirm that node's model during its own baseline.

Validate power, fan, thermal behavior and GPS/RTC stack compatibility for the
actual installed HAT on Trixie. Existing Debian 11 operation does not establish
Trixie compatibility. A future PoE+ replacement requires its own scoped action,
verified switch power capability/budget, stack clearance and GPIO/I2C
compatibility, boot configuration, fan and thermal tests, and recovery path.
Do not reuse PoE HAT assumptions or claim the old SD card alone reverses a
hardware replacement; a failed HAT is not a working rollback spare.

### Shared GPS antenna and maintenance dependency

Both receivers share one GPS Source L1G1A-STD antenna through a Uputronics
two-output SMA GPS splitter, one receiver per output. Aaron visually confirmed
that **j1-svntp supplies antenna power** through its GPS board. Preserve that
power path and the common antenna/splitter connections during the first
j2-svntp1 rebuild. There is no unused third receiver output.

The shared antenna, splitter and supplying node are GPS failure dependencies.
Before any later j1-svntp power-off, define a separately authorized antenna-power
continuity procedure with the exact connection mapping, power compatibility,
expected interruption, acceptance and rollback. Verify the surviving
j2-svntp1's GPS/PPS selection and IPv4/IPv6 time service with the planned
maintenance power arrangement before allowing that outage. No alternative
power source, splitter reconnection or hardware purchase is selected here.
If continuity cannot be established, stop and obtain an explicit revised
service-impact decision; do not assume holdover or upstreams meet acceptance.
Record the final antenna-power source and mapping after maintenance.

## Locked decisions

### NTPsec and GPSD source builds

Aaron selected this application lifecycle on `2026-10-10`:

- Build **both NTPsec and GPSD from source on each target host**, using reviewed
  adaptations of the baseline HOWTO's `clockmaker` and `pinup` scripts.
- Use native source installation: NTPsec through waf and GPSD through SCons,
  with explicit installed-file manifests. A locally built Debian `.deb` is
  not required. Do not install NTPsec or GPSD application/client packages from
  APT, including through dependencies or recommendations.
- Preserve and modernize the combined `timeservice` model. Its accepted
  implementation must supervise and report the health of both GPSD and ntpd;
  the guide's oneshot `active/exited` state alone is not service acceptance.
  A daemon failure stops the pair; systemd restarts both with bounded retries.
- Use the same reviewed `clockmaker` build/update/install lifecycle for later
  application maintenance. Use `pinup` for PPS configuration/query, not as a
  software updater. Preserve local NTP configuration during application updates.

Aaron added these source/runtime requirements on `2026-10-12`:

- Enable NTPsec mDNS registration. Build with DNS-SD headers/libraries, start
  ntpd with `-m`, and provide a working Avahi responder. Require the generated
  `HAVE_DNS_SD_H` feature and successful `_ntp._udp` advertisement on UDP 123
  after synchronization, independently observed by a client on the intended
  local network. Scope Avahi interfaces and firewall permissions in the reviewed
  host profile; cross-VLAN reflection is a separate network decision. mDNS does
  not replace the governed unicast DNS/SRV records or NTP access restrictions.
- Keep `--refclock=shm`: GPSD owns the UART/PPS inputs and exports serial time
  and PPS time through separate SHM units. NTPsec's `nmea` and `pps` refclocks
  read devices directly and are unnecessary for this GPSD-mediated path.
  Observe SHM unit assignments and accept GPS/PPS selection on each target.

The earlier accepted candidate has mDNS disabled. Preserve its evidence and
prepare a newly approved dependency/build stage before live installation.

The [baseline HOWTO](https://www.ntpsec.org/white-papers/stratum-1-microserver-howto/)
defines the starting workflow, not an executable Trixie deployment artifact.
The [operations recipe](OPERATIONS.md#source-build) records reviewed script
bytes, defects, configuration differences and adaptation requirements. Resolve
exact source revisions and hardware/build options before producing a deployment
bundle; moving Git branches or freshly downloaded scripts are not approved
inputs. Build unprivileged; install and activate only within the approved target
stage. Upstream OS/account/purge/reboot modes are not implicit build operations.
Use reviewed stable release tags pinned to exact commits. The
[maintained helper workflow](OPERATIONS.md#live-installation-and-rollback) defines build,
configuration staging, installation, rollback and PPS helper contracts.

APT remains the mechanism for reviewed OS packages, build prerequisites and
baseline applications such as needrestart and msmtp. Resolve those separately
from source artifacts. Build dependency candidates must come from the selected
revisions' build descriptions and the observed Trixie environment, not from an
APT NTPsec/GPSD application dependency list. Reject an APT solution introducing
conflicting application packages.

Prepare each node's package transaction from the checked-in foundation recipe,
pinned assets and a fresh protected target snapshot. Bind dependency resolution
to that snapshot and compare exact before/after inventories. Historical bundles
are execution records; they cannot supply a new node's baseline. The
[operations recipe](OPERATIONS.md#package-foundation-and-installation-controls)
defines capture, resolution, staging, acceptance and cleanup.

Each application release manifest must bind source origin/revision and archive
or tree integrity, upstream/adapted script hashes and diff, toolchain/dependency
versions, build configuration/options and test logs, install prefix,
binary/Python-module/manual paths, and installed-file hashes/owners/modes.
Record the combined service, runtime users, devices and local configuration
separately. Dpkg absence does not prove a source-built application is absent;
also observe binaries, version output and process ownership.

Before an update, preserve accepted application artifacts and manifests,
configuration, combined service definition and Python environment. Define how
to remove candidate-only files and restore the prior installed set together;
rebuilding an old revision against new dependencies is not tested rollback.
The original Debian 11 card remains the rebuild recovery path. Repeat GPS/PPS,
both daemon health, dual-stack client, upstream/NTS, leapfile and monitoring
checks after each application update. No unattended update, restart, mail or
reboot follows from this document.

### Addressing

- `j1-svntp` uses `fd36:5aa8:6971:1::50/64`.
- `j2-svntp1` uses `fd36:5aa8:6971:1::51/64`.
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
│   └── j2-svntp1/
│       └── ntp.conf
├── docs/
│   ├── ntp-architecture-deployment-plan-v1.0.md
│   └── OPERATIONS.md
├── scripts/
│   ├── clockmaker.py
│   ├── pinup.py
│   ├── timeservice.py
│   ├── inspect-node.sh
│   ├── install-node-config.sh
│   └── validate-node.sh
├── templates/
│   ├── timeservice.service
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
acceptance record, and recovery path. Rebuild `j2-svntp1` first. Do not begin
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
- Identify exact GPS/RTC board revision, antenna and PPS wiring, installed PoE HAT
  revision, physical stack order, and the network switch port for each node.
  Board revision controls the RTC chip, UART settings, and boot overlay choice.
  The Uputronics GPS HAT UART rate is fixed at **115200 baud**. For GPSD
  3.27.5, enforce `gpsd -s 115200`; `fixed_port_speed` is not a supported SCons
  option. The modernized timeservice supervisor must successfully initialize
  the observed UART using checked `stty` at 115200 before starting either daemon.
  This replaces the legacy `/etc/init.d/timeservice` initialization. Verify
  receiver communication and persistence at this rate during target acceptance.

### Per-node baseline and acceptance

For **each** Trixie node, install OS/build/baseline packages only from approved
Raspberry Pi OS/Debian repositories and an explicitly approved Webmin
repository. Build NTPsec and GPSD using the source lifecycle above. Record
package origins/versions and application source/install manifests. Configure
and validate:

| Area | Required evidence before accepting the node |
| --- | --- |
| Base OS and access | Raspberry Pi OS Lite Trixie release and arm64 architecture; boot firmware and kernel; correct hostname, SSH access, package sources, updates, users and administrative access; persistent boot and root filesystems |
| Network and DNS | Stable node IPv4 and ULA, retained Router Advertisement global IPv6 and default route, both DNS VIPs with DHCP/RA DNS replacement disabled; dual-stack reachability and reboot persistence |
| `webmin` | Package provenance, service health, authenticated management access from an approved LAN path, intended bind/firewall scope, and no unintended External exposure; restore required settings from observed Debian 11 state only after review |
| `needrestart` | Trixie package, enabled kernel checks with the Pi 4 filter, list-only reporting, actual kernel/service report and notification through the accepted msmtp/Mailrise path; no unattended restart of the combined time service |
| `msmtp` | `msmtp` plus a sendmail-compatible transport if required by the notification workflow; protected relay configuration, successful test delivery through Mailrise, and no committed credentials |
| `munin-node` endpoint | Installed package and enabled service; observed listener and client allowlist; collection from the approved Munin poller over each intended address family; usable host metrics and no unintended External exposure. The Munin component owns endpoint configuration and plugin choices |
| `watchdog` | Observed `/dev/watchdog` owner/driver and service configuration, reboot behavior and recovery path; enable only after the node can be recovered independently and a controlled acceptance test is approved |
| GPS/RTC HAT | Verified board revision, antenna/fix, UART device and baud, I2C RTC identity and sane time, PPS GPIO and `/dev/pps*` pulses, `gpsd` feed and permissions, and persistence after reboot; choose boot overlays for the selected image and observed hardware |
| Installed PoE HAT (PoE+ only if replaced) | Correct switch PoE class and power budget, boot and sustained power without undervoltage, fan detection/control and thermal behavior, and no GPIO/I2C conflict with the GPS/RTC HAT |
| Source-built NTPsec/GPSD | Accepted per-target source revisions and installed-file manifests; actual config/tool/module paths and combined service ownership; GPS/PPS and sanity-source selection, leapfile and four-week timer, no competing time/GPS daemon, IPv4/IPv6 UDP 123 listeners and client responses, NTS/IPv4/IPv6 upstream behavior as configured |

Use the existing NTPsec/GPSD arrangement as input evidence, not as an
installable Trixie artifact. Keep byte-exact Debian 11 `/etc/ntp.conf`
captures for audit. Derive a separate Trixie configuration from the source
builds' combined service, config path, default files, man pages, user/group, device
names, and live hardware; validate it on `j2-svntp1` before reusing the design
on `j1-svntp`. Do not copy old boot overlays, `/etc/ntp.conf`, GPSD unit
assumptions, Webmin settings, or network-manager profiles blindly.

The Uputronics datasheet describes GPS UART, PPS, I2C RTC, and different
settings by board revision. Its Raspberry Pi OS examples are reference inputs,
not proof of a Trixie boot configuration. The NTPsec microserver HOWTO is the
source-build baseline; its scripts and companion files require reviewed Trixie
adaptations under the source lifecycle above.
Prove fan and power operation for the installed HAT on the selected image;
a successful boot alone does not establish full HAT support. Apply the
replacement policy above only if the working PoE HAT fails.

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
Installed PoE HAT model (including PoE+ if replaced)
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

Create a fail-closed collector, then run it against `j2-svntp1` before
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
   against observed source-build paths and the combined service contract.
4. Define node baseline configuration and validation for Webmin, needrestart,
   msmtp/sendmail, the Munin endpoint, watchdog, GPS/RTC/PPS, installed PoE HAT power and
   fan, source-built GPSD/NTPsec through adapted clockmaker and pinup, the
   combined timeservice, dual-stack networking, and the four-week
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

### Phase 3: rebuild and accept `j2-svntp1`

1. Confirm `j1-svntp` serves clients and the reported active IPv4 DNAT target
   remains reachable. Capture a pre-rebuild client and NTP health baseline;
   identify clients that use only `j2-svntp1` and their retry/failover behavior.
   One healthy node does not guarantee zero client impact.
2. Preserve j1-svntp's antenna-power path and the shared splitter connections.
   Under the approved maintenance window, power down only `j2-svntp1` and
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
   Verify UART aliases, serial-console ownership, Bluetooth use, PPS GPIO and
   edge from the actual board and device tree before rendering boot overlays.
   Use PL011 for the GPS UART where supported; apply `disable-bt`, `enable_uart`
   and hciuart changes only as required by the observed mapping. Reject a
   competing clock-discipline process before activating source-built ntpd.
6. Query `j2-svntp1` directly from controlled clients over IPv4 and IPv6;
   confirm GPS/PPS selection, upstream reachability, leap state, Webmin
   management scope, approved Munin polling, delivered mail, needrestart
   reporting, PoE fan/thermal behavior, and a second successful boot. After
   recovery is proven, enable watchdog and run its separately approved
   controlled acceptance test. Record package and hardware facts.
7. Only if the rebuilt node passes all gates, observe it for an agreed interval
   and finish its inventory record. Keep the existing primary DNAT active; do
   not switch DNAT merely to prove the standby rebuild.
   Review Phase 3A before promoting this configuration to the other node.

If boot, network, GPS/PPS, or client acceptance fails, remove the new card and
reinstall that node's preserved Debian 11 card. Validate the old node's NTP
health and client responses. A media swap is the recovery action; copying the
old network profile or NTP config onto the new image is not a rollback.

### Phase 3A: evaluate and accept measured optimizations

Evaluate host, system, NTPsec and GPSD proposals here. Required hardware,
networking and dependency corrections belong in their existing phases; tuning
is evaluated after Phase 3 has established a working, accepted baseline. Run
this phase on the rebuilt standby first and repeat adopted changes on the
primary only after its own rebuild. A decision to retain defaults is valid;
deferred optional experiments do not block deployment.

The goals are measured GPS/PPS accuracy, stable clock discipline, low client
offset/jitter and reliable service. Four GB of RAM does not justify CPU
isolation, and no configuration guarantees deterministic interrupt latency,
zero jitter or absolute UTC accuracy. Absolute accuracy claims require an
independent reference with known uncertainty.

1. Register each proposal with a stable ID, disposition, affected phase,
   evidence and unresolved prerequisites. Evaluation does not authorize live
   collection, packages, boot edits, service changes or reboot.
2. Bind a fresh target baseline: board/firmware/kernel, kernel configuration,
   clocksource, CPU frequency driver/governors/limits, boot arguments, task and
   IRQ placement, software/configuration hashes, receiver/PPS mapping, network
   state, temperature, fan and throttling/undervoltage history. Confirm existing
   recovery and peer/shared-antenna continuity.
3. Define metrics and pass/fail limits before approving an experiment. Compare
   PPS sequence gaps and timestamp variation, SHM samples, source offset/jitter,
   clock frequency/wander, client offsets and response loss, CPU/IRQ activity,
   temperature and power faults. Keep load, sampling, receiver state and
   observation windows comparable. Allow thermal stabilization and NTP
   convergence; the pinned SHM documentation warns that tuning can need several
   hours to converge. A few one-second samples are insufficient.
4. Seal one change with its collection, acceptance, restoration and, where
   necessary, reboot/console recovery. Prefer a reversible runtime experiment
   before boot/kernel changes. Obtain scoped approval and operate on one node
   while the peer serves. Capture before/change/restore comparisons; isolate
   confounding changes rather than applying the proposed tuning block at once.
5. Adopt only repeatable improvements without regressions in GPS/PPS selection,
   service/access, IPv4/IPv6/NTS/mDNS, thermal/power health or reboot persistence.
   Restore the exact baseline if results fail or are inconclusive. Mirror
   accepted settings into the repo's recipes/templates and installed manifests;
   record outcomes in HISTORY with bounded private evidence. Do not leave
   accepted settings dependent on manual commands or historical trial bundles.

#### OPT-001: dedicated Pi 4 timing and telemetry proposal

Evaluated on October 12, 2026 against the pinned GPSD 3.27.5/NTPsec 1.2.5
sources and Raspberry Pi OS Lite Trixie architecture. These are design
dispositions, not measured performance results or live-action approvals.

| Item | Disposition and reason | Placement |
| --- | --- | --- |
| OPT-001-01: APT ntpsec, gpsd, gpsd-clients | Reject this installation command. Both applications and their clients come from pinned source; distro packages would conflict with that lifecycle. | Source lifecycle; Phases 2/3 |
| OPT-001-02: pps-tools | Required and already in the foundation recipe/pins. Provides kernel PPS diagnostics; it is not an additional optimization. | Foundation; Phase 3 hardware acceptance |
| OPT-001-03: setserial | Omit unless a verified serial-driver need emerges. The maintained GPSD supervisor initializes its selected UART with stty and GPSD at 115200; setserial is not a demonstrated prerequisite. | Phase 3 hardware review if needed |
| OPT-001-04: ntpsec-ntpviz | Optional telemetry using pinned-source ntpviz, already in the accepted staged manifest. Do not install the distro package: its python3-ntp dependency mixes another release's modules with the source stack. Prefer plotting on the operator workstation; review compatible modules, gnuplot dependencies, statistics, retention and exposure before adoption. | Phase 3A; routine monitoring |
| OPT-001-05: isolcpus=3 nohz_full=3 rcu_nocbs=3 | Experimental, not a baseline requirement. These flags neither pin ntpd to CPU 3 nor reserve that CPU for PPS IRQs. Check kernel support, task/IRQ/workqueue placement and housekeeping; boot-time scheduler-domain isolation is inflexible. Prefer a reversible affinity/cpuset trial. Full dynticks targets mostly-userspace workloads and can increase kernel-entry/exit overhead; ntpd/GPSD perform kernel I/O. | Phase 3A |
| OPT-001-06: performance governor / cpufrequtils | Experimental. The governor requests the highest permitted policy frequency; it does not prevent thermal/firmware throttling or guarantee clock stability. Measure power/temperature and frequency wander. Inspect the actual driver and persistent policy mechanism; cpufrequtils is absent from the retained Trixie arm64 main index and is not an assumed prerequisite. | Phase 3A; resolve any selected tool separately |
| OPT-001-07: arm_freq=1500 | Do not impose this as a timing requirement. It sets a CPU frequency parameter, not a fixed NTP timebase; the supported default depends on board/firmware and a forced value can reduce performance. Preserve supported defaults unless a separate measured experiment justifies a change. | Phase 3A |
| OPT-001-08: gpu_mem=16 | Optional memory saving with no demonstrated timing benefit on this 4 GB host. It affects legacy GPU allocation and disables some GPU features; verify firmware and console/recovery requirements before changing it. It is not a replacement for checking actual graphics/CMA use. | Phase 3A |
| OPT-001-09: disable-bt / hciuart | Conditional hardware configuration, not general latency tuning. On Pi 4 the overlay can make PL011 UART0 primary; verify aliases, serial-console settings, actual device and enable_uart need. Disable an observed hciuart service only when Bluetooth is intentionally disabled. Do not assume the device name from a sample. | Phase 3 step 5 |
| OPT-001-10: pps-gpio on GPIO 4 or 18 | PPS input setup is required; either example pin is unapproved until wiring is verified. The receiver is Uputronics u-blox M8; history records HAT rev 5.9, but exact BCM PPS GPIO/edge and the target mapping still need confirmation. Use the existing hash-bound pinup workflow and check RTC/PoE conflicts. | Phase 3 step 5 |
| OPT-001-11: disable systemd-timesyncd | The existing requirement is one clock-discipline daemon. Inspect services/processes and inhibit any actual competitor, including timesyncd, within the activation bundle; do not assume it exists or blindly purge packages. GPSD remains the measurement provider. | Phase 3 step 5 |
| OPT-001-12: static network / remove NetworkManager | Static addressing is already required. Use the observed supported manager and preserve RA global IPv6/default route plus explicit DNS VIPs. No evidence supports removing NetworkManager for timing precision. Preserve required Avahi/mDNS and management services. | Phase 3 step 4; Phase 8 validation |
| OPT-001-13: ppswatch -a /dev/pps0 and zero jitter | Correct the acceptance claim. The pinned pps-tools includes ppswatch and ppstest, but identify the actual PPS device first. Observe edge, increasing sequences, missing pulses and timestamp/interval distributions under representative load, then prove GPSD SHM and ntpd PPS selection. One-second pulses do not prove zero jitter, UTC accuracy or a healthy end-to-end service. | Phase 3 steps 5/6; Phase 3A measurement |

The proposal's root-domain/Reddit/YouTube references do not identify specific
evidence for its timing claims. Use these primary references and the selected
build's local manuals; inspect kernel/firmware differences before applying
current upstream guidance to the pinned target:

- [Linux CPU isolation](https://www.kernel.org/doc/html/latest/admin-guide/cpu-isolation.html),
  [CPUFreq](https://www.kernel.org/doc/html/latest/admin-guide/pm/cpufreq.html)
  and [PPS API](https://www.kernel.org/doc/html/latest/driver-api/pps.html).
- Raspberry Pi [UART mapping](https://github.com/raspberrypi/documentation/blob/master/documentation/asciidoc/computers/configuration/interfaces.adoc),
  [frequency/thermal management](https://github.com/raspberrypi/documentation/blob/master/documentation/asciidoc/computers/raspberry-pi/frequency-management.adoc)
  and [legacy GPU memory](https://github.com/raspberrypi/documentation/blob/master/documentation/asciidoc/computers/legacy_config_txt/memory.adoc).
- Pinned NTPsec [SHM driver](https://gitlab.com/ntpsec/ntpsec/-/blob/42b5703303c8c7e6513f3a119cfab670924dd7be/docs/driver_shm.adoc)
  and [ntpviz](https://gitlab.com/ntpsec/ntpsec/-/blob/42b5703303c8c7e6513f3a119cfab670924dd7be/docs/includes/ntpviz-body.adoc).

### Phase 4: rebuild and accept `j1-svntp`

Repeat the Phase 3 controls and Phase 3A review with `10.1.0.50` and
`fd36:5aa8:6971:1::50`. First prove that rebuilt `j2-svntp1` serves clients
independently. Complete the shared-antenna power-continuity gate above before
any primary power-off; DNAT failover does not preserve antenna power. For each
family with an existing active `j1-svntp` DNAT rule,
disable that rule and promote the matching `j2-svntp1` standby rule under a
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
3. Add host keys `j1-svntp` and `j2-svntp1` with their management FQDNs.
4. Add host files that satisfy the complete observed hardware, storage, OS,
   HAT, address-authority, and no-HA inventory contract above. Preserve the
   exact per-host differences; do not fill missing fields with assumptions.
5. Keep IP allocation and authoritative DNS records out of inventory.
6. Run strict YAML and inventory repository validation. Compare each final
   host record with accepted live readback before marking it complete.

### Phase 8: end-to-end acceptance

Acceptance requires:

- Adopted Phase 3A optimizations have per-node comparison, recovery and
  persistence evidence; deferred optional proposals are recorded explicitly.
- Both nodes boot the selected Trixie arm64 image from separately
  identified replacement media, and their labelled Debian 11 cards remain
  available for recovery through the agreed retention period.
- Webmin, needrestart, msmtp, `munin-node`, watchdog, GPS/RTC, PPS, GPSD,
  NTPsec, and installed PoE HAT checks in the per-node acceptance table pass on each
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
  promoted one family at a time to `j2-svntp1` and restored.
- Inventory names, functions, components, hardware, and OS facts match live
  observations, including exact Pi and HAT revisions and boot/root media.
- Each repository passes its focused tests, full baseline, secret scan, and
  whitespace checks.

Run an observation interval after the last change. Review offsets, jitter,
reach, leap state, systemd failures, DNS errors, and UniFi counters before
declaring acceptance.

## Rollback policy

- Roll back one node or one controller policy surface at a time.
- Keep the other NTP node serving throughout host rollback. Preserve the
  accepted antenna-power arrangement; restore any changed mapping only under
  its approved rollback sequence and verify GPS/PPS and client service. Do not
  restore the original power dependency while its supplying node is unavailable.
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
| Shared antenna loses power during primary maintenance | Complete the antenna-power continuity gate before j1-svntp shutdown; verify surviving GPS/PPS and client service and retain an explicit rollback path |
| Failed PoE HAT replaced with PoE+ | Revalidate switch power, stack compatibility, boot/fan behavior and recovery; retain working HATs during the OS rebuild |
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
- [Uputronics two-output GPS antenna splitter](https://store.uputronics.com/products/gps-antenna-signal-splitter-with-sma)
- [Raspberry Pi PoE+ HAT replacement reference](https://www.raspberrypi.com/products/poe-plus-hat/)
- [NTPsec Stratum-1 Microserver HOWTO](https://www.ntpsec.org/white-papers/stratum-1-microserver-howto/)
- [Webmin installation and repository](https://webmin.com/download/)
