// Take-home QR target for the lobby kiosk (adapted from sol/src/kiosk/takeHome.ts).

/**
 * False for a URL a guest's phone cannot open once it leaves the building:
 * localhost, loopback, RFC 1918 and link-local addresses, `.local` names, and
 * anything that is not http(s). The QR refuses to draw these rather than hand a
 * guest a code that opens nothing (sol footgun 42).
 */
export function isReachableFromPhone(url: string): boolean {
  let host: string;
  try {
    const u = new URL(url);
    if (u.protocol !== "https:" && u.protocol !== "http:") { return false; }
    host = u.hostname.toLowerCase().replace(/^\[|\]$/g, "");
  } catch {
    return false;
  }
  if (host === "localhost" || host.endsWith(".local") || host === "0.0.0.0" || host === "::1") { return false; }
  const v4 = host.match(/^(\d+)\.(\d+)\.\d+\.\d+$/);
  if (v4) {
    const a = Number(v4[1]);
    const b = Number(v4[2]);
    if (a === 127 || a === 10 || (a === 192 && b === 168) || (a === 169 && b === 254)
        || (a === 172 && b >= 16 && b <= 31)) {
      return false;
    }
  }
  return true;
}
