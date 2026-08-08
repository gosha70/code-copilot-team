# Origin Alignment Check — pin-litellm-proxy-deps

Date: 2026-08-08 20:10
Trigger: first alignment record for this feature (gate exit 4).

## Origin sources read

- Issue: https://github.com/gosha70/code-copilot-team/issues/220 (root
  cause, reproduction command, proposed diff, eight acceptance criteria,
  and the upstream LiteLLM report).
- The user's instruction: "Then fix this bug: …/issues/220".

## Origin claim (verbatim)

> The benchmark resolves proxy dependencies dynamically on every run. The
> observed environment installed a LiteLLM version that imports FastAPI's
> internal `get_flat_dependant` symbol, while the resolved FastAPI version no
> longer exposes that symbol at the expected location. Because the dependency
> versions are not pinned, a previously working benchmark can fail without
> any CCT source change.

## Acceptance criteria — status

- Deterministic versions/constraints — **met** (`scripts/requirements-litellm-proxy.txt`).
- A clean ephemeral environment starts the proxy — **met**; `--online`
  installs into a fresh venv and imports `litellm.proxy.proxy_server`.
- `pip check` reports no conflicts — **met**, asserted online AND enforced in
  the benchmark itself after provisioning.
- End-to-end Anthropic→vLLM preflight passes / `python/bowling` reaches the
  model — **NOT verified here**; see mismatches.
- Regression test validates proxy startup from a clean environment — **met**.
- Diagnostics report litellm, fastapi and python versions — **met**.
- Temporary environments still removed automatically — **met**, asserted.

## Mismatches

- **Two acceptance criteria are not verified, and I will not claim them.**
  The end-to-end preflight and the `python/bowling` smoke run need a reachable
  vLLM server (`VLLM_BASE=http://192.168.1.23:8000` in the report). I have no
  such server, so I verified everything up to and including
  `from litellm.proxy import proxy_server` in a clean venv — the exact import
  that was failing — but the "Expected Successful Output" lines
  ("OK LiteLLM proxy up", "OK End-to-end translation confirmed") remain
  unverified by me. They need a run on the reporter's host.
- The `./scripts/bench` routing question is deliberately out of scope; the
  issue itself asks for it to be tracked separately.

## Verdict

Verdict: aligned
Confidence: high
