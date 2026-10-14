# NTPsec deployment history

The [architecture plan](docs/ntp-architecture-deployment-plan-v1.0.md) owns
approved design and acceptance criteria. [OPERATIONS](docs/OPERATIONS.md) owns
the reproducible procedure. This history records milestones, deviations,
observations and the next deployment gate. Entries do not authorize live action.

## Current deployment state

Last reconciled: October 14, 2026. These are retained observations, not a new
live inspection.

| Component | Accepted state | Still pending |
| --- | --- | --- |
| Rebuilt node | Former j1-svntp1 renamed j2-svntp1; spare-card first boot accepted | Full hardware/time/network acceptance |
| OS/access | Debian 13 Trixie, aarch64, kernel 6.18.50+rpt-rpi-v8; fixed Ethernet IPv4/ULA, RA, DNS, routes, dual-stack egress and pinned-key SSH accepted | Reboot persistence; Wi-Fi disablement |
| Foundation | 686 package records; original foundation, pps-tools, bc and seven mDNS prerequisites accepted; installation control cleanup complete | Preserve accepted inventory and recheck it before further live changes |
| Source candidate | GPSD 3.27.5 and NTPsec 1.2.5; new mDNS-enabled build/tests/native staging accepted; 159-entry manifest; v5 evidence preserved | Native installation and runtime prerequisites accepted; final configuration and activation pending |
| Runtime | Hardware continuation, account/runtime v2 and receiver/runtime-input inspection accepted; cleanup complete; copied_not_activated | Cutover v1 recovered; retained journal identified minsane recommendation; diagnostic v2 accepted and cleaned; all three NTS-KE IPv6 connections refused before TLS; UniFi/NTS transport inspection accepted and cleaned; IPv4 TCP succeeds, IPv6 refuses; IPv6 permit v2 policy/TCP accepted; both rules enabled; diagnostics cleaned; cutover v2 early gate passed; NTS cookies acquired; error-priority response diagnostics blocked journal acceptance; recovered through both endpoints and cleaned; v3 journal health passed; NTS reach and PPS thresholds remained unsatisfied across five probes; recovered through both endpoints and cleaned; retained NTS/PPS diagnostics accepted through both endpoints and cleaned; startup statistics recovered; runtime diagnostic v2 recovered after early gate; partial packet evidence retained; dual-stack readback and cleanup complete; runtime diagnostic v3 recovered on changed Cloudflare address; rejecting sample and journal retained; dual-stack readback and cleanup complete; runtime diagnostic v4 completed 30 samples and recovered; 57/57 NTS replies authenticated; PPS timing and capture completeness failed; terminal dual-stack readback attempt 11 and cleanup complete; retained analysis complete; larger buffer passed isolated local fixture; cold-start promotion and receipt-selected recovery implemented and tested locally; runtime diagnostic v5 recovered after its first sample rejected control-key journal messages; dual-stack readback and cleanup complete; journal classifier corrected and tested offline; diagnostic v6 executed; 30 samples retained; recovery held on continuity drift; matching readback 13 retained; restoration and source cleanup remain unaccepted; recovery inspection captured and closed; PPS qualification deadline confirmed; historical boot/PID baseline and failed timeservice state differ; recovery timer still waiting at capture; exact frozen-checker replay isolates failed timeservice state; guarded reset tested; restoration continuation accepted through both endpoints and closed; old timer already absent/inactive; original v6 held state/evidence preserved; Offline PPS replay complete; continuous PPS-first monitor and terminal retention implemented/tested locally; start-and-monitor v1 stopped in preflight on expired nested hardware acceptance; conditional readback found no state file; partial stage retained; read-only hardware/runtime revalidation v1 executed and held on runtime binding; matching dual-stack readback and diagnostic closure complete; revalidation v2 prerequisites accepted through both endpoints; diagnostic closure complete; monitor v2 started and passed early/workstation checks; handoff rejected historical boot-ID comparison; recovered through both endpoints and transient cleanup complete; handoff continuity corrected/tested offline; read-only revalidation v3 accepted against recovered monitor v2 through both endpoints; diagnostic closure complete; monitor v3 startup and workstation structural checks passed; handoff rejected PPS platform/class cardinality; approved recovery matched through both endpoints and transient cleanup completed; PPS checker corrected and real transition tested offline; active historical executable dependencies migrated and tested offline; fresh revalidation review pending; successor recovery checker tested past historical expiry; PPS qualification and service activation remain pending |
| Reporting | Needrestart policy installed, microcode checking disabled | Mailrise/msmtp, needrestart.sh and cron installation/delivery |
| Optimizations | OPT-001 through OPT-007 reviewed offline; Phase 3A and proposal register added | Accepted live timing/antenna/network baseline before any optional experiment |
| Primary | Preserved during standby rebuild, including shared antenna power | Its own fresh inspection and later separately approved rebuild |

The current accepted source stage is
`/home/ama/.ntp-source-build-mdns-20261012-v1`; the earlier v5 stage is preserved.
User-managed passwordless sudo for ama remains in place; its removal is an
end-of-project operator action. No cleanup here changes it.

## Standalone artifact migration and retention completion — October 14, 2026

Completed the approved retention sequence: 8,439 duplicate files removed;
4,010 unique files and nine symlinks archived, fully restored and verified before
retiring their old copies. All 328 protected files were reverified. A private
member manifest, recovery-location ledger and verified Git bundle preserve access.
The earlier audit snapshots below describe their original observation times.

Fetched the three missing pinned payloads and verified all 117 assets plus both
source signatures in one explicit cache. No package installation occurred.

New standalone acquisition, restoration, hardware recovery, registry/baseline
and retained-inspection bundles now pin repository implementations. Historical
archives remain data/provenance inputs. Recovery separates the original state
directory from the current executable directory; runtime reconstruction pins its
effective specification and transitive helpers. Historical executable sentinels,
code drift and real constructor tests cover these boundaries.

No target contact or new execution review occurred. Fresh-install automation is
not yet complete: acquisition and monitor still have continuation-only receipt
requirements. Offline clean-directory validation must not be described as a live
fresh installation. Next: implement first-install entry paths using fresh accepted
observations, then prepare fresh revalidation for this host's continuation.

## Runtime artifact migration and private storage audit — October 14, 2026

Revalidation and monitor preparation now bind maintained repository implementations
for archive readers, acquisition/restoration validation and all reconstructed
runtime code. Historical bundles supply digest-checked facts only. The effective
runtime specification pins current helper/checker/supervisor bytes alongside
unchanged baseline data. Monitor rejects code drift from its accepted prerequisite.
The old cutover sealer rejects new trials; executed packages remain unchanged.

Offline validation uses the real retained monitor inputs with a guard rejecting
historical executable imports, plus manifest/identity rejection, code-substitution
and cross-operation code equality tests. Existing real hardware handoff/recovery
fixtures remain in the suite. No target contact or new live review was performed.

The private storage audit found 4,465,500,160 allocated bytes across 254,238 regular
files with no unreadable directories. It identified 21 duplicate NTP package
copies totaling 228,055,040 logical bytes, each recoverable byte-for-byte from the
retained monitor-v3 archive. Current root inputs and unique records remain outside
the deletion candidates. Nothing was deleted. The October 10 cleanup record
confirms an earlier 1,339,399,784-byte, 14,763-file cleanup across 25 paths; all
those paths remain absent. That cleanup deliberately retained executed failures.

Next: review the private deletion manifest separately; prepare fresh revalidation
before another activation review. Execution still needs separate approval.

## Standalone PPS checker and artifact contract — October 14, 2026

Corrected the repository checker to identify the intended GPIO PPS source instead
of requiring a single PPS class globally. The standalone checker accepts explicit
baseline JSON plus its digest and emits bounded inventory and rejection details.
New host, revalidation and monitor artifacts include the maintained checker;
monitor/revalidation bind matching checker bytes. Historical bundles are unchanged.
Handoff stores the PPS observation before recovery and preserves it afterward.

Regression coverage uses the real UART/PPS/RTC checker and immutable receipt
comparison through stopped preflight, active handoff and restoration. An extra
unrelated PPS class passes; missing/duplicate GPIO sources, altered character
identity and accepted mapping drift reject. External filesystem/process I/O is
simulated; the handoff hardware acceptance logic is no longer mocked.

The user extended the contract to all deployment artifacts: repository-owned
code, explicit pinned configuration/baselines and no executable dependency on
private evidence. Removed the workstation-specific evidence path from the monitor
review template. Operations lists remaining legacy executable imports from
historical archives; those have not yet been migrated. Next: replace those imports
with maintained validators and explicit baseline schemas before sealing another
activation. No target contact, service change or new execution bundle occurred.

## Monitor v3 handoff failed; recovery verified — October 14, 2026

Executed the approved [monitor v3 review](/home/aaron/code/.local-evidence/homelab-ntp/current/service-monitor-20261014-v3/review.md)
once, bound to the digest in its `sealing.json`. Receiver pairing, early ntpd
functionality and workstation IPv4/IPv6 responses with denied administrative
queries passed. Handoff failed with `one GPIO PPS platform and class required`;
continuous-monitor handoff and timing acceptance were not achieved.

Readback attempt 1 matched `observing` through both endpoints. The single approved
operator recovery restored baseline files, UART and clock service. Readback
attempt 2 matched `recovered` through both endpoints, producing the recovered
receipt; transient cleanup completed. The terminal startup record retains eight
bootstrap samples with no promotion. Preserve all executed artifacts and prior
evidence. No activation or handoff was replayed.

The checker requires exactly one bound GPIO PPS platform and one PPS class entry.
Retained results do not identify which count failed or establish its cause.
Next: inspect retained evidence and test the active-runtime PPS enumeration path
offline; prepare any necessary scoped inspection for separate execution approval
before another activation. Final timing/mDNS acceptance remains pending.

## Corrected PPS-first monitor v3 prepared — October 14, 2026

Prepared [monitor v3](/home/aaron/code/.local-evidence/homelab-ntp/current/service-monitor-20261014-v3/review.md)
against accepted runtime revalidation v3, matching readback attempt 1 and
diagnostic closure. The new operation also binds the original restoration and
recovered monitor v2 provenance. Its archive digest is in adjacent `sealing.json`.
Preparation made no target contact and changed no service or configuration.

The stage uses the corrected handoff observation binding and scoped journal-child
validation. Fresh preflight rechecks the recovered predecessor and current state.
The rendered fault unit and durable monitor record point to the new operation;
old stages remain evidence. A 600-second installation watchdog covers one start
and structural handoff. PPS-first monitoring has no timing-quality deadline;
selectable NMEA and three NTS upstreams are added only after PPS qualification.
Workstation dual-stack structural checks, up to 60 numbered observations,
conditional readback, explicit recovery and post-recovery cleanup are included.
Boot enablement, leap-fetch activation and final timing/mDNS acceptance remain
outside this operation.

Offline validation checks the actual sealed archive, prerequisite proof chain,
runtime alias, handoff observation, protected staging and rendered units, alongside
the existing handoff/revalidation regression tests. Preserve all prior evidence.

Next: obtain separate approval for monitor v3's exact digest, start once, verify
structural handoff and monitor at the approved cadence. Do not replay earlier
monitor operations or treat preparation as activation/timing acceptance.

## Runtime revalidation v3 accepted and closed — October 14, 2026

Executed the approved [read-only revalidation v3](/home/aaron/code/.local-evidence/homelab-ntp/current/runtime-revalidation-20261014-v3/review.md)
capture once on j2-svntp1, bound to the archive digest in adjacent `sealing.json`.
All seven checks passed: restoration, predecessor-stage continuity, idle workers,
runtime, hardware, observation continuity and source preservation. The exact
recovered monitor v2 state and original restoration/source chain remained valid.

Readback attempt 1 matched over both pinned endpoints and issued the prerequisite
acceptance receipt. Conditional diagnostic closure completed with the same report
digest and evidence preserved. The successor validator accepted the actual
archive, receipt, readbacks and closure offline. All 312 previously recorded
evidence files remain unchanged.

This operation changed no service, boot configuration, receiver setting or clock.
No monitor activation or timing acceptance is claimed. The baseline service state
remains restored; prerequisites are now available for a replacement activation.

Next: prepare and seal the corrected PPS-first start-and-monitor activation and
recovery review against accepted revalidation v3 for separate execution approval.
Preserve the new observation and all prior executed stages; do not replay start.

## Handoff continuity audit and replacement prerequisite review — October 14, 2026

Audited the reachable old-action paths through sealing, preflight, inherited
handoff/measurement, monitoring, recovery and cleanup. The confirmed handoff
fault compared the current boot with the pre-reboot runtime baseline. Handoff
now compares packages/boot/Python with the operation's protected fresh-preflight
observation, whose digest must match the accepted prerequisite report. Historical
native, file, account, loader and SHM provenance checks remain in force.

The audit also found inconsistent handling of the supervisor's temporary
`journalctl` child: measurement allowed it, but unchanged-state checking counted
it as an extra daemon. Both paths now validate the exact scoped arguments and
root credentials, and still reject unknown children, missing/competing daemons,
wrong credentials and genuine drift. This race was identified offline; it was
not the recorded v2 failure. Retained observations exclude Avahi/timesyncd, so
no stale-PID claim or normalization is warranted for their recovery restarts.

The next prerequisite capture binds recovered monitor v2, matching readback
attempt 2, its recovered receipt and transient cleanup. It verifies that retained
stage/state and absent workers, rechecks the original restoration/source chain,
and preserves exact observation comparisons. Local start guards also require
review/spec bytes to match the archive and an SSH-agent reference before
registering an execution. No target contact occurred during this work.

