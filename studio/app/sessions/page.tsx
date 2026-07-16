"use client";

import { useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { Card, ErrorNote, Loading, formatCost, useApi } from "@/components/ui";

const REFRESH_MS = 15000;

export default function SessionsPage() {
  const [query, setQuery] = useState("");
  const [copilot, setCopilot] = useState("");
  const { data, error, loading } = useApi(
    () => api.sessions(query, copilot),
    [query, copilot],
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
          className="border border-slate-300 rounded px-3 py-1.5 text-sm flex-1"
          placeholder="Search project path / model…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <select
          className="border border-slate-300 rounded px-3 py-1.5 text-sm"
          value={copilot}
          onChange={(e) => setCopilot(e.target.value)}
        >
          <option value="">All copilots</option>
          <option value="claude-code">Claude Code</option>
          <option value="aider">Aider</option>
        </select>
      </div>

      {loading && <Loading />}
      {error && <ErrorNote error={error} />}
      {data && (
        <Card>
          <table className="w-full text-sm">
            <thead className="text-left text-slate-500 border-b border-slate-200">
              <tr>
                <th className="py-2">Copilot</th>
                <th>Project</th>
                <th>Model</th>
                <th className="text-right">Turns</th>
                <th className="text-right">Tools</th>
                <th className="text-right">Errors</th>
                <th className="text-right">Cost</th>
                <th>Started</th>
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
                  <td className="truncate max-w-xs">{s.project_path || "—"}</td>
                  <td>{s.model || "—"}</td>
                  <td className="text-right tabular-nums">{s.turn_count}</td>
                  <td className="text-right tabular-nums">{s.tool_call_count}</td>
                  <td className="text-right tabular-nums">{s.error_count}</td>
                  <td className="text-right tabular-nums">{formatCost(s.cost_usd)}</td>
                  <td className="text-slate-500">{(s.started_at || "").slice(0, 19)}</td>
                </tr>
              ))}
              {data.sessions.length === 0 && (
                <tr>
                  <td colSpan={8} className="py-6 text-center text-slate-400">
                    No sessions. Run <code>./scripts/session-analytics ingest</code>.
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
