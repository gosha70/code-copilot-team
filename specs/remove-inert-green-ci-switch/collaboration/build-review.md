---
feature_id: remove-inert-green-ci-switch
date: 2026-10-29
status: final
phase: build
mode: review
subject_provider: claude
peer_provider: deepseek
peer_profile: deepseek
runner_fingerprint: ae8dc147cf1264834bab35d116b6ab96b06618f438763cde3a90621d78036dba
verdict: PASS
blocking_findings_open: 0
target_ref: fix/remove-inert-green-ci-switch
rounds_completed: 1
attempt_count: 1
bypass: false
---

# Peer Review: remove-inert-green-ci-switch — Build Phase

**Reviewer**: deepseek
**Scope**: both
**Rounds**: 1
**Verdict**: PASS

## Summary

The change removes the inert `merge.require_green_ci` key from the shipped template and driver, adds a correction note to the spec/plan, and adds tests asserting the key is gone from the template and driver while legacy configs still validate. The change is small, well-scoped, and the test coverage for backward compatibility is a good touch. A few minor issues around test robustness and documentation consistency are worth noting.

## Findings

- [note] f-abd881d4: The assertion greps the template for `require_green_ci` but the template path is resolved via `$SCRIPT_DIR/../shared/templates/sdd/automation-template.json`; if `$SCRIPT_DIR` is not the tests dir this could silently pass on a missing file (grep -c on missing file returns 0 with ` (tests/test-auto-build-loop.sh)
- [note] f-ef03064e: The new legacy-config test uses `cfg_set` to write a config with `require_green_ci:true` and asserts validation passes, but does not assert that the driver still runs correctly with that key present (only that the validator accepts it). The subsequent `MERGE_CFG` fixture covers runtime, but the new test's stated purpose ("legacy configs keep working") is only half-proven by validation alone. (tests/test-auto-build-loop.sh)
- [note] f-667dfbf9: The correction note says requirements "overstate what shipped" but does not mark which specific requirement lines are affected; a reader scanning the requirements below has no inline signal that e.g. the `require_green_ci` mention in the profile ladder is now historical. (specs/auto-build-loop-merge-profile/spec.md)
- [note] f-30ce180d: Same as spec.md: the correction is a top-of-file blockquote with no inline markers on the affected plan steps, so a reader following the plan linearly will still read the "delegated" language as current. (specs/auto-build-loop-merge-profile/plan.md)
- [note] f-2863486f: The parenthetical hardcodes a date ("2026-10-29") in user-facing skill docs; if the date is wrong or the change is reverted/re-landed, the doc drifts. Also the date is in the future relative to typical review timing, which may confuse readers. (shared/skills/auto-build-loop/SKILL.md)
- [note] f-6d4534ee: Removing the assignment is correct, but confirm no downstream code (including sourced helpers or `set -u` paths) referenced `$MERGE_REQUIRE_GREEN_CI`; the diff shows only the assignment removed, and the new test greps the driver for the symbol, which covers this — noting for completeness that the grep test is the safety net. (scripts/auto-build-loop.sh)
- [note] f-45499673: Count bumped from 1241 to 1244 (+3), matching the three new assertions (two `assert_eq` + one `assert_exit`). Consistent with docs/repo-structure.md update. Good. (tests/test-counts.env)
