# NTPsec deployment history

The [architecture plan](docs/ntp-architecture-deployment-plan-v1.0.md) owns
approved design and acceptance criteria. [OPERATIONS](docs/OPERATIONS.md) owns
the reproducible procedure. This history records milestones, deviations,
observations and the next deployment gate. Entries do not authorize live action.

## Current deployment state

Last reconciled: October 12, 2026. These are retained observations, not a new
live inspection.

| Component | Accepted state | Still pending |
| --- | --- | --- |
| Rebuilt node | Former j1-svntp1 renamed j2-svntp1; spare-card first boot accepted | Full hardware/time/network acceptance |
| OS/access | Debian 13 Trixie, aarch64, kernel 6.18.50+rpt-rpi-v8; fixed Ethernet IPv4/ULA, RA, DNS, routes, dual-stack egress and pinned-key SSH accepted | Reboot persistence; Wi-Fi disablement |
| Foundation | 686 package records; original foundation, pps-tools, bc and seven mDNS prerequisites accepted; installation control cleanup complete | Preserve accepted inventory and recheck it before further live changes |
| Source candidate | GPSD 3.27.5 and NTPsec 1.2.5; new mDNS-enabled build/tests/native staging accepted; 159-entry manifest; v5 evidence preserved | Native installation/readback/payload cleanup accepted; runtime discovery and configuration pending |
| Runtime | Native files reverified; v2 runtime discovery and cleanup accepted; copied_not_activated | Networking accepted; hardware/boot and account/cache/candidate stages prepared offline; final service configuration/cutover pending |
| Reporting | Needrestart policy installed, microcode checking disabled | Mailrise/msmtp, needrestart.sh and cron installation/delivery |
| Optimizations | OPT-001 through OPT-007 reviewed offline; Phase 3A and proposal register added | Accepted live timing/antenna/network baseline before any optional experiment |
| Primary | Preserved during standby rebuild, including shared antenna power | Its own fresh inspection and later separately approved rebuild |

The current accepted source stage is
`/home/ama/.ntp-source-build-mdns-20261012-v1`; the earlier v5 stage is preserved.
User-managed passwordless sudo for ama remains in place; its removal is an
end-of-project operator action. No cleanup here changes it.

## Approved deviations and decisions

| Decision | Date | Effect |
| --- | --- | --- |
| HW-001 | 2026-09-16 | Retain working 2018 PoE HAT; replace with PoE+ upon failure; preserve shared antenna power |
| OS-001 | 2026-09-16 | Clean Trixie rebuild before final dual-stack, DNS and UniFi work; one node at a time |
| Rebuild identity | 2026-10-08 | j2-svntp1 intentionally replaces the former j1-svntp1 hostname; historical evidence keeps its original name |
| Source lifecycle | 2026-10-10 | Signed, pinned GPSD/NTPsec source builds; retain combined timeservice supervision; exclude APT application packages |
| Receiver/profile | 2026-10-10 | Uputronics u-blox M8, timeservice=yes and magic_hat=yes; runtime UART 115200 |
| Installation assets | 2026-10-10 | Checked-in verified fetch tool and pinned manifests; large publisher binaries stay out of Git |
| NTP discovery | 2026-10-12 | Require NTPsec mDNS build support, runtime -m and Avahi; keep GPSD serial/PPS delivery through SHM |
| Optimization lifecycle | 2026-10-12 | Review proposals in Phase 3A; place required setup in existing phases; adopt optional tuning only after per-node measurements |

## Accepted milestones and retained observations

### August 10 and September 16: architecture and legacy baseline

Locked independent NTP nodes, permanent ULA suffixes ::50/::51, equal-priority
and equal-weight SRV records, and active/standby DNAT per family. Leap updates
use one four-week systemd schedule. Repository ownership is split across
inventory, DNS, network and monitoring repositories as specified in the plan.
The initial repository/inventory review found no complete NTP deployment assets
or accepted NTP inventory membership; those findings require a fresh review
before related changes.

The protected Debian 11 baseline remains useful recovery evidence, with its
original collector bytes and captures. Its overall acceptance remains false;
byte/hash verification does not close missing commands or coverage gaps.
The later v2 capture established the following historical facts:

- Pi 4 Model B Rev 1.4, revision c03114, approximately 4 GB RAM; Debian 11.11;
  original 64 GB card; firmware snapshot throttled=0x0.
- NTPsec 1.2.1+82-g7abe7fba6 and GPSD ran from /usr/local/sbin under
  timeservice.service. Its oneshot active/exited state did not supervise health;
  masked ntpd.service did not mean no running daemon.
- SHM(1)/PPS was selected with reach 377, system stratum 1 and leap 00.
  Both IP families had UDP 123 listeners. One authorized IPv6 loopback time
  request returned valid NTPv4, stratum 1 and leap 0 on September 16.
  IPv6 ntpq control timed out; external client acceptance remained unproven.
- dhcpcd owned the observed static IPv4 10.1.0.51/22; the planned permanent ULA
  was absent. Resolver contents did not prove DHCP/RA resistance.
- Captured leapfile expiration was June 28, 2027. Authenticity, effective usage
  and reload behavior remained open. No leap download was performed.
- Configuration review retained 420 paths and 148 stable regular-file hashes;
  three resolver mtimes were treated separately as runtime telemetry.
- Webmin, msmtp, munin-node and userspace watchdog were confirmed absent by
  the operator, consistent with sampled package/configuration non-discovery.
  Needrestart was manually installed; reporting/delivery was unaccepted.

Operator physical observations: Uputronics GPS/RTC HAT rev 5.9 (2020), rv3028
RTC, 2018 Raspberry Pi PoE HAT beneath it, and only the 40-pin header between
boards. A GPS Source L1G1A-STD antenna feeds a two-output Uputronics SMA splitter.
The primary j1-svntp supplies antenna power. Exact PPS GPIO, receiver firmware,
connector/wiring details and the primary's own HAT must still be established
before configuration. The September 16 read-only switch observation matched
USW Lite 8 PoE port 3, 1000 Mbps/full duplex, Class 3 and 2.88 W; allocation
and thermal margin were not established.

Physical recovery confirmations included a 128 GB SanDisk Max Endurance spare,
USB reader and previously working micro-HDMI KVM/laptop. Preserve the untouched
original card; confirmations are not a performed recovery test.

### October 8: media, recovery readiness and first boot

Selected the October 6 Raspberry Pi OS Lite arm64 Trixie image and verified
compressed/expanded integrity. Operator reported Imager write and verification
at 100 percent. The immutable first-boot/recovery bundle was approved under
SHA-256 04c6208589d6f4dc602cdb44403276e2ca79bc73725d018432678588c3c1e42c.

Pre-rebuild network evidence showed one source-limited IPv4 NTP redirect to
10.1.0.50:123; no standby DNAT was shown. This did not establish universal
failover or forwarding behavior. Final network policy remains a later stage.

The operator confirmed halt/power removal before the spare-card swap, original
card retention, normal observed fan/power and untouched primary/antenna wiring.
Thirteen first-boot checks accepted j2-svntp1, Debian 13 Trixie, aarch64,
6.18.50+rpt-rpi-v8, ext4 /dev/mmcblk0p2, Ethernet DHCP 10.1.0.137, IPv6 addresses
and RA default, SSH active and no listed failed units. Console and SSH ED25519
matched SHA256:yXiID8RObBoIejVpvr2KesaqIlocbSORyemD5dKrEys.
Wi-Fi was DOWN; disablement was not proven. Physical event times and individual
operator-command statuses were not supplied and are not inferred.

### October 8–10: authentication, resolution and package foundation

Scoped observations established Trixie package/source/key/hook inputs, Python
3.13.5 and its /usr/local module/ABI paths. Isolated signed metadata resolution
completed with dependency/simulation checks; temporary metadata sudo policy
was removed and verified. Later transactions used the operator's persistent
passwordless sudo without another temporary sudoers installation.

Original foundation installation added 44 packages, yielding 677 package
records. Its acceptance-only continuation completed validation and restored
transaction controls/automatic updates. The installed Pi 4 needrestart policy
retained kernel checks and list-only reporting; kernel status 1 indicated the
running/expected 6.18.50+rpt-rpi-v8 kernel matched, not a service/mail acceptance.

