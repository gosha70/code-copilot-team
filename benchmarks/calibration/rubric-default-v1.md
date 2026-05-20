# Rubric v1 (default) — LLM-Judge prompt template + dimensions

The judge rates four dimensions on a 1–5 scale, one rating per
dimension per attempt. Ratings are integers in `{1,2,3,4,5}` —
enforced by `scripts/benchmark_runner/judge/contracts.py`
`DimensionRating.__post_init__` (out-of-range values are rejected
at construction, before `judge.json` is written). The judge also
produces a free-text explanation per dimension.

## Dimensions

### 1. `idiomaticity`

How idiomatically the code is written for its language: naming
conventions, control flow, standard-library use, paradigm fit
(e.g. Pythonic vs. transliterated-from-Java; idiomatic-Go vs.
"clever"-Go; Rust ownership patterns vs. lifetimes-fighting).
Independent of correctness — code that is wrong but idiomatic
still rates high here; code that is right but cramped or
non-native rates low.

**1 — Anti-idiomatic.** Reads like another language transliterated;
ignores standard library; bespoke loops where comprehensions /
streams / iterators would be obvious; naming violates language
conventions throughout.

**2 — Awkward.** Several local anti-idioms; a few stdlib opportunities
missed; naming partially off. A native reader would notice and
rephrase.

**3 — Adequate.** Idiomatic where easy; awkward where not. A native
reader would accept it but flag 2–3 specific spots in review.

**4 — Idiomatic.** Naming, control flow, and library use match the
language's conventions. A native reviewer would not call out
specific phrasing.

**5 — Exemplary.** Reads like the language's standard library
or its most-respected open-source projects. Any deviation from
the obvious idiom is a deliberate, defensible choice.

### 2. `error_handling`

How the code treats failure: input validation, exception
discipline, partial-failure recovery, error propagation
contracts, never-silently-swallow behavior. Language-aware:
Rust `Result`, Python `try/except`, Go `if err != nil`, Java
`throws` — the right shape for the language.

**1 — Absent / dangerous.** No validation; bare `except:`; `if err
!= nil { _ = err }`; panics on bad input; silently returns wrong
results on edge cases.

**2 — Weak.** Catches too broadly; loses original error context;
ignores some obvious failure modes (empty input, type
mismatch, IO error).

**3 — Functional.** Handles common failure modes; some specificity
in exception types or error returns; minor leaks (over-broad
catch in one spot, unchecked cast in another).

**4 — Thoughtful.** Specific exception/error types throughout;
errors carry context up; documented failure modes match
implemented behavior; input validation present where it matters.

**5 — Defensive without being paranoid.** Every failure mode the
code can produce has a clear path (handle, propagate with
context, or document as panic-equivalent). No silent failures.
Tests would prove out the error paths.

### 3. `test_thoughtfulness`

Quality of the tests the model wrote or modified, where
applicable. Coverage of edge cases, test-naming clarity, AAA
shape (arrange-act-assert), independence of test cases, mock
discipline.

