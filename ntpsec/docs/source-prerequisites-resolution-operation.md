# Source-prerequisite isolated metadata resolution

Prepared October 10, 2026. Preparation is authorized; live execution requires
approval of this replacement bundle's exact hash. This operation supersedes
the unsubmitted APT application selection and installs/builds no application.
The [source release selection](source-release-selection-20261010.md) binds
NTPsec 1.2.5 and GPSD 3.27.5, signed archive/tag review and prerequisite roots.

The bundle includes signed source archives, signatures, signer keys/tag objects,
verification/comparison records, source selection and maintained application
helpers for review and provenance. **None of these application sources/helpers
is executed on the target in this metadata stage.** Execution consumes only
its root metadata worker, inspection helper, exact spec and Python stdin wrapper.
No executable application build profile is prepared: trusted prerequisite
versions and the actual target Python binding must first be observed.

The replacement includes the approved Uputronics requirement: 115200 baud,
GPSD runtime `-s 115200`, and checked supervisor `stty` initialization before
either daemon starts. GPSD 3.27.5 has no declared `fixed_port_speed` SCons
option. These helpers and runtime requirements are bound for review only;
this metadata operation does not initialize a UART or start either daemon.

The revised worker additionally records Python executable/version, sys.path,
sysconfig purelib/platlib and extension suffix after package verification.
The spec adds Python metapackages to verified prerequisites, without inventing
previously observed versions. Missing prerequisites hold before acquisition.
Native solver graphs must reject package application roots, changes and selected
transitive satisfiers, including ntpsec family packages, ntp, gpsd, gpsd-clients
and python3-gps. Supporting runtime libraries remain eligible when reviewed.

## Target, inputs and command

Target only `ama@10.1.0.137`, `j2-svntp1`, Debian 13 Trixie/aarch64, with the
retained console-pinned ED25519 key. The private bundle contains spec.json,
both executors, the inspection helper, exact stdin program, pinned known-host
entry, tests and the preceding inspection/publisher review references.

Execute the bundled workstation launcher through Python with `--bundle` and
the approved `--sha256`. Its manifest contains the full transport template:
one batch, strict-key SSH connection with proxies/reuse/forwarding/local
commands disabled. The remote command is `cd / && sudo -n /usr/bin/python3
-I -B - --controller-epoch @CONTROLLER_EPOCH@`. The launcher substitutes only
its current integer UTC epoch, records it before submission and never edits
the hashed stdin payload. This declared runtime observation checks node time
within 300 seconds of the workstation. No password prompt or sudo fallback.

Require root execution through sudo from the observed ama UID, exact hostname,
OS/architecture/kernel, disabled Python bytecode writes, and unchanged approved
input bytes/ownership/modes, absent inputs and configuration file sets. Query
native/foreign architectures, installed/verified APT, python3-apt, libapt-pkg7.0,
sqv and prior hook/keyring packages; audit dpkg and require inactive APT update
services. Leave timers enabled. Unknown/missing/modified prerequisites fail
before metadata acquisition; do not install a missing binding.

Read the remaining package-listed apt_listchanges Python files as bounded,
redacted data using the corrected inspection helper. Do not execute them or
Debconf, needrestart, notification wrappers or install hooks. Install-hook
acceptance remains a later gate even when metadata resolution succeeds.

## Isolation and permitted effects

Create one unique root-owned `/var/tmp/ntp-metadata-*` directory only after
preflight, requiring a safe root-owned parent and at least 1 GiB free. Record
its device/inode/owner. The top mode is 0711 for the native `_apt` sandbox;
public source/key/index directories use explicit modes and evidence/state
remain protected. No sandbox disablement is permitted.

Copy installed-package status and extended state into protected stage files;
verify the copy against the before hashes. Copy the two reviewed public keys
and byte-bound source files, rewriting only their Signed-By paths to the stage
copies. Original `/etc` configuration, dpkg database, system lists/caches and
timers remain untouched by this execution path.

