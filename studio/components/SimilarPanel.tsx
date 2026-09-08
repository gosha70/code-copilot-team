// Similar-sessions panel (#293 T3; FR-A, FR-C, FR-E), made operable.
//
// Pure presentational, like ClustersView, so the D8 states script can
// render every state without a server.
//
// The two states FR-C names for this surface are STRUCTURALLY distinct
// (no neighbours → 200 with neighbors: []; a missing prerequisite →
// 503 with which one), and the panel renders what it is given. What
// changed: a missing prerequisite is a NEXT STEP, not homework — one
// button runs the pipeline steps that produce it (embed, similar, and
// the graph build first when that is what is missing), with progress
// while they run. Nothing here tells a person to open a terminal.
//
// FR-A: no sort. Neighbours arrive best-first from the producer.

import Link from "next/link";
import { Card } from "@/components/ui";
import type { EmbedProgress, PipelineStep, SimilarNeighbor } from "@/lib/api";
import type { SimilarOutcome } from "@/lib/similarStates";
import { SIMILAR_COPY } from "@/lib/similarStates";
import SessionTagIcons from "@/components/SessionTags";
import { EmbedProgressBar } from "@/components/JudgeProgress";

/** Which pipeline steps produce the missing prerequisite. Pure. */
export function stepsFor(prerequisite: string): string[] {
  if (prerequisite === "graph") return ["graph", "embed", "similar"];
  return ["embed", "similar"];
}

/** One line a person can check: why this neighbour is similar, in
 *  words — shared tools, shared error types, shared files, the same
 *  project — or, honestly, "by transcript meaning only". Pure. */
export function neighbourReason(n: SimilarNeighbor): string {
  const s = n.shared;
  if (!s) return "";
  const parts: string[] = [];
  if (s.same_project) parts.push("same project");
  if (s.tools.length)
    parts.push(
      `shares ${s.tools.slice(0, 4).join(", ")}${s.tools.length > 4 ? "…" : ""}`,
    );
  else if (s.common_tools > 0) parts.push("only the usual tools in common");
  if (s.error_types.length)
    parts.push(`same errors: ${s.error_types.slice(0, 3).join(", ")}`);
  if (s.files.length)
    parts.push(
      `touches ${s.files.slice(0, 3).join(", ")}${s.files.length > 3 ? "…" : ""}`,
    );
  return parts.length
    ? parts.join(" · ")
    : "similar by transcript meaning only";
}

export function projectLabel(path: string | null): string {
  if (!path) return "(no project)";
  const parts = path.replace(/\/+$/, "").split("/");
  return parts[parts.length - 1] || path;
}

function ComputeButton({
  label,
  onCompute,
  disabled,
}: {
  label: string;
  onCompute?: () => void;
  disabled?: boolean;
}) {
  if (!onCompute) return null;
  return (
    <button
      type="button"
      onClick={onCompute}
      disabled={disabled}
      className="mt-3 bg-blue-600 text-white text-sm px-4 py-1.5 rounded hover:bg-blue-700 disabled:opacity-50"
    >
      {label}
    </button>
  );
}

function Running({ steps }: { steps: PipelineStep[] }) {
  const current = steps.find((s) => s.job.state === "running");
  const failed = steps.find((s) => s.job.state === "failed");
  if (failed && !current) {
    return (
      <p className="text-sm text-rose-700 mt-3">
        {failed.title} failed: {failed.job.message}
      </p>
    );
  }
  if (!current)
    return (
      <p className="text-sm text-slate-500 mt-3 animate-pulse">Starting…</p>
    );
  const prog = current.job.progress;
  return (
    <div className="mt-3">
      <p className="text-sm text-slate-700">
        <span className="animate-pulse">{current.title}…</span>
        {current.job.seconds ? (
          <span className="text-slate-500">
            {" "}
            {Math.round(current.job.seconds)}s
          </span>
        ) : null}
      </p>
      {current.id === "embed" && prog && "embedded" in prog && (
        <EmbedProgressBar
          progress={prog as EmbedProgress}
          seconds={current.job.seconds}
          running
        />
      )}
    </div>
  );
}

