# Tasks — Benchmark Adapters & Backends (#33)

One PR (`Closes #33`). Tasks are commit-ordered units **inside that
single PR**, not separate PRs. The docker-tier task (T2.x) must be
**executed for real** before the SWE-bench adapter (T3.x) is accepted
(infra-verification). Two user-authorized deviations from #33's literal
text are recorded in `spec.md` Design Decisions 1 & 6 (in-PR contract
field; in-PR verification record).

AC→task map is in `spec.md` § Acceptance Criteria. Deferred optional
tracks (aider, github-copilot, BigCodeBench/LiveCodeBench/cct-dogfood)
are filed as named follow-up issues (T5.4), not partially built here.

## Phase 1 — IsolationConfig.image (additive contract change)

### T1.1 — add `image` field + record it
- **Output:** `contracts.py` `IsolationConfig` gains
  `image: Optional[str] = None` (docstring: docker-tier-only); the
  run-record `isolation` block includes `image` alongside
  `dockerfile`/`build_args`.
- **Done when:** full existing #32 test suite passes unchanged;
  `IsolationConfig(tier="worktree")` still valid; a docker-tier config
  round-trips `image` into `run-record.json`. No `BenchmarkAdapter`/
  `Backend` method signature changed.

## Phase 2 — docker isolation tier (executed)

### T2.1 — docker provisioner + helper + teardown
- **Output:** `isolation.py` docker branch replacing the
  `NotImplementedError`: probe `docker version` (missing → explicit
  environment error, not skip/bug); create host worktree dir then
  `docker run -d` a long-lived container with the worktree
  **bind-mounted** (`-v <abs>:/workspace -w /workspace
  <config.image>`); register `{worktree→container_id}`; return host
  worktree `Path` (signature unchanged). Add
  `run_in_worktree(worktree, argv, *, timeout, cwd=None)` (docker →
  `docker exec <cid>`; else local subprocess) and
  `release_worktree(config, worktree)` (`docker rm -f` for docker;
  **no-op for worktree/venv**; idempotent). `run.py`: call
  `release_worktree` in a `finally` after verify+diff. **No
  provision-time copy** (bind-mount only).
- **Done when:** faked-`docker` unit tests cover provision-registers /
  `run_in_worktree`-routes-to-`docker exec` / `release_worktree`-
  removes / missing-daemon-errors / non-docker-`run_in_worktree`-runs-
  local / `release_worktree`-no-op-for-worktree-venv; no DinD, no image
  build, no CI docker, no provision-time copy.

### T2.2 — real docker execution (infra-verification)
- **Output:** a real local provision → `run_in_worktree` (run a
  command in-container) → `release_worktree` against a trivial public
  image (`alpine`), output captured for the PR body.
- **Done when:** the real run succeeds, the in-container command output
  is captured, teardown leaves no orphan container; missing-daemon
  reproduction yields the environment error verbatim. (Executed, not
  syntax-checked.)

## Phase 3 — SWE-bench Verified adapter

### T3.1 — `fetch.py` + `REVISION` (HF rows API → JSONL, stdlib-only)
- **Output:** `benchmarks/adapters/swe_bench_verified/REVISION` (HF
  revision of `princeton-nlp/SWE-bench_Verified`) + `fetch.py` —
  **stdlib `urllib`+`json` only**, paginates
  `datasets-server.huggingface.co/rows?...&revision=<REVISION>` and
  normalizes to content-addressed JSONL
  `benchmarks/.cache/swe-bench-verified/<rev>/tasks.jsonl` (NO
  Parquet/`pyarrow`/`datasets`); CLI entry, idempotent; documented
  update procedure; mirrors the Polyglot fetch lifecycle.
- **Done when:** `python3 -m
  benchmarks.adapters.swe_bench_verified.fetch` populates the pinned
  JSONL cache idempotently using only stdlib; a stale/missing revision
  or a paginated-fetch interruption fails loudly with no partial
  cache; no third-party import anywhere in the module.

### T3.2 — `adapter.py` (unchanged #32 contract)
- **Output:** `adapter.py` implementing `BenchmarkAdapter`:
  `benchmark_id="swe-bench-verified"`, `isolation_default=docker`,
  `list_tasks` (one per instance; metadata = image/base_commit/
  FAIL_TO_PASS/PASS_TO_PASS/test_cmd/repo), `isolation_for`→
  `IsolationConfig(tier=docker, image=…)`, `prepare_task` at
  `base_commit`, single-shot `prompt_for`, `verify` **via
  `isolation.run_in_worktree`** (in-container) over
  `FAIL_TO_PASS`+`PASS_TO_PASS`, `golden_patch`=dataset patch,
  `max_attempts()==1`; `list_tasks` reads the JSONL cache with stdlib
  `json`; `__init__.py`; `register()`.
- **Done when:** `./scripts/benchmark list --benchmark
  swe-bench-verified` enumerates real instance ids; `verify` scores
  `tests_passed` correctly on a known-gold instance via `--backend
  stub` locally; `golden_patch` returns the dataset patch; a synthetic-
  spec unit test covers FAIL_TO_PASS/PASS_TO_PASS scoring incl. a
  PASS_TO_PASS regression → fail.

