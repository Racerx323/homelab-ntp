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
| OS/access | Debian 13 Trixie, aarch64, kernel 6.18.50+rpt-rpi-v8; Ethernet DHCP 10.1.0.137; matching console/SSH key | Fixed dual-stack service addresses; Wi-Fi disablement |
| Foundation | 679 package records; original foundation plus pps-tools and bc accepted; controls cleaned up | Fresh snapshot/resolution and exact mDNS prerequisite delta before additional installation |
| Source candidate | GPSD 3.27.5 and NTPsec 1.2.5; upstream tests/native staging and 159-entry manifest accepted with mDNS disabled | New mDNS-enabled build/acceptance, then live installation and activation |
| Runtime | Candidate only; no new ntp.conf or live application deployment | GPS/PPS/RTC, accounts, combined service, leap maintenance |
| Reporting | Needrestart policy installed, microcode checking disabled | Mailrise/msmtp, needrestart.sh and cron installation/delivery |
| Optimizations | OPT-001 through OPT-007 reviewed offline; Phase 3A and proposal register added | Accepted live timing/antenna/network baseline before any optional experiment |
| Primary | Preserved during standby rebuild, including shared antenna power | Its own fresh inspection and later separately approved rebuild |

The accepted source stage remains `/home/ama/.ntp-source-build-v5`.
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

## Exact resume point

The October 12 mDNS requirement is implemented in repository recipes,
runtime argument validation and source acceptance. The source recipe no longer
disables registration; acceptance requires `HAVE_DNS_SD_H`, and the runtime
template requires `-m`. The optional `ntp.conf` directive `mdnstries` controls
retries, not enablement. NTPsec retains only SHM because GPSD owns serial/PPS
devices and exports both signals. No live package/build/runtime changes were
performed for this requirement; the accepted v5 candidate remains unchanged.

Eight Avahi/DNS-SD development/runtime requirements were pinned from the
retained signature-verified Trixie index, bringing the foundation manifest to
56 requirements. Fresh dependency resolution must confirm their closure and
calculate the exact delta; the prior zero-delta expectation no longer applies.
The earlier snapshot and sealed resolution bind the previous recipe and must
not be used to satisfy this revised requirement. Preserve those records.

The revised-recipe v3 capture bundle is prepared and validated offline. Obtain
hash-bound approval for one capture and conditional terminal readback/cleanup,
execute it once, and accept the validated snapshot. Then seal metadata resolution against that
accepted snapshot. Use the checked-in recipe and pinned assets;
recheck snapshot freshness and bound target inputs before resolution. Review
dependency closure, exact native simulation delta and continuity before offline
foundation preparation. This does not authorize reinstalling the accepted
foundation or changing the live APT lists.

After accepted mDNS prerequisites, prepare a new unprivileged source build and
acceptance, then a separately approved destination/collision inspection and live source
installation bundle with explicit metadata, pre-state, backups, rollback and
acceptance. Preserve the accepted v5 stage and receipts. Runtime configuration,
mail/cron, hardware, dual-stack/DNS/UniFi and reboot acceptance follow their
reviewed stages. Earlier approvals have been consumed; further target contact
requires a scoped approval.

The earlier v2 read-only snapshot capture is accepted for its previous recipe
and its stage was cleaned up. The revised-recipe v3 capture remains unexecuted
and is not accepted.
No fresh metadata resolution or new package transaction has been executed. Fresh source-stage
transport bindings and complete live installation/runtime profiles remain pending.
OPERATIONS identifies these gaps; this history does not certify an unattended
end-to-end installer or a completed deployment. No new live action is authorized
by this history entry.