Initial local sealing rejected the 36,526,080-byte retained monitor archive at
the old 32 MiB input bound, before creating an output stage. Archive inputs and
protected staging now share an explicit 64 MiB bound; ordinary file/report and
capture bounds remain unchanged. Local regression checks cover the protection
path, and sealing validates the complete output archive.

Prepared [read-only revalidation v3](/home/aaron/code/.local-evidence/homelab-ntp/current/runtime-revalidation-20261014-v3/review.md);
the bundle digest is in adjacent `sealing.json`. Scope: one bounded capture,
conditional dual-stack readback and diagnostic closure; no service/boot change.
Offline tests exercise real inherited handoff/measurement and recovered-source
capture with simulated host I/O. Prior executed evidence remains unchanged.

Next: separately approve and accept this prerequisite capture. Only then seal
a replacement PPS-first activation review. Timing acceptance remains false.

## Monitor v2 handoff rejected; baseline restored — October 14, 2026

Executed approved bundle
`9b562bfe62d6f56303d28aedc8674f2df88bad7d42c2e591321de9ba8edabdf8`
once. Startup reached `observing`; the bounded receiver-pairing gate and localhost
ntpd check passed. Workstation IPv4/IPv6 structural NTP responses and denied
administrative queries passed. Handoff then rejected `package/boot/Python drift`.
The installation watchdog was not cancelled and monitoring was not handed off.

Readback attempt 1 matched `observing` through both endpoints. Invoked the approved
explicit recovery once; readback attempt 2 matched `recovered` through both
endpoints. Conditional transient cleanup completed. Files/UART and the baseline
clock service were restored; terminal monitor/statistics evidence and prior
stages were preserved. The retained monitor ended in bootstrap with a requested
stop. Time-service/timing acceptance remains false.

Offline inspection found the inherited `Transaction.unchanged` handoff check
compares the current boot ID with the historical runtime baseline. That baseline
boot differs from the accepted fresh revalidation boot, guaranteeing rejection.
Inventory and Python match between those two retained observations; no new
inventory/Python observation was retained at handoff. This is not evidence of a
new target reboot. Earlier wrapper tests covered preflight and recovery but did
not exercise this inherited handoff check against the actual historical baseline.

Next: correct and test handoff continuity against the accepted current-boot
observation, covering the inherited unchanged/measurement path before preparing
another sealed activation review. Do not replay this executed bundle or rewrite
its historical evidence.

## Fresh PPS-first monitor activation prepared — October 14, 2026

Prepared [monitor v2](/home/aaron/code/.local-evidence/homelab-ntp/current/service-monitor-20261014-v2/review.md)
against accepted revalidation v2, matching readback attempt 1 and diagnostic
closure, together with the accepted restoration archive and its receipts. The
new operation preserves the failed monitor v1 and all earlier evidence. No target
contact or service/configuration change occurred during preparation.

The proposed stage installs and starts once under a 600-second installation
watchdog. Structural handoff requires the early receiver/localhost gate,
dual-stack management, daemon safety and workstation IPv4/IPv6 NTP responses with
administrative queries denied. Only successful handoff cancels the watchdog.
PPS-first convergence then continues without a timing-quality shutdown deadline;
qualification promotes selectable NMEA and all three NTS sources. Monitoring uses
30-second intervals, or 300 seconds when ready, with up to 60 numbered captures.

Fault recovery and one explicit recovery restore the baseline. Conditional
readback and post-recovery cleanup preserve evidence. Historical receipt age does
not disable recovery of this operation. Boot enablement, warm restart, leap-fetch
activation and final synchronized client/mDNS acceptance remain pending.

Next: separately approve the sealed monitor v2 archive, start once, verify
structural handoff and monitor at the approved cadence. Neither this preparation
nor prerequisite acceptance establishes live time-service acceptance.

## Hardware/runtime revalidation accepted — October 14, 2026

Executed the approved v2 capture once, bound to bundle SHA-256
`b86035b637bbbf33e1efc73229cae501c2d8c8417c529a9c5aa20bab5fcec2a8`.
All seven prerequisite checks passed: restoration, failed-stage continuity, idle
workers, runtime, hardware, current-state continuity and preserved source state.
Readback attempt 1 returned matching `runtime_validated` reports through both
pinned endpoints. Diagnostic closure completed with all evidence preserved.

The accepted report revalidates UART/PPS/RTC metadata, packages/native/Python
runtime, accounts, loader, networking and protected files against the retained
restored state. Historical acceptance timestamps and executed stages remain
unchanged. No service activation, boot changes or timing trial occurred;
`time_service_accepted` remains false.

Next: prepare a fresh start-and-monitor activation/recovery review bound to this
accepted archive, readback attempt 1 and closure. Preserve PPS-first isolation,
continuous convergence monitoring and the independent installation watchdog.
Execution requires separate approval of that new sealed bundle. Final timing,
workstation IPv4/IPv6 and mDNS acceptance remain pending.

## Revalidation wrapper audit and replacement prepared — October 14, 2026

Audited the current revalidation action offline after the v1 wrapper rejection.
The earlier tests stopped short of the real preflight alias validation. V2 now
uses the acquisition validator's required stage prefix and checks that alias
during sealing; the frozen validator and executed evidence remain unchanged.

The audit also corrected observer-contract weakening, integer stand-ins for boolean checks
and non-integer epochs, missing local review/spec comparison, and SSH-agent absence
consuming a start registration. Timeout and missing-report handling now include
available partial evidence; an unreadable evidence item produces a held report
while preserving readable items. No validation guard was bypassed.

Regression coverage now crosses the real validator, constructor, preflight and
runtime-context interfaces with simulated host I/O. It exercises drift rejection,
one-shot transport loss, dual-stack readback and closure after expiry, and terminal
failure retention. Retained archive validation remains separate from synthetic
fixture results; neither establishes live acceptance.

Prepared the [replacement v2 review](/home/aaron/code/.local-evidence/homelab-ntp/current/runtime-revalidation-20261014-v2/review.md)
for one read-only capture, conditional readback and diagnostic closure. No target
contact or boot/service change occurred. V1 and all prior executed evidence remain
preserved. Next: separately approve the exact v2 archive, execute once and require
accepted fresh prerequisites before sealing monitor activation.

## Hardware/runtime revalidation held — October 14, 2026

Executed the approved runtime-revalidation v1 capture once. The sealed bundle
SHA-256 was `843bf7326f1776d70ca87401cfa6bd2c9fd2a0f78cba2c58d81a0c4dfa9e9ffa`.
The terminal report returned `validation_held` with
`accepted runtime/identity/boot/input binding required`. Readback attempt 1 matched
through both endpoints; diagnostic closure completed with evidence preserved.
No service activation or prerequisite acceptance resulted.

Offline source inspection identifies a stage-path incompatibility: the revalidation
transaction aliases its `ntp-revalidate-` stage into the acquisition validator,
which requires `ntp-acquire-` plus the operation ID. The capture retained command
and failed-stage evidence, but did not produce a fresh runtime observation.
This rejection does not establish hardware or runtime drift.

Next: correct and regression-test the reused runtime binding offline, including
the actual preflight path, then prepare a new sealed revalidation review for
separate execution approval. Preserve this closed held capture and all prior
stages. Fresh accepted revalidation remains required before monitor activation.

## Hardware/runtime revalidation prepared — October 14, 2026

Prepared the separate [read-only revalidation review](/home/aaron/code/.local-evidence/homelab-ntp/current/runtime-revalidation-20261014-v1/review.md)
for j2-svntp1. It binds the failed monitor archive, its preflight rejection and
missing-state readback, plus accepted restoration provenance. No target contact
occurred during this preparation; prior executed artifacts remain unchanged.

The new shared checker preserves the original hardware state, timestamps and
receipt. It rechecks same-boot identity, protected boot hashes and device mapping,
then runs the accepted runtime/network/native/account/loader checks in private
copies. The capture also verifies inactive/absent workers and preserved source
state. A fresh terminal report, matched dual-stack readbacks and diagnostic
closure are required before a schema-2 activation can be sealed. It does not
repeat boot changes, start services or establish timing acceptance.

The successor recovery path uses those same current-state checks after restoring
files/UART/bootstrap service, independent of historical receipt age. Offline tests
advance beyond that age, prove restoration succeeds for unchanged hardware and
still holds on boot-file drift, and verify immutable provenance, source-lock
release, report consistency, partial-stage rejection and closure boundaries.
Integration against the retained archive validates nested receipts and staged
constructor dependencies. Synthetic fixtures provide no live acceptance.

Next: obtain hash-bound approval for one read-only revalidation capture, conditional
readbacks and diagnostic closure. After acceptance, seal the new start-and-monitor
activation/recovery review. Preserve the failed stage; its cleanup and final
synchronized client/mDNS acceptance remain separate.

## Start-and-monitor preflight stopped — October 14, 2026

Executed the approved start once, bound to the unchanged
[sealed review](/home/aaron/code/.local-evidence/homelab-ntp/current/service-monitor-20261014-v1/review.md).
The target returned `accepted bound hardware/reboot gate required` during the
nested runtime preflight. Conditional readback returned a missing operation
`state.json`. No installation watchdog, service installation or daemon startup
was reached. Protected staging/runtime-check copies remain; no recovery or cleanup
was attempted without the required state and recovered receipt. Prior evidence
is preserved. Only the first endpoint was read: the controller stops on its error.

The frozen hardware checker requires acceptance within 24 hours. Retained
acceptance was October 13 at 11:41:04 a.m. CDT; its limit ended October 14 at
11:41:04 a.m. CDT, before this start. Preparation incorrectly capped the window
only at restoration expiry. The stale hardware receipt is sufficient to reject
this start; the error does not establish a physical hardware fault or exclude
other prerequisite drift. The sealer now binds that nested expiry too, and the
launcher checks remaining hardware freshness before a new start. Regression
checks and replay against retained inputs verify rejection offline.

Next: prepare fresh hardware/runtime prerequisite validation, without repeating
boot changes, for separate execution approval. Then seal a new activation against
accepted fresh evidence. Do not alter the executed bundle or historical timestamps,
and do not replay this operation. The inherited recovery path also checks hardware
freshness; test recovery after that expiry and define independent current-state
validation before another continuous-operation approval. Continuous monitoring and timing acceptance
remain pending.

## Start-and-monitor stage prepared — October 14, 2026

Prepared the independent [activation/recovery review](/home/aaron/code/.local-evidence/homelab-ntp/current/service-monitor-20261014-v1/review.md)
for j2-svntp1, using the accepted restoration archive, receipt, matched readbacks
and closure. Current inputs and a unique operation ID are sealed together.
No target contact or live activation occurred during preparation.

The new stage freshly validates restored prerequisites before installing.
A 600-second installation watchdog remains armed until structural dual-stack
SSH/workstation NTP checks, denied admin queries and live daemon/monitor checks
pass. Handoff then permits continuous PPS-first monitoring without a timing
qualification deadline. Keep one-shot promotion, 30/300-second observations,
fault/operator recovery, bounded evidence and conditional recovered cleanup.
Timeservice and leap-fetch boot activation remain disabled; final synchronized
client/mDNS acceptance is separate. Statistics resource limits are explicit
fault conditions. Prior executed stages and held v6 evidence remain intact.

Offline tests cover the actual restoration receipt API, proof/source drift,
source-lock release, watchdog/handoff races, failure recovery, numbered captures,
structural client responses and bounded durable evidence. Recovery/readback use
sealed inputs after repository drift; new startup requires current input hashes.
The independently approved start window is capped by restoration expiry, with
600 seconds reserved for installation; it does not renew prior execution windows.

Next: obtain hash-bound approval for this stage, start once, complete structural
handoff, then monitor at the agreed intervals. Timing acceptance, warm restart,
boot persistence and source-stage cleanup remain pending.

## Continuous PPS-first monitoring implemented offline — October 14, 2026

The operator superseded a longer qualification deadline with continuous
monitoring, and chose to retain PPS-first isolation after reviewing immediate
five-source startup. The new version-2 policy has no timing-quality shutdown
deadline. Keep the bounded receiver pairing gate and unchanged qualification
criteria; observe every 30 seconds until stable and every 300 seconds afterward.
Promote selectable NMEA and three NTS sources only once. Quality degradation
returns to the faster cadence without stopping the service or repeating promotion.

Implemented an operation-bound private evidence record outside `/run`, a
120-sample rolling history, incremental journal reads, retained rejecting
measurements and terminal stop reasons. Daemon/credential cleanup proceeds
even if final evidence writing or socket closure fails. Offline tests cover
late qualification, incremental initialization, steady/degraded monitoring,
one-shot promotion, protected evidence paths, bounded retention and failure cleanup.
No target contact, new sealed trial or runtime activation occurred.

Next: prepare the separate start-and-monitor activation/recovery contract,
binding the accepted restoration receipt/readbacks and closure. The existing
version-1 diagnostic always restores and is not suitable for this operation.
The new handoff must cancel installation recovery only after structural startup
and access checks, preserve fault/operator recovery, and keep running-but-
unqualified distinct from timing acceptance. Warm restart and source-stage
cleanup remain pending. No deadline extension was adopted.

## Retained PPS policy review — October 14, 2026

