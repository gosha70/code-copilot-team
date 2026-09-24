"use client";

// The trace tree under a turn (#371 A1): what the agent did with its tools.
// Every call is listed, with the result that came back — or did not — the
// files it touched, and the time until the result. The data is what ingest
// already stores, redacted then: an input PREVIEW, never bodies, so nothing
// shown here is new information.
import { useState, type ReactNode } from "react";
import { formatDuration } from "@/components/ui";
import type { ToolCallRow } from "@/lib/api";

// The time from the turn that issued the call to the record that carried
// the result. Calls issued together in one turn share a start, so their
// durations overlap rather than add; the label says "until result", not
// "ran for", for that reason.
export function untilResult(c: ToolCallRow): string | null {
  if (c.duration_seconds == null) return null;
  return c.duration_seconds < 1 ? "<1s" : formatDuration(c.duration_seconds);
}

export function resultLabel(c: ToolCallRow): { text: string; tone: string } {
  if (!c.has_result) return { text: "no result recorded", tone: "text-slate-400" };
  if (c.is_error) return { text: "error", tone: "text-rose-700" };
  return { text: c.status || "ok", tone: "text-emerald-700" };
}

export default function TraceTree({
  calls,
  renderCall,
}: {
  calls: ToolCallRow[];
  /** Rendered under each call when the tree is open (#371 A3: feedback). */
  renderCall?: (c: ToolCallRow) => ReactNode;
}) {
  const [open, setOpen] = useState(false);
  if (calls.length === 0) return null;
  const errors = calls.filter((c) => c.is_error).length;
  return (
    <div className="mt-1.5">
      <button
        onClick={() => setOpen(!open)}
        className="text-xs text-blue-700 hover:underline"
        aria-expanded={open}
      >
        {open ? "hide" : "show"} {calls.length} tool call
        {calls.length === 1 ? "" : "s"}
        {errors > 0 ? ` (${errors} failed)` : ""}
      </button>
      {open && (
        <ol className="mt-1 border-l-2 border-slate-200 pl-3 space-y-1.5">
          {calls.map((c) => {
            const r = resultLabel(c);
            return (
              <li key={c.sequence_num} className="text-xs">
                <div className="flex flex-wrap items-baseline gap-2">
                  <span className="font-mono text-slate-800">{c.tool_name}</span>
                  <span className={r.tone}>{r.text}</span>
                  {untilResult(c) && (
                    <span className="font-mono text-slate-500" title="from the turn that issued the call until its result was recorded">
                      {untilResult(c)} until result
                    </span>
                  )}
                  {c.output_length != null && (
                    <span className="text-slate-400">{c.output_length} chars</span>
                  )}
                </div>
                {c.input_preview && (
                  <pre className="mt-0.5 whitespace-pre-wrap break-words text-slate-600 bg-slate-50 rounded px-2 py-1 max-h-24 overflow-y-auto">
                    {c.input_preview}
                  </pre>
                )}
                {c.error_message && (
                  <p className="mt-0.5 text-rose-700 whitespace-pre-wrap break-words">{c.error_message}</p>
                )}
                {c.files.length > 0 && (
                  <ul className="mt-0.5 text-slate-500">
                    {c.files.map((f, i) => (
                      <li key={i} className="font-mono">
                        {f.access_type ? `${f.access_type} ` : ""}
                        {f.file_path}
                      </li>
                    ))}
                  </ul>
                )}
                {renderCall?.(c)}
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}
