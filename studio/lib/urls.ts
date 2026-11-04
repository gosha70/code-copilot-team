// Where a judge URL points, for the privacy note on Settings: a server
// on this machine or the LAN (a DGX Spark at 192.168.x, spark.local)
// keeps transcript text on the network; anything else is off it.

/** localhost, a .local / .lan / single-label hostname (resolved through
 *  the local search domain — a public name always carries a TLD), or an
 *  RFC 1918 / link-local address: text that goes there stays on this
 *  network. A dotted public name or a public address does not. */
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
    host.endsWith(".local") ||
    host.endsWith(".localhost") ||
    host.endsWith(".lan")
  )
    return true;
  // "spark", "nas", "gpu-1": no dot and no colon (IPv6 keeps its
  // colons) — a name only this network resolves.
  if (!host.includes(".") && !host.includes(":")) return true;
  const m = host.match(/^(\d+)\.(\d+)\.(\d+)\.(\d+)$/);
  if (!m) return false;
  const [a, b] = [Number(m[1]), Number(m[2])];
  return a === 127 || a === 10 || (a === 172 && b >= 16 && b <= 31) || (a === 192 && b === 168) || (a === 169 && b === 254);
}
