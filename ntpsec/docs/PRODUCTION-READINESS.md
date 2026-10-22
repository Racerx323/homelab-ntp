# j2-svntp1 production readiness

Reconciled October 22, 2026, after accepted canonical source and producer follow-ups.
This checklist summarizes approved captures and repository documents;
updating it performs no additional live inspection. The [plan](ntp-architecture-deployment-plan-v1.0.md)
defines requirements; [HISTORY](../HISTORY.md) records operation outcomes.

## Decision and next action

**Resume here:** obtain separate exact-hash execution approvals for the sealed,
unexecuted +6h reviews, then execute node first at or after **October 22, 2026,
22:08:28.166 CDT**. Review the node capture before master execution:

1. [Node +6h review](/home/aaron/code/.local-evidence/homelab-ntp/current/munin-growth-6h-node-20261022-v1/review.md)
   / [SHA-256](/home/aaron/code/.local-evidence/homelab-ntp/current/munin-growth-6h-node-20261022-v1/sealing.json:1).
2. [Master +6h review](/home/aaron/code/.local-evidence/homelab-ntp/current/munin-growth-6h-master-20261022-v1/review.md)
   / [SHA-256](/home/aaron/code/.local-evidence/homelab-ntp/current/munin-growth-6h-master-20261022-v1/sealing.json:1).

Both scopes pin the accepted t0 pair and enforce the due time before receipt or
SSH; the remote collector checks it again before observations. Master also
requires reviewed acceptance of that exact +6h node capture. No target access,
sampling, receipt, reminder or waiting process was created during preparation.
Archive expiry is capped by the pinned t0 proofs; the controller's last permitted
start is before **October 23, 2026, 15:47:08.376 CDT**, reserving 15 minutes before
expiry. This upper bound permits execution, not acceptance of an arbitrarily
late checkpoint: record actual elapsed time and assess any lateness explicitly.
No later checkpoint is authorized by either review.

Approved t0 v2 node and master inspections completed once and their reviewed
baselines are accepted:

1. [Node outcome](/home/aaron/code/.local-evidence/homelab-ntp/current/munin-growth-t0-node-20261022-v2/outcome.md):
   t0 is **October 22, 2026, at 16:08:28.166 CDT** (21:08:28.166 UTC), epoch
   1792703308.1661916. All four active streams have matching writable ntpd
   descriptors; exact 33-plugin selection, storage floors and protected
   continuity pass. A transient process descriptor race is retained; relevant
   writer identities match across both scans. Event-driven protostats remains
   quiet with its active inode held writable.
2. [Master outcome](/home/aaron/code/.local-evidence/homelab-ntp/current/munin-growth-t0-master-20261022-v2/outcome.md):
   exact node context and protected continuity pass. All selected RRD files are
   present; nine selected graph configurations decode and thresholded native
   states are `ok`. Three completed scheduled cycles predate t0 and count only
   as baseline context. Committed contacts and successful submission status
   remain unchanged; this observation establishes no new delivery.

The selected [contract](PRODUCTION-OBSERVATION-CONTRACT.md) remains 48 hours at
t0/+6h/+24h/+48h, with 31 days at twice peak daily-equivalent gross growth plus
active-file allowance and unchanged 10 GiB/5% floors. Remaining checkpoints:

| Checkpoint | Due in America/Chicago |
| --- | --- |
| +6h | October 22, 2026, 22:08:28 CDT |
| +24h | October 23, 2026, 16:08:28 CDT |
| +48h | October 24, 2026, 16:08:28 CDT |

Only t0 is accepted; sustained growth and storage budget remain open. Later
samples require fresh due-time reviews. No target mutation, forced collection,
plugin/job/limits invocation, send or retry occurred. Both v2 receipts are
consumed; do not replay them. Failed node v1 and unexecuted master v1 remain
preserved as historical evidence. Final Phase 3 duration/tolerances remain pending.

Coverage reconciliation preserves accepted expanded metrics, canonical IPv4
source attribution, dual-family transport/dashboard evidence and delivered
contacts. Current-boot node RA/resolver policy, representative client/access
coverage, and master source behavior after a separately approved maintenance
event remain open. The contract distinguishes those obligations from a saved
profile or a quiet interval. Final Phase 3 duration, cadence, tolerances and
reset rules remain pending; the selected 48 hours applies only to OBS-02.
Watchdog/recovery, hardware health, recurring/boot maintenance dispositions and
final inventory still need their owning gates. Phase 3B ntpviz and Phase 8
remain separate. The bounded mail follow-up below stays accepted.

The approved [mail observation](/home/aaron/code/.local-evidence/homelab-ntp/current/munin-contact-mail-observation-20261022-v1/outcome.md)
completed once at 15:07:04 CDT on October 22. Protected boot/services/files and
committed config/helper/gate/marker continuity passed; effective includes are
empty. Status is valid, unchanged during capture and successful, with last
attempt at 14:50:15. The status schema has no message identity, so exact writer
attribution is not accepted from timestamp correlation alone. No suppression
record exists; this optional-file absence is not a failure.

Native transport mail sample is 1 at 15:05:13, matching RRD lastupdate; native
limits state is `ok`. Genuine completed cycles began at 14:50:02, 14:55:01 and
15:00:01. The RRD retains the earlier zero, fractional recovery interval and
later one-valued intervals. These five-minute AVERAGE values are consolidated,
not individual raw fetches. Native current-state/collection acceptance is
bounded to this capture and does not establish long-term reliability.

Operator Mailrise/Apprise excerpts establish partial delivery during the initial
failure: Discord and Mailgun reported success while Pushover ALL_DEVICES had a
connection error, yielding API 424 and the retained SMTP 450 result. Later
requests reported all three services successful with HTTP 200. The underlying
Pushover connection cause and exact later per-message mapping remain unproven.
No notification retry, forced collection/evaluation, status reset, HTTP request,
container/provider inspection or mutation occurred. Contacts remain enabled;
the observation receipt is consumed and must not be replayed.

[Activation v3](/home/aaron/code/.local-evidence/homelab-ntp/current/munin-contacts-activate-20261022-v3/outcome.md)
executed once, committed and reconciled the repository. All twelve verified
pre/post HTTPS checks passed. Gated notifications are now enabled for the eight
explicit j2 NTP graphs and J1-SVMF transport; global/j2 defaults remain none.
The proof-preserving successor passed sixteen native contact cases and 28 limits
cases with all seven pinned native module hashes. The diagnostic and rejected
activation v2 remain consumed; do not replay them or the accepted successor.

