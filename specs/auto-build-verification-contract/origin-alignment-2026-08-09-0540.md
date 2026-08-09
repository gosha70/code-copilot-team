# Origin Alignment Check — auto-build-verification-contract

Date: 2026-08-09 05:40
Trigger: plan.md, spec.md and tasks.md revised to rev 11 after the user's
tenth review round; the rev-10 record is stale.

## Origin sources read

- #222, #190 §6, the increment-C handoff notes.
- The user's tenth-round findings (producer order, symlink containment,
  prune intent, preset provenance).
- `scripts/validate-spec.sh` — the #193 governance-before-execution
  ordering this plan must not undo.

## Working claim

Scope unchanged since rev 2. Rev 11 makes producer order normative
(admission before coverage execution on `fresh-unattended-block`), requires
realpath-aware containment before the driver deletes an artifact, bases the
prune on configured intent, and records `preset_id`/`preset_sha256` as null
when no preset contributes policy.

## Mismatches

- #222's `skip_is_failure` remains deliberately unmet (C3); #222 stays open.

## What rev 11 changed, per finding

1. **Producer order was unspecified, and the overview implied the wrong
   one.** On `fresh-unattended-block` the coverage command — arbitrary
   project code — could have run before `validate-spec --unattended`
   approved governance. That undoes the governance-before-execution
   ordering I implemented in #193 after the user's own P2 on that PR. Order
   is now normative: admission bar, THEN contract initialisation, with
   SC-5i asserting a governance-failing fixture never executes its coverage
   command.
2. **Lexical containment became insufficient the moment FR-5a made the
   driver DELETE the artifact.** `coverage/out.json` escapes when
   `coverage` is a symlink out of tree, so the driver would delete and
   parse an external file. Containment now resolves symlinks in every
   existing ancestor, before deletion and after generation; SC-5j asserts
   an external sentinel is neither deleted nor parsed.
3. **The prune trigger referenced an outcome that cannot be known when the
   decision is made** — the prune precedes the `worktree add` it was
   conditioned on. It is now decided from configured intent: in-place
   override or non-git means no attempt and no prune; otherwise prune
   first, regardless of whether creation later fails.
4. **The explicit-floors branch had no provenance representation.** FR-5
   admits a config with every floor explicit and no preset, while FR-4a
   requires `preset_id`/`preset_sha256`. Both are now `null` in that case —
   recorded explicitly so the contract distinguishes "no preset
   contributed" from "resolved but not recorded". SC-6 also stops claiming
   every successful run imports "baseline and accounting", which is false
   for four of the seven paths.

## Verdict

Verdict: aligned
Confidence: high
