# Maintained clockmaker, pinup and combined time service

This is the source application workflow selected in
[plan v1.5](ntp-architecture-deployment-plan-v1.0.md#ntpsec-and-gpsd-source-builds).
The [audit](source-build-audit-20261010.md) explains departures from the upstream
guide. Repository helpers are Python 3 adaptations; they do not silently retain
the guide's OS upgrades, account changes, purges, tuning or automatic reboots.
No target build, installation or service acceptance has occurred.

## Clockmaker inputs and behavior

Use `ntpsec/scripts/clockmaker.py` for initial builds and future updates.
Retained application modes support both subcommands and flags: build/--build,
update/--update, install/--install, configure/--config (also --configure),
inspect/--inspect and rollback/--rollback. Single-hyphen aliases such as -build
and -update also work. --config stages application configuration; it no longer
changes the OS. Legacy --mask, --secure and --strip were removed because their
account/security/purge behavior does not belong in this application tool.
Every retained mode has offline dispatch coverage; target functionality still
requires selected-release build and live acceptance.
The build profile is JSON with these required fields:

| Field | Required meaning |
| --- | --- |
| schema / hostname / prefix | 1, approved target hostname, `/usr/local`; target must be arm64 Debian 13 |
| packages | Map each reviewed prerequisite package name to its exact installed version; verified through dpkg before building |
| helpers | SHA-256 map for maintained clockmaker.py, pinup.py and timeservice.py; staged with the applications |
| sources | Exactly gpsd and ntpsec, each with origin, release_tag, 40-character commit, archive path, SHA-256 and explicit options array |

Source archives are either authenticated publisher-release tarballs with an
explicit archive_format/one-component archive_root, or reviewed git-archive
files whose PAX comment identifies the commit. Publisher archives are verified
against signed tags/commits during source preparation; a PAX comment alone is
not authentication. See the
[selected release review](source-release-selection-20261010.md). The build
helper verifies approved hashes and safe archive paths/internal file links,
performs no download/Git pull, and does not bootstrap publisher key trust.

Publisher build profiles additionally require python with executable
/usr/bin/python3, the observed major/minor version and module_directory under
/usr/local/lib recognized by that interpreter's search paths/sysconfig. The
helper binds GPSD's target Python/shebang/module directory and NTPsec's Python
paths/shebang to that one profile; manual override arguments are rejected.
During NTPsec build it adds only the staged source GPSD module directory to
PYTHONPATH. Do not select an APT application candidate or unreviewed optional
build feature as a substitute for selected-release build descriptions.

`build` and `update` use the same unprivileged target-local compile/test/stage
path. They verify all hashes and installed prerequisites, reject conflicting
package applications, create a new private workspace and retain failures/logs.
Compiler/interpreter/SCons version output and complete command output are logged.
Build subprocesses have a 30-minute bound per command; interrupted/timed-out
commands terminate only their own registered process group. An existing output
directory is never reused.

GPSD runs SCons build, check and install with an owned DESTDIR. NTPsec runs
Python 3 waf configure, build, check and install with an explicit destdir.
Installation at this point is native **staging**, not a root/live install.
Unsupported selected-release options/test targets fail; do not skip tests to
make a candidate succeed. Only static output below `/usr/local` is accepted;
etc/var state/configuration output and escaping/broken links are rejected.
The output release.json records source/profile/helper/dependency identity,
kernel, build-log hash and every staged file/link with hash/mode. Required
ntpd, gpsd, ntpq and ntpleapfetch files must be present. Verify selected source
clients, Python modules/manuals and dynamic-library linkage before acceptance.

Invocation shapes below are schematic; variables represent separately reviewed
inputs, not an approved execution bundle:

```bash
python3 -I -B clockmaker.py build --input "$profile" --sha256 "$profile_sha" --output "$candidate"
python3 -I -B clockmaker.py update --input "$profile" --sha256 "$profile_sha" --output "$candidate"
python3 -I -B clockmaker.py inspect --input "$release" --sha256 "$release_sha"
```

`inspect` is read-only and returns target pre-state for candidate destinations.
For an update, also provide `--previous` and `--previous-sha256` for the accepted
old release manifest. Current old files must still match it. Pre-state includes
candidate files and obsolete paths, so a reviewed update can remove old files
that the new release no longer provides.

Root `install` requires the release hash, the separately captured pre-state
file/hash and a new journal beneath a protected root-owned parent. It rejects
package application conflicts and any running ntpd/gpsd; it does not stop them.
The separately approved cutover must stop the pair first. It reads and verifies
all staged bytes before writes, backs up every replaced/removed regular file,
preserves prior link/owner/mode records, rechecks pre-state, atomically replaces
files, removes approved obsolete paths and records post-state. It never runs
source build code as root or copies `/etc/ntp.conf`.

```bash
sudo -n python3 -I -B clockmaker.py install --input "$release" --sha256 "$release_sha" \
    --state "$state" --state-sha256 "$state_sha" --journal "$new_journal"
```

For updates add the same previous-manifest arguments used in inspection.
`copied_not_activated` means files were verified, not that service works. Dynamic
library cache updates, Python import/path checks, users/groups, unit/config
installation and service activation remain explicit actions in the approved
cutover. Do not assume the installed prefix is already on library/Python/PATH
search paths. The script does not apply ldconfig, pip or systemd changes.

Completed installations can be rolled back through a separately authorized
`rollback` using the exact root-owned receipt hash, with both daemons stopped.
It checks unchanged post-state and backup hashes before restoring old
files/links/metadata and removing new files. It retains directories and original
evidence; it does not activate services. Interrupted installs or rollback are
held for inspection and a new recovery definition; never resubmit automatically.

```bash
sudo -n python3 -I -B clockmaker.py rollback --input "$receipt" --sha256 "$receipt_sha"
```

## Configuration and combined service

`clockmaker configure` stages three reviewed inputs without touching the live
host: candidate ntp.conf, a hash-bound combined service unit, and explicit gpsd/
ntpd argument arrays. Its JSON profile has schema 1, hostname, ntp_config and
unit objects (path and SHA-256), plus timeservice with gpsd/ntpd arrays and an
explicit `uart_device` under `/dev/`, verified on the target. Both
source daemon paths must be absolute; GPSD must use `-N`, ntpd `-n`, explicit
`-c /etc/ntp.conf` and a reviewed `-u` user/group. Runtime account/device
permissions and GPSD export behavior remain target-derived inputs. GPSD must
have exactly one `-s 115200` and include the same UART device; speed overrides
are rejected. The baud requirement is fixed, not an unresolved profile input.

```bash
python3 -I -B clockmaker.py configure --input "$configuration_profile" \
    --sha256 "$configuration_sha" --output "$configuration_candidate"
```

The configuration manifest records intended root ownership and explicit modes;
actual candidate files remain owned by the generating operator. Configuration
staging validates hashes/structural inputs, not NTP configuration semantics or
hardware. Deploy `/etc/ntp.conf`, `/etc/ntpsec-timeservice.json` and the reviewed
timeservice unit under the separate approved configuration stage.

The `timeservice.service` template runs `/usr/local/libexec/timeservice.py`,
which first runs `/usr/bin/stty -F <observed UART> raw 115200 cs8 -parenb
clocal -cstopb -crtscts` with a checked exit status and a 10-second timeout. Failure
prevents either daemon from starting. It then launches GPSD and ntpd in
foreground, supervises both, stops the pair
on either exit and returns failure. Systemd restarts the pair after 10 seconds,
with at most three starts in 300 seconds. Operator stops return success and
do not trigger automatic restart. KillMode covers the whole cgroup; shutdown
is bounded. Service runtime JSON must be root-owned, regular and protected.
The template is a proposed unit, not an installed/accepted artifact.

Launching GPSD first is not proof that fix/PPS is already available. Acceptance
requires both process identities/cgroups, individual daemon/device health,
GPS/PPS convergence, IPv4/IPv6 service, required upstream/NTS behavior, metrics
and journals after restart/reboot. Review GPSD listener/socket exposure and
privilege drop explicitly. Disable competing package services/sockets and other
time providers only through the approved cutover. Keep leap maintenance and
Needrestart/Mailrise as their existing independent mechanisms.

## Pinup and future operations

Use maintained pinup to query explicit boot configuration, or edit a confirmed
BCM PPS GPIO with the approved hostname and exact current file hash. Edits
target only `/boot/firmware/config.txt` on the approved arm64 node. It preserves
comments/other overlay parameters, rejects duplicate/conditional PPS overlays
or include ambiguity, adds a missing overlay under `[all]`, backs up the exact
original, atomically replaces it and makes an unchanged GPIO a no-op. An include
requires effective-config review before preparing a supported edit; do not
strip includes to bypass the check. No reboot or PPS acceptance is implied.

```bash
python3 -I -B pinup.py --config /boot/firmware/config.txt
sudo -n python3 -I -B pinup.py --config /boot/firmware/config.txt \
    --hostname "$approved_hostname" --gpio "$observed_gpio" --expected-sha256 "$boot_sha"
```

Review stable upstream releases/security fixes, then prepare new pinned sources,
prerequisites/options and helper hashes. Build with clockmaker update, compare
release/configuration manifests, preserve rollback and approve one node's exact
install/cutover/acceptance bundle. Do not change PPS or regenerate ntp.conf as a
routine software update. The original card and shared antenna-power constraints
still govern rebuild recovery. Source code passing offline fixtures is not
evidence that either selected release compiles or functions on this Pi.
