"use client";

import { Suspense, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { api, AskInfo, AskTurn } from "@/lib/api";
import {
  Exchange,
  applyEvent,
  argsLine,
  linkSessionRefs,
  linkedSessions,
  newExchange,
  stepLine,
  stopExchange,
} from "@/lib/askView";
import {
  Card,
  ErrorNote,
  Loading,
  describeError,
  useApi,
} from "@/components/ui";

// ASK. A question about the person's own sessions, in words, answered by
// the judge configured in Settings — and only that one — through
// read-only lookups over the store: sessions, turn text, analyses,
// patterns, the knowledge graph. Every lookup is shown as it happens,
// with what was asked and what came back, so the answer can be checked
// against rows; the sessions it used are links. This replaced the Search
// page, which searched only archived text and answered nothing on a
// store with no archive.

export default function AskPage() {
  return (
    <Suspense fallback={<Loading />}>
      <Ask />
    </Suspense>
  );
}

function Ask() {
  const params = useSearchParams();
  const about = params.get("session");
  const { data: info, error, loading } = useApi(() => api.askInfo(), []);
  const [question, setQuestion] = useState(
    about ? `About session #${about}: ` : "",
  );
  const [exchanges, setExchanges] = useState<Exchange[]>([]);
  const abortRef = useRef<AbortController | null>(null);
  const endRef = useRef<HTMLDivElement | null>(null);
  const running = exchanges.some((x) => x.running);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [exchanges]);

  async function submit(q?: string) {
    const text = (q ?? question).trim();
    if (!text || running) return;
    const history: AskTurn[] = exchanges
      .filter((x) => x.answer)
      .map((x) => ({ question: x.question, answer: x.answer as string }));
    const index = exchanges.length;
    setExchanges((xs) => [...xs, newExchange(text)]);
    setQuestion("");
    const controller = new AbortController();
    abortRef.current = controller;
    const update = (fn: (x: Exchange) => Exchange) =>
      setExchanges((xs) => xs.map((x, i) => (i === index ? fn(x) : x)));
    try {
      await api.ask(
        text,
        history,
        (ev) => update((x) => applyEvent(x, ev)),
        controller.signal,
      );
      // A stream that ended without answer or error (server gone).
      update((x) =>
        x.running
          ? { ...x, running: false, error: "the API stopped answering" }
          : x,
      );
    } catch (e) {
      if (controller.signal.aborted) update(stopExchange);
      else update((x) => ({ ...x, running: false, error: describeError(e) }));
    } finally {
      abortRef.current = null;
    }
  }

  function stop() {
    abortRef.current?.abort();
  }

  if (loading) return <Loading />;
  if (error || !info)
    return <ErrorNote error={error || "the API did not answer"} />;

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-bold">Ask</h1>
        <p className="text-sm text-slate-500">
          Ask about your sessions in words. The judge LLM from Settings looks
          things up in your store — never guesses — and shows each lookup so you
          can check the answer.
        </p>
      </div>

      <Facts info={info} />

      {exchanges.length === 0 && (
        <Card title="Try one of these">
          <div className="flex flex-wrap gap-2">
            {info.examples.map((e) => (
              <button
                key={e}
                type="button"
                onClick={() => submit(e)}
                className="text-left text-sm border border-slate-300 bg-white text-slate-700 rounded-full px-3 py-1 hover:bg-slate-50"
              >
                {e}
              </button>
            ))}
          </div>
        </Card>
      )}

      <div className="space-y-4">
        {exchanges.map((x, i) => (
          <ExchangeView key={i} x={x} onStop={stop} />
        ))}
        <div ref={endRef} />
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
        className="flex gap-2 items-start sticky bottom-0 bg-slate-50 py-2"
      >
        <textarea
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
          rows={2}
          placeholder={
            exchanges.length
              ? "Ask a follow-up (Enter to send, Shift+Enter for a new line)"
              : "e.g. Which sessions in this project had the most tool errors last week?"
          }
          className="border border-slate-300 bg-white text-slate-900 rounded px-3 py-2 text-sm w-full"
        />
        {running ? (
          <button
            type="button"
            onClick={stop}
            className="border border-slate-300 bg-white text-slate-700 text-sm px-4 py-2 rounded hover:bg-slate-50 shrink-0"
            title="Stop listening. A lookup the judge is already working on finishes on its own."
          >
            Stop
          </button>
        ) : (
          <button
            type="submit"
            disabled={!question.trim()}
            className="bg-blue-600 text-white text-sm px-4 py-2 rounded hover:bg-blue-700 disabled:opacity-50 shrink-0"
          >
            Ask
          </button>
        )}
      </form>
    </div>
  );
}

