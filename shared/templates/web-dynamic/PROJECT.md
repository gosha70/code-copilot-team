# Dynamic Web Application

## Stack
- Framework: Next.js 14+ (App Router) ← UPDATE: Next.js / Remix / Nuxt
- Language: TypeScript (strict mode)
- Styling: Tailwind CSS + shadcn/ui components
- Database: PostgreSQL via Prisma ORM ← UPDATE per project
- Auth: NextAuth.js ← UPDATE: NextAuth / Clerk / Auth0
- Deployment: Vercel ← UPDATE per project
- API: tRPC for type-safe API ← UPDATE: tRPC / REST / GraphQL

## Project Structure
```
├── CLAUDE.md
├── src/
│   ├── app/                    # Next.js App Router pages + layouts
│   │   ├── (auth)/             # Auth-required route group
│   │   ├── (public)/           # Public route group
│   │   ├── api/                # API routes (or tRPC router)
│   │   ├── layout.tsx
│   │   └── page.tsx
│   ├── components/
│   │   ├── ui/                 # Base UI components (shadcn)
│   │   └── features/           # Feature-specific components
│   ├── lib/                    # Utilities, config, helpers
│   ├── server/                 # Server-only code
│   │   ├── db/                 # Prisma client + helpers
│   │   ├── auth/               # Auth configuration
│   │   └── services/           # Business logic
│   └── types/                  # Shared TypeScript types
├── prisma/
│   ├── schema.prisma
│   └── migrations/
├── public/
├── tests/
└── specs/                    # SDD artifacts and lessons learned
```

## Architecture Rules
> **Non-negotiable.** Violations must be flagged during review, not silently accepted.

- Server Components by default; Client Components only when needed (interactivity)
- Data fetching in Server Components or Route Handlers; never in Client Components
- Business logic in src/server/services/; components should be thin
- Type safety end-to-end: DB schema → Prisma types → API → frontend
- Environment variables: validate with zod at startup, never use raw process.env

## Database Conventions
- Prisma as ORM; migrations via `prisma migrate`
- All models: id (cuid), createdAt, updatedAt fields
- Use Prisma transactions for multi-step operations
- Soft delete preferred (deletedAt field) over hard delete
- Index any field used in WHERE or ORDER BY queries

## Auth & Security
- Auth check at layout level for protected route groups
- API routes: validate auth + permissions before processing
- CSRF protection on all mutation endpoints
- Input validation: zod schemas on all API inputs
- Rate limiting on auth endpoints

## Mobile Support
- Responsive-first design using Tailwind breakpoints (sm/md/lg/xl)
- Touch targets: minimum 44x44px
- PWA support: manifest.json + service worker ← optional, UPDATE if needed
- Test at: 320px, 375px, 768px, 1024px, 1440px
- Bottom navigation pattern for mobile; sidebar for desktop

## Testing
- Unit: Vitest for utilities and server logic
- Component: React Testing Library
- Integration: Playwright for critical user flows
- Smoke: Playwright smoke project for critical-path validation
- API: supertest or direct tRPC caller tests

## Commands
```bash
npm install
npm run dev                              # dev server
npm run build && npm start               # production
npx prisma migrate dev                   # apply migrations
npx prisma studio                        # DB GUI
npx playwright test                      # e2e tests
npx playwright test --project=smoke      # quick smoke tests only
npm run test                             # unit + component tests
```

## Browser Automation (Playwright CLI)

Playwright CLI enables Claude to interact with your running app for debugging, visual testing, and e2e validation.

```bash
# One-time setup (from code-copilot-team repo)
bash adapters/claude-code/setup.sh --playwright

# Or manually
npm install -g @playwright/cli@latest
playwright-cli install --skills
```

## Design System & Visual Review

This project uses the **UI-Enhancement harness** to keep generated UI unique,
on-brand, and release-grade — not "AI-generated"-looking.

- **Steering bundle**: `DESIGN.md` + `design/tokens.json` at the repo root define the
  committed art direction and design tokens. Read them before building any UI.
