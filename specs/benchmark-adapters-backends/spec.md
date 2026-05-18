---
feature_id: benchmark-adapters-backends
spec_mode: full
status: draft
issue: 33
origin:
  issue: gosha70/code-copilot-team#33
  urls:
    - https://www.swebench.com/verified.html
    - https://developers.openai.com/codex/config-advanced
    - https://developers.openai.com/codex/cli/reference
  origin_claim: |
    #33 (v3, 2026-05-08) extends the #32 benchmark harness with (Track
    A) additional benchmark adapters — SWE-bench Verified required, the
    first real use of the docker isolation tier — and (Track B)
    additional copilot backends (codex/aider/github-copilot), each
    gated by a per-backend verification of the headless invocation
    surface against a pinned CLI version + recorded transcript BEFORE
    the backend code lands. Bar: ship SWE-bench Verified (Track A) AND
    ≥1 backend (Track B). No changes to the #32 BenchmarkAdapter/
    Backend contracts unless via a separate amendment. #34's
    calibration corpus is blocked until #33 ships ≥1 additional
    backend.
---

# Benchmark Adapters & Backends — SWE-bench Verified + docker tier + codex backend

> **Delivery-shape notice (user decision, 2026-05-18).** #33's text
> mandates a multi-PR shape (a separate IsolationConfig amendment PR;
> a separate per-backend verification PR landing *before* backend
> code). The user explicitly chose **a single PR that fully closes
> #33, no precursor PRs**. Two deviations from #33's literal text are
> therefore **authorized and recorded** (Design Decisions 1 & 6); they
> are not oversights. The single-PR shape also satisfies the
> repo governance rule "a merged PR must fully close its issue."

## Problem

#32 (CLOSED, PR #35) shipped the benchmark-agnostic harness: the
`BenchmarkAdapter` + `Backend` contracts, `worktree` / `worktree+venv`
isolation, the `aider-polyglot` + `stub` adapters, the `claude-code` +
`stub` backends, run records, deterministic scoring, the report/winner
rule, and the CI stub×stub smoke gate. The `docker` isolation tier was
*defined but unimplemented* — `scripts/benchmark_runner/isolation.py`
raises `NotImplementedError("isolation tier 'docker' lands with issue
#33's SWE-bench adapter")`.

To make CCT useful as a measurement framework, #33 adds:

- **Track A:** the **SWE-bench Verified** adapter — the gold-standard
  agentic-coding benchmark (500 human-validated real GitHub issues),
  which forces the first real implementation of the `docker` isolation
  tier (each task ships a prebuilt image).
- **Track B:** the first **additional copilot backend** beyond
  `claude-code`. Without it, #34's LLM-judge calibration corpus is too
  narrow (one backend × N models) to detect rubric drift — a
  load-bearing downstream dependency.

This spec scopes **exactly one PR** that fully closes #33 by meeting
its bar: SWE-bench Verified (Track A) **and** the `codex` backend
(Track B), with codex's verification record folded inline.

## Scope of this PR (closes #33)

In:

1. **`IsolationConfig.image`** — additive `Optional[str]` field on the
   #32 contract (the one authorized contract change; Design Decision 1).
2. **`docker` isolation tier** — real implementation in `isolation.py`
   (pull per-task image, container lifecycle, worktree mount, in-
   container command execution), replacing the `NotImplementedError`.
3. **SWE-bench Verified adapter** —
   `benchmarks/adapters/swe_bench_verified/` implementing the #32
   `BenchmarkAdapter` contract unchanged; HF-dataset pin via `REVISION`
   + `fetch.py`; `tier: docker`; `max_attempts() == 1`.
