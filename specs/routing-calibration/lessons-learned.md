# Lessons learned — routing-calibration (E3 of #109, issue #266)

Four lessons from the T1–T5 review rounds. All four are
**cross-project**: none depends on routing, gates, or this codebase.
Each is recorded with the concrete incident that produced it, because
the abstraction alone is forgettable and the incident is not.

---

## 1. A closed vocabulary checks the feature's NAME, not its SOURCE

**Incident (T2, round 1).** Feature vocabulary `fv1` is a closed
tuple, and a mutation battery existed specifically to prove that no
post-execution figure could enter the feature vector. The battery
passed. It was nevertheless possible to read `trial_count` — a blessed
member of that closed tuple — from `rec["confidence"]["basis"]
["trials"]`, an *execution observation*, rather than from the
scenario's declared trial count. The leakage ban held on the
vocabulary and leaked through the plumbing behind one of its entries.

The battery was structurally blind: every mutation asked "can a
*new* name enter the vector?" None asked "does an *existing* name
still come from where it claims to?"

**The lesson.** When a rule constrains a set of names, the tests will
naturally guard the set boundary — that is the visible edge. The
unguarded edge is each member's provenance. A vocabulary check and a
provenance check are different tests, and passing the first says
nothing about the second.

**How to apply.** For any closed vocabulary whose members carry a
sourcing rule, add a mutation class that *keeps the vocabulary intact*
and changes only where a member is read from. If that mutation does
not fail a test, the sourcing rule is unenforced no matter how strict
the vocabulary looks.

---

## 2. A mutation battery's real value is catching tests that pass for
the wrong reason

**Incident (T3, self-caught).** Six mutations were written for the
false-downgrade metric. Two did not discriminate — and neither was a
mutation problem:

- The normalization-parity test compared evaluation against serving.
  The mutation moved *both*, so they stayed equal and the test still
  passed. It had been asserting a tautology.
- The baseline test had both branches returning `tier1`, so a fixture
  that was supposed to prove the branches disagree proved nothing.

Both were rebuilt on absolute, hand-computed assertions. Without the
battery, both would have shipped as green tests that could never fail.

**The lesson.** The value of mutation testing is usually described as
"proving the tests catch bugs." The higher-value outcome is the
inverse: it identifies tests that are *incapable* of failing. A
relative assertion (`a == b`) where a mutation moves both sides, or a
fixture whose two branches happen to agree, looks identical to a real
test in a green run.

**How to apply.** When a mutation fails to discriminate, do not patch
the mutation to be nastier — first ask whether the *test* is
tautological. Prefer absolute hand-computed expectations over
comparing two things the system derives, especially when both derive
through the code under test. And never let a non-discriminating
mutation pass silently: it is a finding, not a failed experiment.

---

## 3. A reasoning error can invert a safety reading while sounding
conservative

**Incident (T3, round 1 — the most transferable).** The safety
baseline for "was this recommendation a downgrade?" took the *lowest*
tier the execution chain engaged. That was recorded, in writing, as
the conservative choice.

It was the opposite. A chain is a **composition, not a menu**: a
delegated task's chain is `[tier1 orchestrator, tier2 delegate]`, so
`min` yields `tier2`, nothing ranks below it, and no prediction on any
delegated task could *ever* count as a false downgrade — silently
excusing the exact case the metric existed to catch. The reviewer's
correction included the sentence that mattered most: *"`min` is the
permissive reading, not the conservative one."*

Note what did and did not go wrong. The code did what it was written
to do. The tests passed. The rule was documented. The defect was that
"conservative" had been *asserted* about a choice rather than
*derived* from what the choice permits — and once written down, the
label was never re-examined.

**The lesson.** "Conservative", "safe", "strict", and "fail-closed"
are conclusions, not properties. Any of them can be attached to a
choice that does the reverse, and once written into a comment or a
design doc, the label is what future readers check against instead of
the behaviour. This is a reviewer-and-author failure mode, not a code
defect — which is why tests do not catch it and why it gets
rediscovered expensively.

