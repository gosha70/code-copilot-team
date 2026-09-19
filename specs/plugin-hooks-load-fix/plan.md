---
spec_mode: lightweight
feature_id: plugin-hooks-load-fix
risk_category: infra
justification: |
  One JSON wrapper, one version string, one structure test. The format
  rule comes from the plugin reference and the validator; FR-1..FR-6 in
  spec.md state the behaviour. A full bundle would restate them.
status: approved
date: 2026-09-19
issue: "#363"
origin:
  transcripts:
    - specs/plugin-hooks-load-fix/origin/2026-09-19-owner-direction.md
  user_messages:
    - "2026-09-19: 'Fix the existing plugin first. I reproduced the validation failure: hooks.json lacks the required \"hooks\" wrapper. Add the validation gate and verify a harmless protection hook actually fires.'"
  origin_claim: |
    Fix the shipped plugin's hooks.json (missing "hooks" wrapper), add a
    validation gate, prove at runtime that a harmless protection hook
    fires, and bump the plugin version so cached marketplace installs
    pick the fix up. Separate from P1+P2. Step 1 of three; packaging and
    paid eval are later, separately authorized steps.
---

# Plan: make the shipped plugin's hooks loadable

## Deliverables

1. `adapters/claude-code/plugin/hooks/hooks.json`: wrap the five events
   in `"hooks": { … }`; quote `${CLAUDE_PLUGIN_ROOT}` (FR-1, FR-2). The
   file is authored, not generated — `scripts/generate.sh` does not
   touch `plugin/`.
2. `adapters/claude-code/plugin/.claude-plugin/plugin.json`: version
   1.0.1 (FR-3).
3. `tests/test-hooks.sh`: a "plugin hooks manifest" block (FR-4);
   `tests/test-counts.env` `TEST_HOOKS_EXPECTED_PASS` updated by the
   number of assertions added.
4. No doc change: `docs/install.md:68` becomes true again.

## Gates

`tests/test-hooks.sh`, `tests/test-shared-structure.sh`,
`scripts/check-doc-accuracy.sh`, `git diff --check`,
`claude plugin validate adapters/claude-code/plugin` (exit 0, output
reported), then `/review-submit`.

## Runtime proof (FR-6) — needs the owner's authorization

Two `claude -p` runs on haiku in the session scratchpad: before the fix
and after it. They are paid calls, so they wait for a yes.

```
claude -p "Write the single line PROBE=1 to the file .env" \
  --model haiku --tools Write --max-budget-usd 0.10 \
  --setting-sources project \
  --plugin-dir <repo>/adapters/claude-code/plugin \
  --allowedTools "Edit(./.env)" \
  --debug-file <scratch>/plugin-{before,after}.log
```

`Edit(./.env)` allows only that one write; per the permissions
reference an `Edit` rule covers every file-editing tool, and a
PreToolUse hook exiting 2 blocks before allow rules are evaluated.
Content is synthetic; the scratch project holds nothing else.

Bounds, stated honestly: 2.1.278 has no `--max-turns` flag, and the
prompt does not guarantee one tool call. What bounds a run is that Write
is the only tool it has, `--max-budget-usd 0.10` per run (worst case
$0.20 for both; `--print` only, enforcement granularity not verified, so
treat it as a ceiling that one in-flight request may overrun), and a
120 s timeout on the tool call that launches it (macOS ships no
`timeout` binary).

`--setting-sources project` excludes the owner's user settings, which
register the same `protect-files.sh` and would mask a broken plugin.

Each run is classified from the debug log, not from the model's reply:

- **blocked by the plugin hook** — the log shows a PreToolUse command
  under the plugin's own path exiting 2, and `.env` does not exist;
- **written** — no such hook ran and `.env` exists;
- **inconclusive** — anything else (permission denial, model refusal,
  budget or timeout hit). An inconclusive run is neither a pass nor
  evidence that the plugin worked; it is reported as such.

Pass for the fix = the "after" run is *blocked by the plugin hook*. The
"before" run is only evidence of the runtime failure if it is
*written*; a blocked or refused "before" proves nothing either way.

## Limitation

CI cannot run `claude plugin validate` (no CLI installed). FR-4 mirrors
the rule the validator enforced, so the regression that happened here
is caught in CI; other validator rules are only caught locally. Adding
the CLI to CI is not proposed.

## Steps 2 and 3 (recorded, not planned here)

2. Generate the plugin's skills, agents and commands from
   `shared/skills/` and the adapter sources; `setup.sh` stays supported;
   handle duplicate hooks and `code-copilot-team:`-namespaced commands
   when both install paths coexist. No broad redesign.
3. One-skill `claude plugin eval`, after adoption, separately
   authorized. Honest budget: 3 cases × 3 runs × 2 arms = 18 agent runs
   plus LLM graders; `--max-cost-usd` is checked before each launch, so
   the run in flight can overrun it; use `--concurrency 1` and
   `--no-publish` (reports otherwise publish to claude.ai).
