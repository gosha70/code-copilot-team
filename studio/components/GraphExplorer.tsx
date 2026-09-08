"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  api,
  CatalogueEntry,
  CatalogueResult,
  FileSessions,
  ProjectNeighbourhood,
  SessionNeighbourhood,
  SessionRow,
  ToolTurns,
} from "@/lib/api";
import { Card, describeError } from "@/components/ui";
import {
  NODE_COLORS,
  View,
  ViewNode,
  elementsView,
  projectView,
  sessionView,
  shortName,
  viewSummary,
} from "@/lib/graphView";
import CatalogueCard from "@/components/GraphCatalogue";

// THE GRAPH OF ONE THING. The page used to draw the schema — a bubble
// per node type, sample members on tap, unnamed edges — which tells a
// person nothing about their sessions. Now the canvas is centred on a
// session (or a project) and shows what it is connected to, with the
// relationship written on every edge: the workspace, model, copilot and
// developer it ran with; each tool it called, sized by calls and ringed
// red when it errored; the files it touched most; the sessions most
// like it. Click a tool for the turns that called it, a file for the
// sessions that touched it, a similar session to recentre, the
// workspace to go up to the project — where the sessions are the
// bubbles and SIMILAR_TO edges run between them.

type Focus =
  { kind: "session"; id: number } | { kind: "project"; path: string };

type Selection =
  | { kind: "tool"; tool: string; sessionId: number; turns: ToolTurns | null }
  | { kind: "file"; path: string; sessions: FileSessions | null }
  | { kind: "node"; node: ViewNode };