The PPS supplement then added pps-tools, yielding 678 records, and disabled
microcode checking as requested. The bc supplement yielded 679 records.
Both passed acceptance/cleanup; automatic-update disposition was restored.
Canonical fresh-foundation inputs now include all 46 additions, including
pps-tools and bc. These supplements are consumed historical operations, not
fresh-node installation specifications.

### October 10: authenticated source candidate accepted

Authenticated GPSD 3.27.5 and NTPsec 1.2.5 archives and signed tags, pinned
commits and compared archive/Git content. Trust provenance and exact source
inputs are retained in the recipe, public keyrings and private source evidence.
Both upstream suites and native DESTDIR staging completed unprivileged. The
acceptance-only continuation accepted the original 159-entry v5 candidate
without rebuilding or installing it. Twelve returned evidence records were
hash-verified; all eight original v5 records remained byte-exact.

| Accepted artifact | SHA-256 |
| --- | --- |
| v5 executed source bundle | fba4e9338a83a240b5f261360e7965ce5feb0000012992ffe02f26b5b46de55d |
| Acceptance-only bundle | 79e29a0018edf34eff2d5ce329be070fa1e6ebe47c78425ad05156fe97f1dd4b |
| Completion receipt | 8bc6f73e8b6f45bf111d1387b77f887e7121044b82c26c3405f34866e314e015 |
| Accepted release | 351d42abb619370bc930e032ba1916dec64f3f84ff93c79f04189f1f86b5bc9e |

Versions/manuals/modules, isolated Python ABI/imports, linkage, SHM/NTS/seccomp,
selected GPSD features/u-blox support, exact packages/PPS header and original
boot/access continuity passed. Claims are consumed. Nothing was installed live;
service, hardware and network acceptance remains pending.

### October 10: reproducibility corrections and consolidation

Durable code/tests now account for protected hard-linked native executables,
transaction phase-specific policy inputs, apt-listchanges' inherited FD above
stdio, and needrestart's packaged dpkg hook/helper. Source preparation retains
installed PPS headers, bc timing, explicit decoder/control-socket settings,
Waf's replacement PYTHONPATH and explicit standalone staging library/module
paths. These lessons stay in maintained code/tests rather than retry runbooks.

Added pinned image/package/source manifests, public verification keyrings,
verified fetching, accepted package/source references, and reusable reporting,
mail, combined-service and leap templates. The three maintained documents are
the architecture, operations recipe and this history. Private current records
index accepted provenance; an explicit cleanup review protects original
observations, executed bundles and recovery inputs. The operator approved
retirement of 55 superseded documents and 25 scoped evidence paths. Cleanup
removed 14,763 generated/unexecuted-workspace files and the unused September
image, totaling 1,339,399,784 bytes. Executed bundles/terminal records, accepted
inputs and the selected October image remain. No target contact occurred.

### October 10: fresh foundation preparation implemented offline

Foundation preparation now uses a checked-in recipe and fresh hash-bound snapshot
and resolution evidence. The approved offline refactor removed historical bundle,
plan, receipt and package-count dependencies. It renders target/key/stage bindings,
calculates exact additions, preserves Multi-Arch identities and handles satisfied
requirements without an APT install call. Tests include preparation in an isolated
repository with no historical evidence, different inventory sizes, partial/zero
additions, dependency/control conflicts, drift and exclusive output.

### October 12: fresh foundation snapshot accepted

Confirmed the foundation refactor was committed and pushed as `5eb1aeb` before
preparing the next action. Architecture, operations and history agree on the
accepted foundation/source candidate and pending live application deployment.
The reusable preflight transport now seals all capture inputs, stages them as
protected root-owned files, collects once, retains terminal evidence and supports
bound readback/cleanup. Offline tests cover success, held results, drift, busy
staging, missing receipts and replay rejection. No new target contact occurred.

The separately approved capture was then attempted. Its terminal readback held
on `/bin` while checking an absent helper; the checker rejected the normal
merged-/usr alias. No snapshot was accepted and no package state changed.
The approved cleanup verified and removed the exclusive staging directory.
Collection was not replayed. The offline correction now validates only the
root-owned `/bin` and `/sbin` aliases with exact canonical destinations, in both
snapshot capture and foundation input checks; unexpected links remain held.

The corrected capture was separately approved and executed once. Terminal
readback and the full snapshot validator passed: 679 package records, 197
protected inputs and eight configuration directories; no active time daemons
and no password-database read. The snapshot SHA-256 is
`a9775dac0803f65edc5344b8b55844bf8d049a61100f374bbb917899fd11e4a6`.
Conditional cleanup verified and removed the root-owned stage. Accepted snapshot,
archive and terminal records remain in the private current evidence directory.
No package, service, policy or user-managed sudo configuration changed.

### October 12: first optimization proposal evaluated

Added Phase 3A and the OPT-001 register to the governing plan, with the
measurement/recovery workflow in OPERATIONS. Reviewed package selection, CPU
isolation, governor/CPU frequency, GPU allocation, UART/Bluetooth/PPS overlays,
competing time services, NetworkManager and PPS verification. Baseline setup
stays in its existing phases. Optional tuning has no demonstrated benefit yet
and was not added to package manifests or persistent host settings.

Pinned-source ntpviz is already in the accepted staged file manifest; optional
plotting dependencies and statistics deployment remain unapproved. Exact PPS
GPIO/edge and current hardware/driver mapping need verification. The proposal
does not establish zero jitter or absolute accuracy. No target contact,
packages, boot configuration, affinity, governor, service or reboot changes
were performed during this documentation evaluation.

### October 12: antenna placement and calibration proposal evaluated

Added OPT-002 to the governing register and the antenna/SHM/fallback workflow
to OPERATIONS. Indoor placement is an unverified scenario, not a new target
observation. The shared antenna makes relocation a common physical change.
Selection thresholds are global: mindist 0.002 is a conditional experiment;
maxdist 1.5 is already the pinned default. No calibration value is adopted.
Receiver time validity and PPS measurements remain required.

The first recommended stage is scoped receiver/SHM/NTP logging and placement
assessment, followed by evidence-based calibration only if a stable bias is
demonstrated. Preserve valid upstream failover, actual SHM mappings and the
source-built `/etc/ntp.conf` path. No receiver access, antenna movement,
logging deployment or live configuration change was performed. Existing
snapshot/mDNS prerequisite and build gates remain pending.

### October 12: serial latency and scheduling proposal evaluated

Added OPT-003 and the corresponding operations workflow. Rejected the
8250/ttyAMA0 explanation and stock GPSD/NTPsec overrides/restarts for this
combined service. Real-time scheduling and IRQ placement remain conditional
experiments, with actual driver, per-thread policy, inheritance and recovery
evidence required. Upstream Linux 6.18 PL011/serial-core and systemd 257 policy
sources were inspected; they do not establish the effective downstream kernel
or live scheduler state.

No target access, package, serial flag, IRQ, scheduler, calibration, IPC or
restart change was performed. The existing
fresh snapshot/mDNS prerequisite and build gates remain unchanged.

### October 12: GPSD HOWTO tuning evaluated

Added applicable HOWTO proposals as OPT-004 and the measurement workflow in
OPERATIONS. Prioritised bounded ntpviz/thermal/link observation, followed by
measured PPS SHM polling and active EEE trials. ARP/network polling, governor,
idle-tick and fan-policy changes remain conditional experiments. Software PTP
is a deferred LAN/client extension requiring a separate architecture decision.
The evaluation uses the requested HOWTO, pinned application documentation and
primary Linux/LinuxPTP sources. No target contact, package, configuration,
network or service change was performed. The fresh snapshot/mDNS prerequisite
and source-build gates remain unchanged.

### October 12: Uputronics M8 tuning evaluated

Added applicable receiver proposals as OPT-005 and the receiver transaction
workflow in OPERATIONS. Stationary navigation and full power where needed
are the first candidates after exact module/firmware/configuration capture.
Constellation choice, NMEA format, interference diagnostics and branch-specific
TP5 delay remain conditional on capability and measurements. Persistence and
cold-start recovery must restore the receiver independently of the SD card.
Reviewed the supplied guide, u-blox UBX-13003221 R28 and pinned GPSD commands.
No receiver contact, live setting, save or reset occurred; existing deployment
gates remain unchanged.

