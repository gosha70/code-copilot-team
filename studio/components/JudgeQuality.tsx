"use client";

import { AgreementReport, JudgeRuns } from "@/lib/api";
import { Card } from "@/components/ui";

// "How much can the judge be trusted?" (#313). PURE RENDERER: the page
// fetches the runs and the agreement report and owns the A/B choice.
// Every figure is shown with its n, and a row under the pair floor is
// greyed and said so — a 100% agreement over six turns is not evidence.

export default function JudgeQuality({
  runs,
  report,
  a,
  b,
  onSelect,
  error,
}: {
  runs: JudgeRuns | null;
  report: AgreementReport | null;
  a: string;
  b: string;
  onSelect: (a: string, b: string) => void;
  error: string | null;
}) {
  if (!runs) {
    return (
      <Card title="Judge quality">
        <p className="text-sm text-slate-400">{error ? "Could not load the label runs." : "Loading…"}</p>
      </Card>
    );
  }
  const sources = [
    ...runs.rubrics.map((r) => ({ id: r.source, label: `run ${r.name} (${r.turns.toLocaleString()} turns, ${r.judge || "judge unknown"})` })),
    ...runs.humans.map((h) => ({ id: h.source, label: `human ${h.labeler} (${h.turns.toLocaleString()} turns)` })),
  ];
  if (sources.length < 2) {
    return (
      <Card title="Judge quality">
        {sources.length === 0 ? (
          <p className="text-sm text-slate-600">No judge run yet. Run the judge step, then measure it.</p>
        ) : (
          <p className="text-sm text-slate-600">
            One label source so far: {sources[0].label}. Agreement needs a second one over the
            same turns.
          </p>
        )}
        <ul className="text-xs text-slate-500 mt-2 space-y-1 list-disc pl-5">
          <li>
            Run-to-run: run the judge again with a run name (below) over the turns the first run
            labelled — the same prompt twice should agree with itself.
          </li>
          <li>
            Human: <code>session-analytics labels sample --n 50 --out sample.csv</code>, label the CSV,
            then <code>session-analytics labels import sample.csv --labeler you</code>.
          </li>
        </ul>
      </Card>
    );
  }
  const pct = (v: number | null) => (v == null ? "—" : `${Math.round(v * 100)}%`);
  const kap = (v: number | null) => (v == null ? "—" : v.toFixed(2));
  return (
    <Card title="Judge quality">
      <div className="flex flex-wrap items-center gap-2 text-sm mb-3">
        <label className="text-xs text-slate-500">Compare</label>
        <select
          value={a}
          onChange={(e) => onSelect(e.target.value, b)}
          className="border border-slate-300 bg-white text-slate-900 rounded px-2 py-1 text-sm"
        >
          {sources.map((s) => (
            <option key={s.id} value={s.id}>{s.label}</option>
          ))}
        </select>
        <span className="text-xs text-slate-500">with</span>
        <select
          value={b}
          onChange={(e) => onSelect(a, e.target.value)}
          className="border border-slate-300 bg-white text-slate-900 rounded px-2 py-1 text-sm"
        >
          {sources.map((s) => (
            <option key={s.id} value={s.id}>{s.label}</option>
          ))}
        </select>
      </div>
      {!report ? (
        <p className="text-sm text-slate-400">{error ? "Could not compute agreement." : "Computing…"}</p>
      ) : report.turns_shared === 0 ? (
        <p className="text-sm text-slate-600">
          These two sources share no turns ({report.turns_a.toLocaleString()} and{" "}
          {report.turns_b.toLocaleString()} labelled). Run the second over the first&apos;s turns.
        </p>
      ) : (
        <>
          <p className="text-xs text-slate-500 mb-2">
            {report.turns_shared.toLocaleString()} turns labelled by both. A row under{" "}
            {report.min_pairs} pairs is shown but is not evidence.
          </p>
          <table className="w-full text-sm">
            <thead className="text-left text-slate-500 border-b border-slate-200">
              <tr>
                <th className="py-1 pr-3">Label</th>
                <th className="text-right pr-3">n</th>
                <th className="text-right pr-3">Agreement</th>
                <th className="text-right pr-3" title="Cohen's kappa: 0 = no better than chance, 1 = perfect">κ</th>
                <th className="text-right pr-3">A true</th>
                <th className="text-right">B true</th>
              </tr>
            </thead>
            <tbody>
              {report.labels.map((l) => (
                <tr
                  key={l.label}
                  className={"border-b border-slate-100 " + (l.sufficient ? "" : "text-slate-400")}
                  title={l.sufficient ? undefined : `only ${l.n} pairs — not evidence`}
                >
                  <td className="py-1 pr-3 font-mono text-xs">{l.label}</td>
                  <td className="text-right pr-3 tabular-nums">{l.n}</td>
                  <td className="text-right pr-3 tabular-nums">{pct(l.agreement)}</td>
                  <td className="text-right pr-3 tabular-nums">{kap(l.kappa)}</td>
                  <td className="text-right pr-3 tabular-nums">{l.a_true}</td>
                  <td className="text-right tabular-nums">{l.b_true}</td>
                </tr>
              ))}
              <tr className={"border-b border-slate-100 " + (report.sentiment.sufficient ? "" : "text-slate-400")}>
                <td className="py-1 pr-3 font-mono text-xs">sentiment (exact)</td>
                <td className="text-right pr-3 tabular-nums">{report.sentiment.n}</td>
                <td className="text-right pr-3 tabular-nums">{pct(report.sentiment.exact)}</td>
                <td className="text-right pr-3">—</td>
                <td className="text-right pr-3">—</td>
                <td className="text-right">—</td>
              </tr>
              <tr className={report.interaction_quality.sufficient ? "" : "text-slate-400"}>
                <td className="py-1 pr-3 font-mono text-xs">quality (within 1)</td>
                <td className="text-right pr-3 tabular-nums">{report.interaction_quality.n}</td>
                <td className="text-right pr-3 tabular-nums">{pct(report.interaction_quality.within_1)}</td>
                <td className="text-right pr-3">—</td>
                <td className="text-right pr-3">—</td>
                <td className="text-right">—</td>
              </tr>
            </tbody>
          </table>
          <p className="text-xs text-slate-400 mt-2">{report.basis}</p>
        </>
      )}
    </Card>
  );
}
