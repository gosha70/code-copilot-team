# Origin alignment check — plugin-generate-from-sources

Checked 2026-09-19 13:42, before plan approval and before any implementation. Supersedes the 13:18 record after a one-pass plan review that verified the bundle's factual claims and found two gaps, both folded in: the path rewrite and its test now cover `~/.claude/agents/` (the `list-agents` command), and the generator's clean step is stated, scoped to the five generated subdirectories so the two authored files survive, with a reverse assertion so a stale copy fails. The runtime proof is four runs, worst case $1.00. The design, the claims and the differences below are unchanged. The owner's approval and authorizations are still outstanding.

Origin: specs/plugin-generate-from-sources/origin/2026-09-19-owner-direction-step-2.md
(owner messages in the #363 session) and issue #363.

Origin claim:
> Package the existing skills, agents and commands from their
> authoritative sources: generate the plugin, do not maintain another
> authored copy. Keep setup.sh supported. Address duplicate hooks and
> plugin-namespaced commands when both installation paths coexist. No
> broad redesign. Eval comes afterwards and is separately authorized.

Working claim:
> spec.md FR-1..FR-9 and plan.md: one new section in scripts/generate.sh
> copies skills, agents and commands into the plugin with a single path
> rewrite; generated output is committed and covered by CI's existing
> drift check; setup.sh is untouched apart from an inert guard in five
> shared hook scripts; eval is out of scope.

Differences from the origin, each surfaced in the bundle:

1. More than "skills, agents and commands" is generated: the seven hook
   scripts (they are hand copies today and one has drifted, which is the
   thing the owner said not to keep), plus templates/sdd and
   review-decide.sh, because five commands and eight agents point at
   them. Put to the owner as D3 with the alternative stated.
2. A fact the origin could not have known: a plugin cannot ship
   always-loaded rules, which is how setup.sh delivers six of the 24
   skills. The plan ships them as ordinary skills and says so in the
   docs. Put to the owner as D1.
3. "Address plugin-namespaced commands" is met by verifying and
   documenting what Claude Code does with same-named components, not by
   code, unless the verification shows real harm (FR-5). The owner may
   have meant more than that.
4. Duplicate hooks are handled by a guard that deliberately excludes the
   two safety hooks (D2).

Verdict: aligned
Confidence: medium

Medium, not high: differences 1 to 3 are judgement calls on scope that
the owner has not ruled on yet.

Checked by re-reading the owner's messages, reading the plugin reference
(components, namespacing, no always-loaded instructions, copy-to-cache
and path rules, CLAUDE_PLUGIN_ROOT substitution), grepping every
command, agent and skill for dependencies outside a plugin, reading
scripts/generate.sh, setup.sh's install and sync paths and
sync-check.yml's drift step, diffing the drifted hook copy, and
validating a throwaway plugin assembled from the real sources
(claude plugin validate, exit 0).
