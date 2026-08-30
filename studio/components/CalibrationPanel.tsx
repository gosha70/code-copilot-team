"use client";

import { useState } from "react";
import {
  api,
  RoutingEvaluationSummary,
  RoutingGate,
  RoutingGateEvidenceRef,
  RoutingGateId,
} from "@/lib/api";
import { Badge, Card, useApi } from "@/components/ui";

// routing-calibration (#266) T4: the Calibration panel. Read-only, like
// every other routing surface — the panel renders whether the corpus has
// earned a promotion decision, and NOTHING here makes one.

const GATE_LABELS: Record<RoutingGateId, string> = {
  telemetry_complete: "Telemetry complete",
  labeled_volume: "Labeled volume",
  heldout_evaluated: "Held-out evaluated",
  false_downgrade: "False downgrade",
  floors_authoritative: "Floors authoritative",
};

// Decision-bearing figures render VERBATIM, the same rule the evidence
// detail page holds: String() is JS's shortest round-trip form, so a
// measured rate of 1e-8 shows as "1e-8" and never as a rounded "0.0000"
// that reads like a clean pass. Null is "—", never a fabricated 0.
function fmt(value: number | string | null): string {
  if (value === null) return "—";
  if (typeof value === "string") return value;
  return String(value);
}

function refLabel(ref: RoutingGateEvidenceRef): string {
  switch (ref.kind) {
    case "evidence_set":
      return `set ${ref.evidence_set_id.slice(0, 8)}…`;
    case "task":
      return `task ${ref.task_id} @ ${ref.evidence_set_id.slice(0, 8)}…`;
    case "evaluation_report":
      return "held-out evaluation report";
    case "evaluation_result":
      return `result ${ref.task_id} @ ${ref.evidence_set_id.slice(0, 8)}…`;
  }
}

/** Fetch the coordinate a locator NAMES — through the same read-only
 * surfaces the evidence pages use, so a gate verdict is inspectable
 * rather than merely asserted. Each branch resolves to the exact
 * coordinate, not to the whole artifact. */
async function openRef(ref: RoutingGateEvidenceRef): Promise<unknown> {
  if (ref.kind === "evidence_set") {
    const payload = await api.routingArtifact(ref.evidence_set_id, "report");
    return payload.content;
  }
  if (ref.kind === "task") {
    const payload = await api.routingArtifact(ref.evidence_set_id, "report");
    const doc = payload.content as {
      arms?: Record<string, { tasks?: Record<string, unknown> }>;
    };
    const cell = doc.arms?.cct_router?.tasks?.[ref.task_id];
    if (cell === undefined)
      throw new Error("the task does not resolve in the set it names");
    return cell;
  }
  const payload = await api.routingEvaluation();
  if (payload.state !== "report" || !payload.report)
    throw new Error(payload.reason ?? "no evaluation report");
  if (ref.kind === "evaluation_report") {
    const { results, ...aggregates } = payload.report;
    return { ...aggregates, results: results.length };
  }
  const hit = payload.report.results.find(
    (r) =>
      r.evidence_set_id === ref.evidence_set_id && r.task_id === ref.task_id,
  );
  if (hit === undefined)
    throw new Error("the result is not in the current evaluation report");
  return hit;
}

function EvidenceRefButton({ gateRef }: { gateRef: RoutingGateEvidenceRef }) {
  const [opened, setOpened] = useState<unknown | null>(null);
  const [error, setError] = useState<string | null>(null);

  const follow = () => {
    if (opened !== null || error !== null) {
      setOpened(null);
      setError(null);
      return;
    }
    openRef(gateRef)
      .then(setOpened)
      .catch((e) => setError(String(e)));
  };

  return (
    <li>
      <button
        type="button"
        onClick={follow}
        className="text-left text-blue-600 hover:underline"
        title="open this coordinate"
      >
        {refLabel(gateRef)}
      </button>
      {error !== null && <div className="text-rose-600">{error}</div>}
      {opened !== null && (
        <pre className="mt-1 mb-2 bg-white border border-slate-200 rounded p-2 overflow-x-auto text-[11px] leading-4 whitespace-pre-wrap">
          {JSON.stringify(opened, null, 1)}
        </pre>
      )}
    </li>
  );
}

