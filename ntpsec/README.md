# NTPsec fleet deployment

`scripts/clockmaker.py` is the master source lifecycle interface. It provides
`prepare`, `preflight`, `build`, `update`, `configure`, `inspect`, `install` and
`rollback`, plus `apply-configuration`, `activate`, `check-client`,
`accept-service`, `recover-service` and `restore-service`. Fresh profile preparation, configuration staging and source-file
installation need no previous pilot operation. Existing aliases still work.

Local qualification covers two independent host profiles, input drift and
isolated file installation, configuration, activation and recovery. Native source builds on a second machine,
service activation, boot persistence and hardware acceptance are **not established**
by these tests. Use the fresh service lifecycle below; historical activation wrappers are retained
for their existing callers and are not fresh-install prerequisites.

## Fresh source lifecycle

1. Supply a hash-bound host JSON with `schema: 1`, `hostname`, `recipe` containing
   `path` and `sha256`, `packages` mapping installed package names to versions,
   and `python` containing `executable`, `version` (major/minor integers) and
   `module_directory`. Recipe paths are relative to the host JSON. Use current
   inventory/observations, not an accepted foundation archive. The source recipe
   remains `configs/source-build-recipe.json`; Python/package facts are inputs,
   not claims that preparation has inspected a host.
2. Run `clockmaker.py prepare --input HOST_JSON --sha256 HOST_SHA --artifact-cache CACHE --output PREPARED`.
   Preparation is offline, verifies pinned source bytes and writes only a private
   `profile.json`. It does not copy the cache or substitute values into code.
   Source authentication remains the declared recipe/release verification boundary.
3. On the authorized target, run `clockmaker.py preflight --for build --input PROFILE --sha256 PROFILE_SHA --artifact-cache CACHE`.
   `build` and `update` use that same input reader and repeat native identity,
   package versions, Python compatibility, source and helper hash checks. Invoke
   either with the same input/cache arguments and a new `--output CANDIDATE`.
   Source paths default to the profile directory for existing callers.
4. Stage host configuration with the existing configuration-profile schema:
   `clockmaker.py preflight --for configure --input CONFIG_PROFILE --sha256 CONFIG_SHA`,
   then `configure` with the same inputs and a new `--output CONFIGURATION`.
   Both use the same validator and hash-bound file reader. This stages files;
   it does not install systemd units or start services.
5. During approved cutover with daemons stopped, use
   `clockmaker.py preflight --for install --input RELEASE --sha256 RELEASE_SHA`
   and retain its JSON stdout as the current destination state. It validates
   staged payloads, destination parents, package conflicts and stopped daemons.
   `install` takes the same release plus `--state STATE --state-sha256 STATE_SHA`
   and a new protected `--journal JOURNAL`; it repeats checks before mutation.
   The journal parent must be root-owned and not group/world writable. For
   updates, both commands also take `--previous RELEASE --previous-sha256 SHA`.
6. Retain the installation receipt and backup for `rollback --input RECEIPT --sha256 RECEIPT_SHA`.
   Installation/rollback copy files without activating services. Configuration
   application and activation use the service lifecycle below. Native acceptance
   remains separate; local tests do not authorize target operations.

Preparation and staging outputs must not already exist. Preflight does not grant
authorization or suppress execution-time checks. Build logs and installation
journals remain after failure; partial installation requires state inspection
before recovery. Fleet baseline applications are not installed by these modes.

## Fresh configuration and service lifecycle

These modes implement the Raspberry Pi UART/PPS platform currently supported by
`timeservice.py`: `/dev/serial0`, `/dev/pps0`, and the runtime paths below.
They do not provision accounts, hardware overlays, networking or fleet packages.
The target needs a non-root NTP user/group, systemd, the installed release from
fresh preparation (including all eight helpers), and an inactive/disabled
`timeservice.service`. Conflicting time/GPSD services and sockets must be inactive.
The supported bootstrap is `systemd-timesyncd.service`, enabled or disabled and
active or inactive. Other baselines fail preflight for explicit adaptation.

