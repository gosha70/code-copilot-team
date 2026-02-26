# Alignment Maintenance Checklist

Lightweight routine to keep this repo aligned with agentic coding principles over time.

## Cadence

- Run **after any rule/skill/agent/template change**
- Run **before each release**
- Run a **monthly health pass** even if no major changes landed

## Required Verification

Run from repo root:

```bash
bash tests/test-generate.sh
bash tests/test-hooks.sh
bash tests/test-shared-structure.sh
```

Record the result counts in release notes or PR summary.

## Alignment Gates

1. **Instruction Layer Integrity**
   - Always rules remain concise and enforceable.
   - On-demand rule mappings are accurate for each adapter.
   - No stale references to removed docs/skills/tools.

2. **Verification Contract**
   - `verify-app` definitions include: `type`, `lint`, `tests`, `ui-smoke`, `console`, `network`, `visual`.
   - Output format includes explicit PASS/FAIL/SKIP statuses.

3. **Codex Build Mode Clarity**
   - Single-agent flow remains the default.
   - Optional team-mode behavior is documented as capability-dependent fallback.

4. **Template Quality**
   - Every template has architecture rules and a `team-review.md` command.
   - Web templates require runtime observability statuses in review output.

5. **Documentation Drift**
   - README test-count claims match current test outputs.
   - CONTRIBUTING test instructions remain current.
   - New governance docs are listed under shared documentation.

## Release Checklist

- [ ] All three test suites pass with zero failures
- [ ] README test counts are accurate
- [ ] CONTRIBUTING reflects current contributor workflow
- [ ] No adapter drift (`scripts/generate.sh` produces no unexpected diffs)
- [ ] At least one manual verification run performed for changed behavior

## Failure Handling

When a gate fails:

1. Capture exact failing assertion and file path.
2. Decide if failure is:
   - product regression
   - test expectation drift
   - stale local install data
3. Fix source of truth first (`shared/`, adapter, or setup script).
4. Re-run all three test suites before merging.
