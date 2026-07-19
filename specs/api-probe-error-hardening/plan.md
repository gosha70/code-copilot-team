---
spec_mode: lightweight
feature_id: api-probe-error-hardening
risk_category: security
justification: |
  Small, single-purpose security fix: the connection-probe endpoint returns
  driver exception text (host/IP/port/user) to HTTP callers on a
  caller-supplied DSN. Fix is contained to api/db_test.py plus constants and
  tests; no schema, no new deps, no other endpoint touched. Lightweight
  spec_mode is proportionate — the behavior change is one response field's
  content, fully specified by the classification table below.
status: approved
date: 2026-07-19
issue: 100
origin:
  issue: gosha70/code-copilot-team#100
  urls:
    - https://github.com/gosha70/code-copilot-team/issues/100
  origin_claim: |
    Issue #100: /api/settings/test-connection returns raw exception text
    (CodeQL py/stack-trace-exposure, medium, open since 2026-07-16).
    Replace it with a closed set of curated diagnostics — classify the
    exception by type and by driver signatures used ONLY for classification
    (never echoed), return a fixed message plus a stable error_code, keep
    full detail in the server log, preserve actionable operator feedback in
    the Settings "Test Connection" button. No auth/rate-limiting, no other
    endpoint, no schema change.
---

# Plan: probe error hardening (#100)

Grounded (verified 2026-07-19): `api/db_test.py probe()` returns
`_safe_error(exc)` = first line of `str(exc)`, capped at 200 — the taint
CodeQL follows to `server.py:144`. `_log.warning(..., exc_info=exc)` already
captures full detail server-side. The studio renders the string verbatim
(`settings/page.tsx:71`: `✗ ${r.error}`). `test_api.py:156` covers only the
success path.

## The fix

`probe()` never places exception-derived text in its return value. Instead:

1. **Classify** the exception into a closed enum. Type first (`ImportError`
   → driver missing; `ValueError` from our own `Database.connect` → bad DSN;
   `sqlite3.OperationalError` / `psycopg.OperationalError` → inspect
   signature), then a small table of well-known driver substrings matched
   case-insensitively against `str(exc)` **for classification only** — the
   matched text is never returned.
2. **Return** `{"ok": False, "error_code": <enum>, "error": <curated
   constant>}` where the message is a fixed string in `constants.py`.
3. **Log** full detail (unchanged).

### Classification table

| Signal | `error_code` | Response message |
|---|---|---|
| `ImportError` | `driver_missing` | "PostgreSQL driver not installed — run: pip install psycopg" |
| `ValueError` from `Database.connect` (empty/unsupported DSN) | `bad_dsn` | "DSN is empty or not a supported format (sqlite:/// or postgresql://)." |
| auth signatures (`password authentication failed`, `authentication failed`, `role ... does not exist`) | `auth_failed` | "Authentication failed — check the username and password in the DSN." |
| unreachable signatures (`could not connect`, `connection refused`, `could not translate host`, `timeout expired`, `network is unreachable`) | `unreachable` | "Could not reach the database host — check the host and port in the DSN, and that the server is running." |
| missing-db signatures (`does not exist` on database, `unable to open database file`) | `database_missing` | "The database does not exist (or the SQLite path is not writable)." |
| permission signatures (`permission denied`, `must be owner`, `readonly database`) | `permission_denied` | "Connected, but the account lacks permission to create/read the schema." |
| anything else | `unknown` | "Connection failed. See the server log for details." |

Ordering is table order (first match wins); the table lives in
`constants.py` as `(code, message, signatures)` triples so the CLI/UI and
tests share one source of truth.

## Deliverables

1. `constants.py`: `PROBE_ERROR_*` codes + curated messages + the signature
   table.
2. `api/db_test.py`: `classify_probe_error(exc) -> (code, message)` (pure,
   unit-testable) replacing `_safe_error` in the response path; logging
   unchanged.
3. `tests/test_api.py` (or a focused test module): classification truth
   table incl. a synthetic Postgres-style auth error asserting the
   host/IP/user do NOT appear in the response; success path unchanged;
   endpoint-level assertion that `error_code` is present.
4. README: one line under Settings/troubleshooting noting that the probe
   returns a category, with detail in the server log.

## Decisions to confirm at approval

- **D-error-code-additive** — add `error_code` alongside `error` rather than
  replacing it (the studio keeps rendering `error`; no UI change needed).
  *(Recommend.)*
- **D-signature-matching** — classify on lowercase substring matching of
  `str(exc)`; the matched text is NEVER returned. Type-based signals take
  precedence over substrings. *(Recommend — it is the only portable way to
  distinguish auth-vs-unreachable across sqlite3/psycopg without importing
  psycopg at module level.)*
- **D-no-ui-change** — studio untouched this slice (`✗ ${r.error}` renders
  the curated message fine). *(Recommend.)*
- **D-success-shape** — success response unchanged (`ok/dialect/sessions`).
  *(Recommend — no consumer churn.)*

## Out of scope

Endpoint auth, rate limiting, and SSRF-style restrictions on the
caller-supplied DSN — **filed separately as #101** (unauthenticated
reachability oracle) by maintainer direction; explicitly NOT mixed into this
PR. Also out: any other endpoint's error handling.

## Test strategy

Unit: `classify_probe_error` truth table over synthetic exceptions
(including a realistic multi-line psycopg-style message carrying host, IP,
port and user) asserting (a) the right code, (b) the returned message is
exactly the curated constant, (c) none of host/IP/port/user substrings
appear in the returned message. Integration: existing success-path
`test_test_connection` unchanged; a failure-path endpoint test asserting the
response contains `error_code` and NOT the injected secret-ish DSN
fragments. Local battery: full suite, FastAPI-installed run, studio build
(untouched). CI is back online — the acceptance signal is the CodeQL alert
closing on the merge commit.
