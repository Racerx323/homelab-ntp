# NTPsec implementation history

The [governing architecture](docs/ntp-architecture-deployment-plan-v1.0.md)
defines the approved design and acceptance criteria. This file records
repository observations, operation outcomes, deviations, and the next gate.
A plan entry or history entry does not authorize live action.

## Current status

| Field | Value |
| --- | --- |
| Phase | Phase 1 v2 evidence reviewed; IPv6 loopback time probe passed; operator confirmations remain |
| Last updated | `2026-09-16` |
| Reported live state | j1-svntp1 snapshots show NTP/GPSD running, PPS selected and stratum 1; IPv6 loopback time reply verified; full baseline unaccepted; j1-svntp not contacted |
| Current repository state | Phase 1 checklist updated; v3 response-validation fixes tested offline; IPv6 probe executed successfully; exact executed artifacts preserved |
| Current next single gate | Complete operator inputs for image/media/bootstrap specification before concrete media-only scope |
| Authorization boundary | V2 and IPv6 probe completed; requested read-only UniFi switch/port lookup completed. No further live action, cleanup or mutation authorized |

## Repository observations

The repository audit on `2026-08-10` found skeletal `client/` and
`ntpsec/` trees, no deployable NTPsec configuration or service unit, and no
NTP host group in `homelab-server-configs` inventory. The private ignored
Unbound local-zone fragment had IPv4 A and PTR data for both nodes but lacked
the agreed NTP AAAA, IPv6 PTR, and SRV records. Pi-hole forwarded the ULA
reverse namespace to Unbound. `homelab-network` recorded the Default LAN
ULA and DNS VIP design but had no NTP-specific firewall and DNAT runbook.
All four repositories had clean `main` worktrees before the foundation change.

The inventory inspection on `2026-09-16` found no NTP group or hosts in
`prod/hosts.yaml`. `prod/groups/all.yaml` declared `needrestart` and
`watchdog` as common configuration and a Mailrise SMTP endpoint. Existing
host files showed a structured hardware, storage, management, and no-HA
schema. These are repository observations, not live node facts. Re-audit DNS
and UniFi before editing them.

## Deviation log

| ID | Date | Deviation | Rationale | Status |
| --- | --- | --- | --- | --- |
| None | 2026-08-10 | No deviations recorded | The plan matches the approved preplanning decisions | N/A |
| HW-001 | 2026-09-16 | Retain working PoE HAT; PoE+ only upon failure; account for shared GPS antenna power | Operator corrected hardware and authorized plan reconciliation | Approved plan v1.3; no live action |
| OS-001 | 2026-09-16 | Insert clean OS rebuild before dual-stack, DNS, and final UniFi policy work | User requested a Trixie rebuild and a full baseline, one node at a time | Approved design; no live action |

Add deviations before implementing work that differs from a locked decision or
accepted phase. Record the operator decision, affected artifacts, validation,
rollback impact, and replacement resume point.

## Implementation journal

### 2026-08-10: preplanning decisions

- Locked permanent ULAs `::50/64` and `::51/64`.
- Accepted equal-priority, equal-weight `_ntp._udp` SRV records.
- Selected one active and one disabled standby DNAT rule per IP family.
- Kept NTP without an HA mechanism.
- Confirmed both nodes have working Internet access and a working manual
  `ntpleapfetch` download path.
- Limited leapfile scope to a systemd four-week schedule and its validation.

### 2026-08-10: repository foundation

- Replaced the generic agent guidance with NTP-specific repository and
  live-infrastructure rules.
- Created this governing plan and linked it from the repository README.
- Made no SSH, DNS-node, NTP-node, or UniFi connection.
- Made no live configuration, service, firewall, DHCP, NAT, or DNS change.
- `git diff --check` passed.
- Markdownlint passed for `README.md` and this governing plan.
- `pre-commit run --all-files` passed ShellCheck, shfmt, Markdownlint, yamllint,
  actionlint, JSON validation, and Gitleaks. Hooks without matching files
  reported `Skipped`.
- `gitleaks detect --source . --no-git --redact --no-banner` scanned the full
  working tree, including untracked files, and found no leaks.
- `AGENTS.md` SHA-256:
  `ce27f170479d9bf39c25633bcd885bd8bff0370ca4c8fb1b396249277076a225`.
- `README.md` SHA-256:
  `68e3d59b87d07917a999f164887cc5f021f408f8bf4c75b6d7632d35da69f000`.
