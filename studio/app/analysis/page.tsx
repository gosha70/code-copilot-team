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
import { correlateProgressLine } from "@/lib/benchmarkIntro";
import { isPrivateUrl } from "@/lib/urls";
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

/** The analysis goal, in order. KPI computation is a goal step, not
 *  plumbing: it writes session_kpi, which the Overview's harness
 *  aggregates read — without it the judge's new labels never reach the
 *  front page. Everything else here is feature plumbing (benchmark
 *  linking, embeddings, similarity) — see OPTIONAL_STEP_IDS. */
const CORE_STEP_IDS = ["ingest", "graph", "judge", "kpis"];
const OPTIONAL_STEP_IDS = ["correlate", "embed", "similar"];

/** Where you are, what is finished, what is left. */
function Stepper({
  steps,
  currentId,
  onSelect,
}: {
  steps: PipelineStep[];
  currentId: string;
  onSelect: (id: string) => void;
}) {
  return (
    <div className="flex items-center gap-1 overflow-x-auto pb-1">
      {steps.map((s, i) => {
        const running = s.job.state === "running";
        const failed = s.job.state === "failed";
        const active = s.id === currentId;
        return (
          <div key={s.id} className="flex items-center shrink-0">
            <button
              onClick={() => onSelect(s.id)}
              className="flex items-center gap-2 px-1 group"
              aria-current={active ? "step" : undefined}
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
                        : active
                          ? "bg-white border-blue-500 text-blue-600"
                          : "bg-white border-slate-300 text-slate-500")
                }
              >
                {s.done && !running ? "✓" : i + 1}
              </span>
              <span
                className={
                  "text-sm text-left leading-tight max-w-[8rem] " +
                  (active
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
    // Only the goal steps are chained here. Embedded / Similarity links
    // belong to optional processing: they come from different stores (the
    // session rows vs the Kùzu graph), so a chain across them can read as
    // an impossible story when one was cleared and the other was not.
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
          {c.note && <span className="text-xs text-slate-500">({c.note})</span>}
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
  // The judge costs money per turn, so a whole-store run never includes
  // it unless asked. With an explicit selection it IS the analysis the
  // user asked for, so the box starts checked; it can be unticked.
  const [judgeChoice, setJudgeChoice] = useState<boolean | null>(null);
  // Optional processing (benchmark linking, embeddings, similarity, KPI
  // rollups) stays out of the goal flow unless the user opens it.
  const [showOptional, setShowOptional] = useState(false);
  // The funnel reads `status` (polled); the tiles read the dashboard.
  // Key the tile fetch to the funnel's numbers and step states, so the
  // two cannot show different session counts for one store after a load.
  const statusKey = status
    ? [
        status.counts.sessions,
        status.counts.graph_nodes,
        status.counts.labels,
        status.counts.kpis,
        ...status.steps.map((s) => s.job.state),
      ].join("|")
    : "";
  const { data: kpis } = useApi(() => api.dashboard(), [statusKey]);
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
  // Effective opt-in: an explicit tick/untick wins; otherwise the judge
  // follows the selection (on when sessions are picked, off for the
  // whole store).
  const includeJudge = judgeChoice ?? picked.size > 0;

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

  // When a load finishes, refresh the listing so the state column shows
  // the sessions as loaded. The pick is KEPT on purpose: the same
  // selection then scopes the analysis ("Run all steps · N selected"),
  // which is the point of choosing sessions before reading them.
  // Steps are found BY ID: an index breaks the moment a step is added
  // (and the judge index was already wrong — it pointed at embed).
  const ingestState = status?.steps.find((s) => s.id === "ingest")?.job.state;
  useEffect(() => {
    if (ingestState === "done") {
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
      await api.runAll(includeJudge, {
        load: plan.body,
        judge: judgeOpts,
        sessions: picked.size ? [...picked] : undefined,
      });
      refresh();
    } catch (e) {
      setNote(String(e));
    }
  }

  async function run(step: string, load?: LoadSelection) {
    setNote(null);
    try {
      await api.runStep(step, {
        load,
        judge: judgeOpts,
        sessions: picked.size ? [...picked] : undefined,
      });
      refresh();
    } catch (e) {
      setNote(String(e));
    }
  }

  // The judge is a background job like the other steps (it used to run
  // inside one request with nothing to show until it returned). When it
  // finishes, the runs list for the quality card is stale.
  const judgeState = status?.steps.find((s) => s.id === "judge")?.job.state;
  useEffect(() => {
    if (judgeState === "done") loadRuns();
  }, [judgeState, loadRuns]);

  if (!status)
    return <div className="text-slate-500 text-sm py-8">Loading…</div>;

  const step = status.steps[current];
  // What Run all will analyse after its load: the store it already has,
  // plus the sessions this run will read (the selection, else every new
  // session under the filters).
  const analysisCount = status.counts.sessions + (listing ? plan.count : 0);
  // The judge turn cap is PER SELECTED SESSION (whole-store runs keep a
  // single total), so the most a run can judge is the product — the
  // number that decides cost on a hosted judge.
  const turnsPerRun = Number.isFinite(limit) && limit > 0 ? Math.floor(limit) : 0;
  const turnsNote =
    picked.size > 0
      ? `up to ${(turnsPerRun * picked.size).toLocaleString()} turns across ${picked.size.toLocaleString()} selected session${picked.size === 1 ? "" : "s"}`
      : `up to ${turnsPerRun.toLocaleString()} turns in this run`;
  // Off this network? The same rule as Settings: claude-code always is;
  // an openai-compatible judge counts as external unless its base URL is
  // a private address (a LAN vLLM box is as local as Ollama).
  const cloudJudgeNow =
    !!models &&
    (models.backend === "claude-code" ||
      (models.backend === "openai" &&
        models.url.startsWith("http") &&
        !isPrivateUrl(models.url)));
  const coreSteps = status.steps.filter((s) => CORE_STEP_IDS.includes(s.id));
  const optionalSteps = status.steps.filter((s) =>
    OPTIONAL_STEP_IDS.includes(s.id),
  );
  const coreIndex = coreSteps.findIndex((s) => s.id === step.id);
  const prevStep =
    coreIndex > 0
      ? coreSteps[coreIndex - 1]
      : coreIndex === -1
        ? coreSteps[coreSteps.length - 1]
        : null;
  const nextStep =
    coreIndex >= 0 && coreIndex < coreSteps.length - 1
      ? coreSteps[coreIndex + 1]
      : null;
  const running = step.job.state === "running";
  const isLast = coreIndex === -1 || coreIndex === coreSteps.length - 1;
  const allRunning = status.all?.state === "running";
  const goToStep = (id: string) =>
    setCurrent(status.steps.findIndex((s) => s.id === id));

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-bold">Analysis pipeline</h1>
      </div>

      <Card>
        <Stepper
          steps={coreSteps}
          currentId={step.id}
          onSelect={goToStep}
        />
        {optionalSteps.length > 0 && (
          <div className="mt-2">
            <button
              type="button"
              onClick={() => setShowOptional((v) => !v)}
              aria-expanded={showOptional}
              className="text-xs text-slate-500 hover:text-slate-700"
            >
              {showOptional
                ? "Hide optional processing"
                : `Optional processing (${optionalSteps.length})`}
            </button>
            {showOptional && (
              <div className="mt-2 flex flex-wrap items-center gap-2">
                {optionalSteps.map((s) => (
                  <button
                    key={s.id}
                    type="button"
                    onClick={() => goToStep(s.id)}
                    aria-current={s.id === step.id ? "step" : undefined}
                    title={s.blurb}
                    className={
                      "text-xs rounded-full border px-3 py-1 " +
                      (s.id === step.id
                        ? "border-blue-500 bg-blue-50 text-blue-700"
                        : s.job.state === "failed"
                          ? "border-rose-300 bg-rose-50 text-rose-700"
                          : s.done
                            ? "border-emerald-300 bg-emerald-50 text-emerald-800"
                            : "border-slate-300 bg-white text-slate-600 hover:bg-slate-50")
                    }
                  >
                    {s.title}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
        <div className="mt-3 pt-3 border-t border-slate-100">
          <Funnel counts={status.counts} />
          <p className="mt-1 text-xs text-slate-500">
            {picked.size > 0
              ? `Analysis will run on the ${picked.size} selected session${picked.size === 1 ? "" : "s"}; the graph step still rebuilds the whole store, and optional processing is skipped.`
              : `Analysis runs over the whole loaded store${
                  status.store_reachable
                    ? ` (${status.counts.sessions.toLocaleString()} sessions)`
                    : ""
                }.`}
          </p>
        </div>
      </Card>

      <Card>
        <div className="flex items-center gap-2 flex-wrap">
          <h2 className="font-semibold text-slate-800">
            {coreIndex >= 0
              ? `Step ${coreIndex + 1} — ${step.title}`
              : step.title}
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
          {step.job.state === "done" && step.job.skipped && (
            <span
              className="text-xs px-2 py-0.5 rounded bg-amber-100 text-amber-800"
              title={step.job.message}
            >
              skipped
            </span>
          )}
          {step.job.state === "failed" && step.id !== "ingest" && (
            <button
              type="button"
              onClick={() => run(step.id)}
              disabled={running}
              className="bg-rose-600 text-white text-xs px-3 py-1 rounded hover:bg-rose-700 disabled:opacity-50"
            >
              Retry this step
            </button>
          )}
        </div>

        <p className="text-xs text-slate-500 mt-2">
          Run all runs the flow steps and the optional ones: Load sessions → Link
          benchmark runs → Build knowledge graph → Embed sessions → Find similar
          sessions → LLM judge → Compute KPIs. It loads the current selection
          first, then analyses the selected sessions (or every loaded session
          when nothing is selected); with a selection, optional processing is
          skipped. The LLM judge and Compute KPIs run only when the judge is
          checked — 5 steps unchecked, 7 checked; with sessions selected the
          judge is checked for you. With a selection, the Turns cap applies to
          each selected session, so every one gets judged.
        </p>

        <p className="text-sm text-slate-600 mt-2">{step.blurb}</p>

        {step.id === "ingest" && (
          <LoadSelectionPanel
            listing={listing}
            error={listingError}
            status={
              step.job.message
                ? {
                    text:
                      step.job.message +
                      (step.job.seconds ? ` (${step.job.seconds}s)` : ""),
                    failed: step.job.state === "failed",
                  }
                : null
            }
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
        {step.id === "correlate" && step.job.progress && "scanned" in step.job.progress && (
          <p
            className={`text-xs mt-2 tabular-nums ${
              step.job.state === "failed" ? "text-rose-700" : "text-slate-600"
            }`}
          >
            {correlateProgressLine(step.job.progress, step.job.state, running ? step.job.seconds : undefined)}
          </p>
        )}
        {step.id === "embed" && step.job.progress && "embedded" in step.job.progress && (
          <EmbedProgressBar
            progress={step.job.progress}
            seconds={step.job.seconds}
            running={running}
          />
        )}

        {step.job.message && step.id !== "ingest" && (
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
            <label className="text-xs text-slate-500">
              {picked.size > 0 ? "Turns per session" : "Turns"}
            </label>
            <input
              type="number"
              value={limit}
              onChange={(e) => setLimit(Number(e.target.value))}
              className="border border-slate-300 bg-white text-slate-900 rounded px-2 py-1 text-sm w-20"
            />
            <span className="text-xs text-slate-500">{turnsNote}</span>
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
          <button
            onClick={runAll}
            disabled={allRunning}
            title={
              "Load sessions -> Link benchmark runs -> Build knowledge graph " +
              "-> Embed sessions -> Find similar sessions -> LLM judge -> " +
              "Compute KPIs. The judge and the KPI rollup run only when the " +
              "judge is checked: 5 steps unchecked, 7 checked. With sessions " +
              "selected the judge is checked for you."
            }
            className="bg-blue-600 text-white text-sm px-4 py-1.5 rounded hover:bg-blue-700 disabled:opacity-50"
          >
            {allRunning
              ? "Running all…"
              : includeJudge
                ? picked.size > 0
                  ? `Run all steps · ${picked.size} selected`
                  : `Run all steps · ${analysisCount.toLocaleString()} sessions`
                : picked.size > 0
                  ? `Run without the judge · ${picked.size} selected`
                  : `Run without the judge · ${analysisCount.toLocaleString()} sessions`}
          </button>
          <label className="flex items-center gap-1.5 text-sm text-slate-600 mr-2">
            <input
              type="checkbox"
              checked={includeJudge}
              onChange={(e) => setJudgeChoice(e.target.checked)}
              className="accent-blue-600"
            />
            include LLM judge
          </label>
          {includeJudge && cloudJudgeNow && (
            <span className="text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded px-2 py-1">
              ⚠ This judge
              {models?.configured.spec ? ` (${models.configured.spec})` : ""} is off
              your network: turn previews and steering-file excerpts go to it.
              Choose a judge on this machine or your LAN for a fully-local run.
            </span>
          )}
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
            onClick={() => prevStep && goToStep(prevStep.id)}
            disabled={!prevStep}
            className="border border-slate-300 bg-white text-slate-700 text-sm px-3 py-1.5 rounded hover:bg-slate-50 disabled:opacity-40"
          >
            ← Back
          </button>
          <button
            onClick={() => nextStep && goToStep(nextStep.id)}
            disabled={!nextStep}
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
            label="Cost / priced session"
            value={formatCost(kpis.totals.cost_per_session)}
            note={
              `over ${kpis.totals.priced_sessions.toLocaleString()} of ` +
              `${kpis.totals.sessions.toLocaleString()} sessions with priced turns; ` +
              "unpriced turns are excluded, not zeroed"
            }
          />
        </div>
      )}

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
