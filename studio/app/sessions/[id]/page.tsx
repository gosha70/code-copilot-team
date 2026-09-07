"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import {
  ANALYSIS_KINDS,
  AnalysisKind,
  AnalysisRow,
  api,
  JudgeModels,
  SessionAnalysisResponse,
  SessionDetail,
  TurnRow,
} from "@/lib/api";
import {
  Badge,
  Card,
  ErrorNote,
  Loading,
  formatCost,
  formatDuration,
  useApi,
} from "@/components/ui";
import SessionAnalysis, { PanelState } from "@/components/SessionAnalysis";
import SimilarPanel from "@/components/SimilarPanel";
import { classifySimilar, type SimilarOutcome } from "@/lib/similarStates";

// One session, read the way a person reads it: what was said (Timeline,
// with the real text and how long each reply took), then what to change
// (Agent Tuning), how to prompt (Prompt Coaching), where the time went
// (Efficiency). The three analyses are produced by the configured judge
// over the WHOLE transcript and stored — nothing on those tabs is a
// heuristic dressed up as advice.

type Tab = "timeline" | AnalysisKind | "similar";

const TURN_HASH = /^#turn-(\d+)$/;

const TAB_LABEL: Record<Tab, string> = {
  timeline: "Timeline",
  tuning: "Agent Tuning",
  coaching: "Prompt Coaching",
  efficiency: "Efficiency",
  similar: "Similar",
};

export default function SessionDetailPage() {
  const params = useParams();
  const id = Number(params.id);
  const [tab, setTab] = useState<Tab>("timeline");
  const { data, error, loading } = useApi(() => api.session(id), [id]);

  // A turn chip on an analysis tab links to `#turn-N`, which lives on the
  // Timeline. The Timeline is not mounted while another tab is showing,
  // so the hash must first switch the tab; the Timeline then scrolls to
  // the turn once it has rendered (see Timeline).
  useEffect(() => {
    const onHash = () => {
      if (TURN_HASH.test(window.location.hash)) setTab("timeline");
    };
    onHash();
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  if (loading) return <Loading />;
  if (error || !data) return <ErrorNote error={error || "not found"} />;

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-bold">{data.copilot} session</h1>
        <p className="text-sm text-slate-500">
          {data.project_path} · {data.model} · {data.turn_count} turns ·{" "}
          {data.error_count} errors · {formatDuration(data.duration_seconds)} ·{" "}
          {formatCost(data.cost_usd)}
        </p>
      </div>

      <div className="flex gap-1 border-b border-slate-200 overflow-x-auto">
        {(["timeline", ...ANALYSIS_KINDS, "similar"] as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm font-medium whitespace-nowrap ${
              tab === t
                ? "border-b-2 border-blue-600 text-blue-600"
                : "text-slate-500 hover:text-slate-700"
            }`}
          >
            {TAB_LABEL[t]}
          </button>
        ))}
      </div>

      {tab === "timeline" && <Timeline data={data} />}
      {ANALYSIS_KINDS.includes(tab as AnalysisKind) && (
        <Analysis id={id} kind={tab as AnalysisKind} />
      )}
      {tab === "similar" && <Similar id={id} />}
    </div>
  );
}

// ── Timeline ────────────────────────────────────────────────────────────

function turnBadges(t: TurnRow) {
  const out: { kind: string; label: string }[] = [];
  if (t.user_corrects_agent)
    out.push({ kind: "correction", label: "Correction" });
  if (t.rework_detected) out.push({ kind: "rework", label: "Rework" });
  if (t.role === "user" && !t.user_corrects_agent)
    out.push({ kind: "command", label: "Command" });
  if (t.sentiment) out.push({ kind: t.sentiment, label: t.sentiment });
  return out;
}

// Latency is judged against the ASSISTANT's turns: a slow reply is the
// harness's business, a slow user is a person thinking.
function latencyTone(t: TurnRow): string {
  if (t.latency_seconds == null) return "text-slate-400";
  if (t.role !== "assistant") return "text-slate-400";
  if (t.latency_seconds >= 120) return "text-rose-700";
  if (t.latency_seconds >= 30) return "text-amber-700";
  return "text-slate-500";
}

function Timeline({ data }: { data: SessionDetail }) {
  const anyArchived = data.turns.some((t) => t.archived);
  // The browser's own anchor jump happened before these cards existed
  // (the tab was not mounted), so repeat it now that they do — and mark
  // the turn ourselves: `:target` is not re-evaluated for an element that
  // appears after the fragment navigation.
  const [target, setTarget] = useState<number | null>(null);
  useEffect(() => {
    const onHash = () => {
      const m = TURN_HASH.exec(window.location.hash);
      setTarget(m ? Number(m[1]) : null);
      if (m)
        document
          .getElementById(`turn-${m[1]}`)
          ?.scrollIntoView({ block: "start" });
    };
    onHash();
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, [data]);
  return (
    <div className="space-y-3">
      {data.latency && (
        <Card title="Response time (assistant turns)">
          <div className="flex flex-wrap gap-x-8 gap-y-2 text-sm">
            <span>
              median{" "}
              <span className="font-medium">
                {formatDuration(data.latency.p50)}
              </span>
            </span>
            <span>
              p90{" "}
              <span className="font-medium">
                {formatDuration(data.latency.p90)}
              </span>
            </span>
            <span>
              slowest{" "}
              <span className="font-medium">
                {formatDuration(data.latency.max)}
              </span>
            </span>
            <span className="text-slate-500">
              {data.latency.measured_turns.toLocaleString()} turns measured
            </span>
            <span className="text-slate-500">
              slowest:{" "}
              {data.latency.slowest.map((s, i) => (
                <a
                  key={s.sequence_num}
                  href={`#turn-${s.sequence_num}`}
                  className="font-mono text-blue-700 hover:underline"
                >
                  #{s.sequence_num} {formatDuration(s.seconds)}
                  {i < data.latency!.slowest.length - 1 ? ", " : ""}
                </a>
              ))}
            </span>
          </div>
        </Card>
      )}
      {!anyArchived && (
        <p className="text-xs text-slate-500">
          Showing content previews only. Enable <code>trace_archive</code> for
          this project in Settings and re-run Load sessions to keep the full
          text.
        </p>
      )}
      {data.turns.map((t) => (
        <TurnCard
          key={t.sequence_num}
          t={t}
          highlighted={t.sequence_num === target}
        />
      ))}
    </div>
  );
}