Completed the approved offline review in the private
[analysis record](/home/aaron/code/.local-evidence/homelab-ntp/current/pps-policy-review-20261014-v1/review.md).
The executed startup helper matches current source. Frozen-machine replay of
30 retained supervisor snapshots agrees with stored qualification counts,
update tuples and phases. Both terminal readback results match; six statistic
payloads passed hash checks, representing three duplicate current/dated pairs.

PPS selection passed the early gate; frequency initialization completed around
321 seconds. The first qualifying update was recorded at 836.743 seconds.
Peer statistics show 64-second updates and only two quality-passing updates
before shutdown. The last supervisor snapshot retains one qualifying update;
the later peer-statistics row lacks the full supervisor acceptance tuple.
Three passing updates could not fit this observed trajectory before the
900-second deadline. No promotion occurred. Sparse replay does not reconstruct
unretained supervisor ticks or prove future convergence.

Recommend testing a 1080-second bootstrap ceiling while preserving quality
limits, three fresh updates and the early gate. Implementation must prove the
remaining outer observation budget covers promotion, NTS setup and fresh PPS
updates, and retain bounded terminal supervisor diagnostics. No executable
policy changed, new trial was sealed or target contacted.

Next: implement/test that bounded candidate and diagnostic retention offline,
binding successor preparation to the accepted restoration receipt/readbacks
and closure. New live execution remains separately approved; persistent
warm-restart policy, timing acceptance and source-stage cleanup remain pending.

## Restoration continuation accepted — October 14, 2026

Executed the approved [restoration continuation](/home/aaron/code/.local-evidence/homelab-ntp/current/cutover-restoration-20261014-v1/review.md)
once. All ten restoration checks passed; readback attempt 1 matched over IPv4 and
IPv6, and conditional closure completed. The adjacent acceptance receipt records
restoration only. No time-service activation or timing acceptance is claimed.

The sole mutation was the guarded `reset-failed timeservice.service`; inactive/dead
was confirmed. The old retry timer was already absent/inactive at preflight, so no
timer stop was issued. Its recovery service was failed and remained preserved.
This establishes the observed service state, not the cause of that later failure.
Files, UART, observation, network, native installation, accounts, loader cache,
hardware metadata and retained statistics passed their checks.

The original v6 stage remains historically `recovery_held` and was not rewritten.
Its backups, source records and runtime evidence remain intact. The separate
continuation receipt establishes restored host state; source-stage cleanup remains
unapproved. Next: review the retained PPS qualification samples and startup policy
offline before proposing another trial. Successor preparation must consume this
restoration receipt and matching readback/closure without rewriting v6 history.
Any new live stage requires its own sealed review and execution approval.

## Restoration continuation prepared — October 14, 2026

Replayed the exact frozen runtime checker against the accepted recovery inspection.
It already excludes reboot-related boot-ID/PID differences. Correcting only the
unloaded timeservice failure state makes its observation comparison pass; package,
Python, daemon and unrelated service drift remain rejected. The inspection's raw
differences were findings, not proof that every listed field caused recovery failure.
No historical baseline or executed bundle was edited.

Added a guarded reset after ordinary cutover file restoration: require the exact
unloaded, PID-zero failed timeservice state, reset only that unit, and confirm
inactive/dead before the unchanged runtime checker runs. An already inactive unit
requires no reset. Loaded, running, altered, incomplete or duplicate metadata holds.

Prepared [restoration continuation v1](/home/aaron/code/.local-evidence/homelab-ntp/current/cutover-restoration-20261014-v1/review.md)
from the accepted inspection, matching readbacks and cleanup, and the immutable v6
archive. Its adjacent sealing receipt supplies the exact approval digest and expiry.
It verifies that files, created directories and UART settings are already restored,
takes the source lock, checks the retry timer/worker, stops only that obsolete timer,
and conditionally clears timeservice failure metadata. It revalidates network,
native/package/Python state, accounts, loader-cache and hardware metadata using a
private copy of the original inputs. Historical acceptance age does not authorize
new installation; the continuation has its own bounded restoration-only window.
Original source state, backups, runtime evidence and accepted stages remain intact.

Offline coverage includes frozen-checker behavior, exact reset/recheck, timer races,
file/UART/new-observation drift, failure after mutation, matching terminal readback
and closure. Preparation made no target contact. Next: separate execution approval
for one continuation, conditional dual-stack readback and evidence-preserving
closure. A held result leaves any timer stop/reset in place and requires review;
never rearm the known-failing recovery or replay the trial. Persistent time service,
PPS qualification and source-stage cleanup remain unaccepted.

## Read-only recovery inspection completed — October 13, 2026

Executed the approved [recovery inspection](/home/aaron/code/.local-evidence/homelab-ntp/current/cutover-recovery-inspection-20261013-v1/review.md)
once. Both endpoints returned the same captured report on readback attempt 2;
attempt 1 was blocked by the local sandbox before connection. Diagnostic closure
completed and preserved all source/inspection evidence. This accepts retrieval
only; v6 remains `recovery_held`, without restoration or source-cleanup acceptance.

The retained journal confirms `PPS qualification deadline`: the startup supervisor
terminated ntpd and timeservice exited with status 1 before promotion. Recovery's
raw continuity comparison differs in the historical boot ID, SSH/NetworkManager
PIDs and timeservice's failed rather than inactive state. The later frozen-checker
replay establishes that only the failed service state caused rejection. Package inventory, Python
metadata and active-daemon observations match. These differences do not establish
a reboot during v6; the compared baseline predates the current boot.

At capture, bootstrap timesyncd and Avahi were active, timeservice was failed with
its unit absent, and `/etc/ntp.conf` was absent. The independent recovery timer was
active/waiting with an empty last-trigger field; its recovery service was inactive.
Do not infer a later timer result from elapsed workstation wall time.

Next: correct/test recovery continuity against the accepted current-boot evidence,
then prepare a bounded restoration continuation with explicit failed-unit handling
and fresh timer-state checks for separate execution approval. Preserve historical
baselines and executed bundles. Resolve restoration before any new timing trial;
PPS qualification policy remains a separate unresolved question.

## Read-only cutover recovery inspection prepared — October 13, 2026

Prepared the [recovery inspection review](/home/aaron/code/.local-evidence/homelab-ntp/current/cutover-recovery-inspection-20261013-v1/review.md)
against v6's matching held readback attempt 13 and exact executed bundle. Its
adjacent sealing receipt supplies the digest and inspection-only expiry. No
target/controller contact occurred; the later recovery-timer outcome remains
unknown. V6 evidence and the root-owned source stage remain preserved.

The inspection collects bounded operation/supervisor/recovery journals, original
command and recovery-command records, runtime statistics, service/timer state and
the original baseline/current continuity comparison. It uses the pinned observer
and verifies the original runtime-check inputs. Only expected automatic recovery
state transitions are allowed under the existing read-only source lock; changed
non-recovery fields hold capture. Continuity differences are retained as findings.

Offline tests cover held/recovered transitions, wrong identities, changed source
records, truncated/missing/wrong-boot journals, baseline drift, bounded retrieval,
read-only commands and acceptance without restoration claims. One capture,
conditional dual-stack readback and diagnostic closure are proposed. This does
not authorize recovery, timer cancellation, cleanup of v6 or another trial.
Next: separate execution approval of the inspection's sealed digest.

## PPS-led runtime diagnostic v6 recovery held — October 13, 2026

Executed the approved v6 bundle once. The short serial/PPS gate passed, PPS was
selected, and the corrected journal classifier remained healthy. The required
freq_mode/freq_set/clock_sync sequence was recorded. Thirty diagnostic samples
were retained. The last sample at about 887 seconds reported PPS offset
-0.145 ms and jitter 0.353 ms, but only one qualifying fresh update was counted.
No promotion commands were submitted; NMEA/NTS promotion was not reached.

The subsequent measurement command failed and automatic recovery entered
`recovery_held` with `package/service/Python/process drift`. The retained state
reports the startup-promotion file unavailable. It does not establish the exact
process-exit cause or identify the continuity mismatch. Restoration is not
accepted. The packet observer stopped with zero packets/drops; NTS capture was
not exercised.

Readback 12 straddled a sample update and produced no matching receipt. Readback
13 returned matching held state through IPv4 and IPv6. No explicit recovery retry
or cleanup was attempted after drift detection. The independent timer has not
been confirmed canceled; do not assume the held state is the final timer outcome.
The immutable [v6 review](/home/aaron/code/.local-evidence/homelab-ntp/current/nts-pps-runtime-20261013-v6/review.md)
and all readbacks remain private and preserved.

Next: prepare a scoped read-only inspection of retained operation/supervisor
journals, recovery command records, timer state and the baseline/current
continuity difference for separate approval. Resolve restoration before another
trial. No timing, diagnostic or persistent-service acceptance is claimed.

## PPS-led runtime diagnostic v6 prepared — October 13, 2026

Prepared the [v6 diagnostic review](/home/aaron/code/.local-evidence/homelab-ntp/current/nts-pps-runtime-20261013-v6/review.md)
offline with the corrected journal classifier. The adjacent sealing receipt
identifies its exact bundle SHA-256. It binds current inputs, accepted receiver
and network evidence, original retained diagnostics, and v5's matching recovered
readback attempt 1 and cleanup. Prior executed bundles and evidence are preserved.

Scope remains one cold-start PPS-led diagnostic, authenticated promotion of
selectable NMEA and three NTS upstreams, bounded packet observation, mandatory
restoration, conditional dual-stack readback/recovery and cleanup. No persistent
service acceptance is included. Live identity and baseline preflight remain
mandatory. No target/controller contact occurred during preparation.

The inherited window is unchanged: start before October 14, 2026,
11:11:04 a.m. CDT; inputs expire at 11:41:04 a.m. CDT. Next: separate execution
approval bound to v6's exact sealed digest. Do not replay v5.

## PPS startup journal classifier corrected offline — October 13, 2026

The pinned NTPsec 1.2.5 source logs successful key-file reading and the number of
keys added at LOG_ERR. The classifier now permits exactly one ordered pair for
the fixed per-start control-key path and one added key, only when PPS startup is
enabled. Both records must match the current daemon identity and boot and fall
within 120 seconds of apply. Key loading stays bound to apply time after NTS
startup telemetry moves to the promotion window.

Replay of v5's complete retained priority-0-to-3 journal fails the original
classifier and passes the correction before and after promotion. With PPS
startup disabled, those same messages remain rejected. Offline regressions cover
missing, duplicate, reordered, late, altered and wrong-origin messages, actual
key-loading errors and integration through the measurement path. These checks
classify telemetry; they do not establish timing or NTS authentication.

No target/controller contact occurred. Executed v5 evidence remains unchanged.
Next: prepare a fresh diagnostic review against the recovered receipt and current
inputs, for separate execution approval. No replacement bundle is sealed yet.

## PPS-led runtime diagnostic v5 recovered — October 13, 2026

Executed the approved v5 bundle once. The short serial/PPS gate passed and the
first startup sample selected PPS. The first diagnostic sample then failed the
journal-health gate on two priority-3 messages: control-key file reading and
one key added. No promotion commands were submitted; selectable NMEA and the
three NTS associations were not added. The trial did not establish settled PPS
timing or NTS packet behavior.

Automatic recovery restored the baseline. Readback attempt 1 returned matching
recovered state over IPv4 and IPv6; conditional cleanup completed. The terminal
receipt records both diagnostic and time-service acceptance as false. Retained
journal/statistics and the rejecting sample remain beside the immutable
[v5 review](/home/aaron/code/.local-evidence/homelab-ntp/current/nts-pps-runtime-20261013-v5/review.md).
The 2 MiB observer reported TPACKET_V3, zero packets and zero drops during this
brief bootstrap; that does not qualify capture under NTS traffic.

Next: qualify the startup journal classifier against the pinned daemon's
control-key messages and retained evidence, including rejection tests, before
preparing another separately approved trial. Preserve v5 and do not replay it.

## PPS-led runtime diagnostic v5 prepared — October 13, 2026

Prepared the [fresh v5 review](/home/aaron/code/.local-evidence/homelab-ntp/current/nts-pps-runtime-20261013-v5/review.md)
using the checked-in diagnostic recipe and tested startup/promotion helpers.
The adjacent sealing receipt supplies the bundle digest. Inputs bind accepted
receiver/runtime and network evidence, original retained diagnostics, and v4's
matching terminal readback attempt 11 and cleanup. Prior executed artifacts are
preserved. No target/controller contact occurred during preparation.

The proposed scope is one cold-start PPS-led activation followed by authenticated
promotion of selectable NMEA and the three NTS upstreams, without a daemon restart.
It includes early functionality checks, the 2 MiB observer, bounded observation,
mandatory restoration, conditional dual-stack readback/recovery and cleanup.
No persistent service acceptance or warm-restart policy is included.

Offline sealing rejected the stale fourth capture address: original and latest
terminal measurements both contain the same three upstream addresses. The v5
recipe now uses that exact three-address set. No runtime scope expansion or DNS
query was used to resolve the mismatch; an unexpected address still recovers.

The inherited evidence window is unchanged: start before October 14, 2026,
11:11:04 a.m. CDT and complete within the 11:41:04 a.m. CDT expiry. Fresh target
identity/baseline preflight is still mandatory at execution. Next: obtain
separate approval of v5's exact sealed digest before its one start. Do not replay
an earlier diagnostic or extend the execution window from retained evidence.

## PPS-led cold-start promotion implemented — October 13, 2026