### October 12: applicable system tuning evaluated

Added OPT-006 and the system/network trial procedure in OPERATIONS.
Ethernet coalescing is the main new candidate, with driver-specific controls
and effective readback required. Service activity, swap/memory pressure,
unused audio and panic recovery are conditional housekeeping/reliability
reviews. Existing topology/affinity, thermal and other tuning decisions are
reused. Retained package records identify rpi-swap/zram-generator for fresh
memory-state inspection. Required mDNS and maintenance remain preserved.
No target contact, package, service, boot, swap or recovery policy changed;
the existing deployment gates remain unchanged.

### October 12: Arlington public NTS candidates evaluated

Added OPT-007 and the public-upstream selection procedure in OPERATIONS.
Cloudflare and System76 provider documentation supports the provisional
Cloudflare/Ohio/Oregon shortlist. Local routing/performance, operator diversity
and authenticated associations still need scoped per-node acceptance; no DFW
path or lowest-latency claim is accepted. Unconfirmed community entries were
omitted. Kept valid NTPsec syntax and distinct NTS-KE/NTP network checks, with
normal certificate validation and no insecure fallback. No NTP-node contact,
upstream change or network mutation occurred; deployment gates remain unchanged.

### October 12: revised foundation snapshot v3 prepared

Reconciled OPERATIONS with the pending mDNS prerequisite delta and new
source-build acceptance. Extended offline snapshot sealing to retain and bind
the current installation-assets manifest controller-side, without adding
collector inputs. The regression checks include rejection of a manifest/spec
binding mismatch. All 56 pinned foundation requirements validate offline.

Prepared [v3 review](/home/aaron/code/.local-evidence/homelab-ntp/current/fresh-foundation-preflight-20261012-v3/review.md)
for j2-svntp1 with operation ID
`foundation-mdns-snapshot-20261012t202254z`. Bundle SHA-256:
`b22386e29521b628a9c6d2a9191909f4b62b3bebfd489653c250b480f7f1e11b`.
The expected hostname/kernel/SSH key comes from the retained accepted capture;
the new operation verifies identity live before collection. Preparation and
validation were offline. No target contact, new capture, metadata refresh or
package action occurred; prior executed evidence is preserved.

### October 12: revised foundation snapshot v3 accepted and cleaned up

Executed the approved v3 bundle once on j2-svntp1. Collection, bound terminal
readback and cleanup each returned matching transport/worker status 0.
The strict host-key and target identity checks passed; the full snapshot
validator accepted 679 package records, 197 protected inputs and eight
configuration directories. No active ntpd/gpsd process was observed and the
password database was not read.

Snapshot SHA-256:
`bb1906d5fa9f62263655654e1fe3c27fe560bbb5577470fad4f9196d72cbb6c6`.
Collected at `2026-10-12T20:30:41Z` against the current recipe/pinned-manifest
binding. [Acceptance](/home/aaron/code/.local-evidence/homelab-ntp/current/fresh-foundation-preflight-20261012-v3/acceptance.json)
and [cleanup receipt](/home/aaron/code/.local-evidence/homelab-ntp/current/fresh-foundation-preflight-20261012-v3/cleanup-result.json)
are retained with complete controller/transport evidence and the executed
bundle. Cleanup verified and removed only the approved root-owned stage.
No package refresh/install, service/policy/update change, sudoers change or
reboot was performed. Metadata resolution remains unexecuted and requires
its own sealed review and approval.

## Exact resume point

The current recipe requires mDNS support and runtime `-m`; NTPsec retains SHM
because GPSD owns UART/PPS and exports both signals. The revised foundation
snapshot, metadata resolution, seven-package supplement and mDNS-enabled source
build are accepted. The exact accepted foundation contains 686 package records.
Earlier 679-package snapshots/resolutions are execution records only; future
foundation transactions require a fresh accepted snapshot.

The destination inspection supplied the accepted absent pre-state. Native
GPSD/NTPsec installation, terminal readback and payload cleanup now passed:
all 159 release entries are installed with verified hashes/links and ownership.
The result is `copied_not_activated`. Preserve both source workspaces and all
executed privileged code, baseline records, native journal/backups and receipts.
Do not replay the consumed inspection or installation.

V2 runtime discovery, terminal acceptance and observation-stage cleanup passed.
All installed release entries and parent/target continuity were verified.
No matching UART/PPS/RTC device nodes were observed; the serial console is still
requested and GPS UART/PPS/RTC overlays are absent. Runtime ntp/ntpd/gpsd accounts and
groups are absent. Native Python package roots are on the isolated root search
path, and /usr/local/lib is configured, but libgps is absent from the loader cache.
Avahi and systemd-timesyncd are active; application time-service units are absent.

Next prepare host networking, verified UART/PPS/RTC bring-up, runtime accounts and
bounded loader/runtime validation from this accepted report. Review remaining
physical wiring, privilege/access, listener/upstream/configuration and recovery
choices before rendering host configuration and combined-service cutover.
Fixed dual-stack networking precedes service activation under Phase 3. Mail/cron,
leap maintenance, hardware/time/client, DNS/UniFi and reboot acceptance remain
pending. No further target contact, cache refresh, deployment or activation is
authorized by this history entry.

### October 12: revised snapshot-bound metadata resolution sealed

Prepared the [resolution review](/home/aaron/code/.local-evidence/homelab-ntp/current/fresh-foundation-resolution-20261012-v3/review.md)
offline for j2-svntp1, ama UID 1000, 10.1.0.137 and kernel 6.18.50+rpt-rpi-v8.
Operation ID: `foundation-resolution-20261012-v3`.
Bundle SHA-256:
`d1ce84487410d0dcdcd91457b5865b6cee7fe86f49b948b3c8627d8d956a7922`.
It binds the accepted v3 snapshot
`bb1906d5fa9f62263655654e1fe3c27fe560bbb5577470fad4f9196d72cbb6c6`,
the current recipe, pinned manifest, resolver policy and console-confirmed SSH key.
Collection expires October 13, 2026 at 20:30:41 UTC.

Offline comparison found seven missing pinned requirements:
libavahi-compat-libdnssd-dev, libavahi-compat-libdnssd1, libavahi-client-dev,
libavahi-client3, libavahi-common-dev, libdbus-1-dev and libsystemd-dev.
These are preparation expectations; signed metadata and native simulation must
confirm the complete dependency closure and exact transaction delta.

The execution review covers protected root-owned staging, one isolated signed
APT metadata refresh and combined foundation simulation, conditional terminal
readback, acceptance and verified cleanup. It rechecks the full accepted target
snapshot before and after resolution. Lost transport permits one bound readback;
held, incomplete or changed state requires separately reviewed recovery without
replay. Live APT lists, installed packages, services and update policy are outside
this scope. Prior executed evidence remains preserved. Execution approval is the
next gate; no target contact occurred during preparation.

### October 12: resolution v3 held, cleaned up; corrected v4 prepared

Executed the approved v3 resolution once. Native refresh and simulation returned
zero, with seven proposed additions, and retained package, boot, protected-input
and metadata checks reported unchanged state. Final full-snapshot continuity
failed with `ValueError: unexpected environment override`: the resolver left its
isolated APT_CONFIG in the worker process, so the protected Debconf collector
rejected it. Acceptance remains false; the simulation does not authorize installation.

Collection and bound terminal readback both returned matching transport/worker
status 2. The [held report](/home/aaron/code/.local-evidence/homelab-ntp/current/fresh-foundation-resolution-20261012-v3/held-resolution.json)
is retained with signed metadata and complete command output. Conditional
[cleanup](/home/aaron/code/.local-evidence/homelab-ntp/current/fresh-foundation-resolution-20261012-v3/cleanup-result.json)
returned transport/worker status 0 and removed the exact disposable workspace
and root-owned stage. No package installation, live APT list refresh, service
change or reboot occurred. The consumed v3 bundle was preserved and not replayed.