- The final handoff records this plan's SHA-256 because a document cannot
  contain its own stable digest.

### 2026-08-10: governance policy simplification

- Audited `AGENTS.md` and accepted all recommendations from that review.
- Reduced `AGENTS.md` from 229 to 130 lines.
- Removed duplicated architecture values and deployment procedure. The
  governing plan retains those details.
- Removed the unavailable `verify_done` requirement.
- Allowed one scoped approval to cover one complete read-only collection.
- Allowed a persistent deployment approval to include its defined preflight,
  acceptance, and rollback checks.
- Limited immutable artifact hashes to privileged remote scripts and
  preapproved command bundles.
- Limited the Caddy-derived SSH evidence and fail-closed assertion controls to
  privileged remote runners.
- Replaced mandatory regression fixtures for simple collectors with a focused
  dry run or self-test.
- `git diff --check`, focused Markdownlint, the full pre-commit suite, and the
  full working-tree Gitleaks scan passed after the policy change.
- Reviewed the Markdownlint-excluded `AGENTS.md` for stale requirements and
  writing defects.
- Updated `AGENTS.md` SHA-256:
  `b8155034057c4189c0c2c240098b2c7e5c3fe8bd4d668eb89d352fca82c22e96`.
- Made no live-system or controller contact.

### 2026-08-10: README current-state expansion

- Expanded the repository entry point with server hardware and software facts,
  the reported current network behavior, and the approved target changes.
- Added the current tracked layout and explained the placeholder `gitkeep`
  files.
- Added project status, cross-repository ownership, validation boundaries, and
  upstream hardware and implementation references.
- Distinguished reported live behavior from target design and repository-only
  validation.
- Updated `README.md` SHA-256:
  `de0227e797a4accf6bcbdb9e788fa6d9c85299390f6db1c30a822be6e2641d7a`.
- `git diff --check`, focused Markdownlint, the full pre-commit suite, and the
  full working-tree Gitleaks scan passed.
- Made no live-system or controller contact.

### 2026-09-16: Trixie rebuild planning

- Selected Raspberry Pi OS Lite (64-bit), Trixie, in Raspberry Pi Imager as the
  target for both Raspberry Pi 4B nodes. It is based on Debian 13 and is not
  pure Debian. The Debian 11 installations remain on their original SD cards;
  new spare cards will be used for both rebuilds.
- Added one-node-at-a-time clean-rebuild gates, full baseline-app and HAT
  validation, per-host recovery, and complete observed inventory specifications.
- `j1-svntp1` remains first; `j1-svntp` remains second. No live host,
  controller, DNS, or boot-media action was taken in this planning update.
- `git diff --check` and `pre-commit run --all-files` passed after the plan,
  README, and repository guidance changes. The cross-file verifier returned
  `not a git repository` from its own context and supplied no checks; it is
  not counted as verification. The CodeRabbit upload-based review was blocked
  by the workspace approval policy, so only local review was completed.

### 2026-09-16: deployment policy and history split

- Kept one-node-at-a-time rollout and separate authorization for each live node
  or controller stage. One approval may cover a hash-bound bundle from
  preflight through rollback.
- Made CodeRabbit optional and narrowed documentation-only validation to
  focused checks.
- Moved current status, repository observations, deviations, dated outcomes,
  and the resume point out of the governing architecture document into this
  file. No live host or controller action occurred in this repository edit.

### 2026-09-16: pre-commit audit integration

- Kept the shared scaffold hooks and documented a full working-tree Gitleaks
  scan for unstaged and untracked artifacts.
- Set the first NTP executable as the trigger for focused offline regression
  tests, a path-triggered pre-commit hook, and matching CI coverage.
- Retained fixed-flag shfmt checks; deferred a scoped write helper until shell
  scripts warrant one. No live host or controller action occurred.

### 2026-09-16: Munin endpoint requirement

- Added a `munin-node` endpoint to each NTP node's planned Trixie baseline,
  acceptance checks, and inventory components. The
  `homelab-monitoring-observability/Munin` component governs endpoint
  configuration and plugins; the approved poller and address families remain
  to be established from that component and read-only node evidence.
- The existing Caddy-specific Munin files belong to deferred Caddy deployment
  work. They do not establish live Munin service or an NTP endpoint template.
- No NTP node, Munin poller, or controller was contacted or changed.

### 2026-09-16: Phase 1 baseline collector definition

