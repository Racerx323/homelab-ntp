# Guarded pre-reboot OS update

This procedure defines the package stage. It does not authorize execution.
The sealed review names the exact node, 22 payloads, input hashes and deadline.
The governing base-OS acceptance gate and OBS-02/D1–D5 remain unchanged.

## Sequence and boundary

`review-maintenance-update.py` freezes the repository implementation and performs
one backup export followed by one installation connection. Both use the established
explicit SSH identity and strict host key. An exclusive controller receipt prevents
replay. No target contact occurs during sealing or checking.

1. Obtain a fresh operator record binding the review hash: attended KVM, peer and
   antenna continuity, exclusive recovery card at 10.1.0.51, no concurrent package
   or reset actions, 90-minute window, and acceptance of the pre-reboot hold.
2. Repeat the accepted read-only input inspection. Reject drift, package activity,
   changed Connect state, existing maintenance controls, inadequate reserves or
   unreviewed boot conditions. Preserve the boot configuration exactly. The
   first-run/resize gates must be absent from the effective kernel command line.
   Do not change early-boot watchdog policy to make the guard pass.
   Require the combined timeservice, Munin node and cron services running;
   standalone gpsd.service must remain not-found/inactive with no PID. Apply
   the same service guard to both retained baseline snapshots before sealing.
   This verifies unit policy, not independent GPS/PPS health; existing NTP
   health and protected configuration checks remain required.
3. Export a closed, deterministic archive containing the eight boot files,
   firmware configuration/command line, dpkg status, APT extended state and vendor
   ALSA rule. Verify every member, size, hash and metadata on the controller;
   fsync and reread the private archive. A missing acknowledgement stops before
   target staging or package mutation. Hashes alone are not backups.
4. Repeat preflight and recreate the same archive on the node. Its hash must
   match the independently stored copy. Create the exclusive root-owned stage
   under `/var/lib/ntp-maintenance`, retain backups and durable phase/command logs,
   and stage only the authenticated payloads. Verify package metadata. Native
   isolated APT simulation must reproduce exactly the reviewed 22 upgrades.
5. Verify the ALSA candidate with the target native parser. Stop the two active
   APT timers and publish owned persistent masks for those timers and their two
   services. Reject existing package activity rather than killing it. Publish the
   persistent EEPROM marker before its atomic drop-in, reload definitions and
   verify the effective condition is false. Do not invoke the updater.
6. Install exact local archives with no download, removal, recommendation or
   source refresh. Isolated APT configuration bypasses ordinary APT hooks; it
   does not bypass maintainer scripts, dpkg triggers or the installed status
   logger. Use noninteractive debconf and retain existing conffiles with
   `--force-confdef` and `--force-confold`. Run needrestart explicitly in list-only
   mode with its accepted no-notification policy. Source/key/pin files stay intact. Restore the exact prior APT extended state
   after the exact no-addition/no-removal inventory check, preserving automatic
   and manual package flags.
7. Require the exact complete package inventory and empty dpkg audit. Verify
   EEPROM skip and unchanged staging/boot policy; confirm kernel files unchanged,
   paired initramfs copies identical and native initramfs listings readable.
   Publish and parse the same-basename ALSA override without reloading devices.
   Require NTP leap/stratum health and unchanged service invocation identities.
8. Stop at **pre-reboot-held**, retaining the EEPROM inhibit, APT persistent masks,
   stage and both recovery copies. This is package-stage evidence, not final
   production acceptance. Review actual generated initramfs hashes and retained
   logs before sealing the distinct reboot/restoration continuation.

The separate reboot boundary is necessary because generated initramfs hashes do
not exist at preparation time. No reboot, firmware tool, panic, notification,
retry, generic repair or recovery-card boot is part of this package-stage review.
Restoring the EEPROM policy later may leave its oneshot inactive; do not invoke
it to recover a status label. A later normal boot applies restored normal policy.

## Recovery and interruption

Both preflight calls retain the inspection and each completed native command
before evaluating its result. Backup failures return structured evidence and a
nonzero transport status; the controller stores that report before rejecting the
connection. No backup acknowledgement or installation follows an incomplete
backup. Installation preflight failures retain the same evidence in the report.
An interrupted transport can still prevent export; retain its raw streams and
hold acceptance. Partial evidence is never a completed preflight or live approval.

Before package intent, remove only owned inhibit controls and persistent masks and
restore the previously active timers. Preserve the stage as consumed evidence.
If ownership changed, stop cleanup and report the exact residue.

After package intent, retain controls on any failure or uncertainty. A native
command timeout or output bound terminates only its recorded process group
(TERM, then KILL after fifteen seconds). Partial dpkg state is held for inspection;
its PID and phase are recorded. The worker has a 1,500-second command deadline
and a separate 120-second pre-package cleanup allowance. A lost controller connection is not permission to rerun installation,
remove containment or reboot. Use a separately approved bounded status inspection
and continuation. Do not run blanket configure-all/fix-broken commands.

`maintenance-recovery.py` verifies closed backups and provides exact boot-file
restoration for a separately reviewed continuation. It checks every current file
before any write, uses same-directory replacement and verifies restored bytes and
metadata. It cannot restore dpkg/package state or EEPROM. Mid-restoration failure
requires remaining on the running system with reboot held. Bind unchanged kernel
and module identity before authorizing boot-file restoration.

Independent boot-file backups are not a full system image. The operator-attested
old card is an exclusive replacement with the same address, not a parallel peer.
Keep j1 and antenna power unchanged. FAT rename/durability, real power loss,
post-reboot NTP/GPS/PPS, watchdog ownership, hardware, journals and natural
monitoring/producer cycles remain live acceptance checks.

## Qualification

The update reuses only the repository foundation worker's durable bounded
command/logging primitive. It does not call or replay the foundation installer.

Local tests use actual private files for archive round trips, byte restoration,
foreign/symlink/hardlink rejection, publication/cleanup and one-use receipts.
Native systemd condition evaluation tests marker presence/absence. The retained
exact helper qualification establishes local helper preservation, not a live
service restart or boot. The retained target solver output tests exact-delta
parsing. The controller bootstrap must reject wrong identity before target work.
No synthetic package installation is represented as native target qualification.
