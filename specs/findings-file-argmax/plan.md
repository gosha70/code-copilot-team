---
spec_mode: none
feature_id: findings-file-argmax
risk_category: bugfix
justification: |
  Non-security bug fix (#209): pass the reviewer's output to jq by file
  instead of argv, check the write's exit status, and refuse to compose a
  fix prompt from an unusable findings file. No new surface.
status: approved
date: 2026-08-08
origin:
  issue: https://github.com/gosha70/code-copilot-team/issues/209
  origin_claim: |
    Bug #209: "jq ARG_MAX destroys findings-round-N.json — a real review is
    silently written as an empty file, starving the fix session". The runner
    passed the reviewer's entire raw output as `--arg`, so a verbose
    reviewer exceeded ARG_MAX, jq died with "Argument list too long", and —
    because the call sat inside a heredoc command substitution with no exit
    check — the findings file was written as an empty 1-byte file while the
    console still reported success. The driver then built the fix prompt
    from that empty file, so the fix session received zero findings.
---

# Plan: stop destroying the findings file (#209)

1. **Pass the output by file** — `--rawfile raw_output` from a temp file, so
   nothing unbounded goes on argv. Verified: a >2MB reviewer output (past
   this host's 1048576 ARG_MAX) now produces a valid file with all findings;
   against master the same test yields an empty artifact.
2. **Write directly and check the status** — jq writes to a temp file, its
   exit status is checked, and the result must parse as an object before it
   is moved into place. A failure is a loud exit 1 with no artifact, never a
   plausible-looking empty one.
3. **Validate before use** — the driver refuses to compose a fix prompt from
   a findings file that is missing, empty, or not a JSON object, parking with
   a reason that names the file instead of dispatching a no-op fix session
   that would later park as `git_anomaly`.

## Not done

- **Capping `raw_output`** (issue item 4): unnecessary once the value travels
  by file, and truncating would discard the only record of what the provider
  actually said.
- **Persisting severity/file/suggested_fix into state.json** (item 5): the
  metadata loss was a consequence of the destroyed artifact, which no longer
  happens. A state-schema change to hedge against a fixed failure is not
  worth the migration surface.
