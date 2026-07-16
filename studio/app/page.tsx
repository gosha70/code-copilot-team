"use client";

import { api } from "@/lib/api";
import { Bar, Card, ErrorNote, Loading, Stat, useApi } from "@/components/ui";

const REFRESH_MS = 15000;

export default function DashboardPage() {
  const { data, error, loading } = useApi(() => api.dashboard(), [], REFRESH_MS);
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

      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
        <Stat label="Sessions" value={data.totals.sessions} />
        <Stat label="Turns" value={data.totals.turns} />
        <Stat label="Tool calls" value={data.totals.tool_calls} />
        <Stat label="Errors" value={data.totals.errors} />
        <Stat
          label="Avg duration (s)"
          value={Math.round(data.totals.avg_duration_seconds)}
        />
      </div>

      <div className="grid md:grid-cols-2 gap-6">
        <Card title="Sessions by copilot">
          {data.by_copilot.map((c) => (
            <Bar key={c.copilot} label={c.copilot} value={c.sessions} max={maxCopilot} />
          ))}
        </Card>

        <Card title="Tool usage (top 25)">
          <div className="max-h-72 overflow-y-auto">
            {data.tool_usage.map((t) => (
              <Bar key={t.tool} label={t.tool} value={t.count} max={maxTool} />
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
              />
            ))
          )}
        </Card>

        <Card title="Sessions by day (last 30)">
          <div className="max-h-72 overflow-y-auto">
            {data.by_day.map((d) => (
              <Bar
                key={d.day}
                label={d.day}
                value={d.sessions}
                max={Math.max(1, ...data.by_day.map((x) => x.sessions))}
              />
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}
