---
feature_id: audit-claim-corrections
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
target_ref: docs/audit-claim-corrections
rounds_completed: 1
attempt_count: 1
bypass: false
---

# Peer Review: audit-claim-corrections — Build Phase

**Reviewer**: deepseek
**Scope**: both
**Rounds**: 1
**Verdict**: PASS

## Summary

This is a documentation-accuracy pass that corrects 15 claims the code does not honour, plus a small generator change (`generate-readme-inserts.sh`) and a mirrored header update in `scripts/lib/config_reference.py`. The changes are internally consistent and the generator/header pair is kept in sync, but several corrected claims are themselves unverified against the code they describe, and one correction introduces a new factual claim (a command count) that is not backed by anything in the diff.

## Findings

- [warning] f-f61aef18: The new header asserts `./scripts/cct config validate` "checks the provider profile, the feature catalog and the capability registry" and "does not validate every setting listed below", but the diff provides no evidence this matches the actual `config validate` implementation. The prior text claimed it "runs every validator below"; the correction swings to a specific enumeration that could itself be wrong. This is the same class of error the audit is meant to fix. (docs/configuration-reference.md)
- [warning] f-b8ffad24: The `HEADER` string in `config_reference.py` is the source of truth for the generated `docs/configuration-reference.md` (per the drift guard). The two were edited identically here, which is correct, but the claim "the `cct` front door does not exist in the v1.1.0 tag" is a version-pinned assertion embedded in a generated file that will drift as tags move. It also hardcodes `master` as the checkout branch. (scripts/lib/config_reference.py)
- [warning] f-50359168: The new tree line hardcodes "14" CCT slash commands. Nothing in the diff derives this count; if `setup.sh` installs a different number (or the count changes), the generated README and `docs/configuration-layers.md` become stale with no drift guard catching it. The comment says `COMMANDS_TARGET` is the source but the count is a literal. (scripts/generate-readme-inserts.sh)
- [warning] f-416000b5: The correction changes "six skills" to "four skills" and reclassifies `origin-confirmation` and `wiki-first-query` as on-demand. This is a substantive behavioural claim about `setup.sh`'s always-on rule installation. The diff shows no corresponding change to `setup.sh` or the skill manifests, so either the original doc was wrong (fine) or the always-on set actually changed and the code was not updated. The reviewer cannot tell which from this diff. (docs/install.md)
- [warning] f-8c2033cc: A precise numeric claim (21 of 24; three exceptions `list`, `calibrate`, `start`) with no supporting change or test in the diff. If a subcommand is added or one of the three gains `--db`, this silently rots. The specificity invites the same audit to flag it next round. (docs/session-analytics-cookbook.md)
- [note] f-f592159e: The doc now states `stop_timeout_sec` is required whenever `verification.app` is present and that `validate-automation-config.sh` refuses without it. This is a strong, checkable claim; the diff does not touch the validator. Worth a one-line confirmation that the validator actually enforces it (and that the conformance example elsewhere was updated — the note says "the conformance example above carries it too", which the diff does show). (docs/auto-build.md)
- [note] f-009b93c9: Claims `status` and `origin` are required and that `validate-spec.sh` fails a plan with no `origin:` block, and that the approval gate reads `status: approved`. These are precise validator behaviours asserted in prose with no validator change in the diff. Also adds Pi ("Enforced under the `disciplined` profile") and Codex rows to the adapter table — new capability claims not otherwise evidenced here. (docs/spec-driven-development.md)
- [note] f-c545564d: The row now says `--resume` is "conditionally" allowed for three reasons "provided the phase's build commit is still the branch head (#190 D2)". This references a specific increment/decision id; ensure #190 D2 is actually landed, otherwise the skill documents unimplemented behaviour. (shared/skills/auto-build-loop/SKILL.md)
- [note] f-edd40fa6: The correction enumerates "nine toolchain workflows" and three pack workflows with specific per-file behaviour (`pack-content.yml` push/PR only, etc.). Accurate-looking but unverified in this diff; a miscount here repeats the original defect. (docs/project-templates.md)
- [note] f-c9d5c3e5: Changes "5 SDD templates" to "10 SDD templates" with an explicit list plus `validate-pitch.sh`. The list is checkable; ensure the count and names match the directory exactly (the parenthetical mixes templates and a script, which is slightly confusing). (docs/repo-structure.md)
- [note] f-0bba212a: Moving inline trailing comments to their own lines above the commented-out keys is fine, but it makes the "commented example" block longer and slightly harder to scan; the `disable_thinking` and `price_usd_per_mtok_input` comments now read as prose above a disabled key. Purely cosmetic. (shared/templates/provider-profile-template.toml)
- [note] f-95d0dc60: The two adapter command files are edited identically (good — they are generated/mirrored), but the new text describes `unattended` admission, `pr.closes` preflight refusal, and `validate-spec.sh --unattended` — all behaviours that must exist in the driver. If these are aspirational, the command doc will mislead the agent that reads it. Ensure the mirrored source is the single origin so the two copies cannot diverge. (adapters/claude-code/.claude/commands/auto-build.mdandadapters/claude-code/plugin/commands/auto-build.md)
