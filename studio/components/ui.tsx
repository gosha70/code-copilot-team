"use client";

import { useEffect, useState } from "react";

export function Card({
  title,
  children,
  className = "",
}: {
  title?: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={`bg-white rounded-lg border border-slate-200 shadow-sm p-4 ${className}`}>
      {title && <h3 className="text-sm font-semibold text-slate-500 mb-3">{title}</h3>}
      {children}
    </div>
  );
}

export function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <Card>
      <div className="text-3xl font-bold tabular-nums">{value}</div>
      <div className="text-sm text-slate-500 mt-1">{label}</div>
    </Card>
  );
}

const BADGE_COLORS: Record<string, string> = {
  POSITIVE: "bg-green-100 text-green-800",
  NEUTRAL: "bg-slate-100 text-slate-700",
  NEGATIVE: "bg-orange-100 text-orange-800",
  FRUSTRATED: "bg-red-100 text-red-800",
  command: "bg-blue-100 text-blue-800",
  question: "bg-purple-100 text-purple-800",
  correction: "bg-amber-100 text-amber-900",
  rework: "bg-rose-100 text-rose-800",
};

export function Badge({ kind, children }: { kind: string; children: React.ReactNode }) {
  const cls = BADGE_COLORS[kind] || "bg-slate-100 text-slate-700";
  return <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${cls}`}>{children}</span>;
}

export function Bar({ value, max, label }: { value: number; max: number; label: string }) {
  const pct = max > 0 ? Math.round((value / max) * 100) : 0;
  return (
    <div className="flex items-center gap-2 text-sm py-0.5">
      <span className="w-32 truncate text-slate-600">{label}</span>
      <div className="flex-1 bg-slate-100 rounded h-4 overflow-hidden">
        <div className="bg-blue-500 h-full" style={{ width: `${pct}%` }} />
      </div>
      <span className="w-12 text-right tabular-nums text-slate-500">{value}</span>
    </div>
  );
}

/** Tiny data hook: returns {data, error, loading} for an async loader. */
export function useApi<T>(loader: () => Promise<T>, deps: unknown[] = []): {
  data: T | null;
  error: string | null;
  loading: boolean;
} {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let live = true;
    setLoading(true);
    loader()
      .then((d) => live && (setData(d), setError(null)))
      .catch((e) => live && setError(String(e)))
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return { data, error, loading };
}

export function Loading() {
  return <div className="text-slate-400 text-sm py-8">Loading…</div>;
}

export function ErrorNote({ error }: { error: string }) {
  return (
    <div className="bg-red-50 border border-red-200 text-red-700 rounded p-3 text-sm">
      {error}
      <div className="text-red-400 mt-1">
        Is the API running? Start it with <code>./scripts/session-analytics serve</code>.
      </div>
    </div>
  );
}
