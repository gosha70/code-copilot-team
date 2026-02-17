# Environment Setup Protocol

## .env File Management

- **Always create `.env` from `.env.example`** at project start (Phase 1)
- `.env` must exist before first `npm run dev` or services requiring env validation will crash
- Add `.env` to `.gitignore` (verify it's excluded)
- Validate `.env` completeness before running agents that depend on database/auth/email

## Phase 1: Initial Setup

After scaffolding the project, immediately:

1. Copy example file:
   ```bash
   cp .env.example .env
   ```

2. Fill in **minimum required values** for local development:
   - `DATABASE_URL` — local PostgreSQL connection string
   - `NEXTAUTH_SECRET` — generate with `openssl rand -base64 32`
   - `NEXTAUTH_URL` — `http://localhost:3000` (or your dev port)
   - Email vars can use placeholders initially if not testing auth

3. Test that env validation passes:
   ```bash
   npm run dev
   ```
   If `env.ts` validation fails, add missing vars to `.env`

## Environment Variable Validation

Use zod to validate env vars at startup:

```typescript
// src/lib/env.ts
import { z } from "zod";

const envSchema = z.object({
  DATABASE_URL: z.string().url(),
  NEXTAUTH_URL: z.string().url(),
  NEXTAUTH_SECRET: z.string().min(1),
  ADMIN_EMAIL: z.string().email(),
  EMAIL_SERVER: z.string().min(1),
  EMAIL_FROM: z.string().min(1),
});

export const env = envSchema.parse(process.env);
```

This crashes fast with clear error messages if env vars are missing or invalid.

## Security Best Practices

### Local Development

- `.env` contains real credentials for your local database/email
- Never commit `.env` to git (verify `.gitignore` includes `.env*`)
- Use app-specific passwords (Gmail App Password, not your real password)

### Production Deployment

- **Never put production secrets in `.env` files**
- Use hosting platform environment variable UI (Vercel, AWS, Railway, etc.)
- Rotate secrets regularly
- Use different values per environment (dev/staging/production)

### Sharing with Team

- Keep `.env.example` updated with all required var names
- Use placeholder values in `.env.example` (not real secrets)
- Document where to get real values (e.g., "Get DATABASE_URL from team lead")

## Common Environment Variables

| Variable | Purpose | Example |
|----------|---------|---------|
| `DATABASE_URL` | PostgreSQL connection string | `postgresql://user:pass@localhost:5432/dbname` |
| `NEXTAUTH_SECRET` | NextAuth JWT signing key | `openssl rand -base64 32` |
| `NEXTAUTH_URL` | Public URL of your app | `http://localhost:3000` (dev) or `https://example.com` (prod) |
| `ADMIN_EMAIL` | Admin user email for auth gate | `admin@example.com` |
| `EMAIL_SERVER` | SMTP server for sending emails | `smtp://user:pass@smtp.gmail.com:587` |
| `EMAIL_FROM` | Sender email address | `noreply@example.com` |

## Gmail SMTP Setup

For Gmail, use an App Password (not your regular password):

1. Enable 2-Step Verification on your Google account
2. Go to https://myaccount.google.com/apppasswords
3. Create an App Password for "Mail"
4. Use the 16-character password in `EMAIL_SERVER`:
   ```
   EMAIL_SERVER="smtp://your.email@gmail.com:APP_PASSWORD@smtp.gmail.com:587"
   EMAIL_FROM="your.email@gmail.com"
   ```

## Troubleshooting

### "Module not found" errors on startup

- Missing runtime dependency (e.g., `nodemailer` for NextAuth email)
- Install the missing package: `npm install <package>`

### "Environment variable validation failed"

- Missing var in `.env`
- Add the missing var with a valid value

### "Database connection refused"

- PostgreSQL not running: `brew services start postgresql@16`
- Wrong credentials in `DATABASE_URL`
- Database doesn't exist: `createdb <dbname>`
