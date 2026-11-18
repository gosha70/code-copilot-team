---
feature_id: pi-project-config
status: approved
---

# Tasks: per-project Pi configuration at `.cct.toml` (#460)

| # | Task | Requirement(s) | File(s) | Done |
|---|---|---|---|---|
| 0 | Owner rules D1–D4 (done 2026-11-18: `.cct.toml` at the root, no gitignore exception, explicit migrate, fallback through 2.1.x); D5 approved with the bundle (2026-11-18); statuses approved | all | bundle | [x] |
| 1 | TypeScript resolver `config/project.ts` with `project.test.mjs`; `loader.ts` project and project-local layers through it; trust gate unchanged | FR-1, FR-2, FR-3 | `adapters/pi/runtime/config/project.ts`, `config/loader.ts`, tests | [x] |
| 2 | `pi-code` resolver function; `init` writes `.cct.toml` + `.cct-init.json`, refuses on a legacy config, ensures `.cct/` and `.cct.local.toml` are ignored (decided with `git check-ignore`), `--dry-run` | FR-2, FR-4 | `adapters/pi/bin/pi-code`, `tests/test-pi-launcher.sh` | [x] |
| 3 | `sync` reads the manifest through the rule; ownership unchanged. Build finding: `pi-code sync` never reads the project manifest (it regenerates the repo's managed resources), so nothing changes and its ownership rule holds | FR-5 | `adapters/pi/bin/pi-code`, `tests/test-pi-launcher.sh` | [x] |
| 4 | `pi-code migrate [--dry-run] [<project>]`: no-replace moves, manifest rewrite, empty-directory removal, conflicts exit 1, refusal (exit 1) when `git check-ignore` reports `.cct.toml` or `.cct-init.json` ignored, paste-safe output | FR-6 | `adapters/pi/bin/pi-code`, `tests/test-pi-launcher.sh` | [x] |
| 5 | `pi-code doctor`: location per file, legacy warnings, ignore checks | FR-7 | `adapters/pi/bin/pi-code`, runtime CLI, tests | [x] |
| 6 | Other spellings: `isSpecPath`, `env-scrub.ts` comment, `provider-emit.sh` + golden fixtures; updated tests (`config.test.mjs`, `security-battery.test.mjs`, `test-sync.sh`, `test-cct-cli.sh`) | FR-8 | as listed | [x] |
| 7 | Docs: Pi configuration reference, `docs/cct-home.md` pointer, CHANGELOG (the move, and the removal version per FR-9); pins in `test-counts.env` and `repo-structure.md` | FR-8, FR-9 | docs | [x] |
| 8 | Gates: validate-spec, origin alignment, all suites, golden check, doc accuracy, `git diff --check`, `pre-pr-check.sh --closes 460`; Linux CI read from GitHub | all | repository gates | [ ] |
