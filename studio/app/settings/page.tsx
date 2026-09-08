"use client";

import { useEffect, useState } from "react";
import { api, ConfigResponse, EmbedModels, JudgeModels, ProjectRedactionRow } from "@/lib/api";
import { Card, ErrorNote, Loading, useApi } from "@/components/ui";
import PathPicker from "@/components/PathPicker";
import { pathFromValue } from "@/lib/paths";
import { isPrivateUrl } from "@/lib/urls";

// Fields are GROUPED BY THE FEATURE THEY CONFIGURE, not listed flat.
// A flat list gave no signal that the five Judge* keys are one feature
// and useless individually — you cannot tell from the page that setting
// "Judge model" alone does nothing. Groups also let the Judge section
// show only the fields the CHOSEN backend actually uses, so an operator
// is never asked for an OpenAI base URL while running Ollama.
const GROUPS: { title: string; blurb: string; keys: string[] }[] = [
  {
    title: "Storage",
    blurb: "Where analytics data is kept. Required — everything else reads from here.",
    keys: ["CCT_SA_DB", "CCT_SA_KUZU_PATH"],
  },
  {
    title: "Privacy",
    blurb: "Applied before anything is written to the database or sent to a judge.",
    keys: ["CCT_SA_REDACTION"],
  },
  {
    title: "LLM-as-Judge",
    blurb:
      "The model that labels turns on the Analysis tab — configured here " +
      "and only here. Pick a backend first; the fields below change to " +
      "match it. Ollama and vLLM can run on another machine (a DGX box): " +
      "point the URL at it.",
    keys: [
      "CCT_SA_JUDGE_BACKEND", "CCT_SA_JUDGE_MODEL", "CCT_SA_JUDGE_BASE_URL",
      "CCT_SA_JUDGE_API_KEY", "CCT_SA_JUDGE_WORKERS", "CCT_SA_OLLAMA_URL",
    ],
  },
  {
    title: "Embeddings",
    blurb:
      "The model that turns each session into a vector for the Similar tab " +
      "(Analysis → Embed sessions, Find similar sessions). A small local " +
      "embedding model such as nomic-embed-text on Ollama is enough; it " +
      "shares the Ollama URL above.",
    keys: ["CCT_SA_EMBED_BACKEND", "CCT_SA_EMBED_MODEL"],
  },
  {
    title: "Benchmarks",
    blurb:
      "Where this repository's benchmark harness wrote its runs. With it " +
      "set, Analysis → Link benchmark runs (and Run all) stores every " +
      "attempt's pass/fail and links Claude Code runs whose run record " +
      "names a loaded session — what the Benchmark tab shows. Leave it " +
      "blank if you have not run the harness; the step is then skipped.",
    keys: ["CCT_SA_BENCHMARK_RUNS_ROOT"],
  },
  {
    title: "Identity",
    blurb: "Attributes sessions to a developer. Defaults to your git email.",
    keys: ["CCT_DEVELOPER_ID"],
  },
];

// Judge fields that are MEANINGLESS for a given backend are hidden, not
// merely unexplained — showing an OpenAI base URL to an Ollama user is
// how a config page teaches the wrong thing.
const JUDGE_FIELDS_BY_BACKEND: Record<string, string[]> = {
  "": ["CCT_SA_JUDGE_BACKEND", "CCT_SA_JUDGE_MODEL", "CCT_SA_JUDGE_WORKERS"],
  "claude-code": ["CCT_SA_JUDGE_BACKEND", "CCT_SA_JUDGE_MODEL", "CCT_SA_JUDGE_WORKERS"],
  ollama: [
    "CCT_SA_JUDGE_BACKEND", "CCT_SA_JUDGE_MODEL", "CCT_SA_OLLAMA_URL",
    "CCT_SA_JUDGE_WORKERS",
  ],
};
const JUDGE_FIELDS_OPENAI = [
  "CCT_SA_JUDGE_BACKEND", "CCT_SA_JUDGE_MODEL", "CCT_SA_JUDGE_BASE_URL",
  "CCT_SA_JUDGE_API_KEY", "CCT_SA_JUDGE_WORKERS",
];

