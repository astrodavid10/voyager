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
        <span v-show="!p.labelHidden" class="pin-label">{{ p.label }}<small v-if="p.sub">{{ p.sub }}</small></span>
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
  BufferGeometry, Float32BufferAttribute, Group, Line, LineBasicMaterial, Mesh, MeshBasicMaterial,
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
import { Flyby, PulsarMap, createFlyby, createPulsarMap } from "../three/farLayers";
import { createShellMaterial } from "../three/shellMaterial";
import { ThreeStage, createThreeStage } from "../three/stage";
import { installSunGestures, type SunGestures } from "../wwt/gestures";
import { installHiDpiCanvas } from "../wwt/wwt-hacks";
import {
  Shot, StageHost, aimTo, currentDistanceAu, currentShot, fitDistance, flyTo, initVoyagerStage, liveTargetEcl,
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
  /** Dot only: the label would have covered a higher-priority label. */
  labelHidden?: boolean;
  /** Draw as an open ring (Pale Blue Dot Earth: the real dot shows through). */
  ring?: boolean;
}

/** Lower = placed first, so it wins a collision. */
const PIN_PRIORITY: Record<string, number> = {
  craft: 1, flyby: 2, sun: 3, planet: 4, galaxy: 5, crossing: 6, star: 6, pulsar: 8,
};

