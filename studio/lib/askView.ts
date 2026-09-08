// What the Ask page shows for one exchange, folded from the stream of
// events — pure, so the states script can assert every state without a
// browser: a lookup in flight, a lookup that found nothing, a truncated
// result, the answer with its cited sessions, the judge's failure.

import type { AskEvent } from "@/lib/api";

export interface AskStep {
  n: number;
  tool: string;
  args: Record<string, unknown>;
  why: string;
  /** Seconds the judge took to decide on this call. */
  thinkSeconds: number;
  /** Filled by the matching result event. */
  summary?: string;
  chars?: number;
  truncated?: boolean;
  error?: string | null;
  sessionIds: number[];
  /** Exactly what the judge was given for this step: the evidence. */
  resultText?: string;
  lookupSeconds?: number;
}

export interface Exchange {
  question: string;
  judge: string | null;
  steps: AskStep[];
  /** Markdown, once the answer event arrived. */
  answer: string | null;
  /** Sessions the answer cited that a lookup actually returned. */
  sessions: number[];
  /** Sessions the answer named that no lookup returned: not evidence. */
  unverified: number[];
  error: string | null;
  /** The error names a Settings gap (no judge URL, CLI missing). */
  prerequisite: string | null;
  /** True until answer or error arrives, or the person stops it. */
  running: boolean;
  stopped: boolean;
}

export function newExchange(question: string): Exchange {
  return {
    question,
    judge: null,
    steps: [],
    answer: null,
    sessions: [],
    unverified: [],
    error: null,
    prerequisite: null,
    running: true,
    stopped: false,
  };
}

/** Fold one event into an exchange. Returns a new object. */
export function applyEvent(x: Exchange, ev: AskEvent): Exchange {
  switch (ev.event) {
    case "judge":
      return { ...x, judge: ev.judge };
    case "step":
      return {
        ...x,
        steps: [
          ...x.steps,
          {
            n: ev.n,
            tool: ev.tool,
            args: ev.args,
            why: ev.why,
            thinkSeconds: ev.seconds,
            sessionIds: [],
          },
        ],
      };
    case "result":
      return {
        ...x,
        steps: x.steps.map((s) =>
          s.n === ev.n
            ? {
                ...s,
                summary: ev.summary,
                chars: ev.chars,
                truncated: ev.truncated,
                error: ev.error,
                sessionIds: ev.session_ids,
                resultText: ev.result_text,
                lookupSeconds: ev.seconds,
              }
            : s,
        ),
      };
    case "answer":
      return {
        ...x,
        answer: ev.markdown,
        sessions: ev.sessions,
        unverified: ev.unverified,
        running: false,
      };
    case "error":
      return {
        ...x,
        error: ev.error,
        prerequisite: ev.prerequisite ?? null,
        running: false,
      };
  }
}

export function stopExchange(x: Exchange): Exchange {
  return { ...x, running: false, stopped: true };
}

/** Sessions worth linking under an exchange: the verified citations
 *  first, then any a lookup returned, without repeats. An id the model
 *  named but no lookup returned is never here, so it is never linked. */
export function linkedSessions(x: Exchange, max = 12): number[] {
  const out: number[] = [];
  for (const id of [...x.sessions, ...x.steps.flatMap((s) => s.sessionIds)]) {
    if (!out.includes(id)) out.push(id);
    if (out.length >= max) break;
  }
  return out;
}

/** One line for a step: "find_sessions · 20 sessions · 4.1 s". */
export function stepLine(s: AskStep): string {
  const parts = [s.tool];
  if (s.error) parts.push(`error: ${s.error}`);
  else if (s.summary) parts.push(s.summary);
  else parts.push("running…");
  if (s.truncated && s.chars)
    parts.push(`result cut to fit (${s.chars.toLocaleString()} chars)`);
  parts.push(`${s.thinkSeconds.toFixed(1)} s to decide`);
  return parts.join(" · ");
}

/** The arguments as short text: session_id=12, query="pytest". */
export function argsLine(args: Record<string, unknown>): string {
  return Object.entries(args)
    .filter(([, v]) => v !== "" && v !== null && v !== undefined)
    .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
    .join(", ");
}

/** "#12" in the answer becomes a link to /sessions/12 — only for ids
 *  the exchange actually touched, so an issue number like "#319" in
 *  quoted text is left alone. Markdown in, Markdown out. */
export function linkSessionRefs(markdown: string, ids: number[]): string {
  if (!ids.length) return markdown;
  const known = new Set(ids);
  return markdown.replace(/(^|[^\w\]\/(])#(\d+)\b/g, (m, before: string, num: string) =>
    known.has(Number(num)) ? `${before}[#${num}](/sessions/${num})` : m,
  );
}
