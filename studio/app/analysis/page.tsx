"use client";

import { useCallback, useEffect, useState } from "react";
import { api, JudgeModels, PipelineStatus, PipelineStep } from "@/lib/api";
import { Card, Stat, formatCost, useApi } from "@/components/ui";

// THE PIPELINE AS A FLOW, not a list of cards.
//
// Two earlier versions failed differently. The first listed five shell
// commands with a button on one of them, so most of the page was
// copy-paste homework. The second gave every step a Run button but still
// rendered them as four equal cards — operable, yet nothing showed how
// the data MOVES, so it read as four unrelated chores.
//
// This version is a stepper you can read at a glance, a funnel of counts
// underneath it, and one step in focus. The funnel is the important
// part: it shows WHERE RECORDS STOP, which is the question an analysis
// pipeline exists to answer and the thing neither previous version said.

const POLL_MS = 2000;

/** Where you are, what is finished, what is left. */
function Stepper({
  steps,
  current,
  onSelect,
}: {
  steps: PipelineStep[];
  current: number;
  onSelect: (i: number) => void;
}) {
  return (
    <div className="flex items-center gap-1 overflow-x-auto pb-1">
      {steps.map((s, i) => {
        const running = s.job.state === "running";
        const failed = s.job.state === "failed";
        return (
          <div key={s.id} className="flex items-center shrink-0">
            <button
              onClick={() => onSelect(i)}
              className="flex items-center gap-2 px-1 group"
              aria-current={i === current ? "step" : undefined}
            >
              <span
                className={
                  "w-7 h-7 rounded-full flex items-center justify-center text-xs shrink-0 border-2 " +
                  (failed
                    ? "bg-rose-500 border-rose-500 text-white"
                    : s.done
                      ? "bg-emerald-500 border-emerald-500 text-white"
                      : running
                        ? "bg-white border-blue-500 text-blue-600 animate-pulse"
                        : i === current
                          ? "bg-white border-blue-500 text-blue-600"
                          : "bg-white border-slate-300 text-slate-400")
                }
              >
                {s.done && !running ? "✓" : i + 1}
              </span>
              <span
                className={
                  "text-sm text-left leading-tight max-w-[8rem] " +
                  (i === current
                    ? "text-slate-900 font-medium"
                    : "text-slate-500 group-hover:text-slate-700")
                }
              >
                {s.title}
              </span>
            </button>
            {i < steps.length - 1 && (
              <span className="w-8 h-px bg-slate-300 mx-1 shrink-0" />
            )}
          </div>
        );
      })}
    </div>
  );
}

/** How many records survive each stage — and where they stop. */
function Funnel({ counts }: { counts: PipelineStatus["counts"] }) {
  const cells = [
    { label: "Sessions", value: counts.sessions },
    { label: "Graph nodes", value: counts.graph_nodes },
    { label: "Labelled turns", value: counts.labels },
    { label: "KPI rows", value: counts.kpis },
  ];
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
      {cells.map((c, i) => (
        <span key={c.label} className="flex items-center gap-1">
          <span className="text-slate-500">{c.label}:</span>
          {/* Zero is the INTERESTING value — it marks where the pipeline
              stopped — so it is coloured rather than blending in with
              the stages that succeeded. */}
          <span
            className={
              "font-semibold tabular-nums " +
              (c.value > 0 ? "text-slate-800" : "text-amber-600")
            }
          >
            {c.value.toLocaleString()}
          </span>
          {i < cells.length - 1 && (
            <span className="text-slate-300 ml-2">→</span>
          )}
        </span>
      ))}
      {counts.label_failures > 0 && (
        // Attempts that produced no label are not a footnote — they are
        // the reason the next stage has nothing to work with.
        <span className="text-rose-700">
          ({counts.label_failures.toLocaleString()} judge attempts failed)
        </span>
      )}
    </div>
  );
}