const GRAPH_STATE_LABEL: Record<AskInfo["facts"]["graph_state"], string> = {
  ready: "graph ready",
  absent: "graph not built",
  unbuilt: "graph store empty (not built)",
  unopenable: "graph store cannot be opened",
  "kuzu-missing": "graph unavailable (kuzu not installed)",
};

function Facts({ info }: { info: AskInfo }) {
  const f = info.facts;
  const parts = [
    `${f.sessions.toLocaleString()} sessions`,
    `${f.project_count.toLocaleString()} project${f.project_count === 1 ? "" : "s"}`,
    f.sessions_with_analyses
      ? `analyses on ${f.sessions_with_analyses}`
      : "no analyses yet",
    GRAPH_STATE_LABEL[f.graph_state] ?? f.graph_state,
    f.sessions_with_archived_text
      ? `full text for ${f.sessions_with_archived_text}`
      : "turn previews only",
  ];
  return (
    <p className="text-xs text-slate-500">
      Answers come from <span className="font-mono">{info.judge.spec}</span> (
      {info.judge.source === "settings" ? "Settings" : "packaged default"}
      {" · "}
      <Link href="/settings" className="text-blue-700 hover:underline">
        change
      </Link>
      ). It can see: {parts.join(" · ")}.
    </p>
  );
}

function ExchangeView({ x, onStop }: { x: Exchange; onStop: () => void }) {
  const ids = linkedSessions(x);
  return (
    <div className="space-y-2">
      <div className="flex justify-end">
        <div className="bg-blue-600 text-white text-sm rounded-2xl rounded-br-sm px-4 py-2 max-w-2xl whitespace-pre-wrap">
          {x.question}
        </div>
      </div>
      <Card>
        {x.steps.length > 0 && (
          <ol className="text-xs text-slate-600 space-y-1 mb-3">
            {x.steps.map((s) => (
              <li key={s.n} className="flex gap-2">
                <span className="text-slate-400 tabular-nums w-4 shrink-0">
                  {s.n}.
                </span>
                <div className="min-w-0">
                  <div className={s.error ? "text-rose-700" : ""}>
                    <span className="font-mono">{stepLine(s)}</span>
                  </div>
                  {argsLine(s.args) && (
                    <div
                      className="font-mono text-slate-500 truncate"
                      title={argsLine(s.args)}
                    >
                      {argsLine(s.args)}
                    </div>
                  )}
                  {s.why && (
                    <div className="text-slate-500 italic">{s.why}</div>
                  )}
                  {s.resultText !== undefined && (
                    <details className="mt-1">
                      <summary className="cursor-pointer text-slate-500 hover:text-slate-700">
                        Result — what the judge was given
                        {s.chars ? ` (${s.chars.toLocaleString()} chars` : ""}
                        {s.truncated ? ", cut to fit)" : s.chars ? ")" : ""}
                        {s.lookupSeconds !== undefined
                          ? ` · lookup ${s.lookupSeconds.toFixed(2)} s`
                          : ""}
                      </summary>
                      <pre className="mt-1 max-h-72 overflow-auto rounded bg-slate-50 border border-slate-200 p-2 text-[11px] whitespace-pre-wrap break-all">
                        {s.resultText}
                      </pre>
                    </details>
                  )}
                </div>
              </li>
            ))}
          </ol>
        )}
        {x.running && (
          <p className="text-sm text-slate-500 flex items-center gap-2">
            <span className="inline-block w-3 h-3 rounded-full border-2 border-blue-600 border-t-transparent animate-spin" />
            {x.steps.length === 0
              ? "Reading the question…"
              : x.steps[x.steps.length - 1].summary === undefined
                ? `Looking up ${x.steps[x.steps.length - 1].tool}…`
                : "Deciding what to do next…"}
            <button
              type="button"
              onClick={onStop}
              className="text-blue-700 hover:underline"
            >
              stop
            </button>
          </p>
        )}
        {x.stopped && (
          <p className="text-sm text-slate-500">
            Stopped listening. A lookup the judge was already working on
            finishes on its own; nothing is written.
          </p>
        )}
        {x.error && (
          <div className="text-sm bg-rose-50 border border-rose-200 text-rose-800 rounded p-2">
            {x.error}
            {x.prerequisite === "judge" && (
              <span className="block text-xs mt-1">
                Configure the judge LLM in{" "}
                <Link
                  href="/settings"
                  className="text-blue-700 hover:underline"
                >
                  Settings
                </Link>{" "}
                and use Test judge LLM there.
              </span>
            )}
          </div>
        )}
        {x.answer !== null && (
          <div className="text-sm text-slate-800">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={ANSWER_COMPONENTS}
            >
              {linkSessionRefs(x.answer, ids)}
            </ReactMarkdown>
          </div>
        )}
        {x.answer !== null && (ids.length > 0 || x.unverified.length > 0) && (
          <div className="flex flex-wrap gap-1 mt-3 text-xs items-center">
            <span className="text-slate-500 mr-1">Sessions used:</span>
            {ids.map((id) => (
              <Link
                key={id}
                href={`/sessions/${id}`}
                className={`rounded-full px-2 py-0.5 border ${
                  x.sessions.includes(id)
                    ? "border-blue-300 bg-blue-50 text-blue-800"
                    : "border-slate-200 bg-slate-50 text-slate-600"
                }`}
                title={
                  x.sessions.includes(id)
                    ? "cited in the answer"
                    : "returned by a lookup"
                }
              >
                #{id}
              </Link>
            ))}
            {x.unverified.map((id) => (
              <span
                key={`u${id}`}
                className="rounded-full px-2 py-0.5 border border-dashed border-rose-300 bg-rose-50 text-rose-700"
                title="The answer names this session, but no lookup returned it — treat it as unverified."
              >
                #{id} unverified
              </span>
            ))}
          </div>
        )}
        {x.answer !== null && x.judge && (
          <p className="text-[11px] text-slate-400 mt-2">
            Answered by {x.judge} after {x.steps.length} lookup
            {x.steps.length === 1 ? "" : "s"}.
          </p>
        )}
      </Card>
    </div>
  );
}

