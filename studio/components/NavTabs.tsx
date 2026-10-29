"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { activeNav, type NavGroup, type NavItem } from "@/lib/nav";

const ITEMS_ROW_ID = "nav-items";

function itemClass(active: boolean) {
  return (
    "px-3 py-1.5 rounded transition-colors " +
    (active ? "bg-slate-700 font-semibold" : "hover:bg-slate-700")
  );
}

/** Two rows: the group headers (and Settings, pushed right), then the
 *  open group's items. Only the item for the current page carries
 *  aria-current — a group header is never the page. */
export default function NavTabs({
  groups,
  settings,
}: {
  groups: NavGroup[];
  settings: NavItem;
}) {
  const pathname = usePathname() || "/";
  const hit = activeNav(pathname);
  // A header click opens another group to browse; navigating resets to
  // the group that owns the page.
  const [chosen, setChosen] = useState<string | null>(null);
  useEffect(() => setChosen(null), [pathname]);
  // Settings and unowned paths have no group: keep the first open so
  // the second row is never empty.
  const open = groups.find((g) => g.id === chosen) ?? hit?.group ?? groups[0];

  return (
    <nav
      aria-label="Main"
      className="flex-1 min-w-0 flex flex-col gap-1 text-sm"
    >
      <div className="flex gap-1 overflow-x-auto whitespace-nowrap">
        {groups.map((g) => {
          const expanded = g.id === open?.id;
          return (
            <button
              key={g.id}
              type="button"
              aria-expanded={expanded}
              aria-controls={ITEMS_ROW_ID}
              onClick={() => setChosen(g.id)}
              className={
                "px-3 py-1 rounded transition-colors " +
                (expanded
                  ? "text-white font-semibold"
                  : "text-slate-300 hover:bg-slate-700")
              }
            >
              {g.label}
            </button>
          );
        })}
        <Link
          href={settings.href}
          aria-current={hit?.item.href === settings.href ? "page" : undefined}
          className={"ml-auto " + itemClass(hit?.item.href === settings.href)}
        >
          {settings.label}
        </Link>
      </div>
      <div
        id={ITEMS_ROW_ID}
        className="flex gap-1 overflow-x-auto whitespace-nowrap"
      >
        {(open?.items ?? []).map((it) => {
          const active = hit?.item.href === it.href;
          return (
            <Link
              key={it.href}
              href={it.href}
              aria-current={active ? "page" : undefined}
              className={itemClass(active)}
            >
              {it.label}
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
