// =====================================================================
// Placement model for the sprite clouds and star points
// =====================================================================
// Ported from JWST src/galaxy-structure.ts, with two changes:
//
//  1. Arms come from two honest sources instead of one hand-tuned table.
//     * Where the arms are MEASURED (the near side, Reid et al. 2019 maser
//       parallaxes, arms.ts) the young-star ridge puffs and the H II / OB
//       knots sit on the published fits.
//     * Everywhere else, puffs and dust follow the face-on texture itself
//       (bright-vs-radial-mean = arm, dark-vs-radial-mean = dust lane), so
//       the sprites can never "fight" the painted arms the way a
//       extrapolated log-spiral table would on the unmeasured far side.
//  2. The warp is the Cepheid-sized one from frame.ts and is shared with the
//     slice stack, so the whole body bends together.
//
// Everything is in galactocentric kpc (frame.ts). Seeded, so reproducible.
// This reproduces morphology only; it is not a dynamical model.

import { ARMS, BAR_ANGLE_RAD, BAR_HALF_LEN_KPC, armPoint } from "./arms";
import { CELL } from "./atlas";
import { TEX_SIDE_KPC, flare, warpZ } from "./frame";

export interface SpriteBatch {
  count: number;
  /** x, y, z (kpc) per instance. */
  pos: Float32Array;
  /** Half-extent (kpc) per instance. */
  size: Float32Array;
  /** r, g, b, a (0..1) per instance. */
  color: Float32Array;
  /** Atlas cell index per instance. */
  cell: Float32Array;
}

export interface StarBatch {
  count: number;
  pos: Float32Array;
  /** r, g, b, and a size multiplier in the 4th slot. */
  color: Float32Array;
}

export interface GalaxyModel {
  glow: SpriteBatch;
  dust: SpriteBatch;
  stars: StarBatch;
}

/** Low-resolution copy of the face-on texture used to steer placement. */
export interface Guide {
  n: number;
  /** RGBA bytes, row 0 = top of the image. */
  data: Uint8ClampedArray;
}

interface Counts {
  bulge: number; texArm: number; ridge: number; haze: number; knots: number; dust: number; stars: number;
}
const FULL: Counts = { bulge: 320, texArm: 1700, ridge: 520, haze: 420, knots: 320, dust: 800, stars: 36000 };
const LITE: Counts = { bulge: 110, texArm: 520, ridge: 170, haze: 120, knots: 110, dust: 240, stars: 8000 };

type RGB = [number, number, number];
const c255 = (r: number, g: number, b: number): RGB => [r / 255, g / 255, b / 255];
const COL_BULGE_HOT = c255(255, 205, 155);
const COL_BULGE_COOL = c255(255, 160, 105);
const COL_INTERARM = c255(255, 235, 200);
const COL_THICK = c255(255, 205, 160);
const COL_HII = c255(255, 130, 145);
const COL_OB = c255(185, 220, 255);
const COL_ARM_YOUNG = c255(170, 205, 255);
const COL_ARM_OLD = c255(255, 210, 165);

function lerpRGB(a: RGB, b: RGB, t: number): RGB {
  return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];
}

