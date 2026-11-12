<template>
  <div ref="root" class="v3d" :class="{ ready }">
    <WorldWideTelescope wwt-namespace="wwt-voyager" />
    <div class="v3d-pins" aria-hidden="true">
      <div
        v-for="p in pins"
        v-show="p.visible"
        :key="p.id"
        class="pin"
        :class="['pin-' + p.kind, 'pin-' + p.id, { flip: p.x > vw * 0.58 }]"
        :style="{ transform: `translate(${p.x}px, ${p.y}px)`, '--pin': p.color }"
      >
        <span class="pin-dot" />
        <span class="pin-label">{{ p.label }}<small v-if="p.sub">{{ p.sub }}</small></span>
      </div>
    </div>
    <nav v-if="ready" class="ladder" aria-label="Distance from the Sun">
      <div class="ladder-rail" />
      <div class="ladder-now" :style="{ top: ladderNowPct + '%' }" aria-hidden="true" />
      <button
        v-for="(r, i) in ladder" :key="r.id" type="button" class="rung"
        :class="{ hot: r.id === 'voyager1' }"
        :style="{ top: (1 - i / (ladder.length - 1)) * 100 + '%' }"
        :aria-label="`Fly out to ${r.label}, ${r.au.toLocaleString()} au`"
        @click="flyRung(r.au)"
      >
        <span class="rung-dot" />
        <span class="rung-t">{{ r.label }}<small>{{ r.short }}</small></span>
      </button>
    </nav>
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
import type { GalaxyLayer } from "../three/galaxy";
import { createOortPoints } from "../three/oortPoints";
import { createShellMaterial } from "../three/shellMaterial";
import { ThreeStage, createThreeStage } from "../three/stage";
import { installSunGestures, type SunGestures } from "../wwt/gestures";
import { installHiDpiCanvas } from "../wwt/wwt-hacks";
import {
  Shot, StageHost, aimTo, currentDistanceAu, currentShot, fitDistance, flyTo, initVoyagerStage, liveTargetEcl,
  viewFromEcliptic,
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
  },

  emits: ["ready", "failed"],

  beforeCreate() { installEngine(); },

  data() {
    return {
      ready: false,
      failed: false,
      pins: [] as Pin[],
      ladder: LADDER.map((r) => ({ ...r, short: r.au >= 1000 ? `${(r.au / 1000).toLocaleString()}k au` : `${r.au} au` })),
      ladderNowPct: 0,
      vw: window.innerWidth,
      frame: 0,
      rt: markRaw({
        stage: null, gestures: null, eph: null, trails: {}, targets: [], projected: [],
        world: null, helio: null, offset: [0, 0, 0], shellMats: {}, tidal: null, oort: null, galaxy: null,
        timer: 0, destroyed: false,
      } as Runtime),
    };
  },

  watch: {
    chapter() { void this.frameChapter(false); },
    shape() { /* weights are eased in tick() */ },
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

    /** Distance ladder: frame the Sun out to this radius (AUDIT-UI #8). */
    flyRung(au: number): void {
      const s = currentShot();
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

    async frameChapter(instant: boolean): Promise<void> {
      if (!this.ready) { return; }
      await flyTo(this.shotFor(this.chapter), instant ? 0 : 3000);
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
      pins.push({ id: "gc", kind: "star", label: "Toward the Milky Way's centre", sub: "",
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
          // natural-colour panorama is far darker than DSS's boosted colours, so
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
      if (this.chapter === "journey") {
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
        tgt.position.set(pos[0] - off[0], pos[1] - off[1], pos[2] - off[2]);
      }
      const w = window.innerWidth, h = window.innerHeight;
      projectTargets(stage.camera, w, h, rt.targets, 0, rt.projected);
      for (let i = 0; i < this.pins.length; i++) {
        const p = this.pins[i], q = rt.projected[i];
        let vis = !!q?.visible;
        if (p.kind === "crossing") { vis = vis && showCrossings; }
        if (p.id === "earth") { vis = vis && this.chapter === "journey" && distanceAu(this.craftPos("voyager1")) < 25; }
        if (p.kind === "star") { vis = vis && viewR > 60000; }
        if (far && (p.id === "sun" || p.id === "voyager2")) { vis = false; }
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
.pin.flip { flex-direction: row-reverse; .pin-label { text-align: right; transform: translateX(calc(-100% - 16px)); } }
.pin.flip .pin-label { position: absolute; left: 0; top: -8px; }
.pin-craft .pin-dot { width: 14px; height: 14px; margin: -7px 0 0 -7px; }
.pin-voyager2 .pin-dot { border-radius: 2px; transform: rotate(45deg); }
.pin-sun .pin-dot { background: #ffd166; }
.pin-crossing .pin-dot { width: 9px; height: 9px; margin: -4.5px 0 0 -4.5px; background: transparent;
  border: 2px solid var(--pin); box-shadow: 0 0 0 1px #000; }
.pin-crossing .pin-label { font-size: 12px; opacity: 0.9; }
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
.v3d-cover {
  position: absolute; inset: 0; display: grid; place-items: center; align-content: center; gap: 12px;
  background: #05030f; color: #cfd6ff; font-size: 16px; text-align: center; padding: 24px;
}
</style>
