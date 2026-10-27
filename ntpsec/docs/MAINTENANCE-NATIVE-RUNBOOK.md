# Attended native OS maintenance runbook

This is an ordered, operator-reviewed command runbook, not an automatic installer.
The sealed review supplies the operation ID, fixed paths, exact package manifest,
SSH identity, expiry and recovery scope. Run each block once only after its stated
gate passes. Save complete stdout/stderr and status privately. Never paste this
whole document into a shell. A failed command or predicate stops progression;
use only the recovery branch below. No live action is authorized by this document.

## Controller and transfer

Verify the sealed archive hash and closed member manifest locally. Create an
exclusive controller execution receipt before target access. Record fresh attended
KVM, peer/antenna continuity, exclusive recovery-card availability, 90-minute window
and approval for this exact update plus one conditional reboot. Existing v1/v2
receipts and stages remain consumed. A transport failure is not permission to retry
any mutation. Read-only status/reconnection commands below remain in scope.

Local payload filenames must be APT's canonical cache names, as emitted by the
same-version native `--print-uris` qualification. Preserve package bytes/hashes.
With `--no-download`, arbitrary names such as package.deb can pass simulation but
fail at installation. The sealed package manifest and payload hash list use the
canonical names; do not rename payloads on the target or enable network downloads.

This continuation retains the prior operation's verified controls. Its spec binds
`control_operation_id`, the four mask ownership records and original Conditions
JSON. The new stage contains repository-owned helper code and copied evidence data;
it never imports or executes code from the consumed stage. Inherited controls may
be checked/restored but not republished. The approved operation ID remains distinct.

Use the frozen `ssh-options.json` for every connection: explicit key, no agent,
strict existing host key, no multiplexing or password, target ama@10.1.0.51.
Stream each reviewed Bash block to `cd / && sudo -n /bin/bash -s`; capture both
streams on the controller. Do not use a remote multi-command `bash -c` argument.
The controller invokes the exact argument array through subprocess, not shell
interpolation. Do not call any consumed review runner.

Before staging, read hostname, boot ID, date, package audit/locks, retained
stage ownership and existing EEPROM/APT controls. Require the exact approved
predecessor marker/drop-in and four masks, APT timers stopped/masked, no active
package/updater process and no package lock. Original package/boot/configuration
state must still match the verified backup and before-inventory. The predecessor
failed unit must have MainPID 0 and exit 100; its consumed intent remains intact.
No deletion, replay or blanket unmask is permitted. The sealed preflight also
checks the retained archive identity. Stop on any foreign or changed control.

```bash
set -Eeuo pipefail
export LC_ALL=C PATH=/usr/sbin:/usr/bin:/sbin:/bin
# Resolve every native command before staging or changing service policy.
for executable in /bin/bash /usr/bin/apt-get /usr/bin/busctl /usr/bin/cat \
    /usr/bin/chmod /usr/bin/cmp /usr/bin/date /usr/bin/df /usr/bin/diff \
    /usr/bin/dpkg /usr/bin/dpkg-query /usr/bin/env /usr/bin/find /usr/bin/hostname \
    /usr/bin/journalctl /usr/bin/ls /usr/bin/lsinitramfs /usr/bin/lslocks \
    /usr/bin/mkdir /usr/bin/ps /usr/bin/python3 /usr/bin/readlink \
    /usr/bin/sha256sum /usr/bin/sort /usr/bin/ss /usr/bin/stat \
    /usr/bin/sync /usr/bin/systemctl /usr/bin/systemd-analyze \
    /usr/bin/systemd-run /usr/bin/tar /usr/bin/tee /usr/bin/udevadm \
    /usr/bin/uname /usr/local/bin/ntpq /usr/sbin/ip /usr/sbin/needrestart; do
    if [[ ! -f $executable || ! -x $executable ]]; then
        printf 'Missing executable: %s\n' "$executable" >&2
        exit 1
    fi
done
hostname
cat /proc/sys/kernel/random/boot_id
uname -r
date -Iseconds
/usr/bin/dpkg --audit
/usr/bin/systemctl --no-pager show --property=Id,LoadState,ActiveState,SubState,MainPID,UnitFileState timeservice.service gpsd.service munin-node.service cron.service apt-daily.timer apt-daily-upgrade.timer apt-daily.service apt-daily-upgrade.service rpi-eeprom-update.service
/usr/bin/systemctl --no-pager --no-legend list-jobs
/usr/bin/lslocks --output COMMAND,PID,PATH
/usr/bin/stat -c '%F %U:%G %a %n' /var/lib/ntp-maintenance /var/lib/ntp-maintenance/base-os-update-20261027-v2
/usr/bin/find /etc/systemd/system/rpi-eeprom-update.service.d -maxdepth 1 -ls
/usr/bin/ls -ld /var/lib/ntp-maintenance/eeprom-inhibit /etc/systemd/system/apt-daily.timer /etc/systemd/system/apt-daily-upgrade.timer /etc/systemd/system/apt-daily.service /etc/systemd/system/apt-daily-upgrade.service
/usr/bin/busctl --system --json=short get-property org.freedesktop.systemd1 /org/freedesktop/systemd1/unit/rpi_2deeprom_2dupdate_2eservice org.freedesktop.systemd1.Unit Conditions
/usr/local/bin/ntpq -n -c 'rv 0' -c peers
```