- Implemented [inspect-node.sh](scripts/inspect-node.sh) as a single hashable
  Bash entry point with an embedded Python standard-library engine. The live
  entry point requires root, the exact `j1-svntp1` kernel hostname and a
  Debian/Raspbian 11 release before creating output or starting collection.
- Documented the [output and authorization contract](docs/inspect-node.md):
  protected raw streams and byte-exact configurations, pre/post SHA-256 and
  metadata comparisons, explicit absent/error/unknown states, bounded local
  diagnostics, and separate collection status versus baseline acceptance.
- Covered host/boot-media identity, Pi/GPS/RTC/PPS/PoE evidence, local network
  and DNS ownership, NTPsec/GPSD/leapfile/listener/peer state, and Webmin,
  needrestart, msmtp, munin-node and watchdog evidence. Physical wiring,
  switch port/power, card labels, recovery and historical download success
  require operator confirmation. Unsupported software paths and unproven
  leapfile validity remain open review items.
- Avoided network-manager D-Bus clients that could activate an inactive
  service; capture local runtime files and unit state instead. NTP queries
  are numeric loopback only. The collector never runs ntpleapfetch, opens
  watchdog/serial/PPS device nodes, or executes captured configurations.
- Added 14 focused synthetic tests, including success, identity/release/root
  rejection, destination rejection, incomplete/interrupted output, raw error
  retention, changing files, symlink/special-file handling, reference parsing,
  leap expiration, service-only properties, and shell variable collision
  policy. Fixtures do not run the collector against the workstation or a node.
- Added the same offline test path to a path-triggered pre-commit hook and
  a dedicated CI job. Tests, `bash -n`, ShellCheck, canonical shfmt checks,
  pre-commit validation, working-tree Gitleaks and Git whitespace checks
  passed. The cross-file verifier again reported `not a git repository` and
  is not counted as verification.
- Kept the governing plan unchanged: this implements its existing Phase 1
  scope without an architecture decision. No host, UniFi or DNS contact,
  live collection, boot-media action, service change or live acceptance
  occurred. The final handoff supplies the collector SHA-256.

### 2026-09-16: persistent workstation evidence destination

- Selected `/home/aaron/code/.local-evidence/homelab-ntp/j1-svntp1/phase1-20260916/`
  for retained workstation evidence, including transport streams, status
  records, transfer hashes and retrieved collector output. Local evidence
  must persist beyond workstation/WSL shutdown and remain outside Git.
- Retained the node's `/var/tmp` staging and collection paths, with verified
  retrieval into the persistent local archive. Documented exclusive operation
  directory creation, owner-only permissions and retention of partial results.
- This changes the operation contract only; the collector and its SHA-256
  are unchanged. No collection, node contact or live execution was authorized
  or performed by this destination correction.

### 2026-09-16: authorized attempt stopped at SSH trust gate

- User authorized the complete read-only operation for `j1-svntp1`
  (`10.1.0.51`) and specified SSH user `pi`, bound to collector SHA-256
  `55868258e5e694fadeef5b862e0c42e8461b99e38931e45d76855e4e25bf5948`.
  Verified the local collector against that hash and preserved an exact copy
  with the authorized contract in the protected workstation evidence directory.
- SSH returned `255`: no ED25519 host key was known for `10.1.0.51`, and
  strict host-key checking rejected the connection before authentication.
  No remote staging, sudo execution, collector run or baseline capture occurred.
- Preserved separate stdout/stderr, transport status, the transport wrapper,
  authorization record, failure outcome and local evidence SHA-256 manifest in
  `/home/aaron/code/.local-evidence/homelab-ntp/j1-svntp1/phase1-20260916/`.
  Confirmed owner-only local file permissions. There are no remote pre/post
  hashes or collector status because the collector never started.
- Did not enroll a host key, bypass strict checking, retry, clean up evidence,
  contact another node/controller, or change any live configuration or service.
  Baseline acceptance remains open. The failed-attempt directory is retained
  and must not be reused or overwritten by a later attempt.

### 2026-09-16: resumed collection with corrected SSH account

- User reported host keys repaired and corrected the account to `ama`, FQDN
  `ntp1.local.theama.co`, IPv4 `10.1.0.51`. Resumed the authorized operation
  with the unchanged collector hash and strict host-key checking, connecting
  directly by IPv4 without DNS lookup. Retained the original failure archive.
