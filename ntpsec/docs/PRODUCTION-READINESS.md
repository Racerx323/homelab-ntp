# j2-svntp1 production readiness

Reconciled October 15, 2026, after statistics-retention installation.
This is a reconciliation of retained evidence and repository documents,
not a new live inspection. The [plan](ntp-architecture-deployment-plan-v1.0.md)
defines requirements; [HISTORY](../HISTORY.md) records operation outcomes.

## Decision and next action

**Resume here:** prepare a scoped, read-only monitoring-prerequisites inspection
for j2-svntp1, covering OBS-02 and OBS-07. Establish separated statistics-growth
samples, available bytes/inodes, existing space/failure alerting, Munin endpoint
state, intended poller and approved access scope. Review the owning Munin
repository first; do not assume a poller identity or topology. Use the findings to
prepare monitoring configuration and acceptance. No new target contact or
monitoring deployment is authorized by this checkpoint; prepare the sealed
inspection review for execution approval.

Keep OBS-01 and OBS-03 queued: inspect actual results after the retained October
16 checkpoints (00:52:56 CDT logrotate and 05:30 CDT needrestart). Initial global
logrotate state discovery may defer this rule's rotation. Neither checkpoint has
been observed by this documentation update. Reconcile the follow-up register
before advancing; required ntpviz remains Phase 3B after current-node completion.

The NTP runtime, controlled restart, warm reboot/RTC initialization, convergence
and post-reboot client/discovery checks have passed. **Overall host production
acceptance is still open.** Phase 3 steps 6–7 require the remaining baseline
applications, hardware checks, observation interval and inventory closure.

Mail installation `mail-install-20261015-v1` passed under its approved bundle.
Eight pinned packages were installed; the accepted inventory has 701 records.
The msmtp transport and root failure alias are active; msmtpd remains masked and
inactive. Both exact synthetic messages were submitted once, and the operator
confirmed downstream Apprise receipt for report and failure routes at 8:30 p.m.
The reporter capture checks and daily schedule activation passed under
`mail-reporting-20261015-v1`. The real list-only scan was quiet and produced no
message; synthetic scan failure and lock contention produced the expected captured
failure handling. No immediate test message was sent. The exact cron file is now
active for daily 05:30 America/Chicago; the first scheduled occurrence is October
16, 2026, at 5:30 a.m. CDT. Package/NTP/protected-file continuity passed.
The operator subsequently confirmed the installed reporter's manual test delivery
to Apprise at 21:16:41 CDT on October 15. Its sample kernel/services/session items
are synthetic, not live findings. First scheduled execution and cron-generated
failure-mail delivery remain unobserved; overall reporting acceptance stays open.

The timer-only correction `leap-timer-correction-20261015-v1` executed and passed
on October 15, 2026. It restores the plan's OnBootSec=15min while retaining
OnUnitActiveSec=4w and RandomizedDelaySec=30min. The enabled/waiting timer's next
trigger remained four weeks out after manager reload. The successful scheduled
run at 7:18:55 p.m. CDT was preserved; no new fetch was requested. NTP retained
its PID and invocation with zero restarts, and the live leapfile was preserved.
The next trigger is estimated at November 12, 2026, 6:19:41 p.m. CST from retained
realtime/monotonic evidence; this is not a fresh list-timers observation.
Four-week soak and physical Pi reboot/initial-trigger acceptance remain pending.
No mail installation or notification occurred.

Webmin 2.670 and its five dependencies are installed. Continuation v2 passed:
Webmin is active/running/enabled, both exact TCP listeners and local IPv4/IPv6
HTTP 200 checks passed, UDP discovery is absent, and the confirmed full-file
configuration hash remained unchanged after probes. The three theme-handler
additions were previously proven to explain the entire configuration change.
The failure reset succeeded; the guard/permit remain installed. NTP identity
and zero restarts were preserved. That Webmin-stage inventory had 693 records; mail installation increased it to 701.
The operator subsequently confirmed authenticated ama login over IPv4 and IPv6.
Read-only temp-storage inspection passed: `/tmp` has about 1.85 GiB available,
Webmin temp usage is 4 KiB, and `/var/tmp` is ext4 with about 106.3 GiB available.
No current byte/inode shortage was found; settings remain unchanged. Suitability
for large uploads/backups and physical RAM headroom under load remain unassessed.
The approved policy remains HTTP on the Default LAN IPv4/ULA pair with `ama`;
Caddy integration is deferred. Operator-attested authenticated login passed. Controller
firewall policy and External exposure remain unverified. Observe scheduled leap
maintenance during final observation; do not infer a result from elapsed time.

## Phase 3 gate reconciliation

