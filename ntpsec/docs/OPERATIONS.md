# Installation, configuration, operations and maintenance

This is the single operations recipe. The
[architecture plan](ntp-architecture-deployment-plan-v1.0.md) owns design,
addresses, schedules, hardware constraints and acceptance requirements.
[HISTORY](../HISTORY.md) records accepted milestones and the next deployment
gate. Machine-readable recipes and manifests are supporting installation
assets, not separate plans. A documented or tested procedure is not permission
to contact a node, deploy files, send a notification or reboot it.

## Current state and remaining work

j2-svntp1 is the renamed former j1-svntp1 physical node, now running Raspberry
Pi OS Lite Trixie on the spare card. Its accepted foundation contains 679 package
records. The retained NTPsec/GPSD source candidate has 159 manifest entries;
both upstream suites, native staging and corrected standalone acceptance passed.
The applications have not been installed live or configured on the new image.

| Stage | State | Next requirement |
| --- | --- | --- |
| Media and bootstrap | Accepted | Preserve original Debian 11 card and primary/antenna power |
| Foundation | Accepted, including pps-tools and bc | Fresh observations and resolution before another node's installation |
| Source candidate | Accepted | Destination/collision inspection and deployment/rollback review |
| Live installation | Pending | Reviewed pre-state, explicit metadata, journal and scoped execution |
| Runtime configuration | Pending | Observed UART/PPS/RTC, accounts, NTP configuration and combined-service cutover |
| Maintenance/reporting | Policy installed; other assets are templates | Leapfile command/reload review, cron/relay rendering and delivery acceptance |
| Node/network acceptance | Pending | Hardware, time, dual-stack clients, monitoring and reboot evidence |

There is no completed unattended end-to-end installer yet. Current package
preparation includes compatibility inputs from the accepted foundation seed;
it must not apply the old 633-record pre-install baseline to the current node.
Some transport workers are bound to j2-svntp1 and consumed stage names. Render
fresh target identities, dates and exclusive stage names before a new operation.
Do not describe those historical specifications as a portable fresh-node recipe.

## Repository assets and private evidence

| Asset | Purpose |
| --- | --- |
| [source-build-recipe.json](../configs/source-build-recipe.json) | Source revisions, archive integrity, build roots/options, prefix and jobs |
| [installation-assets.json](../configs/installation-assets.json) | Exact image/source/package download URLs, sizes, hashes and source signing keys |
| [public-keys](../configs/public-keys) | Public source verification keyrings; no private keys |
| [accepted-source-release.json](../configs/accepted-source-release.json) | Byte-exact accepted target candidate file/link manifest |
| [accepted-packages.tsv](../configs/accepted-packages.tsv) | Accepted target package/version/status reference, not a future observation |
| [asset-provenance.json](../configs/asset-provenance.json) | Vendored reporting-script identity and template adaptations |
| [scripts](../scripts) | Maintained inspectors, preparation, guarded installers and runtime helpers |
| [templates](../templates) | Service/policy artifacts and examples requiring reviewed target values |
| [tests](../tests) | Offline success/rejection, preservation, parser and lifecycle regressions |

Required reusable assets belong in this repo. Large publisher binaries are
obtained through the checked-in verification tool, not copied repeatedly into
operation folders. Keep credentials, raw host captures, recovery-card data and
execution receipts private. The current private index is
`/home/aaron/code/.local-evidence/homelab-ntp/current/catalog.json`; it identifies
verified accepted package/Python/source records by hash and provenance.
The staged target files remain under ama's retained `.ntp-source-build-v5`.

The shared `.local-evidence` directory also serves other projects. NTP cleanup
does not authorize deleting those projects' records. Retain unique observations
and accepted provenance until their purpose/dependencies have been checked.
Do not keep unsuccessful attempts as separate operating instructions. Preserve
useful corrections in current code/tests and this recipe instead.