Implemented the approved cold-start policy in the supervisor and diagnostic
recipe. Startup defers NMEA/NTS, requires PPS initialization and distinct fresh
updates, then adds the final selectable sources through authenticated localhost
Mode 6 without restarting ntpd. Commands are submitted once; uncertain or partial
promotion stops both daemons and proceeds through diagnostic recovery. Per-start
keys/configuration are protected and removed after the children stop. The final
selectable-NMEA `ntp.conf` remains unchanged.

A private local build of pinned NTPsec 1.2.5 exposed asymmetric Mode 6 alignment:
4-byte requests, 8-byte authenticated replies. The helper now handles that
asymmetry and rejects invalid MACs without the client's automatic retry. The
isolated rootless network/IPC fixture passed authenticated addition of SHM0 and
three NTS associations, unchanged PPS association/PID, wrong-key and corrupted
response-MAC rejection, and cleanup. No external network or host clock adjustment was available to the
fixture. It does not establish NTS handshakes or timing acceptance on the target.

Recovery preparation now selects the unique receipt-bound terminal readback pair.
The retained v4 evidence passed selection of attempt 11; all previous evidence
remains unchanged. Diagnostic observation is bounded at 1500 seconds/50 samples,
with a 1620-second packet window and the existing independent 1800-second recovery
timer. Timing thresholds remain unchanged. Offline tests cover repeated/stale
samples, initialization sequence, identity, deadlines, partial promotion and
recovery provenance. Private build/test records are under local PPS-startup
qualification storage, outside Git.

The enabled profile is a cold-start diagnostic and rejects an existing drift
file. Persistent warm-restart policy remains a service-cutover prerequisite.
No target/controller contact occurred and no new live review was sealed.
Next: prepare a fresh diagnostic review with current inputs, retained receipt
bindings and the tested startup path for separate execution approval.

## Local buffer qualification and PPS-led policy — October 13, 2026

Implemented a 2 MiB observer-buffer candidate with libpcap/backend metadata and
packet timestamps. Tested the actual collector in a fresh rootless network
namespace using synthetic Ethernet/IP/UDP/NTP frames and Debian libpcap 1.10.5-2
extracted privately, without host package installation. The attempted local source
build lacked flex/lex; its log is preserved. No target/controller contact occurred.

The real x86-64 Linux fixture confirmed TPACKET_V3. Three spaced and three burst
comparisons were run for each address family. The 256 KiB control dropped
30/32/34 packets (IPv4 spaced), 142/90/106 (IPv4 burst), 31/20/32 (IPv6 spaced)
and 142/94/90 (IPv6 burst). The 2 MiB candidate captured every expected packet
in all twelve cases: 2880 packets, zero drops, exact request/response identifiers.
Evidence, package hash, worker logs, source hash and backend metadata remain in
private local-capture storage. This reproduces observer loss locally and validates
the candidate there, not on the Raspberry Pi. Drop rejection remains mandatory.

Prepared the explicit PPS-led startup policy in OPERATIONS. It defers NMEA/NTS
association creation until PPS frequency/timing qualification, then restores the
requested final selectable NMEA and three NTS sources without restarting ntpd.
Distinct PPS updates must advance the acceptance sequence; repeated queries of
one sample cannot. No serial calibration or startup frequency seed is proposed.

The policy is not integrated into the supervisor. Authenticated localhost Mode 6
promotion, exact pinned-version event parsing, partial-promotion recovery and
terminal-readback provenance handling require implementation/testing before a
live bundle can be sealed. The current final ntp.conf is unchanged. No new target
execution review or approval hash was created.

Next: implement/test the prepared startup state machine and protected promotion
path against pinned NTPsec 1.2.5, then prepare a separately reviewed bounded
trial with the tested observer candidate and explicit recovery reserve.

## Retained startup and capture analysis — October 13, 2026

Completed [offline analysis](/home/aaron/code/.local-evidence/homelab-ntp/analysis/runtime-v4-20261013/report.md)
with a private recomputation script and input/source hashes. No target/controller
contact, candidate change or new trial. Pinned public libpcap source was read to
verify the capture-buffer hypothesis.

SHM2 recorded 872 good samples from 872 ticks, with no not-ready, bad or clashing
samples. This establishes ingestion, not pulse-edge jitter. NMEA supplied the
first loop correction (-86.045088 ms), before the network/PPS startup transition.
The direct frequency calculation is reproducible from loopstats: 57.320730 ms
over 359 seconds gives 159.667772 ppm. That startup estimate later declined to
149.503937 ppm; it is not a qualified oscillator calibration. The trial creates
a fresh drift directory, so repeating it repeats cold frequency initialization.
Nearby network/PPS offsets show a common clock displacement; the final PPS peer
jitter is not a standalone measurement of hardware pulse jitter.

The observer retained all 57 requests but 37 responses: Cloudflare 19/19,
System76 Ohio 4/19 and Oregon 14/19. The 20 missing responses agree with its
capture-drop counter while ntpd authenticated all 57. This local capture loss
does not establish network-path loss. The configured 256 KiB buffer can produce
one ring block under libpcap 1.10.5's Linux TPACKET_V3 backend. Buffer handoff is
a plausible cause, but actual backend/ring geometry were not retained.

Next proposed preparation: test a 2 MiB observer buffer with a real local
Linux/libpcap fixture and retain backend/drop metadata; review PPS-led startup
while preserving eventual selectable NMEA. No permanent selection change,
guessed serial calibration, drift seed or relaxed timing limit is approved.
A future observation should distinguish frequency-calibration milestones from
settled timing, retain hard recovery limits, and bind terminal readback attempt
11 without relabeling prior evidence. No new execution bundle was sealed.

## Runtime diagnostic v4 completed and recovered — October 13, 2026

Executed approved archive `80d348c79af00f1ee8c0c2260eed57f50a0553adbfa2fe0e47bb79c56cc37def`
once. The early serial SHM0/PPS SHM2 gate passed. The worker completed 30 samples
within the 900-second observation window, then restored the baseline; recovery
finished about 908 seconds after apply. Matching terminal dual-stack readback
was attempt **11**, not attempt 1. Cleanup completed; all earlier readbacks,
source archives, statistics and backups remain preserved.

The final sample recorded 57 NTS sends and 57 good NTS receives, zero bad NTS
receives and zero system bad-authentication events. All three upstreams passed
the authentication/reach checks. This trial supports the source-policy correction;
it does not establish future availability or time-service acceptance.

PPS remained selected with full reach, but no post-600-second sample passed all
timing checks. The final PPS offset was -30.728319 ms and peer jitter 27.804557 ms,
against the unchanged 5 ms/1 ms limits. Frequency estimation changed from zero
to about 159.668 ppm during startup and ended at 149.504 ppm. Loopstats, peerstats
and clockstats are preserved for offline analysis; no calibration, poll change,
threshold relaxation or automatic retry was performed.

The observer retained 94 packets, reporting 114 received and 20 capture drops,
with zero interface drops and unsupported records. Packet evidence is incomplete;
these are observer counters, not proof of network-path loss. All 328 bounded
journal records were retained. No diagnostic execution/evidence error occurred,
but packet incompleteness withheld diagnostic acceptance. Time service remains
unaccepted independently because timing limits failed and this profile always
recovers.

Next: analyze retained PPS/startup discipline statistics and packet-observer loss
offline before proposing another bounded trial. Any successor must bind terminal
readback attempt 11 and its matching receipt/cleanup, preserving the earlier
nonterminal readbacks rather than renaming or overwriting them.

## Corrected source policy and diagnostic v4 prepared — October 13, 2026

Prepared the [v4 runtime review](/home/aaron/code/.local-evidence/homelab-ntp/current/nts-pps-runtime-20261013-v4/review.md)
offline against v3's matching recovered receipts and completed cleanup. Its
adjacent sealing receipt binds current inputs and the unchanged execution window.
No target or controller contact occurred during preparation.

The candidate removes only `notrust` from `restrict source`; each of the three
upstreams retains `nts iburst`. Default-deny IPv4/IPv6, Default LAN serving and
localhost administration remain unchanged. Pinned source inspection showed the
legacy MAC gate precedes NTS response processing. Configuration regressions check
the full restriction set and mandatory NTS association options. This correction
is a candidate, not proof that authenticated packets will now be accepted.

The reviewed packet scope contains four addresses: both Cloudflare IPv6 addresses
observed across the original retained evidence and v3, plus the two System76
addresses. Sealing requires that exact evidence-derived union, with at most four
unique public addresses. No runtime DNS lookup broadens capture; a new address
still triggers recovery. Packet limits and all timing/authentication gates are
unchanged. V3's one capture drop remains unexplained; collector behavior is
unchanged and regression tests require either capture-drop counter to prevent
complete evidence. No loss is discarded or reclassified as success.

Next: separately approve v4's one bounded diagnostic activation, mandatory
recovery, conditional dual-stack readback and cleanup. No service acceptance.

## Runtime diagnostic v3 recovered — October 13, 2026

Executed approved archive `9807edc4efbbadffb60d17cfe416cd1ab129529baa603a1df4e5da5b85dc56a3`
once. The early gate passed, including serial SHM0/PPS SHM2 pairing, packet
observer and pre-activation journal cursor. At about 42 seconds, the saved
sample showed Cloudflare at `2606:4700:f1::123`, outside the sealed packet scope.
Automatic recovery completed about 51 seconds after apply. Both endpoints
returned matching recovered state; cleanup completed. No second activation ran.

Pending NTS associations were retained correctly. The bounded journal contains
261 records, including successful NTS-KE for all three providers. The second
sample recorded three NTS sends, zero good/bad NTS receives and three system
bad-authentication events. All upstream associations still had zero reach.
The partial packet report contains an Ohio request/response pair and an Oregon
request, with one reported capture drop. It cannot establish complete traffic,
NTS authentication, or RTT. PPS startup offset was about -33 ms; this short
trial cannot establish settling. Diagnostic and time-service acceptance remain
false. Prior evidence, statistics, terminal journal and backups are preserved.

Offline inspection of the pinned NTPsec 1.2.5 `ntpd/ntp_proto.c`, verified against
its retained source archive, identified a candidate-policy defect: `restrict
source notrust` requires legacy MAC authentication before the NTS response
handler. That rejection path increments the system bad-auth counter without
entering NTS validation, consistent with the saved counters. The effective live
restriction mask was not captured; do not describe NTS cryptographic verification
as failed. No configuration or authentication requirement was changed live.

Next: prepare a corrected source-restriction policy that retains `nts` on every
upstream and the Default LAN/localhost access limits, with offline regression
checks. Review bounded capture-address handling and reported capture loss before
sealing another diagnostic for separate execution approval.

## Runtime diagnostic v2 recovered; v3 prepared — October 13, 2026

Executed the approved v2 archive once. The early receiver/control/counter gate
passed: serial mapped to SHM0 and GPIO PPS to SHM2. Recovery followed about
20 seconds after apply, with matching dual-stack readback and cleanup. Prior
archives and evidence remain private and preserved.

The packet observer retained a matching Cloudflare IPv6 UDP request/response
pair with no reported capture drops. This does not establish ntpd authentication
or acceptance; userspace packet read times cannot establish RTT. The rejecting
sample was not saved, so the exact association that triggered the scope error
is unknown. Early queries contained pending NTS associations without addresses;
the checker incorrectly rejected that state. Terminal journal retrieval exceeded
its output bound before operation filtering. No settling conclusion is possible.

Corrected offline: pending NTS setup has a 60-second grace checked at each
30-second sample; resolved addresses outside the sealed scope still fail closed.
Rejecting measurements are saved before ancillary collection and recovery.
A pre-activation boot-bound cursor scopes journal queries to the new operation.
The new review binds the latest recovered diagnostic and unchanged retained
evidence anchor, without treating the failed diagnostic as accepted.

Next: separately approve the [v3 runtime diagnostic review](/home/aaron/code/.local-evidence/homelab-ntp/current/nts-pps-runtime-20261013-v3/review.md).
Its sealing receipt binds the new hash and window. No second activation occurred.

## Bounded runtime diagnostic prepared — October 13, 2026

Prepared the [runtime diagnostic review](/home/aaron/code/.local-evidence/homelab-ntp/current/nts-pps-runtime-20261013-v2/review.md)
from accepted retained diagnostics and cutover v3 recovery. Its adjacent sealing
receipt binds the archive digest and execution window. Preparation and testing
were offline; no daemon restart, target or controller contact occurred.

The diagnostic reuses the cutover backup/recovery transaction, with automatic
supervisor restart disabled and service acceptance prohibited. A ready eth0
observer precedes activation; the short GPSD/SHM and localhost counter gate
precedes long observation. Capture is limited to UDP 123 and the three observed
upstream addresses, at most 512 packets, with only selected headers saved.
NTS counters, peer interface bindings, addresses/routes and timing measurements
are sampled for at most 900 seconds after apply. Timing success cannot count
until 600 seconds; unchanged service thresholds still apply. These bounds do
not promise convergence. Every outcome restores the baseline, with independent
worker limits and the existing 1800-second recovery timer as fallback.

The supplied `.XFAC.` hypothesis is included in scope. Pinned NTPsec 1.2.5
`ntpd/ntp_peer.c` clears the peer with that refid when its local interface binding
changes; it does not uniquely identify a boot-order failure. The retained trial
had a global IPv6 listener before its successful NTS-KE exchanges. Correlate
`srcadr`, `dstadr`, refid, route/address changes, packet observations and counters
before proposing a networking or restart fix. No standalone restart is approved.

