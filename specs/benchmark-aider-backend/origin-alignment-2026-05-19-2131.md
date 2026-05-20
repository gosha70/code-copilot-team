# Origin-Alignment Record — benchmark-aider-backend

Date: 2026-05-19 21:31 UTC
Gate: build-entry (B3 capture landed; B1/B2 reworked from ground truth; B3 verification record written)
Origin: gosha70/code-copilot-team#41 (issue body + 2026-05-19 user clarifications + Option-3 git-handling decision)
Supersedes: origin-alignment-2026-05-19-0641.md (B0-correction gate)

## Why this record exists

The 0641 record covered B0's flag-contract corrections (`--yes-always`,
no `--temperature`). The B3 maintainer capture then surfaced two more
classes of finding that required spec/code rework, all completed in a
single coherent commit alongside the B3 verification record. This
record covers that combined revision and the Option-3 git-handling
decision the user explicitly resolved.

## Findings caught by the B3 capture (and the corrective work)

1. **Three `_parse_transcript` regex bugs vs real Aider output.** B2's
   hand-authored fixtures matched the hand-authored regexes (synthetic
   fixture trap; saved as memory
   `feedback_recorded_capture_is_fixture_ground_truth`). The capture
   showed real shapes: `Tokens: 2.7k sent, 73 received.` (k/M suffix),
   `Model: … with diff edit format` (substring, not standalone
   `Edit format:` line), `Repo-map: using N tokens` (with leading
   `using`). Fix: replaced all three regexes with capture-derived
   versions; added `_parse_token_count` supporting plain ints, comma
   thousands, decimal `k`/`M`. Regenerated all three fixture files
   from the recorded transcript shape. The success fixture IS the
   recorded transcript verbatim; no-summary + zero-tokens are derived
   from it minimally. Added an inline-string parser test exercising
   the `Repo-map: using N tokens` branch (real form when not under
   `--no-git`) as a robustness guard.
2. **Worktree pollution: real aider creates `.git/` + `.gitignore` in
   a non-git dir despite `--no-gitignore`.** The capture's terminal
   `ls -la` confirmed the previous (pre-`--no-git`) run polluted the
   dir; the post-`--no-git` run produced `Git repo: none`,
   `Repo-map: disabled` and made no changes to the prior `.git/`. The
   user resolved (Option 3) to pin `--no-git` in the argv contract +
   file the git-with-cleanup follow-up
   [`#46`](https://github.com/gosha70/code-copilot-team/issues/46) with
   a 5%/5-task empirical decision criterion. Fix: added `--no-git` to
   the pinned argv in spec.md, plan.md, tasks.md, `aider.py`,
   `verification/aider.md`, and the README; strengthened the
   test_aider_backend.py fake-shim to simulate real Aider's
   `.git/`+`.gitignore` pollution when argv lacks `--no-git`, with a
   negative-control test that proves the shim DOES pollute without the
   flag (so the cleanliness assertions are now real regression guards,
   not no-ops).
3. **`_VERIFIED_VERSION` placeholder → `aider 0.86.2`** (the captured
   value, verbatim). The self-enforcing
   `test_verified_version_not_placeholder` was added (per the
   B2/B3-ordering fix landed in `1a49a4c`) — green from this commit
   forward, fails on any future bump that drops the real version back
   to the placeholder.
4. **`verification/aider.md` written** mirroring `codex.md` shape: the
   pinned version, the full recorded transcript verbatim, the observed
   `EXIT_CODE=0`, the flag contract table, the transcript-key→harness
   field table, the `--no-stream` display-only confirmation, the
   apples-to-apples caveat citing #46, and the enumerated 7-point
   reviewer checklist.

## Documented divergences (status)

- The four 0332/0641 divergences (mirror codex / verbatim model
  string / methodology-fidelity / leaderboard runnable-not-executed)
  are unchanged and stand.
- New Option-3 entry recorded in spec.md § Deviation from origin: the
  `--no-git` pin and the #46 follow-up. This is a documented,
  bounded, user-confirmed deviation — apples-to-apples gap is named,
  not hidden.

## Assessment

- Intent: unchanged from prior records. One PR fully closes #41.
- Out-of-scope list (bench.py / dogfood-subset / aider_polyglot
  adapter / leaderboard execution): intact, untouched.
- Parser + fixtures + verification record + recorded transcript are
  all mutually consistent — derived from the same canonical recorded
  run (the discipline `feedback_recorded_capture_is_fixture_ground_truth`
  exists to enforce).
- Test suite (per-module): 153 passed across aider/codex/claude_code/
  run_orchestration/compare; the new `test_verified_version_not_placeholder`
  + negative-control shim-pollution test are green; no collateral.

Verdict: aligned
Confidence: high
