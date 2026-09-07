"use client";

import { api } from "@/lib/api";
import {
  Bar,
  Card,
  ErrorNote,
  Loading,
  SEMANTIC_COLORS,
  SERIES_COLORS,
  Stat,
  formatDuration,
  useApi,
} from "@/components/ui";
import DevelopersPanel from "@/components/DevelopersPanel";
import {
  CostByOutcomeCard,
  FailedCard,
  LabelDistributionCard,
  LatencyStat,
  PhaseProcessCard,
  RecentErrorsCard,
} from "@/components/DashboardCards";

const REFRESH_MS = 15000;

export default function DashboardPage() {
  const { data, error, loading } = useApi(() => api.dashboard(), [], REFRESH_MS);
  // E1 (#65): fetched separately so a failure here cannot blank the
  // whole dashboard — the panel is additive, not a prerequisite.
  const devs = useApi(() => api.developers(), [], REFRESH_MS);
  // #307: each additional card is its own fetch for the same reason —
  // a card that cannot load says so in its own space.
  const latency = useApi(() => api.latency(), [], REFRESH_MS);
  const cost = useApi(() => api.costByOutcome(), [], REFRESH_MS);
  const labels = useApi(() => api.labels(), [], REFRESH_MS);
  const errors = useApi(() => api.recentErrors(), [], REFRESH_MS);
  const phases = useApi(() => api.phaseProcess(), []);
  if (loading) return <Loading />;
  if (error || !data) return <ErrorNote error={error || "no data"} />;

  const maxTool = Math.max(1, ...data.tool_usage.map((t) => t.count));
  const maxCopilot = Math.max(1, ...data.by_copilot.map((c) => c.sessions));

  return (
    <div className="space-y-6">
      <div className="flex items-baseline gap-2">
        <h1 className="text-2xl font-bold">Dashboard</h1>
        <span className="text-slate-400 text-xs">
          Auto-refreshing every {REFRESH_MS / 1000}s
        </span>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-6 gap-4">
        {/* Every figure on this page is over the SAME sessions; the note
            says what was left out so the count matches the Sessions
            page and the Analysis funnel. */}
        <Stat
          label="Sessions"
          value={data.totals.sessions}
          note={
            data.totals.excluded_noise > 0
              ? `${data.totals.excluded_noise.toLocaleString()} excluded as noise`
              : undefined
          }
        />
        <Stat label="Turns" value={data.totals.turns} />
        <Stat label="Tool calls" value={data.totals.tool_calls} />
        {/* Errors are not a neutral tally — the card should read as one
            glance at whether anything is wrong. */}
        <Stat label="Errors" value={data.totals.errors} tone="warn" />
        {/* formatDuration, NOT raw seconds: "137027" was rendered as the
            biggest number on the page and means 38 hours, which is not a
            figure anyone recognises as an average session. The shared
            helper exists so duration rendering cannot fork per page. */}
        <Stat
          label="Avg duration"
          value={formatDuration(data.totals.avg_duration_seconds)}
        />
        <LatencyStat data={latency.data} error={latency.error} />
      </div>

      <div className="grid md:grid-cols-2 gap-6">
        <Card title="Sessions by copilot">
          {data.by_copilot.map((c, i) => (
            <Bar
              key={c.copilot}
              label={c.copilot}
              value={c.sessions}
              max={maxCopilot}
              color={SERIES_COLORS[i % SERIES_COLORS.length]}
            />
          ))}
        </Card>

        <Card title="Tool usage (top 25)">
          <div className="max-h-72 overflow-y-auto">
            {data.tool_usage.map((t, i) => (
              <Bar
                key={t.tool}
                label={t.tool}
                value={t.count}
                max={maxTool}
                // Rotating palette: these rows are unrelated categories,
                // not slices of one quantity.
                color={SERIES_COLORS[i % SERIES_COLORS.length]}
              />
            ))}
          </div>
        </Card>

        <Card title="Sentiment distribution">
          {data.sentiment_distribution.length === 0 ? (
            <p className="text-sm text-slate-400">
              No heuristic labels yet — run the Analysis tab.
            </p>
          ) : (
            data.sentiment_distribution.map((s) => (
              <Bar
                key={s.sentiment}
                label={s.sentiment}
                value={s.count}
                max={Math.max(1, ...data.sentiment_distribution.map((x) => x.count))}
                // Semantic, not decorative: NEGATIVE must not be the same
                // colour as POSITIVE just because it is the next row.
                color={SEMANTIC_COLORS[s.sentiment] || "bg-slate-400"}
              />
            ))
          )}
        </Card>

        {/* Each card: data → render (annotated if the last refresh
            failed); no data + error → say so; else still loading. */}
        {cost.data ? (
          <CostByOutcomeCard data={cost.data} stale={cost.error} />
        ) : cost.error ? (
          <FailedCard title="Cost by outcome" error={cost.error} />
        ) : null}
        {labels.data ? (
          <LabelDistributionCard data={labels.data} stale={labels.error} />
        ) : labels.error ? (
          <FailedCard title="Label distribution" error={labels.error} />
        ) : null}
        {errors.data ? (
          <RecentErrorsCard errors={errors.data.errors} stale={errors.error} />
        ) : errors.error ? (
          <FailedCard title="Recent tool errors" error={errors.error} />
        ) : null}
        {phases.data ? (
          <PhaseProcessCard data={phases.data} stale={phases.error} />
        ) : phases.error ? (
          <FailedCard title="Pi workflow phases" error={phases.error} />
        ) : null}

        <Card title="Sessions by day (last 30)">
          <div className="max-h-72 overflow-y-auto">
            {data.by_day.map((d) => (
              <Bar
                key={d.day}
                label={d.day}
                value={d.sessions}
                max={Math.max(1, ...data.by_day.map((x) => x.sessions))}
                // ONE colour here on purpose: every row is the same
                // measure over time, so varying hue would imply a
                // distinction that does not exist.
                color="bg-indigo-500"
              />
            ))}
          </div>
        </Card>
      </div>

      {/* Isolated from the rest of the dashboard, but never silent: a
          first-load failure says so instead of the panel vanishing, and
          a failed REFRESH keeps the last good data with a staleness
          warning rather than presenting it as current. */}
      {devs.data ? (
        <DevelopersPanel data={devs.data} stale={devs.error} />
      ) : devs.error ? (
        <Card title="Developers">
          <p className="text-sm text-slate-700">
            The developer rollup could not be loaded.
          </p>
          <p className="text-xs text-slate-500 mt-2">{devs.error}</p>
        </Card>
      ) : null}
    </div>
  );
}