export default function GraphExplorer() {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<any>(null);
  const [focus, setFocus] = useState<Focus | null>(null);
  const [data, setData] = useState<
    SessionNeighbourhood | ProjectNeighbourhood | null
  >(null);
  const [view, setView] = useState<View | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [prereq, setPrereq] = useState<string | null>(null);
  const [selection, setSelection] = useState<Selection | null>(null);
  const [projects, setProjects] = useState<
    { path: string; sessions: number }[]
  >([]);
  const [recent, setRecent] = useState<SessionRow[]>([]);
  const [catalogue, setCatalogue] = useState<CatalogueEntry[]>([]);
  const [overlay, setOverlay] = useState<CatalogueResult | null>(null);

  // Pickers: the projects the graph knows, and the newest sessions.
  useEffect(() => {
    api
      .graphProjects()
      .then((r) => setProjects(r.projects))
      .catch(() => setProjects([]));
    api
      .sessions("", "", false, "started_at", "desc")
      .then((r) => {
        setRecent(r.sessions);
        if (r.sessions[0])
          setFocus((f) => f ?? { kind: "session", id: r.sessions[0].id });
      })
      .catch(() => setRecent([]));
    api
      .graphCatalogue()
      .then((r) => setCatalogue(r.queries))
      .catch(() => setCatalogue([]));
  }, []);

  // Load the neighbourhood of the focus.
  useEffect(() => {
    if (!focus) return;
    let live = true;
    setErr(null);
    setPrereq(null);
    setSelection(null);
    setOverlay(null);
    const load =
      focus.kind === "session"
        ? api.graphSession(focus.id)
        : api.graphProject(focus.path);
    load
      .then((outcome) => {
        if (!live) return;
        if (!outcome.ok) {
          if (outcome.detail)
            setPrereq(`${outcome.detail.error} ${outcome.detail.guidance}`);
          else setErr(describeError(new Error(outcome.message)));
          return;
        }
        setData(outcome.report);
        setView(
          outcome.report.kind === "session"
            ? sessionView(outcome.report)
            : projectView(outcome.report),
        );
      })
      .catch((e) => live && setErr(describeError(e)));
    return () => {
      live = false;
    };
  }, [focus]);

  const onTapNode = useCallback(async (node: ViewNode) => {
    const d = node.data as Record<string, any>;
    if (node.type === "Tool" && typeof d.sessionId === "number") {
      setSelection({
        kind: "tool",
        tool: d.tool,
        sessionId: d.sessionId,
        turns: null,
      });
      try {
        const turns = await api.graphSessionTool(d.sessionId, d.tool);
        setSelection({
          kind: "tool",
          tool: d.tool,
          sessionId: d.sessionId,
          turns,
        });
      } catch (e) {
        setErr(describeError(e));
      }
      return;
    }
    if (
      (node.type === "File" || node.type === "FileNode") &&
      typeof d.path === "string"
    ) {
      setSelection({ kind: "file", path: d.path, sessions: null });
      try {
        setSelection({
          kind: "file",
          path: d.path,
          sessions: await api.graphFile(d.path),
        });
      } catch (e) {
        setErr(describeError(e));
      }
      return;
    }
    if (node.type === "Session" && !node.centre) {
      if (typeof d.sessionId === "number")
        setFocus({ kind: "session", id: d.sessionId });
      else if (typeof d.sessionKey === "string") {
        // A session from a catalogue result: find its id by key.
        const [copilot, native] = [
          d.sessionKey.split(":")[0],
          d.sessionKey.slice(d.sessionKey.indexOf(":") + 1),
        ];
        const r = await api.sessions(native, copilot, true);
        if (r.sessions[0]) setFocus({ kind: "session", id: r.sessions[0].id });
      }
      return;
    }
    if (
      node.type === "Workspace" &&
      typeof d.projectPath === "string" &&
      !node.centre
    ) {
      setFocus({ kind: "project", path: d.projectPath });
      return;
    }
    setSelection({ kind: "node", node });
  }, []);

  // Draw (or redraw) the canvas from the view or a catalogue overlay.
  useEffect(() => {
    const v = overlay?.elements ? elementsView(overlay.elements) : view;
    if (!v || !containerRef.current) return;
    let cancelled = false;
    (async () => {
      const [{ default: cytoscape }, fcoseMod] = await Promise.all([
        import("cytoscape"),
        import("cytoscape-fcose"),
      ]);
      if (cancelled) return;
      // @ts-ignore — plugin registration
      cytoscape.use(fcoseMod.default);
      if (cyRef.current) cyRef.current.destroy();
      const cy = cytoscape({
        container: containerRef.current,
        elements: [
          ...v.nodes.map((n) => ({
            data: {
              ...n,
              id: n.id,
              label: n.label,
              type: n.type,
              size: n.size,
              ring: n.ring ?? 1,
              view: n,
            },
          })),
          ...v.edges.map((e, i) => ({
            data: {
              id: `e${i}`,
              source: e.source,
              target: e.target,
              rel: e.rel,
              note: e.note ?? "",
            },
          })),
        ],
        style: [
          {
            selector: "node",
            style: {
              label: "data(label)",
              "background-color": (ele: any) =>
                NODE_COLORS[ele.data("type")] || "#94a3b8",
              color: "#1e293b",
              "font-size": 10,
              "text-valign": "bottom",
              "text-margin-y": 4,
              width: "data(size)",
              height: "data(size)",
              "border-width": (ele: any) =>
                ele.data("errored") ? 3 : ele.data("centre") ? 3 : 0,
              "border-color": (ele: any) =>
                ele.data("errored") ? "#ef4444" : "#1e293b",
            },
          },
          {
            selector: "edge",
            style: {
              width: 1.2,
              "line-color": "#cbd5e1",
              "curve-style": "bezier",
              label: (ele: any) =>
                `${ele.data("rel")}${ele.data("note") ? " " + ele.data("note") : ""}`,
              "font-size": 8,
              color: "#64748b",
              "text-rotation": "autorotate",
              "text-background-color": "#f8fafc",
              "text-background-opacity": 1,
              "text-background-padding": "2px",
              "target-arrow-shape": "triangle",
              "target-arrow-color": "#cbd5e1",
              "arrow-scale": 0.7,
            },
          },
          {
            selector: "edge[rel = 'SIMILAR_TO']",
            style: { "line-style": "dashed", "line-color": "#93c5fd" },
          },
        ],
        // Rings, not a force layout: the thing in the middle, what it
        // ran with next to it, its tools, then files and similar
        // sessions outside — so the picture reads the same every time.
        layout: (overlay?.elements
          ? { name: "fcose", animate: false, nodeSeparation: 120, idealEdgeLength: 140 }
          : {
              name: "concentric",
              animate: false,
              minNodeSpacing: 36,
              concentric: (node: any) => node.data("ring") ?? 1,
              levelWidth: () => 1,
              startAngle: Math.PI / 2,
            }) as any,
      });
      cy.on("tap", "node", (evt: any) => onTapNode(evt.target.data("view")));
      cyRef.current = cy;
    })();
    return () => {
      cancelled = true;
    };
  }, [view, overlay, onTapNode]);

  useEffect(() => () => cyRef.current?.destroy(), []);

  const centreSession = data?.kind === "session" ? data.centre : null;
  const projectPath =
    data?.kind === "session"
      ? data.centre.project_path
      : data?.kind === "project"
        ? data.project_path
        : null;
  const shownView = overlay?.elements ? elementsView(overlay.elements) : view;

  return (
    <div className="space-y-4">
      {err && (
        <div className="bg-rose-50 border border-rose-200 text-rose-800 rounded p-3 text-sm">
          {err}
        </div>
      )}
      {prereq && (
        <div className="bg-amber-50 border border-amber-200 text-amber-800 rounded p-3 text-sm">
          {prereq}{" "}
          <Link href="/analysis" className="underline">
            Open the Analysis page
          </Link>
        </div>
      )}

      {/* Where you are, and where to go. */}
      <div className="flex items-center gap-2 flex-wrap text-sm">
        <label className="text-xs text-slate-500">Project</label>
        <select
          value={projectPath ?? ""}
          onChange={(e) =>
            e.target.value &&
            setFocus({ kind: "project", path: e.target.value })
          }
          className="border border-slate-300 bg-white text-slate-900 rounded px-2 py-1 text-sm max-w-xs"
        >
          <option value="">— pick a project —</option>
          {projects.map((p) => (
            <option key={p.path} value={p.path}>
              {shortName(p.path)} ({p.sessions})
            </option>
          ))}
        </select>
        <label className="text-xs text-slate-500">Session</label>
        <select
          value={focus?.kind === "session" ? String(focus.id) : ""}
          onChange={(e) =>
            e.target.value &&
            setFocus({ kind: "session", id: Number(e.target.value) })
          }
          className="border border-slate-300 bg-white text-slate-900 rounded px-2 py-1 text-sm max-w-md"
        >
          <option value="">— pick a session —</option>
          {projectPath && (
            <optgroup label={`in ${shortName(projectPath)}`}>
              {recent
                .filter((s) => s.project_path === projectPath)
                .map((s) => (
                  <option key={s.id} value={s.id}>
                    {(s.started_at || "").slice(0, 10)} · {s.model ?? ""} · {s.turn_count} turns
                  </option>
                ))}
            </optgroup>
          )}
          <optgroup label={projectPath ? "other projects" : "recent sessions"}>
            {recent
              .filter((s) => !projectPath || s.project_path !== projectPath)
              .map((s) => (
                <option key={s.id} value={s.id}>
                  {(s.started_at || "").slice(0, 10)} · {s.project_path ? shortName(s.project_path) : "?"} · {s.model ?? ""} · {s.turn_count} turns
                </option>
              ))}
          </optgroup>
        </select>
        {/* Breadcrumb */}
        <span className="ml-auto text-xs text-slate-500 flex items-center gap-1">
          {projectPath && (
            <button
              type="button"
              onClick={() => setFocus({ kind: "project", path: projectPath })}
              className={
                "hover:underline " +
                (data?.kind === "project"
                  ? "font-semibold text-slate-800"
                  : "text-blue-700")
              }
            >
              {shortName(projectPath)}
            </button>
          )}
          {centreSession && (
            <>
              <span>›</span>
              <span className="font-semibold text-slate-800">
                session {centreSession.started_at?.slice(0, 10)}
              </span>
              <Link
                href={`/sessions/${centreSession.id}`}
                className="text-blue-700 hover:underline ml-2"
              >
                open transcript →
              </Link>
            </>
          )}
          {overlay && (
            <button
              type="button"
              onClick={() => setOverlay(null)}
              className="ml-2 text-blue-700 hover:underline"
            >
              back to {data?.kind === "project" ? "the project" : "the session"}
            </button>
          )}
        </span>
      </div>

      <div className="grid lg:grid-cols-3 gap-4">
        <Card
          title={
            overlay
              ? `Query: ${overlay.name}`
              : data?.kind === "project"
                ? "Project neighbourhood"
                : "Session neighbourhood"
          }
          className="lg:col-span-2"
        >
          <div
            ref={containerRef}
            className="w-full h-[520px] bg-slate-50 rounded border border-slate-200"
          />
          <p className="text-xs text-slate-500 mt-2">
            {shownView
              ? viewSummary(shownView)
              : "Pick a session or a project."}
            {" · "}
            Click a tool for its turns, a file for the sessions that touched it,
            a session to recentre, the workspace to go up.
          </p>
        </Card>

        <Card title="Selected">
          <SelectionPanel
            selection={selection}
            data={data}
            onFocusSession={(id) => setFocus({ kind: "session", id })}
          />
        </Card>
      </div>

      <CatalogueCard
        entries={catalogue}
        sessionKey={centreSession?.session_key ?? null}
        projectPath={projectPath}
        onResult={(r) => setOverlay(r.render === "graph" ? r : null)}
      />
    </div>
  );
}

