// build-content.mjs — stage the repository's documentation for Starlight.
//
// The repository is the single source of documentation, and the Studio's Learn
// tab serves it through scripts/session_analytics/config_data/learn-sections.json.
// The site reads the SAME registry and stages those files into
// site/src/content/docs/, which is gitignored: a build artifact, never a second
// tracked copy to drift.
//
// While staging, every repo-relative link is rewritten:
//   - to another staged document  -> the site route
//   - to any other repo file      -> a GitHub blob URL on the default branch
//   - to an image under docs/images -> a file copied into site/public/images
// A link that cannot be resolved fails the build rather than shipping a 404.
import { mkdir, readFile, writeFile, rm, copyFile, readdir } from "node:fs/promises";
import { existsSync } from "node:fs";
import { dirname, join, relative, resolve, basename, extname } from "node:path";
import { fileURLToPath } from "node:url";

const SITE = dirname(fileURLToPath(import.meta.url));
const REPO = resolve(SITE, "..");
const REGISTRY = join(REPO, "scripts/session_analytics/config_data/learn-sections.json");
const OUT = join(SITE, "src/content/docs");
const PUBLIC_IMAGES = join(SITE, "public/images");

const registry = JSON.parse(await readFile(REGISTRY, "utf8"));
const BLOB = `${registry.repo_url}/blob/${registry.repo_branch}`;
// A project site is served under /<repo>/, so a root-relative link written
// into markdown must carry that prefix — Astro does not add it to link
// targets inside content. SITE_BASE lets a fork or custom domain build at /.
const BASE = (process.env.SITE_BASE ?? `/${registry.repo_url.split("/").pop()}`).replace(/\/$/, "");
// The registry marks each section's kind. "doc" sections are documentation and
// belong on the site — including the three that are declared as globs
// (adapters/claude-code/docs, adapters/pi/docs, shared/docs), which an earlier
// version silently dropped. Skills, agents and wiki pages are instruction files
// the Studio serves; they stay off the site, and site-data records that choice
// rather than leaving it implicit.
const SITE_KINDS = ["doc"];

/** Registry path -> site slug. docs/foo.md -> foo; README.md -> index. */
function slugFor(rel) {
  if (rel === "README.md") return "index";
  const withoutExt = rel.replace(/\.md$/, "");
  if (withoutExt === "docs/README") return "documentation";
  // Keep the adapter and shared guides in named folders rather than flattening
  // them into adapters-claude-code-docs-hooks-guide.
  const adapter = withoutExt.match(/^adapters\/([^/]+)\/docs\/(.+)$/);
  if (adapter) return `${adapter[1]}/${adapter[2]}`.toLowerCase();
  const shared = withoutExt.match(/^shared\/docs\/(.+)$/);
  if (shared) return `shared/${shared[1]}`.toLowerCase();
  return withoutExt.replace(/^docs\//, "").replace(/\//g, "-").toLowerCase();
}

/** A page title is text, not markup: an H1 may carry bold, code spans or
 *  links, and the sidebar showed one as "**🎛️ Claude Code Setup Cookbook**".
 *  Emphasis and backticks are stripped; a link keeps its text. */
function plainText(text) {
  return text
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/(\*\*|__)(.+?)\1/g, "$2")
    .replace(/(^|\s)([*_])(\S(?:.*?\S)?)\2(?=\s|$)/g, "$1$3")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/\s+/g, " ")
    .trim();
}

function titleFrom(rel, body) {
  // The home page is the site, not a document called "README".
  if (rel === "README.md") return "Code Copilot Team";
  if (registry.titles?.[rel]) return plainText(registry.titles[rel]);
  const h1 = body.split("\n").find((l) => l.startsWith("# "));
  return h1 ? plainText(h1.slice(2)) : basename(rel, ".md");
}

/** Expand a registry glob. Only "<dir>/*.<ext>" is supported — an unknown
 *  shape is an error, never a silently empty section. */
async function expand(pattern) {
  const match = pattern.match(/^(.*)\/\*\.([A-Za-z0-9]+)$/);
  if (!match) {
    console.error(`[ERROR] unsupported glob in the Learn registry: ${pattern}`);
    process.exit(1);
  }
  const [, dir, ext] = match;
  if (!existsSync(join(REPO, dir))) {
    console.error(`[ERROR] the registry globs a directory that does not exist: ${dir}`);
    process.exit(1);
  }
  const deny = registry.deny_prefixes || [];
  const found = (await readdir(join(REPO, dir)))
    .filter((f) => f.endsWith(`.${ext}`))
    .map((f) => `${dir}/${f}`)
    .filter((rel) => !deny.some((p) => rel.startsWith(p)))
    .sort();
  if (!found.length) {
    console.error(`[ERROR] the registry glob ${pattern} matched nothing`);
    process.exit(1);
  }
  return found;
}

const sections = [];
for (const section of registry.sections || []) {
  if (!SITE_KINDS.includes(section.kind)) continue;
  const paths = [...(section.paths || [])];
  for (const pattern of section.globs || []) paths.push(...(await expand(pattern)));
  if (paths.length) sections.push({ ...section, paths });
}
if (!sections.length) {
  console.error("[ERROR] the Learn registry yielded no documents — nothing to stage");
  process.exit(1);
}

