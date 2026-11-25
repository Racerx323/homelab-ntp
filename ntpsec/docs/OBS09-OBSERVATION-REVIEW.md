# Bounded final-observation procedure

Use this procedure with the [approved OBS-09 contract](FINAL-OBSERVATION-CONTRACT.md).
The controller is [observe-service-window.py](../scripts/observe-service-window.py).
It performs read-only entry capture and a conditional fixed observation window;
it does not install, configure, restart or repair production services.

## Current checkpoint

The November 9 operation is consumed and incomplete: it stopped at
12:38:48 p.m. CST on a changed client IPv6 source after six recorded slots.
Its [terminal record](/home/aaron/code/.local-evidence/homelab-ntp/current/obs09-observation-20261109-v1-run/terminal.json)
and partial captures remain intact. Aaron reported a workstation reboot and
selected J1-SVMF for the successor on November 24. No successor is executable
or approved yet. Final acceptance remains pending.

Aaron accepted two bounded entry limitations: reported USW-Pro-48-POE/600 W/PoE+
facts plus ordinary-load hardware health, without measured per-port reserve; and
workstation IPv4/IPv6 Webmin access, without proof of external/controller filtering.
He owns master persistence verification at the next relevant approved maintenance.
These dispositions do not claim the missing evidence. OBS-02/D1–D5 and the
accepted watchdog limitation remain unchanged.

## Existing workstation procedure (historical; do not replay)

1. Verify the approved manifest with `observer.py check --bundle BUNDLE --sha256 HASH`.
   Use a new empty private output directory; keep inputs separate from results.
   The exact key fingerprint, host-key aliases and controller identity are checked.
2. After execution approval, run `entry` with the same bundle/hash and `--output`.
   It consumes one receipt before contact and captures native node, master and
   independent client evidence. Bounded discovery reads missing current facts;
   failed checks do not authorize changes or wider inspection.
3. Review all entry results. Use `entry-grant-template.json` only as a template:
   populate the actual entry digest, reviewer, timestamp and each evidence-backed
   decision. Record the real OBS-05 trigger and follow-up deadline +24 hours.
   Aaron confirms authenticated Webmin access on both workstation families;
   credentials are never stored. Any unresolved gate prevents start.
4. Run `observe` with `--grant` within 30 minutes of the original entry receipt.
   This is a covered conditional stage of the approved operation, not another
   installation or a replay. Its durable start receipt prevents a second start.
   The window is 48 elapsed hours, with 577 five-minute slots per stream.
5. At completion, review actual health, gaps, journals, inventory and boundaries.
   Obtain finish Webmin confirmation and Aaron's explicit Phase 3 decision.
   A completeness summary or zero exit status is not production acceptance.

The controller must remain awake and connected. Native commands have 20-second
bounds; remote batches have a 130-second bound and controller timeout of 140
seconds. Boundary probes share 90 seconds. Native and client streams run in
parallel within the 240-second slot budget. Output is capped at 2 GiB with
reserve, and entry requires at least 3 GiB free. No server-side timer is installed.

## Evidence and interruption

The shared bounded subprocess helper writes pipe chunks to private output from
launch, preserving partial failures and timeouts. No catch-up probes, retries,
automatic extensions or failure-triggered sends occur. Changed identity/boot,
time-service invocation, protected configuration, field membership or client
source stops collection. Retain failed samples; never classify them as successful
because later samples recover. Routine Munin restarts are assessed for their
actual freshness/coverage effects.

Use monotonic deadlines and UTC/RRD/scheduler epochs across daylight-saving
changes. Munin local log timestamps cannot alone disambiguate a repeated hour.
Retain rotation and bounded-tail limitations; do not infer continuous coverage
from a healthy final snapshot. Raw evidence is an output in a configurable
private directory, not a fleet installation dependency.

On interruption, preserve receipts and partial files. Only owned controller
processes are terminated; remote timeouts bound outstanding reads. No target
restoration is needed. Do not replay entry/start or fabricate missing samples.
Any continuation or correction needs the applicable scope decision.

## Qualification

Focused tests exercise real subprocess failure/timeout/output retention,
no-replay controls, manifest rejection, scheduling completeness/gaps and client
probe separation. The normal repository test suite includes them. Native Munin
Perl syntax and Windows parser/local-adapter checks were qualified locally;
these do not establish current node/master health or actual 48-hour acceptance.
The shared helper's optional output sink preserves existing callers' behavior.

