"use client";

import { EffortEstimate, EffortSummary, SessionDetail, SessionTagsInfo } from "@/lib/api";
import { Stat, formatCost, formatDuration } from "@/components/ui";
import SessionTagIcons, { HandTag } from "@/components/SessionTags";

// THE TOP OF A SESSION PAGE. It used to be one grey sentence — path,
// model, "4659 turns · 46 errors · 3d 7h · —" — with the project's
// medians in a smaller grey sentence under it. The numbers were there;
// nothing said whether they were large. Now: a title that names the
// project, badges for copilot and model, when it ran, and one tile per
// metric with the comparison to THIS project's other sessions written
// on it ("2.2× the project median"), coloured when the session is past
// the project's p90.

/** How a session figure compares with its project. Pure. */
export function versusProject(
  value: number | null | undefined,
  summary: EffortSummary | undefined,
): { note: string; tone: "default" | "warn" } {
  if (
    value == null ||
    !summary ||
    !summary.sufficient ||
    summary.median == null
  ) {
    return { note: "", tone: "default" };
  }
  if (summary.median === 0) {
    return {
      note: value > 0 ? "project median is 0" : "same as the project median",
      tone: "default",
    };
  }
  const ratio = value / summary.median;
  const past90 = summary.p90 != null && value > summary.p90;
  const word =
    ratio >= 0.95 && ratio <= 1.05
      ? "about the project median"
      : `${ratio.toFixed(1)}× the project median`;
  return {
    note: past90 ? `${word} · above its p90` : word,
    tone: past90 ? "warn" : "default",
  };
}

/** The last path segment: what a person calls the project. */
export function projectName(path: string | null): string {
  if (!path) return "(no project path)";
  const parts = path.replace(/\/+$/, "").split("/");
  return parts[parts.length - 1] || path;
}

export function errorRate(errors: number, turns: number): string {
  if (!turns) return "—";
  return `${((errors / turns) * 100).toFixed(1)} per 100 turns`;
}

/** One labelled fact: the label small and grey above the value, so a
 *  row of them reads as facts rather than as a sentence. */
function Fact({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div>
      <dt className="text-[11px] uppercase tracking-wide text-slate-400">{label}</dt>
      <dd className={"text-slate-700 " + (mono ? "font-mono text-xs" : "")}>{value}</dd>
    </div>
  );
}

export default function SessionHeader({
  data,
  baseline,
  tags,
  onToggleTag,
}: {
  data: SessionDetail;
  baseline: EffortEstimate | null;
  /** The session's tags (may be newer than data.tags after a toggle). */
  tags?: SessionTagsInfo;
  onToggleTag?: (tag: HandTag, on: boolean) => void;
}) {
  const b = baseline && baseline.sessions > 0 ? baseline : null;
  const turns = versusProject(data.turn_count, b?.turns);
  const tools = versusProject(data.tool_call_count, b?.tool_calls);
  const errors = versusProject(data.error_count, b?.errors);
  const duration = versusProject(
    data.duration_seconds ?? null,
    b?.duration_seconds,
  );
  // A priced SUBTOTAL must not be compared with complete costs: $1 of
  // priced turns beside unpriced ones is not "0.1× the median", it is
  // unknown. Only a fully priced session gets the comparison.
  const cov = data.cost_coverage;
  const cost = cov?.complete
    ? versusProject(data.cost_usd, b?.cost_usd)
    : { note: "", tone: "default" as const };
  const costNote =
    data.cost_usd == null
      ? "no priced turns"
      : cov && !cov.complete
        ? `priced turns only — ${cov.priced_turns} of ${cov.priceable_turns}; not compared`
        : cost.note || undefined;
  const started = data.started_at ? new Date(data.started_at) : null;
  const ended = data.ended_at ? new Date(data.ended_at) : null;
  return (
    <div className="space-y-3">
      <div>
        <div className="flex items-center gap-2 flex-wrap">
          <h1 className="text-2xl font-bold">
            {projectName(data.project_path)}
          </h1>
          <span className="text-xs px-2 py-0.5 rounded bg-slate-200 text-slate-700">
            {data.copilot}
          </span>
          {data.model && (
            <span className="text-xs px-2 py-0.5 rounded bg-blue-50 text-blue-700 font-mono">
              {data.model}
            </span>
          )}
          <SessionTagIcons tags={tags ?? data.tags} onToggle={onToggleTag} size="md" />
        </div>
        <p
          className="text-xs text-slate-500 font-mono mt-0.5"
          title={data.session_id}
        >
          {data.project_path || ""}
        </p>
        <dl className="mt-2 flex flex-wrap gap-x-6 gap-y-2 text-sm">
          <Fact label="Started" value={started ? started.toLocaleString() : "unknown"} />
          <Fact label="Ended" value={ended ? ended.toLocaleString() : "unknown"} />
          <Fact label="Session id" value={data.session_id} mono />
          <Fact
            label="Compared with"
            value={
              b
                ? `${b.sessions} other session${b.sessions === 1 ? "" : "s"} of this project`
                : "nothing yet — too few sessions of this project"
            }
          />
        </dl>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <Stat
          label="Turns"
          value={data.turn_count.toLocaleString()}
          note={turns.note || undefined}
          tone={turns.tone}
        />
        <Stat
          label="Tool calls"
          value={data.tool_call_count.toLocaleString()}
          note={tools.note || undefined}
          tone={tools.tone}
        />
        <Stat
          label="Errors"
          value={data.error_count.toLocaleString()}
          note={[errorRate(data.error_count, data.turn_count), errors.note]
            .filter(Boolean)
            .join(" · ")}
          tone={
            data.error_count > 0 && errors.tone === "warn" ? "warn" : "default"
          }
        />
        <Stat
          label="Duration"
          value={formatDuration(data.duration_seconds)}
          note={duration.note || undefined}
          tone={duration.tone}
        />
        <Stat
          label="Cost"
          value={formatCost(data.cost_usd)}
          note={costNote}
          tone={cost.tone}
        />
      </div>
    </div>
  );
}