4. **`codex` backend** — `scripts/benchmark_runner/backends/codex.py`
   implementing the #32 `Backend` Protocol unchanged; `codex exec
   "<prompt>" --json`; provider-routing env recorded (never set);
   recorded-transcript test via a fake-CLI shim (the `claude_code`
   test pattern).
5. **codex verification record** —
   `specs/benchmark-harness/verification/codex.md` (TRACKED location;
   Design Decision 6): pinned `codex --version`, recorded headless
   invocation transcript against a hand-crafted prompt, documented
   flag/env contract. Folded into this PR (not a separate PR — Design
   Decision 1).
6. **Registration + docs** — register both in `_register.py`;
   `./scripts/benchmark list` shows both; `benchmarks/README.md`
   backend table + codex provider-routing section + SWE-bench adapter
   + docker-tier section; per-adapter calibration note.

Out (deferred to **named follow-up issues**, not half-built here —
governance: optional tracks are not partially delivered):

- **`aider` backend** + its verification record → follow-up issue
  (includes the apples-to-apples Aider-Polyglot leaderboard
  comparison, which is only meaningful with the Aider backend).
- **`github-copilot` backend** → follow-up issue (April 2026 BYOK
  surface too recent; #33 itself permits dropping it).
- **BigCodeBench / LiveCodeBench / cct-dogfood-\*** adapters →
  follow-up issue(s); all explicitly optional in #33.
- LLM-judge scoring / charts / HTML — #34. Provider-config feature —
  `specs/provider-config/`. GUI-only copilots — not headless.

The deferred items are listed in § "Named follow-ups" with the issues
to file; #34's calibration unblocks the moment this PR merges (codex
is the ≥1 additional backend it needs).

## User Scenarios

1. **SWE-bench locally.** A maintainer runs
   `./scripts/benchmark run --benchmark swe-bench-verified --backend
   claude-code --model sonnet --task <id>`. The harness pulls the
   task's prebuilt image, mounts a worktree at the base commit, sends
   the issue text as the prompt, lets Claude Code edit in-container,
   runs the task's `FAIL_TO_PASS`+`PASS_TO_PASS` pytest sets in the
   container, and scores `tests_passed` against the gold expectation.
2. **codex backend.** `./scripts/benchmark run --benchmark
   aider-polyglot --backend codex --model gpt-5-codex --runs 1` drives
   `codex exec` headlessly; the run record's `backend_metadata`
   captures the resolved `~/.codex/config.toml` path + selected
   provider id (never secrets).
3. **List.** `./scripts/benchmark list` shows `swe-bench-verified`
   among adapters and `codex` among backends.
4. **CI unchanged.** The stub×stub smoke gate from #32 still runs in
   <90s and is not regressed; SWE-bench/docker are local-only.
5. **Stub parity.** `--backend stub --benchmark swe-bench-verified`
   copies the dataset's gold patch via `golden_patch` (local-only;
   not in CI — images are multi-GB).

## Interface

### Contract change (the one authorized amendment)

`scripts/benchmark_runner/contracts.py` — `IsolationConfig` gains:

```python
image: Optional[str] = None   # docker tier: prebuilt image ref to pull
                              # (e.g. "swebench/sweb.eval.x86_64.<inst>")
