<template>
  <div ref="root" class="v3d" :class="{ ready }">
    <WorldWideTelescope wwt-namespace="wwt-voyager" />
    <div class="v3d-pins" aria-hidden="true">
      <div
        v-for="p in pins"
        v-show="p.visible"
        :key="p.id"
        class="pin"
        :class="['pin-' + p.kind, 'pin-' + p.id, { flip: p.side === 'l', ring: p.ring }]"
        :style="{ transform: `translate(${p.x}px, ${p.y}px)`, '--pin': p.color }"
      >
        <span class="pin-dot" />
        <span v-show="!p.labelHidden && !p.leader" class="pin-label" :style="{ top: (p.dy ?? -10) + 'px' }">{{ p.label }}<small v-if="p.sub">{{ p.sub }}</small></span>
      </div>
    </div>
    <div class="v3d-pins" aria-hidden="true">
      <div v-for="p in leaderPins" :key="'ld-' + p.id" class="leader">
        <div class="leader-line" :style="leaderLine(p)" />
        <div
          class="leader-label" :class="{ right: p.leaderSide === 'r' }"
          :style="{ transform: `translate(${p.lx}px, ${p.ly}px)`, '--pin': p.color }"
        >
          {{ p.label }}
        </div>
      </div>
    </div>
    <nav v-if="ready" class="ladder" aria-label="Distance from the Sun">
      <div class="ladder-rail" />
      <div class="ladder-now" :style="{ top: ladderNowPct + '%' }" aria-hidden="true" />
      <button
        v-for="(r, i) in ladder" :key="r.id" type="button" class="rung"
        :class="{ hot: r.id === 'voyager1' }"
        data-obstacle
        :style="{ top: (1 - i / (ladder.length - 1)) * 100 + '%' }"
        :aria-label="`Fly out to ${r.label}, ${r.au.toLocaleString()} au`"
        @click="flyRung(r.au)"
      >
        <span class="rung-dot" />
        <span class="rung-t">{{ r.label }}<small>{{ r.short }}</small></span>
      </button>
    </nav>
    <!-- CC BY-SA attribution while the galaxy is on screen; tap for full credits. -->
    <button v-if="galaxyCredit" type="button" class="v3d-credit" data-obstacle @click="$emit('show-credits')">
      Milky Way: ESA/Gaia/DPAC, S. Payne-Wardenaar · CC BY-SA
    </button>
    <div v-if="!ready && !failed" class="v3d-cover"><loading-record /></div>
    <div v-if="failed" class="v3d-cover v3d-failed">
      <p>The 3D view could not start on this device or network.</p>
      <button type="button" class="btn" @click="retry">Try again</button>
    </div>
  </div>
</template>

<script lang="ts">
// Patches must run at import time, before <WorldWideTelescope> mounts (sol footgun 10).
import "../wwt/wwt-hacks";

import { EngineSetting, RenderContext, WWTControl } from "@wwtelescope/engine";
import { WWTAwareComponent, WWTComponent, wwtPinia } from "@wwtelescope/engine-pinia";
import { PropType, defineComponent, markRaw } from "vue";
import {
  ArrowHelper, BufferGeometry, DoubleSide, Float32BufferAttribute, Group, Line, LineBasicMaterial, Mesh, MeshBasicMaterial,
  Points, ShaderMaterial, Vector3,
} from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";

import { getAppHandle } from "../appHandle";
import LoadingRecord from "./LoadingRecord.vue";
import { CROSSINGS, LADDER } from "../data/chapters";
import {
  Ephemeris, Vec3, distanceAu, formatLightTime, lightHoursFromEarth, loadEphemeris,
  positionAt, sampleIndexAt,
} from "../data/ephem";
import { Projected, ProjectTarget, projectTargets } from "../three/project";
import type { GalaxyLabel, GalaxyLayer } from "../three/galaxy";
import { createOortPoints } from "../three/oortPoints";
import { PaleBlueDot, createPaleBlueDot } from "../three/paleBlueDot";
import { FamilyPortrait, createFamilyPortrait } from "../three/familyPortrait";
import { Flyby, PulsarMap, createFlyby, createPulsarMap } from "../three/farLayers";
import { createShellMaterial } from "../three/shellMaterial";
import { ThreeStage, createThreeStage } from "../three/stage";
import { installSunGestures, type SunGestures } from "../wwt/gestures";
import { installHiDpiCanvas } from "../wwt/wwt-hacks";
import {
  Shot, StageHost, aimZoom, currentDistanceAu, currentShot, fitDistance, flyTo, initVoyagerStage, liveTargetEcl,
  rollForUp, viewFromEcliptic,
} from "../wwt/voyagerStage";

let engineInstalled = false;
function installEngine(): void {
  if (engineInstalled) { return; }
  const app = getAppHandle();
  if (!app) { console.error("[VoyagerView3D] no app handle"); return; }
  app.use(wwtPinia);
  app.component("WorldWideTelescope", WWTComponent);
  engineInstalled = true;
}
installEngine();

const CRAFT = ["voyager1", "voyager2"] as const;
/** Length of the "toward the Galactic center" arrow, au (past the 283,000 au tidal edge). */
const GC_ARROW_AU = 380000;
/** Family Portrait: camera-to-pivot distance, au (the camera stays at Voyager 1). */
const FAM_EYE = 0.05;

function eclXYZ(lonDeg: number, latDeg: number, rAu: number): Vec3 {
  const lo = (lonDeg * Math.PI) / 180, la = (latDeg * Math.PI) / 180;
  return [rAu * Math.cos(la) * Math.cos(lo), rAu * Math.cos(la) * Math.sin(lo), rAu * Math.sin(la)];
}
const OVERALL_TIMEOUT_MS = 20000;

interface Pin {
  id: string; kind: string; label: string; sub: string; color: string;
  x: number; y: number; visible: boolean;
  /** Label side chosen by the declutter pass ("r" default, "l" flipped). */
  side?: "r" | "l";
  /** Label top offset from the dot, px (-10 = beside it). */
  dy?: number;
  /** Dot only: the label would have covered a higher-priority label. */
  labelHidden?: boolean;
  /** Draw as an open ring (Pale Blue Dot Earth: the real dot shows through). */
  ring?: boolean;
  /** Label parked at (lx, ly) with a leader line to the dot (fast-moving Earth). */
  leader?: boolean;
  lx?: number;
  ly?: number;
  /** Which side of the dot the parked label sits ("l": (lx, ly) is its right edge; "r": its left edge). */
  leaderSide?: "l" | "r";
}

/** Lower = placed first, so it wins a collision. */
const PIN_PRIORITY: Record<string, number> = {
  craft: 1, flyby: 2, sun: 3, planet: 4, galaxy: 5, crossing: 6, star: 6, pulsar: 8,
};

interface Rect { x0: number; y0: number; x1: number; y1: number }
/** Markers a top-priority label may cover when nothing else fits (minor ticks only). */
const SMALL_KINDS = new Set(["crossing", "pulsar"]);
const placed: Rect[] = [];
const dots: Rect[] = [];
const order: Pin[] = [];

