"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { api } from "@/lib/api";
import { ErrorNote, Loading, useApi } from "@/components/ui";
import MarkdownDoc from "@/components/MarkdownDoc";
import { tableOfContents } from "@/lib/docLinks";

export default function LearnDocPage() {
  const params = useParams();
  const slug = decodeURIComponent(String(params.slug));
  const index = useApi(() => api.docs(), []);
  const doc = useApi(() => api.doc(slug), [slug]);

  if (index.loading || doc.loading) return <Loading />;
  if (index.error || !index.data) return <ErrorNote error={index.error || "no data"} />;
  if (doc.error || !doc.data) {
    return (
      <div className="space-y-3">
        <Link href="/learn" className="text-xs text-blue-700 hover:underline">← Learn</Link>
        <ErrorNote error={doc.error || "This page is not in the Learn catalogue."} />
      </div>
    );
  }
  const section = index.data.sections.find((s) => s.id === doc.data!.section);
  const siblings = section?.entries ?? [];
  // A document that opens with its own H1 does not need the page's;
  // showing both read as a stutter.
  const ownsTitle = tableOfContents(doc.data.body)[0]?.level === 1;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <Link href="/learn" className="text-xs text-blue-700 hover:underline">← Learn</Link>
        {section && (
          <Link
            href={`/learn#${section.id}`}
            className="text-xs text-slate-500 hover:text-blue-700"
          >
            {section.title}
          </Link>
        )}
        <span className="text-xs text-slate-400 font-mono truncate" title={doc.data.path}>
          {doc.data.path}
        </span>
        <a
          href={`${index.data.repo_url}/blob/${index.data.repo_branch}/${doc.data.path}`}
          target="_blank"
          rel="noreferrer"
          className="text-xs text-slate-500 hover:text-blue-700 ml-auto"
        >
          View on GitHub ↗
        </a>
      </div>
      {!ownsTitle && <h1 className="text-2xl font-bold">{doc.data.title}</h1>}
      {doc.data.description && (
        <p className="text-sm text-slate-600">{doc.data.description}</p>
      )}
      <div className="bg-white rounded border border-slate-200 p-6">
        <MarkdownDoc doc={doc.data} index={index.data} />
      </div>
      {siblings.length > 1 && (
        <div className="text-xs text-slate-500">
          Also in {section?.title}:{" "}
          {siblings
            .filter((e) => e.slug !== doc.data!.slug)
            .slice(0, 8)
            .map((e, i) => (
              <span key={e.slug}>
                {i > 0 && " · "}
                <Link href={`/learn/${encodeURIComponent(e.slug)}`} className="text-blue-700 hover:underline">
                  {e.title}
                </Link>
              </span>
            ))}
        </div>
      )}
    </div>
  );
}