Corrected the repository resolver to restore the previous APT_CONFIG, including
its absence, in its finally path. Regression coverage exercises the actual
assignment and failure path with absent and pre-existing values. Protected
collector checks remain intact. Sealed [v4 review](/home/aaron/code/.local-evidence/homelab-ntp/current/fresh-foundation-resolution-20261012-v4/review.md)
offline against the same still-fresh accepted snapshot, with unique operation ID
`foundation-resolution-20261012-v4`. Bundle SHA-256:
`c2e9918c7fbd00e59b1ed9a4e0d62dc978d797c72ee98e246818667bab30a044`.
Target and scope remain j2-svntp1, one isolated resolution with conditional
readback, acceptance and cleanup. Collection expires October 13, 2026 at
20:30:41 UTC. Separate approval of v4 is the next gate; its execution has not begun.

### October 12: resolution v4 accepted and cleaned up

Executed approved v4 once on j2-svntp1. Collection, terminal readback and cleanup
each returned matching transport/worker status 0. The complete validator accepted
signed releases/indexes, dependency closure, native/Python simulation agreement,
exact pinned delta and full target continuity before and after resolution.
Installed state, live metadata, protected inputs and boot remained unchanged.

Accepted resolution SHA-256:
`3b953c4a742b5a6b0346a67c025ba080b4c84daa6c7ed2f5665c099b61dddf62`.
It binds the accepted v3 snapshot and current pinned asset manifest.
[Acceptance receipt](/home/aaron/code/.local-evidence/homelab-ntp/current/fresh-foundation-resolution-20261012-v4/acceptance.json)
and complete signed metadata/query evidence remain private. The simulation
confirmed seven additions and no upgrades or removals: libavahi-client-dev,
libavahi-client3, libavahi-common-dev, libavahi-compat-libdnssd-dev and
libavahi-compat-libdnssd1 at 0.8-16; libdbus-1-dev at 1.16.2-2; and
libsystemd-dev at 257.13-1~deb13u1, all arm64.

[Verified cleanup](/home/aaron/code/.local-evidence/homelab-ntp/current/fresh-foundation-resolution-20261012-v4/cleanup-result.json)
removed only the bound disposable APT workspace and root-owned code/evidence
stage. No package installation, service/update-policy change or reboot occurred.
Prior executed evidence remains preserved. Next prepare the foundation delta
offline from accepted v4 evidence, fetch and verify exact pinned archives as
separately authorized, and seal installation with acceptance, recovery and cleanup
for separate execution approval. Snapshot freshness ends October 13, 2026 at
20:30:41 UTC; preparation and execution must reject stale evidence or state drift.

### October 12: mDNS prerequisite installation prepared and sealed

Prepared the [installation review](/home/aaron/code/.local-evidence/homelab-ntp/current/foundation-mdns-install-20261012-v1/review.md)
for j2-svntp1, ama UID 1000, 10.1.0.137, kernel 6.18.50+rpt-rpi-v8.
Operation ID: `mdns-20261012-v1`; exclusive target stage:
`/var/lib/ntp-foundation-mdns-20261012-v1`.
Bundle SHA-256:
`c6629e7ac07c452bf5da006f77706faf6ad211116860b5e81467243c05d94672`.
It binds the accepted v3 snapshot, accepted v4 resolution, current recipe/pinned
manifest, target boot/identity/SSH key and every non-secret execution input.
The install/readback/recovery window ends October 13, 2026 at 20:30:41 UTC.

Fetched only the seven missing archives on the workstation through the checked-in
verified fetcher, checking pinned sizes/hashes against the authenticated accepted
resolution. The [fetch receipt](/home/aaron/code/.local-evidence/homelab-ntp/current/foundation-mdns-install-20261012-v1-assets/fetch-receipt.json)
and native archive-control inspection remain private. The preparer used no
historical baseline/bundle and contacted no target. It derived the exact expected
inventory of 686 records from the accepted 679-record baseline plus seven
additions. There are no upgrades, removals or newly installed daemon packages.

Archive inspection found ldconfig triggers in libavahi-client3 and
libavahi-compat-libdnssd1, and generated XML catalog maintenance in libdbus-1-dev.
These normal package effects are explicitly covered by the review. The other
four archives have no maintainer scripts/triggers; none declares conffiles.
The rendered worker's 48 offline regressions passed. Bundle/member/provenance
verification and all three generated payloads passed offline validation.

The review covers one root-owned staged installation, local-archive simulation
and protocol checks, full acceptance, temporary-control/update-disposition
cleanup, one conditional terminal readback and bounded configuration recovery.
The executed stage/backups/claims/logs are retained as mutation evidence;
cleanup restores controls rather than deleting that evidence. Prior executed
evidence is preserved. Separate hash-bound execution approval is the next gate.
No packages were installed and no target contact occurred during preparation.
Only after package acceptance may a separately reviewed mDNS-enabled source
build and acceptance proceed; this bundle does not authorize that build.

### October 12: mDNS prerequisite installation accepted; controls restored

Executed the approved seven-package installation once on j2-svntp1 under bundle
SHA-256 `c6629e7ac07c452bf5da006f77706faf6ad211116860b5e81467243c05d94672`.
Transport and worker both returned 0. Hash-verified 395 returned evidence records,
including complete, acceptance and cleanup receipts. Exact inventory, clean dpkg,
protected inputs, hook/protocol completion, effective needrestart policy,
unchanged listchanges seen state and boot/access/network continuity all passed.
Needrestart reported version 3.11, current and expected kernel
6.18.50+rpt-rpi-v8, and kernel status 1.

All seven exact pinned packages are installed. The accepted inventory now contains
686 records, with no upgrades, removals or unrelated additions. Mirrored the
observed terminal inventory byte-for-byte in configs/accepted-packages.tsv;
its SHA-256 is
`009fa317306e75c70b7f4cbbb8a6cc651cafddf689eb1fc32fbb3a6a4997176c`.
[Acceptance receipt](/home/aaron/code/.local-evidence/homelab-ntp/current/foundation-mdns-install-20261012-v1/acceptance.json)
and complete private evidence are retained. Temporary policies and runtime masks
were restored/removed, original automatic updates restored, and the approved
final needrestart policy retained with microcode checking disabled.

Conditional readback/recovery were unnecessary because complete terminal evidence
and acceptance/cleanup succeeded. The root-owned stage, claim, backups and logs
remain preserved as reviewed mutation evidence. No source build, daemon activation,
hardware/network configuration, notification delivery or reboot occurred.
Next prepare and review a new mDNS-enabled GPSD/NTPsec source build against the
accepted 686-record inventory. The old 679-record snapshot/resolution and consumed
installation approval are execution records, not a current baseline or permission
for further execution.

### October 12: mDNS-enabled source build prepared and sealed

Prepared the [source build review](/home/aaron/code/.local-evidence/homelab-ntp/current/source-build-mdns-20261012-v1/review.md)
offline for j2-svntp1, ama UID 1000, 10.1.0.137 and kernel 6.18.50+rpt-rpi-v8.
Operation ID: `mdns-20261012-v1`; exclusive unprivileged target workspace:
`/home/ama/.ntp-source-build-mdns-20261012-v1`.
Bundle SHA-256:
`daddefa703f2466a46425151c4dca4aba889cc78457c2eebef46269c51dda98d`.
Build/readback approval window ends October 13, 2026 at 20:30:41 UTC.

Used the newly accepted installation specification and observed 686-record
inventory, with Python/ABI evidence from accepted resolution and unchanged
interpreter packages. The specification binds foundation and Python evidence
hashes, exact inventory, installed PPS header, target boot and all build inputs.
Reverified both pinned publisher archives and detached signatures through the
checked-in verified asset tool. Safe unpacking and native option/layout checks
passed; no source execution or target contact occurred during preparation.

Updated source preparation to require a unique operation ID, render stage and
hostname/kernel/SSH bindings, reject stale foundation windows before output and
hash-bind Python evidence. The worker rejects operation-stage and foundation
boot drift. Regression checks cover malformed/ambiguous transport bindings,
expired input with no output and stage/boot drift. Eleven preparer regressions
and the rendered stage's 20 offline regressions passed.

