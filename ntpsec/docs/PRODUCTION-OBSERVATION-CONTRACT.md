# j2-svntp1 growth budget and remaining observation contract

Recorded October 22, 2026. Aaron selected the OBS-02 sampling window and budget
below. This document defines measurements and evidence; it starts no observation
and authorizes no target access. The [governing plan](ntp-architecture-deployment-plan-v1.0.md#statistics-30-day-retention-and-ntpviz)
owns policy; [readiness](PRODUCTION-READINESS.md#decision-and-next-action) owns
current disposition. Earlier consumed operations must not be replayed.

## Selected OBS-02 contract

Observe j2-svntp1's four streams: `loopstats`, `peerstats`, `clockstats` and
`protostats`. Aaron owns the review and acceptance. Existing collection,
retention, reporting and Munin schedules continue unchanged.

| Checkpoint | Intended offset from t0 | Purpose |
| --- | --- | --- |
| Baseline | 0 | Bind current boot, writer/configuration, filesystem, file identities and native monitoring evidence |
| Early sample | +6 hours | Detect short-interval growth, unexpected files and capacity changes |
| First daily sample | +24 hours | Account for rollover, genuine maintenance and first daily growth |
| Closing sample | +48 hours | Compare the second day, calculate the budget and reconcile monitoring evidence |

`t0` is unset until an approved baseline completes. Record actual UTC and local
timestamps and elapsed seconds at every checkpoint; do not substitute intended
times. No lateness tolerance has been agreed: record a late/missed checkpoint
and assess its coverage explicitly. Calendar dates and automatic reminders are
not assigned by this contract. This 48-hour baseline is not the final Phase 3
observation interval.

Prepare separate one-use node and master read-only reviews for each checkpoint.
Existing observation archives expire within 24 hours; prepare fresh reviews when
due rather than extending an archive, replaying a receipt or claiming one approval
covers 48 hours. Define each executable scope before approval. No new timer,
background collector, forced job, synthetic fault, restart or notification is
part of sampling.

## Snapshot and growth accounting

Each node snapshot must bind boot/service identities and accepted NTP, filegen,
retention and reporting inputs. Record the actual statistics mount/device,
available bytes, total/free available inodes and filesystem accounting units.
Record the four base-file targets, writer/open-descriptor identity and bounded
depth-one file metadata: stream/name, device/inode, size, allocated blocks,
mtime, link count and active/completed/compressed classification. Keep raw
evidence private. Do not traverse unrelated paths, follow unreviewed links or
rename, truncate, compress or remove statistics.

Count a unique inode once even when a base name and dated name are hardlinks.
Across each pair of snapshots, sum positive increments for continuing files
and sizes of new files separately for each stream. Report removed completed
files separately: retention reclamation must not turn gross growth negative.
Track logical and allocated growth independently; use the more conservative
measured rate for byte budgeting. Record generated inode counts separately from
net inode consumption.

Unexplained shrinkage, inode reuse/replacement, missing active files, changed
writers/configuration or files created and removed between snapshots prevent
a complete gross-growth claim. Label lower bounds and gaps; do not silently
replace them with zero. Correlate ordinary daily rollover and cleanup with
genuine rule-specific evidence. Quiet event-driven `protostats` may legitimately
stay unchanged; it neither fails merely for zero growth nor establishes a
representative event-burst rate. Do not induce events to fill the gap.

At the corresponding master checkpoints retain existing native collections,
fresh storage/statistics/job metrics, RRD/graph identity and existing limits
evidence. Bound the time window and distinguish current raw state from
consolidated RRD values. Observe successful recurring retention/reporting records
and their collected ages; timer activation alone is insufficient. Capture
only the required data; invoke no plugin, update, limits evaluator or contact.

## Budget calculation and acceptance

Use actual elapsed time. For each fully accounted interval, normalize gross
growth to a 24-hour rate. Let `R` be the highest measured aggregate daily-equivalent
byte rate and `I` the highest measured daily-equivalent new-inode rate. Identify
short-interval extrapolations explicitly; they are not measured complete days.
Let `A` and `A_i` be the largest observed active-file byte and unique-inode
allowances. Aaron selected:

- Statistics byte budget: `B = 31 × (2 × R) + A`.
- Statistics inode budget: `B_i = ceil(31 × (2 × I)) + A_i`.
- Preserve at least 31 days of uncompressed statistics. The 2× multiplier is
  growth headroom, not permission to shorten retention.
- Retain the deployed minimum-free-byte floor of 10 GiB and minimum-free-inode
  floor of 5%. These values do not authorize a plugin or threshold change.

For capacity, subtract only additional required statistics capacity from current
available space: `max(0, B − current statistics allocation)`. Give no speculative
credit for future cleanup. Reserve explicit capacity for other filesystem
consumers and metadata before comparing projected availability with the floors.
Apply the same approach to available inodes. If other growth/reserves are unknown,
report the statistics-only result as conditional; do not claim the whole volume
is budgeted by assuming other use is zero.

Accept OBS-02 only when all four streams are accounted for, the window is
representative or its limitations have an explicit disposition, the projected
byte/inode budgets preserve both floors, and real master collection/limits
evidence shows the ongoing storage policy. Record each stream's rate, assumptions,
remaining headroom and expected retention behavior. The controlled health/mail
tests prove those routes, not a storage-floor fault or cron-originated failure.
Any remaining failure/space-notification requirement needs an explicit mapping
to existing qualified limits evidence or a separately reviewed test/disposition;
never fill a disk or resend a message to manufacture acceptance.

## Coverage and persistence reconciliation

| Surface | Accepted evidence | Remaining acceptance |
| --- | --- | --- |
| Generic/NTP metrics | 29 generic plugins plus four NTP readers; expanded scheduled RRDs and dual-stack graphs accepted | Preserve the explicit device/interface mapping and capability dispositions; compare any changed inventory with the accepted selection |
| Native source identity | October 22 socket/UID/process/cron attribution accepted for the canonical IPv4 updater | Do not substitute transport-probe sockets for the updater; compare policy and both-family collection after the next separately approved master network-maintenance event |
| Address-family coverage | Canonical IPv4 series, source-bound dual-family transport checks and sampled dual-stack dashboard access accepted | Saved-profile/static-address evidence does not prove renewal/reboot behavior; retain the master persistence obligation with an owner and next maintenance checkpoint |
| Node networking | Prior fixed endpoints and post-boot client-family checks accepted | Reconcile current-boot RA global address/default route, resolver views and DHCP/RA DNS suppression; master persistence cannot prove node persistence |
| Clients/access | Controlled IPv4/IPv6 NTP responses, query denial and native Windows discovery accepted in earlier captures | Build the expected client/VLAN/family and management-access matrix from inventory; identify representative tested clients, gaps and explicit dispositions rather than claiming every client was covered |
| Alerts and jobs | Genuine producers, corrected timing limits, committed contacts, both exact delivered tests and bounded native mail recovery accepted | Retain cron-originated failure-mail gate OBS-04, storage-specific acceptance and continuing job-health checks; Pushover connection cause remains unproven |

The current baseline is evidence from named captures, not a new live inventory.
Do not infer persistence from a saved profile, a quiet interval, a successful
endpoint or another host's reboot. A maintenance/reboot/power test needs its own
recovery review and approval. An open persistence obligation must be observed
or have an explicit operator-approved phase disposition with owner/checkpoint.

## Final Phase 3 window: inputs still required

Do not start or backdate OBS-09 from the mail capture or this growth baseline.
The governing plan requires the remaining Phase 3 baseline gates before its
extended observation. Reconcile watchdog device/ownership/enablement and its
controlled recovery test, current network policy, hardware/power health, software
and access facts, and final inventory. Historical watchdog absence is not a
current inspection. OBS-05/06 recurrence/boot gaps and OBS-10 battery retention
must retain their applicable requirements or explicit approved dispositions.
Required separate-host ntpviz is Phase 3B; two-node end-to-end work is Phase 8.
Neither is silently pulled into or removed from the current Phase 3 window.

| Decision | Disposition before final observation |
| --- | --- |
| Duration and start | Pending agreement; start only after the last relevant accepted change and prerequisite reconciliation |
| Cadence and completeness | Pending agreement, including node/master/client checkpoints, allowed gaps and what continuous records establish between snapshots |
| Time/client tolerances | Bind adopted source, leap, reach, offset/jitter, freshness and storage limits; agree client response/loss limits and do not invent new numeric thresholds |
| Hardware/load envelope | Agree ordinary workload, fan/PoE/thermal/undervoltage evidence and exclusions; no stress, antenna power change or switch mutation is implied |
| Ownership and response | Aaron is operator; svmf owns existing native polling/evaluation/delivery. Record recurring review cadence, response to failures and evidence retention before handoff |
| Reset/retest | Record boot/configuration/source/device changes, missing samples and real failures. Rebaseline affected evidence and agree restart/disposition; do not erase failed intervals or impose an automatic full restart without the agreed rule |

For the selected OBS-02 window, relevant writer/filegen/retention/filesystem or
boot changes invalidate cross-change growth attribution; start a separately
approved baseline for the affected measurements. For final Phase 3, duration,
gap tolerance and reset decisions remain pending until explicitly agreed.
Any declaration of overall host readiness must cite the completed contract,
every remaining gate's disposition and final inventory, not just passing graphs.

## Next executable preparation

Prepare the t0 node and master read-only reviews with exact bounded inputs,
accepted baselines, recovery/continuity boundaries and acceptance labels. Inspect
current facts before selecting collectors or asserting coverage. Separate t0
[node](/home/aaron/code/.local-evidence/homelab-ntp/current/munin-growth-t0-node-20261022-v2/review.md)
and [master](/home/aaron/code/.local-evidence/homelab-ntp/current/munin-growth-t0-master-20261022-v2/review.md)
reviews retain one-use/expiry controls; prepare the master against the node
archive and require reviewed node t0 acceptance before master execution. Their
preparation is not permission to execute them. Later snapshots require their
own due-time preparation; routine observation does not authorize renewal,
reboot, cleanup or a send.

The approved node t0 v1 attempt failed to export a complete baseline because the
no-symlink reader rejected `/proc/self/mountinfo`. Its receipt is consumed and
master v1 remains blocked/unexecuted; no 48-hour start was accepted. Corrected
v2 uses `/proc/<collector-pid>/mountinfo` with the same guard and data bounds.
Both successors require fresh exact-hash approvals; do not replay or retarget v1.
