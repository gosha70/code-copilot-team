"use client";

import { useState } from "react";
import {
  AnalysisKind,
  AnalysisRow,
  ApiFailure,
  CoachingPrompt,
  Inefficiency,
  TuningFinding,
} from "@/lib/api";
import { Badge, Card, formatDuration } from "@/components/ui";

// One analysis panel: Agent Tuning, Prompt Coaching or Efficiency.
//
// PURE RENDERER over a stored row. The page owns fetching and the run
// button's request; this component turns the row into something a
// person can act on — every item carries the turns it was drawn from,
// and each turn chip jumps to that turn on the Timeline, so nothing here
// is advice without evidence.
//
// The footer is not decoration: it says WHICH model produced the text
// and WHAT it was shown (archive vs previews, how many characters,
// truncated or not). A finding drawn from previews of a truncated
// transcript is worth less than one drawn from the full archive, and
// the reader must be able to tell.

export type PanelState =
  | { kind: "absent" }
  | { kind: "running" }
  | { kind: "failed"; failure: ApiFailure; keptPrevious?: boolean }
  | { kind: "done"; row: AnalysisRow };

const SEVERITY_BADGE: Record<string, string> = {
  high: "FRUSTRATED",
  medium: "correction",
  low: "NEUTRAL",
};

// Mirrors judge/contracts.py: the statuses under which no answer arrived.
const NO_ANSWER_STATUSES = new Set(["backend_error", "timeout"]);

const LEVER_HINT: Record<string, string> = {
  SCRIPT: "a shell or Python script",
  HOOK: "a Claude Code hook",
  SKILL: "a reusable skill",
  STEERING: "a CLAUDE.md rule",
};

export default function SessionAnalysis({
  kind,
  title,
  state,
  judge,
  onRun,
  learnLinks,
}: {
  kind: AnalysisKind;
  title: string;
  state: PanelState;
  judge: string;
  onRun: (force: boolean) => void;
  /** finding category / lever → Learn slug or "section:<id>" (#309);
   *  absent while the Learn index has not loaded. */
  learnLinks?: Record<string, string>;
}) {
  if (state.kind === "absent") {
    return (
      <Card title={title}>
        <p className="text-sm text-slate-600 mb-3">{BLURB[kind]}</p>
        <button
          onClick={() => onRun(false)}
          className="bg-blue-600 text-white text-sm px-4 py-1.5 rounded hover:bg-blue-700"
        >
          Generate with {judge}
        </button>
        <span className="text-xs text-slate-500 ml-3">
          One model call over the whole transcript — usually 1–3 minutes.
        </span>
      </Card>
    );
  }
  if (state.kind === "running") {
    return (
      <Card title={title}>
        <p className="text-sm text-slate-600 animate-pulse">
          Asking {judge} to read the whole session… this is one call and can
          take a few minutes.
        </p>
      </Card>
    );
  }
  if (state.kind === "failed") {
    const f = state.failure;
    return (
      <Card title={title}>
        <div className="bg-amber-50 border border-amber-200 text-amber-900 rounded p-3 text-sm space-y-1">
          <p className="font-medium">{f.detail?.error || f.message}</p>
          {f.detail?.guidance && (
            <p className="text-amber-800">{f.detail.guidance}</p>
          )}
          {state.keptPrevious && (
            <p className="text-amber-800">
              Your earlier result was kept — reload the page to see it.
            </p>
          )}
        </div>
        <button
          onClick={() => onRun(true)}
          className="mt-3 border border-slate-300 bg-white text-slate-700 text-sm px-3 py-1 rounded hover:bg-slate-50"
        >
          Try again
        </button>
      </Card>
    );
  }

  const row = state.row;
  if (row.parse_status !== "ok" || !row.result) {
    // A stored failure is either the judge not answering (backend_error,
    // timeout) or answering something the parser could not read. Say
    // which: the fix is different (check the backend vs. try another
    // model).
    const noAnswer = NO_ANSWER_STATUSES.has(row.parse_status);
    return (
      <Card title={title}>
        <div className="bg-amber-50 border border-amber-200 text-amber-900 rounded p-3 text-sm space-y-1">
          <p className="font-medium">
            {noAnswer
              ? `The judge did not answer (${row.parse_status}).`
              : `The model answered but the answer could not be read (${row.parse_status}).`}
          </p>
          {row.error && (
            <pre className="text-xs whitespace-pre-wrap text-amber-800 max-h-40 overflow-y-auto">
              {row.error}
            </pre>
          )}
          {row.kept_previous && (
            <p className="text-amber-800">
              Your earlier result was kept — reload the page to see it.
            </p>
          )}
        </div>
        <Footer row={row} onRun={onRun} />
      </Card>
    );
  }

  return (
    <Card title={title}>
      <p className="text-sm text-slate-700 mb-4">{row.result.summary}</p>
      {kind === "tuning" && (
        <Findings
          items={row.result.findings || []}
          dropped={row.result.dropped_items || 0}
          learnLinks={learnLinks}
        />
      )}
      {kind === "coaching" && (
        <Coaching
          items={row.result.prompts || []}
          score={row.result.overall_score ?? null}
          patterns={row.result.patterns || []}
          dropped={row.result.dropped_items || 0}
        />
      )}
      {kind === "efficiency" && (
        <Efficiency
          items={row.result.inefficiencies || []}
          dropped={row.result.dropped_items || 0}
          learnLinks={learnLinks}
        />
      )}
      <Footer row={row} onRun={onRun} />
    </Card>
  );
}

