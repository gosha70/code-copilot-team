// check-site.mjs — assert the built site publishes what the registry lists,
// and that nothing links into a page that does not exist (#214 Phase 4.1).
//
// Run after `astro build`: `npm run check` does both.
import { readFile, readdir, stat } from "node:fs/promises";
import { existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const SITE = dirname(fileURLToPath(import.meta.url));
const DIST = join(SITE, "dist");
const REPO = resolve(SITE, "..");
const registry = JSON.parse(
  await readFile(join(REPO, "scripts/session_analytics/config_data/learn-sections.json"), "utf8"),
);
const data = JSON.parse(await readFile(join(SITE, "site-data.generated.json"), "utf8"));
const base = process.env.SITE_BASE ?? `/${registry.repo_url.split("/").pop()}`;

let failures = 0;
const fail = (msg) => { console.error(`  FAIL: ${msg}`); failures += 1; };
const ok = (msg) => console.log(`  PASS: ${msg}`);

if (!existsSync(DIST)) {
  fail("dist/ does not exist — run `npm run build` first");
  process.exit(1);
}

// 1. Every registered document has a page.
const expected = [...new Set((registry.sections || []).flatMap((s) => s.paths || []))];
for (const rel of expected) {
  const slug = rel === "README.md" ? "index"
    : rel === "docs/README.md" ? "documentation"
    : rel.replace(/\.md$/, "").replace(/^docs\//, "").replace(/\//g, "-").toLowerCase();
  const page = join(DIST, slug === "index" ? "index.html" : join(slug, "index.html"));
  existsSync(page) ? ok(`published: ${rel}`) : fail(`registered but not published: ${rel} (expected ${slug}/)`);
}

// 2. Search is built (Starlight ships Pagefind; a silent miss loses search).
existsSync(join(DIST, "pagefind", "pagefind.js"))
  ? ok("search index built")
  : fail("no Pagefind index in dist/ — search would be missing");

// 3. The release banner is on every page: the site documents the default
//    branch while the Quick Start installs the tag.
const pages = [];
const walk = async (dir) => {
  for (const entry of await readdir(dir)) {
    const full = join(dir, entry);
    if ((await stat(full)).isDirectory()) await walk(full);
    else if (entry.endsWith(".html")) pages.push(full);
  }
};
await walk(DIST);
const missingBanner = [];
for (const page of pages) {
  const html = await readFile(page, "utf8");
  if (!html.includes(data.branch) || !html.includes("unreleased")) missingBanner.push(page);
}
missingBanner.length === 0
  ? ok(`release banner on all ${pages.length} pages`)
  : fail(`${missingBanner.length} page(s) without the unreleased banner, e.g. ${missingBanner[0]}`);

// 4. No internal link points at a page the build did not produce.
const dead = new Set();
for (const page of pages) {
  const html = await readFile(page, "utf8");
  for (const [, href] of html.matchAll(/href="([^"]+)"/g)) {
    if (!href.startsWith(base + "/") || href.startsWith(base + "/pagefind")) continue;
    const clean = href.split("#")[0].split("?")[0].slice(base.length);
    if (!clean || clean === "/") continue;
    const target = join(DIST, clean.endsWith("/") ? join(clean, "index.html") : clean);
    if (!existsSync(target) && !existsSync(join(DIST, clean))) dead.add(`${href} (from ${page.slice(DIST.length)})`);
  }
}
dead.size === 0 ? ok("no dead internal links") : [...dead].forEach((d) => fail(`dead link: ${d}`));

console.log("=".repeat(41));
console.log(`  Site: ${pages.length} pages, ${expected.length} registered documents, ${failures} failed`);
console.log("=".repeat(41));
process.exit(failures ? 1 : 0);
