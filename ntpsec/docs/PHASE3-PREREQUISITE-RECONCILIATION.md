# Phase 3 prerequisites and final observation

Reconciled October 30, 2026, using retained October 26–29 evidence and Aaron's
October 30 acceptance decisions. No new target contact or execution occurred.
Historical observation proposals below retain their original scope; the current
preparation order and final contract supersede their stale handoff instructions.

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

Only the explicitly approved watchdog exception and OBS-05 phase deferral apply.
Aaron remains the
decision owner; inspection and implementation owners must be named in each
subsequent operation review.

| Gate | Retained position | Required next evidence or decision | Boundary |
| --- | --- | --- | --- |
| OS, media and access | October 27 v5 completed 22 upgrades, clean dpkg audit, protected-file and initramfs verification; kernel unchanged | Refresh only affected inventory, filesystem/access and unresolved Wi-Fi facts | Observe first; no update, package refresh, media write or access change |
| Node network persistence | October 28 network capture plus October 29 recovery before/after comparison confirm fixed addresses, routes and resolver policy | Preserve dated profile/network evidence; final-window and broader controller/client coverage remain separate | A saved profile or reachable endpoint is insufficient; no lease renewal/reboot |
| Management and endpoint exposure | Webmin authenticated LAN access and Munin collection accepted | Intended listeners/allowlists, representative management paths and controller firewall/External exposure evidence | Node state alone cannot prove controller policy; controller work is a separate scope |
| Watchdog | October 29 recovery passed four automated gates; October 30 one-test exception accepted | J2 prerequisite satisfied; preserve unproved independent timing/hardware attribution | No repeat solely for timing; fleet requirements unchanged |
| Power, fan and thermal | October 26 fan state 2/4 and pwm1=10; October 29 final temperature 49.660 C and throttle flags 0x0; sustained evidence missing | Record installed HAT, fan/control, power class/budget, thermal and undervoltage/throttling facts; agree ordinary workload and evidence during OBS-08/09 | No stress, switch mutation, HAT change or antenna-power interruption |
| Leap recurrence, OBS-05 | Corrected timer accepted; four-week recurrence unobserved | Aaron approved phase-gate deferral October 30; record actual next trigger at OBS-09 start and review genuine result within 24 hours afterward | October 29 post-boot invocation supersedes assumptions based on the October 27 schedule; no current recurrence date asserted; OBS-05 stays open |
| Initial leap trigger, OBS-06 | October 28 observed the October 27 13:25:27 successful invocation, valid unchanged leapfile and recurrence schedule | Initial invocation/schedule accepted within this scope; actual four-week run remains OBS-05 | No reboot is authorized or required merely to satisfy this document |
| RTC retention, OBS-10 | Synchronized set/readback and warm boot accepted | Keep battery-backed retention explicitly untested for its Phase 8 power-loss gate | Not a new Phase 3 power-loss prerequisite; protect primary/shared antenna power |
| Monitoring persistence, OBS-07 | Expanded metrics/graphs, producers, contacts and canonical IPv4 attribution accepted | Preserve dual-family probes versus canonical updater distinction; assign master persistence owner/checkpoint and compare after separately approved relevant maintenance | No forced updater, plugin, limits run, contact test or master restart |
| Client/access coverage | Controlled IPv4/IPv6 NTP, query denial and Windows discovery accepted | Build expected client/VLAN/family/access matrix from repository inventory, link tested representatives and list gaps | Do not invent hosts or expand the approved initial service scope |
| Final inventory | Facts exist across dated accepted captures | Consolidate per-node baseline with provenance, dates and remaining unknowns; refresh affected facts under approved scope | Historical package counts and another host's evidence are not current inventory |

The [watchdog acceptance addendum](/home/aaron/code/.local-evidence/homelab-server-configs/current/watchdog-timing-disposition-20261030-v1/acceptance.md)
satisfies the J2 recovery prerequisite with its precise limitation. The original
execution verdict remains unchanged. OBS-06 is accepted; the October 29 final
capture also records a successful post-boot leap invocation. Neither invocation
proves OBS-05 recurrence. Aaron approved its bounded phase-gate deferral in the
[final contract](FINAL-OBSERVATION-CONTRACT.md#obs-05-approved-phase-gate-deferral).

## Final observation decisions and next checkpoint

Aaron selected a new 48-hour OBS-09 ordinary-service window with five-minute
node/client samples and existing Munin records. OBS-09 has not started. The
[final contract](FINAL-OBSERVATION-CONTRACT.md) records the completeness, tolerance,
reset/response and handoff criteria approved by Aaron on October 30.
No start epoch or current target health is inferred from this preparation.

1. Use the approved contract criteria. Preserve all accepted scopes and limits.
2. Prepare bounded read-only entry checks only for unresolved current facts:
   Wi-Fi persistence, hardware/fan/power class and budget, intended management
   listeners/allowlists and representative client coverage. Existing host inventory
   declares node monitoring and both families but does not supply a complete
   client/VLAN or switch-power matrix. Do not invent that coverage.
3. Bind the existing controlled dual-stack client and Windows discovery path in
   the observation review. Obtain the relevant controller/access evidence or
   explicit scoped disposition; node listener output cannot establish it.
4. Aaron accepted ownership of master network-persistence follow-up at the next
   separately approved relevant maintenance on October 30. No persistence test
   is claimed. Establish required current master state using retained evidence
   plus bounded missing reads.
5. Seal the observation scope after local qualification and prerequisite
   dispositions. One review may include bounded entry discovery and collection;
   do not create redundant inspection stages. Failed entry conditions stop start.

Later second-host qualification follows accepted J2 production deployment.
OBS-10 battery retention, OBS-11 separate-host ntpviz and Phase 8 end-to-end work
retain their owning phases. OBS-12 Webmin temporary-storage suitability remains
an obligation before large uploads/backups, not proof supplied by idle capacity.

The [observation procedure](OBS09-OBSERVATION-REVIEW.md) records consumed v3.
Entry stopped on duplicate collector records before boundaries or t0; qualify
record composition before another successor. Retained timing/client snapshots
do not establish accepted entry. Aaron accepted
ordinary-load health plus reported USW-Pro-48-POE/600 W/PoE+ facts without measured
per-port reserve, and workstation IPv4/IPv6 Webmin scope without proof of
external/controller filtering. Master persistence remains assigned to him at
the next relevant approved maintenance. These are bounded dispositions, not
claims of measurements. Bounded entry reads occurred; sampling has not started.

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