Retained controls are assessed from their metadata and bound ownership records. The combined
timeservice, cron and Munin node must be running; standalone gpsd.service remains
not-found/inactive. NTP requires leap=00, stratum=1 and the accepted PPS selection.
No inference of healthy GPS from an absent standalone unit is permitted.

Run the complete frozen health.sh on stdin and the controller client-check.py
before creating any stage. Preserve both streams and each exit status even when
health stops early. Require the baseline health gate in addition to block-01;
path availability alone does not establish command compatibility or host health.

Create only the new root-owned 0700 stage named in the sealed review. Reject any
existing path, including a dangling link. Transfer the exact archive there using
stdin and exclusive file creation; check its SHA-256 before extraction. The archive
contains only regular relative files with a closed member list; no symlinks,
absolute paths or parent traversal. Extract within that private directory, without
preserving archive ownership. All commands below run there as root with umask 077.
The v2 stage is never an output directory. The sealed review gives exact transfer
commands and archive/member hashes.

## Current inputs, backup and native plan

`spec.json` binds the unchanged boot, packages and 13-file recovery manifest.
`before-inventory.tsv`, `after-inventory.tsv`, `backup.sha256`,
`protected.sha256`, `package-paths.txt` and `payloads.sha256` are frozen inputs.
The inventory excludes volatile installed-size/output formatting; it includes
package, architecture, version and dpkg state. Expected config-files entries stay.

```bash
set -Eeuo pipefail
umask 077
sha256sum --check payloads.sha256
sha256sum --check backup.sha256
sha256sum --check protected.sha256
/usr/bin/systemctl --no-pager --no-legend list-units --all 'user@*.service' > user-managers-current.txt
diff -u user-managers-expected.txt user-managers-current.txt
/usr/bin/systemctl --user --machine=1000@.host --no-pager show --property=Id,LoadState,ActiveState,SubState,UnitFileState,FragmentPath,DropInPaths rpi-connect.service rpi-connect-signin.path rpi-connect-signin.service > connect-current.txt
diff -u connect-expected.txt connect-current.txt
readlink /etc/localtime > timezone-current.txt
diff -u timezone-expected.txt timezone-current.txt
/usr/bin/dpkg-query -W '-f=${Package}\t${Architecture}\t${Version}\t${db:Status-Status}\n' | LC_ALL=C sort > inventory-before.tsv
diff -u before-inventory.tsv inventory-before.tsv
df -B1 / /boot/firmware
df -i /
/usr/bin/lsinitramfs /boot/initrd.img-6.18.50+rpt-rpi-v8 > initramfs-before-v8.txt
/usr/bin/lsinitramfs /boot/initrd.img-6.18.50+rpt-rpi-2712 > initramfs-before-2712.txt
python3 -I -B - <<'PY'
import importlib.util,json,pathlib
s=importlib.util.spec_from_file_location('recovery','recovery.py');r=importlib.util.module_from_spec(s);s.loader.exec_module(r)
spec=json.loads(pathlib.Path('spec.json').read_text())
raw=pathlib.Path('/var/lib/ntp-maintenance/base-os-update-20261027-v2/recovery.tar.gz').read_bytes()
r.verify_backup(raw,spec['backup'])
assert r.sha(raw)==spec['independent_backup_sha256']
for name,expected in spec['backup'].items(): assert r.read(name)[1]==expected,name
root,boot=__import__('os').statvfs('/'),__import__('os').statvfs('/boot/firmware')
print(r.reserve(root.f_bavail*root.f_frsize,root.f_favail,root.f_files,boot.f_bavail*boot.f_frsize,spec['backup'],sum(p['size'] for p in spec['packages'])))
print(r.boot_conditions(pathlib.Path('/proc/cmdline').read_bytes(),r.read('/boot/firmware/config.txt')[0]))
PY
/usr/bin/busctl --system --json=short get-property org.freedesktop.systemd1 /org/freedesktop/systemd1/unit/rpi_2deeprom_2dupdate_2eservice org.freedesktop.systemd1.Unit Conditions > conditions-held.json
python3 -I -B check-maintenance-conditions.py inhibited < conditions-held.json
mapfile -t packages < package-paths.txt
APT_CONFIG="$PWD/apt.conf" /usr/bin/apt-get --simulate --no-download --no-remove --no-install-recommends --no-install-suggests -y install "${packages[@]}" > simulation.txt
/usr/bin/udevadm verify candidate.rules
```

