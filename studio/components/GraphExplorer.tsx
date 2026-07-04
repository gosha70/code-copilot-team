"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { Card } from "@/components/ui";

const NODE_COLORS: Record<string, string> = {
  Session: "#3b82f6",
  Turn: "#64748b",
  ToolInvocation: "#06b6d4",
  FileNode: "#f59e0b",
  ErrorNode: "#ef4444",
  Workspace: "#f59e0b",
  Agent: "#ec4899",
  Model: "#06b6d4",
  Copilot: "#8b5cf6",
  Developer: "#10b981",
};

const TEMPLATES: { label: string; cypher: string }[] = [
  { label: "Tools that fail most", cypher: "MATCH (i:ToolInvocation) RETURN i.tool_name AS tool, count(i) AS n ORDER BY n DESC LIMIT 20" },
  { label: "Sessions + turn counts", cypher: "MATCH (s:Session) RETURN s.session_key AS session, s.turn_count AS turns ORDER BY turns DESC LIMIT 20" },
  { label: "Errors by tool", cypher: "MATCH (e:ErrorNode) RETURN e.tool_name AS tool, count(e) AS errors ORDER BY errors DESC LIMIT 20" },
];

export default function GraphExplorer() {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<any>(null);
  const [counts, setCounts] = useState<Record<string, number> | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [cypher, setCypher] = useState(TEMPLATES[0].cypher);
  const [rows, setRows] = useState<Record<string, unknown>[] | null>(null);
  const [queryErr, setQueryErr] = useState<string | null>(null);

  // Load node counts + render a summary graph.
  useEffect(() => {
    let cy: any;
    let cancelled = false;
    (async () => {
      try {
        const data = await api.graphCounts();
        if (cancelled) return;
        setCounts(data.node_counts);

        const [{ default: cytoscape }, fcoseMod] = await Promise.all([
          import("cytoscape"),
          import("cytoscape-fcose"),
        ]);
        // @ts-ignore — plugin registration
        cytoscape.use(fcoseMod.default);

        const elements: any[] = [];
        elements.push({ data: { id: "ROOT", label: "Graph", type: "Root" } });
        Object.entries(data.node_counts).forEach(([label, n]) => {
          elements.push({ data: { id: label, label: `${label} (${n})`, type: label } });
          elements.push({ data: { source: "ROOT", target: label } });
        });

        cy = cytoscape({
          container: containerRef.current,
          elements,
          style: [
            {
              selector: "node",
              style: {
                label: "data(label)",
                "background-color": (ele: any) => NODE_COLORS[ele.data("type")] || "#94a3b8",
                color: "#1e293b",
                "font-size": 10,
                "text-valign": "bottom",
                width: 26,
                height: 26,
              },
            },
            { selector: "edge", style: { width: 1, "line-color": "#cbd5e1", "curve-style": "bezier" } },
          ],
          layout: { name: "fcose", animate: false } as any,
        });
        cyRef.current = cy;

        // Tap a node-type bubble to expand sample members of that type.
        cy.on("tap", "node", async (evt: any) => {
          const node = evt.target;
          const label = node.data("type");
          if (!label || label === "Root") return;
          await expandLabel(cy, label);
        });
      } catch (e) {
        if (!cancelled) setErr(String(e));
      }
    })();
    return () => {
      cancelled = true;
      if (cy) cy.destroy();
    };
  }, []);

  async function expandLabel(cy: any, label: string) {
    // Pull a few real nodes of this type and attach them (double-tap-to-
    // expand gesture; each added node carries its key for further expansion).
    const keyField = label === "Session" ? "session_key" : label === "FileNode" ? "path" : null;
    if (!keyField) return;
    try {
      const res = await api.graphQuery(
        `MATCH (n:${label}) RETURN n.${keyField} AS k LIMIT 8`,
      );
      res.rows.forEach((r) => {
        const k = String(r["k"]);
        const id = `${label}:${k}`;
        if (cy.getElementById(id).length === 0) {
          cy.add([
            { data: { id, label: k.slice(0, 24), type: label, keyField, keyValue: k } },
            { data: { source: label, target: id } },
          ]);
        }
      });
      cy.layout({ name: "fcose", animate: false } as any).run();
    } catch {
      /* graph not built / kuzu missing — ignore in the visual */
    }
  }

  async function runQuery() {
    setQueryErr(null);
    setRows(null);
    try {
      const res = await api.graphQuery(cypher);
      setRows(res.rows);
    } catch (e) {
      setQueryErr(String(e));
    }
  }

  return (
    <div className="space-y-4">
      {err && (
        <div className="bg-amber-50 border border-amber-200 text-amber-800 rounded p-3 text-sm">
          Graph unavailable: {err}. Build it with{" "}
          <code>./scripts/session-analytics graph --rebuild</code> (needs the{" "}
          <code>kuzu</code> package).
        </div>
      )}

      <div className="grid lg:grid-cols-3 gap-4">
        <Card title="Explorer" className="lg:col-span-2">
          <div
            ref={containerRef}
            className="w-full h-[420px] bg-slate-50 rounded border border-slate-200"
          />
          <p className="text-xs text-slate-400 mt-2">
            Tap a node-type bubble to expand sample members.
          </p>
        </Card>

        <Card title="Node counts">
          {counts ? (
            <ul className="text-sm space-y-1">
              {Object.entries(counts).map(([k, v]) => (
                <li key={k} className="flex justify-between">
                  <span className="flex items-center gap-2">
                    <span
                      className="inline-block w-3 h-3 rounded-full"
                      style={{ background: NODE_COLORS[k] || "#94a3b8" }}
                    />
                    {k}
                  </span>
                  <span className="tabular-nums text-slate-500">{v}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-slate-400">—</p>
          )}
        </Card>
      </div>

      <Card title="Cypher query (read-only)">
        <div className="flex gap-2 mb-2">
          <select
            className="border border-slate-300 rounded px-2 py-1 text-sm"
            onChange={(e) => setCypher(e.target.value)}
          >
            {TEMPLATES.map((t) => (
              <option key={t.label} value={t.cypher}>
                {t.label}
              </option>
            ))}
          </select>
          <button
            onClick={runQuery}
            className="bg-blue-600 text-white text-sm px-4 py-1 rounded hover:bg-blue-700"
          >
            Run
          </button>
        </div>
        <textarea
          className="w-full border border-slate-300 rounded p-2 text-sm font-mono h-20"
          value={cypher}
          onChange={(e) => setCypher(e.target.value)}
        />
        {queryErr && <p className="text-red-600 text-sm mt-2">{queryErr}</p>}
        {rows && (
          <div className="mt-3 max-h-64 overflow-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-slate-500 border-b">
                <tr>
                  {rows[0] && Object.keys(rows[0]).map((c) => <th key={c} className="py-1">{c}</th>)}
                </tr>
              </thead>
              <tbody>
                {rows.map((r, i) => (
                  <tr key={i} className="border-b border-slate-100">
                    {Object.values(r).map((v, j) => (
                      <td key={j} className="py-1 tabular-nums">{String(v)}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
            {rows.length === 0 && <p className="text-slate-400 text-sm">No rows.</p>}
          </div>
        )}
      </Card>
    </div>
  );
}