The approved [problem v2](/home/aaron/code/.local-evidence/homelab-ntp/current/munin-contacts-problem-20261022-v2/outcome.md)
was attempted once. SMTP returned `450 failed to send notification` and genuine
failure status was recorded. Aaron supplied the exact downstream Apprise problem
notification, confirming delivery despite submission failure. Both facts remain
recorded; the failed result was not rewritten or retried.

After that exact operator confirmation, the approved
[recovery v2](/home/aaron/code/.local-evidence/homelab-ntp/current/munin-contacts-recovery-20261022-v2/outcome.md)
was submitted once successfully and recorded genuine success status. Aaron also
supplied its exact downstream notification. Both confirmations bind the sealed
message, archive and consumed receipt. All three execution stages are consumed.

Aaron additionally supplied an automatic `Munin CRITICAL: J1-SVMF/ntp_transport_j2`
notification identifying critical field `mail`, followed by the automatic
`Munin OK: J1-SVMF/ntp_transport_j2` notification with no warning, critical or
unknown fields. Both downstream receipts are operator-confirmed. This establishes
an observed automatic CRITICAL-to-OK notification sequence. The separate
read-only observation above now accepts fresh native mail/current limits state
and the retained consolidated failure/recovery history.
The [contact procedure](../../../homelab-monitoring-observability/Munin/docs/ntp-contact-reviews.md)
keeps SMTP status, downstream confirmation and genuine scheduled use distinct.
The timing-reader correction committed
and reconciled at 11:35:57 CDT on October 22; master acceptance passed at 11:54:45.
Consumed operations:
[node reader correction + companion master checks](/home/aaron/code/.local-evidence/homelab-ntp/current/munin-generic-timing-20261022-v2/review.md)
/ [SHA-256](/home/aaron/code/.local-evidence/homelab-ntp/current/munin-generic-timing-20261022-v2/sealing.json:1),
then the [read-only master acceptance](/home/aaron/code/.local-evidence/homelab-ntp/current/munin-timing-master-acceptance-20261022-v1/review.md)
/ [SHA-256](/home/aaron/code/.local-evidence/homelab-ntp/current/munin-timing-master-acceptance-20261022-v1/sealing.json:1).
Both receipts are consumed; do not replay them. The
[node outcome](/home/aaron/code/.local-evidence/homelab-ntp/current/munin-generic-timing-20261022-v2/outcome.md)
accepts all 33 plugins across both complete post-change protocol families and
twelve HTTPS continuity requests. The
[master outcome](/home/aaron/code/.local-evidence/homelab-ntp/current/munin-timing-master-acceptance-20261022-v1/outcome.md)
accepts the genuine 11:40/11:45/11:50 CDT cycles, twelve fresh GAUGE RRDs with
three finite post-commit samples each, and ten verified dual-stack HTTPS
resources including both day graphs. Both new timing flags are 1; historical
pre-creation unknowns are preserved. Protected continuity and empty effective
includes passed.
That reader rollout did not install contacts. The separately accepted contact
activation and controlled delivery outcomes are recorded in the current checkpoint.

Guarded qualification passes 17 real native systemd cases, including eight
reader-specific success/recovery, worker/controller-loss, preflight and foreign
file/link/settings cases. Scope checks reject nine broadened/missing-prerequisite
variants. Repeated recovery after restoration does not restart the node again.
The master capture uses the accepted node commit epoch as a separately hashed
runtime context; older collection cannot satisfy it, and later read-only
successors do not require replaying the node change. The
[deployment procedure](../../../homelab-monitoring-observability/Munin/docs/ntp-timing-deployment.md)
records guard, acceptance, reset and restoration boundaries. Unexecuted node v1
was superseded during preparation; use v2 only.

The reader now evaluates inclusive ±5 ms offset and 0–1 ms jitter before native
rounding, exposing `selected_offset_ok`/`selected_jitter_ok` as 1/0/U in
`ntp_health` with critical `1:1`. Existing timing values/names/seconds units remain;
the incorrect native seconds critical directives are removed in production.
This adds two health RRD fields, with the same 33 plugins and graph identities.
The generic metrics remain collected. Contact scope is explicitly eight NTP
limit graphs plus master transport; global and host defaults are `contacts none`,
and the helper accepts only those graph origins.

The [native correction qualification](../../../homelab-monitoring-observability/Munin/docs/ntp-limits-qualification.md)
passes 28 cases using the real 2.0.73 engine with matched module bytes in the
pinned network-disabled image. Correct boundaries, unknown flags, transition
suppression, per-message pipes and actual candidate inheritance passed. Generic
and unrelated-host/unselected-master graphs invoked no contact. SMTP/status
functions were not called. The guarded reader deployment passed complete
dual-stack probes of all 33 plugins and twelve HTTPS continuity requests.
Fresh-field scheduled collection and serving passed the separate master capture.
Contact activation and exact-message delivery remain separately approved stages.

The separately approved [master maintenance outcome](/home/aaron/code/.local-evidence/homelab-ntp/current/munin-master-maintenance-observation-20261022-v1/outcome.md)
accepted all four maintenance RRDs at 10:28:57 CDT on October 22. Both evidence
fields are 1; both fresh numeric age series agree with the genuine completion
epochs. Each field has six finite 300-second samples. Native scheduled cycles
at 10:10/10:15/10:20 CDT and all ten dual-stack verified HTTPS requests passed,
including both maintenance day PNGs. Protected continuity, empty effective
includes and the four native module hashes passed. Contacts remain disabled.
This receipt is consumed; no replay. No job, parser, update, limits, contact or
service action was invoked. Master maintenance consumption is now accepted
within this bounded capture; corrected alert behavior and delivery remain open.
Retain client coverage, source persistence, sustained four-stream growth/storage
budget and final observation.

Both approved October 22 inspections completed with controller/SSH exit 0 and
unchanged protected continuity. The
[master source outcome](/home/aaron/code/.local-evidence/homelab-ntp/current/munin-canonical-source-20261022-v1/outcome.md)
accepts canonical IPv4 source `10.1.3.83` to `10.1.0.51:4949`: actual sockets,
munin-update ownership, munin-cron/pinned-cron ancestry and native events match
the 09:55 and 10:00 CDT cycles. Transport-plugin sockets were separately
identified. The 360-scan passive capture invoked no collection or probe.

The [producer outcome](/home/aaron/code/.local-evidence/homelab-ntp/current/munin-producer-followup-20261022-v1/outcome.md)
accepts both valid/fresh real rule-specific records at 09:55 CDT: retention
completed October 22 at 00:45:58 CDT and reporting at 05:30:03 CDT. Reporting
matches root cron; retention completion correlates with timer/unit events.
Filtered logrotate events omit verdict labels, so global unit success is not
claimed. The actual protected rule-specific record is independent evidence.
The exact 33-plugin selection passed. Both receipts are consumed; no replay.
No job/message, configuration change or service action was performed.

