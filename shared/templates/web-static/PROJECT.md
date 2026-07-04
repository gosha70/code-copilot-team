# Static Website

## Stack
- Framework: Astro ← UPDATE: Astro / Next.js (static export) / Hugo / 11ty
- Styling: Tailwind CSS
- Content: Markdown/MDX files in content/
- Deployment: Vercel ← UPDATE: Vercel / Netlify / Cloudflare Pages
- CMS: None (file-based) ← UPDATE if using headless CMS

## Project Structure
```
├── CLAUDE.md
├── src/
│   ├── pages/            # Route-based pages
│   ├── layouts/          # Page layouts (base, blog, landing)
│   ├── components/       # Reusable UI components
│   └── styles/           # Global styles + Tailwind config
├── content/              # Markdown/MDX content files
│   ├── blog/
│   └── pages/
├── public/               # Static assets (images, fonts, favicons)
├── specs/                    # SDD artifacts and lessons learned
└── astro.config.mjs
```

## Architecture Rules
> **Non-negotiable.** Violations must be flagged during review, not silently accepted.

- All content in Markdown/MDX with frontmatter metadata
- Images: optimized at build time; use framework's image component
- SEO: every page must have title, description, og:image meta tags
- Performance budget: Lighthouse score ≥ 95 on all categories
- Accessibility: semantic HTML, ARIA labels, keyboard navigation
- No client-side JS unless absolutely necessary (progressive enhancement)

## Content Rules
- Blog posts: frontmatter must include title, date, description, tags
- Internal links: use relative paths, never absolute URLs to own domain
- Images: always include alt text; prefer WebP format
- Code blocks: always specify language for syntax highlighting

## Mobile Support
- Mobile-first responsive design (min-width breakpoints)
- Touch targets: minimum 44x44px
- Test at: 320px, 375px, 768px, 1024px, 1440px
- No horizontal scrolling at any breakpoint

## Testing
- Visual regression: Playwright for screenshot comparison (if configured)
- Performance: Lighthouse CI for performance budget validation
- Accessibility: axe-core via Playwright or browser extension

## Commands
```bash
npm install
npm run dev                  # local dev server
npm run build                # production build
npm run preview              # preview production build
npx lighthouse http://localhost:4321 --view   # performance audit
npx playwright test          # e2e/visual tests (if configured)
```

## Browser Automation (Playwright CLI)

Playwright CLI enables Claude to interact with your running site for debugging and visual regression testing.

```bash
# One-time setup (from code-copilot-team repo)
bash adapters/claude-code/setup.sh --playwright

# Or manually
npm install -g @playwright/cli@latest
playwright-cli install --skills
```

## Design System & Visual Review

This site uses the **UI-Enhancement harness** to keep the design unique, on-brand,
and release-grade — not "AI-generated"-looking.

- **Steering bundle**: `DESIGN.md` + `design/tokens.json` at the repo root define the
  committed art direction and design tokens. Read them before building any UI.
- **Scaffold once** (if absent), then add `"copilot:review": "cd harness && npm run harness:verify"` to `package.json`:
  ```bash
  cp -r ~/.claude/templates/ui-harness/harness \
        ~/.claude/templates/ui-harness/design \
        ~/.claude/templates/ui-harness/DESIGN.md .
  ```
- **Derive** `DESIGN.md` from the site's domain/brand with the `design-system` skill;
  override the four defaults (neutral, accent, font, radius) — shipping framework
  defaults is the AI-slop tell.
- **Verify** with the `visual-review` skill: `DEV_URL=<your dev url> npm run copilot:review`
  runs the axe-core WCAG 2.2 AA gate + anti-slop rubric + screenshot critique at
  375/768/1440. On Claude Code the `visual-reviewer` agent is the critic.

## Agent Team

### Roles

| Role | Trigger | Owns |
|------|---------|------|
| **Team Lead** (default) | Planning, site architecture, content strategy | Overall coordination |
| **Frontend Developer** | Components, layouts, styling, interactivity | `src/` |
| **Content & SEO Specialist** | Content structure, metadata, accessibility, performance | `content/`, SEO meta |
| **QA Engineer** | Cross-browser testing, Lighthouse audits, accessibility checks | Testing |

### Team Lead — Default Behavior
You ARE the Team Lead. Static sites are simpler, so you handle most tasks directly.
Delegate only when a task is heavily specialized (e.g., complex animation, SEO audit).

### Frontend Developer
Expertise: Astro/Next.js components, Tailwind CSS, responsive design, progressive enhancement, build optimization.
Constraints: no client-side JS unless essential. Mobile-first breakpoints. Semantic HTML. Components must be accessible (ARIA). Read `DESIGN.md` + the `design-system` skill before building UI; use `design/tokens.json` semantic tokens (never framework defaults).

### Content & SEO Specialist
Expertise: content structure, frontmatter schemas, meta tags, Open Graph, structured data (JSON-LD), Lighthouse optimization, accessibility auditing.
Constraints: every page has title + description + og:image. Alt text on all images. Lighthouse ≥ 95. No broken internal links.

### QA Engineer
Expertise: cross-browser testing, responsive testing, Lighthouse CI, accessibility auditing (axe-core), link validation.
Constraints: test at all 5 breakpoints. Run Lighthouse after every significant change. Validate HTML semantics. Check all links. Run `npm run copilot:review` (visual-review loop) and resolve findings in `tmp/ui-review/critique-feedback.json`.