Accepted continuation helpers and their regressions remain recovery assets;
they do not authorize replaying a consumed operation. Private cleanup/retirement
records identify the explicitly approved removals. A temporary consolidation
checkpoint preserves original prose for review; it is not another active recipe.

## Fetch and verify installation inputs

The pinned image is Raspberry Pi OS Lite arm64 Trixie, October 6, 2026:
compressed size 550466056, expanded size 3078619136. Both integrity values are
in the installation manifest. This is an exact selected image, not a claim
about the latest publisher release. Use the architecture's confirmed Pi 4,
spare-media, original-card and independent-access requirements before writing.
Imager completion/verification evidence does not establish Wi-Fi state or
individual account settings; verify those after boot.

From the repository root, choose only needed groups and a new private cache:

```bash
python3 -I -B ntpsec/scripts/fetch-installation-assets.py \
    --cache "$new_cache" --group image --group foundation --group sources
python3 -I -B ntpsec/scripts/fetch-installation-assets.py \
    --cache "$new_cache" --group image --group foundation --group sources --verify-only
```

Other manifest groups are mail, hardware, munin and watchdog. Fetching them
does not approve installing or activating them. The tool validates all inputs
before cache creation, rejects unsafe paths/URLs and conflicting application
packages, verifies exact size/hash, publishes only complete files, refuses
replacement and checks both source signatures using pinned public keyrings.
It executes no downloaded script or package. Source/key changes need review.

Debian archive hashes were obtained from previously accepted signed Release
metadata and matching Packages records, not inferred from filename/version.
The manifest binds that evidence's integrity identity. Downloads are verified
against the checked-in pins; this does not replace fresh APT dependency,
origin, policy/hook and installed-state checks before mutation. If an exact
asset is unavailable, stop; do not silently substitute a newer version.

## Observe the target before rendering

Use a separately authorized, hash-bound read-only scope. Pin the target's SSH
key, preserve existing access and capture complete stdout/stderr/terminal status
once. Never retry a potentially submitted operation to recover missing output.

| Helper | Contract |
| --- | --- |
| inspect-node.sh | Debian 11/root legacy baseline; fixed local commands and byte-exact captures; missing tools or protected drift remain gaps |
| inspect-trixie.py --inspect | Non-root Debian 13/aarch64 identity, packages, sources, network/storage/services and passive hardware metadata |
| inspect-trixie.py --package-policy | Installed package/source/update/needrestart policy observations |
| inspect-trixie.py --installation-inputs | Read-only inputs for package preparation; no refresh/install |
| inspect-trixie.py --keyring-hooks | Installed authentication and hook source evidence |
| pre-rebuild-health.sh / inspect-ipv6-time.sh | Scoped health/protocol diagnostics; explicit target/client boundary |
| hook-closure-preflight.py / read-debconf-answers.py | Bounded hook/database observations before approving package effects |

Inspectors do not authorize service activation, Wi-Fi disablement, sensors/I2C
transactions, GPS/PPS/RTC access, controller mutation or stress testing.
Recorded source hints and conditional boot snippets are not effective policy.
Do not source captured configurations, execute them or publish raw secrets.

The current rebuilt node was observed at DHCP IPv4 10.1.0.137; that is not its
future fixed service address. Python was observed as 3.13.5 with purelib
`/usr/local/lib/python3.13/dist-packages` and extension suffix
`.cpython-313-aarch64-linux-gnu.so`. New target observations must establish
their own interpreter/ABI, package paths, manager/profile, resolver, accounts,
device ownership, boot configuration and recovery access.

## Package foundation and installation controls

The source recipe includes build-essential, bison, m4, pkg-config, python3-dev,
scons, libssl-dev, libcap-dev, libseccomp-dev, libncurses-dev, asciidoctor,
python3-serial, pps-tools and bc. The reviewed retained-baseline union is 46
new packages: 39 build/test prerequisites and seven needrestart packages.
The installation manifest holds each exact version/architecture/size/hash.
python3-dev replaces the old python-dev name. Git is not needed for these
publisher-archive builds. Target client/manual builds need their target
ncurses/AsciiDoctor dependencies even if those tools exist on the workstation.

