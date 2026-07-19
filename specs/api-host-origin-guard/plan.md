---
spec_mode: full
feature_id: api-host-origin-guard
risk_category: security
justification: |
  Adds request-admission control in front of EVERY API route, so a mistake
  breaks the whole Studio rather than one feature — hence full spec_mode
  with checkpoints despite the small diff. Closes the DNS-rebinding path
  that CORS cannot (#103). No new deps, no endpoint behaviour change, no
  Studio change; the main risk is over-tight allowlisting, which the
  test-suite checkpoints are designed to catch.
status: approved
date: 2026-07-19
issue: 103
origin:
  issue: gosha70/code-copilot-team#103
  urls:
    - https://github.com/gosha70/code-copilot-team/issues/103
  origin_claim: |
    Issue #103: the API performs no Host-header validation, so DNS rebinding
    makes all 18 routes reachable AND readable by a hostile page (CORS does
    not defend against rebinding; loopback binding does not either). Add a
    Host allowlist covering every route; add an Origin check for
    state-changing routes if it does not break the Studio or TestClient;
    treat Sec-Fetch-Site as optional defence-in-depth only after verifying
    browsers send it consistently; defer a local token unless Host+Origin
    prove insufficient.
---

# Plan: API Host + Origin guard (#103)

Grounded (verified 2026-07-19, empirically):

- `TrustedHostMiddleware` compares `headers["host"].split(":")[0]` — port is
  stripped, so the allowlist is hostnames; mismatch → `400 Invalid host
  header` before the handler runs.
- `TestClient` defaults to `Host: testserver`, and sends **no** `Origin` and
  **no** `Sec-Fetch-Site`. Pointing it at `http://127.0.0.1:8765` yields
  `Host: 127.0.0.1:8765`.
- The Studio calls the API cross-origin (`localhost:3000` →
  `127.0.0.1:<port>` via `NEXT_PUBLIC_API_BASE`), so its requests DO carry
  `Origin: http://localhost:3000`.
- `[::1]:8765`.split(":")[0] == `[` — IPv6 literals cannot be allowlisted by
  this middleware. Moot today (uvicorn binds IPv4 `127.0.0.1`), but it must
  be noted so a future `::`-bind change is not silently broken.

## Deliverables

1. `api/server.py`: `TrustedHostMiddleware` with a `create_app`-constructed
   allowlist (FR-1, FR-5), plus a small Origin-check middleware/dependency
   applied to non-GET requests (FR-2).
2. `constants.py`: the default host + origin allowlists as named constants.
3. `tests/test_api.py`: point `TestClient` at an allowlisted base_url
   (FR-6); new admission tests per FR-7 (likely a focused
   `test_api_admission.py` so the guard's cases live together).
4. README: the guard note (FR-8).

## Decisions to confirm at approval

- **D-core-contract** — Host + Origin only. `Sec-Fetch-Site` is NOT part of
  the contract (unverified on the real browser path); no local token.
  *(Pre-set by the maintainer 2026-07-19; recorded, not re-litigated.)*
- **D-absent-origin** — a request with NO `Origin` header is ALLOWED even on
  state-changing routes. Required: `TestClient`, `curl` and scripts never
  send one. Documented limit: this does not stop a local non-browser
  process, which already has code execution and is outside the threat
  model. *(Recommend — the alternative breaks every non-browser client for
  no gain against the rebinding threat, which is browser-borne and always
  carries a forged-impossible `Host`.)*
- **D-test-host** — tests point `TestClient` at
  `http://127.0.0.1:<port>` rather than adding `testserver` to the
  production default allowlist. *(Recommend — keeps the shipped allowlist
  tight; `testserver` in production config would be a small but real
  widening, and a needless one.)*
- **D-origin-scope** — the Origin check applies to ALL non-GET methods
  (POST/PUT/PATCH/DELETE), not a hand-maintained route list. *(Recommend —
  a list would drift as routes are added; method-based is closed by
  default.)*
- **D-failure-mode** — Host mismatch → `400` (Starlette's built-in);
  disallowed Origin → `403` with a short constant message, no echo of the
  offending value. *(Recommend.)*

## Out of scope

`Sec-Fetch-Site` (FR-3), any local token/handshake (FR-4), authentication,
rate limiting, the probe's DSN constraints (#101, follows this slice), and
any change to endpoint payloads.

## Test strategy

Focused admission tests with `TestClient` (fastapi/httpx venv):
allowed Host passes on a read route; `Host: attacker.com` → 400 on a read
AND on a state-changing route (proving the guard runs before handlers);
POST with a disallowed `Origin` → 403; POST with NO `Origin` → passes; POST
with the Studio's real origin (`http://localhost:3000`) → passes. Plus the
existing suite re-pointed per D-test-host, which is itself the regression
signal that the guard does not break normal operation. Local battery: full
suite, fastapi run, Studio build (untouched). CI: all checks + CodeQL.
Manual: `serve` + click through the Studio is the honest end-to-end check
that the browser path still works, since no automated test exercises a real
browser.