```

Additive, defaulted, back-compatible: every existing adapter/test that
constructs `IsolationConfig` is unaffected (`image` defaults to
`None`). The runner records `image` in `run-record.json`'s `isolation`
block alongside the other tier fields (same as `dockerfile`/
`build_args` today). No `BenchmarkAdapter` or `Backend` *method*
signature changes.

### `docker` isolation tier

`scripts/benchmark_runner/isolation.py` — replace the
`NotImplementedError` branch with a real provisioner:

- Require host `docker` (probe `docker version`); a missing daemon is
  an **environment** failure (clear message, distinct from a bug —
  infra-verification rule), never a silent skip.
- **Bind-mount, not copy.** `provision_worktree` runs *before*
  `prepare_task` and the backend (verified: `run.py:141-191`), so the
  worktree is empty at provision time. The docker tier creates the
  host worktree dir (like `_provision_plain`), then starts a
  long-lived container (`docker run -d`) with the **host worktree
  bind-mounted** (`-v <abs worktree>:/workspace -w /workspace
  <config.image>`). Host-side `prepare_task` + backend edits are then
  live in-container for `verify`. Returns the host worktree `Path`
  (unchanged `provision_worktree` signature).
- **Container lifecycle spans the whole attempt** (provision →
  prepare_task → backend → verify → teardown), owned by the isolation
  module via an internal `{worktree_path → container_id}` registry.
- **Verify routes through an isolation helper, not a contract change.**
  New harness API `isolation.run_in_worktree(worktree, argv, *,
  timeout, cwd=None) -> subprocess.CompletedProcess`: if `worktree`
  was provisioned under docker (registry hit) it execs
  `docker exec <cid> …`; otherwise it runs a local subprocess. The
  SWE-bench adapter's `verify` calls this helper. `verify(task,
  worktree)`'s **Protocol signature is unchanged** — the helper is
  internal harness infrastructure, not a `BenchmarkAdapter` method
  (Design Decision 7 holds). Existing adapters (Polyglot) keep their
  own direct subprocess and are unaffected.
- **Teardown** (`docker rm -f <cid>`) via a new
  `isolation.release_worktree(config, worktree)` called by `run.py`
  in a `finally` after verify+diff (a `run.py` change — there is no
  teardown hook today; `worktree`-tier `release` is a no-op so
  existing tiers are unaffected). Orphan-safe.
- No Docker-in-Docker, no image building, no network assumptions
  beyond the image pull; local-only; CI continues on `stub`.

### SWE-bench Verified adapter

`benchmarks/adapters/swe_bench_verified/` :

- `REVISION` — HF dataset revision (commit hash) of
  `princeton-nlp/SWE-bench_Verified`, the SWE-bench analogue of the
  Polyglot git SHA pin. **Fetch is stdlib-only via the HF
  datasets-server JSON rows API** (Design Decision 3): the dataset is
  published as **Parquet**, which stdlib cannot parse and the
  no-new-deps constraint forbids `pyarrow`/`datasets`. `fetch.py`
  (stdlib `urllib`+`json`) paginates
  `https://datasets-server.huggingface.co/rows?dataset=princeton-nlp/
  SWE-bench_Verified&config=default&split=test&offset=…&length=100`
  pinned with `&revision=<REVISION>`, normalizing rows into a
  committed-shape JSONL cache
  `benchmarks/.cache/swe-bench-verified/<rev>/tasks.jsonl`
  (content-addressed, mirrors the Polyglot fetch lifecycle:
  idempotent, fails loud with no partial cache). Documented update
  procedure: edit `REVISION`, run `python3 -m
  benchmarks.adapters.swe_bench_verified.fetch`. The adapter reads the
  JSONL with stdlib `json` only.
- `benchmark_id = "swe-bench-verified"`; `isolation_default =
  ISOLATION_DOCKER`.
- `list_tasks()` — one `TaskSpec` per dataset row; `task_id` =
  SWE-bench `instance_id`; metadata carries `image`, `base_commit`,
  `FAIL_TO_PASS`, `PASS_TO_PASS`, `test_cmd`, `repo`.
- `isolation_for(task)` → `IsolationConfig(tier=ISOLATION_DOCKER,
  image=task.metadata["image"], container_mount="/testbed")` — the
  worktree is bound **over the image's repo dir** (Design Decision 10).
- `prepare_task(task, worktree)` — materialize the repo at
  `base_commit` into the host worktree by `docker cp`-ing the image's
  `/testbed` out of a throwaway container (the image is built at
  `base_commit`; deps are editable-installed from `/testbed`). The
  worktree, bound back at `/testbed`, then carries backend edits into
  the location the editable install + tests resolve (Design Decision
  10 — corrects the original metadata-only stub).
- `prompt_for(task, 1, None)` — the issue text + repo/problem framing;
  single-shot.
- `verify(task, worktree)` — runs `FAIL_TO_PASS`+`PASS_TO_PASS` **via
  `isolation.run_in_worktree(worktree, …)`** (which execs in the
  task's container); `tests_passed` iff all `FAIL_TO_PASS` pass and no
  `PASS_TO_PASS` regress. `VerifyResult.tests_output` captures the
  in-container run. Signature unchanged (helper is internal API).
- `golden_patch(task)` — write the dataset's reference `patch` to a
  golden dir (stub-backend parity; local-only).
- `max_attempts() == 1`.

### `codex` backend

`scripts/benchmark_runner/backends/codex.py` :

- `BACKEND_FAMILY = "codex"`; `factory(model) -> CodexBackend`.
- `run(prompt, ctx)` — **verified argv for the pinned
  `codex-cli 0.130.0`** (captured live 2026-05-18; the verification
  record holds the recorded transcript and is the authority):
  `codex exec --json --sandbox workspace-write --skip-git-repo-check
  [--model <ctx.model> if non-empty] -` with the **prompt on stdin**
  (trailing `-`), `cwd=ctx.worktree`, host env forwarded unchanged.
  Rationale (Design Decision 9): (a) `--model`/`-m` passed only when
  `ctx.model` non-empty, else the run silently uses the `~/.codex/
  config.toml` default; (b) SWE-bench-sized prompts → stdin via `-`,
  not argv; (c) `codex exec` is **inherently non-interactive** —
  there is **no `--ask-for-approval` flag** on `exec` in 0.130.0 (an
  earlier draft assumed one; the verification probe disproved it —
  this is exactly the drift the gate exists to catch); `--sandbox
  workspace-write` gives a sandbox that can still edit the worktree;
  `--skip-git-repo-check` because attempt worktrees are not git repos.
  Transcript is **JSONL events**: `thread.started` →
  `item.completed`(`item.type=agent_message`) →
  `turn.completed`(`usage.{input_tokens,cached_input_tokens,
  output_tokens,reasoning_output_tokens}`). The defensive parser maps
  these codex keys (the `claude_code.py` pattern, codex-specific key
  set; null-vs-zero preserved). If a future pinned version's surface
  differs, the verification record is refreshed and the backend
  matches it (no silent drift).
- `backend_metadata` records: family, model, resolved
  `~/.codex/config.toml` path, selected `model_providers.<id>`,
  `codex --version`, exit code, stderr tail — **never** API keys.
- Recorded-transcript test: fake `codex` shim on PATH echoing a
  committed fixture + logging argv/stdin/cwd; fixtures under
  `scripts/benchmark_runner/tests/fixtures/codex/`. No live CLI/network.

### Registration / CLI / docs

`_register.py` gains the two `register_*` calls (explicit, grep-able —
no auto-discovery). `benchmarks/README.md`: add `codex` to the backend
table with its provider-routing env story (`~/.codex/config.toml`
`[model_providers.<id>]`, recorded path+id), and a SWE-bench adapter +
`docker` tier section (local-only, image-size caveat). Per-adapter
calibration note (SWE-bench leaderboard is per-agent — comparison
meaningful only same-agent-both-sides) in the merge commit body or
`specs/benchmark-harness/dogfood/`.

## Reuse map

| Existing artifact | Use |
|---|---|
| `contracts.py::IsolationConfig` | extended additively with `image` (the single authorized contract change). `BenchmarkAdapter`/`Backend` method signatures untouched. |
| `isolation.py` worktree/venv provisioners | the structural template for the new `docker` provisioner; the `NotImplementedError` branch is replaced. |
| `benchmarks/adapters/aider_polyglot/fetch.py` + `REVISION` pattern | mirrored for SWE-bench's HF-dataset pin + content-addressed cache + documented update procedure. |
| `backends/claude_code.py` (argv build, defensive transcript parse, `backend_metadata` provider recording, start_new_session/timeout) | the template `codex.py` follows. |
| `tests/test_claude_code_backend.py` fake-CLI shim + fixtures | the exact pattern for `test_codex_backend.py`. |
| `registry.py` / `_register.py` | additive registration; no discovery change. |
| `specs/benchmark-harness/` spec/plan/tasks + audit-2026-05-08 | the parent spec; this bundle is its #33 extension and obeys the backends≠providers correction. |
| `shared/skills/infra-verification/SKILL.md` | governs the docker-tier verification (must be executed, not syntax-checked; env-vs-artifact distinction). |

## Design Decisions

**1 — Single PR; two authorized deviations from #33's text.** #33
mandates (a) the contract change as a separate amendment PR and (b)
each backend's verification record as a separate PR landing before the
backend code. The user (2026-05-18) explicitly chose **one PR, no
precursor**, which also satisfies the repo governance rule (a merged
PR must fully close its issue — partial/sequenced PRs against one issue
are disallowed). Therefore: `IsolationConfig.image` is added **in this
PR** (not a separate amendment), and codex's verification record
(`specs/benchmark-harness/verification/codex.md`) is **in this PR**
alongside the backend (not a prior separate PR). These are recorded,
user-authorized deviations — not misses. The verification *content*
discipline is unchanged (pinned version + recorded transcript +
reviewer-checkable contract); only its PR *packaging* differs.

**2 — Codex is the Track-B backend (not aider/github-copilot).**
#33's own ordering rationale: codex has the most fully documented,
already-verified headless surface (`codex exec --json`, `~/.codex/
config.toml` provider blocks). It satisfies the Track-B bar and
unblocks #34's calibration with the least verification risk. `aider`
(and its apples-to-apples Polyglot comparison) and `github-copilot`
are deferred to named follow-up issues rather than partially attempted.

**3 — SWE-bench pin via HF datasets-server JSON rows API (stdlib-only;
NOT Parquet).** SWE-bench Verified is published as **Parquet** on HF,
which the standard library cannot parse and the no-new-deps constraint
forbids resolving with `pyarrow`/`datasets`. So `REVISION` holds the HF
dataset revision (commit hash) and `fetch.py` (stdlib `urllib`+`json`)
paginates the **HF datasets-server rows API**
(`datasets-server.huggingface.co/rows?...&revision=<REVISION>`),
normalizing rows into a committed-shape JSONL cache
(`benchmarks/.cache/swe-bench-verified/<rev>/tasks.jsonl`,
content-addressed, idempotent, loud-fail no-partial — the Polyglot
fetch lifecycle). The adapter reads JSONL with stdlib `json`. Same
pin/update convention as Polyglot, dataset-appropriate transport, zero
new dependencies.

**4 — docker tier: bind-mount + attempt-spanning container + an
isolation helper (no contract-method change).** `provision_worktree`
runs before `prepare_task`/backend (verified `run.py:141-191`), so the
worktree is empty at provision. The docker tier creates the host
worktree dir then a long-lived `docker run -d` container with the
worktree **bind-mounted** (`-v <abs>:/workspace -w /workspace
<config.image>`), keyed in an internal `{worktree→container}`
registry; the container spans provision→verify; teardown is a new
`isolation.release_worktree(config, worktree)` that `run.py` calls in a
`finally` (no-op for non-docker tiers — a small `run.py` change, since
there is no teardown hook today). `verify` runs the test sets through a
new internal helper `isolation.run_in_worktree(worktree, argv, …)`
that execs `docker exec <cid> …` for docker-provisioned worktrees and a
local subprocess otherwise — so the `BenchmarkAdapter.verify(task,
worktree)` Protocol signature is **unchanged** (Design Decision 7
holds; the helper is harness infrastructure, not a Protocol method).
No DinD, no image build, no CI docker (multi-GB; local-only). Missing
daemon → environment prerequisite error, never a silent pass
(infra-verification).

**5 — `IsolationConfig.image` is additive and back-compatible.**
`Optional[str] = None`; only the docker tier reads it; recorded in the
run-record `isolation` block exactly like `dockerfile`/`build_args`.
Every existing `IsolationConfig(...)` call site is unaffected — verified
by the unchanged #32 test suite staying green.

**6 — Verification record lives in `specs/`, not `doc_internal/`.**
#33 says `doc_internal/copilot-verification-codex.md`, but
`doc_internal/` is **gitignored** in this repo (`.gitignore: /doc_internal`)
— a review-gate artifact there would be invisible to reviewers and CI.
Repo convention is "`specs/` is always committed; `doc_internal/` is
local." So the codex verification record is
`specs/benchmark-harness/verification/codex.md` (tracked). Recorded
deviation with rationale; the artifact's *content* matches #33's spec
exactly.

**7 — No changes to `BenchmarkAdapter`/`Backend` method contracts.**
The only contract surface touched is the additive `IsolationConfig.image`
field (Design Decision 1/5). If SWE-bench/codex reveal a genuine method
contract gap, that is a #32 design regression and is split out — it is
**not** silently folded in.

**8 — Stub parity local-only; CI stays stub×stub.** SWE-bench
`golden_patch` returns the dataset reference patch so `stub × swe-bench`
works for parity, but the multi-GB images keep it out of CI; the #32
CI smoke (stub adapter × stub backend) is unchanged and must stay
green (regression gate).

**9 — codex argv: verified against `codex-cli 0.130.0` (gate caught a
drift).** Verified live 2026-05-18. The backend invokes
`codex exec --json --sandbox workspace-write --skip-git-repo-check
[--model <ctx.model>] -` with the prompt on **stdin**: (a) `--model`
is passed only when `ctx.model` is non-empty — otherwise the run
silently uses the `~/.codex/config.toml` default and the promised
`--model gpt-5-codex` scenario is unmet; (b) SWE-bench-sized prompts
exceed sane argv limits — stdin via the trailing `-` (0.130.0 help:
"if `-` is used, instructions are read from stdin"); (c) `codex exec`
is **inherently non-interactive** — **there is no `--ask-for-approval`
flag** (an earlier draft, following a reviewer suggestion, assumed
`--ask-for-approval never`; the verification probe returned `exit=2
usage error` and `codex exec --help` confirmed no such flag — the
per-backend verification gate did exactly its job). `--sandbox
workspace-write` permits worktree edits while sandboxed;
`--skip-git-repo-check` because attempt worktrees aren't git repos.
The **verification record** (`specs/benchmark-harness/verification/
codex.md`) pins `codex-cli 0.130.0` and holds the real recorded
transcript; if a future pinned version's surface differs the record is
refreshed and the backend matches it (no silent drift). This drift,
caught in planning, is the concrete justification for #33's
verification-before-code gate.

**10 — SWE-bench×docker model corrected by real execution (3 real
bugs the faked unit tests missed).** Mandated real `docker` execution
(infra-verification) during the build uncovered defects invisible to
docker-faked unit tests; all are fixed in-PR:
(a) `run_in_worktree` built `docker exec <cid> -w <cwd> …` — `-w` is a
`docker exec` *option* and must precede the container id, else
`OCI exec: "-w" not found`. Fixed: options before `<cid>`.
(b) the docker-branch default cwd was the *host* worktree path, but
inside the container the worktree is bind-mounted elsewhere — `docker
exec -w <host-tmp-path>` fails `chdir … no such file or directory`.
Fixed: docker-branch default cwd is the container mount; `_CONTAINER_MOUNT`
extracted as a single source of truth (no magic string in two places).
(c) **Architectural:** SWE-bench prebuilt images hold the repo at
`/testbed` (deps editable-installed from there), but the tier
hard-bind-mounted the host worktree at `/workspace` while
`prepare_task` only wrote a metadata file and `verify` ran the image's
untouched `/testbed` — so a backend's fix could never reach the scored
location. **Correction:** add a *second* additive contract field
`IsolationConfig.container_mount: Optional[str] = None` (default
`/workspace`; SWE-bench sets `/testbed`) so an adapter can bind the
host worktree **over the image's repo path**; the docker tier uses it
for `-v`/`-w` and as `run_in_worktree`'s docker default cwd (registry
records the per-worktree mount). SWE-bench `prepare_task` materializes
the repo by `docker cp`-ing the image's `/testbed` into the host
worktree (throwaway container), so backend edits on the host are live
at `/testbed` where the editable install resolves; `verify` runs the
test sets at `/testbed` where the edits now are. This is the same
"in-PR additive contract field, user-authorized" latitude as Design
Decision 1 (the user chose single-PR, no precursor). The model is
proven by a real multi-GB SWE-bench image run (Requirement 11), not
just faked tests — exactly the infra-verification discipline.

## Requirements

1. `IsolationConfig.image: Optional[str] = None` **and**
   `IsolationConfig.container_mount: Optional[str] = None` added (two
   additive, defaulted, back-compatible fields — Design Decisions 1 &
   10); all existing #32 tests pass unchanged (back-compat proven). No
   `BenchmarkAdapter`/`Backend` method-signature change.
2. `docker` tier implemented and **executed** (real `docker` run,
   per infra-verification): bind-mounts the host worktree,
   attempt-spanning container, `isolation.run_in_worktree` helper for
   in-container verify, `isolation.release_worktree` teardown called
   from `run.py` in a `finally` (no-op for non-docker tiers); missing
   daemon → explicit environment error, not skip.
3. SWE-bench Verified adapter implements the unchanged #32
   `BenchmarkAdapter`; `REVISION` pin + stdlib-only `fetch.py` via the
   HF datasets-server rows API → JSONL cache (no Parquet/pyarrow/
   datasets dep) + documented update procedure; `verify` runs through
   `isolation.run_in_worktree`; `max_attempts()==1`; `golden_patch`
   returns the dataset patch.
4. `codex` backend implements the unchanged #32 `Backend`; argv =
   `codex exec --json --sandbox workspace-write --skip-git-repo-check
   [--model <ctx.model> when non-empty] -` (prompt on **stdin**),
   matching the `codex-cli 0.130.0` verification record; provider env
   recorded (never set); recorded-transcript test, no live CLI/network.
5. `specs/benchmark-harness/verification/codex.md` present: pinned
   `codex --version`, recorded headless transcript, documented
   flag/env contract, reviewer-checkable.
6. `./scripts/benchmark list` shows `swe-bench-verified` AND `codex`.
7. Per-adapter calibration note (SWE-bench per-agent caveat) in merge
   commit body or `specs/benchmark-harness/dogfood/`.
8. CI stub×stub smoke from #32 not regressed.
9. Stdlib + `git`/`docker` subprocess + `urllib` (HF rows API) only —
   **no Parquet/`pyarrow`/`datasets` dependency**; Bash 3.2 for shell;
   `validate-spec.sh --feature-id benchmark-adapters-backends` exits 0.
10. One PR fully closes #33; deferred tracks filed as named follow-up
    issues (§ Named follow-ups).
11. **Real SWE-bench×docker end-to-end proof (infra-verification):** a
    real multi-GB SWE-bench image is pulled and one instance runs
    end-to-end locally — at minimum `--backend stub` (deterministic:
    stub applies `golden_patch` into the host worktree → bind-mounted
    at `/testbed` → `verify` runs `FAIL_TO_PASS`/`PASS_TO_PASS` in the
    container → `tests_passed=True`), proving the corrected mount model
    (Design Decision 10) actually works; and an attempted
    `--backend claude-code --model sonnet` run on ≥1 instance. The
    captured output is recorded in the PR. A genuine environment limit
    (disk/time/registry) is reported as such, never faked.

## Constraints / What NOT to Build

1. No `aider`/`github-copilot` backends here (deferred follow-ups).
2. No BigCodeBench/LiveCodeBench/cct-dogfood adapters here (optional;
   follow-ups).
3. No LLM-judge/charts/HTML (#34); no provider-config feature.
4. No `BenchmarkAdapter`/`Backend` method-signature change; only the
   additive `IsolationConfig.image`.
5. No Docker-in-Docker; no docker in CI; no image building; no
   provision-time worktree copy (bind-mount only).
5b. No Parquet/`pyarrow`/`datasets` dependency; SWE-bench data is
   fetched stdlib-only via the HF datasets-server rows API.
6. The harness records provider env vars; it never sets them.
7. No secrets in run records / verification record / metadata
   (presence booleans + config path + provider id only).
8. No regression to the #32 stub×stub CI smoke or existing tests.

## Key Entities

- **`IsolationConfig.image`** — optional prebuilt-image ref; docker
  tier only; recorded in the run-record isolation block.
- **docker isolation tier** — pull image → container → run worktree +
  verify in-container → teardown; local-only.
- **SWE-bench Verified adapter** — `swe-bench-verified`; HF-dataset
  pinned; docker tier; single-shot; gold patch for stub parity.
- **codex backend** — `codex exec --json`; provider via `~/.codex/
  config.toml`; recorded transcript test.
- **Verification record** — `specs/benchmark-harness/verification/
  codex.md`; pinned version + transcript + contract.

## Acceptance Criteria

Quoted verbatim from issue #33, mapped to tasks in `tasks.md`. Items
#33 marks optional and that this PR defers are shown as **deferred
(named follow-up)** with rationale in § Named follow-ups.

| #33 criterion (verbatim) | Disposition | Tasks |
|---|---|---|
| "SWE-bench Verified adapter runs end-to-end against `claude-code --model sonnet` for ≥1 task locally." | met | T3.x, T6.1 |
| "SWE-bench Verified `tier: docker` integration is exercised (the first real use of Docker isolation in CCT)." | met | T2.x, T6.1 |
| "At least one of {BigCodeBench, LiveCodeBench, CCT-dogfood} … OR at least one of {aider, codex} backends … (≥1 from EACH track)." | met (SWE-bench + codex) | T3.x, T4.x |
| "Per-backend verification gate: any Track B backend has a corresponding verification PR … BEFORE the backend code." | met as **verification record in-PR** (Design Decision 1; user-authorized deviation from the separate-PR packaging) | T4.1 |
| "Each shipped adapter has a `REVISION` … and a documented update procedure." | met | T3.2 |
| "Each shipped backend has documented provider-routing env vars and a recorded-transcript test (no live CLI/network)." | met | T4.2, T4.3 |
| "`./scripts/benchmark list` shows all shipped adapters AND backends." | met | T5.1 |
| "No changes to the `BenchmarkAdapter` or `Backend` contracts … separate PR amending #32's deliverable." | met for methods; `IsolationConfig.image` added **in-PR** (Design Decision 1; user-authorized deviation) | T1.1 |
| "Per-adapter calibration note in the merge commit body (or `specs/benchmark-harness/dogfood/`)." | met | T5.3 |
| "If aider backend ships: apples-to-apples Aider Polyglot leaderboard comparison documented." | n/a — aider deferred (named follow-up) | — |
| "CI smoke continues to pass — stub adapter from #32 is not regressed." | met | T6.2 |

Spec approved when `validate-spec.sh --feature-id
benchmark-adapters-backends` exits 0 and every non-deferred AC maps to
a task. Delivered when, in one PR (`Closes #33`): all existing + new
tests pass; docker tier executed for real on ≥1 SWE-bench task locally;
`benchmark list` shows both; CI stub×stub green; the deferred follow-up
issues are filed and referenced.

