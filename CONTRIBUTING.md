# Contributing to Code Copilot Team

Thanks for your interest in improving this project. Contributions are welcome in several areas.

## What We're Looking For

**New project templates** — Have a stack that isn't covered (e.g., Rust/WASM, Go microservices, Flutter)? Add a template directory under `~/.claude/templates/` via `claude-setup.sh` and submit a PR.

**Rule improvements** — Found a coding standard, safety guard, or efficiency tip that should be universal? Propose changes to the files in `claude_code/.claude/rules/`.

**Ports to other tools** — Have working configurations for Cursor, Windsurf, Aider, or other AI coding tools? We'd love to add tool-specific setup guides under `claude_code/docs/`.

**Bug fixes** — Especially for cross-platform issues (macOS vs Linux, bash version differences).

## How to Contribute

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/go-microservice-template`)
3. Make your changes
4. Test: if you modified `claude-setup.sh`, run it on a clean `~/.claude/` directory
5. Commit with a clear message (`git commit -m "Add Go microservice template with gRPC agent team"`)
6. Open a pull request

## Guidelines

- Keep rules concise. AI copilots have limited context; every word costs tokens.
- Test templates by actually running `claude-code init <type>` and verifying the generated files.
- Maintain tool-agnostic language in the `rules/` files where possible.
- One PR per concern. Don't mix a new template with a rule change.

## Questions?

Open an issue. Happy to discuss design decisions or help with template development.