// EVERY field gets: what it is for, and a concrete example. A label
// alone ("Judge base URL") tells an operator nothing about whether they
// need it, what shape the value takes, or what happens if it is blank —
// which is how a settings page becomes a guessing game.
const META: Record<
  string,
  {
    label: string;
    help?: string;
    example?: string;
    placeholder?: string;
    type?: string;
    browse?: "file" | "dir";
  }
> = {
  CCT_SA_DB: {
    label: "Database",
    browse: "file",
    help:
      "Where every ingested session, turn and label is stored. This is the " +
      "one required setting — the CLI and this UI read the same store. " +
      "SQLite needs no server; Postgres is for a shared team store.",
    placeholder: "sqlite:////Users/you/.cct/session-analytics.db",
  },
  CCT_SA_KUZU_PATH: {
    label: "Knowledge-graph store",
    browse: "dir",
    help:
      "Where the Kùzu graph for the Graph tab and clustering lives. A " +
      "folder works: the store file session-analytics-graph is created " +
      "inside it by the graph step, which takes seconds. A file path is " +
      "used as given.",
    placeholder: "~/.cct",
  },
  CCT_SA_REDACTION: {
    label: "Redaction level",
    help:
      "What is stripped from session text BEFORE it is written to the " +
      "database or sent to a judge. `code` (recommended) keeps prose but " +
      "removes fenced code blocks and tool inputs. `metadata-only` stores " +
      "no content at all — counts and timestamps only. `none` stores text " +
      "verbatim, including any secrets it contained.",
    type: "redaction",
  },
  CCT_SA_JUDGE_BACKEND: {
    label: "Backend",
    help:
      "Which model reads your turns and labels them. Default uses the " +
      "copilot's own model. Ollama keeps everything on this machine. " +
      "OpenAI-compatible covers LM Studio, vLLM and hosted APIs.",
    type: "backend",
  },
  CCT_SA_JUDGE_MODEL: {
    label: "Model",
    help:
      "Which model the backend should use. The list is what the saved " +
      "backend URL actually serves (Ollama: its installed tags; vLLM/LM " +
      "Studio: its /v1/models). Save a new URL first, then the list " +
      "follows it. Choose Other… to type a name that is not listed.",
    placeholder: "the backend's default",
  },
  CCT_SA_JUDGE_BASE_URL: {
    label: "Base URL",
    help:
      "The OpenAI-compatible endpoint to call, ending in /v1 — LM Studio, " +
      "vLLM (e.g. http://spark.local:8000/v1 on a DGX Spark), or a hosted " +
      "API. Needed only for the OpenAI-compatible backend.",
    placeholder: "http://localhost:1234/v1",
  },
  CCT_SA_JUDGE_API_KEY: {
    label: "API key",
    help:
      "Only for hosted endpoints — local servers usually ignore it. " +
      "Stored in .env and never sent to the browser.",
    placeholder: "none",
    type: "password",
  },
  CCT_SA_JUDGE_WORKERS: {
    label: "Parallel workers",
    help:
      "How many turns are judged at once. Higher is faster but hits rate " +
      "limits on hosted APIs and can swamp a local model.",
    placeholder: "1",
    type: "number",
  },
  CCT_SA_OLLAMA_URL: {
    label: "Ollama URL",
    help:
      "Where Ollama is listening. Only used by the Ollama backend. Another " +
      "machine works (e.g. http://spark.local:11434) if that Ollama is " +
      "started with OLLAMA_HOST=0.0.0.0.",
    placeholder: "http://localhost:11434",
  },
  CCT_SA_EMBED_BACKEND: {
    label: "Backend",
    help: "Where embeddings are computed. Ollama is the packaged default and the only local option today.",
    type: "embed-backend",
  },
  CCT_SA_EMBED_MODEL: {
    label: "Model",
    help:
      "An EMBEDDING model, not a chat model — e.g. nomic-embed-text (after " +
      "`ollama pull nomic-embed-text`). Ollama has no default embedding " +
      "model, so this must be set before Embed sessions can run. The list " +
      "holds only the models the saved Ollama URL can embed with; its chat " +
      "models are left out, because Ollama refuses to embed with them.",
    placeholder: "nomic-embed-text",
  },
  CCT_SA_BENCHMARK_RUNS_ROOT: {
    label: "Benchmark runs folder",
    browse: "dir",
    help:
      "The folder the benchmark harness writes into (each attempt has a " +
      "run-record.json and a score.json below it). The harness's default " +
      "is the repository's runs/ folder.",
    placeholder: "/path/to/code-copilot-team/runs",
  },
  CCT_DEVELOPER_ID: {
    label: "Developer id",
    help:
      "Attributes sessions to a person, so a shared store can be broken " +
      "down per developer.",
    placeholder: "derived from your git email",
  },
};