function TurnCard({ t, highlighted }: { t: TurnRow; highlighted: boolean }) {
  const [open, setOpen] = useState(false);
  const text = t.archived ? t.content : t.content_preview;
  const long = (text || "").length > 300 || (text || "").split("\n").length > 3;
  return (
    <Card className={highlighted ? "!p-3 ring-2 ring-blue-400" : "!p-3"}>
      <div
        id={`turn-${t.sequence_num}`}
        className="flex items-start gap-3 scroll-mt-20"
      >
        <div className="flex flex-col items-end gap-1 shrink-0 w-24">
          <span
            className={`text-xs font-mono px-2 py-0.5 rounded ${
              t.role === "user" ? "bg-slate-200" : "bg-blue-50 text-blue-700"
            }`}
          >
            {t.role}#{t.sequence_num}
          </span>
          {t.latency_seconds != null && (
            <span
              className={`text-xs font-mono ${latencyTone(t)}`}
              title="since the previous turn"
            >
              {/* formatDuration renders zero as "—" (unknown); a measured
                  sub-second gap is a real number, so say so. */}
              +
              {t.latency_seconds < 1
                ? "<1s"
                : formatDuration(t.latency_seconds)}
            </span>
          )}
        </div>
        <div className="flex-1 min-w-0">
          <p
            className={`text-sm text-slate-700 whitespace-pre-wrap break-words ${
              open ? "" : "line-clamp-3"
            }`}
          >
            {text ? (
              text
            ) : t.archived ? (
              <span className="text-slate-400">
                (tool results only, no prose)
              </span>
            ) : (
              <span className="text-slate-400">
                (preview only — no text captured)
              </span>
            )}
          </p>
          {long && (
            <button
              onClick={() => setOpen(!open)}
              className="text-xs text-blue-700 hover:underline mt-0.5"
            >
              {open ? "show less" : "show all"}
            </button>
          )}
          <div className="flex flex-wrap gap-1 mt-1.5">
            {t.slash_command && <Badge kind="command">{t.slash_command}</Badge>}
            {t.has_tool_use && <Badge kind="question">tools</Badge>}
            {turnBadges(t).map((b, i) => (
              <Badge key={i} kind={b.kind}>
                {b.label}
              </Badge>
            ))}
            {t.interaction_quality != null && (
              <span className="text-xs text-slate-400">
                quality {t.interaction_quality}/5
              </span>
            )}
          </div>
        </div>
      </div>
    </Card>
  );
}

