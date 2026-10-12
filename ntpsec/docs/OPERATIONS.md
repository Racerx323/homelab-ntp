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
Pi OS Lite Trixie on the spare card. Its accepted foundation contains 686 package
records. The retained NTPsec/GPSD source candidate has 159 manifest entries;
both upstream suites, native staging and mDNS feature acceptance passed.
The 159 native file/link entries are installed and accepted; runtime
configuration and activation remain pending.

| Stage | State | Next requirement |
| --- | --- | --- |
| Media and bootstrap | Accepted | Preserve original Debian 11 card and primary/antenna power |
| Foundation | Original foundation, pps-tools, bc and seven mDNS prerequisites accepted; 686 package records; installation control cleanup complete | Preserve accepted inventory and recheck it before further live changes |
| Source candidate | New mDNS-enabled GPSD/NTPsec candidate accepted; 159 manifest entries; v5 evidence preserved | Preserve accepted build and installation receipts |
| Live installation | Native installation, terminal readback and payload cleanup accepted; copied_not_activated | Prepare library/Python runtime discovery and host configuration for separate approval |
| Runtime configuration | Pending | Observed UART/PPS/RTC, accounts, NTP configuration and combined-service cutover |
| Maintenance/reporting | Policy installed; other assets are templates | Leapfile command/reload review, cron/relay rendering and delivery acceptance |
| Node/network acceptance | Pending | Hardware, time, dual-stack clients, monitoring and reboot evidence |

On October 12, the earlier v2 foundation snapshot passed validation with the same
679 package records, 197 protected inputs and eight configuration directories.
Its root-owned capture stage was cleaned up. The subsequent mDNS requirement
changed the foundation recipe, requiring a new hash-bound capture before metadata
resolution. The v2 capture authorizes no package changes and cannot bind
the revised recipe.
The exact snapshot hash and retained execution outcome are recorded in HISTORY.

The [v3 capture review](/home/aaron/code/.local-evidence/homelab-ntp/current/fresh-foundation-preflight-20261012-v3/review.md)
was approved and executed once against the revised recipe and pinned manifest.
Identity checks, terminal readback and full snapshot validation passed;
the verified root-owned stage was removed. The accepted snapshot retains 679
package records, 197 protected inputs and eight configuration directories.
Its hash and receipts are recorded in HISTORY. The
[corrected snapshot-bound resolution review](/home/aaron/code/.local-evidence/homelab-ntp/current/fresh-foundation-resolution-20261012-v4/review.md)
was approved and executed once. Terminal readback passed the complete resolution
validator: signed metadata, dependency closure, exact native/Python simulation
agreement and full target continuity. Verified workspace/stage cleanup completed.
The accepted delta is seven additions, with no upgrades or removals. HISTORY
records the bundle/report hashes and receipts. The
[seven-package installation review](/home/aaron/code/.local-evidence/homelab-ntp/current/foundation-mdns-install-20261012-v1/review.md)
was approved and executed once. Exact package, dpkg, protected-input, hook,
needrestart and boot/access/network acceptance passed. Controls and the original
automatic-update disposition were restored. The accepted inventory is now
686 records and is mirrored in accepted-packages.tsv from hash-verified terminal
evidence. The old 679-record snapshot/resolution remain executed preparation
records; their baseline no longer describes the target after installation.

The installation review includes the Avahi libraries' ldconfig triggers and
libdbus-1-dev's generated XML catalog maintenance. Successful cleanup restores
temporary controls and the original automatic-update disposition; it retains
the executed privileged stage, claim, backups and logs as recovery evidence.
At the package-installation gate no source build or mDNS runtime activation
had occurred. The subsequent source build was separately approved and accepted
against this inventory; runtime activation remains pending.

Resolution v3 performed its isolated refresh and simulation but final continuity
was held: the resolver left its temporary APT_CONFIG in the worker environment.
Terminal readback and verified workspace/stage cleanup completed. The resolver
now restores the caller's environment on exit; protected collection still rejects
unexpected overrides. The held report is retained evidence, not an accepted
installation input. Accepted v4 supplies the current preparation evidence.

