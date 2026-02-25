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
└── astro.config.mjs
```

## Conventions
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

## Commands
```bash
npm install
npm run dev                  # local dev server
npm run build                # production build
npm run preview              # preview production build
npx lighthouse http://localhost:4321 --view   # performance audit
```

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
Constraints: no client-side JS unless essential. Mobile-first breakpoints. Semantic HTML. Components must be accessible (ARIA).

### Content & SEO Specialist
Expertise: content structure, frontmatter schemas, meta tags, Open Graph, structured data (JSON-LD), Lighthouse optimization, accessibility auditing.
Constraints: every page has title + description + og:image. Alt text on all images. Lighthouse ≥ 95. No broken internal links.

### QA Engineer
Expertise: cross-browser testing, responsive testing, Lighthouse CI, accessibility auditing (axe-core), link validation.
Constraints: test at all 5 breakpoints. Run Lighthouse after every significant change. Validate HTML semantics. Check all links.
