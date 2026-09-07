"use client";

import dynamic from "next/dynamic";
import { useEffect, useState } from "react";

import ClustersView from "@/components/ClustersView";
import { Loading, describeError } from "@/components/ui";
import { api } from "@/lib/api";
import { classify, type ClustersState } from "@/lib/clusterStates";

// Cytoscape touches the DOM — load the explorer client-only.
const GraphExplorer = dynamic(() => import("@/components/GraphExplorer"), {
  ssr: false,
  loading: () => <div className="text-slate-400 text-sm py-8">Loading explorer…</div>,
});

export default function GraphPage() {
  // #307: Clusters is a view over the same graph store, so it lives
  // below the explorer; /clusters stays as a deep link to the same view.
  const [clusters, setClusters] = useState<ClustersState | null>(null);
  useEffect(() => {
    let live = true;
    api
      .clusters()
      .then((outcome) => live && setClusters(classify(outcome)))
      .catch((e) => live && setClusters({ kind: "failed", message: describeError(e) }));
    return () => {
      live = false;
    };
  }, []);

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Graph</h1>
      <GraphExplorer />
      <section className="space-y-3">
        <h2 className="text-lg font-semibold">Clusters</h2>
        {clusters === null ? <Loading /> : <ClustersView state={clusters} />}
      </section>
    </div>
  );
}
