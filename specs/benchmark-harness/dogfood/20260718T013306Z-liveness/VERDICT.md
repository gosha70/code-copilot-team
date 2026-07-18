# Gate 1 — liveness run verdict (T4.4)

Run: `20260718T013306Z-aider-polyglot-claude-code-001` · backend `claude-code`
· model `sonnet` · 1 attempt/task · executed 2026-07-18 (UTC) on the
maintainer's machine. GitHub Actions was unavailable; all verification local.

## Scope deviation (documented, deliberate)

The committed dogfood subset lists 12 tasks across 6 languages, but this host
has **no go, cargo, gradle, or cmake toolchains** — those languages' verify
steps would fail environmentally, not on model quality, spuriously tripping
the >30%-failure pause rule. Per the 2026-07-17 maintainer decision, this run
covers the **6 python + javascript tasks** (the languages whose verify can
execute honestly here). go/rust/java/cpp liveness remains open until a host
with those toolchains runs the full subset.

Also note: the subset itself was REPAIRED in this same increment — the
original file listed `leap` exercises that never existed in Aider's
hard-exercise polyglot snapshot (the pre-run blocker recorded in the Phase 4b
standing notes). Every task below is snapshot-verified
(`TestDogfoodSubsetResolvesAgainstRealCache` passes).

## Results — 6/6 pass, 0% failure (threshold: pause at >30%)

| Task | Result | tests_passed | Elapsed |
|---|---|---|---|
| javascript/bowling | pass | true | 147.0s |
| javascript/grade-school | pass | true | 62.1s |
| python/affine-cipher | pass | true | 24.6s |
| python/book-store | pass | true | 60.7s |
| python/bowling | pass | true | 132.5s |
| python/grade-school | pass | true | 30.6s |

**Gate 1 verdict: PASS.** The harness end-to-end (prepare → claude-code
invocation → worktree edit → verify → classify) is live and produces
credible pass verdicts on real tasks.

## Notes

- A mechanics canary (`python/bowling`, separate run) passed in 99.8s before
  this batch; not committed (superseded by this run's own python/bowling).
- `backend.metadata.session_id` is **null** on all attempts: the harness
  invoked claude-code in bare mode (session capture is a launcher-mode
  feature). E9 `correlate` will report these runs as `null_session_id` —
  correctly, per its explicit-coverage contract.
- The two javascript `diff.patch` files are filtered to source-only sections
  (see `DIFF-FILTERED.txt`): `npm install` materialized `node_modules/` and a
  generated `package-lock.json` in the worktrees and the raw `diff -urN`
  patches were ~79 MB each; both the node_modules sections AND the lockfile
  section are stripped from the committed patches.
- Caveat on `score.json` derived counts for the javascript attempts: the
  harness computed `files_changed`/`lines_added`/`lines_removed` over the RAW
  worktree diff, so they include the install noise (e.g.
  `files_changed=21406`, `lines_added>1M`). Those counts were **not** used
  for the Gate 1 judgment — the verdict rests on the verify step's test
  execution (`tests_passed`).
- `worktree/` and `prepared/` snapshots are not committed (hundreds of MB;
  reconstructible from the pinned polyglot cache + the diffs).