function mulberry32(seed: number): () => number {
  let s = seed >>> 0;
  return function next(): number {
    s |= 0; s = (s + 0x6d2b79f5) | 0;
    let t = Math.imul(s ^ (s >>> 15), 1 | s);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

class Sprites {
  private p: number[] = [];
  private s: number[] = [];
  private c: number[] = [];
  private k: number[] = [];
  add(x: number, y: number, z: number, size: number, col: RGB, a: number, cell: number): void {
    this.p.push(x, y, z); this.s.push(size); this.c.push(col[0], col[1], col[2], a); this.k.push(cell);
  }
  done(): SpriteBatch {
    return {
      count: this.s.length, pos: new Float32Array(this.p), size: new Float32Array(this.s),
      color: new Float32Array(this.c), cell: new Float32Array(this.k),
    };
  }
}

export function buildModel(guide: Guide | null, lite: boolean): GalaxyModel {
  const counts = lite ? LITE : FULL;
  const rnd = mulberry32(0x1a2b3c);
  const gauss = (): number => {
    let u = 0, v = 0;
    while (u === 0) { u = rnd(); }
    while (v === 0) { v = rnd(); }
    return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
  };
  const puffCell = (): number => [CELL.glowPuffA, CELL.glowPuffB, CELL.glowPuffC][Math.floor(rnd() * 3)];

  // ── texture guide: luminance, color, and the azimuthal mean profile ──
  const rBins = 64, rMax = 16;
  const mean = new Float32Array(rBins).fill(0.25);
  function texel(x: number, y: number): { lum: number; rgb: RGB } {
    if (!guide) { return { lum: 0.25, rgb: [1, 0.92, 0.82] }; }
    const n = guide.n;
    const col = Math.min(n - 1, Math.max(0, Math.floor((0.5 - y / TEX_SIDE_KPC) * n)));
    const row = Math.min(n - 1, Math.max(0, Math.floor((0.5 - x / TEX_SIDE_KPC) * n)));
    const i = (row * n + col) * 4, d = guide.data;
    const r = d[i] / 255, g = d[i + 1] / 255, b = d[i + 2] / 255;
    return { lum: 0.3 * r + 0.59 * g + 0.11 * b, rgb: [r, g, b] };
  }
  if (guide) {
    const sum = new Float32Array(rBins), cnt = new Float32Array(rBins);
    for (let i = 0; i < rBins; i++) {
      const r = (i + 0.5) / rBins * rMax;
      for (let j = 0; j < 180; j++) {
        const a = j / 180 * 2 * Math.PI;
        sum[i] += texel(r * Math.cos(a), r * Math.sin(a)).lum; cnt[i]++;
      }
      mean[i] = Math.max(0.02, sum[i] / cnt[i]);
    }
  }
  const meanAt = (r: number): number => mean[Math.min(rBins - 1, Math.floor(r / rMax * rBins))];
  /** >1 on a painted arm, <1 in a painted gap or dust lane. */
  const contrast = (x: number, y: number): number => texel(x, y).lum / meanAt(Math.hypot(x, y));
  const tint = (rgb: RGB): RGB => {
    const m = Math.max(rgb[0], rgb[1], rgb[2], 1e-3);
    return [rgb[0] / m, rgb[1] / m, rgb[2] / m];
  };
  const cb = Math.cos(BAR_ANGLE_RAD), sb = Math.sin(BAR_ANGLE_RAD);
  /** Inside the bar's footprint (padded)? No dust is laid there (JWST B1 request). */
  const inBar = (x: number, y: number): boolean => {
    const along = -x * cb + y * sb, across = x * sb + y * cb;
    return Math.abs(along) < BAR_HALF_LEN_KPC + 0.3 && Math.abs(across) < 1.5;
  };

  const glow = new Sprites();
  const dust = new Sprites();

  // ── Bulge: boxy/peanut, warm, along the bar ──
  const bulgeScale = 0.7;
  for (let i = 0; i < counts.bulge; i++) {
    const r = bulgeScale * Math.pow(-Math.log(1 - rnd()), 1 / 4);
    const u = rnd() * 2 - 1, t = rnd() * 2 * Math.PI;
    let along = r * Math.sqrt(1 - u * u) * Math.cos(t);
    const across = r * Math.sqrt(1 - u * u) * Math.sin(t);
    let z = r * 0.6 * u;
    z *= 1 + 0.35 * Math.min(1, Math.abs(along) / (bulgeScale * 1.2)); // peanut
    along *= 1.3;
    const x = -along * cb + across * sb, y = along * sb + across * cb;
    glow.add(x, y, z, 0.35 + 0.45 * rnd(), lerpRGB(COL_BULGE_HOT, COL_BULGE_COOL, rnd()), 0.10 + 0.10 * rnd(), puffCell());
  }

  // ── Arm body: follows the texture's bright lanes at every azimuth ──
  for (let i = 0, tries = 0; i < counts.texArm && tries < counts.texArm * 60; tries++) {
    const r = 2.6 + Math.pow(rnd(), 0.8) * 12.4;
    const a = rnd() * 2 * Math.PI;
    const x = r * Math.cos(a), y = r * Math.sin(a);
    const c = contrast(x, y);
    if (rnd() > (c - 0.95) * 2.5) { continue; }
    const z = gauss() * 0.06 * flare(r) + warpZ(x, y);
    const col = lerpRGB(tint(texel(x, y).rgb), COL_ARM_YOUNG, 0.35);
    glow.add(x, y, z, 0.22 + 0.32 * rnd(), col, 0.06 + 0.07 * rnd(), puffCell());
    i++;
  }

  // ── Measured arm ridges (Reid et al. 2019): cross-arm age gradient ──
  // Young/blue on the inner (compression) edge, warmer on the outer edge.
  const totalW = ARMS.reduce((acc, arm) => acc + arm.weight * (arm.betaMaxDeg - arm.betaMinDeg), 0);
  for (const arm of ARMS) {
    const share = arm.weight * (arm.betaMaxDeg - arm.betaMinDeg) / totalW;
    const nRidge = Math.round(counts.ridge * share), nKnots = Math.round(counts.knots * share);
    for (let i = 0; i < nRidge; i++) {
      const beta = arm.betaMinDeg + rnd() * (arm.betaMaxDeg - arm.betaMinDeg);
      const cross = gauss(); // in arm widths; negative = inner edge
      const [x, y] = armPoint(arm, beta, cross * arm.widthKpc * 1.6);
      const r = Math.hypot(x, y);
      const z = gauss() * 0.05 * flare(r) + warpZ(x, y);
      const young = 1 - Math.min(1, Math.max(0, (cross + 1.3) / 2.4));
      glow.add(x, y, z, 0.2 + 0.26 * rnd(), lerpRGB(COL_ARM_OLD, COL_ARM_YOUNG, 0.1 + 0.8 * young), 0.05 + 0.06 * rnd(), puffCell());
    }
    for (let i = 0; i < nKnots; i++) {
      const beta = arm.betaMinDeg + rnd() * (arm.betaMaxDeg - arm.betaMinDeg);
      const [x, y] = armPoint(arm, beta, gauss() * arm.widthKpc);
      const z = gauss() * 0.04 + warpZ(x, y);
      glow.add(x, y, z, 0.07 + 0.11 * rnd(), rnd() < 0.6 ? COL_HII : COL_OB, 0.28 + 0.28 * rnd(), CELL.hii);
    }
  }

  // ── Thick-disk haze: broad, faint, warm ──
  for (let i = 0; i < counts.haze; i++) {
    const r = 1.0 + Math.pow(rnd(), 0.6) * 13.0;
    const a = rnd() * 2 * Math.PI;
    const x = r * Math.cos(a), y = r * Math.sin(a);
    const z = gauss() * 0.18 * flare(r) + warpZ(x, y);
    glow.add(x, y, z, 0.5 + 0.7 * rnd(), lerpRGB(COL_THICK, COL_INTERARM, rnd() * 0.5), 0.035 + 0.04 * rnd(), CELL.glowSoft);
  }

  // ── Dust: real dark geometry in the texture's dark lanes, off the bar ──
  for (let i = 0, tries = 0; i < counts.dust && tries < counts.dust * 80; tries++) {
    const r = 3.0 + Math.pow(rnd(), 0.6) * 10.0;
    const a = rnd() * 2 * Math.PI;
    const x = r * Math.cos(a), y = r * Math.sin(a);
    if (inBar(x, y)) { continue; }
    if (rnd() > (0.97 - contrast(x, y)) * 5) { continue; }
    const z = (rnd() - 0.5) * 0.09 + warpZ(x, y);
    dust.add(x, y, z, 0.18 + 0.32 * rnd(), COL_INTERARM, 0.16 + 0.2 * rnd(), rnd() < 0.5 ? CELL.dustA : CELL.dustB);
    i++;
  }

  // ── Star sparkle: tiny points; texture, not body ──
  const sp: number[] = [], sc: number[] = [];
  for (let i = 0, tries = 0; i < counts.stars && tries < counts.stars * 40; tries++) {
    const kind = rnd();
    let x: number, y: number, z: number, col: RGB;
    if (kind < 0.12) { // bulge / bar
      const along = gauss() * 1.6, across = gauss() * 0.7;
      x = -along * cb + across * sb; y = along * sb + across * cb; z = gauss() * 0.45;
      col = lerpRGB(COL_BULGE_HOT, [1, 1, 1], rnd() * 0.4);
    } else if (kind < 0.2) { // old thick disk / inner halo, slightly flattened
      const r = Math.pow(rnd(), 0.5) * 16, a = rnd() * 2 * Math.PI;
      x = r * Math.cos(a); y = r * Math.sin(a); z = gauss() * 0.9;
      col = COL_THICK;
    } else { // thin disk, following the texture's light
      const r = 1.5 + Math.pow(rnd(), 0.75) * 14.5, a = rnd() * 2 * Math.PI;
      x = r * Math.cos(a); y = r * Math.sin(a);
      const t = texel(x, y);
      if (rnd() > t.lum * 2.2 + 0.03) { continue; }
      z = gauss() * 0.12 * flare(r) + warpZ(x, y);
      col = lerpRGB(tint(t.rgb), [1, 1, 1], 0.35);
    }
    // Luminosity law: nearly all dim, a few bright.
    const bright = rnd() < 0.03 ? 1.0 : 0.35 + 0.35 * rnd();
    sp.push(x, y, z);
    sc.push(col[0] * bright, col[1] * bright, col[2] * bright, bright > 0.9 ? 1.7 : 1.0);
    i++;
  }

  return {
    glow: glow.done(), dust: dust.done(),
    stars: { count: sp.length / 3, pos: new Float32Array(sp), color: new Float32Array(sc) },
  };
}
