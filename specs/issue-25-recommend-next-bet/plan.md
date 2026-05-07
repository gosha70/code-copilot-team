---
feature_id: issue-25-recommend-next-bet
spec_mode: none
justification: |
  Prompt-text edits to existing agents/skills/templates + new bash contract test.
  No novel data model, no auth surface, no runtime/migration changes, no new
  external dependencies. The risk surface is prompt drift across the canonical
  + adapter copies; tests/test-cooldown-recommendation.sh pins it (46 assertions).
  Acceptance mapping below ties each issue acceptance item to the file that
  satisfies it — that mapping is the spec for this kind of work.
status: approved
date: 2026-05-06
issue: 25
origin:
  issue: gosha70/code-copilot-team#25
  origin_claim: |
    "Sibling to #24. Same root cause — agents over-defer to the user when
    the project context already contains the answer — but it manifests at
    the cycle-0 → cycle-1 transition, not the pitch-shaping step. After
    cycle 0 shipped on AI-NEMO and the cooldown report was written, the
    session labelled cycle 1 as 'the natural next bet' in its own state
    table and then asked the user 'What's next?' anyway. The answer is in
    the question. The fix: cooldown-report and the Team Lead session-start
    behavior must surface a confident recommendation ('Recommend
    /bet 0001-foundation followed by /cycle-start 0001-foundation.
    Confirm?') instead of an open-ended 'What's next?'. Read ROADMAP.md +
    specs/pitches/*/ to identify the highest-priority shaped pitch; fall
    back to ambiguity-listing only when no clear ordering exists.
    Authorize-the-bet stays explicit; the change is recommend vs. ask."
  clarifications:
    - "ROADMAP.md is a downstream-project artifact (motivating example was
      AI-NEMO). Agents in this repo read ROADMAP.md from the consuming
      project's working directory if present and fall back to bet_status:
      shaped pitches when absent. Do NOT introduce ROADMAP.md into
      code-copilot-team itself."
    - "Surface the actionable /bet <id> + /cycle-start <id>. Confirm?
      prompt at /cooldown step 7 and in Team Lead session-start behavior
      (shared/skills/team-lead-efficiency, agent-team-protocol)."
    - "Add a bash contract test in tests/test-cooldown-recommendation.sh
      that pins the prompt text so future drift can't silently regress
      the recommendation behavior."
---

# Plan — Issue #25: recommend the next bet at cycle transitions

> Issue: https://github.com/gosha70/code-copilot-team/issues/25
> Sibling to #24 (already shipped in commit `2241584`).

## Context

After a cycle ships and `/cooldown` runs, the cooldown-report agent already
produces a "Recommended bets for next cycle" section in the report file —
but the *chat surface* (the agent's one-line output and `/cooldown` step 7)
ends with passive prose like *"Review the report. When ready, `/shape` new
pitches and convene the next betting table."*  That's the "what's next?"
moment the issue describes: the agent has already named the next bet inside
the report, but its closing message hands the decision back to the user
open-endedly instead of surfacing a concrete recommendation with the actual
commands to run.

The fix mirrors #24's pattern — same root cause (over-defer when the answer
is in context), same remedy (read project docs upfront, default to a
confident recommendation rather than an open question).

The Shape-Up authorization gate stays explicit — the user still has to run
`/bet` and `/cycle-start`. We change *how* the agent asks (concrete
recommendation with the exact commands) not *whether* it asks.

## Files to modify

1. **`claude_code/.claude/agents/cooldown-report.md`** — expand step 5
   (ranking inputs: ROADMAP.md if present in cwd, else rank shaped
   pitches by appetite-fit + scope clarity + circuit-breaker
   concreteness); replace the **Output** section with three conditional
   messages (1 winner / 0 shaped / >1 ambiguous); add a
   "Recommendation discipline" rule.

2. **`claude_code/.claude/commands/cooldown.md`** — replace the static
   step-7 next-step line with a conditional that surfaces whichever of
   the three messages the cooldown-report agent emitted, verbatim.

3. **`shared/templates/sdd/cooldown-report-template.md`** — extend the
   "Recommended bets for next cycle" section with a **"Next-bet
   recommendation"** subsection containing the actionable command pair.

4. **`shared/skills/team-lead-efficiency/SKILL.md`** — add a new section
   **"Cycle-Transition Handoff"** codifying the recommend-don't-ask rule
   for session start after a shipped cycle.

5. **`shared/skills/agent-team-protocol/SKILL.md`** — one-line
   cross-reference under §"Three-Phase Workflow" pointing at the new
   section in `team-lead-efficiency.md`. No duplication.

6. **`docs/shape-up-workflow.md`** — add a short subsection
   (≈10 lines) titled **"Cycle-transition handoff (recommend, don't
   ask)"** between *"Workflow at a glance"* and *"Frontmatter schema"*.

7. **`tests/test-cooldown-recommendation.sh`** *(new — guidance-contract
   test)* — bash test asserting that all four edited surfaces
   (agent prompt, command, template, skill) carry the required guidance
   phrases; plus a fixture smoke that the new template section validates
   cleanly. Documents at the top that it's a contract test pinning prompt
   text, not a runtime test of LLM behavior.

## Reuse — existing functions and patterns

- **Pitch ranking signals already present in cooldown-report step 5**
  (appetite, clarity, circuit breaker). The fix sharpens these into a
  recommendation, doesn't replace them.
- **`validate-pitch.sh`** at `scripts/validate-pitch.sh` and the consumer
  copy at `shared/templates/sdd/validate-pitch.sh` — used by the fixture
  smoke test.
- **Existing test harness style** — `tests/test-validate-pitch.sh` is the
  template for the new test.
- **#24's calibration commit `2241584`** — same shape (read project context
  first; suppress unnecessary questions). Agent-prompt edit, no code.

## Verification (end-to-end)

1. `bash scripts/validate-pitch.sh --all` — confirm existing pitches
   still validate.
2. `bash tests/test-cooldown-recommendation.sh` — new test, must pass.
3. `bash tests/test-validate-pitch.sh` — must pass unchanged.
4. `bash tests/test-shared-structure.sh` — must pass unchanged.
5. `bash scripts/check-origin-alignment.sh issue-25-recommend-next-bet`
   — must exit 0 or 1 (origin-confirmation circuit breaker).
6. Visual review of `docs/shape-up-workflow.md` rendering.

## Out of scope (per issue)

- Auto-betting without user confirmation. The user still runs `/bet` and
  `/cycle-start` explicitly — we only change the chat surface that
  precedes those commands.
- Multi-pitch parallel cycles or roadmap shapes the existing pitch list
  doesn't cover.
- Introducing ROADMAP.md into `code-copilot-team` itself. The agent reads
  it from the consuming project's cwd if present; absence is graceful.

## Acceptance mapping (from issue body)

| Issue acceptance item | Where it lands |
|---|---|
| `cooldown-report` inspects ROADMAP.md + pitches → concrete recommendation | File 1 (agent), step 5 + Output |
| Team Lead default-behavior at session start after a shipped cycle | File 4 (team-lead skill) + File 5 cross-ref |
| Regression test simulating post-cycle-N state, verifies confident `/bet` recommendation | File 7 (new test) |
| Doc note in `docs/shape-up-workflow.md` | File 6 |