const BLURB: Record<AnalysisKind, string> = {
  tuning:
    "Where the assistant's behaviour could be fixed by configuration — steering rules, permissions, hooks, skills — with the exact change to apply.",
  coaching:
    "Which of your prompts were vague or missing context, and the prompt you could have sent instead.",
  efficiency:
    "Where the turns went: retries, re-discovery, detours — and the script, hook, skill or rule that would remove each one.",
};

/** The href for a finding category or lever, per the Learn index. */
export function learnHref(value: string, learnLinks?: Record<string, string>): string | null {
  const target = learnLinks?.[value];
  if (!target) return null;
  return target.startsWith("section:")
    ? `/learn#${target.slice("section:".length)}`
    : `/learn/${encodeURIComponent(target)}`;
}

// The category badge doubles as the way out: "hooks" links to the Hooks
// Guide, "permissions" to the permissions guide — the finding names the
// problem, the page explains the fix (#309).
function LearnBadge({ value, learnLinks }: { value: string; learnLinks?: Record<string, string> }) {
  const href = learnHref(value, learnLinks);
  if (!href) return <Badge kind="command">{value}</Badge>;
  return (
    <a href={href} title={`How to fix this: open the ${value} guide in Learn`} className="hover:underline">
      <Badge kind="command">{value} ↗</Badge>
    </a>
  );
}

// `turns` may be absent on a row stored before the item contract was
// enforced server-side; render it as "no turn cited", never crash.
function TurnChips({ turns = [] }: { turns?: number[] }) {
  if (!turns.length)
    return <span className="text-xs text-slate-400">no turn cited</span>;
  return (
    <span className="inline-flex flex-wrap gap-1">
      {turns.map((t) => (
        <a
          key={t}
          href={`#turn-${t}`}
          className="text-xs font-mono px-1.5 py-0.5 rounded bg-slate-100 text-slate-700 hover:bg-blue-100 hover:text-blue-800"
          title={`Jump to turn ${t} on the Timeline`}
        >
          #{t}
        </a>
      ))}
    </span>
  );
}

function CopyButton({ text }: { text: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      onClick={() => {
        navigator.clipboard?.writeText(text).then(() => {
          setDone(true);
          setTimeout(() => setDone(false), 1500);
        });
      }}
      className="text-xs border border-slate-300 bg-white text-slate-700 rounded px-2 py-0.5 hover:bg-slate-50"
    >
      {done ? "Copied" : "Copy"}
    </button>
  );
}

// An empty list is only "nothing found" when the model offered nothing.
// When it offered items the contract had to drop (unknown category or
// lever, blank coaching rows), say so — the fix is a stronger model, not
// a cleaner session.
function EmptyList({ text, dropped }: { text: string; dropped: number }) {
  if (dropped > 0) {
    return (
      <p className="text-sm text-amber-700">
        The model offered {dropped} item{dropped === 1 ? "" : "s"} that did not
        follow the expected format, so none can be shown. Re-generate, or try a
        stronger model.
      </p>
    );
  }
  return <p className="text-sm text-slate-500">{text}</p>;
}