interface Rect { x0: number; y0: number; x1: number; y1: number }
const placed: Rect[] = [];
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
  for (const p of order) {
    const small = p.kind === "pulsar" || p.kind === "crossing";
    const cw = small ? 6.6 : 7.6;
    const w = Math.min(170, Math.max(p.label.length, p.sub.length * 0.92) * cw) + 6;
    const h = p.sub ? 34 : 19;
    const gap = p.ring ? 22 : 11;
    const right: Rect = { x0: p.x + gap, y0: p.y - 10, x1: p.x + gap + w, y1: p.y - 10 + h };
    const left: Rect = { x0: p.x - gap - w, y0: right.y0, x1: p.x - gap, y1: right.y1 };
    const fits = (r: Rect) => r.x0 >= 2 && r.x1 <= vw - 2 && r.y0 >= 0 && r.y1 <= vh
      && !placed.some((q) => r.x0 < q.x1 && r.x1 > q.x0 && r.y0 < q.y1 && r.y1 > q.y0);
    if (fits(right)) { p.side = "r"; p.labelHidden = false; placed.push(right); } else if (fits(left)) {
      p.side = "l"; p.labelHidden = false; placed.push(left);
    } else {
      p.labelHidden = true;
    }
    // The dot itself is an obstacle for lower-priority labels.
    const d = p.ring ? 17 : 8;
    placed.push({ x0: p.x - d, y0: p.y - d, x1: p.x + d, y1: p.y + d });
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
  oort: Points | null;
  galaxy: GalaxyLayer | null;
  galaxyLabels: Record<string, GalaxyLabel>;
  pbd: PaleBlueDot | null;
  pbdAlpha: number;
  pulsarMap: PulsarMap | null;
  flyby: Flyby | null;
  obstacles: Rect[];
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
        world: null, helio: null, offset: [0, 0, 0], shellMats: {}, tidal: null, oort: null, galaxy: null, galaxyLabels: {}, pbd: null, pbdAlpha: 0, pulsarMap: null, flyby: null, obstacles: [], momentAlpha: 0, momentT0: 0, flybyYears: 0,
        lastYearEmit: 0, lastFadeMs: 0, lastTimeSync: 0,
        timer: 0, destroyed: false,
      } as Runtime),
    };
  },

  watch: {
    chapter() { void this.frameChapter(false); },
    shape() { /* weights are eased in tick() */ },
    pbd(on: boolean) { void (on ? this.showPbd() : this.frameChapter(false)); },
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
        const { lat, lng } = viewFromEcliptic([0.3, 0.8, 0.5]);
        return { target: [0, 0, 0], distanceAu: fitDistance(330000), lat, lng };
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
      const gc = eclXYZ(266.84, -5.54, 1.687e9 * 0.42);
      const { lat, lng } = viewFromEcliptic([-0.7128, 0.4469, 0.466]);
      await flyTo({ target: gc, distanceAu: fitDistance(1.25e9), lat, lng, rotation: 0 }, 3600);
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
      rt.flybyYears = 0;
      rt.momentT0 = performance.now() + 3000; // the clock starts after the flight
      await flyTo({ target, distanceAu: fitDistance(7.5e5), lat, lng, rotation: 0 }, 3000);
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
      // alpha Cen (SIMBAD/Gaia via the research notes): 1.347 pc at ecliptic (239.5, -42.6).
      pins.push({ id: "acen", kind: "star", label: "Alpha Centauri, the nearest stars", sub: "4.4 light-years",
        color: "#ffe0a3", x: 0, y: 0, visible: false });
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
        rt.tidal = markRaw(gltf.scene);
        rt.tidal.visible = false;
        rt.world?.add(rt.tidal);
      } catch (err) {
        console.error("[VoyagerView3D] tidal.glb failed:", err);
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
      if (performance.now() - rt.lastTimeSync > 100) {
        rt.lastTimeSync = performance.now();
        (this as unknown as { setTime: (d: Date) => void }).setTime(new Date(ms));
      }
      if (rt.pbd) {
        // Time-based fade (frame rate varies a lot on phones): ~2.5 s in, ~0.6 s out.
        const now = performance.now();
        const dt = Math.min(0.1, (now - (rt.lastFadeMs || now)) / 1000);
        rt.lastFadeMs = now;
        rt.pbdAlpha = this.pbd ? Math.min(1, rt.pbdAlpha + dt / 2.5) : Math.max(0, rt.pbdAlpha - dt / 0.6);
        rt.pbd.setOpacity(rt.pbdAlpha);
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
      if (this.chapter === "journey" && !this.pbd) {
        const r = Math.max(12, distanceAu(this.craftPos("voyager1")) * 1.15);
        const s = this.shotFor("journey");
        s.distanceAu = fitDistance(r);
        aimTo(s);
      }
      // Layers follow the CAMERA, not the chapter, so the ladder and free
      // pinch-zoom reveal them too. viewR = radius (au) framed on screen.
      const viewR = currentDistanceAu() / fitDistance(1);
      const far = viewR > 2500;
      if (rt.oort) { rt.oort.visible = viewR > 1200; }
      if (rt.tidal) { rt.tidal.visible = viewR > 25000; }
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
        if (p.id === "acen") { pos = eclXYZ(239.5, -42.6, 277900); }
        if (p.id === "gc") { pos = eclXYZ(266.84, -5.54, 283157); }
        if (p.kind === "galaxy") { pos = rt.galaxyLabels[p.id].position; }
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
          p.ring = this.pbd;
        }
        if (p.kind === "star") { vis = vis && viewR > 60000; }
        if (far && (p.id === "sun" || p.id === "voyager2")) { vis = false; }
        if (p.kind === "pulsar") {
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
      if ((this.frame & 15) === 1) { this.refreshObstacles(); }
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
// Top right, under the header's info button: clear of the ladder (left), the
// story card / pill (bottom) and the top-left title.
.v3d-credit {
  position: absolute; z-index: 6; right: 12px; top: calc(env(safe-area-inset-top, 0px) + 64px);
  max-width: 190px; padding: 4px 8px; border-radius: 8px; text-align: right;
  font-size: 12px; line-height: 1.3; color: #cfd6ff; background: rgba(5, 3, 15, 0.55); cursor: pointer;
  &:focus-visible { outline: 3px solid #ffd166; }
}
.v3d-cover {
  position: absolute; inset: 0; display: grid; place-items: center; align-content: center; gap: 12px;
  background: #05030f; color: #cfd6ff; font-size: 16px; text-align: center; padding: 24px;
}
</style>