The new recipe retains pinned GPSD 3.27.5 and NTPsec 1.2.5, time-service/magic_hat,
unchanged upstream test coverage, SHM/Python/manual/client staging and two jobs.
Acceptance additionally requires generated HAVE_DNS_SD_H=1 and records NTPsec
mDNS support explicitly. Build inputs preserve the accepted v5 candidate in its
separate stage; no historical candidate is reused or replaced.

Next obtain separate approval for one unprivileged build, both upstream suites,
DESTDIR staging, feature/module/linkage/file acceptance and conditional terminal
readback. Failure and success both preserve the new stage/claim/logs/candidate;
there is no automatic retry or live installation. Destination/collision inspection,
application installation and runtime activation remain later separately reviewed
gates. The plan, operations and current history status agree on this resume point.

### October 12: mDNS-enabled source build accepted

Executed the approved linked build once on j2-svntp1. The supplied digest omitted
its final character; the unchanged linked review and verified complete bundle
SHA-256 `daddefa703f2466a46425151c4dca4aba889cc78457c2eebef46269c51dda98d`
were used and the approval binding was retained privately. Transport and worker
both returned 0. All nine returned evidence records were hash-verified, including
the claim/specification binding, acceptance/complete receipts, native build log
and release manifest.

Both unchanged upstream suites, native DESTDIR staging, manuals/clients/modules,
isolated staged imports, linkage and manifest stability passed. GPSD retained
time-service/magic_hat/SHM and the u-blox driver. NTPsec SHM/NTS/seccomp and
generated HAVE_DNS_SD_H=1 passed; ntpsec_mdns_registration is explicitly true.
The complete 686-record package inventory and boot/SSH/NetworkManager continuity
remained unchanged. No live installation, service activation, package/policy
change, reboot or hardware/receiver/network configuration occurred.

Accepted release SHA-256:
`7ea41e51c571744776c2d4563b0da42eb03ce7a237c45922ddc976ee726390f6`.
The release contains 159 file/link entries and is mirrored byte-for-byte in
configs/accepted-source-release.json. [Acceptance receipt](/home/aaron/code/.local-evidence/homelab-ntp/current/source-build-mdns-20261012-v1/acceptance.json)
and complete private terminal evidence are retained. The accepted target stage
is `/home/ama/.ntp-source-build-mdns-20261012-v1`; its candidate, claims and logs
remain preserved, along with the earlier v5 evidence. Conditional readback was
unnecessary because complete terminal acceptance evidence was returned.

Next prepare and review a bounded read-only destination/collision inspection for
this accepted manifest and target. Execute it only after separate scope/hash
approval. Then prepare installation with observed pre-state, explicit ownership/
modes, journal, backups, obsolete-file handling, acceptance and recovery for its
own approval. Source-build approval has been consumed; it authorizes no further
target contact or application deployment. Runtime mDNS policy/activation follows
the governed runtime stage.

### October 12: destination/collision inspection prepared and sealed

Prepared the [read-only inspection review](/home/aaron/code/.local-evidence/homelab-ntp/current/source-destinations-20261012-v1/review.md)
for j2-svntp1, operation `source-destinations-20261012-v1`, without target contact.
Bundle SHA-256:
`efa5fc69df7f9dce63bbace722c7961a95541e2b5d4e163f34c80d4105c94775`.
Collection expires `2026-10-13T22:05:56+00:00`; readback/cleanup remain available
after expiry.

It binds the accepted 159-entry release
`7ea41e51c571744776c2d4563b0da42eb03ce7a237c45922ddc976ee726390f6`,
build specification
`a3b1eb9a19f01ac504c074afd124c73b6d3e2a540f6a21b9471c04a74bad9679`,
acceptance receipt
`9e077154a1abf40bb8a7363d9d92b45559e7402b291f11498773711b6e6483fe`,
exact 686 package records, accepted boot/Python identity and pinned SSH key.

Extended the existing protected preflight transport with a destination mode
and bounded manifest collector. One capture compares two hash passes, records
absent/identical/different destinations and root-safe parent metadata, and checks
package/boot/Python plus service/process continuity. It executes no installed
application code and changes no package, application, runtime, service or update
policy. Only the new exclusive root-owned observation stage and its records are
written. Conditional terminal readback validates full coverage and saves the
canonical installation pre-state; cleanup verifies terminal/input/file bindings
before removing only this stage. Drift, missing receipts or unknown entries hold
cleanup/replay for a separately reviewed recovery. Prior executed evidence and
accepted candidate workspaces are preserved.

Offline bounds, ancestor rejection, file/link handling, mutation detection,
receipt/hash binding, readback/acceptance and completed/held cleanup regression
checks passed. Plan, operations and history now agree: obtain separate approval
for capture/readback/cleanup, accept the retained observation, then prepare a
new live installation bundle with explicit metadata, backups and rollback.
No inspection execution or live installation has occurred.

### October 12: destination/collision inspection accepted; staging removed

Executed the separately approved [inspection review](/home/aaron/code/.local-evidence/homelab-ntp/current/source-destinations-20261012-v1/review.md)
once on j2-svntp1, bound to bundle
`efa5fc69df7f9dce63bbace722c7961a95541e2b5d4e163f34c80d4105c94775`.
Capture, conditional terminal readback and verified cleanup each completed with
matching zero transport/worker status. Full controller-side acceptance passed.

All 159 accepted-release destinations are absent; there are no collisions.
Captured 27 parent records, including missing directories, and verified existing
ancestors are protected root-owned directories. No ntpd/GPSD processes were
active; inspected time-service units were absent/inactive. SSH and NetworkManager
remained active/running. Exact 686 package records, dpkg audit, accepted boot,
Python ABI and service/process state passed continuity checks across both
manifest observation passes.

Accepted inspection SHA-256:
`44efbdb8928b2f6d6182e49936340fbe40797d53421d8ce399010da12c5ddc40`.
Canonical installation pre-state SHA-256:
`d6fa64c51c3a08a112219556700912bed71995b1ef1451ace7d48450e43ca75f`.
Both files and their acceptance receipt, registrations, terminal records and
complete transport logs remain in the private inspection directory. Verified
cleanup removed only `/var/lib/ntp-preflight-source-destinations-20261012-v1`.
Prior executed evidence and accepted source workspaces were preserved. No
application installation, configuration, service change or reboot occurred.

Next prepare and seal the native GPSD/NTPsec installation bundle using the
accepted release and this canonical pre-state. Define explicit metadata,
destination revalidation, root-owned backups/journal, failure readback,
rollback and post-install acceptance before requesting separate execution
approval. Runtime configuration/activation and hardware/network/maintenance
acceptance remain later scoped gates. The consumed inspection must not be
replayed; its acceptance does not authorize installation.

### October 12: native GPSD/NTPsec first installation prepared and sealed

Prepared the [native installation review](/home/aaron/code/.local-evidence/homelab-ntp/current/source-install-20261012-v1/review.md)
for j2-svntp1, operation `source-install-20261012-v1`, entirely offline.
Bundle SHA-256:
`cda87986ec9ab35499356f8dda1258d558a247db755debedbc212059bf752f32`.
Installation window expires `2026-10-13T17:12:58-05:00` (America/Chicago).
It binds the accepted mDNS-enabled 159-entry release, build receipt/specification,
exact 686-package/boot/Python state and accepted absent destination pre-state
`d6fa64c51c3a08a112219556700912bed71995b1ef1451ace7d48450e43ca75f`.

Added a sealed controller and protected first-install wrapper. Verified native
payload is copied from the accepted target staging tree through no-follow,
bounded reads into root-owned staging. Recheck the exact pre-state and target
continuity before invoking the accepted clockmaker installer. Explicit ownership
and modes, parent identities and complete installed hashes/links govern acceptance;
terminal readback rechecks installed state. Existing directories remain intact;
new parents are root:root 0755. Baseline metadata and native journal/backups remain
protected. The prior-file backup set is empty because all destinations are absent.

Conditional recovery verifies every current artifact, parent identity and new
directory contents before removing anything; then restores absent paths and
removes only proved new empty directories. Missing/interrupted journal records,
unrelated data or drift hold recovery for a new review. Exclusive registrations
prevent replay. Conditional cleanup removes only verified temporary payload;
executed privileged code, journals and recovery evidence remain retained.

