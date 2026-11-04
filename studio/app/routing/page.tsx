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
import { CalibrationPanel } from "@/components/CalibrationPanel";

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
      <td className="py-2 text-xs text-slate-500">not consumable</td>
    </tr>
  );
}

// ROUTING HAS TWO HALVES, and the page says which is which:
//
//   1. the runtime registry the supervisor actually routes under
//      (~/.code-copilot-team/routing.toml) — shown first, or a clear
//      "not configured" state with the one command that opts in;
//   2. the evidence that says whether a route is earned — rendered only
//      when evidence roots exist, with its calibration gates.
//
// Both are read-only. `cct routing validate` remains the authoritative
// check of the registry grammar; this page shows the declarations.

export default function RoutingPage() {
  const { data, error, loading } = useApi(() => api.routingEvidence());
  const registry = useApi(() => api.routingRegistry());
  const settings = useApi(() => api.settings());
  if (loading) return <Loading />;
  if (error || !data) return <ErrorNote error={error || "no data"} />;

  const routingSettings = settings.data?.routing_evidence as
    | RoutingEvidenceSettings
    | undefined;
  const evidenceConfigured = routingSettings?.configured === true;
  const reg = registry.data;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Routing</h1>
        <p className="text-sm text-slate-600">
          Keep unattended builds running when a provider fails — without
          silently switching to a weaker model.
        </p>
        <p className="text-xs text-slate-500 mt-1">
          Read-only; nothing on this page changes what runs.{" "}
          <Link
            href="/learn/docs--llm-routing"
            className="text-blue-700 hover:underline"
          >
            How routing works →
          </Link>
        </p>
      </div>

      <Card title="Routing configuration">
        {registry.loading ? (
          <p className="text-sm text-slate-500">Reading the registry…</p>
        ) : registry.error || !reg ? (
          <p className="text-sm text-rose-700">
            The routing registry could not be read: {registry.error}
          </p>
        ) : !reg.configured ? (
          <div className="space-y-2 text-sm text-slate-600">
            <p>
              <span className="font-medium text-slate-800">
                Routing is not configured.
              </span>{" "}
              The registry is read from{" "}
              <code className="bg-slate-100 px-1 rounded">{reg.path}</code>;
              with no registry, routing is off and existing behavior is
              unchanged.
            </p>
            <p className="text-xs text-slate-500">
              From the repository root:
            </p>
            <pre className="text-xs bg-slate-50 border border-slate-200 rounded p-3 overflow-x-auto">
              {`mkdir -p ~/.code-copilot-team
cp shared/templates/routing/routing.toml.example ~/.code-copilot-team/routing.toml
./scripts/cct routing validate`}
            </pre>
            <p className="text-xs text-slate-500">
              Activate it per run with{" "}
              <code>scripts/cooldown-supervisor.sh &lt;feature-id&gt; --routing</code>.
            </p>
          </div>
        ) : !reg.valid ? (
          <div className="space-y-2 text-sm text-rose-700">
            <p>
              The registry exists but cannot be used: it is not valid TOML, or
              the routing validator rejects it. Routing is off until it is
              fixed — the profiles are not shown because they would never run.
            </p>
            <pre className="text-xs bg-rose-50 border border-rose-200 rounded p-3 overflow-x-auto whitespace-pre-wrap">
              {reg.error}
            </pre>
            <p className="text-xs text-slate-500">
              Run <code>./scripts/cct routing validate</code> for the
              authoritative check.
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            <p className="text-xs text-slate-500">
              {reg.path} · schema v{reg.schema_version ?? "—"} ·{" "}
              {reg.profiles.length} profile
              {reg.profiles.length === 1 ? "" : "s"}
              {reg.policy?.preferred_profile
                ? ` · preferred ${reg.policy.preferred_profile}`
                : ""}
            </p>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-slate-500 border-b border-slate-200">
                    <th className="py-2 pr-4 font-medium">Profile</th>
                    <th className="py-2 pr-4 font-medium">Backend</th>
                    <th className="py-2 pr-4 font-medium">Provider / model</th>
                    <th className="py-2 pr-4 font-medium">Tier</th>
                    <th className="py-2 pr-4 font-medium text-right">Priority</th>
                    <th className="py-2 font-medium">Roles</th>
                  </tr>
                </thead>
                <tbody>
                  {reg.profiles.map((p) => (
                    <tr key={p.id} className="border-b border-slate-100">
                      <td className="py-2 pr-4 font-mono text-xs">{p.id}</td>
                      <td className="py-2 pr-4">{p.backend ?? "—"}</td>
                      <td className="py-2 pr-4 text-slate-600">
                        {[p.provider, p.model].filter(Boolean).join(" / ") || "—"}
                      </td>
                      <td className="py-2 pr-4">{p.capability_tier ?? "—"}</td>
                      <td className="py-2 pr-4 text-right tabular-nums">
                        {p.priority ?? "—"}
                      </td>
                      <td className="py-2 text-slate-600">
                        {p.roles.join(", ") || "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {Object.keys(reg.route_classes).length > 0 && (
              <p className="text-xs text-slate-500">
                Route classes:{" "}
                {Object.entries(reg.route_classes)
                  .map(
                    ([name, tiers]) =>
                      `${name} (${tiers.join(" → ") || "—"})`,
                  )
                  .join(" · ")}
              </p>
            )}
            <p className="text-xs text-slate-500">
              Declarations only — run <code>./scripts/cct routing validate</code>{" "}
              for the authoritative check. Credential references and endpoints
              are not shown.
            </p>
          </div>
        )}
      </Card>

      {evidenceConfigured && (
        <>
          {data.sets.length === 0 ? (
            <Card title="No routing evidence sets yet">
              <p className="text-sm text-slate-600">
                Evidence roots are configured, but no set has been published
                under them. Sets come from the benchmark harness&rsquo;s routing
                evaluation, which publishes one atomically after running the
                scenario and the fixed-profile matrix sweep.
              </p>
              <p className="text-xs text-slate-500 mt-2">
                Point the analytics API at a publication root with{" "}
                <code>CCT_SA_ROUTING_EVIDENCE_ROOTS</code> (path-separator
                separated) or the <code>routing_evidence_roots</code> config
                key.{" "}
                <Link
                  href="/learn/docs--llm-routing"
                  className="text-blue-700 hover:underline"
                >
                  How routing evidence is produced →
                </Link>
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
              <p className="text-xs text-slate-500 mt-3">
                Invalid sets are rendered with their sanitized failure code —
                never silently skipped — and produce no recommendations.
              </p>
            </Card>
          )}
          <CalibrationPanel />
        </>
      )}
    </div>
  );
}