pps-tools supplies `/usr/include/sys/timepps.h` for magic_hat/PPS builds and
later diagnostics. bc is required by unchanged upstream regression timing.
Do not use a private header as a substitute for the installed dependency.
Never install APT ntp, ntpsec, gpsd, gpsd-clients or python3-gps, create a global
python alias, use unreviewed pip or purge/autoremove packages as a shortcut.

Resolution uses resolve-trixie-packages.py and its guarded transport helpers.
An isolated metadata refresh uses retained source/key/hook inputs and a private
APT list/cache workspace; it is a distinct approved mutation scope. Require
signature/index/package identity, complete recommendations/dependency closure,
exact native simulation semantics, unchanged inventory and clean dpkg. No
moving suite, arbitrary source or changed existing package is implicitly allowed.

Before installation, inspect apt-listchanges, Debconf backend/answers,
needrestart hooks and package maintainer/config/trigger scripts. Hook wrappers
may tolerate failures and APT success alone is insufficient. Explicitly bound
controls suppress transaction-time mail/restarts, preserve effective policy and
restore automatic-update disposition. Account/device/service effects remain
reviewed package effects. Reject unreviewed update-menus execution.

The preparer takes both hook/answer helpers and the temporary
apt-listchanges-transaction.conf policy from this repo. Historical seed data
provides compatibility observations/package inputs, not the maintained helpers.

prepare-foundation.py prepares a full foundation or bounded supplement from
authenticated evidence; foundation-install.py and run-foundation-install.py
enforce exact inputs, exclusive claim, pre-state and recovery/cleanup. The
current preparer's compatibility seed is the accepted original foundation
bundle plus package plan/accepted receipts; do not delete these while code
still reads them. A fresh node needs freshly captured baseline/closure and a
new full transaction, not reuse of a prior supplement or its expiry.

Installation acceptance requires exact package delta/status, clean dpkg,
protected new inputs, effective needrestart policy, expected hook completion,
restored controls/automatic updates and boot/access/network continuity.
Do not replay installation after an acceptance failure; inspect its terminal
state and prepare only the necessary recovery/acceptance action.

## Source build

NTPsec 1.2.5 and GPSD 3.27.5 are pinned in the source recipe, with signed tags,
commits, publisher archives and signing fingerprints. Both archive signatures
and tags were checked, with archive/Git comparisons: all 688 NTPsec tracked
files matched; 795 GPSD tracked files matched, with seven omitted CI/ignore/AIS
sample files and release-only generated/manual/packaging material. GPSD trust
bootstrap used publisher/project HTTPS and the signed-tag identity; no
independent out-of-band maintainer certification is claimed.

The original clockmaker/pinup HOWTO is an adaptation source, not an executable
installer. Repository Python 3 helpers replace moving pulls, ignored shell
statuses, Python 2, blind OS/account/purge/reboot changes and unsupervised SysV
launching. Upstream clockmaker bytes were SHA-256
`67b52fe2bc4c94c61fdc7edd438eaf1799ff6672cfc208d85e7d79fda2e3b1d9`;
pinup bytes were
`559eb46968cd242f87fccf7bcbb4d8ad96b25545c931b174bbde1da7f6f27c5b`.
Retain attribution/provenance when changing these adaptations.

GPSD must keep timeservice=yes, magic_hat, SHM, clients, Python, ncurses,
manuals, shared libraries and control_socket. Explicit default/tested protocol
options prevent this release's time-service preset from stripping decoders.
Even passing timeservice=no enters its raw nonempty argument guard. SiRF,
Zodiac/EARTHMATE and EverMore support unchanged tests; the daemon suite also
uses other protocols. Their presence does not identify the receiver.

