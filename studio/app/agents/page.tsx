"use client";

import { useState } from "react";
import { Card } from "@/components/ui";

// The Agents tab mirrors the kiro-analyzer Studio: discover agent configs,
// upload a new one, manage the registered set. Discovery/registration is a
// local-filesystem concern; this page provides the UI shell and a client-side
// registry (wiring to a persistent agents endpoint is a follow-up).

interface AgentEntry {
  name: string;
  description: string;
  path: string;
  status: string;
}

const SEED: AgentEntry[] = [
  { name: "build", description: "Decomposes plans, delegates, integrates.", path: ".claude/agents/build", status: "active" },
  { name: "plan", description: "Produces implementation plans.", path: ".claude/agents/plan", status: "active" },
  { name: "review", description: "Holistic review of changes.", path: ".claude/agents/review", status: "active" },
];

export default function AgentsPage() {
  const [agents, setAgents] = useState<AgentEntry[]>(SEED);
  const [json, setJson] = useState("");
  const [msg, setMsg] = useState<string | null>(null);

  function upload() {
    try {
      const obj = JSON.parse(json);
      setAgents((a) => [
        ...a,
        {
          name: String(obj.name || "unnamed"),
          description: String(obj.description || ""),
          path: String(obj.path || "(uploaded)"),
          status: "active",
        },
      ]);
      setJson("");
      setMsg("Agent registered.");
    } catch {
      setMsg("Invalid JSON.");
    }
  }

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">Agents</h1>

      <Card title="Upload agent config (JSON)">
        <textarea
          className="w-full border border-slate-300 rounded p-2 text-sm font-mono h-24"
          placeholder='{"name": "my-agent", "description": "…", "path": "…"}'
          value={json}
          onChange={(e) => setJson(e.target.value)}
        />
        <div className="mt-2 flex items-center gap-3">
          <button
            onClick={upload}
            className="bg-blue-600 text-white text-sm px-4 py-1.5 rounded hover:bg-blue-700"
          >
            Register
          </button>
          {msg && <span className="text-sm text-slate-500">{msg}</span>}
        </div>
      </Card>

      <Card title="Registered agents">
        <table className="w-full text-sm">
          <thead className="text-left text-slate-500 border-b border-slate-200">
            <tr>
              <th className="py-2">Name</th>
              <th>Description</th>
              <th>Status</th>
              <th>Path</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {agents.map((a, i) => (
              <tr key={i} className="border-b border-slate-100">
                <td className="py-2 font-medium">{a.name}</td>
                <td className="text-slate-600">{a.description}</td>
                <td>
                  <span className="inline-block px-2 py-0.5 rounded text-xs bg-green-100 text-green-800">
                    {a.status}
                  </span>
                </td>
                <td className="font-mono text-xs text-slate-500">{a.path}</td>
                <td className="text-right">
                  <button
                    onClick={() => setAgents((x) => x.filter((_, j) => j !== i))}
                    className="text-red-500 hover:text-red-700 text-xs"
                  >
                    Delete
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}
