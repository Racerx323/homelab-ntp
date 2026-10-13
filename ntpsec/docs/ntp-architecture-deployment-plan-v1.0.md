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

For the rebuilt node's Uputronics GPS/RTC board, the operator-supplied datasheet
(document revision 2.2, December 2020) specifies time pulse on BCM GPIO18,
physical header pin 12, and an RV-3028-C7 RTC at I2C address 0x52. Its serial
example uses 115200 baud. These are vendor wiring inputs for preparation;
target overlay availability, UART mapping, PPS edge and RTC operation still
require verification. The document revision is not the board revision. Use
explicit GPIO18 in the PPS overlay candidate and the rv3028 RTC parameter;
do not infer device aliases or apply the document's older Raspbian setup steps.

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

Before source installation, seal a read-only inspection bound to the accepted
release, build receipt/specification and target identity. Require accepted
canonical destination pre-state before preparing live installation. Inspect every
intended destination and protected ancestor; retain complete file/link pre-state and
collision classifications. Recheck package, boot, Python and service/process
continuity. Use exclusive root-owned staging, one capture, conditional terminal
readback and verified cleanup; preserve executed build evidence. An accepted
inspection authorizes no replacement or activation. Unsafe paths, bounds or
state drift hold the next installation gate for separately reviewed recovery.

For native first installation, verify accepted staged bytes/links into protected
root staging before invoking the accepted installer; never execute user-owned
build code as root. Require stopped application daemons, no conflicting APT
application packages, exact destination pre-state and target continuity. Use
explicit file/directory ownership/modes and retain baseline, journal and backups.
Accept complete installed-file verification separately from runtime activation.
Recovery must prove every removal and created-directory identity/content before
restoring the baseline; ambiguous partial state requires a new recovery review.
Payload cleanup preserves executed privileged artifacts and recovery evidence.

Before runtime configuration, accept a separately sealed read-only discovery
bound to the native installation receipt. Verify installed bytes, parent identity
and package/boot/Python/service continuity. Observe UART/PPS/RTC metadata, boot
and time configuration, local account/group identifiers, loader metadata and
network profiles without executing installed applications or opening receiver
devices. Retain unknowns explicitly; static discovery does not prove runtime
linkage, receiver health or configuration readiness. Bind configuration rendering
to the accepted report, current templates and reviewed host choices. Library-cache
changes, runtime validation, accounts, network/configuration installation and
activation require explicit scope in subsequent hash-bound approvals.