## Local retained-capture qualification

Run `ntpsec/tests/test_service_observation.py` with `OBS09_RETAINED_RUN` pointing
to a complete run directory and `OBS09_RETAINED_BUNDLE` to its frozen inputs.
This exercises the real entry, boundary, grant and continuity predicates without
launching target commands or writing acceptance/start records. Add
`OBS09_NATIVE_IMAGE=localhost/munin-master-validation:bookworm` to qualify flat
and nested cache selection with the installed Munin parser in the existing
network-disabled Podman image. Run that option outside the filesystem sandbox.
Default CI skips these optional private/native cases and retains portable
schema and rejection tests; private evidence is not a build dependency.

An offline pass proves parser/predicate compatibility, not that every reviewed
entry criterion passed. Record missing selections, stale values and operator
conditions separately; never fill all grant checks merely because tests pass.

## J1-SVMF successor preparation

Aaron selected the existing master as controller and independent dual-stack
client. Keep native measurements on j2-svntp1 and native Munin reads on J1-SVMF.
Use the existing collector and native systemd lifecycle; do not build another
transaction framework or transfer workstation private keys to the master.
The hosted adapter is [host-service-observation.py](../scripts/host-service-observation.py).
The deployment review freezes it with the existing collector and the native
[systemd template](../templates/obs09-master.service.in).

The [v2 readiness result](/home/aaron/code/.local-evidence/homelab-ntp/current/obs09-controller-readiness-20261124-v2-run/outcome.md)
is accepted for its read-only scope. Both fixed-source binds/routes passed;
master native tools and Munin cache metadata were present. No outbound key was
found in the inspected master root/pi SSH directories. Prepare dedicated scoped
authentication instead of transferring the workstation key. Actual onward SSH
and NTP response acceptance remain deployment-entry checks. V1 remains consumed
with its helper-import failure; v2 is also consumed and must not be replayed.

The readiness scope below records the inputs now inspected. Carry its findings
into deployment preflight; do not repeat the inspection to obtain an approval:

- On J1-SVMF: current hostname/SSH host key, admitted boot, Python/native tool
  paths, systemd execution capability, candidate private output filesystem and
  available space. Verify local access to the existing Munin cache/RRDs and the
  identities needed for node reads. Do not dump credentials or entire environments.
- Determine whether suitable scoped J1-SVMF-to-node authentication already exists.
  If not, include its narrowly scoped provisioning and removal in the deployment
  review; no private-key copying or broad passwordless privileges.
- Observe routes and stable configured IPv4/IPv6 source addresses toward j2.
  Bind probe sockets to verified sources and record actual socket addresses.
  Reject unavailable sources and wrong endpoints; do not disable continuity
  checks or change host networking to hide source changes.
- Capture current boot at admission, rather than pinning historical boot IDs.
  Unexpected in-window boot/configuration change still stops for reconciliation.

Run the finite collector in one explicitly owned systemd service independent of
SSH and the workstation, with no automatic restart, catch-up or retry. Preserve
partial results and exit status on interruption; bound runtime and output to the
existing contract. Use explicit unit/staging/output ownership. Reconcile stale
owned state before start; never overwrite a prior run. Cleanup removes only the
operation's service/staging after terminal evidence has been retained and verified;
no service-network, Munin or time-service changes are included.

Keep the 48-hour/five-minute cadence, 577 slots, 99% coverage, ten-minute maximum
gap and all precision/health limits. Qualification must prove explicit source
binding, retained failure evidence and one-use start using existing tests. Target
entry verifies actual permissions/routes; a substitute fixture cannot prove them.

Windows-native discovery and operator-authenticated dual-stack Webmin checks
remain start/finish boundary evidence from the workstation. They must not be
called by the Linux master as Windows executables or silently omitted. The
successor must define their timestamp binding and accepted timing relative to
start/finish before approval; missing boundaries block acceptance. Workstation
reboot between boundaries does not stop the master-hosted collector. J1-SVMF
is independent of the NTP node, but shares the Munin failure domain; document that
limit rather than claiming a separate monitoring witness.

## Hosted execution and retirement contract

