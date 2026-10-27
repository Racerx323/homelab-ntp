# Base OS maintenance procedure

The [governing update gate](ntp-architecture-deployment-plan-v1.0.md#base-os-update-completion-gate)
defines acceptance. This procedure separates preparation from live changes.
[Readiness](PRODUCTION-READINESS.md) identifies the current checkpoint and
[HISTORY](../HISTORY.md) records outcomes. A review-only archive is not executable.

## Current maintenance approach

The [attended native runbook](MAINTENANCE-NATIVE-RUNBOOK.md) implements the next
review: one native package invocation, conditional reboot, verification and owned
restoration, with explicit hold/fallback branches. It is an ordered command
runbook with operator/agent gates, not an automatic installer. Readiness names the
current sealed review; only its exact-hash approval authorizes target access.

Use the [consolidated assessment and plan](MAINTENANCE-SIMPLIFICATION.md) for the
next maintenance review. It replaces the repeated inspection/update/reboot
handoffs with one bounded scope using native package management. Cleanup state
and effective EEPROM controls belong in its preflight. A successful generated
initramfs check does not itself require a second approval before the planned reboot.
This changes the proposed workflow, not the governing acceptance gate or any
consumed authorization. No new live operation is authorized.

The stages and tools below describe the earlier preparation chain. Preserve their
evidence and reusable checks; do not repeat that chain as a mandatory checklist.

## Earlier preparation stages

1. Inspect the accepted package/rule/service evidence. Record missing inputs;
   cached indexes do not establish a fresh or complete update transaction.
2. Implement and qualify a bounded maintenance snapshot and native rule-parser
   stage. Include effective sources/key references, preferences/holds, hooks,
   needrestart policy, package locks/automatic-update controls, dpkg health,
   root/boot capacity, firmware policy and protected service state. Sanitization
   must exclude secrets. Any scratch staging is explicit and removed by ownership.
3. Seal that qualification stage for scoped approval. Capture fresh before/after
   continuity without publishing configuration or changing services.
4. Qualify and separately approve isolated authenticated metadata refresh and
   exact native resolution. Keep live APT lists/state and installed packages
   unchanged. Bind signed metadata, payload origins/hashes and proposed delta.
5. Review every selected maintainer script, trigger, conffile and service/firmware
   effect. Qualify the exact update, interruption and recovery path. Do not replay
   a consumed foundation installer or broaden a pinned-addition recipe implicitly.
6. Seal the resulting package, rule, restart/reboot and recovery transaction only
   when all prerequisites are satisfied. Obtain fresh operator attendance and
   independent recovery confirmation before execution.

## Snapshot and resolution boundary

`review-maintenance-snapshot.py` seals, checks and submits one bounded collection
implemented by `maintenance-snapshot.py`. It verifies the retained baseline and
review-only candidate inputs, freezes repository sources, validates explicit SSH
authentication and consumes an exclusive receipt before target contact. Native
parser scratch is removed by recorded directory/file identity. Inspect the
transport, partial capture and cleanup outcome even when execution fails.

A complete snapshot requires operator assessment before it can become a resolver
input. Review redactions, symlink targets, hook references, firmware package files,
source/key policy, holds/preferences and automatic package activity. Missing policy
is unresolved; do not silently substitute the old foundation recipe. A snapshot
records concurrency at two points; it does not reserve a future maintenance window.

The existing `resolve-trixie-packages.py` provides isolated APT configuration,
signed Release-to-Packages verification and native/Python solver comparison.
Its existing operation selects pinned foundation roots, not all OS updates. Keep
that path unchanged. Before a maintenance resolution can be sealed:

- Bind an accepted snapshot no older than 24 hours and every source/key/input
  hash. Resolve all effective pins, holds, architectures and package exclusions.
- Construct disposable lists/cache and copied dpkg/extended state; disable all
  hook paths and package execution. Keep live APT lists unchanged. Verify the
  actual native and Python configuration use those isolated paths.
- Resolve all applicable upgrades with native APT and the same Python APT policy;
  retain kept-back/held packages and reasons. Treat additions, removals, downgrades,
  source-built application conflicts and unsupported sources as review findings,
  never silently remove them to obtain an apparently complete plan.
- Require authenticated fresh metadata, reviewed origins/keyrings, release identity
  and validity, signed index hashes and exact selected package versions,
  architectures, payload hashes/URIs and solver agreement. A successful metadata
  download alone is insufficient. Unknown sources require disposition.
- Preserve failed/partial output and owned-workspace identity. Bound network/time
  and output, disable retries, and define evidence export plus exact cleanup before
  approval. Metadata resolution cannot install packages or invoke maintainer hooks.

`review-maintenance-resolution.py` now seals and submits the separate full-update
metadata stage implemented by `resolve-maintenance.py`. It consumes an accepted
fresh snapshot, preserves the reviewed Webmin source/keyring and package-only pin,
and uses the existing authenticated-index primitives without changing the pinned
foundation execution path. Native `apt-get --simulate dist-upgrade` and Python
APT must agree. Retain offered candidates before solving so a solver's changed
candidate does not hide a kept-back upgrade. Removals, additions, downgrades,
source-built NTP/GPSD conflicts and kernel/firmware changes remain explicit findings.

The metadata stage performs no package download/install or service action. All
owned scratch is removed after bounded evidence collection, with cleanup and
unchanged live state required for acceptance. A failed attempt is consumed; uncertain
residue needs scoped inspection. Local signed-APT testing uses the controller's
native toolchain; target-version agreement remains an execution acceptance gate.
EEPROM update-on-boot remains a later payload/boot-effect/recovery decision even
when the resolver selects no EEPROM package. Do not disable that service or infer
firmware rollback from file backups. Exact payload/script/firmware assessment and
update/reboot recovery remain subsequent stages.

## ALSA rule correction

Prefer an inspected, verified corrected package. If unavailable, a separately
reviewed same-basename override can preserve the vendor file. Bind the exact
vendor hash, prior override state, rule-search paths and candidate bytes. Use
root:root 0644, native parser verification and same-directory atomic publication.
Do not trigger devices to test syntax. Qualify activation through the planned
reboot or explicitly review a necessary reload. Retain exact restoration to the
previous override or its absence. Reevaluate a full-file override after vendor
updates and remove it once the corrected vendor rule is accepted.

Local parser qualification does not establish target-version compatibility or
audio behavior. Missing-label errors are not silently exempted from the journal
guard. NTP startup diagnostics use their accepted bounded classifier with fresh
boot, PID, monotonic start and invocation; independent NTP health remains required.

## Package effects before reboot

Review candidate and installed maintainer scripts and the installed trigger
handlers together. A simulated dependency plan does not enumerate script effects.
In particular, an EEPROM package postinst can request updater restart during
configuration; an update-on-boot unit is not a boot-only mutation boundary.
List-only needrestart does not suppress maintainer-script service actions.

Account for initramfs regeneration, certificate hooks and user-service restarts
even when no kernel or server daemon package is selected. Bind helper versions,
hook membership, conffile decisions and existing user-unit state. Do not export
credentials when establishing whether a signin path or remote-access unit exists.

Qualify any temporary firmware inhibit across package configuration and reboot,
including helper enable/unmask behavior and exact restoration. An OS recovery
card, configuration backup or package downgrade does not prove EEPROM recovery.
Retain the distinction between package installation, firmware staging and flashing.

## Installed-effects inspection and containment qualification

`review-maintenance-effects.py` seals the bounded non-mutating collection in
`inspect-maintenance-effects.py`. It reads installed old control scripts, hook
implementations and firmware policy without invoking them. It checks the accepted
resolution's package/configuration identity, protects partial evidence, and repeats
collected input identities before accepting continuity. Symlinks, redactions,
large text and unsupported user-bus state remain explicit gaps. Capture completion
is not approval to update or a guarantee that every referenced helper was resolved.

A persistent `ConditionPathExists=!<owned-inhibit-marker>` on the EEPROM unit is a
candidate containment mechanism. Native local condition evaluation verifies absent,
present and restored-marker behavior only. Before deployment, inspect the installed
helpers, complete unit/drop-ins and conflicting conditions; qualify exact publication,
package-script interaction, reboot persistence, interruption and restoration. Restore
prior files and unit state without inadvertently running the EEPROM updater. A
condition skip does not by itself restore the prior active/exited invocation.
No condition, marker, mask or policy is installed by the inspection stage.

The [containment and recovery contract](EEPROM-MAINTENANCE-CONTAINMENT.md)
separates local helper/condition qualification from live reboot and restoration
acceptance. It explicitly addresses the skipped oneshot state and independent
boot backups when automatic initramfs backup retention is disabled.

## Guarded package stage

The [execution procedure](MAINTENANCE-UPDATE-EXECUTION.md) defines the one-use
backup and package transaction. It verifies independent recovery files before
mutation, preserves source/key/pin and manual/automatic package policy, and retains
persistent controls at its pre-reboot stop. The implementation reuses only the
qualified durable command primitive from repository source, never a consumed
foundation installation. Generated initramfs hashes and native results become
inputs to the separate reboot/restoration review.

## Recovery and acceptance

Keep the peer time source and shared antenna powered. Record configuration and
package state independently of the node. Confirm usable recovery media and its
network identity before approving maintenance. An old card with unknown address
must not be introduced to the service network. Do not promise generic package or
firmware rollback from file backups.

A failed/uncertain transaction is consumed. Inspect its recorded phase and native
dpkg/boot state before a reviewed continuation; never replay the full installer.
Constrain any partial-package recovery to exact reviewed packages and actions.
No unreviewed repair, distribution upgrade, removal, notification or second reboot.

After maintenance, verify the exact package delta, configured/audited state,
remaining updates and explicit deferrals, running kernel/firmware and required
reboot. Verify access, networking, time-source/client health, watchdog ownership,
hardware/storage, journal policy, native ALSA syntax and new-boot diagnostics.
Restore temporary controls exactly and observe affected natural monitoring and
producer cycles. Requalify every affected source/runtime/reset-path proof before
watchdog testing. Preserve historical OBS-02/D1–D5 and bounded OBS-04; do not
start OBS-09 or infer final acceptance from an upgrade command's exit status.