Offline native-copy/link/mode checks, injected partial failure and recovery,
unknown-data/drift rejection, bounded source reads, replay/expiry rejection,
terminal acceptance and payload-only cleanup regressions passed. Corrected the
source-reader fixture to simulate target UID/GID 1000 independently of the CI
runner account and verify UID/GID 1001 rejection. Production ownership checks
remain unchanged. Resealed the unexecuted bundle because its tests are bound
inputs; the previous hash is superseded. No target
contact, package change, application installation, configuration or activation
occurred. Next obtain separate hash-bound execution approval. Library-cache and
Python/runtime discovery, configuration, services, hardware, networking and
maintenance acceptance remain subsequent reviewed stages.

### October 12: native GPSD/NTPsec installation accepted

Executed the approved bundle once for j2-svntp1:
`cda87986ec9ab35499356f8dda1258d558a247db755debedbc212059bf752f32`.
Installation, conditional terminal readback and payload cleanup each completed
with worker and transport status 0. Controller acceptance verified all 159
installed entries, release hashes/links, root ownership, explicit modes, new
parent metadata and exact package/boot/Python/service/process continuity.
Terminal SHA-256:
`504e2afc82d926f0e02c461c547e3a536527b58a7cb0d2cad82554755fd90b72`.

The installed release remains `copied_not_activated`. No library-cache change,
runtime configuration, service activation or reboot occurred. Recovery was not
needed. Verified temporary payload was removed; root-owned executed code,
baseline, journal/backups and receipts remain at
`/var/lib/ntp-preflight-source-install-20261012-v1`.
Controller execution registrations, full streams/statuses and acceptance remain
in the private [operation directory](/home/aaron/code/.local-evidence/homelab-ntp/current/source-install-20261012-v1).
The plan's separate installation/runtime acceptance boundary remains unchanged.
Next prepare runtime discovery/configuration for its own hash-bound approval.

### October 12: read-only runtime discovery and configuration inputs prepared

Prepared the [runtime discovery review](/home/aaron/code/.local-evidence/homelab-ntp/current/runtime-discovery-20261012-v1/review.md)
for j2-svntp1 entirely offline. Operation `runtime-discovery-20261012-v1` binds
accepted native installation bundle
`cda87986ec9ab35499356f8dda1258d558a247db755debedbc212059bf752f32`,
its acceptance/readback and completed payload cleanup, target identity/key,
current recipes/assets/templates and snapshots of the three governing documents.
Discovery bundle SHA-256:
`7758bddb17f1e69066b262ca060d01297ac997c3e95492f3914cff4e2ee4c76d`.
Capture window expires `2026-10-13T18:31:25-05:00` (America/Chicago).

Added a checked-in fixed read-only runtime recipe, inspector/controller and
13 offline regressions. The capture verifies installed files and accepted parent
identities, enforces target continuity and gathers bounded configuration/device,
account/group, loader and network inputs. It executes only fixed OS read-only
queries, never installed applications or receiver I/O. Root staging, exclusive
capture, conditional terminal readback and verified scoped cleanup reuse the
protected preflight lifecycle. Drift, query failures, missing terminal records
and unknown cleanup entries hold the operation without repairing live state.

Configuration requirements and current combined-service templates are sealed;
no deployable host ntp.conf, accounts, overlays or listener/upstream choices were
invented. Accepted discovery and review of unresolved inputs precede configuration
rendering and separate loader/runtime/configuration/activation approvals.
Local lifecycle/binding/bounds/coverage/replay/drift regressions and repository
pre-commit passed. No target contact occurred; the native installation stage,
journals and all executed evidence remain preserved. Next obtain separate
approval for one discovery capture with conditional readback and cleanup.

### October 12: runtime discovery held; canonical receipt comparison corrected

Executed the approved v1 capture once for j2-svntp1. It held before runtime
queries with `installed release drift`; capture and terminal readback each
returned matching worker/transport status 2. Scoped observation-stage cleanup
completed with status 0. No runtime discovery acceptance was issued. Prior native
installation code/journals, source workspaces and all controller evidence remain
preserved. No configuration, daemon, account, package or network change occurred.

Offline diagnosis found a deterministic schema mismatch: the native journal's
`after` contains only hostname/files, while the inspector's canonical state also
contains release hash, previous hash and obsolete entries. The comparison could
never succeed and does not establish live file drift. Corrected the projection
using the bound release hash, no previous release and no obsolete files; exact
file/link/owner/mode and parent/target continuity checks remain required.
Removed synthetic fixture fields that had concealed the discrepancy and added
an explicit real-receipt-shape regression. The offline suite now has 14 tests.

Prepared a new operation `runtime-discovery-20261012-v2` for separate approval;
do not replay consumed v1. Host configuration remains gated on accepted fresh
discovery and review of unresolved inputs. The three-document architecture
and runtime activation boundary are unchanged. Replacement discovery bundle:
`a19d107c37368c60bb952d191a98d07e882303be07bd371cf4db77a0d04f5df4`.
Capture expires `2026-10-13T18:41:54-05:00`
(America/Chicago).

### October 12: v2 runtime discovery accepted and observation stage removed

Executed approved discovery bundle once for j2-svntp1:
`a19d107c37368c60bb952d191a98d07e882303be07bd371cf4db77a0d04f5df4`.
Capture, conditional terminal readback and scoped cleanup each completed with
worker/transport status 0. Controller acceptance verified report/spec hashes,
all 159 installed entries, parent identities, package/boot/Python/service/process
continuity and the read-only scope. Accepted runtime report SHA-256:
`d60fca2ad170d6318d16cde9d24da102cefdebaa8c6b6b194ec87f8e0586f22d`.

Removed only `/var/lib/ntp-preflight-runtime-discovery-20261012-v2`; native
installation code, baseline/journal/backups and both source workspaces remain
preserved. Raw report, acceptance, registered executions and full streams/statuses
remain in the private [operation directory](/home/aaron/code/.local-evidence/homelab-ntp/current/runtime-discovery-20261012-v2).

No UART/PPS/RTC nodes or matching sysfs entries were observed. Boot lacks the
GPS UART/PPS/RTC overlays and retains the serial-console request. Runtime accounts/groups
are absent. Native Python roots match the isolated root search path; local library
path is configured but libgps is not cached. These are static observations, not
successful daemon/client imports or receiver/clock acceptance. Avahi and bootstrap
systemd-timesyncd are running; application service units are absent. Configuration
readiness remains false. No application/device execution, loader/cache change,
configuration, account, service, network mutation or reboot occurred.

Next prepare reviewed host networking/hardware/account and runtime configuration
inputs with recovery and bounded loader/runtime validation. Further execution and
combined-service activation require separately approved hash-bound stages.

### October 12: host configuration preparation and supplemental input gate

Approved offline preparation of networking, hardware, accounts and runtime
configuration. Accepted v2 discovery remains the starting observation; no new
target contact occurred. It lacks persistent Ethernet properties and installed
overlay capabilities required to prepare guarded changes. Prepared supplemental
operation `host-inputs-20261012-v1` using the existing protected runtime discovery
lifecycle, accepted native receipt and current governing input hashes.

The collector adds bounded Ethernet properties by UUID, registry/profile drift
checks, boot-overlay bytes/hashes, nobody/nogroup and serial/Bluetooth unit
enablement state. Credentials and receiver I/O remain excluded. Offline tests
cover scoped profile queries, malformed registries, missing profile coverage and
profile drift, alongside existing replay/readback/cleanup regressions.

Pinned GPSD source defaults to nobody/dialout; future runtime identities still
require accepted-build/device-access confirmation. Added nowait polling to the
foreground GPSD template. No account, loader/cache, network, boot, application
configuration or service changes were executed. Existing native release modes,
executed evidence and journals remain intact.

Next: separately approve the supplemental read-only capture and confirm the
revision 5.9 HAT's PPS BCM GPIO and RTC. Then seal networking with timed recovery,
hardware changes with console/reboot recovery, and account/loader/runtime
configuration from accepted inputs. No deployable hardware or ntp.conf settings
are inferred from missing devices. Activation remains separately gated.

