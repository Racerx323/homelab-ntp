# NTPsec fleet deployment

`clockmaker.py` is the intended master deployment interface. The existing CLI
provides `build`, `update`, `configure`, `inspect`, `install` and `rollback`.
The complete fresh-host lifecycle is **not yet qualified**: current wrappers
still contain pilot-specific prerequisites. This map defines the refactor;
it does not certify those wrappers as reusable or authorize live execution.

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
| Clockmaker build/update | `clockmaker.py`, `pinup.py`, `fetch-installation-assets.py`, `prepare-source-build.py`, `source-build-stage.py`, `run-source-build.py` | Preserve pinned releases; replace source-string substitution with explicit host inputs and a shared invocation contract. |
| Clockmaker inspect/install/configure/rollback | `clockmaker.py`, `runtime-artifacts.py`, `inspect-source-destinations.py`, `source-install-stage.py`, `run-source-install.py` | Consolidate the operator path; use current observations and installed-state manifests instead of pilot handoffs. |
| NTP runtime and health | `timeservice.py`, `gpsd-pairing.py`, `pps-startup.py`, `shm-access.py`, `shm-access.c`, `measure-time-service.py`, `check-time-client.py`, `check-pps.py` | Retain needed behavior; separate hardware/platform inputs from implementation and expose acceptance through the lifecycle. |
| Activation and boot integration | `run-gpsd-acquisition.py`, `service-cutover-stage.py`, `production-transition.py`, `production-boot.py`, `service-monitor-stage.py` and their runners | Extract first-install behavior without previous accepted captures or restoration receipts; retain bounded recovery. |
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

1. Trace the existing clockmaker modes and their callers; define one shared
   preflight/execution input contract. Preserve working build/runtime behavior.
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
