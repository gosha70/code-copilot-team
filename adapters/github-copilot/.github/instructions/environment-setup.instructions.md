---
applyTo: "**/.env*,**/docker-compose*"
---

# Environment Setup Protocol

Rules for managing environment variables, secrets, and local configuration across any stack.

## Core Principle

Every project should have a template/example config file checked into source control, and the actual config file (with real values) gitignored. The developer copies the template and fills in real values locally.

## Common Patterns by Stack

| Stack | Template File | Actual File | Gitignored |
|---|---|---|---|
| Node.js / Python | `.env.example` | `.env` | `.env` |
| Java / Spring | `application-example.yml` | `application.yml` | `application.yml` |
| Go | `config.example.yaml` | `config.yaml` | `config.yaml` |
| Docker | `docker-compose.override.example.yml` | `docker-compose.override.yml` | `docker-compose.override.yml` |

## Phase 1: Initial Setup

During scaffolding, before the first build/run:

1. **Copy the template** — `cp .env.example .env` (or equivalent for your stack).
2. **Fill minimum required values** — database URL, secret keys, API credentials.
3. **Verify .gitignore** — confirm the actual config file is excluded.
4. **Test the build** — run the dev server to validate config is loaded correctly.

## Environment Variable Validation

Always validate required environment variables at startup. Fail fast with clear error messages rather than crashing with cryptic errors later.

```
# Pseudocode — adapt to your language/framework

required_vars = ["DATABASE_URL", "SECRET_KEY", "API_BASE_URL"]

for var in required_vars:
    if var not set or empty:
        raise Error("Missing required environment variable: {var}")
```

Most frameworks have libraries for this (e.g., Zod + dotenv for Node, pydantic-settings for Python, Spring @ConfigurationProperties for Java).

## Security Best Practices

**Local development:**
- Use real credentials for local services (database, SMTP, etc.).
- Never commit the actual config file.
- Use app-specific passwords where available (not your personal account password).

**Production:**
- Never use `.env` files in production. Use the platform's secret management (e.g., cloud provider secrets manager, Kubernetes secrets, CI/CD variables).
- Rotate credentials periodically.
- Use least-privilege service accounts.

**Team sharing:**
- Keep the template file updated with all required variables (use placeholder values).
- Document where to obtain each credential (e.g., "Get from team password manager" or "Generate at https://...").
- Never share secrets via chat, email, or committed files.

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| App crashes on startup | Missing required env var | Check template file, add missing vars to local config |
| "Connection refused" errors | Service not running or wrong credentials | Verify the service is running, check URL and credentials |
| "Module not found" at runtime | Missing runtime dependency | Install the dependency (may not be caught by type checkers) |
| Auth/login fails | Missing or incorrect secret key | Regenerate and set the secret key in local config |
