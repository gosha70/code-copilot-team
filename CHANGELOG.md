# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project aims
to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Releases are cut from git tags (`vX.Y.Z`); `pi install git:…@<tag>` installs the
advisory content and `pi-code` (via `scripts/setup.sh --pi`) installs the
enforced runtime. See `adapters/pi/docs/quickstart.md`.

## [Unreleased]

### Added

- **Runtime conformance evaluator for autonomous builds (#242, increment
  C2 of #190 §6)** — `verification.conformance` in `automation.json`
  (schema-validated, closed; `required` rejected by name because it is
  DERIVED from `verification.yaml`; http(s) same-origin `app.interface` /
  `ready.url`; integer-second bounds). Admission flips from refusing
  `runtime_conformance` mappings to screening the evaluator: it must
  resolve in providers.toml, DECLARE `conformance_command` (with the
  `{review_request}` placeholder — reviewer health is not conformance
  capability), and pass its healthcheck, which now runs only after
  governance and after the canonical verification capture. The contract
  lifecycle keys on a verification-wide predicate (coverage block OR a
  finalized artifact), and the preflight initialiser freezes the
  deterministic verifier set and the conformance contract — evaluator,
  app, resolved interface, criteria with their `statement_sha` — from ONE
  validated capture shared with admission. The landing verifier gate
  (after coverage, before finalize/push/PR) EXECUTES every frozen
  deterministic verifier, launches and stops the application itself
  (own process group, launch-bound readiness, TERM→KILL teardown proven
  on every exit including signals), invokes the evaluator once through
  its `conformance_command` with a driver-authored request, and accepts
  only an exact identity multiset of the frozen criteria in a single
  fenced JSON block. Evidence lands in `verification-results.json` as
  FR → per-verifier results, written atomically; a mutated checkout
  (tracked or untracked) disposes `git_anomaly` and suppresses the
  termination commit/push; failures dispose `conformance_gate` (sharing
  C1's commit-bound recovery arm) or `provider_unavailable` with
  evaluator-scoped provenance that resume re-checks. Evaluator
  invocations debit the same caps as reviewers through the adapter cost
  channel, with a checked ledger write — an unrecorded cost parks
  `cost_accounting_failed`, one of the reasons that publish
  `resumable: false` and refuse `--resume` rather than forgive unrecorded
  spend. Driver suite 673 → 890.

- **Frozen coverage contract for autonomous builds (#222, increment C1 of
  #190)** — `verification.coverage` in `automation.json` (schema-validated;
  `test`/`app`/`visual`/`conformance` rejected by name until their
  increments ship): preset resolution from
  `shared/templates/<preset>/verification-preset.json` with per-key config
  override and sha256 provenance; preflight contract initialiser freezes
  the fully resolved contract (command, parser, artifact, floors,
  `max_regression_pct`, `timeout_sec`, `floor_enforced_at`, captured
  brownfield baseline) into the run ledger behind an atomic per-feature
  init lock, with attempt-scoped rollback on ordinary refusal and
  attempt-private evidence bundles when the canonical ledger cannot be
  claimed; driver coverage gate at `phase`/`landing` reads only the
  in-memory pinned contract (disk drift parks), collects fresh evidence
  in a throwaway worktree at HEAD (FR-5a containment both sides,
  `CCT_PROJECT_DIR`/`CCT_SPECS_DIR` rebound, `OLDPWD` dropped), enforces
  absolute floors plus point-based brownfield regression, fails closed on
  missing metrics, and parks/terminates naming the measured number and
  floor; attended coverage parks are resumable with commit-bound recovery
  (anything past the last reviewed HEAD needs its own review PASS —
  including recovery of failed required-artifact commits), an
  escalation-stack drain with verified progress and corruption/gap-refusing
  scans, and resolve-before-consume `/review-decide` handling; `git
  worktree prune` fires at every throwaway-worktree creation site
  (admission, brownfield capture, and the coverage gate), site-scoped
  under `CCT_ADMISSION_TEST_IN_PLACE=1`, non-fatal and journalled even
  when git fails silently. Driver suite 399 → 620.

### Fixed

- **Review runner: read-only directories no longer poison verdicts** — the
  snapshot sandbox is built with tar (deferred directory modes, `.git`
  excluded at source) instead of `cp -R`, snapshot setup failures map to
  RUNNER_ERROR instead of a `set -e` exit 1 that read as a FAIL verdict,
  and cleanup never decides the exit code.
- **Auto-build sessions: prompts on stdin, not argv (#234)** — a fix
  prompt carrying a large findings file exceeded ARG_MAX and died E2BIG
  before the session started; both the claude and pi backends now pass
  the prompt on stdin, and fix prompts drop the reviewer's `raw_output`
  transcript (the findings file retains it).

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

### Added
- **The cost cap is discoverable, live, and raisable mid-run (#201)** — a
  run inherited a **$25 default** the README never mentioned, showed no
  spend while in flight, and could not have its cap raised without first
  being parked. Now: a "Cost & safety caps" README section (default, where
  it lives, the `cap_exceeded` park, `--resume` semantics); a per-phase
  line — `[auto-build] phase 1 complete — $4.24 spent of $25.00 cap
  ($20.76 left)` — that names the estimated portion when there is one, so a
  conservative estimate never reads as measured spend; and a phase-gate
  re-read of `caps.cost_usd` from the live config for attended profiles, so
  a raise applies without waiting to be parked (announced on stdout,
  journalled as `cap_updated`, frozen snapshot updated). Deliberately
  narrow: only `caps.cost_usd`, only at phase gates (never mid-phase, so a
  session's budget cannot move under it), only positive values (a `0` is
  ignored rather than zeroing the budget), and never for `unattended` —
  (a LOWER cap is honoured too, and enforced on the spot: the gate
  re-checks immediately, so an over-budget run parks there instead of
  committing and finishing `done`) —
  such a run stays bound to the config it was ADMITTED against (#193), and
  an unaudited mid-run policy change would break that binding.
  **Upgrade note:** the cost cap was silently INERT before the #197/#198
  result-parsing fix — spend evaluated to `0`, so `caps.cost_usd` never
  accrued or triggered. Anyone on an older version was not protected by it.

### Fixed
- **The `max_rounds` breaker is no longer a dead end (#227)** — three
  defects together made it terminal. (1) Round numbering is deliberately
  monotonic, so a CUMULATIVE ceiling made `/review-decide retry`
  structurally impossible: with `current_round=5` and `max_rounds=5` the
  next round was already over the limit and the breaker re-tripped before
  the reviewer ran. The budget is now per ATTEMPT, anchored by the runner
  itself rather than by the slash command, so retry gets a fresh budget
  while numbering stays monotonic. (2) `review.max_rounds` shipped in the
  template but was never read — the driver only set `CCT_REVIEW_MAX_ROUNDS`
  for the advisory pass, so the gating loop always used the built-in 5 and
  raising it in `automation.json` did nothing (the same class as #205's
  `loop_timeout_sec`); it is now read and passed through, env still
  overriding. (3) Finding ids hash the description, so a reviewer that
  reworded produced fresh ids every round, `consecutive_fixed` never
  incremented, and the stale-finding breaker never fired — the loop read N
  "new" findings instead of one stuck reviewer. Staleness is now bucketed
  by `(file, category)`, which ignores prose; finding ids are unchanged
  because dispositions are keyed by them.
- **The benchmark's LiteLLM proxy dependencies are pinned (#220)** — the
  Anthropic-vs-vLLM benchmark installed an unconstrained
  `litellm[proxy]>=1.50` into a fresh venv on every run. litellm's own
  `proxy` extra allows `fastapi<1.0,>=0.136.3`, and fastapi 0.141.1 removed
  `get_flat_dependant`, which litellm imports at module scope — so the proxy
  crashed at startup (`ImportError: cannot import name 'get_flat_dependant'`,
  then `No module named 'proxy_server'`) and a previously working benchmark
  broke with no CCT change. Verified in clean venvs: fastapi 0.141.1
  reproduces the crash, 0.139.2 imports fine. Pins now live in
  `scripts/requirements-litellm-proxy.txt` with the reason and the upgrade
  procedure beside them; `pip check` runs right after provisioning so a
  conflicting resolution fails where the message names packages; every proxy
  failure path reports the resolved python/litellm/fastapi versions; and
  `tests/test-litellm-proxy-deps.sh` guards the pins in CI, with `--online`
  provisioning a real clean venv as the acceptance test.
- **`setup.sh --playwright` is no longer silently ignored (#212)** — the root
  parser's `*)` branch assigned unknown arguments to `PROJECT_DIR`, so the
  flag became a phantom project directory and the Claude adapter was invoked
  without it, while two docs told users the command installs the Playwright
  MCP server. Worse than a rejection: users believed it was installed. The
  flag is now forwarded to the claude-code adapter, exits nonzero with a
  pointer to the adapter when the resolved tool set cannot carry it — or
  when no tools are detected at all, which is the docs' own bare
  `setup.sh --playwright` and used to exit 0 saying "No tools detected" —
  and appears in `--help`. `--playwright` with `--sync` or `--memkernel` is
  rejected at the wrapper with the adapter's own wording, instead of
  regenerating everything and only then failing downstream. The class defect is fixed with
  it: anything starting with `-` is a flag by definition and exits nonzero
  naming itself, so a misspelled tool flag can no longer run a different
  installation than the one asked for. A positional project dir is
  unchanged.
- **The driver's wall-clock cap no longer bills parked time either (#210)**
  — #205 fixed the review-loop clock; the driver's own guard had the
  identical defect. `totals.started_epoch` was reset only on the
  `cap_exceeded` resume path, so resuming from `review_breaker`,
  `git_anomaly`, `provider_unavailable`, `test_failure` or `origin_gate`
  inherited the original start time and billed the human's turnaround
  against `caps.wall_clock_sec`. A real run was killed at **17886s of
  14400s** having done ~25 minutes of actual work. The reset now lives in
  the common resume path alongside the review-loop reset, so both guards
  restart together and cannot drift apart again; `cap_exceeded` resume
  behaviour is unchanged. Semantics are per-attempt, matching the review
  loop post-#207. Both resets live in one helper (`reset_run_clocks`) called
  from every successful resume path — including the `milestone-paused` arm,
  which bypasses `resume_parked()` entirely and therefore still billed a
  human's sign-off wait until it was wired in.
- **A verbose reviewer no longer destroys the findings file (#209)** — the
  reviewer's entire output travelled as a `jq --arg`, so a verbose reviewer
  (codex echoes the prompt plus its reasoning, captured with `2>&1`) blew
  past `ARG_MAX`; jq died with "Argument list too long" and, because the
  call sat inside a heredoc command substitution with no exit check, the
  findings file was written as an **empty 1-byte file** while the console
  still reported `findings written` and `Verdict: FAIL (blocking: 2)`. A
  real review with blocking findings was destroyed silently, and the fix
  session was then composed from nothing — the #204 phantom-findings shape
  from a new cause. The output now travels by file (`--rawfile`), jq writes
  to a temp file whose exit status is checked and whose result must parse
  before it is moved into place (a failure is a loud exit, never a
  plausible-looking artifact), and the driver refuses to compose a fix
  prompt from a findings file that is missing, empty, or not a JSON object —
  parking with a reason that names the file instead of dispatching a no-op
  fix session that would later park as `git_anomaly`.
- **The review loop's clock no longer bills time spent parked (#205)** —
  three defects from one real run. (1) `loop_start` was set when review
  state was initialised and carried verbatim through every round, so the
  900s wall-clock counted the time a run sat **parked waiting for a
  human**. Parking exists to invite that intervention, and every park
  reason needs an action taking longer than 15 minutes, so resuming
  tripped the breaker **instantly** — zero review rounds ran, and the
  human had to run `/review-decide retry` just to clear a timer that had
  measured their own thinking time. The clock now restarts on a
  successful resume, mirroring the driver's own guard. (2) Two producers
  wrote `breaker-tripped.json` with two key names — the runner `breaker`,
  the driver `breaker_type` — and the driver read only the latter, so
  **every** runner breaker was reported as `'unknown'` while the file
  plainly said `"timeout"`; it now reads either, which also fixes files
  already on disk. (3) The loop wall-clock is now configurable as
  `review.loop_timeout_sec` in `automation.json` (default 900) instead of
  env-only, with a non-numeric value falling back rather than being
  evaluated as `0` and tripping on the first round. Note
  `review.round_timeout_sec` is a different knob and remains inert —
  documented rather than silently rewired.
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