function Findings({
  items,
  dropped,
  learnLinks,
}: {
  items: TuningFinding[];
  dropped: number;
  learnLinks?: Record<string, string>;
}) {
  if (!items.length) {
    return (
      <EmptyList
        text="No configuration problem is evidenced by this session."
        dropped={dropped}
      />
    );
  }
  return (
    <div className="space-y-3">
      {items.map((f, i) => (
        <div key={i} className="border border-slate-200 rounded p-3">
          <div className="flex flex-wrap items-center gap-2 mb-1">
            <Badge kind={SEVERITY_BADGE[f.severity] || "NEUTRAL"}>
              {f.severity}
            </Badge>
            <LearnBadge value={f.category} learnLinks={learnLinks} />
            <span className="font-medium text-sm">{f.title}</span>
            <span className="ml-auto">
              <TurnChips turns={f.evidence_turns} />
            </span>
          </div>
          <p className="text-sm text-slate-700">{f.explanation}</p>
          <p className="text-sm text-slate-900 mt-1">
            <span className="font-medium">Change:</span> {f.recommendation}
          </p>
          {f.config_change && (
            <div className="mt-2">
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs font-mono text-slate-500">
                  {f.config_change.file}
                </span>
                <CopyButton text={f.config_change.diff} />
              </div>
              <pre className="text-xs bg-slate-900 text-slate-100 rounded p-3 overflow-x-auto whitespace-pre-wrap">
                {f.config_change.diff}
              </pre>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

function Coaching({
  items,
  score,
  patterns,
  dropped,
}: {
  items: CoachingPrompt[];
  score: number | null;
  patterns: string[];
  dropped: number;
}) {
  return (
    <div className="space-y-3">
      {score != null && (
        <p className="text-sm text-slate-600">
          Overall prompting score:{" "}
          <span className="font-medium text-slate-900">{score}/5</span>
        </p>
      )}
      {items.length === 0 ? (
        <EmptyList
          text="Every prompt in this session was clear enough to act on."
          dropped={dropped}
        />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-slate-500 border-b border-slate-200">
              <tr>
                <th className="py-2 pr-3 w-14">Turn</th>
                <th className="pr-3">Original</th>
                <th className="pr-3">Issue</th>
                <th>Improved prompt</th>
              </tr>
            </thead>
            <tbody>
              {items.map((p, i) => (
                <tr key={i} className="border-b border-slate-100 align-top">
                  <td className="py-2 pr-3">
                    {p.turn != null ? <TurnChips turns={[p.turn]} /> : "—"}
                  </td>
                  <td className="pr-3 whitespace-pre-wrap text-slate-600 max-w-xs">
                    {p.original}
                  </td>
                  <td className="pr-3 text-slate-700 max-w-xs">{p.issue}</td>
                  <td className="whitespace-pre-wrap text-slate-900 max-w-md">
                    <div className="flex items-start gap-2">
                      <span className="flex-1">{p.improved}</span>
                      <CopyButton text={p.improved} />
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {patterns.length > 0 && (
        <div>
          <p className="text-xs font-medium text-slate-500 uppercase tracking-wide mb-1">
            Patterns
          </p>
          <ul className="list-disc pl-5 text-sm text-slate-700 space-y-0.5">
            {patterns.map((p, i) => (
              <li key={i}>{p}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function Efficiency({
  items,
  dropped,
  learnLinks,
}: {
  items: Inefficiency[];
  dropped: number;
  learnLinks?: Record<string, string>;
}) {
  const [open, setOpen] = useState<number | null>(null);
  if (!items.length) {
    return (
      <EmptyList
        text="No wasted effort was evidenced by this session."
        dropped={dropped}
      />
    );
  }
  return (
    <div className="space-y-3">
      {items.map((x, i) => (
        <div key={i} className="border border-slate-200 rounded p-3">
          <div className="flex flex-wrap items-center gap-2 mb-1">
            <LearnBadge value={x.lever} learnLinks={learnLinks} />
            <span className="font-medium text-sm">{x.title}</span>
            <span className="text-xs text-slate-500">
              {x.wasted_turns != null && `${x.wasted_turns} turns`}
              {x.wasted_turns != null && x.wasted_seconds != null && " · "}
              {x.wasted_seconds != null && formatDuration(x.wasted_seconds)}
            </span>
            <span className="ml-auto">
              <TurnChips turns={x.evidence_turns} />
            </span>
          </div>
          <p className="text-sm text-slate-600">
            Remove it with {LEVER_HINT[x.lever] || x.lever}
            {x.starter && (
              <>
                {" · "}
                <button
                  onClick={() => setOpen(open === i ? null : i)}
                  className="text-blue-700 hover:underline"
                >
                  {open === i ? "hide starter" : `starter: ${x.starter.file}`}
                </button>
              </>
            )}
          </p>
          {x.starter && open === i && (
            <div className="mt-2">
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs font-mono text-slate-500">
                  {x.starter.file}
                </span>
                <CopyButton text={x.starter.content} />
              </div>
              <pre className="text-xs bg-slate-900 text-slate-100 rounded p-3 overflow-x-auto whitespace-pre-wrap">
                {x.starter.content}
              </pre>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

function Footer({
  row,
  onRun,
}: {
  row: AnalysisRow;
  onRun: (force: boolean) => void;
}) {
  const when = row.created_at ? new Date(row.created_at).toLocaleString() : "";
  const source =
    row.transcript_source === "archive"
      ? "the full archived transcript"
      : row.transcript_source === "mixed"
        ? "a partly archived transcript"
        : "content previews only (enable trace_archive for this project to give the model the full text)";
  return (
    <div className="mt-4 pt-3 border-t border-slate-100 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-slate-500">
      <span>
        {row.parse_status === "ok" ? "Generated" : "Attempted"} {when} by{" "}
        <span className="font-mono">
          {row.judge_id}:{row.judge_model}
        </span>{" "}
        from {source}, {row.transcript_chars.toLocaleString()} chars
        {row.truncated && (
          <span className="text-amber-700">
            {" "}
            — truncated to fit the model's context
          </span>
        )}
        .
      </span>
      <button
        onClick={() => onRun(true)}
        className="ml-auto border border-slate-300 bg-white text-slate-700 rounded px-2 py-0.5 hover:bg-slate-50"
      >
        Re-generate
      </button>
    </div>
  );
}
