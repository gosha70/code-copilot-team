// Per-developer rollup (E1, #65).
//
// Pure presentational — the page fetches, this renders — so the shape can
// be exercised without a server.
//
// Two design constraints are load-bearing here, both inherited from the
// aggregate itself:
//
// 1. NO SORTING. Rows arrive ordered by developer_id and stay that way.
//    Sessions and turns measure how much a copilot was used, not how well
//    someone works; a table that puts the busiest person on top reads as
//    a ranking of people no matter what the column header says.
//
// 2. The single-developer case is EXPLAINED, not hidden. Every real store
//    today has one developer, so a team view that just renders one row
//    looks broken. It says why instead.

import { Card, formatCost } from "@/components/ui";
import type { DeveloperAggregates } from "@/lib/api";

function Cell({ children }: { children: React.ReactNode }) {
  return <td className="py-2 pr-4 align-top">{children}</td>;
}

export default function DevelopersPanel({
  data,
  stale,
}: {
  data: DeveloperAggregates;
  // Set when a REFRESH failed after data had already loaded. useApi keeps
  // the last good payload in that case, so without this the table would
  // go on showing figures that may no longer be current, silently.
  stale?: string | null;
}) {
  // Rendered by BOTH branches below. It sat only in the populated one
  // at first, so an empty last-good payload went on asserting "nothing
  // ingested" as current after a refresh failed — the emptiest possible
  // screen is exactly where a stale reading is least questioned.
  const staleNote = stale ? (
    <p className="text-sm text-amber-700 mb-3">
      Showing the last successful load — the most recent refresh failed.
      <span className="block text-xs text-slate-500 mt-1">{stale}</span>
    </p>
  ) : null;

  if (data.developer_count === 0) {
    return (
      <Card title="Developers">
        {staleNote}
        <p className="text-sm text-slate-500">
          No sessions ingested yet, so there is nobody to attribute them to.
        </p>
      </Card>
    );
  }

  return (
    <Card title="Developers">
      {staleNote}

      {data.is_single_developer && (
        <p className="text-sm text-slate-600 mb-3">
          This store holds sessions from a single developer. That is the
          expected view for a machine-local install — team aggregates need
          stores ingested by more than one person.
        </p>
      )}

      {data.unattributed_sessions > 0 && (
        <p className="text-sm text-slate-600 mb-3">
          {data.unattributed_sessions} session
          {data.unattributed_sessions === 1 ? " is" : "s are"} recorded under
          the default developer id, which is what an unset{" "}
          <code>developer_id</code> looks like — not necessarily one person.
        </p>
      )}

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-xs text-slate-500 border-b border-slate-200">
            <tr className="text-left">
              <th className="py-2 pr-4 font-medium">Developer</th>
              <th className="py-2 pr-4 font-medium">Sessions</th>
              <th className="py-2 pr-4 font-medium">Turns</th>
              <th className="py-2 pr-4 font-medium">Tool calls</th>
              <th className="py-2 pr-4 font-medium">Errors</th>
              <th className="py-2 pr-4 font-medium">Projects</th>
              <th className="py-2 pr-4 font-medium">Cost</th>
              <th className="py-2 pr-4 font-medium">Priced turns</th>
              <th className="py-2 pr-4 font-medium">Last seen</th>
            </tr>
          </thead>
          <tbody>
            {/* No .sort(): the producer's order is the contract. */}
            {data.developers.map((d) => (
              <tr key={d.developer_id} className="border-b border-slate-100">
                <Cell>
                  <span className="font-mono text-xs">{d.developer_id}</span>
                  {d.display_name && (
                    <span className="block text-xs text-slate-500">
                      {d.display_name}
                    </span>
                  )}
                </Cell>
                <Cell>{d.sessions}</Cell>
                <Cell>{d.turns}</Cell>
                <Cell>{d.tool_calls}</Cell>
                <Cell>{d.errors}</Cell>
                <Cell>{d.projects}</Cell>
                {/* formatCost is the shared null-safe renderer: an em dash
                    for "no price data", never "$0.00". Reusing it keeps
                    cost formatting from forking per page. */}
                <Cell>{formatCost(d.cost_usd)}</Cell>
                <Cell>
                  {/* The denominator behind the cost, measured against
                      PRICE-ELIGIBLE turns. Against every turn instead, a
                      fully-priced developer would read as partial
                      forever, because user turns have no model and are
                      never pricing candidates. */}
                  <span
                    className={
                      d.priced_turns < d.priceable_turns
                        ? "text-amber-700"
                        : "text-slate-500"
                    }
                    title={
                      d.priceable_turns === 0
                        ? "No turns were pricing candidates"
                        : d.priced_turns < d.priceable_turns
                          ? `Priced ${d.priced_turns} of ${d.priceable_turns} eligible turns`
                          : "Every eligible turn is priced"
                    }
                  >
                    {d.priced_turns} / {d.priceable_turns}
                  </span>
                </Cell>
                <Cell>
                  <span className="text-xs text-slate-500">
                    {d.last_seen ? d.last_seen.slice(0, 10) : "—"}
                  </span>
                </Cell>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {data.registered_without_sessions.length > 0 && (
        // "Registered but never ingested" is a different statement from
        // "worked zero sessions", so these are named rather than shown as
        // zero rows in the table above.
        <p className="text-xs text-slate-500 mt-3">
          Registered with no ingested sessions:{" "}
          {data.registered_without_sessions.join(", ")}
        </p>
      )}
    </Card>
  );
}
