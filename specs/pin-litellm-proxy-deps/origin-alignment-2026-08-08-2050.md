# Origin Alignment Check — pin-litellm-proxy-deps

Date: 2026-08-08 20:50
Trigger: plan.md revised after the user's P2 on PR #221; the previous record
(`origin-alignment-2026-08-08-2010.md`) is stale — and its criteria table
was wrong, which is the point of this record.

## Origin sources read

- Issue: https://github.com/gosha70/code-copilot-team/issues/220.
- The user's P2 on PR #221: "The acceptance test does not prove proxy
  startup. … only imports `litellm.proxy.proxy_server`, then labels that
  'proxy can start.' It never launches the CLI, exercises
  `benchmark_runner.proxy`, waits for `/v1/models`, or verifies process
  cleanup. Yet the alignment record marks both clean-environment startup and
  the startup regression as met."

## What was wrong in the previous record

It marked "A clean ephemeral environment can start the LiteLLM proxy
successfully" and "A regression test validates proxy startup from a clean
environment" as **met** on the strength of an import. An import-compatible
dependency set can still fail during application initialisation, so those
two ticks were not earned. The finding is accepted in full.

## Working claim

`--online` now starts the PRODUCTION helper — the same
`benchmark_runner.proxy` the benchmark uses — on an ephemeral port, and
asserts: a pid is reported, the process survives startup, `/v1/models`
answers with the configured model, and SIGTERM reaps it with no leaked
listener. Verified passing (22/22 online). No upstream vLLM is required
because LiteLLM serves `/v1/models` from its own config, which is what makes
the criterion testable here at all.

## Acceptance criteria — corrected status

- Deterministic versions/constraints — met.
- Clean ephemeral environment starts the proxy — **now genuinely met**
  (production helper started, healthy, terminated).
- `pip check` clean — met, asserted online and enforced in the benchmark.
- Regression validates proxy startup from a clean environment — **now
  genuinely met**.
- Diagnostics report litellm/fastapi/python — met.
- Temp environments removed automatically — met.
- End-to-end Anthropic→vLLM preflight — **NOT verified**; needs a reachable
  vLLM server.
- `python/bowling` reaches the model — **NOT verified**; same reason.

## Mismatches

- The two unverified criteria stay unverified and are stated as such here,
  in the plan, and in the PR body. Proxy startup is no longer among them.

## Verdict

Verdict: aligned
Confidence: high
