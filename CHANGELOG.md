# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project aims
to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Releases are cut from git tags (`vX.Y.Z`); `pi install git:…@<tag>` installs the
advisory content and `pi-code` (via `scripts/setup.sh --pi`) installs the
enforced runtime. See `adapters/pi/docs/quickstart.md`.

## [Unreleased]

### Added

- **Unattended admission control + traceability (#193, increment B of
  #190)** — `specs/<feature>/verification.yaml` requirement→verifier
  evidence graph (`shared/schemas/verification.schema.json` contract,
  canonical FR normalizer/hasher in `scripts/lib/verification-common.sh`,
  deterministic draft generator `scripts/generate-verification-draft.sh`);
  `validate-spec.sh --unattended` admission bar (two-way coverage,
  `statement_sha` recomputation against `spec.md`, executable-verifier
  resolution, governance-before-execution ordering, `test.command`
  proven in a throwaway worktree, C-owned checks surfaced as DEFER);
  the driver's increment-A test seam replaced by real admission bound
  to the EFFECTIVE config — an admitted `unattended` run executes for
  the first time, a refusal is an un-admitted exit-1. Review-cost
  measurement moved to the out-of-band `CCT_REVIEW_COST_FILE` adapter
  channel (in-band text envelopes are never measured); capability-
  downgraded runs report their effective state honestly in summary,
  ledger, and triage. Behavior note: ALL `--resume` invocations
  (attended included) now parse every config value from the frozen
  ledger snapshot — the parked-resume arms (caps/pr/merge refreshes)
  are the sanctioned channel for post-freeze edits; other live-file
  edits are ignored on resume by design.


### Added
- **Unattended policy core + metering (#191, increment A of #190)** —
  terminal-outcome vocabulary in the auto-build driver (`landed` /
  `terminated_policy` exit 6 / `failed`); terminate-only disposition
  dispatch for the new `unattended` profile (fail-closed at config load
  until increment B ships admission control) with mandatory
  `termination.json` + `triage-report.md` artifacts and journaled
  best-effort commit/push; `automation.json` schema_version 2
  (`shared/schemas/automation.schema.json`) + dedicated jq validator
  gating every run (`origin_gate` locked to terminate in all
  increments); full cost accounting — review rounds emit per-invocation
  cost and debit the same `caps.cost_usd`, with conservative flagged
  estimates for unmetered invocations; `cooldown-supervisor.sh` treats
  exit 6 as terminal (never cooled down or relaunched, including across
  supervisor re-invocations on the same ledger). Attended profiles are
  byte-identical, with one deliberate exception: a reviewer backend that
  genuinely reports measured cost now debits `caps.cost_usd` on every
  profile (previously silently free); estimates stay opt-in for
  attended configs and inactive for v1.

### Fixed
- **Autonomous builds run through the branded launcher (#195)** — the
  auto-build driver's Claude backend defaulted to the generic `claude`
  binary while the PI backend correctly used `pi-code`, so unattended
  sessions skipped the launcher's config (BUN_OPTIONS ipv4-first fix,
  project permission tier/hooks, transcript logging). `CCT_CLAUDE_BIN`
  now defaults to `claude-code`; the launcher gained a headless
  passthrough (`-p`/`--print`/`--version` forward verbatim to `claude`
  — no cmux/tmux, the prompt is never treated as a path) and a branded
  autonomous entry, `claude-code build <feature-id> [driver args]`, so
  no-human-in-loop intent never needs
  `--dangerously-skip-permissions`. `pi-code` is unchanged.

## [1.1.0]

Pi adopted as a first-class **enforced** coding-agent harness alongside Claude
Code, with honest capability reporting throughout.

### Added

- **Launcher & install** — `pi-code` launcher (upstream-`pi` resolution,
  version gate ≥ 0.79.0, recursion guard, `--no-cct`/`--profile`/`--project`/`--`
  passthrough); `scripts/setup.sh --pi`; advisory `pi install …@<tag>`.
- **Config & profiles** — layered TOML config (defaults < profile < global <
  trusted project < project-local < env < cli < session), fail-closed trust
  gating (FR-004a), monotonic security floor (P7), 8 built-in profiles, and
  `pi-code doctor`/`config`/`config explain`/`features`/`export`/`resources`.
- **Skills, prompts, always-context** — generated from `shared/`; command→prompt
  conversion; always-on context bundle.
- **Enforced workflow** — SDD risk classification + phase state machine;
  lifecycle-event schema with honest `degraded`/`unsupported` reporting; the
  allow/ask/deny permission engine with deterministic headless resolution;
  protected paths + protected operations; peer review + verification gates.
- **Agents (Slice D)** — neutral agent manifests + Claude-agent importer;
  out-of-process subagent child-session runner (model/thinking/tools/isolation/
  timeout/cancel enforced); worktree manager (isolation, ownership-conflict
  detection, tamper-safe ledger, safe cleanup); worker verification + redacted
  analytics correlation; team controller (identities, single-claimant ledger,
  plan approval, controlled shutdown) + team status/synthesis/recovery.
- **Durability (Slice E)** — session-state checkpoint/recovery, memory promotion
  with secret controls, MCP provider, sandbox detection + fail-closed gate,
  auto-build Pi backend.
- **Release & docs** — Pi analytics adapter → neutral CCT format; generated
  capability compatibility matrix (`shared/capabilities/COMPATIBILITY.md`);
  security battery + cross-adapter contract; quickstart / configuration /
  security-model / migration / extension-development guides;
  `specs/pi-harness-adoption/lessons-learned.md`; CycloneDX SBOM
  (`adapters/pi/sbom.cdx.json`), checksums, and this changelog.

### Security

- Fail-closed defaults throughout: unknown trust → untrusted; unresolved
  required gate → block; required sandbox absent → block. Secret redaction
  before persistence across memory, analytics, and team messages. Tamper-safe
  ledgers reconcile their invariants on load.

### Notes — honestly degraded (not faked)

Pi lacks some native primitives; these are reported `degraded`/`unsupported` in
the capability registry, never as a fake pass: no observable Stop/compaction
event (verification/session-state gates fire at explicit CCT actions), the
runtime cannot itself create a sandbox (detects + rejects), and teams have no
live transport/UI. See `shared/capabilities/COMPATIBILITY.md`.
