# Stack Constraints

## Prisma Version Management

- **Use Prisma 6.x (stable)** — avoid 7.x until production-ready
- Always use traditional `datasource` format:
  ```prisma
  datasource db {
    provider = "postgresql"
    url      = env("DATABASE_URL")
  }
  ```
- Avoid early-access features that break CLI tooling
- If Prisma 7 is installed, downgrade: `npm install prisma@6.9.0 @prisma/client@6.9.0`

## Dependency Installation Protocol

When agents create code requiring new packages:

1. **Agent should install dependencies as part of their task** (if they have Bash permission)
2. **If agent lacks permission**, pause and install manually before continuing
3. **Always test build after new dependencies**: run `npm run dev`, not just `tsc --noEmit`
4. Common missing peer deps:
   - `nodemailer` (NextAuth email provider)
   - `bcrypt` / `bcryptjs` (password hashing)
   - `@types/*` packages for TypeScript types

## Technology Version Pinning

When starting a new project, prefer stable, well-documented versions over bleeding-edge:

- **Prisma**: 6.x (not 7.x)
- **Next.js**: LTS or latest stable (avoid canary unless required)
- **React**: Stable release
- **TypeScript**: Latest stable (not beta/rc)

Check package documentation for "stable" vs "experimental" badges before adopting.
