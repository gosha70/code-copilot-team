"use client";

import { JudgeModels, JudgeProgress as Progress } from "@/lib/api";

// THE JUDGE STEP, WHILE IT RUNS. A model call per turn over a batch
// takes minutes, and "running…" for minutes is indistinguishable from
// hung. The runner reports after every turn; this shows done/total,
// what labelled and what failed, the rate and the remaining time, and
// the reason the most recent call failed — so a wrong model name or a
// dead backend is visible on the first turn, not after fifty.

/** Text for the progress line. Pure, so the states check asserts it. */
export function progressSummary(
  p: Progress,
  seconds: number | undefined,
): { pct: number; line: string; eta: string } {
  const done = p.labeled;
  const pct = p.total > 0 ? Math.round((done / p.total) * 100) : 0;
  const parts = [
    `${done.toLocaleString()} of ${p.total.toLocaleString()} turns`,
  ];
  parts.push(`${p.parse_ok.toLocaleString()} labelled`);
  if (p.parse_failed > 0)
    parts.push(`${p.parse_failed.toLocaleString()} failed`);
  let eta = "";
  if (seconds && done > 0 && p.total > done) {
    const perTurn = seconds / done;
    parts.push(`${(60 / perTurn).toFixed(1)} turns/min`);
    const left = Math.round(perTurn * (p.total - done));
    eta =
      left >= 90
        ? `about ${Math.round(left / 60)} min left`
        : `about ${left}s left`;
  }
  return { pct, line: parts.join(" · "), eta };
}

/** What the judge choice means: the configured judge is the default,
 *  named with where it is set; anything else is a one-off override. */
export function judgeChoiceLabel(
  configured: JudgeModels["configured"] | undefined,
): string {
  if (!configured) return "The judge configured in Settings";
  const where =
    configured.source === "settings" ? "Settings" : "packaged default";
  return `${configured.spec} (${where})`;
}

export default function JudgeProgressBar({
  progress,
  seconds,
  running,
}: {
  progress: Progress;
  seconds: number | undefined;
  running: boolean;
}) {
  const { pct, line, eta } = progressSummary(progress, seconds);
  const allFailed =
    progress.parse_failed > 0 &&
    progress.parse_ok === 0 &&
    progress.labeled >= 3;
  return (
    <div className="mt-3">
      <div className="h-2 w-full rounded bg-slate-100 overflow-hidden">
        <div
          className={
            "h-2 rounded " +
            (progress.parse_failed > 0 ? "bg-amber-500" : "bg-blue-600")
          }
          style={{ width: `${pct}%` }}
        />
      </div>
      <p className="text-xs text-slate-600 mt-1">
        {line}
        {running && eta ? ` · ${eta}` : ""}
        {progress.judge ? ` · ${progress.judge}` : ""}
      </p>
      {progress.last_error && (
        <p
          className={
            "text-xs mt-1 " + (allFailed ? "text-rose-700" : "text-amber-800")
          }
        >
          {allFailed ? "Every call is failing — " : "Last failure: "}
          {progress.last_error}
          {allFailed
            ? ". Check the judge under Settings → LLM-as-Judge, or pick another model."
            : ""}
        </p>
      )}
    </div>
  );
}
