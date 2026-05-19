# Origin-Alignment Record — benchmark-aider-backend

Date: 2026-05-19 03:32 UTC
Gate: plan-approval (Phase A, pre-build)
Origin: gosha70/code-copilot-team#41 (issue body + 2026-05-19 user clarifications)

## What the user asked for

Issue #41: add the `aider` copilot backend mirroring the codex backend
(#33) — backend code + a separate verification record (pinned `aider
--version` + a recorded headless transcript) + a recorded-transcript
test (no live CLI) + provider env recorded-never-set + README; plus
the apples-to-apples Aider-vs-Aider Polyglot leaderboard comparison.
One PR that fully closes #41 (one-PR-per-issue rule; no
partial/phased delivery).

## What the spec/plan commit to

A new `backends/aider.py` mirroring `codex.py`; a one-line
`_register.py` change; `verification/aider.md` mirroring `codex.md`
(real pinned version + real recorded transcript); a fake-CLI
recorded-transcript test (no live CLI/network) plus a
worktree-cleanliness regression; a README Aider section + the
documented 9-invariant apples-to-apples maintainer procedure. No
harness orchestration/scoring change (D2 heartbeat + D5 timeout
classification inherited unchanged from `run.py`). One PR, fully
closes #41.

## Divergences (documented, user-confirmed 2026-05-19)

Four clarifications were taken with the user; none rescopes a
deliverable or breaches the issue:

1. **Mirror codex exactly; bench untouched.** `aider` is not
   bench-addressable (codex isn't either; #41 never mentions bench).
   The "bench supports non-claude-code backends" idea is explicit
   future scope the user files post-#41 — OUT here. (Corrects an
   over-reach in the original task framing, retracted by the user.)
2. **Verbatim model-string passthrough** — `<provider>/<model>`
   straight to `--model`, no aliasing (mirrors codex).
3. **Methodology-fidelity principle** — pin only headless/hygiene
   flags; leave `--map-tokens/--edit-format/--temperature` at Aider's
   defaults (matches Aider's leaderboard) and record resolved values.
   An earlier draft's `--map-tokens 0` "for determinism" was reopened
   on review and removed: it would systematically depress numbers vs
   Aider's published leaderboard — a buried apples-to-apples
   regression. This is methodology *fidelity*, the opposite of a
   deviation.
4. **Leaderboard = runnable path + invariants, not executed in the
   PR** (maintainer-scale, like the dogfood Gate);
   `dogfood-subset.txt` `*/leap` staleness left as a documented
   caveat, not fixed (scope discipline).

Forced codex-template departures (recorded in spec.md § Deviation +
the verification record): text transcript not JSONL; best-effort/None
token metrics; `--message-file` not stdin; env-presence-boolean
provider routing; extra `--no-auto-commits/--no-dirty-commits/
--no-gitignore` hygiene flags (forced by `run.py` `_write_diff`
excluding only `.venv`); empirically-pinned exit codes. All are
tool-forced structural mirrors, not scope changes.

## Outstanding (not a divergence)

The pinned `aider --version` + recorded transcript are captured at
Phase-B start on the maintainer machine (need the real CLI); Phase A
records the procedure and the verification-record skeleton.

## Assessment

- Out-of-scope list (bench.py, dogfood-subset, aider_polyglot adapter,
  leaderboard execution, live CLI in tests): intact, reproduced as
  binding Constraints. No creep.
- Acceptance criteria: every #41 deliverable maps to a Success
  Criterion and a task.
- Harness orchestration/scoring: untouched.

Verdict: aligned
Confidence: high