Next: separately approve the sealed diagnostic activation, mandatory recovery,
conditional dual-stack readback and cleanup. Diagnostic acceptance is collection
acceptance only; time-service cutover, client/mDNS and settled timing acceptance
remain pending. Preserve all previous executed bundles and evidence.

## Retained NTS/PPS diagnostics accepted — October 13, 2026

Executed the approved retained-data capture once. Both management endpoints
returned matching terminal evidence; diagnostic acceptance and cleanup completed.
The [private outcome](/home/aaron/code/.local-evidence/homelab-ntp/current/nts-pps-retained-20261013-v1/outcome.json)
binds the approved bundle and result hashes. All source bytes and captured
artifacts remain preserved. No daemon, configuration, receiver or firewall
change occurred.

Retrieved 287 retrospective journal records, five saved journal probes and six
statistics files: matching current/dated copies of loopstats, peerstats and
clockstats. The two distinct loopstats updates are 308 seconds apart: offset
changed from -83.814356 ms with zero frequency to +45.720453 ms with
148.443029 ppm. This supports startup frequency estimation as a hypothesis;
it does not establish settled PPS performance. Peer statistics include both
SHM0 and SHM2. No refclock mapping, calibration or timing threshold changed.

The journal confirms successful NTS-KE for all three upstreams. Saved probes
still show zero upstream reach, and no retained NTS packet rejection counters
or wire capture locate the cause. Current observations show timeservice absent
and inactive, bootstrap timesyncd active, and `/etc/ntp.conf` absent, consistent
with the earlier recovery. Diagnostic acceptance is not time-service acceptance.

Next: prepare a separately reviewed bounded runtime diagnostic for NTS packet
counters and request/response observation, with an early functionality gate and
explicit startup-settling versus final timing checks. Define recovery and preserve
the current evidence before authorizing any service start or active probe.

## Retained NTS/PPS diagnostic review prepared — October 13, 2026

Prepared the [read-only diagnostic review](/home/aaron/code/.local-evidence/homelab-ntp/current/nts-pps-retained-20261013-v1/review.md)
against v3's recovered/cleaned state. The adjacent sealing receipt identifies the
archive digest. Preparation used local retained evidence only; no target or
controller contact, service start or network probe occurred.

System frequency was zero through 246 seconds and 148.443 ppm at the fifth
probe, 334 seconds after apply. The pinned source's 300-second startup frequency
estimation path is consistent with this sequence, without proving that path
was active. The samples do not establish steady-state PPS error. Saved queries
omit NTS packet rejection counters, so the loss/rejection location remains unknown.
The other host's supplied NTP1 snippet does not alter j2's observed NTP0/NTP2
pairing or explicit PPS preference; no refclock configuration changed.

Updated and tested the existing collector for multiple compact-boot journal
probes and bounded recovery-preserved statistics. Tests cover byte preservation,
missing files, unsafe links/names, size/count bounds, command scope, truncation
and source drift. No acceptance, calibration or live-service policy changed.

Next: approve one retained-data capture, conditional dual-stack readback and
cleanup. Evaluate its journal/statistics before defining any active packet or
counter capture. Retain v3 and all previous executed evidence.

## Service cutover v3 recovered — October 13, 2026

Executed the approved v3 bundle once. The short GPSD/SHM gate passed with five
PPS and six serial matches, and localhost ntpd responded. Journal health passed
all five probes, with one minsane advisory and three pairs of bounded NTS
response diagnostics; there were no unexpected error-priority records.

Across roughly 334 seconds from apply, PPS became reachable and selected.
The fifth probe measured +45.720453 ms offset and 38.583872 ms jitter, beyond
the configured limits. All three NTS peers retained cookies but reach stayed
zero. Authenticated NTP packets and three consecutive passing observations were
not accepted. No workstation acceptance was attempted. These samples do not
identify a packet-path fault or explain the startup timing transient.

Used the approved conditional recovery before exhausting the 40-probe budget.
Both management endpoints returned matching recovered state; terminal cleanup
completed. Original files, `/etc/ntp.conf` absence, UART and bootstrap timesyncd
were restored. The private [outcome](/home/aaron/code/.local-evidence/homelab-ntp/current/service-cutover-20261013-v3/outcome.json)
binds all five probes, recovery, readbacks and cleanup. Preserve all stages,
backups and generated timing statistics. The time service remains unaccepted.

Next prepare a scoped diagnostic review covering retained logs/statistics,
NTS packet counters and UDP request/response behavior, and startup clock
selection/discipline. New probes or service activity require explicit scope;
do not replay v3 or change calibration/thresholds from these observations.

## Service cutover v3 prepared — October 13, 2026

Prepared the [v3 review](/home/aaron/code/.local-evidence/homelab-ntp/current/service-cutover-20261013-v3/review.md)
with its digest in adjacent `sealing.json`, without target/controller contact.
It binds v2's matching recovered-state receipts and cleanup, accepted network
and receiver/runtime evidence, current inputs and a unique operation ID.
The original execution window remains unchanged; executed evidence is preserved.

The classifier now recognizes the pinned NTPsec read-byte and cookie-count
startup formats within source-defined numeric bounds. At most three of each
are allowed, with matching totals, expected process provenance and the existing
120-second window. The single minsane allowance remains. Unexpected errors,
invalid values, incomplete exchanges, repeated records and excess counts remain
blocked. Cookie telemetry does not replace per-upstream packet acceptance.

Offline tests cover observed success records, source-bound values, malformed
messages, TLS/NTS failures, provenance, timing and recovered-receipt drift.
All seven retained v2 error-priority records pass the revised classification.
The prepared scope covered one cutover, early gate, complete NTS/PPS and
workstation acceptance, backups, timed recovery and conditional cleanup.

## Service cutover v2 recovered — October 13, 2026

Executed the approved v2 bundle once. The short GPSD/SHM pairing gate passed
with five PPS and six serial matches; localhost ntpd responded. The first
probe correctly allowed the expected minsane advisory, but six other
error-priority records blocked journal acceptance: three NTS read-byte counts
and three cookie-count messages. All three upstreams reported seven available
cookies. PPS reach/selection and authenticated NTP packet checks had not passed.
No workstation acceptance or second probe was attempted.

The cumulative journal gate could not clear with waiting. Immediate approved
recovery restored the original files, `/etc/ntp.conf` absence, UART state and
bootstrap timesyncd. Both management endpoints returned matching recovered
state; terminal cleanup completed and all evidence/backups remain retained.
The private [outcome](/home/aaron/code/.local-evidence/homelab-ntp/current/service-cutover-20261013-v2/outcome.json)
binds the probe, recovery, readbacks and cleanup. The time service is not accepted.

Offline source review verified the pinned NTPsec archive digest and found
`ntpd/nts_client.c` lines 714 and 870 emit these response diagnostics at
`LOG_ERR`; the cookie-count message precedes a successful return. This is
progress beyond the previous IPv6 refusals, without proving authenticated UDP
exchange. Next correct/test the journal classifier against the pinned source,
then prepare a replacement cutover for separate execution approval. Do not
replay v2 or broaden the existing exception during execution.

## Corrected service cutover prepared — October 13, 2026

Prepared the [v2 review](/home/aaron/code/.local-evidence/homelab-ntp/current/service-cutover-20261013-v2/review.md)
for separate execution approval. Its adjacent sealing receipt identifies the
archive SHA-256. No target or UniFi contact occurred during preparation.
The accepted firewall v2 receipts and matching after-capture evidence are
bound with the retained receiver/runtime inputs, without extending freshness.
All earlier executed archives and evidence remain unchanged.

The candidate explicitly selects `minsane 1` for local-reference availability,
accepting the absence of a multi-source quorum. Tests cover the exact ntpd
startup advisory, duplicate/unexpected/late errors, provenance and boot mismatch,
malformed JSON, network evidence binding, early failure and recovery. Journal
selection now uses a compact boot ID and monotonic apply time; the informational
stderr duplicate is outside the error-priority gate.

The prepared scope was one v2 cutover with the early functionality gate,
three authenticated NTS associations, PPS selection, workstation dual-stack
NTP/mDNS acceptance, backups, 30-minute timed recovery and conditional cleanup.
TCP reachability alone does not establish UDP or authenticated NTS operation.

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

### October 13: fresh baseline accepted; corrected hardware review

Executed the approved `host-baseline-20261013-v1` capture once. Acceptance
bound the recovered boot, stable host observations and baseline SHA-256
`8ae795f59e0c2bd39a7ef1a13295b2e991126aa60230c7ea2f348407b2138172`.
Conditional cleanup removed its diagnostic stage after matching the accepted
terminal hash. Original hardware/recovery stages and all local evidence remain
preserved. No device I/O, host configuration change or reboot occurred.

Prepared `host-hardware-20261013-v2` from this accepted, cleaned baseline and
the original accepted networking provenance. Its corrected registry check
permits only the constrained loopback UUID replacement. UART/PPS/RTC bring-up
and account/runtime prerequisites remain unaccepted and unstarted respectively;
clock services remain unactivated.

Next approve the [corrected hardware review](/home/aaron/code/.local-evidence/homelab-ntp/current/host-hardware-20261013-v2/review.md)
and its `sealing.json` SHA-256 for hardware/boot setup, one controlled reboot,
dual-stack/device-metadata acceptance and conditional recovery/cleanup.
Console/media readiness is required before reboot. Account/runtime execution
requires a separately reviewed bundle bound to this baseline and accepted
hardware. This baseline approval does not authorize either mutation.

### October 13: hardware v2 held; conditional recovery completed

Executed the approved `host-hardware-20261013-v2` bundle once, SHA-256
`2e121c4a4f83b87f3f8c6ee9814462b32205f1466db92867ded6965b9dc7abe5`.
Boot changes and the controlled reboot completed. All six bounded acceptance
probes held at `PL011 driver required`. The serial alias and ttyAMA character
device checks preceding that comparison passed; the actual sysfs driver name
was not included in the terminal error. Hardware failure is not established.
The remaining device-tree, PPS and RTC checks did not complete.

The approved conditional recovery inspected retained state, restored both
original boot files, submitted one recovery reboot and reached `recovered`.
The retained dual-stack network/native continuity checks passed. This recovery
mode uses the reachable pinned endpoint; it does not produce the hardware
acceptance mode's separate IPv4/IPv6 SSH proofs. Cleanup recorded
`transient_units_cleaned=true`. No hardware acceptance receipt was issued.
The protected root stage, before-state, journals and all private execution
records remain preserved in the operation directory. Account/runtime setup
and clock-service activation remain unstarted.

Next prepare a scoped read-only UART/sysfs/driver inspection for separate
execution approval. Establish the observed mapping before changing the recipe
or checker; preserve this executed bundle unchanged. A replacement hardware
stage needs fresh evidence and its own approval. Do not replay consumed modes
or treat recovery as UART/PPS/RTC acceptance.

### October 13: read-only UART/sysfs inspection prepared

Prepared `host-uart-inspection-20261013-v1` offline using the existing registry
inspection controller. Bind the exact hardware v2 bundle, completed recovery
and cleanup state, recovered boot, pinned SSH identity, current worker/tests
and all three governing documents. Preserve the executed hardware bundle and
its root stage unchanged.

One capture reads the serial alias metadata, bounded ttyAMA/ttyS parent driver
chains, device-tree compatible/status/name properties and AMBA driver/device
metadata twice. The inherited capture also records stable retained state,
network profiles/routes and boot files; restored boot bytes must match the
protected originals. It performs no device opens, sysfs writes, module changes,
service changes or reboot. Conditional readback never repeats capture; cleanup
removes only the new protected diagnostic stage after terminal-hash acceptance.
Interrupted captures remain preserved.

Focused offline tests cover parent-driver relationships, absent devices,
path escapes, property/entry bounds, changing metadata, restored-file drift
and recovered-boot/cleanup binding. These checks establish capture behavior,
not a diagnosis of the failed candidate boot. No target contact occurred.

Next approve the [UART/sysfs review](/home/aaron/code/.local-evidence/homelab-ntp/current/host-uart-inspection-20261013-v1/review.md)
and its `sealing.json` SHA-256 for one read-only capture with conditional
readback and cleanup. Receiver timing, hardware acceptance, account/runtime
setup and clock-service activation remain pending.

### October 13: UART inspection accepted; ancestry correction prepared

Executed the approved `host-uart-inspection-20261013-v1` capture once.
Diagnostic acceptance bound the recovered boot and stable retained state,
original boot files and UART metadata. Conditional cleanup matched the terminal
hash and removed only the new diagnostic stage. Original hardware/recovery
stages and all private execution evidence remain preserved.

The recovered boot reports `uart-pl011` bound to AMBA device
`fe201000.serial`, with `arm,pl011-axi`, `arm,pl011` and `arm,primecell`
compatibility and device-tree status `okay`. No serial0 alias or ttyAMA/ttyS
nodes were observed. This confirms the AMBA driver exists on the recovered
boot; it does not reconstruct the failed candidate boot's tty mapping.

Approved offline correction now follows the selected tty's bounded sysfs
parent chain and requires exactly one PL011 AMBA ancestor with matching
registry identity and device-tree compatibility. It no longer assumes the
driver sits directly under the tty device. The worker records the observed
chain and any UART validation error in protected state before subsequent
checks or recovery. Tests cover intermediate serial layers, wrong/ambiguous
ancestors, registry mismatch, path/property bounds and saved failure evidence.
Executed bundles remain unchanged.