There is no completed unattended end-to-end installer yet. Foundation preparation
now uses a checked-in recipe, fresh target snapshot and accepted combined
resolution report; it reads no historical bundle or acceptance receipt.
Source preparation now renders the target identity, pinned SSH binding and
exclusive stage from evidence and a required operation ID, and binds the
accepted foundation boot. The [mDNS build review](/home/aaron/code/.local-evidence/homelab-ntp/current/source-build-mdns-20261012-v1/review.md)
was approved and executed once on j2-svntp1. Both upstream suites, native staging,
u-blox/features, imports/linkage and explicit NTPsec mDNS acceptance passed;
the accepted release manifest is mirrored byte-for-byte in the repository.
The package inventory and boot/access-service continuity remained unchanged.
Conditional readback was unnecessary; complete terminal evidence was retained.
Live installation/runtime profiles and
hardware/network acceptance remain pending.

## Repository assets and private evidence

| Asset | Purpose |
| --- | --- |
| [source-build-recipe.json](../configs/source-build-recipe.json) | Source revisions, archive integrity, build roots/options, prefix and jobs |
| [foundation-recipe.json](../configs/foundation-recipe.json) | Fresh foundation requirements, observation coverage, package effects, acceptance and recovery |
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
The current accepted target files remain under ama's retained
`.ntp-source-build-mdns-20261012-v1/candidate/stage`. The earlier v5 workspace
is preserved as prior executed evidence.

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
python3-serial, pps-tools, bc, libavahi-compat-libdnssd-dev and avahi-daemon.
The mDNS headers/library use Avahi's DNS-SD compatibility API; Avahi supplies
the runtime responder. The original deployment added 46 packages;
the fresh preparation manifest now pins 56 requirements, including the two
prerequisite roots supplied by that image's baseline. `build-essential` is pinned
directly; the explicit `root_providers` mapping selects Trixie's `pkgconf` for
the `pkg-config` capability. Additions are calculated from the fresh snapshot.
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
An isolated metadata refresh uses fresh snapshot-bound source/key/hook inputs and a private
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
apt-listchanges-transaction.conf policy from this repo. The
[foundation recipe](../configs/foundation-recipe.json) declares requirements,
protected observation coverage, package effects, acceptance and recovery.

prepare-foundation.py prepares a foundation from fresh evidence and verified
cached assets. foundation-install.py and run-foundation-install.py enforce exact
inputs, exclusive claim, pre-state and recovery/cleanup. Historical supplements
remain consumed execution records; they are not preparation inputs.

Fresh preparation follows this sequence:

1. Review the recipe and pinned manifest for the selected image. Fetch/verify
   the foundation group using the checked-in assets tool. Preparation itself
   performs no network access.
2. Separately approve root-owned staging and one read-only snapshot capture.
   capture-foundation-snapshot.py and its peer worker/inspection/hook/answer
   modules must be staged as protected root-owned files. Do not invoke the
   collector as root from the user-owned repository. Bind the recipe hash,
   observed hostname/kernel, SSH endpoint and controller epoch. The collector
   reads the normal Debconf database's five approved answers; it never reads
   the password database. Retain complete output/status and review the snapshot.
3. Resolve one combined foundation group using the recipe's roots, freshly
   authenticated metadata and native simulation. The resolver specification
   must bind hostname, kernel, snapshot_sha256 and the snapshot's protected
   input state. Review origins, dependency closure, recommendations, hooks and
   continuity before accepting its report. A pinned-version conflict requires
   a reviewed recipe/manifest correction; never silently upgrade or substitute.
4. Wrap the unchanged accepted report in resolution.json with schema=1,
   snapshot_sha256, asset_manifest_sha256 and report. Hash-bind both evidence
   files in the offline preparation command below.

Use `run-foundation-preflight.py seal` to prepare the capture bundle from repository
inputs, a pinned `known_hosts`, target identity and a unique operation ID. Its
private output contains the complete review, member manifest and archive hash.
The archive retains the current installation-assets manifest controller-side;
its hash is also bound in the operation specification. Sealing validates the
recipe's pinned requirements offline and does not fetch packages or metadata.
Snapshot staging/collection still uses only the reviewed collector inputs.
After hash-bound approval, `execute --mode collect` creates an exclusive root-owned
stage and collects once. `--mode readback` retrieves the same terminal snapshot;
the checked-in validator must pass before accepting it. `--mode cleanup` requires
retained terminal readback and removes only the verified stage. Keep complete
controller output and the accepted snapshot after cleanup. Busy, incomplete or
drifted staging is preserved for reviewed recovery; never replay collection.
No temporary sudoers fragment is needed with the existing operator-managed sudo.
For helper observations through `/bin` or `/sbin`, validate the root-owned
merged-/usr link and its exact `/usr/bin` or `/usr/sbin` destination, then check
the protected canonical file or its absence. Preserve the requested path in the
snapshot; repeat these checks during installation. Other directory symlinks and
changed alias targets remain rejected.
Resolution is a subsequent sealed operation bound to the accepted snapshot hash;
capture approval does not authorize metadata refresh or package installation.

