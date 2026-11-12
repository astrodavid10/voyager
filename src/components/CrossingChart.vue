<template>
  <figure class="xc">
    <svg v-if="paths" :viewBox="`0 0 ${w} ${h}`" role="img" :aria-label="summary">
      <g class="grid">
        <line v-for="g in grid" :key="g.v" :x1="padL" :x2="w - 4" :y1="g.y" :y2="g.y" />
        <text v-for="g in grid" :key="'t' + g.v" :x="padL - 4" :y="g.y + 4" text-anchor="end">{{ g.label }}</text>
      </g>
      <line class="cross" :x1="xCross" :x2="xCross" :y1="4" :y2="h - 16" />
      <text class="cross-t" :x="xCross + 4" :y="14">{{ crossLabel }}</text>
      <path class="sol" :d="paths.sol" />
      <path class="gcr" :d="paths.gcr" />
      <text class="yr" :x="padL" :y="h - 2">{{ years[0] }}</text>
      <text class="yr" :x="w - 4" :y="h - 2" text-anchor="end">{{ years[1] }}</text>
    </svg>
    <figcaption>
      <span class="k sol">Particles from the Sun</span>
      <span class="k gcr">Cosmic rays from the Galaxy</span>
      <span class="src">Voyager {{ craftNo }} CRS daily data, NASA SPDF. Each line is relative to its level before the crossing.</span>
    </figcaption>
  </figure>
</template>

<script lang="ts">
import { defineComponent } from "vue";

interface Series { key: string; v: (number | null)[]; step?: { before_mean?: number } } // eslint-disable-line @typescript-eslint/naming-convention
interface Crossing { id: string; craft: string; date: string; t: string[]; series: Series[] }

const W = 340, H = 120, PAD_L = 34;
const Y_MIN = Math.log10(0.004), Y_MAX = Math.log10(3);

export default defineComponent({
  name: "CrossingChart",
  props: { id: { type: String, default: "v1_hp" } },
  data() {
    return { w: W, h: H, padL: PAD_L, data: null as Crossing | null };
  },
  computed: {
    craftNo(): string { return this.data?.craft.replace("Voyager ", "") ?? ""; },
    years(): string[] { return this.data ? [this.data.t[0].slice(0, 4), this.data.t[this.data.t.length - 1].slice(0, 4)] : ["", ""]; },
    crossLabel(): string {
      if (!this.data) { return ""; }
      return new Date(this.data.date + "T00:00:00Z").toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
    },
    xCross(): number {
      if (!this.data) { return 0; }
      return this.xFor(this.data.t.indexOf(this.data.date));
    },
    grid(): { v: number; y: number; label: string }[] {
      return [1, 0.1, 0.01].map((v) => ({ v, y: this.yFor(v), label: v === 1 ? "1×" : `${v}×` }));
    },
    paths(): { sol: string; gcr: string } | null {
      if (!this.data) { return null; }
      const get = (k: string) => this.data!.series.find((s) => s.key === k);
      const mk = (s?: Series): string => {
        if (!s) { return ""; }
        const base = s.step?.before_mean ?? 1;
        // 7-day running mean so the line reads on a phone without inventing data.
        let d = "", pen = false;
        for (let i = 0; i < s.v.length; i++) {
          let sum = 0, n = 0;
          for (let k = Math.max(0, i - 3); k <= Math.min(s.v.length - 1, i + 3); k++) {
            const x = s.v[k];
            if (x !== null && x > 0) { sum += x; n++; }
          }
          if (s.v[i] === null || n === 0) { pen = false; continue; }
          const y = this.yFor(sum / n / base);
          d += `${pen ? "L" : "M"}${this.xFor(i).toFixed(1)},${y.toFixed(1)}`;
          pen = true;
        }
        return d;
      };
      return { sol: mk(get("crs_low")), gcr: mk(get("crs_gcr")) };
    },
    summary(): string {
      return "Chart: at the heliopause, particles from the Sun dropped more than a hundredfold within days, while cosmic rays from the Galaxy rose.";
    },
  },
  async mounted() {
    try {
      this.data = await (await fetch(`./data/crossings/${this.id}.json`)).json();
    } catch (err) {
      console.error("[CrossingChart]", err);
    }
  },
  methods: {
    xFor(i: number): number { return PAD_L + (i / Math.max(1, (this.data?.t.length ?? 2) - 1)) * (W - PAD_L - 4); },
    yFor(v: number): number {
      const l = Math.min(Y_MAX, Math.max(Y_MIN, Math.log10(Math.max(v, 1e-6))));
      return 4 + (1 - (l - Y_MIN) / (Y_MAX - Y_MIN)) * (H - 22);
    },
  },
});
</script>

<style lang="less">
.xc {
  margin: 0 0 12px;
  svg { width: 100%; height: auto; display: block; }
  .grid line { stroke: rgba(200, 210, 255, 0.15); stroke-width: 1; }
  .grid text, .yr { fill: #b9bfe6; font-size: 11px; }
  .cross { stroke: #fff; stroke-dasharray: 3 3; stroke-width: 1; opacity: 0.7; }
  .cross-t { fill: #fff; font-size: 11px; }
  path { fill: none; stroke-width: 2; stroke-linejoin: round; }
  path.sol { stroke: #ffd166; }
  path.gcr { stroke: #b39dff; }
  figcaption { display: flex; flex-wrap: wrap; gap: 4px 12px; font-size: 13px; color: #b9bfe6; margin-top: 4px; }
  .k::before { content: ""; display: inline-block; width: 14px; height: 3px; margin-right: 5px; vertical-align: middle; }
  .k.sol::before { background: #ffd166; }
  .k.gcr::before { background: #b39dff; }
  .src { flex-basis: 100%; font-size: 12px; opacity: 0.85; }
}
</style>
