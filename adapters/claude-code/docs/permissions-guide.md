# Claude Code Permission Profiles Guide

`claude-code init` and `claude-code permissions` write a project's permission
posture as one of three **tiers**. Pick a tier by how much you trust the
codebase — the tier does the work, so you don't hand-maintain allow/deny lists.

> **Why tiers, not enumerated allowlists.** Enumerating "safe" commands does
> NOT stop prompts — the next unlisted command (`python -m alembic`,
> `npx prisma …`) prompts again. Durable zero-prompt work comes from a blanket
> allow under `dontAsk` plus **`deny` rules + the `protect-*` hooks** as the
> real safety boundary — not from prompt friction. The per-stack enumerated
> lists below are kept only as an appendix for custom middle grounds; see the
> warning there.

## The three tiers

| Tier | Prompts for repo work | Destructive guardrails | Commit/push + credential edits | Use for |
|---|---|---|---|---|
| `default` | Yes (everything) | n/a | `protect-*` hooks gate them | Shared, unfamiliar, or high-risk repos |
| `balanced` | **No** (`dontAsk`) | `deny` rules (rm -rf, sudo, force-push, hard-reset) | `protect-*` hooks still gate them | **Your own repos (recommended)** |
| `relaxed` ⚠️ | **No** | `deny` rules kept | **Disarmed** (`HOOK_*_ALLOW`) — fully autonomous | A project you fully trust and run unattended |

### `default` — current behavior, unchanged

No project `settings.json` is written; only the git-approval allows in
`settings.local.json`. Everything prompts. This is the safe default for shared
or unfamiliar codebases.

### `balanced` — zero prompts for repo work, guarded destructives

Writes `.claude/settings.json` with `permissions.defaultMode: "dontAsk"`
(auto-denies anything not allowlisted — never a stall, never a prompt), a broad
tool `allow` list, and a `deny` list that blocks the dangerous operations. The
`protect-git.sh` / `protect-files.sh` hooks still gate commits, pushes, and
credential/`.env` edits through chat approval.

```json
{
  "permissions": {
    "defaultMode": "dontAsk",
    "allow": ["Read", "Glob", "Grep", "Edit", "Write", "Bash", "WebSearch", "WebFetch"],
    "deny": [
      "Read(./.env)", "Read(./.env.local)", "Read(./.env.production)",
      "Bash(rm -rf:*)", "Bash(sudo:*)",
      "Bash(git push --force:*)", "Bash(git reset --hard:*)"
    ]
  }
}
```

Stack-specific `deny` extras are appended per template type (e.g. `web-dynamic`
adds `Bash(npx prisma migrate reset:*)`, `Bash(npx prisma db push:*)`,
`Bash(git push:*)`).

### `relaxed` (dangerous) — fully autonomous, hooks disarmed

`balanced` plus an `env` block that disarms both protect hooks:

```json
{
  "env": { "HOOK_GIT_ALLOW": "true", "HOOK_PROTECT_ALLOW": "true" }
}
```

- `HOOK_GIT_ALLOW=true` — commits and pushes run without chat approval.
- `HOOK_PROTECT_ALLOW=true` — `.env`/credential/key edits are allowed;
  consequently the `Read(./.env*)` denies are **dropped** in this tier
  (read-deny + edit-allow is incoherent).
- The Bash `deny` guardrails (rm -rf / sudo / push --force / reset --hard) are
  **kept** — `deny` wins over allow and costs zero prompts.
- **`bypassPermissions` is never used** — it would skip `deny` too.
- Writing this tier requires explicit confirmation: `--yes-dangerous`, or an
  interactive `y/N` after a loud warning.

## Applying a tier

```bash
# At init (default tier if the flag is omitted; interactive prompt in a TTY):
claude-code init web-dynamic ./my-app --permissions balanced
claude-code init web-dynamic ./my-app --permissions relaxed --yes-dangerous

# Switch an existing project onto (or off) a managed tier:
claude-code permissions balanced ./my-app
claude-code permissions relaxed  ./my-app --yes-dangerous
claude-code permissions default  ./my-app   # strips the managed keys, keeps your custom ones
```

The chosen tier is recorded in `.claude/template.json`. `claude-code sync`
**reports** permission-profile drift but never re-applies it — switching a
safety boundary is always an explicit act.

Docs recommendation: use `balanced` for personal repos; keep `default` for
shared, unfamiliar, or high-risk repos.

---

## Appendix: enumerated per-stack patterns (custom middle grounds)

> ⚠️ **These lists re-trigger prompts.** Enumeration only allows exactly what
> you list — the next unlisted command prompts again. Prefer a tier above.
> These are here only if you deliberately want a hand-tuned middle ground.

### Universal (All Stacks)

```
Read            # read any file
Glob            # search for files by pattern
Grep            # search file contents
WebFetch        # fetch public URLs
WebSearch       # web search
```

### Python Projects

```
Bash(poetry install*)       # install dependencies
Bash(poetry add*)           # add packages
Bash(pip install*)          # pip install
Bash(pytest*)               # run tests
Bash(python -m pytest*)     # run tests (module form)
Bash(mypy*)                 # type checking
Bash(ruff check*)           # linting
Bash(ruff format*)          # formatting
Bash(black*)                # formatting (alternative)
```

### Node.js Projects

```
Bash(npm install*)          # install dependencies
Bash(npm run test*)         # run tests
Bash(npm run lint*)         # linting
Bash(npm run build*)        # build
Bash(npx vitest*)           # vitest
Bash(npx playwright test*)  # e2e tests
Bash(npx tsc*)              # type checking
Bash(npx eslint*)           # linting
Bash(npx prettier*)         # formatting
```

### Java Projects

```
Bash(./gradlew test*)       # Gradle tests
Bash(./gradlew build*)      # Gradle build
Bash(./gradlew flywayMigrate*)  # DB migrations
Bash(./mvnw test*)          # Maven tests
Bash(./mvnw compile*)       # Maven compile
```

### Go Projects

```
Bash(go test*)              # run tests
Bash(go build*)             # build
Bash(go vet*)               # vet
Bash(golangci-lint*)        # linting
```

### Recommended Deny Patterns

```
Bash(rm -rf*)               # recursive delete
Bash(git push --force*)     # force push
Bash(docker rm*)            # remove containers
Bash(docker rmi*)           # remove images
Bash(npm publish*)          # publish packages
Bash(DROP TABLE*)           # destructive SQL
Bash(TRUNCATE*)             # destructive SQL
```

### Tips

- Deny patterns take precedence over Allow patterns in every mode.
- Use `*` wildcards to match command variations (e.g., `npm run test*`).
- **Always chain bash commands with `&&` on a single line** — multi-line
  commands generate unique permission strings that don't match wildcard
  patterns, causing repeated prompts even when `Bash` is allowed.
