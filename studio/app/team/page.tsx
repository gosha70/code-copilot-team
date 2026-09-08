"use client";

import Link from "next/link";
import { api, TeamStatus, TeamWindow } from "@/lib/api";
import {
  ALERT_STYLE,
  LIVENESS_DOT,
  LIVENESS_LABEL,
  activeLegend,
  alertHref,
  alertSummary,
  alertsEmptyNote,
  anyPartial,
  costCell,
  currentWork,
  developerName,
  sessionsCell,
  storeNote,
} from "@/lib/teamView";
import { Card, ErrorNote, Loading, useApi } from "@/components/ui";

// TEAM (#174, Slices B2 + C + E). The shared store's status: who is
// active right now (a heartbeat within the window — last-seen, never
// a liveness verdict), what they are on, and what sessions cost per
// developer, per project and in total over three windows. Read-only;
// refreshes on the watch interval so heartbeats appear as they land.

const REFRESH_MS = 15_000;
const WINDOWS: { key: TeamWindow; label: string }[] = [
  { key: "today", label: "Today" },
  { key: "7d", label: "7 days" },
  { key: "30d", label: "30 days" },
];

export default function TeamPage() {
  const { data, error, loading } = useApi(
    () => api.teamStatus(),
    [],
    REFRESH_MS,
  );
  if (loading && !data) return <Loading />;
  if (error && !data) return <ErrorNote error={error} />;
  if (!data) return <ErrorNote error="the API did not answer" />;
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Team</h1>
        <p className="text-sm text-slate-500 mt-1">{storeNote(data)}</p>
        <p className="text-xs text-slate-500 mt-1">
          {data.totals.active_now} of {data.totals.developers} developer
          {data.totals.developers === 1 ? "" : "s"} active ·{" "}
          {activeLegend(data.active_window_seconds)}
          {error && (
            <span className="text-rose-700">
              {" "}
              · last refresh failed: {error}
            </span>
          )}
        </p>
      </div>

      {data.alerts && (
        <Card title={`Alerts${alertSummary(data.alerts) ? ` — ${alertSummary(data.alerts)}` : ""}`}>
          {data.alerts.alerts.length === 0 ? (
            <p className="text-sm text-slate-600">{alertsEmptyNote(data.alerts)}</p>
          ) : (
            <ul className="space-y-2">
              {data.alerts.alerts.map((a, i) => (
                <li key={i} className={`border rounded px-3 py-2 text-sm ${ALERT_STYLE[a.level]}`}>
                  <span className="text-xs uppercase tracking-wide font-semibold mr-2">{a.level}</span>
                  {a.message}
                  {alertHref(a) && (
                    <>
                      {" "}
                      <Link href={alertHref(a) as string} className="text-blue-700 hover:underline">
                        open the session →
                      </Link>
                    </>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Card>
      )}

      <Card title="Developers">
        <Table data={data} />
      </Card>

      <Card title="Projects">
        {data.projects.length === 0 ? (
          <p className="text-sm text-slate-500">
            No sessions in the last 30 days.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-slate-500 border-b border-slate-200">
                  <th className="py-2 pr-4 font-medium">Project</th>
                  <th className="py-2 pr-4 font-medium">
                    Developers (30 days)
                  </th>
                  {WINDOWS.map((w) => (
                    <th
                      key={w.key}
                      className="py-2 pr-4 font-medium text-right"
                    >
                      {w.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.projects.map((p) => (
                  <tr
                    key={p.project_path}
                    className="border-b border-slate-100"
                  >
                    <td
                      className="py-2 pr-4 font-mono text-xs"
                      title={p.project_path}
                    >
                      {p.project_path.replace(/\/+$/, "").split("/").pop() ||
                        p.project_path}
                    </td>
                    <td className="py-2 pr-4 text-xs text-slate-600">
                      {p.developers.join(", ") || "—"}
                    </td>
                    {WINDOWS.map((w) => (
                      <td
                        key={w.key}
                        className="py-2 pr-4 text-right tabular-nums"
                      >
                        <div>{costCell(p.windows[w.key])}</div>
                        <div className="text-xs text-slate-500">
                          {sessionsCell(p.windows[w.key])}
                        </div>
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <p className="text-xs text-slate-500">
        Cost sums priced turns only
        {anyPartial(data)
          ? "; * marks a window where some priceable turns had no price"
          : ""}
        .
        {data.totals.unstamped_turns > 0 && (
          <>
            {" "}
            {data.totals.unstamped_turns.toLocaleString()} turns without a
            timestamp are in no window.
          </>
        )}{" "}
        Sessions per developer:{" "}
        <Link href="/sessions" className="text-blue-700 hover:underline">
          Sessions
        </Link>
        .
      </p>
    </div>
  );
}

function Table({ data }: { data: TeamStatus }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-slate-500 border-b border-slate-200">
            <th className="py-2 pr-4 font-medium">Developer</th>
            <th className="py-2 pr-4 font-medium">State</th>
            <th className="py-2 pr-4 font-medium">Current work</th>
            {WINDOWS.map((w) => (
              <th key={w.key} className="py-2 pr-4 font-medium text-right">
                {w.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.developers.map((d) => (
            <tr key={d.developer_id} className="border-b border-slate-100">
              <td className="py-2 pr-4 font-mono text-xs">
                {developerName(d)}
              </td>
              <td className="py-2 pr-4">
                <span className="inline-flex items-center gap-2 text-xs text-slate-700">
                  <span
                    className={`inline-block w-2.5 h-2.5 rounded-full ${LIVENESS_DOT[d.liveness]}`}
                  />
                  {LIVENESS_LABEL[d.liveness]}
                </span>
              </td>
              <td className="py-2 pr-4 text-xs text-slate-700">
                {currentWork(d)}
                {d.current && (
                  <span className="text-slate-400">
                    {" "}
                    · {d.current.checkpoint_count.toLocaleString()} checkpoints
                    · seen {d.current.at}
                  </span>
                )}
              </td>
              {WINDOWS.map((w) => (
                <td key={w.key} className="py-2 pr-4 text-right tabular-nums">
                  <div>{costCell(d.windows[w.key])}</div>
                  <div className="text-xs text-slate-500">
                    {sessionsCell(d.windows[w.key])}
                  </div>
                </td>
              ))}
            </tr>
          ))}
          <tr className="font-medium">
            <td className="py-2 pr-4 text-xs">total</td>
            <td className="py-2 pr-4 text-xs text-slate-500">
              {data.totals.active_now} active
            </td>
            <td className="py-2 pr-4" />
            {WINDOWS.map((w) => (
              <td key={w.key} className="py-2 pr-4 text-right tabular-nums">
                <div>{costCell(data.totals.windows[w.key])}</div>
                <div className="text-xs text-slate-500">
                  {sessionsCell(data.totals.windows[w.key])}
                </div>
              </td>
            ))}
          </tr>
        </tbody>
      </table>
    </div>
  );
}