The earlier accepted candidate has mDNS disabled; preserve its evidence.
The replacement dependency/build stage has passed acceptance, as recorded in
HISTORY. Live installation still requires separately approved destination
inspection and a reviewed installation/recovery bundle.
First seal a fresh foundation snapshot against the revised recipe and current
pinned asset manifest, verify its target identity during the approved capture,
and accept its terminal readback/cleanup. Metadata resolution is a subsequent
approved operation bound to that accepted snapshot, current recipe and pinned
manifest. Recheck freshness and protected target state before and after isolated
resolution; require signed metadata, dependency closure and native simulation
agreement before preparing installation. Package and source-build
execution require their own reviews. Optimization trials remain after baseline
hardware/time/network acceptance in Phase 3A.

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
   Before sealing these changes, collect persistent Ethernet properties by UUID
   and available boot overlays without reading credentials or opening devices.
   Confirm the HAT's PPS GPIO and RTC from board evidence. Review networking,
   boot/reboot and account/loader/runtime changes as distinct recoverable stages;
   network endpoint changes need timed restoration and console recovery.
   Bind prepared network/boot transactions to the accepted supplemental
   host-input report and exact affected configuration before-state; reject
   intervening drift. Availability of overlay files does not establish that
   devices are configured or working. Keep capture acceptance distinct from
   configuration readiness and combined-service activation.
   Use a separate NetworkManager candidate profile with the original retained
   for recovery. Arm root-owned timed recovery before persistent network changes;
   require pinned-key management access through both fixed addresses and route,
   DNS and dual-stack egress evidence before cancelling it. Recover original
   profile settings on missed acceptance, preserving journals and holding on
   unrelated drift. Reboot persistence remains a later independently approved
   hardware/reboot check; do not claim it from live profile activation alone.
   On October 13, 2026, `host-network-20261013-v1` passed live dual-stack
   host acceptance and transient cleanup on j2-svntp1. Fixed IPv4/ULA,
   retained RA, both DNS VIPs, routes, HTTPS egress and pinned-key management
   access were verified. The original DHCP profile and recovery evidence
   remain retained. Hardware execution on October 13 subsequently held on
   post-reboot network registry drift. The accepted inspection established
   that only the loopback UUID changed. The separately approved recovery
   continuation completed a reboot into the restored original boot files,
   dual-stack acceptance and transient cleanup on October 13. Native files,
   packages, services, addresses, RA, DNS and routes retained continuity.
   Keep the constrained loopback comparison in future hardware/reboot stages:
   allow only the observed lo identity and reserved addresses, methods,
   gateways and autoconnect state; preserve exact non-loopback registry and
   network/native checks. The corrected checker and fresh-baseline sealer
   are tested offline; the post-recovery read-only capture was accepted and
   cleaned on October 13. Hardware v2 subsequently held at the PL011 driver-name
   check; original boot files were restored and recovery reboot/network checks
   and transient cleanup completed. The accepted read-only inspection found
   the PL011 driver bound to the AMBA UART on the recovered boot, without a
   serial0 alias or ttyAMA/ttyS nodes; the failed-boot mapping remains unknown.
   Validate the selected tty's bounded parent chain against exactly one PL011
   AMBA driver, device registry identity and compatible device-tree node.
   Preserve the observed chain and validation errors in protected state before
   a hold or recovery. These checks are tested offline. Fresh baseline v2, bound
   to hardware v2's completed recovery/cleanup, was accepted and cleaned on
   October 13. Hardware v3 then held at sysfs path validation and completed
   conditional recovery/cleanup. The bounded traversal must permit tty class
   subsystem links and the device-tree root while retaining exact AMBA driver
   and registry checks. Save partial ancestry and the rejected link before a
   hold. These corrections are tested offline; fresh baseline v3 requires
   separate capture approval before a replacement hardware bundle is sealed.
   Bind replacement stages independently from historical
   networking provenance; do not rewrite historical boot IDs. See HISTORY for
   execution evidence. Hardware/time-service/client acceptance remains pending.
   Prepare hardware/boot and account/runtime prerequisites as separately
   approved hash-bound stages. Boot edits preserve unrelated settings and
   storage/root parameters, remove only the observed serial console, and use
   byte-exact protected backups. Require declared console/media readiness for
   one controlled reboot and, if needed, one guarded recovery reboot. A failed
   boot or lost endpoints requires console recovery; do not claim an automatic
   recovery timer survives reboot. Accept new-boot dual-stack management and
   device-tree/node metadata separately from GNSS fix, physical PPS samples,
   RTC time accuracy, PoE/thermal behavior and NTP client acceptance.
   Bind account/runtime preparation to the exact accepted hardware specification
   and its post-reboot boot ID. Use a dedicated `ntp:ntp` system identity with
   nologin and no home creation; retain the pinned GPSD `nobody`/`dialout` defaults.
   Refresh only the backed-up library cache with `ldconfig -X`, preserving
   native files/modes, library symlinks and loader configuration. Require root
   native/GPS/NTP checks and isolated NTP-user imports. Keep rendered service
   candidates inside the private stage; final NTP configuration, global file
   installation and daemon activation remain a separate reviewed cutover.
   Keep bootstrap time synchronization until the approved ntpd cutover. Use
   foreground GPSD with nowait polling so time service does not depend on a
   connected client. Derive daemon identities from the accepted build and
   device permissions, preserving accepted release modes unless separately
   reviewed changes prove necessary.
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

#### OPT-002: indoor antenna placement and SHM calibration

Evaluated on October 12, 2026. Indoor/window placement is a proposed scenario,
not a newly verified site observation. Obstruction, reflective surroundings
and some glazing can degrade reception; neither a particular serial delay nor
loss of valid time follows from placement alone. Establish actual reception
and receiver behavior before changing clock-selection policy.

The goal remains correct time with GPS/PPS preference when valid. Falling back
to accepted independent network sources during invalid GPS time is protective,
not an optimization failure. Both receivers share the antenna/splitter and
primary-supplied antenna power; an antenna move is a common physical change
that can affect both services. Review its scope, power/cable continuity,
expected service impact and restoration explicitly rather than treating it
as an isolated software experiment on the standby.

