"use client";

// #371 A6: this session's lineage — which session it was resumed from.
//
// Rendered as a TREE with indentation, never a numbered list: two
// incomparable branches are siblings at the same depth, and nothing on
// screen suggests one came before the other. The rules live in
// lib/lineageView so the states check can render every state without
// Next's runtime.
import {
  coverageLabel,
  edgeEvidence,
  edgeInto,
  candidateNote,
  lineageMessage,
  lineageState,
  sourceLabel,
  walk,
  type LineageView,
} from "@/lib/lineageView";

// Tailwind utilities, as every other panel here does it. The earlier
// version carried inline CSSProperties because the `lineage-*` class
// names had no rules behind them — but this Studio has no component
// stylesheet to put them in: globals.css is the Tailwind directives and
// `body`, nothing more. The semantic class names are kept as hooks for
// anything that wants to find these nodes; they carry no styling.
const TAG = "ml-2 text-xs text-slate-500";
// slate-500, NOT slate-400: at 12px this is normal text for WCAG,
// and slate-400 on the slate-50 body is about 2.45:1 — below the
// 4.5:1 threshold. It carries the provenance and the
// shared/added/dropped counts, so it has to stay readable.
const EVIDENCE = "ml-3 text-xs text-slate-500";

export default function LineagePanel({ view }: { view: LineageView }) {
  const state = lineageState(view);
  return (
    <section className="lineage-panel mt-4" data-state={state}>
      <h3 className="text-sm font-medium text-slate-700 mb-1">Lineage</h3>
      <p className="lineage-message text-sm text-slate-700">
        {lineageMessage(view)}
      </p>
      <p className="lineage-coverage text-xs text-slate-500 mb-2">
        {coverageLabel(view)}
      </p>

      {view.thread ? (
        // NOT an <ol>: an ordered list tells the browser and assistive
        // technology that these members form a SEQUENCE, which is
        // exactly the reading A6 forbids — the order is partial, and CSS
        // hiding the numbers would not change what was announced. A tree
        // with an explicit level says "nested", not "first, second".
        <ul className="lineage-tree text-sm" role="tree" aria-label="resumed lineage">
          {walk(view.thread.roots).map(({ member, depth }) => {
            const edge = edgeInto(view.thread!, member.member_ref);
            return (
              <li
                key={member.member_ref}
                role="treeitem"
                aria-level={depth + 1}
                aria-selected={false}
                className="py-0.5"
                style={{ marginLeft: `${depth * 16}px` }}
                data-depth={depth}
              >
                <span className="lineage-source text-slate-800">{sourceLabel(member)}</span>
                {member.is_root ? (
                  <span className={`lineage-tag ${TAG}`}>
                    root
                  </span>
                ) : null}
                {member.is_terminal ? (
                  <span className={`lineage-tag ${TAG}`}>
                    latest
                  </span>
                ) : null}
                {member.source_available ? null : (
                  <span className={`lineage-tag ${TAG}`}>
                    source unreadable
                  </span>
                )}
                {edge ? (
                  <span className={`lineage-evidence ${EVIDENCE}`}>
                    {edgeEvidence(edge)}
                  </span>
                ) : null}
              </li>
            );
          })}
        </ul>
      ) : null}

      {view.thread?.fork_suspected ? (
        <p className="lineage-flag text-xs text-amber-700 mt-2">
          Two continuations branch from one transcript. They are shown side by
          side; nothing orders them.
        </p>
      ) : null}
      {view.thread?.joins.length ? (
        <p className="lineage-flag text-xs text-amber-700 mt-2">
          {view.thread.joins.length} transcript(s) continue more than one
          lineage. Shown once above, with every ancestor recorded.
        </p>
      ) : null}
      {view.thread?.terminal_ambiguous ? (
        <p className="lineage-flag text-xs text-amber-700 mt-2">
          More than one transcript is a live continuation of this lineage;
          none was chosen as the latest.
        </p>
      ) : null}
      {view.thread?.root_ambiguous ? (
        <p className="lineage-flag text-xs text-amber-700 mt-2">
          More than one transcript begins this lineage; none was chosen.
        </p>
      ) : null}

      {view.relation_candidates.length ? (
        <ul className="lineage-candidates text-xs text-slate-500 mt-2 list-disc ml-4">
          {view.relation_candidates.map((candidate) => (
            <li key={`${candidate.member_a}-${candidate.member_b}`}>
              {candidateNote(candidate)}
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
