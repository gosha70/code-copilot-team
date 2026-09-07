"use client";

import Link from "next/link";
import {
  CostByOutcome,
  DashboardLatency,
  LabelDistribution,
  PhaseProcessReport,
  RecentError,
} from "@/lib/api";
import {
  Bar,
  Card,
  SEMANTIC_COLORS,
  SERIES_COLORS,
  Stat,
  formatCost,
  formatDuration,
} from "@/components/ui";

// Dashboard cards for #307 (Studio Phase 2). Every component here is a
// PURE RENDERER over an API payload — the page owns the fetches, each
// isolated so one failing endpoint cannot blank the rest — and the
// states-check script renders them from fixtures. Each card answers one
// question a person has, or says plainly why it cannot yet.

// A refresh that failed after a successful load must not present old
// numbers as current (the DevelopersPanel rule); a first load that
// failed must not leave a blank where a card was.
export function StaleNote({ error }: { error?: string | null }) {
  if (!error) return null;
  return (
    <p className="text-xs text-amber-700 mb-2">
      Refresh failed ({error}) — showing the last successful load.
    </p>
  );
}

export function FailedCard({ title, error }: { title: string; error: string }) {
  return (
    <Card title={title}>
      <p className="text-sm text-slate-700">This card could not be loaded.</p>
      <p className="text-xs text-slate-500 mt-1">{error}</p>
    </Card>
  );
}

// ── "How fast does the agent answer?" ────────────────────────────────
export function LatencyStat({
  data,
  error,
}: {
  data: DashboardLatency | null;
  error: string | null;
}) {
  if (!data) {
    return (
      <Stat
        label="Median agent response"
        value="—"
        note={error ? "could not be loaded" : "loading…"}
      />
    );
  }
  if (data.measured_turns === 0 || data.p50 == null) {
    return (
      <Stat
        label="Median agent response"
        value="—"
        note={
          "no turn carries timestamps on both sides yet" +
          (error ? " · refresh failed, last successful load" : "")
        }
      />
    );
  }
  return (
    <Stat
      label="Median agent response"
      value={formatDuration(data.p50)}
      note={
        `p90 ${formatDuration(data.p90)} · over ` +
        `${data.measured_turns.toLocaleString()} assistant turns in ` +
        `${data.sessions.toLocaleString()} sessions` +
        (error ? " · refresh failed, last successful load" : "")
      }
    />
  );
}

// ── "Where does the money go?" ───────────────────────────────────────
export function CostByOutcomeCard({
  data,
  stale,
}: {
  data: CostByOutcome;
  stale?: string | null;
}) {
  const phases = data.by_phase.filter((p) => p.cost_usd > 0);
  const sentiments = data.by_sentiment.filter((s) => s.cost_usd > 0);
  if (phases.length === 0 && sentiments.length === 0) {
    // An empty result is still a RESULT of the last successful load: a
    // failed refresh is annotated here exactly as on a populated card.
    return (
      <Card title="Cost by outcome">
        <StaleNote error={stale} />
        <p className="text-sm text-slate-400">
          No priced turns yet. Cost needs a model with a rate in the pricing
          table; sentiment needs the judge step on the Analysis page.
        </p>
      </Card>
    );
  }
  const maxPhase = Math.max(1, ...phases.map((p) => p.cost_usd));
  const maxSent = Math.max(1, ...sentiments.map((s) => s.cost_usd));
  return (
    <Card title="Cost by outcome">
      <StaleNote error={stale} />
      {phases.length > 0 && (
        <div className="mb-3">
          <p className="text-xs font-medium text-slate-500 uppercase tracking-wide mb-1">
            By workflow phase
          </p>
          {phases.map((p, i) => (
            <Bar
              key={p.phase}
              label={`${p.phase && p.phase !== "(none)" ? p.phase : "no phase recorded"} (${p.sessions})`}
              value={p.cost_usd}
              max={maxPhase}
              color={SERIES_COLORS[i % SERIES_COLORS.length]}
              format={formatCost}
            />
          ))}
        </div>
      )}
      {sentiments.length > 0 && (
        <div>
          <p className="text-xs font-medium text-slate-500 uppercase tracking-wide mb-1">
            By turn sentiment
          </p>
          {sentiments.map((s) => (
            <Bar
              key={s.sentiment}
              label={`${s.sentiment} (${s.turns})`}
              value={s.cost_usd}
              max={maxSent}
              color={SEMANTIC_COLORS[s.sentiment] || "bg-slate-400"}
              format={formatCost}
            />
          ))}
        </div>
      )}
      <p className="text-xs text-slate-400 mt-2">
        Priced turns only; a phase or sentiment with no priced turn is not
        shown.
      </p>
    </Card>
  );
}

