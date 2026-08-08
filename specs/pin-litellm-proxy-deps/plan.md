---
spec_mode: none
feature_id: pin-litellm-proxy-deps
risk_category: bugfix
justification: |
  Non-security bug fix (#220): pin the benchmark's LiteLLM proxy
  dependencies, fail fast on a conflicting resolution, and report resolved
  versions on failure. Dependency + diagnostics change; no new surface.
status: approved
date: 2026-08-08
origin:
  issue: https://github.com/gosha70/code-copilot-team/issues/220
  origin_claim: |
    Bug #220: "fix(benchmark): pin compatible LiteLLM proxy dependencies".
    The Anthropic-vs-vLLM benchmark installs an unconstrained
    `litellm[proxy]>=1.50` into a fresh venv on every run, which can resolve
    an incompatible LiteLLM/FastAPI combination. The proxy then crashes at
    startup with "ImportError: cannot import name 'get_flat_dependant' from
    'fastapi.dependencies.utils'" (and a secondary "No module named
    'proxy_server'"), so the benchmark never reaches the smoke test or the
    model. Because versions are not pinned, a previously working benchmark
    can fail with no CCT source change. Proposed: pin a verified compatible
    set, preferably in a dedicated requirements/constraints file, and report
    the resolved LiteLLM and FastAPI versions when the proxy fails.
---

# Plan: pin the proxy dependencies (#220)

## Root cause, confirmed by execution

litellm 1.95.0's `proxy` extra declares `fastapi<1.0,>=0.136.3`, so pip
resolves whatever fastapi is newest. Verified in clean venvs on 2026-08-08,
python 3.13:

| fastapi | `get_flat_dependant` | `from litellm.proxy import proxy_server` |
|---|---|---|
| 0.141.1 (latest) | **missing** | **ImportError** — the reported crash, reproduced verbatim |
| 0.139.2 | present | imports fine |

So the range in litellm's own metadata is what breaks it: nothing in CCT
changed, and the benchmark self-broke the moment fastapi 0.141.1 shipped.

## Changes

1. **`scripts/requirements-litellm-proxy.txt`** — the dedicated pins file the
   issue prefers, carrying `litellm[proxy]==1.95.0` and `fastapi==0.139.2`,
   with the reason, the verification date/method, and the upgrade procedure
   written next to the numbers.
2. **The benchmark installs from that file** instead of the loose spec.
3. **`pip check` runs immediately after provisioning.** A conflicting
   resolution now fails where the message names packages, not three steps
   later as an ImportError inside the proxy.
4. **`proxy_dep_versions()`** prints python, litellm, fastapi and the pins
   path on every proxy failure path. The original report showed an
   ImportError with no way to tell which versions were in play.
5. **`tests/test-litellm-proxy-deps.sh`** — offline contract checks (13) in
   CI; `--online` (9 more) provisions a real clean venv and, crucially,
   **starts the production proxy helper**: `benchmark_runner.proxy start` on
   an ephemeral port, process alive, `/v1/models` answering with the
   configured model, then SIGTERM with no leaked listener. No upstream vLLM
   is needed — LiteLLM serves `/v1/models` from its own config.

   Review round 4 (P2) fixed the trap SHAPE: `trap cleanup EXIT INT TERM`
   runs cleanup and *returns 0*, so bash resumes the script after the signal
   — potentially continuing with a deleted venv, or re-creating what it just
   removed, and never producing the claimed 130/143. Cleanup now stays on
   `EXIT` while `INT`/`TERM` handlers `exit` with the conventional status.
   My round-3 "verified by interrupting" used an explicit `exit 130`, which
   only exercised the EXIT trap — the signal path was never tested.

   Review round 3 (P2) made that startup test fail-safe: an OS-assigned free
   port instead of a guess inside a fixed 8800-9199 window (a "random" port
   from a fixed range still collides, and a collision reads as a proxy
   failure); an `EXIT/INT/TERM` trap registered before anything is created;
   the generated `log=` removed alongside `config=`; SIGTERM escalated to
   SIGKILL; and the PORT probed for a live listener rather than treating the
   parent PID's disappearance as proof. Verified by interrupting a run
   mid-flight (`exit 130`): process reaped, config and log removed, port
   free.

   Review round 2 (P2) corrected this: the first cut asserted only that
   `litellm.proxy.proxy_server` **imports**, and labelled that "proxy can
   start" — an import-compatible dependency set can still die during
   application initialisation, so the label was doing work the test had not
   earned. Same class as the stub lesson in #212: assert the thing that
   decides, not a proxy for it.

## Still not verified here

The end-to-end Anthropic→vLLM translation preflight and the `python/bowling`
smoke run need a reachable vLLM server (the report used
`192.168.1.23:8000`). Proxy startup IS now verified against the production
helper; what remains unverified is traffic actually reaching a model, and
the "OK End-to-end translation confirmed" line. That needs a run on the
reporter's host.

## Not done

`./scripts/bench` possibly bypassing LiteLLM after an insufficient
`/v1/messages` probe — the issue explicitly asks for that to be tracked
separately, and it is a routing question, not a dependency one.

## Note on the pin

`fastapi==0.139.2` is below the latest (0.141.1) by necessity, not
conservatism: the newest release is the one that removed the symbol. The
pins file says how to move both together when litellm stops importing it.
