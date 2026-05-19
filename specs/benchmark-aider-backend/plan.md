---
spec_mode: full
feature_id: benchmark-aider-backend
risk_category: integration
justification: "New copilot backend mirroring the codex backend: a new scripts/benchmark_runner/backends/aider.py + one-line _register.py change + a committed verification record + a recorded-transcript test (no live CLI) + a README section + the documented apples-to-apples leaderboard procedure. External integration: the Aider CLI (aider-chat), driven non-interactively; provider env recorded never set. No harness orchestration/scoring/adapter change — D2 heartbeat + D5 timeout classification inherited unchanged from run.py. Single PR fully closing #41."
status: draft
date: 2026-05-19
issue: 41
origin:
  issue: gosha70/code-copilot-team#41
  urls:
    - https://github.com/gosha70/code-copilot-team/issues/41
    - https://github.com/gosha70/code-copilot-team/issues/33
    - https://aider.chat/docs/scripting.html
    - https://aider.chat/docs/leaderboards/
    - https://aider.chat/2024/12/21/polyglot.html
    - https://aider.chat/docs/more/edit-formats.html
  origin_claim: |
    See spec.md `origin:` block. Issue #41 adds the `aider` copilot
    backend mirroring codex (#33): backend + verification record
    (pinned version + recorded headless transcript) + recorded-
    transcript test + provider-env-recorded-never-set + README + the
    apples-to-apples Aider-vs-Aider Polyglot procedure, one PR fully
    closing #41. Four user decisions (2026-05-19): mirror codex
    exactly / bench untouched; verbatim model-string passthrough;
    methodology-fidelity (pin only headless/hygiene flags);
    leaderboard runnable-but-not-executed.
---

# Implementation Plan — Aider Backend (#41)

> **Mirror codex, structurally.** Accompanies
> `specs/benchmark-aider-backend/spec.md`. No harness orchestration,
> scoring, or adapter change. The forced codex-template departures are
> in spec.md § Deviation from origin; the origin-alignment record
> dated alongside this plan covers them.

## Approach

One feature branch (`feat/benchmark-aider-backend`), **one PR** that
fully closes #41 (one-PR-per-issue rule; no partial/phased delivery
against a single issue). Two gated phases:

- **Phase A** (this bundle): SDD artifacts only. STOP, report, await
  explicit user "go".
- **Phase B** (post-approval): the backend + verification + test +
  README + leaderboard procedure, in the order below, each ending in a
  reviewed commit; the harness stays runnable after every commit (the
  existing backends/tests never regress).

The backend mirrors `codex.py` structurally; the only real divergences
(text transcript, message-file prompt, env-presence metadata, the
no-commit hygiene flags) are forced by Aider's CLI and `run.py`'s
`_write_diff` and are documented, not invented.

## Phase boundaries

| Step | Working slice | Gate |
|---|---|---|
| Phase A | spec/plan/tasks + origin-alignment | `validate-spec.sh` + `check-origin-alignment.sh` exit 0; user "go" |
| B0 preflight | aider CLI facts confirmed; version+transcript captured | preflight spot-checks (plan § Preflight) pass |
| B1 backend | `aider.py` + `_register.py` | `benchmark list` shows `aider`; unit tests green |
| B2 tests | fake-shim suite + fixtures | per-module suite green; worktree-clean assertion green |
| B3 verification record | `verification/aider.md` with real version+transcript | 7-point checklist maps record→code |
| B4 README + leaderboard proc | README section + 9 invariants | links resolve; non-execution statement present |
| B5 closeout | fresh origin-alignment; one PR | `check-origin-alignment.sh` ≤1; PR `Closes #41` |

## Preflight spot-checks (B0, before writing the backend)

1. `aider --help | grep -i message` — confirm `--message-file <path>`
   exists with file-path semantics in the pinned version.
2. Confirm `--no-stream` is **display-only** (does not change what is
   sent to the model or how edits apply) against the live recorded
   transcript; record the finding in `verification/aider.md`. If
   behavior-bearing, drop it and capture the summary another way.
3. Re-read https://aider.chat/docs/leaderboards/ + the polyglot post
   for any methodology knob not yet covered (temperature, num-tries,
   weak/editor-model override). Anything Aider pins that we don't →
   record as a comparability invariant or adopt; do not assume.
4. Capture `aider --version` + a real headless transcript with the
   exact pinned argv on the maintainer machine; pin the constant
   verbatim.

## B1 — Backend (`scripts/benchmark_runner/backends/aider.py`)

Mirror `codex.py`: module docstring stating the pinned-argv contract;
`BACKEND_FAMILY="aider"`, `_VERIFIED_VERSION`,
`_DEFAULT_TIMEOUT_SECONDS=600`, `_STDERR_TAIL_CHARS=1024`,
`CCT_AIDER_TIMEOUT_SECONDS` override (mirror claude_code
`_timeout_override`), `AiderCliNotFoundError`, `AiderBackend.run`,
`_build_argv` (the pinned contract; `--model` iff non-empty;
`--edit-format` iff `CCT_AIDER_EDIT_FORMAT`), `_resolve_provider_env`
(presence booleans), `_build_metadata`, best-effort
`_parse_transcript`, `factory(model)`. Subprocess block byte-for-byte
the codex pattern (`Popen(... start_new_session=True)`,
`communicate(timeout=)`, `TimeoutExpired` → `os.killpg(os.getpgid,
SIGKILL)` + defensive re-`communicate(10s/5s)` →
`BackendResult(..., failed_commands=1, timed_out=True)`). Prompt
written to `attempt_dir/aider-message.txt`; history flags point at
`attempt_dir`. One-line `_register.py` block after codex.

