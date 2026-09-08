"use client";

import { useEffect, useMemo, useState } from "react";
import { CatalogueEntry, CatalogueResult, api } from "@/lib/api";
import { Card, describeError } from "@/components/ui";

// QUESTIONS, NOT CYPHER. The catalogue is data (config_data/
// graph-queries.json): each entry is a question in words, grouped the
// way Kiro Analyzer groups them — search (find things), detail (one
// thing), pattern (across things) — with the parameters it needs and
// how its answer is shown: a table, a bar chart, or drawn on the
// canvas when the rows are nodes and relationships. Raw Cypher stays,
// for people who read it.

export const INTENT_LABEL: Record<CatalogueEntry["intent"], string> = {
  search: "Find",
  detail: "One thing",
  pattern: "Across everything",
};

/** Rows → (label, value) pairs for a bar chart: the first column is the
 *  label, the first NUMERIC column the value. Pure. */
export function barData(
  columns: string[],
  rows: Record<string, unknown>[],
): { label: string; value: number }[] {
  if (!columns.length) return [];
  const labelCol = columns[0];
  const valueCol = columns.find(
    (c, i) => i > 0 && rows.some((r) => typeof r[c] === "number"),
  );
  if (!valueCol) return [];
  return rows.map((r) => ({
    label: String(r[labelCol] ?? ""),
    value: Number(r[valueCol] ?? 0),
  }));
}

export default function CatalogueCard({
  entries,
  sessionKey,
  projectPath,
  onResult,
}: {
  entries: CatalogueEntry[];
  /** The session in focus: fills a query's session parameter. */
  sessionKey: string | null;
  projectPath: string | null;
  onResult: (r: CatalogueResult) => void;
}) {
  const [chosen, setChosen] = useState<string>("");
  const [params, setParams] = useState<Record<string, string>>({});
  const [result, setResult] = useState<CatalogueResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [cypher, setCypher] = useState(
    "MATCH (s:Session) RETURN s.session_key AS session, s.turn_count AS turns ORDER BY turns DESC LIMIT 20",
  );
  const [rawRows, setRawRows] = useState<Record<string, unknown>[] | null>(
    null,
  );
  const [rawErr, setRawErr] = useState<string | null>(null);

  const entry = useMemo(
    () => entries.find((e) => e.id === chosen) ?? null,
    [entries, chosen],
  );

  // A query's session/project parameter follows the focus unless the
  // person typed something else.
  useEffect(() => {
    if (!entry) return;
    setParams((p) => {
      const next = { ...p };
      for (const spec of entry.params) {
        if (spec.type === "session" && sessionKey && !next[spec.name])
          next[spec.name] = sessionKey;
        if (spec.type === "project" && projectPath && !next[spec.name])
          next[spec.name] = projectPath;
      }
      return next;
    });
  }, [entry, sessionKey, projectPath]);

  async function run() {
    if (!entry) return;
    setBusy(true);
    setErr(null);
    try {
      const r = await api.graphCatalogueRun(entry.id, params);
      setResult(r);
      onResult(r);
    } catch (e) {
      setErr(describeError(e));
    } finally {
      setBusy(false);
    }
  }

  async function runRaw() {
    setRawErr(null);
    setRawRows(null);
    try {
      setRawRows((await api.graphQuery(cypher)).rows);
    } catch (e) {
      setRawErr(describeError(e));
    }
  }

  const groups = (["search", "detail", "pattern"] as const).map((g) => ({
    intent: g,
    items: entries.filter((e) => e.intent === g),
  }));

  return (
    <Card title="Ask the graph a question">
      <div className="flex items-start gap-3 flex-wrap">
        <select
          value={chosen}
          onChange={(e) => {
            setChosen(e.target.value);
            setResult(null);
          }}
          className="border border-slate-300 bg-white text-slate-900 rounded px-2 py-1 text-sm max-w-md"
        >
          <option value="">— choose a question —</option>
          {groups.map((g) => (
            <optgroup key={g.intent} label={INTENT_LABEL[g.intent]}>
              {g.items.map((e) => (
                <option key={e.id} value={e.id}>
                  {e.name}
                </option>
              ))}
            </optgroup>
          ))}
        </select>
        {entry?.params.map((spec) => (
          <label
            key={spec.name}
            className="text-xs text-slate-500 flex items-center gap-1"
          >
            {spec.label}
            <input
              type="text"
              value={params[spec.name] ?? ""}
              onChange={(e) =>
                setParams((p) => ({ ...p, [spec.name]: e.target.value }))
              }
              placeholder={spec.required ? "required" : "blank = all"}
              className="border border-slate-300 bg-white text-slate-900 rounded px-2 py-1 text-sm font-mono w-64"
            />
          </label>
        ))}
        <button
          type="button"
          onClick={run}
          disabled={!entry || busy}
          className="bg-blue-600 text-white text-sm px-4 py-1.5 rounded hover:bg-blue-700 disabled:opacity-50"
        >
          {busy ? "Running…" : "Answer"}
        </button>
      </div>
      {entry && <p className="text-sm text-slate-600 mt-2">{entry.question}</p>}
      {err && <p className="text-sm text-rose-700 mt-2">{err}</p>}

      {result && result.render === "graph" && (
        <p className="text-sm text-slate-600 mt-3">
          Drawn on the canvas above: {result.elements?.nodes.length ?? 0}{" "}
          things, {result.elements?.edges.length ?? 0} relationships. Click a
          session there to recentre on it.
        </p>
      )}
      {result && result.render === "bar" && (
        <Bars columns={result.columns} rows={result.rows} />
      )}
      {result && result.render === "table" && (
        <Table columns={result.columns} rows={result.rows} />
      )}
      {result && result.render !== "graph" && result.rows.length === 0 && (
        <p className="text-sm text-slate-500 mt-3">
          No rows — the graph holds nothing matching this question.
        </p>
      )}

      <details className="mt-4">
        <summary className="text-xs text-slate-500 cursor-pointer">
          Raw Cypher (read-only)
        </summary>
        <div className="mt-2 grid lg:grid-cols-3 gap-3">
          <div className="lg:col-span-2">
            <textarea
              value={cypher}
              onChange={(e) => setCypher(e.target.value)}
              rows={3}
              className="w-full border border-slate-300 bg-white text-slate-900 rounded px-2 py-1 text-xs font-mono"
            />
            <button
              type="button"
              onClick={runRaw}
              className="mt-1 border border-slate-300 bg-white text-slate-700 text-xs px-3 py-1 rounded hover:bg-slate-50"
            >
              Run
            </button>
            {rawErr && <p className="text-xs text-rose-700 mt-1">{rawErr}</p>}
            {rawRows && (
              <Table
                columns={rawRows[0] ? Object.keys(rawRows[0]) : []}
                rows={rawRows}
              />
            )}
          </div>
          <div className="text-[11px] text-slate-500 font-mono leading-5">
            <div className="text-slate-600 font-sans font-medium mb-1">
              Schema
            </div>
            Session, Turn, ToolInvocation, FileNode, ErrorNode, Workspace,
            Model, Copilot, Developer, Agent
            <br />
            Session-HAS_TURN→Turn · Turn-INVOKED→ToolInvocation ·
            ToolInvocation-ACCESSED_FILE→FileNode ·
            ToolInvocation-PRODUCED_ERROR→ErrorNode ·
            Session-IN_WORKSPACE→Workspace · Session-USED_MODEL→Model ·
            Session-RAN_ON→Copilot · Session-BY_DEVELOPER→Developer ·
            Session-USED_AGENT→Agent · Turn-FOLLOWED_BY→Turn ·
            ToolInvocation-RETRIED→ToolInvocation · Session-SIMILAR_TO→Session
            (score)
          </div>
        </div>
      </details>
    </Card>
  );
}