export default function AnalysisPage() {
  const [status, setStatus] = useState<PipelineStatus | null>(null);
  const [current, setCurrent] = useState(0);
  const [judge, setJudge] = useState("");
  const [limit, setLimit] = useState(50);
  const [judgeRunning, setJudgeRunning] = useState(false);
  // Real installed models, not a guess. A hardcoded "ollama:llama3"
  // silently 404'd on a machine that had llama3.2 instead.
  const [models, setModels] = useState<JudgeModels | null>(null);
  const [note, setNote] = useState<string | null>(null);
  // Opt-in, never implied: the judge costs money per turn, so a
  // "run everything" button must not spend it without being asked.
  const [includeJudge, setIncludeJudge] = useState(false);
  const { data: kpis } = useApi(() => api.dashboard());

  const refresh = useCallback(async () => {
    try {
      setStatus(await api.pipelineStatus());
    } catch {
      /* keep the last known state rather than blanking the page */
    }
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, POLL_MS);
    return () => clearInterval(id);
  }, [refresh]);

  useEffect(() => {
    api.judgeModels().then(setModels).catch(() => setModels(null));
  }, []);

  async function runAll() {
    setNote(null);
    try {
      await api.runAll(includeJudge);
      refresh();
    } catch (e) {
      setNote(String(e));
    }
  }

  async function run(step: string) {
    setNote(null);
    try {
      await api.runStep(step);
      refresh();
    } catch (e) {
      setNote(String(e));
    }
  }

  async function runJudge() {
    setJudgeRunning(true);
    setNote(null);
    try {
      const r = await api.analyze({ judge: judge || undefined, limit });
      // A WRITTEN ROW IS NOT A LABEL. The runner reports parse_ok and
      // parse_failed separately; reporting only the row count turned 50
      // backend errors into "Labelled 50 turns" with a green check.
      const per = r.by_copilot
        ? Object.values(r.by_copilot as Record<string, any>)
        : [r as any];
      const ok = per.reduce((n, s) => n + (s.parse_ok ?? 0), 0);
      const failed = per.reduce((n, s) => n + (s.parse_failed ?? 0), 0);
      if (ok === 0 && failed > 0) {
        setNote(
          `✗ Nothing was labelled — all ${failed} attempts failed. ` +
            `The judge backend rejected every call (wrong model name, or ` +
            `the server is not reachable). Check Backend below.`,
        );
      } else {
        setNote(
          `Labelled ${ok} turns` +
            (failed > 0 ? ` · ${failed} failed` : "") +
            ".",
        );
      }
      refresh();
    } catch (e) {
      setNote(`${String(e)} — is the judge backend reachable?`);
    } finally {
      setJudgeRunning(false);
    }
  }

  if (!status)
    return <div className="text-slate-400 text-sm py-8">Loading…</div>;

  const step = status.steps[current];
  const running =
    step.job.state === "running" || (step.id === "judge" && judgeRunning);
  const isLast = current === status.steps.length - 1;
  const allRunning = status.all?.state === "running";

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <h1 className="text-2xl font-bold">Analysis pipeline</h1>
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-1.5 text-sm text-slate-600">
            <input
              type="checkbox"
              checked={includeJudge}
              onChange={(e) => setIncludeJudge(e.target.checked)}
              className="accent-blue-600"
            />
            include LLM judge
          </label>
          <button
            onClick={runAll}
            disabled={allRunning}
            className="bg-blue-600 text-white text-sm px-4 py-1.5 rounded hover:bg-blue-700 disabled:opacity-50"
          >
            {allRunning ? "Running all…" : "Run all steps"}
          </button>
        </div>
      </div>

      <Card>
        <Stepper steps={status.steps} current={current} onSelect={setCurrent} />
        <div className="mt-3 pt-3 border-t border-slate-100">
          <Funnel counts={status.counts} />
        </div>
      </Card>

      {kpis && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <Stat label="Sessions" value={kpis.totals.sessions} />
          <Stat label="Turns" value={kpis.totals.turns} />
          <Stat
            label="Total cost (USD)"
            value={formatCost(kpis.totals.total_cost_usd)}
            note="priced turns only — unpriced turns are excluded, not zeroed"
          />
          <Stat
            label="Cost / session"
            value={formatCost(kpis.totals.cost_per_session)}
            note={
              `over ${kpis.totals.priced_sessions.toLocaleString()} of ` +
              `${kpis.totals.sessions.toLocaleString()} sessions with priced turns`
            }
          />
        </div>
      )}

      <Card>
        <div className="flex items-center gap-2 flex-wrap">
          <h2 className="font-semibold text-slate-800">
            Step {current + 1} — {step.title}
          </h2>
          {step.done && !running && (
            <span className="text-xs px-2 py-0.5 rounded bg-emerald-100 text-emerald-800">
              done
            </span>
          )}
          {running && (
            <span className="text-xs px-2 py-0.5 rounded bg-blue-100 text-blue-800">
              running…
            </span>
          )}
          {step.job.state === "failed" && (
            <span className="text-xs px-2 py-0.5 rounded bg-rose-100 text-rose-800">
              failed
            </span>
          )}
          {step.optional && (
            <span className="text-xs text-slate-400">optional</span>
          )}
        </div>

        <p className="text-sm text-slate-600 mt-1">{step.blurb}</p>

        {step.id === "graph" && (
          <p className="text-xs text-amber-700 mt-2">
            ⏱ This step can take a long time on a large store.
          </p>
        )}

        {step.id === "judge" && (
          // The cost warning belongs HERE, at the moment of the decision
          // — not in documentation the user has already walked past.
          <div className="text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded p-2 mt-2">
            ⚠ Judging calls a model for <em>every turn</em> and can consume
            significant credits on a large batch. A local backend (Ollama) keeps
            it free and on this machine — switch it in Settings → LLM-as-Judge.
          </div>
        )}

        {step.id === "graph" && running && (
          <p className="text-xs text-blue-700 mt-2">
            {status.counts.graph_nodes.toLocaleString()} nodes written so far
            {step.job.seconds
              ? ` · ${Math.round(step.job.seconds)}s elapsed`
              : ""}
          </p>
        )}

        {step.job.message && (
          <p
            className={
              "text-xs mt-2 " +
              (step.job.state === "failed" ? "text-rose-700" : "text-slate-600")
            }
          >
            {step.job.message}
            {step.job.seconds ? ` (${step.job.seconds}s)` : ""}
          </p>
        )}

        {step.id === "judge" && (
          <div className="flex items-center gap-2 mt-3 flex-wrap">
            <label className="text-xs text-slate-500">Backend</label>
            <select
              value={judge}
              onChange={(e) => setJudge(e.target.value)}
              className="border border-slate-300 bg-white text-slate-900 rounded px-2 py-1 text-sm"
            >
              <option value="">Each copilot&apos;s own LLM</option>
              {models?.models.map((m) => (
                <option key={m} value={`ollama:${m}`}>
                  ollama:{m}
                </option>
              ))}
            </select>
            {models && !models.reachable && (
              <span className="text-xs text-rose-700">
                Ollama unreachable at {models.url} — only the copilot&apos;s own
                LLM is available.
              </span>
            )}
            <label className="text-xs text-slate-500">Turns</label>
            <input
              type="number"
              value={limit}
              onChange={(e) => setLimit(Number(e.target.value))}
              className="border border-slate-300 bg-white text-slate-900 rounded px-2 py-1 text-sm w-20"
            />
          </div>
        )}

        <div className="flex items-center gap-2 mt-4 flex-wrap">
          <button
            onClick={() => (step.id === "judge" ? runJudge() : run(step.id))}
            disabled={running}
            className="bg-slate-800 text-white text-sm px-4 py-1.5 rounded hover:bg-slate-700 disabled:opacity-50"
          >
            {running
              ? "Running…"
              : step.done
                ? `Re-run ${step.title.toLowerCase()}`
                : `Run ${step.title.toLowerCase()}`}
          </button>
          <button
            onClick={() => setCurrent(Math.max(0, current - 1))}
            disabled={current === 0}
            className="border border-slate-300 bg-white text-slate-700 text-sm px-3 py-1.5 rounded hover:bg-slate-50 disabled:opacity-40"
          >
            ← Back
          </button>
          <button
            onClick={() =>
              setCurrent(Math.min(status.steps.length - 1, current + 1))
            }
            disabled={isLast}
            className="border border-slate-300 bg-white text-slate-700 text-sm px-3 py-1.5 rounded hover:bg-slate-50 disabled:opacity-40"
          >
            Next →
          </button>
          {isLast && (
            <a
              href="/"
              className="ml-auto text-sm text-blue-700 hover:underline"
            >
              View dashboard →
            </a>
          )}
        </div>
      </Card>

      {status.all?.message && (
        <p
          className={
            "text-sm rounded p-2 border " +
            (status.all.state === "failed"
              ? "bg-rose-50 border-rose-200 text-rose-800"
              : "bg-slate-50 border-slate-200")
          }
        >
          Run all: {status.all.message}
          {status.all.seconds ? ` (${status.all.seconds}s)` : ""}
        </p>
      )}

      {note && (
        <p className="text-sm bg-slate-50 border border-slate-200 rounded p-2">
          {note}
        </p>
      )}
    </div>
  );
}
