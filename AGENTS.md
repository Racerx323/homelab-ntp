# Repository instructions

## Scope and sources of truth

- Keep portable NTPsec server and client configuration in this repository.
- Treat `ntpsec/docs/ntp-architecture-deployment-plan-v1.0.md` as the source of
  truth for locked decisions, deployment state, risks, and the resume point.
- Keep host membership and OS facts in `homelab-server-configs/inventory`.
- Keep A, AAAA, PTR, and SRV records in `homelab-dns`.
- Keep addresses, DHCP, UniFi firewall policy, and NAT policy in
  `homelab-network`.
- Keep architecture diagrams in `homelab-docs`; keep secrets, private keys,
  credentials, and controller exports out of Git.
- Keep addresses, ports, schedules, records, and rollout procedure in the
  governing plan instead of duplicating them here.

## Working practice

- Inspect live state before generating host configuration. Do not infer
  interfaces, connection profiles, package paths, unit names, daemon users,
  leapfile locations, or UniFi rule order.
- Repository edits and local tests do not require a live-action gate.
- Update the governing plan after a decision, milestone, failed live action,
  rollback, or resume-point change.
- A plan entry does not authorize live access.
- One scoped approval may cover a defined read-only collection on one target.
  It does not require approval for each command in that collection.
- Obtain approval for each persistent host or controller change. The approved
  action may include its predeclared read-only preflight, acceptance, and
  rollback checks.
- Record the SHA-256 of privileged remote scripts and preapproved command
  bundles. An edit invalidates approval for that artifact.
- Preserve executed privileged mutation artifacts with their evidence. Edit
  unexecuted files through the normal review workflow.
- After a failed or interrupted mutation, inspect live state before retrying.

## Rollout safety

- Change and accept `j1-svntp1` before changing `j1-svntp`.
- Mutate one NTP node or one DNS node at a time. Keep the peer serving while
  changing the other node.
- Follow the governing plan's independent-server and active/standby DNAT
  design. Do not add an HA mechanism without an approved plan change.
- Define rollback before a persistent mutation. Verify the backup path and the
  configuration needed to restore service.
- Retain ordinary diagnostics without a classification step. Redact secrets and
  protect output that may contain credentials or private material.
- Use the observed UniFi rule model; do not require a fixed number of rules.

## Configuration artifacts

- Mirror each accepted live `/etc/ntp.conf` under a host-specific
  `ntpsec/configs/` path. Keep the accepted mirror byte-for-byte exact.
- Keep source templates separate from rendered files. Put server scripts under
  `ntpsec/scripts/`, client scripts under `client/scripts/`, and runbooks under
  `ntpsec/docs/`.
- Keep public examples free of private hostnames, addresses, credentials, and
  operational evidence.
- Install files with explicit owner, group, and mode. Reject symlinks and
  unexpected file types at installation boundaries.

## NTPsec and systemd

- Treat the installed Debian 11 NTPsec build and its local manual pages as the
  runtime authority.
- Audit the live GPS/PPS, upstream, restriction, interface, driftfile, leapfile,
  and daemon state before changing `ntp.conf`.
- Prove IPv4 and IPv6 listeners, client responses, peer selection, reach,
  stratum, leap state, offset, jitter, and journal health after deployment.
- Confirm the installed leapfile reload behavior before adding an `ntpd`
  restart or reload.
- Run `systemd-analyze verify` on changed units when available and repeat unit
  validation on a Debian 11 target before installation.
- Query `MainPID` and `NRestarts` only for service units. Use properties common
  to the inspected type for timers, paths, sockets, and targets.
- Treat workstation checks as partial when required packages, hardware,
  systemd state, or UniFi behavior exist only on a target. Follow the governing
  plan's network and DNS acceptance checks.

## Shell rules

- Use Bash for repository shell entry points. Standalone entry points should
  use `set -Eeuo pipefail`; sourced helpers must not change caller shell options.
- Handle fallible commands explicitly in functions used by `if`, `!`, `&&`, or
  `||`.
- Never reuse a script-level readonly variable name as a function-local name.
  Bash dynamic scope can reject the local declaration at runtime.
- Run `bash -n`, ShellCheck, and shfmt on each changed shell file. Never run
  bare `shfmt -w`; format intended files with `shfmt -w -i 4 -ci FILE`.
- Keep tracked shell entry points executable in the working tree and Git index.
- Test success and rejection paths for parsers, fail-closed validators, and
  mutation scripts. Give simple read-only wrappers a focused dry run or
  self-test.

Privileged remote runners require extra controls:

- Set an explicit remote working directory, invoke staged files through
  `/bin/bash`, and capture both output streams with the transport status.
- Give acceptance conditions distinct labels and fail on missing, duplicate,
  or false results.
- Test rollback and early-failure behavior before requesting live execution.

## Validation

Run focused checks for changed files, followed by:

```bash
git diff --check
pre-commit run --all-files
```

Run Markdownlint on changed documentation that policy does not exclude. Review
excluded `AGENTS.md` by inspection.

If Gitleaks classifies a reviewed public integrity hash as a secret, allowlist
that exact value. Do not add path-wide or arbitrary-hex exclusions.

## Reviews

- Run `coderabbit review` with network escalation.
- Use pull-request title format `[homelab-ntp] <title>`. Describe validation,
  live impact, authorization, rollback, and cross-repository changes.
- Do not claim live acceptance from local tests.

## vexp

Call `run_pipeline` once at task start for orientation unless the task names
the files or symbols to inspect. Use `eager: true` for non-trivial work. After
that call, use normal tools and native search for literal strings and runtime
output.
