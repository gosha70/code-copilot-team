"use client";

import { useCallback, useEffect, useState } from "react";

// A "Browse…" picker for settings fields that point at real files or
// folders on this machine.
//
// WHY THIS IS SERVER-BACKED AND NOT <input type="file">. A browser
// deliberately refuses to reveal a real path — a file input yields
// "sa.db", never "/Users/you/.cct/sa.db" — so it cannot fill a setting
// that the CLI will later read. The listing therefore comes from the
// local API, which is read-only, returns names and is_dir only, and is
// reachable on 127.0.0.1 only.
//
// The point is that a path is something you should be able to FIND, not
// something you have to remember and retype correctly.

interface Entry {
  name: string;
  is_dir: boolean;
}

interface BrowseResponse {
  path: string;
  parent: string | null;
  entries: Entry[];
  truncated: boolean;
  shortcuts: string[];
}

const BASE = process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8765";

export default function PathPicker({
  mode,
  startPath,
  onPick,
  onClose,
}: {
  /** "file" selects a store; "dir" selects a folder. */
  mode: "file" | "dir";
  startPath?: string;
  onPick: (path: string) => void;
  onClose: () => void;
}) {
  const [data, setData] = useState<BrowseResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const browse = useCallback(
    async (path: string) => {
      setError(null);
      try {
        const r = await fetch(
          `${BASE}/api/fs/browse?path=${encodeURIComponent(path)}` +
            `&only_dirs=${mode === "dir"}`,
          { cache: "no-store" },
        );
        if (!r.ok) throw new Error(`browse → ${r.status}`);
        setData(await r.json());
      } catch (e) {
        setError(String(e));
      }
    },
    [mode],
  );

  useEffect(() => {
    browse(startPath || "");
  }, [browse, startPath]);

  // Escape closes — a modal that traps you is worse than no modal.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 bg-black/30 flex items-center justify-center z-50 p-4"
      onClick={onClose}
    >
      <div
        className="bg-white rounded shadow-lg w-full max-w-lg max-h-[70vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-3 py-2 border-b border-slate-200 flex items-center justify-between">
          <span className="text-sm font-medium text-slate-700">
            {mode === "dir" ? "Choose a folder" : "Choose a database file"}
          </span>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-slate-700 text-sm"
            aria-label="Close"
          >
            ✕
          </button>
        </div>

        {error && (
          <p className="text-xs text-red-700 bg-red-50 px-3 py-2">{error}</p>
        )}

        {data && (
          <>
            <div className="px-3 py-2 border-b border-slate-100 flex flex-wrap items-center gap-2">
              {data.shortcuts.map((s) => (
                <button
                  key={s}
                  onClick={() => browse(s)}
                  className="text-xs border border-slate-300 bg-white text-slate-700 rounded px-2 py-0.5 hover:bg-slate-50"
                >
                  {s}
                </button>
              ))}
            </div>

            <p className="px-3 py-1.5 text-xs font-mono text-slate-600 border-b border-slate-100 break-all">
              {data.path}
            </p>

            <div className="overflow-y-auto flex-1">
              {data.parent && (
                <button
                  onClick={() => browse(data.parent as string)}
                  className="w-full text-left px-3 py-1.5 text-sm hover:bg-slate-50 text-slate-600"
                >
                  ↑ ..
                </button>
              )}
              {data.entries.map((e) => (
                <button
                  key={e.name}
                  onClick={() =>
                    e.is_dir
                      ? browse(`${data.path}/${e.name}`)
                      : onPick(`${data.path}/${e.name}`)
                  }
                  className="w-full text-left px-3 py-1.5 text-sm hover:bg-slate-50 text-slate-800"
                >
                  {e.is_dir ? "📁" : "🗄"} {e.name}
                </button>
              ))}
              {data.entries.length === 0 && (
                // An empty folder and an unreadable one look identical
                // from here, so say both rather than implying "empty".
                <p className="px-3 py-3 text-xs text-slate-500">
                  Nothing selectable here — the folder is empty, unreadable, or
                  holds no {mode === "dir" ? "sub-folders" : "database files"}.
                </p>
              )}
              {data.truncated && (
                <p className="px-3 py-2 text-xs text-amber-700">
                  Showing the first {data.entries.length} entries only.
                </p>
              )}
            </div>

            <div className="px-3 py-2 border-t border-slate-200 flex justify-end gap-2">
              {mode === "dir" && (
                <button
                  onClick={() => onPick(data.path)}
                  className="bg-blue-600 text-white text-sm px-3 py-1 rounded hover:bg-blue-700"
                >
                  Use this folder
                </button>
              )}
              <button
                onClick={onClose}
                className="border border-slate-300 bg-white text-slate-700 text-sm px-3 py-1 rounded hover:bg-slate-50"
              >
                Cancel
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
