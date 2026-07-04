"use client";

import dynamic from "next/dynamic";

// Cytoscape touches the DOM — load the explorer client-only.
const GraphExplorer = dynamic(() => import("@/components/GraphExplorer"), {
  ssr: false,
  loading: () => <div className="text-slate-400 text-sm py-8">Loading explorer…</div>,
});

export default function GraphPage() {
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">Knowledge Graph</h1>
      <GraphExplorer />
    </div>
  );
}
