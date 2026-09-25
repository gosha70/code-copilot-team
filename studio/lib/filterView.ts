// The sessions filter bar's URL rules (#371 A2): the filters live in the
// query string, so a filtered list can be linked and reloaded.
import type { SessionFilters } from "@/lib/api";

export const FILTER_KEYS = [
  "query", "copilot", "date_from", "date_to", "tag", "developer", "model", "tool",
  "min_cost", "max_cost", "label", "harness",
] as const;

export function filtersFromParams(get: (k: string) => string | null): SessionFilters {
  const f: SessionFilters = {};
  for (const k of FILTER_KEYS) {
    const v = get(k);
    if (v === null || v === "") continue;
    if (k === "min_cost" || k === "max_cost") {
      const n = Number(v);
      if (Number.isFinite(n)) f[k] = n;
    } else {
      f[k] = v;
    }
  }
  return f;
}

export function paramsFromFilters(f: SessionFilters): URLSearchParams {
  const p = new URLSearchParams();
  for (const k of FILTER_KEYS) {
    const v = f[k];
    if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  }
  return p;
}

/** How many filters are set, for the bar's "clear (n)" control. */
export function activeCount(f: SessionFilters): number {
  return FILTER_KEYS.filter((k) => f[k] !== undefined && f[k] !== null && f[k] !== "").length;
}
