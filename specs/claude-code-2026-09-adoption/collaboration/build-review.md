---
feature_id: claude-code-2026-09-adoption
date: 2026-09-19
status: final
phase: build
mode: review
subject_provider: claude
peer_provider: deepseek
peer_profile: deepseek
runner_fingerprint: ae8dc147cf1264834bab35d116b6ab96b06618f438763cde3a90621d78036dba
verdict: PASS
blocking_findings_open: 0
target_ref: feat/363-agent-effort-cli-facts
rounds_completed: 1
attempt_count: 1
bypass: false
---

# Peer Review: claude-code-2026-09-adoption — Build Phase

**Reviewer**: deepseek
**Scope**: both
**Rounds**: 1
**Verdict**: PASS

## Summary

The change adds `effort:` frontmatter to 14 shipped agents, appends a "CLI Facts (September 2026)" section to the shared `opus-4-7-features` skill (regenerated into three adapters), adds a structure-test assertion, and updates counts. The spec/plan/tasks artifacts are thorough and the origin-alignment trail is well documented. The main concerns are a fragile awk-based frontmatter parser in the new test, a hardcoded count bump that depends on a machine-local installed copy, and a few documentation/consistency gaps.

## Findings

- [warning] f-e2a73be8: The awk frontmatter extractor `awk '/^---[[:space:]]*$/{n++; next} n==1'` treats any `---` line as a delimiter and only captures the block between the first and second `---`. If an agent file ever has a leading blank line, BOM, or a `---` inside a body code fence before the frontmatter, the extraction silently yields the wrong region and the assertion can pass or fail spuriously. It also does not anchor to the first line, so a `---` in prose above the frontmatter would break it. (tests/test-shared-structure.sh)
- [warning] f-5c64187f: The count bump from 812 to 826 is justified in tasks.md by "821 passed, 5 failed" where the 5 failures are machine-local (`~/.claude/skills` vs `shared/`). Pinning the expected pass count to a value that only holds when the local install is out of sync means CI (no installed copy) and a synced developer machine will disagree with the pinned number. This is a latent flake. (tests/test-counts.env)
- [note] f-f8245c75: The table lists `effort` "Since v2.1.78" but the caveat says it was ignored on pinned-default models until 2.1.267. A reader scanning the table alone will conclude `effort` works from 2.1.78. The caveat is present but only in the Notes cell; consider a short inline marker (e.g., "effective 2.1.267 on pinned-default models") so the gate is unambiguous without reading the whole cell. (shared/skills/opus-4-7-features/SKILL.md)
- [note] f-d446faf4: The added sentence says the subagent's frontmatter `effort` "governs it, not this section." That is correct, but the surrounding prose still reads as if the phase strategy applies to all work. A one-clause pointer ("for the main session only") at the top of the phase-strategy block would prevent the same confusion the new sentence is trying to fix. (adapters/claude-code/setup.sh)
- [note] f-9210c939: The plan notes `/list-agents` will not show `effort` and defers the column. Since FR-5 forbids enumerating per-agent values in prose, the only discoverable source of truth for a human is the frontmatter itself. Consider filing the `/list-agents` follow-on as a tracked issue reference in the plan so it is not lost. (specs/claude-code-2026-09-adoption/plan.md)
- [note] f-cf32e620: The plan's D1 table justifies `security-review` at `high` as "review work; a shallow pass is the failure mode," which departs from the brief's literal "narrow utility agents low." The owner accepted D1, so this is intentional, but the shipped file carries no comment explaining the departure. If a future reader diffs against the brief they will see a mismatch with no in-file rationale. (adapters/claude-code/.claude/agents/security-review.md)
- [note] f-234084ef: The 10:35 and 10:36 records are near-identical and both marked superseded. Keeping both adds noise; the 10:36 record's only delta is a one-sentence clarification. Consider collapsing superseded alignment records to a single line in the latest record rather than retaining full duplicates. (specs/claude-code-2026-09-adoption/origin-alignment-2026-09-19-1035.md)
- [note] f-003dcc6a: The assertion only checks the value is one of `low (tests/test-shared-structure.sh)
