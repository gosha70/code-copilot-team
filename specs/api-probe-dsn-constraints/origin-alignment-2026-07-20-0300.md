# Origin alignment check — api-probe-dsn-constraints

Origin: https://github.com/gosha70/code-copilot-team/issues/101

Origin claim:
> Issue #101 + its recorded threat-model decision (2026-07-19): keep
> caller-supplied DSNs for test-before-save; add a scheme allowlist (sqlite,
> postgresql, postgres); add a host allowlist (loopback plus the configured
> DSN host, optional extra hosts later); for SQLite probe only EXISTING
> database files, never create one. No auth/token work (#103 handled browser
> rebinding); no Studio UX redesign unless the existing error display cannot
> carry the constrained failure messages.

Working claim:
> specs/api-probe-dsn-constraints/{spec.md,plan.md} bind exactly that scope
> (FR-1..FR-9), approved by the user 2026-07-20 with all six decisions
> confirmed: distinct scheme_not_allowed / host_not_allowed /
> sqlite_file_missing codes; missing sqlite files rejected with
> save-config-and-ingest guidance; in-memory sqlite:// allowed; host
> allowlist = loopback + configured DSN host only (extras deferred); the
> caller DSN is split from the configured DSN in the probe path; the sqlite
> path parsing is extracted into a shared db.py helper and reused. The user
> designated the "missing path remains nonexistent" test as MANDATORY — it
> is the core regression this slice must prove. No implementation exists yet
> on branch fix/api-probe-dsn-constraints-101.

Verdict: aligned
Confidence: high

Checked 2026-07-20 against issue #101 and its recorded decision comment, and
the grounded surfaces: db.py's sqlite target rule (path[1:] when leading "/",
:memory: for empty), server.py:201's merged probe(req.dsn or dsn) call, the
Studio's `✗ ${r.error}` display, and the file-creation primitive reproduced
during the threat model.
