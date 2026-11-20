# Origin Alignment Check — project-key-precedence

Date: 2026-11-20 16:10
Trigger: the owner's ruling on PR #478; supersedes the 2026-11-19 21:00 record.

## Origin sources read

- Issue: https://github.com/gosha70/code-copilot-team/issues/477.
- The owner's first answer (2026-11-19): "Code: explicit rule wins
  (Recommended)". PR #478 was opened on it at `71e4fec`.
- The owner's ruling on that PR (2026-11-20), which replaces the first.

## Origin claim (verbatim)

> #478, option (a): apply the stricter of both keys. For each session,
> resolve both the matching project_ids id and the git-root path. If either
> key's projects entry has ingest: "off", the session is opted out.
> Otherwise use the stricter of the two entries' redaction modes, or the
> global mode when neither has one. Use this combined lookup everywhere a
> project's setting is read: ingest, the outbound policy, the steering-file
> read in project_context, and the trace archive. Tests: a broad rule plus a
> path-keyed opt-out inside it is skipped; an id-keyed opt-out on a
> checked-out repo is skipped (the #477 case); conflicting modes resolve to
> the stricter one. Update the CHANGELOG line to match.

## Acceptance criteria — status

- Both keys resolved for each session — **met** (`ProjectKeyResolver.keys`;
  `test_a_checkout_a_rule_matches_has_both_keys`, real `git init`).
- Opted out if either entry opts out; else the stricter mode; the global
  mode when neither states one — **met** (`combined_override`;
  `TestCombinedOverride`).
- The combined lookup at every reader — **met**: ingest, `OutboundPolicy`,
  `project_context`, the archive and its purge. The heartbeat sweep reads
  the same opt-out and uses it too. No single-key reader is left
  (`AnalyticsConfig.project_override` is removed).
- A broad rule plus a path-keyed opt-out inside it is skipped — **met**
  (`test_an_opt_out_keyed_by_the_repo_path_holds_inside_a_broad_rule`).
- An id-keyed opt-out on a checked-out repo is skipped — **met**
  (`test_an_opt_out_keyed_by_a_project_id_stops_ingest_inside_a_git_checkout`).
- Conflicting modes resolve to the stricter one — **met**, at ingest
  (`test_conflicting_modes_ingest_under_the_stricter_one`) and on every
  outbound path (`test_a_setting_under_either_key_applies_inside_a_git_checkout`).
- The CHANGELOG line matches — **met**.

## Fail-before proof

The new behaviour tests (`test_canary_floor.py`, `test_heartbeat_ingest.py`)
run in throwaway copies against each one-key order:

- master's order (git root, else rule): 8 failures. Every id-keyed case
  fails: both id subcases of the outbound test, the id-keyed opt-out at
  ingest, the two conflicting-mode subcases where the id entry is the
  stricter, the id-keyed heartbeat opt-out, and both archive subcases
  (the id-keyed opt-in archives nothing).
- `71e4fec`'s order (rule, else git root): 7 failures. Every path-keyed
  case fails: both path subcases of the outbound test, the path-keyed
  opt-out inside a broad rule, the two conflicting-mode subcases where the
  path entry is the stricter, and both archive subcases.

## Mismatches

- The ruling names the opt-out and the redaction mode. `trace_archive`
  with an entry under both keys is not stated; the same rule is applied
  (both entries must opt in). Recorded in plan.md for the owner's review.
- The ruling lists four readers. The heartbeat sweep is a fifth reader of
  the same opt-out and uses the same lookup.
- The feature id still says "precedence"; neither key takes precedence now.

## Verdict

Verdict: aligned
Confidence: high
