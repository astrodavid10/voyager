<template>
  <div class="lrec" role="status" aria-live="polite">
    <svg
      viewBox="-62 -66 172 132" width="320" height="246" aria-hidden="true"
      :class="{ still: reduced }"
    >
      <!-- The line to the centre of the Galaxy (drawn first; it sets the scale). -->
      <line class="gc" x1="0" y1="0" :x2="GC_LEN" y2="0" pathLength="1" />
      <g v-for="(r, i) in rays" :key="r.name" class="ray" :style="{ '--d': 0.6 + i * 0.12 + 's' }">
        <!-- plain inner part, near the Sun -->
        <line class="inner" x1="0" y1="0" :x2="r.ix" :y2="r.iy" pathLength="1" />
        <!-- outer part: the period in binary, 1 = tick across, 0 = dash along -->
        <g class="digits">
          <line v-for="(m, k) in r.marks" :key="k" :x1="m.x1" :y1="m.y1" :x2="m.x2" :y2="m.y2" />
        </g>
      </g>
      <circle class="sun" r="1.6" />
      <!-- hydrogen hyperfine transition: the map's unit of time -->
      <g class="hydrogen" transform="translate(78 44)">
        <circle cx="-7" cy="0" r="3.4" /><circle cx="7" cy="0" r="3.4" />
        <line x1="-3.6" y1="0" x2="3.6" y2="0" /><line x1="0" y1="-1.6" x2="0" y2="1.6" />
      </g>
    </svg>
    <p>{{ text }}</p>
    <p class="lrec-sub">The pulsar map from Voyager's Golden Record: the way home, in binary.</p>
  </div>
</template>

<script lang="ts">
import { defineComponent } from "vue";

/**
 * Loading mark: the Golden Record cover's pulsar map drawing itself.
 *
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
  svg { max-width: 80vw; height: auto; }
  line { stroke: #f2cf74; stroke-linecap: round; }
  .gc, .inner { stroke-width: 0.9; }
  .digits line { stroke-width: 0.8; }
  .sun { fill: #fff3c4; }
  .hydrogen circle { fill: none; stroke: #f2cf74; stroke-width: 0.8; }
  .hydrogen line { stroke-width: 0.8; }
  .gc { stroke-dasharray: 1; stroke-dashoffset: 1; animation: lrec-line 0.9s ease-out forwards; }
  .inner { stroke-dasharray: 1; stroke-dashoffset: 1; animation: lrec-line 0.7s ease-out forwards; animation-delay: var(--d); }
  .digits { opacity: 0; animation: lrec-fade 0.6s ease-out forwards; animation-delay: calc(var(--d) + 0.6s); }
  .hydrogen { opacity: 0; animation: lrec-fade 0.8s ease-out 2.8s forwards; }
  .still .gc, .still .inner { animation: none; stroke-dashoffset: 0; }
  .still .digits, .still .hydrogen { animation: none; opacity: 1; }
}
@keyframes lrec-line { to { stroke-dashoffset: 0; } }
@keyframes lrec-fade { to { opacity: 1; } }
</style>
