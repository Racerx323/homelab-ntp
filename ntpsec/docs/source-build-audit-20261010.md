# NTPsec/GPSD source lifecycle audit

Reviewed October 10, 2026. This is a repository audit, not target acceptance.
No node was contacted. Public upstream files were downloaded as data into
private evidence; neither upstream script was executed.

## Decisions and baseline

The [governing plan](ntp-architecture-deployment-plan-v1.0.md#ntpsec-and-gpsd-source-builds)
now requires target-local source builds of both applications, reviewed stable
release tags pinned to exact commits, native waf/SCons installation with file
manifests, and a modernized combined timeservice. Aaron chose to stop both
daemons when either fails and let systemd restart the pair. Configuration and
PPS changes remain separately scoped. APT supplies OS/build/baseline packages,
not NTPsec/GPSD application/client packages.

Sources reviewed:

- [Microserver HOWTO](https://www.ntpsec.org/white-papers/stratum-1-microserver-howto/)
- [clockmaker](https://www.ntpsec.org/white-papers/stratum-1-microserver-howto/clockmaker)
- [pinup](https://www.ntpsec.org/white-papers/stratum-1-microserver-howto/pinup)
- [ntp.conf](https://www.ntpsec.org/white-papers/stratum-1-microserver-howto/ntp.conf)
- [timeservice](https://www.ntpsec.org/white-papers/stratum-1-microserver-howto/timeservice)
- [timeservice.service](https://www.ntpsec.org/white-papers/stratum-1-microserver-howto/timeservice.service)
- [NTPsec build instructions](https://gitlab.com/ntpsec/ntpsec/-/blob/master/docs/build.adoc)
- [GPSD build instructions](https://gpsd.gitlab.io/gpsd/building.html)

The guide's content must be checked against selected source revisions and
Trixie; the web page's modification date is not compatibility evidence.
The downloaded clockmaker SHA-256 is
`67b52fe2bc4c94c61fdc7edd438eaf1799ff6672cfc208d85e7d79fda2e3b1d9`;
pinup is `559eb46968cd242f87fccf7bcbb4d8ad96b25545c931b174bbde1da7f6f27c5b`.
Full upstream files and digest records remain in private evidence under
`.local-evidence/homelab-ntp/source-build-audit-20261010/` in the workspace.
These hashes identify downloaded bytes; they do not independently establish
release authenticity or authorize executing them.

## Upstream defects and required adaptations

| Upstream behavior | Finding and replacement requirement |
| --- | --- |
| Python launcher | `clockmaker` uses Python 2 print statements; Python 3 parsing fails at line 210. Use explicit Python 3, checked subprocess calls and nonzero failures. Do not install Python 2 to preserve this script. `pinup` parses under Python 3 but still needs the changes below |
| Error handling | Many `os.system` statuses are ignored; `(chdir gpsd; git pull)` and the NTPsec equivalent use a nonexistent shell command. Replace moving clone/pull and shell concatenation with reviewed pinned inputs and argument arrays; fail before installation on build/test error |
| Boot/platform detection | Both assume `/boot/config.txt`; clockmaker also edits `/boot/cmdline.txt`. Their revision dictionaries omit observed `c03114` and the primary's 8 GB variants. One detects an SD device, the other a particular UART. Use observed board identity and `/boot/firmware` paths; reject ambiguous configuration instead of guessing a model from a device node |
| PPS writer | `clockmaker` references nonexistent `RaspberryPi.config` before a changed overlay write. Regexes can match commented/conditional entries, mishandle unknown pins and duplicate overlays. `pinup` cannot create a missing PPS overlay and treats an unchanged choice as an error. Use explicit GPIO, hash-bound input, active-section checks, atomic replacement and an unchanged-file no-op |
| Source selection | Clone/pull tracks branch heads; downloaded pinup, configuration and service files are replaced during builds. Pin reviewed stable tags to commits and archive hashes, bind every helper, and prevent build/update from downloading or replacing configuration |
| Build options | GPSD hard-codes `timeservice=yes magic_hat=yes`, driver choices, 9600 baud and stop bits; NTPsec enables `nmea,pps,shm,gpsd`. Validate options against each selected revision and actual Uputronics receiver/UART/PPS evidence. Do not assume all flags still exist or all four refclocks are needed |
| Prerequisites | Old list includes `python-dev`, omits an explicit C toolchain, and mixes build tools, hardware tools and performance tuning. Resolve Trixie build dependencies from both selected revisions; distinguish required headers/tools, optional GUI/docs/tests and runtime libraries. Do not run buildprep or sudo pip blindly on the target |
| OS/config mode | Reconfigures locale/timezone, does dist-upgrade, edits UART/Bluetooth/GPU/nohz/governor/console/udev and reboots. Remove these from the application lifecycle. Boot/hardware/tuning changes require observed inputs and their own approved operation; retain console recovery and PoE fan support |
| Install mode | Installs both applications, creates ntp account, copies `/etc/ntp.conf`, installs a combined launcher, purges stock ntp/autoremoves, changes MOTD and reboots. Stage application output first, produce manifests and preserve configuration. Do not infer that probing `/usr/sbin/ntp-keygen` detects all competing daemons. Review actual users/units and dependencies before a separate service cutover |
| Account/security modes | Assumes a pi account, moves/deletes home content and creates broad passwordless sudo. Guide says root login is disabled, but script writes `PermitRootLogin without-password`. Remove account/SSH changes from clockmaker; use the already established operator access and separately validated security policy |
| Strip mode | Unreviewed purges/autoremove can remove useful board-management dependencies. Remove this mode; no arbitrary baseline cleanup belongs in an application update |
| Combined service | SysV wrapper behind `Type=oneshot`/`RemainAfterExit` does not supervise either daemon. Preserve one combined service, supervise two foreground daemons, stop the pair on either failure and let systemd restart the pair with bounds. Prove process/cgroup ownership and each daemon's health; do not equate active/exited with health |
| Update mode | It preserves the build-directory ntp.conf, but pulls moving heads, rebuilds GPSD too and downloads helpers; a subsequent install copies config and reboots. Modern updates build pinned candidates, preserve live configuration and boot files, retain the old artifacts, and use a separately approved install/service acceptance operation |

## Configuration differences and duplication

The downloaded ntp.conf uses GPSD SHM units 0 (serial) and 1 (PPS), a US public
pool, default IPv4/IPv6 restrictions, loopback query access and
`/var/lib/ntp/ntp.drift`. Its comment claims a preference but it sets no explicit
`prefer`. It has no leapfile, four-week schedule, NTS upstream, statistics or
explicit listener policy. Preserve the established SHM arrangement as baseline
input; do not add a second PPS/refclock pipeline or new offsets blindly.

The existing Debian 11 v2 baseline observed selected `SHM(1)`, stratum 1,
reach 377, both source binaries under `/usr/local/sbin`, and combined
timeservice process ownership. These are historical observations, not current
Trixie acceptance. The guide's `gpsd0`/9600/UART assumptions require receiver
validation; source defaults must not overwrite captured configuration.

Keep one authoritative rendered `/etc/ntp.conf` per accepted host, one combined
service owner, one PPS overlay, one GPSD device path and one leap maintenance
schedule. Do not enable package GPSD sockets/services or a package ntpsec unit
beside timeservice. Inspect and disable competing time providers only through
the approved cutover. Leap maintenance remains the plan's four-week systemd
timer; neither clockmaker nor an additional cron job should duplicate it.
Needrestart remains kernel checks enabled, Pi 4 `-v8` filter, list-only service
reporting and the existing msmtp → Mailrise notification path. The combined
service must appear correctly in reports for both source-built processes.

## Repository, inventory and evidence deviations

| Artifact/surface reviewed | Disposition |
| --- | --- |
| Governing plan v1.4 | Implied repository installation and installed package units; treated HOWTO as conceptual only. Corrected in v1.5, including source provenance, combined ownership, maintenance and rollback |
| `trixie-candidate-recovery-plan.md` | Claimed package-unit discovery for custom timeservice. Corrected to target-local source builds and combined service; historical binaries still must not be copied as Trixie candidates |
| `trixie-package-stage.md`, `trusted-package-resolution.md` | Separate build prerequisites and hardware diagnostics from source applications; retain OS, needrestart, mail, Munin, watchdog and Webmin gates. No APT NTPsec/GPSD installation candidate remains selected |
| `metadata-resolution-operation.md` and private spec/manifest | Prepared archive's ntp_gps roots are ntpsec, gpsd, gpsd-clients, pps-tools and i2c-tools. Marked superseded and unsubmitted. Preserve its bytes/hash; a replacement needs source prerequisites and diagnostic roots only, transitive conflict rejection and a new approval |
| `resolve-trixie-packages.py` / its tests | Previously accepted arbitrary groups; now rejects source application roots, changed packages and selected transitive satisfiers. Launcher rejects old application roots before submission. New regressions cover exclusions; metadata tests do not prove source-build prerequisites or target acceptance |
| `inspect-trixie.py` / tests | APT queries for ntpsec/gpsd/gpsd-clients remain useful conflict/absence observations, not install requirements. Added combined timeservice and competing gpsd.socket to unit queries; existing fixtures retain package query names. A future source inspection must cover absolute binaries/modules/manuals, manifests, both process cgroups and combined service, with source-present/dpkg-absent fixtures |
| `inspect-node.sh` / historical fixtures | Preserve executed collector bytes and Debian 11 baseline tests. A fixture listing ntpsec.service or package paths is parser coverage, not a selected Trixie deployment design. Baseline v2 established actual timeservice ownership |
| Inspection result documents | Oct 8/9 snapshots report absent package names and cached APT ntpsec 1.2.3+dfsg1-8 / gpsd 3.25-5+deb13u2. Preserve observations; those candidates are excluded from the source application lifecycle. Dpkg queries alone cannot prove no source installation |
| `ntpsec/configs/`, leap templates | No accepted per-host ntp.conf or rendered leap unit is present. Do not manufacture a configuration difference or target path. Render after source build/hardware inputs and compare with historical captures; source-installed ntpleapfetch path/options require verification |
| `homelab-server-configs/inventory/prod` | No NTP host membership/component entries were found in the reviewed YAML files. No current accepted NTP inventory exists to update. Draft source revision/prefix/manifest/combined-service facts under its own ownership; do not record APT candidates as installed components |
| CI/pre-commit and test runner | Existing offline NTP suite runs through the shared runner in both paths. New maintained script tests now join that runner; explicit -B prevents bytecode even under isolated Python. Target compile/install, hardware and service convergence require separately approved real-node acceptance |

The primary's current installed versions are not freshly established by this
audit. Reuse protected snapshots with dates and preserve unknowns. No inventory,
DNS or controller change follows from source selection.

## Maintained adaptations

Removing account/SSH/package-cleanup modes does not mean those administrative
tasks are inherently unsafe. The downloaded `--mask` creates an account,
moves/chowns home content and grants unrestricted passwordless sudo, with
user input interpolated into shell commands. `--secure` rewrites SSH settings
without syntax/effective-policy validation, permits root key login while
claiming to disable root login, and deletes the default user's home content
and account. `--strip` purges bluez/triggerhappy and runs unreviewed autoremove.
These implementations assume the old default-account/package layout and can
leave partial changes or remove access/tools. If wanted later, account setup,
SSH hardening and cleanup need their own observed inputs, safe implementation,
reviewed change set, access checks and recovery. They are outside the selected
NTPsec/GPSD source application lifecycle.

Added clockmaker.py, pinup.py, timeservice.py and a proposed timeservice.service
under the repository scripts/templates. The
[maintenance workflow](source-build-maintenance.md) defines their retained
modes, exact input contracts, native staging, protected install/rollback and
configuration/PPS boundaries. Helpers are bound by hashes and staged with each
release. Their tests cover failure/rejection paths and offline installation,
obsolete-file removal and rollback. Selected releases have not been compiled
on the target; source present/dpkg absent inspection and hardware acceptance
remain separate future gates.

## Authenticated release selection follow-on

The [selected release review](source-release-selection-20261010.md) now binds
NTPsec 1.2.5 and GPSD 3.27.5 to verified archive/tag signatures and exact commits.
The helper now supports their publisher archive roots and safe internal file
links. The replacement metadata operation resolves reviewed build roots and
collects actual target Python paths/ABI. Neither selected release has been built
on the target; installation/runtime acceptance remains open.

## Improvements and next inputs

Release sources, stable tags and commit/archive hashes have been selected and
authenticated in the follow-on review. Resolve exact trusted Trixie dependency
versions and actual Python binding before producing the executable build profile. Candidate tools/headers include a C toolchain,
pkg-config, Python 3/development headers, SCons, OpenSSL and capability headers;
ncurses, documentation and other libraries depend on the selected GPSD/NTPsec
features. This is a review checklist, not a complete installation manifest.
Bind Python module destinations/interpreter and dynamic library dependencies;
do not mix APT client modules with a source daemon or modify Debian's managed
Python environment through an unreviewed pip installation.

Use unprivileged builds/tests and native DESTDIR staging; verify required
binaries, tools, modules and manuals before installation. Retain signed-source
review, archive digests, commands, toolchain and full logs. Root deployment
should copy reviewed staged artifacts, not execute build code from a mutable
operator directory. Record collisions, owners, modes, links, installed paths
and rollback copies before any install. Include stale-file removal when later
releases change installed paths. Source applications are outside normal APT
upgrade coverage; define release/security review and a separately approved
clockmaker update for each node, followed by service/hardware/client acceptance.

The Uputronics HAT rate is user-confirmed at 115200 baud. GPSD 3.27.5 does not
declare the guide's `fixed_port_speed` SCons option. The approved adaptation
uses `gpsd -s 115200` and checked supervisor `stty` initialization instead of
the legacy SysV declaration. Failure prevents both daemons from starting.

Keep exact Trixie dependency versions, UART device/PPS/RTC,
runtime UID/GID, source options and service arguments unresolved until supported
by evidence. This audit does not authorize downloads or builds on the Pi,
installation, package mutation, service activation, reboot or notification.