- The collector ran once. The transport wrapper recorded SSH status `0` and
  collector status `3`. Retrieval SSH status was `0`; all 288 transferred
  files passed SHA-256 verification, including the exact executed collector.
  Evidence resides in
  `/home/aaron/code/.local-evidence/homelab-ntp/j1-svntp1/phase1-20260916-attempt02/`.
- All 113 captured regular-file content hashes matched. Only modification
  times on three `/run/resolvconf` entries differed; preserve the failed
  metadata comparison rather than claiming acceptance. Six diagnostic
  commands failed because ntpq/iptables-save/ip6tables-save were unavailable
  on the collector PATH. Masked-unit `/dev/null` handling also needs correction.
- Observed Debian 11.11, Pi 4B Rev 1.4, NTP and GPSD processes under
  `/usr/local/sbin`, and dual-stack listeners. Peer health and actual startup
  ownership remain unverified. Recorded the detailed
  [sanitized result and follow-up requirements](docs/baseline-j1-svntp1-20260916.md).
- No collector rerun, remediation, cleanup, other-node/controller contact,
  ntpleapfetch execution, or service/network/boot configuration change occurred.
  Baseline acceptance remains open. Documentation, working-tree secret scan
  and Git whitespace checks passed after recording the result.

### 2026-09-16: corrected collector and deployment-guide review

- User authorized preparation/offline validation of the follow-up and its
  subsequent hash-bound live authorization request. Implemented schema v2
  without changing the preserved executed v1 artifact or its original result.
- Added explicit, ownership-checked ntpq discovery across system and local
  installation paths; ambiguous, unsafe and missing candidates remain errors.
  Captured process ancestry/cgroups, startup definitions, unit masks and
  separate resolver-runtime timestamp differences. Configuration bytes,
  ownership, modes, links, types and path membership remain protected.
- The user supplied the original NTPsec microserver deployment guide. Local
  reinspection of existing captures confirms `timeservice.service` enabled
  and active/exited, invoking `/etc/init.d/timeservice`. V2 explicitly selects
  that unit and captures the init script and associated udev/pinup policy.
  No guide command or startup script was executed.
- Adopted the user's minimal local evidence layout: reuse
  `/home/aaron/code/.local-evidence/homelab-ntp/j1-svntp1/`, with only
  `baseline-v2.tar`, `baseline-v2.stdout`, `baseline-v2.stderr` and
  `baseline-v2.status.json` for the proposed run. Verify the archive without
  duplicating it as an extracted tree. No new local evidence directory was
  created and no existing evidence was deleted or overwritten.
- All 21 offline tests passed, including custom/ambiguous/untrusted executable
  discovery, timeservice capture without execution, masked units, disappearing
  processes, and strict checks on content/permissions despite runtime mtime
  changes. Shell syntax, full pre-commit, working-tree secret scan and Git
  whitespace checks passed. The final handoff supplies the new collector hash.
- No node contact or v2 execution occurred. The governing plan is unchanged.

### 2026-09-16: authorized v2 run and archive verification

- User authorized v2 hash
  `ba6dcaea5e98eb02eaeb3dd5aaead99845df42bd01bdab4b60ee9a87d9e1e82f`
  and requested a completion summary plus next-action prompt. Ran it once as
  root through `ama@10.1.0.51`, with strict host-key checking and no DNS lookup.
- Collection and retrieval SSH statuses were both `0`; collector status was
  `2`. Verified all 377 transferred files inside `baseline-v2.tar` without
  extraction. Retained only the four agreed files in the existing host evidence
  directory; created no new local action directory.
- Protected integrity passed across 420 paths and 148 regular-file hashes.
  Recorded three resolver runtime mtime differences separately. No ntpq
  discovery, mask-handling or startup-observation errors remained.
- Confirmed `/usr/local/bin/ntpq` and both daemon cgroups under
  `timeservice.service`. IPv4 evidence shows PPS selected with reach `377`,
  system stratum `1` and leap `00`. IPv6 loopback control query timed out
  despite exit `0`; captured IPv6 `noquery` policy lacks a loopback exception.
  Six clock-variable queries on network peers reported `BADASSOC` despite
  exit `0`. These response errors remain open even though absent from the
  collector's exit-code-only issue list.
- The two exit-code errors were unavailable iptables-save tools; nftables
  output was empty with status `0`. No tools were installed or configuration
  changed. See the [updated sanitized result](docs/baseline-j1-svntp1-20260916.md).