Extended fresh-baseline preparation to bind directly to a hardware stage's
completed recovery verification and cleanup, retaining support for the older
recovery-continuation provenance. Prepared `host-baseline-20261013-v2` for one
read-only capture with conditional readback and cleanup. No target contact
occurred during this preparation; no replacement hardware bundle has been
sealed against stale observations.

Next approve the [fresh baseline review](/home/aaron/code/.local-evidence/homelab-ntp/current/host-baseline-20261013-v2/review.md)
and its `sealing.json` SHA-256. After capture acceptance and cleanup, seal the
corrected hardware bundle for separate execution approval. Account/runtime
setup and clock-service activation remain pending hardware acceptance.

### October 13: fresh baseline v2 accepted; hardware v3 prepared

Executed the approved `host-baseline-20261013-v2` capture once. Diagnostic
acceptance bound the recovered boot, hardware v2 recovery/cleanup provenance
and stable fresh observations. Baseline SHA-256:
`a7581ff7a3fd21ed6dfbaa96315b924f20eedfe482625e623b0ad845ed0d08c3`.
Conditional cleanup matched the accepted terminal hash and removed only the
new diagnostic stage. Original protected stages and all local evidence remain
preserved. No device I/O, configuration change or reboot occurred.

Prepared `host-hardware-20261013-v3` offline against that accepted, cleaned
baseline. It validates the selected UART through its PL011 AMBA ancestor,
registry identity and device-tree compatibility, and records the observed
mapping in protected state before any hold or recovery. The constrained
loopback comparison and remaining network/native/PPS/RTC checks remain binding.
No hardware execution or account/runtime setup occurred in this step.

Next approve the [hardware v3 review](/home/aaron/code/.local-evidence/homelab-ntp/current/host-hardware-20261013-v3/review.md)
and its `sealing.json` SHA-256 for hardware/boot setup, one controlled reboot,
dual-stack/device-metadata acceptance and conditional readback/recovery/cleanup.
Console/media recovery readiness is required before reboot. Account/runtime
setup remains separately approved and conditional on hardware acceptance;
clock-service activation remains pending.

### October 13: hardware v3 held; recovery and checker corrections

Executed approved hardware v3 once. Boot edits and the controlled reboot
completed, but bounded acceptance probes held at `UART metadata link escaped
sysfs tree`. Conditional readback preserved the candidate boot identity and
`serial0 -> /dev/ttyAMA0`; its ancestor array was empty. PPS/RTC acceptance
did not complete. The terminal error did not identify the rejected link, so
its exact live target remains unconfirmed.

The approved recovery restored original boot files, submitted one recovery
reboot and passed the retained network/native continuity checks. Cleanup
recorded `phase=recovered` and `transient_units_cleaned=true`. As with v2,
recovery uses a reachable pinned endpoint rather than the hardware acceptance
mode's separate IPv4/IPv6 SSH proofs. Root backups, candidate bytes, state,
journals and all local records remain preserved. Account/runtime setup and
clock-service activation remain unstarted.

Offline review identified two checker defects: all subsystem links were
restricted to `/sys/bus`, excluding tty class links, and partial ancestry was
lost when collection raised an exception. Corrected the bounded traversal to
permit exactly the tty class subsystem and device-tree root where applicable,
while preserving AMBA driver/registry identity checks. Partial ancestry and
the rejected link are now saved before failure. Regression fixtures include
an intermediate serial layer, tty class link, device-tree-root ancestor and
rejected unrelated class with retained evidence. This is an offline correction,
not proof of the precise candidate-boot failure or hardware acceptance.

Prepared `host-baseline-20261013-v3` from v3's completed recovery/cleanup for
one read-only capture with conditional readback and cleanup. No additional
target contact occurred after the approved cleanup. Next approve the
[fresh baseline v3 review](/home/aaron/code/.local-evidence/homelab-ntp/current/host-baseline-20261013-v3/review.md)
and its `sealing.json` SHA-256. After acceptance, seal the corrected hardware
bundle for separate execution approval; do not replay consumed v3 modes.

### October 13: fresh baseline v3 accepted; hardware v4 prepared

Executed the approved `host-baseline-20261013-v3` capture once. Acceptance
bound hardware v3's recovered boot, completed recovery/cleanup and stable
fresh observations. Baseline SHA-256:
`254c131c0f305911126b395ff72f4250083d81dce98264aa7a2c598e4248c840`.
Conditional cleanup matched the accepted terminal hash and removed only the
diagnostic stage. Earlier protected stages and all local records remain
preserved; no device I/O, configuration change or reboot occurred.

Prepared `host-hardware-20261013-v4` offline against the accepted baseline.
It includes the tested tty-class/device-tree-root traversal correction and
partial ancestry/error retention, while requiring one matching PL011 AMBA
ancestor and retaining the network/native/PPS/RTC checks. No hardware or
account/runtime execution occurred in this step.

Next approve the [hardware v4 review](/home/aaron/code/.local-evidence/homelab-ntp/current/host-hardware-20261013-v4/review.md)
and its `sealing.json` SHA-256 for boot setup, one controlled reboot,
dual-stack/device-metadata acceptance and conditional readback/recovery/cleanup.
Console/media readiness is required before reboot. Account/runtime setup and
clock-service activation remain pending hardware acceptance and their own
execution approvals.

### October 13: hardware v4 held at PPS path; candidate retained

Executed approved hardware v4 once. Boot changes and controlled reboot
completed. The corrected UART ancestry check passed: serial0 resolves to
ttyAMA0 through serial-base port/controller layers to the registered PL011
AMBA device with matching device-tree compatibility. Retained network/native
checks passed during the bounded probes. Acceptance then held because
`/sys/class/pps/pps0/device/of_node/compatible` does not exist. PPS/RTC metadata
acceptance and separate IPv4/IPv6 SSH acceptance proofs did not complete.

The approved conditional readback preserved the actual candidate-boot UART
chain and error evidence. Candidate boot configuration remains applied and
unaccepted. No recovery reboot, restoration or cleanup was performed; keep the
live hierarchy available for diagnosis before recovery. Protected originals,
sealed inputs and journals remain intact. Existing hardware recovery modes
remain available under v4's approval. Account/runtime setup and clock-service
activation remain unstarted.

Prepared `host-timing-inspection-20261013-v1` offline using the existing
protected registry-inspection controller. Bind the exact v4 readback state,
candidate boot and candidate boot-file hashes. One capture records bounded
PPS/RTC class ancestry, device/driver/subsystem/device-tree links, bound
pps-gpio platform devices and fixed GPIO controller metadata twice. Only
metadata properties are read: no device opens, PPS assert/clear samples, RTC
clock attributes, sysfs writes, driver binding, service changes or reboot.
Tests cover virtual PPS classes without a device link, platform mappings,
RTC ancestry, excluded sample/clock reads, path/size bounds, candidate drift
and stable capture acceptance. No new target contact occurred during preparation.

Next approve the [candidate PPS/RTC inspection](/home/aaron/code/.local-evidence/homelab-ntp/current/host-timing-inspection-20261013-v1/review.md)
and its `sealing.json` SHA-256 for one capture with conditional readback and
cleanup of only the new diagnostic stage. This does not accept hardware or
clean up the retained hardware stage. Use the observed hierarchy to determine
the next correction or execute the already-approved v4 recovery; do not replay
consumed start/reboot/verify/readback modes.

### October 13: candidate PPS/RTC inspection accepted and cleaned

Executed the approved `host-timing-inspection-20261013-v1` capture once.
Diagnostic acceptance bound the unchanged candidate boot, v4 readback state,
candidate boot-file hashes and two matching metadata passes. Conditional
cleanup matched the accepted terminal hash and removed only the diagnostic
stage. Original hardware state, backups, candidate boot and private evidence
remain preserved. No hardware recovery or clock-service activation occurred.

Observed PPS class `pps0` at `/sys/devices/virtual/pps/pps0`, without a device
link or device-tree node. Its name is `pps@12.-1`; the separately bound
pps-gpio platform device is `pps@12`. That platform's device-tree node has
`pps-gpio` compatibility, GPIO controller phandle 7, BCM GPIO18 and flags 0;
`assert-falling-edge` is absent. The referenced controller identifies as
`brcm,bcm2711-gpio`. The checker incorrectly assumed that the virtual class
provided `device/of_node/compatible`.

RTC class `rtc0` links to I2C device `1-0052`, driver `rtc-rv3028`, with
`microcrystal,rv3028` compatibility. No PPS samples, RTC clock attributes or
device data were read. These are accepted diagnostic observations, not proof
of pulse health, RTC accuracy or completed hardware/time-service acceptance.

Next prepare corrected PPS class/platform correlation and an acceptance-only
continuation bound to this candidate and accepted inspection, for separate
execution approval. Preserve original v4 sealed code/state. No repeated boot
change is needed solely to correct the metadata validator. Account/runtime
setup remains conditional on successful full hardware acceptance; v4 recovery
modes remain available under their existing approval.

### October 13: PPS correction and acceptance-only continuation prepared

Prepared `host-hardware-acceptance-20261013-v1` offline, bound to unchanged
hardware v4 and the accepted/cleaned PPS/RTC inspection. Corrected PPS checks
use the registered pps-gpio platform and GPIO controller metadata, correlate
the virtual class source name, and verify its character-device number.
Regression fixtures cover the observed virtual-class hierarchy, ambiguous or
wrong mappings, candidate/source drift, shared-lock exclusion, evidence-only
staging/cleanup, prohibited mutation modes and dual-endpoint acceptance.

The new stage may only stage its own protected evidence, verify the existing
candidate, record a separate acceptance, read back and close its evidence.
It cannot repeat boot edits, reboot, restore files, activate services or open
devices. The original source stage is checked under its existing shared lock
and remains unchanged. Failure preserves diagnostics and candidate state.
The original v4 controller and dependencies were preserved privately and its
remaining recovery payloads verified offline against the original archive.

Next approve the [acceptance-only continuation](/home/aaron/code/.local-evidence/homelab-ntp/current/host-hardware-acceptance-20261013-v1/review.md)
using its exact `sealing.json` hash, for j2-svntp1. No target contact or live
acceptance occurred during preparation. Hardware v4 remains applied and
unaccepted; its authorized recovery remains available. Account/runtime must
be resealed against successful continuation acceptance before execution.

### October 13: hardware acceptance-only continuation accepted and closed

Executed the approved `host-hardware-acceptance-20261013-v1` evidence-only
start once, followed by one verification sequence. Both fixed IPv4/IPv6 SSH
endpoints produced matching candidate-boot and hardware proofs. Acceptance
passed all eight checks: network, native files, boot files, changed boot,
UART, PPS, RTC and unchanged bootstrap clock-service state. The corrected
PPS class/platform correlation passed against the retained candidate.

The separate hardware receipt records successful metadata acceptance.
Conditional cleanup marked its evidence closed while preserving both stages,
original v4 specification/state/backups/journal, and all private execution
records. Terminal replies were complete; separate readback was unnecessary.
No boot writes, reboot, recovery, account/cache mutation, service activation,
PPS samples, RTC clock reads or device opens occurred.

Next prepare and seal account/runtime prerequisites against this accepted
continuation for separate execution approval. The older runtime bundle is
bound to hardware v1 and must not be executed. Dedicated account creation,
loader validation and rendered service candidate remain pending; physical
GNSS/PPS/RTC health and clock-service activation remain later gates.

### October 13: account/runtime v2 prepared against accepted hardware

Prepared `host-runtime-20261013-v2` offline using the checked-in runtime recipe,
current helpers/templates/manifests and all three governing documents. Bound
the exact accepted hardware continuation specification and archive, accepted
baseline v3 and retained network acceptance. Offline checks revalidate the
hardware receipt, both endpoint proofs and closed continuation evidence.
Live execution must still pass the guarded hardware/current-boot, native,
package, service, loader and account preflight before mutation.

Separated historical-input validation from execution freshness checks: an
accepted baseline predating the PPS inspector update remains valid provenance
when its archive, manifest, target and accepted terminal records match.
Current-controller matching remains mandatory for execution. The new runtime
archive includes the hardware acceptance and cleanup records; the worker
also rejects live gate state that differs from the sealed receipt. Regression
tests cover old-launcher provenance, execution rejection of that launcher,
receipt/cleanup drift and live accepted-boot/hardware mismatches.

Scope remains dedicated `ntp:ntp` account creation, protected loader-cache
backup and refresh without library-symlink changes, root and NTP-user native
Python validation, and rendering/validation of a private service candidate.
No global service/config installation, clock-service activation, boot changes,
reboot or receiver/PPS/RTC I/O is authorized by preparation. Conditional
readback, guarded account/cache recovery and operation cleanup are defined
in the new review; prior artifacts remain preserved.

Next approve the [account/runtime v2 review](/home/aaron/code/.local-evidence/homelab-ntp/current/host-runtime-20261013-v2/review.md)
using its exact `sealing.json` hash. No target contact or runtime mutation
occurred during preparation. Hardware metadata remains accepted; final
NTP configuration, physical timing and service activation remain later gates.

### October 13: account/runtime v2 accepted and cleaned

Executed the approved `host-runtime-20261013-v2` start once. Preflight accepted
the bound hardware continuation and current boot, retained network/native
state, loader inputs and absent NTP names. Created the dedicated `ntp:ntp`
system identity (UID 999, GID 985), with `/nonexistent` home, nologin shell and
no home creation. Backed up the loader cache and refreshed it with `ldconfig
-X`, preserving native files/modes and library symlinks.