| Item | Disposition and reason | Placement |
| --- | --- | --- |
| OPT-002-01: window placement and small antenna moves | Assess actual sky visibility, obstructions/glazing, antenna mounting/orientation, interference and cable/splitter health. A small move may help, but two inches is not a guaranteed remedy. Compare candidate locations using reception and timing records over representative satellite geometry, not a single snapshot; preserve shared antenna power. | Phase 3 hardware acceptance; Phase 3A comparison for later moves |
| OPT-002-02: tos mindist 0.002 | Conditional selection experiment, not an indoor-GPS preset. The pinned default is 0.001 seconds; 0.002 doubles the global minimum distance to 2 ms. It affects selection/intersection and anticlockhop behavior for all sources, not just PPS jitter. A measured high-jitter association can justify investigation, but this does not restore invalid GPS data or repair multipath. Keep the reviewed baseline unless selection logs demonstrate a need. | Phase 3A; accepted host ntp.conf only after comparison |
| OPT-002-03: tos maxdist 1.5 | No new optimization: 1.5 seconds is already the pinned default synchronization-distance threshold. It is not a GPS fade timer or a guarantee of bridging loss of fix. Preserve validity/aging checks and accepted network fallback rather than increasing tolerances to retain a bad reference. | Phase 3 runtime configuration and loss/recovery acceptance |
| OPT-002-04: serial SHM calibration | Determine the actual serial SHM unit, protocol/message schedule, baud, GPSD timing behavior and stable bias. Document the calibration reference, sign, uncertainty and before/after results; calibrate serial and PPS paths separately. | Phase 3A; per-node host configuration if justified |
| OPT-002-06: center SHM offset using ntpq -p | Useful initial diagnosis, not sufficient calibration evidence. Serial offset is relative to the already disciplined system clock and may reflect UART/receiver message latency. A PPS-disciplined local clock can help compare the serial path, but it does not independently prove GPS/PPS UTC accuracy. Use sustained statistics, receiver time-validity/accuracy reports where available and an independent reference of known uncertainty for absolute claims. | Phase 3A measurement |
| OPT-002-07: gpsmon and four satellites above SNR 30 | Monitor through the reviewed running GPSD endpoint without opening the live UART independently or issuing receiver-control commands. Use observed versus used satellites, signal-strength units, geometry/fix status, UTC validity and reported time accuracy. Four satellites above 30 is a screening heuristic, not a universal timing/PPS criterion. Verify the exact M8 model/firmware and available timing mode; do not assume every M8 supports survey-in or needs a continuous 3D fix for valid time. | Phase 3 hardware/time acceptance; Phase 3A observation |
| OPT-002-08: logging versus immediate tuning | First prepare bounded receiver/SHM/NTP logging and a placement baseline, with explicit capture/retention scope. Correlate receiver quality with PPS gaps, SHM freshness, source selection, frequency and client offsets before choosing any calibration or selection change. Accept valid failover/recovery; never count forced GPS selection as success. | Phase 3 baseline logging; Phase 3A evaluation |

Use `/etc/ntp.conf`, the governed source-built runtime path, rather than the
proposal's distro-package `/etc/ntpsec/ntp.conf`. No numeric calibration, global
threshold change, receiver-mode change or antenna move is adopted by this
evaluation. Preserve GPS/PPS, leap/stratum and failover checks when comparing
any later candidate.