Use `run-foundation-preflight.py seal-resolution --snapshot PATH
--snapshot-sha256 SHA256 --known-hosts PATH --operation-id ID --output PATH`
to prepare that operation without target contact. The checked-in
`foundation-resolution-policy.json` defines trusted release identities and
verification packages. The tool derives native/foreign architecture, exact root
pins/providers, installed versions, protected inputs and configuration memberships
from the fresh snapshot and repository assets. It reads no historical bundle or
baseline. Execution uses the same one-shot collect/readback/cleanup protocol.
It rechecks the full snapshot before and after isolated APT refresh and one native
simulation; the complete dependency/delta validator must pass after readback.
Live APT lists, packages, policies and automatic-update units stay untouched.
Cleanup removes the exclusive disposable metadata workspace after ownership and
inode checks; signed releases, selected Packages records and complete query output
remain in the controller's private resolution wrapper. A held or interrupted
operation is never replayed.

The snapshot contract is schema=1, recipe_sha256 and collected_epoch; observed
hostname/kernel/boot_id/os/architecture/machine/caller/ssh; complete baseline
package/version/status mapping; inputs with path/hash/owner/group/mode or explicit
absence; directory membership and discovered Debconf/listchanges/keyring/source coverage;
five answers plus their static database structure; foreign architectures,
network and automatic-update state; empty dpkg audit and no active time daemons.
The recipe defines required observations. Source/key/hook snippets alone are
insufficient. The collector rechecks packages, files, directory membership,
boot, network and update state before returning.

```bash
python3 -I -B ntpsec/scripts/prepare-foundation.py \
    --snapshot "$snapshot" --snapshot-sha256 "$snapshot_sha" \
    --resolution "$resolution" --resolution-sha256 "$resolution_sha" \
    --asset-cache "$verified_cache" --known-hosts "$pinned_known_hosts" \
    --operation-id "$new_operation_id" --output "$new_preparation"
```

The preparer computes missing packages from exact pinned requirements and the
observed inventory, including Multi-Arch names from matching Packages/archive
control metadata. It rejects existing-version/status conflicts, incomplete
closure, unexpected native deltas, cache drift, unsafe paths and stale snapshots
before creating output. Expected inventory is the exact baseline plus that delta;
there is no fixed baseline or addition count. Already satisfied prerequisites
stay untouched. Zero additions produce no APT install call; any policy application
still requires a reviewed execution bundle and approval.

The rendered worker/launcher bind the snapshot's hostname, endpoint/key, kernel,
boot and unique stage. They recheck package/input/network/update state before
controls or unpacking. Preparation includes recipe, pins, snapshot, resolution,
provenance, member hashes and standalone regressions. Add the exact review, run
the sealed tests and regenerate the complete manifest/archive before requesting
execution approval. Prepared data alone cannot pass the launcher's sealed-review
input-set check. Old operation approvals never authorize this new bundle.

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

NTPsec uses SHM refclock, NTS, seccomp, native Python extension, manual pages
and mDNS registration; HTML docs remain disabled. Remove the mDNS-disable
option and require `HAVE_DNS_SD_H` in generated `build/config.h`: waf's
header/library detection is optional and can otherwise omit support silently.
The pinned manifest includes the Avahi compatibility library and development
dependency closure. Resolve them against a fresh snapshot before installation.
Bind observed target Python module/shebang paths.
Prefix is `/usr/local`, with two jobs for both native build systems. Do not
replace selected source descriptions with APT application dependency lists.

Keep `--refclock=shm`. GPSD reads the receiver's serial data and PPS, exporting
each through SHM; NTPsec consumes those segments. `nmea` and `pps` enable direct
device drivers in ntpd and are not required to receive PPS through GPSD.
Verify the observed segment assignments before rendering host `ntp.conf`.

Offline source preparation invocation shape:

```bash
python3 -I -B ntpsec/scripts/prepare-source-build.py \
    --foundation "$foundation_spec" --foundation-sha256 "$foundation_sha" \
    --python-evidence "$python_evidence" --python-evidence-sha256 "$python_sha" \
    --sources "$verified_source_cache" --known-hosts "$pinned_known_hosts" \
    --operation-id "$new_operation_id" --output "$new_preparation"
```

