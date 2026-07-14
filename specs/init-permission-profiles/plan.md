---
spec_mode: full
feature_id: init-permission-profiles
risk_category: integration
justification: |
  Modifies a safety boundary: adds opt-in permission profiles that reduce
  prompt friction for init'd projects, plus a switch subcommand and sync
  drift reporting. Touches the launcher's init dispatch and init_project(),
  setup.sh --sync distribution, a new permissions/ profile set, and the
  permissions-guide docs. Sensitive because it changes default prompting
  behavior, so the relaxed (hook-disarming) tier is gated behind explicit
  confirmation and no tier ever uses bypassPermissions. Source:
  doc_internal/plans/2026-07-08-init-permission-profiles.md.
status: approved
date: 2026-07-14
issue: 76
origin:
  issue: gosha70/code-copilot-team#76
  urls:
    - https://github.com/gosha70/code-copilot-team/issues/76
  origin_claim: |
    Issue #76: opt-in permission profiles for `claude-code init`. Three tiers
    — default (unchanged), balanced (settings.json with defaultMode=dontAsk +
    allow/deny + stack deny-extras; zero prompts for repo work, protect-*
    hooks still gate commits/pushes/credential edits), and relaxed (dangerous:
    balanced + HOOK_GIT_ALLOW/HOOK_PROTECT_ALLOW env, dropped env-read denies,
    kept Bash guardrails, no bypassPermissions, requires --yes-dangerous).
    `--permissions <tier>` at init (default default; interactive TTY prompt
    when absent), tier recorded in template.json; profiles in
    adapters/claude-code/permissions/ distributed by setup.sh --sync; a new
    `claude-code permissions <tier> [dir]` switch subcommand (jq-merge, never
    clobber); sync reports profile drift but never auto-applies;
    permissions-guide.md rewritten around the tiers. Grounded in the
    user-confirmed decisions of 2026-07-08 and the manual fix already applied
    to mileroot/hookatlas.
---

# Plan: permission profiles for `claude-code init`

Source: `doc_internal/plans/2026-07-08-init-permission-profiles.md`
(§Proposed tiers, §Implementation sketch, §Resolved decisions). Grounded code
facts (verified 2026-07-14):
- `init_project()` — `adapters/claude-code/claude-code:573`; writes
  `template.json` (:658) and jq-merges `settings.local.json` git approvals
  (:666) — the never-clobber pattern the profile write mirrors.
- init dispatch — `:1394` (parses `--playwright`/`--license`); `--permissions`
  + `--yes-dangerous` parse here. New `permissions` subcommand slots into the
  top-level case beside `playwright)` (:1444).
- Hook overrides confirmed: `HOOK_GIT_ALLOW=true` disables `protect-git.sh`
  (:39), `HOOK_PROTECT_ALLOW=true` disables `protect-files.sh` (:12).
- `setup.sh --sync` (:140) copies rules/skills/agents/hooks/templates — add a
  `permissions/` → `~/.claude/permissions/` copy step.

## Deliverables

1. **Profiles** — `adapters/claude-code/permissions/balanced.json`,
   `relaxed.json`, and `deny-extras/<template>.json` (per-stack). `default` =
   absence of a profile. These carry the exact allow/deny sets from the shaped
   plan (schema-only-in-config discipline: the launcher reads these files, it
   does not inline the JSON).
2. **`init --permissions <tier>`** (`init_project`) — resolve the tier
   (flag > interactive TTY prompt > `default`), jq-merge the profile (+
   deny-extras for the type) into `settings.json`, record the tier in
   `template.json`. `relaxed` gated by FR-3a confirmation.
3. **`claude-code permissions <tier> [dir]`** subcommand — apply/switch on an
   existing project (same jq-merge; `default` strips profile-managed keys);
   updates `template.json`; `relaxed` confirmation reused.
4. **`setup.sh --sync`** — copy `permissions/` to `~/.claude/permissions/`.
5. **`sync` drift** — report recorded-tier vs profile-definition drift; no
   auto-apply.
6. **Docs** — rewrite `permissions-guide.md` around the three tiers; enumerated
   per-stack lists demoted to an appendix with the re-trigger warning.
7. **Tests** — extend the `tests/` shell suite per FR-7; register counts.

## Design decisions to confirm at approval

Most were user-confirmed on 2026-07-08 (see the plan doc). Re-surfacing the
few with a code-level fork:

- **D1 (interactive prompt).** On a missing `--permissions` flag, prompt only
  when stdin is a TTY (default `default`); silently use `default` with no TTY
  so scripts/CI never block. Confirm this is the desired UX (vs. always-silent
  default).
- **D2 (`permissions default` semantics).** Switching to `default` on an
  existing project strips the profile-managed `permissions.defaultMode` +
  managed allow/deny + relaxed env, leaving other `settings.json` content
  intact. Confirm (vs. a no-op that only prints guidance).
- **D3 (settings.json is tracked).** Profiles write the shared, committed
  `settings.json` (not `settings.local.json`), so a tier choice propagates to
  the whole team on purpose. Confirm this is intended for `balanced`/`relaxed`.

## Out of scope

- Profiles for non-claude-code adapters (cursor/codex/etc. permission models).
- Auto-applying tiers on `sync` (explicitly rejected).
- New deny patterns beyond the shaped plan's lists (add later if needed).

## Test strategy

Shell-suite only, mirroring existing launcher tests: init each tier into a
`mktemp -d`, assert jq-valid `settings.json` shape per tier, `template.json`
tier recording, `relaxed` refusal without `--yes-dangerous`, and the
`permissions` subcommand's idempotent, non-clobbering merge. Verify
`generate.sh` + `test-shared-structure.sh` stay drift-free after the docs and
profile additions.
