"use client";

import { DiscoveredSessions, LoadSelection as Selection } from "@/lib/api";

// WHICH SESSIONS TO LOAD — the owner's requirement from the Kiro
// Analyzer reference: choose before reading. "Load sessions" used to
// read every transcript under every source root, with no way to see
// how much that was or to narrow it; on a machine with years of copilot
// history that is gigabytes parsed in one go.
//
// This block lists what the load WOULD read (nothing is parsed to list
// it), lets the user narrow by date and count, or tick exact sessions,
// and shows the size of what the button is about to read. The button
// says what it does: "Load 3 selected" or "Load 41 new", never "Run".

/** Above this much to read, the size line turns into a warning. */
export const LARGE_LOAD_BYTES = 200 * 1024 * 1024;

export function formatBytes(n: number): string {
  if (n >= 1024 * 1024 * 1024)
    return `${(n / (1024 * 1024 * 1024)).toFixed(1)} GB`;
  if (n >= 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MB`;
  if (n >= 1024) return `${Math.round(n / 1024)} KB`;
  return `${n} B`;
}

/** What the Load button will send, and how to label it. Pure, so the
 *  states check can assert it: an explicit pick wins over the filters;
 *  no pick means "every new session under the filters". */
export function loadPlan(
  listing: DiscoveredSessions | null,
  picked: ReadonlySet<string>,
  since: string,
  limit: string,
): { body: Selection; label: string; bytes: number; count: number } {
  const lim = Number(limit) > 0 ? Number(limit) : undefined;
  if (picked.size > 0) {
    const rows = (listing?.sessions ?? []).filter((s) =>
      picked.has(s.session_id),
    );
    const bytes = rows.reduce((n, s) => n + s.bytes, 0);
    return {
      body: { session_ids: [...picked] },
      label: `Load ${picked.size} selected`,
      bytes,
      count: picked.size,
    };
  }
  const count = listing?.new ?? 0;
  return {
    body: { since: since || undefined, limit: lim },
    label: count === 1 ? "Load 1 new session" : `Load ${count} new sessions`,
    bytes: listing?.new_bytes ?? 0,
    count,
  };
}

export default function LoadSelectionPanel({
  listing,
  error,
  since,
  limit,
  picked,
  running,
  onSince,
  onLimit,
  onTogglePick,
  onPickNew,
  onClearPicks,
  onLoad,
}: {
  listing: DiscoveredSessions | null;
  error: string | null;
  since: string;
  limit: string;
  picked: ReadonlySet<string>;
  running: boolean;
  onSince: (v: string) => void;
  onLimit: (v: string) => void;
  onTogglePick: (id: string) => void;
  onPickNew: () => void;
  onClearPicks: () => void;
  onLoad: (body: Selection) => void;
}) {
  const plan = loadPlan(listing, picked, since, limit);
  const large = plan.bytes >= LARGE_LOAD_BYTES;

  return (
    <div className="mt-3 border border-slate-200 rounded">
      <div className="flex items-center gap-3 flex-wrap px-3 py-2 bg-slate-50 border-b border-slate-200">
        <span className="text-sm font-medium text-slate-800">
          Which sessions
        </span>
        <label className="text-xs text-slate-500">modified since</label>
        <input
          type="date"
          value={since}
          onChange={(e) => onSince(e.target.value)}
          className="border border-slate-300 bg-white text-slate-900 rounded px-2 py-1 text-sm"
        />
        <label className="text-xs text-slate-500">newest</label>
        <input
          type="number"
          min={1}
          value={limit}
          placeholder="all"
          onChange={(e) => onLimit(e.target.value)}
          className="border border-slate-300 bg-white text-slate-900 rounded px-2 py-1 text-sm w-20"
        />
        {listing && (
          <span className="text-xs text-slate-500">
            {listing.total.toLocaleString()} found ·{" "}
            {listing.new.toLocaleString()} new
            {" · "}
            {formatBytes(listing.total_bytes)} on disk
          </span>
        )}
        <span className="ml-auto flex items-center gap-2">
          <button
            type="button"
            onClick={onPickNew}
            disabled={!listing || listing.new === 0}
            className="text-xs text-blue-700 hover:underline disabled:text-slate-400 disabled:no-underline"
          >
            tick all new
          </button>
          <button
            type="button"
            onClick={onClearPicks}
            disabled={picked.size === 0}
            className="text-xs text-blue-700 hover:underline disabled:text-slate-400 disabled:no-underline"
          >
            clear
          </button>
        </span>
      </div>

      {error && <p className="text-xs text-rose-700 px-3 py-2">{error}</p>}
      {!listing && !error && (
        <p className="text-xs text-slate-400 px-3 py-2">Listing sessions…</p>
      )}
      {listing && listing.sessions.length === 0 && (
        <p className="text-xs text-slate-500 px-3 py-2">
          No sessions under the source roots match. Widen the date, or check the
          sources under Settings.
        </p>
      )}
      {listing && listing.sessions.length > 0 && (
        <div className="max-h-72 overflow-auto">
          <table className="w-full text-xs">
            <thead className="text-slate-500 text-left sticky top-0 bg-white">
              <tr>
                <th className="px-3 py-1 w-6"></th>
                <th className="px-2 py-1">copilot</th>
                <th className="px-2 py-1">source</th>
                <th className="px-2 py-1">modified</th>
                <th className="px-2 py-1 text-right">size</th>
                <th className="px-2 py-1">state</th>
              </tr>
            </thead>
            <tbody>
              {listing.sessions.map((s) => (
                <tr
                  key={`${s.copilot}:${s.session_id}`}
                  className="border-t border-slate-100"
                >
                  <td className="px-3 py-1">
                    <input
                      type="checkbox"
                      checked={picked.has(s.session_id)}
                      onChange={() => onTogglePick(s.session_id)}
                      className="accent-blue-600"
                      aria-label={`select ${s.session_id}`}
                    />
                  </td>
                  <td className="px-2 py-1 text-slate-700">{s.copilot}</td>
                  <td
                    className="px-2 py-1 text-slate-700 font-mono truncate max-w-[22rem]"
                    title={s.session_id}
                  >
                    {s.source}
                  </td>
                  <td className="px-2 py-1 text-slate-600 whitespace-nowrap">
                    {new Date(s.modified).toLocaleString()}
                  </td>
                  <td className="px-2 py-1 text-slate-600 text-right whitespace-nowrap">
                    {formatBytes(s.bytes)}
                  </td>
                  <td className="px-2 py-1">
                    {s.loaded ? (
                      <span className="px-1.5 py-0.5 rounded bg-slate-100 text-slate-600">
                        loaded
                      </span>
                    ) : (
                      <span className="px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-800">
                        new
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {listing.total > listing.sessions.length && (
            <p className="text-xs text-slate-500 px-3 py-2 border-t border-slate-100">
              Showing the newest {listing.sessions.length.toLocaleString()} of{" "}
              {listing.total.toLocaleString()} — narrow by date to see the rest.
            </p>
          )}
        </div>
      )}

      <div className="flex items-center gap-3 flex-wrap px-3 py-2 border-t border-slate-200">
        <button
          type="button"
          onClick={() => onLoad(plan.body)}
          disabled={running || plan.count === 0}
          className="bg-slate-800 text-white text-sm px-4 py-1.5 rounded hover:bg-slate-700 disabled:opacity-50"
        >
          {running ? "Loading…" : plan.label}
        </button>
        <span
          className={"text-xs " + (large ? "text-amber-800" : "text-slate-500")}
        >
          {plan.count > 0
            ? `${formatBytes(plan.bytes)} to read` +
              (large
                ? " — a large load; narrow it if this machine is short on memory"
                : "")
            : "nothing to load — every session under these filters is already loaded"}
        </span>
      </div>
    </div>
  );
}
