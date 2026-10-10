# Trixie trusted metadata and package-resolution definition

Prepared October 10, 2026. Definition-only: no target contact, metadata refresh,
package resolution or download is authorized. The previous
[isolated metadata/resolution operation](metadata-resolution-operation.md) is
superseded by the source-build decision. Its retained preparation used the
[keyring/hook results](keyring-hooks-results-20261010.md). This document defines
replacement inputs, permitted effects and acceptance; it is not an instruction
to run APT now.

## Source-build correction

The previous isolated bundle remains retained but superseded and unsubmitted.
See the [source-build audit](source-build-audit-20261010.md). A replacement must
reject roots and any selected dependency/recommendation introducing conflicting
NTPsec/GPSD application/client packages. The revised executor and launcher enforce these exclusions; a replacement
bundle must bind their revised bytes and regression tests. Source archives, scripts, native build
options and installed-file manifests need their own review; APT cannot resolve
them. The [source-prerequisite replacement operation](source-prerequisites-resolution-operation.md)
is now defined from the authenticated release review; execution still requires
its own exact hash approval.

## Required inputs before bundling

Use the rebuilding `j2-svntp1` only, with observed arm64 native architecture and
armhf foreign architecture preserved. Bind its identity/host key, source and
policy files, both source-referenced .pgp keyrings, verified signer identities,
keyring package provenance, installed APT/manual evidence and reviewed update
hooks into one exact operation. An HTTPS checksum or a local dpkg checksum
alone cannot accept archive trust.

Resolve how the installed APT build verifies signatures, and whether its
installed manuals support every selected option. Require sane node time and
normal signature, date and expiry checks. Do not disable authentication,
Check-Date or Check-Valid-Until; reject trusted=yes, insecure/downgrade-to-insecure
overrides, unauthenticated packages and unexpected release-identity changes.
No new source/key or Webmin repository may be added by this stage.

The completed keyring inspection matched captured primary-key identities to
publisher resources locally; fresh archive signatures are still unverified.
Include a bounded read of the observed apt_listchanges Python implementation
in the next bundle's preflight, rather than rerunning the consumed inspection.
Debconf source redaction and incomplete install-hook closure continue to block
installation. Review these separately from update hooks: the metadata/solver
stage must not execute dpkg pre-install hooks. Any missing input material to
metadata safety must fail preflight before refresh.

Review APT update hooks separately from dpkg install hooks. Name every permitted
metadata-refresh side effect, including configured helper invocations. Resolve
automatic APT activity/lock contention and noninteractive administrative access
without assuming sudo -n works. Capture before-state for owned metadata/cache
paths and package status. No timer disablement or generic hook suppression is
implied; any necessary policy change needs exact inputs and authorization.

## Resolution roots and baseline coverage

Resolve each group separately against one accepted fresh metadata snapshot.
The manifest must retain requested architecture, selected versions, source/
origin/suite, alternatives, recommends policy, all transitive dependencies,
changes to already installed packages, proposed removals and package integrity
metadata. Package queries in prior collectors are not install requests.

| Group | Requested roots | Ownership/constraint |
| --- | --- | --- |
| needrestart bootstrap | needrestart | Establish enabled kernel checks and list-only policy before bulk updates; this stage only resolves packages |
| Notification transport | msmtp, msmtp-mta, cron, coreutils, ca-certificates, util-linux | Preserve the common Needrestart/Mailrise design; installation, recipients, scheduling and mail acceptance require later approval |
| Hardware diagnostics | pps-tools, i2c-tools | No APT NTPsec/GPSD application/client packages; no device or service activation |
| Source build prerequisites | Roots in the [selected release review](source-release-selection-20261010.md) | Resolve compiler, interpreter, build-tool, header and runtime-library inputs separately; selected versions/hashes await fresh trusted resolution |
| Munin endpoint | munin-node | Owning component supplies configuration and later poller acceptance |
| Watchdog | watchdog | No activation until independent recovery and a controlled test are approved |
| Webmin | webmin | No cached candidate was returned; keep unresolved until separately reviewed source/key/provenance inputs are authorized |
| OS/firmware and HAT support | Explicit selections from the observed build and hardware only | Do not request legacy Raspberry Pi kernel packages or assume fancontrol/lm-sensors are required; any update/support selections need their own reviewed manifest |

Keep recommends enabled unless a documented group-specific decision approves
otherwise. Do not substitute an optional alternative merely to clear an error.
Installed status is not proof of version compatibility with the fresh solver
result. Preserve the complete solution, rather than only the root package or
the five missing needrestart Perl modules. Webmin and hardware unknowns prevent
claiming that the whole governing baseline is installation-ready.

## Proposed command family and acceptance

The replacement executor uses an isolated APT configuration, copied installed
state and initially empty owned lists. Its exact settings, commands, runtime
clock observation, effects and recovery are in the operation above. The system
APT policy/cache is not modified. The installed native/Python APT and metadata
are validated before accepting a plan; unsupported prerequisites hold execution.

The executor must render exact native commands from the reviewed local
manuals and policy. The intended family is apt-get update with error-on-any
failure, then apt-get --simulate install with removals forbidden and explicit
reviewed root selectors. Simulation must disable both persistent package-cache
output paths. These are design choices pending installed-build validation,
not executable commands or permission to run an unpinned apt upgrade.

The refresh stage may contact only the reviewed configured repository endpoints
and write its explicitly owned APT metadata/cache/lock/log state. It must retain
complete acquisition/signature outcomes, Release/InRelease identity/date/expiry,
accepted signer evidence and the hashes of the metadata used by the solver.
Reject partial fetches, stale fallback indexes, unsigned input, signature/date
failures or an unreviewed source. A zero exit status alone does not establish
that every required index is fresh and authenticated.

Resolve roots without downloading archives or invoking dpkg, maintainer
scripts, needrestart, notification wrappers or installed hook programs.
Capture proposed upgrades/removals and dependencies even when acceptance fails;
never apply the simulated solution automatically. Compare source/key/policy and
package state before/after. A changed database, source, key or policy invalidates
the solution. Record unresolved packages and any unavailable signing or
administrative prerequisite; do not substitute tools or relax trust checks.

Before installation, bind exact package versions/architectures and verified
archive hashes plus the reviewed needrestart override, permitted hooks/service
effects, executor and recovery inputs into a separate installation bundle.
The local needrestart archive already reviewed is usable only if its exact
bytes are authenticated against this accepted fresh package manifest.

## Failure, rollback and later gates

Metadata refresh is a persistent live effect even though it installs no
packages. The exact executor must identify its directories, locking strategy,
before-state capture and bounded cleanup/restoration before authorization.
On refresh or resolution failure, preserve evidence, mark the input unusable
and hold installation. Do not restore stale metadata and label it trusted,
remove arbitrary APT files, run dpkg repair, retry an interrupted operation or
reimage the node. Inspect the original execution and its partial state first.

No package database mutation, reboot, service restart/activation, fixed-network
change, controller/DNS access, primary outage, SMTP probe or mail is included.
No old-card swap is needed for successful metadata/resolution work; preserve
that card and the primary/shared antenna path for the installation recovery
stage. The [package-stage definition](trixie-package-stage.md) remains the
installation and physical rollback reference.

Documentation basis: current upstream APT guidance obtained through Context7
from the Debian APT project. The installed Trixie manuals and actual policy
remain authoritative; generic upstream documentation does not accept this node.
