// D8 states check (#293) — renders each FR-C/FR-D state to real markup
// and asserts on it. No new dependency: `tsc` and `react-dom/server`
// are already present, so the components are compiled to a temp dir and
// rendered there.
//
// WHY THIS EXISTS RATHER THAN A CHECKLIST. D6 established that the
// visual-review harness does not apply to the Studio. It does not
// follow that hand checking is the only option — hand checking cannot
// fail visibly and depends on diligence at one moment, which is the
// failure mode this arc keeps finding. This is the smallest thing that
// can fail on its own.
//
// THE MARKERS MUST BE MUTUALLY EXCLUSIVE, AND THAT IS ASSERTED.
// Asserting each state on its "distinguishing" copy is only as good as
// the copy being genuinely distinguishing: if graph-absent and
// graph-unbuilt shared a sentence, every per-state assertion would pass
// while the script conflated exactly the two states FR-C names. So the
// first check is that no marker appears in any other state's render.
//
// Usage: node studio/scripts/states-check.mjs   (from the repo root)

import { execFileSync } from "node:child_process";
import {
  mkdtempSync,
  readFileSync,
  readdirSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { pathToFileURL } from "node:url";

const STUDIO = resolve(import.meta.dirname, "..");
// Compiled INSIDE the studio tree, not /tmp: node resolves bare imports
// ("react", "react-dom") by walking up to studio/node_modules, which a
// temp dir elsewhere on the filesystem cannot reach. Removed in the
// finally block, and the prefix is gitignored.
const out = mkdtempSync(join(STUDIO, ".states-tmp-"));

function fail(msg) {
  console.error(`FAIL: ${msg}`);
  process.exitCode = 1;
}

try {
  // Compile the two modules under test (JSX included) with the
  // already-installed tsc. React is aliased through the studio's own
  // node_modules by the module resolution below.
  // `--paths` is tsconfig-only, so extend the studio's own config
  // rather than restating its module resolution here — the compiled
  // output then matches what `next build` would produce.
  const cfg = join(out, "tsconfig.states.json");
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
      include: [
        join(STUDIO, "components/ClustersView.tsx"),
        join(STUDIO, "lib/clusterStates.ts"),
        join(STUDIO, "components/SimilarPanel.tsx"),
        join(STUDIO, "lib/similarStates.ts"),
        join(STUDIO, "components/ui.tsx"),
      ],
    }),
  );
  execFileSync(join(STUDIO, "node_modules/.bin/tsc"), ["-p", cfg], {
    cwd: STUDIO,
    stdio: "inherit",
  });

  // tsc does NOT rewrite the "@/..." path alias in emitted JS — that is
  // a bundler's job, and there is no bundler here. Rewrite the aliases
  // to relative specifiers so plain node can load the output.
  const emitted = readdirSync(out, { recursive: true })
    .filter((f) => String(f).endsWith(".js"))
    .map((f) => join(out, String(f)));
  for (const file of emitted) {
    const src = readFileSync(file, "utf8").replace(
      /(from\s+")@\/([^"]+)(")/g,
      (_m, pre, spec, post) => {
        let rel = relative(dirname(file), join(out, spec)).replace(/\\/g, "/");
        if (!rel.startsWith(".")) rel = `./${rel}`;
        return `${pre}${rel}.js${post}`;
      },
    );
    writeFileSync(file, src);
  }
  writeFileSync(join(out, "package.json"), '{"type":"module"}');

  const { renderToStaticMarkup } = await import("react-dom/server");
  const React = (await import("react")).default;

  const { default: ClustersView } = await import(
    pathToFileURL(join(out, "components/ClustersView.js"))
  );
  const { COPY, STATE_MARKERS, classify } = await import(
    pathToFileURL(join(out, "lib/clusterStates.js"))
  );
  const { default: SimilarPanel } = await import(
    pathToFileURL(join(out, "components/SimilarPanel.js"))
  );
  const { SIMILAR_COPY, SIMILAR_MARKERS, classifySimilar } = await import(
    pathToFileURL(join(out, "lib/similarStates.js"))
  );

  const report = (clusters, counts = {}) => ({
    clusters,
    cluster_count: counts.total ?? clusters.length,
    clustered_sessions: counts.clustered ?? 0,
    unclustered_sessions: counts.unclustered ?? 0,
    graph_sessions: counts.graph ?? 0,
    basis: "embedding",
    membership_basis: "the SIMILAR_TO edges currently stored in the graph",
    inventory_basis: "the current Session node inventory",
    limitations: [
      "a cluster is a transitive discovery grouping",
      "membership reflects the edges the producer created at production time",
    ],
  });

  const cluster = (identity, members, edges) => ({
    identity,
    size: members.length,
    members,
    directed_edge_count: edges,
  });

  // THE ORDERING FIXTURE MUST DISCRIMINATE. Identities "m" (size 3) and
  // "a" (size 2): the reader's order is size-descending → [m, a], while
  // identity-ascending would be [a, m]. A fixture whose two candidate
  // orders AGREE cannot detect a client-side sort — the first version
  // of this script used a=3, p=2, where both orders are [a, p], and a
  // deliberately-introduced sort escaped it. Same trap as #289's
  // ordering fixture, and it escaped here until it was mutated.
  const populated = report(
    [cluster("m", ["m", "n", "o"], 4), cluster("a", ["a", "b"], 2)],
    { clustered: 5, unclustered: 1, graph: 6 },
  );

  // Each entry carries the DISTINCT STATE it exercises. The cap is a
  // VARIANT of "populated", not a state of its own — tagging that
  // explicitly is what lets the exclusivity check below compare only
  // across genuinely different states. (The first run of that check
  // failed here, by flagging populated-vs-capped: correct behaviour
  // from the check, and the thing it forced was this precision.)
  const STATES = [
    ["populated (FR-A order rendered as received)", "populated",
      classify({ ok: true, report: populated }), COPY.populatedMarker],
    ["healthy empty (FR-C: a result, not a failure)", "empty",
      classify({ ok: true, report: report([], { graph: 2, unclustered: 2 }) }),
      COPY.emptyMarker],
    ["graph absent (FR-C prerequisite)", "absent",
      classify({ ok: false, status: 503, message: "503",
        detail: { error: "graph database absent at /x",
          prerequisite: "graph", state: "absent",
          guidance: "run graph first" } }),
      COPY.absentMarker],
    ["graph unbuilt (FR-C: distinct from absent)", "unbuilt",
      classify({ ok: false, status: 503, message: "503",
        detail: { error: "graph store holds no Session table",
          prerequisite: "graph", state: "unbuilt",
          guidance: "run graph first" } }),
      COPY.unbuiltMarker],
    ["capped list (FR-D: N of M)", "populated",
      classify({ ok: true,
        report: report([cluster("a", ["a", "b"], 2)],
          { total: 9, clustered: 2, unclustered: 0, graph: 2 }) }),
      COPY.cap(1, 9)],
    ["uncapped list shows NO cap notice (FR-D)", "populated",
      classify({ ok: true, report: populated }), null],
    ["unnamed prerequisite (older server, no `state` field)", "unnamed",
      classify({ ok: false, status: 503, message: "503",
        detail: { error: "graph database absent at /x",
          prerequisite: "graph", guidance: "run graph first" } }),
      COPY.unnamedMarker],
    ["honest failure (not a prerequisite)", "failed",
      classify({ ok: false, status: 500, message: "GET /api/clusters → 500" }),
      COPY.failedMarker],
  ];

  const rendered = new Map();
  for (const [name, kind, state, marker] of STATES) {
    const html = renderToStaticMarkup(React.createElement(ClustersView, { state }));
    rendered.set(name, { kind, html });
    if (marker === null) {
      // the negative case: an uncapped list must NOT claim a cap
      if (/Showing \d+ of \d+ clusters/.test(html)) {
        fail(`${name}: a cap notice was rendered for an uncapped list`);
      } else {
        console.log(`  ok  ${name}`);
      }
      continue;
    }
    if (!html.includes(marker)) {
      fail(`${name}: marker not rendered — ${JSON.stringify(marker)}`);
    } else {
      console.log(`  ok  ${name}`);
    }
  }

  // THE META-ASSERTION: markers must be mutually exclusive, or every
  // check above could pass while two states were conflated.
  console.log("\nmarker exclusivity:");
  for (const [name, kind, , marker] of STATES) {
    if (marker === null || !STATE_MARKERS.includes(marker)) continue;
    for (const [otherName, other] of rendered) {
      // Compare only across DIFFERENT states: two renders of the same
      // state (populated and its capped variant) share copy by design.
      if (other.kind === kind) continue;
      if (other.html.includes(marker)) {
        fail(
          `${JSON.stringify(marker)} appears in state "${kind}" and in ` +
          `"${otherName}" — those two states are not distinguishable`,
        );
      }
    }
  }
  if (!process.exitCode) console.log("  ok  every marker is unique to its state");

  // The unnamed prerequisite must claim NOTHING about which one it is,
  // and must still show the server's own error + guidance. A renderer
  // that defaulted to "absent" would pass its own marker check while
  // giving a confident wrong remedy.
  const unnamed = rendered.get(STATES[6][0]).html;
  if (unnamed.includes(COPY.absentMarker) || unnamed.includes(COPY.unbuiltMarker)) {
    fail("unnamed prerequisite was rendered as a NAMED one");
  } else if (
    !unnamed.includes("graph database absent at /x") ||
    !unnamed.includes("run graph first")
  ) {
    fail("unnamed prerequisite dropped the server's error or guidance");
  } else {
    console.log("  ok  unnamed prerequisite claims nothing, shows what it got");
  }

  // FR-A: the view must not reorder. Rendered identities must appear in
  // the order the report supplied, which is size-desc then identity-asc
  // — an order that differs from plain identity-asc, so a sort here
  // would change the output.
  const html = rendered.get(STATES[0][0]).html;
  const order = [...html.matchAll(/class="font-mono text-sm">([^<]+)</g)].map(
    (m) => m[1],
  );
  if (order.join(",") !== "m,a") {
    fail(
      `FR-A: identities rendered as [${order}] — expected [m,a] as received. ` +
      `[a,m] would mean the view sorted by identity.`,
    );
  } else {
    console.log("  ok  FR-A: order rendered as received, no client-side sort");
  }

  // FR-A extends to MEMBERS: they arrive sorted by session_key and are
  // rendered as received. Fixture members are m,n,o — a reverse or a
  // re-sort changes this sequence.
  const members = [...html.matchAll(/<li>([mnoab])<\/li>/g)].map((m) => m[1]);
  if (members.join(",") !== "m,n,o,a,b") {
    fail(
      `FR-A: members rendered as [${members}] — expected [m,n,o,a,b] ` +
      `as received, per cluster.`,
    );
  } else {
    console.log("  ok  FR-A: members rendered as received");
  }

  // FR-E: the limitations block and BOTH provenance labels must be
  // DISPLAYED, not merely fetched. This is the requirement that stops a
  // cluster travelling without the two claims #289 refuses.
  const honesty = [
    ["transitive discovery grouping", "the transitive-grouping limitation"],
    ["production time", "the production-time compatibility limitation"],
    ["SIMILAR_TO edges currently stored", "the membership provenance"],
    ["current Session node inventory", "the inventory provenance"],
  ];
  let honest = true;
  for (const [needle, what] of honesty) {
    if (!html.includes(needle)) {
      fail(`FR-E: ${what} is not rendered (${JSON.stringify(needle)})`);
      honest = false;
    }
  }
  if (honest) console.log("  ok  FR-E: limitations + both provenances displayed");

  // ── T3: the similar-sessions panel ────────────────────────────────
  console.log("\nsimilar panel:");
  const similar = (neighbors) => ({
    session_id: 1,
    basis: "embedding",
    scores_are: "a snapshot of the last completed 'similar' pass",
    neighbors,
  });
  // Neighbour order is the producer's (best-first) and must render as
  // received: scores 0.91 then 0.72, identities z then a — so an
  // identity sort WOULD reorder, and a score sort would not. The
  // fixture discriminates a sort by either key.
  const NEIGHBOURS = [
    { session_key: "z", score: 0.91, id: null, project_path: null,
      started_at: null, basis: "embedding", kpi: null },
    { session_key: "a", score: 0.72, id: null, project_path: null,
      started_at: null, basis: "embedding", kpi: null },
  ];
  const SIMILAR_STATES = [
    ["neighbours present", "neighbours",
      classifySimilar({ ok: true, report: similar(NEIGHBOURS) }),
      SIMILAR_COPY.neighbours],
    ["no neighbours (healthy — the unclustered case)", "none",
      classifySimilar({ ok: true, report: similar([]) }), SIMILAR_COPY.none],
    ["absent from the graph (prerequisite, NOT 'no neighbours')",
      "prerequisite",
      classifySimilar({ ok: false, status: 503, message: "503",
        detail: { error: "session 1 has no graph node",
          prerequisite: "graph",
          guidance: "run graph to sync the graph, then similar" } }),
      SIMILAR_COPY.prerequisite],
    ["honest failure", "failed",
      classifySimilar({ ok: false, status: 500, message: "GET → 500" }),
      SIMILAR_COPY.failed],
  ];
  const simRendered = new Map();
  for (const [name, kind, state, marker] of SIMILAR_STATES) {
    const h = renderToStaticMarkup(React.createElement(SimilarPanel, { state }));
    simRendered.set(name, { kind, html: h });
    if (!h.includes(marker)) fail(`${name}: marker not rendered`);
    else console.log(`  ok  ${name}`);
  }
  for (const [name, kind, , marker] of SIMILAR_STATES) {
    if (!SIMILAR_MARKERS.includes(marker)) continue;
    for (const [otherName, other] of simRendered) {
      if (other.kind === kind) continue;
      if (other.html.includes(marker)) {
        fail(
          `${JSON.stringify(marker)} appears in state "${kind}" and in ` +
          `"${otherName}" — those two states are not distinguishable`,
        );
      }
    }
  }
  if (!process.exitCode) console.log("  ok  similar markers are unique");

  const simHtml = simRendered.get(SIMILAR_STATES[0][0]).html;
  const simOrder = [...simHtml.matchAll(/font-mono text-xs">([^<]+)</g)].map(
    (m) => m[1],
  );
  if (simOrder.join(",") !== "z,a") {
    fail(`FR-A: neighbours rendered as [${simOrder}] — expected [z,a]`);
  } else {
    console.log("  ok  FR-A: neighbours rendered as received");
  }
  // FR-E: the panel must state the snapshot basis AND refuse the
  // all-pairs reading.
  for (const [needle, what] of [
    ["snapshot of the last completed", "the snapshot note"],
    ["do not assert that these sessions are similar", "the not-pairwise note"],
  ]) {
    if (!simHtml.includes(needle)) fail(`FR-E: ${what} is not rendered`);
  }
  if (!process.exitCode) console.log("  ok  FR-E: basis + not-pairwise displayed");

  // FR-C: a prerequisite is only useful if its REMEDY reaches the user.
  // The producer tailors `guidance` per case (run embed / run graph /
  // run graph then similar); rendering the marker without it would show
  // a dead end.
  const preHtml = simRendered.get(SIMILAR_STATES[2][0]).html;
  for (const [needle, what] of [
    ["run graph to sync the graph, then similar", "the tailored guidance"],
    ["has no graph node", "the producer's own error text"],
  ]) {
    if (!preHtml.includes(needle)) {
      fail(`FR-C: ${what} is not rendered in the prerequisite state`);
    }
  }
  if (!process.exitCode) console.log("  ok  FR-C: prerequisite guidance rendered");

  if (!process.exitCode) console.log("\nstates-check: all states asserted");
} finally {
  rmSync(out, { recursive: true, force: true });
}
