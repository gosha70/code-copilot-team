# Origin alignment check — api-probe-error-hardening

Origin: https://github.com/gosha70/code-copilot-team/issues/100

Origin claim:
> Issue #100: /api/settings/test-connection returns raw exception text
> (CodeQL py/stack-trace-exposure, medium, open since 2026-07-16). Replace
> it with a closed set of curated diagnostics — classify by type first, then
> driver signatures used ONLY for classification (never echoed), return a
> fixed message plus a stable error_code, keep full detail in the server
> log, preserve actionable operator feedback. No auth/rate-limiting, no
> other endpoint, no schema change.

Working claim:
> specs/api-probe-error-hardening/{spec.md,plan.md} bind exactly that scope
> (FR-1..FR-7), approved by the user 2026-07-19 with all four defaults
> confirmed: error_code additive alongside a curated error; exception TYPES
> first with substring matching for classification only; no Studio change;
> success payload unchanged. Two maintainer directions are recorded and
> binding: (a) the unauthenticated-DSN / reachability-oracle concern is
> filed SEPARATELY as #101 and must NOT be mixed into this PR; (b) tests
> must assert the raw exception text is absent from the FULL SERIALIZED
> response, not just the `error` field. No implementation exists yet on
> branch fix/api-probe-error-hardening-100.

Verdict: aligned
Confidence: high

Checked 2026-07-19 against issue #100, the live CodeQL alert (rule
py/stack-trace-exposure at api/server.py:144, created 2026-07-16), and the
grounded surfaces: api/db_test.py probe()/_safe_error, server.py's
test_connection endpoint, studio settings/page.tsx:71 rendering `error`
verbatim, and test_api.py:156 covering only the success path.
