# Origin alignment check — claude-code-2026-09-adoption

> Superseded by `origin-alignment-2026-09-19-1159.md`. Kept as history; the latest record is the current one.

Checked 2026-09-19 10:36, before implementation and before plan approval. Supersedes the 10:35 record: spec.md now states that the unknown-key probe covers 2.1.278 only. Claims and differences are unchanged. A review on 2026-09-19 recommends accepting D1 and D2 and not renaming the skill; the owner's acceptance is still outstanding.

Origin: issue #363 (body, no comments) and
specs/claude-code-2026-09-adoption/origin/2026-09-19-owner-brief.md

Origin claim:
> P1: `effort` in the frontmatter of the 14 shipped agents, matching the
> manifest (Research/Plan/Review high, Build medium, narrow utility
> low). P2: this release's version-gated CLI facts in the
> opus-4-7-features skill, gates confirmed from a source. One slice.
> No plugin eval, no rename, no `omitClaudeMd` adoption (record the
> decline), no environmental work. Edit sources, regenerate derived.

Working claim:
> spec.md FR-1..FR-6 and plan.md: one `effort:` line per agent at its
> authored source, one new section in the existing skill with gates
> taken from the changelog and docs, the `omitClaudeMd` decline recorded
> in that section, one test assertion. Skill name untouched. P3 and the
> environmental items absent.

Differences from the origin, each surfaced in plan.md:

1. Source directory. The brief names the adapter directory as the agent
   source; for verify-app and visual-reviewer the authored source is
   `claude_code/.claude/agents/` (`scripts/generate.sh:69-80`). The plan
   follows the brief's rule (never hand-edit a generated surface) over
   its path.
2. Effort values. The plan's recommended table puts security-review at
   high and code-simplifier / doc-writer at medium, where a literal
   reading of "narrow utility agents low" gives low. Raised as owner
   decision D1 with the literal alternative stated.
3. Two small additions the origin does not name: a structure-test
   assertion (FR-6) and an optional one-sentence manifest pointer (D2,
   the issue's open question). D2 is gated on the owner's answer.
4. The issue calls the subagent frontmatter surface new this release;
   the changelog shows only `omitClaudeMd` is. P2 records the real
   gates, as the brief instructs.

Verdict: aligned
Confidence: medium

Medium, not high, because difference 2 changes shipped values relative
to the brief's wording until the owner rules on D1.

Checked by re-reading the issue body and the brief, grepping the raw
changelog for every gate, reading the sub-agents doc page, probing the
local CLI (2.1.278) with an agent file carrying unknown keys, and
reading `scripts/generate.sh`, `adapters/claude-code/setup.sh`
(sync + manifest heredoc) and the agent loop in
`tests/test-shared-structure.sh`.