## Named follow-ups (filed with this PR; not partially built)

- **aider backend** + verification record + apples-to-apples
  Aider-Polyglot leaderboard comparison — its own issue, its own
  complete PR.
- **github-copilot backend** + verification record — its own issue
  (#33 itself permits dropping it if the April-2026 BYOK surface
  doesn't verify).
- **Optional adapters** (BigCodeBench / LiveCodeBench / cct-dogfood) —
  its own issue(s); all optional in #33.

#34's calibration dependency is satisfied by this PR (codex is the ≥1
additional backend); #34 may proceed once this merges.

## Open questions for the user

None outstanding. The two structural decisions (single-PR shape;
contract-change + verification-record packaging) were resolved by the
user on 2026-05-18 and are recorded as authorized deviations (Design
Decisions 1 & 6). The deferred-tracks scoping is a governance
consequence of the single-PR + one-PR-per-issue rules, not an open
policy question.

## Sources

- `issue: gosha70/code-copilot-team#33` — origin.
- `issue: gosha70/code-copilot-team#32` (CLOSED, PR #35) — the harness
  this extends; contracts + isolation + adapter/backend patterns.
- `issue: gosha70/code-copilot-team#34` — the calibration consumer
  unblocked by this PR's codex backend.
- `path: scripts/benchmark_runner/contracts.py` — `BenchmarkAdapter`,
  `Backend`, `IsolationConfig`, `IsolationTier` (the `image` add site).
- `path: scripts/benchmark_runner/isolation.py` — the docker-tier
  `NotImplementedError` to replace; worktree/venv templates.
- `path: benchmarks/adapters/aider_polyglot/{adapter.py,fetch.py,REVISION}`
  — adapter + dataset-pin template.
- `path: scripts/benchmark_runner/backends/claude_code.py` — backend
  template (argv, transcript parse, metadata, timeout).
- `path: scripts/benchmark_runner/tests/test_claude_code_backend.py`
  — fake-CLI recorded-transcript test pattern.
- `path: scripts/benchmark_runner/_register.py`,
  `path: scripts/benchmark_runner/registry.py` — registration.
- `path: specs/benchmark-harness/{spec.md,plan.md,tasks.md,audit-2026-05-08.md}`
  — parent spec + backends≠providers correction.
- `path: shared/skills/infra-verification/SKILL.md` — docker-tier
  execution discipline.
- `path: .gitignore` — `/doc_internal` (why the verification record is
  in `specs/`, Design Decision 6).
- `url: https://www.swebench.com/verified.html` — SWE-bench Verified
  dataset + per-agent leaderboard caveat.
- `url: https://developers.openai.com/codex/config-advanced`,
  `url: https://developers.openai.com/codex/cli/reference` — codex
  `exec --json` + `[model_providers.<id>]` contract.
