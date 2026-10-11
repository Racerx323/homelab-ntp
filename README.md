# Homelab NTP

Reproducible Raspberry Pi NTPsec/GPSD installation, configuration and maintenance
using authenticated, pinned sources and independently operated NTP nodes.

- [Architecture plan](ntpsec/docs/ntp-architecture-deployment-plan-v1.0.md): approved design, constraints, deployment stages and acceptance criteria.
- [Operations recipe](ntpsec/docs/OPERATIONS.md): installation, configuration, recovery, operations and maintenance.
- [Deployment history](ntpsec/HISTORY.md): accepted milestones, observations, deviations and next gate.

Supporting assets live in [scripts](ntpsec/scripts), [configs](ntpsec/configs),
[templates](ntpsec/templates) and [offline tests](ntpsec/tests).
The [pinned input manifest](ntpsec/configs/installation-assets.json) and
[verified fetch tool](ntpsec/scripts/fetch-installation-assets.py) provide exact
image, package and signed source inputs without committing large binaries.
Credentials, raw captures, recovery data and execution receipts remain private.

As of October 10, 2026, j2-svntp1's package foundation and staged GPSD 3.27.5 /
NTPsec 1.2.5 candidate are accepted. Live application installation, runtime
configuration, reporting and full hardware/network acceptance remain pending.
The operations recipe records the remaining fresh-node installer gaps.
A document, test result or previous approval does not authorize a live stage.
