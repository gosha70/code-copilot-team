---
feature_id: benchmark-aider-backend
spec_mode: full
status: draft
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
    - https://github.com/gosha70/code-copilot-team/issues/46
  origin_claim: |
    Issue #41: "Follow-up to #33 (deferred, not partially built per the
    one-PR-per-issue rule). Add the `aider` copilot backend to the
    benchmark harness: a separate verification record (pinned
    `aider --version` + recorded headless transcript of the working
    non-interactive invocation) landing with the backend code in one PR
    that fully closes this issue; recorded-transcript test (no live
    CLI); provider env recorded never set; README. Also: the
    apples-to-apples Aider-vs-Aider Polyglot leaderboard comparison
    (only meaningful with the Aider backend). Pattern: mirror the codex
    backend (scripts/benchmark_runner/backends/codex.py) +
    specs/benchmark-harness/verification/codex.md shipped in #33."
    Four user clarifications (2026-05-19) lock: mirror codex exactly
    (aider NOT bench-addressable); verbatim model-string passthrough;
    methodology-fidelity (pin only headless/hygiene flags, never
    model/edit/repo-map/temperature behavior); leaderboard = runnable
    path + invariants, not executed in the PR.
---

# Aider Backend — `aider` copilot backend + verification + Polyglot apples-to-apples

