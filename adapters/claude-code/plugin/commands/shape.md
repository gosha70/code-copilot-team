Shape a rough idea into a Shape-Up pitch via the `pitch-shaper` agent.

Usage: `/shape <topic>`

## Steps

### 1. Parse arguments

The `<topic>` is the rough idea — a one-line description (e.g. `add streaming responses to the chat API`). If absent, ask the user for one.

### 2. Invoke `pitch-shaper`

Use the Agent tool with `subagent_type: pitch-shaper`. Pass the topic and any additional context the user has volunteered.

The pitch-shaper will:
- Pick the next `NNNN-slug` pitch id under `specs/pitches/`
- List the genuinely open decisions (appetite, problem, solution shape, no-gos, circuit breaker) in the pitch's `## Open decisions` section, each with a default, and shape the pitch on those defaults. It cannot ask the owner itself: Claude Code removes `AskUserQuestion` from every subagent (#407).
- Decompose into 3–7 scopes
- Write `specs/pitches/<id>/pitch.md` from `${CLAUDE_PLUGIN_ROOT}/templates/sdd/pitch-template.md`
- Set `bet_status: shaped`
- Validate via `${CLAUDE_PLUGIN_ROOT}/templates/sdd/validate-pitch.sh`

### 3. Ask the open decisions (main session)

Read the new pitch's `## Open decisions` section. If it lists any `D<n>` entries, ask them now with `AskUserQuestion` — this command runs in the main session, where the tool exists — offering the agent's default as the first option. Then record each answer in the pitch: replace the default with the decision (`D<n>: <question> — decided: <answer> (<date>)`), update any scope, no-go or circuit-breaker text the answer changes, and re-run `${CLAUDE_PLUGIN_ROOT}/templates/sdd/validate-pitch.sh`. If the section is empty or absent, say so and move on.

### 4. Report to user

Once the decisions are recorded, print:
- The new pitch path
- Frontmatter summary (id, appetite, scope count, circuit breaker)
- The decisions asked and answered in step 3, or "no open decisions"
- Validator confirmation
- Next step: "Run `/bet <pitch-id>` to lock this as a bet for the next cycle, or refine via direct edits."

## Notes

- This command does not lock the pitch as a bet. `bet_status: shaped` means "ready for the betting table" — not yet committed.
- A pitch can sit in `shaped` indefinitely. Only `/bet` advances to `bet_status: bet`.
- Re-running `/shape` for the same topic produces a NEW pitch with a new id — it does not overwrite. Edit the existing pitch directly if you want to refine.