export default function SimilarPanel({
  state,
  onCompute,
  running,
  computeError,
}: {
  state: SimilarOutcome;
  /** Runs the steps that produce the missing prerequisite (or refreshes
   *  the neighbours). Absent = read-only (the states script). */
  onCompute?: () => void;
  /** The pipeline steps while a compute is in flight; null otherwise. */
  running?: PipelineStep[] | null;
  computeError?: string | null;
}) {
  const busy = !!running;
  if (state.kind === "prerequisite") {
    const missingGraph = state.detail.prerequisite === "graph";
    return (
      <Card title="Similar sessions">
        <p className="text-sm text-slate-700">{SIMILAR_COPY.prerequisite}</p>
        <p className="text-sm text-slate-600 mt-2">
          {missingGraph
            ? "The knowledge graph has not been built for this store, and the embeddings that similarity needs have not been computed."
            : "This session has not been embedded yet — a vector per session is what similarity is computed from."}{" "}
          It is two pipeline steps{missingGraph ? " after the graph build" : ""}
          : embed every session with the model under Settings → Embeddings, then
          link each to its nearest neighbours.
        </p>
        <ComputeButton
          label={
            missingGraph
              ? "Build graph, embed and find similar"
              : "Embed sessions and find similar"
          }
          onCompute={onCompute}
          disabled={busy}
        />
        {running && <Running steps={running} />}
        {computeError && (
          <p className="text-sm text-rose-700 mt-2">{computeError}</p>
        )}
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
          No other session scored above the similarity threshold. Embedding
          sessions loaded since the last pass, then finding similar again, can
          change that.
        </p>
        <ComputeButton
          label="Embed new sessions and find similar again"
          onCompute={onCompute}
          disabled={busy}
        />
        {running && <Running steps={running} />}
        {computeError && (
          <p className="text-sm text-rose-700 mt-2">{computeError}</p>
        )}
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
            className="border border-slate-200 rounded p-2"
          >
            <div className="flex items-center gap-3 flex-wrap">
              <div className="w-28 shrink-0">
                <div
                  className="h-2 rounded bg-slate-100 overflow-hidden"
                  title={`score ${n.score.toFixed(3)}`}
                >
                  <div
                    className="h-2 rounded bg-blue-600"
                    style={{
                      width: `${Math.round(Math.max(0, Math.min(1, n.score)) * 100)}%`,
                    }}
                  />
                </div>
                <div className="text-[11px] text-slate-500 tabular-nums">
                  score {n.score.toFixed(3)}
                </div>
              </div>
              {n.id != null ? (
                <Link
                  href={`/sessions/${n.id}`}
                  className="text-blue-700 hover:underline font-medium"
                >
                  {projectLabel(n.project_path)}
                </Link>
              ) : (
                <span className="font-mono text-xs">{n.session_key}</span>
              )}
              {n.model && (
                <span className="text-xs px-1.5 py-0.5 rounded bg-blue-50 text-blue-700 font-mono">
                  {n.model}
                </span>
              )}
              {n.tags && <SessionTagIcons tags={n.tags} />}
              <span className="text-xs text-slate-500 ml-auto whitespace-nowrap">
                {n.started_at
                  ? new Date(n.started_at).toLocaleDateString()
                  : ""}
                {n.turn_count != null
                  ? ` · ${n.turn_count.toLocaleString()} turns`
                  : ""}
                {n.error_count ? ` · ${n.error_count} errors` : ""}
              </span>
            </div>
            <p className="text-xs text-slate-600 mt-1">{neighbourReason(n)}</p>
            {n.kpi && n.kpi.avg_interaction_quality != null && (
              <p className="text-[11px] text-slate-500 mt-0.5">
                judged: quality {String(n.kpi.avg_interaction_quality)} ·
                corrections {String(n.kpi.correction_rate)} · rework{" "}
                {String(n.kpi.rework_rate)}
              </p>
            )}
          </li>
        ))}
      </ul>
      <ComputeButton
        label="Embed new sessions and find similar again"
        onCompute={onCompute}
        disabled={busy}
      />
      {running && <Running steps={running} />}
      {computeError && (
        <p className="text-sm text-rose-700 mt-2">{computeError}</p>
      )}
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