**Null is NOT for ordinary absence.** If the task gave the model
a meaningful opportunity to add or modify tests and it did not,
that is a low-quality signal — rate `1`, not `null`. `null` is
reserved for the narrow case where the task structurally does
not afford a test contribution: the benchmark provides the test
suite and the task instructions explicitly say the model must
not modify tests (e.g. Aider Polyglot's "solve so that the
provided tests pass — do not edit the test file" framing). The
judge writes a one-line explanation justifying `null` in those
cases. Anything else — model produced no tests on a task where
adding tests was natural; model edited tests in trivial ways;
model wrote a single tautological test — rates `1`.

**1 — Tests absent or token.** No tests on a task where adding
tests was natural; or a single happy-path test that always
passes; or a tautological assertion (`assert True`, `assertEqual(x, x)`).

**2 — Tests present but shallow.** One or two cases, only the
golden path; no boundary / failure tests; cases are coupled.

**3 — Tests cover the obvious.** Golden path + one boundary
case; case names are descriptive; cases are independent.

**4 — Tests cover the obvious + a few non-obvious.** Boundary
cases (empty, single-element, max-size); failure cases
(invalid input, IO failure); test names communicate intent.

**5 — Tests as a specification.** A new contributor could
understand the function's contract from the test suite alone.
Edge cases enumerated systematically; failure modes asserted;
no test depends on another test's order.

### 4. `security_hygiene`

Defensive posture against the OWASP-style failure modes the
code's surface area exposes. Language- and task-aware: a string
function's surface is different from a web handler's. Includes
SQL injection (parameterized queries), command injection
(no shell concatenation), path traversal, unsafe deserialization,
secret-handling in logs, integer-overflow surface, and obviously
"avoid `eval()`-class" patterns.

**1 — Actively dangerous.** Concatenates user input into shell /
SQL / paths; logs raw credentials; uses `eval` / `pickle.loads`
on untrusted input; trusts file uploads without validation.

**2 — Naive.** One or more of the above in lower-impact paths;
no obvious malice but a hostile input would land.

**3 — Adequate for the surface.** Standard tooling used where
present (parameterized queries, `pathlib`, `shlex`); no shell
concatenation; no obvious mishandling. Doesn't go beyond.

**4 — Defensive.** Input validated at boundaries; secrets never
logged; least-privilege where the task allows; explicit
treatment of untrusted input.

**5 — Hostile-input-ready.** Every external input is treated as
hostile; failure modes are documented; the code would pass a
focused security review without rewrites.

## When a dimension does not apply

`null` is reserved for cases where the dimension is
**structurally inapplicable** to the attempt, NOT for cases of
ordinary absence (e.g. model produced no test code on a task
that allowed tests — that is `1`, not `null`; model produced
unsafe code on a task with an external-input surface — that is
`1`, not `null`).

Examples of structural inapplicability:

- `test_thoughtfulness` on a task whose instructions explicitly
  forbid editing tests (the benchmark owns the test suite, e.g.
  Aider Polyglot's "solve so that the provided tests pass —
  do not edit the test file" framing). The model had no
  opportunity to demonstrate test thoughtfulness.
- `security_hygiene` on a task that has no external-input
  surface and no security-relevant operations (pure-string
  algorithm with no IO, no parsing, no shell, no SQL, no
  deserialization). There is nothing for a defensive posture
  to defend against.

In every other case — the dimension applies and the rating is
1–5. The judge writes a one-line explanation justifying `null`
when it is recorded.

`null` ratings are excluded from that dimension's calibration
sample (a rating cannot agree or disagree with a non-rating);
they do not count against the judge's Spearman score. But they
are still LABELED records in the calibration set — see
`benchmarks/calibration/<name>.jsonl` schema below: every
(run_path, dimension) pair is labeled, with `rating: null +
explanation` when the dimension is structurally inapplicable.

## Prompt template (sent to the judge LLM)

```
You are an expert code reviewer rating one attempt at solving a
benchmark task. Rate the model's work on four dimensions on a
1-5 integer scale. Respond in strict JSON matching the schema
below. Do not include any text outside the JSON.

Task: {task_id} ({benchmark_id})

Prompt the model received:
---
{prompt}
---

Diff the model produced (against the prepared starter):
---
{diff}
---

Verify-step output (what the deterministic harness measured):
---
{verify_output}
---

Rubric:

{rubric_dimensions_block}

When a dimension does not apply to this attempt, set its rating
to null and use the explanation to say why. Never coerce a
non-applicable dimension to a numeric rating.

Output JSON only:
{
  "ratings": {
    "idiomaticity":         { "rating": <1-5 or null>, "explanation": "<one paragraph>" },
    "error_handling":       { "rating": <1-5 or null>, "explanation": "<one paragraph>" },
    "test_thoughtfulness":  { "rating": <1-5 or null>, "explanation": "<one paragraph>" },
    "security_hygiene":     { "rating": <1-5 or null>, "explanation": "<one paragraph>" }
  }
}
```

`{rubric_dimensions_block}` is rendered at prompt-format time by
the judge from this file's "Dimensions" section above (anchor
sentences only, one paragraph per dimension), so a rubric edit
takes effect with no judge code change.

## Versioning

This is rubric v1. Any edit to the dimension list, anchor
sentences, or prompt template MUST go to a new
`rubric-default-vN.md`. Calibration reports record the rubric
version they were generated against; reports built against the
old rubric remain readable.

## Out of scope for v1

- Per-language sub-rubrics (a "Python idiomaticity" rubric
  separate from a "Rust idiomaticity" rubric). v1 uses one
  rubric across all languages; the judge LLM is responsible
  for language-aware anchoring within each dimension.
- Reviewer-vs-reviewer agreement bounding (a second human
  reviewer overlapping ≥10% of the corpus). Useful for
  bounding the achievable Spearman ceiling, but adds labeling
  cost and is deferred.
- Cost / performance dimensions (token usage, elapsed time).
  These are deterministic signals, not judge-rated; they
  remain in `score.json` / `stats.json` / the deterministic
  report block.
