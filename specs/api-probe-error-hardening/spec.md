# Spec: probe error hardening (#100)

CodeQL `py/stack-trace-exposure` [medium], open since 2026-07-16, on
`/api/settings/test-connection` → `api/db_test.py probe()`. Not a false
positive: `_safe_error()` logs full detail server-side and caps the response
at 200 chars, but still returns `str(exc)`'s first line — and a real
Postgres failure carries hostname, IP, port, database and username. The
endpoint accepts a **caller-supplied DSN**, so a local caller can probe
arbitrary hosts and read back the driver's verdict.

## User Scenarios

- US1: As an operator whose DSN password is wrong, the Settings "Test
  Connection" button tells me "Authentication failed — check the username
  and password in the DSN", so the result is still actionable.
- US2: As a security reviewer, no response from this endpoint contains
  hostnames, IPs, ports, usernames, file paths, or any other text derived
  from a driver exception — that detail exists only in the server log.

## Requirements

- FR-1: **No exception-derived text in the response.** `probe()` returns
  only curated constants; `str(exc)`, `repr(exc)` and `type(exc).__name__`
  never reach the HTTP payload.
- FR-2: **Closed diagnostic set.** A pure `classify_probe_error(exc) ->
  (code, message)` maps every exception to one of: `driver_missing`,
  `bad_dsn`, `auth_failed`, `unreachable`, `database_missing`,
  `permission_denied`, `unknown` — with the fixed message defined in
  `constants.py` (single source of truth, per the plan's table).
- FR-3: **Classification signals may read the exception; the response may
  not echo it.** Type-based signals take precedence; well-known driver
  substrings are matched case-insensitively for classification only.
- FR-4: **Server-side detail preserved.** Full exception (with traceback)
  continues to `_log.warning(..., exc_info=exc)`.
- FR-5: **Additive response shape.** `error_code` is added; `error` remains
  (now a curated message); the success path (`ok`/`dialect`/`sessions`) is
  unchanged, so the studio needs no change.
- FR-6: **Tests** prove the leak is closed: a realistic multi-line
  psycopg-style auth error carrying host/IP/port/user classifies as
  `auth_failed` AND — the binding assertion (maintainer guardrail,
  2026-07-19) — none of those substrings appear anywhere in the **full
  serialized response** (`json.dumps` of the whole payload), not merely in
  the `error` field, so a leak through `error_code` or any future field is
  caught too; plus the full classification truth table and an
  endpoint-level failure-path assertion over the raw response body.
- FR-7: **Docs**: one line noting the probe returns a category, with detail
  in the server log.

## Constraints

- Stdlib only; no new deps; no psycopg import at module level.
- No change to any other endpoint, to the schema, or to the studio.
- One issue per PR: this bundle covers exactly #100.
- Acceptance includes the CodeQL alert closing on the merge commit.
