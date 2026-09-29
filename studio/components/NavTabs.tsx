"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

export interface NavTab {
  href: string;
  label: string;
  /** Other route prefixes that belong to this tab (a page reached only
   *  from it, with no tab of its own). */
  also?: string[];
}

/** The tab a path belongs to: the tab's own route or anything under it.
 *  "/" matches only itself, or every page would light Dashboard. */
export function activeTab(tabs: NavTab[], pathname: string): string | null {
  const under = (prefix: string) =>
    prefix === "/" ? pathname === "/" : pathname === prefix || pathname.startsWith(prefix + "/");
  const hit = tabs.find((t) => under(t.href) || (t.also ?? []).some(under));
  return hit ? hit.href : null;
}

export default function NavTabs({ tabs }: { tabs: NavTab[] }) {
  const current = activeTab(tabs, usePathname() || "/");
  return (
    <nav aria-label="Main" className="flex gap-1 text-sm overflow-x-auto whitespace-nowrap">
      {tabs.map((t) => {
        const active = t.href === current;
        return (
          <Link
            key={t.href}
            href={t.href}
            aria-current={active ? "page" : undefined}
            className={
              "px-3 py-1.5 rounded transition-colors " +
              (active ? "bg-slate-700 font-semibold" : "hover:bg-slate-700")
            }
          >
            {t.label}
          </Link>
        );
      })}
    </nav>
  );
}