- Preserved original results/artifacts and owner-only evidence permissions.
  No retry, cleanup, service/network/boot change, ntpleapfetch execution or
  other-node/controller contact occurred. Documentation, working-tree secret
  scan and Git whitespace checks passed after recording the outcome.

### 2026-09-16: repository-only evidence checklist and minimal probe

- Reviewed `baseline-v2.tar` directly, without extraction or new evidence
  files/directories. Added the [Phase 1 checklist](docs/phase1-evidence-checklist.md)
  covering observed facts, unknowns and operator confirmations for every
  baseline area. No node contact occurred.
- Captured IPv6 default `noquery` with no loopback exception is consistent
  with the ntpq control timeout; it does not establish failure of IPv6 time
  service. Planned permanent ULA is absent from the snapshot. DNS contents
  match the VIPs, but DHCP/RA resistance remains unproven.
- Package/config evidence did not discover Webmin, msmtp, munin-node or
  userspace watchdog at sampled locations. Custom installs or intentional
  absence require confirmation. Needrestart is installed; notification and
  effective restart policy remain unaccepted. Physical recovery is still open.
- Corrected unexecuted collector schema v3 to preserve zero process statuses
  while reporting ntpq response errors, and issue clock-variable queries only
  for confirmed refclocks. Archived replay detects all seven response errors
  and distinguishes two SHM refclocks from six network peers. Missing-tool
  evidence and both executed collector artifacts remain unchanged.
- Added `inspect-ipv6-time.sh`: one five-second-bounded, numeric IPv6 loopback
  NTP time request with identity/response validation; no root, remote files,
  configuration change or time adjustment. This is the smallest proposed
  live software diagnostic, not a full baseline rerun. Its scope and output
  requirements are documented in the checklist; final handoff supplies hashes.
- All 27 offline tests passed; shell syntax, ShellCheck, shfmt, pre-commit,
  working-tree secret scan and Git whitespace checks passed. The same offline
  runner covers the probe in CI. No live execution, installation, cleanup or
  rebuild occurred. The governing plan is unchanged.

### 2026-09-16: authorized IPv6 loopback time probe

- Executed `inspect-ipv6-time.sh` once as `ama@10.1.0.51`, without sudo,
  under SHA-256
  `1802267547ed5cadc865da86eb95d5da6ff90ad39825f0e0abdfeafc29b12573`.
  Verified the source locally and in remote memory; created no remote files.
- One request to `[::1]:123` returned a valid NTPv4 response at stratum `1`,
  leap `0`, at `2026-09-16T22:31:01 UTC`. SSH status and probe status were
  both `0`; packet validation also passed against the retained request locally.
- Retained only `ipv6-time-v1.stdout`, `ipv6-time-v1.stderr` and
  `ipv6-time-v1.status.json` in the existing host evidence directory, with
  owner-only permissions. Exact source, command, separate statuses, response
  and stream hashes are preserved; no additional directory or archive needed.
- No retry, package installation, configuration/service/network change,
  time adjustment, cleanup or other-node/controller contact occurred.
- Updated the Phase 1 checklist. IPv6 loopback time service is evidenced;
  external client reachability and control-query access remain distinct.
  Documentation, working-tree secret scan and Git checks passed.

### 2026-09-16: operator recovery-access confirmations

- Aaron confirmed physical access and ability to swap j1-svntp1's SD card
  during a future maintenance window. His micro-HDMI KVM/laptop console has
  previously worked with this node.
- Confirmed a SanDisk Max Endurance microSDXC 128 GB spare, USB card reader,
  and ability to retain the existing Debian 11 card untouched for rollback.
- Recorded these statements in the Phase 1 checklist. Physical card identity
  and labelling, a recovery procedure and actual recovery verification remain
  open; no new hardware/media/console test, live access or mutation occurred.

### 2026-09-16: physically observed HAT details

- Aaron confirmed physical observation as the source: Uputronics GPS/RTC
  Expansion Board rev 5.9, dated 2020; Raspberry Pi PoE HAT, dated 2018.
- Recorded stack order as Pi, PoE HAT, GPS HAT; antenna attached to GPS HAT
  and inter-board connection through 40-pin GPIO. Additional jumper wires,
  antenna connector type and exact PPS pin assignment remain unconfirmed.
