# Tasks — Aider Backend (#41)

Single PR on `feat/benchmark-aider-backend`. Each task is bounded and
independently verifiable. Steps ship in order; a later step starts
only after the earlier step's tasks are green. AC map: spec.md
§ Success Criteria ←→ tasks below.

Pre-existing-failure note (memories
`project_benchmark_preexisting_env_test_failures`,
`project_polyglot_dogfood_subset_stale`): run suites **per-module**;
`test_polyglot_adapter`×4, a `test_cli_skeleton` hang, the stale
`test_polyglot_dogfood_subset` `*/leap` list, and pytest
auto-collecting `fixtures/**/leap_test.py` are known host noise, NOT
regressions.

## Phase A — SDD bundle (gated; STOP after)

### TA.1 — Bundle + alignment record
- **Output:** `specs/benchmark-aider-backend/{spec,plan,tasks}.md` +
  `origin-alignment-2026-05-19-0332.md`, mirroring
  `specs/benchmark-bench-driver/` format; the 4 locked decisions as
  Design Decisions; the bench-vs-harness architectural separation; the
  OUT list; Deviation-from-origin.
- **Done when:** `validate-spec.sh --feature-id benchmark-aider-backend`
  and `check-origin-alignment.sh benchmark-aider-backend` both exit 0;
  reported to user; **explicit "go" received before any Phase-B task.**

## Phase B0 — Preflight (no code yet)

### TB0.1 — Confirm Aider CLI facts + capture version/transcript
- **Output:** confirmed `--message-file` flag/semantics; `--no-stream`
  display-only finding; leaderboard-methodology re-scan notes;
  captured `aider --version` + `pip show aider-chat` + a real headless
  transcript with the exact B0-corrected pinned argv (`--yes-always`,
  no `--temperature`), capturing **`EXIT_CODE`** (Aider's exit codes
  are undocumented — the canonical run pins it empirically) — maintainer
  machine, AFTER B1–B2 settle so the fixture pins a stable contract.
- **Done when:** the doc-confirmable spot-checks (1–3) recorded
  [DONE 2026-05-19, see origin-alignment-0641]; spot-check 4 (live
  capture) supplied by the maintainer before B3.

## Phase B1 — Backend

### TB1.1 — `backends/aider.py`
- **Output:** `AiderBackend` mirroring `codex.py`: `BACKEND_FAMILY`,
  `_VERIFIED_VERSION`, timeout constants + `CCT_AIDER_TIMEOUT_SECONDS`
  override, `_build_argv` (pinned contract: `--yes-always` (NOT
  `--yes` — B0); `--model` iff non-empty; `--edit-format` iff
  `CCT_AIDER_EDIT_FORMAT`; NO `--map-tokens`; `--temperature` is not
  an Aider flag), Popen+pgkill timeout →
  `timed_out=True`, `_resolve_provider_env` (presence booleans),
  `_build_metadata`, best-effort `_parse_transcript`, `factory`.
  **Loud placeholder (B0 gate, option-b):**
  `_VERIFIED_VERSION = "PHASE_B3_CAPTURE_REQUIRED__DO_NOT_MERGE"`
  until TB0.1's real capture is wired in B3.
  Prompt → `attempt_dir/aider-message.txt`; history flags →
  `attempt_dir`.
### TB1.2 — Registration
- **Output:** one block after codex in `_register.py`.
- **Done when:** `python3 -m benchmark_runner list` shows `aider`;
  `isinstance(AiderBackend(...), Backend)`; backend unit tests green.

**B1 commit:** `feat(benchmark): aider copilot backend (#41)`

## Phase B2 — Tests + fixtures

### TB2.1 — Fake-shim suite + 3 fixtures
- **Output:** `tests/test_aider_backend.py` (3 classes mirroring
  codex) + `fixtures/aider/transcript-{success,no-summary,zero-tokens}.txt`.
- **Done when (asserted):** argv contract flag-by-flag; prompt via
  `--message-file`; cwd==worktree; history files under `attempt_dir`;
  **post-`run()` worktree has no `.aider*` and no commits**;
  `no-summary`→all token fields `None`, `zero-tokens`→`0`,
  `success`→tokens + `edit_format_resolved`; metadata presence
  booleans; no `sk-`/`Bearer ` in `str(metadata)`;
  nonzero exit→`failed_commands=1`; no live CLI / no network. Suite
  green per-module.
