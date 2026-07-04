"use client";

import { useEffect, useState } from "react";
import { api, ConfigResponse } from "@/lib/api";
import { Card, ErrorNote, Loading } from "@/components/ui";

// Friendly labels + hints per .env key. Anything not listed renders as text.
const META: Record<string, { label: string; help?: string; type?: string }> = {
  CCT_SA_DSN: { label: "Database (DSN)", help: "SQLite local file (sqlite:////path) or postgresql://user:pass@host/db" },
  CCT_SA_KUZU_PATH: { label: "Knowledge-graph dir (Kùzu)", help: "Folder for the embedded graph; blank = ~/.cct default" },
  CCT_SA_REDACTION: { label: "Redaction", type: "redaction" },
  CCT_SA_JUDGE_BACKEND: { label: "Judge backend", type: "backend" },
  CCT_SA_JUDGE_MODEL: { label: "Judge model", help: "Blank = the backend's default (Claude Code → Opus 4.8)" },
  CCT_SA_JUDGE_BASE_URL: { label: "Judge base URL", help: "OpenAI-compatible endpoint, e.g. http://localhost:1234/v1 (LM Studio)" },
  CCT_SA_JUDGE_API_KEY: { label: "Judge API key", type: "password", help: "For hosted endpoints. Blank keeps the existing key." },
  CCT_SA_JUDGE_WORKERS: { label: "Parallel judge workers", type: "number" },
  CCT_SA_OLLAMA_URL: { label: "Ollama URL" },
};

export default function SettingsPage() {
  const [cfg, setCfg] = useState<ConfigResponse | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [probe, setProbe] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  async function load() {
    try {
      const c = await api.config();
      setCfg(c);
      const v: Record<string, string> = {};
      c.fields.forEach((f) => (v[f.key] = f.value));
      setValues(v);
    } catch (e) {
      setError(String(e));
    }
  }
  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function set(key: string, val: string) {
    setValues((v) => ({ ...v, [key]: val }));
  }

  async function save() {
    setSaved("Saving…");
    try {
      await api.saveConfig(values);
      setSaved("✓ Saved to .env");
      load();
    } catch (e) {
      setSaved(`✗ ${String(e)}`);
    }
  }

  async function testConn() {
    setProbe("Testing…");
    try {
      const r = await api.testConnection(values["CCT_SA_DSN"] || undefined);
      setProbe(r.ok ? `✓ ${r.dialect} · ${r.sessions} sessions` : `✗ ${r.error}`);
    } catch (e) {
      setProbe(`✗ ${String(e)}`);
    }
  }

  if (error) return <ErrorNote error={error} />;
  if (!cfg) return <Loading />;

  const backend = values["CCT_SA_JUDGE_BACKEND"] || "";
  const baseUrl = values["CCT_SA_JUDGE_BASE_URL"] || "";
  const cloudJudge =
    backend === "claude-code" ||
    (backend === "openai" && baseUrl.startsWith("http") && !baseUrl.includes("localhost") && !baseUrl.includes("127.0.0.1"));

  return (
    <div className="space-y-4 max-w-2xl">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Settings</h1>
        {!cfg.configured && (
          <span className="text-sm px-2 py-1 rounded bg-amber-100 text-amber-800">
            Not configured yet — fill this in and Save
          </span>
        )}
      </div>

      <Card title="Configuration (.env — shared with the CLI)">
        <div className="space-y-3">
          {cfg.fields.map((f) => {
            const m = META[f.key] || { label: f.key };
            return (
              <div key={f.key}>
                <label className="block text-sm font-medium text-slate-700">{m.label}</label>
                {m.type === "redaction" ? (
                  <select
                    className="border border-slate-300 rounded px-2 py-1 text-sm w-full"
                    value={values[f.key] || "code"}
                    onChange={(e) => set(f.key, e.target.value)}
                  >
                    {cfg.redaction_modes.map((r) => (
                      <option key={r} value={r}>{r}</option>
                    ))}
                  </select>
                ) : m.type === "backend" ? (
                  <select
                    className="border border-slate-300 rounded px-2 py-1 text-sm w-full"
                    value={values[f.key] || ""}
                    onChange={(e) => set(f.key, e.target.value)}
                  >
                    <option value="">Default — the copilot’s own model (Claude Code → Opus 4.8)</option>
                    {cfg.judge_backends.map((b) => (
                      <option key={b} value={b}>{b}</option>
                    ))}
                  </select>
                ) : (
                  <input
                    type={m.type === "password" ? "password" : m.type === "number" ? "number" : "text"}
                    className="border border-slate-300 rounded px-2 py-1 text-sm w-full font-mono"
                    placeholder={f.secret && f.has_value ? "•••••• (unchanged)" : ""}
                    value={values[f.key] || ""}
                    onChange={(e) => set(f.key, e.target.value)}
                  />
                )}
                {m.help && <p className="text-xs text-slate-400 mt-0.5">{m.help}</p>}
              </div>
            );
          })}
        </div>

        {cloudJudge && (
          <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded p-2 mt-3">
            ⚠ This judge sends redacted turn previews to an external service. Choose Ollama
            or a localhost endpoint for a fully-local judge.
          </p>
        )}

        <div className="mt-4 flex items-center gap-3">
          <button onClick={save} className="bg-blue-600 text-white text-sm px-4 py-1.5 rounded hover:bg-blue-700">Save</button>
          <button onClick={testConn} className="bg-slate-800 text-white text-sm px-4 py-1.5 rounded hover:bg-slate-700">Test Connection</button>
          {saved && <span className="text-sm text-slate-600">{saved}</span>}
          {probe && <span className="text-sm font-mono">{probe}</span>}
        </div>
      </Card>

      <Card title="Effective judge">
        <p className="text-sm">
          Default judge resolves to{" "}
          <code className="bg-slate-100 px-1 rounded">{cfg.judge_default}</code>. A blank backend
          uses each copilot’s own LLM; set a backend above to force one for all sessions.
        </p>
      </Card>
    </div>
  );
}