The reported Uputronics receiver is u-blox M8. This release includes the UBX
driver directly; ublox, mtk3301, nmea0183, fixed_port_speed and fixed_stop_bits
are not declared build options. Acceptance requires a u-blox driver listing.
GPSD's runtime `-s 115200` and checked UART initialization enforce the approved
baud rate. Receiver suffix/firmware, active wire protocol and device paths
remain target evidence. control_socket support is needed by gpsfake; it does
not select or activate a production socket.

NTPsec uses SHM refclock, NTS, seccomp, native Python extension and manual pages;
HTML docs/mDNS are disabled. Bind observed target Python module/shebang paths.
Prefix is `/usr/local`, with two jobs for both native build systems. Do not
replace selected source descriptions with APT application dependency lists.

Offline source preparation invocation shape:

```bash
python3 -I -B ntpsec/scripts/prepare-source-build.py \
    --foundation "$foundation_spec" --foundation-sha256 "$foundation_sha" \
    --python-evidence "$python_evidence" --python-evidence-sha256 "$python_sha" \
    --sources "$verified_source_cache" --known-hosts "$pinned_known_hosts" \
    --output "$new_preparation"
```

The preparer verifies hashes, prerequisites/options, safe archive roots/links,
target profile and worker inputs. Publisher archives do not contain a Git PAX
commit comment; authentication comes from the reviewed signature/tag/blob
chain. Only contained links to archive regular files are accepted.

Seal the complete private execution bundle with its specification, every input,
strict launcher, host key, offline tests and review. Approve its exact digest,
target, effect, acceptance and failure path before submission. Prepared data
and old approvals do not authorize contact; edits require a new hash/approval.

Native commands are GPSD SCons build/check/install and NTPsec waf
configure/build/check/install, all unprivileged with an owned DESTDIR. Preserve
full logs and failures, reject existing output paths and stop only owned child
process groups on interruption. Do not skip tests or regenerate expectations.

Waf binary tests replace inherited PYTHONPATH. clockmaker validates and exposes
the staged gps package in the owned build/main/tests/pylib path; preparation
checks the pinned layout. Standalone acceptance also sets staged PYTHONPATH
and LD_LIBRARY_PATH. Isolated imports must resolve inside the candidate.
This prevents live Python installation from being used to satisfy build tests.

Acceptance verifies the full file/link manifest, binaries/clients/manuals/modules,
ABI/imports/linkage, required GPSD/NTPsec generated features, u-blox support and
unchanged inventory/boot/access state. Only static `/usr/local` output is
accepted; etc/var configuration, escaping links and unsafe modes are rejected.
The accepted release manifest binds helper/source/dependency versions, options,
kernel, build log and every staged hash/mode. Acceptance is not live deployment.

## Live installation and rollback

First inspect all intended destinations/collisions under a separately approved
read-only scope. Source-built files may exist even when dpkg has no application
record. Capture destination types, bytes/hashes, links, ownership and modes.
For updates, also compare the previously accepted installed release and include
obsolete destinations that need removal.

Invocation shapes use separately reviewed inputs:

```bash
python3 -I -B ntpsec/scripts/clockmaker.py inspect \
    --input "$release" --sha256 "$release_sha"
sudo -n python3 -I -B ntpsec/scripts/clockmaker.py install \
    --input "$release" --sha256 "$release_sha" \
    --state "$pre_state" --state-sha256 "$state_sha" --journal "$new_root_journal"
sudo -n python3 -I -B ntpsec/scripts/clockmaker.py rollback \
    --input "$installation_receipt" --sha256 "$receipt_sha"
```

An update adds --previous and --previous-sha256 to both inspect and install.
The installer rejects conflicting package applications/running ntpd or gpsd;
it does not stop them. Approve the actual pair cutover separately/in the exact
bundle. Verify all staged bytes before writes, back up replacements/removals,
recheck captured pre-state, atomically install, and record verified post-state.
Do not build as root or copy ntp.conf as part of application installation.