> **Mirror codex, structurally.** This feature adds a fourth backend
> (`aider`) to the benchmark harness by mirroring the codex backend,
> its verification record, and its recorded-transcript test. It changes
> no harness orchestration, scoring, or adapter logic. Where Aider's
> CLI reality forces departures from the codex template (no JSON
> output; prompt via file not stdin; methodology-bearing flags left at
> Aider's defaults), each is recorded in § Deviation from origin and
> was confirmed with the user 2026-05-19.

## Problem

The harness ships `claude-code`, `stub`, and `codex` backends. Issue
#33 deferred the `aider` backend under the one-PR-per-issue rule; #41
is that deferred work. Without an `aider` backend the harness cannot
drive the Aider coding agent, and therefore cannot produce numbers
comparable to Aider's own published polyglot leaderboard — the single
most-cited external benchmark for "how good is model X at agentic
code editing." The codex backend (#33) established the exact pattern
to follow: a `Backend` implementation, a committed verification record
(pinned `--version` + a real recorded headless transcript), a
recorded-transcript test that never spawns the live CLI, provider env
recorded-but-never-set, and a README section. #41 reproduces that
pattern for Aider and adds the apples-to-apples leaderboard procedure
that only becomes meaningful once the Aider backend exists.

## User Scenarios

1. **Run Aider as the agent on a Polyglot task.**
   `./scripts/benchmark run --benchmark aider-polyglot --backend aider
   --model anthropic/claude-sonnet-4-5 --task python/bowling --runs 3`
   drives Aider non-interactively against the existing aider-polyglot
   adapter; per-attempt artifacts, scoring, heartbeat, and timeout
   classification all work exactly as for codex.
2. **Compare Aider against another backend.** A compare-config with a
   `{"backend":"aider","model":"anthropic/claude-sonnet-4-5"}` candidate
   runs alongside e.g. a `claude-code` candidate; the aggregate report
   groups them like any other comparison.
3. **Audit a run's methodology.** A reviewer opens a run's
   `run-record.json` / backend_metadata and sees `aider_version`, the
   *resolved* `edit_format`, effective `map_tokens`,
   `chat_mode`, and provider-env *presence booleans* — never any key
   value — enough to judge leaderboard comparability.
4. **A hung Aider attempt.** Aider exceeds the per-attempt timeout; the
   backend kills the process group, returns `timed_out=True`, the
   campaign records `result:"timeout"` and continues — inherited free
   from `run.py` (D5 of #36), no aider-specific code.
5. **Reproduce the Aider leaderboard.** A maintainer follows the
   documented apples-to-apples procedure (the 9 comparability
   invariants + the exact leaderboard-faithful command) to produce
   numbers directly comparable to https://aider.chat/docs/leaderboards/.
   The PR does not execute this run (maintainer-scale, like the
   existing dogfood Gate).

## Interface

### Addressing (codex-identical; bench untouched)

`aider` is a backend, not a bench provider. The `scripts/bench`
wrapper's parser whitelists *providers* (sonnet/ollama:/vllm:/…) that
all resolve to `backend=claude-code`; it has no backend concept and is
**not modified**. Aider — like codex — is addressed only via the
lower-level harness:

```bash
./scripts/benchmark run --benchmark aider-polyglot \
    --backend aider --model anthropic/claude-sonnet-4-5 \
    --task python/bowling --runs 3
# or compare-config:  { "candidates": [
#   { "name": "aider-sonnet", "backend": "aider",
#     "model": "anthropic/claude-sonnet-4-5" } ] }
```

Architectural separation (documented, not papered over): *bench
wrapper = one backend (claude-code) / many LLM providers*;
*`scripts/benchmark run|compare` = many backends, each with its own
model-string convention*. Aider joins codex in the second category.

### Pinned aider argv (the contract)

```
aider
  --model <model>              # only when ctx.model non-empty (codex pattern)
  --yes-always                 # auto-confirm (the ONLY flag; `--yes` does NOT exist — B0)
  --no-auto-commits
  --no-dirty-commits
  --no-gitignore
  --no-git                     # do not create/use a git repo (B3 capture confirmed
                               #   real aider creates .git/ in a non-git dir,
                               #   polluting _write_diff). See #46 for the
                               #   git-with-cleanup follow-up evaluation.
  --no-check-update            # no startup network version check
  --no-stream                  # reliable end-of-run summary (display-only;
                               #   confirmed in the verification record)
  --chat-history-file <attempt_dir>/aider.chat.history.md
  --llm-history-file  <attempt_dir>/aider.llm.history.txt
  [--edit-format <fmt>]        # ONLY if CCT_AIDER_EDIT_FORMAT set; else omitted
  --message-file <attempt_dir>/aider-message.txt   # prompt; no codex-style stdin
```

`--model` is appended only when `ctx.model` is non-empty (codex
pattern). The prompt is written to `aider-message.txt` and passed via
`--message-file` (Aider has no codex `-` stdin; message files handle
the large multiline two-shot prompts). Message + history files live in
`attempt_dir` (= `ctx.worktree.parent`), never in `worktree`. NOT
pinned (Decision 3 — methodology fidelity): `--map-tokens`,
`--edit-format` (unless `CCT_AIDER_EDIT_FORMAT`), chat-mode (→ Aider
default `code`). **Aider exposes no `--temperature` CLI flag (B0
confirmed)** — temperature is Aider-internal (litellm default); the
harness neither sets nor can observe it via the CLI.

### backend_metadata schema (presence/paths only — never secret values)

`family="aider"`, `model`, `aider_version` (pinned constant),
`chat_mode="code"`, `edit_format_resolved` (parsed or `None`),
`edit_format_forced` (bool), `map_tokens_effective` (parsed or `None`),
`auto_commits=False`, `dirty_commits=False`, `provider_env_present` =
`{ANTHROPIC_API_KEY, OPENAI_API_KEY, OPENROUTER_API_KEY,
OPENAI_API_BASE}` booleans only, `exit_code`, `stderr_tail` (≤1024
chars), optional `note` (timeout only).

### Transcript

Aider emits no JSON. stdout → `attempt_dir/transcript.txt`, stderr →
`attempt_dir/transcript.stderr.txt`; Aider's own
`aider.chat.history.md` / `aider.llm.history.txt` already land in
`attempt_dir` via the pinned flags. `model_output_path` = the chat
history file if non-empty, else `None`. `_parse_transcript` is
best-effort: tolerant regex over Aider's `Tokens:`/cost summary →
`tokens_input/output`; `cache_*` always `None`; `tool_calls` always
`{}`; the `Edit format:` line → `edit_format_resolved`.
`failed_commands = 0 if returncode==0 else 1`.

### Apples-to-apples (documented procedure, not executed in the PR)

A README + verification-record section: the 9 comparability invariants
(same 225-task Polyglot pool; 2 attempts; attempt-2 receives attempt-1
test output; pass@2 primary / pass@1 secondary; per-model default edit
format; resolved edit_format recorded; model+params recorded; T=0 not
truly deterministic; unit-test-exit-0 scoring), each mapped to where
the existing `aider_polyglot` adapter (`max_attempts()==2`,
`prior.tests_output` on attempt 2) + this backend already satisfy it;
the exact leaderboard-faithful command; an explicit non-execution
statement; and the `dogfood-subset.txt` `*/leap` staleness caveat.

## Reuse map

- `scripts/benchmark_runner/backends/codex.py` — structural template
  (class shape, `_build_argv`, Popen + `start_new_session=True` +
  `os.killpg(SIGKILL)` timeout block, `_build_metadata`, `factory`).
- `scripts/benchmark_runner/backends/claude_code.py` — the
  `timed_out=True` D5 signal + the `CCT_*_TIMEOUT_SECONDS` override
  (`_timeout_override`) pattern.
- `scripts/benchmark_runner/run.py` — `_execute_attempt` (RunContext,
  timeout, D2 heartbeat, D5 classification) inherited unchanged; its
  `_write_diff` (= `diff -urN -x .venv …`, excludes ONLY `.venv`) is
  the constraint that forces the no-commit / history-outside-worktree
  flags.
- `scripts/benchmark_runner/_register.py` — one-line registration.
- `scripts/benchmark_runner/tests/test_codex_backend.py` — fake-shim
  test design (PATH shim echoing a fixture, 3 test classes).
- `specs/benchmark-harness/verification/codex.md` — verification-record
  shape.
- `benchmarks/adapters/aider_polyglot/` — already implements the
  2-attempt/pass@2 protocol; **not modified**.

## Design Decisions

1. **Mirror codex exactly; bench untouched (user, 2026-05-19).** No
   `aider:` token in `bench.py`; codex isn't bench-addressable either;
   #41's body never mentions bench. A "bench supports non-claude-code
   backends" follow-up is explicit future scope the user files
   post-#41 — out of scope here.
2. **Verbatim model-string passthrough.** `ctx.model` (Aider-native
   `<provider>/<model>`) is passed straight to `--model`; no aliasing
   (mirrors codex).
3. **Methodology-fidelity principle.** The argv contract pins ONLY
   headless-operation and worktree-hygiene flags. It pins nothing that
   changes model/edit/repo-map/temperature behavior — those use
   Aider's defaults so the harness matches Aider's published
   leaderboard methodology; the *resolved* values are recorded for
   audit. (An earlier draft pinned `--map-tokens 0` "for determinism";
   reopened on review — that would systematically depress numbers vs
   Aider's leaderboard, which runs the default repo map. Corrected:
   not pinned; repo-map variance accepted as one more run-variance
   source, same class as LLM nondeterminism.) `CCT_AIDER_EDIT_FORMAT`
   is the only force path (sets `edit_format_forced=true`).
4. **Leaderboard = runnable path + invariants, not executed.** The
   225-task pass@2 run is maintainer-scale (hours, real spend), like
   the existing dogfood Gate. The PR ships the documented invariants +
   exact command; it does not run the leaderboard.
   `dogfood-subset.txt`'s stale `*/leap` ids are a pre-existing issue
   left as a documented caveat, not fixed here (scope discipline).

## Requirements

1. `scripts/benchmark_runner/backends/aider.py` implements `Backend`
   mirroring codex: `BACKEND_FAMILY="aider"`, `AiderBackend.run`,
   `_build_argv` emitting the pinned contract, Popen +
   process-group-SIGKILL timeout returning
   `BackendResult(..., failed_commands=1, timed_out=True)`,
   `_build_metadata`, best-effort `_parse_transcript`, a
   `CCT_AIDER_TIMEOUT_SECONDS` override, module-level `factory(model)`.
2. One-line registration in `_register.py`.
3. `specs/benchmark-harness/verification/aider.md` mirrors `codex.md`
   sections, with the pinned `aider --version`, a real recorded
   headless transcript (captured at Phase-B start on the maintainer
   machine), the enumerated 7-point reviewer checklist, and the
   `--no-stream` display-only confirmation.
4. `scripts/benchmark_runner/tests/test_aider_backend.py` + fixtures
   `transcript-{success,no-summary,zero-tokens}.txt` mirror
   `test_codex_backend.py` (fake-CLI shim; no live CLI / no network);
   `no-summary`→all token fields `None`, `zero-tokens`→`0` (distinct
   asserted paths); plus a post-`run()` worktree-cleanliness assertion
   (no `.aider*`, no commits).
5. README "Aider backend" section + the apples-to-apples maintainer
   procedure (9 invariants, exact command, non-execution statement,
   `dogfood-subset` caveat).
6. Provider env (`ANTHROPIC_API_KEY` etc.) is recorded as presence
   booleans only and never set by the harness.
7. One PR that fully closes #41 (no partial/phased delivery).

## Constraints / What NOT to Build

1. **No `bench.py` change.** No `aider:` provider token; bench stays
   one-backend/many-providers.
2. **No `dogfood-subset.txt` refresh.** Pre-existing stale `*/leap`
   data; documented caveat only.
3. **No `aider_polyglot` adapter change.** It already implements
   2-attempt/pass@2; the apples-to-apples claim rides on it unmodified.
4. **No live CLI / network in tests.** Recorded-transcript fake-shim
   only (issue #41 explicit).
5. **No leaderboard execution in the PR.** Maintainer procedure only.
6. **No new harness orchestration/scoring.** D2 heartbeat + D5 timeout
   classification are inherited; nothing in `run.py` is modified.
7. **No secrets recorded.** Provider env presence booleans only.

## Key Entities

- **AiderBackend** — the `Backend` implementation.
- **Pinned argv contract** — the exact `aider` invocation; the audited
  unit of comparability.
- **Verification record** (`verification/aider.md`) — pinned version +
  recorded transcript + flag contract + 7-point reviewer checklist.
- **Comparability invariants** — the 9 conditions under which CCT-Aider
  numbers are leaderboard-comparable.
- **Fake-aider shim** — test-only PATH executable echoing a fixture.

## Success Criteria

- [ ] `./scripts/benchmark run --backend aider --model <m> --benchmark
      aider-polyglot --task python/bowling` drives Aider end-to-end
      (verified via fake-CLI in tests; live path documented).
- [ ] `python3 -m benchmark_runner list` shows `aider` in backends.
- [ ] Fake-CLI end-to-end test asserts the argv contract flag-by-flag,
      prompt via `--message-file`, history files under `attempt_dir`,
      and a clean `worktree` (no `.aider*`/commits) after `run()`.
- [ ] `_parse_transcript`: `no-summary`→all token fields `None`;
      `zero-tokens`→`0`; `success`→parsed tokens + `edit_format_resolved`.
- [ ] `backend_metadata` carries provider presence booleans + resolved
      edit_format/map_tokens (no `temperature` — not an Aider flag);
      `str(metadata)` contains no `sk-`/`Bearer ` substring.
- [ ] Timeout path sets `timed_out=True`; `result:"timeout"` inherited
      from `run.py` with no aider-specific code.
- [ ] `verification/aider.md` carries the real pinned version, a real
      recorded transcript, and the enumerated 7-point checklist.
- [ ] README has the Aider section + the 9-invariant apples-to-apples
      procedure with the explicit non-execution statement.
- [ ] `validate-spec.sh --feature-id benchmark-aider-backend` and
      `check-origin-alignment.sh benchmark-aider-backend` exit 0.
- [ ] One PR `Closes #41`; bench.py / dogfood-subset / aider_polyglot
      adapter untouched.

## Deviation from origin

"Mirror codex" holds structurally. Forced departures, all recorded
here and in `verification/aider.md`:

1. **Transcript is text, not JSONL** — Aider emits no JSON.
2. **Token metrics best-effort / often `None`**; `cache_*` always
   `None`; `tool_calls` always `{}` (Aider has no codex tool events).
3. **Prompt via `--message-file`**, not codex's `-` stdin.
4. **Provider routing = env-presence booleans**, not codex's
   `config.toml` path/provider id (Aider routes via env vars).
5. **Extra pinned `--no-auto-commits --no-dirty-commits
   --no-gitignore --no-git`** — no codex analogue; forced by `run.py`'s
   `_write_diff` excluding only `.venv` (commits/`.aider*`/`.git/` in
   the worktree would pollute every scored diff). The B3 recorded
   capture proved real aider creates `.git/` in a non-git dir despite
   `--no-gitignore`; `--no-git` (confirmed in aider 0.86.2 options
   reference) suppresses it and yields `Git repo: none`,
   `Repo-map: disabled` in the transcript. Apples-to-apples caveat:
   Aider's published Polyglot leaderboard runs each exercise inside a
   git repo, so `--no-git` may degrade the repo-map on multi-file
   tasks — tracked for empirical evaluation in
   gosha70/code-copilot-team#46 (git-with-cleanup pattern).
6. **Exit codes pinned empirically** — Aider's are undocumented; the
   recorded transcript pins observed success behavior.

NOT a deviation (the opposite): leaving `--map-tokens` and
`--edit-format` at Aider's defaults is the methodology-fidelity choice
that keeps the apples-to-apples claim honest (Design Decision 3).
Temperature is not an Aider CLI flag at all (B0) — Aider-internal,
neither set nor recorded by the harness; noted in the invariants doc.

Documented comparability caveat (no code change — adapter is OUT of
scope): Aider's own polyglot harness truncates attempt-2 test output
to the first 50 lines; the CCT `aider_polyglot` adapter appends the
full `prior.tests_output`. Recorded in the invariants doc, not
modified here.

## Sources

- `issue: gosha70/code-copilot-team#41` — deliverables, one-PR rule,
  "mirror codex" directive.
- `issue: gosha70/code-copilot-team#33` — the codex backend +
  `verification/codex.md` this mirrors.
- `path: scripts/benchmark_runner/backends/codex.py` — structural
  template.
- `path: scripts/benchmark_runner/run.py` — `_execute_attempt`,
  `_write_diff` (`.venv`-only exclusion).
- `url: https://aider.chat/docs/config/options.html` — authoritative
  flag reference: `--message-file`, `--yes-always`, `--no-auto-commits`,
  `--no-dirty-commits`, `--no-gitignore`, `--no-check-update`,
  `--no-stream` (display-only), `--edit-format` (per-model default);
  confirmed no `--yes` and no `--temperature` (B0).
- `url: https://aider.chat/docs/leaderboards/` +
  `https://aider.chat/2024/12/21/polyglot.html` — 225-task pool,
  2-attempt pass@2, per-model edit format, 50-line attempt-2 truncation.
- `decisions: 2026-05-19 user clarifications` — mirror-codex/bench-out;
  verbatim model string; methodology-fidelity (no map-tokens pin);
  leaderboard runnable-not-executed.