Extend the configuration profile with `leapfile: {"path": "leap-seconds.list",
"sha256": "..."}`. Supply an unexpired file; no download occurs. The NTP config
must declare `/var/lib/ntpsec/drift/ntp.drift`, `/var/log/ntpstats/`, and
`/var/lib/ntpsec/leap-seconds.list`. Includes are unsupported. The timeservice
configuration must pass the supervisor's startup-gate and daemon-argument
validation, including the explicit non-root `ntpd -u USER:GROUP` account.

Create a service profile using the following schema. Paths are relative to this
profile; replace the example identity, addresses, hashes and health criteria with
reviewed host inputs, including observed credentials (real, effective, saved and
filesystem IDs). `peers` must contain the two mapped SHM names and three NTS
association names. Declare the independent client hostname and source addresses.
Health bounds are 90–1200 seconds, at least three samples at least 30 seconds
apart, offset at most 5 ms and jitter at most 1 ms.

```json
{
  "schema": 1,
  "hostname": "ntp-west.example.test",
  "release": {"path": "candidate/release.json", "sha256": "..."},
  "configuration": {"path": "configuration-profile.json", "sha256": "..."},
  "health": {
    "timeout_seconds": 300,
    "interval_seconds": 30,
    "consecutive_samples": 3,
    "offset_ms": 5,
    "jitter_ms": 1,
    "peers": ["SHM(0)", "SHM(1)", "nts-a.example.test", "nts-b.example.test", "nts-c.example.test"],
    "credentials": {
      "gpsd": {"uid": [0, 0, 0, 0], "gid": [0, 0, 0, 0]},
      "ntpd": {"uid": [123, 123, 123, 123], "gid": [123, 123, 123, 123]}
    },
    "ipv4": "192.0.2.51",
    "ipv6": "2001:db8::51"
  },
  "client": {"hostname": "client.example.test", "ipv4": "192.0.2.10", "ipv6": "2001:db8::10"}
}
```

For each phase, retain root preflight JSON in `STATE`, calculate its SHA-256,
and pass it unchanged to execution:

```text
clockmaker.py preflight --for apply-configuration --input SERVICE --sha256 SHA
clockmaker.py apply-configuration --input SERVICE --sha256 SHA --state STATE --state-sha256 STATE_SHA --journal NEW_JOURNAL
clockmaker.py preflight --for activate --input SERVICE --sha256 SHA
clockmaker.py activate --input SERVICE --sha256 SHA --state STATE --state-sha256 STATE_SHA --journal ANOTHER_NEW_JOURNAL
```

Preflight and execution share identity, release/configuration, device, directory,
service-state and native unit-parser checks. Each journal must be new with a
protected root-owned parent. Application backs up replaced files, installs the
four configuration files atomically, creates runtime directories with explicit
ownership, reloads systemd and leaves the service inactive. It leaves bootstrap
time service unchanged.

Activation first arms a root-owned systemd recovery timer, stops bootstrap time,
then starts the supervised GPSD/NTP pair. Consecutive samples require the same
unrestarted invocation, exact daemon credentials, both refclocks reachable,
PPS selection, three authenticated/reachable NTS associations with cookies,
leap zero, stratum one, declared precision limits, local dual-stack UDP replies
and no new service/Avahi error-priority entries. Journal parsing is shared with
preflight. Failure retains output and restores the prior state.

A healthy trial returns `awaiting_acceptance`, leaving startup disabled and the
recovery timer armed. Transfer its `client-challenge.json` through the approved
operator channel to the declared independent client. On that client, use the
same pinned checkout/helper and capture JSON stdout and stderr separately:

```text
clockmaker.py check-client --input CHALLENGE --sha256 CHALLENGE_SHA
```

