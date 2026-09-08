// What the Graph page draws, as data — pure, so the states script can
// assert it without a browser.
//
// The picture is of ONE thing (a session, or a project) and what it is
// connected to, every edge named by its relationship. The 65k-turn
// layer is never drawn one node per turn: tools are one bubble per
// tool sized by calls, files one per file, and the rest is one hop.

import type {
  GraphElements,
  ProjectNeighbourhood,
  SessionNeighbourhood,
} from "@/lib/api";

export interface ViewNode {
  id: string;
  label: string;
  /** Node kind for colour and click behaviour. */
  type: string;
  /** Bubble diameter in px. */
  size: number;
  /** Carried through to the click handler. */
  data: Record<string, unknown>;
  /** Red ring: this thing errored. */
  errored?: boolean;
  centre?: boolean;
  /** Concentric ring: 4 = centre, 3 = context, 2 = tools/sessions, 1 = files/similar. */
  ring?: number;
}

export interface ViewEdge {
  source: string;
  target: string;
  /** The relationship name, drawn on the edge. */
  rel: string;
  /** Optional detail beside the name (a score, a count). */
  note?: string;
  weight?: number;
}

export interface View {
  nodes: ViewNode[];
  edges: ViewEdge[];
}

export const NODE_COLORS: Record<string, string> = {
  Session: "#3b82f6",
  Turn: "#64748b",
  ToolInvocation: "#06b6d4",
  Tool: "#06b6d4",
  FileNode: "#f59e0b",
  File: "#f59e0b",
  ErrorNode: "#ef4444",
  Workspace: "#a16207",
  Agent: "#ec4899",
  Model: "#0ea5e9",
  Copilot: "#8b5cf6",
  Developer: "#10b981",
};

const MIN_SIZE = 18;
const MAX_SIZE = 56;

/** Bubble diameter proportional to a count, on a square-root scale so
 *  2,722 bash calls do not make every other tool invisible. */
export function bubbleSize(count: number, max: number): number {
  if (max <= 0 || count <= 0) return MIN_SIZE;
  const r = Math.sqrt(count / max);
  return Math.round(MIN_SIZE + (MAX_SIZE - MIN_SIZE) * Math.min(1, r));
}

/** The last path segment, for a label; the full path stays in data. */
export function shortName(path: string): string {
  const parts = path.replace(/\/+$/, "").split("/");
  return parts[parts.length - 1] || path;
}

export function shortSessionKey(key: string): string {
  const native = key.includes(":") ? key.slice(key.indexOf(":") + 1) : key;
  return native.length > 12 ? native.slice(0, 8) + "…" : native;
}

export function sessionView(n: SessionNeighbourhood): View {
  const c = n.centre;
  const centreId = `Session:${c.session_key}`;
  const nodes: ViewNode[] = [
    {
      id: centreId,
      label: `${c.project_path ? shortName(c.project_path) : "session"} · ${c.turn_count.toLocaleString()} turns`,
      type: "Session",
      size: 44,
      centre: true,
      ring: 4,
      errored: c.error_count > 0,
      data: { sessionId: c.id, sessionKey: c.session_key },
    },
  ];
  const edges: ViewEdge[] = [];
  for (const ctx of n.context) {
    const id = `${ctx.label}:${ctx.key}`;
    nodes.push({
      id,
      label: ctx.label === "Workspace" ? shortName(ctx.key) : ctx.key,
      type: ctx.label,
      size: 26,
      ring: 3,
      data: {
        key: ctx.key,
        kind: ctx.label,
        projectPath: ctx.label === "Workspace" ? ctx.key : undefined,
      },
    });
    edges.push({ source: centreId, target: id, rel: ctx.rel });
  }
  const maxCalls = Math.max(0, ...n.tools.map((t) => t.calls));
  for (const t of n.tools) {
    const id = `Tool:${t.tool}`;
    nodes.push({
      id,
      label: `${t.tool} ×${t.calls.toLocaleString()}${t.errors ? ` (${t.errors} err)` : ""}`,
      type: "Tool",
      size: bubbleSize(t.calls, maxCalls),
      ring: 2,
      errored: t.errors > 0,
      data: { tool: t.tool, calls: t.calls, errors: t.errors, sessionId: c.id },
    });
    edges.push({
      source: centreId,
      target: id,
      rel: "INVOKED",
      note: `×${t.calls}`,
      weight: t.calls,
    });
  }
  const maxAcc = Math.max(0, ...n.files.map((f) => f.accesses));
  for (const f of n.files) {
    const id = `File:${f.path}`;
    nodes.push({
      id,
      label: shortName(f.path),
      type: "File",
      size: bubbleSize(f.accesses, maxAcc),
      ring: 1,
      data: { path: f.path, accesses: f.accesses, accessTypes: f.access_types },
    });
    edges.push({
      source: centreId,
      target: id,
      rel: "ACCESSED_FILE",
      note: f.access_types.join("/"),
    });
  }
  for (const s of n.similar) {
    const id = `Session:${s.session_key}`;
    if (nodes.some((x) => x.id === id)) continue;
    nodes.push({
      id,
      label: `${s.project_path ? shortName(s.project_path) : shortSessionKey(s.session_key)} · ${s.turn_count.toLocaleString()} turns`,
      type: "Session",
      size: 28,
      ring: 1,
      data: { sessionId: s.id, sessionKey: s.session_key, score: s.score },
    });
    edges.push({
      source: centreId,
      target: id,
      rel: "SIMILAR_TO",
      note: s.score.toFixed(2),
    });
  }
  return { nodes, edges };
}

