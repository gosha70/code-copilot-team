# Tasks: one harness home (#411)

| # | Task | Requirement(s) | File(s) | Done |
|---|---|---|---|---|
| 0 | Owner rules D1–D6 (done 2026-11-15: D1 ~/.cct wins, D3 explicit migrate, D5 project side as its own issue and PR, D2/D4/D6 as recommended); markers removed; statuses approved; fresh alignment record; the D5 follow-up issue text drafted for the owner to file | all | bundle | [x] |
| 1 | Bash resolver `scripts/lib/cct-home.sh` (precedence, fallback, `legacy_hits`) with `tests/test-cct-home.sh`; the legacy name appears in code only here, with the 2.2 removal comment | FR-2, FR-3, FR-11 | `scripts/lib/cct-home.sh`, `tests/test-cct-home.sh` | [ ] |
| 2 | Python resolver `session_analytics/home.py` + `scripts/lib/cct_home.py`; `config.py` three defaults and `api/server.py` allow-list through it; `test_home.py` | FR-2, FR-3, FR-8 | `scripts/session_analytics/home.py`, `scripts/lib/cct_home.py`, `config.py`, `api/server.py`, tests | [ ] |
| 3 | TypeScript resolver `adapters/pi/runtime/config/home.ts`; `index.ts` and `loader.ts` global config through it; `pi-code` and `adapters/pi/setup.sh` default `CCT_HOME` from the bash resolver; `pi-code doctor` reports the home; `home.test.mjs`, `test-pi-launcher.sh` cases | FR-2, FR-3, FR-7 | Pi runtime, launcher, setup, tests | [ ] |
| 4 | Every other reader on the resolver: hook, `adapters/claude-code/setup.sh`, `scripts/setup.sh`, peer review and review runner, auto-build driver, supervisor, routing state and probe, provider-emit/setup, `cct_config.py`, `cct_doctor.py`, `config_reference.py`; their suites updated; golden fixtures regenerated | FR-1, FR-4 | the inventory in the origin record | [ ] |
| 5 | `cct home show|migrate [--dry-run]` with its tests; `scripts/cct` dispatch and help | FR-5 | `scripts/cct`, `scripts/cct-home.sh`, `tests/test-cct-cli.sh`, `tests/test-cct-home.sh` | [ ] |
| 6 | Doctor **Home** section and the setup notice | FR-6 | `scripts/lib/cct_doctor.py`, `scripts/setup.sh`, `tests/test-cct-cli.sh` | [ ] |
| 7 | Structure-suite guard with exception list and planted-spelling mutation test; pins | FR-9 | `tests/test-shared-structure.sh`, `tests/test-counts.env`, `docs/repo-structure.md` | [ ] |
| 8 | Docs: `docs/cct-home.md`, the 9 pages, README, template headers, `providers.schema.json`, generated reference, CHANGELOG (2.1 move, 2.2 removal); amend the #400 spec on record if slice A has not started | FR-10, FR-11, FR-12 | docs, templates, schema, CHANGELOG, `specs/llm-catalog/` | [ ] |
| 9 | Gates: validate-spec, origin alignment, all suites, generators `--check`, doc accuracy, `git diff --check`, `pre-pr-check.sh --closes 411`, peer review, PR; Linux CI read from GitHub | all | repository gates | [ ] |