function GateRow({ gate }: { gate: RoutingGate }) {
  return (
    <tr className="border-b border-slate-100 align-top">
      <td className="py-2 pr-4 whitespace-nowrap">
        {GATE_LABELS[gate.id] ?? gate.id}
      </td>
      <td className="py-2 pr-4">
        <Badge kind={gate.status}>{gate.status}</Badge>
      </td>
      <td className="py-2 pr-4 text-right tabular-nums whitespace-nowrap">
        {fmt(gate.measured)}
      </td>
      <td className="py-2 pr-4 text-right tabular-nums whitespace-nowrap">
        {fmt(gate.threshold)}
      </td>
      <td className="py-2 text-slate-600">
        {gate.reason ?? "—"}
        {gate.evidence_refs.length > 0 && (
          <details className="mt-1 text-xs">
            <summary className="cursor-pointer text-slate-500">
              Evidence ({gate.evidence_refs.length})
            </summary>
            <ul className="mt-1 space-y-0.5 font-mono">
              {gate.evidence_refs.map((ref, i) => (
                <EvidenceRefButton key={i} gateRef={ref} />
              ))}
            </ul>
          </details>
        )}
      </td>
    </tr>
  );
}

function Aggregate({
  label,
  value,
  emphasis = false,
  stale = false,
}: {
  label: string;
  value: number | null;
  emphasis?: boolean;
  stale?: boolean;
}) {
  // A stale figure is VOID, not merely old: it is muted and struck so a
  // scan can never mistake a superseded 0.0 rate for a current one.
  const box = stale
    ? "rounded border border-slate-200 bg-slate-50 px-3 py-2"
    : emphasis
      ? "rounded border border-blue-200 bg-blue-50 px-3 py-2"
      : "rounded border border-slate-200 px-3 py-2";
  return (
    <div className={box}>
      <div
        className={`text-lg font-semibold tabular-nums ${
          stale ? "text-slate-400 line-through" : ""
        }`}
      >
        {fmt(value)}
      </div>
      <div className="text-xs text-slate-500">{label}</div>
    </div>
  );
}

function EvaluationAggregates({
  evaluation,
}: {
  evaluation: RoutingEvaluationSummary;
}) {
  if (!evaluation.present) {
    return (
      <p className="text-sm text-slate-500 mt-4">
        No held-out evaluation report is bound to this corpus and policy, so
        three of the five gates cannot conclude. Produce one by running{" "}
        <code>session-analytics calibrate</code>, then reload.
      </p>
    );
  }
  const stale = evaluation.stale;
  return (
    <div className="mt-4">
      {stale && (
        <p className="text-xs font-medium text-amber-800 mb-2">
          Figures below come from the STALE report and describe a corpus and
          policy that no longer exist — they are void, not merely old.
        </p>
      )}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2">
        <Aggregate
          label="agreement (no gate reads this)"
          value={evaluation.agreement}
          emphasis
          stale={stale}
        />
        <Aggregate
          label="compared"
          value={evaluation.compared}
          stale={stale}
        />
        <Aggregate
          label="judged (denominator)"
          value={evaluation.evaluated}
          stale={stale}
        />
        <Aggregate
          label="refused"
          value={evaluation.refused}
          stale={stale}
        />
        <Aggregate
          label="tier unresolved"
          value={evaluation.unresolved_tier}
          stale={stale}
        />
        <Aggregate
          label="unevaluable"
          value={evaluation.unevaluable}
          stale={stale}
        />
        <Aggregate
          label="false downgrades"
          value={evaluation.false_downgrades}
          stale={stale}
        />
        <Aggregate
          label="false-downgrade rate"
          value={evaluation.false_downgrade_rate}
          stale={stale}
        />
        <Aggregate
          label="floor violations"
          value={evaluation.floor_violations}
          stale={stale}
        />
      </div>
      <p className="text-xs text-slate-500 mt-3">
        The five gates are a <strong>safety</strong> floor and cannot, by
        construction, tell a useful recommender from an inert one: a recommender
        that keeps every profile makes real recommendations, none of which can
        be a downgrade, so it earns a truthful 0.0 rate and full coverage while
        proposing nothing. Agreement is the usefulness reading — a promotion
        decision needs both numbers, so it sits here beside the verdicts even
        though no gate consumes it.
      </p>
    </div>
  );
}