An explicit APT_CONFIG is loaded first, with empty stage configuration parts
and no main file, isolated state/lists/cache/log paths, blank binary-cache output
paths, no preferences/global trust fallback and `/bin/false` as the dpkg binary.
Both native APT and its Python binding must use this namespace. Check the
effective configuration for every required setting and reject any hook. This
is invocation isolation, not a persistent system-policy change.

Preserve arm64/armhf, recommends and the internal solver. Require normal
authentication/date/expiry checks, disallow insecure/downgrade-to-insecure and
unauthenticated input. Metadata requests have no retries and 20-second HTTP(S)
timeouts. Normal repository name resolution/redirects and native acquisition/
signature methods are included; no production-node/controller access is added.

## Acquisition, simulation and acceptance

Run apt-get `--error-on=any update` once into initially empty owned lists. No
system index or cached fallback participates. Record complete native auth
output, all 26 required architecture/component package-index identities/hashes,
and four clear-signed InRelease documents/identity/date/expiry/hashes. Require
trusted package targets within the stage and the exact reviewed codename,
origin and suite for Debian trixie/updates/security and Raspberry Pi trixie.
Retain signed bytes for independent review. Publisher identities were checked
locally during preparation; the Pi must freshly authenticate its own inputs.

Simulate these groups independently with native apt-get `--simulate --no-remove`:
needrestart; msmtp/msmtp-mta/cron/coreutils/ca-certificates/util-linux;
pps-tools/i2c-tools; the reviewed source-build prerequisite group; munin-node;
watchdog. Source-build roots are build-essential, bison, m4, pkg-config,
python3-dev, scons, libssl-dev, libcap-dev, libseccomp-dev, libncurses-dev,
asciidoctor and python3-serial. Source application roots and selected transitive
NTPsec/GPSD application packages are rejected. Select native
arm64 roots, allowing architecture-all packages normally. No archive download,
upgrade application, package configuration or service activation occurs.

Use the installed, package-verified Python APT binding to mark changes only in
memory. Require its library version and configuration to match native APT.
Compare every changed version/architecture with the native simulation; solver
disagreement or any removal/broken requirement rejects that group's plan.
Traverse selected Depends/PreDepends/Recommends, retaining alternatives and all
currently selected satisfiers (including installed transitive dependencies),
origins, full package records and archive URI/SHA-256 for each changed package.
No commit/fetch method is called. Bound each graph to 1024 versions.

Group failures remain distinct from metadata acceptance. Webmin provenance and
OS/HAT selections remain unresolved; no Webmin source/key is added. A successful
group is a reviewed candidate input, not installation authorization or full
baseline acceptance. Recheck boot, installed state and all approved inputs/file
sets after collection; continuity failure invalidates every proposed plan.

## Evidence, bounds and recovery

The root runner has a 660-second operation deadline; metadata update gets 240
seconds and other native commands at most 60. Capture combined native command
output with a 4 MiB cap. Register command/owned process-group PID in protected
state before waiting; on timeout, excess output or interruption terminate only
that invocation's group. SSH has an 840-second outer bound plus five-second
termination allowance. No uncontrolled retry or process/service kill is allowed.

The client verifies archive/members/payload/host key and its own source, then
registers before submission. Preserve full SSH stdout/stderr/status privately;
parse a separate METADATA_RESOLUTION_EXIT_STATUS marker and retain the JSON
report with hashes. Terminal review is limited to 32 MiB. Missing output or an
interrupted submission requires recovery of that execution, never resubmission.

Before refresh begins, failure cleans only the newly created workspace after
checking its identity; the report preserves cleanup outcome. After acquisition
begins, success or failure retains the owned metadata/evidence directory and
reports its exact path. No stale-system-cache restoration or dpkg repair is
needed or allowed. Partial signed metadata is not accepted; inspect the retained
stage before any later cleanup/retry. Unexpected ownership/residue is a hold.

No package rollback, reboot or old-card swap is included. Preserve the old card,
KVM recovery, primary power and antenna/splitter wiring. The eventual
[installation stage](trixie-package-stage.md) must separately bind trusted
archive hashes, effective kernel/list-only policy, permitted hooks/service
effects, acceptance and physical rollback before approval.
