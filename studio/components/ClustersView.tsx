// Presentational clusters view (#293 T2; FR-A, FR-C, FR-D, FR-E).
//
// PURE: it takes a ClustersState and renders. All fetching lives in the
// page, so the D8 script can render every one of the eight states
// deterministically without a server — a view that could only be seen
// by running the pipeline could only be checked by eye.
//
// FR-A: THIS FILE CONTAINS NO SORT. Ordering is the reader's contract
// (descending size, then ascending identity) and arrives already
// correct; `.sort()` anywhere here would fork the rule silently. The
// same applies to members, which arrive sorted by session_key.

import { Card } from "@/components/ui";
import {
  COPY,
  capNotice,
  type ClusterReport,
  type ClustersState,
} from "@/lib/clusterStates";

function Limitations({ report }: { report: ClusterReport }) {
  // FR-E: the limitations block is DISPLAYED, not merely fetched. A
  // cluster that travels without them invites the two claims #289
  // refuses — all-pairs similarity, and current-envelope equality.
  return (
    <div className="text-xs text-slate-500 border-t border-slate-200 pt-3 space-y-1">
      <div>
        <span className="font-medium text-slate-600">Membership basis:</span>{" "}
        {report.membership_basis}
      </div>
      <div>
        <span className="font-medium text-slate-600">Inventory basis:</span>{" "}
        {report.inventory_basis}
      </div>
      <ul className="list-disc ml-4 space-y-0.5">
        {report.limitations.map((l) => (
          <li key={l}>{l}</li>
        ))}
      </ul>
    </div>
  );
}

function Counts({ report }: { report: ClusterReport }) {
  // Displayed verbatim (FR-A): nothing here sums, averages or re-counts.
  return (
    <div className="flex gap-6 text-sm">
      <div>
        <span className="font-semibold">{report.cluster_count}</span>{" "}
        <span className="text-slate-500">clusters</span>
      </div>
      <div>
        <span className="font-semibold">{report.clustered_sessions}</span>{" "}
        <span className="text-slate-500">clustered sessions</span>
      </div>
      <div>
        <span className="font-semibold">{report.unclustered_sessions}</span>{" "}
        <span className="text-slate-500">unclustered</span>
      </div>
      <div>
        <span className="font-semibold">{report.graph_sessions}</span>{" "}
        <span className="text-slate-500">in the graph</span>
      </div>
    </div>
  );
}

export default function ClustersView({ state }: { state: ClustersState }) {
  if (state.kind === "prerequisite") {
    // FR-C: absent and unbuilt are DIFFERENT sentences, because they
    // have different remedies. The branch is on the classified state,
    // never on message text at this layer.
    return (
      <Card title="Clusters unavailable">
        <p className="text-sm text-slate-700">
          {state.unbuilt ? COPY.unbuiltMarker : COPY.absentMarker}
        </p>
        <p className="text-sm text-slate-500 mt-2">{state.detail.guidance}</p>
        <pre className="mt-2 bg-slate-100 rounded p-2 text-xs overflow-x-auto">
          {state.unbuilt
            ? "./scripts/session-analytics graph\n./scripts/session-analytics similar"
            : "./scripts/session-analytics graph"}
        </pre>
      </Card>
    );
  }

  if (state.kind === "prerequisiteUnnamed") {
    // Render the server's own words and claim NOTHING about which
    // prerequisite it is. Guessing "absent" here would be a confident
    // wrong remedy — the same failure as collapsing three states into
    // one empty panel, arriving from the other direction.
    return (
      <Card title="Clusters unavailable">
        <p className="text-sm text-slate-700">{COPY.unnamedMarker}</p>
        <p className="text-sm text-slate-600 mt-2">{state.detail.error}</p>
        <p className="text-sm text-slate-500 mt-1">{state.detail.guidance}</p>
      </Card>
    );
  }

  if (state.kind === "failed") {
    return (
      <Card title="Clusters unavailable">
        <p className="text-sm text-slate-700">{COPY.failedMarker}</p>
        <p className="text-xs text-slate-500 mt-2">{state.message}</p>
      </Card>
    );
  }

  if (state.kind === "empty") {
    // A RESULT, not a failure (#289 FR-E: the CLI's exit 0).
    return (
      <Card title="Clusters">
        <p className="text-sm text-slate-700">{COPY.emptyMarker}</p>
        <p className="text-sm text-slate-500 mt-2">
          Every prerequisite held; the stored snapshot simply groups no
          sessions. Re-run <code>similar</code> after embedding more sessions to
          change that.
        </p>
        <div className="mt-4">
          <Counts report={state.report} />
        </div>
        <div className="mt-4">
          <Limitations report={state.report} />
        </div>
      </Card>
    );
  }

  const { report } = state;
  const cap = capNotice(report);
  return (
    <Card title="Clusters">
      <p className="text-sm text-slate-500">{COPY.populatedMarker}</p>
      <div className="mt-3">
        <Counts report={report} />
      </div>
      {cap && <p className="mt-2 text-xs text-amber-700">{cap}</p>}
      <ul className="mt-4 space-y-3">
        {/* No .sort(): the reader's order is the contract (FR-A). */}
        {report.clusters.map((c) => (
          <li key={c.identity} className="border border-slate-200 rounded p-3">
            <div className="flex items-baseline justify-between gap-3">
              <span className="font-mono text-sm">{c.identity}</span>
              <span className="text-xs text-slate-500">
                {c.size} sessions · {c.directed_edge_count} stored edges
              </span>
            </div>
            <ul className="mt-2 text-xs font-mono text-slate-600 space-y-0.5">
              {c.members.map((m) => (
                <li key={m}>{m}</li>
              ))}
            </ul>
          </li>
        ))}
      </ul>
      <div className="mt-4">
        <Limitations report={report} />
      </div>
    </Card>
  );
}
