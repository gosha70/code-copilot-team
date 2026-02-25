# Claude Code Permission Patterns Guide

Recommended `/permissions` Allow and Deny patterns for Claude Code projects. These reduce friction on safe commands while blocking destructive operations.

## How Permissions Work

Claude Code's permission system controls which tools and commands the agent can execute without asking. Configure via `/permissions` in a Claude session or edit `~/.claude/settings.json` directly.

Patterns are matched against tool names and command arguments:
- `Allow` — automatically approved, no confirmation prompt
- `Deny` — always blocked, Claude cannot execute

## Recommended Allow Patterns

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

## Recommended Deny Patterns

```
Bash(rm -rf*)               # recursive delete
Bash(git push*)             # push to remote
Bash(git push --force*)     # force push
Bash(docker rm*)            # remove containers
Bash(docker rmi*)           # remove images
Bash(npm publish*)          # publish packages
Bash(pip upload*)           # upload packages
Bash(DROP TABLE*)           # destructive SQL
Bash(TRUNCATE*)             # destructive SQL
```

## Setup Instructions

### Via CLI

```bash
# Open permissions UI
claude
# Then type: /permissions
```

### Via settings.json

Add to `~/.claude/settings.json`:

```json
{
  "permissions": {
    "allow": [
      "Read",
      "Glob",
      "Grep",
      "Bash(npm run test*)",
      "Bash(npx tsc*)"
    ],
    "deny": [
      "Bash(rm -rf*)",
      "Bash(git push*)"
    ]
  }
}
```

### Project-Level Permissions

Add to `.claude/settings.json` in your project root for project-specific patterns. Project permissions are merged with global permissions.

## Tips

- Start conservative — you can always add more Allow patterns as you build trust.
- Deny patterns take precedence over Allow patterns.
- Use `*` wildcards to match command variations (e.g., `npm run test*` matches `npm run test`, `npm run test:unit`).
- Review permissions periodically with `/permissions` to see what's configured.