const staged = new Map(); // repo-relative path -> { slug, title, section }
for (const section of sections) {
  for (const rel of section.paths) {
    if (!existsSync(join(REPO, rel))) {
      console.error(`[ERROR] the registry lists a file that does not exist: ${rel}`);
      process.exit(1);
    }
    if (!staged.has(rel)) staged.set(rel, { slug: slugFor(rel), section: section.title });
  }
}

await rm(OUT, { recursive: true, force: true });
await mkdir(OUT, { recursive: true });
await mkdir(PUBLIC_IMAGES, { recursive: true });
for (const image of await readdir(join(REPO, registry.image_dir))) {
  if ([".png", ".jpg", ".jpeg", ".svg", ".gif", ".webp"].includes(extname(image).toLowerCase())) {
    await copyFile(join(REPO, registry.image_dir, image), join(PUBLIC_IMAGES, image));
  }
}

let unresolved = 0;
function rewrite(target, fromRel) {
  if (/^(https?:|mailto:|#)/.test(target)) return target;
  const [path, hash = ""] = target.split("#");
  const anchor = hash ? `#${hash}` : "";
  if (!path) return target;
  // Resolve relative to the file's own directory, as markdown does.
  const abs = resolve(REPO, dirname(fromRel), path);
  const rel = relative(REPO, abs);
  if (rel.startsWith("..")) return target; // outside the repo; leave alone
  if (staged.has(rel)) {
    const slug = staged.get(rel).slug;
    return slug === "index" ? `${BASE}/${anchor}` : `${BASE}/${slug}/${anchor}`;
  }
  if (rel.startsWith(registry.image_dir + "/")) return `${BASE}/images/${basename(rel)}${anchor}`;
  if (!existsSync(abs)) {
    console.error(`[ERROR] ${fromRel} links to ${rel}, which does not exist`);
    unresolved += 1;
    return target;
  }
  return `${BLOB}/${rel}${anchor}`; // a real file with no page: send them to GitHub
}

for (const [rel, meta] of staged) {
  const body = await readFile(join(REPO, rel), "utf8");
  const title = titleFrom(rel, body);
  let content = body
    // Starlight renders the title itself; strip the page's own H1, in either
    // markdown or the HTML form the README uses for its logo block, or every
    // page shows its name twice.
    .replace(/^<h1>[\s\S]*?<\/h1>/, "")
    .replace(/^#\s+.*$/m, "")
    .replace(/\]\(([^)\s]+)\)/g, (m, t) => `](${rewrite(t, rel)})`)
    .replace(/<img\s+[^>]*src="([^"]+)"[^>]*>/g, (m, src) =>
      src.startsWith("/docs/images/") ? m.replace(src, `${BASE}/images/${basename(src)}`) : m);
  const frontmatter = [
    "---",
    `title: ${JSON.stringify(title)}`,
    `editUrl: ${JSON.stringify(`${BLOB}/${rel}`)}`,
    "---",
    "",
  ].join("\n");
  meta.title = title;                               // the sidebar reads it back
  const file = join(OUT, `${meta.slug}.md`);
  await mkdir(dirname(file), { recursive: true });
  await writeFile(file, frontmatter + content.trimStart(), "utf8");
}

// Values the site's own components need at render time, written into the
// project root: a component that read the registry with readFileSync broke
// once Astro bundled it, because import.meta.url no longer pointed at the
// source file.
await writeFile(
  join(SITE, "site-data.generated.json"),
  JSON.stringify(
    {
      branch: registry.repo_branch,
      repoUrl: registry.repo_url,
      releasesUrl: `${registry.repo_url}/releases`,
      documentCount: staged.size,
      // The manifest is the contract between the builder and check-site.mjs.
      // Recomputing slugs there let the checker inherit the builder's blind
      // spot: both skipped the glob sections and both called it clean.
      documents: [...staged].map(([rel, meta]) => ({ path: rel, slug: meta.slug, section: meta.section })),
      excludedKinds: (registry.sections || [])
        .filter((s) => !SITE_KINDS.includes(s.kind))
        .map((s) => ({ id: s.id, kind: s.kind, title: s.title })),
    },
    null,
    2,
  ) + "\n",
  "utf8",
);

// The sidebar is the registry's own grouping, so the site, the landing page
// and the Studio present the documentation in the same order.
const sidebar = sections.map((s) => ({
  label: s.title,
  // Starlight prefixes the base itself for sidebar links, so these stay bare.
  items: s.paths.map((rel) => {
    const slug = slugFor(rel);
    return { label: staged.get(rel)?.title ?? rel, link: slug === "index" ? "/" : `/${slug}/` };
  }),
}));
await writeFile(join(SITE, "sidebar.generated.json"), JSON.stringify(sidebar, null, 2) + "\n", "utf8");

if (unresolved) {
  console.error(`[ERROR] ${unresolved} unresolved link(s) — refusing to build a site with dead links`);
  process.exit(1);
}
console.log(`[OK] staged ${staged.size} documents in ${sections.length} sections`);