/**
 * Label declutter, every frame (AUDIT: labels must not cover each other).
 * Pins are placed in priority order; each label tries the right side of its
 * dot, then the left; if both collide with an already-placed label (or leave
 * the screen), only the dot is drawn. Widths are estimated from text length
 * (no DOM measuring per frame). Markers never move.
 */
function declutter(pins: Pin[], vw: number, vh: number, obstacles: Rect[]): void {
  order.length = 0;
  for (const p of pins) { if (p.visible) { order.push(p); } }
  order.sort((a, b) => (PIN_PRIORITY[a.kind] ?? 9) - (PIN_PRIORITY[b.kind] ?? 9));
  placed.length = 0;
  // UI chrome (header, ladder, card, credit, QR) is pre-placed: labels yield to it.
  for (const o of obstacles) { placed.push(o); }
  // So are ALL visible markers (a label must not hide another pin's dot).
  dots.length = 0;
  for (const p of order) {
    const d = p.ring ? 17 : 7;
    dots.push({ x0: p.x - d, y0: p.y - d, x1: p.x + d, y1: p.y + d });
  }
  for (let i = 0; i < order.length; i++) {
    const p = order[i];
    const own = dots[i];
    if (p.leader) {
      // Parked label: reserve its box so other labels stay clear of it.
      const lx = p.lx ?? 0, ly = p.ly ?? 0;
      placed.push(p.leaderSide === "r" ? { x0: lx - 2, y0: ly - 11, x1: lx + 60, y1: ly + 11 }
        : { x0: lx - 60, y0: ly - 11, x1: lx + 2, y1: ly + 11 });
      continue;
    }
    const small = p.kind === "pulsar" || p.kind === "crossing";
    const cw = small ? 6.6 : 7.6;
    // Labels wrap at 170 px, so long names take two lines: estimate the height.
    const textW = Math.max(p.label.length, p.sub.length * 0.92) * cw;
    const w = Math.min(170, textW) + 6;
    const lines = Math.ceil(textW / 170) + (p.sub ? 1 : 0);
    const h = lines * 17 + 2;
    const gap = p.ring ? 22 : 11;
    // Candidate placements: beside the dot, then above, then below it.
    const cands: [Pin["side"], number][] = [["r", -10], ["l", -10], ["r", -h - 4], ["l", -h - 4], ["r", 8], ["l", 8],
      ["r", -h - 30], ["l", -h - 30], ["r", 34], ["l", 34]];
    const rectFor = (side: Pin["side"], dy: number): Rect => side === "r"
      ? { x0: p.x + gap, y0: p.y + dy, x1: p.x + gap + w, y1: p.y + dy + h }
      : { x0: p.x - gap - w, y0: p.y + dy, x1: p.x - gap, y1: p.y + dy + h };
    const over = (r: Rect, q: Rect) => r.x0 < q.x1 && r.x1 > q.x0 && r.y0 < q.y1 && r.y1 > q.y0;
    const fits = (r: Rect) => r.x0 >= 2 && r.x1 <= vw - 2 && r.y0 >= 0 && r.y1 <= vh
      && !placed.some((q) => over(r, q)) && !dots.some((q) => q !== own && over(r, q));
    // Top-priority labels (craft, flyby, Sun) may cover LOWER-priority markers
    // rather than vanish; everything else must clear every marker.
    const loose = (r: Rect) => r.x0 >= 2 && r.x1 <= vw - 2 && r.y0 >= 0 && r.y1 <= vh
      && !placed.some((q) => over(r, q))
      && !dots.some((q, k) => q !== own && over(r, q) && !SMALL_KINDS.has(order[k].kind));
    const vip = (PIN_PRIORITY[p.kind] ?? 9) <= 3;
    p.labelHidden = true;
    for (const test of vip ? [fits, loose] : [fits]) {
      const hit = cands.find(([side, dy]) => test(rectFor(side, dy)));
      if (hit) {
        p.side = hit[0]; p.dy = hit[1]; p.labelHidden = false;
        placed.push(rectFor(hit[0], hit[1]));
        break;
      }
    }
  }
}

interface Runtime {
  stage: ThreeStage | null;
  gestures: SunGestures | null;
  eph: Ephemeris | null;
  trails: Record<string, { line: Line; geom: BufferGeometry; count: number }>;
  world: Group | null;
  helio: { root: Group; morphs: Mesh[] } | null;
  offset: Vec3;
  shellMats: Record<string, ShaderMaterial>;
  tidal: Group | null;
  gcArrow: ArrowHelper | null;
  /** Nearest stars, pin id -> heliocentric ecliptic au (public/data/neighbors.json). */
  neighbors: Record<string, Vec3>;
  oort: Points | null;
  galaxy: GalaxyLayer | null;
  galaxyLabels: Record<string, GalaxyLabel>;
  pbd: PaleBlueDot | null;
  pbdAlpha: number;
  family: FamilyPortrait | null;
  familyAlpha: number;
  /** Standing at Voyager 1 for the whole Family Portrait: zoom held at FAM_EYE. */
  famEye: boolean;
  pulsarMap: PulsarMap | null;
  flyby: Flyby | null;
  obstacles: Rect[];
  obstaclesAt: number;
  momentAlpha: number;
  momentT0: number;
  flybyYears: number;
  lastYearEmit: number;
  lastFadeMs: number;
  lastTimeSync: number;
  targets: ProjectTarget[];
  projected: Projected[];
  timer: number;
  destroyed: boolean;
}