## B2 — Tests (`tests/test_aider_backend.py` + `fixtures/aider/`)

Mirror `test_codex_backend.py`. Fake-`aider` shim on a PATH tmpdir
echoing `CCT_FAKE_AIDER_TRANSCRIPT`, logging `{argv, cwd,
message_file_contents, env_keys}`, writing a fake
`aider.chat.history.md` to the `--chat-history-file` path, honoring
`CCT_FAKE_AIDER_{STDERR,EXIT_CODE}`. Fixtures:
`transcript-success.txt` (token summary + `Edit format:` line),
`transcript-no-summary.txt` (no summary at all → all token fields
`None`), `transcript-zero-tokens.txt` (summary present, values 0 →
`0` not `None`). Three classes: `TestParseTranscript` (pure fn),
`TestBackendShape` (protocol/`backend_id`/`factory`/CLI-missing),
`TestBackendEndToEndAgainstFakeCli` (argv flag-by-flag; prompt via
`--message-file`; cwd==worktree; history files under `attempt_dir`;
**worktree clean — no `.aider*`/commits**; metadata booleans + no
`sk-`/`Bearer ` in `str(metadata)`; nonzero exit→`failed_commands=1`).
No live CLI / no network anywhere.

## B3 — Verification record (`specs/benchmark-harness/verification/aider.md`)

Mirror `codex.md` section-for-section: preamble (pinned `aider
--version`, captured live), ## Version, ## Verified argv (### Flag
contract table; ### Flags NOT present — `--yes` doesn't exist (the
flag is `--yes-always`, B0); no chat-mode flag intentional;
`--map-tokens/--edit-format` deliberately unpinned; `--temperature`
not an Aider flag at all), ## Transcript format (no JSON;
summary shape; key→field best-effort table; tokens may be None / cache
None / tool_calls {}), ## Real recorded transcript (live dump +
observed exit code), ## Provider routing (env presence booleans, never
set), ## Edit-format & comparability, ## Reviewer checklist (the 7
points, enumerated verbatim — see tasks.md). Also records the
`--no-stream` display-only confirmation.

## B4 — README + apples-to-apples procedure

README "Aider backend" section (invocation, model-string format,
provider env recorded-never-set) + "Aider-vs-Aider Polyglot
apples-to-apples (maintainer procedure)": the 9 comparability
invariants each mapped to where the existing adapter+backend satisfy
it; the exact leaderboard-faithful `./scripts/benchmark run --backend
aider --benchmark aider-polyglot …` command; the explicit
"this PR does not execute the leaderboard" statement; the
`dogfood-subset.txt` `*/leap` staleness caveat (pointing maintainers
at the full pool or verified-present `*/bowling`).

## Reuse map

Defers to spec.md § Reuse map. Headline: structurally clone `codex.py`
/ `codex.md` / `test_codex_backend.py`; inherit `run.py`'s
`_execute_attempt` (RunContext/timeout/D2/D5) unchanged; do not touch
bench.py, the aider_polyglot adapter, or dogfood-subset.txt.

## Test strategy

Stdlib `unittest`/pytest under `scripts/benchmark_runner/tests/`. New:
`test_aider_backend.py` (3 classes above). Run **per-module** — the
documented host failures (`test_polyglot_adapter`×4, `test_cli_skeleton`
hang, stale `test_polyglot_dogfood_subset`, `fixtures/**/leap_test.py`
autocollection) are pre-existing, not regressions (memories
`project_benchmark_preexisting_env_test_failures`,
`project_polyglot_dogfood_subset_stale`). Mandatory extra: the
post-`run()` worktree-cleanliness regression. Verify by tracing every
code path, not one sampled path (memory
`feedback_verify_delegated_build_trace_all_paths`).

## Delegation strategy

Single build agent, phase-scoped per B-step in order; reads
spec/plan/tasks first; one step per scoped invocation; runs that
step's tests; does not advance until green; does not commit (team lead
commits with per-step user diff approval). No parallel sub-agents —
steps are sequential (B2 needs B1; B3 needs the live capture; B4
references the shipped backend).

## Files to create

- `scripts/benchmark_runner/backends/aider.py`
- `scripts/benchmark_runner/tests/test_aider_backend.py`
- `scripts/benchmark_runner/tests/fixtures/aider/transcript-success.txt`
- `scripts/benchmark_runner/tests/fixtures/aider/transcript-no-summary.txt`
- `scripts/benchmark_runner/tests/fixtures/aider/transcript-zero-tokens.txt`
- `specs/benchmark-harness/verification/aider.md`
- `specs/benchmark-aider-backend/{spec,plan,tasks}.md` +
  `origin-alignment-2026-05-19-0332.md` (Phase A — this bundle)

## Files to modify

- `scripts/benchmark_runner/_register.py` — one block after codex.
- `benchmarks/README.md` — Aider section + apples-to-apples procedure
  (confirm exact path in B4; it is the benchmark README).

## Rollout

1. Branch `feat/benchmark-aider-backend` (already created), one PR
   titled `feat(benchmark): aider backend + verification +
   Aider-Polyglot apples-to-apples (Closes #41)`.
2. Commit chain: B1, B2, B3, B4, B5 (each reviewed; diff shown +
   explicit approval before every commit; never push to master).
3. PR opened only after per-module suites green,
   `check-origin-alignment.sh benchmark-aider-backend` ≤1, and the
   executable artifacts actually run (fake-CLI suite; `benchmark list`)
   — infra-verification discipline.
4. The live leaderboard run is a documented maintainer procedure, NOT
   part of the PR.
