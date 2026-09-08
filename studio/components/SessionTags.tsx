"use client";

import { SessionTagsInfo } from "@/lib/api";

// THREE INDEPENDENT TAGS ON A SESSION, as icons: a star for favourite
// and a warning sign for to-do, both set by hand and toggled in place;
// a green check for analyzed, which is DERIVED — it means the optional
// per-session analyses (Agent Tuning, Prompt Coaching, Efficiency) have
// produced a result, so it cannot be set by hand. Each is a plain
// boolean-ish state a person reads at a glance and the grid can sort by.

export type HandTag = "favorite" | "todo";

/** What the analyzed icon means, for its tooltip and colour. Pure. */
export function analyzedState(tags: SessionTagsInfo): {
  state: "none" | "partial" | "all";
  title: string;
} {
  const n = tags.analyzed_kinds;
  const total = tags.analysis_kinds_total;
  if (n <= 0)
    return {
      state: "none",
      title:
        "Not analyzed yet — run Agent Tuning, Prompt Coaching or Efficiency on the session page",
    };
  if (n >= total)
    return {
      state: "all",
      title: `Analyzed: all ${total} analyses have results`,
    };
  return {
    state: "partial",
    title: `Analyzed: ${n} of ${total} analyses have results`,
  };
}

function Star({ on }: { on: boolean }) {
  return (
    <svg viewBox="0 0 20 20" className="w-4 h-4" aria-hidden="true">
      <path
        d="M10 1.8l2.5 5.3 5.8.7-4.3 4 1.1 5.8L10 14.8l-5.1 2.8 1.1-5.8-4.3-4 5.8-.7z"
        fill={on ? "#f59e0b" : "none"}
        stroke={on ? "#d97706" : "#cbd5e1"}
        strokeWidth="1.4"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function Warning({ on }: { on: boolean }) {
  return (
    <svg viewBox="0 0 20 20" className="w-4 h-4" aria-hidden="true">
      <path
        d="M10 2.5l8 14H2z"
        fill={on ? "#fb923c" : "none"}
        stroke={on ? "#ea580c" : "#cbd5e1"}
        strokeWidth="1.4"
        strokeLinejoin="round"
      />
      <path
        d="M10 8v4.2M10 14.4v.2"
        stroke={on ? "#7c2d12" : "#cbd5e1"}
        strokeWidth="1.6"
        strokeLinecap="round"
      />
    </svg>
  );
}

function Check({ state }: { state: "none" | "partial" | "all" }) {
  const fill =
    state === "all" ? "#10b981" : state === "partial" ? "#a7f3d0" : "none";
  const stroke = state === "none" ? "#cbd5e1" : "#059669";
  return (
    <svg viewBox="0 0 20 20" className="w-4 h-4" aria-hidden="true">
      <rect
        x="2.5"
        y="2.5"
        width="15"
        height="15"
        rx="3"
        fill={fill}
        stroke={stroke}
        strokeWidth="1.4"
      />
      <path
        d="M6 10.2l2.6 2.6L14 7.6"
        fill="none"
        stroke={state === "all" ? "#ffffff" : stroke}
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/** The header icon for one tag column (the grid sorts by it). */
export function TagHeaderIcon({ tag }: { tag: HandTag | "analyzed" }) {
  if (tag === "favorite") return <Star on />;
  if (tag === "todo") return <Warning on />;
  return <Check state="all" />;
}

export const TAG_LABEL: Record<HandTag | "analyzed", string> = {
  favorite: "Favorite",
  todo: "To-do",
  analyzed: "Analyzed",
};

export default function SessionTagIcons({
  tags,
  onToggle,
  size = "sm",
}: {
  tags: SessionTagsInfo;
  /** Present = the hand-set tags are buttons; absent = read-only icons. */
  onToggle?: (tag: HandTag, on: boolean) => void;
  size?: "sm" | "md";
}) {
  const analyzed = analyzedState(tags);
  const cls =
    "inline-flex items-center justify-center rounded " +
    (size === "md" ? "w-7 h-7" : "w-5 h-5");
  const hand = (
    tag: HandTag,
    on: boolean,
    icon: React.ReactNode,
    title: string,
  ) =>
    onToggle ? (
      <button
        type="button"
        onClick={(e) => {
          e.preventDefault();
          e.stopPropagation();
          onToggle(tag, !on);
        }}
        className={cls + " hover:bg-slate-100"}
        title={title}
        aria-pressed={on}
        aria-label={title}
      >
        {icon}
      </button>
    ) : (
      <span className={cls} title={title} aria-label={title}>
        {icon}
      </span>
    );
  return (
    <span className="inline-flex items-center gap-0.5">
      {hand(
        "favorite",
        tags.favorite,
        <Star on={tags.favorite} />,
        tags.favorite ? "Favorite — click to remove" : "Mark as favorite",
      )}
      {hand(
        "todo",
        tags.todo,
        <Warning on={tags.todo} />,
        tags.todo ? "To-do — click to clear" : "Mark as to-do",
      )}
      <span className={cls} title={analyzed.title} aria-label={analyzed.title}>
        <Check state={analyzed.state} />
      </span>
    </span>
  );
}
