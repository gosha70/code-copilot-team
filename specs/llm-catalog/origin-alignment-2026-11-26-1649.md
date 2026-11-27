# Origin alignment check — llm-catalog (S3, built)

Date: 2026-11-26 16:49 EST

Supersedes the 2026-11-26 13:46 record, written at S3's start. Since then
S3 was built (issue #546), and an independent review's findings were
fixed and re-reviewed.

Origin sources: the 13:46 record's.

## What S3 delivers against its origin

| Origin | Delivered in |
|---|---|
| The probe runner (FR-15), over canary primitives extracted from `routing-probe.sh`, with routing's pins unchanged (D6) | `scripts/lib/llm-probe.sh`, over `scripts/lib/cct-canary.sh`. Routing's prompt, nonce and scrub are byte for byte as before, and a test pins the prompt. Routing's suites and pins, and the benchmark test that runs the real `rb_probe`, pass unchanged |
| The watchdog | `ca_run_bounded`, the routing probe's runner, with `CCT_LLM_PROBE_TIMEOUT_SEC` (default 120) and `KILL` ten seconds after `TERM`, through an argument the runner gained; routing keeps its two. A signal to `cct llm test` reaps the harness's process group and removes what the run made |
| The stub gateway, with one negative-control switch per capability | `tests/fixtures/llm-stub-gateway.py`. Each capability fails under its switch, with the state FR-13 assigns, through the mock harness in CI, and through the real `claude` 2.1.332 in `verification/claude-code-probe-capture.md` |
| `cct llm test` | `scripts/llm-cli.sh`, with its `--json` form in the schema; `unsupported` and `unavailable` targets are refused as a launch refuses them |
| Claude Code launches refuse `unverified` and `incompatible` targets, with `--allow-unverified` (D7), under the milder rule; departure 1 retired | `llm_gate` in the launcher, in the launcher that opens a pane and again in the pane; the newer-harness notice; the stamp records the gate. Departure 1 is marked retired in `spec.md` |
| A restored target goes through the gate (FR-19) | The gate runs at the end of `llm_prepare`, which a resume passes through; `cct llm sessions` reads it |
| The real binary through the stub gateway with every switch, and once against a configured target, quoted in the PR | The first is `verification/capture-claude-probe.sh` and its record. The second sends a real request with the owner's credential and is put to the owner in the PR |

## Mismatches

- **The run against a configured target is not done yet.** It waits on the
  owner's word, since it spends the owner's credential. The PR says so.
- **Two choices where FR-15 says more or is silent,** stated in issue #546
  and in FR-15's S3 notes:
  - the stub gateway speaks Anthropic Messages only, with the OpenAI
    protocols left to S6 and S7;
  - a refused credential is an attempt outcome of its own, `unavailable`.
- **Unchanged, and accepted by the owner on 2026-11-25:** the native notice
  for `--continue` and the picker prints only where stamps exist (FR-18).

Verdict: aligned
Confidence: high
