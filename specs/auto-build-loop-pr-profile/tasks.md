# Tasks: auto-build-loop `pr` profile (increment D)

<!-- [P] = can run in parallel within the story group. [US#] traces to spec.md. -->

## US1: Profile ladder + guarded push + gh preflight

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 1 | | Profile ladder: `can_push`/`can_open_pr`/`can_merge` from profile; allow `pr`, still refuse `merge` (FR-1) | `scripts/auto-build-loop.sh` | build | [ ] |
| 2 | | `push_branch()`: plain `git push -u <remote> <branch>`, no `--force` path, hard-refuse master/main/base; call after each phase gate + before PR open (FR-2) | `scripts/auto-build-loop.sh` | build | [ ] |
| 3 | | gh preflight iff `can_push`: `$CCT_GH_BIN` present + `gh auth status`; advisory skips (FR-2a) | `scripts/auto-build-loop.sh` | build | [ ] |

**Checkpoint US1** — verify before continuing:
- [ ] `bash -n` clean; advisory path byte-for-byte unchanged (no gh, no push)
- [ ] Push refusal fires for master/main/base branch names

---

## US2: PR create / idempotent update

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 4 | | Close-id sourcing (config `pr.closes` else origin issue; park `pr_config` if none) + deterministic `pr-body.md` (FR-3, FR-4) | `scripts/auto-build-loop.sh` | build | [ ] |
| 5 | | `open_or_update_pr`: resolve existing PR (ledger/`gh pr view`) → `gh pr edit`; else `pre-pr-check.sh` (park `pr_precheck` on fail) → `gh pr create`, parse number+url, record in ledger, journal; never merge (FR-5, FR-6, FR-7) | `scripts/auto-build-loop.sh` | build | [ ] |
| 6 | | Profile-aware finalize messaging (advisory unchanged; pr prints PR #N url) | `scripts/auto-build-loop.sh` | build | [ ] |

**Checkpoint US2** — verify before continuing:
- [ ] `pr create` invoked at most once across a create→kill→resume cycle
- [ ] pre-pr-check failure parks (`pr_precheck`), never bypassed

---

## US3: WIP-push-on-escalation

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 7 | | `park()`: after esc record, `can_push` → push feature branch; failure journaled `wip_push_failed`, never blocks park; `wip_pushed` on esc record; advisory unchanged (FR-8) | `scripts/auto-build-loop.sh` | build | [ ] |

**Checkpoint US3** — verify before continuing:
- [ ] A failing push during park still parks (exit 4) and journals the failure
- [ ] advisory park pushes nothing

---

## US4: Config + tests + docs + Linux parity

| # | [P] | Task | File(s) | Owner | Done |
|---|-----|------|---------|-------|------|
| 8 | [P] | Config: add `pr` block (`closes`, optional `title`) to template; document `CCT_GH_BIN` | `shared/templates/sdd/automation-template.json`, `adapters/claude-code/.claude/settings.json` | build | [ ] |
| 9 | | Tests: gh argv stub + bare remote — pr happy path (push per phase, one `pr create`, ledger pr.*), resume→`pr edit`, advisory zero-gh/zero-push, push refusal, gh-auth-fail preflight, WIP-push park, no `--force` in any argv (FR-9) | `tests/test-auto-build-loop.sh` | build | [ ] |
| 10 | [P] | Skill pr row + config `pr` block; regenerate adapters (zero drift) | `shared/skills/auto-build-loop/SKILL.md`, `adapters/` (generated) | build | [ ] |
| 11 | [P] | Count sync: `tests/test-counts.env` + README suite line | `tests/test-counts.env`, `README.md` | build | [ ] |
| 12 | | Linux container run of test-auto-build-loop.sh (ubuntu + git + jq) | — (verification) | build | [ ] |

**Checkpoint US4** — verify before continuing:
- [ ] `bash scripts/generate.sh` zero drift
- [ ] Full local gate green; container suite green

---

## Final Verification

- [ ] `bash -n` on driver + tests, 0 errors
- [ ] All suites pass with updated counts
- [ ] No [NEEDS CLARIFICATION] markers remain in spec.md
- [ ] Origin alignment re-checked (Gate 3) before presenting