// The answer's Markdown, styled like Learn's documents (no typography
// plugin here); session links stay in-app.
const ANSWER_COMPONENTS: Components = {
  h1: ({ children }) => <h3 className="text-base font-semibold mt-3 mb-1">{children}</h3>,
  h2: ({ children }) => <h3 className="text-base font-semibold mt-3 mb-1">{children}</h3>,
  h3: ({ children }) => <h4 className="text-sm font-semibold mt-2 mb-1">{children}</h4>,
  p: ({ children }) => <p className="my-2 leading-relaxed">{children}</p>,
  ul: ({ children }) => <ul className="list-disc pl-6 my-2 space-y-1">{children}</ul>,
  ol: ({ children }) => <ol className="list-decimal pl-6 my-2 space-y-1">{children}</ol>,
  code: ({ children }) => (
    <code className="bg-slate-100 rounded px-1 py-0.5 text-[0.9em]">{children}</code>
  ),
  pre: ({ children }) => (
    <pre className="bg-slate-900 text-slate-100 rounded p-3 my-2 overflow-x-auto text-xs">
      {children}
    </pre>
  ),
  table: ({ children }) => (
    <div className="overflow-x-auto my-3">
      <table className="w-full text-sm border-collapse">{children}</table>
    </div>
  ),
  th: ({ children }) => (
    <th className="text-left border-b border-slate-300 px-2 py-1 bg-slate-50 font-semibold">
      {children}
    </th>
  ),
  td: ({ children }) => <td className="border-b border-slate-100 px-2 py-1 align-top">{children}</td>,
  a: ({ href, children }) =>
    href && href.startsWith("/") ? (
      <Link href={href} className="text-blue-700 hover:underline">
        {children}
      </Link>
    ) : (
      <a href={href} className="text-blue-700 hover:underline" target="_blank" rel="noreferrer">
        {children}
      </a>
    ),
};