## Phase 4 — codex backend + verification record

### T4.1 — verification record (tracked, in-PR)
- **Output:** `specs/benchmark-harness/verification/codex.md`: pinned
  **`codex-cli 0.130.0`** (verified live 2026-05-18), recorded headless
  invocation `codex exec --json --sandbox workspace-write
  --skip-git-repo-check [--model <model>] -` (prompt on stdin) against
  a hand-crafted prompt, real transcript snapshot (JSONL
  `thread.started`/`item.completed`(`agent_message`)/`turn.completed`
  (`usage.{input_tokens,cached_input_tokens,output_tokens,
  reasoning_output_tokens}`)), documented flag/env contract — and an
  explicit note that **`codex exec` has no `--ask-for-approval` flag**
  (the assumed flag was disproved by the planning probe). (In-PR per
  Design Decision 1; tracked location per Design Decision 6.) If a
  future pinned version's flags differ, the record documents the actual
  working set.
- **Done when:** a reviewer can map every documented flag/env to the
  T4.2 backend argv; the snapshot shape matches the T4.3 fixture.

### T4.2 — `codex.py` backend (unchanged #32 contract)
- **Output:** `scripts/benchmark_runner/backends/codex.py`:
  `BACKEND_FAMILY="codex"`, `factory`, `run()` — argv per Design
  Decision 9 (`codex exec --json --sandbox workspace-write
  --skip-git-repo-check [--model <ctx.model> when non-empty] -`,
  **prompt on stdin** via trailing `-`, no approval flag) exactly
  matching the `codex-cli 0.130.0` verification record;
  `cwd=ctx.worktree`, host env forwarded; defensive `--json`
  transcript parse (tokens/tools, null-vs-zero); `backend_metadata` =
  family/model/config.toml path/selected
  `model_providers.<id>`/version/exit/stderr-tail — never secrets.
- **Done when:** argv matches the verification record exactly;
  `--model` present iff `ctx.model` non-empty; prompt delivered on
  stdin; `backend_metadata` carries provider id + config path and no
  key.

### T4.3 — recorded-transcript test (offline)
- **Output:** `tests/fixtures/codex/…` recorded transcripts +
  `tests/test_codex_backend.py` (fake `codex` shim on PATH echoing the
  fixture, logging argv/stdin/cwd) — the `claude_code` pattern.
- **Done when:** test green with no live CLI/network; asserts argv,
  metadata (provider id/path present, no secret), and parsed
  tokens/tools incl. the null-vs-zero distinction.

## Phase 5 — registration, docs, calibration, follow-ups

### T5.1 — register both
- **Output:** `_register.py` adds the swe-bench-verified adapter +
  codex backend `register_*` calls (explicit, grep-able).
- **Done when:** `./scripts/benchmark list` shows `swe-bench-verified`
  AND `codex`.

### T5.2 — README
- **Output:** `benchmarks/README.md`: `codex` backend-table row +
  provider-routing section (`~/.codex/config.toml`
  `[model_providers.<id>]`, recorded path+id); SWE-bench-verified
  adapter + `docker` tier section (local-only, multi-GB caveat,
  update procedure).
- **Done when:** README documents codex env + SWE-bench/docker;
  existing structure/links intact.

### T5.3 — calibration note
- **Output:** per-adapter calibration note — SWE-bench leaderboard is
  per-agent; comparison meaningful only same-agent-both-sides — in the
  merge-commit body or
  `specs/benchmark-harness/dogfood/<UTC-ts>-swe-bench-note/`.
- **Done when:** the note exists and states the per-agent caveat
  explicitly.

### T5.4 — file named follow-up issues
- **Output:** GitHub issues filed for the deferred tracks: (a) aider
  backend + verification + apples-to-apples Aider-Polyglot comparison;
  (b) github-copilot backend + verification; (c) optional adapters
  (BigCodeBench/LiveCodeBench/cct-dogfood). Each scoped to be closable
  by one complete PR. Referenced from the #33 PR body; #34 noted as
  unblocked on merge.
- **Done when:** the follow-up issues exist and are linked in the PR
  body and in `spec.md` § Named follow-ups.

## Phase 6 — verification (real execution; #32 not regressed)

### T6.1 — full + real-execution verification
- **Output:** captured outputs of: full `unittest discover`
  (new + unchanged #32 suite green); real docker provision/teardown
  (T2.2); one real `./scripts/benchmark run --benchmark
  swe-bench-verified --backend claude-code --model sonnet --task
  <instance>` end-to-end; `./scripts/benchmark list`.
- **Done when:** all run, outputs in the PR body, failures fixed (not
  skipped); environment prerequisites (docker daemon, HF access,
  authenticated claude-code) reported distinctly from artifact bugs.

### T6.2 — regression + spec gates
- **Output:** the #32 CI stub×stub smoke unchanged + green;
  `bash scripts/validate-spec.sh --feature-id
  benchmark-adapters-backends` exits 0.
- **Done when:** both pass; no #32 test/file regressed; PR opened
  `Closes #33` with the AC table (deviations flagged) + follow-up
  links; merged when CI green; #33 auto-closed; #34 unblocked.
