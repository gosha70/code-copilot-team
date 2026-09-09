# Origin alignment check — team-developer-aliases

Origin: specs/team-developer-aliases/origin/2026-09-08-first-unattended-run.md
(owner's #190 directive of 2026-09-08 and the observed three-id attribution
on the owner's store); parent issue #174.

Origin claim:
> One person's sessions appear under several developer ids on the Team
> tab because identity derivation changed over time; fold them into one
> row under one configured name at read time, without rewriting the
> store. The first real unattended auto-build run.

Working claim:
> specs/team-developer-aliases/{spec,plan,tasks}.md: a `team.aliases`
> mapping (config file + CCT_SA_TEAM_ALIASES), applied in
> team_status() to fold rows sharing a display name into one row that
> lists every folded id in `merged_ids`, with summed windows and the
> newest heartbeat; wired into the API route and the CLI; tests; one
> cookbook paragraph. No schema, no UI, no store write.

Verdict: aligned
Confidence: high

Checked 2026-09-08 against the owner's message, the Team tab output on
the owner's store (three ids), and PR #324's team_status contract.