This performs native IPv4/IPv6 PPS/stratum-1 requests, administrative-query denial
and mDNS checks. It binds actual client source addresses, target boot/invocation,
a per-trial nonce and checker hash. Return the result through the approved
operator channel; a digest binds the record, not an independent cryptographic
attestation of who ran it. Do not hand-author an acceptance result.

On the target, within 120 seconds of the client measurement and before the
30-minute trial deadline, with at least five minutes remaining for commit/recovery:

```text
clockmaker.py accept-service --input JOURNAL/recovery.json --sha256 PLAN_SHA --client-result RESULT --client-result-sha256 RESULT_SHA
```

Acceptance rejects stale/mismatched results or missing recovery protection,
rechecks release/configuration and native health, then disables bootstrap startup
and enables timeservice. It writes `active_enabled` before cancelling the timer;
a racing timer cannot undo that committed state. This is bounded acceptance,
not proof of reboot persistence, independent UTC accuracy or sustained stability.

The 1800-second transient systemd timer runs a protected current-run copy of the
recovery code independently of the SSH/controller process. It also protects
configuration application until that phase completes. It survives controller
exit/SIGKILL, but not reboot or power loss. Recovery serializes against controller
operations with a bounded 90-second lock wait and a 300-second native service
limit. A wedged host or failed native recovery still requires console access.
Timer cleanup failures remain visible; terminal state prevents a late callback
from undoing completed work. There are no notification sends or automatic retries.

For an incomplete same-boot attempt, inspect retained state and use:

```text
clockmaker.py recover-service --input JOURNAL/recovery.json --sha256 PLAN_SHA
```

For intentional reversal of a completed activation or configuration application:

```text
clockmaker.py restore-service --input JOURNAL/recovery.json --sha256 PLAN_SHA
```

Restore activation first, then configuration, then source files if returning the
entire install to baseline. Completed restoration records a separate request and
preserves `completion.json`; interrupted restoration resumes through
`recover-service`. Completed restoration is operator-driven, not a new automatic
trial; retain attendance until it finishes. Both refuse changed boots, corrupt
backups and unrelated file drift. Runtime data is retained. A restored bootstrap
service is not proof of restored precision NTP. `expire-service` is the timer's
internal callback, not an operator retry command.

Source `rollback` supports both completed installs and partial installs whose
pre-mutation backups were completed. It accepts only original or intended files,
so interruption between replacement and progress recording is recoverable.
Interrupted rollback can resume using the same receipt; completed rollback cannot
be replayed. No service configuration is implicitly reversed. Assess state after
reboot before any recovery. Historical pilot evidence is never an input.

## Contract and ownership

Inputs: clean checkout, declared release artifacts, host/platform inventory and
current target observations. Outputs: installed configuration/service, health
results, installed-state manifest and deployment/recovery records. Artifact cache
and output paths must be caller-selected; no historical `.local-evidence` tree
is required. Updates may consume the installed-state manifest and their own backup.

Base OS maintenance, Webmin, watchdog and needrestart are fleet prerequisites
owned by `homelab-server-configs`. Munin is owned by
`homelab-monitoring-observability`; DNS and networking retain their own owners.
Clockmaker checks explicit prerequisite contracts rather than installing those
applications. NTP-specific reporting and metrics integration remain relevant.

## Initial implementation map

These are migration destinations, not permission to delete files. Validate callers
and tests before moving code; some workers mix reusable logic and pilot policy.