export default function SettingsPage() {
  const [cfg, setCfg] = useState<ConfigResponse | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  // Results of the two probes. Each is a box under its own button, in
  // colour — the DB result used to be a mono span at the end of the
  // button row, and the owner did not see it.
  const [probe, setProbe] = useState<{ ok: boolean; text: string } | null>(null);
  const [judgeProbe, setJudgeProbe] = useState<{ ok: boolean; text: string } | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [projects, setProjects] = useState<ProjectRedactionRow[] | null>(null);
  const [projectsError, setProjectsError] = useState<string | null>(null);
  // Models Ollama actually has, offered on the Model field: a name typed
  // from memory that is not installed 404s on every judge call.
  const [models, setModels] = useState<JudgeModels | null>(null);
  // "Other…" on the Model dropdown: type a name the server does not list.
  const [modelOther, setModelOther] = useState(false);
  const [embedModels, setEmbedModels] = useState<EmbedModels | null>(null);
  // The embedding list has THREE states the field must tell apart:
  // loading (a disabled select saying so), failed (a text box plus the
  // reason and Retry), listed. It used to fall back to a bare text box
  // in the first two, which read as the dropdown vanishing.
  const [embedListState, setEmbedListState] = useState<"loading" | "failed" | "ready">("loading");
  const [embedOther, setEmbedOther] = useState(false);
  const [embedProbe, setEmbedProbe] = useState<{ ok: boolean; text: string } | null>(null);
  const loadModels = () => {
    api.judgeModels().then(setModels).catch(() => setModels(null));
    setEmbedListState("loading");
    api
      .embedModels()
      .then((m) => {
        setEmbedModels(m);
        setEmbedListState("ready");
      })
      .catch(() => {
        setEmbedModels(null);
        setEmbedListState("failed");
      });
  };
  useEffect(() => {
    loadModels();
  }, []);
  // ONE open at a time. Help is on demand behind a (?) — permanently
  // rendering every explanation is what made this page unreadable.
  const [openHelp, setOpenHelp] = useState<string | null>(null);
  // Fields that name something on THIS machine get a Browse… button —
  // a path should be findable, not remembered and retyped.
  const [picking, setPicking] = useState<{ key: string; mode: "file" | "dir" } | null>(
    null,
  );

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

  useEffect(() => {
    api
      .projectRedaction()
      .then((r) => setProjects(r.projects))
      .catch((e) => setProjectsError(String(e)));
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
      // The model list follows the SAVED backend and URL.
      loadModels();
    } catch (e) {
      setSaved(`✗ ${String(e)}`);
    }
  }

  async function testConn() {
    setProbe({ ok: true, text: "Testing the database…" });
    try {
      const r = await api.testConnection(values["CCT_SA_DB"] || undefined);
      // `sessions` is null when the target has no CCT schema: the probe
      // no longer creates one, so "0 sessions" would misreport a database
      // that simply is not an analytics store.
      setProbe(
        r.ok
          ? {
              ok: true,
              text: r.schema_present
                ? `Database reachable: ${r.dialect}, ${r.sessions} sessions.`
                : `Database reachable: ${r.dialect}; no analytics schema yet (run setup to initialize).`,
            }
          : { ok: false, text: `Database not reachable: ${r.error}` },
      );
    } catch (e) {
      setProbe({ ok: false, text: `Database not reachable: ${String(e)}` });
    }
  }

  async function testEmbedding() {
    setEmbedProbe({ ok: true, text: "Embedding one short sentence…" });
    try {
      const r = await api.testEmbedding();
      setEmbedProbe(
        r.ok
          ? { ok: true, text: `${r.embedding} answered in ${r.seconds}s: ${r.dimensions} dimensions (model ${r.model})` }
          : { ok: false, text: `${r.embedding} failed${r.seconds ? ` after ${r.seconds}s` : ""}: ${r.error}` },
      );
    } catch (e) {
      setEmbedProbe({ ok: false, text: `Embedding test failed: ${String(e)}` });
    }
  }

  async function testJudge() {
    setJudgeProbe({ ok: true, text: "Asking the judge for one answer…" });
    try {
      const r = await api.testJudge();
      setJudgeProbe(
        r.ok
          ? { ok: true, text: `${r.judge} answered in ${r.seconds}s: ${r.answer}` }
          : { ok: false, text: `${r.judge} failed${r.seconds ? ` after ${r.seconds}s` : ""}: ${r.error}` },
      );
    } catch (e) {
      setJudgeProbe({ ok: false, text: `Judge test failed: ${String(e)}` });
    }
  }

  function ProbeBox({ result }: { result: { ok: boolean; text: string } | null }) {
    if (!result) return null;
    return (
      <div
        className={
          "mt-3 text-sm rounded border px-3 py-2 " +
          (result.ok
            ? "bg-emerald-50 border-emerald-200 text-emerald-900"
            : "bg-rose-50 border-rose-200 text-rose-900")
        }
        role="status"
      >
        {result.text}
      </div>
    );
  }

  if (error) return <ErrorNote error={error} />;
  if (!cfg) return <Loading />;

  const backend = values["CCT_SA_JUDGE_BACKEND"] || "";
  // The Model field is a dropdown when the saved backend serves a
  // catalogue (Ollama, an OpenAI-compatible server) and the chosen
  // backend is that same backend; a datalist was tried and rejected —
  // browsers filter it by what is typed, so with the current model in
  // the box only that one entry showed and nothing else was pickable.
  const savedBackend = models?.backend ?? "";
  const effectiveBackend = backend === "" ? "ollama" : backend;
  const modelList =
    models && models.reachable && effectiveBackend === savedBackend ? models.models : null;
  // Same rule for the embedding model: the SAVED backend's catalogue.
  const embedBackend = values["CCT_SA_EMBED_BACKEND"] || "ollama";
  const embedModelList =
    embedModels && embedModels.reachable && embedBackend === embedModels.backend ? embedModels.models : null;
  const baseUrl = values["CCT_SA_JUDGE_BASE_URL"] || "";
  // "External" means off this network: a vLLM box on the LAN (a DGX
  // Spark at 192.168.x, spark.local) is as local as Ollama for privacy.
  const cloudJudge =
    backend === "claude-code" || (backend === "openai" && baseUrl.startsWith("http") && !isPrivateUrl(baseUrl));

  return (
    <div className="space-y-4 max-w-2xl">
      {picking && (
        <PathPicker
          mode={picking.mode}
          // A database URL is not a path: strip the sqlite:/// scheme so
          // the picker opens where the current value points, not at home.
          startPath={pathFromValue(values[picking.key] || "")}
          onClose={() => setPicking(null)}
          onPick={(path) => {
            // The Database field takes a URL, not a bare path — the
            // picker returns a filesystem path, so convert it here
            // rather than making the user know the sqlite:/// form.
            set(
              picking.key,
              // A picked folder is kept as-is for the graph store: the
              // store file is resolved inside it by the API.
              picking.key === "CCT_SA_DB" ? `sqlite:///${path}` : path,
            );
            setPicking(null);
          }}
        />
      )}
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Settings</h1>
        <ApiPill />
        {!cfg.configured && (
          // Same defect as the app-wide banner: this fired whenever no
          // .env existed, even with a healthy store visible on the same
          // screen. It now states the ONE thing that is actually
          // missing, and what saving will change.
          <span className="text-sm px-2 py-1 rounded bg-amber-100 text-amber-800">
            {cfg.readiness && cfg.readiness.store_reachable
              ? "Store is reachable — Save to keep these settings for next time"
              : "Set a Database below and Save — nothing else is required"}
          </span>
        )}
      </div>

      {cfg.legacy_db_key && (
        <p className="text-xs text-slate-500">
          Your <code>.env</code> names the database with the old key{" "}
          <code>CCT_SA_DSN</code>; it still works, and Save writes it as{" "}
          <code>CCT_SA_DB</code>.
        </p>
      )}
      {cfg.dsn_overridden && (
        // The single most confusing thing this page could do is show a
        // database that is not the one producing the numbers next door.
        <div className="text-sm bg-amber-50 border border-amber-200 rounded p-3">
          <span className="font-medium text-amber-900">
            The running server is using a different database than the one saved
            below.
          </span>
          <p className="text-xs text-amber-800 mt-1">
            In use now:{" "}
            <code className="bg-white border border-amber-200 px-1 rounded font-mono">
              {cfg.effective_dsn}
            </code>{" "}
            — passed with <code>--db</code> when the server started, which wins
            over the saved value. Every figure in the Dashboard comes from that
            store, not from the one in this form.
          </p>
        </div>
      )}

      <Card title="Configuration (.env — shared with the CLI)">
        <div className="space-y-6">
          {GROUPS.map((g) => {
            const inGroup = cfg.fields.filter((f) => {
              if (!g.keys.includes(f.key)) return false;
              // Judge group: show only what the chosen backend uses.
              if (g.keys.includes("CCT_SA_JUDGE_BACKEND")) {
                const backend = values["CCT_SA_JUDGE_BACKEND"] || "";
                const allowed =
                  JUDGE_FIELDS_BY_BACKEND[backend] || JUDGE_FIELDS_OPENAI;
                return allowed.includes(f.key);
              }
              return true;
            });
            if (inGroup.length === 0) return null;
            return (
              <fieldset key={g.title} className="border border-slate-200 rounded p-3">
                <legend className="text-sm font-semibold text-slate-700 px-1">
                  {g.title}
                </legend>
                <p className="text-xs text-slate-500 mb-3">{g.blurb}</p>
                <div className="space-y-3">
          {inGroup.map((f) => {
            const m = META[f.key] || { label: f.key };
            return (
              <div key={f.key}>
                <div className="flex items-center gap-1.5">
                  <label className="block text-sm font-medium text-slate-700">
                    {m.label}
                  </label>
                  {(m.help || m.example) && (
                    <button
                      type="button"
                      aria-expanded={openHelp === f.key}
                      aria-label={`What is ${m.label}?`}
                      title={`What is ${m.label}?`}
                      onClick={() =>
                        setOpenHelp(openHelp === f.key ? null : f.key)
                      }
                      className={
                        "w-4 h-4 shrink-0 rounded-full border text-[10px] leading-none " +
                        "flex items-center justify-center " +
                        (openHelp === f.key
                          ? "border-blue-500 bg-blue-500 text-white"
                          : "border-slate-300 bg-white text-slate-500 hover:border-slate-400 hover:text-slate-700")
                      }
                    >
                      ?
                    </button>
                  )}
                </div>
                {m.type === "redaction" ? (
                  <select
                    className="border border-slate-300 bg-white text-slate-900 rounded px-2 py-1 text-sm w-full"
                    value={values[f.key] || "code"}
                    onChange={(e) => set(f.key, e.target.value)}
                  >
                    {cfg.redaction_modes.map((r) => (
                      <option key={r} value={r}>{r}</option>
                    ))}
                  </select>
                ) : m.type === "backend" ? (
                  <select
                    className="border border-slate-300 bg-white text-slate-900 rounded px-2 py-1 text-sm w-full"
                    value={values[f.key] || ""}
                    onChange={(e) => set(f.key, e.target.value)}
                  >
                    <option value="">Packaged default — local Ollama</option>
                    {cfg.judge_backends.map((b) => (
                      <option key={b} value={b}>{b}</option>
                    ))}
                  </select>
                ) : m.type === "embed-backend" ? (
                  <select
                    className="border border-slate-300 bg-white text-slate-900 rounded px-2 py-1 text-sm w-full"
                    value={values[f.key] || ""}
                    onChange={(e) => set(f.key, e.target.value)}
                  >
                    <option value="">Packaged default — local Ollama</option>
                    {cfg.embedding_backends.map((b) => (
                      <option key={b} value={b}>{b}</option>
                    ))}
                  </select>
                ) : f.key === "CCT_SA_EMBED_MODEL" && !embedOther && embedListState === "loading" ? (
                  <select
                    disabled
                    className="border border-slate-300 bg-slate-50 text-slate-500 rounded px-2 py-1 text-sm w-full font-mono"
                  >
                    <option>{values[f.key] ? `${values[f.key]} — listing the server's models…` : "listing the server's models…"}</option>
                  </select>
                ) : f.key === "CCT_SA_EMBED_MODEL" && !embedOther && !embedModelList ? (
                  <div>
                    <input
                      type="text"
                      value={values[f.key] || ""}
                      onChange={(e) => set(f.key, e.target.value)}
                      placeholder={m.placeholder}
                      className="border border-slate-300 bg-white text-slate-900 rounded px-2 py-1 text-sm w-full font-mono"
                    />
                    <p className="text-xs text-rose-700 mt-1">
                      {embedModels && embedModels.url
                        ? `Could not list models at ${embedModels.url}${embedModels.error ? ` (${embedModels.error})` : ""}`
                        : embedModels && embedBackend !== embedModels.backend
                          ? "The list is for the saved backend — Save, then it refreshes."
                          : "Could not reach the API to list models."}{" "}
                      <button type="button" onClick={loadModels} className="text-blue-700 hover:underline">
                        Retry
                      </button>
                    </p>
                  </div>
                ) : f.key === "CCT_SA_EMBED_MODEL" && embedModelList && !embedOther ? (
                  <div className="flex gap-2 items-center">
                    <select
                      className="border border-slate-300 bg-white text-slate-900 rounded px-2 py-1 text-sm w-full font-mono"
                      value={values[f.key] || ""}
                      onChange={(e) => {
                        if (e.target.value === "__other__") setEmbedOther(true);
                        else set(f.key, e.target.value);
                      }}
                    >
                      <option value="">— choose an embedding model —</option>
                      {embedModelList.map((name) => (
                        <option key={name} value={name}>{name}</option>
                      ))}
                      {values[f.key] && !embedModelList.includes(values[f.key]) && (
                        <option value={values[f.key]}>
                          {values[f.key]}
                          {embedModels?.not_embedding?.includes(values[f.key])
                            ? " (a chat model — cannot embed)"
                            : " (not served)"}
                        </option>
                      )}
                      <option value="__other__">Other…</option>
                    </select>
                    <span className="shrink-0 text-xs text-slate-500">
                      {embedModelList.length === 1 ? "1 embedding model" : `${embedModelList.length} embedding models`} on the server
                      {embedModels?.not_embedding?.length
                        ? ` · ${embedModels.not_embedding.length} chat model${embedModels.not_embedding.length === 1 ? "" : "s"} left out`
                        : ""}
                      {embedModelList.length === 0 && (
                        <span className="block text-amber-700">
                          None can embed. Pull one first: <code>ollama pull nomic-embed-text</code>
                        </span>
                      )}
                    </span>
                  </div>
                ) : f.key === "CCT_SA_JUDGE_MODEL" && modelList && !modelOther ? (
                  <div className="flex gap-2 items-center">
                    <select
                      className="border border-slate-300 bg-white text-slate-900 rounded px-2 py-1 text-sm w-full font-mono"
                      // The saved value stays selected even when the
                      // catalogue lacks it — it is what will run.
                      value={values[f.key] || ""}
                      onChange={(e) => {
                        if (e.target.value === "__other__") setModelOther(true);
                        else set(f.key, e.target.value);
                      }}
                    >
                      <option value="">the backend&apos;s default</option>
                      {modelList.map((name) => (
                        <option key={name} value={name}>{name}</option>
                      ))}
                      {values[f.key] && !modelList.includes(values[f.key]) && (
                        <option value={values[f.key]}>{values[f.key]} (not served)</option>
                      )}
                      <option value="__other__">Other…</option>
                    </select>
                    <span className="shrink-0 text-xs text-slate-500">
                      {modelList.length === 1 ? "1 model" : `${modelList.length} models`} on the server
                    </span>
                  </div>
                ) : (
                  <div className="flex gap-2">
                  <input
                    type={m.type === "password" ? "password" : m.type === "number" ? "number" : "text"}
                    className="border border-slate-300 bg-white text-slate-900 rounded px-2 py-1 text-sm w-full font-mono"
                    placeholder={
                      f.secret && f.has_value
                        ? "•••••• (unchanged)"
                        : m.placeholder || ""
                    }
                    value={values[f.key] || ""}
                    onChange={(e) => set(f.key, e.target.value)}
                  />
                  {f.key === "CCT_SA_JUDGE_MODEL" && models && (
                    <span className="shrink-0 self-center text-xs text-slate-500">
                      {modelOther
                        ? "typed name"
                        : effectiveBackend !== savedBackend
                          ? "save to list this backend's models"
                          : models.reachable
                            ? ""
                            : models.url
                              ? `not reachable at ${models.url}`
                              : ""}
                    </span>
                  )}
                  {m.browse && (
                    <button
                      type="button"
                      onClick={() => setPicking({ key: f.key, mode: m.browse! })}
                      className="shrink-0 border border-slate-300 bg-white text-slate-700 text-sm px-3 rounded hover:bg-slate-50"
                    >
                      Browse…
                    </button>
                  )}
                  </div>
                )}
                {openHelp === f.key && (m.help || m.example) && (
                  <div className="mt-1 text-xs text-slate-700 bg-slate-50 border border-slate-200 rounded p-2">
                    {m.help && <p>{m.help}</p>}
                    {m.example && (
                      <p className="mt-1">
                        <span className="text-slate-500">e.g.</span>{" "}
                        <code className="bg-white border border-slate-200 px-1 rounded font-mono">
                          {m.example}
                        </code>
                      </p>
                    )}
                    {/* Defaults are NOT repeated here — the field's own
                        placeholder shows what applies when it is blank,
                        which is where you are already looking. */}
                  </div>
                )}
              </div>
            );
          })}
                </div>
              </fieldset>
            );
          })}
        </div>

        {cloudJudge && (
          <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded p-2 mt-3">
            ⚠ This judge sends redacted turn previews off your network. Choose Ollama, or a
            server on this machine or your LAN, for a fully-local judge.
          </p>
        )}

        {/* Both probes read the SAVED file, not the form: Save first.
            "Test judge" sends one tiny prompt to the judge the settings
            resolve to and shows the answer or the backend's own reason. */}
        <div className="mt-4 flex items-center gap-3 flex-wrap">
          <button onClick={save} className="bg-blue-600 text-white text-sm px-4 py-1.5 rounded hover:bg-blue-700">Save</button>
          <button onClick={testConn} className="bg-slate-800 text-white text-sm px-4 py-1.5 rounded hover:bg-slate-700">Test database</button>
          <button onClick={testJudge} className="bg-slate-800 text-white text-sm px-4 py-1.5 rounded hover:bg-slate-700">
            Test judge LLM
          </button>
          <button onClick={testEmbedding} className="bg-slate-800 text-white text-sm px-4 py-1.5 rounded hover:bg-slate-700">
            Test embedding
          </button>
          {saved && <span className="text-sm text-slate-600">{saved}</span>}
        </div>
        <p className="mt-2 text-xs text-slate-500">
          Judge in effect:{" "}
          <code className="bg-slate-100 px-1 rounded">{models?.configured.spec ?? cfg.judge_default}</code>
          {models?.configured.source === "settings" ? " (from your saved settings)" : " (the packaged default)"}
          {models && models.url ? (
            models.reachable ? (
              <span> · {models.models.length === 1 ? "1 model" : `${models.models.length} models`} on the server at {models.url}</span>
            ) : (
              <span className="text-rose-700">
                {" "}· could not list models at {models.list_url ?? models.url} ({models.error})
              </span>
            )
          ) : null}
          . Embedding in effect:{" "}
          <code className="bg-slate-100 px-1 rounded">
            {embedModels?.configured.model_set ? embedModels.configured.spec : "none — choose an embedding model above"}
          </code>
          . All three tests use the saved settings — Save first.
        </p>
        <ProbeBox result={probe} />
        <ProbeBox result={judgeProbe} />
        <ProbeBox result={embedProbe} />
      </Card>

      <Card title="Effective per-project redaction">
        <p className="text-xs text-slate-400 mb-3">
          Read-only — the redaction mode each project’s already-ingested sessions were recorded
          with. To change redaction for future ingests, edit the per-project config file.
        </p>
        {projectsError ? (
          <ErrorNote error={projectsError} />
        ) : projects === null ? (
          <Loading />
        ) : projects.length === 0 ? (
          <p className="text-sm text-slate-500">No per-project data yet — ingest some sessions.</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-slate-500 border-b border-slate-200">
                <th className="py-1 font-medium">Project</th>
                <th className="py-1 font-medium text-right">Sessions</th>
                <th className="py-1 font-medium">Effective redaction</th>
              </tr>
            </thead>
            <tbody>
              {projects.map((p) => (
                <tr key={p.project_path} className="border-b border-slate-100 last:border-0">
                  <td className="py-1 font-mono text-xs truncate max-w-xs" title={p.project_path}>
                    {p.project_path}
                  </td>
                  <td className="py-1 text-right tabular-nums">{p.session_count}</td>
                  <td className="py-1">
                    {p.effective_redaction_mode === "mixed" ? (
                      <span>
                        mixed{" "}
                        <span className="text-xs text-slate-400">
                          (
                          {Object.entries(p.redaction_modes)
                            .map(([mode, count]) => `${mode}: ${count}`)
                            .join(", ")}
                          )
                        </span>
                      </span>
                    ) : (
                      p.effective_redaction_mode
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}

// Answers the first question a person has on this page when a field
// misbehaves: is the API even there? Polled, so a restart shows up.
function ApiPill() {
  const { data, error } = useApi(() => api.health(), [], 10000);
  const ok = !!data && !error;
  return (
    <span
      className={
        "text-xs px-2 py-1 rounded font-medium " +
        (ok ? "bg-emerald-100 text-emerald-800" : "bg-rose-100 text-rose-800")
      }
      title={ok ? "GET /api/health answered" : "GET /api/health did not answer"}
    >
      {ok ? "API reachable" : "API not reachable"}
    </span>
  );
}
