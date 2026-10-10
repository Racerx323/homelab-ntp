# Narrow elevation for source-prerequisite resolution

Defined, implemented and tested locally October 10, 2026. This is not an
installed runner or execution approval. The
[v2 attempt](source-prerequisites-resolution-results-20261010.md) remains
preserved: sudo rejected it before the collector started.

## Decision and scope

Use a temporary sudo rule permitting one exact command that runs a fixed,
root-owned Python runner. Bind that runner to the reviewed metadata payload
and give it a persistent one-shot claim. The rule must not permit Python with
arbitrary arguments, stdin programs, user-selected scripts or `-c` code.

Separate operator bootstrap from unattended metadata execution. The operator
uses existing administrative access to stage reviewed bytes and the temporary
rule. The subsequent metadata operation still uses `sudo -n`, with no password
prompt or fallback. An interactive bootstrap does not change the approved
metadata operation into an interactive command.

The only permitted collector effects remain those in the
[metadata operation](source-prerequisites-resolution-operation.md): isolated
workspace creation, authenticated index acquisition and dependency simulation.
No application build/install, UART initialization, service activation, reboot
or notification is added. Bootstrap additionally changes its named runner
directory and one temporary sudoers fragment; those effects need their own
exact authorization and rollback.

## Fixed command and policy candidate

Use a new attempt directory, proposed as
`/var/lib/ntp-metadata-elevation/attempt-v4/`, with root-owned ancestors that
are not writable by the operator. The directory is root:root mode 0700;
runner, sealed payload and manifest files are root:root mode 0600. Reject
symlinks, unexpected file types and pre-existing attempt files.

The candidate sudoers fragment is one complete literal line:

```sudoers
ama j2-svntp1 = (root) NOPASSWD: NOSETENV: /usr/bin/python3 -I -B /var/lib/ntp-metadata-elevation/attempt-v4/runner.py
```

Install only as `/etc/sudoers.d/ntp-metadata-attempt-v4`, root:root mode 0440.
The command arguments are specified in full and contain no wildcard or regex.
Do not shorten the entry to `/usr/bin/python3` or omit its arguments. Python's
`-I -B` isolates imports and disables bytecode writes. `NOSETENV` accompanies
runner environment sanitization; it does not replace that sanitization.

The new strict-key SSH command is fixed:

```text
cd / && sudo -n /usr/bin/python3 -I -B /var/lib/ntp-metadata-elevation/attempt-v4/runner.py
```

Its stdin contains only the controller's declared UTC epoch, as decimal ASCII
followed by one newline. Application/helper code is never supplied over this
privileged stdin. Retain existing proxy, reuse, forwarding and host-key
protections and the outer execution deadline.

## Required runner behavior

Implement and test these requirements before preparing an executable bundle:

1. Require root execution, the approved `SUDO_USER=ama` and `SUDO_UID=1000`,
   isolated Python and no extra command-line arguments. Inspect the actual
   interpreter and sudo versions during bootstrap; do not infer target
   compatibility from controller tests.
2. Open only fixed runner-directory inputs. Require root ownership, protected
   ancestor permissions, regular files, exact modes and the expected manifest
   and payload hashes. Reject links and drift before executing payload code.
   The expected hashes are fixed in the reviewed runner, not obtained from
   operator-controlled stdin, environment or an arbitrary manifest path.
3. Read at most 22 bytes of stdin with a ten-second deadline: a 21-byte record
   and one overflow-detection byte. Accept only
   1–20 decimal digits followed by one newline and EOF; reject additional
   bytes or a stream left open. Preserve the worker's 300-second controller
   clock check. The timestamp is a bounded observation, never a code/config
   input or an authorization token.
4. Enforce a fixed UTC expiry supplied by the new execution approval. Verify
   node time before activation during bootstrap, and reject execution outside
   that window. No caller-controlled expiry or bypass is permitted.
5. Clear inherited environment settings, preserving only verified sudo
   identity plus a fixed PATH and locale required by the existing collector.
   Ignore inherited APT_CONFIG, Python settings and user search paths. The
   existing worker creates and checks its own isolated APT configuration.
6. Before executing the collector, atomically create `claim.json` in the
   protected attempt directory using exclusive creation, no-follow behavior
   and mode 0600. Persist the claim before starting work. An existing claim,
   including one from a failure or interruption, always rejects a second run.
   Do not reset or remove this claim during normal cleanup.
7. Execute only the verified sealed metadata payload, preserving its helper,
   worker and spec bytes. Supply the validated epoch through its existing
   argument contract. Keep its native authentication, package exclusions,
   deadlines, subprocess-group handling and evidence-retention behavior.
   NTPsec/GPSD sources and application helpers remain review data only.
