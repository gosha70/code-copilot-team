---
spec_mode: lightweight
feature_id: api-probe-dsn-constraints
risk_category: security
justification: |
  Small, contained validation slice on one endpoint: scheme/host allowlists
  plus sqlite existing-file-only, removing a verified arbitrary-file-creation
  primitive and unconstrained outbound probing. Touches db_test.py,
  constants.py, one call site, and extracts an existing sqlite-path helper in
  db.py (behaviour-preserving). No auth work (#103 closed the browser path),
  no Studio change, no new deps — lightweight spec_mode is proportionate.
status: approved
date: 2026-07-20
issue: 101
origin:
  issue: gosha70/code-copilot-team#101
  urls:
    - https://github.com/gosha70/code-copilot-team/issues/101
  origin_claim: |
    Issue #101 + its recorded threat-model decision (2026-07-19): keep
    caller-supplied DSNs for test-before-save; add a scheme allowlist
    (sqlite, postgresql, postgres); add a host allowlist (loopback plus the
    configured DSN host, optional extra hosts later); for SQLite probe only
    EXISTING database files, never create one. No auth/token work (#103
    handled browser rebinding); no Studio UX redesign unless the existing
    error display cannot carry the constrained failure messages.
---

# Plan: probe DSN constraints (#101)

Grounded (verified 2026-07-20):

- `Database.connect` (db.py:60-70) resolves sqlite targets with a
  non-obvious rule — `path = dsn[len("sqlite://"):]`, then `path[1:]` when
  it starts with `/`, and `:memory:` for `sqlite://` or `sqlite:///`. So
  `sqlite:////abs/path` is the absolute form. A validator that re-parsed
  this independently would be a second parser guaranteed to drift.
- `server.py:201` calls `probe(req.dsn or dsn)` — the caller's DSN and the
  configured DSN are merged before probe sees them, so the host allowlist
  cannot be implemented without changing that call.
- `studio/app/settings/page.tsx:71` renders `✗ ${r.error}`, so any curated
  message displays without a UI change (FR: no Studio work).
- The file-creation primitive is real and was reproduced during the threat
  model: probing a fresh sqlite path created a 172 KB schema file.

## Deliverables

1. `relational/db.py`: extract the sqlite target resolution into a small
   public helper (e.g. `sqlite_target(dsn) -> str`) and call it from
   `connect()` — behaviour-preserving, and the single source FR-4 requires.
2. `constants.py`: three new `PROBE_ERR_*` codes + curated messages, plus
   the scheme and loopback-host allowlists.
3. `api/db_test.py`: `validate_probe_dsn(dsn, configured_dsn) -> Optional[str]`
   (pure; returns an error code or None) called at the top of `probe()`
   before any connection attempt; `probe` gains the configured-DSN argument.
4. `api/server.py`: pass both DSNs (`probe(req.dsn or dsn, configured_dsn=dsn)`).
5. `tests/test_probe_errors.py`: FR-8 truth table + the no-file-created test.
6. README: the accepted-DSN note.

## Decisions to confirm at approval

- **D-new-codes** — add `scheme_not_allowed`, `host_not_allowed`,
  `sqlite_file_missing` to the #100 closed set rather than folding them into
  `bad_dsn`. *(Recommend — the set is meant to grow deliberately, and each
  needs a different operator action: fix the scheme, use the configured
  host, or save-then-ingest to create the file.)*
- **D-shared-resolver** — extract the sqlite path rule into db.py and use it
  from both `connect()` and the validator. *(Recommend — the alternative is
  two parsers of a non-obvious rule, which is the exact defect class flagged
  and fixed twice in this series.)*
- **D-sqlite-new-file-message** — a missing sqlite file is REJECTED with
  "database file does not exist yet — save the configuration and run ingest
  to create it", not created. *(Recommend — for a brand-new store there is
  nothing to test; probing would only prove the server can write a file,
  which is precisely the primitive being removed. The message keeps the
  test-before-save workflow honest rather than blocking it.)*
- **D-in-memory-allowed** — `sqlite://` / `sqlite:///` (in-memory) is
  accepted: it touches no filesystem path and is what the test suite uses.
  *(Recommend.)*
- **D-host-source** — the allowlist is loopback + the host parsed from the
  CONFIGURED DSN only. Config-declared extra hosts are deliberately deferred
  until someone needs them. *(Recommend — matches the recorded decision.)*
- **D-no-studio-change** — confirmed by reading `settings/page.tsx:71`; the
  display renders arbitrary strings. *(Recommend.)*

## Out of scope

Authentication, tokens, rate limiting (#103 closed the browser path);
config-declared extra host allowlists; any other endpoint; changes to
`Database.connect`'s behaviour beyond the helper extraction; Studio UX.

## Test strategy

Pure-unit truth table for `validate_probe_dsn`: schemes (`sqlite`,
`postgresql`, `postgres` accepted; `mysql`, `http`, empty, garbage
rejected); hosts (loopback names, the configured DSN's host, a foreign host,
a host that only *looks* like the configured one); sqlite (existing file →
accepted, missing file → `sqlite_file_missing`, in-memory → accepted,
relative vs `sqlite:////abs` forms via the shared resolver). Integration:
`probe()` on a missing sqlite path returns the rejection AND
`os.path.exists` is still False afterwards (the primitive is gone); a
rejected response contains no DSN fragment (asserted over the full
serialized payload, per the #100 convention); the existing success path is
unchanged. Endpoint-level: a foreign-host DSN is rejected without any
connection attempt. Local battery: full suite, FastAPI run, Studio build.
