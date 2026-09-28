# Repository instructions

## Scope and sources of truth

- Keep portable NTPsec server and client configuration in this repository.
- Treat `ntpsec/docs/ntp-architecture-deployment-plan-v1.0.md` as the source of
  truth for locked architecture, constraints, stages, and acceptance criteria.
- Keep current state, operation outcomes, deviations, and the exact resume
  point in `ntpsec/HISTORY.md`; keep active operation definitions and sanitized
  evidence separate from the governing plan.
- Keep host membership and OS facts in `homelab-server-configs/inventory`.
- Keep A, AAAA, PTR, and SRV records in `homelab-dns`.
- Keep addresses, DHCP, UniFi firewall policy, and NAT policy in
  `homelab-network`.
- Keep Munin endpoint configuration and plugins in
  `homelab-monitoring-observability/Munin`; record the NTP hosts' Munin
  requirement and acceptance evidence here.
- Keep architecture diagrams in `homelab-docs`; keep secrets, private keys,
  credentials, and controller exports out of Git.
- Keep addresses, ports, schedules, records, and rollout procedure in the
  governing plan instead of duplicating them here.

## Working practice

- Inspect live state before generating host configuration. Do not infer
  interfaces, connection profiles, package paths, unit names, daemon users,
  leapfile locations, or UniFi rule order.
- Repository edits and local tests do not require a live-action gate.
- Change the governing plan for an approved architecture decision or deviation.
  Record milestones, live actions, rollback, and resume-point changes in
  `ntpsec/HISTORY.md`, not in the governing plan.
- A plan entry does not authorize live access.
- One scoped approval may cover a defined read-only collection on one target.
  It does not require approval for each command in that collection.
- Obtain scoped authorization for each live node or controller stage. One
  approval may cover its exact preflight, mutation, convergence, acceptance,
  and rollback path; it does not authorize another node or controller stage.
- Bind that approval to the SHA-256 of one deployment bundle containing the
  operation specification and every non-secret execution input. Name the
  target, command, mutation boundary, acceptance checks, and rollback in the
  approval request. An edit or scope change requires a new hash and approval.
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

- Treat each installed build and its local manual pages as the authority for
  that node: Debian 11 for baseline capture, then Raspberry Pi OS Lite
  (64-bit), Trixie for rebuild candidates and acceptance. Do not assume that
  package paths or boot overlays carry over.
- Audit the live GPS/PPS, upstream, restriction, interface, driftfile, leapfile,
  and daemon state before changing `ntp.conf`.
- Prove IPv4 and IPv6 listeners, client responses, peer selection, reach,
  stratum, leap state, offset, jitter, and journal health after deployment.
- Confirm the installed leapfile reload behavior before adding an `ntpd`
  restart or reload.
- Run `systemd-analyze verify` on changed units when available and repeat unit
  validation on the Trixie target before installation.
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
- Keep the pre-commit shfmt check at `-d -i 4 -ci`. If an NTP `--write` helper
  becomes useful, require an explicit regular-file list, reject symlinks and
  paths outside this repository, and format only the requested files. Do not
  copy the server-configs wrapper's unrelated Munin path exception.
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

Run the smallest checks that cover the change. Documentation-only edits need
focused Markdown, link, and Git checks; they do not require a full behavior
suite. When executable behavior or a durable safety boundary changes, add or
run regression tests for the affected entry points and failure paths. Run
repository-wide pre-commit before a release or when the change spans multiple
components.

When the first NTP collector, installer, or deployment operation is added,
add focused success and rejection tests and a pre-commit hook for that
behavior. Trigger the hook on its executable, tests, relevant configuration,
and `.pre-commit-config.yaml`; use `pass_filenames: false` if the test runner
accepts no file arguments. Add the same NTP test path to this repository's CI
workflow because the shared baseline job runs only its named general hooks.
Keep the hook and CI test offline; live acceptance remains a separate gate.

Baseline checks:

```bash
git diff --check
```

The pre-commit Gitleaks hook checks staged content. `pre-commit run --all-files`
does not scan untracked or unstaged files for secrets through that hook. Before
reviewing new local artifacts or requesting deployment, scan the working tree:

```bash
gitleaks detect --source . --no-git --redact --no-banner
```

Run Markdownlint on changed documentation that policy does not exclude. Review
excluded `AGENTS.md` by inspection.

If Gitleaks classifies a reviewed public integrity hash as a secret, allowlist
that exact value. Do not add path-wide or arbitrary-hex exclusions.

## Reviews

- CodeRabbit review is optional. Run it only when the user authorizes sharing
  the relevant private infrastructure content with that external service and
  workspace policy permits the upload. Its absence does not block local work.
- Use pull-request title format `[homelab-ntp] <title>`. Describe validation,
  live impact, authorization, rollback, and cross-repository changes.
- Do not claim live acceptance from local tests.

## vexp

Call `run_pipeline` once at task start for orientation unless the task names
the files or symbols to inspect. Use `eager: true` for non-trivial work. After
that call, use normal tools and native search for literal strings and runtime
output.


## vexp - Context-Aware AI Coding <!-- vexp v3.3.0 -->

### Context strategy: call run_pipeline ONCE at task start
If the task already names the files/symbols to touch, SKIP vexp. Otherwise one
`run_pipeline({ "task": "..." })` returns ranked pivot files with line ranges and
blast radius. Do NOT open files one by one to find your way around - every extra
tool call costs a turn. Call it again ONLY when the task moves to a new area.
`get_skeleton` for files to understand, not edit. `verify_done` before calling a
multi-file task complete, then RUN the tests it names.

### Query shape (do this)
Anchor the task on real identifiers (ClassName, functionName) or file paths:
`run_pipeline({ "task": "fix JWT expiry in AuthService.validateToken" })`

vexp runs entirely on this machine, index in `.vexp/`;
`run_pipeline` transmits nothing to any external service.
On `status: "degraded"` or 0 pivots the index is still building - use your own tools.
For literal string sweeps use your native search - do NOT route text sweeps through vexp.
Repo SOURCE only: logs, dist/, node_modules/ and files outside the repo are NOT indexed.
<!-- /vexp -->