- Flagged the PoE HAT versus governing-plan PoE+ HAT discrepancy for
  reconciliation before candidate configuration. No inference about the
  other node, PoE PCB revision, negotiated power class or budget was made.
- Updated only the checklist and this history; no node/controller contact,
  evidence directory creation, media operation or service change occurred.

### 2026-09-16: jumper confirmation and authorized UniFi lookup

- Aaron confirmed no separate jumper wires: only the 40-pin header.
- Under his explicit request to poll UniFi, used the documented local audit
  credential with verified TLS and read-only GET requests. Matched baseline
  eth0 MAC to client, switch MAC and port index.
- Identified P-D1-SW8LPOE, USW Lite 8 PoE, port 3 (`J1-SVNTP1:1`).
  At 22:57:48 UTC, link was up at 1000 Mbps/full duplex; PoE good, auto,
  reported Class 3, measured 2.88 W. Per-port allocation remains unknown.
- Retained one protected sanitized `unifi-port.json` in the existing host
  evidence directory. No new directory, node access or controller mutation.
  The broader UniFi policy audit was not performed.

### 2026-09-16: shared antenna and application confirmations

- Aaron reported a GPS Source L1G1A-STD antenna shared by both NTP nodes
  through a Uputronics SMA GPS splitter, initially described as three-port
  and subsequently corrected to two-output, powered by a GPS board.
  The powering node and installed splitter port mapping remain unknown.
- Manufacturer documentation describes one DC-pass receiver connection and
  DC-blocked alternatives. Recorded the shared GPS dependency and the risk
  that powering down the supplying node affects both receivers. Maintenance
  planning must resolve that dependency; no power-loss test was performed.
- Recorded j1-svntp1 operator reports: Webmin, munin-node and watchdog not
  currently installed; needrestart manually installed. Aaron immediately
  corrected his initial msmtp answer to not currently installed, consistent
  with captured non-discovery. No additional msmtp inspection is needed to
  resolve that answer. Needrestart matches captured evidence.
- Updated checklist and resume point only. No live access, additional evidence
  directory, installation or configuration change. Governing-plan reconciliation
  awaits the antenna power-path details; no new architecture was selected.

### 2026-09-16: antenna powering node visually confirmed

- Aaron visually verified that j1-svntp currently supplies the shared antenna's
  power. Updated the checklist; the earlier unknown powering-node field is
  resolved. The subsequent two-output correction below removes the
  unused-third-output question.
- First-node rebuild planning must preserve j1-svntp's running antenna-power
  path. The later j1-svntp outage needs an approved power-continuity and
  surviving-service procedure; no power-loss or failover test has occurred.
- Documentation-only update; no live access, wiring/power change or new
  evidence directory. Governing architecture remains unchanged pending
  reconciliation of the maintenance dependency and PoE HAT model.

### 2026-09-16: splitter output-count correction

- Aaron corrected the splitter to the two-output model, one output per NTP
  node. Removed the unused-third-output question from the checklist and
  resume point. The visually confirmed j1-svntp antenna-power source stands.
- Documentation-only correction; no new live action or architecture decision.

### 2026-09-16: approved hardware and shared-antenna plan reconciliation

- Updated governing plan to v1.3, retaining its stable filename. Retain
  j1-svntp1's working 2018 PoE HAT. Aaron reports the model is no longer
  available and selected PoE+ replacement upon failure, with separately
  authorized compatibility, power/fan and recovery validation.
- Removed unsupported PoE+ assumptions from per-node acceptance and inventory;
  j1-svntp's HAT model remains pending its own confirmation.
- Incorporated the shared L1G1A-STD antenna, two-output splitter and visually
  confirmed j1-svntp power source. Preserve that path during j1-svntp1 rebuild;
  require an approved and verified continuity arrangement before j1-svntp's
  outage. No alternative power hardware or rewiring was selected.
- Aligned README and Phase 1 checklist. No live contact, service change,
  purchase, evidence directory creation or hardware operation occurred.

### 2026-09-16: repository-only candidate and recovery planning

- Added [Trixie candidate/recovery plan](docs/trixie-candidate-recovery-plan.md)
  from captured baseline and operator confirmations, under governing plan v1.3.
- Defined target-input requirements for image/bootstrap, networking, HATs,
  GPSD/NTPsec, leap maintenance and baseline applications. No guessed target
  paths, overlays, units or installable configuration were generated.