8. Record terminal status alongside the claim without losing interruption
   evidence. Preserve original worker JSON and its terminal status marker;
   runner rejection must also produce an explicit failure record. Keep
   controller registration and streams so a disconnect cannot lead to an
   automatic second submission.

## Bootstrap, acceptance and removal

Prepare a separate hash-bound bootstrap specification containing the runner,
sealed payload, manifest, exact sudoers candidate, approval expiry and
installation/removal procedure. Include every non-secret execution input.
The bootstrap is not covered by the consumed v2 execution approval.

Before writes, inspect hostname, OS/kernel, ama identity, native sudo/Python
tools, effective sudo policy, configuration include paths, file ownership and
ancestor permissions. Require the new runner directory and fragment to be
absent; never replace an existing local policy or attempt. Retain snapshots
of inspected policy and identities as private evidence.

The operator stages reviewed bytes through existing interactive administrative
access, such as the confirmed console. No password is captured by the agent,
stored in a file or placed in a command argument. Copy only data: securely
read and verify bytes against approved digests before writing protected
destinations. Do not execute bootstrap code from a mutable user directory,
extract arbitrary archive paths as root or use a hash check followed by a
fresh unverified read of operator-writable files.

Validate the candidate with native `visudo -c -f` before activation, then
validate the complete effective sudoers configuration with native `visudo -c`.
Confirm effective `sudo -l` permissions for ama include the exact command.
Review broader existing grants and Defaults rather than claiming the new
fragment proves the entire account's privilege scope. Do not invoke the
one-shot collector as a permission probe.

Accept bootstrap only when exact installed hashes, owners, modes, interpreter
identity, effective command policy, approval window and absence of a claim
are recorded. Any mismatch holds execution. New transport/input handling
requires a new controller launcher and bundle; the v2 launcher must not be
edited to rerun the failed attempt.

After terminal completion or failure, use the separately approved operator
cleanup procedure to remove only the unchanged named sudoers fragment.
Validate the complete policy again. Preserve the claimed runner directory
and all execution evidence; do not authorize another run by deleting its
claim. A timeout or disconnect requires recovery of the original state first.
If cleanup fails, the consumed claim still rejects reuse. An unclaimed runner
must reject after its fixed expiry; verify policy removal independently.
Before collector submission, bootstrap rollback removes only its verified
fragment and unclaimed staging files, retaining bootstrap evidence. Existing
sudo policy, package state, network/services, old card and primary/antenna
power remain outside that rollback.

## Review findings and remaining work

| Boundary | Review conclusion |
| --- | --- |
| Arbitrary root Python | Avoided by exact sudo command arguments and protected fixed runner; no arbitrary stdin code or script path is accepted |
| Operator-writable code | Must be copied as verified data into root-owned storage before sudo permission is activated |
| Environment injection | NOSETENV, isolated Python and explicit runner environment clearing are all required |
| Repeated metadata acquisition | Persistent exclusive claim rejects reuse after success, failure or interruption |
| Residual sudo permission | Temporary fragment removal is explicit; expiry and the consumed claim limit leftover permissions |
| Existing broad sudo grants | Unknown; inspect native effective policy during separately authorized bootstrap |
| Version compatibility | Controller syntax validation is partial; target tools and effective policy remain unverified |
| Worker operation scope | Existing metadata-only worker inputs and effects are retained; bootstrap adds narrowly named privilege/staging writes |

Local sudoers documentation confirms that specified command arguments must
match and that omitting arguments permits caller-chosen arguments. The
controller's `visudo` is 1.9.15p5; its parser can check the candidate syntax.
Neither check proves target policy admission or runtime security.
The candidate parsed successfully with exit status zero. The local parser
also warned about controller `/etc/sudo.conf` ownership; its log is retained.
No effective-policy or privilege-admission check was performed on that basis.

Implemented `metadata-elevation-runner.py`, `bootstrap-metadata-elevation.py`,
`prepare-elevation-bootstrap.py` and `run-sealed-package-resolution.py`.
Offline tests cover input bounds, EOF/timeouts, changed hashes/ownership,
environment clearing, expiry, duplicate/concurrent claims, interruption,
activation failure, policy drift, terminal removal and unclaimed rollback.

The [bootstrap operation](source-prerequisites-bootstrap-operation.md) binds
operator staging/removal and fresh clock observations; the
[sealed execution operation](source-prerequisites-sealed-operation.md) binds
the replacement transport. The controller-local approval bundles contain
rendered fixed inputs. Target native tools and effective policy still need
bootstrap acceptance. Nothing has been installed or executed on the target.
