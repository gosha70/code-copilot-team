Begin a cycle for a bet pitch — initializes the hill chart and transitions the pitch to `building`.

Usage: `/cycle-start <pitch-id>`

## Steps

### 1. Parse arguments

`<pitch-id>` is the directory name under `specs/pitches/`. If absent, list pitches with `bet_status: bet` and ask.

### 2. Verify state

Read `specs/pitches/<pitch-id>/pitch.md`. Required:
- `bet_status: bet`. Refuse if any other status.
- `cycle:` non-empty.

Run `bash ~/.claude/templates/sdd/validate-pitch.sh --pitch-id <pitch-id>`. Refuse on validator failure.

### 3. Parse scopes

From `pitch.md`, extract every `### S<N>: <name>` heading under the `## Scopes` section. Build the scope list as `[{id: "S1", name: "..."}, ...]`.

Refuse if fewer than 3 or more than 7 scopes are found — that's a malformed pitch.

### 4. Generate hill.json

Write `specs/pitches/<pitch-id>/hill.json` matching the schema in `~/.claude/templates/sdd/hill-chart.json`:

```json
{
  "pitch_id": "<pitch-id>",
  "cycle": "<NN>",
  "updated_at": "<ISO-8601 now>",
  "scopes": [
    {
      "id": "S1",
      "name": "<scope name from pitch.md>",
      "status": "uphill",
      "last_updated": "<ISO-8601 now>"
    }
  ]
}
```

All scopes start at `uphill`. Refuse to overwrite an existing `hill.json` — that means the cycle was already started; the user should `/hill` to update existing scopes, not re-init.

### 5. Update pitch frontmatter

In `pitch.md`:
- `bet_status:` from `bet` → `building`

### 6. Append to bet log

Add a row: `| <YYYY-MM-DD> | building | Cycle NN started; hill chart initialized. |`

### 7. Re-validate

`bash ~/.claude/templates/sdd/validate-pitch.sh --pitch-id <pitch-id>`. Refuse if it fails — restore prior state.

### 8. Report

Print:
- Pitch id, title, cycle number
- Number of scopes initialized to `uphill`
- Path to the new `hill.json`
- Next step: "Use the `scope-executor` agent on a scope to begin work, or `/hill <scope> down` to mark a scope mechanical."
