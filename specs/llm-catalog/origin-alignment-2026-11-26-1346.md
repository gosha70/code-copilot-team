# Origin alignment check — llm-catalog (S3, at its start)

Date: 2026-11-26 13:46 EST

Supersedes the 2026-11-25 23:33 record. Since then:
- PR #539 (S4) merged on 2026-11-26 at `e0f3ebd`, as `a5e7986`;
- the owner ruled to keep both launch-identity checks for a resume
  opened in a new pane, the one point the 23:33 record left open;
- the owner asked for the next item, S3, and ruled on open decision 1,
  which the 2026-11-23 rulings reserved for S3.

Origin sources: the 23:33 record's; the owner's ruling on the double
check, added to `origin/2026-11-25-s4-rulings.md`; and the owner's S3
rulings, `origin/2026-11-26-s3-rulings.md`.

## Where the origin stands

| Origin | Where it is |
|---|---|
| S4's point (2): don't pay the stamp twice on the interactive path | Settled: the owner ruled to keep both launch-identity checks for a resume in a new pane (FR-17's note) |
| The 2026-11-23 ruling (3): state S3's consequence in full, and put the milder rule to the owner as an open decision for S3 | Put on 2026-11-26 and ruled: the milder rule, with a changed tuning option or rule version refusing as `unverified`. FR-12, FR-13, FR-19 and D7 carry the amendment, and `plan.md` marks open decision 1 settled |
| The order: S0, S1, S2, then S4 before S3 | S0 (#524), S1 (#525), S2 (#528), S5 (#529) and S4 (#539) are merged; S3 is next |

## What S3 must deliver

From `plan.md`, "Remaining slices", row S3, as approved in #521, under
the 2026-11-26 rulings:
- the probe runner (FR-15), over canary primitives extracted from
  `routing-probe.sh`, with routing's pins unchanged (D6);
- the watchdog;
- the stub gateway, with one negative-control switch per capability;
- `cct llm test`;
- Claude Code launches that refuse `unverified` and `incompatible`
  targets, with `--allow-unverified` (D7), under the milder rule; this
  retires the launch-first slice's departure 1;
- a restored target that goes through the gate like a fresh `--llm`
  (FR-19);
- the real binary run through the stub gateway with every switch, and
  once against a configured target, quoted in the PR.

## Mismatches

None open. Unchanged, and accepted by the owner on 2026-11-25: the
native notice for `--continue` and the picker prints only where stamps
exist (FR-18).

Verdict: aligned
Confidence: high