The preparer verifies hashes, prerequisites/options, safe archive roots/links,
target profile and worker inputs. The operation ID renders an exclusive workspace;
hostname/kernel and SSH endpoint/key are rendered from the supplied evidence.
Reject malformed identities and ambiguous template bindings. Build execution
also checks the accepted foundation boot ID. Publisher archives do not contain a Git PAX
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
record. Capture destination types, hashes, links, ownership and modes.
For updates, also compare the previously accepted installed release and include
obsolete destinations that need removal.

Use `run-foundation-preflight.py seal-destinations` to prepare an offline bundle
from private copies of the accepted release, build specification and acceptance
receipt, each with an explicit SHA-256, the pinned known_hosts and a unique
operation ID/output directory. The checked-in helper must match the accepted
release; the build inventory must match the repository's accepted package records.
This first-install scope covers only manifest destinations and their protected
ancestors, OS/boot/Python identity, package inventory/audit and safe service/process
observations. It runs no installed application code. Bound each file hash to
64 MiB and each of two comparison passes to 512 MiB within one capture; reject
unsafe parents, special files or continuity drift. No existing files are replaced.

The [current inspection review](/home/aaron/code/.local-evidence/homelab-ntp/current/source-destinations-20261012-v1/review.md)
was approved and executed once on j2-svntp1. Terminal readback passed full
validation: all 159 destinations are absent, with zero collisions, 27 ancestor
records and no active ntpd/GPSD processes. Exact 686-package inventory, boot,
Python and service/process continuity passed. Verified root-owned staging
cleanup completed; the accepted inspection and canonical pre-state remain private.
The native installation consumed this pre-state and passed acceptance. Activation
requires a separate reviewed bundle; the consumed inspection must not be replayed.

For future inspection bundles, use exclusive root-owned 0700 staging with
0600 hash-verified inputs. Submit once with the same
launcher/bundle/hash using `execute --mode collect`, conditionally read the same
terminal record with `--mode readback`, and clean only the verified stage with
`--mode cleanup` after retaining that readback. Readback saves `inspection.json`,
canonical `installation-state.json` and a bound acceptance receipt. Held states,
missing receipts, busy locks, changed inputs or unexpected stage entries prohibit
recollection and require separately reviewed recovery. Historical execution
records and both accepted source workspaces remain preserved. A collision or
active daemon observation is input to installation review, not replacement or
service-change authorization. HISTORY records the exact bundle hash and expiry.

The [native first-install review](/home/aaron/code/.local-evidence/homelab-ntp/current/source-install-20261012-v1/review.md)
was approved and executed once for j2-svntp1. Installation, terminal readback
and payload cleanup passed; all 159 native entries are accepted. Preparation used
only the accepted release/build evidence and destination inspection; no target
contact occurred during preparation. Executed journals, receipts and privileged
code remain retained; only the verified temporary payload was removed. For
future nodes, use `run-source-install.py seal` with private input files,
explicit `--input-hashes`, pinned known_hosts and a unique operation ID/output.
The archive binds the current source recipe, pinned assets, transport, root
helpers, tests, release, build receipt/specification and accepted inspection
receipt/specification/pre-state. Future nodes require their own accepted inputs.
Offline fixtures simulate target ownership independently of the workstation or
CI account; source ownership rejection remains an acceptance boundary.

The wrapper walks the accepted target staging tree with no-follow directory
descriptors, verifies bounded bytes/links and copies them into protected root
staging before calling the accepted native clockmaker installer. Revalidate
absent destinations, protected ancestors, exact packages, boot, Python and
service/process state. Install manifest modes with root:root ownership; retain
existing directories and create missing parents as root:root 0755 with recorded
identities. The root-owned journal keeps baseline metadata and native backups;
this first-install transaction has no prior files to back up. It accepts only
complete installed hashes/links/ownership/modes and target continuity, with
terminal readback revalidation. The result is `copied_not_activated`.

Submit once using `execute --mode collect`, then conditional `readback` with the
same bundle/hash. A held installation may use conditional `rollback` only when
all current destinations are absent or proved accepted installed artifacts,
parent identities match, created-directory contents contain no unrelated data,
and the baseline/target state is intact. Restore absent files and remove only
proved new empty directories. Missing records or ambiguous/interrupted state
require separate recovery review; never replay installation or recovery.
After retained terminal readback and completed installation or verified recovery,
`cleanup` removes only the verified temporary payload. Executed privileged code,
journals, backups and receipts remain private on target and controller. Runtime
linkage/cache discovery, configuration and activation are later reviewed gates.

