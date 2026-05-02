Update a scope's status on the hill chart of the active pitch.

Usage: `/hill <scope> <up|down|done> [--force]`

## Steps

### 1. Parse arguments

- `<scope>` — scope id (`S1`, `S2`, ...) as it appears in `pitch.md` and `hill.json`.
- `<up|down|done>` — target status. Maps to `uphill`, `downhill`, `done`.
- `--force` (optional) — required to move a scope from `done` back to `uphill` (treats the work as not-actually-done).

### 2. Find the active pitch

Scan `specs/pitches/*/pitch.md` for `bet_status: building`.

- 0 matches → refuse with: "No active cycle. Run `/cycle-start <pitch-id>` first."
- >1 match → refuse with: "More than one pitch is building (\<list\>). Resolve before running `/hill`."
- exactly 1 → that's the active pitch.

### 3. Verify scope and load hill.json

Read `specs/pitches/<active-pitch>/hill.json`. The named scope must exist. Refuse otherwise (likely a typo or the pitch was changed without re-running `/cycle-start`).

### 4. Validate the transition

| Current → Target | Allowed |
|------------------|---------|
| uphill → downhill | yes |
| uphill → done | yes (skipping downhill is unusual but legal) |
| downhill → done | yes |
| downhill → uphill | yes (you discovered an unknown) |
| done → downhill | yes (work was prematurely declared done) |
| done → uphill | requires `--force` |

### 5. Update hill.json

- Set the scope's `status` to the target.
- Set the scope's `last_updated` to ISO-8601 now.
- Set the file root `updated_at` to ISO-8601 now.

### 6. Report

Print:
- Pitch id, scope id and name
- Transition (e.g. `uphill → downhill`)
- Current state of all scopes (one-line summary like `S1=done S2=downhill S3=uphill`)
- If all scopes are `done`: "All scopes complete. Run `/cooldown` to close the cycle."