Runtime validation passed libgps cache resolution, GPSD/NTPsec version probes,
isolated root GPS/NTP imports, isolated NTP-user imports, UART dialout access
and the private rendered timeservice candidate with target systemd validation.
Both fixed management endpoints produced matching acceptance proofs. All eight
checks passed: network, native, hardware gate, account, loader, Python,
candidate and unchanged bootstrap clock-service state. The separate runtime
receipt records acceptance; conditional operation cleanup completed.

Complete terminal replies made separate readback and recovery unnecessary.
Account and cache changes remain accepted; protected before-state, candidate,
receipts and prior artifacts are preserved. No global service/config copy,
clock-service activation, reboot, GNSS/PPS/RTC sampling or device I/O occurred.

Next prepare final NTP configuration and the GPSD/NTPsec service cutover with
acceptance and recovery for separate execution approval. Physical timing,
NTP client responses and service activation remain pending.

### October 13: acquisition-first profile selected and prepared offline

The user selected all three NTS candidates (Cloudflare, System76 Ohio and
System76 Oregon), Default LAN IPv4/ULA time service and localhost-only
administrative queries. The user also selected separate GPSD acquisition
before rendering final NTP configuration. These are configuration decisions;
no NTS association or client service is activated by preparation.

Prepared the [GPSD acquisition review](/home/aaron/code/.local-evidence/homelab-ntp/current/gpsd-acquisition-20261013-v1/review.md)
against accepted account/runtime v2, its cleanup receipt and candidate boot.
The adjacent sealing.json binds the exact archive hash and execution window.
The checked-in recipe/controller defines one receiver-read-only GPSD run,
900-second JSON/SHM capture, protected staging, independent timeout and UART
restoration, bounded conditional readback, recovery and transient-unit cleanup.
Original executed stages, all evidence and SHM segments remain preserved.

Next obtain separate execution approval for this acquisition. Then review
actual receiver validity and SHM assignments/ownership before preparing the
final ntp.conf and service-cutover review. No target contact, service start,
receiver I/O or clock change occurred during this preparation.

### October 13: GPSD acquisition captured, restored and cleaned

Executed the approved `gpsd-acquisition-20261013-v1` start once. Readback 18
returned matching terminal evidence through both fixed management endpoints;
prior readbacks reported pending without replaying acquisition. The bounded
window completed in approximately 901 seconds, and both monitoring clients
exited successfully. GPSD stopped; the independent stop handler restored the
saved UART settings. Post-capture runtime, native, hardware, network and
bootstrap continuity passed. Conditional transient-unit cleanup completed;
recovery was unnecessary. Original stages, raw evidence and all SHM segments
remain preserved. NTPsec was not started and bootstrap synchronization remains
unchanged.

The private capture contains 902 TPV reports, all mode 3/status 2, decoded as
NMEA0183 at 115200; 899 NTP0 samples reported leap 0 and precision -1. No NTP1
samples were collected. GPSD reported kernel PPS unavailable for `/dev/serial0`.
The accepted receipt therefore records capture acceptance while keeping
receiver timing and SHM mapping acceptance false. Receiver firmware identity
was not established. Raw receiver coordinates and logs remain outside Git.

Offline inspection of the pinned GPSD source confirms that an explicit PPS
device is supported; the serial-device lookup used by this capture did not
associate the GPIO PPS device. This does not establish whether physical PPS
pulses were absent. Next prepare a corrected acquisition using explicit
`/dev/pps0`, source-reviewed serial/PPS pairing and explicit PPS reporting,
then obtain its separate execution approval. Final NTP configuration and
service cutover remain gated on accepted timing and SHM observations.

### October 13: corrected explicit-PPS acquisition v2 prepared offline

Prepared the [v2 acquisition review](/home/aaron/code/.local-evidence/homelab-ntp/current/gpsd-acquisition-20261013-v2/review.md)
with `/dev/serial0` and explicit `/dev/pps0`, retaining receiver-read-only mode,
115200, loopback access and the 900-second limit. Added `gpspipe -P` so PPS/TOFF
reports expose device paths, timestamps and SHM unit names. Pinned-source
review confirms serial time propagation to PPS-only devices; one serial input
makes that relationship unambiguous. Unit numbers remain observation-driven.

The new bundle binds accepted runtime and v1 capture/cleanup provenance,
original terminal/restoration evidence and retained SHM inventory. Guards reject
changed segment identities/ownership or attachments and preserve original
executed inputs. Offline tests cover exact device/watch arguments, provenance
drift, timestamp correlation, ambiguous/missing reports, duplicate samples,
independent timeout and UART recovery. GPSD credentials are captured after the
observation window rather than immediately after startup.

Next approve v2 using its adjacent sealing.json hash. No target contact,
receiver I/O, service activation or repeat acquisition occurred during this
preparation. Final configuration/cutover remains gated on accepted PPS and SHM
observations, with timing accuracy and firmware identity assessed separately.

### October 13: explicit-PPS v2 captured, restored and cleaned

Executed the approved `gpsd-acquisition-20261013-v2` start once. The prior
capture/cleanup, retained SHM inventory and runtime gates passed. Readback 19
returned matching terminal evidence on both fixed management endpoints after
approximately 900 seconds. Both monitoring clients exited successfully; GPSD
stopped, saved UART settings were restored, and runtime/native/hardware/network
and bootstrap continuity passed. Conditional cleanup retired transient unit
state while preserving all original evidence and SHM segments. No recovery,
NTPsec activation or bootstrap clock-service change was needed.

PPS/TOFF JSON and independent SHM sampling established `/dev/serial0` on NTP0
and `/dev/pps0` on NTP2, with 897 exact leap-0 timestamp matches per source.
There were 899 serial SHM samples, 898 PPS SHM samples, 901 mode-3 TPV reports
and one mode-2 report. GPSD confirmed kernel PPS use for `/dev/pps0`; its final
UID/GID were 65534/20 (nobody/dialout). The retained root-owned NTP0/NTP2 modes
were 0600/0666. A local hash-bound `pairing-review.json` independently reproduces
the correlation and keeps timing-accuracy acceptance false. Raw coordinates
and logs remain private.

The user correctly challenged starting a full observation before checking
initial functionality. The executed runner checked process/socket readiness
but exposed only pending status until completion; that did not establish PPS
functionality. The plan and operations recipe now require a short, visible
functional gate before any further long observation. The executed runner and
bundle remain unchanged; this requirement must be implemented in a future
reviewed acquisition rather than claimed as part of v2.

Next resolve the remaining receiver firmware and final runtime inputs, then
prepare final NTP configuration and service cutover for separate execution
approval. Rerender the earlier serial-only service candidate with the observed
explicit-PPS profile and unit mapping. Source pairing is established; clock
discipline, timing accuracy and dual-stack client acceptance remain pending.

### October 13: functional gate implemented; remaining input inspection prepared

Implemented the short functional gate in the checked-in acquisition recipe
and runner. Five distinct leap-0 serial/PPS matches on different SHM units
must arrive within 30 seconds with live children before the longer window
continues. Start and pending readback responses expose the durable result.
Failure stops children and retains independent UART restoration; partial held
captures can be read back and cleaned after dual-stack restoration/continuity
acceptance without accepting samples or replaying acquisition. Prior executed
archives remain unchanged. This implementation is tested offline, not on target.

Reviewed accepted v2 evidence offline: NMEA0183/115200 and NTP0/NTP2 pairing
are established, but no receiver firmware response is present. The pinned
NTPsec source resolves leapfile refresh options and reload checks without an
automatic restart; current leap contents/destination/permissions and final
service/Avahi inputs still require inspection.

Prepared `receiver-runtime-inputs-20261013-v1` using the existing protected
acquisition controller and a checked-in bounded inspector/recipe. Its private
review and sealing.json bind the accepted runtime and v2 capture/cleanup,
current inputs and target identity. Scope: one MON-VER query at 115200 with a
10-second/65536-byte bound, read-only runtime file/service metadata, independent
UART restoration, dual-stack acceptance, conditional recovery and cleanup.
The query writes a version request but no receiver settings. GPSD/NTPsec stay
stopped; no long acquisition, leap download or clock-service change is prepared.

Next approve that sealed inspection, review the receiver response and runtime
inputs, then prepare final configuration/cutover for separate execution
approval. No target contact or mutation occurred during this preparation.

### October 13: receiver identity and runtime inputs accepted

Executed the approved `receiver-runtime-inputs-20261013-v1` once. One MON-VER
query and bounded runtime metadata capture completed; the worker recorded
about 0.3 seconds. Both fixed management endpoints returned matching terminal
evidence, restored UART settings and unchanged runtime/network/bootstrap/SHM
continuity. Conditional cleanup completed, preserving all evidence and SHM
segments. No recovery, receiver-setting change, daemon activation or repeat
query was needed.

The checksum-valid response reports ROM CORE 3.01 (107888), hardware 00080000,
FWVER SPG 3.01 and PROTVER 18.00. Its constellation strings describe capabilities,
not enabled settings or a confirmed module variant. A private `inputs-review.json`
binds acceptance, cleanup and the independently decoded response.

The installed ntpleapfetch is root-owned 0755. The root-owned 0644 distribution
leap list has a valid internal checksum and expires June 28, 2027 UTC; no leap
asset was downloaded or deployed. Final NTP/supervisor configuration and service
unit are absent, as are the inspected drift/statistics directories. The NTP
account is UID 999/GID 985. Avahi and bootstrap timesyncd are active, while UDP
123 has no listener. GPSD/NTPsec remain stopped.

Next prepare and seal final explicit-PPS configuration/service cutover using
these observed inputs: select and pin the leap asset, render paths/permissions,
SHM associations, selected NTS upstreams, LAN restrictions and Avahi scope;
include backups, early functionality, timing/client acceptance and recovery.
Execution requires separate approval. No new long acquisition is needed solely
to reproduce the already accepted source pairing.

### October 13: final service cutover prepared offline

The user selected serial NMEA as a selectable source, without assumed
calibration, alongside preferred GPIO PPS and all three NTS upstreams. This
workstation is the approved client-test location. The checked-in candidate
binds observed NTP0/NTP2 ordering, receiver-read-only GPSD, Default LAN access,
localhost-only administrative queries, eth0-only Avahi and the pinned leap asset.

The reproducible supervisor now applies the shared short source-pairing gate
before every ntpd start. The sealed cutover procedure includes byte-exact backups,
120-second apply limit, early ntpd functionality, independent 1800-second
recovery, consecutive convergence checks, dual-endpoint proof and workstation
NTP/mDNS acceptance. Durable acceptance precedes recovery cancellation;
only acceptance enables persistent timeservice and leap maintenance. Recovery
restores files/UART/bootstrap service while preserving all executed evidence;
it cannot reverse clock corrections or survive a reboot.

The current review is `service-cutover-20261013-v1/review.md` under the private
current-evidence directory; its adjacent `sealing.json` binds the archive SHA-256.
No target contact, clock-service activation, receiver change or upstream query
occurred during preparation. Next obtain separate approval of this sealed
cutover, then execute its one start and early functionality gate before the
bounded convergence/client checks. Timing/client acceptance remains pending.

Offline input-binding, startup, client parser, acceptance and recovery tests
passed against the candidate, including an offline seal using the accepted
receiver archive. Exact ntpleapfetch unit/executable validation remains a target
pre-activation requirement because that pinned executable is absent from the
workstation. These checks do not constitute live acceptance.

### October 13: cutover v1 recovered without acceptance

Executed the approved `service-cutover-20261013-v1` once. Protected backups,
installation and target unit validation completed. The early functional gate
matched six serial NTP0 samples and five GPIO PPS NTP2 samples, then ntpd
answered its first localhost query. The independent recovery timer was armed.

The first convergence probe observed selected/reachable PPS, reachable serial,
leap 0 and stratum 1. Daemon credentials, unchanged supervisor and the configured
PPS offset/jitter thresholds passed. The journal-health check was false;
all three NTS associations were still unauthenticated and unreachable at that
probe. This does not establish a persistent NTS failure or its cause. The sealed
journal check covers the entire trial, so further waiting could not clear it.
No long observation, acceptance attempt or workstation NTP/mDNS check followed.

Invoked the approved explicit recovery. The runner restored backed-up files
and UART settings, preserved generated statistics, restarted original Avahi
and bootstrap timesyncd, and passed original runtime/network/hardware continuity.
Both fixed management endpoints returned identical recovered state; the
terminal receipt was recorded and conditional cleanup completed. GPSD/NTPsec
are stopped and the cutover was not accepted. No reboot, receiver-setting
change, leap maintenance fetch or repeat cutover occurred. Recovery does not
undo any clock corrections already made during the trial.

The private `outcome.json` binds the start, probe, recovery, both readbacks,
terminal receipt and cleanup evidence. The executed archive and root-owned
stage, including command/journal output and backups, remain preserved. Current
readback omitted the underlying journal entries, so the failure's cause remains
unverified. Next prepare a scoped read-only retrieval of that retained journal
and command evidence for separate execution approval before correcting or
retrying cutover. Do not relax acceptance or change upstreams without evidence.

### October 13: retained cutover journal inspection prepared offline

Prepared `run-cutover-inspection.py` and offline regression tests for one scoped
read-only retrieval on `j2-svntp1`. The
[private review](/home/aaron/code/.local-evidence/homelab-ntp/current/cutover-inspection-20261013-v1/review.md)
and adjacent `sealing.json` bind the executed cutover archive, recovered/cleaned
state, matching recovery receipts, current inputs, target boot and a unique
operation ID. No target contact occurred during preparation.

