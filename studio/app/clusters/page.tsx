"use client";

// Clusters page (#293 T2). Fetching only — every rendering decision
// lives in ClustersView, which is pure so the D8 states script can
// render all eight states without a server.

import { useEffect, useState } from "react";

import ClustersView from "@/components/ClustersView";
import { Loading } from "@/components/ui";
import { api } from "@/lib/api";
import { classify, type ClustersState } from "@/lib/clusterStates";

export default function ClustersPage() {
  const [state, setState] = useState<ClustersState | null>(null);

  useEffect(() => {
    let live = true;
    api
      .clusters()
      .then((outcome) => live && setState(classify(outcome)))
      // A rejected promise is not a prerequisite — it is an honest
      // failure, and FR-C forbids collapsing the two.
      .catch((e) => live && setState({ kind: "failed", message: String(e) }));
    return () => {
      live = false;
    };
  }, []);

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">Clusters</h1>
      {state === null ? <Loading /> : <ClustersView state={state} />}
    </div>
  );
}