Invocation shapes for the underlying helper use separately reviewed inputs:

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
UART. ntpd requires foreground -n, -m, -c /etc/ntp.conf and a reviewed -u account.
Use timeservice.json.example only as a schema example; unresolved @...@ values
must be rendered/reviewed, not installed. Select GPSD listener/socket scope,
export and privilege/device access explicitly. Validate NTP restrictions,
upstreams/NTS, drift/leap paths and SHM GPS/PPS configuration against the pinned
build's manuals and actual device/service evidence.

In NTPsec 1.2.5, mDNS is enabled by ntpd's `-m`/`--mdns` startup option,
not by an `ntp.conf` enable directive. The optional `mdnstries 5` entry in
`ntp.conf` sets registration retries and is already the default. Once ntpd
synchronizes, verify its registration journal and browse `_ntp._udp` from
another client on the intended network; verify the advertised host/port and
IPv4/IPv6 reachability. Registration alone does not establish time-service
acceptance. Inspect Avahi service state, interface policy and UDP 5353
multicast permissions; do not enable reflection implicitly. Retain NTP
restrictions and the governed unicast DNS/SRV records.

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

## Optimization evaluation and measurement

[Phase 3A and the proposal register](ntp-architecture-deployment-plan-v1.0.md#phase-3a-evaluate-and-accept-measured-optimizations)
own optimization decisions. Add each future proposal there with a stable ID,
evidence, disposition and owning phase. Keep operational outcomes in HISTORY;
do not create a separate tuning runbook for each experiment.

OPT-001 does not change the current package/build recipe. pps-tools, source-built
GPSD/NTPsec, static network settings, verified UART/PPS overlays and exclusion
of competing time daemons are baseline work in their existing phases. CPU
isolation, performance-governor policy, arm_freq and GPU allocation remain
unadopted candidates until measured on an accepted node. Do not paste the
proposal's APT command or boot/config.txt block onto a target.

For an experiment, prepare a fresh scoped collection and a hash-bound bundle
with exact settings, comparison metrics/window, baseline backups, acceptance,
restoration and any reboot/console recovery. Verify active clocksource, kernel
options, CPU policies, task/IRQ placement and hardware mapping before choosing
controls. Keep the peer and shared antenna power available. Run one change at
a time; allow clock convergence and representative load/thermal cycles. Use
identical logging/sampling for baseline and candidate so instrumentation does
not become the apparent optimization. Preserve GPS/PPS sequence, SHM, source
and client timing evidence separately; they measure different parts of the
path. A kernel PPS pulse report alone is not end-to-end acceptance.

The accepted staged manifest already includes pinned-source ntpviz and its
manual. Plotting is optional and does not authorize deploying that candidate.
Prefer collecting bounded NTP statistics on the node and generating graphs on
the operator workstation. Review statistics paths, permissions, rotation,
retention and transfer; review compatible Python modules and pinned gnuplot
dependencies on the analysis host. Do not install distro ntpsec-ntpviz or copy
ARM binaries/extensions onto a workstation of another architecture. Plot
generation must not add an unreviewed public web service or unbounded log load.

After accepted tuning, mirror the actual persistent settings and metadata into
the maintained repo assets, update HISTORY and repeat affected service/network,
thermal/power and reboot checks. Restore ineffective or inconclusive changes;
record deferred candidates without treating them as incomplete mandatory work.

### Antenna quality, serial calibration and fallback

[OPT-002](ntp-architecture-deployment-plan-v1.0.md#opt-002-indoor-antenna-placement-and-shm-calibration)
reviews indoor/window placement and the proposed SHM/selection changes. Begin
with scoped evidence collection, not global thresholds or a copied time1.
Confirm antenna location/model/mounting, splitter/power mapping and cable
health; identify the actual receiver model/firmware, GPSD endpoint, serial/PPS
SHM assignments and current host configuration. The antenna is shared, so
approve any move or reconnection with both services' impact and restoration.

Use pinned GPSD clients through the running daemon for observation. Do not
open its UART separately or send gpsmon/UBX configuration commands during a
read-only capture. Collect signal-strength units and used/visible satellites,
geometry/fix status, time validity and receiver time accuracy where exposed.
Correlate those records with PPS sequence gaps, SHM timestamps/freshness,
ntpq source state, loopstats/peerstats/clockstats and client timing. Record load,
temperature, capture timing and placement so later comparisons are meaningful.
Protect location/raw receiver records as bounded private evidence. Review
statistics ownership, retention/rotation and compatible off-host plotting
before deploying logging; no logging or receiver access is authorized here.

For calibration, establish a repeatable bias and a reference of known quality.
Document any time1 correction in seconds using sustained measurements.
Serial calibration and PPS/antenna-cable timing corrections are separate paths.
An offset against a PPS-disciplined system can characterize serial timing but
does not independently validate that PPS source's absolute UTC accuracy.
Document correction sign/uncertainty and compare after convergence.

The governed configuration path is `/etc/ntp.conf`. mindist/maxdist are global
selection controls, not receiver sensitivity or loss-of-fix settings. Decide
the serial SHM role and precision from the accepted source-selection profile.
Define accepted GPS/PPS loss, network fallback, stale-sample rejection and
recovery behavior in the runtime acceptance bundle. Preserve truthful leap/stratum reporting and
do not force invalid GPS time to remain selected.

### Serial latency and scheduler experiments

[OPT-003](ntp-architecture-deployment-plan-v1.0.md#opt-003-serial-latency-scheduling-and-irq-affinity)
reviews setserial, FIFO priority and IRQ affinity.
No tuning or restart is selected. Capture actual UART/driver, receiver message
schedule, SHM mappings and full association status before inferring a scheduling
problem. Do not apply an 8250 recipe to PL011 or use rc.local to persist an
unverified flag.

If measurements justify a scheduling experiment, bind observed policies and
priorities for the supervisor, both daemons and relevant threads, plus CPU
placement, IRQ source/allowed/effective affinity, counters and RT limits.
Account for daemon priority changes and service-child inheritance. Do not
substitute a stock gpsd.service override for the combined lifecycle. Test one
change with explicit access/starvation recovery and exact restoration; inspect
the actual Raspberry Pi kernel and any irqbalance policy. An accepted IRQ
setting must identify the device dynamically, not preserve an example IRQ ID.

Any necessary restart belongs to the reviewed timeservice transaction with
before/after state and both daemons' acceptance. Do not restart stock GPSD or
NTPsec units, remove IPC segments or treat a restart as proof that SHM was
cleared. Prefer bounded logging over simultaneously changing serial flags,
priority, IRQ placement and calibration; retain the next-day data privately
with configuration and sampling metadata.

### GPSD HOWTO measurement and network tuning

[OPT-004](ntp-architecture-deployment-plan-v1.0.md#opt-004-gpsd-time-service-howto-tuning)
evaluates the applicable HOWTO proposals. Begin after the combined service and
hardware baseline are accepted. Verify continuous GPSD acquisition and actual
kernel PPS capture, not just the presence of pps-tools. Preserve the existing
UART/PPS ownership and SHM mapping.

For an approved ntpviz comparison:

1. Render `statistics loopstats peerstats`, the observed `statsdir`, and daily
   `filegen` settings into the candidate `/etc/ntp.conf`. Resolve writable
   ownership under the daemon account and service sandbox, rotation/retention,
   storage budget and backup/restoration before enabling capture. Add clockstats
   or receiver/temperature collection only where needed and supported.
2. Keep separate baseline and candidate directories, configuration hashes,
   exact UTC windows, source identities and load/thermal records. Capture
   convergence separately from the comparison window. Use several hours after
   a poll change and comparable daily cycles where temperature is relevant.
3. Transfer bounded logs privately and generate plots on the workstation using
   the matching NTPsec Python modules, ntpviz and reviewed gnuplot installation.
   Use the same `--datadir`, `--starttime` and `--endtime` window for
   `--local-offset`, `--local-jitter`, `--local-stability`, `--peer-offsets`
   and `--peer-jitters` views. Read actual peer identifiers from peerstats.
   Temperature/GPS plots require the documented `temps`/`gpsd` input formats;
   ordinary journal output is not a substitute.
4. Compare serial and PPS peers separately, local frequency/wander and
   independent client timing. Record gaps, loss/fallback and outliers alongside
   distributions. A plot against the disciplined system clock characterises
   that path; absolute UTC claims still require an independent reference.
5. Trial the PPS SHM association's poll interval as one change, preserving its
   unit, calibration and selection settings. Review the accepted interval
   against shorter supported intervals, then restore or retain from measured
   offset/jitter, frequency stability and client results. Persist an adopted
   value in the rendered host configuration and installation manifest.

For network-path trials, bind the observed interface/driver, switch port,
addresses/routes and actual next-hop MAC. Collect IPv4 ARP/IPv6 neighbour
state and packet-delay evidence under a reviewed capture scope. Distinguish
link-layer resolution from upstream server and PPS behavior. A lower network
poll ceiling needs a compatible minimum and the server's rate policy; avoid
changing all upstreams to keep a neighbour entry alive.

Read EEE support/negotiation and software timestamp capabilities using the
observed interface with `ethtool --show-eee` and `ethtool -T`, if available in
the approved collection. An unsupported response closes that trial; enabled
but inactive EEE is not evidence of LPI latency. For an applicable EEE trial,
save the exact advertisement/LPI settings and restoration method before
changing them. Review switch-port changes in homelab-network. Verify link
recovery, IPv4/IPv6 client timing, errors, power/temperature and persistence
after any accepted host or switch policy.

Keep governor, tick and fan-policy experiments separate. Capture supported
controls and actual behavior, use the Phase 3A comparison/recovery process,
and preserve PoE fan safety and peer/shared-antenna continuity. Optional tools,
collectors or persistent policies need checked-in inputs and verified pins
when selected; this review adds no installation dependency.

Software PTP needs a separate server/client/network design before a bundle.
Define the client accuracy goal, timestamp capability, transport/domain,
clock ownership, elections, UTC/holdover reporting and unique SHM allocations
where used. Prevent a server selecting its own redistributed clock or a PTP
servo competing with NTPsec. Do not activate the HOWTO's sample ptp4l service
or feed a new SHM association into the current server profile.

### M8 receiver configuration trials

[OPT-005](ntp-architecture-deployment-plan-v1.0.md#opt-005-uputronics-u-blox-m8-receiver-tuning)
owns receiver-tuning decisions. Prepare a separately approved transaction
after identifying the exact module, firmware, protocol and configuration.
Use GPSD 3.27.5's ubxtool through the reviewed GPSD endpoint and explicitly
selected device. In this tool, `--device` selects a device managed by GPSD;
direct serial access uses `--file` and needs exclusive ownership and the
observed 115200 baud. Any direct-access transaction must coordinate the
combined service's stop/start and client impact. Do not open the UART alongside
GPSD. `MON-VER` establishes `-P`; command support follows that version.

1. Preserve raw receiver identity and affected configuration replies privately,
   with timestamps, message hashes and target binding. Capture NAV5, supported
   GNSS/channel allocation, power mode, NMEA/output configuration, ITFM and TP5
   as applicable. Define exact restoration messages before writing. Preserve
   the primary's shared-antenna power and operate on one receiver at a time.
2. Trial one justified change in volatile state where supported. The pinned
   tool's `MODEL,2` changes the NAV5 dynamic model; `CFG-PMS,0` selects full
   power on supporting receivers. These are mutation inputs for a sealed
   bundle, not approved commands. For composite messages, preserve unrelated
   fields; in particular a partial TP5 command can supply defaults for omitted
   fields instead of retaining the receiver's current values.
3. Read back settings and prove effective behavior. An ACK or lack of errors
   does not establish that a GNSS combination was applied. Compare acquisition,
   valid time, used satellites/accuracy, PPS gaps, serial/PPS SHM, NTP frequency
   and client timing under the OPT-004 measurement procedure. Capture any
   additional fields changed by a predefined power setup.
4. Save only an accepted configuration using reviewed masks and observed
   storage support. Define any required cold start and outage window from the
   actual change and manufacturer guidance. Verify reacquisition, valid UTC,
   PPS/SHM freshness, source selection and service/client recovery; then verify
   persistence across the approved restart/power cycle. Restore receiver and
   host settings if acceptance fails; an SD-card swap alone is insufficient.
5. Check in adopted desired settings, firmware/protocol constraints, complete
   command/message inputs, hashes, acceptance and restoration in the maintained
   installer assets. Keep receiver identifiers, location and raw captures
   private. Include the branch-specific RF-delay calculation and uncertainty
   for any TP5 correction. Until adoption, no new receiver profile is installed.

### System and Ethernet moderation trials

[OPT-006](ntp-architecture-deployment-plan-v1.0.md#opt-006-applicable-system-tuning)
reviews the applicable system proposals. Reuse OPT-001/OPT-003/OPT-004 for
previously reviewed hardware, scheduling and thermal/network controls.

For an approved coalescing trial, capture the observed interface/driver and
kernel, full `ethtool --show-coalesce` output, supported controls, adaptive
state, link settings and packet/error counters. Save the exact baseline and
restoration command before changing one supported setting. Choose the effective
RX delay from this driver's readback and granularity; account for frame
thresholds and adaptive RX behavior. Compare independent client timing,
IRQ/CPU load, PPS/SHM continuity, loss and temperature under matched idle and
busy-link windows using OPT-004 statistics. Keep EEE and CPU/IRQ placement
unchanged for this comparison. Restore if the lower moderation provides no
repeatable improvement or harms time-service health.

An adopted policy must use the observed interface and tool path, supported
parameters and verified restoration values in a maintained installation asset.
Use the supported network-manager mechanism or a reviewed unit with explicit
device readiness and failure reporting. Verify reapplication after reboot,
link reconnect and any manager/driver reset. Do not treat a successful oneshot
start as evidence that the settings remain effective.

For service housekeeping, record effective units, dependencies, enable/mask
states, schedules and actual CPU/I/O/IRQ activity. Select only an unused,
observed component; preserve mDNS, management/access and required maintenance.
Any rescheduling must account for missed-run catch-up and randomisation,
security-update timeliness, mail/reporting and peer availability. Capture
exact restoration and repeat affected service/network acceptance.

For memory tuning, inspect `/proc/swaps`, swap priorities, zram configuration
and backing devices, memory-pressure/paging/OOM records and actual disk I/O.
The retained package list is not proof of active swap topology. Include build
and maintenance peaks in the comparison; do not change memory protection from
RAM capacity alone. Reconcile the observed distribution generator/profile
before rendering persistent changes, and verify reboot state and recovery.

Audio/boot and panic-reboot policies follow their own approved hardware or
recovery transaction. Capture existing settings, boot/access checks and
restoration. Preserve crash evidence and a manual boot-loop recovery route;
do not induce a production panic as a performance test. Keep adopted settings
and their installer/acceptance/recovery inputs in the repo, with live outcomes
in HISTORY.

### Public NTS upstream selection

[OPT-007](ntp-architecture-deployment-plan-v1.0.md#opt-007-public-nts-upstreams-for-arlington-texas)
owns the Arlington candidate shortlist. Provider documentation was checked on
October 12, 2026; none of these associations has been accepted on the rebuilt
node. Keep public-service names in the repo, with actual DNS addresses, paths
and capture results in bounded private evidence. Do not pin a sampled anycast
IP or infer the serving data centre from the certificate or hostname.

Candidate syntax for the pinned NTPsec client is:

```conf
server time.cloudflare.com nts
server ohio.time.system76.com nts
server oregon.time.system76.com nts
```

This is a review example, not an installed host profile. Render the selected
subset and poll/source-selection options alongside observed GPS/PPS, drift,
leap and restriction settings into the approved `/etc/ntp.conf` transaction.
Resolve operator/path/reference diversity before accepting the final set.
Keep normal TLS hostname, chain and validity checks; verify trusted CAs and
sane initial RTC/system time instead of adding `noval`.

Prepare one scoped upstream trial per node with exact candidates, address
families, sampling window/rate, egress checks, acceptance and restoration.
Verify DNS and TCP 4460 NTS-KE, then the negotiated NTP destination and UDP
port. Confirm the node's requests are not redirected back to local NTP by the
network interception policy. Review firewall changes in homelab-network.
Protect raw logs/captures and avoid collecting key material.

Use the pinned daemon's certificate/NTS-KE journal, association data,
`ntpq -pn` and `ntpq -c ntsinfo` with bounded peerstats/client observations.
Correlate authentication counters with each association; aggregate counters
alone do not prove all candidates work. Check authenticated responses and
renewal/recovery, not only TLS connectivity. Keep TLS setup duration separate
from NTP packet delay because key exchange is not performed for every sample.

Compare candidates under the same GPS/PPS discipline, poll profile and capture
windows, including peak/off-peak network load. Record NTP delay distributions,
offset/jitter, root distance/dispersion, loss, leap state and availability.
Verify supported address families and time-service behavior during approved
GPS/PPS or upstream-loss scenarios. Reuse OPT-004 plotting; do not conflate
smaller RTT with independently proven UTC accuracy.

After selection, check in the exact rendered host configuration and desired
upstream/poll/authentication policy as installation inputs. Record accepted
measurements in HISTORY and recheck provider policy, certificate/DNS health,
path quality and source diversity during routine maintenance. No live probe,
configuration or restart is authorised by this documentation.

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
