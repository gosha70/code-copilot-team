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
- **A broken reviewer is no longer reported as a review verdict (#204)** —
  a non-zero reviewer process exit means the reviewer never ran, but it
  was mapped onto `FAIL`, the same vocabulary as a genuine rejection. The
  driver could not tell "reviewer is broken" from "your code has
  problems": it spawned fix sessions against **zero findings**, made
  unplanned commits, burned rounds and money, and parked as a misleading
  `git_anomaly`. Observed on a real run: 2 wasted rounds, 2 fix sessions,
  1 unplanned commit, ~$4 of a $6.76 budget, because codex exited on a
  one-line usage error. Now the verdict is `INCONCLUSIVE` (fail-closed),
  `findings-round-N.json` records `provider_error` with the exit code and
  message, and the round exits **3** — parked by the driver as
  `provider_unavailable`, naming the provider and its error, with no fix
  session and no burned round. A reviewer *timeout* (124/143) was the same
  class and previously exited 1; it now exits 3 too. A failed invocation
  is also no longer charged the conservative unmetered estimate (the
  observed run was billed `$2.0 estimated` for a reviewer that never ran);
  genuinely measured cost is still debited. A real review that fails the
  code still exits 1 and records no `provider_error`. Every provider
  failure — including one that produces NO output, and including a
  timeout — writes the findings artifact before exiting, because the
  driver reads the provider, exit code and message out of it.
- **A provider's echoed prompt is no longer parsed as its review (#200)**
  — providers are captured with `2>&1`, and a CLI that echoes its prompt
  (codex exec does) fed the request's own `### Verdict` section and its
  literal `FINDING|<severity>|...` format line back into the parser. The
  round runner took the FIRST `### Verdict` block, so the echoed
  instruction "State exactly one of: PASS, FAIL, or INCONCLUSIVE" became
  the verdict — PASS. The blocking-severity override masked this whenever
  a `blocking` finding was parsed, so the escape window was a review that
  fails on non-blocking grounds: reproduced end-to-end, a model verdict of
  FAIL with warning-only findings produced a **successful** round. The
  echoed format line also recorded a phantom finding with severity
  `<severity>` (stable id, so it polluted the stale-findings breaker), and
  the duplicated real findings made `jq --argjson` receive a multi-line
  `first_seen_round`, crashing the runner with exit 2 — the code its own
  header documents as BREAKER_TRIPPED — leaving no findings file and no
  breaker file. Now: a verdict is a bare `PASS`/`FAIL`/`INCONCLUSIVE`
  alone on the line after a line holding only `### Verdict`, parsed by one
  shared implementation (`scripts/lib/review-verdict.sh`) for both
  runners; placeholder findings are rejected by shape (not by a severity
  allow-list, which would silently drop misspelled real findings);
  findings are deduplicated by id; and the blocking override is kept as
  defence in depth.
  Crucially, **both requests now describe the verdict shape in prose and
  never instantiate it**. Ordering across the merged `2>&1` stream is not
  a contract — an echoed request can land after the answer as easily as
  before it — so "take the first block" and "take the last block" are
  equally unsound. A request that is parseable at all is a forged verdict
  waiting for buffering to change. The regression that pins this is a
  provider whose entire output is the real request echoed verbatim: it can
  only ever be INCONCLUSIVE.
  **Behaviour change:** a review with no `### Verdict` section is now
  INCONCLUSIVE instead of matching the bare word `PASS` anywhere in the
  output ("the tests pass", "password"). `scripts/peer-review-runner.sh`
  had only that bare-word match and its own request contains the string
  "A verdict: PASS, FAIL, or INCONCLUSIVE", so a prompt-echoing provider
  verdicted PASS unconditionally on an artifact the driver hard-gates on;
  it now requests an explicit `### Verdict` section and parses it the same
  way. Peer reviewers that never emitted such a section will report
  INCONCLUSIVE until they do — a failed gate, never a silent pass.
- **The shipped Codex reviewer command actually runs (#199)** — the
  provider template (and the README block users copy from) configured
  codex with `--quiet --prompt-file`, flags that no longer exist, so
  every codex review round failed on an unknown flag. Replaced with
  `codex exec --color never -s read-only --skip-git-repo-check -
  < {review_request} 2>/dev/null`, chosen from a recorded capture of
  codex-cli 0.147.0 (`specs/codex-provider-command/verification/`), not
  from `--help`. Two things only execution revealed: the runner strips
  `.git` from its snapshot sandbox and codex refuses to start outside a
  git repo, and codex echoes the whole prompt to stderr — which the
  runner merges via `2>&1`, making the echoed "State exactly one of:
  PASS, FAIL, or INCONCLUSIVE" the first `^### Verdict` block. Captured
  live: a review the model returned **FAIL** parsed as **PASS**, with a
  phantom finding from the echoed template line. The template had no
  test coverage at all; it now has guards for each flag and for
  `{review_request}` across every shipped `cli` provider.
- **Successful build sessions no longer park (#197)** — the driver
  parsed `claude -p --output-format json` as a single result object,
  but the current CLI emits a JSON array of messages (result = the
  `type=="result"` element): `.subtype` on the array read "unknown" and
  parked every succeeded phase, cost read 0 (caps never accrued), and
  `session_id` read empty (breaking `--resume` chaining). Both session
  backends now slurp-normalize all three real shapes — the claude
  message array, pi's JSON-LINES stream, and the legacy object — via
  `session_result_obj()`;
  the test suite's mock CLI emits the array shape by default so every
  driver path is exercised against the real output, with legacy-object,
  344-element captured-scale, and resume-chaining regressions. The same
  normalization is folded onto the review runner's `CCT_REVIEW_COST_FILE`
  reader, which a cli provider may legitimately point at a whole CLI
  result: a stream carrying more than one cost-bearing document used to
  yield a multi-line cost that blanked the cost state and wrote
  `findings-round-N.json` as a 1-byte file (still passing downstream
  `-f` checks) — reproduced driving the driver to exit 6. Unlike the
  driver, the cost reader keeps NO tail fallback: that channel is a
  trust boundary where a promoted non-result document would forge a
  measurement and suppress the conservative estimate.
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
