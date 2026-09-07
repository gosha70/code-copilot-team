// Link and image resolution for documents served by the Learn center
// (#309). Pure functions, rendered by states-check: every link form the
// corpus actually uses is a case there — sibling (`agent-traces.md`),
// parent-relative (`../README.md#quick-start`), root-relative
// (`docs/hooks-guide.md`), the README's absolute `/docs/images/x.png`,
// and bare anchors.

export type ResolvedLink =
  | { kind: "anchor"; href: string }
  | { kind: "learn"; href: string; slug: string }
  | { kind: "external"; href: string };

const ABSOLUTE_URL = /^[a-z][a-z0-9+.-]*:/i;

/** POSIX-normalise `base/../x` without touching the filesystem. */
export function normalizePath(path: string): string {
  const out: string[] = [];
  for (const part of path.split("/")) {
    if (part === "" || part === ".") continue;
    if (part === "..") {
      out.pop();
      continue;
    }
    out.push(part);
  }
  return out.join("/");
}

/** The repo-relative path a link `target` names when written inside
 *  `docPath`. A leading `/` is repo-root-relative (the README's logo). */
export function resolveRepoPath(target: string, docPath: string): string {
  if (target.startsWith("/")) return normalizePath(target);
  const dir = docPath.includes("/") ? docPath.slice(0, docPath.lastIndexOf("/")) : "";
  return normalizePath(dir ? `${dir}/${target}` : target);
}

export function resolveDocLink(
  href: string,
  docPath: string,
  slugByPath: Record<string, string>,
  repoUrl: string,
  branch: string,
): ResolvedLink {
  if (!href || href.startsWith("#")) return { kind: "anchor", href: href || "#" };
  if (ABSOLUTE_URL.test(href) || href.startsWith("//")) {
    return { kind: "external", href };
  }
  const hashAt = href.indexOf("#");
  const target = hashAt >= 0 ? href.slice(0, hashAt) : href;
  const anchor = hashAt >= 0 ? href.slice(hashAt) : "";
  const path = resolveRepoPath(target, docPath);
  const slug = slugByPath[path];
  if (slug) return { kind: "learn", href: `/learn/${encodeURIComponent(slug)}${anchor}`, slug };
  return { kind: "external", href: `${repoUrl}/blob/${branch}/${path}${anchor}` };
}

/** Images under the repo's image directory come from the API; anything
 *  else stays where it points (an absolute URL) or goes to GitHub raw. */
export function resolveDocImage(
  src: string,
  docPath: string,
  apiBase: string,
  imageRoute: string,
  imageDir: string,
  repoUrl: string,
  branch: string,
): string {
  if (!src) return src;
  if (ABSOLUTE_URL.test(src) || src.startsWith("//")) return src;
  const path = resolveRepoPath(src, docPath);
  if (path.startsWith(`${imageDir}/`) && !path.slice(imageDir.length + 1).includes("/")) {
    return `${apiBase}${imageRoute}${encodeURIComponent(path.slice(imageDir.length + 1))}`;
  }
  return `${repoUrl}/raw/${branch}/${path}`;
}

/** GitHub's heading-id rule for one heading's text: lowercase, drop
 *  punctuation, spaces → hyphens. Uniqueness across a document is
 *  `tableOfContents`'s job (it suffixes repeats in source order), and the
 *  renderer takes ids from there by source line, so headings and TOC
 *  cannot disagree however many times React renders. */
export function headingSlug(text: string): string {
  return text
    .toLowerCase()
    .replace(/[`*_~]/g, "")
    .replace(/[^\p{L}\p{N}\s-]/gu, "")
    .trim()
    .replace(/\s+/g, "-");
}

export interface TocEntry {
  level: number;
  text: string;
  id: string;
  /** 1-based source line, the key the renderer uses to find this entry. */
  line: number;
}

/** Headings (levels 1–3) outside fenced code, in source order, with
 *  unique ids: a repeated heading gets `-1`, `-2`, … as on GitHub. A pure
 *  function of the document, so the renderer and the rail agree. */
export function tableOfContents(markdown: string): TocEntry[] {
  const out: TocEntry[] = [];
  const seen = new Map<string, number>();
  let inFence = false;
  const lines = markdown.split("\n");
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trimEnd();
    if (/^```/.test(line.trim())) {
      inFence = !inFence;
      continue;
    }
    if (inFence) continue;
    const m = /^(#{1,3})\s+(.+?)\s*#*\s*$/.exec(line);
    if (!m) continue;
    const text = m[2].replace(/\[([^\]]+)\]\([^)]*\)/g, "$1").replace(/[`*_]/g, "").trim();
    const base = headingSlug(text);
    const n = seen.get(base) ?? 0;
    seen.set(base, n + 1);
    out.push({ level: m[1].length, text, id: n === 0 ? base : `${base}-${n}`, line: i + 1 });
  }
  return out;
}