- **Self-enforcing B0 gate test:** `test_verified_version_not_placeholder`
  asserts `"PHASE_B3_CAPTURE_REQUIRED" not in _VERIFIED_VERSION` with a
  message pointing at the spec § verification capture. It FAILS until
  B3 wires the real version → the gate enforces itself; the
  placeholder cannot reach merge by human oversight.

**B2 commit:** `test(benchmark): recorded-transcript aider backend tests (#41)`

## Phase B3 — Verification record

### TB3.1 — `specs/benchmark-harness/verification/aider.md`
- **Output:** mirrors `codex.md`; real pinned version + real recorded
  transcript (from TB0.1); ## Verified argv (### Flag contract; ###
  Flags NOT present: `--yes` (doesn't exist — flag is `--yes-always`,
  B0); map-tokens/edit-format deliberately unpinned; `--temperature`
  not an Aider flag); ## Transcript format; ##
  Provider routing (booleans, never set); ## Edit-format &
  comparability; the `--no-stream` display-only confirmation; and the
  **enumerated 7-point Reviewer checklist** verbatim:
  1. pinned version matches `_VERIFIED_VERSION`; transcript regenerated
     if CLI bumped.
  2. `_build_argv` emits the contract; `--yes-always` (NOT `--yes`);
     `--model` iff `ctx.model`; no `--map-tokens/--edit-format` unless
     `CCT_AIDER_EDIT_FORMAT` (then `edit_format_forced=true`);
     `--temperature` never (not an Aider flag).
  3. prompt via `--message-file` under `attempt_dir`, not argv/stdin.
  4. `--no-auto-commits --no-dirty-commits --no-gitignore` always
     present; history files under `attempt_dir`; post-`run()` worktree
     has no `.aider*`/commits.
  5. metadata = provider presence booleans + resolved
     edit_format/map_tokens (no `temperature` — not an Aider flag);
     no key values, no `sk-`/`Bearer ` in `str(metadata)`.
  6. `timed_out=True` on `TimeoutExpired`; parser
     `no-summary`→`None`, `zero-tokens`→`0`.
  7. fake-CLI suite passes per-module; no live CLI/network.
- **Done when:** every checklist item maps to a code/test location.

**B3 commit:** `docs(benchmark): aider verification record (#41)`

## Phase B4 — README + leaderboard procedure

### TB4.1 — README Aider section + apples-to-apples
- **Output:** benchmark README "Aider backend" section + the
  maintainer apples-to-apples procedure: the 9 comparability
  invariants each mapped to existing adapter/backend behavior; the
  exact leaderboard-faithful command; explicit non-execution
  statement; `dogfood-subset.txt` `*/leap` staleness caveat.
- **Done when:** links resolve; non-execution statement present; no
  previously-documented knob lost.

**B4 commit:** `docs(benchmark): README aider section + apples-to-apples procedure (#41)`

## Phase B5 — Closeout

### TB5.1 — Suites + origin-alignment + PR
- **Output:** per-module suites green; executable artifacts actually
  run (fake-CLI suite, `benchmark list`); fresh
  `origin-alignment-<date>-<time>.md` (mtime-newest, `Verdict:` +
  `Confidence:` lines).
- **PR-description pre-merge gate line (mandatory):** "Pre-merge gate:
  `specs/benchmark-harness/verification/aider.md` contains the real
  captured `aider --version` + headless transcript (NOT the B0
  placeholder); `test_verified_version_not_placeholder` passes." Two
  independent signals (failing test + PR line) catch a leaked
  placeholder.
- **Done when:** `check-origin-alignment.sh benchmark-aider-backend`
  exits ≤1; `test_verified_version_not_placeholder` green (real
  version wired); diff shown + explicitly approved per commit; single PR
  `feat(benchmark): aider backend + verification + Aider-Polyglot
  apples-to-apples (Closes #41)` from `feat/benchmark-aider-backend`
  (never pushed to master). bench.py / dogfood-subset / aider_polyglot
  adapter confirmed untouched.
