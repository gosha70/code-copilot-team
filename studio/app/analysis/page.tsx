"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { Card } from "@/components/ui";

const STEPS = [
  { key: "select", label: "Select Sessions", cmd: "session-analytics ingest --since-days 7" },
  { key: "load", label: "Load to Database", cmd: "session-analytics ingest" },
  { key: "graph", label: "Build Knowledge Graph", cmd: "session-analytics graph --rebuild" },
  { key: "judge", label: "LLM Judge", cmd: "session-analytics analyze --judge ollama:llama3" },
  { key: "kpis", label: "Session Analysis", cmd: "session-analytics kpis" },
];

export default function AnalysisPage() {
  const [judge, setJudge] = useState("");   // "" = default (each copilot's own LLM)
  const [limit, setLimit] = useState(50);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<string | null>(null);

  async function runJudge() {
    setRunning(true);
    setResult(null);
    try {
      const r = await api.analyze({ judge: judge || undefined, limit });
      if (r.by_copilot) {
        const parts = Object.entries(r.by_copilot).map(
          ([c, s]) => `${c} → ${(s as any).labeled} turns via ${(s as any).judge}`,
        );
        setResult(`Labeled by each copilot's own LLM: ${parts.join("; ") || "(nothing to label)"}.`);
      } else {
        setResult(`Labeled ${(r as any).labeled} turns with ${(r as any).judge}.`);
      }
    } catch (e) {
      setResult(`Error: ${String(e)}. Is the judge backend reachable?`);
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">Analysis</h1>
      <p className="text-sm text-slate-500">
        The pipeline runs as five steps. Ingestion/graph/kpis run from the CLI; the
        LLM-Judge step can be triggered here.
      </p>

      <ol className="space-y-3">
        {STEPS.map((s, i) => (
          <li key={s.key}>
            <Card className="!p-3">
              <div className="flex items-center gap-3">
                <span className="w-7 h-7 rounded-full bg-blue-600 text-white text-sm flex items-center justify-center">
                  {i + 1}
                </span>
                <div className="flex-1">
                  <div className="font-medium text-sm">{s.label}</div>
                  <code className="text-xs text-slate-500">./scripts/{s.cmd}</code>
                </div>
                {s.key === "judge" && (
                  <div className="flex items-center gap-2">
                    <select
                      className="border border-slate-300 rounded px-2 py-1 text-sm"
                      value={judge}
                      onChange={(e) => setJudge(e.target.value)}
                    >
                      <option value="">Default — each copilot’s own LLM (Claude → Opus 4.8)</option>
                      <option value="claude-code:sonnet">claude-code:sonnet</option>
                      <option value="ollama:llama3">ollama:llama3 (local)</option>
                      <option value="openai:local-model">openai (LM Studio / external — set base URL in Settings)</option>
                    </select>
                    <input
                      type="number"
                      className="border border-slate-300 rounded px-2 py-1 text-sm w-20"
                      value={limit}
                      onChange={(e) => setLimit(Number(e.target.value))}
                    />
                    <button
                      onClick={runJudge}
                      disabled={running}
                      className="bg-blue-600 text-white text-sm px-4 py-1 rounded hover:bg-blue-700 disabled:opacity-50"
                    >
                      {running ? "Running…" : "Run"}
                    </button>
                  </div>
                )}
              </div>
            </Card>
          </li>
        ))}
      </ol>

      {result && (
        <div className="bg-slate-100 border border-slate-200 rounded p-3 text-sm">{result}</div>
      )}
    </div>
  );
}