// ── Analysis tabs ───────────────────────────────────────────────────────

function Analysis({ id, kind }: { id: number; kind: AnalysisKind }) {
  const [meta, setMeta] = useState<SessionAnalysisResponse | null>(null);
  const [metaError, setMetaError] = useState<string | null>(null);
  const [state, setState] = useState<PanelState>({ kind: "absent" });
  // The configured judge is the default. A blank configured model means
  // the backend's own default (ollama → llama3), which is often not the
  // model a machine actually has — so, like the Analysis page, offer the
  // installed Ollama models as a per-run choice. "" = configured.
  const [models, setModels] = useState<JudgeModels | null>(null);
  const [judge, setJudge] = useState("");

  useEffect(() => {
    api
      .judgeModels()
      .then(setModels)
      .catch(() => setModels(null));
  }, []);

  const load = useCallback(() => {
    api
      .sessionAnalysis(id)
      .then((m) => {
        setMeta(m);
        const row = m.kinds[kind];
        setState(row ? { kind: "done", row } : { kind: "absent" });
      })
      .catch((e) => setMetaError(String(e)));
  }, [id, kind]);

  useEffect(() => {
    load();
  }, [load]);

  const run = useCallback(
    (force: boolean) => {
      // The server never replaces a parsed result with a failure; tell
      // the reader that what they had is still there.
      const keptPrevious =
        state.kind === "done" && state.row.parse_status === "ok";
      setState({ kind: "running" });
      api
        .runSessionAnalysis(id, kind, { force, judge: judge || undefined })
        .then((outcome) => {
          if (outcome.ok) {
            const row: AnalysisRow = outcome.report;
            setState({ kind: "done", row });
          } else {
            setState({ kind: "failed", failure: outcome, keptPrevious });
          }
        });
    },
    [id, kind, judge, state],
  );

  if (metaError) return <ErrorNote error={metaError} />;
  if (!meta) return <Loading />;

  const installed = models?.reachable ? models.models : [];
  const configuredOllama = meta.judge.startsWith("ollama:")
    ? meta.judge.slice("ollama:".length)
    : null;
  const configuredMissing =
    configuredOllama != null &&
    installed.length > 0 &&
    !installed.includes(configuredOllama);

  return (
    <div className="space-y-3">
      {meta.archive.archived_turns === 0 && state.kind === "absent" && (
        <p className="text-xs text-amber-700">
          This session has no archived transcript; the model will see content
          previews only. Enable <code>trace_archive</code> for the project in
          Settings for full-text analysis.
        </p>
      )}
      {installed.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
          <label htmlFor="analysis-judge">Judge</label>
          <select
            id="analysis-judge"
            value={judge}
            onChange={(e) => setJudge(e.target.value)}
            className="border border-slate-300 bg-white text-slate-900 rounded px-2 py-1 text-sm"
          >
            <option value="">configured: {meta.judge}</option>
            {installed.map((m) => (
              <option key={m} value={`ollama:${m}`}>
                ollama:{m}
              </option>
            ))}
          </select>
          {configuredMissing && !judge && (
            <span className="text-rose-700">
              {configuredOllama} is not installed on {models?.url} — pick an
              installed model, or set one under Settings › LLM-as-Judge.
            </span>
          )}
        </div>
      )}
      <SessionAnalysis
        kind={kind}
        title={meta.titles[kind]}
        state={state}
        judge={judge || meta.judge}
        onRun={run}
      />
    </div>
  );
}

// #293 T3: fetching only — every rendering decision lives in
// SimilarPanel, which is pure so the D8 script can render its states.
function Similar({ id }: { id: number }) {
  const [state, setState] = useState<SimilarOutcome | null>(null);
  useEffect(() => {
    let live = true;
    api
      .similar(id)
      .then((outcome) => live && setState(classifySimilar(outcome)))
      // A rejected promise is an honest failure, not a prerequisite.
      .catch((e) => live && setState({ kind: "failed", message: String(e) }));
    return () => {
      live = false;
    };
  }, [id]);
  return state === null ? <Loading /> : <SimilarPanel state={state} />;
}