The stage reads the original protected source under its existing shared lock,
retrieves before/state/command records and the saved journal-health result,
and runs one retrospective journal query bounded to the trial boot/time window.
It also records `/etc/ntp.conf` metadata and fixed service states. Source files
are limited to 2 MiB each, journal output to 399 complete records/2 MiB, and
retrieved evidence to 8 MiB before encoding. Overflow or incomplete evidence
holds diagnostic acceptance. The worker is bounded to 90 seconds; individual
queries to 20 seconds. Conditional matching dual-endpoint readbacks precede
closure, which preserves all diagnostic and original evidence.

Recovery removed `/etc/ntp.conf` because the pre-trial file was absent. GPSD/NTPsec
remain stopped in the recovered record, with bootstrap synchronization restored.
The journal failure's cause remains unknown. Next obtain separate execution
approval for this inspection; do not retry the cutover or change acceptance
criteria before reviewing its evidence.

### October 13: retained journal trigger retrieved; diagnostic held and cleaned

Executed the approved `cutover-inspection-20261013-v1` capture once. The original
protected specification, recovered/cleaned state and input hashes passed their
initial checks. The saved before/state/command files and journal-health output
were retrieved. The original error-priority query had returned exactly one
entry: `SYNC: Found 5 servers, suggest minsane at least 3`. That nonempty output
made the cutover journal-health criterion false. It does not explain the initial
pending NTS associations or prove persistent NTS failure.

The supplemental retrospective query failed with status 1 because `journalctl`
rejected the hyphenated boot descriptor. This is a collector defect. No repeat
capture was attempted. Current service/configuration metadata and final source
comparison were not reached, so full diagnostic acceptance remains held and
source-preservation verification is incomplete. The saved pre-trial record
confirms `/etc/ntp.conf` was absent; current absence was not independently checked.

Both pinned-key management endpoints returned identical partial reports with
verified evidence digests. The held terminal receipt authorized diagnostic
cleanup, which completed and retained all files. No services, configurations,
receiver settings or clocks were changed. Original cutover and diagnostic
artifacts remain preserved; private `outcome.json` binds the execution results,
readbacks, held receipt and cleanup result.

Next correct/test journal boot-ID handling and prepare a new bounded diagnostic
for separate execution approval. Evaluate the `minsane` recommendation against
the intended source/fallback policy before another cutover; do not suppress the
journal entry or change upstream choices without review. Time-service acceptance
remains pending.

### October 13: corrected diagnostic v2 prepared; minsane policy reviewed

Corrected the journal boot filter to compact hexadecimal while retaining the
canonical UUID for target validation. Added malformed-ID rejection and regression
coverage that exercises the local `journalctl` parser with `--help`, without
opening a journal. Existing bounded capture, drift, held-result and cleanup tests
remain required. The
[v2 review](/home/aaron/code/.local-evidence/homelab-ntp/current/cutover-inspection-20261013-v2/review.md)
and adjacent `sealing.json` bind a new operation/stage to the recovered cutover
state and current inputs. No target contact occurred during preparation; v1's
executed archive, partial report and cleanup evidence remain preserved.

Reviewed the retained pinned NTPsec 1.2.5 source and corroborating upstream docs.
The startup recommendation counts selectable configured associations; selection
separately enforces the survivor threshold. Recommend retaining `minsane=1` for
local-reference availability instead of requiring a network survivor when only
two local GPS associations remain. Both local associations share one receiver;
this choice prioritizes availability over a multi-source quorum. OPERATIONS
records the evidence and the requirements for any future narrow journal exception.
No cutover configuration, acceptance code or target setting changed.

Next obtain separate execution approval for v2's read-only capture, conditional
readbacks and diagnostic closure. Complete the diagnostic before a new cutover
review; the source-policy recommendation is not an executed configuration change.

### October 13: diagnostic v2 accepted and cleaned; NTS transport failures identified

Executed the approved `cutover-inspection-20261013-v2` capture once. Corrected
boot filtering returned 191 records for the bounded trial window. Both pinned-key
management endpoints returned identical complete reports, all evidence digests
verified, and the original source-file comparisons passed. Diagnostic acceptance
and closure completed; all staged and prior evidence remains preserved. Private
`outcome.json` binds the capture, both readbacks, receipt and cleanup result.

The saved journal-health trigger remains the `minsane` startup recommendation.
The wider journal additionally shows each of the three configured NTS-KE
connections attempted over IPv6 on TCP 4460 and refused before TLS negotiation.
No IPv4 attempts are shown in this window. The evidence establishes the initial
transport failures, not the location of the rejection, its persistence, a
certificate problem or provider outage. No new upstream probes were performed.

NTPsec logged successful mDNS registration with Avahi compatibility warnings;
Avahi later logged legacy-unicast response-size warnings. Workstation discovery
and client acceptance remain unproven. Current metadata confirms `/etc/ntp.conf`
is absent, the trial service and leap timer are absent/inactive, and bootstrap
synchronization and Avahi are active/enabled. This matches the recorded recovery;
no target services or configurations changed during inspection.

Next prepare a scoped IPv4/IPv6 NTS transport inspection, accounting for the
intended service context, for separate execution approval. Resolve the connection
refusals before another cutover; retain authentication and upstream choices.
The `minsane` recommendation still requires explicit treatment in the next
cutover review. Diagnostic acceptance is not time-service acceptance.

The operator subsequently reported missing IPv6 address entries in the UniFi
Default LAN-to-External NTP rule. This is a plausible, unverified explanation
for the observed transport failures. Next inspection should establish the actual
rule matches and IPv6 egress source, and distinguish TCP 4460 key exchange from
UDP 123 time traffic. No UniFi inspection or firewall modification was performed
or authorized by this diagnostic execution.

### October 13: scoped UniFi/NTS transport inspection prepared offline

The operator confirms there are no IPv6 permits for UDP 123 or TCP 4460 from
Default LAN to External. This is operator-reported confirmation, not an agent
inspection or a proved rule hit. The retained September 21 controller snapshot
also shows separate IPv4 UDP 123 and TCP 4460 exceptions and a later dual-stack
reject referencing both ports. Those historical facts are not current acceptance.

Prepared `run-nts-transport-inspection.py`, its closed recipe and network helper,
with offline tests for controller identity/TLS failure, credential redaction,
pagination/ordering completeness, bounded public-address probes, NTP-account
privilege drop, refused connections and protected evidence preservation. Reused
the tested diagnostic staging/readback/closure controls. The
[private review](/home/aaron/code/.local-evidence/homelab-ntp/current/nts-transport-inspection-20261013-v1/review.md)
and adjacent `sealing.json` bind current inputs and the recovered cutover state.
No target, controller or Doppler access occurred during preparation.

Scope: one verified local-controller GET collection, then one protected node
capture with at most 12 TCP 4460 attempts across the three names, both families
and root/NTP accounts. Controller bounds are 40 requests, 400 rows per endpoint,
16 referenced lists, 16 MiB total and 300 seconds. Node commands retain the
90-second worker/20-second command bounds and two-second connect timeouts.
Dual-endpoint readback and diagnostic closure preserve all previous evidence.
No firewall changes, daemon start, TLS/NTS negotiation, UDP probes, receiver or
clock writes are authorized by preparation. Account probes do not recreate the
service sandbox, and an API snapshot cannot establish packet/rule-hit attribution.

Next obtain separate execution approval for this two-target diagnostic. Review
its current source-address and policy evidence before preparing any network-owner
firewall change or another cutover. The diagnostic is not time-service acceptance.

### October 13: UniFi/NTS transport inspection accepted and closed

Executed the approved `nts-transport-inspection-20261013-v1` bundle once against
both named targets. Verified controller collection completed before node start;
13 bounded requests collected current policy, ordering and referenced lists.
Both pinned management readbacks matched; diagnostic cleanup completed with all
original and new evidence preserved. Private `inspection-acceptance.json` and
`outcome.json` beside the review bind the receipts, result hashes and conclusions.

Current Default LAN-to-External ordering has IPv4-only UDP 123 and TCP 4460
exceptions referencing an IPv4 NTP-server list, followed by an enabled dual-stack
reject referencing both ports. There is no applicable IPv6 NTP/NTS exception.
All three upstreams accepted IPv4 TCP 4460 connections under both root and the
NTP account; all six IPv6 attempts returned connection refused. The actual IPv6
socket source was a global address, not the fixed management ULA. Exact addresses,
policy identifiers and per-probe timings remain in private evidence.

These observations support the missing-permit explanation, but do not prove
which component generated each refusal: no packet trace or rule-hit counters
were collected. UDP, TLS/NTS negotiation and the service sandbox were not tested.
The recovered state remains intact: `/etc/ntp.conf` absent, trial service inactive,
and bootstrap timesyncd active. No firewall or service configuration changed;
time service remains unaccepted.

Next prepare a network-owner IPv6 permit correction with source-identity/stability
checks, ordering, return traffic, backups, recovery and bounded transport
acceptance for separate approval. Resolve transport before another cutover;
retain the pending explicit `minsane` policy and narrowly tested journal handling,
NTS authentication, dual-stack client and mDNS acceptance requirements.

### October 13: automated IPv6 permit candidate prepared offline

The operator approved preparation and requested maintainable matching for the
host's changing global IPv6 address. The candidate uses two IPv6-only source-MAC
permits for the observed Ethernet interface, preserving RA/SLAAC and avoiding a
global-address list or recurring credentialed updater. API support is based on
the operator-supplied Ubiquiti Network v10.6.106 OpenAPI specification; the
retained controller reports 11.0.83, so schema and packet behavior remain live gates.
The operator also considered UniFi's IPv6 interface-ID selector and explicitly
chose MAC matching with no host addressing change.

The operator chose automated API execution and confirmed `AUDIT_LOCAL` has full
read/write permissions. The network-owned `UNIFI_ACCESS.md` now records that
capability separately from action authorization; existing diagnostics remain
GET-only. No credential retrieval or controller/node contact occurred in this
preparation.

`homelab-network/Ubiquiti/ntp-ipv6/` owns offline sealing, exact policy creation,
ordering, readback, recovery and tests. It reuses fresh NTP diagnostic bundles
before/after the change and conditionally after recovery. Original rules/lists
stay unchanged; restore only exact operation-owned additions. There is no
independent gateway rollback timer. Interrupted work requires retained intent
inspection and the approved recovery continuation, without resubmitting a create.

Next obtain separate hash-bound execution approval for the private parent review
under `homelab-network/ntp-ipv6-permit-20261013-v1`. It accepts only policy scope
and root/NTP-account dual-stack TCP reachability. UDP exchange, authenticated
NTS, explicit minsane/journal policy and client/mDNS acceptance remain pending
for the service cutover. Prefix rollover itself is not tested by this stage.

### October 13: IPv6 permit v1 held before mutation; v2 prepared

Executed the approved parent bundle once. Its before-diagnostic completed,
matched both management readbacks and recorded cleanup. Fresh controller data
showed the existing IPv6 DNS allow rule now matched MAC addresses instead of
its previously referenced IPv6 address list. That list was no longer referenced
by the collection; this does not establish deletion. All other compared baseline
sections and policy fields matched. This existing DNS change was observed, not
performed or reverted by the NTP operation.

Exact preflight comparison held before the mutation client authenticated or any
firewall write was submitted. No NTP permits were created; no recovery was needed.
The fresh TCP results still showed all six IPv4 connections succeeding and all
six IPv6 connections refused. Original service state and all evidence remain
preserved. The v1 apply registration cannot be replayed.

Prepared v2 offline from v1's accepted and closed before-diagnostic. It retains
the same MAC-bound two-permit scope, current DNS policy, conditional recovery and
TCP acceptance. Fresh child operation IDs and a new archive hash require separate
execution approval. No host address change, UDP/NTS authentication or service
cutover occurred. The next review is
`homelab-network/ntp-ipv6-permit-20261013-v2` under private evidence storage.

### October 13: IPv6 permit v2 policy and TCP acceptance completed

Executed the separately approved v2 parent once. Fresh preflight matched the
reviewed controller baseline, including the operator-confirmed DNS MAC-source
change. Both new IPv6-only NTP permits were created disabled, verified, ordered
before the existing reject, then enabled. Original policies, referenced lists,
return traffic and relative order were preserved. The permits match the observed
Ethernet MAC; no host address, prefix or interface configuration changed.

Before the change, six IPv4 TCP probes succeeded and six IPv6 probes were refused.
Afterward, all twelve connected successfully: all three configured upstreams,
both families, under root and the NTP account. Both diagnostics matched their
dual-endpoint readbacks and completed cleanup; their source state remained
unchanged. V2 recorded `policy_and_tcp_accepted`. The two permits remain enabled;
recovery was unnecessary and was not exercised. All original and new evidence,
including v1's held execution, remains private and preserved.

This accepts firewall policy and bounded TCP connectivity only. It does not prove
UDP delivery, TLS/NTS authentication, service-sandbox behavior, prefix rollover,
clock discipline or client/mDNS acceptance. No clock service was activated.
Private `apply/accepted.json` and `outcome.json` under
`homelab-network/ntp-ipv6-permit-20261013-v2` bind the operation and results.

Next prepare a corrected service-cutover review using the accepted network
receipt and current node inputs. Explicit minsane policy and narrowly tested
journal handling remain required, along with early functionality, authenticated
upstreams, dual-stack workstation NTP/mDNS acceptance and recovery. Separate
execution approval is required; neither accepted firewall transaction nor the
previous cutover may be replayed.
