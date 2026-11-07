# Tasks: `cct` as the single user-facing command name

<!-- Three phases, one commit each. Suites with a count in
     tests/test-counts.env must end each phase at exactly that count. -->

## Phase 1: `cct start` and the shim (FR-1, FR-2, FR-5)

| # | Task | File(s) | Done |
|---|------|---------|------|
| 1 | `start` case: resolve `claude-code` on PATH, then `~/.local/bin`; exec with `"$@"`; else exit 2 naming `./scripts/setup.sh --claude-code` | `scripts/cct` | [x] |
| 2 | `usage()`: `start` block, example line; unknown-command hint lists `start` | `scripts/cct` | [x] |
| 3 | `install_cct_shim()` writing `~/.local/bin/cct` with the baked checkout path; call after each of the three `bake_launcher_repo_path` calls; `[done]` lines name it | `adapters/claude-code/setup.sh` | [x] |
| 4 | Assertions: help documents `start`; hint lists `start`; mock launcher receives args verbatim; no launcher → exit 2 with the install hint | `tests/test-cct-cli.sh` | [x] |
| 5 | Assertions: shim function defined; called at 3 sites; sourced function + throwaway HOME → executable shim, `help` prints `cct — code-copilot-team CLI`, `CCT_REPO_DIR` override wins; a gone checkout exits 2 naming `CCT_REPO_DIR` | `tests/test-claude-code-launcher.sh`, `tests/test-counts.env`, `docs/repo-structure.md` if listed | [x] |
| 5b | `check_shim()` in doctor's Tools section (warn / ok / fail); assertions with a planted dead shim and a planted live shim | `scripts/lib/cct_doctor.py`, `tests/test-cct-cli.sh` | [x] |

**Checkpoint 1**: `bash tests/test-cct-cli.sh`, `bash tests/test-claude-code-launcher.sh` exit 0 at the recorded count; `bash tests/test-shared-structure.sh` unchanged.

## Phase 2: the plugin is named `cct` (FR-3, FR-5)

| # | Task | File(s) | Done |
|---|------|---------|------|
| 6 | `"name": "cct"` | `adapters/claude-code/plugin/.claude-plugin/plugin.json` | [x] |
| 7 | plugin entry `"name": "cct"`; marketplace name unchanged | `.claude-plugin/marketplace.json` | [x] |
| 8 | check: plugin name == marketplace plugin name == `cct` | `tests/test-release-readiness.sh` | [x] |

**Checkpoint 2**: `bash tests/test-release-readiness.sh --no-stack` passes the version-carrier section; `bash tests/test-generate.sh` unchanged.

## Phase 3: docs (FR-4)

| # | Task | File(s) | Done |
|---|------|---------|------|
| 9 | Quick Start step 3 and "Your first session": `cct start ~/projects/my-app`; keep `claude-code` as the equivalent | `README.md` | [x] |
| 10 | Install line `/plugin install cct@code-copilot-team`; namespace examples `/cct:shape`, `cct:build`; one line for users of the old name | `docs/install.md` | [x] |
| 11 | PATH caveats: the shim comes with `setup.sh --claude-code`; `./scripts/cct` still works from a checkout | `docs/codespace-tour.md`, `docs/llm-routing.md` | [x] |
| 12 | `[Unreleased]`: Added `cct start`, `cct` shim; Changed plugin name | `CHANGELOG.md` | [x] |

**Checkpoint 3**: `bash scripts/check-doc-accuracy.sh --counts-only`, `bash tests/test-doc-gates.sh`, `bash tests/test-readme-inserts.sh` exit 0.