export function CalibrationPanel() {
  const { data, error, loading } = useApi(() => api.routingCalibration());

  if (loading) {
    return <Card title="Calibration gates">Loading…</Card>;
  }
  if (error || !data) {
    return (
      <Card title="Calibration gates">
        <p className="text-sm text-slate-600">
          The calibration surface is unavailable: {error || "no data"}
        </p>
      </Card>
    );
  }

  if (data.state === "insufficient_data" || !data.report) {
    return (
      <Card title="Calibration gates">
        <Badge kind="insufficient_data">insufficient_data</Badge>
        <p className="text-sm text-slate-600 mt-3">
          {data.reason ??
            "No calibration verdict can be computed for this configuration."}
        </p>
        <p className="text-xs text-slate-400 mt-2">
          Gate thresholds and classifier parameters are operator policy and are
          never completed from code — set them in the
          <code> routing_calibration</code> configuration block.
        </p>
      </Card>
    );
  }

  const report = data.report;
  const verdictKind = report.calibrated ? "calibrated" : "not_calibrated";

  return (
    <Card title="Calibration gates">
      <div className="flex flex-wrap items-center gap-3">
        <Badge kind={verdictKind}>
          {report.calibrated ? "calibrated" : "not calibrated"}
        </Badge>
        <span className="text-xs text-slate-500">
          {report.corpus.sets} set(s) · {report.corpus.labeled_tasks} labeled
          task(s)
          {report.corpus.invalid_sets > 0 &&
            ` · ${report.corpus.invalid_sets} invalid`}
        </span>
        <span
          className="font-mono text-xs text-slate-400"
          title={`corpus ${report.corpus_id} · policy ${report.policy_id}`}
        >
          corpus {report.corpus_id.slice(0, 8)}… / policy{" "}
          {report.policy_id.slice(0, 8)}…
        </span>
      </div>

      {data.evaluation.stale && (
        <div className="mt-3 rounded border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
          <strong>Stale evaluation report.</strong> Its bindings no longer match
          the live corpus and configuration (
          {data.evaluation.stale_reasons.join(", ")}), so it satisfies no gate.
          Re-run the held-out evaluation against the current corpus and policy.
        </div>
      )}

      <div className="overflow-x-auto mt-3">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-slate-500 border-b border-slate-200">
              <th className="py-2 pr-4 font-medium">Gate</th>
              <th className="py-2 pr-4 font-medium">Status</th>
              <th className="py-2 pr-4 font-medium text-right">Measured</th>
              <th className="py-2 pr-4 font-medium text-right">Threshold</th>
              <th className="py-2 font-medium">Evidence</th>
            </tr>
          </thead>
          <tbody>
            {report.gates.map((gate) => (
              <GateRow key={gate.id} gate={gate} />
            ))}
          </tbody>
        </table>
      </div>

      <EvaluationAggregates evaluation={data.evaluation} />

      {data.policy && (
        <p className="text-xs text-slate-400 mt-3">
          Policy: {data.policy.feature_vocabulary} · k={data.policy.k} (min{" "}
          {data.policy.k_min}) · {data.policy.distance_metric} ·{" "}
          {data.policy.normalization} · floor {data.policy.tier_floor} · max
          rate {data.policy.max_false_downgrade_rate} · source{" "}
          {data.policy.policy_source_digest
            ? `${data.policy.policy_source_digest.slice(0, 8)}…`
            : "none"}
        </p>
      )}
      <p className="text-xs text-slate-400 mt-1">
        Shadow-only: a calibrated verdict is evidence for a promotion decision
        an operator makes, never a routing change this page can apply.
      </p>
    </Card>
  );
}
