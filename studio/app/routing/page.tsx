"use client";

import Link from "next/link";
import {
  api,
  RoutingEvidenceEntry,
  RoutingEvidenceSettings,
  RoutingEvidenceSetSummary,
  RoutingInvalidEvidenceSet,
} from "@/lib/api";
import { Badge, Card, ErrorNote, Loading, useApi } from "@/components/ui";

function digest8(value: string): string {
  // Digests render truncated for scanability; the full value stays in the
  // payload (title attribute) — the Studio never rewrites identity fields.
  return value.replace(/^sha256:/, "").slice(0, 8);
}

function ValidSetRow({ set }: { set: RoutingEvidenceSetSummary }) {
  return (
    <tr className="border-b border-slate-100">
      <td className="py-2 pr-4">
        <Link
          href={`/routing/${set.set_id}`}
          className="text-blue-600 hover:underline font-mono text-xs"
          title={set.set_id}
        >
          {digest8(set.set_id)}…
        </Link>
      </td>
      <td className="py-2 pr-4">
        <Badge kind="valid">valid</Badge>
      </td>
      <td className="py-2 pr-4">{set.tasks.join(", ")}</td>
      <td className="py-2 pr-4">{set.arms.join(", ")}</td>
      <td className="py-2 pr-4 text-right tabular-nums">{set.record_count}</td>
      <td className="py-2 pr-4">{set.pareto_status ?? "—"}</td>
      <td
        className="py-2 font-mono text-xs text-slate-500"
        title={`registry ${set.registry_digest} · preset ${set.preset_digest} · tasks ${set.task_set_revision} · toolchain ${set.toolchain_digest ?? "—"}`}
      >
        {digest8(set.registry_digest)} / {digest8(set.preset_digest)}
      </td>
    </tr>
  );
}

function InvalidSetRow({ set }: { set: RoutingInvalidEvidenceSet }) {
  return (
    <tr className="border-b border-slate-100 bg-rose-50/50">
      <td className="py-2 pr-4 font-mono text-xs text-slate-500">
        {set.label}
      </td>
      <td className="py-2 pr-4">
        <Badge kind="invalid_evidence">invalid_evidence</Badge>
      </td>
      <td className="py-2 pr-4" colSpan={4}>
        <span className="font-mono text-xs">{set.code}</span>
        <span className="text-slate-500 text-xs"> [{set.artifact}]</span>
        <span className="text-slate-600 text-xs"> — {set.detail}</span>
      </td>
      <td className="py-2 text-xs text-slate-400">not consumable</td>
    </tr>
  );
}

export default function RoutingPage() {
  const { data, error, loading } = useApi(() => api.routingEvidence());
  const settings = useApi(() => api.settings());
  if (loading) return <Loading />;
  if (error || !data) return <ErrorNote error={error || "no data"} />;

  const routingSettings = settings.data?.routing_evidence as
    RoutingEvidenceSettings | undefined;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Routing</h1>
        <p className="text-sm text-slate-500">
          Shadow-mode analysis of E1 routing evidence — read-only. Nothing on
          this page feeds back into live selection.
        </p>
      </div>

      {routingSettings && (
        <p className="text-xs text-slate-400">
          Evidence roots:{" "}
          {routingSettings.configured
            ? `${routingSettings.root_count} configured`
            : "none configured"}
        </p>
      )}

      {data.sets.length === 0 ? (
        <Card title="No routing evidence sets yet">
          <p className="text-sm text-slate-600">
            No published evidence sets were found under the configured evidence
            roots. Evidence sets are produced by the E1 routing-eval scenario —{" "}
            <code>publish_evidence_set</code> in
            <code> benchmark_runner.routing_eval</code> runs the hybrid scenario
            plus the fixed-profile matrix sweep and publishes the set
            atomically.
          </p>
          <p className="text-sm text-slate-500 mt-3">
            Point the analytics API at one or more publication roots with the
            <code> CCT_SA_ROUTING_EVIDENCE_ROOTS</code> environment variable
            (path-separator separated) or the
            <code> routing_evidence_roots</code> config key, then reload this
            page.
          </p>
        </Card>
      ) : (
        <Card title="Evidence sets">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-slate-500 border-b border-slate-200">
                  <th className="py-2 pr-4 font-medium">Set</th>
                  <th className="py-2 pr-4 font-medium">State</th>
                  <th className="py-2 pr-4 font-medium">Tasks</th>
                  <th className="py-2 pr-4 font-medium">Arms</th>
                  <th className="py-2 pr-4 font-medium text-right">Records</th>
                  <th className="py-2 pr-4 font-medium">Pareto</th>
                  <th className="py-2 font-medium">Fingerprint</th>
                </tr>
              </thead>
              <tbody>
                {data.sets.map((entry: RoutingEvidenceEntry, i: number) =>
                  entry.state === "valid" ? (
                    <ValidSetRow key={entry.set_id} set={entry} />
                  ) : (
                    <InvalidSetRow key={`invalid-${i}`} set={entry} />
                  ),
                )}
              </tbody>
            </table>
          </div>
          <p className="text-xs text-slate-400 mt-3">
            Invalid sets are rendered with their sanitized failure code — never
            silently skipped — and produce no recommendations.
          </p>
        </Card>
      )}
    </div>
  );
}
