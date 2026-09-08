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
        join(STUDIO, "components/DevelopersPanel.tsx"),
        join(STUDIO, "components/DashboardCards.tsx"),
        join(STUDIO, "lib/paths.ts"),
        join(STUDIO, "lib/docLinks.ts"),
        join(STUDIO, "components/JudgeQuality.tsx"),
        join(STUDIO, "components/LoadSelection.tsx"),
        join(STUDIO, "components/JudgeProgress.tsx"),
        join(STUDIO, "components/MarkdownDoc.tsx"),
        join(STUDIO, "lib/urls.ts"),
        join(STUDIO, "components/ResponseTime.tsx"),
        join(STUDIO, "components/SessionHeader.tsx"),
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
    // next/link is a bundler-era ESM entry that plain node cannot
    // resolve; for a static render a Link IS an anchor, so it is
    // stubbed as one (href and children survive, which is what the
    // assertions read).
    writeFileSync(
      file,
      src.replace(/from\s+"next\/link"/g, 'from "./__next_link_stub.js"'),
    );
  }
  writeFileSync(
    join(out, "components/__next_link_stub.js"),
    'import React from "react";\n' +
      "export default function Link({ href, children, ...rest }) {\n" +
      "  return React.createElement(\"a\", { href, ...rest }, children);\n}\n",
  );
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
    ["graph unopenable (FR-C: distinct from absent AND unbuilt)",
      "unopenable",
      classify({ ok: false, status: 503, message: "503",
        detail: { error: "graph database absent or unopenable at /x",
          prerequisite: "graph", state: "unopenable",
          guidance: "run graph first" } }),
      COPY.unopenableMarker],
    ["UNRECOGNISED state string (a future server value)", "unnamed",
      classify({ ok: false, status: 503, message: "503",
        detail: { error: "graph database is quarantined",
          prerequisite: "graph", state: "quarantined",
          guidance: "contact your administrator" } }),
      COPY.unnamedMarker],
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
  const unnamed = rendered.get(
    STATES.find((e) => e[0].startsWith("unnamed prerequisite"))[0],
  ).html;
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

  // An UNRECOGNISED state string must not become a confident wrong
  // diagnosis either. The classifier whitelists the three known values;
  // anything else claims nothing, exactly like a missing field.
  const future = rendered.get(
    STATES.find((e) => e[0].startsWith("UNRECOGNISED"))[0],
  ).html;
  if (
    future.includes(COPY.absentMarker) ||
    future.includes(COPY.unopenableMarker) ||
    future.includes(COPY.unbuiltMarker)
  ) {
    fail("an UNRECOGNISED state string was rendered as a known one");
  } else if (!future.includes("quarantined")) {
    fail("the unrecognised state dropped the server's own error");
  } else {
    console.log("  ok  unrecognised state claims nothing");
  }

  // "unopenable" must NOT invent a remedy: the cause is unknown to the
  // client (a lock, permissions, a partial write), so no command block.
  const unopen = rendered.get(
    STATES.find((e) => e[0].startsWith("graph unopenable"))[0],
  ).html;
  if (unopen.includes("<pre")) {
    fail("unopenable invented a remedy command");
  } else if (!unopen.includes("could not be opened")) {
    fail("unopenable did not render its own marker");
  } else {
    console.log("  ok  unopenable states the cause, invents no remedy");
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

  // ── developers panel (E1, #65) ──────────────────────────────────────
  // Both assertions below exist because review caught the panel failing
  // them: the cost denominator was carried in the payload but never
  // rendered, and a refresh failure left stale figures on screen with
  // nothing saying so. Type-checking passed in both cases — only
  // rendering the markup catches "the field exists but nobody shows it".
  const { default: DevelopersPanel } = await import(
    pathToFileURL(join(out, "components/DevelopersPanel.js"))
  );
  console.log("\ndevelopers panel:");

  // turns (100) is deliberately NOT priceable_turns (60): a developer
  // whose every eligible turn is priced must not read as partial just
  // because user turns exist. That distinction is the whole point of
  // the coverage assertions below.
  const devRow = (over = {}) => ({
    developer_id: "alice", display_name: null, sessions: 2, turns: 100,
    tool_calls: 5, errors: 1, projects: 2, first_seen: "2026-08-01T00:00:00Z",
    last_seen: "2026-09-01T00:00:00Z", cost_usd: 4.0, priced_turns: 25,
    priceable_turns: 60,
    ...over,
  });
  const devData = (rows, over = {}) => ({
    developers: rows, developer_count: rows.length,
    is_single_developer: rows.length <= 1, unattributed_sessions: 0,
    registered_without_sessions: [], ...over,
  });
  const renderDev = (data, stale) =>
    renderToStaticMarkup(React.createElement(DevelopersPanel, { data, stale }));

  // Unknown cost must never render as a figure someone could budget on.
  const unpriced = renderDev(devData([devRow({ cost_usd: null, priced_turns: 0 })]));
  if (unpriced.includes("$0.00")) {
    fail("unpriced developer renders $0.00 — unknown cost shown as free");
  } else if (!unpriced.includes("—")) {
    fail("unpriced developer renders neither a dash nor a cost");
  } else {
    console.log("  ok  unknown cost renders as a dash, not $0.00");
  }

  // The denominator behind a cost must REACH THE SCREEN, not just the
  // payload: 25 of 100 turns priced is a materially different claim
  // from a complete total, and this is the finding review raised.
  const partial = renderDev(devData([devRow()]));
  if (partial.includes("25 / 100")) {
    fail("coverage measured against every turn — user turns are never priceable");
  } else if (!partial.includes("25 / 60")) {
    fail("priced_turns is not rendered — cost total looks complete");
  } else {
    console.log("  ok  cost coverage is priced/ELIGIBLE turns, not /all turns");
  }

  // Fully-priced must not read as partial. This is the case the wrong
  // denominator got backwards: 60/60 eligible, with 40 unpriceable user
  // turns alongside, is complete coverage and must not be flagged amber.
  const complete = renderDev(devData([devRow({ priced_turns: 60 })]));
  if (complete.includes("text-amber-700")) {
    fail("fully-priced developer flagged as partial coverage");
  } else {
    console.log("  ok  fully-priced developer is not flagged partial");
  }

  // A failed refresh keeps the last good payload (useApi does not clear
  // it). Showing that as current is the silent-staleness finding.
  const stale = renderDev(devData([devRow()]), "GET /api/... → 500");
  if (!stale.includes("last successful load")) {
    fail("stale data rendered with no staleness warning");
  } else if (!stale.includes("25 / 60")) {
    fail("staleness warning replaced the data instead of annotating it");
  } else {
    console.log("  ok  stale refresh is annotated, not hidden or blanked");
  }

  // An EMPTY last-good payload plus a failed refresh. The harness only
  // covered stale non-empty data at first, and the empty branch
  // returned before the warning — so the emptiest possible screen was
  // the one asserting "nothing ingested" as current, unchallenged.
  const staleEmpty = renderDev(devData([]), "GET /api/... → 500");
  if (!staleEmpty.includes("last successful load")) {
    fail("empty stale payload presents 'no sessions' as current");
  } else if (!staleEmpty.includes("No sessions ingested")) {
    fail("staleness warning replaced the empty-state explanation");
  } else {
    console.log("  ok  empty + stale is annotated, not presented as current");
  }

  // The single-developer case is what every real store renders today.
  const single = renderDev(devData([devRow()]));
  if (!single.includes("single developer")) {
    fail("single-developer store renders one row with no explanation");
  } else {
    console.log("  ok  single-developer store explains itself");
  }

  // Ordering is the producer's, and deliberately not a leaderboard.
  const two = renderDev(
    devData([devRow({ developer_id: "alice" }),
             devRow({ developer_id: "zoe", sessions: 99, turns: 9999 })]),
  );
  const devOrder = [...two.matchAll(/font-mono text-xs">([^<]+)</g)].map((m) => m[1]);
  if (devOrder.join(",") !== "alice,zoe") {
    fail(`developers rendered as [${devOrder}] — expected [alice,zoe]`);
  } else {
    console.log("  ok  rows rendered as received (busiest not promoted)");
  }

  // ── #307 dashboard cards + helpers ────────────────────────────────
  const cards = await import(pathToFileURL(join(out, "components/DashboardCards.js")));
  const ui = await import(pathToFileURL(join(out, "components/ui.js")));
  const paths = await import(pathToFileURL(join(out, "lib/paths.js")));
  console.log("\ndashboard cards (#307):");
  const render = (C, props) => renderToStaticMarkup(React.createElement(C, props));

  // Latency: the measured-n is part of the number, never optional.
  const lat = render(cards.LatencyStat, {
    data: { measured_turns: 12, p50: 3, p90: 11.5, max: 54, sessions: 4, by_copilot: [], basis: "" },
    error: null,
  });
  if (!/12 assistant turns in 4 sessions/.test(lat)) {
    fail("latency stat renders a median without its measured-n");
  } else if (!/p90/.test(lat)) {
    fail("latency stat drops the p90");
  } else {
    console.log("  ok  median agent response carries measured-n and p90");
  }
  const latEmpty = render(cards.LatencyStat, {
    data: { measured_turns: 0, p50: null, p90: null, max: null, sessions: 0, by_copilot: [], basis: "" },
    error: null,
  });
  if (/\b0s\b|NaN/.test(latEmpty) || !/no turn carries timestamps/.test(latEmpty)) {
    fail("latency stat with nothing measured does not say so");
  } else {
    console.log("  ok  unmeasured latency is stated, not shown as 0s");
  }

  // Label distribution: every bar is a link to its traces page.
  const labels = render(cards.LabelDistributionCard, {
    data: { labels: [
      { label: "rework_detected", true: 7, total: 40 },
      { label: "user_corrects_agent", true: 3, total: 40 },
      { label: "never_fired", true: 0, total: 0 },
    ] },
  });
  const links = [...labels.matchAll(/href="\/labels\/([^"]+)"/g)].map((m) => m[1]);
  if (links.join(",") !== "rework_detected,user_corrects_agent") {
    fail(`label distribution links were [${links}] — expected one per label with data`);
  } else {
    console.log("  ok  each label with data links to its traces page");
  }
  const noLabels = render(cards.LabelDistributionCard, { data: { labels: [] } });
  if (!/No heuristic labels yet/.test(noLabels)) fail("empty label distribution has no explanation");
  else console.log("  ok  empty label distribution explains itself");

  // Recent errors: an empty list says so; a full one is capped at 15.
  const errs = render(cards.RecentErrorsCard, {
    errors: Array.from({ length: 30 }, (_, i) => ({
      error_type: "ToolError", tool_name: `t${i}`, message: "m", copilot: "claude-code", project_path: "/a/b/c",
    })),
  });
  if ((errs.match(/<tr class/g) || []).length !== 15) fail("recent errors not capped at 15 rows");
  else console.log("  ok  recent errors capped at 15 rows");
  if (!/No tool errors recorded/.test(render(cards.RecentErrorsCard, { errors: [] }))) {
    fail("empty recent errors has no explanation");
  } else {
    console.log("  ok  empty recent errors explains itself");
  }

  // Cost by outcome: zero rows are not drawn, and money is formatted as money.
  const cost = render(cards.CostByOutcomeCard, {
    data: { by_phase: [{ phase: "build", cost_usd: 12.5, sessions: 3 }, { phase: "plan", cost_usd: 0, sessions: 2 }],
            by_sentiment: [] },
  });
  if (!/\$12\.50/.test(cost)) fail("cost by outcome does not format money");
  else if (/plan \(2\)/.test(cost)) fail("cost by outcome draws a zero-cost phase");
  else console.log("  ok  cost by outcome formats money and skips zero rows");

  // Phase process renders nothing when no project has history.
  const noPhases = render(cards.PhaseProcessCard, {
    data: { projects: [{ project_path: "/p", has_workflow_history: false, features: [], history_may_be_truncated: false }],
            projects_with_history: 0, retention_cap: 50, any_history_may_be_truncated: false, absence_note: "n", source_root_configured: true },
  });
  if (noPhases !== "") fail("phase-process card renders with no history");
  else console.log("  ok  phase-process card is absent without history");

  // A failed refresh is annotated, never presented as current; a failed
  // first load leaves a card that says so, not a blank.
  const staleLabels = render(cards.LabelDistributionCard, {
    data: { labels: [{ label: "rework_detected", true: 1, total: 2 }] },
    stale: "GET /api/dashboard/labels failed on the server.",
  });
  if (!/last successful load/.test(staleLabels)) fail("stale label card not annotated");
  else console.log("  ok  stale card is annotated, not presented as current");
  const failed = render(cards.FailedCard, { title: "Cost by outcome", error: "The API is not reachable." });
  if (!/could not be loaded/.test(failed) || !/API is not reachable/.test(failed)) fail("failed card lacks its reason");
  else console.log("  ok  failed first load leaves a card that says why");
  const staleLat = render(cards.LatencyStat, {
    data: { measured_turns: 12, p50: 3, p90: 11.5, max: 54, sessions: 4, by_copilot: [], basis: "" },
    error: "refresh failed",
  });
  if (!/last successful load/.test(staleLat)) fail("stale latency stat not annotated");
  else console.log("  ok  stale latency stat is annotated");

  // Empty + stale: an empty result from the last successful load still
  // carries the refresh-failed annotation (it was the reviewer's repro).
  const emptyStale = [
    ["cost", render(cards.CostByOutcomeCard, { data: { by_phase: [], by_sentiment: [] }, stale: "boom" })],
    ["labels", render(cards.LabelDistributionCard, { data: { labels: [] }, stale: "boom" })],
    ["errors", render(cards.RecentErrorsCard, { errors: [], stale: "boom" })],
    ["latency", render(cards.LatencyStat, {
      data: { measured_turns: 0, p50: null, p90: null, max: null, sessions: 0, by_copilot: [], basis: "" },
      error: "boom",
    })],
  ];
  for (const [name, html] of emptyStale) {
    if (!/last successful load/.test(html)) fail(`empty ${name} card hides a failed refresh`);
    else console.log(`  ok  empty ${name} card still annotates a failed refresh`);
  }

  // Empty store: zeros are a doorway, and the card says where it leads —
  // differently for "nothing loaded", "everything excluded as noise", and
  // "the store did not answer".
  const emptyNone = render(cards.EmptyStore, { excludedNoise: 0, sources: "Reading from — claude-code: ~/.claude/projects", storeReachable: true });
  if (!/No sessions have been loaded/.test(emptyNone) || !/href="\/analysis"/.test(emptyNone)) fail("empty store (nothing loaded) does not point at Analysis → Load sessions");
  else if (!/reads claude-code/.test(emptyNone)) fail("empty store does not say what Load sessions would read");
  else console.log("  ok  empty store → Analysis → Load sessions, with the source folders");
  const emptyNoise = render(cards.EmptyStore, { excludedNoise: 1, sources: null, storeReachable: true });
  if (!/excluded as noise/.test(emptyNoise) || !/href="\/sessions"/.test(emptyNoise) || !/Show excluded/.test(emptyNoise)) fail("all-noise store does not explain the exclusion or point at the toggle");
  else console.log("  ok  all-noise store explains the exclusion and points at Show excluded");
  const emptyDown = render(cards.EmptyStore, { excludedNoise: 0, sources: null, storeReachable: false });
  if (!/not reachable/.test(emptyDown) || /No sessions have been loaded/.test(emptyDown)) fail("unreachable store presented as an empty one");
  else console.log("  ok  unreachable store is not presented as empty");

  // Helpers (F10, F12, F15).
  const de = ui.describeError;
  if (de(new TypeError("Failed to fetch")) !== "The API is not reachable.") fail("describeError leaks 'Failed to fetch'");
  else if (de(new Error("GET /api/graph/node-counts → 503")) !== "GET /api/graph/node-counts not available yet.") fail(`describeError status mapping: ${de(new Error("GET /api/graph/node-counts → 503"))}`);
  else console.log("  ok  describeError speaks in words, keeps the path");
  const el = ui.elideMiddle("mcp__claude-in-chrome__navigate", 26);
  if (!el.startsWith("mcp__claude") || !el.endsWith("navigate") || !el.includes("…")) fail(`elideMiddle lost an end: ${el}`);
  else if (ui.elideMiddle("bash", 26) !== "bash") fail("elideMiddle touches a short label");
  else console.log("  ok  elideMiddle keeps head and tail");
  if (paths.pathFromValue("sqlite:////Users/x/a.db") !== "/Users/x/a.db") fail("pathFromValue does not strip the sqlite scheme");
  else if (paths.pathFromValue("/plain/dir") !== "/plain/dir") fail("pathFromValue changes a plain path");
  else console.log("  ok  picker start path strips the DSN scheme");

  // ── #309 Learn center: link + image resolution over the real link forms
  const dl = await import(pathToFileURL(join(out, "lib/docLinks.js")));
  console.log("\nlearn links (#309):");
  const slugs = {
    "README.md": "README",
    "adapters/claude-code/docs/hooks-guide.md": "adapters--claude-code--docs--hooks-guide",
    "adapters/claude-code/docs/agent-traces.md": "adapters--claude-code--docs--agent-traces",
    "shared/capabilities/COMPATIBILITY.md": "shared--capabilities--COMPATIBILITY",
  };
  const repo = "https://github.com/x/y";
  const cases = [
    // [href, from, expected kind, expected href]
    ["adapters/claude-code/docs/hooks-guide.md", "README.md", "learn", "/learn/adapters--claude-code--docs--hooks-guide"],
    ["agent-traces.md", "adapters/claude-code/docs/hooks-guide.md", "learn", "/learn/adapters--claude-code--docs--agent-traces"],
    ["../README.md#quick-start", "docs/developer-cookbook.md", "learn", "/learn/README#quick-start"],
    ["../../../shared/capabilities/COMPATIBILITY.md", "adapters/pi/docs/quickstart.md", "learn", "/learn/shared--capabilities--COMPATIBILITY"],
    ["specs/pi-harness-adoption/lessons-learned.md", "README.md", "external", `${repo}/blob/master/specs/pi-harness-adoption/lessons-learned.md`],
    ["#documentation", "README.md", "anchor", "#documentation"],
    ["https://example.com/x", "README.md", "external", "https://example.com/x"],
  ];
  for (const [href, from, kind, expected] of cases) {
    const r = dl.resolveDocLink(href, from, slugs, repo, "master");
    if (r.kind !== kind || r.href !== expected) {
      fail(`resolveDocLink(${href} from ${from}) → ${r.kind} ${r.href}, expected ${kind} ${expected}`);
    } else {
      console.log(`  ok  ${href} from ${from} → ${kind}`);
    }
  }
  const imgCases = [
    ["images/mapatlas-claude-demo.jpg", "docs/mapatlas-harness-experiment.md", "http://api/api/docs/image/mapatlas-claude-demo.jpg"],
    ["docs/images/configuration-layers.png", "README.md", "http://api/api/docs/image/configuration-layers.png"],
    ["/docs/images/CCT_LOGO.png", "README.md", "http://api/api/docs/image/CCT_LOGO.png"],
    ["shots/x.png", "adapters/pi/docs/quickstart.md", `${repo}/raw/master/adapters/pi/docs/shots/x.png`],
    ["https://cdn.example/x.png", "README.md", "https://cdn.example/x.png"],
  ];
  for (const [src, from, expected] of imgCases) {
    const got = dl.resolveDocImage(src, from, "http://api", "/api/docs/image/", "docs/images", repo, "master");
    if (got !== expected) fail(`resolveDocImage(${src} from ${from}) → ${got}, expected ${expected}`);
    else console.log(`  ok  image ${src} from ${from}`);
  }
  const toc = dl.tableOfContents("# Title\n```sh\n# not a heading\n```\n## Quick Start\n## Quick Start\n### `code` head");
  const ids = toc.map((h) => h.id).join(",");
  const lines = toc.map((h) => h.line).join(",");
  if (ids !== "title,quick-start,quick-start-1,code-head") fail(`toc ids were ${ids}`);
  else if (lines !== "1,5,6,7") fail(`toc lines were ${lines}`);
  else console.log("  ok  toc skips fenced code, dedupes repeats, and carries source lines");

  // ── #313 judge quality card ────────────────────────────────────────
  const { default: JudgeQuality } = await import(pathToFileURL(join(out, "components/JudgeQuality.js")));
  console.log("\njudge quality (#313):");
  const jq = (props) => renderToStaticMarkup(React.createElement(JudgeQuality, { onSelect: () => {}, error: null, ...props }));
  const runs2 = {
    rubrics: [
      { source: "rubric:heuristic-v1", name: "heuristic-v1", turns: 50, first: null, last: null, judge: "ollama:llama3.2" },
      { source: "rubric:rerun", name: "rerun", turns: 50, first: null, last: null, judge: "ollama:llama3.2" },
    ],
    humans: [], min_pairs: 20,
  };
  const one = jq({ runs: { ...runs2, rubrics: runs2.rubrics.slice(0, 1) }, report: null, a: "", b: "" });
  if (!/One label source so far/.test(one) || !/labels sample/.test(one)) fail("single-source card lacks the how-to");
  else console.log("  ok  one source → says what to do next");
  const rep = {
    a: "rubric:heuristic-v1", b: "rubric:rerun", turns_a: 50, turns_b: 50, turns_shared: 50, min_pairs: 20,
    labels: [
      { label: "user_gives_command", n: 50, agreement: 0.9, kappa: 0.71, a_true: 20, b_true: 22, sufficient: true },
      { label: "user_asks_question", n: 6, agreement: 1.0, kappa: null, a_true: 0, b_true: 0, sufficient: false },
    ],
    sentiment: { n: 50, exact: 0.8, sufficient: true },
    interaction_quality: { n: 50, within_1: 0.95, exact: 0.5, sufficient: true },
    basis: "b",
  };
  const full = jq({ runs: runs2, report: rep, a: rep.a, b: rep.b });
  if (!/50 turns labelled by both/.test(full)) fail("agreement card lacks the shared-n line");
  else if (!/not evidence/.test(full)) fail("agreement card lacks the pair-floor note");
  else if (!/text-slate-400[^>]*title="only 6 pairs/.test(full)) fail("insufficient row not greyed with its n");
  else if (!/90%/.test(full) || !/0\.71/.test(full)) fail("agreement/kappa not rendered");
  else console.log("  ok  agreement table: n, %, κ, greyed under-floor rows");
  const none = jq({ runs: runs2, report: { ...rep, turns_shared: 0, labels: [] }, a: rep.a, b: rep.b });
  if (!/share no turns/.test(none)) fail("zero shared turns not explained");
  else console.log("  ok  zero shared turns is explained, not a blank table");

  // ── which sessions to load (owner's selection requirement) ──────────
  console.log("\nload selection:");
  const ls = await import(pathToFileURL(join(out, "components/LoadSelection.js")));
  const MB = 1024 * 1024;
  const disc = {
    sessions: [
      { copilot: "claude-code", session_id: "a", source: "-Users-x-proj", files: 1, bytes: 3 * MB, modified: "2026-09-07T10:00:00+00:00", modified_epoch: 3, loaded: false },
      { copilot: "claude-code", session_id: "b", source: "-Users-x-other", files: 2, bytes: 250 * MB, modified: "2026-09-06T10:00:00+00:00", modified_epoch: 2, loaded: true },
    ],
    total: 2, total_bytes: 253 * MB, new: 1, new_bytes: 3 * MB, cap: 500,
  };
  const noPick = ls.loadPlan(disc, new Set(), "", "");
  if (noPick.label !== "Load 1 new session" || noPick.bytes !== 3 * MB || noPick.body.session_ids) fail(`no pick → every new session under the filters; got ${JSON.stringify(noPick)}`);
  else console.log("  ok  no pick loads the new sessions under the filters");
  const filtered = ls.loadPlan(disc, new Set(), "2026-09-01", "5");
  if (filtered.body.since !== "2026-09-01" || filtered.body.limit !== 5) fail("filters do not reach the load body");
  else console.log("  ok  since/limit reach the load body");
  const pick = ls.loadPlan(disc, new Set(["b"]), "2026-09-01", "5");
  if (pick.label !== "Load 1 selected" || pick.bytes !== 250 * MB || !pick.body.session_ids || pick.body.since) fail(`a pick must win over the filters; got ${JSON.stringify(pick)}`);
  else console.log("  ok  an explicit pick wins over the filters");
  const nothing = ls.loadPlan({ ...disc, new: 0, new_bytes: 0 }, new Set(), "", "");
  if (nothing.count !== 0) fail("all-loaded listing still offers a load");
  else console.log("  ok  all loaded → nothing to load");
  const panelProps = {
    listing: disc, error: null, since: "", limit: "", picked: new Set(["b"]), running: false,
    onSince() {}, onLimit() {}, onTogglePick() {}, onPickNew() {}, onClearPicks() {}, onLoad() {},
  };
  const panel = render(ls.default, panelProps);
  if (!/Load 1 selected/.test(panel) || !/250\.0 MB to read/.test(panel)) fail("panel button does not say what it loads and how much");
  else if (!/large load/.test(panel)) fail("a 250 MB load carries no size warning");
  else if (!/>new</.test(panel) || !/>loaded</.test(panel)) fail("rows lack the new/loaded state");
  else if (!/2 found · 1 new/.test(panel)) fail("listing summary missing");
  else console.log("  ok  panel: labelled button, size + large-load warning, new/loaded rows");
  const small = render(ls.default, { ...panelProps, picked: new Set() });
  if (/large load/.test(small) || !/3\.0 MB to read/.test(small)) fail("small load wrongly warned, or size missing");
  else console.log("  ok  a small load is not warned");
  const capped = render(ls.default, { ...panelProps, listing: { ...disc, total: 900 } });
  if (!/newest 2 of 900/.test(capped)) fail("capped listing does not say so");
  else console.log("  ok  capped listing says how many are not shown");
  const empty = render(ls.default, { ...panelProps, listing: { ...disc, sessions: [], total: 0, new: 0, new_bytes: 0, total_bytes: 0 }, picked: new Set() });
  if (!/No sessions under the source roots match/.test(empty)) fail("empty listing is a blank table");
  else console.log("  ok  empty listing explains itself");
  const down = render(ls.default, { ...panelProps, listing: null, error: "could not list sessions: boom" });
  if (!/could not list sessions/.test(down) || /Listing sessions…/.test(down)) fail("listing error hidden behind a spinner");
  else console.log("  ok  listing failure is shown");

  // ── judge progress + the judge choice ──────────────────────────────
  console.log("\njudge progress:");
  const jp = await import(pathToFileURL(join(out, "components/JudgeProgress.js")));
  const half = { total: 50, labeled: 25, parse_ok: 24, parse_failed: 1, last_error: "HTTP 404: model 'x' not found", judge: "ollama:x" };
  const sum = jp.progressSummary(half, 50);
  if (sum.pct !== 50 || !/25 of 50 turns/.test(sum.line) || !/24 labelled/.test(sum.line) || !/1 failed/.test(sum.line)) fail(`progress line wrong: ${JSON.stringify(sum)}`);
  else if (!/30\.0 turns\/min/.test(sum.line) || !/about 50s left/.test(sum.eta)) fail(`rate/eta wrong: ${JSON.stringify(sum)}`);
  else console.log("  ok  progress line: done/total, labelled, failed, rate, time left");
  const slow = jp.progressSummary({ ...half, labeled: 10, parse_ok: 10, parse_failed: 0, last_error: "" }, 300);
  if (!/about 20 min left/.test(slow.eta)) fail(`long eta not in minutes: ${slow.eta}`);
  else console.log("  ok  a long remaining time is in minutes");
  const bar = render(jp.default, { progress: half, seconds: 50, running: true });
  if (!/width:50%/.test(bar) || !/Last failure: HTTP 404/.test(bar)) fail("bar or last-failure line missing");
  else console.log("  ok  bar at 50% and the last failure named");
  const dead = render(jp.default, { progress: { ...half, labeled: 5, parse_ok: 0, parse_failed: 5 }, seconds: 5, running: true });
  if (!/Every call is failing/.test(dead) || !/Settings/.test(dead)) fail("all-failing run not called out");
  else console.log("  ok  every-call-failing is called out with a next step");
  const fin = render(jp.default, { progress: { ...half, labeled: 50, parse_ok: 49 }, seconds: 100, running: false });
  if (/left/.test(fin) || !/width:100%/.test(fin)) fail("finished run still shows time left");
  else console.log("  ok  finished run: full bar, no time left");
  const conf = { spec: "ollama:qwen3.6:27b", backend: "ollama", model: "qwen3.6:27b", source: "settings", by_copilot: {} };
  if (jp.judgeChoiceLabel(conf) !== "ollama:qwen3.6:27b (Settings)") fail(`judge choice label: ${jp.judgeChoiceLabel(conf)}`);
  else if (!/packaged default/.test(jp.judgeChoiceLabel({ ...conf, source: "packaged default" }))) fail("packaged default not named");
  else if (!/Settings/.test(jp.judgeChoiceLabel(undefined))) fail("no-config label does not point at Settings");
  else console.log("  ok  the default judge choice names what Settings says and where it is set");

  // ── Learn: fenced code blocks ────────────────────────────────────────
  console.log("\nlearn code blocks:");
  try {
    const md = await import(pathToFileURL(join(out, "components/MarkdownDoc.js")));
    const index = { sections: [], finding_links: {} };
    const docOf = (body) => ({
      slug: "x", path: "docs/x.md", section: "start", kind: "doc", title: "X", description: "",
      page_type: "doc", generated: false, frontmatter: {}, body,
    });
    const page = render(md.default, {
      doc: docOf("Prose with `inline` code.\n\n```\nplain fence\nline two\n```\n\n```bash\necho tagged\n```\n"),
      index,
    });
    const pres = page.match(/<pre[^>]*>[\s\S]*?<\/pre>/g) || [];
    if (pres.length !== 2) fail(`expected 2 code blocks, got ${pres.length}`);
    else if (pres.some((p) => /bg-slate-100/.test(p))) fail("a fenced block carries the inline-code light background (white bars)");
    else if (!/plain fence/.test(pres[0]) || !/echo tagged/.test(pres[1])) fail("fenced block text missing");
    else if (!/<code class="bg-slate-100[^"]*">inline<\/code>/.test(page)) fail("inline code lost its style");
    else console.log("  ok  fences with and without a language render as dark blocks; inline code keeps its style");
    const logo = render(md.default, { doc: docOf('![Logo](/docs/images/x.png "width=250")\n\n# Title\n'), index: { ...index, image_route: "/api/docs/image", repo_url: "", repo_branch: "master" } });
    if (!/<img[^>]*width="250"/.test(logo) || /title="width=250"/.test(logo)) fail("README logo width not applied (or leaked as a tooltip)");
    else if (md.imageWidth("hello") !== undefined) fail("a real title mistaken for a width");
    else console.log("  ok  an HTML <img width> from a README keeps its width");
    const png1x1 = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==";
    const embedded = render(md.default, { doc: docOf(`![][shot]\n\n[shot]: <${png1x1}>\n`), index: { ...index, image_route: "/api/docs/image", repo_url: "", repo_branch: "master" } });
    if (!/<img[^>]*src="data:image\/png;base64,/.test(embedded)) fail("embedded data:image screenshot dropped (empty src)");
    else if (md.docUrlTransform("javascript:alert(1)") !== "") fail("unsafe URL scheme let through");
    else console.log("  ok  embedded data:image screenshots render; unsafe schemes still dropped");
    const noSrc = render(md.default, { doc: docOf("![missing]()\n"), index: { ...index, image_route: "/api/docs/image", repo_url: "", repo_branch: "master" } });
    if (/<img/.test(noSrc)) fail("an image with no source still rendered an <img>");
    else console.log("  ok  an image with no source renders no <img>");
  } catch (e) {
    fail(`MarkdownDoc could not be rendered: ${e && e.message ? e.message : e}`);
  }

  // ── which judge URLs count as local ───────────────────────────────
  console.log("\nlocal judge urls:");
  const { isPrivateUrl } = await import(pathToFileURL(join(out, "lib/urls.js")));
  const local = ["http://localhost:1234/v1", "http://127.0.0.1:8001", "http://192.168.1.23:8001/v1", "http://spark-c2e5.local:8001", "http://10.0.0.5:8000", "http://172.20.1.1:8000"];
  const remote = ["https://api.openai.com/v1", "http://172.32.0.1:8000", "http://8.8.8.8", "not a url"];
  const wrongLocal = local.filter((u) => !isPrivateUrl(u));
  const wrongRemote = remote.filter((u) => isPrivateUrl(u));
  if (wrongLocal.length || wrongRemote.length) fail(`isPrivateUrl wrong for ${JSON.stringify([...wrongLocal, ...wrongRemote])}`);
  else console.log("  ok  LAN/.local/loopback are local; hosted and public addresses are not");

  // ── response time card ─────────────────────────────────────────────
  console.log("\nresponse time:");
  const rt = await import(pathToFileURL(join(out, "components/ResponseTime.js")));
  const turn = (seq, role, lat, text = "") => ({ sequence_num: seq, role, latency_seconds: lat, content_preview: text, content: null, archived: false, timestamp: null, has_tool_use: false, slash_command: null, sentiment: null });
  const turns = [turn(1, "user", null, "q"), turn(2, "assistant", 0.5), turn(3, "assistant", 2), turn(4, "assistant", 45, "running the test suite"), turn(5, "assistant", 964, "reading the whole tree"), turn(6, "user", 3)];
  const h = rt.latencyBuckets(turns);
  if (h.measured !== 4 || h.slow !== 2) fail(`measured/slow wrong: ${JSON.stringify(h)}`);
  else if (h.buckets.map((b) => b.count).join(",") !== "1,1,0,0,1,0,1") fail(`bands wrong: ${h.buckets.map((b) => b.count)}`);
  else console.log("  ok  histogram counts assistant turns only, into the right bands");
  if (!/2 of 4 assistant turns \(50%\) took 30 s or longer/.test(rt.latencyVerdict(4, 2))) fail("verdict text");
  else if (!/under 30 s/.test(rt.latencyVerdict(4, 0)) || !/nothing is measured/.test(rt.latencyVerdict(0, 0))) fail("verdict edge cases");
  else console.log("  ok  the verdict names the share over 30 s, or says all fast / nothing measured");
  const card = render(rt.default, { latency: { measured_turns: 4, p50: 2, p90: 45, max: 964, slowest: [{ sequence_num: 5, seconds: 964 }, { sequence_num: 4, seconds: 45 }] }, turns });
  if (!/Median response/.test(card) || !/16m 4s/.test(card) || !/50%/.test(card)) fail("KPI tiles missing");
  else if (!/href="#turn-5"/.test(card) || !/reading the whole tree/.test(card)) fail("slowest table lacks the link or the turn text");
  else if (!/bg-rose-500/.test(card) || !/width:100%/.test(card)) fail("histogram bars missing");
  else console.log("  ok  card: tiles, bars, slowest-turn table with links and text");

  // ── session header ─────────────────────────────────────────────────
  console.log("\nsession header:");
  const sh = await import(pathToFileURL(join(out, "components/SessionHeader.js")));
  const es = (median, p90) => ({ observations: 14, sufficient: true, median, p90, max: p90 * 2 });
  const v = sh.versusProject(4659, es(2114, 6457));
  if (!/2\.2× the project median/.test(v.note) || v.tone !== "default") fail(`versus: ${JSON.stringify(v)}`);
  else if (sh.versusProject(7000, es(2114, 6457)).tone !== "warn" || !/above its p90/.test(sh.versusProject(7000, es(2114, 6457)).note)) fail("past-p90 not flagged");
  else if (sh.versusProject(2100, es(2114, 6457)).note !== "about the project median") fail("near-median wording");
  else if (sh.versusProject(5, { observations: 3, sufficient: false, median: 4, p90: 9, max: 9 }).note !== "") fail("insufficient baseline must say nothing");
  else if (sh.projectName("/Users/x/dev/repo/code-copilot-team/") !== "code-copilot-team" || sh.projectName(null) !== "(no project path)") fail("project name");
  else console.log("  ok  comparison wording: ×median, near-median, above p90, withheld when insufficient");
  const detail = { id: 1, copilot: "claude-code", session_id: "abc", project_path: "/Users/x/dev/repo/code-copilot-team", model: "claude-opus-5", turn_count: 4659, tool_call_count: 1543, error_count: 46, started_at: "2026-09-03T11:46:54Z", duration_seconds: 284400, cost_usd: null, turns: [], tool_usage: [], errors: [], latency: null };
  const base = { scope: "project", sessions: 14, turns: es(2114, 6457), tool_calls: es(600, 2000), errors: es(10, 40), duration_seconds: es(100000, 250000), cost_usd: { observations: 0, sufficient: false, median: null, p90: null, max: null }, cost_usd_coverage: { sessions_with_any_priced_turn: 0, sessions_fully_priced: 0, sessions_with_priceable_turns: 0 }, min_observations: 5, basis: "" };
  const head = render(sh.default, { data: detail, baseline: base });
  if (!/<h1[^>]*>code-copilot-team<\/h1>/.test(head)) fail("title is not the project name");
  else if (!/claude-opus-5/.test(head) || !/claude-code/.test(head)) fail("copilot/model badges missing");
  else if (!/2\.2× the project median/.test(head) || !/1\.0 per 100 turns/.test(head) || !/above its p90/.test(head)) fail("tile notes missing");
  else if (!/14 other sessions of this project/.test(head) || !/no priced turns/.test(head)) fail("baseline fact or cost note missing");
  else if (!/<dt[^>]*>Started<\/dt>/.test(head) || !/<dt[^>]*>Session id<\/dt>/.test(head) || !/>abc</.test(head)) fail("labelled facts (Started, Session id) missing");
  else console.log("  ok  header: project title, badges, five tiles with comparisons");
  const bare = render(sh.default, { data: { ...detail, project_path: null, model: null, started_at: null, duration_seconds: null }, baseline: null });
  if (!/no project path/.test(bare) || !/too few sessions of this project/.test(bare) || /×/.test(bare)) fail("header without a project/baseline still claims a comparison");
  else console.log("  ok  no project path / no baseline: nothing compared, nothing invented");

  if (!process.exitCode) console.log("\nstates-check: all states asserted");
} finally {
  rmSync(out, { recursive: true, force: true });
}
