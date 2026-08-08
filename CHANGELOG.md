# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project aims
to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Releases are cut from git tags (`vX.Y.Z`); `pi install git:…@<tag>` installs the
advisory content and `pi-code` (via `scripts/setup.sh --pi`) installs the
enforced runtime. See `adapters/pi/docs/quickstart.md`.

## [Unreleased]

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
