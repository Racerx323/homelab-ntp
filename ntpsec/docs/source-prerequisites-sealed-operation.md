# Sealed source-prerequisite metadata execution

Prepared October 10, 2026. The v4 candidate narrows remaining-module enumeration to apt-listchanges
Python files before applying its 128-file bound. The helper and acquisition
specification remain unchanged from v3. The consumed v3 attempt stays preserved.
Neither prior execution nor bootstrap authorization covers this execution.

## Prerequisite and command

Require reviewed acceptance of the
[operator bootstrap](source-prerequisites-bootstrap-operation.md), preserved
bootstrap receipt/evidence and a separate approval of this execution bundle's
exact SHA-256. Target only `ama@10.1.0.137`, `j2-svntp1`, using the retained
console-pinned ED25519 key. The fixed root inputs live beneath
`/var/lib/ntp-metadata-elevation/attempt-v4/`. Admission expires October 12,
2026 at 08:08:48 UTC (03:08:48 CDT).

Use `run-sealed-package-resolution.py --bundle <execution archive> --sha256
<approved hash>`. Its single strict-key transport runs:

```text
cd / && sudo -n /usr/bin/python3 -I -B /var/lib/ntp-metadata-elevation/attempt-v4/runner.py
```

Stdin is only the current controller epoch, decimal ASCII plus newline and
EOF. The manifest binds the epoch template; the launcher substitutes this
declared clock observation into stdin, not code or the remote command. It
records the epoch and input digest before submission. No password prompt,
fallback, extra argument or root Python stdin program is accepted.

The launcher verifies all members, its own source, external known-host/epoch
template bytes and the sealed payload contract before registering one attempt.
The runner verifies root ownership/modes, sealed input hashes, the bootstrap
receipt, sudo identity, isolated Python, hostname, clock and expiry. It creates
and fsyncs a persistent exclusive claim before the collector. Any existing
claim rejects reuse, including after interruption. It clears inherited
environment settings and executes only the verified sealed payload.

## Effects, acceptance and recovery

The root runner adds its protected claim/terminal record. All worker effects,
native repository authentication, independent group simulations, full graph
comparison, source-application exclusions, ownership/continuity checks and
stage cleanup/retention remain those in the
[metadata acquisition operation](source-prerequisites-resolution-operation.md).
That earlier document's stdin-Python transport applies only to v2; v4 replaces
it with the fixed command and timestamp-only input above.

Source archives and clockmaker/pinup/timeservice remain provenance/review data.
No package installation, application build, notification, UART initialization,
service activation, network/boot change or reboot is permitted. The existing
660-second worker bound and 840-second SSH bound remain unchanged.

Capture the original stdout, stderr, transport status, worker JSON/marker and
claim status. Metadata acceptance and each dependency group remain distinct;
missing output is not acceptance. Preserve the original submission on timeout
or disconnect. Review remote claim/stage state through a separately scoped
recovery operation before considering another attempt. Never remove the claim
or overwrite controller registration to force a retry.

After terminal review, use the bootstrap bundle's separately authorized
operator removal procedure. Remove only its exact unchanged sudoers fragment;
keep claim and collector evidence. Metadata success does not authorize
application installation or bypass remaining needrestart/hook/notification,
Python binding, account and hardware acceptance gates.
