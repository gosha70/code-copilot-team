"use client";

import { useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { Card, ErrorNote, Loading, formatCost, useApi } from "@/components/ui";

const REFRESH_MS = 15000;

export default function SessionsPage() {
  const [query, setQuery] = useState("");
  const [copilot, setCopilot] = useState("");
  // #307: probe runs and too-short sessions are hidden by default. The
  // count on the toggle is the server's, from the same filters, so it
  // equals what appears when the toggle is on.
  const [showNoise, setShowNoise] = useState(false);
  const { data, error, loading } = useApi(
    () => api.sessions(query, copilot, showNoise),
    [query, copilot, showNoise],
    REFRESH_MS
  );

  return (
    <div className="space-y-4">
      <div className="flex items-baseline gap-2">
        <h1 className="text-2xl font-bold">Sessions</h1>
        <span className="text-slate-400 text-xs">
          Auto-refreshing every {REFRESH_MS / 1000}s
        </span>
      </div>
      <div className="flex gap-3">
        <input
          className="border border-slate-300 bg-white text-slate-900 rounded px-3 py-1.5 text-sm flex-1"
          placeholder="Search project path / model…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <select
          className="border border-slate-300 bg-white text-slate-900 rounded px-3 py-1.5 text-sm"
          value={copilot}
          onChange={(e) => setCopilot(e.target.value)}
        >
          <option value="">All copilots</option>
          <option value="claude-code">Claude Code</option>
          <option value="aider">Aider</option>
        </select>
      </div>
      {data && data.excluded_noise > 0 && (
        <label className="flex items-center gap-2 text-sm text-slate-600">
          <input
            type="checkbox"
            checked={showNoise}
            onChange={(e) => setShowNoise(e.target.checked)}
          />
          Show excluded ({data.excluded_noise.toLocaleString()})
          <span
            className="text-xs text-slate-400"
            title="Sessions under the turn or duration minimum, or in a probe/temp directory (sessions.noise in config)"
          >
            probe runs, temp dirs, and sessions too short to mean anything
          </span>
        </label>
      )}

      {loading && <Loading />}
      {error && <ErrorNote error={error} />}
      {data && (
        <Card>
          <table className="w-full text-sm">
            <thead className="text-left text-slate-500 border-b border-slate-200">
              <tr>
                <th className="py-2 pr-3">Copilot</th>
                <th className="pr-3">Project</th>
                <th className="pr-3">Model</th>
                <th className="text-right pr-3">Turns</th>
                <th className="text-right pr-3">Tools</th>
                <th className="text-right pr-3">Errors</th>
                <th className="text-right pr-3">Cost</th>
                <th className="pl-3">Started</th>
              </tr>
            </thead>
            <tbody>
              {data.sessions.map((s) => (
                <tr key={s.id} className="border-b border-slate-100 hover:bg-slate-50">
                  <td className="py-2">
                    <Link href={`/sessions/${s.id}`} className="text-blue-600 hover:underline">
                      {s.copilot}
                    </Link>
                  </td>
                  <td className="truncate max-w-xs pr-3" title={s.project_path || undefined}>
                    {s.project_path || "—"}
                  </td>
                  <td className="pr-3">{s.model || "—"}</td>
                  <td className="text-right tabular-nums pr-3">{s.turn_count}</td>
                  <td className="text-right tabular-nums pr-3">{s.tool_call_count}</td>
                  <td className="text-right tabular-nums pr-3">{s.error_count}</td>
                  <td className="text-right tabular-nums pr-3">{formatCost(s.cost_usd)}</td>
                  <td className="text-slate-500 pl-3">{(s.started_at || "").slice(0, 19)}</td>
                </tr>
              ))}
              {data.sessions.length === 0 && (
                <tr>
                  <td colSpan={8} className="py-6 text-center text-slate-400">
                    {data.excluded_noise > 0
                      ? `No sessions worth showing — ${data.excluded_noise.toLocaleString()} excluded as noise (toggle above).`
                      : "No sessions. Run the Analysis page's Load sessions step."}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}