export default defineComponent({
  name: "VoyagerView3D",
  extends: WWTAwareComponent,
  components: { "loading-record": LoadingRecord },

  props: {
    chapter: { type: String, required: true },
    sceneMs: { type: Number, required: true },
    shape: { type: String as PropType<"comet" | "croissant" | "bubble">, default: "comet" },
    /** Pale Blue Dot moment (journey chapter): fly to Voyager's 1990 sightline. */
    pbd: { type: Boolean, default: false },
    /** True while the journey clock is running: zoom follows and is locked. */
    following: { type: Boolean, default: false },
    /** Family Portrait step inside the Pale Blue Dot moment: "" | "all" | a planet name. */
    family: { type: String, default: "" },
    /** Chapter-5 moments: "" | "pulsars" (Golden Record map) | "flyby" (Gliese 445). */
    moment: { type: String, default: "" },
  },

  emits: ["ready", "failed", "flyby-year", "show-credits", "framed"],

  beforeCreate() { installEngine(); },

  data() {
    return {
      ready: false,
      failed: false,
      pins: [] as Pin[],
      ladder: LADDER.map((r) => ({ ...r, short: r.au >= 1000 ? `${(r.au / 1000).toLocaleString()}k au` : `${r.au} au` })),
      ladderNowPct: 0,
      galaxyCredit: false,
      vw: window.innerWidth,
      frame: 0,
      rt: markRaw({
        stage: null, gestures: null, eph: null, trails: {}, targets: [], projected: [],
        world: null, helio: null, offset: [0, 0, 0], shellMats: {}, tidal: null, gcArrow: null, neighbors: {}, oort: null, galaxy: null, galaxyLabels: {}, pbd: null, pbdAlpha: 0, family: null, familyAlpha: 0, famEye: false, pulsarMap: null, flyby: null, obstacles: [], obstaclesAt: 0, momentAlpha: 0, momentT0: 0, flybyYears: 0,
        lastYearEmit: 0, lastFadeMs: 0, lastTimeSync: 0,
        timer: 0, destroyed: false,
      } as Runtime),
    };
  },

  computed: {
    leaderPins(): Pin[] { return this.pins.filter((p) => p.leader && p.visible); },
  },

  watch: {
    chapter() { void this.frameChapter(false); },
    shape() { /* weights are eased in tick() */ },
    pbd(on: boolean) { void (on ? this.showPbd() : this.frameChapter(false)); },
    family(f: string) { void (f ? this.showFamily(f) : this.pbd ? this.showPbd() : null); },
    moment(m: string) {
      if (m === "pulsars") { void this.showPulsars(); } else if (m === "flyby") { void this.showFlyby(); } else {
        void this.frameChapter(false);
      }
    },
  },

  async mounted() {
    const rt = this.rt;
    rt.timer = window.setTimeout(() => {
      if (!this.ready) { this.failed = true; this.$emit("failed"); }
    }, OVERALL_TIMEOUT_MS);
    try {
      await (this as unknown as { waitForReady: () => Promise<void> }).waitForReady();
    } catch (err) {
      console.error("[VoyagerView3D] WWT never became ready:", err);
      this.failed = true; this.$emit("failed");
      return;
    }
    if (rt.destroyed) { return; }
    installHiDpiCanvas(2);
    rt.eph = markRaw(await loadEphemeris());
    initVoyagerStage(this as unknown as StageHost, this.shotFor(this.chapter));
    void this.useIauSky();
    try {
      rt.stage = markRaw(createThreeStage({ target: "wwt", onBeforeRender: this.tick }));
    } catch (err) {
      console.error("[VoyagerView3D] three.js stage failed:", err);
      this.failed = true; this.$emit("failed");
      return;
    }
    rt.world = markRaw(new Group());
    rt.stage.scene.add(rt.world);
    this.buildTrails();
    void this.loadHeliosphere();
    void this.loadGravity();
    void this.loadGalaxy();
    const root = this.$refs.root as HTMLElement | undefined;
    if (root) { rt.gestures = installSunGestures(root); }
    this.ready = true;
    window.clearTimeout(rt.timer);
    this.$emit("ready");
    if (new URLSearchParams(location.search).has("debug")) {
      (window as unknown as Record<string, unknown>).voyager = { view: this, rt };
    }
  },

  beforeUnmount() {
    const rt = this.rt;
    rt.destroyed = true;
    window.clearTimeout(rt.timer);
    rt.gestures?.dispose();
    rt.galaxy?.dispose();
    rt.stage?.dispose();
  },

  methods: {
    retry(): void { window.location.reload(); },

    /** CSS for a 1 px line from the dot to the parked label's right edge. */
    leaderLine(p: Pin): Record<string, string> {
      const dx = (p.lx ?? 0) + (p.leaderSide === "r" ? -4 : 4) - p.x, dy = (p.ly ?? 0) - p.y;
      return {
        width: `${Math.hypot(dx, dy)}px`,
        transform: `translate(${p.x}px, ${p.y}px) rotate(${Math.atan2(dy, dx)}rad)`,
        "--pin": p.color,
      };
    },

    /** Screen rects of every [data-obstacle] element (UI chrome), ~4 Hz. */
    refreshObstacles(): void {
      const out: Rect[] = [];
      document.querySelectorAll<HTMLElement>("[data-obstacle]").forEach((el) => {
        const r = el.getBoundingClientRect();
        if (r.width > 0 && r.height > 0 && el.offsetParent !== null) {
          out.push({ x0: r.left - 4, y0: r.top - 4, x1: r.right + 4, y1: r.bottom + 4 });
        }
      });
      this.rt.obstacles = out;
    },

    /** Distance ladder: frame the Sun out to this radius (AUDIT-UI #8). */
    flyRung(au: number): void {
      const s = currentShot();
      if (au >= 1e8) {
        // Galaxy: center between the Sun and the Galactic center (8.178 kpc =
        // 1.687e9 au toward ecliptic 266.84, -5.54), seen obliquely from the
        // galactic NORTH side (NGP at ecliptic 180.02, +29.81).
        const gc = eclXYZ(266.84, -5.54, 1.687e9 * 0.5);
        const { lat, lng } = viewFromEcliptic([-0.7128, 0.4469, 0.466]);
        void flyTo({ target: gc, distanceAu: fitDistance(au * 1.1), lat, lng, rotation: 0 }, 3600);
        return;
      }
      void flyTo({ target: [0, 0, 0], distanceAu: fitDistance(au * 1.25), lat: s.lat, lng: s.lng, rotation: 0 }, 2600);
    },

    /** Marker position: piecewise-log between the evenly spaced rungs. */
    updateLadder(): void {
      const viewR = currentDistanceAu() / fitDistance(1);
      const rs = this.ladder;
      let pct = 0;
      if (viewR <= rs[0].au) { pct = 0; } else if (viewR >= rs[rs.length - 1].au) { pct = 100; } else {
        for (let i = 0; i < rs.length - 1; i++) {
          if (viewR >= rs[i].au && viewR <= rs[i + 1].au) {
            const f = Math.log(viewR / rs[i].au) / Math.log(rs[i + 1].au / rs[i].au);
            pct = ((i + f) / (rs.length - 1)) * 100;
            break;
          }
        }
      }
      this.ladderNowPct = 100 - pct; // far is up
      this.galaxyCredit = !!this.rt.galaxy && viewR > 3e7;
    },

    // ── camera ───────────────────────────────────────────────────────
    craftPos(id: string, ms?: number): Vec3 {
      return positionAt(this.rt.eph!.bodies[id], ms ?? this.sceneMs);
    },

    shotFor(chapter: string): Shot {
      const v1 = this.craftPos("voyager1"), v2 = this.craftPos("voyager2");
      switch (chapter) {
      case "journey": {
        const r = Math.max(12, distanceAu(v1) * 1.15);
        const { lat, lng } = viewFromEcliptic([-0.35, -0.6, 0.72]);
        return { target: [0, 0, 0], distanceAu: fitDistance(r), lat, lng };
      }
      case "bubble": {
        // Side-on to the nose axis (gas arrives from ecliptic 255.7, +5.1) so
        // the tail reads; aimed a little downwind so nose and tail both fit.
        const { lat, lng } = viewFromEcliptic([-0.908, 0.243, 0.342]);
        return { target: [0.246 * 140, 0.965 * 140, -0.089 * 140], distanceAu: fitDistance(380), lat, lng };
      }
      case "oort": {
        const { lat, lng } = viewFromEcliptic([0.3, 0.8, 0.5]);
        return { target: [0, 0, 0], distanceAu: fitDistance(110000), lat, lng };
      }
      case "edge": {
        const { lat, lng } = viewFromEcliptic([0.8, 0.05, 0.6]); // side-on to the Galactic-center direction
        return { target: [0, 0, 0], distanceAu: fitDistance(420000), lat, lng };
      }
      default: {
        // Today: the Sun and both craft, seen from the side so V1 (35 deg
        // north) and V2 (38 deg south) fan apart.
        const mid: Vec3 = [(v1[0] + v2[0]) * 0.25, (v1[1] + v2[1]) * 0.25, (v1[2] + v2[2]) * 0.25];
        const { lat, lng } = viewFromEcliptic([-0.95, 0.1, 0.25]);
        return { target: mid, distanceAu: fitDistance(150), lat, lng };
      }
      }
    },

    /**
     * Pale Blue Dot: first stand just behind Voyager 1 (Feb 1990) looking home,
     * then glide down its sightline to Earth while the photo fades in. On the
     * sightline there is no parallax, so Earth stays on its pixel throughout.
     */
    async showPbd(): Promise<void> {
      const rt = this.rt;
      if (!rt.pbd) {
        try {
          rt.pbd = markRaw(await createPaleBlueDot("./data/"));
          rt.world?.add(rt.pbd.mesh);
        } catch (err) {
          console.error("[VoyagerView3D] Pale Blue Dot failed:", err);
          return;
        }
      }
      const d = rt.pbd.data;
      const e = d.earth_au, v = d.v1_au;
      const back: Vec3 = [v[0] - e[0], v[1] - e[1], v[2] - e[2]];
      const { lat, lng } = viewFromEcliptic(back);
      const rotation = rollForUp(lat, lng, d.up_ecl);
      const dist = Math.hypot(back[0], back[1], back[2]);
      await flyTo({ target: e, distanceAu: dist + 8, lat, lng, rotation }, 3200);
      if (!this.pbd) { return; }
      await flyTo({ target: e, distanceAu: fitDistance(rt.pbd.halfHeightAu * 1.7), lat, lng, rotation }, 4200);
    },

    /** The Golden Record pulsar map, in the real Galaxy. */
    async showPulsars(): Promise<void> {
      const rt = this.rt;
      if (!rt.pulsarMap) {
        try {
          rt.pulsarMap = markRaw(await createPulsarMap("./data/"));
          rt.world?.add(rt.pulsarMap.group);
          for (const p of rt.pulsarMap.data.pulsars) {
            this.pins.push({ id: `psr-${p.bname}`, kind: "pulsar", label: p.bname,
              sub: `${p.dist_kpc.toLocaleString()} kpc`, color: "#f2cf74", x: 0, y: 0, visible: false });
            rt.targets.push({ id: `psr-${p.bname}`, position: new Vector3() });
          }
        } catch (err) {
          console.error("[VoyagerView3D] pulsar map failed:", err);
          return;
        }
      }
      rt.momentT0 = performance.now();
      // Centered on the Sun: the map is drawn FROM here. Frame the farthest pulsar (~4 kpc = 8.3e8 au).
      const { lat, lng } = viewFromEcliptic([-0.7128, 0.4469, 0.466]);
      await flyTo({ target: [0, 0, 0], distanceAu: fitDistance(9.5e8), lat, lng, rotation: 0 }, 3600);
    },

    /** Voyager 1 meets Gliese 445: a straight-line fast-forward to closest approach. */
    async showFlyby(): Promise<void> {
      const rt = this.rt;
      if (!rt.flyby) {
        try {
          rt.flyby = markRaw(await createFlyby("./data/"));
          rt.world?.add(rt.flyby.group);
          for (const id of ["fb-craft", "fb-star", "fb-closest"]) {
            this.pins.push({ id, kind: "flyby", label: "", sub: "", color: id === "fb-star" ? "#ff8a7a" : "#e69f00",
              x: 0, y: 0, visible: false });
            rt.targets.push({ id, position: new Vector3() });
          }
        } catch (err) {
          console.error("[VoyagerView3D] flyby failed:", err);
          return;
        }
      }
      const fb = rt.flyby;
      const enc = fb.at(fb.encounter.t_years);
      const s0 = fb.star.r0_au;
      // Look down on the plane holding the star's path and Voyager's.
      const sv = fb.star.v_au_per_yr, cv = fb.craft.v_au_per_yr;
      const n: Vec3 = [sv[1] * cv[2] - sv[2] * cv[1], sv[2] * cv[0] - sv[0] * cv[2], sv[0] * cv[1] - sv[1] * cv[0]];
      const { lat, lng } = viewFromEcliptic(n);
      const target: Vec3 = [(s0[0] + enc.craft[0]) * 0.4, (s0[1] + enc.craft[1]) * 0.4, (s0[2] + enc.craft[2]) * 0.4];
      const dist = fitDistance(7.5e5);
      // Screen-up = ecliptic north, flattened onto the view plane. On a portrait
      // phone the card covers the bottom, so aim BELOW the scene: it rides up.
      const nn = Math.hypot(n[0], n[1], n[2]);
      const up: Vec3 = [-n[0] * n[2] / (nn * nn), -n[1] * n[2] / (nn * nn), 1 - n[2] * n[2] / (nn * nn)];
      const un = Math.hypot(up[0], up[1], up[2]);
      let rotation = 0;
      if (un > 0.05) {
        rotation = rollForUp(lat, lng, up);
        if (window.innerWidth < window.innerHeight) {
          const k = (0.3 * dist * Math.tan(Math.PI / 8)) / un;
          target[0] -= up[0] * k; target[1] -= up[1] * k; target[2] -= up[2] * k;
        }
      }
      rt.flybyYears = 0;
      rt.momentT0 = performance.now() + 3000; // the clock starts after the flight
      await flyTo({ target, distanceAu: dist, lat, lng, rotation }, 3000);
    },

    /**
     * The Family Portrait: the camera stands AT Voyager 1's 1990 position (target
     * D au ahead, camera distance D), the only viewpoint where every panel lines
     * up. "all" faces the 60-frame mosaic; a planet name glides down that
     * planet's sightline to its narrow-angle frame.
     */
    async showFamily(which: string): Promise<void> {
      const rt = this.rt;
      if (!rt.family) {
        try {
          rt.family = markRaw(await createFamilyPortrait("./data/"));
          rt.world?.add(rt.family.group);
          for (const f of rt.family.data.frames) {
            if (f.planet === "Earth") { continue; } // the Earth pin already exists
            this.pins.push({ id: `fam-${f.planet}`, kind: "planet", label: f.planet, sub: "", color: "#cfe3ff",
              x: 0, y: 0, visible: false });
            rt.targets.push({ id: `fam-${f.planet}`, position: new Vector3() });
          }
        } catch (err) {
          console.error("[VoyagerView3D] Family Portrait failed:", err);
          return;
        }
      }
      const d = rt.family.data;
      const v1 = d.v1_au;
      if (which === "all") {
        // Stand AT Voyager 1: the camera orbits a point only FAM_EYE au ahead, so a
        // drag turns the view (looks around the mosaic) without leaving the spot
        // where everything lines up; zoom is held there (tick).
        const mm = d.mosaic.mesh;
        let dir: Vec3, up: Vec3;
        if (mm) { dir = mm.center_dir_ecl; up = mm.up_ecl; } else {
          const cs = d.mosaic.corners_on_unit_plane;
          dir = [0, 1, 2].map((k) => (cs[0][k] + cs[1][k] + cs[2][k] + cs[3][k]) / 4) as Vec3;
          up = [0, 1, 2].map((k) => cs[0][k] - cs[3][k]) as Vec3; // left edge, bottom -> top
        }
        if (window.innerWidth < window.innerHeight) {
          // Portrait shows ~22 deg across: start on the Sun-Earth-Venus-Jupiter end.
          const pts = ["Venus", "Jupiter"].map((k) => d.frames.find((f) => f.planet === k)!.planet_au);
          const u = (q: Vec3): Vec3 => { const n = Math.hypot(q[0] - v1[0], q[1] - v1[1], q[2] - v1[2]);
            return [(q[0] - v1[0]) / n, (q[1] - v1[1]) / n, (q[2] - v1[2]) / n]; };
          const a = u(pts[0]), b = u(pts[1]);
          dir = [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
        }
        const n = Math.hypot(dir[0], dir[1], dir[2]);
        dir = [dir[0] / n, dir[1] / n, dir[2] / n];
        const { lat, lng } = viewFromEcliptic([-dir[0], -dir[1], -dir[2]]);
        rt.famEye = false;
        await flyTo({ target: [v1[0] + dir[0] * FAM_EYE, v1[1] + dir[1] * FAM_EYE, v1[2] + dir[2] * FAM_EYE],
          distanceAu: FAM_EYE, lat, lng, rotation: rollForUp(lat, lng, up) }, 3200);
        rt.famEye = this.family === "all";
        return;
      }
      rt.famEye = false;
      const f = d.frames.find((x) => x.planet === which);
      if (!f) { return; }
      const p = f.planet_au;
      const back: Vec3 = [v1[0] - p[0], v1[1] - p[1], v1[2] - p[2]];
      const { lat, lng } = viewFromEcliptic(back);
      await flyTo({ target: p, distanceAu: fitDistance(rt.family.frameHalfHeight[which] * 1.8), lat, lng,
        rotation: rollForUp(lat, lng, f.up_ecl) }, 3600);
    },

    async frameChapter(instant: boolean): Promise<void> {
      if (!this.ready) { return; }
      const ch = this.chapter;
      await flyTo(this.shotFor(ch), instant ? 0 : 3000);
      if (ch === this.chapter) { this.$emit("framed", ch); }
    },

    // ── layers ───────────────────────────────────────────────────────
    buildTrails(): void {
      const rt = this.rt, eph = rt.eph!;
      for (const id of CRAFT) {
        const b = eph.bodies[id];
        const geom = new BufferGeometry();
        geom.setAttribute("position", new Float32BufferAttribute(b.xyz, 3));
        const line = new Line(geom, new LineBasicMaterial({
          color: b.color, transparent: true, opacity: 0.95, depthTest: false,
        }));
        line.frustumCulled = false;
        line.renderOrder = 10;
        rt.world!.add(line);
        rt.trails[id] = markRaw({ line, geom, count: b.count });
      }
      // Pins: Sun, Earth, the craft, and the four boundary crossings.
      const pins: Pin[] = [
        { id: "sun", kind: "sun", label: "Sun", sub: "", color: "#ffd166", x: 0, y: 0, visible: false },
        { id: "earth", kind: "planet", label: "Earth", sub: "", color: "#4F8FE8", x: 0, y: 0, visible: false },
      ];
      for (const id of CRAFT) {
        const b = eph.bodies[id];
        pins.push({ id, kind: "craft", label: b.name, sub: "", color: b.color, x: 0, y: 0, visible: false });
      }
      for (const c of CROSSINGS) {
        pins.push({ id: `x-${c.craft}-${c.kind}`, kind: "crossing", label: c.label, sub: "",
          color: eph.bodies[c.craft].color, x: 0, y: 0, visible: false });
      }
      // The nearest stars (alpha Cen, Barnard's Star...) arrive with neighbors.json (loadGravity).
      pins.push({ id: "gc", kind: "star", label: "Toward the Milky Way's center", sub: "",
        color: "#9fdcff", x: 0, y: 0, visible: false });
      this.pins = pins;
      rt.targets = pins.map((p) => ({ id: p.id, position: new Vector3() }));
    },

    async loadHeliosphere(): Promise<void> {
      const rt = this.rt;
      try {
        const gltf = await new GLTFLoader().loadAsync("./data/models/heliosphere.glb");
        const morphs: Mesh[] = [];
        gltf.scene.traverse((o) => {
          const m = o as Mesh;
          if (!m.isMesh) { return; }
          const old = m.material as MeshBasicMaterial;
          // Additive + no depth write: order-independent nested shells.
          const shell = createShellMaterial({
            opacity: m.name === "bow_wave" ? 1.6 : 1.0,
            power: m.name === "termination_shock" ? 1.6 : 2.4,
            floor: m.name === "heliopause" ? 0.10 : 0.06,
          });
          rt.shellMats[m.name] = shell;
          m.material = shell;
          old.dispose();
          m.frustumCulled = false;
          m.renderOrder = 2;
          if (m.morphTargetInfluences) { morphs.push(m); }
        });
        rt.helio = markRaw({ root: gltf.scene, morphs });
        rt.world?.add(gltf.scene);
      } catch (err) {
        console.error("[VoyagerView3D] heliosphere.glb failed:", err);
      }
    },

    /**
     * Sky backdrop: the IAU/NOIRLab all-sky panorama by Eckhard Slawik instead
     * of DSS2. In solar-system mode WWT draws its backdrop from a PRIVATE field,
     * `_milkyWayBackground`, which it fills once with
     * getImagesetByName("Digitized Sky Survey (Color)") (engine 7.39, the
     * renderType 4 branch of WWTControl.render). Loading our WTML and setting
     * that field swaps it. `?sky=dss` keeps the engine default; `?sky=dsm` uses
     * NASA's Deep Star Maps 2020 for an A/B comparison.
     */
    async useIauSky(): Promise<void> {
      const sky = new URLSearchParams(location.search).get("sky");
      if (sky === "dss") { return; }
      try {
        let name = "Eckhard All Sky";
        if (sky === "dsm") {
          // NASA SVS Deep Star Maps 2020, from WWT's own catalog (as in the Orion app).
          name = "Deep Star Maps 2020";
        } else {
          const host = this as unknown as {
            loadImageCollection: (p: { url: string; loadChildFolders?: boolean }) => Promise<unknown>;
          };
          await host.loadImageCollection({ url: new URL("iau-allsky.wtml", location.href).toString() });
        }
        const iset = WWTControl.singleton.getImagesetByName(name);
        if (iset) {
          (WWTControl.singleton as unknown as { _milkyWayBackground: unknown })._milkyWayBackground = iset;
          // WWT draws this backdrop at (1 - fade)/2, i.e. 50% at best. The
          // natural-color panorama is far darker than DSS's boosted colors, so
          // double it (only for our imageset); the distance fade still applies.
          const proto = RenderContext.prototype as unknown as {
            drawImageSet: (this: unknown, is: unknown, opacity: number) => void;
          };
          const orig = proto.drawImageSet;
          proto.drawImageSet = function (is: unknown, opacity: number) {
            return orig.call(this, is, is === iset ? Math.min(100, opacity * 2) : opacity);
          };
        } else {
          console.warn("[VoyagerView3D] IAU all-sky imageset not found; keeping DSS.");
        }
      } catch (err) {
        console.error("[VoyagerView3D] IAU all-sky failed; keeping DSS:", err);
      }
    },

    /** 3D Milky Way (src/three/galaxy owns everything past this call). */
    async loadGalaxy(): Promise<void> {
      const rt = this.rt;
      try {
        const { createGalaxy } = await import("../three/galaxy");
        const mem = (navigator as unknown as { deviceMemory?: number }).deviceMemory;
        const g = await createGalaxy({
          world: rt.world!, camera: rt.stage!.camera, renderer: rt.stage!.renderer,
          dpr: Math.min(window.devicePixelRatio || 1, 2),
          lite: new URLSearchParams(location.search).get("galaxy") === "lite" || (mem !== undefined && mem <= 4),
        });
        rt.galaxy = g ? markRaw(g) : null;
        if (g) {
          // Galaxy anchor labels become ordinary pins (index-aligned with targets).
          for (const l of g.labels()) {
            rt.galaxyLabels[`gx-${l.id}`] = l;
            this.pins.push({ id: `gx-${l.id}`, kind: "galaxy", label: l.label, sub: l.sub ?? "",
              color: l.kind === "sun" ? "#ffd166" : "#cfe3ff", x: 0, y: 0, visible: false });
            rt.targets.push({ id: `gx-${l.id}`, position: new Vector3() });
          }
        }
      } catch (err) {
        console.error("[VoyagerView3D] galaxy layer failed:", err);
      }
    },

    async loadGravity(): Promise<void> {
      const rt = this.rt;
      try {
        const gltf = await new GLTFLoader().loadAsync("./data/models/tidal.glb");
        gltf.scene.traverse((o) => {
          const m = o as Mesh;
          if (!m.isMesh) { return; }
          (m.material as MeshBasicMaterial).dispose();
          m.material = createShellMaterial({ opacity: 1.0, power: 1.8, floor: 0.05 });
          m.frustumCulled = false;
          m.renderOrder = 1;
        });
        // Arrow from the Sun toward the Galactic center (l = 0, b = 0; ecliptic
        // 266.84, -5.54), reaching past the tidal edge; the label sits at its tip.
        const g = eclXYZ(266.84, -5.54, 1);
        rt.gcArrow = markRaw(new ArrowHelper(new Vector3(g[0], g[1], g[2]), new Vector3(0, 0, 0), GC_ARROW_AU,
          0x9fdcff, GC_ARROW_AU * 0.12, GC_ARROW_AU * 0.06));
        rt.gcArrow.traverse((o) => {
          const m = (o as Mesh).material as MeshBasicMaterial | undefined;
          if (m) { m.depthTest = false; m.transparent = true; m.opacity = 0.9; m.side = DoubleSide; }
          o.frustumCulled = false;
          o.renderOrder = 25;
        });
        rt.gcArrow.visible = false;
        rt.world?.add(rt.gcArrow);
        rt.tidal = markRaw(gltf.scene);
        rt.tidal.visible = false;
        rt.world?.add(rt.tidal);
      } catch (err) {
        console.error("[VoyagerView3D] tidal.glb failed:", err);
      }
      try {
        // The stars that sit as close to the Sun as its own tidal edge (pipeline/neighbors.py).
        /* eslint-disable @typescript-eslint/naming-convention -- pipeline JSON keys */
        const nb = (await (await fetch("./data/neighbors.json")).json()) as {
          stars: { id: string; label: string; dist_ly: number; xyz_au: Vec3 }[] };
        /* eslint-enable @typescript-eslint/naming-convention */
        for (const st of nb.stars) {
          const id = `nb-${st.id}`;
          rt.neighbors[id] = st.xyz_au;
          this.pins.push({ id, kind: "star", label: st.label, sub: `${st.dist_ly} light-years`,
            color: "#ffe0a3", x: 0, y: 0, visible: false });
          rt.targets.push({ id, position: new Vector3() });
        }
      } catch (err) {
        console.error("[VoyagerView3D] neighbors.json failed:", err);
      }
      try {
        const buf = await (await fetch("./data/oort.bin")).arrayBuffer();
        rt.oort = markRaw(createOortPoints(new Float32Array(buf), Math.min(window.devicePixelRatio || 1, 2)));
        rt.oort.visible = false;
        rt.world?.add(rt.oort);
      } catch (err) {
        console.error("[VoyagerView3D] oort.bin failed:", err);
      }
    },

    /** Per frame, from the stage's onBeforeRender. */
    tick(): void {
      const rt = this.rt, eph = rt.eph, stage = rt.stage;
      if (!eph || !stage) { return; }
      const ms = this.sceneMs;
      if ((this.frame++ & 7) === 0) { this.updateLadder(); this.vw = window.innerWidth; }
      // WWT draws relative to its viewTarget; follow it (see liveTargetEcl).
      const off = liveTargetEcl(rt.offset);
      rt.world?.position.set(-off[0], -off[1], -off[2]);
      if (rt.helio) {
        const want = [this.shape === "croissant" ? 1 : 0, this.shape === "bubble" ? 1 : 0];
        const breathe = 0.5 + 0.5 * Math.sin((performance.now() / 1000) * (2 * Math.PI / 22));
        for (const m of rt.helio.morphs) {
          const w = m.morphTargetInfluences!;
          w[0] += (want[0] - w[0]) * 0.06;
          w[1] += (want[1] - w[1]) * 0.06;
          w[2] = breathe;
        }
        rt.helio.root.visible = this.chapter !== "journey" || distanceAu(this.craftPos("voyager1")) > 60;
      }
      for (const id of CRAFT) {
        const t = rt.trails[id];
        t.geom.setDrawRange(0, sampleIndexAt(eph.bodies[id], ms) + 1);
      }
      // Keep WWT's own planets (and orbits) on the scene date: ~10 Hz is plenty.
      // Every frame while the journey clock runs (smooth planets); ~10 Hz otherwise.
      if (performance.now() - rt.lastTimeSync > (this.following ? 0 : 100)) {
        rt.lastTimeSync = performance.now();
        (this as unknown as { setTime: (d: Date) => void }).setTime(new Date(ms));
      }
      if (rt.pbd) {
        // Time-based fade (frame rate varies a lot on phones): ~2.5 s in, ~0.6 s out.
        const now = performance.now();
        const dt = Math.min(0.1, (now - (rt.lastFadeMs || now)) / 1000);
        rt.lastFadeMs = now;
        const pbdOn = this.pbd && !this.family;
        rt.pbdAlpha = pbdOn ? Math.min(1, rt.pbdAlpha + dt / 2.5) : Math.max(0, rt.pbdAlpha - dt / 0.6);
        rt.pbd.setOpacity(rt.pbdAlpha);
      }
      if (rt.family) {
        const famOn = this.pbd && !!this.family;
        rt.familyAlpha = famOn ? Math.min(1, rt.familyAlpha + 0.04) : Math.max(0, rt.familyAlpha - 0.1);
        rt.family.setOpacity(0.9 * rt.familyAlpha, rt.familyAlpha);
      }
      // Chapter-5 moments: fade their layers; run the flyby clock.
      const mWant = this.moment ? 1 : 0;
      rt.momentAlpha = mWant ? Math.min(1, rt.momentAlpha + 0.03) : Math.max(0, rt.momentAlpha - 0.08);
      rt.pulsarMap?.setOpacity(this.moment === "pulsars" ? rt.momentAlpha : 0);
      rt.flyby?.setOpacity(this.moment === "flyby" ? rt.momentAlpha : 0);
      if (this.moment === "flyby" && rt.flyby) {
        const f = Math.max(0, Math.min(1, (performance.now() - rt.momentT0) / 20000));
        // Ease out toward the encounter, then hold there.
        rt.flybyYears = rt.flyby.encounter.t_years * (1 - Math.pow(1 - f, 2.2));
        if (performance.now() - rt.lastYearEmit > 200) {
          rt.lastYearEmit = performance.now();
          this.$emit("flyby-year", Math.round(rt.flybyYears));
        }
      }
      if (rt.famEye) {
        if (this.pbd && this.family === "all") { aimZoom(FAM_EYE); } else { rt.famEye = false; }
      }
      if (this.chapter === "journey" && !this.pbd && this.following) {
        // Zoom follows Voyager outward (zoom locked); the guest keeps the angle.
        aimZoom(fitDistance(Math.max(12, distanceAu(this.craftPos("voyager1")) * 1.15)));
      }
      // Layers follow the CAMERA, not the chapter, so the ladder and free
      // pinch-zoom reveal them too. viewR = radius (au) framed on screen.
      const viewR = currentDistanceAu() / fitDistance(1);
      const far = viewR > 2500;
      if (rt.oort) { rt.oort.visible = viewR > 1200; }
      if (rt.tidal) { rt.tidal.visible = viewR > 25000; }
      if (rt.gcArrow) { rt.gcArrow.visible = viewR > 25000 && viewR < 1e6 && this.moment !== "flyby"; }
      rt.galaxy?.update({ viewRAu: viewR, ms });
      // Pins
      const showCrossings = this.chapter === "bubble";
      for (let i = 0; i < this.pins.length; i++) {
        const p = this.pins[i], tgt = rt.targets[i];
        let pos: Vec3 = [0, 0, 0];
        if (p.kind === "craft" || p.id === "earth") { pos = positionAt(eph.bodies[p.id], ms); }
        if (p.kind === "crossing") {
          const c = CROSSINGS.find((cc) => `x-${cc.craft}-${cc.kind}` === p.id)!;
          pos = positionAt(eph.bodies[c.craft], Date.parse(c.date + "T00:00:00Z"));
        }
        if (p.id.startsWith("nb-")) { pos = rt.neighbors[p.id] ?? pos; }
        if (p.id === "gc") { pos = eclXYZ(266.84, -5.54, GC_ARROW_AU); }
        if (p.kind === "galaxy") { pos = rt.galaxyLabels[p.id].position; }
        if (p.id.startsWith("fam-") && rt.family) {
          pos = rt.family.data.frames.find((f) => `fam-${f.planet}` === p.id)!.planet_au;
        }
        if (p.kind === "pulsar" && rt.pulsarMap) {
          pos = rt.pulsarMap.data.pulsars.find((q) => `psr-${q.bname}` === p.id)!.xyz_au;
        }
        if (p.kind === "flyby" && rt.flyby) {
          const at = rt.flyby.at(p.id === "fb-closest" ? rt.flyby.encounter.t_years : rt.flybyYears);
          pos = p.id === "fb-star" ? at.star : at.craft;
        }
        tgt.position.set(pos[0] - off[0], pos[1] - off[1], pos[2] - off[2]);
      }
      const w = window.innerWidth, h = window.innerHeight;
      projectTargets(stage.camera, w, h, rt.targets, 0, rt.projected);
      for (let i = 0; i < this.pins.length; i++) {
        const p = this.pins[i], q = rt.projected[i];
        let vis = !!q?.visible;
        if (p.kind === "crossing") { vis = vis && showCrossings; }
        if (p.id === "earth") {
          vis = vis && this.chapter === "journey" && (this.pbd || distanceAu(this.craftPos("voyager1")) < 25);
          p.label = "Earth";
          p.sub = this.pbd ? "Feb. 14, 1990" : "";
          p.ring = this.pbd && (!this.family || this.family === "Earth" || this.family === "all");
        }
        if (p.kind === "star") { vis = vis && viewR > 60000 && this.moment !== "flyby"; }
        if (far && (p.id === "sun" || p.id === "voyager2")) { vis = false; }
        if (p.id.startsWith("fam-")) {
          vis = vis && this.pbd && !!this.family;
          p.ring = this.family === p.label || this.family === "all";
        } else if (p.kind === "pulsar") {
          vis = vis && this.moment === "pulsars";
        } else if (p.kind === "flyby") {
          vis = vis && this.moment === "flyby" && !!rt.flyby;
          if (rt.flyby) {
            const yrs = Math.round(rt.flybyYears).toLocaleString();
            if (p.id === "fb-craft") { p.label = "Voyager 1"; p.sub = `+${yrs} years`; }
            if (p.id === "fb-star") { p.label = "Gliese 445"; p.sub = "red dwarf, 114 km/s"; }
            if (p.id === "fb-closest") {
              vis = vis && rt.flybyYears >= rt.flyby.encounter.t_years - 50;
              p.label = `Closest: ${rt.flyby.encounter.min_dist_ly.toFixed(1)} light-years`;
              p.sub = `about the year ${Math.round(2026 + rt.flyby.encounter.t_years).toLocaleString()}`;
            }
          }
        } else if (p.kind === "galaxy") {
          const l = rt.galaxyLabels[p.id];
          vis = vis && viewR >= l.minViewRAu && viewR <= l.maxViewRAu;
        } else if (viewR > 1e6 || (this.moment === "flyby" && p.id === "voyager1")) {
          vis = false; // galactic scale: the galaxy's own labels take over
        }
        p.x = q ? q.xCss : 0; p.y = q ? q.yCss : 0; p.visible = vis;
        if (p.kind === "craft" && far) {
          p.label = p.id === "voyager1" ? "The Sun, Earth and Voyager 1 are all here" : p.label;
          p.sub = p.id === "voyager1" ? "49 years of travel: 172 au" : "";
        } else if (p.kind === "craft") {
          p.label = eph.bodies[p.id].name;
          p.sub = this.chapter === "today" || this.chapter === "journey"
            ? formatLightTime(lightHoursFromEarth(eph, p.id, ms)) + " of light"
            : `${distanceAu(positionAt(eph.bodies[p.id], ms)).toFixed(0)} au`;
        }
      }
      if (performance.now() - rt.obstaclesAt > 250) { rt.obstaclesAt = performance.now(); this.refreshObstacles(); }
      // Earth races around the Sun during the journey, and the planets crossing
      // in front kept bumping the Sun's label: park both labels (Earth up-left,
      // Sun up-right of the Sun) and join each to its dot with a leader line.
      const sunIdx = this.pins.findIndex((q) => q.id === "sun");
      const sunQ = sunIdx >= 0 ? rt.projected[sunIdx] : undefined;
      for (const p of this.pins) {
        if (p.id !== "earth" && p.id !== "sun") { continue; }
        p.leader = this.chapter === "journey" && !this.pbd && !!sunQ?.visible && p.visible;
        p.leaderSide = p.id === "sun" ? "r" : "l";
        if (p.leader && sunQ) {
          const sx = p.id === "sun" ? 70 : -70;
          p.lx = Math.min(w - 80, Math.max(80, sunQ.xCss + sx));
          p.ly = Math.min(h - 20, Math.max(110, sunQ.yCss - 70));
          // Step the parked label out of any UI chrome (ladder, card): AUDIT phone runs.
          for (let pass = 0; pass < 3; pass++) {
            const r = p.leaderSide === "r" ? { x0: p.lx - 2, x1: p.lx + 60 } : { x0: p.lx - 60, x1: p.lx + 2 };
            const o = rt.obstacles.find((q) => r.x0 < q.x1 && r.x1 > q.x0 && p.ly! - 11 < q.y1 && p.ly! + 11 > q.y0);
            if (!o) { break; }
            const toRight = o.x0 + o.x1 < w; // chrome on the left half: go right of it
            if (p.leaderSide === "r") { p.lx = toRight ? o.x1 + 4 : o.x0 - 64; } else { p.lx = toRight ? o.x1 + 64 : o.x0 - 4; }
          }
        }
      }
      declutter(this.pins, w, h, rt.obstacles);
    },
  },
});

// Keep EngineSetting referenced for future layer toggles.
export type { EngineSetting };
</script>

<style lang="less">
.v3d {
  position: absolute;
  inset: 0;
  z-index: 0; // own stacking context (sol footgun 27)
  .wwtelescope-component { position: absolute; inset: 0; touch-action: none; }
}
.v3d-pins {
  position: absolute; inset: 0; pointer-events: none; overflow: hidden;
}
.pin {
  position: absolute; left: 0; top: 0; display: flex; align-items: center; gap: 6px;
  will-change: transform;
  .pin-dot {
    width: 12px; height: 12px; margin: -6px 0 0 -6px; border-radius: 50%;
    background: var(--pin); box-shadow: 0 0 0 2px rgba(0, 0, 0, 0.75), 0 0 12px var(--pin);
  }
  .pin-label {
    margin-top: -6px; width: max-content; max-width: 170px; font-size: 14px; line-height: 1.2; color: #fff;
    text-shadow: 0 1px 3px #000, 0 0 6px #000;
    small { display: block; font-size: 13px; color: var(--pin); font-variant-numeric: tabular-nums; }
  }
}
.pin { display: block; width: 0; height: 0; }
.leader-line {
  position: absolute; left: 0; top: 0; height: 1px; transform-origin: 0 50%;
  background: var(--pin); opacity: 0.75; box-shadow: 0 0 2px #000;
}
.leader-label {
  position: absolute; left: 0; top: 0; margin: -11px 0 0 -60px; width: 60px; text-align: right;
  font-size: 14px; line-height: 22px; color: #fff; text-shadow: 0 1px 3px #000, 0 0 6px #000;
  &.right { margin-left: 0; text-align: left; }
}
.pin .pin-dot { position: absolute; left: 0; top: 0; }
.pin .pin-label { position: absolute; left: 11px; top: -10px; margin-top: 0; }
.pin.flip .pin-label { left: auto; right: 11px; text-align: right; }
.pin.ring .pin-dot {
  width: 30px; height: 30px; margin: -15px 0 0 -15px; background: transparent;
  border: 2px solid var(--pin); box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.6);
}
.pin.ring .pin-label { left: 22px; }
.pin.ring.flip .pin-label { left: auto; right: 22px; }
.pin-craft .pin-dot { width: 14px; height: 14px; margin: -7px 0 0 -7px; }
.pin-voyager2 .pin-dot { border-radius: 2px; transform: rotate(45deg); }
.pin-sun .pin-dot { background: #ffd166; }
.pin-crossing .pin-dot { width: 9px; height: 9px; margin: -4.5px 0 0 -4.5px; background: transparent;
  border: 2px solid var(--pin); box-shadow: 0 0 0 1px #000; }
.pin-crossing .pin-label { font-size: 12px; opacity: 0.9; }
.pin-pulsar .pin-dot { width: 7px; height: 7px; margin: -3.5px 0 0 -3.5px; }
.pin-pulsar .pin-label { font-size: 12px; small { font-size: 12px; } }
.pin-fb-closest .pin-dot { background: transparent; border: 2px solid #ffd166; }
.pin-star .pin-dot { width: 8px; height: 8px; margin: -4px 0 0 -4px; }
// Distance ladder (left edge; the story card owns the bottom / right).
.ladder {
  position: absolute; z-index: 5; left: 12px; width: 150px;
  top: calc(env(safe-area-inset-top, 0px) + 112px); bottom: calc(44vh + 40px);
  pointer-events: none;
  .ladder-rail { position: absolute; left: 11px; top: 0; bottom: 0; width: 2px; background: rgba(200, 210, 255, 0.25); }
  .ladder-now {
    position: absolute; left: 4px; width: 16px; height: 16px; margin-top: -8px; border-radius: 50%;
    border: 2px solid #ffd166; box-shadow: 0 0 10px rgba(255, 209, 102, 0.8); transition: top 120ms linear;
  }
  .rung {
    position: absolute; left: 0; margin-top: -22px; height: 44px; display: flex; align-items: center; gap: 8px;
    pointer-events: auto; color: #dfe3ff; cursor: pointer; text-align: left;
    &:focus-visible { outline: 3px solid #ffd166; outline-offset: 2px; border-radius: 8px; }
  }
  .rung-dot { width: 8px; height: 8px; margin-left: 8px; border-radius: 50%; background: #dfe3ff; flex: none; }
  .rung-t { font-size: 13px; line-height: 1.1; text-shadow: 0 1px 3px #000, 0 0 6px #000;
    small { display: block; font-size: 12px; color: #b9bfe6; font-variant-numeric: tabular-nums; } }
  .rung.hot { color: #e69f00; .rung-dot { background: #e69f00; } }
}
@media (max-width: 599px) {
  .ladder { width: 96px; .rung-t { font-size: 12px; small { display: none; } } }
}
@media (min-width: 900px) { .ladder { bottom: 40px; top: 120px; } }
@media (max-height: 520px) and (orientation: landscape) {
  .ladder { top: 100px; bottom: 18px; width: 110px;
    .rung { height: 24px; margin-top: -12px; }
    .rung-t { font-size: 12px; small { display: none; } } }
  .v3d-credit { top: 78px; right: 372px; }
}
// Top right, under the header's info button: clear of the ladder (left), the
// story card / pill (bottom) and the top-left title.
.v3d-credit {
  position: absolute; z-index: 6; right: 12px; top: calc(env(safe-area-inset-top, 0px) + 100px);
  max-width: 190px; padding: 4px 8px; border-radius: 8px; text-align: right;
  font-size: 12px; line-height: 1.3; color: #cfd6ff; background: rgba(5, 3, 15, 0.55); cursor: pointer;
  &:focus-visible { outline: 3px solid #ffd166; }
}
.v3d-cover {
  position: absolute; inset: 0; display: grid; place-items: center; align-content: center; gap: 12px;
  background: #05030f; color: #cfd6ff; font-size: 16px; text-align: center; padding: 24px;
}
// Phones: the story card owns the bottom 44vh; center the loader in the space above it.
@media (max-width: 899px) and (orientation: portrait) {
  .v3d-cover { padding: 110px 16px calc(44vh + 16px); }
}
</style>
