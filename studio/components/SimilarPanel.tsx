// Similar-sessions panel (#293 T3; FR-A, FR-C, FR-E).
//
// Pure presentational, like ClustersView, so the D8 states script can
// render every state without a server.
//
// NO TEXT SNIFFING HERE, AND NONE NEEDED. The two states FR-C names for
// this surface are already STRUCTURALLY distinct:
//
//   unclustered / no neighbours -> 200 with neighbors: []
//   absent from the graph       -> 503 with a prerequisite
//
// and `similar_sessions` supplies a guidance string TAILORED per case
// (run embed, run graph, run graph then similar). So the panel renders
// what it is given rather than reconstructing which case applies —
// which is why no `state` discriminator was added upstream for T3: the
// #289 tools stay byte-unchanged.
//
// FR-A: no sort. Neighbours arrive best-first from the producer.

import { Card } from "@/components/ui";
import type { SimilarOutcome } from "@/lib/similarStates";
import { SIMILAR_COPY } from "@/lib/similarStates";

export default function SimilarPanel({ state }: { state: SimilarOutcome }) {
  if (state.kind === "prerequisite") {
    // The remedy differs per case and the producer already phrased it;
    // rendering its own guidance is more honest than re-deriving a
    // sentence from the error text.
    return (
      <Card title="Similar sessions">
        <p className="text-sm text-slate-700">{SIMILAR_COPY.prerequisite}</p>
        <p className="text-sm text-slate-600 mt-2">{state.detail.error}</p>
        <p className="text-sm text-slate-500 mt-1">{state.detail.guidance}</p>
      </Card>
    );
  }

  if (state.kind === "failed") {
    return (
      <Card title="Similar sessions">
        <p className="text-sm text-slate-700">{SIMILAR_COPY.failed}</p>
        <p className="text-xs text-slate-500 mt-2">{state.message}</p>
      </Card>
    );
  }

  if (state.kind === "none") {
    // HEALTHY: every prerequisite held, the snapshot simply holds no
    // edges for this session. Not a failure, and deliberately different
    // copy from the missing-graph-node case above (#289 FR-F).
    return (
      <Card title="Similar sessions">
        <p className="text-sm text-slate-700">{SIMILAR_COPY.none}</p>
        <p className="text-sm text-slate-500 mt-2">
          Re-run <code>similar</code> after embedding more sessions to change
          that.
        </p>
      </Card>
    );
  }

  const { response } = state;
  return (
    <Card title="Similar sessions">
      <p className="text-sm text-slate-500">{SIMILAR_COPY.neighbours}</p>
      <ul className="mt-3 space-y-2">
        {/* No .sort(): the producer's order is the contract (FR-A). */}
        {response.neighbors.map((n) => (
          <li
            key={n.session_key}
            className="flex items-baseline justify-between gap-3 border border-slate-200 rounded p-2"
          >
            <span className="font-mono text-xs">{n.session_key}</span>
            <span className="text-xs text-slate-500">
              score {n.score.toFixed(3)}
            </span>
          </li>
        ))}
      </ul>
      {/* FR-E: basis and the snapshot note are DISPLAYED, and nothing
          here implies that every pair of neighbours is similar. */}
      <div className="text-xs text-slate-500 border-t border-slate-200 mt-3 pt-3 space-y-1">
        <div>
          <span className="font-medium text-slate-600">Basis:</span>{" "}
          {response.basis}
        </div>
        <div>{response.scores_are}</div>
        <div>{SIMILAR_COPY.notPairwise}</div>
      </div>
    </Card>
  );
}
