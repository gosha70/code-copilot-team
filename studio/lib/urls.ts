// Where a judge URL points, for the privacy note on Settings: a server
// on this machine or the LAN (a DGX Spark at 192.168.x, spark.local)
// keeps transcript text on the network; anything else is off it.

/** localhost, a .local / .lan / single-label hostname (resolved through
 *  the local search domain — a public name always carries a TLD), an
 *  RFC 1918 / link-local / CGNAT address, or an IPv6 unique-local /
 *  link-local literal: text that goes there stays on this network. A
 *  dotted public name or a public address does not.
 *
 *  NOT .ts.net: a Tailscale Funnel URL shares that suffix and is public,
 *  so the name proves neither your tailnet nor a private path — it
 *  warns. A Tailscale-reached host is local by its CGNAT address
 *  (100.64.0.0/10) or a private name, which is the reliable signal. */
export function isPrivateUrl(url: string): boolean {
  let host = "";
  try {
    host = new URL(url).hostname.toLowerCase();
  } catch {
    return false;
  }
  if (
    host === "localhost" ||
    host === "::1" ||
    host === "[::1]" ||
    host.endsWith(".local") ||
    host.endsWith(".localhost") ||
    host.endsWith(".lan")
  )
    return true;
  // "spark", "nas", "gpu-1": no dot and no colon (IPv6 keeps its
  // colons) — a name only this network resolves.
  if (!host.includes(".") && !host.includes(":")) return true;
  // IPv6 literals keep their brackets in a URL hostname. fc00::/7
  // (unique-local) and fe80::/10 (link-local) stay on this network; any
  // other literal parses as a public address. A compressed leading "::"
  // is not one of the local forms handled above, so it warns.
  if (host.startsWith("[") && host.endsWith("]")) {
    const first = host.slice(1, -1).split(":")[0];
    const n = first ? parseInt(first, 16) : Number.NaN;
    if (Number.isNaN(n)) return false;
    return (n >= 0xfc00 && n <= 0xfdff) || (n >= 0xfe80 && n <= 0xfebf);
  }
  const m = host.match(/^(\d+)\.(\d+)\.(\d+)\.(\d+)$/);
  if (!m) return false;
  const [a, b] = [Number(m[1]), Number(m[2])];
  return (
    a === 127 ||
    a === 10 ||
    (a === 172 && b >= 16 && b <= 31) ||
    (a === 192 && b === 168) ||
    (a === 169 && b === 254) || // link-local
    (a === 100 && b >= 64 && b <= 127) // CGNAT, incl. Tailscale
  );
}
