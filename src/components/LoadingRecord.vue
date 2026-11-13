<template>
  <div class="lrec" role="status" aria-live="polite">
    <svg
      viewBox="-70 -150 340 300" width="320" height="282" aria-hidden="true"
      :class="{ still: reduced }"
    >
      <defs>
        <radialGradient id="lrec-bulge">
          <stop offset="0" stop-color="#fff1d6" stop-opacity="0.95" />
          <stop offset="0.35" stop-color="#f3c98b" stop-opacity="0.45" />
          <stop offset="1" stop-color="#9a86ff" stop-opacity="0" />
        </radialGradient>
        <filter id="lrec-glow" x="-20%" y="-20%" width="140%" height="140%">
          <feGaussianBlur stdDeviation="3.5" />
        </filter>
      </defs>
      <!-- The Milky Way seen from above (north), drawing itself outward from the center. -->
      <g class="galaxy">
        <ellipse class="bar" :cx="bar.cx" :cy="bar.cy" rx="58" ry="13" :transform="`rotate(${bar.rot} ${bar.cx} ${bar.cy})`" />
        <path v-for="(d, i) in arms" :key="'g' + i" class="arm-glow" :d="d" pathLength="1" />
        <path v-for="(d, i) in arms" :key="'a' + i" class="arm" :d="d" pathLength="1" />
        <path class="arm local" :d="localArm" pathLength="1" />
        <circle class="bulge" :cx="GC_LEN" cy="0" r="42" />
      </g>
      <!-- The Golden Record pulsar map, already drawn, at the Sun's place in the disk. -->
      <g class="map">
        <line class="gc" x1="0" y1="0" :x2="GC_LEN" y2="0" />
        <g v-for="r in rays" :key="r.name">
          <line class="inner" x1="0" y1="0" :x2="r.ix" :y2="r.iy" />
          <line v-for="(m, k) in r.marks" :key="k" class="digit" :x1="m.x1" :y1="m.y1" :x2="m.x2" :y2="m.y2" />
        </g>
        <circle class="sun" r="2" />
      </g>
    </svg>
    <p>{{ text }}</p>
    <p class="lrec-sub">Our home in the Milky Way, marked by the Golden Record's pulsar map.</p>
  </div>
</template>

<script lang="ts">
import { defineComponent } from "vue";

/**
 * Loading mark: the Milky Way's spiral arms draw outward from its center around
 * the Golden Record cover's pulsar map, which is complete from the first frame
 * (a fast load still shows the whole map, not one line).
 *
 * Galaxy: seen from the north Galactic pole, Galactic longitude counter-clockwise
 * (as on the cover), the Sun at the origin and the center GC_LEN to its right, so
 * GC_LEN = R0 = 8.18 kpc. Four trailing log-spiral arms (pitch 12 deg, radii at the
 * Sun's azimuth after Reid et al. 2019: Norma, Scutum-Centaurus, Sagittarius-
 * Carina, Perseus; Norma continues as the Outer arm), the Local arm from Reid's
 * fit and the long bar (27 deg, near end at positive longitude). A sketch, not a map.
 *
 * Pulsar map:
 * Geometry is the cover's own, measured from NASA's photo (public/data/pulsars.json,
 * docs/RESEARCH-pulsars-flybys.md): each line's angle counter-clockwise from the
 * Galactic-centre line (= Galactic longitude) and its engraved length as a
 * fraction of that line. Each line carries its pulsar's period in binary, in
 * units of the hydrogen hyperfine period, as on the cover: plain near the Sun,
 * then the digits (1 = a short tick across the line, 0 = a dash along it).
 * Embedded here so the loader needs no network. Pulsars identified by
 * W. R. Johnston; cover NASA/JPL. Static under prefers-reduced-motion.
 */
