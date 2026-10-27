# Phase 3 prerequisites and final observation

Reconciled October 26, 2026, from repository requirements and retained accepted
outcomes and the approved October 26 passive node capture. Fresh claims below
are limited to that snapshot; no additional target operation is authorized.
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
| OS, media and access | Accepted Trixie/source installation and boot history | Reconcile installed versions/origins, kernel/firmware, update status, persistent filesystems, access and Wi-Fi policy with current inventory | Observe first; no update, package refresh, media write or access change |
| Node network persistence | Fixed IPv4/ULA and earlier RA/DNS/egress acceptance; later dual-stack boot reachability | Current-boot profile/address/route/resolver and DHCP/RA DNS-suppression comparison; identify remaining reboot-persistence gaps | A saved profile or reachable endpoint is insufficient; no lease renewal/reboot |
| Management and endpoint exposure | Webmin authenticated LAN access and Munin collection accepted | Intended listeners/allowlists, representative management paths and controller firewall/External exposure evidence | Node state alone cannot prove controller policy; controller work is a separate scope |
| Watchdog | October 26 passive capture: PID 1/systemd owns watchdog0; runtime/reboot 1min/2min; protected continuity passed | Fleet policy/adoption design, independent recovery facts and separately reviewed controlled recovery test; no competing owner | Phase 3 requires acceptance before extended observation; no device open, enablement, reset or failure injection during inspection |
| Power, fan and thermal | Prior boot/operator observations; sustained evidence missing | Record installed HAT, fan/control, power class/budget, thermal and undervoltage/throttling facts; agree ordinary workload and evidence during OBS-08/09 | No stress, switch mutation, HAT change or antenna-power interruption |
| Leap recurrence, OBS-05 | Corrected timer accepted; four-week recurrence unobserved | Observe the actual run or obtain an explicit phase-gate deferral with owner, deadline, evidence and failure response | November 12, 2026, 18:19:41 CST is a retained estimate, not a fresh schedule; do not close by elapsed time |
| Initial leap trigger, OBS-06 | Isolated tests passed; corrected physical-host boot behavior unobserved | Observe at a separately approved maintenance reboot, potentially coordinated with watchdog acceptance only in a reviewed recovery plan | No reboot is authorized or required merely to satisfy this document |
| RTC retention, OBS-10 | Synchronized set/readback and warm boot accepted | Keep battery-backed retention explicitly untested for its Phase 8 power-loss gate | Not a new Phase 3 power-loss prerequisite; protect primary/shared antenna power |
| Monitoring persistence, OBS-07 | Expanded metrics/graphs, producers, contacts and canonical IPv4 attribution accepted | Preserve dual-family probes versus canonical updater distinction; assign master persistence owner/checkpoint and compare after separately approved relevant maintenance | No forced updater, plugin, limits run, contact test or master restart |
| Client/access coverage | Controlled IPv4/IPv6 NTP, query denial and Windows discovery accepted | Build expected client/VLAN/family/access matrix from repository inventory, link tested representatives and list gaps | Do not invent hosts or expand the approved initial service scope |
| Final inventory | Facts exist across dated accepted captures | Consolidate per-node baseline with provenance, dates and remaining unknowns; refresh affected facts under approved scope | Historical package counts and another host's evidence are not current inventory |

The watchdog requirement is mandatory under Phase 3 steps 5–7. Deferring it
would require an explicit governing-plan decision, not a checkbox change here.
OBS-05 permits an explicit phase-gate disposition; none is approved by this
reconciliation. OBS-06 remains open until observed or explicitly reconciled
against its owning requirement. Ordinary later Munin restarts do not erase
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

**Next action:** prepare the single controlled panic watchdog-expiry review with
preflight, independent evidence, precise timing and restoration. The accepted
[debugger snapshot](/home/aaron/code/.local-evidence/homelab-server-configs/current/watchdog-debugger-inputs-20261026-v1/outcome.md) resolves configured normal/early transport using the
exact-package source assessment. Ordinary KVM identification is confirmed; no
trigger or recovery result exists. Receipt consumed; no broad rediscovery needed.
Keep five-minute usable-NTP acceptance and the existing accepted dispositions.
The [readiness snapshot](/home/aaron/code/.local-evidence/homelab-server-configs/current/watchdog-recovery-readiness-20261026-v1/outcome.md) completed October 26 at 11:46:49.422 CDT;
protected continuity passed. Vendor ownership/native versions are retained, but
volatile journal configuration and empty pstore leave evidence survival unproved.
No trigger is selected; controlled recovery remains unready. Further target access,
persistence changes and failure injection require separate scopes. Steps 2–4 and
OBS-02/D1–D5/OBS-04 retain their existing dispositions; OBS-09 has not started.

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
