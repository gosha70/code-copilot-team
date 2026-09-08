"use client";

import { SessionLatency, TurnRow } from "@/lib/api";
import { Stat, formatDuration } from "@/components/ui";

// RESPONSE TIME AS A PICTURE, not a sentence. "median 3s · p90 12s ·
// slowest 16m 4s · slowest: #1313 16m 4s, …" is correct and says
// nothing at a glance. What a person working with an AI harness wants
// to see is the SHAPE: how many assistant turns came back in under a
// second, how many took minutes, and which ones — because a fat tail
// of minute-long turns is a strategy problem (huge tool runs, a model
// re-reading the whole context), not a model problem.

/** Duration bands for the histogram; upper bound in seconds, Infinity
 *  for the last. Thresholds match the per-turn colouring on the page
 *  (amber from 30 s, rose from 2 min). */
export const LATENCY_BANDS: {
  label: string;
  upTo: number;
  tone: "ok" | "warn" | "bad";
}[] = [
  { label: "< 1s", upTo: 1, tone: "ok" },
  { label: "1–3s", upTo: 3, tone: "ok" },
  { label: "3–10s", upTo: 10, tone: "ok" },
  { label: "10–30s", upTo: 30, tone: "ok" },
  { label: "30s–2m", upTo: 120, tone: "warn" },
  { label: "2–5m", upTo: 300, tone: "bad" },
  { label: "> 5m", upTo: Infinity, tone: "bad" },
];

export const SLOW_TURN_SECONDS = 30;

export interface LatencyBucket {
  label: string;
  tone: "ok" | "warn" | "bad";
  count: number;
  share: number;
}

/** Histogram over assistant turns with a measured latency. Pure. */
export function latencyBuckets(turns: TurnRow[]): {
  buckets: LatencyBucket[];
  measured: number;
  slow: number;
} {
  const counts = LATENCY_BANDS.map(() => 0);
  let measured = 0;
  let slow = 0;
  for (const t of turns) {
    if (t.role !== "assistant" || t.latency_seconds == null) continue;
    measured += 1;
    if (t.latency_seconds >= SLOW_TURN_SECONDS) slow += 1;
    const i = LATENCY_BANDS.findIndex((b) => t.latency_seconds! < b.upTo);
    counts[i === -1 ? LATENCY_BANDS.length - 1 : i] += 1;
  }
  return {
    buckets: LATENCY_BANDS.map((b, i) => ({
      label: b.label,
      tone: b.tone,
      count: counts[i],
      share: measured ? counts[i] / measured : 0,
    })),
    measured,
    slow,
  };
}

/** One sentence a person can act on. Pure. */
export function latencyVerdict(measured: number, slow: number): string {
  if (measured === 0)
    return "No assistant turn carries a timestamp, so nothing is measured.";
  if (slow === 0) return "Every assistant turn came back in under 30 s.";
  const pct = Math.round((slow / measured) * 100);
  return (
    `${slow.toLocaleString()} of ${measured.toLocaleString()} assistant turns (${pct}%) took 30 s or longer — ` +
    "usually long tool runs (tests, builds, searches over a big tree) or a model working through a large context. " +
    "Open the slowest ones below to see which."
  );
}

const BAR_TONE = {
  ok: "bg-blue-500",
  warn: "bg-amber-500",
  bad: "bg-rose-500",
};

export default function ResponseTimeCard({
  latency,
  turns,
}: {
  latency: SessionLatency;
  turns: TurnRow[];
}) {
  const { buckets, measured, slow } = latencyBuckets(turns);
  const maxCount = Math.max(1, ...buckets.map((b) => b.count));
  const previewOf = (seq: number) => {
    const t = turns.find((x) => x.sequence_num === seq);
    const text = (t?.archived ? t.content : t?.content_preview) || "";
    return text.replace(/\s+/g, " ").slice(0, 90);
  };
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Stat
          label="Median response"
          value={formatDuration(latency.p50)}
          note="half the assistant turns were faster"
        />
        <Stat
          label="p90 response"
          value={formatDuration(latency.p90)}
          note="9 in 10 were faster"
        />
        <Stat
          label="Slowest turn"
          value={formatDuration(latency.max)}
          note={
            latency.slowest[0]
              ? `turn #${latency.slowest[0].sequence_num}`
              : undefined
          }
          tone={latency.max >= 120 ? "warn" : "default"}
        />
        <Stat
          label="Turns over 30 s"
          value={measured ? `${Math.round((slow / measured) * 100)}%` : "—"}
          note={`${slow.toLocaleString()} of ${measured.toLocaleString()} measured`}
          tone={slow > 0 ? "warn" : "default"}
        />
      </div>

      <div>
        <div className="text-xs text-slate-500 mb-1">
          Assistant turns by response time
        </div>
        <div className="space-y-1">
          {buckets.map((b) => (
            <div key={b.label} className="flex items-center gap-2 text-xs">
              <span className="w-14 text-right text-slate-600 font-mono">
                {b.label}
              </span>
              <div className="flex-1 h-4 bg-slate-100 rounded overflow-hidden">
                <div
                  className={"h-4 rounded " + BAR_TONE[b.tone]}
                  style={{
                    width: `${Math.round((b.count / maxCount) * 100)}%`,
                  }}
                  title={`${b.count} turns`}
                />
              </div>
              <span className="w-24 text-slate-600 tabular-nums">
                {b.count.toLocaleString()}
                {measured ? ` · ${Math.round(b.share * 100)}%` : ""}
              </span>
            </div>
          ))}
        </div>
      </div>

      <p className="text-sm text-slate-700">{latencyVerdict(measured, slow)}</p>

      {latency.slowest.length > 0 && (
        <table className="w-full text-xs">
          <thead className="text-left text-slate-500 border-b border-slate-200">
            <tr>
              <th className="py-1 pr-3">Slowest turns</th>
              <th className="pr-3 text-right">Took</th>
              <th>What the assistant was doing</th>
            </tr>
          </thead>
          <tbody>
            {latency.slowest.map((s) => (
              <tr key={s.sequence_num} className="border-b border-slate-100">
                <td className="py-1 pr-3">
                  <a
                    href={`#turn-${s.sequence_num}`}
                    className="font-mono text-blue-700 hover:underline"
                  >
                    #{s.sequence_num}
                  </a>
                </td>
                <td
                  className={
                    "pr-3 text-right tabular-nums " +
                    (s.seconds >= 120 ? "text-rose-700" : "text-amber-700")
                  }
                >
                  {formatDuration(s.seconds)}
                </td>
                <td className="text-slate-600 truncate max-w-[32rem]">
                  {previewOf(s.sequence_num) || "(no text captured)"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