| Lifecycle / owner | Existing implementation | Required change |
| --- | --- | --- |
| Clockmaker build/update | `clockmaker.py`, `pinup.py`, `fetch-installation-assets.py`, `prepare-source-build.py`, `source-build-stage.py`, `run-source-build.py` | New clockmaker prepare/preflight use explicit inputs; preserve legacy wrappers for historical callers until migrated. |
| Clockmaker inspect/install/configure/rollback | `clockmaker.py`, `runtime-artifacts.py`, `inspect-source-destinations.py`, `source-install-stage.py`, `run-source-install.py` | Shared source/configuration/install validators are implemented; current snapshots and optional prior installed releases drive file installation. |
| NTP runtime and health | `timeservice.py`, `gpsd-pairing.py`, `pps-startup.py`, `shm-access.py`, `shm-access.c`, `measure-time-service.py`, `check-time-client.py`, `check-pps.py` | Retain needed behavior; separate hardware/platform inputs from implementation and expose acceptance through the lifecycle. |
| Activation and boot integration | `run-gpsd-acquisition.py`, `service-cutover-stage.py`, `production-transition.py`, `production-boot.py`, `service-monitor-stage.py` and their runners | Fresh application/activation now use `clockmaker-service.py`; native platform acceptance and remaining historical caller migration are separate. |
| NTP maintenance/reporting | `statistics-retention.py`, `leap-activation.py`, `mail-reporting.py`, `maintenance-success.py` and their runners | Keep NTP behavior; use fleet notification prerequisites and current installed state. |
| Fleet prerequisites | `foundation-*`, `prepare-foundation.py`, package-resolution helpers, `webmin-*`, `run-webmin-*`, `needrestart.sh`, base-OS `maintenance-*`, `run-watchdog-inspection.py` | Separate generic OS/application ownership from NTP build dependencies; migrate reusable fleet behavior to its owner before retiring wrappers. |
| Monitoring integration | `run-munin-*`, `read-munin-health-state.py`, `inspect-munin-ntp-selection.py`, `install-maintenance-producers.py` | Keep an explicit NTP integration contract; move general installer/poller ownership to monitoring. |
| Historical continuations | `continue-foundation.py`, `continue-source-acceptance.py`, `run-host-recovery-continuation.py`, `leap-timer-correction.py`, `maintenance-native-files.py` | Preserve historical artifacts; extract reusable fixes and remove consumed-operation dependencies from the supported path. |
| Host/network provisioning | `host-network-stage.py`, `run-host-network.py`, `host-configuration-stage.py`, `run-host-configuration.py`, `rtc-commissioning.py` | Separate network/fleet policy from NTP hardware integration; consume owned inventory and platform profiles. |

Script names above are relative to `scripts/`. Remaining diagnostics and tests
must be classified by actual callers during each migration, not deleted by name.
Keep release recipes in `configs/`; distinguish host overrides and accepted pilot
snapshots from defaults. Keep templates separate from rendered configurations.

## Implementation sequence and acceptance

Use the [second-host qualification procedure](docs/FLEET-QUALIFICATION.md) for
the complete command sequence, prerequisites and acceptance boundaries. It is
prepared locally; native execution remains unapproved.

1. Implemented shared preparation/preflight inputs, offline two-host checks and
   fresh configuration/activation with recovery. Qualify the actual second-host
   platform, service health, recovery and reboot persistence under live approval
   only after J2-SVNTP1 production deployment is accepted.
2. Replace pilot constants and predecessor-operation prerequisites in the
   fresh-install path. Keep generic fleet installers outside that path.
3. Exercise a second host profile from a clean checkout with a caller-selected
   artifact cache/output directory, without historical evidence or pilot paths.
   Local checks establish portability only; authorized native deployment and
   recovery remain separate acceptance requirements.
4. Reconcile tests with supported behavior. Retire unused continuations only
   after checking callers, preserving historical evidence and updating docs.
5. Prepare a separate evidence-retention/deletion inventory. Deduplicate large
   artifacts by digest; preserve unique outcomes and usable recovery copies.
   No evidence deletion is authorized by this migration map.

[Architecture requirements](docs/ntp-architecture-deployment-plan-v1.0.md),
[operations](docs/OPERATIONS.md), and [current readiness](docs/PRODUCTION-READINESS.md)
retain their distinct roles. Existing OBS-02 acceptance and D1–D5 limitations,
other accepted outcomes and remaining production gates are unchanged.
