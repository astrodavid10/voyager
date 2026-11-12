// =====================================================================
// WWT solar-system stage for Voyager: entering 3D mode, camera flights
// =====================================================================
// Adapted from sol/src/wwt/sunStage.ts. The difference is scale: Sol frames
// a few solar radii, while Voyager runs from ~1 au to the Sun's tidal edge at
// ~283,000 au, about 1e7 in camera distance. So:
//   * zoom limits are opened to the full range;
//   * orbit is about the ECLIPTIC pole (WWT's own lat/lng sphere), not the
//     Sun's axis, because nothing here is anchored to the solar surface;
//   * flights interpolate log(distance), because a linear zoom ease across
//     five decades spends its whole duration in the last decade.
//
// FRAME (sol footguns 1, 14, 26, 47): WWT's world frame is ecliptic J2000
// AU with Y and Z swapped, so +Y is the ecliptic pole. `lat` is ecliptic
// latitude and `lng` is ecliptic longitude - 90. The camera target is
// `custom` (20) with our own viewTarget, NEVER setTrackedObject.

import { EngineSetting, WWTControl } from "@wwtelescope/engine";

export type Vec3 = [number, number, number];

const SS_CUSTOM = 20;
const FIT_FACTOR = 2.414; // 1/tan(22.5 deg): WWT's fixed pi/4 VERTICAL FOV
export const MIN_ZOOM = (9 / 4) * 0.02; // 0.02 au
export const MAX_ZOOM = (9 / 4) * 4.0e10; // ~630 kly: the whole Milky Way (pulsar map, galaxy layer)
const MAX_LAT_DEG = 89.0;
const ORBIT_DEG_PER_PX = 0.2;

const STAGE_SETTINGS: EngineSetting[] = [
  ["solarSystemStars", true],
  ["solarSystemCosmos", false],
  ["solarSystemMilkyWay", true],
  ["solarSystemMinorPlanets", false],
  ["solarSystemOrbits", true],
  ["solarSystemLighting", false],
  ["solarSystemPlanets", true],
  ["actualPlanetScale", false],
  ["solarSystemScale", 1],
  ["showCrosshairs", false],
  ["showConstellationFigures", false],
  ["showConstellationBoundries", false],
  ["galacticMode", false],
  ["showEcliptic", false],
  ["showGrid", false],
];

export interface StageHost {
  applySetting: (setting: EngineSetting) => void;
  setBackgroundImageByName: (name: string) => void;
  setForegroundImageByName: (name: string) => void;
  setClockSync: (synced: boolean) => void;
  setTime: (time: Date) => void;
}

interface MutableCamera {
  lat: number; lng: number; zoom: number; rotation: number; angle: number;
  target: number; targetReferenceFrame: string;
  viewTarget: { x: number; y: number; z: number };
  copy: () => MutableCamera;
}
interface MutableRenderContext { viewCamera: MutableCamera; targetCamera: MutableCamera }

function rc(): MutableRenderContext | null {
  const c = WWTControl.singleton;
  return c?.renderContext ? (c.renderContext as unknown as MutableRenderContext) : null;
}

// ── frame helpers ────────────────────────────────────────────────────
/** Ecliptic J2000 (x, y, z) -> WWT world (x, z, y). Its own inverse. */
export function eclToWwt(v: Vec3): Vec3 { return [v[0], v[2], v[1]]; }

export function aspectPad(): number {
  const w = window.innerWidth, h = window.innerHeight;
  return w > 0 && h > 0 ? Math.max(1, h / w) : 1;
}
export function zoomForDistance(dAu: number): number { return clampZoom(((dAu - 1e-6) * 9) / 4); }
export function distanceForZoom(z: number): number { return (4 * z) / 9 + 1e-6; }
/** Camera distance that fits a feature of radius R (au) on the short axis. */
export function fitDistance(radiusAu: number): number { return radiusAu * FIT_FACTOR * aspectPad(); }
function clampZoom(z: number): number { return Math.min(Math.max(z, MIN_ZOOM), MAX_ZOOM); }
function clampLat(d: number): number { return Math.min(Math.max(d, -MAX_LAT_DEG), MAX_LAT_DEG); }

