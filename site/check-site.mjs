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

// 1. Every staged document has a page. The manifest is the builder's own
//    record — recomputing slugs here is what let the checker inherit the
//    builder's blind spot and call an incomplete site clean (#357 review).
const expected = data.documents ?? [];
if (!expected.length) fail("site-data.generated.json lists no documents — did the build run?");
for (const { path: rel, slug } of expected) {
  const page = join(DIST, slug === "index" ? "index.html" : join(slug, "index.html"));
  existsSync(page) ? ok(`published: ${rel}`) : fail(`staged but not published: ${rel} (expected ${slug}/)`);
}

// 1b. Every documentation section in the registry reaches the site. A section
//     declared as a glob was silently dropped before; an excluded kind has to
//     be excluded on purpose, and the manifest says which.
const registrySections = registry.sections ?? [];
const excluded = new Set((data.excludedKinds ?? []).map((s) => s.id));
for (const section of registrySections) {
  if (excluded.has(section.id)) {
    ok(`deliberately not on the site: ${section.id} (${section.kind})`);
    continue;
  }
  const staged = expected.filter((d) => d.section === section.title).length;
  staged > 0
    ? ok(`section published: ${section.title} (${staged} documents)`)
    : fail(`registry section "${section.title}" reached the site with no documents`);
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

// 4. No internal link points at a page the build did not produce — and no
//    fragment points at an anchor that page does not have. Discarding the
//    fragment hid four links into README sections that Phase 3 had moved out.
const anchors = new Map(); // page path -> Set of ids
for (const page of pages) {
  const html = await readFile(page, "utf8");
  const ids = new Set();
  for (const [, id] of html.matchAll(/\sid="([^"]+)"/g)) ids.add(id);
  for (const [, name] of html.matchAll(/<a[^>]+name="([^"]+)"/g)) ids.add(name);
  anchors.set(page, ids);
}

const dead = new Set();
for (const page of pages) {
  const html = await readFile(page, "utf8");
  for (const [, href] of html.matchAll(/href="([^"]+)"/g)) {
    if (!href.startsWith(base + "/") || href.startsWith(base + "/pagefind")) continue;
    const [pathPart, fragment = ""] = href.split("#");
    const clean = pathPart.split("?")[0].slice(base.length);
    const target = clean === "" || clean === "/"
      ? join(DIST, "index.html")
      : join(DIST, clean.endsWith("/") ? join(clean, "index.html") : clean);
    const asset = join(DIST, clean);
    if (!existsSync(target) && !existsSync(asset)) {
      dead.add(`${href} (from ${page.slice(DIST.length)})`);
      continue;
    }
    if (fragment && existsSync(target) && anchors.has(target) && !anchors.get(target).has(fragment)) {
      dead.add(`${href} — no #${fragment} on that page (from ${page.slice(DIST.length)})`);
    }
  }
}
dead.size === 0
  ? ok("no dead internal links or fragments")
  : [...dead].forEach((d) => fail(`dead link: ${d}`));

console.log("=".repeat(41));
console.log(`  Site: ${pages.length} pages, ${expected.length} staged documents, ${failures} failed`);
console.log("=".repeat(41));
process.exit(failures ? 1 : 0);
