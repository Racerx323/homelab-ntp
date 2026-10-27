# Second-host fleet qualification

Status: repository procedure prepared; no target selected or contacted, no live
execution authorized. Use [clockmaker](../README.md) from a clean, reviewed
checkout. The [architecture plan](ntp-architecture-deployment-plan-v1.0.md) defines
requirements; [readiness](PRODUCTION-READINESS.md) retains production status.
OBS-02 acceptance and D1–D5 limitations are unchanged. This procedure establishes
the repeatable core install; it does not close all production observation gates.

## Scope and prerequisites

Select and deploy a second host only after the accepted production deployment of
J2-SVNTP1. Meanwhile, keep procedure implementation and qualification local.
For the later trial, qualify one fresh host while a different host serves time. Identify
both hosts explicitly. A disposable second host may qualify the procedure;
promotion to the existing other production node still requires the plan's
Phase 3 completion and Phase 3A review. Do not change DNAT or peer configuration.

The implemented platform contract is Debian-family Linux with systemd, native
source builds under `/usr/local`, `/dev/serial0` at 115200 baud and `/dev/pps0`.
The devices must resolve to root-owned character devices. This is the current
supported interface, not a claim that every Pi, receiver or Debian release works.
Record OS, architecture, kernel, receiver/HAT, UART/PPS mapping, Python version
and module directory for the selected host. Other hardware needs qualification
before adapting the contract; do not substitute pilot hardware observations.

| Prerequisite | Owner and required input |
| --- | --- |
| Base OS and tools | `homelab-server-configs`: updated supported OS, completed required reboot, clean package state, declared recipe build packages and versions. Preserve any explicit update exceptions. |
| Accounts and access | Fleet baseline: non-root NTP user/group, root execution access, independently usable console and recovery media. Confirm peer/shared-power continuity. |
| Hardware | Fleet/platform configuration: working UART/PPS devices and observed TOFF/PPS SHM unit mapping. Receiver provisioning is outside clockmaker. |
| Network and naming | Owning inventory, network and DNS repositories: unique hostname, fixed IPv4/IPv6, approved clients, upstreams, DNS and firewall policy. |
| Service baseline | Loaded `systemd-timesyncd.service`, active/inactive and enabled/disabled; timeservice inactive/disabled or absent; competing GPSD/time services and sockets inactive. Package-provided GPSD/NTP applications must be absent. |
| Fleet services | Webmin, watchdog, needrestart and Munin remain in their owning repositories. Record required integration readiness; these are not installed by clockmaker. |
| Artifacts | Reviewed recipe, authenticated source releases matching its digests, current leapfile and pinned repository revision. Clockmaker checks archive hashes; it does not independently authenticate publisher signatures. |

Resolve missing facts through a single scoped current-state assessment within the
approved deployment outcome. Do not require historic pilot receipts. Do not start
installation while hardware mapping, account identity or recovery access is unknown.

## Inputs, outputs and approval

Choose absolute paths for `CHECKOUT`, `CACHE`, `INPUTS`, `WORK` and `JOURNALS`.
`CACHE` holds immutable source archives once. `WORK` is private, writable by the
unprivileged builder; `JOURNALS` has protected root-owned ancestors and mode 0700.
Use new output/journal directories for each operation. Root commands must use the
same reviewed checkout and hash-bound inputs; never execute build steps as root.

Prepare these files; paths within profiles are relative to the containing file:

