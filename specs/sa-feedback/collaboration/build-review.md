---
feature_id: sa-feedback
date: 2026-09-23
status: final
phase: build
mode: review
subject_provider: claude
peer_provider: deepseek
peer_profile: deepseek
runner_fingerprint: ae8dc147cf1264834bab35d116b6ab96b06618f438763cde3a90621d78036dba
verdict: PASS
blocking_findings_open: 0
target_ref: feat/371-a3-feedback
rounds_completed: 2
attempt_count: 1
bypass: false
---

# Peer Review: sa-feedback — Build Phase

**Reviewer**: deepseek
**Scope**: both
**Rounds**: 2
**Verdict**: PASS

## Summary

Round 2 review of the sa-feedback slice (A3). The builder addressed the substantive Round 1 findings: the DB-API `IntegrityError` race is now caught and mapped to `InvalidFeedbackError` → 400, the large-whole-number round-trip is fixed with a `2**53` guard, the all-NULL CHECK case is tested, the single-query spy now asserts the self-LEFT-JOIN shape, and the README states the bounds. The remaining items are minor notes; no blocking issues found.

## Findings

- [note] f-4dfa29f6: The helper derives the driver's `IntegrityError` by importing the top-level module of `type(db.conn).__module__`. For `sqlite3.Connection` this is `sqlite3` (fine); for `psycopg` connections the module is `psycopg` (fine today), but a wrapper/proxy connection class (e.g. a pooled connection whose `__module__` is `psycopg_pool` or a test double) would import the wrong module and raise `AttributeError`/`ImportError` at the moment a constraint fires — turning a 400 into a 500 exactly on the path this fix was meant to protect. (scripts/session_analytics/feedback.py)
- [note] f-1fa3db80: The `except _integrity_error(db)` branch calls `db.rollback()` then raises. If the caller (the API route) also closes the connection in `finally`, that is fine, but the store function now owns a rollback that the caller did not ask for; a future caller that wraps `add_feedback` in its own transaction (e.g. a batch writer) would have its outer transaction silently rolled back. The docstring does not say the function rolls back on refusal. (scripts/session_analytics/feedback.py)
- [note] f-1e646fbe: The race is now handled at the insert (UNIQUE fires → 400), which is correct. But the pre-check still reads `later.id` and the row's target/name; between that read and the insert another writer can supersede the same row, and the error message the user sees is the generic "was superseded by another writer" rather than the specific invariant that failed. Acceptable, but the message loses the "same target/name" detail that the pre-check would have given. (scripts/session_analytics/feedback.py)
- [note] f-866d05e4: The race test mocks `_check_supersedes` to return the base id, forcing the UNIQUE to fire. It does not assert that the *rollback* actually happened (i.e. that no partial row was left). A future change that removed the `db.rollback()` would still pass this test if the connection is closed afterwards. (scripts/session_analytics/tests/test_feedback.py)
- [note] f-49961441: The test asserts `post({"name": "n"})` is 422 (Pydantic missing `value`), which is correct, but it does not assert the 422 body shape or that the route's own 400 path is distinct from Pydantic's 422. A future change to the `FeedbackWrite` model (e.g. making `value` optional) would silently move this case to 400 without the test noticing the semantic change. (scripts/session_analytics/tests/test_api.py)
- [note] f-90045285: The section says "a custom name (up to 80 characters) is accepted with any one of those types" and states the 4,000-char text/rationale bound, but does not state that `source_id` is bounded at 120 characters or that the source is resolved per request (so a changed `.env` is honoured without a restart). Minor, but the source-resolution behaviour is user-visible. (scripts/session_analytics/README.md)
- [note] f-956cfa4d: The default name is "the first text-typed entry in the vocabulary", which is `note` today. The Round 1 note stands: this couples the UI to a vocabulary invariant (exactly one text-typed name, and it is the default) that is not stated in the spec. The builder marked it not-applicable, but the coupling is real — a future text-typed name added before `note` silently changes the default. (studio/components/FeedbackControl.tsx)
- [note] f-3a35b95a: For a custom numeric name (`entry` is null), `draftValue` accepts any finite number, including `1e20`. The server stores it as a float and reads it back as a float (the Round 1 fix), so round-trip is consistent. But the form's `<input type="number">` with `step="any"` will accept `1e20` and the display will show `100000000000000000000` — a silent precision cliff for a custom numeric name. Acceptable for a custom name, but worth a note in the README's custom-name paragraph. (studio/lib/feedbackView.ts)
- [note] f-70f2c865: The Round 1 note about the magic index `r[13]` for `later.id` stands. The builder marked it not-applicable (consistent with the package's style), but the mixed `f.`-prefixed and bare `later.id` in the same string literal is still easy to misread, and `_row` indexes positionally. A one-line comment above `_ROW_COLS` naming the trailing column would remove the ambiguity at no cost. (scripts/session_analytics/feedback.py)
