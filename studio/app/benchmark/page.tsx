"use client";

import Link from "next/link";
import { api, RoutingEvidenceEntry } from "@/lib/api";
import { FailedCard, StaleNote } from "@/components/DashboardCards";
import {
  Badge,
  Card,
  ErrorNote,
  Loading,
  Stat,
  formatCost,
  formatDuration,
  useApi,
} from "@/components/ui";

export default function BenchmarkPage() {
  // D-refresh: one-shot fetch — benchmark data only changes when `correlate`
  // runs, unlike live session ingest (no auto-refresh in this slice).
  const { data, error, loading } = useApi(() => api.benchmark());
  // #307: the outcome base rate and the routing evidence are both
  // benchmark-derived, so they live here; each is its own fetch so a
  // missing one cannot blank the page.
  const outcome = useApi(() => api.predictOutcome());
  const routing = useApi(() => api.routingEvidence());
  if (loading) return <Loading />;
  if (error || !data) return <ErrorNote error={error || "no data"} />;

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Benchmark</h1>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Stat label="Sessions (total)" value={data.sessions_total} />
        <Stat label="Benchmark-linked sessions" value={data.sessions_linked} />
        <Stat label="Organic (unlinked) sessions" value={data.sessions_unlinked} />
        <Stat label="Distinct benchmark attempts" value={data.distinct_benchmark_attempts} />
      </div>

      {outcome.data ? (
        <OutcomeRow data={outcome.data} stale={outcome.error} />
      ) : outcome.error ? (
        <FailedCard title="Predicted pass rate by project" error={outcome.error} />
      ) : null}

      {data.by_result.length === 0 ? (
        <Card title="No benchmark outcomes yet">
          <p className="text-sm text-slate-600">
            No benchmark results have been ingested into this store. After a
            benchmark run, link its artifacts and ingest the outcomes with:
          </p>
          <pre className="mt-3 bg-slate-50 border border-slate-200 rounded p-3 text-xs overflow-x-auto">
            ./scripts/session-analytics correlate --runs-root &lt;benchmark runs dir&gt;
          </pre>
          <p className="text-sm text-slate-500 mt-3">
            Outcomes appear here per result (pass / fail / error / timeout),
            compared by attempts, linked sessions, cost, and duration.
          </p>
        </Card>
      ) : (
        <Card title="Sessions by benchmark result">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-slate-500 border-b border-slate-200">
                  <th className="py-2 pr-4 font-medium">Result</th>
                  <th className="py-2 pr-4 font-medium text-right">Attempts</th>
                  <th className="py-2 pr-4 font-medium text-right">Linked sessions</th>
                  <th className="py-2 pr-4 font-medium text-right">Total linked cost</th>
                  <th className="py-2 font-medium text-right">Avg session duration</th>
                </tr>
              </thead>
              <tbody>
                {data.by_result.map((row) => (
                  <tr key={row.result} className="border-b border-slate-100">
                    <td className="py-2 pr-4">
                      <Badge kind={row.result}>{row.result}</Badge>
                    </td>
                    <td className="py-2 pr-4 text-right tabular-nums">{row.attempts}</td>
                    <td className="py-2 pr-4 text-right tabular-nums">{row.linked_sessions}</td>
                    <td className="py-2 pr-4 text-right tabular-nums">
                      {/* The endpoint coerces SQL NULL (unpriced turns) to 0.0,
                          so 0 here means "no price data", never "free" — dash
                          it per the formatCost convention. */}
                      {row.total_cost_usd > 0 ? formatCost(row.total_cost_usd) : "—"}
                    </td>
                    <td className="py-2 text-right tabular-nums">
                      {formatDuration(row.avg_duration_seconds)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-xs text-slate-400 mt-3">
            Cost and duration aggregate over distinct linked sessions only
            (unlinked attempts count in Attempts but contribute no cost);
            &ldquo;—&rdquo; means no linked or priced data, never zero.
          </p>
        </Card>
      )}
      <RoutingCard
        sets={routing.data?.sets ?? null}
        error={routing.error}
      />
    </div>
  );
}

// "Will the next attempt pass?" — /api/predict/outcome: per-project pass
// rates from benchmark results, withheld below the sample floor.
function OutcomeRow({
  data,
  stale,
}: {
  data: import("@/lib/api").OutcomePrediction;
  stale?: string | null;
}) {
  const shown = data.projects.filter((p) => p.sufficient);
  if (data.sessions_with_outcome === 0) return null;
  return (
    <Card title="Predicted pass rate by project">
      <StaleNote error={stale} />
      {shown.length === 0 ? (
        <p className="text-sm text-slate-400">
          {data.sessions_with_outcome.toLocaleString()} sessions carry a
          benchmark outcome, but no project has {data.min_observations} yet —
          a rate over fewer would not mean anything.
        </p>
      ) : (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {shown.map((p) => (
            <Stat
              key={p.project_path || "(none)"}
              label={p.project_path?.split("/").filter(Boolean).slice(-1)[0] || "(no project)"}
              value={
                p.predicted_pass_rate == null
                  ? "—"
                  : `${Math.round(p.predicted_pass_rate * 100)}%`
              }
              note={`${p.attempts} attempts`}
            />
          ))}
        </div>
      )}
      <p className="text-xs text-slate-400 mt-3">{data.basis}</p>
    </Card>
  );
}

// Routing evidence lives on its own page (/routing, with calibration);
// this card is the doorway, and says when there is nothing behind it.
function RoutingCard({
  sets,
  error,
}: {
  sets: RoutingEvidenceEntry[] | null;
  error: string | null;
}) {
  const valid = (sets ?? []).filter((s) => s.state === "valid");
  const invalid = (sets ?? []).length - valid.length;
  return (
    <Card title="Routing evidence">
      {sets === null ? (
        <p className="text-sm text-slate-400">
          {error ? "Routing evidence could not be loaded." : "Loading…"}
        </p>
      ) : sets.length === 0 ? (
        <p className="text-sm text-slate-600">
          No routing evidence sets published. Point{" "}
          <code>CCT_SA_ROUTING_EVIDENCE_ROOTS</code> at a publication root to
          see them here.
        </p>
      ) : (
        <p className="text-sm text-slate-700">
          {valid.length.toLocaleString()} valid set{valid.length === 1 ? "" : "s"}
          {invalid > 0 && (
            <span className="text-rose-700"> · {invalid} invalid</span>
          )}
          .
        </p>
      )}
      <Link href="/routing" className="text-sm text-blue-700 hover:underline mt-2 inline-block">
        Open Routing: evidence sets, recommendations and calibration →
      </Link>
    </Card>
  );
}
