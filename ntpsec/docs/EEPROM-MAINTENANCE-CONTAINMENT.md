# EEPROM containment and maintenance recovery

This is a proposed maintenance contract, not authorization to install controls,
update packages, invoke the EEPROM updater or reboot. Current evidence and the
next approved stage are recorded in [readiness](PRODUCTION-READINESS.md).
Historical OBS-02/D1–D5 and bounded OBS-04 remain unchanged.

## Boundary and locally qualified mechanism

The selected EEPROM package requests updater restart during configuration. Its
unit runs `rpi-eeprom-update -s -a`; even no-update handling can remove boot staging
files. Keep package installation, firmware staging and hardware flashing distinct.
The captured bootloader timestamp matches the default candidate image, but does
not prove all SPI contents/configuration or VL805 state.

Proposed root-owned persistent controls:

- `/etc/systemd/system/rpi-eeprom-update.service.d/90-maintenance-inhibit.conf`,
  mode 0644, containing `[Unit]` and
  `ConditionPathExists=!/var/lib/ntp-maintenance/eeprom-inhibit`.
- `/var/lib/ntp-maintenance/eeprom-inhibit`, mode 0600 inside a root-owned 0700
  directory. Bind its operation identity; reject pre-existing unowned controls.

Local qualification used the actual captured deb-systemd-helper bytes and exact
vendor unit in an isolated controller root. Native enable/update-state/unmask
operations preserved the drop-in and marker; native systemd condition evaluation
passed absent/present/restored-marker checks. No target, service manager job,
package maintainer script or reboot was exercised. This does not prove target
unit merging, live restoration, crash persistence or hardware recovery.

Before publication, inspect all unit/drop-ins, helper bookkeeping, control paths,
firmware staging and running updater state. Reject unexpected conditions, existing
controls, in-flight updater/package actions or drift. Freeze exact source bytes
and target native versions. The condition governs systemd starts only: it does
not block a direct updater invocation. The approved transaction must exclude
those paths and account for every hook it executes.

## Proposed sequence and interruption handling

1. Confirm operator attendance/KVM, independent peer/antenna power, maintenance
   window and exclusive recovery-card replacement. Record the accepted current
   boot and package state. The five-minute normal-service objective remains;
   deployment-test outage tolerance is a separate decision.
2. Before any package change, create and verify independent recovery artifacts.
   Include exact root and firmware boot artifacts, configuration metadata,
   package database/state and transaction logs. Copy essential recovery material
   off the node and verify hashes at both ends. Directory copies alone are not
   an OS image or a demonstrated package downgrade path.
3. Publish the owned marker first, then the drop-in with same-directory atomic
   replacement and durable writes. Reload definitions without starting/stopping
   the updater. Verify the effective condition and marker ownership. Failure
   before package mutation restores only the exact owned controls and records
   whether the prior service state changed.
4. Keep the inhibit across package configuration and the planned maintenance
   reboot. Verify the drop-in/marker after package helpers and before reboot;
   stop if either changes. Verify no updater invocation or unexpected firmware
   staging. Do not interpret dpkg exit zero as proof that every helper succeeded.
5. After reboot, verify the inhibit survived and the updater was skipped. Verify
   usable NTP/GPS/PPS, networking, monitoring, watchdog ownership, journals, ALSA
   syntax, package audit and boot artifact/kernel identity before restoration.
6. Restore only owned controls under the guarded transaction, with no queued
   updater job or concurrent package operation. Restore exact prior file absence
   or bytes/metadata, reload definitions, and verify the original enable policy.
   Do not start the updater merely to make a status label match.

A condition skip may leave the previously active/exited oneshot inactive.
Restoring its definitions and enable policy is **not** restoring the old
invocation. The execution review must explicitly accept that post-maintenance
state or separately authorize and qualify any updater invocation needed for a
stronger service-state requirement. It must also state that restored normal
policy applies on a later boot; the inhibit is not a permanent policy change.

For interruption after package mutation, retain the inhibit until firmware and
package state have been assessed. No blanket `dpkg --configure -a`, fix-broken
install, EEPROM cancellation, replay or extra reboot. Capture the exact phase and
prepare a bounded continuation. If initramfs generation or boot-copy fails, do
not reboot into unverified artifacts. Restore exact verified boot backups only
under an approved recovery branch, and validate their consistency with the
installed kernel/modules. Removing the inhibit is not recovery from partial dpkg
state or flashing.

## Recovery facts and limits

The installed initramfs policy has `backup_initramfs=no`; automatic `.bak` files
are not the recovery plan. Raspberry Pi hooks can write both v8 and 2712 boot
artifacts despite no selected kernel upgrade. Budget scratch/new/backup space on
both root and firmware filesystems using actual artifact sizes; preserve the
existing boot selection and account for each affected flavour.

Aaron reports the old Debian 11 NTP card works and confirms hostname j1-svntp1,
address 10.1.0.51. It replaces the rebuilt node exclusively; never run both on that
address. This operator attestation resolves addressing, not independently tested
usable-NTP recovery for this maintenance. Keep the peer and antenna powered.
No recovery-card boot, image write or network test has been performed here.

A saved bootloader configuration is not a full EEPROM recovery image. If a guard
fails and firmware may have changed, stop before another reboot and obtain a
specific hardware recovery disposition. Do not promise that an OS-card swap or
package downgrade reverses EEPROM contents. Hardware recovery and post-update
acceptance remain live gates.

## Package-stage execution and later restoration

The accepted successor inspection supplied the referenced trigger receivers,
firmware defaults, shared initramfs tree, configuration, helper bookkeeping and
boot hashes. Exact historical boot-config bytes match those current hashes;
first-run/resize requests are absent from the configured command line. The
execution preflight must also check the effective kernel command line. Early-boot
watchdog continuity is not established or changed by this maintenance.

The [guarded package procedure](MAINTENANCE-UPDATE-EXECUTION.md) requires a verified
independent backup acknowledgement before mutation, persistent automatic-update
masks and the EEPROM inhibit. Local tests qualify exact backup/file restoration
and refusal boundaries; captured native helper and current local native mask
checks qualify file-level preservation. They do not establish hardware recovery.

The consumed package-stage reviews ended before reboot by design. That split is
historical, not a requirement for every successor. The
[consolidated maintenance plan](MAINTENANCE-SIMPLIFICATION.md) proposes one scope
covering generated-initramfs assessment, one reboot, health checks and restoration.
It retains the inhibit through reboot and restores automatic-update policy only
after acceptance checks. The skipped oneshot is not invoked merely to restore a
status label. The effective-condition check still needs native qualification;
the prior unprintable text response is not evidence of condition absence.
