---
spec_mode: none
feature_id: setup-playwright-flag
risk_category: bugfix
justification: |
  Non-security bug fix (#212): forward a flag the root installer silently
  dropped, and stop the parser swallowing unknown flags as a project dir.
  Installer argument handling plus a smoke test; no new surface.
status: approved
date: 2026-08-08
origin:
  issue: https://github.com/gosha70/code-copilot-team/issues/212
  origin_claim: |
    Bug #212: "setup.sh silently ignores --playwright (root neither forwards
    nor rejects)". The root parser's *) branch assigns an unknown first arg
    to PROJECT_DIR, so --playwright becomes a phantom project dir; the
    Claude adapter is then invoked WITHOUT it, although the adapter supports
    it and two docs recommend `setup.sh --playwright`. Users following the
    docs believe Playwright was installed when it was not. Fix: forward it,
    or reject nonzero with a pointer to the adapter path — never silently
    ignore.
---

# Plan: never silently ignore an installer flag (#212)

Both remedies the issue offers, applied where each is correct:

1. **Forward** `--playwright` to the claude-code adapter — the docs
   recommend the root command, and the adapter already implements the flag.
   Works alongside `--sync`.
2. **Reject**, nonzero and with guidance, when the flag cannot reach an
   adapter that supports it (`--codex --playwright`). Forwarding it nowhere
   would be the same silent no-op one layer deeper.

## Review round 2 (user P1 + P2)

Both were in the first cut, and both were failures of the same kind — a
claim not checked against the real thing:

- **P1: the issue's own acceptance command still no-opped.** With no tools
  detected, `setup.sh --playwright` reached the "No tools detected" branch
  and exited **0** before any playwright check. The bug survived one branch
  further along than where I fixed it. It now exits nonzero naming both
  ways to run it.
- **P2: `--sync --playwright` never worked.** The claude-code adapter
  explicitly rejects that pair, but the wrapper forwarded it happily — so
  the run regenerated everything and then failed downstream. My test proved
  only that the flags were *forwarded*, because it used an echo-only stub
  with no contract of its own. The wrapper now rejects the pair up front
  with the adapter's wording, and the suite checks the REAL adapter's
  rejection so the two cannot drift.

Lesson recorded: a stub proves plumbing, never a contract. Where the claim
is "this combination works", the test has to reach the thing that decides.

## The class defect

The reported bug was one symptom of the `*)` branch: **any** unknown
argument became `PROJECT_DIR`. A misspelled `--claud-code` would have run an
auto-detected installation against a phantom directory without a word. Now
anything starting with `-` is a flag by definition and exits nonzero naming
itself; a positional project dir still works exactly as before.

`--playwright` is also documented in `--help`, which is where a user looks
after being told the flag exists.
