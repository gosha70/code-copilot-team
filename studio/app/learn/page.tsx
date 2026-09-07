"use client";

import Link from "next/link";
import { api, DocEntry } from "@/lib/api";
import { Badge, Card, ErrorNote, Loading, useApi } from "@/components/ui";

// The Learn landing (#309): four questions a person arrives with, a live
// strip saying whether the tool underneath is working, and the whole
// catalogue by section. Everything here is the repository's own
// markdown, served from a closed allowlist.

export default function LearnPage() {
  const docs = useApi(() => api.docs(), []);
  const status = useApi(() => api.pipelineStatus(), []);
  const judge = useApi(() => api.judgeModels(), []);

  if (docs.loading) return <Loading />;
  if (docs.error || !docs.data) return <ErrorNote error={docs.error || "no data"} />;
  const idx = docs.data;
  const bySlug: Record<string, DocEntry> = {};
  for (const s of idx.sections) for (const e of s.entries) bySlug[e.slug] = e;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Learn</h1>
        <p className="text-sm text-slate-500">
          The project&apos;s own guides, skills, agents and wiki, read in place.
        </p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {idx.intents.map((it) => {
          const target = bySlug[it.slug];
          return (
            <Link
              key={it.id}
              href={`/learn/${encodeURIComponent(it.slug)}`}
              className="block bg-white rounded border border-slate-200 p-4 hover:border-blue-400 hover:shadow-sm"
            >
              <p className="font-semibold text-slate-800">{it.title}</p>
              <p className="text-xs text-slate-500 mt-1">{it.blurb}</p>
              {target && (
                <p className="text-xs text-blue-700 mt-2">{target.title} →</p>
              )}
            </Link>
          );
        })}
      </div>

      <Card title="Right now">
        <div className="flex flex-wrap gap-x-6 gap-y-1 text-sm">
          <span>
            Store:{" "}
            {status.data && status.data.store_reachable ? (
              <span className="font-medium">
                {status.data.counts.sessions.toLocaleString()} sessions
                {status.data.counts.excluded_noise > 0 &&
                  ` (${status.data.counts.excluded_noise.toLocaleString()} excluded as noise)`}
              </span>
            ) : status.data || status.error ? (
              // Zero counts from a store that did not answer are not
              // "0 sessions"; the server says so with store_reachable.
              <span className="text-rose-700">not reachable</span>
            ) : (
              "…"
            )}
          </span>
          <span>
            Judge:{" "}
            {judge.data ? (
              judge.data.reachable ? (
                <span className="font-medium">
                  Ollama with {judge.data.models.length} model
                  {judge.data.models.length === 1 ? "" : "s"}
                </span>
              ) : (
                <span className="text-amber-700">Ollama not reachable at {judge.data.url}</span>
              )
            ) : judge.error ? (
              <span className="text-rose-700">unknown</span>
            ) : (
              "…"
            )}
          </span>
          <span>
            Labelled turns:{" "}
            <span className="font-medium">
              {status.data && status.data.store_reachable
                ? status.data.counts.labels.toLocaleString()
                : status.data || status.error
                  ? "—"
                  : "…"}
            </span>
          </span>
          <Link href="/analysis" className="text-blue-700 hover:underline">
            Analysis pipeline →
          </Link>
        </div>
      </Card>

      <div className="grid md:grid-cols-2 gap-6">
        {idx.sections.map((s) => (
          <Card key={s.id} title={s.title}>
            <div id={s.id} className="scroll-mt-20" />
            {s.entries.length === 0 ? (
              <p className="text-sm text-slate-400">Nothing here yet.</p>
            ) : (
              <ul className="space-y-1.5 text-sm">
                {s.entries.map((e) => (
                  <li key={e.slug} className="flex items-baseline gap-2">
                    <Link
                      href={`/learn/${encodeURIComponent(e.slug)}`}
                      className="text-blue-700 hover:underline"
                    >
                      {e.title}
                    </Link>
                    {e.page_type && e.kind === "wiki" && (
                      <Badge kind="question">{e.page_type}</Badge>
                    )}
                    {e.generated && <Badge kind="NEUTRAL">generated</Badge>}
                    {e.description && (
                      <span className="text-xs text-slate-500 truncate" title={e.description}>
                        {e.description}
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </Card>
        ))}
      </div>
    </div>
  );
}