### October 12: operator-supplied GPS/RTC datasheet evaluated offline

Reviewed Uputronics Raspberry Pi GPS/RTC Expansion Board datasheet, document
revision 2.2 (December 2020), supplied for the reported revision 5.9 M8 HAT.
Pages 1 and 2 specify BCM GPIO18/header pin 12 for PPS and an RV-3028-C7 RTC
at I2C address 0x52; pages 4 and 5 describe the rv3028 overlay and 115200-baud
serial operation. These vendor inputs resolve the preparation question about
PPS GPIO/RTC without claiming observed device operation or board revision.
Recorded them in the architecture and operations documents. Source PDF SHA-256:
`63ef89d93c79a939033ee5e0a7645ae56f5adf66d3f0393d5cbbf8e0755d9004`.
The supplied PDF remains in private local evidence.

No commands embedded in the datasheet were executed. Its older Raspbian paths,
UART example and hwclock/package changes are not the Trixie installation recipe.
The already sealed supplemental capture is unchanged and still awaits separate
approval. Next accept its network/boot inputs, then prepare guarded networking,
explicit GPIO18/rv3028 boot candidates and account/loader/runtime configuration.
No target contact, receiver access, boot edit, reboot or activation occurred.

### October 12: supplemental host-input capture accepted and cleaned

Executed the approved `host-inputs-20261012-v1` bundle once for j2-svntp1:
`2420d0276107b8a10c12da8ffefd3b245611fc0aa8383de5b36fca086f13603a`.
Capture, conditional terminal readback/acceptance and scoped cleanup each
completed with worker/transport status 0. Accepted runtime report SHA-256:
`954736cd1068a48c4178001042dda8efc18f4b41bc1f5b9bac524003fc03279a`.
Verified all 159 native entries and 686 package records plus target/boot/Python,
parent and service continuity. Ethernet registry/properties remained unchanged
across capture. Removed only `/var/lib/ntp-preflight-host-inputs-20261012-v1`;
prior executed evidence, native journals/backups and source workspaces remain.
Full streams, status records, report and acceptance remain in the private
[operation directory](/home/aaron/code/.local-evidence/homelab-ntp/current/host-inputs-20261012-v1).

Observed one eth0 Ethernet profile with autoconnect and automatic IPv4/IPv6
configuration/DNS; no persistent static addresses, gateway or DNS overrides.
nobody/nogroup and dialout exist; ntp/ntpd/gpsd accounts/groups remain absent.
disable-bt, pps-gpio and i2c-rtc overlay files are present, including rv3028
and gpiopin metadata. UART/PPS/RTC nodes remain absent. hciuart is absent;
queried serial-getty units are disabled/inactive. Bootstrap timesyncd and
Avahi remain enabled/running. These observations establish preparation inputs,
not hardware operation, runtime readiness or activation acceptance.

No package, network, boot, account, library cache, receiver or application
configuration was changed. Next prepare fixed dual-stack networking with exact
profile before-state, timed recovery and endpoint acceptance, then hardware
GPIO18/rv3028 bring-up and account/loader/runtime stages. Each live mutation,
reboot and service cutover still requires a separately approved sealed bundle.

### October 13: fixed dual-stack networking prepared offline

Approved preparation of the next networking stage. Added a checked-in desired
network recipe, offline sealer/controller, guarded root transaction and regression
tests using accepted host-inputs as the baseline. Prepared operation
`host-network-20261013-v1` for j2-svntp1, bound to the accepted report, original
Ethernet UUID/MAC/bootstrap endpoint, boot/kernel, native/package/service state
and current architecture/operations/history hashes.

The transaction retains the original DHCP profile, clones a unique candidate,
records its allocated UUID, sets the governed fixed dual-stack addresses/DNS
while retaining IPv6 RA, and disables original autoconnect before switching.
A root timer is armed before profile mutation and restores original settings
at 300 seconds without depending on SSH. Acceptance requires exact profile
settings, DAD/address/route/DNS/source/egress evidence and pinned-key SSH at both
new fixed addresses, with a 45-second reserve before recovery. Durable acceptance
precedes timer cancellation; conditional readback recovers a lost acceptance
response without replaying the mutation. Unrelated drift holds recovery.

Offline tests cover early failures, activation faults, interrupted clone UUID
recording, atomic-write interruption, deadline exhaustion, dual-endpoint/label
requirements, state drift, lost responses, one-shot submission and receipt
recovery. Existing native helper APIs and guarded file checks remain in use.
The three governing documents agree on networking before hardware/account and
runtime configuration. No target contact or live network change occurred.

Next approve the exact [networking review](/home/aaron/code/.local-evidence/homelab-ntp/current/host-network-20261013-v1/review.md)
and bundle hash for one apply, conditional endpoint acceptance/readback,
timed or conditional recovery and transient-unit cleanup. Root before-state,
command streams/status records and receipts remain preserved. Original DHCP
policy restoration does not promise the old lease; console recovery is required
for lost endpoints or a held transaction. No reboot, DNS/controller changes,
hardware bring-up or application cutover is included. Reboot persistence remains
a later separately approved acceptance gate.

### October 13: fixed dual-stack networking accepted

Executed approved `host-network-20261013-v1` once on j2-svntp1. The linked
review and uniquely matching pasted hash prefix identified the full sealed
bundle SHA-256
`460b694931e63748f101832f9a8a59ab934b862f63280eb1d66de3307169dcf5`.
Start, dual-endpoint verification/acceptance and transient cleanup returned
status 0. All ten acceptance checks passed: profile, retained original,
registry, addresses, IPv6 RA, DNS, routes, DNS reachability, HTTPS egress and
continuity. Both fixed addresses passed pinned-key SSH checks.

The host now uses `10.1.0.51/22` and `fd36:5aa8:6971:1::51/64`, retaining
automatic IPv6/RA and the governed DNS VIPs. Durable acceptance was committed
before stopping timed recovery; no recovery was needed. Cleanup removed only
transient-unit activity, retaining the original DHCP profile, root-owned
before-state/journal and all private execution streams and receipts under
`.local-evidence/homelab-ntp/current/host-network-20261013-v1`.

The three governing documents agree on accepted live host networking and the
next hardware/boot and account/loader/runtime preparation gates. No reboot or
application activation occurred. Reboot persistence, hardware/time service,
dual-stack NTP clients and maintenance/reporting acceptance remain pending.

### October 13: hardware/boot and account/runtime stages prepared offline

Approved preparation of separate hardware/boot and account/runtime stages.
Aaron selected account/runtime prerequisites and a rendered service candidate,
leaving final NTP source/access configuration and service cutover for later.
Added checked-in hardware/runtime recipes, an offline sealer/controller and a
protected root worker reusing the existing native/file/network guards. Added
regression coverage to the existing offline test runner.
Synthetic execution receipts now use explicit 0600 modes rather than inheriting
the operator workstation's umask; validate with CI's 022 umask as well. The
production owner-private input checks remain unchanged.

Prepared `host-hardware-20261013-v1` for j2-svntp1, bound to the accepted
networking archive, target boot/kernel, fresh host-input baseline, installed
release and current recipe/manifest/document hashes. Its reviewed scope is two
boot-file edits, one console-ready reboot, new-boot dual-stack management and
PL011/BCM18 PPS/RV3028 metadata acceptance, conditional readback, guarded
restoration and a recovery reboot when needed, plus transient cleanup. The
retained worker supports guarded console readback/recovery without SSH. No
user-space GNSS/PPS/RTC device I/O or clock-service activation is included. Metadata
acceptance does not establish pulse/fix health, RTC accuracy or thermal behavior.

Prepared `host-runtime-20261013-v1`, conditional on that exact hardware bundle's
accepted root specification and current post-reboot boot ID. It creates only a
dedicated NTP system account/group, refreshes the backed-up loader cache without
link changes, preserves GPSD nobody/dialout and every accepted native mode,
validates native/Python execution contexts and renders private service
candidates. It installs no global configuration, activates no service and does
not change bootstrap timesyncd. Unrelated or unrecorded partial mutation holds
recovery; all executed evidence remains retained.

