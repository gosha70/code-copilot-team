"use client";

// The sessions list's filter bar (#371 A2). Every control is a value the
// store really has (the facets), or a date or a number; the list and the
// "Show excluded (n)" count take the same filters, so they agree.
import type { SessionFacets, SessionFilters } from "@/lib/api";
import { activeCount } from "@/lib/filterView";
import { GROUP_ABSENT, GROUP_MIXED, GROUP_UNSTAMPED, dimensionLabel, short } from "@/lib/harnessView";

const TAGS = [
  ["", "Any tag"],
  ["favorite", "Favourite"],
  ["todo", "To do"],
  ["analyzed", "Analyzed"],
] as const;

export default function SessionFiltersBar({
  filters,
  facets,
  onChange,
}: {
  filters: SessionFilters;
  facets: SessionFacets | null;
  onChange: (next: SessionFilters) => void;
}) {
  const set = (patch: Partial<SessionFilters>) => onChange({ ...filters, ...patch });
  const select = "border border-slate-300 bg-white text-slate-900 rounded px-2 py-1.5 text-sm";
  const options = (values: string[] | undefined, any: string) => (
    <>
      <option value="">{any}</option>
      {(values ?? []).map((v) => (
        <option key={v} value={v}>
          {v}
        </option>
      ))}
    </>
  );
  const n = activeCount(filters);
  return (
    <div className="flex flex-wrap items-center gap-2" data-testid="session-filters">
      <input
        className={`${select} flex-1 min-w-[14rem]`}
        placeholder="Search project path / model…"
        value={filters.query ?? ""}
        onChange={(e) => set({ query: e.target.value })}
      />
      <select className={select} value={filters.copilot ?? ""} onChange={(e) => set({ copilot: e.target.value })} aria-label="copilot">
        <option value="">All copilots</option>
        <option value="claude-code">Claude Code</option>
        <option value="aider">Aider</option>
      </select>
      <select className={select} value={filters.developer ?? ""} onChange={(e) => set({ developer: e.target.value })} aria-label="developer">
        {options(facets?.developers, "Any developer")}
      </select>
      <select className={select} value={filters.model ?? ""} onChange={(e) => set({ model: e.target.value })} aria-label="model">
        {options(facets?.models, "Any model")}
      </select>
      <select className={select} value={filters.tool ?? ""} onChange={(e) => set({ tool: e.target.value })} aria-label="tool" title="sessions that made at least one call to the tool">
        {options(facets?.tools, "Any tool")}
      </select>
      <select className={select} value={filters.label ?? ""} onChange={(e) => set({ label: e.target.value })} aria-label="label" title="the packaged rubric marked it on at least one turn">
        {options(facets?.labels, "Any label")}
      </select>
      {/* #371 A4b: one closed control for every harness dimension, so a
          row of the Dashboard's compare links to exactly its sessions.
          The three named groups come first; then each dimension's values
          under its own label. */}
      <select className={select} value={filters.harness ?? ""} onChange={(e) => set({ harness: e.target.value })} aria-label="harness" title="the harness a session ran under, recorded when it started">
        <option value="">Any harness</option>
        <option value={GROUP_MIXED}>changed mid-session</option>
        <option value={GROUP_UNSTAMPED}>no harness stamp</option>
        {Object.entries(facets?.harness ?? {}).map(([dim, values]) => (
          <optgroup key={dim} label={dimensionLabel(dim)}>
            <option value={`${GROUP_ABSENT}:${dim}`}>
              no {dimensionLabel(dim).toLowerCase()} recorded
            </option>
            {values.map((v) => (
              <option key={v} value={`${dim}:${v}`}>
                {short(v)}
              </option>
            ))}
          </optgroup>
        ))}
      </select>
      <select className={select} value={filters.tag ?? ""} onChange={(e) => set({ tag: e.target.value })} aria-label="tag">
        {TAGS.map(([v, l]) => (
          <option key={v} value={v}>
            {l}
          </option>
        ))}
      </select>
      <label className="text-xs text-slate-500 flex items-center gap-1">
        from
        <input type="date" className={select} value={filters.date_from ?? ""} onChange={(e) => set({ date_from: e.target.value })} aria-label="from date" />
      </label>
      <label className="text-xs text-slate-500 flex items-center gap-1" title="the whole day, inclusive">
        to
        <input type="date" className={select} value={filters.date_to ?? ""} onChange={(e) => set({ date_to: e.target.value })} aria-label="to date" />
      </label>
      <label className="text-xs text-slate-500 flex items-center gap-1" title="priced cost: the sum of the turns that carry a price; a session with no priced turn matches neither bound">
        priced cost $
        <input type="number" min={0} step={0.01} className={`${select} w-20`} placeholder="min" value={filters.min_cost ?? ""} onChange={(e) => set({ min_cost: e.target.value === "" ? null : Number(e.target.value) })} aria-label="min priced cost" />
        –
        <input type="number" min={0} step={0.01} className={`${select} w-20`} placeholder="max" value={filters.max_cost ?? ""} onChange={(e) => set({ max_cost: e.target.value === "" ? null : Number(e.target.value) })} aria-label="max priced cost" />
      </label>
      {n > 0 && (
        <button className="text-xs text-blue-700 hover:underline" onClick={() => onChange({})}>
          clear {n} filter{n === 1 ? "" : "s"}
        </button>
      )}
    </div>
  );
}
