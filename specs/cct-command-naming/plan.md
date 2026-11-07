---
spec_mode: lightweight
feature_id: cct-command-naming
risk_category: cli
justification: |
  A new subcommand that execs an existing launcher, a two-line generated
  shim installed next to that launcher, and a rename of one JSON field in
  two manifests. No schema, no API, no new dependency, nothing the
  installed hooks read. Every behaviour is asserted by the existing bash
  suites with a mock launcher and a throwaway HOME.
status: approved
date: 2026-11-07
origin:
  issue: 410
  transcripts:
    - specs/cct-command-naming/origin/2026-11-07-owner-direction.md
  origin_claim: |
    Start a session as a CCT action and spell every CCT command `cct`
    (owner, 2026-11-07, #410). The profile-directory move is deferred in
    #410 after planning found it is the Pi adapter's home.
---

# Plan: `cct` as the single user-facing command name

## Deliverables

1. **`scripts/cct`** — `start` case: resolve the launcher
   (`command -v claude-code`, else `$HOME/.local/bin/claude-code`), exec
   it with `"$@"`; otherwise print the install hint to stderr and exit 2.
   `usage()` gains the `start` block and the EXAMPLES line; the unknown-
   command hint lists `start`.

2. **`adapters/claude-code/setup.sh`** — `install_cct_shim()` next to
   `bake_launcher_repo_path()`. It writes `$HOME/.local/bin/cct` with
   `printf`, so the checkout path from `cd "$SCRIPT_DIR/../.." && pwd`
   lands verbatim in the line `CCT_REPO_DIR_DEFAULT="<repo>"` (no sed, for
   the same reason the launcher bake uses awk). The shim tests that
   `<checkout>/scripts/cct` is executable before execing it and otherwise
   exits 2 naming `CCT_REPO_DIR` and the setup command. Called once after
   each of the three `bake_launcher_repo_path` calls. The `[done]` lines
   name the shim.

   **`scripts/lib/cct_doctor.py`** — `check_shim()` in the Tools section:
   WARN when no `cct` is on `PATH`, OK when the shim's baked checkout (or
   `CCT_REPO_DIR`) holds `scripts/cct`, BAD when it does not.

3. **Manifests** — `adapters/claude-code/plugin/.claude-plugin/plugin.json`
   `name: "cct"`; `.claude-plugin/marketplace.json` plugin entry
   `name: "cct"`; marketplace `name` unchanged.

4. **Docs** — README (Quick Start step 3, "Your first session"),
   docs/install.md (install line, namespace examples, a "moving from the
   old plugin name" line), docs/codespace-tour.md and docs/llm-routing.md
   PATH caveats, CHANGELOG `[Unreleased]`.

5. **Tests** — `tests/test-cct-cli.sh`: `start` in help and in the
   unknown-command hint; a mock `claude-code` on PATH receives the
   arguments verbatim; with an empty PATH and a HOME without the launcher
   the exit is 2 and the message names `setup.sh --claude-code`.
   `tests/test-claude-code-launcher.sh`: the shim function is defined and
   called at all three install sites; sourcing only that function with a
   throwaway HOME produces an executable shim whose `help` output is
   `scripts/cct`'s and which honours `CCT_REPO_DIR`.
   `tests/test-release-readiness.sh`: plugin name equals marketplace
   plugin name equals `cct`.

## Phases

| Phase | FRs | Commit |
|---|---|---|
| 1 | FR-1, FR-2, FR-5 (cli + launcher suites) | `feat(cct): cct start and a cct shim on PATH` |
| 2 | FR-3, FR-5 (release check) | `feat(plugin): name the plugin cct` |
| 3 | FR-4 | `docs(cct): start sessions with cct start; /cct: namespace` |

## Verification

Run from the worktree root after each phase; the suites that have a count
in `tests/test-counts.env` must report exactly that count.

```bash
bash tests/test-cct-cli.sh
bash tests/test-claude-code-launcher.sh
bash tests/test-release-readiness.sh --no-stack
bash tests/test-shared-structure.sh
bash scripts/check-doc-accuracy.sh --counts-only
bash scripts/validate-spec.sh cct-command-naming
bash scripts/check-origin-alignment.sh cct-command-naming
```

## Risks

- `test-shared-structure.sh` asserts the exact wording of setup.sh's
  `[done]` lines in places; grep before changing any.
- The launcher suite has an assertion count (26); every added assertion
  bumps `tests/test-counts.env` and, if listed, `docs/repo-structure.md`.
- Plugin users who installed `code-copilot-team@code-copilot-team` keep
  that copy until they uninstall it; the docs say so.
