---
spec_mode: full
feature_id: benchmark-adapters-backends
risk_category: integration
justification: "Extends the #32 benchmark harness: one authorized additive contract change (IsolationConfig.image), the first real docker isolation tier (container lifecycle, subprocess docker), a heavyweight external dataset adapter (SWE-bench Verified, HF-pinned, multi-GB images, local-only), and a second copilot backend (codex exec --json) with a recorded-transcript test + tracked verification record. Single PR fully closing #33 per user decision 2026-05-18. Integration risk: external CLIs/datasets/Docker, contract surface touched, downstream #34 dependency."
status: draft
date: 2026-05-18
issue: 33
origin:
  issue: gosha70/code-copilot-team#33
  origin_claim: |
    #33 v3: SWE-bench Verified adapter (required; first docker-tier
    use) + ≥1 additional copilot backend (codex), per-backend
    verification of the headless surface before the backend is relied
    on. No #32 contract method changes. Single-PR delivery + the two
    authorized deviations (in-PR contract field; in-PR verification
    record) per user decision 2026-05-18; deferred optional tracks
    filed as named follow-up issues.
---

# Implementation Plan — Benchmark Adapters & Backends (#33)

> **One PR.** Per the user decision (2026-05-18) and the repo
> governance rule, the entire scope ships in **one PR titled with
> `Closes #33`**. The phases below are **commit-ordered units inside
> that single PR**, not separate PRs. Dependency ordering (contract
> field → docker tier → adapter → backend → docs → verify) is
> preserved by the commit sequence.

## Approach

Build bottom-up so each layer is testable before the next sits on it,
and so the one risky executable artifact (the docker tier) is proven
with a real `docker` run before the SWE-bench adapter depends on it:

1. Additive contract field (inert; back-compat proven by the unchanged
   #32 suite).
2. docker isolation tier — implemented and **executed for real**
   (infra-verification) against a trivial public image, before any
   adapter needs it.
3. SWE-bench Verified adapter on top of the proven tier.
4. codex backend + its tracked verification record + recorded-
   transcript test (independent of 1–3; could be done in parallel but
   is sequenced last-but-one to keep the PR's commit story linear).
5. Registration + README + calibration note.
6. Full verification incl. a real local SWE-bench×claude-code run and
   the unchanged #32 CI smoke.

No phase changes a `BenchmarkAdapter`/`Backend` method signature.

## Phased delivery (commit-ordered units in ONE PR)

### Phase 1 — `IsolationConfig.image` (additive contract change)

**Goal:** the one authorized contract amendment, inert and
back-compatible.

- `contracts.py`: add `image: Optional[str] = None` to
  `IsolationConfig` with the docstring noting it is docker-tier-only.
- Runner: include `image` in the `run-record.json` `isolation` block
  next to `dockerfile`/`build_args` (audit parity).

**Acceptance:** entire existing #32 test suite passes unchanged
(back-compat); a constructed `IsolationConfig(tier="worktree")` still
valid; `image` round-trips into the run record.

**Failure modes considered:** a frozen-dataclass field-order or
default-arg break (mitigated: appended, defaulted); run-record schema
consumers (additive, null-safe — matches the #32 "no renames/removes,
null-safe additions" rule).

**Rollback:** delete one field + one record line; nothing depends on
it yet.

### Phase 2 — docker isolation tier (executed, not syntax-checked)

**Goal:** replace the `NotImplementedError` with a real, proven
provisioner.

- `isolation.py`: docker branch — probe `docker version` (missing →
  explicit `IsolationProvisionError` worded as an **environment**
  prerequisite, not a bug, not a skip). Create the host worktree dir
  (like `_provision_plain`) then `docker run -d` a long-lived
  container with the worktree **bind-mounted**
  (`-v <abs worktree>:/workspace -w /workspace <config.image>`);
  register `{worktree → container_id}` in a module-level dict; return
  the host worktree `Path` (signature unchanged). Add
  `run_in_worktree(worktree, argv, *, timeout, cwd=None) ->
  CompletedProcess` (docker-registered → `docker exec <cid>`; else
  local subprocess) and `release_worktree(config, worktree)`
  (`docker rm -f <cid>` for docker; **no-op for worktree/venv**).
  No DinD, no image build, no CI docker, **no provision-time copy**
  (bind-mount only — provision precedes `prepare_task`/backend so a
  copy would capture an empty dir).
- `run.py`: call `release_worktree(isolation_config, worktree)` in a
  `finally` after `verify` + diff (there is no teardown hook today;
  the call is a no-op for the existing tiers, so they are unaffected).
- Unit test with `docker` faked (subprocess shim, the backend fake-CLI
  pattern): provision registers a container, `run_in_worktree` routes
  to `docker exec`, `release_worktree` removes it, missing-daemon path
  errors as environment. PLUS a real local provision→`run_in_worktree`
  →teardown against a tiny public image (`alpine`) in Phase 6
  (infra-verification), output captured in the PR.

**Acceptance:** faked-subprocess unit tests green (provision/route/
release/missing-daemon); a real `docker`-backed
provision→exec→teardown of a trivial image succeeds locally (captured);
`run_in_worktree` on a non-docker worktree runs locally (parity);
`release_worktree` is a verified no-op for worktree/venv.

**Failure modes considered:** orphan containers on crash (`finally`
release + `-f`); image-pull failure vs daemon-down (distinct messages);
bind-mount path mismatch host↔container (explicit `-v <abs>:/workspace`
contract, asserted by test); non-zero in-container exit surfaced into
`VerifyResult`, not swallowed; `release_worktree` double-call
idempotent (registry pop).

**Rollback:** restore the `NotImplementedError` branch; Phase 1 field
becomes inert again.

### Phase 3 — SWE-bench Verified adapter

**Goal:** the required Track-A adapter on the proven docker tier.

- `benchmarks/adapters/swe_bench_verified/`: `REVISION` (HF dataset
  revision of `princeton-nlp/SWE-bench_Verified`); `fetch.py` —
  **stdlib `urllib`+`json` only**, paginates the HF datasets-server
  rows API (`datasets-server.huggingface.co/rows?...&revision=
  <REVISION>`) and normalizes to a content-addressed JSONL cache
  `benchmarks/.cache/swe-bench-verified/<rev>/tasks.jsonl` (NO
  Parquet/`pyarrow`/`datasets`; idempotent, loud-fail no-partial; CLI
  entry + documented update procedure; mirrors the Polyglot fetch
  lifecycle). `adapter.py` implementing the **unchanged**
  `BenchmarkAdapter` (`list_tasks` reads the JSONL with stdlib `json`,
  `isolation_for`→docker+image, `prepare_task` at `base_commit`,
  single-shot `prompt_for`, `verify` runs `FAIL_TO_PASS`+`PASS_TO_PASS`
  **via `isolation.run_in_worktree`** (in-container),
  `golden_patch`=dataset patch, `max_attempts()==1`); `__init__.py`;
  `register()`.

**Acceptance:** `./scripts/benchmark list --benchmark
swe-bench-verified` enumerates real instance ids from the pinned
revision; `prepare_task` materializes the repo at `base_commit`;
`verify` runs the task test sets in-container and computes
`tests_passed` correctly on a known-gold instance via `--backend stub`
locally; `golden_patch` returns the dataset patch; update procedure
documented + exercised (re-fetch idempotent).

**Failure modes considered:** HF revision unavailable / rows-API
pagination or rate-limit (fetch fails loudly, no partial cache; retries
with backoff bounded); instance image missing upstream (clear per-task
error, not a harness crash); `FAIL_TO_PASS` vs `PASS_TO_PASS`
mis-scoring incl. a `PASS_TO_PASS` regression → fail (unit test on a
synthetic task spec); multi-GB image cost (documented; local-only;
never CI).

**Rollback:** remove the adapter dir + its `register()` line; tier +
field remain (used by nothing else) — inert.

### Phase 4 — codex backend + verification record

**Goal:** the Track-B backend, with its verification record folded in
(Design Decision 1).

- `specs/benchmark-harness/verification/codex.md` (TRACKED — Design
  Decision 6): pinned **`codex-cli 0.130.0`** (verified live
  2026-05-18), the exact recorded headless invocation
  `codex exec --json --sandbox workspace-write --skip-git-repo-check
  [--model <model>] -` (prompt on stdin) against a hand-crafted
  prompt, the real transcript snapshot (JSONL: `thread.started` →
  `item.completed`/`agent_message` → `turn.completed`/`usage`),
  documented flag/env contract; reviewer confirms the backend argv
  matches it. **No `--ask-for-approval` flag exists on `codex exec`**
  (the planning probe disproved the earlier assumption — the gate
  worked). If a future pinned version's flags differ, the record is
  refreshed and the backend matches **that** (no silent drift).
- `scripts/benchmark_runner/backends/codex.py`: `BACKEND_FAMILY="codex"`,
  `factory`, `run()` — argv per Design Decision 9 (`--model
  <ctx.model>` only when non-empty; **prompt on stdin via trailing
  `-`**, not argv; `--sandbox workspace-write --skip-git-repo-check`;
  no approval flag — `exec` is inherently non-interactive), exactly
  matching the verification record; `cwd=ctx.worktree`, host env
  forwarded;
  defensive `--json` transcript parse (tokens/tools, null-vs-zero);
  `backend_metadata` records config.toml path + selected
  `model_providers.<id>` + version + exit/stderr-tail, never secrets.
- `tests/fixtures/codex/` recorded transcripts +
  `tests/test_codex_backend.py` (fake `codex` shim on PATH echoing the
  fixture + logging argv/stdin/cwd; no live CLI/network) — the
  `claude_code` pattern.

**Acceptance:** `test_codex_backend.py` green offline; `backend_metadata`
carries provider id + config path, never a key; the recorded fixture
shape matches the verification record; a reviewer reading
`verification/codex.md` can map every documented flag to the backend's
argv.

**Failure modes considered:** codex `--json` shape drift vs the pinned
version (the verification record is the contract; a mismatch is a
documented refresh, not silent acceptance); provider-config absent
(metadata records "none", backend still runs); secret leakage (test
asserts only presence/path/id in metadata).

**Rollback:** remove `codex.py` + fixtures + test + its `register()`
line + the verification doc; nothing else depends on it.

### Phase 5 — registration, README, calibration note

- `_register.py`: add the swe-bench-verified adapter + codex backend
  `register_*` calls (explicit; grep-able).
- `benchmarks/README.md`: `codex` row in the backend table + its
  provider-routing section (`~/.codex/config.toml`
  `[model_providers.<id>]`, recorded path+id); SWE-bench-verified
  adapter + `docker` tier section (local-only, multi-GB caveat,
  update procedure).
- Per-adapter calibration note (SWE-bench leaderboard is per-agent;
  same-agent-both-sides only) — merge-commit body or
  `specs/benchmark-harness/dogfood/<UTC-ts>-swe-bench-note/`.

**Acceptance:** `./scripts/benchmark list` shows both; README
documents codex env + SWE-bench/docker; `lint-wiki.sh` unaffected;
calibration note present.

**Rollback:** revert the doc/registration commit; trivial.

### Phase 6 — verification (real execution; #32 not regressed)

- `PYTHONPATH=scripts python3 -m unittest discover -s
  scripts/benchmark_runner/tests` — all green (incl. new docker/codex
  tests, unchanged #32 suite).
- Real local `docker` provision/teardown of a trivial image (captured)
  — infra-verification.
- Real local `./scripts/benchmark run --benchmark swe-bench-verified
  --backend claude-code --model sonnet --task <one-instance>` end-to-
  end (captured) — AC "end-to-end ≥1 task locally" + "docker tier
  exercised."
- `./scripts/benchmark list` output captured (both shown).
- The #32 CI stub×stub smoke (`.github/workflows/benchmark-smoke.yml`)
  unchanged + green (regression gate).
- `bash scripts/validate-spec.sh --feature-id
  benchmark-adapters-backends` exits 0.

**Acceptance:** every command above run and its output reported in the
PR; any failure fixed (not skipped); environment prerequisites (docker
daemon, HF access, an authenticated claude-code for the one live task)
reported distinctly from artifact bugs.

**Rollback:** the whole PR reverts as one unit (single PR); each phase
above is independently inert if its successors are removed.

## Reuse map

See `spec.md` § Reuse map. Summary: additive contract field; docker
provisioner patterned on the worktree/venv ones; SWE-bench fetch/pin
patterned on Polyglot's; codex backend + test patterned on
claude_code's; additive registration; infra-verification governs the
docker execution gate.

## Test strategy

- Unit: `IsolationConfig.image` back-compat; docker provisioner logic
  with faked `docker` subprocess; SWE-bench scoring
  (`FAIL_TO_PASS`/`PASS_TO_PASS`) on synthetic specs + `golden_patch`;
  codex backend via fake-CLI recorded transcript (offline).
- Real local (captured in PR, not CI): docker tier against a trivial
  image; one SWE-bench instance × claude-code end-to-end.
- Regression: full #32 suite unchanged-green; CI stub×stub smoke
  unchanged.
- No live CLI/network in unit tests; SWE-bench/docker never in CI.

## Delegation strategy

Single-implementer build via the build agent against this on-disk
spec, with the parent owning verification + all git (the pattern used
for #31/#37). The docker tier (Phase 2) must be executed for real
before Phase 3 is accepted.

## Files to create

- `scripts/benchmark_runner/backends/codex.py`
- `scripts/benchmark_runner/tests/test_codex_backend.py` (+
  `tests/fixtures/codex/…`)
- `scripts/benchmark_runner/tests/test_docker_isolation.py`
- `benchmarks/adapters/swe_bench_verified/{__init__.py,adapter.py,fetch.py,REVISION}`
- `scripts/benchmark_runner/tests/test_swe_bench_verified_adapter.py`
- `specs/benchmark-harness/verification/codex.md`
- `specs/benchmark-adapters-backends/IMPLEMENTATION_STATUS.md`

## Files to modify

- `scripts/benchmark_runner/contracts.py` — `IsolationConfig.image`
- `scripts/benchmark_runner/isolation.py` — docker tier +
  `run_in_worktree` + `release_worktree` + worktree→container registry
- `scripts/benchmark_runner/run.py` — record `image` in the isolation
  block (`_isolation_record`, ~line 287) **and** call
  `release_worktree(...)` in a `finally` after verify+diff (no teardown
  hook exists today; no-op for non-docker tiers)
- `scripts/benchmark_runner/_register.py` — register adapter + backend
- `benchmarks/README.md` — codex + SWE-bench/docker sections

## Rollout

**One PR** against `master`, branch `feat/benchmark-adapters-backends`,
title `feat(benchmark): SWE-bench Verified + docker tier + codex backend (Closes #33)`.
Commit sequence = Phases 1→6. PR body: AC table (with the two
user-authorized deviations explicitly flagged), the real-execution
evidence (docker run + SWE-bench live task + list output + #32 smoke),
and the named follow-up issues filed for the deferred tracks
(aider backend, github-copilot backend, optional adapters). #34 noted
as unblocked on merge.
