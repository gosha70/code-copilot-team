"use client";

import { useParams } from "next/navigation";
import {
  api,
  RoutingArm,
  RoutingDeltaSource,
  RoutingEvidenceLocator,
  RoutingFigureSource,
  RoutingRecommendation,
  RoutingReport,
} from "@/lib/api";
import { Badge, Card, ErrorNote, Loading, Stat, useApi } from "@/components/ui";

// E1 permits a null toolchain identity (a cell the scenario could not
// fingerprint) — a null digest renders as an em dash, never crashes.
function digest8(value: string | null): string {
  if (value === null) return "—";
  return value.replace(/^sha256:/, "").slice(0, 8);
}

// Decision-bearing figures render VERBATIM: String() is JS's shortest
// round-trip representation, so a 1e-8 delta (above E2's 1e-9 comparison
// tolerance — it can be WHY a switch was recommended) shows as "1e-8",
// never as a rounded "0.0000". Null means "insufficient", never zero.
function fig(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return String(value);
}

function ArmsTable({ report }: { report: RoutingReport }) {
  const arms = Object.entries(report.arms) as [string, RoutingArm][];
  // The COMPLETE metric vector: the quality-function mask first (its
  // declared order), then every remaining served metric key — the
  // sequence-dependent measures included — sorted for a stable order.
  const columns = [...report.components_included];
  const extra = new Set<string>();
  for (const [, arm] of arms)
    for (const key of Object.keys(arm.metrics))
      if (!columns.includes(key)) extra.add(key);
  columns.push(...Array.from(extra).sort());
  return (
    <Card
      title={`Arms — quality (${report.quality_fn}) · vector · cost (${report.cost_basis})`}
    >
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-slate-500 border-b border-slate-200">
              <th className="py-2 pr-4 font-medium">Arm</th>
              <th className="py-2 pr-4 font-medium text-right">Q</th>
              {columns.map((c) => (
                <th key={c} className="py-2 pr-4 font-medium text-right">
                  {c}
                </th>
              ))}
              <th className="py-2 pr-4 font-medium text-right">Cost</th>
              <th className="py-2 font-medium">Insufficiency</th>
            </tr>
          </thead>
          <tbody>
            {arms.map(([name, arm]) => (
              <tr key={name} className="border-b border-slate-100">
                <td className="py-2 pr-4 font-mono text-xs">{name}</td>
                <td className="py-2 pr-4 text-right tabular-nums">
                  {fig(arm.quality)}
                </td>
                {columns.map((c) => (
                  <td key={c} className="py-2 pr-4 text-right tabular-nums">
                    {typeof arm.metrics[c] === "number"
                      ? fig(arm.metrics[c] as number)
                      : (arm.metrics[c] ?? "—")}
                  </td>
                ))}
                <td
                  className="py-2 pr-4 text-right tabular-nums"
                  title={arm.cost.reason ?? undefined}
                >
                  {arm.cost.value === null
                    ? `— (${arm.cost.status})`
                    : fig(arm.cost.value)}
                </td>
                <td className="py-2 text-xs text-slate-500">
                  {Object.keys(arm.insufficient).length === 0
                    ? "—"
                    : Object.entries(arm.insufficient).map(([k, v]) => (
                        <div key={k}>
                          <span className="font-mono">{k}</span>: {v}
                        </div>
                      ))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function PerTaskTable({ report }: { report: RoutingReport }) {
  const arms = Object.keys(report.arms);
  const tasks = Array.from(
    new Set(arms.flatMap((a) => Object.keys(report.arms[a].tasks))),
  ).sort();
  return (
    <Card title="Per-task figures (quality / cost per arm)">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-slate-500 border-b border-slate-200">
              <th className="py-2 pr-4 font-medium">Task</th>
              {arms.map((a) => (
                <th key={a} className="py-2 pr-4 font-medium text-right">
                  {a}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {tasks.map((task) => (
              <tr key={task} className="border-b border-slate-100">
                <td className="py-2 pr-4 font-mono text-xs">{task}</td>
                {arms.map((a) => {
                  const cell = report.arms[a].tasks[task];
                  return (
                    <td key={a} className="py-2 pr-4 text-right tabular-nums">
                      {cell ? `${fig(cell.quality)} / ${fig(cell.cost)}` : "—"}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function ParetoCard({ report }: { report: RoutingReport }) {
  if (report.pareto.status === "insufficient_evidence") {
    return (
      <Card title="Pareto frontier — withheld">
        <div className="flex items-start gap-2">
          <Badge kind="insufficient_data">insufficient_evidence</Badge>
          <p className="text-sm text-slate-600">{report.pareto.reason}</p>
        </div>
      </Card>
    );
  }
  return (
    <Card title="Pareto frontier">
      <table className="text-sm">
        <thead>
          <tr className="text-left text-slate-500 border-b border-slate-200">
            <th className="py-2 pr-6 font-medium">Arm</th>
            <th className="py-2 pr-6 font-medium text-right">Quality</th>
            <th className="py-2 font-medium text-right">Cost</th>
          </tr>
        </thead>
        <tbody>
          {report.pareto.frontier.map((p) => (
            <tr key={p.arm} className="border-b border-slate-100">
              <td className="py-2 pr-6 font-mono text-xs">{p.arm}</td>
              <td className="py-2 pr-6 text-right tabular-nums">
                {fig(p.quality)}
              </td>
              <td className="py-2 text-right tabular-nums">{fig(p.cost)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}

const OUTCOME_EXPLANATION: Record<RoutingRecommendation["outcome"], string> = {
  switch_profile:
    "An executable candidate arm dominated the router on this task, and its profile appears admissible in the router's own candidate evidence.",
  no_change_recommended:
    "The evidence CONCLUDED: no executable candidate dominated the router's routing on this task.",
  insufficient_data:
    "The evidence CANNOT conclude — a declared insufficiency, missing figure, or unavailable suggested profile blocks any recommendation. This is not a keep-current verdict.",
};

// Every closed locator shape (US3: evidence is addressable), rendered as
// the coordinates it names — never a filesystem path.
function locatorLabel(locator: RoutingEvidenceLocator): string {
  if ("cell" in locator)
    return `cell ${locator.cell.task} · ${locator.cell.profile} · trial ${locator.cell.trial}`;
  if ("arm" in locator) return `${locator.arm} × ${locator.task}`;
  return locator.decision !== undefined
    ? `record ${locator.record} · decision ${locator.decision}`
    : `record ${locator.record}`;
}

function sourceLabel(source: RoutingFigureSource | null): string {
  return source === null ? "—" : `${source.artifact}${source.pointer}`;
}

function deltaSourceLabel(source: RoutingDeltaSource | null): string {
  if (source === null) return "—";
  return `${sourceLabel(source.lhs)} − ${sourceLabel(source.rhs)}`;
}

function EvidenceBlock({ rec }: { rec: RoutingRecommendation }) {
  return (
    <details className="mt-3 text-xs">
      <summary className="cursor-pointer text-slate-500 font-medium">
        Evidence &amp; sources ({rec.evidence_refs.length} refs)
      </summary>
      <div className="mt-2 space-y-2">
        <ul className="space-y-0.5">
          {rec.evidence_refs.map((ref, i) => (
            <li key={i} className="font-mono text-slate-600">
              <span className="text-slate-400">{ref.artifact}</span>{" "}
              {locatorLabel(ref.locator)}
            </li>
          ))}
        </ul>
        <div className="text-slate-500">
          <div className="font-medium mb-0.5">Figure sources (decision 9)</div>
          <div className="font-mono text-slate-600">
            oracle quality: {sourceLabel(rec.oracle_ceiling.sources.quality)}
          </div>
          <div className="font-mono text-slate-600">
            oracle cost: {sourceLabel(rec.oracle_ceiling.sources.cost)}
          </div>
          {Object.entries(rec.divergence).map(([arm, d]) => (
            <div key={arm} className="font-mono text-slate-600">
              {arm} Δquality: {deltaSourceLabel(d.sources.quality_delta)}
              <br />
              {arm} Δcost: {deltaSourceLabel(d.sources.cost_delta)}
            </div>
          ))}
        </div>
        <p className="text-slate-400">
          Locators address artifacts inside this set (no reference is a served
          evidence file, so none links to the evidence-file endpoint).
        </p>
      </div>
    </details>
  );
}

function RecommendationCard({ rec }: { rec: RoutingRecommendation }) {
  const basis = rec.confidence.basis;
  return (
    <Card>
      <div className="flex flex-wrap items-center gap-3">
        <span className="font-mono text-sm font-semibold">{rec.task_id}</span>
        <Badge kind={rec.outcome}>{rec.outcome}</Badge>
        <span className="text-xs text-slate-500">confidence</span>
        <Badge kind={rec.confidence.grade}>{rec.confidence.grade}</Badge>
      </div>
      <p className="text-xs text-slate-500 mt-2">
        {OUTCOME_EXPLANATION[rec.outcome]}
      </p>

      <div className="grid md:grid-cols-2 gap-4 mt-4">
        <div>
          <h4 className="text-xs font-semibold text-slate-500 mb-2">
            Actual routing (per trial)
          </h4>
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left text-slate-500 border-b border-slate-200">
                <th className="py-1 pr-3 font-medium">Trial</th>
                <th className="py-1 pr-3 font-medium">Selected chain</th>
                <th className="py-1 pr-3 font-medium">Delegated</th>
                <th className="py-1 font-medium">Reconciled</th>
              </tr>
            </thead>
            <tbody>
              {rec.actual.per_trial.map((t) => (
                <tr key={t.trial} className="border-b border-slate-100">
                  <td className="py-1 pr-3 tabular-nums">{t.trial}</td>
                  <td className="py-1 pr-3 font-mono">
                    {t.chain.length ? t.chain.join(" → ") : "—"}
                  </td>
                  <td className="py-1 pr-3">{t.delegated ? "yes" : "no"}</td>
                  <td className="py-1">{t.reconciled ? "yes" : "no"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div>
          <h4 className="text-xs font-semibold text-slate-500 mb-2">
            Suggested
          </h4>
          {rec.suggested ? (
            <p className="text-sm">
              switch to{" "}
              <span className="font-mono">{rec.suggested.profile_id}</span>{" "}
              <span className="text-slate-500">(per {rec.suggested.arm})</span>
            </p>
          ) : (
            <p className="text-sm text-slate-500">
              no profile suggested
              {rec.outcome === "insufficient_data" &&
                " — the evidence is insufficient, not approving"}
            </p>
          )}
          <h4 className="text-xs font-semibold text-slate-500 mt-3 mb-1">
            Oracle ceiling (hindsight bound — not a runnable policy)
          </h4>
          <p className="text-sm tabular-nums">
            Q {fig(rec.oracle_ceiling.quality)} · cost{" "}
            {fig(rec.oracle_ceiling.cost)}
          </p>
          <h4 className="text-xs font-semibold text-slate-500 mt-3 mb-1">
            Divergence (router − candidate)
          </h4>
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left text-slate-500 border-b border-slate-200">
                <th className="py-1 pr-3 font-medium">Candidate arm</th>
                <th className="py-1 pr-3 font-medium text-right">Δ quality</th>
                <th className="py-1 font-medium text-right">Δ cost</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(rec.divergence).map(([arm, d]) => (
                <tr key={arm} className="border-b border-slate-100">
                  <td className="py-1 pr-3 font-mono">{arm}</td>
                  <td className="py-1 pr-3 text-right tabular-nums">
                    {fig(d.quality_delta)}
                  </td>
                  <td
                    className="py-1 text-right tabular-nums"
                    title={`cost basis: ${d.cost_basis}`}
                  >
                    {fig(d.cost_delta)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="mt-4 text-xs text-slate-500">
        <span className="tabular-nums">
          {basis.trials} trial{basis.trials === 1 ? "" : "s"}
        </span>
        {" · agreement "}
        <span className="tabular-nums">{fig(basis.agreement)}</span>
        {basis.unevaluated_trials && basis.unevaluated_trials.length > 0 && (
          <span>
            {" · unevaluated trials: "}
            {basis.unevaluated_trials.join(", ")}
          </span>
        )}
      </div>
      <EvidenceBlock rec={rec} />
      {basis.insufficiency_refs.length > 0 && (
        <ul className="mt-2 text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded p-2 space-y-1">
          {basis.insufficiency_refs.map((ref) => (
            <li key={ref} className="font-mono">
              {ref}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

export default function RoutingSetPage() {
  const params = useParams();
  const setId = String(params.setId);
  const detail = useApi(() => api.routingEvidenceSet(setId), [setId]);
  const recs = useApi(() => api.routingRecommendations(setId), [setId]);

  if (detail.loading || recs.loading) return <Loading />;
  if (detail.error || !detail.data)
    return <ErrorNote error={detail.error || "not found"} />;
  if (recs.error || !recs.data)
    return <ErrorNote error={recs.error || "not found"} />;

  const report = detail.data.report;
  const fp = report.fingerprint;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">
          Evidence set{" "}
          <span className="font-mono text-lg text-slate-500" title={setId}>
            {digest8(setId)}…
          </span>
        </h1>
        <p className="text-sm text-slate-500 font-mono">
          registry {digest8(fp.registry_digest)} · preset{" "}
          {digest8(fp.preset_digest)} · tasks {fp.task_set_revision} · toolchain{" "}
          {digest8(fp.toolchain_digest)}
        </p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Stat label="Arms" value={Object.keys(report.arms).length} />
        <Stat
          label="Tasks"
          value={Object.keys(report.arms.cct_router?.tasks ?? {}).length}
        />
        <Stat label="Run records" value={detail.data.record_count} />
        <Stat label="Cost basis" value={report.cost_basis} />
      </div>

      <ArmsTable report={report} />
      <PerTaskTable report={report} />
      <ParetoCard report={report} />

      <div>
        <h2 className="text-lg font-bold">Shadow recommendations</h2>
        <p className="text-sm text-slate-500">
          Derived read-only from this set&apos;s evidence. Never applied, never
          fed back into selection.
        </p>
      </div>
      {recs.data.recommendations.length === 0 ? (
        <Card title="No recommendations">
          <p className="text-sm text-slate-600">
            The router arm carries no per-task figures in this set, so there is
            nothing to compare.
          </p>
        </Card>
      ) : (
        recs.data.recommendations.map((rec) => (
          <RecommendationCard key={rec.task_id} rec={rec} />
        ))
      )}
    </div>
  );
}