// ── "What did the judge see, and where?" ─────────────────────────────
export function LabelDistributionCard({
  data,
  stale,
}: {
  data: LabelDistribution;
  stale?: string | null;
}) {
  const labels = data.labels.filter((l) => l.total > 0);
  if (labels.length === 0) {
    return (
      <Card title="Label distribution">
        <StaleNote error={stale} />
        <p className="text-sm text-slate-400">
          No heuristic labels yet — run the judge step on the Analysis page.
        </p>
      </Card>
    );
  }
  const max = Math.max(1, ...labels.map((l) => l.true));
  return (
    <Card title="Label distribution">
      <StaleNote error={stale} />
      <div className="max-h-72 overflow-y-auto">
        {labels.map((l, i) => (
          <Link
            key={l.label}
            href={`/labels/${encodeURIComponent(l.label)}`}
            className="block hover:bg-slate-50 rounded"
            title={`${l.true.toLocaleString()} of ${l.total.toLocaleString()} labelled turns — open the traces`}
          >
            <Bar
              label={l.label}
              value={l.true}
              max={max}
              color={SERIES_COLORS[i % SERIES_COLORS.length]}
            />
          </Link>
        ))}
      </div>
      <p className="text-xs text-slate-400 mt-2">
        Turns where the label fired. Click a label to read the turns.
      </p>
    </Card>
  );
}

// ── "What broke recently?" ───────────────────────────────────────────
export function RecentErrorsCard({
  errors,
  stale,
}: {
  errors: RecentError[];
  stale?: string | null;
}) {
  if (errors.length === 0) {
    return (
      <Card title="Recent tool errors">
        <StaleNote error={stale} />
        <p className="text-sm text-slate-400">No tool errors recorded.</p>
      </Card>
    );
  }
  return (
    <Card title="Recent tool errors">
      <StaleNote error={stale} />
      <div className="max-h-72 overflow-y-auto">
        <table className="w-full text-sm">
          <thead className="text-left text-slate-500 border-b border-slate-200">
            <tr>
              <th className="py-1 pr-3">Tool</th>
              <th className="pr-3">Error</th>
              <th>Project</th>
            </tr>
          </thead>
          <tbody>
            {errors.slice(0, 15).map((e, i) => (
              <tr key={i} className="border-b border-slate-100 align-top">
                <td className="py-1 pr-3 font-mono text-xs whitespace-nowrap">
                  {e.tool_name || "—"}
                </td>
                <td className="pr-3 text-slate-700">
                  <span className="text-xs text-rose-700 mr-1">
                    {e.error_type}
                  </span>
                  <span className="text-xs text-slate-600 line-clamp-2">
                    {e.message || ""}
                  </span>
                </td>
                <td
                  className="text-xs text-slate-500 truncate max-w-[10rem]"
                  title={e.project_path || undefined}
                >
                  {shortPath(e.project_path)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

// ── "Did the Pi workflow behave?" — only when a project has history ──
export function PhaseProcessCard({
  data,
  stale,
}: {
  data: PhaseProcessReport;
  stale?: string | null;
}) {
  const projects = data.projects.filter((p) => p.has_workflow_history);
  if (projects.length === 0) return null;
  return (
    <Card title="Pi workflow phases">
      <StaleNote error={stale} />
      <div className="space-y-3 max-h-72 overflow-y-auto">
        {projects.map((p) => (
          <div key={p.project_path}>
            <p
              className="text-sm font-medium text-slate-800 truncate"
              title={p.project_path}
            >
              {shortPath(p.project_path)}
            </p>
            <table className="w-full text-xs mt-1">
              <thead className="text-left text-slate-500">
                <tr>
                  <th className="pr-2">Feature</th>
                  <th className="pr-2 text-right">Moves</th>
                  <th className="pr-2 text-right">Oscillations</th>
                  <th className="pr-2 text-right">Rework</th>
                  <th>Review</th>
                </tr>
              </thead>
              <tbody>
                {p.features.map((f) => (
                  <tr key={f.feature_id} className="border-t border-slate-100">
                    <td className="pr-2 font-mono">{f.feature_id}</td>
                    <td className="pr-2 text-right tabular-nums">
                      {f.entries}
                    </td>
                    <td className="pr-2 text-right tabular-nums">
                      {f.oscillations}
                    </td>
                    <td className="pr-2 text-right tabular-nums">
                      {f.rework_cycles}
                    </td>
                    <td>{f.review_observed ? "observed" : "not observed"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {p.history_may_be_truncated && (
              <p className="text-xs text-amber-700 mt-1">
                History is capped at {data.retention_cap} entries; earlier moves
                may have been evicted.
              </p>
            )}
          </div>
        ))}
      </div>
      <p className="text-xs text-slate-400 mt-2">{data.absence_note}</p>
    </Card>
  );
}

// The last two path segments: enough to tell projects apart without
// the home-directory prefix every row shares.
export function shortPath(path: string | null): string {
  if (!path) return "—";
  const parts = path.split("/").filter(Boolean);
  return parts.length <= 2 ? path : "…/" + parts.slice(-2).join("/");
}