Require the exact 22 reviewed upgrades, no additions/removals/holds/kept-back
changes, unchanged metadata/payload validity and native parser success. The controller
must reverify its independent v2 recovery archive and record acknowledgement of its
hash before package intent. No new backup is needed if every bound file still matches;
any mismatch stops for assessment, not silent expansion of the package transaction.

Use the frozen narrow APT configuration already qualified by v2's native simulation.
It has no network sources and uses the reviewed local payloads. The three known APT
hook files are deliberately omitted for this transaction: apt-listchanges (no UI or
changelog mail), debconf preconfiguration (configuration still runs noninteractively
inside dpkg), and needrestart (run explicitly in list-only/no-notification mode).
No maintainer script, dpkg trigger or installed status logger is disabled. Preserve
all live source/key/pin files. Do not substitute a default APT environment that
silently reintroduces hooks. This is an explicit fixed-input native transaction,
not a replacement package manager or a second solver.

## Containment, one package invocation and pre-reboot gate

Record current Conditions JSON and compare the held control policy to its bound
predecessor evidence. The original pre-containment Conditions JSON is a separate
frozen input for restoration. The file helper verifies the inherited marker and
four masks against copied ownership records without changing them. A mismatch
holds before package intent. Do not stop/start or republish already-held controls.

```bash
set -Eeuo pipefail
python3 -I -B maintenance-native-files.py check
/usr/bin/busctl --system --json=short get-property org.freedesktop.systemd1 /org/freedesktop/systemd1/unit/rpi_2deeprom_2dupdate_2eservice org.freedesktop.systemd1.Unit Conditions > conditions-inhibited.json
python3 -I -B check-maintenance-conditions.py inhibited < conditions-inhibited.json
if /usr/bin/systemd-analyze condition 'ConditionPathExists=!/var/lib/ntp-maintenance/eeprom-inhibit'; then
    exit 1
else
    test "$?" -eq 1
fi
/usr/bin/systemctl --no-pager show --property=ActiveState,MainPID apt-daily.service apt-daily-upgrade.service rpi-eeprom-update.service
/usr/bin/lslocks --output COMMAND,PID,PATH
```

Require no package/updater process or job, owned marker/drop-in unchanged, and
structured non-trigger negated marker condition present. Cached condition state
alone proves neither current file presence nor a service skip. Do not start the
EEPROM updater to test the condition. Recheck expiry immediately before package
intent. A partial containment failure follows the owned cleanup branch below.

Run the sealed `package-command.sh` once through the exact `systemd-run` command
in the review. It invokes native APT with the frozen local payloads, noninteractive
conffile policy, no download/removal and no retries. The transient oneshot has
Restart=no, no package-killing timeout, RemainAfterExit=yes and durable stdout/stderr
in this stage. It is not enabled for boot. An exclusive package-intent file prevents
relaunch. At 20 minutes inspect the job; do not terminate or replay APT. On transport
loss reconnect only to read that same unit, process and logs. Uncertain package
state holds reboot/cleanup. The 90-minute window is an operator handover limit,
not permission to kill dpkg.

Require Result=success and ExecMainStatus=0. Then:

```bash
set -Eeuo pipefail
/usr/bin/dpkg --audit
/usr/bin/dpkg-query -W '-f=${Package}\t${Architecture}\t${Version}\t${db:Status-Status}\n' | LC_ALL=C sort > inventory-after.tsv
diff -u after-inventory.tsv inventory-after.tsv
sha256sum --check protected.sha256
/usr/bin/systemctl --no-pager --no-legend list-units --all 'user@*.service' > user-managers-current.txt
diff -u user-managers-expected.txt user-managers-current.txt
/usr/bin/systemctl --user --machine=1000@.host --no-pager show --property=Id,LoadState,ActiveState,SubState,UnitFileState,FragmentPath,DropInPaths rpi-connect.service rpi-connect-signin.path rpi-connect-signin.service > connect-current.txt
diff -u connect-expected.txt connect-current.txt
readlink /etc/localtime > timezone-current.txt
diff -u timezone-expected.txt timezone-current.txt
/usr/bin/systemctl --no-pager show --property=ActiveState,ConditionResult,MainPID rpi-eeprom-update.service
cmp /boot/initrd.img-6.18.50+rpt-rpi-v8 /boot/firmware/initramfs8
cmp /boot/initrd.img-6.18.50+rpt-rpi-2712 /boot/firmware/initramfs_2712
/usr/bin/lsinitramfs /boot/initrd.img-6.18.50+rpt-rpi-v8 > initramfs-after-v8.txt
/usr/bin/lsinitramfs /boot/initrd.img-6.18.50+rpt-rpi-2712 > initramfs-after-2712.txt
/usr/bin/sha256sum /boot/initrd.img-* /boot/firmware/initramfs* > generated-initramfs.sha256
/usr/sbin/needrestart -r l -b
/usr/local/bin/ntpq -n -c 'rv 0' -c peers
```

