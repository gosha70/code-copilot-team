"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { api, BenchmarkSummary, RoutingEvidenceEntry } from "@/lib/api";
import { FailedCard, StaleNote } from "@/components/DashboardCards";
import {
  benchmarkIntro,
  linkJobLine,
  settleWatch,
  shouldPoll,
} from "@/lib/benchmarkIntro";
import {
  Badge,
  Card,
  ErrorNote,
  Loading,
  Stat,
  describeError,
  formatCost,
  formatDuration,
  useApi,
} from "@/components/ui";

export default function BenchmarkPage() {
  // The link step runs in the background. Polling follows the SERVER's
  // job state; `pending` covers the gap right after the button is
  // pressed, while useApi still holds the response from before it (see
  // lib/benchmarkIntro: shouldPoll / settleWatch).
  const [version, setVersion] = useState(0);
  const [pending, setPending] = useState<BenchmarkSummary | null>(null);
  const [linkError, setLinkError] = useState<string | null>(null);
  const [polling, setPolling] = useState(false);
  const { data, error, loading } = useApi(
    () => api.benchmark(),
    [version],
    polling ? 1500 : undefined,
  );
  // #307: the outcome base rate and the routing evidence are both
  // benchmark-derived, so they live here; each is its own fetch so a
  // missing one cannot blank the page.
  const outcome = useApi(() => api.predictOutcome(), [version]);
  const routing = useApi(() => api.routingEvidence());
  const lastState = useRef<string | null>(null);

  useEffect(() => {
    setPending((p) => settleWatch(p, data));
  }, [data]);
  useEffect(() => {
    setPolling(shouldPoll(pending, data));
  }, [pending, data]);
  // When a scan ends, the outcome row (and the page) are refetched once.
  useEffect(() => {
    const now = data?.link_job.state ?? null;
    if (lastState.current === "running" && now !== null && now !== "running") {
      setVersion((v) => v + 1);
    }
    lastState.current = now;
  }, [data]);

  async function link() {
    setLinkError(null);
    try {
      await api.runStep("correlate");
      // Hold the response we had BEFORE the press: its "idle" is stale.
      setPending(data);
      setVersion((v) => v + 1);
    } catch (e) {
      setLinkError(describeError(e));
    }
  }

  if (loading && !data) return <Loading />;
  if (error || !data) return <ErrorNote error={error || "no data"} />;
  const intro = benchmarkIntro(data);
  const running = polling;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Benchmark</h1>
        <p className="text-sm text-slate-500 mt-1">
          Results of this repository&rsquo;s benchmark harness. A run attempts
          tasks from a public benchmark (Aider Polyglot, SWE-bench) with a
          copilot and scores each attempt pass or fail. Outcomes are imported
          for every backend; session linking applies to Claude Code runs whose
          run record names a Claude Code session that is loaded here, and a
          linked session tells you what its outcome cost and how long it took.
          Nothing is here until you run the harness and link its runs.{" "}
          <Link href="/learn/benchmarks--README" className="text-blue-700 hover:underline">
            How to run the harness →
          </Link>
        </p>
      </div>

      <Card>
        <p className="text-sm text-slate-700">{intro.headline}</p>
        {intro.cause && (
          <p className="text-sm text-slate-600 mt-1">{intro.cause}</p>
        )}
        {intro.rootLine && (
          <p className="text-xs text-slate-500 mt-2">
            Runs folder: <span className="font-mono">{intro.rootLine}</span>{" "}
            <Link href="/settings" className="text-blue-700 hover:underline">
              change
            </Link>
          </p>
        )}
        <div className="flex items-center gap-3 mt-3 flex-wrap">
          {intro.canLink ? (
            <button
              type="button"
              onClick={link}
              disabled={running}
              className="bg-blue-600 text-white text-sm px-4 py-1.5 rounded hover:bg-blue-700 disabled:opacity-50"
            >
              {running
                ? "Linking…"
                : intro.state === "linked" || intro.state === "outcomes-only"
                  ? "Link benchmark runs again"
                  : "Link benchmark runs"}
            </button>
          ) : (
            <Link
              href="/settings"
              className="bg-blue-600 text-white text-sm px-4 py-1.5 rounded hover:bg-blue-700"
            >
              Set the runs folder in Settings
            </Link>
          )}
          {linkJobLine(data.link_job) && (
            <span
              className={`text-xs ${
                data.link_job.state === "failed" ? "text-rose-700" : "text-slate-500"
              }`}
            >
              {linkJobLine(data.link_job)}
            </span>
          )}
          {linkError && <span className="text-xs text-rose-700">{linkError}</span>}
        </div>
        {intro.state !== "linked" && intro.state !== "outcomes-only" && (
          <p className="text-xs text-slate-500 mt-3">
            Once scanned, this page shows attempts by result (pass / fail /
            error / timeout) with linked sessions, cost and duration, and the
            predicted pass rate per project.
          </p>
        )}
      </Card>

      {outcome.data ? (
        <OutcomeRow data={outcome.data} stale={outcome.error} />
      ) : outcome.error ? (
        <FailedCard title="Predicted pass rate by project" error={outcome.error} />
      ) : null}

      {data.by_result.length > 0 && (
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
