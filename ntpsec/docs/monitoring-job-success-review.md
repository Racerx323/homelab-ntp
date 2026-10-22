# Maintenance job-success recording review

Reconciled October 21, 2026. Master static networking and DNS are accepted;
the [v2 node/producer readiness capture](/home/aaron/code/.local-evidence/homelab-ntp/current/munin-node-producer-readiness-20261021-v2/outcome.md)
completed at 10:51:48 CDT. The approved producer bundle executed once and passed
installation/readback at 12:02:25 CDT. See the [accepted outcome](/home/aaron/code/.local-evidence/homelab-ntp/current/munin-producers-20261021-v3/outcome.md)
and [archive SHA-256](/home/aaron/code/.local-evidence/homelab-ntp/current/munin-producers-20261021-v3/sealing.json:1).
No job, schedule change or message ran; no success record was fabricated. The
execution receipt is consumed. Real scheduled success remains pending under
OBS-01/OBS-03/OBS-07. The subsequent node acceptance failure/containment does not
undo this accepted producer installation.

The approved [node/producer observation](/home/aaron/code/.local-evidence/homelab-ntp/current/munin-node-producer-observation-20261021-v1/outcome.md)
completed October 21 at 16:00 CDT with unchanged continuity and consumed receipt.
Both genuine records are still absent and no matching post-install scheduler
completion was captured. Native scheduled Munin data correctly shows evidence=0,
ages unknown. Neither job's scheduled success is accepted. Captured retention
timer next trigger is October 22 00:45:39 CDT; reporting is configured for October
22 05:30 CDT. These are intended schedules, not promises of completion.
Prepare a new read-only review after both runs have had time to finish; inspect
each real record/provenance independently. No job was forced and no mail sent.

## Intended producer contract

The selected [Munin reader](../../../homelab-monitoring-observability/Munin/node/profiles/ntp/README.md)
expects two independent root-owned mode-0600 regular files under protected,
non-symlink directories:

| Actual completed job | Success record | Schema job |
| --- | --- | --- |
| NTP statistics retention rule | `/var/lib/ntpstats-retention/last-success.json` | `retention` |
| Needrestart production reporter | `/var/lib/needrestart-reporting/last-success.json` | `reporting` |

Schema 1 has `job`, `status: success` and finite `completed_epoch`, at most 4096
bytes. Write atomically only after the actual job succeeds. Preserve locking,
quiet successful scans, daily schedule, failure exit status and existing mail
behavior. A lock skip, `-t` test, dry run, partial failure or global logrotate
success must not advance the record. A quiet successful real reporter run does.
No backdated or synthetic production records; until actual completion the reader
must continue reporting missing evidence as a fault.

The retention record must prove execution of this exact four-stream cleanup
rule, including a successful no-op when the rule genuinely runs. A scheduled
logrotate run that skips this trigger is not a cleanup completion. It must not
depend on files being old enough for deletion or a postrotate hook that may not
run. Bind completion to the actual cleanup producer. Reporter success records
must not assert downstream delivery merely because sendmail returned zero.

## Current source and ordering

The accepted [retention rule](../templates/ntpstats-retention.logrotate) and
[reporter](../scripts/needrestart.sh) remain byte-exact baseline sources for their
existing installation paths. The [stage controller](../scripts/run-munin-stage.py)
renders successor bytes inside the closed archive. It replaces the rule's
`firstaction` body with the fixed helper call and injects reporting completion
only at the real reporter's final successful exit. Older installation paths do
not acquire a dependency on an unprovisioned helper.

The [completion helper](../scripts/maintenance-success.py) performs the actual
four-stream cleanup before atomically recording retention success. It preserves
the 30-day mtime boundary, active files, shared hardlinks, unrelated names and
indirect files. Reporting completion follows any required successful mail
submission; downstream receipt remains separate. No second scheduler.

Deploy producers before the node when using these bundles: both pin the captured
701-package inventory, and node installation would invalidate the producer pin.

The selected reader and missing-record behavior are already defined. Node
installation can accept those explicit faults without waiting for synthetic
success. Producer implementation/preparation can proceed independently, but
final master health acceptance requires actual successful scheduled completions
for both jobs. DNS acceptance does not establish job execution or delivery.

## Preflight, implementation and acceptance

The approved v2 capture now retains installed rule/trigger/state metadata,
reporter and cron hashes/schedule, fixed producer markers and lock observations.
The rule and reporter match repository sources; both success files are absent.
Cron is 05:30 root in America/Chicago; no kernel-lock match was observed and no
lock was acquired. Recheck these pinned inputs in the later mutation preflight;
do not infer a new lock-free window or job completion from this sample. The
shared node readiness capture ran no job or mail. Producer mutation remains a
separate stage with exact before/after bytes, host/boot/package and time-service
pins. Stop on drift; do not export mail secrets.

Focused offline qualification covers actual cleanup/no-op/boundary handling,
quiet/actionable scans with captured mail, test/failure/cron-lock exclusion,
real logrotate debug behavior, interrupted atomic replacement and rejection of
indirect/shared/unsafe records. A writer failure uses the reporter's existing
nonzero failure path or fails logrotate firstaction. Previous success survives a
failed replacement. No production path is invoked and no mail is sent.

The sealed bundle binds before/after bytes, private backups, helper, tests,
write paths and rollback. Its worker acquires existing reporter/global-logrotate
locks without creating them, rejects busy locks and schedule/trigger drift,
installs the helper before hooks and restores only matching authored changes on
caught failure. Only the protected sticky `/run/lock` parent is excepted from
ordinary ancestor-mode checks. No unrelated installer/failover suite was rebuilt.
Any real scan capable of sending existing reports needs explicit scope and
content handling.
Use the next actual scheduled job to accept genuine records, unless a separately
approved real invocation is chosen. Record each job independently; do not close
both from one global timer result.

## Recovery and remaining gates

Restore matching authored script/rule/helper changes from verified backups, retain
record/evidence provenance, and prove original schedule, locking, quiet behavior
and failure handling. Hold on foreign drift; never restore a stale success
timestamp as evidence of a new run. Preserve NTP continuity.

The baseline, implementation and sealed mutation/recovery bundle are prepared.
The approved installation stage is now consumed. Genuine scheduled completion
and any further observation/invocation remain separate gates. This review does not activate synthetic
success, alter reporting recipients or send problem/recovery tests. Scheduled
success observation and cron-generated failure delivery remain explicit readiness
items after installation.