The separate sealed review binds one installation, entry assessment, conditional
48-hour start, boundary checks, evidence retrieval and owned-state cleanup.
It does not authorize repairing NTP/Munin, changing network or fleet policies,
or replaying a failed sample. Native commands remain the deployment procedure;
the adapter adds only restricted access, admission, boundary binding and key edits.

Generate a new Ed25519 key on J1-SVMF inside the root-private operation directory.
Only its public key crosses hosts. Append one node `authorized_keys` line with
`restrict`, source `10.1.3.83` and a fixed root-owned Python gateway. Preserve
other lines, ownership and mode. The gateway rejects every SSH command except
`entry` and `slot-000` through `slot-576`; it accepts no stdin/code. It escalates
only its own fixed collector through existing sudo policy. Each label consumes
an exclusive receipt before reading. Access expires 50 hours after admission;
an unexpected node boot invalidates it immediately. A one-shot native timer
revokes the line at 50 hours; an intervening reboot does not re-arm the timer
or authorize observation, and attended cleanup still verifies key removal.

On the master, bind NTP sockets to `10.1.3.83` and
`fd36:5aa8:6971:1::83`; SSH to the node also binds the IPv4 source. Run native
master reads locally, including `/usr/sbin/runuser` for Munin decoding. The
same unit first performs entry capture under its final restrictions and waits
up to 30 minutes for the reviewed, atomically published grant; no window starts
without it. The unit is never enabled, has no restart policy, stops within 49 hours plus its
15-second termination grace, and kills its entire process group. Private
results retain the existing 2 GiB bound and 3 GiB admission-space requirement.
The private key is removed on normal exit, collector failure or systemd stop.
A reboot or hard interruption may leave files; no automatic restart is allowed.

Proposed boundary allowance, bound by the new execution approval: complete
Windows-native discovery, DNS/HTTPS and operator-authenticated dual-stack Webmin
within 30 minutes before start and within 30 minutes after the last scheduled
sample. Each automated boundary capture remains at most 90 seconds. Retain its
manifest hash, timestamps, raw output and operator confirmation. Copy only the
start receipt to the master; bind its digest into the start grant. Complete
native/client boundary samples and master DNS/HTTPS still occur at slots 0 and
576. Missing/late workstation evidence blocks acceptance; it never silently
extends or restarts collection. The workstation may reboot between boundaries.

Stop only the owned observer on failure. Preserve time, GPSD, Munin, notifications
and networking. Revoke the operation key, retain command statuses and partial
records, export results with hashes, verify the received copy, and only then
remove the operation's unit, gateway and staging. Do not export the private key.
Aaron owns attended retirement within 72 hours of admission; if evidence cannot
be retrieved, retain it and record the exact exception and retirement trigger.
OBS-02/D1–D5 and all accepted limitations remain unchanged. A local qualification
pass does not prove native SSH admission, service runtime or final acceptance.

## OBS-05 bounded read-only follow-up scope

Aaron approved verification on November 24. The November 9 schedule capture
listed November 26 at 17:45:57 CST, with review due within 24 hours. First establish
the actual next/last trigger and current boot; if the genuine recurrence has not
occurred, record pending status instead of forcing it. A later capture follows
the actual due event. Do not schedule a new inspection or retry implicitly.

Use installed systemd properties/list-timers for `ntpleapfetch.timer` and
`ntpleapfetch.service`, bounded timestamped journal records for those units
covering the recurrence, and the installed leapfile's metadata/hash/validity.
Read the service/timer definitions and applicable drop-ins only to establish
provenance and explain schedule changes. Use `timeservice.service` for current
service health. Capture host identity and boot before/after the read, plus each
command's status and incomplete/truncation indicators.

Acceptance requires a genuine timer-originated invocation, native completion
result, valid retained leapfile and next trigger. A successful no-change run is
eligible; service success alone does not prove scheduling provenance. Missing
journal history or ambiguous invocation remains unresolved. Reboot-triggered
initial invocation is distinct from the four-week recurrence.

No fetch, timer/service start, reload, restart, package action, notification or
configuration edit is permitted. Scope exact commands and bounded outputs in the
execution manifest before contact. The existing `run-leap-inspection.py` pins an
old baseline boot and targets initial activation assessment; do not reuse it
unchanged for recurrence or import a consumed bundle. Reuse its bounded readers
only where their contracts fit. This section is preparation, not a sealed
executable review; the requested verification has not yet been performed.