The approved expanded observations completed with controller/SSH exit 0 and
unchanged protected continuity. The
[node outcome](/home/aaron/code/.local-evidence/homelab-ntp/current/munin-expanded-node-observation-20261021-v1/outcome.md)
accepts the exact 33 enabled links, but both genuine success records remain
absent at 19:13:59 CDT on October 21. The
[master outcome](/home/aaron/code/.local-evidence/homelab-ntp/current/munin-expanded-master-observation-20261021-v1/outcome.md)
accepts genuine expanded cycles at 19:00/19:05/19:10 CDT, all 56 j2 graphs plus
master transport, 280 fresh RRDs with no missing fields and all 120 verified
dual-stack HTTPS responses. df/df_inode each contain six recent fields. Only
the two missing maintenance ages and disabled mail status are unknown.
These are bounded collection/freshness/serving conclusions, not producer,
source-attribution, limits/delivery or final-observation acceptance. The
[observation procedure](/home/aaron/code/homelab-monitoring-observability/Munin/docs/ntp-expanded-observation.md)
retains scope and reset rules.

All three approved v2 generic expansion stages are committed, accepted and
repository-reconciled: master compatibility, node expansion and master
finalization. The node now selects 29 generic package plugins plus four NTP
readers. Both source-bound warm passes covered all 33 in 7.92/8.06 seconds after
the genuine 305-second interval; NTP health and existing HTTPS continuity passed.
Finalization also passed both expanded protocol families before/after. The later expanded observation above separately accepts scheduled cycles and
graph freshness/serving. Contacts remain
disabled; genuine maintenance records, canonical collector source attribution,
limits/transitions, delivered alerts and all other gates stay open.

The [deployment outcome](/home/aaron/code/.local-evidence/homelab-ntp/current/munin-generic-expanded-20261021-v2/outcome.md)
and [procedure](/home/aaron/code/homelab-monitoring-observability/Munin/docs/ntp-generic-deployment.md)
record all three consumed approvals. Compatibility v1's failed single-link
preflight remains historical; v2 verified and preserved its commissioning proof.
No consumed bundle may replay. Preserve NTP/GPS, ordinary plugin/RRD state and
retained historical proofs; no cleanup or alert activation is implied.

The operator confirmed the main-config stanza move was intentional for human
readability; operational directives were unchanged. Preserve that repository
layout. Production retains its accepted byte hash, so byte-for-byte equality
is not claimed. This is a documented presentation difference, not an unexplained
functional defect or a blocker for these observations. Any future live layout
synchronization belongs to a separately reviewed configuration deployment.

Nine final native Munin/systemd update/recovery cases pass, including
real independent timers, worker/controller loss and preservation of foreign
file/link/proof drift. Master source publication needs no daemon restart. The node
stage pins effective unit/drop-ins/startup permit and includes genuine per-source
diskstats seeding, a 305-second interval, warm IPv4/IPv6 protocol and independent
HTTPS acceptance before commit. Guarded recovery is 600 seconds; no consumed
installer/qualification can replay. The
[v2 native qualification outcome](/home/aaron/code/.local-evidence/homelab-ntp/current/munin-generic-qualification-20261021-v2/outcome.md)
is accepted within its native-workload scope: controller/SSH exit 0, complete
334.20-second capture, all 71 pinned files and both service identities unchanged.
All 33 proposed plugins ran; both NFS counter sets are present and no capability
omission is needed. Individual native config/fetch took 13.14 seconds; three
complete concurrent workloads took 15.50/15.33/15.33 seconds after a genuine
305-second wait, within the existing 25-second budget. All generic warm fields
were numeric; the two genuine maintenance-job ages remain unknown.

Diskstats native state/readback passed as munin mode 0600, with 51 numeric
fields for loop0/mmcblk0/zram0 and four overview families. Temperature, CPU
frequency, both interfaces and NFS worked without new root privileges. Wi-Fi
speed metadata remains unavailable as munin; retain traffic/error counters
without root escalation or radio changes. Only ntp_statistics/jobs retain root.
The isolated qualification stage/state remains retained and must not be copied
into production. Both v1/v2 receipts are consumed; no replay.

Expanded settings and exact old-or-expanded/final-expanded transport candidates
are bound in the
[candidate manifest](../../../homelab-monitoring-observability/Munin/node/profiles/ntp/generic-expansion.candidate-manifest.json).
Offline tests reject partial/superset selections and validate native captured
warm frames, including self-referencing interface CDEFs. The
[coordinated deployment draft](../../../homelab-monitoring-observability/Munin/docs/ntp-generic-deployment.md)
defines exact old/expanded master compatibility, node continuation, restoration
baselines and genuine per-source diskstats warm-up before commit. Native target
qualification bypassed systemd-property simulation: production daemon
confinement, source-bound dual-family polling and scheduled expanded RRD/graph
freshness were subsequently accepted through the guarded v2 stages and expanded
observation. Canonical collector source attribution remains a separate gate. The
[comparison and qualification requirements](../../../homelab-monitoring-observability/Munin/docs/ntp-generic-comparison.md)
map 33 reference graph groups to 29 generic package plugin instances (24 additions),
retaining all four NTP readers. The
[candidate](../../../homelab-monitoring-observability/Munin/node/profiles/ntp/generic-parity.candidate.json)
is retained as definition/provenance; the canonical expanded profile is deployed.

Both approved inventories passed October 21 at 16:30 CDT with controller/SSH
exit 0, complete capture and unchanged continuity:
[node outcome](/home/aaron/code/.local-evidence/homelab-ntp/current/munin-generic-node-inventory-20261021-v1/outcome.md)
and [master outcome](/home/aaron/code/.local-evidence/homelab-ntp/current/munin-generic-master-inventory-20261021-v1/outcome.md).
All four verified index requests passed. Both families and native RRD overview
names agree on the 33 reference groups. The 33 unmatched child filenames were
resolved offline to diskstats device-field series; no reference group was dropped.
At that earlier inventory, the target enabled five generic plus four NTP plugins. Those inventories
ran no plugin/sensor commands or installs and made no service change or reference
node connection; the later v2 qualification ran only the isolated native profile.

