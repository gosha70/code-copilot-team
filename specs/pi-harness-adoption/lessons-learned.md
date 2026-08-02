# Lessons Learned — Pi harness adoption

Operationally useful lessons from adopting Pi as a first-class enforced harness.
These are the practices that repeatedly mattered; they generalize to any future
adapter or capability work.

## 1. Honesty boundaries: state what is *enforced* vs *reported*

Every capability was shipped with an explicit **enforceable-vs-declared** line,
not a marketing status. The recurring discipline:

- Before claiming a capability works, verify the primitive actually exists. Pi's
  SDK has **no subagent/child-session primitive, no result contract, no team
  primitive, no Stop/compaction event** — confirmed against upstream docs, not
  assumed. Where a primitive was unverified from our position, we did **not**
  build on it (the `ctx.mode` / native-transcript discipline).
- Separate "resolved & reported" from "enforced." A T7.1 manifest field is
  *reported* until a runner can *apply* it; a T7.3 verification status is
  *tracked* until T7.4 *runs* it. Say which.
- When a value cannot be produced, mark it **absent (`null`)**, never `0` or a
  fabricated default (the analytics null-vs-zero discipline).

**Takeaway:** the status is a claim you must be able to defend with a test. If
you can't test it, it's `degraded`/`unsupported`, not `enabled`.

## 2. Degraded, not faked

The most valuable posture of the whole adoption. Repeatedly, the honest move was
to report a real limitation rather than approximate:

- verification/review gates fire at explicit CCT actions because **Pi has no
  Stop event** — reported `degraded`, never a fake lifecycle hook.
- the sandbox capability **cannot create a sandbox** — it detects + fail-closed
  rejects; fork-bomb containment is out of reach and is *called out*, not tested
  as if it worked.
- teams are a **polled append-log + separate runners**, not a live bus — reported
  `degraded`, never presented as live peer execution.

A `degraded` that tells the truth is worth more than an `enabled` that lies. The
capability registry became the single home for these honest reasons, and the
security battery asserts the degraded surfaces are **never** reported `enabled`.

## 3. Autosync / merge-race discipline

The single biggest process hazard. The user's IDE autosync **pushes any local
commit within seconds and can auto-merge the PR** — so a review-fix commit that
is still local when the PR merges lands master **without the fix**. This
happened on #154, #157 (twice), #160.

Practices that worked:

- **Every commit must be green and mergeable** — never stack a "hold for review"
  state, because it can ship at any moment.
- **Verify the merge in its own command**: check `state=MERGED` **and** that the
  merge `head` is the commit you expected (the *fix* commit, not the pre-fix
  one). Never assume "merged" means "merged with the fix."
- **Recovery when the fix missed the merge:** the PR is closed, so cherry-pick
  the fix onto a fresh branch off the new master and open a **follow-up PR**.
  This is a reliable, repeatable recovery — not an incident.
- **Cleanup order is exact:** verify MERGED (own command) → sync master →
  confirm the fix is present on master → delete the branch. Deleting an open
  PR's head auto-closes it.

## 4. Tamper-safe ledgers: sanitize is not enough

Any `.cct/*.json` the runtime reads is **untrusted** and may be hand-edited. Two
levels are required, and the second was repeatedly the one reviewers caught:

1. **field sanitization** (single-line, control-char strip, bounded, enum-clamp)
   — necessary but insufficient.
2. **structural re-enforcement of invariants on load** — the ledger must be
   *reconciled* to the same contract the live operations enforce. The team
   ledger needed: exactly one lead (else reject), approval valid only when
   `approvedBy` is that lead, and a claim valid only when the claimant is active
   **and** consistent with assignment. Field sanitization alone let a tampered
   ledger load `active + approved` with a bogus lead and bypass the gate.

**Takeaway:** `loadX()` must apply the *same* fail-closed invariants as the
runtime operations, or the persisted surface becomes a bypass. Provenance
(`origin: "cct"`) is a hard deletion boundary — preserve it, never rewrite it on
load.

## 5. Security tripwires over the whole surface

Deep per-area tests are essential but scatter the security story. A single
**consolidating battery** — one canonical fail-closed invariant per category,
importing the *same real functions* — gives one place that fails if any
invariant regresses. It is a **tripwire, not a parallel implementation**: it must
exercise the real code path, and it must assert the **specific** reason (a test
that passes via "no such task" instead of "not active" proves nothing). Pair it
with an **audit manifest** mapping each requirement → concrete test, and call out
what is intentionally degraded rather than faking parity.

## 6. Registry-driven docs cannot drift

Capability documentation must be **generated from the registry**, never
hand-authored. The generator is a pure function of `catalog.yaml` +
adapter YAMLs; a `--check` drift guard in CI fails the build if the committed
doc differs from a fresh generation (or if anyone hand-edits it). The fix for
weak wording is to improve the **registry `reason`**, then regenerate — there is
no authored capability claim outside the registry. This same drift-guard pattern
(a golden/regeneration compared in CI, with a planted-drift negative test)
recurred for the capabilities.ts↔pi.yaml seed and the analytics fixtures.

## 7. Small cross-cutting mechanics that saved time

- **Prettier PostToolUse hook churns whole `.ts`/`.json` files** — edit existing
  TS via out-of-band scripts and `git diff` after; new files are fine.
- **`node --test` runs files in parallel** → cross-file spawn contention under
  fork pressure; `--test-concurrency=1` fixed CI flakes.
- **macOS `/var`→`/private/var` symlink** breaks lexical path comparison against
  git/realpath output — normalize both sides via realpath (and resolve the
  deepest existing ancestor to catch symlink escapes).
- **Drift guards need a planted-drift negative test** — proving the guard *fires*
  matters as much as proving it passes.
- **The store persists only fixed columns** — mapping data into
  `RawSession.metadata` does not persist it; verify with a **DB-level** test that
  queries the DB, not the in-memory object. Narrow the claim or file a follow-up.