function SelectionPanel({
  selection,
  data,
  onFocusSession,
}: {
  selection: Selection | null;
  data: SessionNeighbourhood | ProjectNeighbourhood | null;
  onFocusSession: (id: number) => void;
}) {
  if (!selection) {
    if (data?.kind === "session") {
      const c = data.centre;
      return (
        <div className="text-sm space-y-2">
          <p className="text-slate-700">
            <span className="font-medium">
              {c.project_path ? shortName(c.project_path) : "session"}
            </span>{" "}
            · {c.model ?? "?"} · {c.turn_count.toLocaleString()} turns ·{" "}
            {c.tool_call_count.toLocaleString()} tool calls · {c.error_count}{" "}
            errors
          </p>
          <ul className="text-xs text-slate-600 space-y-1">
            {data.context.map((x) => (
              <li key={x.rel + x.key}>
                <span className="font-mono text-slate-400">{x.rel}</span>{" "}
                {x.label}: {x.label === "Workspace" ? shortName(x.key) : x.key}
              </li>
            ))}
            <li>
              <span className="font-mono text-slate-400">INVOKED</span>{" "}
              {data.tools.length} tools;{" "}
              {data.errors.reduce((n, e) => n + e.count, 0)} errors
              {data.errors.length &&
              data.errors.every((e) => e.error_type === "redacted")
                ? " (types redacted under the store's redaction level)"
                : ""}
            </li>
            <li>
              <span className="font-mono text-slate-400">ACCESSED_FILE</span>{" "}
              {data.files.length} files shown (most accessed)
            </li>
            <li>
              <span className="font-mono text-slate-400">SIMILAR_TO</span>{" "}
              {data.similar.length} neighbours
              {data.similar.length === 0
                ? " — run Embed sessions and Find similar on the Analysis page"
                : ""}
            </li>
            {data.retries.length > 0 && (
              <li>
                <span className="font-mono text-slate-400">RETRIED</span>{" "}
                {data.retries.map((r) => `${r.tool} ×${r.chains}`).join(", ")}
              </li>
            )}
          </ul>
          <p className="text-xs text-slate-400">Click a bubble for detail.</p>
        </div>
      );
    }
    if (data?.kind === "project") {
      return (
        <div className="text-sm space-y-2">
          <p className="text-slate-700">
            <span className="font-medium">{shortName(data.project_path)}</span>{" "}
            · {data.sessions.length} sessions · {data.similar_edges.length}{" "}
            similarity links among them
          </p>
          <div className="text-xs text-slate-600">
            <div className="font-medium text-slate-500 mb-1">
              Tools across the project
            </div>
            <ul className="space-y-0.5">
              {data.tools.slice(0, 8).map((t) => (
                <li key={t.tool}>
                  {t.tool} · {t.calls.toLocaleString()} calls in {t.sessions}{" "}
                  sessions
                </li>
              ))}
            </ul>
          </div>
          <div className="text-xs text-slate-600">
            <div className="font-medium text-slate-500 mb-1">
              Files touched by the most sessions
            </div>
            <ul className="space-y-0.5">
              {data.files.slice(0, 8).map((f) => (
                <li key={f.path} title={f.path}>
                  {shortName(f.path)} · {f.sessions} sessions
                </li>
              ))}
            </ul>
          </div>
        </div>
      );
    }
    return <p className="text-sm text-slate-400">Nothing selected.</p>;
  }
  if (selection.kind === "tool") {
    const t = selection.turns;
    return (
      <div className="text-sm space-y-2">
        <p className="text-slate-700">
          <span className="font-mono">{selection.tool}</span> — the turns that
          called it
        </p>
        {!t ? (
          <p className="text-xs text-slate-400">Loading…</p>
        ) : (
          <>
            <p className="text-xs text-slate-500">
              {t.turns.length.toLocaleString()} calls ·{" "}
              {t.turns.filter((x) => x.is_error).length} errored
            </p>
            <ul className="text-xs max-h-72 overflow-auto space-y-0.5">
              {t.turns.slice(0, 200).map((x) => (
                <li key={x.sequence_num}>
                  <Link
                    href={`/sessions/${selection.sessionId}#turn-${x.sequence_num}`}
                    className="text-blue-700 hover:underline font-mono"
                  >
                    #{x.sequence_num}
                  </Link>
                  {x.is_error && (
                    <span className="ml-1 text-rose-700">
                      error
                      {x.error_types.length
                        ? `: ${x.error_types.join(", ")}`
                        : ""}
                    </span>
                  )}
                </li>
              ))}
              {t.turns.length > 200 && (
                <li className="text-slate-400">
                  … {t.turns.length - 200} more
                </li>
              )}
            </ul>
          </>
        )}
      </div>
    );
  }
  if (selection.kind === "file") {
    const f = selection.sessions;
    return (
      <div className="text-sm space-y-2">
        <p className="text-slate-700 break-all">
          <span className="font-mono text-xs">{selection.path}</span>
        </p>
        {!f ? (
          <p className="text-xs text-slate-400">Loading…</p>
        ) : (
          <>
            <p className="text-xs text-slate-500">
              touched by {f.sessions.length} sessions
            </p>
            <ul className="text-xs space-y-1 max-h-72 overflow-auto">
              {f.sessions.map((s) => (
                <li key={s.session_key} className="flex items-center gap-2">
                  {s.id != null ? (
                    <button
                      type="button"
                      onClick={() => onFocusSession(s.id!)}
                      className="text-blue-700 hover:underline"
                    >
                      {s.started_at?.slice(0, 10) ?? s.session_key} ·{" "}
                      {s.project_path ? shortName(s.project_path) : ""}
                    </button>
                  ) : (
                    <span className="font-mono">{s.session_key}</span>
                  )}
                  <span className="text-slate-500">
                    {s.accesses} {s.access_types.join("/")}
                  </span>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    );
  }
  const n = selection.node;
  return (
    <div className="text-sm space-y-1">
      <p className="text-slate-700">
        <span className="text-xs text-slate-400">{n.type}</span>{" "}
        <span className="font-mono break-all">
          {String((n.data as any).key ?? n.label)}
        </span>
      </p>
    </div>
  );
}
