// Where a judge URL points, for the privacy note on Settings: a server
// on this machine or the LAN (a DGX Spark at 192.168.x, spark.local)
// keeps transcript text on the network; anything else is off it.

/** localhost, *.local, or an RFC 1918 / link-local address: text that
 *  goes there stays on this network. */
export function isPrivateUrl(url: string): boolean {
  let host = "";
  try {
    host = new URL(url).hostname.toLowerCase();
  } catch {
    return false;
  }
  if (host === "localhost" || host === "::1" || host.endsWith(".local") || host.endsWith(".localhost"))
    return true;
  const m = host.match(/^(\d+)\.(\d+)\.(\d+)\.(\d+)$/);
  if (!m) return false;
  const [a, b] = [Number(m[1]), Number(m[2])];
  return a === 127 || a === 10 || (a === 172 && b >= 16 && b <= 31) || (a === 192 && b === 168) || (a === 169 && b === 254);
}
