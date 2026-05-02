Close out a cycle — invoke `cooldown-report` and finalize the active pitch's bet status.

Usage: `/cooldown`

## Steps

### 1. Find the active pitch

Scan `specs/pitches/*/pitch.md` for `bet_status: building`.

- 0 matches → no cycle to close. Continue to step 2 with `active_pitch_id=""`.
- >1 match → refuse. Resolve first.
- exactly 1 → that's the active pitch.

### 2. Determine the cycle number

- If an active pitch was found in step 1: read its `cycle:` frontmatter (e.g. `01`). This is the cycle being closed.
- If no active pitch: list `specs/retros/cycle-NN.md` files and pick the highest `NN`. That's the most recent closed cycle; cooldown reports against it. Confirm with the user before proceeding. If `specs/retros/` is empty or does not exist, refuse — there is no cycle to report on.

### 3. Decide the bet outcome

If no active pitch was found in step 1, skip steps 3–5 and jump to step 6 (cooldown-report only — no frontmatter to mutate).

Otherwise read `hill.json` for the active pitch:

- All scopes `done` → suggest `shipped`.
- Some `done`, some not → suggest `shipped` (partial) or `shelved`. Ask the user.
- No scopes `done` → suggest `shelved`. Ask the user to confirm.

Use AskUserQuestion: "Was the bet `<pitch-id>` shipped or shelved?" — `shipped | shelved`.

### 4. Update pitch frontmatter

- `bet_status:` from `building` → `shipped` or `shelved` per user's choice.

Append to bet log: `| <YYYY-MM-DD> | <shipped|shelved> | Cycle NN closed. <one-line summary of hill final state>. |`

### 5. Re-validate

Run `bash ~/.claude/templates/sdd/validate-pitch.sh --pitch-id <pitch-id>`. Refuse if it fails — restore previous state.

### 6. Invoke `cooldown-report`

Use the Agent tool with `subagent_type: cooldown-report`. Pass the cycle number that just finished.

The agent will:
- Summarize bug fixes from `git log` since cycle end
- List pitches shaped during cooldown
- Recommend candidates for the next betting table
- Write `specs/retros/cooldown-after-<NN>.md`

### 7. Report

Print:
- Pitch outcome (`shipped` or `shelved`)
- Path to the cooldown report
- Next step: "Review the report. When ready, `/shape` new pitches and convene the next betting table."