// Camera direction for lat/lng (sunStage's decoded formula), inverted below:
//   u = (-cos(lat) sin(lng), sin(lat), cos(lat) cos(lng))  in WWT world.
function latLngFor(u: Vec3): { lat: number; lng: number } {
  return { lat: (Math.asin(Math.max(-1, Math.min(1, u[1]))) * 180) / Math.PI,
    lng: (Math.atan2(-u[0], u[2]) * 180) / Math.PI };
}
/** Camera lat/lng that looks at the target FROM ecliptic direction `fromEcl`. */
export function viewFromEcliptic(fromEcl: Vec3): { lat: number; lng: number } {
  const w = eclToWwt(fromEcl);
  const n = Math.hypot(w[0], w[1], w[2]) || 1;
  return latLngFor([w[0] / n, w[1] / n, w[2] / n]);
}

/**
 * The `rotation` that puts an ecliptic up-vector on screen-up for a camera at
 * lat/lng (sol sunStage.rollFor: lookUp = sin(-rot) e1 + cos(-rot) e2).
 */
export function rollForUp(lat: number, lng: number, upEcl: Vec3): number {
  const la = (lat * Math.PI) / 180, ln = (lng * Math.PI) / 180;
  const up = eclToWwt(upEcl);
  const e1: Vec3 = [Math.cos(ln), 0, Math.sin(ln)];
  const e2: Vec3 = [Math.sin(la) * Math.sin(ln), Math.cos(la), -Math.sin(la) * Math.cos(ln)];
  const a = up[0] * e1[0] + up[1] * e1[1] + up[2] * e1[2];
  const b = up[0] * e2[0] + up[1] * e2[1] + up[2] * e2[2];
  return -Math.atan2(a, b);
}

function pin(cam: MutableCamera, targetEcl: Vec3): void {
  cam.target = SS_CUSTOM;
  cam.targetReferenceFrame = "";
  const w = eclToWwt(targetEcl);
  cam.viewTarget.x = w[0]; cam.viewTarget.y = w[1]; cam.viewTarget.z = w[2];
}

// ── shot state ───────────────────────────────────────────────────────
export interface Shot {
  /** Look-at point, ecliptic J2000 AU. */
  target: Vec3;
  /** Camera distance from the target, AU. */
  distanceAu: number;
  lat: number;
  lng: number;
  rotation?: number;
}

let currentTarget: Vec3 = [0, 0, 0];
let flight: { from: Shot; to: Shot; t0: number; ms: number; raf: number } | null = null;

export function currentShot(): Shot {
  const r = rc();
  if (!r) { return { target: currentTarget, distanceAu: 1, lat: 0, lng: 0 }; }
  const v = r.viewCamera;
  return { target: [...currentTarget] as Vec3, distanceAu: distanceForZoom(v.zoom),
    lat: v.lat, lng: v.lng, rotation: v.rotation };
}
export function flying(): boolean { return flight !== null; }

function write(s: Shot, both: boolean): void {
  const r = rc();
  if (!r) { return; }
  const cams = both ? [r.targetCamera, r.viewCamera] : [r.targetCamera];
  for (const cam of cams) {
    pin(cam, s.target);
    cam.lat = clampLat(s.lat);
    cam.lng = s.lng;
    cam.zoom = clampZoom(((s.distanceAu - 1e-6) * 9) / 4);
    cam.rotation = s.rotation ?? 0;
    cam.angle = 0;
  }
  currentTarget = [...s.target] as Vec3;
}

function ease(t: number): number { return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2; }
function lerpAngle(a: number, b: number, t: number): number {
  let d = ((b - a + 540) % 360) - 180;
  if (d < -180) { d += 360; }
  return a + d * t;
}

