"use client";

// #371 A6: this session's lineage — which session it was resumed from.
//
// Rendered as a TREE with indentation, never a numbered list: two
// incomparable branches are siblings at the same depth, and nothing on
// screen suggests one came before the other. The rules live in
// lib/lineageView so the states check can render every state without
// Next's runtime.
import type { CSSProperties } from "react";
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

// Carried in the markup, not a stylesheet: these class names have no
// CSS behind them, so without explicit spacing every span ran into its
// neighbour and the tree read as one unbroken string.
const TAG: CSSProperties = {
  marginLeft: "8px",
  fontSize: "0.75rem",
  opacity: 0.7,
};
const EVIDENCE: CSSProperties = {
  marginLeft: "12px",
  fontSize: "0.75rem",
  opacity: 0.6,
};
const ROW: CSSProperties = { padding: "2px 0" };

export default function LineagePanel({ view }: { view: LineageView }) {
  const state = lineageState(view);
  return (
    <section className="lineage-panel" data-state={state}>
      <h3 style={{ marginBottom: "4px" }}>Lineage</h3>
      <p className="lineage-message">{lineageMessage(view)}</p>
      <p className="lineage-coverage">{coverageLabel(view)}</p>

      {view.thread ? (
        // NOT an <ol>: an ordered list tells the browser and assistive
        // technology that these members form a SEQUENCE, which is
        // exactly the reading A6 forbids — the order is partial, and CSS
        // hiding the numbers would not change what was announced. A tree
        // with an explicit level says "nested", not "first, second".
        <ul className="lineage-tree" role="tree" aria-label="resumed lineage">
          {walk(view.thread.roots).map(({ member, depth }) => {
            const edge = edgeInto(view.thread!, member.member_ref);
            return (
              <li
                key={member.member_ref}
                role="treeitem"
                aria-level={depth + 1}
                aria-selected={false}
                style={{ ...ROW, marginLeft: `${depth * 16}px` }}
                data-depth={depth}
              >
                <span className="lineage-source">{sourceLabel(member)}</span>
                {member.is_root ? (
                  <span className="lineage-tag" style={TAG}>
                    root
                  </span>
                ) : null}
                {member.is_terminal ? (
                  <span className="lineage-tag" style={TAG}>
                    latest
                  </span>
                ) : null}
                {member.source_available ? null : (
                  <span className="lineage-tag" style={TAG}>
                    source unreadable
                  </span>
                )}
                {edge ? (
                  <span className="lineage-evidence" style={EVIDENCE}>
                    {edgeEvidence(edge)}
                  </span>
                ) : null}
              </li>
            );
          })}
        </ul>
      ) : null}

      {view.thread?.fork_suspected ? (
        <p className="lineage-flag">
          Two continuations branch from one transcript. They are shown side by
          side; nothing orders them.
        </p>
      ) : null}
      {view.thread?.joins.length ? (
        <p className="lineage-flag">
          {view.thread.joins.length} transcript(s) continue more than one
          lineage. Shown once above, with every ancestor recorded.
        </p>
      ) : null}
      {view.thread?.terminal_ambiguous ? (
        <p className="lineage-flag">
          More than one transcript is a live continuation of this lineage;
          none was chosen as the latest.
        </p>
      ) : null}
      {view.thread?.root_ambiguous ? (
        <p className="lineage-flag">
          More than one transcript begins this lineage; none was chosen.
        </p>
      ) : null}

      {view.relation_candidates.length ? (
        <ul className="lineage-candidates">
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
