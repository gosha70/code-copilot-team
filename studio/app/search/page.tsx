"use client";

import { useState } from "react";
import Link from "next/link";
import { api, TraceHit } from "@/lib/api";
import { Card } from "@/components/ui";

// SEARCH HAS A PAGE. Ranked full-text search over archived trace text
// shipped with no way to reach it: no nav entry, and no component
// called the endpoint. It was usable only from a terminal, which for a
// feature whose entire point is "find what was said" means it did not
// really ship.
//
// The results are the producer's order — best match first — and are NOT
// re-sorted here.

export default function SearchPage() {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<TraceHit[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [ran, setRan] = useState("");

  async function run(e?: React.FormEvent) {
    e?.preventDefault();
    if (!q.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const r = await api.searchTraces(q.trim());
      setHits(r.results);
      setRan(q.trim());
    } catch (err) {
      setError(String(err));
      setHits(null);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">Search</h1>
      <p className="text-sm text-slate-500">
        Full-text search across archived turn text. Words match in any order and
        anywhere in a turn, stemmed, best match first.
      </p>

      <form onSubmit={run} className="flex gap-2">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="e.g. cluster threshold"
          className="border border-slate-300 bg-white text-slate-900 rounded px-3 py-1.5 text-sm w-full"
        />
        <button
          type="submit"
          disabled={busy || !q.trim()}
          className="bg-blue-600 text-white text-sm px-4 py-1.5 rounded hover:bg-blue-700 disabled:opacity-50 shrink-0"
        >
          {busy ? "Searching…" : "Search"}
        </button>
      </form>

      {error && (
        <p className="text-sm bg-rose-50 border border-rose-200 text-rose-800 rounded p-2">
          {error}
          <span className="block text-xs mt-1">
            Search reads archived trace text. If nothing is archived yet, run{" "}
            <code>session-analytics archive</code> for an opted-in project.
          </span>
        </p>
      )}

      {hits && (
        <p className="text-sm text-slate-600">
          {hits.length === 0
            ? // An empty result is a real answer, and the reason matters:
              // no archive at all looks identical to no match otherwise.
              `No archived turns match “${ran}”. Only projects with trace_archive enabled are searchable.`
            : `${hits.length} match${hits.length === 1 ? "" : "es"} for “${ran}”, best first.`}
        </p>
      )}

      <div className="space-y-2">
        {hits?.map((h, i) => (
          <Card key={`${h.session_ref}-${h.sequence_num}-${i}`}>
            <div className="flex items-baseline justify-between gap-3 flex-wrap">
              <Link
                href={`/sessions/${h.session_ref}`}
                className="text-sm font-medium text-blue-700 hover:underline"
              >
                {h.project_path || "(no project)"}
              </Link>
              <span className="text-xs text-slate-400 font-mono">
                {h.copilot} · turn {h.sequence_num} · {h.redaction_mode}
              </span>
            </div>
            <p className="text-sm text-slate-700 mt-1 whitespace-pre-wrap break-words">
              {h.snippet}
            </p>
          </Card>
        ))}
      </div>
    </div>
  );
}