`copied_not_activated` is a file-installation result. Library-cache management,
Python/PATH discovery, runtime users/groups, service/config installation and
activation are explicit reviewed actions; clockmaker does not run ldconfig,
pip or systemd changes. Do not assume `/usr/local` is already discoverable.

Rollback requires the exact root-owned receipt, unchanged post-state and verified
backups with both daemons stopped. It restores prior files/links/metadata and
removes candidate-only files without activating services. Interrupted installs
or rollback need inspection and a new recovery definition, never resubmission.
Retain a tested rollback artifact, not merely an old source revision that must
be rebuilt against changed dependencies.

## Configuration and combined service

Do not create a deployable ntp.conf or select UART/PPS/RTC overlays without
observed target inputs. The approved Uputronics revision on the rebuilt node
is reported as 5.9 (2020), with rv3028 RTC and fixed 115200 baud. Primary-node
HAT/power details still need their own observations. Verify device names,
permissions, PPS GPIO, RTC behavior, firmware/fix and stack/fan compatibility.

clockmaker configure takes a hash-bound profile with schema/hostname,
ntp_config and unit path/hash objects, plus explicit timeservice gpsd/ntpd
argument arrays and uart_device. It stages configuration only:

```bash
python3 -I -B ntpsec/scripts/clockmaker.py configure \
    --input "$configuration_profile" --sha256 "$configuration_sha" \
    --output "$configuration_candidate"
```

GPSD requires foreground -N and exactly one -s 115200 matching the observed
UART. ntpd requires foreground -n, -c /etc/ntp.conf and a reviewed -u account.
Use timeservice.json.example only as a schema example; unresolved @...@ values
must be rendered/reviewed, not installed. Select GPSD listener/socket scope,
export and privilege/device access explicitly. Validate NTP restrictions,
upstreams/NTS, drift/leap paths and SHM GPS/PPS configuration against the pinned
build's manuals and actual device/service evidence.

The proposed timeservice.service runs `/usr/local/libexec/timeservice.py` with
root-protected `/etc/ntpsec-timeservice.json`. The supervisor checks stty
initialization, launches both foreground daemons, stops both if either exits
and returns failure. Systemd restarts the pair with the template's bounded
retry policy; an operator stop succeeds and does not trigger automatic restart.
KillMode covers the whole cgroup. Launch order does not prove GPS/PPS readiness.

Deploy configuration files/units with explicit root ownership/modes and
backups, validate rendered units and NTP syntax, and approve activation/cutover.
Disable competing package services/sockets and other time providers only in
that reviewed operation. Require individual process identities/cgroups,
GPS/PPS convergence, IPv4/IPv6 UDP 123 clients, upstream/NTS behavior, offsets,
jitter, reach, leap state, metrics and journals after restart/reboot.

pinup queries or edits only reviewed `/boot/firmware/config.txt`, with approved
hostname, exact input hash and confirmed BCM GPIO. It preserves comments and
other overlays, rejects conditional/duplicate/include ambiguity, backs up bytes
and atomically writes; unchanged settings are a no-op. It does not reboot or
prove effective overlays/PPS pulses. Reboot and device acceptance are separate.

## Needrestart and notification

The installed policy template retains list-only reporting, kernel checking,
Pi 4/v8 filtering and no built-in notification; ucodehints=0 disables the
processor microcode check requested for this platform. Kernel report status 1
was the accepted report's current-kernel result, not completion of mail/cron.
Do not apply a Pi 5/-2712 filter or disable kernel checking as a side effect.

needrestart.sh is now a byte-exact repo asset vendored from the shared server
configuration project, with provenance in asset-provenance.json. Its cron
example uses flock and the shared daily reporting model; render both recipient
variables and review schedule/timezone before installation. Install the script
at `/usr/local/sbin/needrestart.sh` and rendered cron at
`/etc/cron.d/needrestart_check` with explicit root ownership/modes. These files
have not been deployed on the rebuilt node.