| Gate | Retained evidence and disposition | Remaining work |
| --- | --- | --- |
| NTP/GPSD runtime | All-source startup, saved-drift controlled restart, acquisition-aware startup and new-boot structural handoff accepted | Preserve the accepted runtime while closing other gates |
| Timing and clients | Boot observations 5 and 6 passed 392 seconds apart; unchanged daemons and zero restarts. Final IPv4/IPv6 timing, query denial and native Windows discovery passed | Repeat affected checks after later changes; these samples do not replace the agreed final observation interval |
| RTC | Commissioning v3 and boot v2 prove RV3028 identity, UTC policy, synchronized set/readback, fake-clock absence and kernel boot initialization | Battery-backed power-loss retention remains explicitly untested; the plan distinguishes it from warm reboot acceptance |
| Leap maintenance | Timer-only correction executed and passed; prior successful scheduled run preserved and four-week next trigger checked across reload | Actual four-week recurrence and physical-host post-reboot initial trigger remain unobserved; see OBS-05 and OBS-06 |
| Webmin | v2 local HTTP/configuration checks and operator ama login over IPv4/IPv6 passed; temp-storage inspection found no current space shortage | Assess storage needs before large uploads/backups; controller exposure remains unverified |
| Mail and needrestart | Mail transport, both operator-confirmed synthetic deliveries, reporter capture checks, installed reporter manual-test delivery and daily 05:30 cron activation accepted | Observe the first scheduled run on October 16, 2026; cron-generated failure mail remains unobserved |
| Statistics retention | Four-stream rule/private trigger installed; target fixtures, debug validation and targeted first run passed with empty deletion preview and unchanged NTP/writer identity. Approved 10 GiB/5 percent free-inode pre/postflight floors passed | Subsequent scheduled rotation, continued statistics growth, sustained storage budget, ongoing free-space alerts and maintenance failure reporting remain unaccepted. Next timer trigger observed as October 16 at 00:52:56 CDT; initial global-state discovery may defer rotation. Required plotting is Phase 3B |
| Munin | munin-node absent from the post-reboot inventory | Endpoint/plugin configuration in the Munin repository; approved poller/allowlist and collection over intended address families |
| Hardware watchdog | Userspace watchdog package absent from the post-reboot inventory. Deployment recovery timers are different mechanisms | Inspect device/driver ownership and configuration; approve installation/enablement and controlled failure/recovery test separately |
| Network persistence | Earlier network acceptance established fixed addresses, RA, DNS and egress. Latest boot passed both fixed SSH endpoints and client families | Reconcile current-boot RA global address/default route, resolver views and DHCP/RA DNS suppression; endpoint reachability alone does not prove these properties |
| PoE, fan and thermal health | Earlier operator observations establish normal fan/power and original PoE HAT; boot success does not establish sustained health | Current power budget/class, fan/control, temperature, undervoltage/throttling and sustained-operation evidence; no stress or switch changes implicit |
| OS/media/access | Trixie identity and accepted boot/kernel continuity are recorded; original recovery card retained | Close the complete per-node baseline, current update status and final observed inventory. Wi-Fi disablement remains unproven in HISTORY, not silently accepted |
| Final observation and inventory | Short timing convergence accepted; no agreed final host observation interval or completed final inventory established by these captures | Agree interval and criteria after remaining changes; complete inventory from observed facts |

Package absence above comes from the inventory retained by the post-reboot RTC
check, not from the original Debian 11 baseline. No new target query was made.
The relevant retained operations are `production-boot-20261015-v2`,
`rtc-set-readback-20261015-v3`, and `client-postboot-20261015-v1`.

## Monitoring and deferred observation register

