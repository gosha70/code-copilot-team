# Origin alignment check — init-permission-profiles

Origin: https://github.com/gosha70/code-copilot-team/issues/76

Origin claim:
> Issue #76: opt-in permission profiles for `claude-code init`. Three tiers —
> default (unchanged), balanced (settings.json with defaultMode=dontAsk +
> allow/deny + stack deny-extras; zero prompts for repo work, protect-* hooks
> still gate commits/pushes/credential edits), and relaxed (dangerous:
> balanced + HOOK_GIT_ALLOW/HOOK_PROTECT_ALLOW env, dropped env-read denies,
> kept Bash guardrails, no bypassPermissions, requires --yes-dangerous).
> `--permissions <tier>` at init (default default; interactive TTY prompt when
> absent), tier recorded in template.json; profiles in
> adapters/claude-code/permissions/ distributed by setup.sh --sync; a new
> `claude-code permissions <tier> [dir]` switch subcommand (jq-merge, never
> clobber); sync reports profile drift but never auto-applies;
> permissions-guide.md rewritten around the tiers. Grounded in the
> user-confirmed decisions of 2026-07-08 and the manual fix already applied to
> mileroot/hookatlas.

Working claim:
> specs/init-permission-profiles/{spec.md,plan.md,tasks.md} bind exactly that
> scope (FR-1..FR-7), with three code-level decisions confirmed by the user at
> plan approval (2026-07-14): D1 — interactive tier prompt only on a TTY,
> silent `default` in CI; D2 — `permissions default` strips the
> profile-managed keys and preserves other settings.json content; D3 —
> profiles write the tracked, team-shared settings.json (not
> settings.local.json). `dontAsk` verified against the official permission-modes
> doc as auto-deny-unmatched + honor-deny. No implementation exists yet on
> branch feat/init-permission-profiles-76.

Verdict: aligned
Confidence: high

Checked 2026-07-14 by re-reading issue #76, the shaped source plan
(doc_internal/plans/2026-07-08-init-permission-profiles.md), and the verified
launcher/hook code locations. Plan flipped to status: approved with explicit
user approval; D1/D2/D3 confirmed.
