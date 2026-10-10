# Source-prerequisite resolution execution result

## Outcome

Aaron authorized one execution of source-prerequisites-resolution-v2 on
`ama@10.1.0.137`. The hash-bound launcher submitted its strict-key SSH command
once. SSH reached sudo, which returned `sudo: a password is required`.
Transport exit status was 1; stdout was empty. The launcher rejected the
missing terminal JSON/status marker and retained the original evidence.

The root metadata collector did not start. It created no metadata workspace
and performed no metadata acquisition or dependency simulation. Acceptance
is false; the preparation checks do not substitute for target results.
No package installation, source build, configuration deployment, service
activation or reboot occurred. No retry or password fallback was attempted.

Bundle SHA-256:
`f37a5c575baf5852749f1ac9b7eab7eaa47a244482b60bd7e34a7117bf6792ce`.
The bundle remains unchanged, and both preceding superseded archives remain
preserved. Its preparation-time approval record remains an immutable account
of preparation; the subsequent user authorization and failed execution are
recorded in the execution review.

## Evidence and limits

Private evidence is retained under
`.local-evidence/homelab-ntp/j1-svntp1/source-prerequisites-resolution-v2/`
in the controller workspace:

- `metadata-resolution-execution.json`: registered/submitted/terminal transport
  state, exact command, runtime controller epoch and exit status.
- `metadata-resolution.stdout` and `metadata-resolution.stderr`: original
  transport streams; stdout is empty and stderr records sudo's rejection.
- `launcher.log`: missing-terminal-marker exception.
- `local-execution-review.json`: authorization scope, failure classification,
  acceptance false and original evidence hashes.

There is no worker JSON result because sudo did not admit root execution.
The current sudo policy was not inspected or changed; this result establishes
only that the exact noninteractive invocation was rejected. It does not
establish why previously available elevation no longer works.

## Operator bootstrap clock rejection

The subsequent authorized bootstrap v1 operator invocation was reported to
fail with `ValueError: bootstrap clock/window mismatch`, at the gate before
persistent bootstrap writes. Installation is not accepted.

A later strict-key read-only clock preflight observed target time
2026-10-07 13:29:54 UTC while the controller measured
2026-10-10 08:52:57–08:52:58 UTC: about 242584 seconds behind.
The target reported `NTP=yes` and `NTPSynchronized=no`. This establishes
current skew, not the exact time at the reported failure or its underlying
cause. No target filesystem inspection or clock mutation was performed.

Both the preparation lower bound and the 300-second controller comparison
reject that observed time. Preserve the original paste and private bootstrap
clock evidence. Clock correction needs separate scoped authorization; verify
agreement before refreshing only the declared runtime timestamp. Metadata
execution remains unauthorized.

Aaron subsequently authorized clock correction (annotation 1). Preflight found
systemd-timesyncd running with repeated Debian fallback-pool reply timeouts.
Prepared a guarded operator forward step using a boot-bound monotonic sample;
the sample expires after 300 seconds. Nine focused checks mocked the clock
setter. The operator step and subsequent SSH clock verification remain pending.
No time-service configuration or network policy was changed; ongoing NTP
synchronization is not accepted.

Aaron reported the operator step done without supplying its terminal JSON/error.
Subsequent strict-key read-only verification found the same boot/kernel and
target-controller agreement within 0.41 seconds. The bootstrap parent, attempt
directory and sudoers fragment were absent. NTP still reported unsynchronized.
Refreshed only the declared runtime epoch in a new operator installation paste
from the unchanged authorized bootstrap archive; member/helper hashes and shell
syntax passed. Bootstrap execution and policy review were pending then.

## Bootstrap acceptance review

Aaron supplied the operator installation receipt observed at 09:01:43 UTC.
Its bound inputs and admission checks match the authorized bootstrap archive.
Live strict-key sudo listing confirms NOPASSWD/NOSETENV for the exact fixed
runner command. Protected readback verifies root ownership, mode 0700 for the
attempt, installed input hashes/modes, the effective fragment and a receipt
equal to the operator-supplied JSON. No claim is present; no collector was invoked.

