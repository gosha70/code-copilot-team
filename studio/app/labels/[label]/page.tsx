"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { api } from "@/lib/api";
import { Badge, Card, ErrorNote, Loading, Stat, useApi } from "@/components/ui";

// One judge label, read the way a person checks a label: how often it
// fired, whether that rate rests on enough turns to mean anything, and
// the turns themselves — each linking to its place on the session's
// Timeline. Surfaces /api/labels/correlation and /api/labels/{label}/traces
// (#307), which had no UI before.

export default function LabelPage() {
  const params = useParams();
  const label = decodeURIComponent(String(params.label));
  const corr = useApi(() => api.labelCorrelation(), [label]);
  const traces = useApi(() => api.labelTraces(label, 100), [label]);

  if (corr.loading || traces.loading) return <Loading />;
  if (corr.error) return <ErrorNote error={corr.error} />;
  if (traces.error) return <ErrorNote error={traces.error} />;
  if (!corr.data || !traces.data) return <ErrorNote error="no data" />;

  const row = corr.data.labels.find((l) => l.label === label);
  const pct = (v: number | null) =>
    v == null ? "—" : `${Math.round(v * 100)}%`;

  return (
    <div className="space-y-4">
      <div>
        <Link href="/" className="text-xs text-blue-700 hover:underline">
          ← Dashboard
        </Link>
        <h1 className="text-2xl font-bold font-mono">{label}</h1>
        <p className="text-sm text-slate-500">
          {corr.data.rubric_name ? `Rubric ${corr.data.rubric_name}. ` : "All rubrics. "}
          Rates are over turns that carry both a label and an archived trace;
          a label under {corr.data.min_support} such turns is shown but not
          trusted.
        </p>
      </div>

      {row ? (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <Stat
            label="Fired on"
            value={pct(row.true_rate)}
            note={
              `${row.true_count.toLocaleString()} of ` +
              `${row.correlated_turns.toLocaleString()} correlated turns` +
              (row.sufficient ? "" : " — below the support floor")
            }
          />
          <Stat
            label="Correlated turns"
            value={row.correlated_turns}
            note={`of ${corr.data.coverage.labelled_turns.toLocaleString()} labelled`}
          />
          <Stat
            label="Avg trace length"
            value={
              row.avg_trace_chars == null
                ? "—"
                : Math.round(row.avg_trace_chars)
            }
            note="chars, where the label fired"
          />
          <Stat
            label="Avg quality"
            value={
              row.avg_interaction_quality == null
                ? "—"
                : row.avg_interaction_quality.toFixed(1)
            }
            note="judge's 1–5, where the label fired"
          />
        </div>
      ) : (
        <Card>
          <p className="text-sm text-slate-600">
            No correlation row for this label: nothing labelled with it has an
            archived trace. Enable <code>trace_archive</code> for the project
            and re-run Load sessions, then the judge.
          </p>
        </Card>
      )}

      <Card title={`Turns where ${label} fired`}>
        {traces.data.traces.length === 0 ? (
          <p className="text-sm text-slate-400">
            No archived turn carries this label yet.
          </p>
        ) : (
          <table className="w-full text-sm">
            <thead className="text-left text-slate-500 border-b border-slate-200">
              <tr>
                <th className="py-2 pr-3">Turn</th>
                <th className="pr-3">Project</th>
                <th className="pr-3">Role</th>
                <th>What was said</th>
              </tr>
            </thead>
            <tbody>
              {traces.data.traces.map((t, i) => (
                <tr key={i} className="border-b border-slate-100 align-top">
                  <td className="py-2 pr-3 whitespace-nowrap">
                    <Link
                      href={`/sessions/${t.session_ref}#turn-${t.sequence_num}`}
                      className="font-mono text-xs text-blue-700 hover:underline"
                      title={`${t.copilot} session, turn ${t.sequence_num}`}
                    >
                      #{t.sequence_num}
                    </Link>
                  </td>
                  <td
                    className="pr-3 text-xs text-slate-500 truncate max-w-[12rem]"
                    title={t.project_path || undefined}
                  >
                    {t.project_path || "—"}
                  </td>
                  <td className="pr-3 text-xs">
                    <Badge kind={t.role === "user" ? "command" : "question"}>
                      {t.role}
                    </Badge>
                    {t.sentiment && (
                      <span className="ml-1">
                        <Badge kind={t.sentiment}>{t.sentiment}</Badge>
                      </span>
                    )}
                  </td>
                  <td className="text-slate-700 whitespace-pre-wrap break-words">
                    {t.snippet}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}
