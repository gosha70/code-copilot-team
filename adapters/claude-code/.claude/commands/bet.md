Lock a shaped Shape-Up pitch as a bet for the next cycle.

Usage: `/bet <pitch-id>`

## Steps

### 1. Parse arguments

`<pitch-id>` is the directory name under `specs/pitches/` (e.g. `0001-shape-up-support`). If absent, list pitches with `bet_status: shaped` and ask which to bet on.

### 2. Verify state

Read `specs/pitches/<pitch-id>/pitch.md`. Required:
- `bet_status: shaped`. Refuse if `shaping` ("not ready"), `bet`/`building`/`shipped` ("already bet"), or `shelved` ("re-shape first").
- All required frontmatter fields populated (run `bash ~/.claude/templates/sdd/validate-pitch.sh --pitch-id <pitch-id>` first; refuse on validator failure).

### 3. Determine cycle number

Find the highest existing `cycle:` value across `specs/pitches/*/pitch.md`. The new cycle number is that + 1, zero-padded to 2 digits (`01`, `02`, ...). If no existing cycles, start at `01`.

Confirm with the user before writing.

### 4. Update frontmatter

In `specs/pitches/<pitch-id>/pitch.md`:
- `bet_status:` from `shaped` → `bet`
- `cycle:` set to the determined value (e.g. `"01"`)

### 5. Append to bet log

Add a row to the `## Bet log` table at the bottom:

```
| <YYYY-MM-DD> | bet | Bet for cycle NN. |
```

### 6. Re-validate

Run `bash ~/.claude/templates/sdd/validate-pitch.sh --pitch-id <pitch-id>`. **Refuse if it fails** — restore the previous frontmatter and tell the user.

### 7. Report

Print:
- Pitch id and title
- New `bet_status` and `cycle`
- Validator confirmation
- Next step: "Run `/cycle-start <pitch-id>` to begin the cycle and create the hill chart."
