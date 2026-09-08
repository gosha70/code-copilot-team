"use client";

import { useState, type ReactNode } from "react";
import Link from "next/link";
import { SessionSort, SessionTagsInfo, api } from "@/lib/api";
import SessionTagIcons, { HandTag, TAG_LABEL, TagHeaderIcon } from "@/components/SessionTags";
import { Card, ErrorNote, Loading, formatCost, useApi } from "@/components/ui";

const REFRESH_MS = 15000;

export default function SessionsPage() {
  const [query, setQuery] = useState("");
  const [copilot, setCopilot] = useState("");
  // #307: probe runs and too-short sessions are hidden by default. The
  // count on the toggle is the server's, from the same filters, so it
  // equals what appears when the toggle is on.
  const [showNoise, setShowNoise] = useState(false);
  // Sorting is the SERVER's: the list is the top N after ordering, so a
  // sort by errors shows the sessions with the most errors, not the
  // newest N reordered.
  const [sort, setSort] = useState<SessionSort>("started_at");
  const [order, setOrder] = useState<"asc" | "desc">("desc");
  const { data, error, loading } = useApi(
    () => api.sessions(query, copilot, showNoise, sort, order),
    [query, copilot, showNoise, sort, order],
    REFRESH_MS
  );

  // A tag toggled in the grid shows at once; the server's answer wins
  // (it is what the toggle returns), and the next refresh confirms it.
  const [tagOverrides, setTagOverrides] = useState<Record<number, SessionTagsInfo>>({});
  async function toggleTag(id: number, tag: HandTag, on: boolean, current: SessionTagsInfo) {
    setTagOverrides((o) => ({ ...o, [id]: { ...current, [tag]: on } }));
    try {
      const r = await api.setSessionTag(id, tag, on);
      setTagOverrides((o) => ({ ...o, [id]: r.tags }));
    } catch {
      setTagOverrides((o) => ({ ...o, [id]: current }));
    }
  }

  function sortBy(column: SessionSort) {
    if (column === sort) setOrder(order === "desc" ? "asc" : "desc");
    else {
      setSort(column);
      // Numbers and dates open with the largest first; names A→Z.
      setOrder(["copilot", "project_path", "model"].includes(column) ? "asc" : "desc");
    }
  }

  function Th({
    column,
    children,
    className = "",
    label,
  }: {
    column: SessionSort;
    children: ReactNode;
    className?: string;
    /** For an icon header: the words the tooltip and screen reader use. */
    label?: string;
  }) {
    const active = column === sort;
    return (
      <th className={className}>
        <button
          type="button"
          onClick={() => sortBy(column)}
          className={
            "inline-flex items-center gap-1 hover:text-slate-800 " +
            (active ? "text-slate-800 font-semibold" : "")
          }
          title={`Sort by ${label ?? String(children)}`}
          aria-label={label ? `Sort by ${label}` : undefined}
          aria-sort={active ? (order === "asc" ? "ascending" : "descending") : undefined}
        >
          {children}
          <span className="text-[10px] w-3">{active ? (order === "asc" ? "▲" : "▼") : ""}</span>
        </button>
      </th>
    );
  }

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
                <Th column="favorite" className="py-2 pr-0.5" label={TAG_LABEL.favorite}><TagHeaderIcon tag="favorite" /></Th>
                <Th column="todo" className="pr-0.5" label={TAG_LABEL.todo}><TagHeaderIcon tag="todo" /></Th>
                <Th column="analyzed" className="pr-3" label={TAG_LABEL.analyzed}><TagHeaderIcon tag="analyzed" /></Th>
                <Th column="copilot" className="pr-3">Copilot</Th>
                <Th column="project_path" className="pr-3">Project</Th>
                <Th column="model" className="pr-3">Model</Th>
                <Th column="turn_count" className="text-right pr-3">Turns</Th>
                <Th column="tool_call_count" className="text-right pr-3">Tools</Th>
                <Th column="error_count" className="text-right pr-3">Errors</Th>
                <Th column="cost_usd" className="text-right pr-3">Cost</Th>
                <Th column="started_at" className="pl-3">Started</Th>
              </tr>
            </thead>
            <tbody>
              {data.sessions.map((s) => (
                <tr key={s.id} className="border-b border-slate-100 hover:bg-slate-50">
                  <td className="py-1 whitespace-nowrap" colSpan={3}>
                    <SessionTagIcons
                      tags={tagOverrides[s.id] ?? s.tags}
                      onToggle={(tag, on) => toggleTag(s.id, tag, on, tagOverrides[s.id] ?? s.tags)}
                    />
                  </td>
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
                  <td colSpan={11} className="py-6 text-center text-slate-400">
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