This is the current checklist for the plan's
[deferred observation and ongoing monitoring register](ntp-architecture-deployment-plan-v1.0.md#deferred-observation-and-ongoing-monitoring).
All current rows concern j2-svntp1 unless noted. Repeat applicable checks for the
next node; j2 evidence does not accept another host. These are retained observations,
not new live checks. Recorded times are checkpoints, not automatic reminders or
proof of completion. Owner assignment and recurring monitoring implementation
remain pending wherever not established below.

| ID | Current status | Next checkpoint or dependency | Evidence required to close or hand over |
| --- | --- | --- | --- |
| OBS-01 | Installed; targeted first run passed; scheduled rule execution unobserved | Captured next logrotate trigger: October 16, 2026, 00:52:56 CDT. Inspect afterward; first global-state discovery may defer this rule's rotation | Scheduled service result plus rule-specific state/trigger evidence; preserve the installation record `statistics-retention-20261015-v1`. Do not close from timer success alone |
| OBS-02 | Short-transaction active-file checks passed; sustained growth, storage budget and ongoing alerts incomplete | Prepare separated read-only samples and decide representative interval; integrate ongoing monitoring before Phase 3 extended observation | Four-stream growth/capacity assessment, approved 10 GiB/5 percent inode floors reflected in monitoring or explicitly revised, failure visibility and alert acceptance. Event-driven protostats need not grow on every sample |
| OBS-03 | Manual reporter test delivered; first daily scheduled execution unobserved | October 16, 2026, 05:30 America/Chicago, then inspect the actual result | Cron execution and report/quiet-scan outcome under `mail-reporting-20261015-v1`; record ongoing job-health owner |
| OBS-04 | Synthetic failure route delivered; cron-generated failure mail unobserved | Prepare a separate controlled failure-path review with exact recipient/content approval | Cron-originated test evidence and operator-confirmed downstream receipt; do not resend existing tests implicitly |
| OBS-05 | Corrected timer accepted; four-week live recurrence unobserved | Retained estimate: November 12, 2026, 18:19:41 CST; refresh live schedule under approved scope before relying on it | Actual scheduled result, valid leapfile and subsequent trigger. Estimate is not a fresh timer observation; reconcile any phase-gate deferral explicitly |
| OBS-06 | Isolated boot-trigger tests passed; physical Pi boot-trigger behavior after correction unobserved | Next separately approved reboot; observe the 15-minute initial trigger plus allowed jitter | Host reboot/maintenance result and next recurrence schedule; preserve shared-antenna power and recovery controls |
| OBS-07 | Munin endpoint/poller acceptance incomplete | Scoped endpoint/poller review, then repeated collection over the agreed interval | Intended-family collection, fresh metrics and missing-data/failure visibility; configuration owned by the Munin repository |
| OBS-08 | Boot and earlier operator fan/power observations retained; sustained health not accepted | Agree duration/load and collect during final host observation | Fan/thermal/PoE/undervoltage evidence; watchdog controlled failure/recovery remains a separately approved baseline gate |
| OBS-09 | Final Phase 3 interval, cadence and tolerances not agreed; Phase 8 still later | Close prerequisite gates, agree observation contract, then start after the last relevant change | Reviewed time/client/network health across the full interval and final inventory; record restart/retest rules and recurring operations owner |
| OBS-10 | RTC set/readback and warm-boot initialization accepted; power-loss retention untested | Separate operator decision and approved recoverable power-loss window | Battery-retention result or explicit untested disposition; never infer it from the accepted warm reboot |
| OBS-11 | Required separate-host dashboard deferred to Phase 3B; host/name undecided | After j2 Phase 3 completion, before next-server installation | Host sizing and private dashboard acceptance, then refresh/staleness/failure monitoring under the statistics policy |
| OBS-12 | Webmin idle temp capacity inspected; large upload/backup suitability unassessed | Before enabling/using large workloads | Workload-specific disk/RAM assessment; retain current configuration until a separate change is reviewed |

Update this table after every relevant operation, including a quiet or failed
observation. Reference the exact operation/result in HISTORY; keep raw evidence
private. A new delayed obligation needs a row here and, if it changes requirements,
a corresponding plan entry. Before phase closure, account for every open row;
carry continuing checks into an identified operations procedure instead of dropping
them when installation is complete.

## Separate rollout and reproducibility work

- **Phase 3A:** record adopted/deferred optimization decisions before copying
  the configuration to the primary. The plan explicitly permits retaining
  defaults; optional tuning is not a production blocker by itself.
- **Phase 3B required ntpviz dashboard:** after current-server completion, select
  and qualify the separate always-on host, measure resource needs, and deploy/accept
  private plots under the governing statistics section. This remains mandatory
  before the next NTPsec server installation, but does not block j2 Phase 3 completion.
- **Fresh installation:** OPERATIONS and the installation-durability report
  still identify first-install paths that require prior acquisition/restoration
  receipts. Cached payloads and archive-free executable code do not close this
  gap. Implement/test fresh-observation entry paths before reusing the workflow
  for the primary; include the accepted RTC and acquisition policy in the
  reproducibility audit. Do not manufacture failed-run receipts.
- **Phase 4 primary rebuild:** first close standby and Phase 3B dashboard gates, then separately
  establish shared-antenna power continuity and any required interim DNAT
  transition. The primary supplies antenna power; successful standby NTP tests
  do not authorize primary shutdown or prove that dependency is removed.
- **Phase 5 unicast DNS:** A/AAAA/PTR/SRV deployment and queries through both DNS
  nodes/VIPs remain separate. The inspected Unbound file contains standby A and
  IPv4 PTR entries; it has no matching NTP SRV or standby ULA entry. This is
  repository evidence, not a statement about live DNS. mDNS acceptance does not
  substitute for these records.
- **Phases 6–8:** finish UniFi DHCP/allow/deny/DNAT policy and traffic tests,
  both-node inventory, remaining end-to-end acceptance and final observation.
  Do not bring all later rollout work into the next leap-maintenance stage.

No installation, timer activation, mail delivery, poller probe, watchdog test,
power interruption, DNS change or primary-node operation is authorized by this
review. Each live stage requires its scoped, sealed execution approval.
