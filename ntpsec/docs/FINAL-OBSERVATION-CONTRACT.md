# J2 Phase 3 final observation contract (OBS-09)

Prepared October 30, 2026. **Contract approved by Aaron on October 30, 2026.**
Aaron explicitly approved the remaining criteria: “Approve remaining contract criteria.”
No observation has started. This contract does not authorize target contact,
installation, restart, failure injection, notification, retry or second-host work.
Aaron owns acceptance. The architecture plan defines requirements; the
[prerequisite reconciliation](PHASE3-PREREQUISITE-RECONCILIATION.md) records their
current disposition. Existing accepted OBS-02/D1–D5 are unchanged.

## Entry conditions and scope

Use J2-SVNTP1, its declared `timeservice.service`/GPSD stack, the existing svmf
Munin master and one explicitly identified independent dual-stack client.
Windows-native discovery is a boundary check; WSL mDNS failure is not evidence
of a node discovery failure. Keep the serving peer and primary DNAT unchanged.

Before starting, bind current inventory, native tool paths, source identities,
reader thresholds, expected jobs/schedules, protected configuration and boot IDs
in the execution review. Reuse accepted evidence; refresh changed or missing
facts only. Close or explicitly disposition the remaining hardware/power,
Wi-Fi, management/access and master-persistence gaps listed in reconciliation.
An omitted check is unavailable, never an implicit pass.

The accepted October 30 watchdog exception satisfies the J2 recovery prerequisite
only. Its independent reset timing and hardware attribution limitations remain.
OBS-06 initial invocation is accepted. OBS-05 remains open under the approved
phase-gate deferral below. RTC battery retention is Phase 8; separate-host ntpviz
is Phase 3B after J2 acceptance. Neither is waived or pulled into this window.

## Duration, samples and completeness

Aaron selected **48 hours of ordinary intended service** on October 30, with
five-minute node/client samples and existing Munin records, independently for
OBS-09. Do not backdate from OBS-02 or the recovery trial. Start at an explicitly
recorded epoch after entry conditions pass and the node is precision-ready.

- Every five minutes: bounded native node health, independent direct IPv4 and
  IPv6 NTP responses, thermal/throttle counters, and existing monitoring records.
  Use the existing supervisor's 30-second degraded/acquisition records where
  available; do not alter its cadence or force Munin collection.
- Start, +24 hours and finish: configuration/boot continuity, network/resolver/
  listener state, relevant journal range, hardware/fan metadata, storage,
  scheduled-job results, leap state and current inventory differences. Read
  master graph/RRD freshness and existing limits/contact status; no test sends.
- Boundary snapshots: expected DNS answers, Windows discovery, representative
  management access and administrative-query denial on both families. Bind
  exact clients and permitted paths before approval; this is not every VLAN or
  Phase 8 DNAT/failover qualification.
- Require at least 99% of scheduled five-minute slots for each required stream,
  no gap over ten minutes, and both complete boundary snapshots. A slot is
  on time within 60 seconds; late/missing samples retain their actual timestamps.
  Failed service responses are failures, not missing data that can be discarded.
  No catch-up probes or interpolation substitute for missed samples.

These are sampled bounds. Existing logs may describe intervening events; passing
samples and graphs do not prove uninterrupted sub-minute health. State missing
or rotated records explicitly. Collector interruption retains partial results;
resumption needs reconciliation within the approved scope, never silent replay.

## Acceptance criteria