**How to apply.** When labelling a choice conservative, state the
enumeration that makes it so: *what does this permit that the
alternative forbids?* If that sentence cannot be written concretely,
the label is a guess. In review, treat every safety adjective as a
claim requiring the same evidence as a numeric one. When a correction
lands, record the corrected **reasoning**, not just the corrected
code — the code fix prevents this bug, the recorded reasoning prevents
the next one in the family.

---

## 4. A baseline is only meaningful with the instrument that
established it

**Incident (T5, closure sweep).** The closure sweep reported **10**
`benchmark_runner` failures against a documented host baseline of
**6**. The four extra were
`fixtures/polyglot_mini/.../leap/leap_test.py::LeapYearTest::*` —
pytest collecting a *fixture exercise's own* test file, whose `leap.py`
is an unsolved starter stub and therefore fails by design.

The cause was the instrument, not the tree:

| file | `unittest` (`test*.py`) | `pytest` (`test_*.py`, `*_test.py`) |
| --- | --- | --- |
| `leap_test.py` | not collected | **collected** |
| `test_polyglot_adapter.py` | collected | collected |

The documented baseline was established with `unittest discover`; the
sweep script used pytest for convenience. Comparing across the two is
not like-for-like, and the discrepancy is exactly the collection
delta. Verified: `unittest discover` collects 1071 tests here and never
collects `LeapYearTest` at all.

The same trap applied to a second figure in the same record. The
session-analytics total was `421 passed, 6 skipped` under pytest in a
venv carrying `fastapi`+`httpx`, but `427 tests, OK, 37 skipped` under
the documented `unittest discover` on system python. Both are true;
neither is interpretable without its instrument, and the 31-test gap is
entirely CI-gated API tests that one environment can run and the other
cannot.

**The lesson.** A baseline is a measurement, and a measurement without
its instrument is not a number you can compare against. The failure is
*silent*: you do not get an error, you get a plausible total that is
wrong by exactly the delta between two collection rules — and the
natural next move is to explain away the difference, which converts an
instrument mismatch into a permanent, confident-sounding footnote.

**How to apply.** Before comparing anything to a baseline, state what
command produced the baseline and run *that* command. If the answer is
"I don't know how it was measured," the comparison is not available
yet — establish it or re-measure, but do not reconcile. When reporting
totals, name the instrument beside the number, especially where
environment changes what runs at all. And when an anomaly turns out to
be your own tooling, say so plainly: absorbing four unexplained
failures into a "6 baseline + 4 attributed" record would have read as
defensible while quietly establishing that the closure sweep and the
baseline were measured by different instruments.

**Related repo finding (not fixed here) — #268.** The tree carries no
`conftest.py`, no pytest configuration, and no `norecursedirs` /
`collect_ignore`, and no CI workflow invokes pytest — both smoke
workflows use `unittest discover`. Nothing therefore stops pytest from
collecting fixture starter stubs, and nothing warns a reader that those
failures are by design. Filed as its own issue and deliberately NOT
bundled into this increment's closure commit, which would have broken
one-logical-change and dirtied a diff that is exactly T5 scope.

---

## Applied here

- Lesson 1 produced a standing mutation class (source-substitution
  within an intact vocabulary) in
  `scripts/session_analytics/tests/test_routing_calibration.py`.
- Lesson 2 is why every round in
  `origin-alignment-2026-08-29-1700.md` records which mutations
  discriminated, including the ones that failed to and had to be
  rebuilt.
- Lesson 3 is why decision 7 in `plan.md` states the highest-tier rule
  *with its justification inline*, so a future reader can check the
  reasoning rather than trusting the adjective.
- Lesson 4 is why the closure sweep in
  `origin-alignment-2026-08-29-1700.md` records the COMMAND beside every
  total, and why the benchmark_runner leg was re-run under
  `unittest discover` rather than reconciled on paper.
