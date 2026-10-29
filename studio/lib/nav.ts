/** The console's name, in one place: the document title and the header
 *  wordmark both read it. */
export const PRODUCT_NAME = "Harness Studio";

export interface NavItem {
  href: string;
  label: string;
  /** Other route prefixes that belong to this item (a page reached only
   *  from it, with no item of its own). */
  also?: string[];
}

export interface NavGroup {
  id: string;
  label: string;
  items: NavItem[];
}

/** Whether `pathname` is `prefix` or anything under it. "/" matches only
 *  itself, or every page would belong to Overview. */
export function under(prefix: string, pathname: string): boolean {
  return prefix === "/"
    ? pathname === "/"
    : pathname === prefix || pathname.startsWith(prefix + "/");
}

// #307: only pages that answer a question a person has — Graph explores
// a session or a project and what it is connected to; Ask answers
// questions in words through read-only lookups, text search among them;
// Learn (#309), shown as Guides, carries the real catalogue of docs,
// skills and agents from the repo itself. The groups follow the AI
// SDLC: see the system, the moving pieces, what it knows.
export const NAV_GROUPS: NavGroup[] = [
  {
    id: "mission-control",
    label: "Mission Control",
    items: [
      { href: "/", label: "Overview", also: ["/labels"] },
      { href: "/sessions", label: "Sessions" },
      { href: "/search", label: "Search" },
      { href: "/ask", label: "Ask" },
      { href: "/graph", label: "Graph" },
    ],
  },
  {
    id: "development",
    label: "Development",
    items: [
      { href: "/runs", label: "Runs" },
      { href: "/team", label: "Team" },
      { href: "/routing", label: "Routing" },
      { href: "/benchmark", label: "Benchmark" },
      { href: "/analysis", label: "Analysis pipeline" },
    ],
  },
  {
    id: "library",
    label: "Library",
    items: [{ href: "/learn", label: "Guides" }],
  },
];

/** Settings belongs to no group: it configures all of them. */
export const SETTINGS_ITEM: NavItem = { href: "/settings", label: "Settings" };

const owns = (item: NavItem, pathname: string) =>
  under(item.href, pathname) || (item.also ?? []).some((p) => under(p, pathname));

/** The item a path belongs to and the group holding it. The group is
 *  null for Settings, which sits in no group; the whole result is null
 *  for a path no item owns. */
export function activeNav(
  pathname: string,
): { group: NavGroup | null; item: NavItem } | null {
  for (const group of NAV_GROUPS) {
    const item = group.items.find((it) => owns(it, pathname));
    if (item) return { group, item };
  }
  return owns(SETTINGS_ITEM, pathname) ? { group: null, item: SETTINGS_ITEM } : null;
}
