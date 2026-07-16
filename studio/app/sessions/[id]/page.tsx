"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { api, SessionDetail, TurnRow } from "@/lib/api";
import { Badge, Card, ErrorNote, Loading, formatCost, useApi } from "@/components/ui";

type Tab = "insights" | "tuning" | "coaching";

export default function SessionDetailPage() {
  const params = useParams();
  const id = Number(params.id);
  const [tab, setTab] = useState<Tab>("insights");
  const { data, error, loading } = useApi(() => api.session(id), [id]);

  if (loading) return <Loading />;
  if (error || !data) return <ErrorNote error={error || "not found"} />;

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-bold">{data.copilot} session</h1>
        <p className="text-sm text-slate-500">
          {data.project_path} · {data.model} · {data.turn_count} turns ·{" "}
          {data.error_count} errors · {formatCost(data.cost_usd)}
        </p>
      </div>

      <div className="flex gap-1 border-b border-slate-200">
        {(["insights", "tuning", "coaching"] as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm font-medium capitalize ${
              tab === t
                ? "border-b-2 border-blue-600 text-blue-600"
                : "text-slate-500 hover:text-slate-700"
            }`}
          >
            {t === "tuning" ? "Agent Tuning" : t === "coaching" ? "Prompt Coaching" : "Insights"}
          </button>
        ))}
      </div>

      {tab === "insights" && <Insights data={data} />}
      {tab === "tuning" && <AgentTuning data={data} />}
      {tab === "coaching" && <PromptCoaching data={data} />}
    </div>
  );
}

function turnBadges(t: TurnRow) {
  const out: { kind: string; label: string }[] = [];
  if (t.user_corrects_agent) out.push({ kind: "correction", label: "Correction" });
  if (t.rework_detected) out.push({ kind: "rework", label: "Rework" });
  if (t.role === "user" && !t.user_corrects_agent) out.push({ kind: "command", label: "Command" });
  if (t.sentiment) out.push({ kind: t.sentiment, label: t.sentiment });
  return out;
}

function Insights({ data }: { data: SessionDetail }) {
  return (
    <div className="space-y-2">
      {data.turns.map((t) => (
        <Card key={t.sequence_num} className="!p-3">
          <div className="flex items-start gap-3">
            <span
              className={`text-xs font-mono px-2 py-0.5 rounded ${
                t.role === "user" ? "bg-slate-200" : "bg-blue-50 text-blue-700"
              }`}
            >
              {t.role}#{t.sequence_num}
            </span>
            <div className="flex-1">
              <p className="text-sm text-slate-700 line-clamp-3 whitespace-pre-wrap">
                {t.content_preview || <span className="text-slate-400">(no content)</span>}
              </p>
              <div className="flex flex-wrap gap-1 mt-1.5">
                {t.slash_command && <Badge kind="command">{t.slash_command}</Badge>}
                {turnBadges(t).map((b, i) => (
                  <Badge key={i} kind={b.kind}>
                    {b.label}
                  </Badge>
                ))}
                {t.interaction_quality != null && (
                  <span className="text-xs text-slate-400">quality {t.interaction_quality}/5</span>
                )}
              </div>
            </div>
          </div>
        </Card>
      ))}
    </div>
  );
}

function AgentTuning({ data }: { data: SessionDetail }) {
  const corrections = data.turns.filter((t) => t.user_corrects_agent).length;
  const rework = data.turns.filter((t) => t.rework_detected).length;
  const recs: string[] = [];
  if (corrections > 0) recs.push(`${corrections} correction(s) — tighten the agent's confirmation step before acting.`);
  if (rework > 0) recs.push(`${rework} rework turn(s) — add a verification gate so work is checked before moving on.`);
  if (data.error_count > 0) recs.push(`${data.error_count} tool error(s) — add error-handling guidance for the failing tools.`);
  if (recs.length === 0) recs.push("No correction/rework signals detected. Run the Analysis tab to label this session first.");

  const config = {
    name: `${data.copilot}-tuned`,
    guardrails: {
      confirm_before_destructive: corrections > 0,
      verify_before_done: rework > 0,
    },
    error_handling: data.errors.map((e) => e.tool_name).filter(Boolean),
  };

  return (
    <div className="space-y-4">
      <Card title="Assessment">
        <ul className="list-disc pl-5 text-sm space-y-1">
          {recs.map((r, i) => (
            <li key={i}>{r}</li>
          ))}
        </ul>
      </Card>
      <Card title="Improved agent config (heuristic-derived, copy-ready)">
        <pre className="text-xs bg-slate-900 text-slate-100 rounded p-3 overflow-x-auto">
          {JSON.stringify(config, null, 2)}
        </pre>
      </Card>
    </div>
  );
}

function PromptCoaching({ data }: { data: SessionDetail }) {
  const userTurns = data.turns.filter((t) => t.role === "user");
  function issue(t: TurnRow): string {
    const txt = t.content_preview || "";
    if (txt.length < 25) return "Very short — add the file/symbol and the expected outcome.";
    if (/\b(it|this|that|the thing)\b/i.test(txt)) return "Vague pronoun — name the concrete target.";
    if (t.user_corrects_agent) return "Correction turn — the original prompt likely under-specified the constraint.";
    return "—";
  }
  return (
    <Card title="Prompt coaching (user turns)">
      <table className="w-full text-sm">
        <thead className="text-left text-slate-500 border-b border-slate-200">
          <tr>
            <th className="py-2 w-12">Turn</th>
            <th>Original prompt</th>
            <th>Issue</th>
          </tr>
        </thead>
        <tbody>
          {userTurns.map((t) => (
            <tr key={t.sequence_num} className="border-b border-slate-100 align-top">
              <td className="py-2 tabular-nums">#{t.sequence_num}</td>
              <td className="pr-4 whitespace-pre-wrap line-clamp-2">{t.content_preview}</td>
              <td className="text-slate-600">{issue(t)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}
