"use client";

// Sessions by harness version (#371 A4b): the answer to "did the new
// skill change anything", as far as the data can honestly give one.
//
// Three constraints are load-bearing, inherited from the aggregate:
//
// 1. NO RANKING. Rows arrive ordered by value, named groups last, and
//    stay that way. A table sorted by "best" reads a harness change as a
//    verdict it has not earned — these are observational groups, not an
//    experiment with controls.
// 2. A judge figure is NEVER shown as 0 when there is no label. It reads
//    "—" with the judged count beside it, because "quality 0.00" and
//    "nobody judged this" are opposite claims.
// 3. The degenerate cases are EXPLAINED, not rendered as an empty-looking
//    table: one version, or a dimension nothing records yet.
import Link from "next/link";
import { Card, formatCost } from "@/components/ui";
import type { HarnessAggregates } from "@/lib/api";
import {
  compareState,
  dimensionLabel,
  judged,
  rowHref,
  rowKey,
  rowLabel,
  rowTitle,
  stateLine,
} from "@/lib/harnessView";

function Th({ children }: { children: React.ReactNode }) {
  return <th className="py-1 pr-4 text-left font-medium text-slate-500">{children}</th>;
}

function Td({ children, title }: { children: React.ReactNode; title?: string }) {
  return (
    <td className="py-2 pr-4 align-top" title={title}>
      {children}
    </td>
  );
}

export default function HarnessPanel({
  data,
  onDimension,
  stale,
}: {
  data: HarnessAggregates;
  onDimension?: (dimension: string) => void;
  /** Set when a refresh failed after data had loaded; the figures below
   *  may no longer be current and must not pass as current. */
  stale?: string | null;
}) {
  const state = compareState(data.rows, data.comparable_values);
  const note = stateLine(state, data.by);
  return (
    <Card title="Sessions by harness version">
      {stale && (
        <p className="text-sm text-amber-700 mb-3">
          Showing the last good figures — the refresh failed ({stale}).
        </p>
      )}
      <div className="flex flex-wrap items-center gap-2 mb-3">
        <label className="text-xs text-slate-500" htmlFor="harness-by">
          Compare by
        </label>
        <select
          id="harness-by"
          value={data.by}
          onChange={(e) => onDimension?.(e.target.value)}
          className="rounded border border-slate-300 bg-white px-2 py-1 text-sm"
        >
          {data.dimensions.map((d) => (
            <option key={d} value={d}>
              {dimensionLabel(d)}
            </option>
          ))}
        </select>
        <span className="text-xs text-slate-400">
          {data.comparable_values} comparable{" "}
          {data.comparable_values === 1 ? "value" : "values"}
        </span>
      </div>
      {note && <p className="text-sm text-slate-600 mb-3">{note}</p>}
      {data.rows.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200">
                <Th>{dimensionLabel(data.by)}</Th>
                <Th>Sessions</Th>
                <Th>Turns (median)</Th>
                <Th>Tools (median)</Th>
                <Th>Errors / 100 turns</Th>
                <Th>Priced cost</Th>
                <Th>Quality</Th>
                <Th>Rework</Th>
                <Th>Correction</Th>
              </tr>
            </thead>
            <tbody>
              {data.rows.map((r) => (
                <tr
                  key={rowKey(r)}
                  className={
                    "border-b border-slate-100 " + (r.is_group ? "text-slate-500" : "")
                  }
                >
                  <Td title={rowTitle(r, data.by)}>
                    <Link
                      href={rowHref(r, data.by)}
                      className="font-mono text-blue-700 hover:underline"
                    >
                      {rowLabel(r, data.by)}
                    </Link>
                  </Td>
                  <Td>{r.sessions}</Td>
                  <Td>{r.median_turns ?? "—"}</Td>
                  <Td>{r.median_tool_calls ?? "—"}</Td>
                  <Td>
                    {r.errors_per_100_turns == null
                      ? "—"
                      : r.errors_per_100_turns.toFixed(1)}
                  </Td>
                  <Td
                    title={
                      r.cost_usd == null
                        ? "no priced turns in this group"
                        : `${r.priced_turns} of ${r.priceable_turns} priceable turns priced`
                    }
                  >
                    {formatCost(r.cost_usd)}
                    {r.cost_usd != null && r.priced_turns < r.priceable_turns && (
                      <span className="text-xs text-slate-400"> (partial)</span>
                    )}
                  </Td>
                  <Td
                    title={
                      r.sessions_judged === 0
                        ? "no session in this group carries a label from the packaged rubric"
                        : `${r.sessions_judged} of ${r.sessions} sessions judged, ${r.labeled_turns} labelled turns`
                    }
                  >
                    {judged(r.avg_interaction_quality, r.sessions_judged)}
                  </Td>
                  <Td>{judged(r.rework_rate, r.sessions_judged)}</Td>
                  <Td>{judged(r.correction_rate, r.sessions_judged)}</Td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="mt-3 text-xs text-slate-400">{data.basis}</p>
    </Card>
  );
}