Reviewed the retained pre-install policy and current Defaults. The existing
administrative permission remains; no NOEXEC or interception tag appeared.
Readback used noninteractive sudo with existing administrative authentication,
without a password fallback. Bootstrap acceptance is reviewed. Actual collector
admission and ongoing time synchronization remain untested or unresolved.

Reverified sealed metadata v3 archive/member/helper/host-key inputs and the
admission window without registering or submitting it. Execution remains
unauthorized; the next gate is approval of its exact archive hash:
`f197494310cdc110c6f494325f4d7d1486ab27b689284917958ee0309cc45660`.

## Sealed metadata v3 execution result

Aaron approved one v3 execution through annotation 1. The launcher submitted
the fixed sealed runner once. Worker and SSH returned status 2 with matching
terminal JSON/marker; launcher status 0 establishes transport agreement only.
The worker state is held and metadata acceptance is false.

Preflight failed with `keyring/hook input count exceeds approved 128-file bound`
before acquisition or simulation. The general enumerator checks its aggregate
bound before the caller filters apt-listchanges modules. The retained listing
contains 13 apt-listchanges Python paths and 101 Debconf Perl paths, in addition
to fixed policy/manual/source inputs. No workspace was created.

Package-file verification and dpkg audit passed. The worker reports installed
state, approved inputs and boot unchanged. Protected claim readback confirms
completed_with_gaps, status 2 and the matching epoch/payload. Original stdout,
stderr, launcher log, authorization, submission/result and review records are
preserved privately under source-prerequisites-resolution-v3. No retry occurred.
No package installation, source build or service change occurred.

## Policy removal verification

Aaron supplied the successful operator removal receipt. Strict-key protected
readback confirms the temporary fragment is absent, the receipt JSON matches,
and native visudo validates the remaining includes. Effective permissions match
the retained pre-bootstrap snapshot exactly. The terminal claim hash/content
and all four protected input hashes/modes are unchanged. Cleanup acceptance is
complete; the failed attempt and evidence remain preserved. No collector rerun
or further target mutation occurred.

## Offline correction and new attempt preparation

Aaron approved offline correction and bundle preparation through annotation 1.
The worker now enumerates only apt-listchanges Python modules under its fixed
dist-packages directory before enforcing a 1-128 unique-file bound. It rejects
parent traversal anywhere in the listing. The broad keyring/hook helper is
unchanged. The retained listing contains 13 Python and 101 Perl paths; replay
reproduces the previous bound failure and verifies the corrected selection.
Empty lists, duplicate paths, traversal and overflow are covered. All 109
offline tests passed; no target contact or new execution occurred.

Prepared distinct attempt-v4 inputs with bootstrap v2 archive SHA-256
`379a852fb752953a90ca35dac570950241c712629174181cdc4edb6ff0611adf`
and metadata v4 archive SHA-256
`ac80afd65ae1e5936cc80c2942c2cf49892cd80668e65cd4bf4ef2e57a553a06`.
Only the embedded worker literal changes in the payload; the inspection helper
and acquisition specification are byte-preserved from v3. Verified all member
hashes, rendered bindings, operator install/remove/rollback templates and the
sealed launcher's preparation path without registering or submitting it.
Admission still expires October 12, 2026 at 08:08:48 UTC (03:08:48 CDT).

## Bootstrap v2 authorization and operator handoff

Aaron approved bootstrap v2 installation through annotation 1, bound to its
archive hash above. Approval includes identity/policy checks, attempt-v4 staging,
the exact temporary sudo rule, acceptance readback and defined rollback/removal.
Metadata v4 execution remains unauthorized. Reverified archive/member hashes,
helper identity, private output storage and the admission deadline, then
prepared a fresh timestamped operator install paste. No target command was
submitted. Await the original operator receipt or error before readback; do not
automatically repeat an attempted installation.