| Surface | Required result across the agreed window |
| --- | --- |
| Native time | Expected GPS/PPS source selected, leap 0 and stratum 1; absolute selected PPS offset <=5 ms and jitter <=1 ms; expected serial/PPS reach and all three configured NTS associations reachable/authenticated with cookies, using the accepted native predicates |
| Client time | Every completed scheduled probe returns a valid synchronized response from the intended endpoint on each family; zero observed response failures. This validates service responses, not independently calibrated client clock accuracy |
| Availability versus precision | Record fallback/acquisition/degraded states separately; they are not automatically outages. Any precision excursion prevents an unconditional precision pass and requires disposition; leave service running and preserve evidence |
| Service/configuration | Expected native identities and unchanged approved configuration; no unexplained service restart, boot change, ownership conflict or exposure change |
| Monitoring/jobs | Existing required node/master metrics and graphs remain fresh within their configured limits; no unexplained unknown/critical state or missed genuine job completion. Keep the canonical updater distinct from dual-family transport probes |
| Storage | Preserve the accepted OBS-02 conditional budget and limitations, 10 GiB available-byte and 5% free-inode floors, including accepted native rounding; no new growth claim or storage fault test |
| Hardware (OBS-08) | Ordinary workload and installed fan/control recorded; no new undervoltage/throttle flags, thermal fault or unexplained cooling failure. Compare temperature with the installed platform's recorded thermal trip policy; absent RPM telemetry is not a zero-RPM failure |
| Errors/network | No unexplained new relevant errors, address/resolver/policy drift or unexpected listening service; preserve the exact accepted startup-message dispositions rather than suppressing all warnings |

Do not average away a failed sample or infer provider delivery from SMTP status.
No synthetic fault or notification is needed for this observation. Previously
accepted bounded OBS-04 and contact delivery remain accepted within their scope.

## Changes, failures and completion

Boot, time-stack/configuration or hardware changes end the comparable interval;
retain it and prepare a new agreed interval after the change is accepted. A
routine expected Munin restart is assessed for actual freshness/coverage loss,
not automatically treated as a node reboot or an instruction to repeat all work.
Source changes are recorded against the native source and precision criteria.

A collection gap within the stated limits does not restart the window. A larger
gap, failed criterion or unexplained event blocks unconditional acceptance.
Aaron chooses a justified exception, a targeted extension/retest, or correction
and a new interval. Do not automatically extend, restart, repair, reboot or send.
A real service fault follows the existing operations/recovery procedure and its
authorization boundaries; preserving an observation never takes priority over
operator recovery.

At completion, reconcile all streams, failures, gaps, actual schedules and
inventory changes. Retain raw records once in the configurable private output
location, with a digest summary and acceptance decision; no recursive archives
or deletion is implied. Aaron reviews at start, daily and completion. After
handoff, existing alerts remain active and Aaron reviews job/monitoring health
weekly and after relevant maintenance. Final Phase 3 acceptance is explicit,
not implied by elapsed time, script exit status or a healthy final graph.

## OBS-05 approved phase-gate deferral

**Approved by Aaron on October 30, 2026.** Permit J2 Phase 3 acceptance before the genuine
four-week leap-maintenance recurrence, while keeping OBS-05 open. Aaron owns it.
At OBS-09 start, capture the timer's actual next scheduled trigger and record a
concrete follow-up deadline: that trigger plus 24 hours, in UTC and local time.
Do not carry forward November 24 from the October 27 boot as a current fact.
The October 29 post-boot invocation succeeded; it does not prove recurrence.

Close OBS-05 only with genuine scheduled invocation provenance, native service
result, valid leapfile and subsequent schedule. A successful no-replacement-needed
run is eligible; a forced/manual run or elapsed four weeks is not recurrence.
A reboot/schedule change requires recording the new deadline and reason, not
silent indefinite deferral. A missed or failed run is reviewed within 24 hours
of the recorded due time; inspect current leap validity and diagnose within
approved scope. Escalate imminent invalidity promptly under OPERATIONS. No
automatic rerun, reboot, mail test or package change is authorized by deferral.

## Next checkpoint

Prepare one bounded
observation review with explicit node/master/client scopes and any missing
read-only entry checks. Qualify only the required collector behavior locally;
use current repository implementations, never consumed-operation code or a new
unrelated test harness. Start requires separate execution authorization.
