"use client";

// Search (#371 A2): ranked, deterministic matching over archived turns, no
// model involved; every hit is one click from its turn on the session page.
// Ask is the other thing: it interprets the whole store through a model.
// This page supersedes part of the #307 nav cut on purpose, and says which
// is which.
import { Suspense, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
import { SEARCH_VS_ASK, hitHref, searchState, stateLine } from "@/lib/searchView";
import { Card, ErrorNote, Loading, useApi } from "@/components/ui";

export default function SearchPage() {
  return (
    <Suspense fallback={<Loading />}>
      <Search />
    </Suspense>
  );
}

function Search() {
  const params = useSearchParams();
  const router = useRouter();
  const q = params.get("q") ?? "";
  const [draft, setDraft] = useState(q);
  const { data, error, loading } = useApi(
    () => (q.trim() ? api.search(q) : Promise.resolve(null)),
    [q],
  );
  const state = searchState(q, data);
  return (
    <div className="space-y-4">
      <div className="flex items-baseline gap-2">
        <h1 className="text-2xl font-bold">Search</h1>
        <span className="text-slate-400 text-xs">{SEARCH_VS_ASK}</span>
      </div>
      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          router.replace(draft.trim() ? `/search?q=${encodeURIComponent(draft.trim())}` : "/search");
        }}
      >
        <input
          className="border border-slate-300 bg-white text-slate-900 rounded px-3 py-1.5 text-sm flex-1"
          placeholder="Words from a turn: an error message, a file name, a phrase…"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          aria-label="search words"
        />
        <button className="border border-slate-300 rounded px-3 py-1.5 text-sm" type="submit">
          Search
        </button>
      </form>
      {loading && <Loading />}
      {error && <ErrorNote error={error} />}
      {state.kind !== "idle" && <p className="text-sm text-slate-600">{stateLine(state)}</p>}
      {state.kind === "idle" && (
        <p className="text-sm text-slate-500">
          Only archived turns are searched; a project opts in with <code>trace_archive</code>. For
          a question about the store as a whole, use <Link className="text-blue-700 hover:underline" href="/ask">Ask</Link>.
        </p>
      )}
      {data && data.results.length > 0 && (
        <Card>
          <ol className="divide-y divide-slate-100">
            {data.results.map((h, i) => (
              <li key={`${h.session_ref}-${h.sequence_num}-${i}`} className="py-2">
                <Link className="text-blue-700 hover:underline text-sm" href={hitHref(h)}>
                  session #{h.session_ref}, turn #{h.sequence_num}
                </Link>
                <span className="ml-2 text-xs text-slate-400">
                  {h.project_path ?? ""}
                  {h.redaction_mode && h.redaction_mode !== "none" ? ` · redacted: ${h.redaction_mode}` : ""}
                </span>
                <p className="text-sm text-slate-700 whitespace-pre-wrap break-words mt-0.5">{h.snippet}</p>
              </li>
            ))}
          </ol>
        </Card>
      )}
    </div>
  );
}
