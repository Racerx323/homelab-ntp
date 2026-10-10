# Operator bootstrap for sealed metadata elevation

Prepared October 10, 2026. Local implementation and testing are authorized;
target inspection, staging and sudo-policy mutation require approval of the
exact bootstrap bundle. The failed v2 attempt remains preserved.

## Target and inputs

Target only `j2-svntp1`, Debian 13 Trixie/aarch64, observed kernel
`6.18.50+rpt-rpi-v8`, ama UID 1000. Use the confirmed console or existing
operator SSH session with the console-pinned key. This bootstrap is manually
performed through the operator's existing interactive administrative access.
The agent does not collect passwords or automate a password fallback.

The bundle contains a rendered bootstrap program, fixed runner, sealed payload
and manifest, exact sudoers candidate, operator install/remove/rollback
templates, preparation helper, source inputs, tests and operation definitions.
It binds expiry to **October 12, 2026, 08:08:48 UTC (03:08:48 CDT)**. That is an
admission deadline; already admitted collector work retains its existing
bounded operation deadline. Expired bundles require a newly reviewed hash.

After approval, run the bundled `prepare-elevation-bootstrap.py` locally with
the bootstrap archive, its approved SHA-256, `--mode install` and a new output
file in owner-private storage. It verifies all members and its own source,
substitutes only the current controller epoch into the template's command
argument, and writes the operator paste with exclusive creation. It contacts
no target. Generate the paste immediately before use: bootstrap rejects a
node/controller time difference over 300 seconds.

The exact operator template invokes `/usr/bin/sudo /usr/bin/python3 -I -B -
install <controller epoch>` with a literal reviewed Python heredoc. Sudo reads
any administrative password from the operator terminal, never from `-S`, an
argument or an agent. Root executes the reviewed pasted program directly;
it does not read executable bootstrap code from an operator-writable target
directory. The program verifies all embedded data hashes before staging.
Capture its original terminal result privately without automatic resubmission.

## Preconditions and permitted writes

Require native identity, UID, kernel, protected root ancestors, isolated Python,
the approval window and fresh controller time before staging. Inspect native
sudo/Python/visudo versions, resolved tool hashes and package ownership, the
installed sudoers manual hash, existing effective policy and include parsing.
Any unknown path, incompatible tool or identity mismatch holds the operation.

Only these persistent destinations are added:

- `/var/lib/ntp-metadata-elevation/attempt-v4/`, root:root mode 0700, and the
  root-owned protected parent if absent. Existing attempts are not replaced.
- Bound `runner.py`, `payload.py`, `sealed.json`, mode 0600; the policy
  candidate, mode 0440; root-only diagnostic snapshots and receipt files.
- `/etc/sudoers.d/ntp-metadata-attempt-v4`, root:root mode 0440, containing the
  single literal NOPASSWD/NOSETENV command from the elevation definition.

Reject an existing attempt or fragment, including symlinks. Validate the
candidate with native visudo before publication. Publish a fully written,
fsynced policy file using an exclusive link and remove its private publication
link before acceptance. This requires staging and the sudoers directory to
share a filesystem; a differing device holds without a non-atomic fallback.
No partial policy line is written into the effective include directory.

Validate the complete policy after publication and require the new fragment
to appear in the native include report. Query ama's exact command permission
without invoking the collector. Verify installed hashes/modes, absence of a
claim and the unchanged fragment before writing `bootstrap-receipt.json`.
Receipt state is `installed_pending_operator_policy_review`, not automatic
metadata execution authorization.

## Acceptance, failures and removal

The operator reviews the recorded full pre-existing policy, native versions,
include results and exact command permissions, including Defaults/tags that
could interfere with subprocesses. Controller syntax validation does not prove
target admission. Retain the original receipt and its digest, confirm the
deadline and report acceptance before requesting metadata execution approval.
The runner independently requires the completed root-owned receipt, sealed
hashes, protected files, approved identity, fresh time and unconsumed claim.

If activation or later bootstrap checks fail, remove only the fragment whose
bytes still match the approved digest, revalidate policy, and preserve the
staging directory and failure record. A changed fragment is a hold, not
permission to overwrite or remove unrelated policy. Failures before staging
produce only the operator terminal error. Interruptions require recovery of
the original result and protected directory; never regenerate the attempt
by deleting it or retry automatically.

The same bundle defines two separately scoped operator procedures:

- `--mode remove`: after a terminal collector claim, remove only the matching
  fragment, validate policy and retain the claim, payload and all evidence.
  A running or unresolved claim blocks removal pending recovery.
- `--mode rollback`: before any collector claim, verify all bound staging
  inputs, remove the matching fragment, validate policy and remove only those
  inputs. Keep receipts and diagnostic evidence. A claimed attempt can never
  be reset through rollback.

Each generated procedure uses the same protected operator paste mechanism.
Removal records its start before deleting the fragment; a failed policy check
after deletion retains that record for recovery. No restore of unrelated sudo
configuration, package database, service, network or boot state is permitted.
Preserve original media, KVM recovery, primary power and antenna/splitter wiring.

Bootstrap approval must state whether it covers installation, its failure
recovery and the defined remove/rollback procedures. It does not authorize
the metadata collector. That execution has its own bundle and approval gate.
