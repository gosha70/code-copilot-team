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
const RAW_DIRS = ["skills", "agents", "wiki"]; // served by Learn, not by the site

/** Registry path -> site slug. docs/foo.md -> foo; README.md -> index. */
function slugFor(rel) {
  if (rel === "README.md") return "index";
  const withoutExt = rel.replace(/\.md$/, "");
  if (withoutExt === "docs/README") return "documentation";
  return withoutExt.replace(/^docs\//, "").replace(/\//g, "-").toLowerCase();
}

function titleFrom(rel, body) {
  // The home page is the site, not a document called "README".
  if (rel === "README.md") return "Code Copilot Team";
  if (registry.titles?.[rel]) return registry.titles[rel];
  const h1 = body.split("\n").find((l) => l.startsWith("# "));
  return h1 ? h1.slice(2).trim() : basename(rel, ".md");
}

const sections = (registry.sections || []).filter((s) => (s.paths || []).length);
if (!sections.length) {
  console.error("[ERROR] the Learn registry lists no explicit paths — nothing to stage");
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
  JSON.stringify({ branch: registry.repo_branch, repoUrl: registry.repo_url,
                   releasesUrl: `${registry.repo_url}/releases`,
                   documentCount: staged.size }, null, 2) + "\n",
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
