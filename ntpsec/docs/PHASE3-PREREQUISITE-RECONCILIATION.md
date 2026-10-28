# Phase 3 prerequisites and final observation

Reconciled October 28, 2026, from repository requirements, retained October 26
inspections and the October 27 update outcome. These are dated observations,
not a new target inspection; no additional target operation is authorized.
This is a decision record and preparation order, not a live execution approval.

## Authority and preserved acceptance

The [architecture plan](ntp-architecture-deployment-plan-v1.0.md#phase-3-rebuild-and-accept-j2-svntp1)
defines requirements. [OPERATIONS](OPERATIONS.md) defines procedure;
[readiness](PRODUCTION-READINESS.md) and accepted outcomes define current status.
Historical handoffs in procedures and old reviews do not override later acceptance.

- OBS-01/03: initial genuine retention/reporting and master consumption accepted;
  recurring job health still belongs in ongoing observation.
- OBS-02: the [accepted D1–D5 record](/home/aaron/code/.local-evidence/homelab-ntp/current/obs02-acceptance-20261024-v1/decision.json)
  is unchanged. It accepts the qualified planning baseline and conditional
  storage budget, including late samples/gaps, unmeasured bursts, assumed reserve
  sufficiency, composed failure coverage and native inode precision. Do not
  request another storage fault test or alter thresholds to reopen D4/D5.
- OBS-04: the [reviewed October 24 outcome](/home/aaron/code/.local-evidence/homelab-ntp/current/obs04-cron-failure-delivery-test-20261024-v2/outcome.md)
  accepts one genuine cron-originated controlled argument-failure delivery route
  with operator-confirmed receipt. Exact SMTP disposition, full diagnostic
  delivery, scanner crashes, every provider and sustained reliability remain
  unproved. Its receipt is consumed; do not replay it.
- Accepted NTP/GPSD startup, drift reuse, warm boot, RTC set/readback, client
  checks and bounded monitoring captures remain accepted within their scopes.
  They do not establish the still-unagreed final observation interval.

## Prerequisite dispositions

No open requirement is waived by this reconciliation. Aaron remains the
decision owner; inspection and implementation owners must be named in each
subsequent operation review.

| Gate | Retained position | Required next evidence or decision | Boundary |
| --- | --- | --- | --- |
| OS, media and access | October 27 v5 completed 22 upgrades, clean dpkg audit, protected-file and initramfs verification; kernel unchanged | Refresh only affected inventory, filesystem/access and unresolved Wi-Fi facts | Observe first; no update, package refresh, media write or access change |
| Node network persistence | October 28 boundary capture confirms fixed addresses, static IPv4 and RA IPv6 defaults, intended resolver and automatic-DNS suppression | Preserve dated profile/network evidence; final-window and broader controller/client coverage remain separate | A saved profile or reachable endpoint is insufficient; no lease renewal/reboot |
| Management and endpoint exposure | Webmin authenticated LAN access and Munin collection accepted | Intended listeners/allowlists, representative management paths and controller firewall/External exposure evidence | Node state alone cannot prove controller policy; controller work is a separate scope |
| Watchdog | October 26 passive capture: PID 1/systemd owns watchdog0; runtime/reboot 1min/2min; protected continuity passed | Fleet policy/adoption design, independent recovery facts and separately reviewed controlled recovery test; no competing owner | Phase 3 requires acceptance before extended observation; no device open, enablement, reset or failure injection during inspection |
| Power, fan and thermal | Prior boot/operator observations; sustained evidence missing | Record installed HAT, fan/control, power class/budget, thermal and undervoltage/throttling facts; agree ordinary workload and evidence during OBS-08/09 | No stress, switch mutation, HAT change or antenna-power interruption |
| Leap recurrence, OBS-05 | Corrected timer accepted; four-week recurrence unobserved | Observe the actual run or obtain an explicit phase-gate deferral with owner, deadline, evidence and failure response | October 27 v5 lists the next trigger on November 24; this supersedes the older November 12 estimate and is not a fresh schedule; do not close by elapsed time |
| Initial leap trigger, OBS-06 | October 28 observed the October 27 13:25:27 successful invocation, valid unchanged leapfile and recurrence schedule | Initial invocation/schedule accepted within this scope; actual four-week run remains OBS-05 | No reboot is authorized or required merely to satisfy this document |
| RTC retention, OBS-10 | Synchronized set/readback and warm boot accepted | Keep battery-backed retention explicitly untested for its Phase 8 power-loss gate | Not a new Phase 3 power-loss prerequisite; protect primary/shared antenna power |
| Monitoring persistence, OBS-07 | Expanded metrics/graphs, producers, contacts and canonical IPv4 attribution accepted | Preserve dual-family probes versus canonical updater distinction; assign master persistence owner/checkpoint and compare after separately approved relevant maintenance | No forced updater, plugin, limits run, contact test or master restart |
| Client/access coverage | Controlled IPv4/IPv6 NTP, query denial and Windows discovery accepted | Build expected client/VLAN/family/access matrix from repository inventory, link tested representatives and list gaps | Do not invent hosts or expand the approved initial service scope |
| Final inventory | Facts exist across dated accepted captures | Consolidate per-node baseline with provenance, dates and remaining unknowns; refresh affected facts under approved scope | Historical package counts and another host's evidence are not current inventory |

The watchdog requirement is mandatory under Phase 3 steps 5–7. Deferring it
would require an explicit governing-plan decision, not a checkbox change here.
OBS-05 permits an explicit phase-gate disposition; none is approved by this
reconciliation. OBS-06 initial invocation and recurrence schedule were observed on October 28;
the later recurrence itself remains OBS-05. Ordinary later Munin restarts do not erase
accepted within-capture continuity or prove uninterrupted operation between samples.

## Final observation decisions awaiting agreement

OBS-09 has not started. Do not backdate it to OBS-02 t0, October 24's delivery,
or this reconciliation. The [existing contract inputs](PRODUCTION-OBSERVATION-CONTRACT.md#final-phase-3-window-inputs-still-required)
remain pending; the accepted OBS-02 48-hour window supplies no default duration.

| Decision | Proposed treatment for the approval draft | Still required from Aaron |
| --- | --- | --- |
| Duration/start | Select a new interval after relevant changes and prerequisite acceptance/dispositions; record an explicit start epoch | Duration and permission to begin the separately reviewed collection |
| Cadence/completeness | Use existing supervisor and scheduled Munin records where available; bound node/master/client snapshots and retain real timestamps | Snapshot cadence, maximum gap/lateness and required completeness; no assumption that graphs prove every interval |
| Tolerances | Carry forward adopted startup/source policy and accepted reader/native limits; separate acquisition/degraded states from ready timing | Exact interval-level timing, client response/loss, freshness and error acceptance rules, with source references; do not promote one cutover's thresholds silently |
| Workload/hardware | Ordinary intended service load, observed fan/thermal/power state and counters | Workload envelope, hardware evidence cadence and exclusions; stress requires separate approval |
| Reset/retest | Preserve failures and gaps; assess which measurements a configuration, boot, source or device change invalidates | Restart/extension/disposition rules; neither erase failed intervals nor impose an unapproved full reset |
| Ownership/handoff | Aaron owns decisions; svmf supplies accepted native collection/evaluation/delivery | Recurring review cadence, failure response, evidence retention and named owners/checkpoints for deferred obligations |
| Closure | Review the full interval plus current inventory and every open gate | Explicit acceptance; neither successful controller exit nor healthy final snapshot closes Phase 3 |

## Preparation order and next checkpoint

1. Prepare a narrowly scoped, non-mutating **node current-state inspection review**
   for the first six prerequisite rows: baseline inventory, current-boot network,
   management listeners, passive watchdog metadata and available hardware facts,
   plus existing leap timer/service records. Reuse retained facts where adequate.
   Specify bounded commands, exact paths, sensitive-field exclusions, strict host
   identity, continuity checks, one-use/expiry controls and acceptance labels.
   Reading a device's metadata is distinct from opening it. No apt refresh,
   device access, reboot, job invocation, message or failure injection belongs in it.
2. Build the client/access matrix from repository inventory. Prepare separate
   controller-policy or master-persistence reviews only for remaining facts that
   cannot be established from the node and retained evidence. Do not bundle
   unrelated targets into the node approval.
3. Review inspection results before designing watchdog/recovery changes. Resolve
   OBS-05/06 phase dispositions and every baseline gap. Coordinate disruptive
   maintenance only after independent console recovery, peer service and antenna
   power continuity are established in its exact review.
4. Complete the OBS-09 decision table, then seal separate observation scopes.
   Begin only after required changes/gates and explicit contract/execution approval.
   Carry OBS-08 through the agreed interval and finish the observed inventory.

**Next action:** align and locally qualify independent availability/convergence
observation under the [revised contract](../../../homelab-server-configs/watchdog/docs/CONTROLLED-PANIC-REVIEW.md#timing-contract).
Aaron accepted boot/network <=60 seconds and 30-minute convergence followed by
30-minute stability; five minutes applies to NTP availability. The
[v2 addendum](/home/aaron/code/.local-evidence/homelab-server-configs/current/watchdog-panic-recovery-20261028-v2/acceptance-contract-addendum.md)
accepts only the observed boot/network result. Missing early client probes leave
availability unproved; the old observation ended before the new convergence
budget. Original precision failures and inconclusive attribution remain recorded.
No live action or new panic is authorized; retain the operator hold and unchanged
OBS-02/D1–D5, OBS-06 and final observation boundaries.

## Post-update assessment and proposed observation scope

The [October 27 v5 outcome](/home/aaron/code/.local-evidence/homelab-ntp/current/base-os-update-20261027-v5/outcome.md)
records one reboot at 12:55:06 CDT, both client families serving PPS/stratum-1/leap-0
within about 99 seconds, and the following precision samples:

| Checkpoint | Selected offset / jitter | Disposition |
| --- | --- | --- |
| +5 minutes, 13:00:56 CDT | 15.1021 / 18.0712 ms | Failed the 5 ms / 1 ms limits |
| +30 minutes, 13:25:56 CDT | -2.0126 / 0.0630 ms | Passed at this snapshot only |

Availability recovery and precision recovery are distinct. The five-minute
precision miss remains recorded; sparse snapshots and the operator-reported
13:20 Munin OK do not establish an exact convergence time or uninterrupted health.
The update restored its owned APT/EEPROM controls and retained active watchdog
metadata. Package completion does not establish controlled watchdog recovery.

Aaron's October 27 12:56:47 service excerpt ends with successful mDNS registration
after the Avahi compatibility warning. The excerpt establishes neither a timing
fault caused by that warning nor two daemon instances. Repeated messages share
PID 1078. Inspect raw journal provenance only if needed to resolve duplicate
presentation or the journal acceptance predicate; do not suppress messages or
change discovery configuration based on this excerpt.

The following records the preparation scope; the linked outcome now supersedes
its pending status. Actual execution used passive watchdog/temperature metadata
only for hardware and no producer/master reads. Windows discovery was added at
Aaron's direction. It does not authorize replay:

1. Bind j2-svntp1 and the existing independent dual-stack client from owning
   inventory. Reuse maintained repository helpers and installed native tools;
   do not extract executable code from consumed archives. Validate the same
   paths, authentication and commands that the observation will use.
2. Capture boot/service identity and protected configuration continuity at start
   and finish. Read existing package/kernel state, network profiles/routes/resolver
   policy, listeners, passive watchdog ownership/policy, thermal/throttling and
   available fan/PoE facts. Do not open the watchdog device or infer switch power
   policy from node metadata.
3. Read bounded retained journal/statistics for October 27 12:55:06–13:25:56 CDT
   if still available, including priority, transport, executable and PID metadata
   for the reported warning. Record unavailable history and gaps. Existing timing
   samples may bound convergence; interpolation must not invent threshold crossings.
4. Propose 30 minutes of ordinary operation with native timing samples once per
   minute and independent IPv4/IPv6 client checks at start and finish. Record
   source selection, reach, leap/stratum, offset/jitter, relevant NTS/refclock health
   and service continuity. Bound the whole operation to 45 minutes and each command
   with a timeout. This is a diagnostic proposal, not the OBS-09 final interval or
   a repeat of the five-minute recovery test. Preserve all failed/missing samples.
5. Read existing ntpleapfetch service result, timer timestamps and leapfile validity
   to assess OBS-06. Read existing producer completion records; use retained master
   evidence first. Any additional master read must be explicitly listed in the
   review. No forced jobs, plugin evaluations, collections, notifications or retries.
6. Retain partial stdout/stderr/status from launch in a configurable private run
   directory. Label each gate passed, failed or unavailable. Do not install a new
   collector or scheduler. No restart, package refresh, configuration change,
   failure injection or recovery action is in this observation scope.

If current timing is healthy, prepare one separately approved watchdog trial
against the updated baseline and existing fleet recovery contract. Retain the
five-minute criterion and independent KVM/reset evidence; ordinary observation
cannot qualify a reset. If timing is unhealthy, assess the recorded source/timing
facts before proposing a correction. Do not relax thresholds to obtain acceptance.

OBS-05 still needs actual recurrence evidence or an explicit phase-gate deferral.
OBS-09 still needs duration, cadence, tolerances, gap/reset rules and permission to
start. OBS-02/D1–D5 and bounded OBS-04 remain unchanged. Select/deploy a second
host only after accepted J2-SVNTP1 production deployment.

Phase 3A optimization decisions precede reuse on the primary. Required separate-host
ntpviz stays in Phase 3B, after j2 Phase 3 and before the next installation.
Fresh-install reproducibility, shared-antenna primary rebuild, remaining DNS/SRV
work and Phase 8 end-to-end/power-loss acceptance retain their owning phases.
They are neither silently waived nor all promoted into current Phase 3 blockers.

## Historical handoff handling

The observation contract's “Next executable preparation” describes the historical
OBS-02 t0 preparation/failure. Those snapshots have since completed and are
accepted under D1–D5; its old approval wording does not authorize replay.
The contract and accepted OBS-02 evidence remain byte-for-byte unchanged here.
Likewise OPERATIONS' older installation/runtime table is historical; use readiness
and later accepted outcomes to determine whether activation is still pending.
