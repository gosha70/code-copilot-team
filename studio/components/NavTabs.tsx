"use client";

import { useEffect, useState, type ReactNode } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { activeNav, type NavGroup, type NavItem } from "@/lib/nav";

const ITEMS_ROW_ID = "nav-items";
/** Per-section memory of the last page visited, so a section header
 *  returns you where you left it. Session-scoped: a new tab starts each
 *  section at its first page. */
const LAST_KEY = "cct.studio.nav.last";

/** Visible keyboard focus; the offset matches the surface the control
 *  sits on (the section bar is slate-900, the pages banner slate-700). */
const FOCUS_BAR =
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400 " +
  "focus-visible:ring-offset-2 focus-visible:ring-offset-slate-900";
const FOCUS_BANNER =
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400 " +
  "focus-visible:ring-offset-2 focus-visible:ring-offset-slate-700";

/** A link on the dark section bar (Settings). */
function barClass(active: boolean) {
  return (
    "rounded-md px-2.5 py-1 text-[13px] transition-colors " +
    FOCUS_BAR +
    " " +
    (active
      ? "bg-white/15 font-medium text-white"
      : "text-slate-300 hover:bg-white/10 hover:text-white")
  );
}

/** A page in the lighter pages banner. */
function bannerClass(active: boolean) {
  return (
    "rounded-md px-2.5 py-1 text-[13px] transition-colors " +
    FOCUS_BANNER +
    " " +
    (active
      ? "bg-white/20 font-medium text-white"
      : "text-slate-300 hover:bg-white/10 hover:text-white")
  );
}

function Chevron({ open }: { open: boolean }) {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 10 6"
      width="10"
      height="6"
      className={"shrink-0 transition-transform " + (open ? "rotate-180" : "")}
    >
      <path
        d="M1 1l4 4 4-4"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/** The remembered pages, read after mount: server and first client
 *  render must agree, and storage is only available in the browser. */
function readLast(): Record<string, string> {
  try {
    const raw = window.sessionStorage.getItem(LAST_KEY);
    const parsed = raw ? (JSON.parse(raw) as unknown) : null;
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      const out: Record<string, string> = {};
      Object.entries(parsed as Record<string, unknown>).forEach(([k, v]) => {
        if (typeof v === "string") out[k] = v;
      });
      return out;
    }
  } catch {
    // Storage can be blocked or hold garbage; the in-memory map still
    // makes the section headers behave within this page view.
  }
  return {};
}

function writeLast(next: Record<string, string>) {
  try {
    window.sessionStorage.setItem(LAST_KEY, JSON.stringify(next));
  } catch {
    // Same: a session that cannot persist still navigates correctly.
  }
}

/** Two bars with distinct jobs. The dark bar holds the wordmark, the
 *  three sections — small caps, chevron, the open one underlined — and
 *  the global Settings. The lighter, full-width banner below holds the
 *  open section's pages, so a section never reads as a page. A section
 *  header is a link to where you left that section: its last page, or
 *  its first page when you have not been there this session. Only the
 *  page carries aria-current; a section header is never the page. */
export default function NavTabs({
  groups,
  settings,
  wordmark,
}: {
  groups: NavGroup[];
  settings: NavItem;
  wordmark?: ReactNode;
}) {
  const pathname = usePathname() || "/";
  const hit = activeNav(pathname);
  const [chosen, setChosen] = useState<string | null>(null);
  const [last, setLast] = useState<Record<string, string>>({});

  // Memory first, then record the page being viewed — declaration order
  // is effect order, so a fresh mount does not overwrite storage with
  // the section's default before it has been read.
  useEffect(() => setLast(readLast()), []);
  useEffect(() => {
    const owns = activeNav(pathname);
    if (!owns?.group) return;
    const groupId = owns.group.id;
    const href = owns.item.href;
    setLast((prev) => {
      if (prev[groupId] === href) return prev;
      const next = { ...prev, [groupId]: href };
      writeLast(next);
      return next;
    });
  }, [pathname]);
  // Navigating resets the hand-opened section to the one that owns the
  // page.
  useEffect(() => setChosen(null), [pathname]);

  // Settings and unowned paths have no section: keep the first open so
  // the banner is never empty.
  const open = groups.find((g) => g.id === chosen) ?? hit?.group ?? groups[0];
  const settingsActive = hit?.item.href === settings.href;
  const sectionHref = (g: NavGroup) =>
    g.items.find((it) => it.href === last[g.id])?.href ?? g.items[0].href;

  return (
    <nav aria-label="Main">
      <div className="bg-slate-900 text-white">
        <div className="mx-auto flex min-h-14 max-w-7xl items-center gap-6 px-4 py-1">
          {wordmark}
          <div className="flex min-w-0 flex-1 items-center gap-0.5 overflow-x-auto whitespace-nowrap py-1.5">
            {groups.map((g) => {
              const expanded = g.id === open?.id;
              return (
                <Link
                  key={g.id}
                  href={sectionHref(g)}
                  aria-expanded={expanded}
                  aria-controls={ITEMS_ROW_ID}
                  onClick={() => setChosen(g.id)}
                  className={
                    "relative flex items-center gap-1.5 px-2.5 py-1.5 text-[11px] " +
                    "uppercase tracking-wider transition-colors " +
                    FOCUS_BAR +
                    " " +
                    (expanded
                      ? "font-semibold text-white after:absolute after:inset-x-2 " +
                        "after:bottom-0 after:h-0.5 after:rounded-full after:bg-blue-400"
                      : "font-medium text-slate-400 hover:text-white")
                  }
                >
                  {g.label}
                  <Chevron open={expanded} />
                </Link>
              );
            })}
            {/* Settings is a page, not a section: normal case, marked with
                the page pill when it is current. */}
            <Link
              href={settings.href}
              aria-current={settingsActive ? "page" : undefined}
              className={"ml-auto " + barClass(settingsActive)}
            >
              {settings.label}
            </Link>
          </div>
        </div>
      </div>
      <div className="bg-slate-700 text-white">
        <div className="mx-auto max-w-7xl px-4">
          <div
            id={ITEMS_ROW_ID}
            className="flex gap-0.5 overflow-x-auto whitespace-nowrap py-1.5"
          >
            {(open?.items ?? []).map((it) => {
              const active = hit?.item.href === it.href;
              return (
                <Link
                  key={it.href}
                  href={it.href}
                  aria-current={active ? "page" : undefined}
                  className={bannerClass(active)}
                >
                  {it.label}
                </Link>
              );
            })}
          </div>
        </div>
      </div>
    </nav>
  );
}