The three governing documents agree on accepted live networking, separately
pending hardware/reboot and conditional runtime-prerequisite execution, and
later GNSS/time-service/client and maintenance gates. Preparation contacted no
target. Next obtain separate execution approval for the exact
[hardware review](/home/aaron/code/.local-evidence/homelab-ntp/current/host-hardware-20261013-v1/review.md)
and its `sealing.json` SHA-256, followed by the conditional
[runtime review](/home/aaron/code/.local-evidence/homelab-ntp/current/host-runtime-20261013-v1/review.md)
and its own SHA-256. Preserve the primary's antenna-power path and original
Debian 11 card; declare console readiness before reboot submission.

### October 13: hardware acceptance held; boot-file recovery incomplete

Aaron approved the refreshed hardware and conditional runtime bundle hashes,
and confirmed console/media recovery readiness with the original card retained.
The approved hardware start completed with protected backups and candidate boot
files; its one controlled reboot was submitted. IPv4 pinned-key SSH returned,
but all subsequent acceptance probes held on `candidate registry drift`.
Full dual-stack and hardware metadata acceptance were not reached. Conditional
terminal readback completed and reported `reboot_submitted`.

Guarded recovery restored both original boot files and recorded
`recovery_files_restored`. The permitted recovery-reboot attempt was blocked
by the same registry check before reboot submission. Thus the original boot
files are on disk, while the running boot has not been reverted. Recovery
verification and cleanup remain pending; no acceptance receipt was created.
The conditional account/runtime bundle was not started, and no service
activation occurred. Preserve the root stage, before-state, command journal,
all controller/transport records and both sealed bundles unchanged.

Evidence remains in the private `host-hardware-20261013-v1` operation directory,
including `verify-controller.log`, `wait-1.stdout` through `wait-5.stdout`,
`readback-result.json`, `recover-result.json`, and
`recovery-reboot-action-result.json`. The exact registry difference has not
been captured locally; do not assume it is harmless or relax the guard.
Next prepare a separately reviewed read-only capture of the retained command
journal, current network registry/profile identities, boot identity and boot
file state. Use that evidence to review a bounded recovery continuation.
Do not replay consumed controller modes or execute the conditional runtime
stage before accepted hardware and a fresh applicable review.

### October 13: read-only registry inspection prepared offline

Approved preparation of a scoped registry inspection and a subsequent recovery
continuation for separate execution approval. Added the checked-in inspection
controller and offline tests for stable capture, state/member drift, locking,
private files, single-use transport, lost responses, and guarded cleanup.

Prepared `host-registry-inspection-20261013-v1`, bound to the exact executed
hardware archive and `recover-result.json`, target/key, retained input hashes,
and current governing documents. It reads the original operation under a
shared lock, captures exact before/current registry identities and public
profile fields, boot state and the retained command journal. It creates only
a separate protected diagnostic stage. Conditional readback and terminal-bound
cleanup preserve the original stage and all local executed evidence.

No target contact occurred during preparation. Hardware recovery remains
incomplete and runtime/account setup remains unstarted. Next approve the
[inspection review](/home/aaron/code/.local-evidence/homelab-ntp/current/host-registry-inspection-20261013-v1/review.md)
and its `sealing.json` SHA-256. Recovery continuation cannot be sealed until
the inspection is executed and its findings accepted; do not presume the
registry difference is harmless or bypass the existing guard.

### October 13: registry diagnosis accepted; recovery continuation prepared

Executed the approved `host-registry-inspection-20261013-v1` capture once.
The complete bound diagnostic report was accepted, then conditional cleanup
removed only its new diagnostic root stage. Local evidence and the original
hardware stage remain preserved. No network/profile/boot changes or reboot
were performed by the inspection.

The expected and current registries differed only in the loopback profile's
UUID. Both Ethernet UUID/type pairs were unchanged. The observed loopback
profile identifies `lo`, uses manual 127.0.0.1/8 and ::1/128, has no gateways,
and disables autoconnect. This explains the exact-registry guard failure;
it does not substitute for full post-reboot network/hardware acceptance.
The retained original state remains `recovery_files_restored`.

Prepared `host-recovery-continuation-20261013-v1` offline under the existing
preparation approval. Its separate protected stage binds the accepted report,
cleanup, diagnosed boot and original hardware archive. It invokes the sealed
original worker with a constrained in-memory loopback comparison; it neither
edits the worker nor changes NetworkManager profiles. It requires exact
restored original boot files and retained evidence before one console-ready
recovery reboot, then both pinned management endpoints and original network,
package/native/service continuity before acceptance and transient cleanup.
Regression tests cover loopback field/type/count changes, Ethernet drift,
retained evidence drift, single reboot submission, new-boot/dual-endpoint
acceptance and lost responses.

Recovery remains incomplete; account/runtime setup remains unstarted.
Next approve the [recovery review](/home/aaron/code/.local-evidence/homelab-ntp/current/host-recovery-continuation-20261013-v1/review.md)
and its `sealing.json` SHA-256. Retain console/media readiness and the original
Debian 11 card. Do not replay the consumed hardware controller modes.

### October 13: recovery reboot accepted and cleanup complete

Executed the approved `host-recovery-continuation-20261013-v1` bundle after
verifying its exact hash and validity window, using Aaron's confirmed
console/media readiness. Preflight matched the diagnosed boot, retained
state/before/journal hashes and restored original boot bytes/owners/modes.
The continuation submitted its one recovery reboot and observed a new boot.

Both pinned IPv4 and IPv6 endpoints passed matching recovery acceptance:
original boot files, fixed addressing, RA, DNS, routes, HTTPS egress and
package/native/service continuity. The constrained loopback comparison passed
without changing any profile or the sealed original worker. Conditional
cleanup completed for the original operation reboot transients. Both root
stages, the byte-exact before-state, command journals, sealed bundles and all
local execution records remain preserved.

The private continuation directory contains `reboot-result.json`,
`acceptance.json`, endpoint proofs and `cleanup-result.json`; the latter
records `phase=accepted` and `transient_units_cleaned=true`. Rollback is now
complete. This accepts recovery to the pre-hardware boot configuration, not
UART/PPS/RTC bring-up or physical timing performance. No account/runtime setup
or clock-service activation occurred.

Next prepare a fresh target baseline and corrected hardware/boot stage that
incorporates the tested loopback comparison, followed by conditional runtime
prerequisites. Obtain separate execution approval for those exact bundles.
Do not reuse consumed hardware/recovery modes or claim hardware acceptance
from the recovery receipt.

### October 13: fresh baseline capture and corrected hardware preparation

Approved offline preparation of a fresh baseline and corrected hardware/boot
stage for separate execution approval. Extended the existing registry
inspector with a post-recovery baseline capture bound to the accepted recovery
archive, receipt, cleanup and current boot. The capture preserves original
root stages and journals, verifies installed native files and parent identities
twice, and records fresh host/configuration/network/device metadata. It performs
no application imports or device I/O and creates only its own protected stage.

Corrected the hardware/reboot registry check to permit only the verified lo
UUID replacement; all non-loopback identities and existing continuity checks
remain binding. The network mutation stage retains strict registry equality.
The hardware preparer now supports schema 2 with a required accepted/cleaned
fresh-baseline input for the CLI. It binds the new boot and observation hashes
separately from historical networking provenance; runtime candidates must bind
the same fresh baseline. Historical artifacts remain unchanged.

Prepared `host-baseline-20261013-v1` offline. Regression coverage includes
recovery provenance/cleanup, changed boot, package/native/configuration drift,
capture stability, constrained loopback replacement, fresh baseline sealing,
and preserved historical boot identity. No target contact occurred during
preparation. The replacement hardware mutation bundle is deliberately not
sealed without the new live observations; runtime/account setup remains
unstarted.

Next approve the [fresh baseline capture](/home/aaron/code/.local-evidence/homelab-ntp/current/host-baseline-20261013-v1/review.md)
and its `sealing.json` SHA-256 for one read-only capture with conditional
readback and cleanup. After acceptance, seal the corrected hardware/boot
bundle and obtain its separate execution approval.