function Bars({
  columns,
  rows,
}: {
  columns: string[];
  rows: Record<string, unknown>[];
}) {
  const data = barData(columns, rows);
  if (!data.length) return <Table columns={columns} rows={rows} />;
  const max = Math.max(1, ...data.map((d) => d.value));
  return (
    <div className="mt-3 space-y-1">
      {data.slice(0, 25).map((d) => (
        <div key={d.label} className="flex items-center gap-2 text-xs">
          <span
            className="w-56 truncate text-right text-slate-700"
            title={d.label}
          >
            {d.label.includes("/")
              ? d.label.split("/").filter(Boolean).slice(-1)[0]
              : d.label}
          </span>
          <div className="flex-1 h-4 bg-slate-100 rounded overflow-hidden">
            <div
              className="h-4 rounded bg-blue-600"
              style={{ width: `${Math.round((d.value / max) * 100)}%` }}
            />
          </div>
          <span className="w-16 tabular-nums text-slate-600">
            {d.value.toLocaleString()}
          </span>
        </div>
      ))}
    </div>
  );
}

function Table({
  columns,
  rows,
}: {
  columns: string[];
  rows: Record<string, unknown>[];
}) {
  if (!rows.length) return null;
  return (
    <div className="mt-3 overflow-x-auto">
      <table className="text-xs w-full">
        <thead className="text-left text-slate-500 border-b border-slate-200">
          <tr>
            {columns.map((c) => (
              <th key={c} className="py-1 pr-3 font-medium">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.slice(0, 100).map((r, i) => (
            <tr key={i} className="border-b border-slate-100">
              {columns.map((c) => (
                <td
                  key={c}
                  className="py-1 pr-3 font-mono whitespace-nowrap max-w-[28rem] truncate"
                  title={String(r[c] ?? "")}
                >
                  {typeof r[c] === "number"
                    ? (r[c] as number).toLocaleString()
                    : String(r[c] ?? "")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
