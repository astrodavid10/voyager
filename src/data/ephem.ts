// =====================================================================
// Baked Horizons trajectories + one-way light time FROM EARTH
// =====================================================================
// Data: public/data/ephem/trajectories.json + <id>.bin (float32 n x 3,
// heliocentric ecliptic J2000 AU), written by pipeline/ephem.py. Epoch i is
// start + i * step_days (TDB, treated as UTC: 69 s, invisible here).
//
// WWT- and three-free on purpose: the light-day hook paints in the entry
// chunk before the 3D engine loads (AUDIT-UI #4).

export type Vec3 = [number, number, number];

export const AU_KM = 149597870.7;
export const C_KM_S = 299792.458;
export const AU_MI = 92955807.27;
const DAY_MS = 86400000;

export interface Body {
  id: string;
  name: string;
  color: string;
  startMs: number;
  stepDays: number;
  xyz: Float32Array;
  count: number;
}

export interface Ephemeris {
  bodies: Record<string, Body>;
  generated: string;
}

interface RawMeta {
  generated_utc: string; // eslint-disable-line @typescript-eslint/naming-convention
  bodies: { id: string; name: string; color: string; start: string; step_days: number; // eslint-disable-line @typescript-eslint/naming-convention
            count: number; file: string }[];
}

let cache: Promise<Ephemeris> | null = null;

export function dataBase(): string {
  return "./data/";
}

export function loadEphemeris(): Promise<Ephemeris> {
  if (cache) { return cache; }
  cache = (async () => {
    const meta = (await (await fetch(dataBase() + "ephem/trajectories.json")).json()) as RawMeta;
    const bodies: Record<string, Body> = {};
    await Promise.all(meta.bodies.map(async (b) => {
      const buf = await (await fetch(dataBase() + b.file)).arrayBuffer();
      bodies[b.id] = { id: b.id, name: b.name, color: b.color, stepDays: b.step_days,
        startMs: Date.parse(b.start + "T00:00:00Z"), xyz: new Float32Array(buf), count: b.count };
    }));
    return { bodies, generated: meta.generated_utc };
  })();
  cache.catch(() => { cache = null; });
  return cache;
}

/** Linearly interpolated position (ecliptic AU) at a UTC time; clamped to the table. */
export function positionAt(b: Body, ms: number, out: Vec3 = [0, 0, 0]): Vec3 {
  const t = (ms - b.startMs) / (b.stepDays * DAY_MS);
  const i = Math.max(0, Math.min(b.count - 2, Math.floor(t)));
  const f = Math.max(0, Math.min(1, t - i));
  const a = i * 3, c = a + 3;
  out[0] = b.xyz[a] + (b.xyz[c] - b.xyz[a]) * f;
  out[1] = b.xyz[a + 1] + (b.xyz[c + 1] - b.xyz[a + 1]) * f;
  out[2] = b.xyz[a + 2] + (b.xyz[c + 2] - b.xyz[a + 2]) * f;
  return out;
}

/** Index of the last sample at or before `ms` (for drawing a trail "so far"). */
export function sampleIndexAt(b: Body, ms: number): number {
  const t = (ms - b.startMs) / (b.stepDays * DAY_MS);
  return Math.max(0, Math.min(b.count - 1, Math.floor(t)));
}

export function distanceAu(a: Vec3, b: Vec3 = [0, 0, 0]): number {
  return Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
}

/** One-way light time from Earth to the craft, in hours. */
export function lightHoursFromEarth(eph: Ephemeris, craftId: string, ms: number): number {
  const p = positionAt(eph.bodies[craftId], ms);
  const e = positionAt(eph.bodies.earth, ms);
  return (distanceAu(p, e) * AU_KM) / C_KM_S / 3600;
}

/** Speed relative to the Sun, km/s (central difference over one day). */
export function speedKmS(b: Body, ms: number): number {
  const p0 = positionAt(b, ms - DAY_MS / 2), p1 = positionAt(b, ms + DAY_MS / 2);
  return (distanceAu(p1, p0) * AU_KM) / 86400;
}

/**
 * When Earth-to-craft light time first reaches `hours` after `fromMs`, by
 * bisection on hourly samples. Null if not within `horizonDays`.
 */
export function whenLightTimeReaches(eph: Ephemeris, craftId: string, hours: number,
  fromMs: number, horizonDays = 400): number | null {
  if (lightHoursFromEarth(eph, craftId, fromMs) >= hours) { return null; }
  const stepMs = 6 * 3600 * 1000;
  for (let t = fromMs; t < fromMs + horizonDays * DAY_MS; t += stepMs) {
    if (lightHoursFromEarth(eph, craftId, t + stepMs) >= hours) {
      let lo = t, hi = t + stepMs;
      for (let k = 0; k < 30; k++) {
        const mid = (lo + hi) / 2;
        if (lightHoursFromEarth(eph, craftId, mid) >= hours) { hi = mid; } else { lo = mid; }
      }
      return hi;
    }
  }
  return null;
}

export function formatLightTime(hours: number): string {
  const h = Math.floor(hours);
  const m = Math.floor((hours - h) * 60);
  return `${h} h ${String(m).padStart(2, "0")} min`;
}

export function formatMiles(au: number): string {
  const mi = au * AU_MI;
  return mi >= 1e9 ? `${(mi / 1e9).toFixed(1)} billion miles` : `${(mi / 1e6).toFixed(0)} million miles`;
}

/** "Now", overridable with ?now=2026-11-19T12:00Z for testing the date-driven copy. */
export function nowMs(): number {
  const p = new URLSearchParams(window.location.search).get("now");
  if (p) {
    const t = Date.parse(p);
    if (Number.isFinite(t)) { return t; }
  }
  return Date.now();
}