Install the separately reviewed mail group and configure sendmail-compatible
msmtp-mta. msmtprc.example follows the existing LAN Mailrise model with
reviewed host/port/domain; its unauthenticated non-TLS mode requires a trusted,
restricted LAN path. Credentials, if needed for another provider, remain in
protected secret files and are never committed. Protect `/etc/msmtprc` as
root:root 0600 and verify the selected sendmail account/path.

Syntax/pretend-mode checks do not prove delivery. Sending a synthetic or real
notification requires approval for the exact destination/content. Accept the
script, cron failure path and actual Mailrise delivery without unattended
restarts of the combined time service. No notification test was sent during
repository consolidation. Final user-managed passwordless sudo removal is a
separate end-of-project action, not an installer side effect.

## Leapfile, monitoring and routine maintenance

ntpleapfetch.service.in is intentionally unresolved until the installed command,
options, source URL, leapfile path/metadata, retry and reload behavior are
verified. The timer implements the architecture's four-week schedule. Render
the exact command, validate service/timer and approve installation/run before
activation. Do not add an ntpd restart without selected-build evidence.

Webmin needs explicit repository/key/package provenance, scope and authenticated
management acceptance. It is not fetched as an unreviewed extra repository by
the current assets tool. Munin endpoint/plugin configuration is owned by
homelab-monitoring-observability; approve intended poller/allowlist and prove
polling. Watchdog requires observed device/driver, independent recovery and a
separately authorized failure/reboot test. Hardware tools being installed do
not authorize I2C probing, thermal stress or sensor/firmware changes.

Routine checks cover both processes, GPS/PPS selection, reach/leap/stratum,
offset/jitter, dual-stack service/listeners and client responses, NTS/upstreams,
leap expiry, logs, storage, power/fan/temperature, monitoring and notifications.
Maintain the architecture's independent-node design and manual DNAT switching;
verify one active and one standby rule per address family. Preserve RA/global
IPv6 and static DNS VIP ownership through reboot and updates. Do not claim
controller GET data proves NAT state when that API omits the relevant rules.

For an update, review stable source/security changes, update explicit pins and
dependencies, build/test a new unprivileged candidate with clockmaker update,
compare old/new manifests, preserve live configuration and reviewed rollback,
then approve one node's install/cutover/acceptance. Repeat hardware/time/network
checks. Do not change PPS, regenerate ntp.conf or reboot as an automatic update
side effect. Preserve primary-supplied shared antenna power during outages.

## Recovery, records and validation

Old-card recovery restores the original Debian 11 hostname/configuration; it
does not reverse a hardware replacement. Verify physical target/card, access,
GPS/PPS and primary/antenna continuity before any outage. Stop if independent
recovery or antenna-power continuity is unresolved. Failures remain held until
terminal/partial state is inspected and an exact recovery action is reviewed.

Keep one history with accepted state, decisions and next gate, not a retry
transcript. Bundle-local review/specification/manifests and immutable accepted
receipts are necessary evidence assets, not additional active runbooks.
Current evidence carries integrity/provenance; historical claims cannot be
reset. Before pruning, verify dependencies and carry unique facts into the
current catalog/recipe or a required accepted provenance record. Ask when a
unique artifact's value is uncertain; do not delete it merely by age/name.

Offline verification from the repository root:

```bash
ntpsec/tests/run.sh
pre-commit run --all-files
git diff --check
gitleaks detect --source . --no-git --redact --no-banner
```

Keep regression fixtures for rejected parser formats, dependencies, protocol
selection, isolated imports, rollback and exclusive claims. They prevent
recurrence; they are not historical operation runbooks. Check local links,
rendered unit syntax and changed-shell Bash/ShellCheck/shfmt policy. Offline
fixtures and retained observations do not establish new live acceptance.