/** Fly to a shot. Log-distance interpolation; both cameras written per frame. */
export function flyTo(to: Shot, ms = 2500): Promise<void> {
  cancelFlight();
  const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  if (ms <= 0 || reduced) { write(to, true); return Promise.resolve(); }
  const from = currentShot();
  return new Promise((resolve) => {
    const t0 = performance.now();
    const step = () => {
      if (!flight) { resolve(); return; }
      const t = Math.min(1, (performance.now() - t0) / ms);
      const e = ease(t);
      const ld = Math.log(from.distanceAu) + (Math.log(to.distanceAu) - Math.log(from.distanceAu)) * e;
      const target: Vec3 = [0, 1, 2].map((k) => from.target[k] + (to.target[k] - from.target[k]) * e) as Vec3;
      write({ target, distanceAu: Math.exp(ld), lat: from.lat + (to.lat - from.lat) * e,
        lng: lerpAngle(from.lng, to.lng, e),
        rotation: (from.rotation ?? 0) + ((to.rotation ?? 0) - (from.rotation ?? 0)) * e }, true);
      if (t >= 1) { flight = null; resolve(); return; }
      flight!.raf = requestAnimationFrame(step);
    };
    flight = { from, to, t0, ms, raf: requestAnimationFrame(step) };
  });
}
/** Steer toward a shot by writing only targetCamera; the engine eases the view. */
export function aimTo(s: Shot): void {
  if (flight) { return; }
  write(s, false);
}

export function cancelFlight(): void {
  if (flight) { cancelAnimationFrame(flight.raf); flight = null; }
}

// ── gesture hooks (names match sol's sunStage so gestures.ts is reused) ─
export function orbitByPixels(dx: number, dy: number): void {
  const r = rc();
  if (!r) { return; }
  cancelFlight();
  const cam = r.targetCamera;
  cam.lng = cam.lng + dx * ORBIT_DEG_PER_PX;
  cam.lat = clampLat(cam.lat + dy * ORBIT_DEG_PER_PX);
  pin(cam, currentTarget);
}
export function zoomBy(f: number): void {
  const r = rc();
  if (!r || !(f > 0)) { return; }
  cancelFlight();
  r.targetCamera.zoom = clampZoom(r.targetCamera.zoom * f);
}
export function zoomTo(z: number): void {
  const r = rc();
  if (!r || !Number.isFinite(z)) { return; }
  cancelFlight();
  r.targetCamera.zoom = clampZoom(z);
}
export function currentZoom(): number { return rc()?.targetCamera.zoom ?? MIN_ZOOM; }
export function addUserRoll(delta: number): void {
  const r = rc();
  if (!r || !Number.isFinite(delta)) { return; }
  r.targetCamera.rotation += delta;
  r.viewCamera.rotation += delta;
}
export function currentDistanceAu(): number {
  const r = rc();
  return r ? distanceForZoom(r.viewCamera.zoom) : 1;
}

/**
 * WWT renders the solar system RELATIVE TO the camera's viewTarget (the view
 * matrix it hands three-wwt does not include that translation; measured
 * 2026-11-11: with a non-zero target the planets moved and our overlay did not).
 * Sol never saw this because its target is always the Sun at the origin. The
 * overlay therefore shifts its world root by minus this vector every frame.
 * Read from viewCamera (the eased, on-screen value), converted to ecliptic.
 */
export function liveTargetEcl(out: Vec3 = [0, 0, 0]): Vec3 {
  const r = rc();
  if (!r) { out[0] = out[1] = out[2] = 0; return out; }
  const t = r.viewCamera.viewTarget;
  out[0] = t.x; out[1] = t.z; out[2] = t.y;
  return out;
}

export function solarSystemModeActive(): boolean {
  // eslint-disable-next-line @typescript-eslint/naming-convention -- engine API name
  const c = WWTControl.singleton as unknown as { get_solarSystemMode?: () => boolean } | null;
  return !!c?.get_solarSystemMode?.();
}

export function initVoyagerStage(host: StageHost, first: Shot): void {
  host.setClockSync(false);
  host.setTime(new Date());
  host.setBackgroundImageByName("Solar System");
  host.setForegroundImageByName("Solar System");
  STAGE_SETTINGS.forEach((s) => host.applySetting(s));
  const c = WWTControl.singleton;
  if (c) { c.setSolarSystemMinZoom(MIN_ZOOM); c.setSolarSystemMaxZoom(MAX_ZOOM); }
  write(first, true);
}
