Shape a rough idea into a Shape-Up pitch via the `pitch-shaper` agent.

Usage: `/shape <topic>`

## Steps

### 1. Parse arguments

The `<topic>` is the rough idea — a one-line description (e.g. `add streaming responses to the chat API`). If absent, ask the user for one.

### 2. Invoke `pitch-shaper`

Use the Agent tool with `subagent_type: pitch-shaper`. Pass the topic and any additional context the user has volunteered.

The pitch-shaper will:
- Pick the next `NNNN-slug` pitch id under `specs/pitches/`
- Ask clarifying questions (appetite, problem, solution shape, no-gos, circuit breaker)
- Decompose into 3–7 scopes
- Write `specs/pitches/<id>/pitch.md` from `~/.claude/templates/sdd/pitch-template.md`
- Set `bet_status: shaped`
- Validate via `~/.claude/templates/sdd/validate-pitch.sh`

### 3. Report to user

Once pitch-shaper returns, print:
- The new pitch path
- Frontmatter summary (id, appetite, scope count, circuit breaker)
- Validator confirmation
- Next step: "Run `/bet <pitch-id>` to lock this as a bet for the next cycle, or refine via direct edits."

## Notes

- This command does not lock the pitch as a bet. `bet_status: shaped` means "ready for the betting table" — not yet committed.
- A pitch can sit in `shaped` indefinitely. Only `/bet` advances to `bet_status: bet`.
- Re-running `/shape` for the same topic produces a NEW pitch with a new id — it does not overwrite. Edit the existing pitch directly if you want to refine.