Primary evidence is the pinned NTPsec [tos documentation](https://gitlab.com/ntpsec/ntpsec/-/blob/42b5703303c8c7e6513f3a119cfab670924dd7be/docs/miscopt.adoc)
and the SHM driver above, plus pinned GPSD [gpsmon](https://gitlab.com/gpsd/gpsd/-/blob/1d622f5b2c7bf79fc117185be10048e7d4e73c66/man/gpsmon.adoc)
and [timing guidance](https://gitlab.com/gpsd/gpsd/-/blob/1d622f5b2c7bf79fc117185be10048e7d4e73c66/www/gpsd-time-service-howto.adoc).
Receiver-specific validity and timepulse behavior must be checked against the
identified module's u-blox documentation and actual configuration; generic
M8 or older LEA examples do not select a mode for this hardware.

#### OPT-003: serial latency, scheduling and IRQ affinity

Evaluated on October 12, 2026. Establish a bound capture and actual configuration
before diagnosing the serial pipeline. Measure serial/coarse GPS timing and
PPS timing separately, then identify any driver or scheduling contribution.

| Item | Disposition and reason | Placement |
| --- | --- | --- |
| OPT-003-01: infer a kernel latency problem from serial jitter | Collect a timestamped baseline first: actual UART driver/device, receiver protocol/message schedule, baud, GPSD/SHM mappings, full ntpq association status, offsets over time and applied calibration. Receiver emission, serialization and sampling can contribute; a single serial jitter value does not identify the cause. | Phase 3 hardware/time baseline; Phase 3A diagnosis |
| OPT-003-02: setserial ttyAMA0 low_latency and rc.local | Reject the proposed 8250 explanation for the expected Pi PL011 path; verify the actual driver rather than assuming a device name. Upstream Linux 6.18 serial_core can retain the low_latency flag, but the inspected PL011 driver does not implement a special low_latency delivery path. A successful ioctl or displayed flag is not proof of improved timing. Check the actual Raspberry Pi kernel before any applicable experiment; do not add setserial or rc.local persistence on this basis. | Phase 3 UART identification; Phase 3A only if driver evidence justifies a trial |
| OPT-003-03: gpsd.service FIFO override | Reject this deployment target: the approved lifecycle is combined timeservice.service, not a separate gpsd.service. A scheduling policy on the combined supervisor can be inherited by GPSD, ntpd and helpers, unless explicitly reset or changed; it is not a GPSD-only adjustment. Any per-process/thread policy needs a separately reviewed lifecycle adaptation and observed effective scheduling. | Phase 3A, after baseline service acceptance |
| OPT-003-04: FIFO 45 and Nice=-20 guarantee instant processing | Unadopted experiment with no guaranteed latency or jitter result. FIFO can preempt normal runnable work but does not eliminate IRQ, I/O, locks or throttling delays and can starve other work. Nice is not the FIFO priority control. Inspect actual thread policy, privileges, RT limits/budget and built-in behavior: pinned GPSD attempts nice(-10) as root; NTPsec can request FIFO with -N/-P. Do not infer effective policy from a unit file alone or add arbitrary priority 45. | Phase 3A; explicit starvation/access recovery and measured benefit required |
| OPT-003-05: serial IRQ on CPU 2 adjacent to isolated CPU 3 | Conditional experiment, not a selected configuration. OPT-001 did not adopt CPU 3 isolation. CPU numbering does not establish an optimal cache placement; IRQ affinity does not pin GPSD/ntpd tasks or the separate GPIO PPS path. Identify the IRQ from the actual driver/sysfs mapping and counters, not a presumed tty name or IRQ 35. Check routability/shared users, allowed/effective affinity and any active irqbalance. Hex mask 4 denotes CPU 2; verify delivery and persistence without hard-coding a boot-dependent IRQ number. | Phase 3A |
| OPT-003-06: restart gpsd/ntpsec to clear SHM and compile calibration | Reject the commands for this source deployment. Use the reviewed combined service transaction if a restart is needed; do not activate competing stock units. Restarting does not prove SysV SHM resources were removed and is not a compilation step for ntp.conf. Do not delete/reset shared memory as an optimization; preserve ownership/state and define any recovery separately. | Phase 3 lifecycle; approved Phase 3A transaction if needed |
| OPT-003-11: next-day logging | Recommended measurement approach after baseline service acceptance. Scope receiver/SHM/NTP/client records, polling/retention and comparable load/thermal conditions; a 24-hour window can sample a daily cycle but does not alone prove convergence or absolute accuracy. Logging, receiver access and any scheduled plot generation still need the defined execution approval. | Phase 3 baseline instrumentation; Phase 3A |

No serial flag, RT priority, CPU/IRQ placement, IPC reset
or restart is adopted. Inspect effective behavior before testing one justified
change; retain a conservative source-selection and restoration path.

Evidence: pinned NTPsec [priority options](https://gitlab.com/ntpsec/ntpsec/-/blob/42b5703303c8c7e6513f3a119cfab670924dd7be/ntpd/ntpd.c);
pinned GPSD [priority handling](https://gitlab.com/gpsd/gpsd/-/blob/1d622f5b2c7bf79fc117185be10048e7d4e73c66/gpsd/gpsd.c);
upstream Linux 6.18 [PL011](https://github.com/torvalds/linux/blob/v6.18/drivers/tty/serial/amba-pl011.c)
and [serial core](https://github.com/torvalds/linux/blob/v6.18/drivers/tty/serial/serial_core.c);
[IRQ affinity](https://www.kernel.org/doc/html/latest/core-api/irq/irq-affinity.html)
and systemd 257 [execution policy/inheritance](https://github.com/systemd/systemd/blob/v257/man/systemd.exec.xml).
Upstream Linux is comparison evidence; the actual 6.18.50+rpt-rpi-v8 driver,
configuration and effective runtime policy remain authoritative on the node.

#### OPT-004: GPSD time-service HOWTO tuning

Evaluated on October 12, 2026 against GPSD 3.27.5, NTPsec 1.2.5 and the
Pi 4 UART/GPIO-PPS and Ethernet paths. Only applicable proposals are retained.
The HOWTO is guidance; the pinned applications and observed Raspberry Pi
kernel, driver and link state determine the supported controls.

| Item | Disposition and potential improvement | Placement |
| --- | --- | --- |
| OPT-004-01: GPSD continuous acquisition and kernel PPS | Baseline requirement already supported by timeservice=yes and pps-tools. Verify that GPSD continuously acquires without an interactive client, uses the observed kernel PPS device/API and exports fresh serial and PPS samples to the intended SHM units. Kernel capture avoids userspace wakeup delay in the PPS timestamp. Verify device access and privilege drop in the combined service; package presence alone does not prove kernel PPS use. | Phase 3 hardware/runtime acceptance |
| OPT-004-02: ntpviz measurement procedure | Adopt the measurement method for approved tuning trials. Collect bounded loopstats and peerstats; correlate local offset, frequency, jitter and wander with separate serial/PPS peer offsets and client measurements. Add compatible temperature/receiver logs when needed. Generate plots off-host with the pinned NTPsec tools/modules and reviewed analysis dependencies. Use sustained serial measurements to assess calibration only when justified. | Phase 3 instrumentation; Phase 3A; maintenance |
| OPT-004-03: shorten PPS SHM polling | Worth testing after baseline acceptance. NTPsec's SHM driver supports minpoll/maxpoll down to 0, a one-second interval. Compare the accepted interval with shorter fixed intervals on the PPS association alone; serial and network polling are separate decisions. More frequent discipline updates may reduce offset/jitter but can worsen frequency stability. Select from matched ntpviz/client results after several hours of convergence, not the smallest setting by default. | Phase 3A |
| OPT-004-04: ARP and network polling | Conditional network-path trial. Observe IPv4 ARP and IPv6 neighbour discovery for the actual next hop, including the gateway for routed upstreams, and correlate resolution with delay/offset spikes. Linux reachability ageing is not a fixed 60-second deletion deadline. If resolution is a measured cause, compare an agreed local-server polling profile; a maxpoll of 5 caps the interval at 32 seconds only with a compatible minpoll. Respect upstream rate policy and load. This cannot improve GPIO PPS capture. | Phase 3 network baseline; Phase 3A |
| OPT-004-05: thermal stability | Required cooling/power health is already in Phase 3. Correlate fan transitions, temperature and load with frequency wander, PPS timing and client error. Consider a supported, steadier fan policy only if it improves measured stability without overheating, undervoltage or excessive wear. Preserve the installed PoE HAT's safety controls; an optional policy must be rendered and accepted per node. | Phase 3 thermal acceptance; Phase 3A |
| OPT-004-06: power-saving and scheduling ticks | Conditional experiments, not mandatory boot settings. Governor tuning remains OPT-001-06. Assess nohz=off separately on the actual kernel; it disables idle tick suppression and may reduce wakeup variation while adding interrupts, power and heat. Verify kernel support, effective idle/tick behavior and workload, then compare PPS/client metrics and thermal stability with reboot restoration. Do not combine it with the CPU-isolation trial. | Phase 3A |
| OPT-004-07: IEEE 802.3az / EEE | High-priority network-latency candidate if supported and active. Inspect the observed Ethernet driver, host and switch-port EEE negotiation, LPI state, link errors and baseline client delay. Compare EEE enabled/disabled on one controlled link; wakeup latency is a plausible network timestamp effect. Evaluate host and switch controls separately and accept only repeatable benefit with link/access, power/thermal and reboot checks. Do not assume a supported feature is active. | Phase 3 network baseline; Phase 3A; switch changes owned by homelab-network |
| OPT-004-08: software-timestamped PTP | Technically applicable as an optional LAN service extension, deferred pending a client precision requirement. It may improve selected wired clients' synchronisation but does not improve the GPS/PPS input or ordinary NTP clients automatically. Verify software TX/RX timestamp support on both ends, network transport/domain, switch path and LinuxPTP provenance. Preserve NTPsec as the server's clock owner; any PTP-to-NTP SHM integration needs unique units and prevention of source feedback, competing clock servos and election loops. Define GPS-loss/holdover announcements, client failover and recovery before an architecture change or installation. | Separate architecture/network/client decision before Phase 3A implementation |

Start with ntpviz and thermal/link observation; prioritise PPS polling and
active EEE trials when their baselines justify them. ARP, governor and tick
changes require evidence of a relevant contribution. PTP remains an optional
extension, not a deployment prerequisite. No tuning values, new packages or
live changes are adopted by this review.

Evidence: the requested [GPSD HOWTO](https://github.com/ntpsec/gpsd/blob/master/www/gpsd-time-service-howto.adoc)
and the [pinned GPSD copy](https://gitlab.com/gpsd/gpsd/-/blob/1d622f5b2c7bf79fc117185be10048e7d4e73c66/www/gpsd-time-service-howto.adoc);
pinned NTPsec [SHM polling](https://gitlab.com/ntpsec/ntpsec/-/blob/42b5703303c8c7e6513f3a119cfab670924dd7be/docs/driver_shm.adoc),
[ntpviz](https://gitlab.com/ntpsec/ntpsec/-/blob/42b5703303c8c7e6513f3a119cfab670924dd7be/docs/includes/ntpviz-body.adoc)
and [statistics](https://gitlab.com/ntpsec/ntpsec/-/blob/42b5703303c8c7e6513f3a119cfab670924dd7be/docs/includes/mon-commands.adoc);
Linux [ARP](https://man7.org/linux/man-pages/man7/arp.7.html),
[neighbour handling](https://github.com/torvalds/linux/blob/v6.18/net/core/neighbour.c),
[tick suppression](https://www.kernel.org/doc/html/latest/timers/no_hz.html)
and [GENET EEE controls](https://github.com/torvalds/linux/blob/v6.18/drivers/net/ethernet/broadcom/genet/bcmgenet.c);
[LinuxPTP configuration](https://www.linuxptp.org/documentation/ptp4l/).

#### OPT-005: Uputronics u-blox M8 receiver tuning

Evaluated on October 12, 2026. These receiver settings apply independently
of the client time daemon. Evaluate them with the existing GPSD/NTPsec SHM
path; exact module, firmware and protocol support remain to be verified.

| Item | Disposition and potential improvement | Placement |
| --- | --- | --- |
| OPT-005-01: receiver identity and protocol version | Required before configuration. Capture MON-VER, module/HAT identity, supported GNSS and affected configuration blocks. Select ubxtool's protocol version from the receiver response, not a copied value of 18. Preserve UART 115200 and use the pinned GPSD tool with an explicitly selected device/endpoint. | Phase 3 receiver baseline; all receiver trials |
| OPT-005-02: NAV5 stationary dynamic model | Strong candidate for the fixed antenna. Model 2 assumes stationary operation and is intended for timing/static applications. Trial changing only the dynamic-model field, retaining existing fix mode, masks and other navigation settings. Compare receiver time validity/accuracy, PPS continuity and NTP/client metrics; a suitable model is not itself proof of improved UTC accuracy. | Phase 3A |
| OPT-005-03: PMS full power | Worth testing if the receiver is currently using power saving. CFG-PMS setup 0 selects full power on supporting firmware; protocol support starts at 18. Read the complete power configuration before/after because predefined setups can change multiple settings. Assess continuous tracking, PPS/SHM availability, time accuracy, power and heat. If already full power, retain it without a redundant trial. | Phase 3 receiver baseline; Phase 3A if needed |
| OPT-005-04: GNSS constellation selection | Conditional reception/timing experiment. Verify model/firmware capability, simultaneous-constellation and channel-allocation limits, antenna/filter bandwidth and actual used satellites. Compare supported combinations over representative sky conditions. Enabling Galileo or disabling GLONASS/SBAS is not a universal improvement; retain a working combination unless measured timing/availability improves. Any change disabling an active GNSS includes the manufacturer's cold-start recommendation and recovery window. | Phase 3A |
| OPT-005-05: NMEA 4.10 | Conditional protocol compatibility setting when Galileo/BeiDou NMEA reporting is used. It changes message representation, not enabled constellations or PPS precision. Verify support and existing format, then check GPSD parsing, UART message load, valid time and SHM freshness. Retain existing working UBX/NMEA output unless a reporting requirement justifies a change. | Phase 3 receiver/GPSD compatibility; Phase 3A with a constellation trial |
| OPT-005-06: ITFM interference monitor | Optional diagnostic improvement. Monitor supported UBX-MON-HW interference indicators and trial ITFM only where useful. Bind the active-antenna classification to the actual antenna/splitter path; it does not configure antenna power. The monitor needs a good initial fix and an interference baseline for interpretation. Measure detection usefulness and false alarms; enabling telemetry does not remove interference or establish better timing. | Phase 3A diagnostics; maintenance if adopted |
| OPT-005-07: TP5 antenna cable delay | Potential absolute PPS bias correction, not a serial-jitter adjustment. Derive the value from this installation's cable lengths/types, propagation data and splitter/RF-path delay, with uncertainty and independent timing validation where available. Treat each receiver branch separately. Read/merge the complete supported TP5 message, preserving pulse index, period, width, polarity, time grid, locked/unlocked behavior and other delays. Do not duplicate the same correction elsewhere. | Phase 3 PPS configuration; Phase 3A calibrated refinement |
| OPT-005-08: save and cold start | Required persistence/recovery procedure for adopted settings, not an optimization. Verify supported storage rather than assuming EEPROM. Read back actual values, test in volatile state where supported, and save only the accepted profile with the intended configuration/storage masks. Cold start is conditional on the changed settings and firmware guidance, particularly disabled GNSS; define PPS interruption, reacquisition and valid-time acceptance. Receiver configuration survives independently of the SD card, so rollback must restore the receiver as well. | Approved receiver transaction; Phase 3 reboot/persistence acceptance; maintenance |

Prioritise identity/configuration capture, then a stationary-model trial and
full-power trial where needed. Constellation selection and cable compensation
require additional reception/path evidence. No receiver command, setting or
persistent profile is adopted by this evaluation.

Proposal: [Uputronics M8 tuning guide](https://github.com/tiagofreire-pt/rpi_uputronics_stratum1_chrony/blob/main/steps/advanced_ublox_m8_tuning.md).
Authority: u-blox [M8 receiver/protocol manual, UBX-13003221 R28](https://content.u-blox.com/sites/default/files/products/documents/u-blox8-M8_ReceiverDescrProtSpec_UBX-13003221.pdf),
sections 4.2, 8.1, 13.4, 15.2/15.3, 19 and the applicable CFG messages;
pinned GPSD [ubxtool manual](https://gitlab.com/gpsd/gpsd/-/blob/1d622f5b2c7bf79fc117185be10048e7d4e73c66/man/ubxtool.adoc)
and [UBX command implementation](https://gitlab.com/gpsd/gpsd/-/blob/1d622f5b2c7bf79fc117185be10048e7d4e73c66/gps/ubx.py).

#### OPT-006: applicable system tuning

Evaluated on October 12, 2026 for Pi 4/Trixie and the source-built
GPSD/NTPsec stack. Retain applicable proposals only; do not transfer another
board's settings or observed results. Existing UART/PPS mapping, GPU allocation,
daemon scheduling, thermal policy and PTP decisions remain in OPT-001,
OPT-003 and OPT-004 rather than duplicating those trials.

| Item | Disposition and potential improvement | Placement |
| --- | --- | --- |
| OPT-006-01: CPU/cache topology inspection | Useful input to an affinity experiment, not an optimization itself. Inspect CPU/cache topology and effective task/IRQ placement using available sysfs/tools first. hwloc is optional analysis tooling if its visualisation adds value; it is not a timing-stack dependency. Do not install it merely to confirm four cores. | Phase 3A baseline; OPT-003 affinity trials |
| OPT-006-02: Ethernet interrupt coalescing | Strong new network-latency candidate. Identify the actual driver/kernel and supported timer, frame-threshold and adaptive controls. Upstream Linux 6.18 GENET exposes RX delay, RX/TX frame thresholds and adaptive RX; RX timing is quantised in approximately 8.192-microsecond steps. Trial lower effective RX moderation against the accepted settings, with adaptive behavior controlled and readback verified. Reduced receive delay can increase IRQ/CPU load and disturb PPS scheduling; compare client offset/jitter, packet loss, PPS/SHM health and thermal behavior under idle and representative network load. | Phase 3 network baseline; Phase 3A |
| OPT-006-03: service and maintenance activity | Conditional housekeeping based on observed active work and measured load. Review dependencies before disabling an unused service. Preserve Avahi for required mDNS, supported networking/access, time-service supervision, mail/needrestart reporting, leap maintenance and security updates. If update activity causes a measured disturbance, review its schedule/resource policy within the maintenance lifecycle rather than permanently masking update services. | Phase 3 service acceptance; maintenance; Phase 3A comparison |
| OPT-006-04: swap and memory pressure | Retain a working memory policy until measurement justifies a change. The retained package manifest records rpi-swap and systemd-zram-generator; inspect actual swap devices, priorities, generator configuration and any disk backing/writeback. Compressed-RAM swap is different from SD-card swap. Correlate paging/compression, memory pressure, disk I/O and OOM events with timing under operational and build/maintenance load. Review disk-backed changes separately; disabling all swap can trade latency for killed services without any benefit when swap is idle. | Phase 3 memory/storage baseline; Phase 3A if pressure is observed |
| OPT-006-05: onboard audio | Optional headless housekeeping only when the audio device/services are actually enabled and unused. A supported dtparam=audio=off setting may remove unused resources; no timing benefit is assumed for an inactive audio path. Verify console/recovery requirements and observed interrupts/load, then measure any claimed benefit and retain exact boot restoration. | Phase 3 hardware profile; Phase 3A if justified |
| OPT-006-06: panic reboot timeout | Availability/recovery proposal, not precision tuning. A positive kernel.panic value schedules reboot after a kernel panic; it does not recover every hang. Consider only after boot/access recovery, peer service and shared-antenna power continuity are proven. Choose the delay with crash-evidence retention, watchdog policy and boot-loop/manual-recovery controls; do not adopt an arbitrary ten-second delay. | Phase 3 recovery acceptance; maintenance/reliability |

Prioritise a measured coalescing trial after network/time baseline acceptance.
Service and memory-policy changes need evidence of active interference; audio
and topology tooling are optional housekeeping. No new package, boot setting,
service disablement, memory policy or recovery timeout is adopted here.

Proposal: [advanced system tuning guide](https://github.com/tiagofreire-pt/rpi_uputronics_stratum1_chrony/blob/main/steps/advanced_system_tuning.md).
Evidence: Linux 6.18 [GENET coalescing implementation](https://github.com/torvalds/linux/blob/v6.18/drivers/net/ethernet/broadcom/genet/bcmgenet.c),
kernel [zram behavior](https://www.kernel.org/doc/html/latest/admin-guide/blockdev/zram.html)
and [panic policy](https://www.kernel.org/doc/html/latest/admin-guide/sysctl/kernel.html#panic),
[zram-generator configuration](https://github.com/systemd/zram-generator/blob/v1.2.1/man/zram-generator.conf.md)
and systemd 257 [timer scheduling](https://github.com/systemd/systemd/blob/v257/man/systemd.timer.xml).
The actual Raspberry Pi kernel, effective units and generated swap state
remain authoritative on the target.

#### OPT-007: public NTS upstreams for Arlington, Texas

Evaluated on October 12, 2026 for the operator's Arlington, Texas location.
Public NTS upstreams provide authenticated network sanity/fallback references
alongside the existing GPS/PPS profile. Provider documentation establishes
candidates, not local performance or accepted live associations.

| Candidate | Provider evidence and disposition |
| --- | --- |
| time.cloudflare.com | Cloudflare documents public NTS and global anycast. First candidate for a local-path trial; routing from the actual ISP determines the endpoint and delay. DFW delivery, lowest latency and superior reliability are not established by the anycast claim. |
| ohio.time.system76.com | System76 currently lists this as a public NTS service. US regional comparison candidate; accept from actual NTP delay, offset/jitter, availability and authenticated traffic. |
| oregon.time.system76.com | System76 currently lists this as a public NTS service. Regional/path comparison alternative to Ohio; both share one operator and do not establish independent-provider diversity. |

| Item | Disposition and potential improvement | Placement |
| --- | --- | --- |
| OPT-007-01: locality and ranking | Compare from each NTP node's actual egress path, separately for advertised IPv4/IPv6 service. Measure authenticated NTP delay distributions, offset/jitter, dispersion, loss and availability across representative windows. Geographic names or TLS connection times alone cannot rank time-transfer quality or establish one-way path symmetry. Preserve DNS/route and provider identity with the comparison. | Phase 3 upstream/network acceptance; Phase 3A refinement |
| OPT-007-02: correct NTS configuration | Use provider-confirmed FQDNs with NTPsec's server hostname nts syntax and normal certificate validation. NTS-KE normally uses TCP 4460; time packets use the negotiated NTP destination/port, normally UDP 123. The key-exchange port is not the NTP data port. Keep poll settings in the separately reviewed source profile; no geographic claim justifies a fixed poll ceiling. | Phase 3 runtime configuration and network policy |
| OPT-007-03: trustworthy selection and diversity | Compare operator, network/path and timing-reference dependencies as well as delay. Keep a compatible UTC/leap policy and independently useful sanity sources; NTS authenticates the sender and packets, not the correctness of its clock or network path. Multiple System76 regions or multiple Cloudflare addresses do not count as multiple independent operators. Define the final set and GPS/PPS-loss behavior in the accepted host profile. | Phase 3 source-selection acceptance; maintenance |
| OPT-007-04: authentication and reachability | Require valid hostname/chain/time checks, successful NTS-KE/cookies and sustained authenticated NTP replies for every chosen association. A completed TLS handshake alone is insufficient. Confirm CA store, sane RTC/system time, DNS and egress, including NTP-node exceptions to any UDP 123 redirection and negotiated destinations. Do not bypass validation or silently replace an NTS source with unauthenticated NTP to pass acceptance. | Phase 3; Phase 6 network policy; Phase 8 end-to-end checks |
| OPT-007-05: maintained provider list | Recheck provider service/access policy, DNS, certificate renewal, leap behavior and measured path quality during maintenance. Retain only verified candidates in the rendered configuration; community lists are discovery leads, not operational acceptance. Provider withdrawal or changed behavior requires a reviewed replacement and regression checks. | Installation assets after profile selection; maintenance |

These three names are a provisional shortlist, not a final geographically
optimised or independently diversified profile. No upstream configuration,
network allowance, provider probe from an NTP node or source-selection change
was executed or adopted by this review.

Evidence: Cloudflare [NTS documentation](https://developers.cloudflare.com/time-services/nts/)
and [anycast NTP service](https://developers.cloudflare.com/time-services/ntp/);
System76's [provider-maintained endpoint list](https://system76.com/time/);
pinned NTPsec [NTS client configuration and verification](https://gitlab.com/ntpsec/ntpsec/-/blob/42b5703303c8c7e6513f3a119cfab670924dd7be/docs/NTS-QuickStart.adoc),
[NTS options](https://gitlab.com/ntpsec/ntpsec/-/blob/42b5703303c8c7e6513f3a119cfab670924dd7be/docs/includes/nts-commands.adoc)
and [ntpq diagnostics](https://gitlab.com/ntpsec/ntpsec/-/blob/42b5703303c8c7e6513f3a119cfab670924dd7be/docs/includes/ntpq-body.adoc).

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
