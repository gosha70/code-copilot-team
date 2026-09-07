"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Components } from "react-markdown";
import { BASE, DocPayload, DocsIndex } from "@/lib/api";
import {
  headingSlug,
  resolveDocImage,
  resolveDocLink,
  tableOfContents,
} from "@/lib/docLinks";

// One repository document, rendered in-app (#309). GFM tables and code
// fences are what the corpus uses (29 and 30 of 41 files); raw HTML is
// not rendered — the only HTML in the corpus is the README's logo header,
// and escaping it costs nothing a reader misses. Links to other served
// docs stay in-app; anything outside the allowlist goes to GitHub, and
// the reader can see which is which.

const IMAGE_DIR = "docs/images";

export default function MarkdownDoc({
  doc,
  index,
}: {
  doc: DocPayload;
  index: DocsIndex;
}) {
  const slugByPath = useMemo(() => {
    const m: Record<string, string> = {};
    for (const s of index.sections)
      for (const e of s.entries) m[e.path] = e.slug;
    return m;
  }, [index]);
  const toc = useMemo(() => tableOfContents(doc.body), [doc.body]);
  // Heading ids come from the TOC, keyed by the heading's source line
  // (react-markdown hands each component its hast node with a position).
  // A per-render counter drifted under React's double render; a source
  // line does not.
  const idByLine = useMemo(() => {
    const m = new Map<number, string>();
    for (const h of toc) m.set(h.line, h.id);
    return m;
  }, [toc]);

  const heading =
    (Tag: "h1" | "h2" | "h3") =>
    ({ children, node }: { children?: React.ReactNode; node?: unknown }) => {
      const text = plainText(children);
      const line = (node as { position?: { start?: { line?: number } } } | undefined)
        ?.position?.start?.line;
      const id = (line != null && idByLine.get(line)) || headingSlug(text);
      const cls =
        Tag === "h1"
          ? "text-2xl font-bold mt-6 mb-3"
          : Tag === "h2"
            ? "text-xl font-semibold mt-6 mb-2 border-b border-slate-200 pb-1"
            : "text-lg font-semibold mt-4 mb-2";
      return (
        <Tag id={id} className={`${cls} scroll-mt-20`}>
          {children}
        </Tag>
      );
    };

  const components: Components = {
    h1: heading("h1"),
    h2: heading("h2"),
    h3: heading("h3"),
    a: ({ href, children }) => {
      const r = resolveDocLink(
        href || "",
        doc.path,
        slugByPath,
        index.repo_url,
        index.repo_branch,
      );
      if (r.kind === "learn") {
        return (
          <Link href={r.href} className="text-blue-700 hover:underline">
            {children}
          </Link>
        );
      }
      if (r.kind === "anchor") {
        return (
          <a href={r.href} className="text-blue-700 hover:underline">
            {children}
          </a>
        );
      }
      return (
        <a
          href={r.href}
          target="_blank"
          rel="noreferrer"
          className="text-blue-700 hover:underline"
          title="Opens on GitHub"
        >
          {children}
          <span className="text-slate-400 text-xs"> ↗</span>
        </a>
      );
    },
    img: ({ src, alt }) => (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={resolveDocImage(
          String(src || ""),
          doc.path,
          BASE,
          index.image_route,
          IMAGE_DIR,
          index.repo_url,
          index.repo_branch,
        )}
        alt={alt || ""}
        className="max-w-full rounded border border-slate-200 my-3"
      />
    ),
    pre: ({ children }) => <CodeBlock>{children}</CodeBlock>,
    code: ({ className, children }) => {
      const block = /language-/.test(className || "");
      return block ? (
        <code className={className}>{children}</code>
      ) : (
        <code className="bg-slate-100 rounded px-1 py-0.5 text-[0.9em]">
          {children}
        </code>
      );
    },
    table: ({ children }) => (
      <div className="overflow-x-auto my-3">
        <table className="w-full text-sm border-collapse">{children}</table>
      </div>
    ),
    th: ({ children }) => (
      <th className="text-left border-b border-slate-300 px-2 py-1 bg-slate-50 font-semibold">
        {children}
      </th>
    ),
    td: ({ children }) => (
      <td className="border-b border-slate-100 px-2 py-1 align-top">
        {children}
      </td>
    ),
    blockquote: ({ children }) => (
      <blockquote className="border-l-4 border-slate-300 pl-3 text-slate-600 my-3">
        {children}
      </blockquote>
    ),
    ul: ({ children }) => (
      <ul className="list-disc pl-6 my-2 space-y-1">{children}</ul>
    ),
    ol: ({ children }) => (
      <ol className="list-decimal pl-6 my-2 space-y-1">{children}</ol>
    ),
    p: ({ children }) => <p className="my-2 leading-relaxed">{children}</p>,
    hr: () => <hr className="my-6 border-slate-200" />,
  };

  return (
    <div className="grid lg:grid-cols-4 gap-6">
      <article className="lg:col-span-3 min-w-0 text-slate-800 text-sm">
        {doc.generated && (
          <p
            className="inline-block text-xs px-2 py-0.5 rounded bg-slate-200 text-slate-700 mb-2"
            title="Regenerated by a script from its sources of truth; edit those, not this file."
          >
            generated file — read-only
          </p>
        )}
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
          {doc.body}
        </ReactMarkdown>
      </article>
      {toc.length > 1 && (
        <nav className="hidden lg:block text-xs sticky top-4 self-start max-h-[80vh] overflow-y-auto">
          <p className="font-semibold text-slate-500 uppercase tracking-wide mb-2">
            On this page
          </p>
          <ul className="space-y-1">
            {toc.map((h, i) => (
              <li key={i} style={{ paddingLeft: `${(h.level - 1) * 0.75}rem` }}>
                <a
                  href={`#${h.id}`}
                  className="text-slate-600 hover:text-blue-700"
                >
                  {h.text}
                </a>
              </li>
            ))}
          </ul>
        </nav>
      )}
    </div>
  );
}

function CodeBlock({ children }: { children?: React.ReactNode }) {
  const [copied, setCopied] = useState(false);
  const text = plainText(children);
  return (
    <div className="relative group my-3">
      <pre className="bg-slate-900 text-slate-100 rounded p-3 text-xs overflow-x-auto">
        {children}
      </pre>
      <button
        onClick={() => {
          navigator.clipboard?.writeText(text).then(() => {
            setCopied(true);
            setTimeout(() => setCopied(false), 1500);
          });
        }}
        className="absolute top-2 right-2 text-xs border border-slate-600 bg-slate-800 text-slate-200 rounded px-2 py-0.5 opacity-0 group-hover:opacity-100"
      >
        {copied ? "Copied" : "Copy"}
      </button>
    </div>
  );
}

/** The text a React subtree would render — for heading ids and Copy. */
export function plainText(node: React.ReactNode): string {
  if (node == null || typeof node === "boolean") return "";
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(plainText).join("");
  if (typeof node === "object" && "props" in node) {
    return plainText(
      (node as { props: { children?: React.ReactNode } }).props.children,
    );
  }
  return "";
}