All proposed package template names exist in the target's core 2.0.76-5 pool.
V2 confirmed installed source/helper hashes, dependencies, NFS and sensor reads,
native identities/output/state and workload runtime. Keep target interfaces and
device discovery rather than copying reference sda, and preserve radio policy.
Guarded update/recovery passed nine native cases and all three v2 stages
committed/reconciled. Final master transport now requires exactly 33 plugins.
The subsequent expanded observation accepts three scheduled cycles, fresh RRDs
and all selected dual-stack graphs. Original installers and these receipts are
consumed; no replay.

Retain the other acceptance gates. Observe genuine retention/reporting completion after the next scheduled
runs: captured retention timer October 22 at 00:45:39 CDT, configured reporter
October 22 at 05:30 CDT. Allow completion time; do not infer success from the
schedule. A later separately approved read-only capture must inspect each real
record and matching provenance. No job invocation or fabricated record.

The earlier initial-selection [node/producer observation](/home/aaron/code/.local-evidence/homelab-ntp/current/munin-node-producer-observation-20261021-v1/outcome.md)
and [master observation](/home/aaron/code/.local-evidence/homelab-ntp/current/munin-master-observation-20261021-v1/outcome.md)
completed October 21 at 16:00 CDT with controller/SSH exit 0, complete captures
and unchanged continuity. Both receipts are consumed; no replay. Both genuine
maintenance records remain absent, with evidence fields 0 and ages unknown.

Native cron/log evidence accepts the three consecutive cycles at 15:45, 15:50
and 15:55 CDT. Both transport fields remain 1; corresponding RRD samples and all
71 last-update timestamps are current. All 40 verified HTTPS checks passed,
including the 16 j2 day graphs and master transport graph over both families.
Sampled NTP health/timing, storage floors and active statistics ages pass; this
is bounded collection/serving acceptance, not longer observation. Maintenance-age
plots have no successful-job values; master mail remains unknown.

Also prepare scoped qualification of actual canonical TCP source attribution
and native limits/contact transitions, then exact-message delivery reviews.
This earlier observation did not activate contacts; see the current checkpoint.
Client refresh/coverage, OBS-02 sustained growth and
budget, persistence, final observation and later mandatory separate-host ntpviz
remain open. The [observation procedure](../../../homelab-monitoring-observability/Munin/docs/ntp-observation.md)
retains evidence/reset rules; a complete capture alone is not overall readiness.

The approved [master commissioning outcome](/home/aaron/code/.local-evidence/homelab-ntp/current/munin-master-commissioning-20261021-v1/outcome.md)
passed October 21 at 15:34:46 CDT. Controller and apply/commit SSH stages exited
0; prepared then committed, recovery timer disarmed, no recovery errors.
Installed CLI and served config/fetch accepted IPv4=1/IPv6=1/mail=U. Only the
master config, transport plugin/settings/link and private operation state were
authored. Munin-node restarted and verified native CGI workers refreshed;
protected Apache/cron/network/package checks passed. All six verified HTTPS
HTML/CSS/existing-PNG requests passed before and after over .83 and ::83.
Existing-graph continuity does not accept new j2 freshness.

The stale cache directive is removed; native direct-RRD defaults are active.
The exact accepted config was privately scanned and atomically synchronized to
the canonical repository mirror at SHA-256
`eefe2d3f0cfa59f65ee76b06e53e8e4ef911e9f6fa169ff8f6140d9e61c11851`.
Receipt consumed; no replay. The [lifecycle](../../../homelab-monitoring-observability/Munin/master/configuration-lifecycle.md)
requires matching readback after later changes/restoration. No new contacts,
messages, packages, schedules, NTP-node configuration, network or DNS changes.
Keep genuine scheduled records, polling/fresh graphs/delivery, OBS-02/OBS-07
and all longer readiness gates open; missing records remain faults.

The approved [classifier correction/start outcome](/home/aaron/code/.local-evidence/homelab-ntp/current/munin-node-correction-start-20261021-v1/outcome.md)
passed October 21 at 13:04:08 CDT: controller/SSH exit 0, node-resumed accepted,
all nine installed paths before/after startup, exact literal listeners and
independent IPv4/IPv6 TCP checks. Munin-node is enabled/running; NTP continuity
and protected-file/package checks passed. Only the classifier changed; no
package reinstall, job, synthetic record, master activation or message.
The execution receipt is consumed; no replay. Master polling/graphs/delivery
and ongoing readiness gates below remain open.

The [approved read-only selection inspection](/home/aaron/code/.local-evidence/homelab-ntp/current/munin-ntp-selection-20261021-v1/outcome.md)
confirmed the defect: selected association 54497 is *SHM(2), refid PPS and
srcadr 127.127.28.2, matching the accepted unit-2 configuration. Selection was
stable; system leap=00/stratum=1, selected reach=377 and flash=00 ok. The old
classifier required o, producing a false negative. The local fix recognizes
this selected SHM source and retains native PPS support, with negative-identity
coverage and replay of actual output. This sample does not close longer timing,
physical PPS or monitoring acceptance.

During that earlier selection inspection, hashes and time-service identity
matched; Munin stayed disabled/inactive with no listener/permit. The [original node stage](/home/aaron/code/.local-evidence/homelab-ntp/current/munin-node-install-20261021-v3/outcome.md)
and its inspection remain consumed. The continuation has separate state and
backs up only the classifier; its permit proof supports ownership-safe recovery.
It checks the exact 15 installed node package versions and records current full
inventory, without reusing the obsolete 701-package pre-install pin.

The [producer stage](/home/aaron/code/.local-evidence/homelab-ntp/current/munin-producers-20261021-v3/outcome.md)
passed installation at 12:02:25 CDT. Helper and real completion hooks are installed;
no job or notification ran, and no success timestamp was fabricated. Accept each
actual scheduled retention/reporting completion independently later. Producer
installation remains accepted after node containment. The old 701-package
pre-install pin is historical; do not reuse it for a new installation.

The [native master design](../../../homelab-monitoring-observability/Munin/master/ntp-design.md)
now selects one canonical IPv4 series and a master-local plugin that fully fetches
all nine plugins over both source-bound families during the existing five-minute
schedule. Limits, unknown-data handling, fixed Mailrise contacts and recovery are
defined. Native parser/merge/activation commissioning is accepted as recorded
above. Scheduled observations and separately previewed sends retain their own gates.
Actual scheduled producer records, master collection/graphs, delivery, OBS-02/
OBS-07, longer final observation and later mandatory separate-host ntpviz remain
open. No local test substitutes for these observations.