Require empty audit, exact inventory, both expected boot flavours with init and
rpi_wd contents, unchanged kernel/config/source/pin policy and no new firmware
staging. Restore exact original APT extended-state bytes from the verified backup
using same-directory atomic replacement only after that inventory succeeds. Verify
restored ownership/mode/hash. Run `python3 -I -B maintenance-native-files.py
publish-alsa-and-flags` for these file operations. Publish the bound ALSA candidate as root:root 0644
with same-directory atomic creation; reject an existing override. Re-run native
udevadm verification; do not trigger devices. The review supplies exact file commands.

Verify owned inhibition and structured Conditions again, and confirm inactive
EEPROM unit with ConditionResult=no and MainPID=0. No direct updater command is
allowed. Inventory current boot files against the frozen path list; unexpected
files or mismatching generated copies stop reboot. Record all output hashes and
copy logs/boot inventory off-node. None of these success gates requires a new
approval; failure requires assessment within the recovery boundary.

## One reboot, health and restoration

Create the exclusive reboot-intent record and export it, then issue exactly one
`systemctl reboot`. A lost SSH connection is not proof of reboot or permission for
a second reboot. Observe KVM; reconnect read-only for up to five minutes using the
same pinned identity. A changed boot ID must be established before acceptance.
Use the sealed health command list before reboot, after reconnect and at +5/+30
minutes; retain complete native output. The acceptance table in the review covers
NTP, GPS/PPS, address/listeners, package/boot identity, journals, hardware, watchdog,
normal producer/monitoring state and the EEPROM skip. Do not run a synthetic job,
plugin, test notification or panic. Master-side graph acceptance is outside this
node maintenance scope; do not silently claim it from node health.

After successful post-boot checks restore only the bound predecessor's marker/drop-in and
four inode-verified masks through `maintenance-native-files.py restore`, reload definitions, start the two originally active APT timers,
and verify active/enabled timer state, original unit policy, absence of maintenance
conditions and no pending updater job. Do not invoke the updater to restore its
old active/exited label. Later normal boots apply the restored EEPROM policy.
Retain all stages and backups; no recursive cleanup is authorized.

## Recovery branches

Before package intent: read the exact paths and bound predecessor marker, remove only
verified inherited controls, reload definitions, restart the original timers and verify state.
If a partial publication left only the owned marker, the frozen recovery helper
handles it; if ownership or file membership differs, leave it and report residue.
Only unlink APT masks proved to match the inherited /dev/null ownership records;
never call broad unmask or remove the maintenance root.

After package intent: read the unique transient unit, PID, journal and durable logs,
dpkg audit and lock state. No stop/kill, configure-all, fix-broken, automatic package
retry or boot-file restoration is authorized. Keep inhibition until package/boot
state is understood. If recovery requires an unlisted action, stop for a new scope.

At a failed five-minute reconnect/usable-NTP checkpoint use the attended KVM.
One exclusive old-card fallback is authorized only after Aaron reports the failed
boot/health state and chooses that branch. Shut down gracefully if possible; if
unresponsive, Aaron may remove power only from j2's identified PoE port, replace
its card, and power that port once. Keep the new card offline. Old hostname is
j1-svntp1 at 10.1.0.51; do not override SSH host-key checks or remotely operate the
old image under the new identity. Record KVM service observations. This is service
fallback, not new-image acceptance or EEPROM rollback. No repeat power cycling,
firmware write or recovery-image modification is included.

If the new image boots but health fails, keep it running for read-only diagnosis
unless the explicit fallback is chosen. At 90 minutes hand over retained evidence
and remaining controls. Do not force completion or silently extend the operation.
The five-minute objective remains an acceptance criterion; deployment outage
tolerance does not convert a missed objective into a pass.
