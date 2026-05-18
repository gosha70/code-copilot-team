# Benchmark Adapters & Backends (#33) — Implementation Status

Snapshot 2026-05-18. Single PR (`Closes #33`), branch
`feat/benchmark-adapters-backends`. Real execution (infra-verification)
drove the design — several defects were invisible to docker-faked unit
tests and only surfaced under real `docker`/CLI runs.

## Delivered

| Capability | Status | Where / evidence |
|---|---|---|
| `IsolationConfig.image` + `.container_mount` (2 additive, back-compat fields) | ✓ delivered | `contracts.py`; back-compat **proven** vs pristine `origin/master` |
| `docker` isolation tier (real) | ✓ delivered | `isolation.py` — bind-mount, attempt-spanning container, `run_in_worktree`, `release_worktree`; `run.py` `finally` teardown + record. **3 real bugs found & fixed by real `docker` run**: `docker exec -w` arg order; host-vs-container cwd; hardcoded `/workspace` → adapter-configurable. Real `alpine` roundtrip PASS |
| SWE-bench Verified adapter | ✓ delivered | `benchmarks/adapters/swe_bench_verified/` — stdlib HF rows-API `fetch.py` (500-task pinned JSONL incl. `test_patch`); runtime image derivation `sweb.eval.<arch>.<id _1776_>:latest`; `prepare_task` `docker cp`s image `/testbed`; `verify` applies `test_patch` + (stub) gold diff, runs in `testbed` conda env; `max_attempts==1` |
| **Real SWE-bench end-to-end** | ✓ **proven** | `stub × psf__requests-1142` → `tests_passed=True` (6 passed); **`claude-code --model sonnet × psf__requests-1142` → `tests_passed=True`** (real agentic solve), tier=docker, arm64 image, mount=/testbed |
| `codex` backend | ✓ delivered | `backends/codex.py` — verified argv `codex exec --json --sandbox workspace-write --skip-git-repo-check [--model] -` (stdin); `test_codex_backend` 27 OK; metadata records provider/path, never secrets |
| codex verification record | ✓ delivered | `specs/benchmark-harness/verification/codex.md` — pinned **codex-cli 0.130.0**, real transcript; **gate caught the `--ask-for-approval` drift** (assumed flag doesn't exist on `exec`) |
| Registration + `benchmark list` | ✓ delivered | `_register.py`; `list` shows `swe-bench-verified` + `codex` |
| README + provider/docker docs | ✓ delivered | `benchmarks/README.md` |
| Spec bundle | ✓ delivered | `specs/benchmark-adapters-backends/{spec,plan,tasks}.md`; `validate-spec` 2 passed |

## User-authorized deviations (recorded, not oversights)

- Single PR, no precursor (user 2026-05-18): both additive contract
  fields **and** the codex verification record ship in-PR — Design
  Decisions 1, 6, 10.
- Real-docker verification ran with Docker.app's bin one-off on `PATH`
  (user-authorized, verification-only — never baked into harness code).

## Not regressions (pre-existing, environment-induced — proven on pristine `origin/master`)

- `test_polyglot_adapter` ×4 fail: this host resolves
  `python2.7`/no-pytest for polyglot verify. Identical on pristine
  master (no #33 changes).
- `test_cli_skeleton` hangs: pre-existing in this sandbox; identical on
  pristine master. (Was the original "stuck" suite.)

#33 introduces **zero** regressions; all #33-relevant suites green.

## Deferred → named follow-up issues (not partially built)

- `aider` backend + verification + apples-to-apples Aider-Polyglot
  comparison.
- `github-copilot` backend + verification.
- Optional adapters: BigCodeBench / LiveCodeBench / cct-dogfood.

#34's calibration dependency is satisfied (codex is the ≥1 additional
backend); #34 may proceed once this merges.