Both approved v2 read-only captures completed once with exit 0 and exact
continuity pins: [node/producer](/home/aaron/code/.local-evidence/homelab-ntp/current/munin-node-producer-readiness-20261021-v2/outcome.md) at 10:51:48 CDT and
[native master](/home/aaron/code/.local-evidence/homelab-ntp/current/munin-native-master-readiness-20261021-v2/outcome.md) at 10:51:32 CDT on October 21.
Readiness receipts are consumed. The separately approved producer/node execution
and containment inspection above supersede the original pre-install sample.

The pre-install readiness sample recorded 701 package records, ARM64, no Munin
account/unit/listener/config or policy-rc.d. Cached simulation matches all 15
reviewed package versions with zero upgrades/removals; protected NTP config,
retention rule and reporter match repository sources. Both success records are
absent in that sample. Cron is 05:30 America/Chicago; enabled/waiting logrotate timer metadata
does not prove rule-specific success. One storage sample passes the 10 GiB and
5 percent inode floors. Node/master route lookups select .51/::51 and .83/::83.

The native master remains Munin 2.0.73-1 with no j2 registration or active contacts
in inspected configuration. Five-minute cron and bounded recent limits/update
activity are present; no sampled ERROR/FATAL marker. Apache's vhost matches the
accepted ACL bytes. Installed INET6/MultiHomed/address excerpts do not establish
scheduled polling over both required families. Client DNS/CGI/HTTPS/polling were
excluded; no new graph/client/delivery acceptance is claimed. Keep missing job
records faulted until real producer completion. OBS-02/OBS-07 and remaining
client/graph/persistence/ntpviz obligations stay open. Failed v1 evidence remains
preserved and consumed; its bootstrap correction is locally regression-tested.

The [Munin/svmf DNS outcome](/home/aaron/code/.local-evidence/homelab-dns/current/munin-svmf-dns-deployment-20261021-v1/outcome.md)
records all five phases passing October 21 at 10:12:30 CDT under archive
`81d6544c533baa2592c9e63c093f2be2f403400309ffc244fb0561840a827e30`. Both names now have AAAA
::83 with one canonical IPv6 PTR to svmf. Exact node/loopback/VIP DNS answers,
preserved NTP/local records, public DNS and paired Caddy HTTPS passed; all four
linked VIPs were on .53 in retained samples. Both full DNS restarts passed on
each node. Receipts are consumed; backups remain. No rollback, extra live probe
or notification test occurred.

Static .83/::83 networking committed at 09:58:00 CDT; independent literal SSH
and verified Munin HTML/CSS/sample PNG passed both families after commit.
Client cache/FQDN SSH refresh, all-client coverage, graph freshness, intended-
family scheduled polling, delivered problem/recovery alerts and physical
reboot/renewal persistence remain open. Preserve OBS-02/OBS-07 and mandatory
later separate-host ntpviz.

