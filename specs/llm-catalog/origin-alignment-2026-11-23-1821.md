# Origin alignment check — llm-catalog (remaining slices re-planned)

Date: 2026-11-23 18:21 EST

Supersedes the 2026-11-20 15:40 record. The owner asked on 2026-11-23:
"Plan https://github.com/gosha70/code-copilot-team/issues/400".
`plan.md` gains "Remaining slices (proposed 2026-11-23)" as Revision 7,
which awaits the owner's approval. `spec.md` and `tasks.md` are
unchanged; the four spec amendments the plan names are recorded when
their slices start.

Origin sources: issue #400 as amended by the owner on 2026-11-10, and
the owner's umbrella comment of 2026-11-20 that lists what is still
owed; the owner's message of 2026-11-23; `spec.md` (approved, with the
launch-first slice); the repository at `3802a47`; the installed CLIs
(`claude` 2.1.331, `codex-cli` 0.147.0, `pi` 0.83.0, `kiro-cli` 2.36.0).

## What #400 still owes, and the slice that delivers it

| Owed (umbrella comment, 2026-11-20) | Slice |
|---|---|
| The compatibility gate: states, the rule table as data, the probe (`cct llm test`, `cct llm compatibility`), D7's refusal of an unverified launch | S2, S3 |
| Session stamps and the resume rules (FR-17 to FR-19) | S4 |
| The digests, `--json` with its schema, `cct llm show`, `cct llm sessions`, `cct harness explain` | S1; `sessions` in S4 |
| Project policy (`[llm].allowed`), the `cct doctor` section, state-file primitives | S5; doctor and state files in S2 |
| `--llm` on the Codex, Pi and Kiro launchers (C, D, E) | S0 (captures), S6, S7, S8 |
| The unified `cct harness` entry and the Studio page (F) | S9 |
| The routing reference (G), whose PR ends #400 | S10 |

Every owed item maps to a slice, and no slice adds anything the
approved spec does not contain.

## Mismatches

None with the origin. Two points for the owner's review:

- The plan runs the three adapter captures before the adapters (S0)
  instead of as each adapter's first task. Evidence still comes before
  any build, as the approved plan requires.
- Four spec amendments are named, each to be recorded when its slice
  starts: FR-24's project file after #460, `auto_compact_window` in
  the options digest, departure 3 in the rule table, and a re-capture
  of FR-20 on Claude Code 2.1.331.

Verdict: aligned
Confidence: high
