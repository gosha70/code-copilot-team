# Contributing to Code Copilot Team

Thanks for your interest in improving this project. Contributions are welcome in several areas.

## Architecture

Rule content lives in `shared/` as the single source of truth. Tool-specific configurations are generated into `adapters/` by `scripts/generate.sh`. Generated outputs are committed to the repo — CI verifies they never drift.

```
shared/skills/*/SKILL.md  →  scripts/generate.sh  →  adapters/<tool>/
                                                      (committed, CI-verified)
```

## What We're Looking For

**Skill improvements** — Found a coding standard, safety guard, or efficiency tip that should be universal? Edit `SKILL.md` files in `shared/skills/<name>/`, then run `./scripts/generate.sh` to update all adapters.

**New project templates** — Have a stack that isn't covered (e.g., Rust/WASM, Go microservices, Flutter)? Add a template directory under `shared/templates/` and update `adapters/claude-code/setup.sh`.

**New tool adapters** — Want to add support for another AI coding tool? Add a generation target in `scripts/generate.sh` and create `adapters/<tool>/setup.sh`.

**Claude Code improvements** — Agents, hooks, and commands live in `adapters/claude-code/.claude/`. Changes here don't require regeneration.

**Bug fixes** — Especially for cross-platform issues (macOS vs Linux, bash version differences).

## How to Contribute

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/go-microservice-template`)
3. Make your changes:
   - **Shared skills:** edit `shared/skills/<name>/SKILL.md`, then run `./scripts/generate.sh` and commit the updated `adapters/` outputs
   - **Claude-specific:** edit `adapters/claude-code/` directly
   - **Templates:** add to `shared/templates/`
4. Run the test suites:
   ```bash
   bash tests/test-generate.sh        # generation + adapter tests
   bash tests/test-hooks.sh           # hook script tests
   bash tests/test-sync.sh            # sync + init metadata tests
   bash adapters/claude-code/setup.sh # refresh install target for structure checks
   bash tests/test-shared-structure.sh # structure + content tests
   ```
5. Commit with a clear message (`git commit -m "Add Go microservice template with gRPC agent team"`)
6. Open a pull request

## Guidelines

- Keep rules concise. AI copilots have limited context; every word costs tokens.
- Test templates by actually running `claude-code init <type>` and verifying the generated files.
- Maintain tool-agnostic language in `shared/skills/` SKILL.md files.
- Always run `./scripts/generate.sh` after changing `shared/` content. CI will fail if generated outputs are stale.
- One PR per concern. Don't mix a new template with a rule change.

## Ongoing Alignment Checks

To prevent instruction drift and outdated quality claims:

1. Follow [shared/docs/alignment-maintenance.md](shared/docs/alignment-maintenance.md) for release and monthly health checks.
2. Keep README test-count lines in sync with actual test output.
3. Treat `tests/test-counts.env` as the source of truth for expected top-level suite totals when assertions change.
4. Keep `.github/workflows/sync-check.yml` aligned with full gate coverage (all suites + setup before structure test).
5. If structure tests fail on installed template parity, refresh local install and rerun:
   ```bash
   bash adapters/claude-code/setup.sh
   bash tests/test-shared-structure.sh
   ```

## Default Branch Convention

Scripts and hooks shipped by this scaffold auto-detect the consumer repository's default branch at runtime rather than assuming a fixed name. The detection order is:

1. **Runtime detection** via `git symbolic-ref refs/remotes/origin/HEAD` (reports what the remote declares as its HEAD).
2. **Env var override** — set `DEFAULT_BRANCH` before invoking any scaffold script to force a specific branch name.
3. **Fallback** — if detection fails (e.g., no remote configured), scripts fall back to `master`.

The scaffold's own repository stays on `master`, but generated artifacts and hooks that ship to consumer repos must not assume a branch name. When writing new scripts or hooks that need to reference the default branch, use this pattern:

```bash
DEFAULT_BRANCH="${DEFAULT_BRANCH:-$(git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's@^refs/remotes/origin/@@')}"
DEFAULT_BRANCH="${DEFAULT_BRANCH:-master}"
```

The `.github/workflows/sync-check.yml` already handles both conventions via `branches: [master, main]` and must not be changed.

## Community Standards

- [Code of Conduct](CODE_OF_CONDUCT.md)
- [Code Owners](.github/CODEOWNERS)
- [Security Policy](SECURITY.md)
- [Issue Templates](.github/ISSUE_TEMPLATE/)
- [Pull Request Template](.github/pull_request_template.md)
- [GitHub Hardening Playbook](docs/github-hardening-playbook.md)

## Security Reporting

- Do not open public issues for security vulnerabilities.
- Follow [SECURITY.md](SECURITY.md) and use private GitHub Security Advisories for disclosure.

## Questions?

Open an issue. Happy to discuss design decisions or help with template development.