| File | Contents |
| --- | --- |
| `host.json` | Closed schema: `schema: 1`, exact `hostname`, `recipe: {path, sha256}`, installed `packages` mapping and `python: {executable, version, module_directory}`. Python executable is `/usr/bin/python3`; version is `[major, minor]`. Packages cover recipe `build_roots` plus Python/compiler/runtime prerequisites checked by `prepare`. |
| `configuration.json` | `schema: 1`, matching `hostname`, hash-bound `ntp_config`, `unit` and `leapfile` objects (`path`, `sha256`), plus `timeservice` configuration. Use the maintained unit template and explicit daemon arrays, UART device and startup gate. |
| NTP/supervisor inputs | Canonical storage paths from the README, non-root `-u USER:GROUP`, foreground daemons, NTP mDNS flag, observed SHM mapping, approved upstream/ACL configuration. Gate: 30 seconds, five matches per source, distinct observed `TOFF`/`PPS` units; declare acquisition policy. No invented mapping or unbound NTP includes. |
| `service.json` | The [service profile schema](../README.md#fresh-configuration-and-service-lifecycle): matching hostname, hash-bound generated release and configuration profile, explicit health peers/addresses, observed daemon credential arrays, independent client identity/source addresses and timing bounds. |
| Run record | Target/peer identities, revision and input digests, permitted actions, selected deadlines, independent recovery arrangement, external client vantage, outputs and acceptance decisions. |

The release digest exists only after building. Approval may cover the declared
build and generation of its manifest from pinned inputs, with review before root
installation; declare this branch explicitly. Likewise, preflight state and backup
digests are runtime outputs. Record them without pretending they were known in
advance. Bind executable/configuration changes and changed effects to renewed
approval, not unrelated documentation or appended results.

Use one operational approval covering the named host, preflight, build, file and
service changes, bounded diagnostics, recovery and one conditional reboot.
Notifications, failure injection, firmware updates or additional reboots require
explicit inclusion. No such live scope is approved by this document.

## Execution sequence after approval

The following are command templates, not a shell script. `CLOCK` is
`CHECKOUT/ntpsec/scripts/clockmaker.py`; every uppercase path/digest is an explicit
run input. Invoke with `/usr/bin/python3 -I -B "$CLOCK"` followed by the arguments
below. Capture stdout, stderr and exit status separately for every command; stop
on failure. For preflight, preserve unmodified stdout JSON as `STATE` and hash it
only after a zero exit status. Do not mix diagnostics into that JSON.

| Step / privilege | Arguments and result |
| --- | --- |
| Prepare / unprivileged | `prepare --input HOST --sha256 HOST_SHA --artifact-cache CACHE --output PREPARED`; retain `PREPARED/profile.json` and its digest. |
| Build preflight / unprivileged | `preflight --for build --input PROFILE --sha256 PROFILE_SHA --artifact-cache CACHE`; verify current native identity, package and Python assumptions. |
| Build / unprivileged | `build --input PROFILE --sha256 PROFILE_SHA --artifact-cache CACHE --output CANDIDATE`; retain `CANDIDATE/release.json`, staged payload and `build.log`. Upstream checks must pass. |
| Configuration check / unprivileged | `preflight --for configure --input CONFIG --sha256 CONFIG_SHA`. |
| Configuration staging / unprivileged | `configure --input CONFIG --sha256 CONFIG_SHA --output CONFIGURATION`; review rendered files. Create the service profile bound to this configuration and the generated release. |
| Install preflight / root | `preflight --for install --input RELEASE --sha256 RELEASE_SHA`; save a fresh install state. Daemons must be stopped; bootstrap time may remain active. |
| Install / root | `install --input RELEASE --sha256 RELEASE_SHA --state STATE --state-sha256 STATE_SHA --journal INSTALL_JOURNAL`; require `copied_not_activated` in `receipt.json`. |
| Apply preflight / root | `preflight --for apply-configuration --input SERVICE --sha256 SERVICE_SHA`; save a new apply state. This invokes the real systemd unit parser and checks installed release/device/service state. |
| Apply / root | `apply-configuration --input SERVICE --sha256 SERVICE_SHA --state STATE --state-sha256 STATE_SHA --journal APPLY_JOURNAL`; require `configured_inactive` in `status.json`. |
| Activate preflight / root | `preflight --for activate --input SERVICE --sha256 SERVICE_SHA`; save a new activation state after application. |
| Activate / root | `activate --input SERVICE --sha256 SERVICE_SHA --state STATE --state-sha256 STATE_SHA --journal ACTIVATE_JOURNAL`; require `awaiting_acceptance`; boot enablement remains disabled and the timer remains armed. |
| Independent client / operator | Transfer `ACTIVATE_JOURNAL/client-challenge.json` with its digest to the declared client using the approved channel. Run `check-client --input CHALLENGE --sha256 CHALLENGE_SHA`; return captured JSON and its digest. |
| Accept / root | `accept-service --input RECOVERY_PLAN --sha256 PLAN_SHA --client-result RESULT --client-result-sha256 RESULT_SHA`; repeat native checks, enable startup and require `active_enabled`. |

Each mutation repeats its preflight. Never reuse another phase's state, overwrite
a consumed journal or run a successor solely because a command returned nonzero.
Retain the generated release and current-run backups outside the target's sole
failure domain before reboot. Artifact and record paths are configurable; no
historical evidence directory may be mounted, copied or imported as a prerequisite.

## Health and reboot acceptance

Record actual observations and failed criteria, not just a final pass flag.

| Gate | Required evidence / implementation boundary |
| --- | --- |
| Automatic activation | Same unrestarted invocation, exact GPSD/NTP credentials, mapped PPS selection, both refclocks reachable, three authenticated/reachable NTS associations with cookies, leap 0, stratum 1, precision limits, clean service/Avahi error journal and local dual-stack replies. Trial remains disabled at boot until external acceptance. |
| Governing timing criteria | Three consecutive samples at least 30 seconds apart, absolute selected PPS offset at most 5 ms and jitter at most 1 ms. Set these explicitly in the profile; choose and approve the cold-acquisition deadline within the implemented 90–1200-second bound; the independent recovery timer expires after 1800 seconds. Record system and peer measurements. |
| Additional native checks | Retain the native measurements supporting the checks above. Inspect intended listeners and SHM mapping/access against current platform inputs; successful startup/peer checks do not independently measure physical pulse accuracy. |
| Independent clients | From approved external IPv4/IPv6 vantage points, verify PPS/stratum-1 responses, administrative queries denied and required mDNS advertisement. Local UDP checks do not establish external ACLs or discovery. Use `clockmaker.py check-client`, which invokes the pinned client library and binds the result to this trial. Never hand-author a passing result. |
| Recovery | Demonstrate the approved recovery branch below and verify bootstrap state; distinguish bootstrap availability from precision NTP acceptance. Local transaction tests are not native recovery evidence. |
| Reboot | Only after pre-reboot gates and backup/access checks pass, perform the single approved ordinary reboot. Record old/new boot IDs and external outage times. Verify automatic start, addresses, device mapping, release/configuration hashes, timing, NTS, journal and external-client checks again. |
| Resilience and observation | Measure usable-NTP recovery against the operator's five-minute normal-operation requirement. A longer testing outage does not satisfy it. Record any precision/convergence miss separately. Final sustained-observation duration and reset/tolerance rules still need a decision; a successful boot does not close them. |

Activation now separates trial from persistence and provides independent systemd
recovery. Client results must match the challenge, boot, service invocation and
source addresses, be at most 120 seconds old and arrive with at least five
minutes remaining before expiry for bounded commit/recovery. Native
acceptance rechecks health before enabling startup. These are repository-qualified
controls; actual systemd expiry, external client behavior and reboot persistence
still need the later authorized native trial. No second host is selected now.

## Recovery and interruptions

- Before effects, preserve the serving peer, attended console/media access and
  current-run backups. Declare stop/escalation deadlines in the run record.
- A failed configuration/activation attempt tries same-boot restoration. Inspect
  `status.json`, command output and backups. For an incomplete attempt, use
  `recover-service --input RECOVERY_PLAN --sha256 RECOVERY_SHA`, where the plan is
  that journal's `recovery.json`. Use `restore-service --input RECOVERY_PLAN --sha256 RECOVERY_SHA` for deliberate
  reversal of a completed phase, preserving its completion record. Recovery rejects
  changed boot, corrupt backups and unrelated file drift. Retain all partial results.
- To qualify this branch natively, the live scope may include one controlled
  catchable interruption of activation after the bootstrap stops and before
  completion. Specify observation/control method and cleanup in the live review.
  Include a controller-loss trial to observe the independently armed timer. Do
  not use a fake sender, synthetic health result, panic or power cut. This
  branch is proposed, not authorized or proved by repository tests.
- The current-run systemd timer protects an unfinished trial against controller
  exit/SIGKILL. It does not survive reboot/power loss. Preserve native recovery
  failures and use console recovery for a wedged host. Completed restoration is
  attended and resumable, without arming a new trial timer. Do not replay work.
- Source `rollback --input INSTALL_RECEIPT --sha256 RECEIPT_SHA` supports completed
  installs and interrupted installs with completed pre-mutation backups. It
  requires stopped daemons and original/intended file state, verifies all backups
  before effects, and can resume an interrupted rollback. Reverse activation,
  then configuration, then source files; do not remove a running service's code.
  A failed backup phase has no source-file effects and requires state inspection.
- Preserve statistics/drift data. Confirm restored file/service state, peer
  continuity and client health. Record whether recovery restored bootstrap only
  or the accepted precision service. Recovery cannot undo clock corrections.

## Completion and remaining work

A second-host result must identify the exact revision, profile/artifacts, native
build results, installation/configuration receipts, acceptance measurements,
recovery outcome and reboot outcome. Missing gates remain open. Confirm no prior
pilot evidence was used and that the same procedure works from the supplied
checkout/cache/host inputs. Preserve failed criteria and OBS-02/D1–D5 limitations.

Second-host selection and its single deployment approval are deferred until
J2-SVNTP1's production deployment is accepted. That later review will bind current
host inputs, client/recovery commands and deadlines to this reusable procedure.
Do not execute this generic document or treat local tests as native acceptance.
NTP maintenance scheduling (leap refresh, statistics retention and reporting)
and fleet monitoring integration remain separate reusable-procedure work; core
service qualification does not install or accept them. After native qualification,
map remaining callers before retiring historical wrappers. Evidence deduplication
or deletion requires a separate retention scope.
