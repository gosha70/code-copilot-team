---
applyTo: "**/package.json,**/pyproject.toml,**/go.mod,**/Cargo.toml,**/pom.xml"
---

# Stack Constraints

Rules for managing dependency versions and technology choices across all project types.

## Version Pinning Policy

When starting a new project, prefer **stable, well-documented versions** over bleeding-edge:

- **ORM / database tools** — use latest stable, not pre-release (e.g., avoid beta/canary/rc).
- **Framework** — use LTS or latest stable release.
- **Language runtime** — use latest stable (not beta/rc).
- **UI libraries** — use latest stable release.

Check package documentation for "stable" vs "experimental" badges before adopting.

## Dependency Installation Protocol

When agents create code requiring new packages:

1. **Agents should install dependencies as part of their task** — if they have Bash permission, they must install what they import.
2. **If an agent lacks permission**, pause and instruct the user to install manually before continuing.
3. **Always test the build after new dependencies** — run the dev server, not just the type checker. Static analysis doesn't catch missing runtime packages.
4. **Check for peer dependency warnings** — these often surface as runtime crashes, not compile errors.

## When to Downgrade

Downgrade from a newer version to a stable one when:

- CLI or build tooling breaks (common with major version bumps of ORMs, bundlers, and frameworks).
- Runtime behavior changes unexpectedly from documented behavior.
- Community plugins/extensions don't yet support the new version.
- Error messages reference features marked "experimental" or "early access."

Document the version pin and the reason in the project CLAUDE.md or a `DECISIONS.md` so future contributors know why.

## Stack-Specific Notes

Add version constraints relevant to your project in the project-level CLAUDE.md. For example:

```markdown
## Stack Constraints
- ORM: Prisma 6.x (7.x has breaking CLI changes as of Feb 2026)
- Runtime: Node 20 LTS (not 22 — some deps don't support it yet)
- Framework: Next.js 14 stable (not 15 canary)
```

This keeps global rules generic while allowing each project to pin its own versions.
