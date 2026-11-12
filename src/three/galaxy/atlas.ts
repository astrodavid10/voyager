// =====================================================================
// Procedural sprite atlas (ported from JWST src/galaxy-atlas.ts)
// =====================================================================
// A 4 x 2 grid of soft white sprites whose shape lives in the ALPHA channel;
// the shader tints them per instance. Painted on a 2D canvas at start-up, so
// there is no asset to download or license.

export const CELL = {
  glowSoft: 0,   // broad smooth glow (thick disk haze)
  glowPuffA: 1,  // speckled puffs (arms, bulge)
  glowPuffB: 2,
  glowPuffC: 3,
  dustA: 4,      // clumpy dark sprites, used multiplicatively
  dustB: 5,
  hii: 6,        // tight knot with a small halo (H II regions, OB associations)
  star: 7,       // very tight core
} as const;

export const ATLAS_COLS = 4;
export const ATLAS_ROWS = 2;

function hash2(ix: number, iy: number, seed: number): number {
  let h = ix * 374761393 + iy * 668265263 + seed * 2147483647;
  h = (h ^ (h >> 13)) * 1274126177;
  h = h ^ (h >> 16);
  return (h >>> 0) / 4294967295;
}

function smooth(t: number): number { return t * t * (3 - 2 * t); }

function valueNoise(x: number, y: number, seed: number): number {
  const ix = Math.floor(x), iy = Math.floor(y);
  const u = smooth(x - ix), v = smooth(y - iy);
  const a = hash2(ix, iy, seed), b = hash2(ix + 1, iy, seed);
  const c = hash2(ix, iy + 1, seed), d = hash2(ix + 1, iy + 1, seed);
  return a * (1 - u) * (1 - v) + b * u * (1 - v) + c * (1 - u) * v + d * u * v;
}

function fbm(x: number, y: number, seed: number, octaves: number): number {
  let sum = 0, amp = 0.5, freq = 1;
  for (let o = 0; o < octaves; o++) {
    sum += amp * valueNoise(x * freq, y * freq, seed + o * 17);
    freq *= 2;
    amp *= 0.5;
  }
  return sum;
}

function paint(
  img: ImageData, ox: number, oy: number, n: number,
  profile: (rn: number, f: number) => number,
  seed: number, noiseScale: number, octaves: number,
): void {
  const data = img.data, half = (n - 1) / 2;
  for (let py = 0; py < n; py++) {
    for (let px = 0; px < n; px++) {
      const rn = Math.min(1, Math.hypot((px - half) / half, (py - half) / half));
      const f = octaves > 0 ? fbm(px / n * noiseScale, py / n * noiseScale, seed, octaves) : 1;
      const a = Math.max(0, Math.min(1, profile(rn, f)));
      const idx = ((oy + py) * img.width + (ox + px)) * 4;
      data[idx] = 255; data[idx + 1] = 255; data[idx + 2] = 255;
      data[idx + 3] = Math.round(a * 255);
    }
  }
}

/** Build the atlas canvas; cellPx 128 (full) or 64 (lite). Null without a 2D canvas. */
export function buildAtlas(cellPx: number): HTMLCanvasElement | null {
  const canvas = document.createElement("canvas");
  canvas.width = ATLAS_COLS * cellPx;
  canvas.height = ATLAS_ROWS * cellPx;
  const ctx = canvas.getContext("2d");
  if (!ctx) { return null; }
  const img = ctx.createImageData(canvas.width, canvas.height);
  const at = (index: number): [number, number] => [(index % ATLAS_COLS) * cellPx, Math.floor(index / ATLAS_COLS) * cellPx];
  // Every profile is forced to zero at the cell edge so neighbors never bleed.
  const edge = (rn: number): number => Math.min(1, (1 - rn) * 4);

  let [ox, oy] = at(CELL.glowSoft);
  paint(img, ox, oy, cellPx, (rn, f) => Math.exp(-rn * rn * 3.2) * (0.85 + 0.15 * f) * edge(rn), 11, 3, 2);

  for (const [cell, seed, ns] of [[CELL.glowPuffA, 101, 4], [CELL.glowPuffB, 211, 5], [CELL.glowPuffC, 307, 6]]) {
    [ox, oy] = at(cell);
    paint(img, ox, oy, cellPx, (rn, f) => Math.exp(-rn * rn * 2.6) * (0.45 + 0.55 * f) * Math.max(0, 1 - rn), seed, ns, 4);
  }
  for (const [cell, seed] of [[CELL.dustA, 401], [CELL.dustB, 523]]) {
    [ox, oy] = at(cell);
    paint(img, ox, oy, cellPx, (rn, f) => Math.exp(-rn * rn * 2.0) * (0.25 + 0.75 * f * f) * Math.max(0, 1 - rn), seed, 5, 4);
  }
  [ox, oy] = at(CELL.hii);
  paint(img, ox, oy, cellPx, (rn) => Math.min(1, Math.exp(-rn * rn * 9.0) + 0.30 * Math.exp(-rn * rn * 2.2)) * edge(rn), 0, 0, 0);
  [ox, oy] = at(CELL.star);
  paint(img, ox, oy, cellPx, (rn) => Math.exp(-rn * rn * 16.0), 0, 0, 0);

  ctx.putImageData(img, 0, 0);
  return canvas;
}
