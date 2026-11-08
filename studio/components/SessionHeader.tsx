"use client";

import { useRef } from "react";
import { EffortEstimate, EffortSummary, SessionDetail, SessionTagsInfo } from "@/lib/api";
import { Stat, formatCost, formatDuration } from "@/components/ui";
import SessionTagIcons, { HandTag } from "@/components/SessionTags";
import { MIXED_NOTE, UNSTAMPED_NOTE, harnessFacts, harnessState } from "@/lib/harnessView";

// THE TOP OF A SESSION PAGE. It used to be one grey sentence — path,
// model, "4659 turns · 46 errors · 3d 7h · —" — with the project's
// medians in a smaller grey sentence under it. The numbers were there;
// nothing said whether they were large. Now: a title that names the
// project, badges for copilot and model, one tile per metric with the
// comparison to THIS project's other sessions written on it ("2.2× the
// project median"), coloured when the session is past the project's p90.
//
// The ten labelled facts (start/end, session id, baseline, harness stamp)
// used to sit under that as two wrapping rows of small grey type, and the
// page opened as a wall of metadata. They now live in one dialog behind
// the gear beside the title, where a reader looks when they need them.

/** How a session figure compares with its project. Pure. */
/** What duration_seconds measures (#414): ended_at − started_at with no
 *  idle cutoff, so a session resumed after a night counts the night. A
 *  reader of the figure must be told that; an active-time figure with a
 *  stated idle cutoff is the 2.1 follow-up. */
export const DURATION_BASIS = "wall clock, first entry to last";

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

/** One labelled fact. `display: contents` lets the wrapper disappear so
 *  the dt/dd pair lands in the dialog's two grid columns — a table look
 *  without a table's markup. */
function Fact({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="contents">
      <dt className="self-center text-[11px] uppercase tracking-wide text-slate-500">{label}</dt>
      <dd
        className={
          "self-center text-slate-700 " + (mono ? "font-mono text-xs break-all" : "")
        }
      >
        {value}
      </dd>
    </div>
  );
}

function DetailsIcon() {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      width="15"
      height="15"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <circle cx="12" cy="12" r="9" />
      <path d="M12 11v5" />
      <circle cx="12" cy="8" r="1" fill="currentColor" stroke="none" />
    </svg>
  );
}

/** The harness the session ran under (#371 A4): one labelled row of
 *  facts, or a single sentence when there is no stamp. A mixed session
 *  shows its earliest stamp and says so. */
export function HarnessFacts({ data }: { data: SessionDetail }) {
  const state = harnessState(data);
  if (state === "unstamped") {
    return (
      <p
        className="mt-4 border-t border-slate-100 pt-3 text-xs text-slate-500"
        title={UNSTAMPED_NOTE}
      >
        Harness: unstamped — this session predates the harness stamp.
      </p>
    );
  }
  return (
    <dl className="mt-4 grid grid-cols-[9rem,1fr] gap-x-4 gap-y-2.5 border-t border-slate-100 pt-3 text-sm">
      {harnessFacts(data).map((f) => (
        <div key={f.label} className="contents">
          <dt className="self-center text-[11px] uppercase tracking-wide text-slate-500" title={f.title}>
            {f.label}
          </dt>
          <dd className="self-center font-mono text-xs text-slate-700">{f.value}</dd>
        </div>
      ))}
      {state === "mixed" && (
        <div className="contents" title={MIXED_NOTE}>
          <dt className="self-center text-[11px] uppercase tracking-wide text-slate-500">Harness</dt>
          <dd className="self-center text-xs text-amber-700">mixed — earliest stamp shown</dd>
        </div>
      )}
    </dl>
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
  const details = useRef<HTMLDialogElement>(null);
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
          <button
            type="button"
            onClick={() => details.current?.showModal()}
            aria-label="Session details"
            title="Started, ended, session id and the harness stamp"
            className="inline-flex items-center gap-1.5 rounded-md border border-slate-300 bg-white px-2.5 py-1 text-sm text-slate-700 hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400 focus-visible:ring-offset-2"
          >
            <DetailsIcon />
            Details
          </button>
        </div>
        <p
          className="text-xs text-slate-500 font-mono mt-0.5"
          title={data.session_id}
        >
          {data.project_path || ""}
        </p>
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
          note={[DURATION_BASIS, duration.note].filter(Boolean).join(" · ")}
          tone={duration.tone}
        />
        <Stat
          label="Cost"
          value={formatCost(data.cost_usd)}
          note={costNote}
          tone={cost.tone}
        />
      </div>

      <dialog
        ref={details}
        aria-labelledby="session-details-title"
        onClick={(e) => {
          // A click on the backdrop lands on the dialog element itself.
          if (e.target === e.currentTarget) e.currentTarget.close();
        }}
        className="w-[min(46rem,calc(100vw-2rem))] rounded-lg border border-slate-200 p-0 text-slate-900 backdrop:bg-slate-900/40"
      >
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-3">
          <h2 id="session-details-title" className="text-sm font-semibold text-slate-800">
            Session details
          </h2>
          <button
            type="button"
            onClick={() => details.current?.close()}
            className="border border-slate-300 bg-white text-slate-700 text-sm px-3 py-1 rounded hover:bg-slate-50"
          >
            Close
          </button>
        </div>
        <div className="px-5 py-4">
          <dl className="grid grid-cols-[9rem,1fr] gap-x-4 gap-y-2.5 text-sm">
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
          <HarnessFacts data={data} />
        </div>
      </dialog>
    </div>
  );
}
