"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, AutoBuildRun, AutoBuildRuns, RunVerdict } from "@/lib/api";
import {
  VERDICT_OPTIONS,
  costLine,
  costSegments,
  dispositionLine,
  earlierTerminationsLine,
  fallbackLines,
  footnotes,
  intro,
  liveLine,
  outcomeLabel,
  outcomeStyle,
  pageState,
  phaseLine,
  phasesLine,
  policyLine,
  probeLine,
  scoresLine,
  shouldPoll,
  verdictLine,
  verifierLine,
  wallLine,
} from "@/lib/runsView";
import {
  Card,
  ErrorNote,
  Loading,
  describeError,
  useApi,
} from "@/components/ui";

// RUNS (#190 §12, auto-build-run-surface). Every auto-build attempt the
// driver recorded on this machine, read from its ledger on each fetch:
// the outcome in the driver's own words, why it stopped, how far it
// got, cost against cap with the estimated part distinguished, the
// verifier state, the policy decisions — and the one label the ledger
// cannot write: what the human did with the PR. Polls while a run is
// live (lib/runsView: shouldPoll).

const POLL_MS = 5_000;

export default function RunsPage() {
  const [version, setVersion] = useState(0);
  const [polling, setPolling] = useState(false);
  const { data, error, loading } = useApi(
    () => api.autoBuildRuns(),
    [version],
    polling ? POLL_MS : undefined,
  );
  useEffect(() => {
    setPolling(shouldPoll(data));
  }, [data]);

  if (loading && !data) return <Loading />;
  if (error && !data) return <ErrorNote error={error} />;
  if (!data) return <ErrorNote error="the API did not answer" />;
  const head = intro(data);
  const state = pageState(data);
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Runs</h1>
        <p className="text-sm text-slate-500 mt-1">
          {head.headline}
          {error && (
            <span className="text-rose-700">
              {" "}
              · last refresh failed: {error}
            </span>
          )}
        </p>
      </div>

      <Card>
        <p className="text-sm text-slate-700">{head.body}</p>
        {state === "no-root" && (
          <p className="text-sm mt-2">
            <Link href="/settings" className="text-blue-700 hover:underline">
              Open Settings →
            </Link>
          </p>
        )}
      </Card>

      {state === "runs" &&
        data.runs.map((run) => (
          <RunCard
            key={run.key}
            run={run}
            verdicts={data.verdicts}
            onChanged={() => setVersion((v) => v + 1)}
          />
        ))}

      {footnotes(data).length > 0 && (
        <p className="text-xs text-slate-500">{footnotes(data).join(" ")}</p>
      )}
    </div>
  );
}

