# Agent Safety Rules

Non-negotiable safety constraints for all sessions.

## Confirmation Required Before

- Any destructive command: rm -rf, DROP TABLE, TRUNCATE, git reset --hard, git push --force.
- Any deployment or publish action.
- Any command that modifies production data.
- Any command with side effects outside the working directory.

## Secrets & Credentials

- Never hard-code API keys, tokens, passwords, or connection strings in source.
- Strip secrets from all output before displaying.
- Never commit .env files or credential files.
- If a secret is found in code, flag it immediately.

## Password Storage

- **Never store plain passwords** in the database
- Always hash passwords before storing using `bcrypt` or `argon2`:
  ```typescript
  import bcrypt from 'bcryptjs';

  // On registration
  const passwordHash = await bcrypt.hash(plainPassword, 10);

  // On login
  const isValid = await bcrypt.compare(plainPassword, storedHash);
  ```
- Use a salt rounds value of 10+ for bcrypt
- Consider using NextAuth with email magic links to avoid password storage entirely

## Environment Variables

- `.env` files are safe for **local development only** (never committed to git)
- **Production**: use hosting platform env var UI (Vercel, AWS, Railway, etc.)
- App-specific passwords (Gmail App Password, OAuth tokens) are single-use and less sensitive than account passwords
- Always validate env vars at startup with zod or similar
- Use different secrets per environment (dev/staging/production)

## Input Validation

- Validate and sanitize all external inputs at system boundaries.
- Never trust user input for SQL, shell commands, or file paths without sanitization.
- Apply principle of least privilege for service accounts and keys.

## Dependencies

- Keep dependencies updated.
- Review new dependencies before adding (license, maintenance status, security advisories).
- Prefer well-maintained libraries with active communities.
