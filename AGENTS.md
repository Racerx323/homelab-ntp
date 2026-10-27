# Repository instructions

## Product and ownership

- Keep the repeatable NTPsec server build in `ntpsec`; `scripts/clockmaker.py`
  is its operator entrypoint. Prefer reusable helpers over operation-specific
  installers. Keep NTP client configuration under `client`.
- Host inventory, base OS maintenance, Webmin, watchdog and needrestart belong
  to `homelab-server-configs`; Munin belongs to
  `homelab-monitoring-observability`. NTP declares prerequisites and validates
  integration; do not duplicate fleet package installers here.
- Keep DNS records in `homelab-dns`, address/firewall/NAT policy in
  `homelab-network`, and architecture diagrams in `homelab-docs`.
- The architecture plan defines requirements; OPERATIONS defines reusable
  procedures; PRODUCTION-READINESS records current status and the next action;
  HISTORY records concise milestones. Detailed attempts belong in run records.
  Keep host values in owning inventory/configuration and reference them from
  the plan. Preserve accepted outcomes and limitations when reorganizing docs.

## Build contract

- A fresh build takes a clean checkout, declared release artifacts, explicit
  host/platform inputs and current target observations. It must not require
  pilot receipts, historical recovery bundles or private evidence directories.
- Make artifact-cache and output locations configurable. Evidence is an output;
  never import executable implementations from previous operation archives.
  Updates may use installed-state manifests and the current transaction backup.
- Render configuration offline from validated inputs. Before applying, verify
  target identity and assumptions that can change; inspect missing facts rather
  than inventing paths, interfaces, users, unit names or hardware capabilities.
- Separate templates, host inputs and rendered output. Retain accepted host
  configuration mirrors where required, without treating them as fleet defaults.
- Pin executable/configuration inputs and release artifacts. Store large
  immutable artifacts once by digest; reference predecessors rather than nesting
  their archives. Preserve executed artifacts and unique results; cleanup needs
  an explicit retention/deletion scope and must not remove the only recovery copy.

## Authorization and recovery

- Repository edits and local tests do not authorize target contact or mutation.
  Obtain explicit authorization for the named targets and operational outcome.
  One approval may cover preflight, bounded diagnostics, mutation, convergence,
  acceptance and recovery, including declared conditional branches.
- Bind live approval to a digest manifest of executable/configuration inputs,
  targets, permitted effects and recovery scope. Declare runtime discovery and
  its allowed decisions. Changes to those approved inputs or scope require fresh
  approval; unrelated documentation and appended results do not. Preserve the
  originally approved artifact and record new results separately.
- Reuse authorization within its scope. Ask again only for uncovered actions or
  materially changed conditions. Preserve explicit one-send approvals and
  destructive-action boundaries. Existing sealed contracts retain their terms;
  this policy does not retroactively broaden them or authorize replay.
- Change one NTP node or one DNS node at a time; preserve a serving peer. Put
  actual rollout targets/order in the deployment plan. Preserve the approved
  independent-server/network design unless the user approves a design change.
- Before persistent mutation, define bounded recovery and verify protected
  backups, restore inputs and operator access appropriate to the failure mode.
  Repeat attendance confirmation only when conditions materially change or the
  approved contract requires it. After interruption, inspect state before retry;
  do not replay an uncertain or consumed operation.

## Implementation and evidence

- Prefer native package/service operations and existing helpers. Add orchestration
  only for a demonstrated requirement. After a second failure attributable to
  deployment machinery, reassess the design before producing another successor.
- Derive preflight and execution from the same command/input definitions. Verify
  authentication, executable paths, options, native return-code semantics and
  acceptance predicates before mutation. Unsupported checks are unresolved,
  not automatic evidence that the service is unhealthy.
- Use the declared interpreter or verified executable with an explicit working
  directory. Capture stdout, stderr, exit status and partial progress from launch;
  preserve failure evidence even when a later step fails. Label acceptance checks
  distinctly and reject missing, duplicate or false required results.
- Install with explicit owner/group/mode. Validate path types and ownership;
  reject unexpected symlinks and unsafe traversal while allowing documented
  platform links. Keep credentials/private captures out of Git and protect logs.
- Test locally provable failure/recovery behavior. Document hardware/native
  assumptions and qualify them in an authorized pilot; stand-ins do not prove
  native recovery or downstream delivery. Local tests never establish live
  acceptance, and SMTP acceptance alone never establishes receipt.

## NTP acceptance

- Use the declared platform profile and installed build/manuals; do not assume
  paths or boot overlays carry across operating systems. Check GPS/PPS, upstream,
  restriction, drift/leap configuration and daemon state before applying changes.
- Validate intended IPv4/IPv6 listeners and client responses, source selection,
  reach, stratum, leap state, offset/jitter and relevant journal health against
  explicit plan criteria. Preserve failed criteria and measurement limitations.
- Verify leapfile reload behavior before adding restarts. Validate changed units
  with `systemd-analyze verify` where available and on the target before activation.
  Query properties appropriate to the systemd unit type.

## Validation and publication

- Run the smallest checks covering the change. Test meaningful success/rejection
  and interruption paths for changed parsers/installers. Keep offline tests in CI;
  avoid unrelated harnesses and implementation-mirroring tests. Run repository-wide
  pre-commit before release or changes spanning executable components.
- Documentation changes need focused Markdown/link checks and `git diff --check`;
  inspect excluded AGENTS.md manually. Scan new/changed publishable artifacts for
  secrets, including untracked content; staged-only hooks are not sufficient.
  Use `gitleaks detect --source . --no-git --redact --no-banner` for a full local
  scan when needed. Allowlist only verified exact false-positive hashes.
- Use Bash for shell entrypoints, `set -Eeuo pipefail` for standalone scripts,
  and explicit fallible-command handling in conditional functions. Sourced
  helpers must not change caller options. Never shadow script-level readonly
  names with function locals. Keep entrypoints executable in Git and on disk.
- Run `bash -n`, ShellCheck and shfmt on changed shell files; use explicit files
  and `shfmt -w -i 4 -ci`, never bare `shfmt -w`. Keep CI formatting consistent.
- Inherit workspace tool guidance rather than duplicating it here. External
  review requires authorization to share the content; its absence does not block
  local work. PR titles use `[homelab-ntp] <title>` and describe changes, validation,
  live impact and remaining limitations.