function RunCard({
  run,
  verdicts,
  onChanged,
}: {
  run: AutoBuildRun;
  verdicts: AutoBuildRuns["verdicts"];
  onChanged: () => void;
}) {
  const [open, setOpen] = useState(false);
  const seg = costSegments(run);
  const disposition = dispositionLine(run);
  const earlier = earlierTerminationsLine(run);
  const fallbacks = fallbackLines(run);
  const live = liveLine(run);
  return (
    <Card>
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span
          className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${outcomeStyle(run)}`}
        >
          {outcomeLabel(run)}
        </span>
        <span className="font-semibold">
          {run.feature_id ?? "unknown feature"}
        </span>
        <span className="text-xs text-slate-500">
          {run.profile ?? "?"} · {run.branch ?? "?"} from {run.base_ref ?? "?"}{" "}
          · {run.ledger}
        </span>
        {run.pr.number && run.pr.url && (
          <a
            href={run.pr.url}
            className="text-xs text-blue-700 hover:underline"
            target="_blank"
            rel="noreferrer"
          >
            PR #{run.pr.number} →
          </a>
        )}
      </div>
      {disposition && (
        <p className="text-sm text-amber-900 mt-2">{disposition}</p>
      )}
      {earlier && <p className="text-sm text-amber-900 mt-2">{earlier}</p>}
      {live && <p className="text-xs text-slate-600 mt-1">{live}</p>}

      <dl className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-2 mt-3 text-sm">
        <div>
          <dt className="text-xs text-slate-500">Cost</dt>
          <dd>
            {costLine(run)}
            <div
              className="h-2 mt-1 w-full bg-slate-100 rounded overflow-hidden flex"
              title={costLine(run)}
            >
              <div
                className="h-2 bg-blue-500"
                style={{ width: `${seg.metered}%` }}
              />
              <div
                className="h-2 bg-blue-300"
                style={{
                  width: `${seg.estimated}%`,
                  backgroundImage:
                    "repeating-linear-gradient(45deg, transparent, transparent 3px, rgba(255,255,255,.6) 3px, rgba(255,255,255,.6) 6px)",
                }}
              />
            </div>
            <span className="text-xs text-slate-500">
              solid = metered, hatched = estimated
              {seg.over ? " · over the cap" : ""}
            </span>
          </dd>
        </div>
        <div>
          <dt className="text-xs text-slate-500">Wall clock</dt>
          <dd>{wallLine(run)}</dd>
        </div>
        <div>
          <dt className="text-xs text-slate-500">Phases</dt>
          <dd>
            {phasesLine(run)}
            <ul className="text-xs text-slate-600 mt-1 space-y-0.5">
              {run.phases.items.map((p) => (
                <li key={p.n ?? p.title ?? "?"}>{phaseLine(p)}</li>
              ))}
            </ul>
          </dd>
        </div>
        <div>
          <dt className="text-xs text-slate-500">Verifiers</dt>
          <dd>
            {verifierLine(run)}
            {run.verifiers.results && (
              <ul className="text-xs mt-1 flex flex-wrap gap-1">
                {run.verifiers.results.frs.map((f) => (
                  <li
                    key={f.fr}
                    className={`px-1.5 rounded ${f.green ? "bg-emerald-100 text-emerald-800" : "bg-rose-100 text-rose-800"}`}
                  >
                    {f.fr} {f.green ? "green" : "red"}
                  </li>
                ))}
              </ul>
            )}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-slate-500">Reviewer</dt>
          <dd>
            {probeLine(run)}
            {fallbacks.length > 0 && (
              <ul className="text-xs text-amber-900 mt-1 space-y-0.5">
                {fallbacks.map((line, i) => (
                  <li key={i}>{line}</li>
                ))}
              </ul>
            )}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-slate-500">Scores</dt>
          <dd>{scoresLine(run)}</dd>
        </div>
        <div>
          <dt className="text-xs text-slate-500">Policy decisions</dt>
          <dd>
            {policyLine(run)}
            {run.escalations > 0 &&
              ` · ${run.escalations} escalation${run.escalations === 1 ? "" : "s"}`}
            {run.policy_decisions.length > 0 && (
              <>
                {" "}
                <button
                  className="text-xs text-blue-700 hover:underline"
                  onClick={() => setOpen((o) => !o)}
                >
                  {open ? "hide" : "show"}
                </button>
                {open && (
                  <ul className="text-xs text-slate-700 mt-1 space-y-1">
                    {run.policy_decisions.map((e, i) => (
                      <li key={i} className="font-mono">
                        <span className="text-slate-400">{e.ts ?? "—"}</span>{" "}
                        {e.event}: {e.detail ?? ""}
                      </li>
                    ))}
                  </ul>
                )}
              </>
            )}
          </dd>
        </div>
      </dl>

      <VerdictControl run={run} verdicts={verdicts} onChanged={onChanged} />
    </Card>
  );
}

function VerdictControl({
  run,
  verdicts,
  onChanged,
}: {
  run: AutoBuildRun;
  verdicts: AutoBuildRuns["verdicts"];
  onChanged: () => void;
}) {
  const [verdict, setVerdict] = useState<RunVerdict | "">(
    run.verdict?.verdict ?? "",
  );
  const [note, setNote] = useState(run.verdict?.note ?? "");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const options = VERDICT_OPTIONS.filter((o) => verdicts.includes(o.value));

  async function save() {
    if (!verdict) return;
    setBusy(true);
    setErr(null);
    try {
      await api.setRunVerdict(run.key, verdict, note.trim() || null);
      onChanged();
    } catch (e) {
      setErr(describeError(e));
    } finally {
      setBusy(false);
    }
  }
  async function clear() {
    setBusy(true);
    setErr(null);
    try {
      await api.clearRunVerdict(run.key);
      setVerdict("");
      setNote("");
      onChanged();
    } catch (e) {
      setErr(describeError(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-3 pt-3 border-t border-slate-100 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs text-slate-500">Human verdict on the PR:</span>
        <span className="font-medium">{verdictLine(run)}</span>
      </div>
      <div className="flex flex-wrap items-center gap-2 mt-2">
        <select
          className="border border-slate-300 rounded px-2 py-1 text-sm"
          value={verdict}
          onChange={(e) => setVerdict(e.target.value as RunVerdict | "")}
          disabled={busy}
        >
          <option value="">choose a verdict…</option>
          {options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        <input
          className="border border-slate-300 rounded px-2 py-1 text-sm flex-1 min-w-[12rem]"
          placeholder="note (what the human changed or why it was rejected)"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          disabled={busy}
        />
        <button
          className="px-3 py-1 rounded bg-blue-600 text-white text-sm disabled:opacity-50"
          onClick={save}
          disabled={busy || !verdict}
        >
          Save verdict
        </button>
        {run.verdict && (
          <button
            className="px-3 py-1 rounded border border-slate-300 text-sm"
            onClick={clear}
            disabled={busy}
          >
            Clear
          </button>
        )}
      </div>
      {err && <p className="text-xs text-rose-700 mt-1">{err}</p>}
    </div>
  );
}