The [DNS deployment outcome](../../../homelab-dns/Unbound/docs/ntp1-ipv6-prerequisite-review.md#deployment-accepted--october-21-2026)
records .54-first/.53-second atomic writes, full Unbound/Pi-hole restarts and
passed paired gates. All four linked DNS/Proxy VIPs were on .53 in retained
samples; Caddy service and verified HTTPS 204 passed over both proxy VIP families.
No forced failover or downtime-duration claim is made. Private backups and
receipts remain; execution phases are consumed. No Caddy/Keepalived configuration
or synchronization change, extra fixture or test notification occurred.

The operator confirms no Unbound local-zone synchronization is implemented;
Caddy replication is separate. Broad sync/config/crontab and reload-path
qualification are no longer prerequisites for this record update. Prior captures
remain historical evidence, not proof of zone replication. Both v2 captures
completed without target mutation and are consumed; do not replay them.

Update one node at a time, current non-VIP owner first, while the peer is healthy
and serving. Cluster-driven failover during restarts is permitted. Require
coherent ownership of all four linked DNS/Proxy VIPs, a healthy pair and exact node/VIP answers under
the reviewed convergence window before progressing. Do not force failover or
change Keepalived/Caddy. The successor now replaces pinned-role acceptance with paired coherent HA gates,
retains durable backups/state and performs both required full restarts. Live
preflight stopped on no input drift; the approved DNS review has now executed
and passed. Future network preflight must independently enforce its own inputs.

All three approved readiness inspections executed once with complete captures,
controller exit 0 and no target mutation. Their receipts are consumed.
The three private reviews are under `.local-evidence/` at the workspace root:

| Target stage | Review directory | Archive SHA-256 |
| --- | --- | --- |
| NTP IPv4/native-IPv6 identity and address | `homelab-ntp/current/ntp1-address-readiness-20261020-v1` | `bd139b4d64ace97d4c73cb0e1f509e76d5d7c3c3d0a15081b2b9a8e6f95ec24e` |
| DNS .53 baseline and candidate validation | `homelab-dns/current/ntp1-dns53-readiness-20261020-v1` | `b4ee8a69eb5879dd3fe1de84956b52fea25e36fdd87dfab32cfdef9e1cf51ce6` |
| DNS .54 baseline and candidate validation | `homelab-dns/current/ntp1-dns54-readiness-20261020-v1` | `53420d803c3b48a518a1e8f02c0d224a5434a124ab046b0e87167bc95e4cbdd2` |

NTP address publication readiness passed through authenticated literal IPv4
and native IPv6 SSH, stable boot/time-service identity, a saved fixed ::51 ULA
and intended route sources. This does not close overall time/production acceptance.
The local NTP configuration mirror now matches the current captured live hash;
its missing protostats settings were restored from matching retained bytes,
without changing the target.

Both DNS nodes' installed Unbound 1.17.1 validated the original configuration
and the in-memory candidate containing only the two NTP additions. Both VIPs
remained on .53; .54 owned neither. All 24 queries per node completed:
A and IPv4 PTR were correct, AAAA returned NOERROR/zero answers and IPv6 PTR
returned NXDOMAIN/zero answers. Query success does not mean record presence.

The NTP-only DNS deployment executed and passed on both nodes. Broader Phase 5
DNS/SRV work and pending Munin/svmf records remain separate. The guide and repository policy now require both full restarts;
the operator's clarification supersedes the earlier sync/reload-path follow-up.

The repository candidate adds only ntp1 AAAA ::51 and its canonical IPv6 PTR;
both remain pending. Do not copy the whole source file containing pending
Munin/svmf records into this NTP-only stage. No consumed readiness approval
permits another target capture, DNS changes, reloads, restarts or network activation.

The network wrapper now seals `ntp1.local.theama.co`, requires the exact native
.51/::51 endpoints, rejects mapped IPv4 as IPv6 proof and labels lookup failures
by family/status/bounds or timeout. Twenty-one offline wrapper contracts and all
seven native systemd/SSH/NetworkManager 1.42.4 cases passed with unchanged current
candidate bytes. The five recovery paths retained exact backups and independent
original-family SSH/HTTPS proof; incomplete and held durable states were not
accepted. The added missing-AAAA case reproduced successful ahostsv6 mapped
fallback and failed before checkpoint, backup or profile write. Fifteen DNS
repository tests passed; both DNS nodes subsequently passed native validation above.

Qualification is retained under
`.local-evidence/homelab-network/current/svmf-resolver-wrapper-qualification-20261020-v1/`
at the workspace root. No production contact occurred during this preparation or
requalification. No new network deployment is sealed. First accept separately
approved NTP DNS prerequisites, then refresh baseline requirements and prepare a
successor network deployment. Munin/svmf DNS remains a later change requiring
accepted static host networking. Existing monitoring/maintenance obligations stay
open in OBS-02/OBS-07.

Approved `svmf-resolver-diagnostic-20261020-v1` executed once, archive SHA-256
`12b1bb0a770ab96b541049550b7fe7feaaa8c121713c053cdf6aa2bd9ce34b0a`.
Capture completed without target mutation. Both DNS VIPs returned the expected A
10.1.0.51 and NOERROR/zero-answer AAAA for ntp1. Named ahostsv4 returned .51;
ahostsv6 exited 0 but supplied only mapped IPv4 `::ffff:10.1.0.51`, not native
::51. Nonempty ahostsv6 output is insufficient acceptance. NSS/resolver files
and NetworkManager identity remained stable; both configured DNS VIPs responded.
These VIP queries do not inspect each physical DNS node or prove a full zone.
The diagnostic receipt is consumed; private outcomes and transport data remain.

The operator confirms ntp2 does not exist. The production sealer incorrectly
pinned that fixture name instead of the plan's ntp1. Current VIP evidence now
confirms the missing native AAAA prerequisite for the intended name. Do not
create ntp2 or weaken dual-stack requirements. NTP DNS is a prerequisite to the
network successor; Munin/svmf AAAA/PTR publication remains a separate later change
requiring accepted static host networking. All deployment holds remain in force.

Approved `svmf-preflight-diagnostic-20261020-v1` executed once, archive SHA-256
`de3a3f8cf44801ca8dbe43a30b6ec05308fb246d16498a26849b36810889637e`.
Capture completed without target mutation. Retained v2 state identifies
`RuntimeError: bounded command failed: getent` in preflight. The generic label
covers nonzero exit or output-limit failure, and does not identify the address
family. A DNS outage or specific resolver defect is not established. Profile
content and all pinned metadata still match the baseline; NetworkManager identity
was stable during capture. The worker's service exit status was successful,
but its durable transaction failed; it is not deployment acceptance. Both
operation receipts are consumed. The subsequent approved resolver capture is
recorded above; the historical wrong-name failure family/status remains unknown.

The approved archive SHA-256
`20e8297328c270b3c623076479ae6feb35f5f855bfc3e49e44c531f99fb8de83`
executed once and returned `preflight_failed` (controller exit 2). All six
original-family HTTPS baseline responses passed; pinned SSH staging succeeded.
The worker stopped before checkpoint arming or network-settings mutation. Remote
staging and transient-unit execution occurred. The returned status omits the
failed predicate. The later diagnostic identified the getent failure above;
its underlying cause remains unknown. No rollback was invoked.
Preserve private receipts, transport logs and target staging. Both v1 and v2 are
consumed and cannot replay. The review's interruption-only inspection allowance
is not treated as authorization for this terminal-failure diagnostic.

Seventeen offline contracts and six native fixture scenarios remain qualification,
not production acceptance. Actual target preflight, DAD, routing, resolver/apps
and fixed-family SSH/HTTPS acceptance remain mandatory. IPAM stays desired/pending;
DNS publication and NTP monitoring remain held on accepted host networking.

Approved `svmf-apache-acl-20261020-v1` executed once under archive SHA-256
`23aafda870c8cf1dc9863c48c5402ed8aa8306a06838c5d081f40760e0800941`.
It committed the four LAN ULA /64 additions after native full configuration
testing and graceful reload. Final independent checks returned verified HTTPS
200 with expected HTML/CSS/PNG types and PNG signature over both original literal
families. The accepted target hash is
`555551c423e879d6b0ea5706807f5bb7a02c6238293e7509527ecf6d2004091f`;
root:root 0644 metadata and Apache parent/service identity were preserved.
The private original backup/state are retained. Restoration was not needed.
The independent guard's later no-op has not been observed; a committed state
prevents it from restoring. The execution receipt is consumed.

The Apache-owned [review](../../../homelab-monitoring-observability/Apache2/docs/munin-ipv6-access-review.md)
and [runbook](../../../homelab-monitoring-observability/Apache2/docs/acl-deployment.md)
retain eight offline/eight native transaction cases, actual syntax rejection and
recovery limits. Live sampled access is accepted on the current IPv4/generated
ULA, not the future static ULA or DNS AAAA records. Graph freshness, every-client
coverage and scheduled monitoring remain open in OBS-02/OBS-07.

Before that change, approved `svmf-apache-qualification-20261020-v1` ran once, archive SHA-256
`87ba990d3cdbc21321f8aabfec18ea0e5549eaf985af7c4a81318ae0cc1f8ed2`.
One pinned SSH capture completed; Apache owns the inspected TCP 80/443 listeners,
and its service identity stayed unchanged. Twelve HTTPS GETs used the original
literal destinations with dashboard SNI/hostname/Host identity. TLSv1.3 and
certificate verification passed over both families. The presented wildcard
certificate expires January 19, 2027 at 23:59:59 UTC.

Root and three discovered HTML pages returned 200 on both families. `/munin/`
returned 403 on both; `/static/style-new.css` returned IPv4 200 and IPv6 403.
No daily graph link was discovered within the approved three-page traversal,
so no graph request occurred and graph/freshness acceptance remains open.
Do not infer universal IPv6 denial: the root and sampled HTML worked over IPv6.
No configuration change, restart, private-key retrieval or notification occurred;
normal request logging and CGI caches may have been written. This receipt and
both earlier operation receipts are consumed; do not replay them.

The subsequent approved `svmf-graph-qualification-20261020-v1`, archive SHA-256
`f183d89b85872fe132a921043a7870731c1044cf1948bc5278fae9b4a246dbd8`,
made eight verified HTTPS GETs, four per original family. Domain and node HTML
returned 200 on both. `/static/style-new.css` and the discovered daily graph
`/munin-cgi/munin-cgi-graph/J1-SVMF/J1-SVMF/apache_accesses-day.png` returned
IPv4 200 and IPv6 403. The IPv4 response was `image/png` with a valid PNG
signature. TLS validation passed on all requests. No configuration or service
change occurred; normal request logging/CGI cache writes remain possible.

The operator identifies Apache as the dashboard server and moved the supplied
configuration into the [repository vhost](../../../homelab-monitoring-observability/Apache2/configs/001-munin.theama.co-ssl.conf).
At capture its bytes matched the sealed candidate and enabled vhost on disk.
The repository now contains the four ULA ACL additions accepted by the deployment.
Its `ServerName` is
`munin.local.theama.co`; its port-80 vhost explicitly redirects to HTTPS, matching
the diagnostic. The captured `Require ip` rules listed RFC1918 IPv4 ranges and
`::1`, with no ULA client range. The observed IPv6 stylesheet denial is consistent
with that gap; exact authorization merging was not traced. Parsed disk files do
not prove which bytes the running daemon loaded. Keep private-key contents out
of inspection and preserve verified TLS in all successor checks.

The HTTPS successor wrapper is locally requalified: 17 offline contracts and six
real SSH/systemd/NetworkManager 1.42.4 fixture scenarios passed with its sealed
deployment/helper/settings bytes. Five recovery paths have independent original-
family SSH and three-asset HTTPS readbacks; interrupted/held states were not
silently accepted. Worker loss retained `awaiting_confirmation`, interruption
after write retained `write_intent`, and failed health/foreign drift retained
`recovery_held` despite independently restored networking. This is
Debian 12 amd64 local qualification, not live ARM64 or console acceptance.
The [execution review](../../../homelab-network/Ubiquiti/svmf-static-network-review.md#qualified-guard-and-production-execution-gates)
and [runbook](../../../homelab-network/Ubiquiti/svmf-network-deployment.md) preserve
exact pins, durable backup/state, detached supervision, independent dual-stack SSH,
actual resolver/application gates and converged recovery. Current live acceptance
is still open. Console access is available but restoration is unexercised; retain
the later approved renewal/reboot comparison in OBS-07.

Controller data confirms the existing IPv4 reservation and reports no conflict
in selected fields across 61 configured and 43 active client records. Neither
collection exposed selected IPv6 fields, and the matching network exposed none
of the selected IPv6-prefix fields. This does not prove ::83 is unused or that
IPv6 is absent. Require future authorized DAD and guarded acceptance; do not
broaden inspection scope or silently waive this visibility limit.

Inventory represents svmf as the shared native Munin master and Podman Apprise
API/Mailrise host; placeholders are removed. The earlier network-readiness capture
establishes live gateway/DNS and the persistent automatic profile. No backup,
checkpoint or activation occurred. The partial firewall projection, affected
consumers, dashboard/container health and dual-stack access still need evidence.
Accept the separately reviewed network change and dual-stack DNS before Munin.

The operator now requires host-static
`10.1.3.83/22` and `fd36:5aa8:6971:1::83/64`; the earlier automatic-address
preservation decision is superseded. The [IPAM allocation](../../../homelab-network/ipam/README.md)
and [network review](../../../homelab-network/Ubiquiti/svmf-static-network-review.md)
record the finalized desired settings; live acceptance is still pending. Retained
RA/global routing is explicit, with no pinned link-local gateway.

The inventory now explicitly selects `ntp` for `j2-svntp1`. Separate prepared
reviews cover [node installation](../../../homelab-monitoring-observability/Munin/docs/ntp-node-installation-review.md),
[job-success recording](monitoring-job-success-review.md) and
[master/dashboard acceptance](../../../homelab-monitoring-observability/Munin/docs/ntp-master-acceptance-review.md).
These are held definitions, not sealed executable bundles. The dashboard must
respond over both address families; node TCP 4949 listeners, master source
identities and scheduled polling also require explicit dual-stack acceptance.
The DNS source adds both AAAA records and the canonical IPv6 PTR; deployment
requires the [DNS owner review](../../../homelab-dns/Unbound/docs/munin-host-record-review.md).
The definitions themselves made no contact; the separately approved readiness
inspection has now completed.

The approved `munin-master-profile-save-20261020-v1` passed earlier with unchanged
UUID, effective settings, route sources and NetworkManager identity. It saved the
then-automatic profile, not the newly selected static addresses. Its accepted
result remains historical evidence; do not replay it or treat it as static-address
acceptance. Future maintenance observation must compare the accepted static
profile after migration. The existing IPv4 reservation is verified.

`munin-master-identity-20261020-v2` and network-owned
`munin-reservation-inspection-20261020-v1` both executed once at 11:14 CDT on
October 20 with complete captures and no persistent mutation. The controller
confirmed use_fixedip=true and fixed_ip=10.1.3.83 for the matching master MAC.
Both bundles are consumed; do not replay them. Master-identity v1 was superseded
without execution.

The last captured master profile uses automatic IPv4/IPv6 addressing with no explicit
addresses. No temporary flag appeared. The follow-up found addr-gen-mode=default,
no effective generation/stable-id override, unset stable-id, use_tempaddr=0, and
root-owned regular secret_key/machine-id files inspected only for metadata.
Installed 1.42.4 documentation now supports the stable-privacy default tied to
profile and host identity. The subsequent accepted save establishes saved-policy
persistence; renewal/reboot behavior has not been exercised. Preserve that
distinction; the new static-address design still needs its own sealed execution
approval and live acceptance. No active
contacts or j2 registration appear in captured master
configuration. The operator assigned alert evaluation/delivery to the master,
Aaron as operator, problems to `notify.failure@mailrise.xyz` and recovery/status
to `notify@mailrise.xyz`. Contact configuration and delivery still need acceptance;
each delivery test requires exact-message approval.

The [package/plugin qualification](../../../homelab-monitoring-observability/Munin/docs/ntp-package-qualification.md)
records 15 verified cached archives, six syntax checks and 16 isolated plugin runs.
The earlier five package-control scenarios passed. The reusable production
installer payload now also passed eleven isolated scenarios, including real
dual-stack startup/protocol, all nine selected plugin config/fetches,
unprivileged query identity, root-private record access, staged failures, foreign
state preservation, pre-activation drift and resumed/held CLI recovery. These
qualify the actual payload in an amd64 environment using Architecture-all Munin
archives, not ARM64 dependencies or live target acceptance. The selected
metric/privilege candidate is locally qualified and selected in inventory; no
approved installation bundle exists yet. OBS-02/OBS-07 remain open for sustained growth/storage, alerts,
empirical source persistence and intended-family polling. OBS-01/OBS-03 retain
their rule-specific schedule/reporter evidence gaps. Required ntpviz remains Phase 3B.

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
| Mail and needrestart | Transport/manual deliveries and daily cron activation accepted; October 22 genuine reporting record and fresh master evidence/age consumption accepted | Cron-generated failure-mail delivery remains open; recurring reporting must remain observed |
| Statistics retention | Four-stream rule/private trigger, genuine rule-specific success and master evidence/age consumption accepted; 48-hour growth contract selected October 22 | Execute separately reviewed t0/+6h/+24h/+48h snapshots, account for gross growth and reserve capacity, and map storage/failure alert evidence. Global logrotate-unit verdict remains unaccepted; plotting is Phase 3B |
| Munin | Expanded profile/graphs, genuine producers, corrected timing readers, canonical source attribution, committed contacts, exact delivered tests and bounded native mail recovery accepted October 22 | Preserve accepted collection; complete the [coverage/persistence matrix](PRODUCTION-OBSERVATION-CONTRACT.md#coverage-and-persistence-reconciliation) and agree the final observation contract. No consumed stage may be replayed |
| Hardware watchdog | Userspace watchdog package absent from the post-reboot inventory. Deployment recovery timers are different mechanisms | Inspect device/driver ownership and configuration; approve installation/enablement and controlled failure/recovery test separately |
| Network persistence | Earlier network acceptance established fixed addresses, RA, DNS and egress. Latest boot passed both fixed SSH endpoints and client families | Reconcile current-boot RA global address/default route, resolver views and DHCP/RA DNS suppression; endpoint reachability alone does not prove these properties |
| PoE, fan and thermal health | Earlier operator observations establish normal fan/power and original PoE HAT; boot success does not establish sustained health | Current power budget/class, fan/control, temperature, undervoltage/throttling and sustained-operation evidence; no stress or switch changes implicit |
| OS/media/access | Trixie identity and accepted boot/kernel continuity are recorded; original recovery card retained | Close the complete per-node baseline, current update status and final observed inventory. Wi-Fi disablement remains unproven in HISTORY, not silently accepted |
| Final observation and inventory | Short timing/monitoring observations accepted; OBS-02 window selected but not started. Final Phase 3 duration/cadence/tolerances remain pending | Resolve baseline gate dispositions and the [final-window decisions](PRODUCTION-OBSERVATION-CONTRACT.md#final-phase-3-window-inputs-still-required), then begin after relevant changes and complete observed inventory |

The October 20 Munin-absence inspection is historical and superseded by the
accepted deployment/observations above. Watchdog absence comes from the retained post-reboot RTC inventory,
not the original Debian 11 baseline; no new watchdog query was made.
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
| OBS-01 | Initial genuine retention completion/provenance and master evidence/age consumption accepted October 22; four-stream monitoring remains active | Preserve recurring retention evidence and failure visibility; continued statistics/storage observation remains OBS-02 | Actual rule-specific success and collected monitoring evidence accepted within bounded captures; continuing operation is not inferred |
| OBS-02 | Open: t0 node/master v2 accepted at October 22, 16:08:28 CDT; +6h/+24h/+48h remain due | Separate due-time read-only reviews; measure per-inode gross growth and reclamation, then assess 31-day budget with 2x headroom and active allowance | [Contract](PRODUCTION-OBSERVATION-CONTRACT.md); accepted t0 outcomes above |
| OBS-03 | Initial genuine reporter completion/cron correlation and master evidence/age consumption accepted October 22 | Preserve recurring reporter evidence, quiet success, locks and failure-mail handling; delivered failure mail remains OBS-04 | Actual producer completion and collected monitoring evidence accepted within bounded captures; recurrence/delivery remain separate |
| OBS-04 | Synthetic failure route delivered; cron-generated failure mail unobserved | Prepare a separate controlled failure-path review with exact recipient/content approval | Cron-originated test evidence and operator-confirmed downstream receipt; do not resend existing tests implicitly |
| OBS-05 | Corrected timer accepted; four-week live recurrence unobserved | Retained estimate: November 12, 2026, 18:19:41 CST; refresh live schedule under approved scope before relying on it | Actual scheduled result, valid leapfile and subsequent trigger. Estimate is not a fresh timer observation; reconcile any phase-gate deferral explicitly |
| OBS-06 | Isolated boot-trigger tests passed; physical Pi boot-trigger behavior after correction unobserved | Next separately approved reboot; observe the 15-minute initial trigger plus allowed jitter | Host reboot/maintenance result and next recurrence schedule; preserve shared-antenna power and recovery controls |
| OBS-07 | Expanded collection/graphs, source attribution, corrected timing/maintenance, contacts and bounded native mail recovery accepted October 22 | Use the [coverage/persistence matrix](PRODUCTION-OBSERVATION-CONTRACT.md#coverage-and-persistence-reconciliation); preserve the explicit source policy and compare after the next separately approved master maintenance event | Current-boot node network policy, representative clients/access, source persistence or approved disposition, and sustained operation remain separate from accepted short captures |
| OBS-08 | Boot and earlier operator fan/power observations retained; sustained health not accepted | Agree duration/load and collect during final host observation | Fan/thermal/PoE/undervoltage evidence; watchdog controlled failure/recovery remains a separately approved baseline gate |
| OBS-09 | Final Phase 3 interval, cadence, tolerances and reset rules remain pending; selected OBS-02 48-hour baseline is a different window | Resolve prerequisite gates and the [final-window contract inputs](PRODUCTION-OBSERVATION-CONTRACT.md#final-phase-3-window-inputs-still-required), then agree start after the last relevant change | Reviewed time/client/network/hardware health across the full agreed interval, evidence-gap/reset dispositions, final inventory and recurring owner/cadence; Phase 8 remains later |
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
  nodes/VIPs remain separate. The accepted October 21 change establishes standby A/AAAA and IPv4/IPv6 PTR
  answers through both nodes/VIPs. The remaining primary and SRV requirements
  are still separate; this scoped acceptance does not close all Phase 5 DNS. mDNS acceptance does not
  substitute for these records.
- **Phases 6–8:** finish UniFi DHCP/allow/deny/DNAT policy and traffic tests,
  both-node inventory, remaining end-to-end acceptance and final observation.
  Do not bring all later rollout work into the next leap-maintenance stage.

No installation, timer activation, mail delivery, poller probe, watchdog test,
power interruption, DNS change or primary-node operation is authorized by this
review. Each live stage requires its scoped, sealed execution approval.