const MAP: [string, number, number, string][] = [
  ["B1727-47", 343.6, 0.509, "1000110001111100100011011101010"],
  ["B1451-68", 311.9, 0.207, "10110010011000101011101101111"],
  ["B1240-64", 303.2, 0.544, "100000110110010110001001111000"],
  ["B0833-45", 264.6, 0.331, "111100011011011001010100111"],
  ["B0950+08", 228.9, 0.205, "10101011011001101100101000011"],
  ["B0823+26", 197.4, 0.231, "101100111011010101011110001011"],
  ["B0531+21", 185.1, 0.387, "10110011100000101010000010"],
  ["B0525+21", 182.8, 0.352, "100111101000110101000100111000100"],
  ["B0329+54", 147.2, 0.253, "111100011111100011111000010110"],
  ["B2217+47", 99.9, 0.313, "101101100101101001000010110001"],
  ["B2016+28", 68.7, 0.225, "101111001111001110011000001101"],
  ["B1933+16", 52.2, 0.557, "11110010111110001110100011110"],
  ["B1929+10", 47.3, 0.219, "10011001011010111010010111000"],
  ["B1642-03", 13.6, 0.293, "100000110100101010001110101100"],
];
const GC_LEN = 100;
const KPC = GC_LEN / 8.18;              // svg units per kpc
const TAN_PITCH = Math.tan((12 * Math.PI) / 180);
const RAD = Math.PI / 180;
/** Galactocentric (R kpc, azimuth beta rad; beta grows with rotation) -> svg. */
function gal(r: number, beta: number): [number, number] {
  return [(-r * Math.cos(beta) + 8.18) * KPC, -r * Math.sin(beta) * KPC];
}
function pathOf(pts: [number, number][]): string {
  return pts.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`).join("");
}

interface Mark { x1: number; y1: number; x2: number; y2: number }
interface Ray { name: string; ix: number; iy: number; marks: Mark[] }

export default defineComponent({
  name: "LoadingRecord",
  props: { text: { type: String, default: "Loading the 3D view…" } },
  data() {
    return {
      GC_LEN, // eslint-disable-line @typescript-eslint/naming-convention
      reduced: window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false,
    };
  },
  computed: {
    /** Four arms, inner end (bar tip, 3.2 kpc) to 14 kpc; radius at the Sun's azimuth 10.1 kpc / 1.4^i. */
    arms(): string[] {
      const out: string[] = [];
      for (let i = 0; i < 4; i++) {
        const r0 = 10.07 * Math.pow(Math.exp((Math.PI / 2) * TAN_PITCH), -i);
        const pts: [number, number][] = [];
        for (let r = 3.2; r <= 14; r *= 1.02) { pts.push(gal(r, -Math.log(r / r0) / TAN_PITCH)); }
        out.push(pathOf(pts));
      }
      return out;
    },
    /** Local (Orion) arm, Reid et al. 2019: R = 8.26 kpc at beta 9 deg, pitch 11.4 deg, beta -8..34. */
    localArm(): string {
      const pts: [number, number][] = [];
      for (let b = 34; b >= -8; b -= 2) {
        pts.push(gal(8.26 * Math.exp(-(b - 9) * RAD * Math.tan(11.4 * RAD)), b * RAD));
      }
      return pathOf(pts);
    },
    bar(): { cx: number; cy: number; rot: number } {
      return { cx: GC_LEN, cy: 0, rot: 27 }; // near end up-left (toward positive longitude)
    },
    rays(): Ray[] {
      return MAP.map(([name, ang, rel, bits]) => {
        const a = (ang * Math.PI) / 180;
        const ux = Math.cos(a), uy = -Math.sin(a); // y down: counter-clockwise = -y
        const nx = -uy, ny = ux;                    // perpendicular
        const len = rel * GC_LEN;
        // The digits fill the outer part of the line; short lines are mostly digits,
        // which is why the cover lengthens them.
        const step = Math.min(1.5, (len * 0.62) / bits.length);
        const start = len - step * bits.length;
        const marks: Mark[] = [];
        for (let k = 0; k < bits.length; k++) {
          const t = start + (k + 0.5) * step;
          const cx = ux * t, cy = uy * t;
          if (bits[k] === "1") {
            marks.push({ x1: cx - nx * 1.4, y1: cy - ny * 1.4, x2: cx + nx * 1.4, y2: cy + ny * 1.4 });
          } else {
            const h = step * 0.32;
            marks.push({ x1: cx - ux * h, y1: cy - uy * h, x2: cx + ux * h, y2: cy + uy * h });
          }
        }
        return { name, ix: ux * start, iy: uy * start, marks };
      });
    },
  },
});
</script>

<style lang="less">
.lrec {
  display: grid; justify-items: center; gap: 6px; color: #cfd6ff; font-size: 16px; text-align: center;
  p { margin: 0; }
  .lrec-sub { font-size: 13px; color: #b9bfe6; max-width: 280px; }
  svg { max-width: 86vw; height: auto; overflow: visible; }
  .bar { fill: #f3d6a8; opacity: 0.22; filter: url(#lrec-glow); }
  .bulge { fill: url(#lrec-bulge); }
  .arm-glow { fill: none; stroke: #a99bff; stroke-width: 9; opacity: 0.35; stroke-linecap: round; filter: url(#lrec-glow); }
  .arm { fill: none; stroke: #d9d2ff; stroke-width: 1.6; opacity: 0.8; stroke-linecap: round; }
  .arm.local { stroke-width: 1.1; opacity: 0.55; }
  .arm, .arm-glow { stroke-dasharray: 1; stroke-dashoffset: 1; animation: lrec-draw 2.4s cubic-bezier(0.2, 0.6, 0.3, 1) forwards; }
  .bulge, .bar { animation: lrec-glow 2.4s ease-out forwards; }
  .map line { stroke: #f2cf74; stroke-linecap: round; }
  .gc, .inner { stroke-width: 0.9; }
  .digit { stroke-width: 0.7; }
  .sun { fill: #fff3c4; }
  .still .arm, .still .arm-glow { animation: none; stroke-dashoffset: 0; }
  .still .bulge, .still .bar { animation: none; }
}
@keyframes lrec-draw { to { stroke-dashoffset: 0; } }
@keyframes lrec-glow { from { opacity: 0; } }
</style>