export function projectView(p: ProjectNeighbourhood): View {
  const wsId = `Workspace:${p.project_path}`;
  const nodes: ViewNode[] = [
    {
      id: wsId,
      label: shortName(p.project_path),
      type: "Workspace",
      size: 44,
      centre: true,
      ring: 4,
      data: { projectPath: p.project_path, kind: "Workspace" },
    },
  ];
  const edges: ViewEdge[] = [];
  const maxTurns = Math.max(0, ...p.sessions.map((s) => s.turn_count));
  const known = new Set<string>();
  for (const s of p.sessions) {
    const id = `Session:${s.session_key}`;
    known.add(id);
    nodes.push({
      id,
      label: `${s.started_at ? s.started_at.slice(0, 10) : shortSessionKey(s.session_key)} · ${s.turn_count.toLocaleString()}`,
      type: "Session",
      size: bubbleSize(s.turn_count, maxTurns),
      ring: 2,
      errored: s.error_count > 0,
      data: { sessionId: s.id, sessionKey: s.session_key },
    });
    edges.push({ source: id, target: wsId, rel: "IN_WORKSPACE" });
  }
  const seen = new Set<string>();
  for (const e of p.similar_edges) {
    const a = `Session:${e.source}`;
    const b = `Session:${e.target}`;
    const pair = [a, b].sort().join("|");
    if (!known.has(a) || !known.has(b) || seen.has(pair)) continue;
    seen.add(pair);
    edges.push({
      source: a,
      target: b,
      rel: "SIMILAR_TO",
      note: e.score.toFixed(2),
    });
  }
  for (const m of p.models) {
    const id = `Model:${m.model}`;
    nodes.push({
      id,
      label: `${m.model} · ${m.sessions}`,
      type: "Model",
      size: 24,
      ring: 3,
      data: { key: m.model, kind: "Model" },
    });
    edges.push({
      source: wsId,
      target: id,
      rel: "USED_MODEL",
      note: `${m.sessions} sessions`,
    });
  }
  return { nodes, edges };
}

/** Catalogue results that carry Kùzu nodes and relationships. */
export function elementsView(el: GraphElements): View {
  const nodes: ViewNode[] = el.nodes.map((n) => ({
    id: n.id,
    label:
      n.label === "Session"
        ? `${typeof n.props.project_path === "string" ? shortName(n.props.project_path) : shortSessionKey(n.key)}${
            typeof n.props.turn_count === "number"
              ? ` · ${n.props.turn_count}`
              : ""
          }`
        : n.label === "Workspace" || n.label === "FileNode"
          ? shortName(n.key)
          : n.key,
    type: n.label,
    size: n.label === "Session" ? 30 : 24,
    data: {
      key: n.key,
      kind: n.label,
      sessionKey: n.label === "Session" ? n.key : undefined,
      projectPath: n.label === "Workspace" ? n.key : undefined,
      path: n.label === "FileNode" ? n.key : undefined,
    },
  }));
  const edges: ViewEdge[] = el.edges.map((e) => ({
    source: e.source,
    target: e.target,
    rel: e.rel,
    note:
      typeof e.props.score === "number"
        ? (e.props.score as number).toFixed(2)
        : undefined,
  }));
  return { nodes, edges };
}

/** One line that says what a view shows, in relationships. Pure. */
export function viewSummary(view: View): string {
  const rels = new Map<string, number>();
  for (const e of view.edges) rels.set(e.rel, (rels.get(e.rel) ?? 0) + 1);
  const parts = [...rels.entries()]
    .sort((a, b) => b[1] - a[1])
    .map(([r, n]) => `${r} ×${n}`);
  return `${view.nodes.length} things, ${view.edges.length} relationships${parts.length ? ": " + parts.join(", ") : ""}`;
}
