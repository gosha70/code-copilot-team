# Tasks: reviewer fallback at round time (D1)

| # | Task | File(s) | Done |
|---|------|---------|------|
| 1 | One fallback per round on a non-zero invocation; skip the failed provider; both invocations recorded (FR-1, FR-2) | `scripts/review-round-runner.sh` | [x] |
| 2 | Driver debits the failed invocation and journals `reviewer_fallback`; the event is a policy decision on the Runs tab (FR-3) | `scripts/auto-build-loop.sh`, `scripts/session_analytics/constants.py` | [x] |
| 3 | Runner and driver tests; pins (FR-4) | `tests/test-review-loop.sh`, `tests/test-auto-build-loop.sh`, `tests/test-counts.env`, `README.md` | [x] |
| 4 | README paragraph | `README.md` | [x] |
| 5 | DeepSeek review round over the branch (owner's request); findings acted on; artifact committed | `specs/auto-build-reviewer-fallback/collaboration/` | [x] |
