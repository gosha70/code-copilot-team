# Tasks: permission profiles for `claude-code init`

<!-- [P] = can run in parallel within the story group. [US#] traces to spec.md. -->

## US1: Profiles + `init --permissions`

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 1 | [P] | Author `balanced.json`, `relaxed.json`, `deny-extras/<template>.json` with the shaped allow/deny sets (FR-2, FR-3) | `adapters/claude-code/permissions/` | build | [ ] |
| 2 | | Parse `--permissions <tier>` + `--yes-dangerous` in the init dispatch; validate tier, error on unknown (FR-1) | `adapters/claude-code/claude-code` | build | [ ] |
| 3 | | Tier resolution (flag > interactive TTY prompt > default) + record tier in `template.json`; jq-merge profile + deny-extras into `settings.json`, never clobber, idempotent (FR-1, FR-1a, FR-2) | `adapters/claude-code/claude-code` | build | [ ] |

**Checkpoint US1** — verify before continuing:
- [ ] `bash -n` clean; `default` writes no `settings.json`
- [ ] `balanced` init → jq-valid settings with correct defaultMode/allow/deny + per-type deny-extras; tier in template.json

---

## US2: `relaxed` gating + switch subcommand

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 4 | | `relaxed` write path: env block, dropped env-read denies, kept Bash guardrails, never `bypassPermissions`; refuse without `--yes-dangerous`/interactive y/N + loud warning (FR-3, FR-3a) | `adapters/claude-code/claude-code` | build | [ ] |
| 5 | | New `claude-code permissions <tier> [dir]` subcommand: apply/switch via jq-merge (never clobber), update template.json, reuse relaxed confirmation; `default` strips profile-managed keys (FR-4) | `adapters/claude-code/claude-code` | build | [ ] |

**Checkpoint US2** — verify before continuing:
- [ ] `relaxed` refused without the flag; with it, env + dropped denies + no bypassPermissions
- [ ] `permissions` switch is idempotent and preserves unrelated settings.json keys

---

## US3: Distribution + drift + docs

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 6 | | `setup.sh --sync` copies `permissions/` → `~/.claude/permissions/` (FR-5a) | `adapters/claude-code/setup.sh` | build | [ ] |
| 7 | | `sync` reports permission-profile drift (recorded tier vs definition), never auto-applies (FR-5) | `adapters/claude-code/claude-code` | build | [ ] |
| 8 | [P] | Rewrite `permissions-guide.md` around the three tiers; enumerated lists → appendix with re-trigger warning (FR-6) | `adapters/claude-code/docs/permissions-guide.md` | build | [ ] |

**Checkpoint US3** — verify before continuing:
- [ ] `setup.sh --sync` places profiles in `~/.claude/permissions/`; launcher resolves from there
- [ ] `sync` prints drift and applies nothing

---

## US4: Tests + counts + drift-free

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 9 | | Launcher tests: per-tier init (default/balanced/relaxed), tier in template.json, relaxed refusal + confirmed write, `permissions` switch idempotency + non-clobber (FR-7) | `tests/` (launcher suite) | build | [ ] |
| 10 | [P] | Count sync (`tests/test-counts.env` + any README suite line); `generate.sh` + `test-shared-structure.sh` drift-free | `tests/test-counts.env`, `README.md` | build | [ ] |

**Checkpoint US4** — verify before continuing:
- [ ] Full local gate green with updated counts
- [ ] `bash scripts/generate.sh` zero drift

---

## Final Verification

- [ ] `bash -n` on the launcher + tests, 0 errors
- [ ] All suites pass with updated counts
- [ ] No [NEEDS CLARIFICATION] markers remain in spec.md
- [ ] Origin alignment re-checked (Gate 3) before presenting
