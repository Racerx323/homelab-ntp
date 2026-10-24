# OBS-04 cron-originated failure notification

## Status and evidence

The approved v2 transaction executed once on October 24, 2026. Genuine cron
ancestry and the matching command journal establish scheduling; the controlled
wrapper returned 2 with the exact private diagnostic, then released one approved
`!`. Aaron confirmed the matching subject and marker through AppriseAPP at
18:43 CDT. The [reviewed outcome](/home/aaron/code/.local-evidence/homelab-ntp/current/obs04-cron-failure-delivery-test-20261024-v2/outcome.md)
accepts OBS-04 for this controlled route. Qualified OBS-02/D1–D5 are unchanged.

The authored entry was withdrawn at 18:44:16 CDT; terminal observation at
18:44:17 confirmed absence and unchanged running cron/NTP/Munin identities.
No retry occurred. Stage evidence remains retained and the receipt consumed.
No exact SMTP response or mailer exit was captured; downstream receipt proves
this message traversed the route, without establishing all provider fanout or
sustained reliability. The sections below describe the executed design and its
approval boundaries; they do not authorize replay.

| Boundary | Accepted evidence | Limit |
| --- | --- | --- |
| Cron origin | Unique command journal and ancestry to pinned cron daemon | One scheduled controlled run |
| Failure wrapper | Expected status 2, exact private diagnostic and one marker | Argument rejection; full diagnostic not sent, scanner crash not tested |
| Native submission | Native-only output path plus matching downstream receipt | Exact SMTP code/mailer exit not observed |
| Downstream receipt | Aaron's matching AppriseAPP notification | Full wire bytes and every provider not independently captured |
| Withdrawal/continuity | Authored entry absent; ordinary service identities unchanged | No final protected-file rehash or later timer-firing observation |

Earlier copied-reporter/synthetic-scanner tests did not prove cron origin.
An independent sender cannot close this gate. SMTP acceptance is not delivery;
failed/uncertain submission can coexist with partial downstream delivery.

## Native inputs and execution preflight

The official Debian cron 3.0pl1-197 ARM64 package's binary, cron unit and defaults
hashes match the approved non-sending capture. Source archives were checksum
verified against the official manifest and all 85 Debian patches applied locally.
Patched source and matching binary strings establish the subject/mailer formats.
The matched defaults contain `EXTRA_OPTS=""`; source defaults are log level 1 and
short hostname. Under that configuration the subject has no `(failed)` suffix.
The captured msmtp configuration fixes the sender, disables envelope overrides
and replaces the From header; both sendmail links resolve to msmtp.

These findings do not claim a fresh daemon-argument observation. The execution
preflight requires exactly `/usr/sbin/cron -f`, exact hostname `j2-svntp1`, the
accepted boot/cron/time-service identities, matched unit/defaults/binaries,
protected files and safe permissions. Reject root msmtp overrides, cron drop-ins,
timezone drift or non-running required services before publication. Repeat the
relevant checks before release. A mismatch holds the stage without changing
the daemon, message or normal reporting. Any later diagnostic access must use
its own approved scope; the earlier inspection receipt stays consumed.

## Controlled failure and exact payload

Use the installed reporter's existing rejection of
`--obs04-controlled-failure`. The inspected argument parser matches the shared
repository source and exits before scans, direct mail and success recording.
Derive the real production wrapper's capture/status/output handling from the
pinned template, substituting only the rejected argument and private lock.
Require status 2 and exact diagnostic bytes, retained privately.

The patched native cron redirects job output to an anonymous regular file,
not a pipe. Therefore PIPE_BUF cannot protect a multi-byte diagnostic. The
reviewed design releases **one ASCII `!` byte**, only after diagnostic validation,
into an empty anonymous native output file. One byte has no nonempty partial
prefix; an interrupted release is either empty or the approved marker.
SMTP may append one terminal LF/CRLF, explicitly allowed by the message contract.
The preview includes that framing newline. The full diagnostic is not mailed.
This is a controlled route test, not a production fault or proof that every
internal scanner failure is handled identically.

The worker requires ancestry from the pinned running cron daemon and checks
that its authored entry still exists unchanged. It never invokes sendmail/msmtp.
Native cron constructs the reviewed subject and invokes its mailer. The entry's
command contains the unique `delivery-test` operation identifier. Its explicit
recipient is `notify.failure@mailrise.xyz`, sender
`j2-svntp1@local.theama.co`, content type UTF-8 text/plain, encoding 8bit, with no
attachments. Runtime Date, Message-ID, X-Cron-Env, display-name and transport
headers are enumerated generated fields, not a claimed exact whole-wire hash.

## Publication, scheduling and one-use control

Keep the normal daily cron entry, reporter, production lock and success records
unchanged. Use a separate root-owned `/etc/cron.d/obs04_cron_failure` and a
root-private operation stage under `/var/lib/ntp-obs04`. All executable bytes
have repository sources; the bundle contains explicit versioned native data.

At approved installation, select and record the first whole host-local minute
strictly after now +180 seconds. This replaces the draft's preselected minute,
which could expire while approval is pending. The scheduling algorithm is part
of the immutable review and does not alter the message. Reject execution within
15 minutes of ordinary 05:30 reporting, insufficient publication lead time or
an insufficient remaining validity/recovery window. No normal schedule changes
or cron reload/restart are included.

Create a durable exclusive attempt claim before executing the controlled branch.
Existing, expired, withdrawn or interrupted attempts are quiet and cannot send
again. Release is allowed only within 90 seconds after the recorded due minute.
A release-intent record without a final result is uncertain and permanently
consumed. A boot change prevents release, including after a reboot or future
annual match of the date/month-limited cron entry.

## Observation, withdrawal and interruption

Register an operation-owned transient withdrawal timer before publishing the
entry. It removes only the byte-identical authored entry at approximately due
+180 seconds if the controller disappears. Require its active state before
publication. No ordinary service/timer is changed or restarted.

The controller performs one install connection, waits until due +75 seconds,
then one observation, one conditional withdrawal and one terminal observation.
On uncertain installation, inspect once and conditionally withdraw; never
reinstall or resubmit. Each transport and remote action is bounded. Keep all
partial output, receipts, runtime data and private stage files for review.

Withdraw only matching root-owned bytes; preserve foreign drift. An interrupted
publication's known companion link may be removed only when inode/hash/owner/
mode prove it is the second authored name. Stage evidence stays retained. No
process is killed and no submitted message is cancelled. A missing/ambiguous
mail disposition or in-flight uncertainty holds acceptance, not retries.

## Acceptance and approval boundary

Approval must bind the exact executable archive and reviewed recipient,
envelope sender, subject, marker/body-framing rule and no-attachment preview.
One approval can cover its precise preflight/publication, one native mail attempt,
observations and restoration. Earlier recurring-report or Munin-test approvals
do not authorize this new test.

Require correlated cron-daemon scheduling/ancestry, controlled status/diagnostic,
one marker release, native submission disposition, authored entry withdrawal,
service continuity and operator-confirmed downstream receipt. Absence of MTA
errors is not evidence of SMTP success. Concurrent mail/log ambiguity remains a
review finding. The controller does not automatically accept delivery or OBS-04.
Normal reporting and qualified OBS-02 acceptance must remain intact. Final
Phase 3 observation and all other owning-phase requirements stay separate.