- Separated media preparation, first-boot discovery, candidate deployment and
  acceptance scopes. Defined old-card recovery triggers, sequence, verification
  and primary/shared-antenna preservation; recovery remains unexecuted.
- Focused Markdown, local-link, full working-tree secret scan and Git
  whitespace checks passed. Documentation-only work required no behavior tests.
- Kept Phase 1 acceptance open and identified remaining image/media, access,
  maintenance-duration and acceptance-threshold inputs. No node, controller,
  DNS, package, boot-media or service action occurred; no evidence tree created.

### 2026-09-16: image/media and bootstrap specification draft

- Added [image/media/bootstrap specification](docs/image-media-bootstrap-spec.md)
  with exact official Raspberry Pi OS Lite arm64 Trixie release 2026-09-15 and
  published compressed-image SHA-256. Public catalogue checked; binary and
  release-note browser fetches returned 403. No image downloaded or verified.
- Defined spare-card identity/erase gates, bootstrap account/key and network
  choices, new SSH host identity handling, recovery-budget requirements and
  baseline-gap classification. Requested missing operator inputs; no values
  were inferred from the WSL workspace or the old installation.
- No media enumeration/write, application installation, node/controller/DNS
  access or new evidence directory. Governing plan remains v1.3.

### 2026-09-16: Windows writer and password-first bootstrap confirmed

- Aaron confirmed a Windows workstation with the USB reader connected
  directly, and the spare SD card new in its packaging. Disk identity and
  authorization to write the identified card remain separate gates.
- Confirmed ama as administrator, initial password-authenticated SSH over
  Ethernet eth0, a password set privately in Imager, and Wi-Fi disabled.
  Public-key installation follows first boot; its source remains pending.
- Replaced the draft key-only-from-imaging proposal. Defined key-session and
  sudo verification before any later approved password-authentication removal.
  Verify actual Wi-Fi state rather than equating absent credentials with a
  disabled radio. No live access, media write or credential collection occurred.

### 2026-09-16: Imager version and static IPv4 bootstrap choice

- Aaron reports Windows Imager 2.0.11.1 and requests static Ethernet IPv4
  configuration in Imager for first boot, using the governing node addressing.
- Recorded the choice separately from capability: official documentation and
  v2.0.11 release notes did not establish the requested static Ethernet UI.
  Actual screen/field verification remains open; no DHCP fallback selected.
- Updated specification and history only; no media or live-system action.

### 2026-09-16: DHCP-first bootstrap correction

- Aaron selected Ethernet DHCP for first boot, followed by static assignments
  after first boot. This supersedes the Imager static-IP request and removes
  the pending static-address UI question.
- Updated the specification to observe the DHCP address through the KVM,
  verify target identity before SSH, and discover the target network manager
  before a separately scoped static configuration and reconnection check.
- Documentation-only correction; no media write, live access or controller
  change. Markdown, local document links and Git whitespace checks passed.

### 2026-09-16: operator DHCP address discovery preference

- Aaron will identify the first-boot IPv4 address through UniFi Network,
  using the KVM if that lookup fails. Updated the specification to correlate
  the current client record with the captured Ethernet MAC and preserve
  separate SSH host-key verification.
- No agent controller access or live action authorized or performed.
  Focused Markdown, local-link and Git whitespace checks passed.

### 2026-09-16: unrestricted first-node maintenance timing

- Aaron allows maintenance anytime and a j1-svntp1 outage as long as needed.
  Updated both planning documents to remove mandatory discovery deadlines
  and recovery-time budgets; retained failure-based recovery and operator stop.
- Individual checks remain bounded and acceptance/observation criteria remain
  required. This timing choice authorizes no media write or live action and
  does not extend the outage allowance to j1-svntp.
- Focused Markdown, local-link and Git whitespace checks passed.

## Exact resume point

Complete exact spare disk identity, public-key reference and locale in the
[bootstrap specification](docs/image-media-bootstrap-spec.md). Windows Imager
2.0.11.1, anytime maintenance with no fixed j1-svntp1 outage limit, direct reader
access, new packaged spare, ama, password-first Ethernet
SSH using DHCP and disabled Wi-Fi are confirmed. Aaron will discover the
address in UniFi Network first, with KVM fallback. Apply static assignments only
after first boot and observed target network ownership, under the later
configuration scope. No Imager static-IP UI investigation remains. No media
write, live preflight or first boot is authorized. Preserve old media, working
HAT and primary antenna power; baseline acceptance remains open.
