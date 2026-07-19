# Spec: API Host + Origin guard (#103)

The session-analytics API performs no `Host`-header validation. CORS is
configured (`allow_origins = http://localhost:3000, http://127.0.0.1:3000`)
and does block ordinary cross-origin JS, but **CORS is not a defence against
DNS rebinding**: a page on `attacker.com` (TTL≈0) re-resolving to
`127.0.0.1` makes requests to `attacker.com:<port>` *same-origin* to the
browser — no preflight, response readable. Loopback binding does not help;
the browser is a co-resident client. All 18 routes are affected, including
`/api/sessions`, `/api/search` (archived trace text), `/api/settings`, and
the state-changing `PUT /api/config` / `POST /api/analyze` /
`POST /api/settings/test-connection`.

Grounded (verified 2026-07-19): Starlette's `TrustedHostMiddleware` compares
`headers["host"].split(":")[0]` — **port-insensitive, hostname only** — and
returns `400 Invalid host header` on mismatch. `TestClient` defaults to
`Host: testserver` and sends **neither** `Origin` nor `Sec-Fetch-Site`. The
Studio reaches the API cross-origin (`localhost:3000` → `127.0.0.1:<port>`),
so browsers do send `Origin` on its requests.

## User Scenarios

- US1: As an operator running `serve`, the Studio works exactly as before —
  every page loads, Test Connection and config save still function.
- US2: As a security reviewer, a page performing DNS rebinding against the
  API is rejected with `400` before any handler runs, on every route.
- US3: As a developer, the existing test suite and `curl`/script access to
  the local API keep working.

## Requirements

- FR-1: **Host validation on every route.** Requests whose `Host` hostname
  is not in the allowlist are rejected before handler dispatch. Default
  allowlist: `127.0.0.1`, `localhost`. This is the load-bearing control
  against rebinding (a browser always sets `Host` from the URL, so it cannot
  be forged by page script).
- FR-2: **Origin check on state-changing routes.** For non-GET requests, a
  PRESENT `Origin` must be in the allowed set (the Studio origins, plus the
  API's own loopback origins). An ABSENT `Origin` is allowed — `TestClient`,
  `curl`, and server-side callers never send one, and requiring it would
  break them. The honest limit of this control is documented: it stops
  cross-origin browser POSTs that CORS's preflight does not (simple
  requests), but does not stop a local non-browser process, which is out of
  scope for this threat model (such a caller already has code execution).
- FR-3: **`Sec-Fetch-Site` is NOT part of the contract.** `TestClient` does
  not send it and the real browser path has not been verified; per the
  2026-07-19 decision it may only ever be defence-in-depth after
  verification, never load-bearing. Out of scope for this slice.
- FR-4: **No local token.** Deferred unless Host+Origin prove insufficient.
- FR-5: **Configurable, closed by default.** The allowlists are constructed
  in `create_app` (not hardcoded in middleware call sites) so tests and
  future deployments can extend them explicitly; the default must not
  include wildcards.
- FR-6: **Tests keep passing without weakening production config.** The API
  test suite points `TestClient` at an allowlisted host rather than
  `testserver` being added to the production default.
- FR-7: **Tests** prove: an allowed Host passes; a rebinding-style Host
  (`attacker.com`) gets 400 on both a read and a state-changing route; a
  disallowed `Origin` on a POST is rejected; an absent `Origin` on a POST is
  allowed; the Studio's real origin is allowed.
- FR-8: **Docs**: one README note on what the guard blocks and how to extend
  the allowlist.

## Constraints

- No new dependencies (Starlette middleware ships with FastAPI).
- No change to any endpoint's success behaviour or payload shape.
- The Studio must need no change.
- One issue per PR: this bundle covers exactly #103.
