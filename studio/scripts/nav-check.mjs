// Harness Studio navigation contract check (harness-studio-nav, increment 1).
//
// The deterministic verifier behind every FR in
// specs/harness-studio-nav/verification.yaml. One FR per invocation:
//
//   node studio/scripts/nav-check.mjs FR-2
//
// WHY A SCRIPT AND NOT THE BROWSER GATE. tests/release/ui_checks.sh
// already asserts the nav in a real browser, but it needs the whole
// stack up (API + Studio + a synthesized store), so it cannot gate a
// phase. This asserts the same contract from the source and from a
// static render — no server, no browser, no store. It is modelled on
// studio/scripts/states-check.mjs and reuses its compile approach.
//
// IT MUST FAIL BEFORE THE WORK AND PASS AFTER. Written against the
// TARGET state while the tree still holds the eleven flat tabs, so
// every FR below is red on the commit that introduces this file. A
// check that is green before the change verifies nothing.

import { execFileSync } from "node:child_process";
import {
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { pathToFileURL } from "node:url";

// `import.meta.dirname` landed in 20.11 and `readdirSync({recursive})`
// in 18.17, and this machine's default `node` is 16. Without this guard
// the failure is a syntax or TypeError deep in the compile step, which
// reads like a defect in the code under test.
const [major] = process.versions.node.split(".").map(Number);
if (major < 20) {
  console.error(
    `nav-check needs node >= 20 (running ${process.versions.node}).\n` +
      `Try: PATH="$HOME/.nvm/versions/node/v24.11.1/bin:$PATH" node studio/scripts/nav-check.mjs ${process.argv[2] ?? "FR-1"}`,
  );
  process.exit(2);
}

const STUDIO = resolve(import.meta.dirname, "..");
const REPO = resolve(STUDIO, "..");

const FR = (process.argv[2] || "").toUpperCase();
const KNOWN = ["FR-1", "FR-2", "FR-3", "FR-4", "FR-5", "FR-6"];
if (!KNOWN.includes(FR)) {
  console.error(
    `usage: node studio/scripts/nav-check.mjs <${KNOWN.join("|")}>\n` +
      `got: '${process.argv[2] ?? ""}'`,
  );
  process.exit(2);
}

let failures = 0;
function check(name, ok, detail = "") {
  if (ok) {
    console.log(`  ok  ${name}`);
  } else {
    failures += 1;
    console.log(`  FAIL  ${name}${detail ? ` — ${detail}` : ""}`);
  }
}
function read(rel) {
  try {
    return readFileSync(join(REPO, rel), "utf8");
  } catch {
    return null;
  }
}

// ── the contract, stated once ─────────────────────────────────────────
// Changing these means changing specs/harness-studio-nav/spec.md first:
// the FR text is authoritative and admission binds it by statement_sha.
const PRODUCT = "Harness Studio";
const OLD_PRODUCT = "Session Analytics Studio";
const GROUPS = [
  {
    id: "mission-control",
    label: "Mission Control",
    items: [
      ["/", "Overview"],
      ["/sessions", "Sessions"],
      ["/search", "Search"],
      ["/ask", "Ask"],
      ["/graph", "Graph"],
    ],
  },
  {
    id: "development",
    label: "Development",
    items: [
      ["/runs", "Runs"],
      ["/team", "Team"],
      ["/routing", "Routing"],
      ["/benchmark", "Benchmark"],
      ["/analysis", "Analysis pipeline"],
    ],
  },
  { id: "library", label: "Library", items: [["/learn", "Guides"]] },
];
// Every route the flat nav could reach before the regroup, plus
// /settings. FR-3 is the promise that this set does not change.
const ROUTES = [
  "/",
  "/sessions",
  "/search",
  "/ask",
  "/graph",
  "/runs",
  "/team",
  "/routing",
  "/benchmark",
  "/analysis",
  "/learn",
  "/settings",
];

// ── compiled-module checks (FR-2..FR-4) need tsc + a render ───────────
let out = null;
async function loadModules() {
  // Named refusal before tsc: the whole contract lives in these two
  // files, and "lib/nav.ts is missing" is the single most likely state
  // of the tree. Letting tsc emit nothing and then failing on a
  // missing stub directory reports the symptom, not the cause.
  for (const rel of ["studio/lib/nav.ts", "studio/components/NavTabs.tsx"]) {
    if (read(rel) === null) {
      throw new Error(`${rel} does not exist — the navigation contract has no module to check`);
    }
  }
  out = mkdtempSync(join(STUDIO, ".nav-tmp-"));
  const cfg = join(out, "tsconfig.nav.json");
  writeFileSync(
    cfg,
    JSON.stringify({
      extends: join(STUDIO, "tsconfig.json"),
      compilerOptions: {
        noEmit: false,
        jsx: "react-jsx",
        module: "esnext",
        target: "es2022",
        moduleResolution: "bundler",
        skipLibCheck: true,
        outDir: out,
        baseUrl: STUDIO,
        paths: { "@/*": ["./*"] },
      },
      include: [join(STUDIO, "lib/nav.ts"), join(STUDIO, "components/NavTabs.tsx")],
    }),
  );
  execFileSync(join(STUDIO, "node_modules/.bin/tsc"), ["-p", cfg], {
    cwd: STUDIO,
    stdio: "inherit",
  });

  // tsc leaves "@/..." alone (a bundler's job) and plain node cannot
  // resolve next/link or next/navigation. Rewrite and stub, exactly as
  // states-check.mjs does. The pathname stub reads a global so one
  // compile can be rendered at many paths.
  for (const f of readdirSync(out, { recursive: true })) {
    const file = join(out, String(f));
    if (!file.endsWith(".js")) continue;
    let src = readFileSync(file, "utf8").replace(
      /(from\s+")@\/([^"]+)(")/g,
      (_m, pre, spec, post) => {
        let rel = relative(dirname(file), join(out, spec)).replace(/\\/g, "/");
        if (!rel.startsWith(".")) rel = `./${rel}`;
        return `${pre}${rel}.js${post}`;
      },
    );
    src = src
      .replace(/from\s+"next\/link"/g, 'from "./__next_link_stub.js"')
      .replace(/from\s+"next\/navigation"/g, 'from "./__next_nav_stub.js"');
    writeFileSync(file, src);
  }
  // tsc emits only the files it compiled; the stubs sit beside them,
  // so the directory must be guaranteed rather than assumed.
  mkdirSync(join(out, "components"), { recursive: true });
  writeFileSync(
    join(out, "components/__next_link_stub.js"),
    'import React from "react";\n' +
      "export default function Link({ href, children, ...rest }) {\n" +
      '  return React.createElement("a", { href, ...rest }, children);\n}\n',
  );
  writeFileSync(
    join(out, "components/__next_nav_stub.js"),
    'export function usePathname() { return globalThis.__NAV_PATH ?? "/"; }\n',
  );
  writeFileSync(join(out, "package.json"), '{"type":"module"}');

  const nav = await import(pathToFileURL(join(out, "lib/nav.js")));
  const tabs = await import(pathToFileURL(join(out, "components/NavTabs.js")));
  const React = (await import("react")).default;
  const { renderToStaticMarkup } = await import("react-dom/server");
  return { nav, tabs, React, renderToStaticMarkup };
}

// Attribute occurrences in rendered markup, without a DOM.
const countAttr = (html, attr, value) =>
  (html.match(new RegExp(`${attr}="${value}"`, "g")) || []).length;

try {
  // ── FR-1: the console is called Harness Studio ─────────────────────
  if (FR === "FR-1") {
    console.log("FR-1 — the product name");
    const layout = read("studio/app/layout.tsx");
    const readme = read("studio/README.md");
    check("studio/app/layout.tsx is readable", layout !== null);
    check("studio/README.md is readable", readme !== null);
    if (layout) {
      check(
        `layout.tsx no longer carries "${OLD_PRODUCT}"`,
        !layout.includes(OLD_PRODUCT),
        "the old product name is still in the layout",
      );
      check(
        "layout.tsx takes the name from lib/nav (one source, not a literal per site)",
        /from\s+"@\/lib\/nav"/.test(layout) && /PRODUCT_NAME/.test(layout),
        "expected an import of PRODUCT_NAME from @/lib/nav",
      );
    }
    if (readme) {
      check(
        `studio/README.md no longer carries "${OLD_PRODUCT}"`,
        !readme.includes(OLD_PRODUCT),
      );
      check(`studio/README.md names "${PRODUCT}"`, readme.includes(PRODUCT));
    }
    const { nav } = await loadModules();
    check(
      `lib/nav.ts exports PRODUCT_NAME === "${PRODUCT}"`,
      nav.PRODUCT_NAME === PRODUCT,
      `got ${JSON.stringify(nav.PRODUCT_NAME)}`,
    );
  }

  // ── FR-2: three groups, exact labels, exact order ──────────────────
  if (FR === "FR-2") {
    console.log("FR-2 — three groups with the decided membership");
    const { nav } = await loadModules();
    const g = nav.NAV_GROUPS;
    check("NAV_GROUPS is an array of three groups", Array.isArray(g) && g.length === 3,
      `got ${Array.isArray(g) ? `${g.length} groups` : typeof g}`);
    if (Array.isArray(g) && g.length === 3) {
      GROUPS.forEach((want, i) => {
        check(`group ${i + 1} is ${want.label} (id ${want.id})`,
          g[i]?.label === want.label && g[i]?.id === want.id,
          `got label ${JSON.stringify(g[i]?.label)}, id ${JSON.stringify(g[i]?.id)}`);
        const got = (g[i]?.items ?? []).map((it) => [it.href, it.label]);
        check(`${want.label} holds exactly its decided items, in order`,
          JSON.stringify(got) === JSON.stringify(want.items),
          `got ${JSON.stringify(got)}`);
      });
    }
    check("SETTINGS_ITEM is /settings and sits in no group",
      nav.SETTINGS_ITEM?.href === "/settings" &&
        !g?.some((grp) => grp.items?.some((it) => it.href === "/settings")),
      `got ${JSON.stringify(nav.SETTINGS_ITEM)}`);
    check("Overview keeps /labels as a child route",
      JSON.stringify(g?.[0]?.items?.[0]?.also) === JSON.stringify(["/labels"]),
      `got ${JSON.stringify(g?.[0]?.items?.[0]?.also)}`);
  }

  // ── FR-3: no URL changed, and each resolves to one item ────────────
  if (FR === "FR-3") {
    console.log("FR-3 — every pre-existing URL still resolves, to exactly one item");
    const { nav } = await loadModules();
    const hrefs = [
      ...(nav.NAV_GROUPS ?? []).flatMap((grp) => (grp.items ?? []).map((it) => it.href)),
      nav.SETTINGS_ITEM?.href,
    ].filter(Boolean);
    check("the nav covers exactly the twelve pre-existing routes, no more and no fewer",
      JSON.stringify([...hrefs].sort()) === JSON.stringify([...ROUTES].sort()),
      `got ${JSON.stringify([...hrefs].sort())}`);
    check("activeNav is exported", typeof nav.activeNav === "function");
    if (typeof nav.activeNav === "function") {
      for (const route of ROUTES) {
        const hit = nav.activeNav(route);
        check(`${route} resolves to one item`, hit?.item?.href === route,
          `got ${JSON.stringify(hit?.item?.href)}`);
      }
      check("/sessions/<id> stays on Sessions",
        nav.activeNav("/sessions/abc123")?.item?.href === "/sessions",
        `got ${JSON.stringify(nav.activeNav("/sessions/abc123")?.item?.href)}`);
      check("/labels/<label> stays on Overview",
        nav.activeNav("/labels/hooks")?.item?.href === "/",
        `got ${JSON.stringify(nav.activeNav("/labels/hooks")?.item?.href)}`);
      check("an unknown path resolves to nothing, rather than defaulting to Overview",
        nav.activeNav("/nope") === null,
        `got ${JSON.stringify(nav.activeNav("/nope"))}`);
    }
  }

  // ── FR-4: one aria-current, on the item, never the group ───────────
  if (FR === "FR-4") {
    console.log("FR-4 — exactly one aria-current, and it is the sub-tab");
    const { nav, tabs, React, renderToStaticMarkup } = await loadModules();
    const NavTabs = tabs.default;
    check("NavTabs has a default export", typeof NavTabs === "function");
    if (typeof NavTabs === "function") {
      for (const path of [...ROUTES, "/sessions/abc123", "/labels/hooks"]) {
        globalThis.__NAV_PATH = path;
        let html = "";
        try {
          html = renderToStaticMarkup(
            React.createElement(NavTabs, { groups: nav.NAV_GROUPS, settings: nav.SETTINGS_ITEM }),
          );
        } catch (e) {
          check(`${path} renders`, false, String(e.message || e).split("\n")[0]);
          continue;
        }
        const marks = countAttr(html, "aria-current", "page");
        check(`${path} marks exactly one place`, marks === 1, `found ${marks}`);
        const expanded = countAttr(html, "aria-expanded", "true");
        check(`${path} opens exactly one group`, expanded === 1, `found ${expanded}`);
        // The group header must not be the marked element: assert the
        // marked label is the ITEM's, which no group label equals.
        const want = nav.activeNav?.(path)?.item?.label;
        if (want) {
          const escaped = want.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
          const marked = new RegExp(
            `aria-current="page"[^>]*>\\s*${escaped}`,
          ).test(html);
          check(`${path} marks the item "${want}", not its group`, marked,
            "aria-current is not on an element whose text is the item label");
        }
      }
    }
  }

  // ── FR-5: the release browser gate follows the new labels ──────────
  if (FR === "FR-5") {
    console.log("FR-5 — the release nav gate asserts the new labels");
    const gate = read("tests/release/ui_checks.sh");
    check("tests/release/ui_checks.sh is readable", gate !== null);
    if (gate) {
      for (const pair of [
        "/:Overview",
        "/sessions:Sessions",
        "/graph:Graph",
        "/team:Team",
        "/learn:Guides",
        "/settings:Settings",
        "/routing:Routing",
        "/analysis:Analysis pipeline",
      ]) {
        check(`the gate asserts ${pair}`, gate.includes(`"${pair}"`),
          "expected this route:label pair in the nav loop");
      }
      check("the gate no longer expects the retired labels",
        !gate.includes('"/:Dashboard"') && !gate.includes('"/routing:Benchmark"'),
        "a retired route:label pair is still asserted");
      check("the gate still compares against a single aria-current",
        /querySelectorAll\("\[aria-current=page\]"\)/.test(gate),
        "the single-marker assertion was removed rather than updated");
    }
  }

  // ── FR-6: nothing tracked still calls it the old name ──────────────
  if (FR === "FR-6") {
    console.log("FR-6 — no tracked file outside specs/ still uses the old names");
    // `git grep -l` exits 1 when it matches nothing — which is the
    // passing case here, so the exit status is read, never trusted as
    // an error. Any other status is a real tool failure and rethrows.
    let tracked = [];
    try {
      tracked = execFileSync(
        "git",
        ["grep", "-l", "-F", OLD_PRODUCT, "--", ".", ":(exclude)specs", ":(exclude)doc_internal"],
        { cwd: REPO, encoding: "utf8" },
      )
        .split("\n")
        .filter(Boolean);
    } catch (e) {
      if (e.status !== 1) throw e;
    }
    check(`no tracked file outside specs/ carries "${OLD_PRODUCT}"`,
      tracked.length === 0, `still in: ${tracked.join(", ")}`);
  }
} catch (e) {
  // A thrown error is a failure, never a silent pass.
  console.error(`nav-check ${FR}: ${e.message || e}`);
  failures += 1;
} finally {
  if (out) rmSync(out, { recursive: true, force: true });
}

console.log(
  failures === 0
    ? `nav-check ${FR}: contract met`
    : `nav-check ${FR}: ${failures} failure(s)`,
);
process.exit(failures === 0 ? 0 : 1);
