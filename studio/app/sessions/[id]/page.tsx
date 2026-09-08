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
  SessionTagsInfo,
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
import ResponseTimeCard from "@/components/ResponseTime";
import SessionHeader from "@/components/SessionHeader";
import { HandTag } from "@/components/SessionTags";
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
  // "Is this session unusual for this project?" — the base rate from
  // /api/predict/effort (#307), withheld below the sample floor so five
  // sessions never masquerade as a distribution. Without a project path
  // the estimate would be store-wide and "this project" a lie: skipped.
  const projectPath = data?.project_path || "";
  const { data: baselineData } = useApi(
    () => (projectPath ? api.predictEffort(projectPath) : Promise.resolve(null)),
    [projectPath],
  );
  const baseline = projectPath && baselineData && baselineData.turns.sufficient ? baselineData : null;
  // Hand-set tags toggled here show at once; the server's answer wins.
  const [tags, setTags] = useState<SessionTagsInfo | null>(null);
  async function toggleTag(tag: HandTag, on: boolean) {
    if (!data) return;
    const current = tags ?? data.tags;
    setTags({ ...current, [tag]: on });
    try {
      setTags((await api.setSessionTag(id, tag, on)).tags);
    } catch {
      setTags(current);
    }
  }

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
      <SessionHeader
        data={data}
        baseline={baseline}
        tags={tags ?? data.tags}
        onToggleTag={(tag, on) => toggleTag(tag, on)}
      />

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
          <ResponseTimeCard latency={data.latency} turns={data.turns} />
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
  // The judge is chosen under Settings and only there (the owner's
  // rule: one place). This page reports whether the configured model
  // is one its backend serves, so a wrong name is seen before a run.
  const [models, setModels] = useState<JudgeModels | null>(null);
  // Learn index for the finding → guide links; the panel renders without
  // it, the badges just stay plain until it arrives.
  const learn = useApi(() => api.docs(), []);

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
        .runSessionAnalysis(id, kind, { force })
        .then((outcome) => {
          if (outcome.ok) {
            const row: AnalysisRow = outcome.report;
            setState({ kind: "done", row });
          } else {
            setState({ kind: "failed", failure: outcome, keptPrevious });
          }
        });
    },
    [id, kind, state],
  );

  if (metaError) return <ErrorNote error={metaError} />;
  if (!meta) return <Loading />;

  // What the configured backend serves, checked against the configured
  // model — for any backend with a catalogue (Ollama, vLLM), not Ollama
  // alone; the model name is the part after the first colon.
  const served = models?.reachable ? models.models : [];
  const configuredModel = models?.configured.model || "";
  const configuredMissing =
    configuredModel !== "" && served.length > 0 && !served.includes(configuredModel);

  return (
    <div className="space-y-3">
      {meta.archive.archived_turns === 0 && state.kind === "absent" && (
        <p className="text-xs text-amber-700">
          This session has no archived transcript; the model will see content
          previews only. Enable <code>trace_archive</code> for the project in
          Settings for full-text analysis.
        </p>
      )}
      <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
        <span>
          Judge: <span className="font-mono text-slate-800">{meta.judge}</span>
        </span>
        <a href="/settings" className="text-blue-700 hover:underline">
          change in Settings
        </a>
        {configuredMissing && (
          <span className="text-rose-700">
            {configuredModel} is not served at {models?.url} — set one that is,
            under Settings › LLM-as-Judge.
          </span>
        )}
      </div>
      <SessionAnalysis
        kind={kind}
        title={meta.titles[kind]}
        state={state}
        judge={meta.judge}
        onRun={run}
        learnLinks={learn.data?.finding_links}
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