## Bootstrap v2 installation and acceptance

Aaron supplied the successful attempt-v4 operator receipt. Approved strict-key
readback verifies root-protected directory/files, exact bound hashes and modes,
the matching protected receipt, and absence of a collector claim. The effective
grant permits the fixed runner command with NOPASSWD and NOSETENV; no NOEXEC or
INTERCEPT setting was observed. Pre-existing administrative policy matches the
prior snapshot. Clock observations satisfy the 300-second admission bound;
ongoing NTP synchronization remains unresolved.

Bootstrap acceptance is complete. Original operator receipt, protected readback,
policy query and hash-bound acceptance review remain private. Reverified the
metadata v4 archive and launcher preparation without registration or execution.
No collector, acquisition or simulation ran during these acceptance checks.

## Metadata v4 execution result

Aaron approved one metadata v4 execution through annotation 1, bound to its
archive hash above. The launcher submitted once. SSH and worker returned 2;
launcher returned 0 because transport matched the terminal collector status.
Metadata acceptance remains false and no dependency group was evaluated.

The narrowed module enumeration passed. Native authenticated update returned 0
inside the isolated workspace, then index completeness held: 16 observed
architecture/component package targets against 26 required, with no unexpected
targets. Missing targets are contrib, non-free and non-free-firmware for
trixie-updates, and non-free/non-free-firmware for trixie-security, for both
arm64 and armhf. Empty-index status requires review against signed release
metadata; the acceptance rule remains unchanged.

Package state, approved inputs and boot were reported unchanged. The worker
retained its staging workspace as evidence. Original output and status,
index-set comparison and terminal readback remain private. Strict-key readback
verified a completed_with_gaps claim, status 2, matching the original payload
and controller epoch, and the exact unchanged sudoers fragment. No retry occurred.

Prepared the already-authorized operator removal paste for attempt-v4. Preserve
the terminal claim, protected inputs and staged metadata; await the original
removal receipt or error before cleanup readback.

## Attempt-v4 policy removal acceptance

Aaron supplied the successful operator removal receipt. Approved strict-key
readback confirms the temporary fragment is absent, the protected removal
receipt matches the supplied JSON and native visudo validates the remaining
includes. Effective permissions exactly match the attempt-v4 pre-install
snapshot. Terminal claim content/hash and all four protected input hashes/modes
are unchanged. Cleanup acceptance is complete; original receipt, readback and
hash-bound review remain private. No collector retry or additional mutation ran.

## Next gate

The [narrow elevation mechanism](source-prerequisites-elevation.md) is now
defined and reviewed locally: fixed root-owned inputs, an exact temporary
sudo command, a bounded timestamp input and a persistent one-shot claim.
Implementation and offline tests are complete. Separate bootstrap and sealed
metadata approval bundles were prepared; bootstrap acceptance is reviewed and
v3 has now executed once with the held result above. Its claim is consumed.
The temporary fragment has been removed and cleanup verified. The offline
correction and attempt-v4 bundles are prepared. Bootstrap v2 is installed and
acceptance reviewed. Do not repeat installation. Metadata v4 is terminal and
held; its execution approval is consumed. Policy removal and cleanup acceptance
are complete. Review retained signed release metadata before proposing any
index-completeness correction or distinct new attempt. Target counts alone do
not establish empty indexes. Additional target evidence retrieval needs a new
scoped approval. Never reset the v4 claim or repeat its policy removal.
The [approved operation](source-prerequisites-resolution-operation.md) requires
noninteractive sudo and forbids a password fallback. Do not grant general
passwordless access to a root Python interpreter as an incidental workaround.

Preserve this attempted execution; do not rerun its one-shot launcher or
delete its registration. A later execution needs a distinct attempt record
and scoped authorization. A changed transport or execution input requires a
replacement bundle hash before approval. Fresh metadata, exact prerequisite
versions and target Python binding remain unresolved, so application build,
installation and activation stages remain held. Preserve old-card rollback,
primary power and shared antenna/splitter wiring.
