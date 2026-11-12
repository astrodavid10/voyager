<template>
  <div class="lrec" role="status" aria-live="polite">
    <svg viewBox="-110 -110 220 220" width="200" height="200" aria-hidden="true" :class="{ still: reduced }">
      <!-- the record -->
      <circle class="disc" r="100" />
      <circle class="groove" r="88" />
      <circle class="groove" r="76" />
      <circle class="label" r="30" />
      <circle class="hole" r="2.4" />
      <!-- pulsar map: lines from the Sun, angle = Galactic longitude, length ∝ distance -->
      <g class="map" transform="translate(-44 30) scale(0.42)">
        <line class="gc" x1="0" y1="0" x2="150" y2="0" />
        <g v-for="(r, i) in rays" :key="i" :style="{ '--d': i * 0.11 + 's' }">
          <line class="ray" x1="0" y1="0" :x2="r.x" :y2="r.y" pathLength="1" />
          <g class="ticks">
            <line
              v-for="(t, k) in r.ticks" :key="k" :x1="t.x - t.nx" :y1="t.y - t.ny" :x2="t.x + t.nx"
              :y2="t.y + t.ny"
            />
          </g>
        </g>
        <circle class="sun" r="3" />
      </g>
      <!-- hydrogen hyperfine transition, the record's unit of time and length -->
      <g class="hydrogen" transform="translate(52 52)">
        <circle cx="-9" cy="0" r="5" /><circle cx="9" cy="0" r="5" />
        <line x1="-4" y1="0" x2="4" y2="0" />
      </g>
    </svg>
    <p>{{ text }}</p>
  </div>
</template>

<script lang="ts">
import { defineComponent } from "vue";

interface Ray { x: number; y: number; ticks: { x: number; y: number; nx: number; ny: number }[] }

/**
 * Loading mark: the Voyager Golden Record cover's pulsar map drawing itself
 * (14 pulsars + the line to the Galactic centre). Uses public/data/pulsars.json
 * (Galactic longitude + distance) when present; until then an evenly spread
 * stand-in. Static under prefers-reduced-motion. The binary period ticks are
 * decorative here (the real encoding is in the cover, NASA/JPL).
 */
export default defineComponent({
  name: "LoadingRecord",
  props: { text: { type: String, default: "Loading the 3D view…" } },
  data() {
    return {
      rays: this.fallback() as Ray[],
      reduced: window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false,
    };
  },
  async mounted() {
    try {
      const r = await fetch("./data/pulsars.json");
      if (!r.ok) { return; }
      const d = await r.json() as { pulsars?: { gl: number; dist_kpc: number }[] }; // eslint-disable-line @typescript-eslint/naming-convention
      if (!d.pulsars?.length) { return; }
      const maxD = Math.max(...d.pulsars.map((p) => p.dist_kpc));
      this.rays = d.pulsars.map((p) => this.ray(p.gl, 40 + 90 * (p.dist_kpc / maxD)));
    } catch { /* keep the stand-in */ }
  },
  methods: {
    ray(glDeg: number, len: number): Ray {
      // Galactic centre to the right (l = 0), l increasing counter-clockwise.
      const a = (glDeg * Math.PI) / 180;
      const ux = Math.cos(a), uy = -Math.sin(a);
      const ticks = [];
      for (let k = 1; k <= 6; k++) {
        const f = 0.45 + k * 0.08;
        const h = k % 2 ? 4 : 7; // short = 0, long = 1, like the cover's binary marks
        ticks.push({ x: ux * len * f, y: uy * len * f, nx: -uy * h, ny: ux * h });
      }
      return { x: ux * len, y: uy * len, ticks };
    },
    fallback(): Ray[] {
      const out: Ray[] = [];
      for (let i = 0; i < 14; i++) { out.push(this.ray(12 + i * (336 / 13), 60 + ((i * 37) % 60))); }
      return out;
    },
  },
});
</script>

<style lang="less">
.lrec {
  display: grid; justify-items: center; gap: 14px; color: #cfd6ff; font-size: 16px; text-align: center;
  p { margin: 0; }
  .disc { fill: #2a1f05; stroke: #e0b44c; stroke-width: 2; }
  .groove { fill: none; stroke: rgba(224, 180, 76, 0.28); stroke-width: 1; }
  .label { fill: #3b2b08; stroke: #e0b44c; stroke-width: 1; }
  .hole { fill: #05030f; }
  .map line { stroke: #f2cf74; stroke-width: 2.4; stroke-linecap: round; }
  .map .gc { stroke-width: 2; opacity: 0.85; }
  .map .sun { fill: #fff3c4; }
  .ticks line { stroke-width: 1.6; }
  .hydrogen circle { fill: none; stroke: #f2cf74; stroke-width: 1.4; }
  .hydrogen line { stroke: #f2cf74; stroke-width: 1.4; }
  .ray { stroke-dasharray: 1; stroke-dashoffset: 1; animation: lrec-draw 4.2s ease-in-out infinite; animation-delay: var(--d); }
  .ticks { opacity: 0; animation: lrec-ticks 4.2s ease-in-out infinite; animation-delay: var(--d); }
  .still .ray { animation: none; stroke-dashoffset: 0; }
  .still .ticks { animation: none; opacity: 1; }
}
@keyframes lrec-draw {
  0% { stroke-dashoffset: 1; } 35%, 80% { stroke-dashoffset: 0; opacity: 1; } 100% { stroke-dashoffset: 0; opacity: 0; }
}
@keyframes lrec-ticks { 0%, 30% { opacity: 0; } 45%, 80% { opacity: 1; } 100% { opacity: 0; } }
</style>
