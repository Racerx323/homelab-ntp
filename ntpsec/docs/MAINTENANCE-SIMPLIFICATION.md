# Consolidated OS maintenance plan

Local assessment, October 27, 2026. Aaron approved preparation of a simpler
maintenance plan. This document authorizes no target access, package operation,
control change, reboot, recovery-card boot or notification. It is not an executable
review. The [governing update gate](ntp-architecture-deployment-plan-v1.0.md#base-os-update-completion-gate)
remains unchanged. OBS-02/D1–D5 and bounded OBS-04 acceptance remain unchanged.

## What went wrong

Base OS updating was omitted from initial commissioning and became a late
prerequisite for recovery testing. The corrective workflow then introduced a
second problem: a bespoke transaction framework whose guards were not adequately
checked against the accepted architecture and actual native interfaces.

The [v1 outcome](/home/aaron/code/.local-evidence/homelab-ntp/current/base-os-update-20261027-v1/outcome.md)
records a requirement for active standalone gpsd.service despite its absence in
the accepted combined timeservice lifecycle. The
[v2 outcome](/home/aaron/code/.local-evidence/homelab-ntp/current/base-os-update-20261027-v2/outcome.md)
records an unreadable Conditions property being treated as an absent condition.
Local tests covered file mechanics and selected rejection branches, but missed
these execution-path assumptions. More tests of scaffolding did not compensate
for those omissions.

Separate approvals accumulated around individual checks even though repository
policy permits one scope containing preflight, mutation, acceptance and recovery.
Exact package review and backups were useful; repeated discovery and compulsory
handoffs were not requirements of the architecture. The pre-reboot split was an
implementation choice: generated artifacts can be assessed against approved
criteria within the same maintenance scope.

## Current evidence and uncertainty

- No package installation or reboot occurred in v1 or v2. No ALSA override was
  published. No firmware updater invocation was requested by those attempts.
- V2 verified an independent 13-file boot/state backup, recreated it on the node,
  checked all 22 payloads, and passed the native solver and ALSA parser.
- V2 temporarily changed APT/EEPROM controls. Cleanup reported success and both
  timer-start commands returned zero. Final path/unit/health state was not captured.
- The consumed stage and backups remain. Preserve them as evidence; do not delete
  the maintenance root or replay an installer to get past its existence guard.
- The reviewed metadata expires October 27 at 17:12:16 CDT. The old executable's
  latest start is 16:12:16 CDT, but both receipts are consumed. This plan renews
  neither deadline nor authorization. A later plan needs fresh authenticated
  resolution if its metadata has expired or its package set changed.

## Keep, simplify and retire

| Control | Disposition and reason |
| --- | --- |
| Peer time service, independent KVM and exclusive recovery card | Keep: provide service continuity and physical recovery. Confirm once at the maintenance window. |
| Sources, keys, Webmin pin, holds and reviewed package delta | Keep: prevent an unintended source/release or package-policy change. |
| Native APT simulation and installation | Use as the package authority. Do not require a second Python solver or a new package installer. |
| Off-node boot/state backup | Reuse only after current hashes and completeness match; refresh changed members before mutation. It is not a full OS or EEPROM rollback. |
| EEPROM inhibit | Keep across installation and the planned reboot because the assessed package requests updater restart. Do not substitute a mask known to be removed by its helper. |
| Package concurrency control | Keep one temporary, owned mechanism; preserve and restore the observed APT timer policy. Never kill another updater. |
| Exact whole-host snapshot equality | Replace with checks on inputs that affect this operation: package policy, boot files, firmware controls, time-service configuration and health. Ordinary PID/invocation turnover is assessed rather than automatically treated as corruption. |
| Mandatory pre-reboot approval | Remove from the proposed successor scope. Approve reboot criteria and recovery before starting; hold only if those criteria fail. |
| One-use receipt and complete logs | Keep a small controller record and durable native logs. Do not create another custom execution engine. |
| Separate routine inspection approvals | Fold cleanup verification and current-state checks into the consolidated preflight. Unexpected material changes remain a stop. |
| Existing runners and archives | Preserve historical artifacts. Do not replay or incrementally extend the consumed installer as the default solution. |

## One proposed maintenance scope

1. **Open the window and reconcile state.** Confirm attendance, peer/antenna
   continuity and recovery access. Inspect the retained stage and exact owned
   control paths, timer/service state, package audit/locks and boot identity.
   Verify current usable NTP. Preserve v2 evidence. Use a new log/working directory
   alongside it; no recursive cleanup and no requirement for an empty parent.
   Unexpected active package work, foreign controls or broken service stops before
   mutation. No separate exploratory session is required for these planned checks.
2. **Establish the native package plan.** Reuse authenticated, reviewed payloads
   while valid, or refresh metadata using the intended sources/pins within an
   explicitly authorized preparation scope. Record the native simulation and
   remaining updates. An exact execution review still binds the selected delta;
   newly discovered packages, removals, downgrades or conffile decisions outside
   that scope require a decision before installation. Do not silently defer EEPROM
   or other updates and then declare commissioning complete.
3. **Prepare recovery and containment.** Verify the independent backup against
   current boot/state files and sufficient root/boot capacity. Record existing
   timer/control policy, establish owned APT concurrency controls and the EEPROM
   marker/drop-in, then verify loaded policy and the false condition without
   invoking the updater. Check through a structured native interface, not a
   substring in systemctl's unprintable rendering. Reject an unknown result.
4. **Run native APT once.** Use the reviewed native simulation/install commands
   with fixed package inputs and explicit conffile policy. Preserve sources,
   Webmin pin and automatic/manual package policy. Retain native package logs.
   The implementation must explicitly account for apt-listchanges, needrestart,
   dpkg triggers and maintainer-script service actions. Do not silently enable
   hooks previously excluded, or suppress all hooks as a generic precaution.
   Preserve normal reporting; no test notification is included.
5. **Assess and reboot within the same scope.** Require successful package audit,
   the approved inventory, readable matching boot/initramfs pairs, unchanged boot
   selection, no unexpected firmware staging, verified inhibition and parser-clean
   ALSA correction. Record newly generated hashes as outputs. When these approved
   predicates pass, perform one planned reboot without another approval solely
   because hashes were generated during installation. If they fail, do not reboot.
6. **Verify and restore policy.** Confirm a new boot, access/networking, usable NTP
   over both address families, combined GPS/PPS lifecycle and selected reference,
   kernel/boot identity, package audit, hardware/journal health, watchdog ownership,
   and normal monitoring/reporting. Verify EEPROM skip and staging. Restore only
   owned temporary controls and the recorded timer policy, reload definitions,
   and verify the resulting state. Do not start the EEPROM oneshot to recover an
   old status label. Restored normal EEPROM policy applies to later boots and must
   be explicit in the execution review. Check remaining updates and record any
   unresolved deferral; accept the base OS only against the governing gate.

## Bounded recovery and decision points

Propose one attended 90-minute window, with a 20-minute package-command assessment
point, 5-minute post-reboot usable-NTP checkpoint and up to 30 minutes of natural
stability observation. These are proposed execution limits, not measured recovery
performance. The five-minute normal-service objective remains; exceeding it during
this deployment test is recorded as a failure to meet the objective, not excused
as success. Use KVM at the failed access/health checkpoint rather than waiting
through repeated automated attempts. Keep the peer and antenna powered.

Before package work, restore only owned temporary controls and report residue.
After package intent, a timeout or disconnect is an uncertain package transaction:
do not kill an unrelated process, rerun APT, configure everything or reboot blindly.
Retain logs and inhibition; assess process/package state under the same approved
bounded status branch. If recovery needs actions beyond its explicit commands,
stop for a new scope. Do not invent an automatic package downgrade path.

If boot artifacts are invalid, remain on the running system. Boot-file restoration
is allowed only by a preapproved branch that checks kernel/modules compatibility;
otherwise use attended recovery. A fallback-card boot must be explicitly included
in the execution review, replace j2 exclusively at 10.1.0.51, and preserve j1 and
antenna power. It cannot reverse an EEPROM flash. Extra reboot/reset attempts and
firmware repair are not implicit recovery permissions.

Only three decision boundaries are needed: exact maintenance approval before
mutation; a material scope change or failed recovery predicate; and final acceptance
from the resulting evidence. Routine successful checkpoints do not require new
approvals. Operator confirmation is required for observed fallback/console events,
not invented from a command return code.

## Remaining local preparation

Prepare one concise operator/controller runbook with exact commands, owners,
expected results, time bounds and recovery branches. Use existing SSH/logging and
backup tools where they already meet the need. Qualify the actual native condition
representation and relevant parser checks; do not build a simulated package manager
or firmware test harness. A structured native condition query is the candidate
interface; target compatibility and cleanup state are checked in the authorized
preflight, not claimed from workstation results.

Resolve the hook policy and metadata freshness before calling that review executable.
A missing fact that affects package selection or authorization must be identified
explicitly; this assessment does not permit a floating upgrade. When the bounded
runbook is qualified, seal one update/reboot/recovery review. Do not prepare another
standalone cleanup inspection by default. No executable successor is sealed here.
