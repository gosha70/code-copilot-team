"use client";

// Feedback on one target (#371 A3): the current rows under a turn, a
// tool call or the session header, and one small form to add a row or
// replace one. The server names the source (the current developer) and
// types the value by its name; this control only offers the vocabulary
// it fetched and says what the server refused.
import { useState } from "react";
import { api, type FeedbackRow, type FeedbackWrite } from "@/lib/api";
import {
  CUSTOM_NAME,
  applyWrite,
  draftValue,
  formatValue,
  sourceLabel,
  targetLabel,
  typeFor,
  type FeedbackType,
  type VocabularyEntry,
} from "@/lib/feedbackView";

export interface FeedbackControlProps {
  sessionId: number;
  sequenceNum?: number | null;
  toolSequenceNum?: number | null;
  /** The current rows on this target. */
  rows: FeedbackRow[];
  /** The server's offered names; null while loading (the form waits). */
  vocabulary: VocabularyEntry[] | null;
  /** Called with the new list of current rows after a write. */
  onChange: (rows: FeedbackRow[]) => void;
  /** Smaller type and spacing for the trace tree. */
  compact?: boolean;
}

export default function FeedbackControl({
  sessionId,
  sequenceNum = null,
  toolSequenceNum = null,
  rows,
  vocabulary,
  onChange,
  compact = false,
}: FeedbackControlProps) {
  // The form is open for a new row, or for the row it replaces.
  const [editing, setEditing] = useState<{ supersedes: FeedbackRow | null } | null>(null);
  const size = compact ? "text-[11px]" : "text-xs";
  return (
    <div className={`mt-1.5 ${size}`}>
      {rows.length > 0 && (
        <ul className="space-y-0.5">
          {rows.map((r) => (
            <li key={r.id} className="flex flex-wrap items-baseline gap-x-2">
              <span className="font-mono text-slate-800">{r.name}</span>
              <span className="text-slate-700">{formatValue(r)}</span>
              {r.rationale && (
                <span className="text-slate-500 break-words">— {r.rationale}</span>
              )}
              <span
                className="text-slate-400"
                title={`${r.source_type} · ${r.created_at}`}
              >
                {sourceLabel(r)}
                {r.supersedes != null ? " · replaced an earlier row" : ""}
              </span>
              {vocabulary && !editing && (
                <button
                  onClick={() => setEditing({ supersedes: r })}
                  className="text-blue-700 hover:underline"
                  title="add a row that replaces this one; the old row stays as history"
                >
                  replace
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {!editing && vocabulary && (
        <button
          onClick={() => setEditing({ supersedes: null })}
          className="text-blue-700 hover:underline"
        >
          add feedback
        </button>
      )}
      {editing && vocabulary && (
        <FeedbackForm
          vocabulary={vocabulary}
          supersedes={editing.supersedes}
          target={targetLabel(sequenceNum, toolSequenceNum)}
          onCancel={() => setEditing(null)}
          onSubmit={async (body) => {
            const written = await api.addFeedback(sessionId, {
              ...body,
              sequence_num: sequenceNum,
              tool_sequence_num: toolSequenceNum,
              supersedes: editing.supersedes?.id ?? null,
            });
            onChange(applyWrite(rows, written));
            setEditing(null);
          }}
        />
      )}
    </div>
  );
}

/** The form alone, so the states check can render it without a fetch. */
export function FeedbackForm({
  vocabulary,
  supersedes,
  target,
  onCancel,
  onSubmit,
}: {
  vocabulary: VocabularyEntry[];
  supersedes: FeedbackRow | null;
  target: string;
  onCancel: () => void;
  onSubmit: (body: Pick<FeedbackWrite, "name" | "value" | "rationale">) => Promise<void>;
}) {
  const fixedName = supersedes?.name ?? null;
  const [pick, setPick] = useState<string>(() => {
    if (fixedName) return typeFor(vocabulary, fixedName) ? fixedName : CUSTOM_NAME;
    // Free text first: the server's `note` is the one text-typed name.
    return (vocabulary.find((v) => v.type === "text") ?? vocabulary[0])?.name ?? CUSTOM_NAME;
  });
  const [customName, setCustomName] = useState(fixedName && !typeFor(vocabulary, fixedName) ? fixedName : "");
  const [customType, setCustomType] = useState<FeedbackType>("text");
  const [raw, setRaw] = useState("");
  const [rationale, setRationale] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const entry = pick === CUSTOM_NAME ? null : typeFor(vocabulary, pick);
  const type: FeedbackType = entry ? entry.type : customType;
  const name = pick === CUSTOM_NAME ? customName.trim() : pick;

  async function submit() {
    if (!name) return setError("name the feedback");
    const draft = draftValue(type, raw, entry);
    if ("error" in draft) return setError(draft.error);
    setBusy(true);
    setError(null);
    try {
      await onSubmit({ name, value: draft.value, rationale: rationale.trim() || null });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
      className="mt-1 flex flex-wrap items-center gap-1.5 rounded border border-slate-200 bg-slate-50 px-2 py-1.5"
    >
      <span className="text-slate-500">
        {supersedes ? `replace ${supersedes.name} on ${target}` : `feedback on ${target}`}
      </span>
      {fixedName ? (
        <span className="font-mono text-slate-800">{fixedName}</span>
      ) : (
        <select
          value={pick}
          onChange={(e) => {
            setPick(e.target.value);
            setRaw("");
          }}
          className="rounded border border-slate-300 bg-white px-1 py-0.5"
          aria-label="feedback name"
        >
          {vocabulary.map((v) => (
            <option key={v.name} value={v.name}>
              {v.name}
            </option>
          ))}
          <option value={CUSTOM_NAME}>custom name…</option>
        </select>
      )}
      {!fixedName && pick === CUSTOM_NAME && (
        <>
          <input
            value={customName}
            onChange={(e) => setCustomName(e.target.value)}
            placeholder="name"
            maxLength={80}
            className="w-32 rounded border border-slate-300 px-1 py-0.5"
            aria-label="custom feedback name"
          />
          <select
            value={customType}
            onChange={(e) => {
              setCustomType(e.target.value as FeedbackType);
              setRaw("");
            }}
            className="rounded border border-slate-300 bg-white px-1 py-0.5"
            aria-label="custom feedback type"
          >
            <option value="text">text</option>
            <option value="num">number</option>
            <option value="bool">yes/no</option>
          </select>
        </>
      )}
      {type === "bool" ? (
        <select
          value={raw}
          onChange={(e) => setRaw(e.target.value)}
          className="rounded border border-slate-300 bg-white px-1 py-0.5"
          aria-label="feedback value"
        >
          <option value="">—</option>
          <option value="true">yes</option>
          <option value="false">no</option>
        </select>
      ) : type === "num" ? (
        <input
          type="number"
          value={raw}
          onChange={(e) => setRaw(e.target.value)}
          min={entry?.min}
          max={entry?.max}
          step={entry?.min != null ? 1 : "any"}
          placeholder={entry?.min != null ? `${entry.min}–${entry.max}` : "number"}
          className="w-20 rounded border border-slate-300 px-1 py-0.5"
          aria-label="feedback value"
        />
      ) : (
        <input
          value={raw}
          onChange={(e) => setRaw(e.target.value)}
          placeholder="what you saw"
          className="min-w-[12rem] flex-1 rounded border border-slate-300 px-1 py-0.5"
          aria-label="feedback value"
        />
      )}
      <input
        value={rationale}
        onChange={(e) => setRationale(e.target.value)}
        placeholder="why (optional)"
        className="min-w-[10rem] flex-1 rounded border border-slate-300 px-1 py-0.5"
        aria-label="feedback rationale"
      />
      <button
        type="submit"
        disabled={busy}
        className="rounded bg-blue-600 px-2 py-0.5 text-white disabled:opacity-50"
      >
        {busy ? "saving…" : "save"}
      </button>
      <button type="button" onClick={onCancel} className="text-slate-500 hover:underline">
        cancel
      </button>
      {error && <span className="basis-full text-rose-700">{error}</span>}
    </form>
  );
}
