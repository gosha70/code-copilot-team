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
