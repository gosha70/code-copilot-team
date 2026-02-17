# Common Pitfalls & Solutions

Reference guide for issues encountered across projects and how to prevent/resolve them.

## Build & Dependencies

| Issue | Root Cause | Prevention | Solution |
|-------|-----------|------------|----------|
| **Prisma CLI errors** | Used Prisma 7.x bleeding-edge | Pin to stable 6.x in stack constraints | `npm install prisma@6.9.0 @prisma/client@6.9.0` |
| **Missing peer deps** (nodemailer) | Agent didn't install runtime deps | Agent should install or manual gate in workflow | `npm install nodemailer @types/nodemailer` |
| **Build passes but runtime fails** | Only ran `tsc`, not `npm run dev` | Always test dev server after changes | Add build verification to phase workflow |
| **Module not found: X** | New dependency added but not installed | Install immediately after code generation | Check console, `npm install <missing-pkg>` |

## Environment & Configuration

| Issue | Root Cause | Prevention | Solution |
|-------|-----------|------------|----------|
| **Auth crash on startup** | No `.env` file exists | Create `.env` in Phase 1 | `cp .env.example .env` and fill values |
| **CLIENT_FETCH_ERROR** (NextAuth) | Missing env vars → service crash | Test `npm run dev` after Phase 1 | Check terminal for actual error, add missing vars |
| **Database connection refused** | PostgreSQL not running or wrong creds | Verify DB setup before migrations | `brew services start postgresql`, check `DATABASE_URL` |
| **Environment variable validation failed** | `.env` missing required vars | Use zod validation with clear error messages | Add missing vars to `.env` |

## Data Model & Schema

| Issue | Root Cause | Prevention | Solution |
|-------|-----------|------------|----------|
| **Mid-phase schema changes** | Design doc missing entity details | Data model review gate before Phase 2 | Pause agents, update schema, regenerate client, resume |
| **Prisma generate fails** | Schema syntax error or incompatible version | Run `npx prisma validate` before generate | Fix schema errors, downgrade if version issue |
| **Migration fails** | Database doesn't exist or permissions wrong | Test connection before migration | Create database, fix `DATABASE_URL` credentials |
| **Ambiguous field names** | "name" without context | Review granularity in data model gate | Split into `firstName`/`lastName` or clarify semantics |

## Agent Coordination

| Issue | Root Cause | Prevention | Solution |
|-------|-----------|------------|----------|
| **Type errors after parallel agents** | Agents made incompatible changes | Ensure non-overlapping file ownership | Run `tsc --noEmit` after all agents complete, fix conflicts |
| **Duplicate work** | Two agents implement same feature | Clear task delegation | Review task boundaries before spawning |
| **Missing integration** | Agent A expects API agent B didn't create | Define interfaces/contracts upfront | Create stub/placeholder, implement in next phase |
| **Schema drift** | One agent changed schema mid-phase | Lock schema before parallel work | Regenerate Prisma client, update dependent code |

## Authentication & Security

| Issue | Root Cause | Prevention | Solution |
|-------|-----------|------------|----------|
| **Plain passwords in database** | No hashing implemented | Use bcrypt or avoid passwords (magic links) | Migrate to hashed passwords or NextAuth |
| **Secrets in git** | Committed `.env` by mistake | Verify `.gitignore` excludes `.env*` | Remove from history, rotate secrets, update `.gitignore` |
| **Gmail SMTP fails** | Using account password instead of App Password | Document App Password requirement | Generate App Password at myaccount.google.com/apppasswords |
| **Auth route crashes** | Missing NextAuth dependencies | Install `nodemailer` for email provider | `npm install nodemailer` |

## Testing & Validation

| Issue | Root Cause | Prevention | Solution |
|-------|-----------|------------|----------|
| **Tests pass but app crashes** | Tests don't cover real runtime paths | Always run `npm run dev` after changes | Add integration/e2e tests for critical flows |
| **UI renders but data doesn't load** | tRPC procedure returns stub data | Verify backend services wired correctly | Check router implementation, test API directly |
| **Form submits but nothing happens** | Missing mutation error handling | Add error states to all forms | Log errors, show user-friendly messages |
| **Responsive layout breaks** | Only tested on desktop | Test at multiple breakpoints | Use Tailwind responsive classes, test mobile-first |

## Performance & Optimization

| Issue | Root Cause | Prevention | Solution |
|-------|-----------|------------|----------|
| **Slow page loads** | No caching, large bundle size | Use Next.js built-in optimizations | Enable caching, code splitting, image optimization |
| **Database queries slow** | Missing indexes on foreign keys | Add indexes in Prisma schema | `@@index([fieldName])` on FK and filter fields |
| **Memory leaks** | Prisma client not reused | Use singleton pattern | Import from shared `db/client.ts` |
| **API timeouts** | Synchronous blocking operations | Use async/await, queue long tasks | Move to background jobs for heavy operations |

## Git & Deployment

| Issue | Root Cause | Prevention | Solution |
|-------|-----------|------------|----------|
| **Merge conflicts in generated files** | Multiple people ran `prisma generate` | Exclude from git if possible | Resolve manually, regenerate clean |
| **Build fails in CI but passes locally** | Different Node/npm versions | Pin versions in `package.json` engines | Use same versions, add `.nvmrc` |
| **Migrations fail in production** | Database state diverged | Never edit migrations manually | Roll back, fix locally, push clean migration |
| **Secrets exposed in logs** | Logging env vars or sensitive data | Sanitize logs, never log secrets | Remove from logs, rotate exposed secrets |
