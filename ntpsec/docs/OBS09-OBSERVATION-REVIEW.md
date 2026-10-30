# Bounded final-observation procedure

Use this procedure with the [approved OBS-09 contract](FINAL-OBSERVATION-CONTRACT.md).
The controller is [observe-service-window.py](../scripts/observe-service-window.py).
It performs read-only entry capture and a conditional fixed observation window;
it does not install, configure, restart or repair production services.

## Current checkpoint

The [executable review](/home/aaron/code/.local-evidence/homelab-ntp/current/obs09-observation-20261030-v3/review.md)
and [integrity seal](/home/aaron/code/.local-evidence/homelab-ntp/current/obs09-observation-20261030-v3/sealing.json)
bind node/master/client targets, exact source and trust inputs, commands, limits
and recovery boundaries. V3 was approved and consumed during entry, then stopped
on duplicate `capacity` records. The [outcome](/home/aaron/code/.local-evidence/homelab-ntp/current/obs09-observation-20261030-v3-run/outcome.md)
retains partial evidence. No boundary probes or sampling start occurred. Do not
replay v3. Qualify record composition and the producer/parser interface before
preparing another successor. Historical reviews remain unchanged.

Aaron accepted two bounded entry limitations: reported USW-Pro-48-POE/600 W/PoE+
facts plus ordinary-load hardware health, without measured per-port reserve; and
workstation IPv4/IPv6 Webmin access, without proof of external/controller filtering.
He owns master persistence verification at the next relevant approved maintenance.
These dispositions do not claim the missing evidence. OBS-02/D1–D5 and the
accepted watchdog limitation remain unchanged.

## Entry, review and sampling

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
