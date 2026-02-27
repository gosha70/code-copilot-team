# Contributing to Code Copilot Team

Thanks for your interest in improving this project. Contributions are welcome in several areas.

## Architecture

Rule content lives in `shared/` as the single source of truth. Tool-specific configurations are generated into `adapters/` by `scripts/generate.sh`. Generated outputs are committed to the repo — CI verifies they never drift.

```
shared/rules/always/*.md   →  scripts/generate.sh  →  adapters/<tool>/
shared/rules/on-demand/*.md                            (committed, CI-verified)
```

## What We're Looking For

**Rule improvements** — Found a coding standard, safety guard, or efficiency tip that should be universal? Edit files in `shared/rules/always/` or `shared/rules/on-demand/`, then run `./scripts/generate.sh` to update all adapters.

**New project templates** — Have a stack that isn't covered (e.g., Rust/WASM, Go microservices, Flutter)? Add a template directory under `shared/templates/` and update `adapters/claude-code/setup.sh`.

**New tool adapters** — Want to add support for another AI coding tool? Add a generation target in `scripts/generate.sh` and create `adapters/<tool>/setup.sh`.

**Claude Code improvements** — Agents, hooks, and commands live in `adapters/claude-code/.claude/`. Changes here don't require regeneration.

**Bug fixes** — Especially for cross-platform issues (macOS vs Linux, bash version differences).

## How to Contribute

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/go-microservice-template`)
3. Make your changes:
   - **Shared rules:** edit `shared/rules/`, then run `./scripts/generate.sh` and commit the updated `adapters/` outputs
   - **Claude-specific:** edit `adapters/claude-code/` directly
   - **Templates:** add to `shared/templates/`
4. Run the test suites:
   ```bash
   bash tests/test-generate.sh        # generation + adapter tests
   bash tests/test-hooks.sh           # hook script tests
   bash adapters/claude-code/setup.sh # refresh install target for structure checks
   bash tests/test-shared-structure.sh # structure + content tests
   ```
5. Commit with a clear message (`git commit -m "Add Go microservice template with gRPC agent team"`)
6. Open a pull request

## Guidelines

- Keep rules concise. AI copilots have limited context; every word costs tokens.
- Test templates by actually running `claude-code init <type>` and verifying the generated files.
- Maintain tool-agnostic language in the `shared/rules/` files.
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
