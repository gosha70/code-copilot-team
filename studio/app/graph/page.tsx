"use client";

import dynamic from "next/dynamic";
import { useEffect, useState } from "react";

import { api } from "@/lib/api";

// Cytoscape touches the DOM — load the explorer client-only.
const GraphExplorer = dynamic(() => import("@/components/GraphExplorer"), {
  ssr: false,
  loading: () => <div className="text-slate-400 text-sm py-8">Loading explorer…</div>,
});

export default function GraphPage() {
  // Node counts are one line, not a card: the page is judged by what a
  // person can explore, not by how much schema it shows.
  const [counts, setCounts] = useState<Record<string, number> | null>(null);
  useEffect(() => {
    let live = true;
    api
      .graphCounts()
      .then((o) => live && o.ok && setCounts(o.report.node_counts))
      .catch(() => {});
    return () => {
      live = false;
    };
  }, []);
  return (
    <div className="space-y-4">
      <div className="flex items-baseline gap-3 flex-wrap">
        <h1 className="text-2xl font-bold">Graph</h1>
        {counts && (
          <span className="text-xs text-slate-500">
            {Object.entries(counts)
              .filter(([, n]) => n > 0)
              .map(([k, n]) => `${n.toLocaleString()} ${k}`)
              .join(" · ")}
          </span>
        )}
      </div>
      <GraphExplorer />
    </div>
  );
}