- **Scaffold once** (if absent), then add `"copilot:review": "cd harness && npm run harness:verify"` to `package.json`:
  ```bash
  cp -r ~/.claude/templates/ui-harness/harness \
        ~/.claude/templates/ui-harness/design \
        ~/.claude/templates/ui-harness/DESIGN.md .
  ```
- **Derive** `DESIGN.md` from the app's domain with the `design-system` skill; override
  the four defaults (neutral, accent, font, radius) — shipping framework defaults is the
  AI-slop tell.
- **Verify** with the `visual-review` skill: `npm run copilot:review` runs the axe-core
  WCAG 2.2 AA gate + anti-slop rubric + screenshot critique at 375/768/1440. On Claude
  Code the `visual-reviewer` agent is the critic. Iterate ≤3 to the design bar.

## Agent Team

### Roles

| Role | Trigger | Owns |
|------|---------|------|
| **Team Lead / Architect** (default) | Planning, feature design, API contracts, code review | Overall, `src/types/` |
| **Frontend Developer** | React components, pages, styling, client interactivity | `src/app/`, `src/components/` |
| **Backend Developer** | API routes, services, auth, DB operations | `src/server/`, `prisma/`, `src/app/api/` |
| **QA Engineer** | Testing at all layers, Playwright e2e, accessibility | `tests/` |
| **DevOps / Release Engineer** | Deployment, CI/CD, environment config, performance | Vercel/infra config |

### Team Lead / Architect — Default Behavior
You ARE the Team Lead. You own the contract between frontend and backend:
1. API design: tRPC router shape, or REST endpoint contracts, or GraphQL schema.
2. Feature decomposition: split into frontend + backend tasks, delegate accordingly.
3. Type definitions in `src/types/` are shared — you maintain them.
4. Single-layer changes → handle directly. Full-stack features → delegate.

### Delegation Prompts
```
You are the [ROLE] on a Next.js full-stack application.

Architecture: App Router, Server Components by default. tRPC/REST for API.
DB: PostgreSQL via Prisma. Auth: NextAuth.js. Styling: Tailwind + shadcn.

Your task: [specific task description]

Constraints:
- TypeScript strict mode, no `any` types
- Server Components by default; 'use client' only when needed
- Business logic in src/server/services/ (not in components)
- [role-specific constraints below]
- Return: code changes + summary
```

### Frontend Developer
Expertise: React 18+ (Server/Client Components), Next.js App Router, Tailwind CSS, shadcn/ui, responsive design, form handling, loading/error states.
Constraints: Server Components by default. 'use client' only for interactivity (hooks, event handlers). No data fetching in Client Components. Use Suspense for loading states. All inputs validated with zod. Responsive at all breakpoints. Read `DESIGN.md` + the `design-system` skill before building UI; use `design/tokens.json` semantic tokens (never framework defaults); ship empty/loading/error/success/focus states.

### Backend Developer
Expertise: Next.js API routes, tRPC, Prisma ORM, NextAuth, zod validation, server-only utilities, middleware.
Constraints: all inputs validated with zod before processing. Auth checked before any data access. Prisma transactions for multi-step ops. No raw SQL. Soft delete by default. Environment vars validated at startup.

### QA Engineer
Expertise: Vitest, React Testing Library, Playwright, accessibility testing, API testing, load testing.
Constraints: unit tests for all server services (Vitest). Component tests with RTL. E2e tests in Playwright for critical flows (auth, CRUD, checkout). Check responsive at all breakpoints. Accessibility audit with axe-core. Run `npm run copilot:review` (visual-review loop) and resolve findings in `tmp/ui-review/critique-feedback.json`.

### DevOps / Release Engineer
Expertise: Vercel deployment, environment management, CI/CD, Prisma migration deployment, monitoring, performance optimization.
Constraints: all env vars documented. Prisma migrations run automatically on deploy. Preview deployments for all PRs. Lighthouse performance budget ≥ 90. Error tracking configured (Sentry or similar).
