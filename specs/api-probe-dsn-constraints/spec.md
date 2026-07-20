# Spec: probe DSN constraints (#101)

`POST /api/settings/test-connection` accepts a **caller-supplied DSN** and
attempts a real connection to it. #100 removed the leaked driver text and
#103 closed the browser-rebinding path, so what remains is a local-process
concern plus one concrete primitive verified during the threat model:

    probe("sqlite:///…/attacker-chosen.db")  →  creates a 172 KB file
                                                containing the full schema

i.e. arbitrary file *creation* anywhere the server user can write
(non-destructive — sqlite refuses to overwrite a non-DB file — but real),
plus unconstrained outbound connection attempts to any host the DSN names.

Decision recorded on the issue (2026-07-19): keep caller-supplied DSNs,
because validating a DSN *before saving it* is genuine product value in the
Settings page; constrain them instead.

Grounded (verified 2026-07-20): `Database.connect` resolves a sqlite target
with a non-obvious rule (`path[1:]` when it starts with `/`, so
`sqlite:////abs/path` is the absolute form and `sqlite://` is in-memory) —
any second parser would drift from it. `server.py:201` calls
`probe(req.dsn or dsn)`, collapsing the caller's DSN and the configured one
into a single argument, so probe cannot currently know the configured host.
The Studio renders failures as `✗ ${r.error}` (`settings/page.tsx:71`), so
it carries any message without change.

## User Scenarios

- US1: As an operator, I paste a Postgres DSN pointing at my configured
  database host and click Test Connection — it works exactly as before.
- US2: As an operator who typos a scheme (`mysql://…`) or points at an
  unrelated host, I get a specific, actionable message instead of a generic
  failure — and no connection attempt is made.
- US3: As an operator configuring a brand-new sqlite store, Test Connection
  tells me the file does not exist yet rather than silently creating one.
- US4: As a security reviewer, this endpoint can no longer be used to create
  files at arbitrary paths, nor to attempt connections to arbitrary hosts.

## Requirements

- FR-1: **Scheme allowlist** — only `sqlite`, `postgresql`, `postgres` are
  accepted. Anything else is rejected BEFORE any connection attempt.
- FR-2: **Host allowlist** — for non-sqlite DSNs the host must be loopback
  (`localhost`, `127.0.0.1`, `::1`) or the host of the **configured** DSN.
  Rejected before any connection attempt, so no outbound probe occurs.
- FR-3: **SQLite existing-file-only** — a `sqlite:` DSN is probed only when
  its resolved target is an existing file. A non-existent path is rejected
  with a message saying so; the probe never creates a database file.
- FR-4: **One path resolver** — the sqlite target resolution used for FR-3
  MUST be the same code `Database.connect` uses, extracted into a shared
  helper rather than reimplemented, so the validator and the connector
  cannot disagree about what a DSN points at.
- FR-5: **Configured DSN available to the validator** — `probe` receives the
  caller's DSN and the configured DSN separately (today the call site merges
  them), so FR-2 can compare against the configured host.
- FR-6: **Closed diagnostic set extended, not bypassed** — rejections use
  new `error_code`s in the #100 closed set with curated constant messages;
  no DSN content, host, path, or exception text appears in any response.
- FR-7: **Caller-supplied DSNs preserved** — a DSN that satisfies FR-1..FR-3
  is probed exactly as today; the success payload is unchanged.
- FR-8: **Tests** — truth table over schemes, hosts (loopback, configured,
  foreign), and sqlite (existing file, missing file, in-memory); a test
  proving **no file is created** for a missing sqlite path; a test proving
  no rejection response echoes the DSN; the existing success path unchanged.
- FR-9: **Docs** — README note on what the probe accepts and why.

## Constraints

- Stdlib only (`urllib.parse`, `pathlib`); no new dependencies.
- **No auth or token work** — #103 closed the browser path; this slice is
  about what the endpoint will *do*, not who may call it.
- **No Studio change** — the existing error display carries the new
  messages; verified, not assumed.
- No change to any other endpoint or to `Database.connect`'s behaviour
  (only the extraction of FR-4's helper).
- One issue per PR: this bundle covers exactly #101.
