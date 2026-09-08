"use client";

import { useCallback, useEffect, useState } from "react";
import {
  AgreementReport,
  DiscoveredSessions,
  JudgeRuns,
  LoadSelection,
  api,
  JudgeModels,
  PipelineStatus,
  PipelineStep,
} from "@/lib/api";
import { Card, Stat, formatCost, useApi } from "@/components/ui";
import JudgeQuality from "@/components/JudgeQuality";
import LoadSelectionPanel, { loadPlan } from "@/components/LoadSelection";
import JudgeProgressBar, { EmbedProgressBar, judgeChoiceLabel } from "@/components/JudgeProgress";

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
    {
      label: "Sessions",
      value: counts.sessions,
      // #307: the same count the Dashboard and Sessions page show, and
      // the same exclusion, said in the same words.
      note:
        counts.excluded_noise > 0
          ? `${counts.excluded_noise.toLocaleString()} excluded as noise`
          : null,
    },
    { label: "Graph nodes", value: counts.graph_nodes, note: null },
    { label: "Embedded", value: counts.embedded, note: null },
    { label: "Similarity links", value: counts.similar_edges, note: null },
    { label: "Labelled turns", value: counts.labels, note: null },
    { label: "KPI rows", value: counts.kpis, note: null },
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
          {c.note && <span className="text-xs text-slate-400">({c.note})</span>}
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
  const [limit, setLimit] = useState(50);
  // Real installed models, not a guess. A hardcoded "ollama:llama3"
  // silently 404'd on a machine that had llama3.2 instead.
  const [models, setModels] = useState<JudgeModels | null>(null);
  const [note, setNote] = useState<string | null>(null);
  // Opt-in, never implied: the judge costs money per turn, so a
  // "run everything" button must not spend it without being asked.
  const [includeJudge, setIncludeJudge] = useState(false);
  const { data: kpis } = useApi(() => api.dashboard());
  // #313 judge validation: named runs + the agreement card.
  const [runName, setRunName] = useState("");
  const [onlyLabelledBy, setOnlyLabelledBy] = useState("");
  const [runs, setRuns] = useState<JudgeRuns | null>(null);
  const [runsError, setRunsError] = useState<string | null>(null);
  const [cmp, setCmp] = useState<{ a: string; b: string }>({ a: "", b: "" });
  const [report, setReport] = useState<AgreementReport | null>(null);
  const [reportError, setReportError] = useState<string | null>(null);
  // Which sessions to load: the listing under the filters, the filters,
  // and an explicit pick. The pick wins; otherwise "every new session
  // under the filters" — see LoadSelection.loadPlan.
  const [listing, setListing] = useState<DiscoveredSessions | null>(null);
  const [listingError, setListingError] = useState<string | null>(null);
  const [since, setSince] = useState("");
  const [loadLimit, setLoadLimit] = useState("");
  const [picked, setPicked] = useState<Set<string>>(new Set());

  const loadListing = useCallback(async () => {
    try {
      const r = await api.pipelineSessions({
        since: since || undefined,
        limit: Number(loadLimit) > 0 ? Number(loadLimit) : undefined,
      });
      setListing(r);
      setListingError(null);
      // A pick that the new filters no longer show is dropped, so the
      // button never loads something the table does not display.
      setPicked((p) => new Set([...p].filter((id) => r.sessions.some((s) => s.session_id === id))));
    } catch (e) {
      setListingError(String(e));
    }
  }, [since, loadLimit]);

  const loadRuns = useCallback(async () => {
    try {
      const r = await api.judgeRuns();
      setRuns(r);
      setRunsError(null);
      const sources = [...r.rubrics.map((x) => x.source), ...r.humans.map((x) => x.source)];
      setCmp((c) => ({
        a: sources.includes(c.a) ? c.a : sources[0] ?? "",
        b: sources.includes(c.b) && c.b !== (sources.includes(c.a) ? c.a : sources[0]) ? c.b : sources[1] ?? "",
      }));
    } catch (e) {
      setRunsError(String(e));
    }
  }, []);
  useEffect(() => {
    loadRuns();
  }, [loadRuns]);
  useEffect(() => {
    if (!cmp.a || !cmp.b) return;
    let live = true;
    setReport(null);
    api
      .judgeAgreement(cmp.a, cmp.b)
      .then((r) => live && (setReport(r), setReportError(null)))
      .catch((e) => live && setReportError(String(e)));
    return () => {
      live = false;
    };
  }, [cmp]);

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

  useEffect(() => {
    loadListing();
  }, [loadListing]);

  // When a load finishes, the listing's loaded/new column is stale and
  // the pick has been served: clear it so the button falls back to
  // "Load N new" rather than offering the same sessions again.
  const ingestState = status?.steps[0]?.job.state;
  useEffect(() => {
    if (ingestState === "done") {
      setPicked(new Set());
      loadListing();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ingestState]);

  const plan = loadPlan(listing, picked, since, loadLimit);
  // The judge is the one configured in Settings — the only place it is
  // chosen. These are run options, not a second configuration.
  const judgeOpts = {
    limit,
    rubric_name: runName.trim() || undefined,
    only_labelled_by: onlyLabelledBy || undefined,
  };

  async function runAll() {
    setNote(null);
    try {
      // The same selection the Load step shows: "run all" must not
      // quietly read every transcript the user just narrowed away; and
      // the judge, when included, runs with the choices made below.
      await api.runAll(includeJudge, { load: plan.body, judge: judgeOpts });
      refresh();
    } catch (e) {
      setNote(String(e));
    }
  }

  async function run(step: string, load?: LoadSelection) {
    setNote(null);
    try {
      await api.runStep(step, { load, judge: judgeOpts });
      refresh();
    } catch (e) {
      setNote(String(e));
    }
  }

  // The judge is a background job like the other steps (it used to run
  // inside one request with nothing to show until it returned). When it
  // finishes, the runs list for the quality card is stale.
  const judgeState = status?.steps[2]?.job.state;
  useEffect(() => {
    if (judgeState === "done") loadRuns();
  }, [judgeState, loadRuns]);

  if (!status)
    return <div className="text-slate-400 text-sm py-8">Loading…</div>;

  const step = status.steps[current];
  const running = step.job.state === "running";
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
        </div>

        <p className="text-sm text-slate-600 mt-1">{step.blurb}</p>

        {step.id === "ingest" && (
          <LoadSelectionPanel
            listing={listing}
            error={listingError}
            since={since}
            limit={loadLimit}
            picked={picked}
            running={running}
            onSince={setSince}
            onLimit={setLoadLimit}
            onTogglePick={(id) =>
              setPicked((p) => {
                const n = new Set(p);
                if (n.has(id)) n.delete(id);
                else n.add(id);
                return n;
              })
            }
            onPickNew={() =>
              setPicked(
                new Set((listing?.sessions ?? []).filter((s) => !s.loaded).map((s) => s.session_id)),
              )
            }
            onClearPicks={() => setPicked(new Set())}
            onLoad={(body) => run("ingest", body)}
          />
        )}

        {step.id === "graph" && (
          <p className="text-xs text-amber-700 mt-2">
            ⏱ This step can take a long time on a large store.
          </p>
        )}

        {step.id === "judge" && (
          // The judge is CONFIGURED under Settings, and only there. This
          // says which one will run and links to where it is changed —
          // it is not a second place to pick one.
          <p className="text-sm mt-2">
            <span className="text-slate-500">Judge:</span>{" "}
            <span className="font-mono text-slate-800">{judgeChoiceLabel(models?.configured)}</span>
            {" · "}
            <a href="/settings" className="text-blue-700 hover:underline">
              change in Settings
            </a>
            {models && models.backend !== "claude-code" && models.url && !models.reachable && (
              <span className="text-rose-700"> · not reachable at {models.url}</span>
            )}
          </p>
        )}

        {step.id === "judge" && (
          // The cost warning belongs HERE, at the moment of the decision
          // — not in documentation the user has already walked past.
          <div className="text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded p-2 mt-2">
            ⚠ Judging calls the model once for <em>every turn</em>; a hosted
            backend can consume significant credits on a large batch. A local
            backend (Ollama, or vLLM on your own hardware) keeps it free.
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

        {step.id === "judge" && step.job.progress && "labeled" in step.job.progress && (
          <JudgeProgressBar
            progress={step.job.progress}
            seconds={step.job.seconds}
            running={running}
          />
        )}
        {step.id === "embed" && step.job.progress && "embedded" in step.job.progress && (
          <EmbedProgressBar
            progress={step.job.progress}
            seconds={step.job.seconds}
            running={running}
          />
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
            <label className="text-xs text-slate-500">Turns</label>
            <input
              type="number"
              value={limit}
              onChange={(e) => setLimit(Number(e.target.value))}
              className="border border-slate-300 bg-white text-slate-900 rounded px-2 py-1 text-sm w-20"
            />
            {/* #313: a run name keeps this run apart from the packaged
                one; "only turns labelled by" makes it cover the same
                turns so the two can be compared below. */}
            <label className="text-xs text-slate-500">Run name</label>
            <input
              type="text"
              value={runName}
              placeholder="heuristic-v1"
              onChange={(e) => setRunName(e.target.value)}
              className="border border-slate-300 bg-white text-slate-900 rounded px-2 py-1 text-sm w-36"
              title="Write labels under this rubric name; blank = the packaged rubric"
            />
            <label className="text-xs text-slate-500">Only turns labelled by</label>
            <select
              value={onlyLabelledBy}
              onChange={(e) => setOnlyLabelledBy(e.target.value)}
              className="border border-slate-300 bg-white text-slate-900 rounded px-2 py-1 text-sm"
            >
              <option value="">any unlabelled turn</option>
              {runs?.rubrics.map((r) => (
                <option key={r.source} value={r.source}>run {r.name}</option>
              ))}
              {runs?.humans.map((h) => (
                <option key={h.source} value={h.source}>human {h.labeler}</option>
              ))}
            </select>
          </div>
        )}

        <div className="flex items-center gap-2 mt-4 flex-wrap">
          {step.id !== "ingest" && (
            <button
              onClick={() => run(step.id)}
              disabled={running}
              className="bg-slate-800 text-white text-sm px-4 py-1.5 rounded hover:bg-slate-700 disabled:opacity-50"
            >
              {running
                ? "Running…"
                : step.done
                  ? `Re-run ${step.title.toLowerCase()}`
                  : `Run ${step.title.toLowerCase()}`}
            </button>
          )}
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

      {step.id === "judge" && (
        <JudgeQuality
          runs={runs}
          report={report}
          a={cmp.a}
          b={cmp.b}
          onSelect={(a, b) => setCmp({ a, b })}
          error={runsError || reportError}
        />
      )}
    </div>
  );
}
