<template>
  <main class="vy" :class="{ kiosk: kioskMode }">
    <div class="vy-stage" aria-hidden="true">
      <voyager-view-3d
        v-if="startView"
        :chapter="chapter.id"
        :scene-ms="sceneMs"
        :shape="shape"
        :pbd="pbd"
        @ready="viewReady = true"
      />
    </div>

    <header class="vy-top">
      <div class="vy-brand"><brand-mark :size="46" /></div>
      <div class="vy-title">
        <h1>Voyager</h1>
        <p class="vy-hook" aria-live="polite">
          <template v-if="hook">{{ hook }}</template>
          <template v-else>Loading positions…</template>
        </p>
      </div>
    </header>

    <section class="vy-card" :aria-label="chapter.title">
      <div class="vy-card-meta">
        <span v-for="t in chapter.tiers" :key="t" class="tier" :class="'tier-' + t.toLowerCase()">{{ t }}</span>
        <span class="vy-progress">{{ index + 1 }} of {{ chapters.length }}</span>
      </div>
      <h2>{{ chapter.title }}</h2>
      <p v-if="chapter.id === 'today'" class="vy-body">{{ todayBody }}</p>
      <template v-else-if="chapter.id === 'journey' && pbd">
        <p class="vy-body">
          <strong class="vy-year">14 Feb 1990</strong> Voyager 1 turned its camera back from 3.7 billion miles
          away and photographed Earth: less than a pixel, caught in a ray of scattered sunlight. The photo is
          placed exactly where its camera pointed; Earth sits on its dot.
        </p>
        <p class="vy-note">
          “Look again at that dot. That's here. That's home. That's us.” Carl Sagan.
          Image: NASA/JPL-Caltech, Pale Blue Dot Revisited (PIA23645). Camera roll estimated from the sunlight.
        </p>
        <button type="button" class="btn ghost vy-more" @click="endPbd">Continue the journey</button>
      </template>
      <template v-else-if="chapter.id === 'journey'">
        <p class="vy-body">
          <strong class="vy-year">{{ sceneYear }}</strong> {{ journeyCaption || chapter.body }}
        </p>
        <button type="button" class="btn ghost vy-more" @click="startPbd">See the Pale Blue Dot</button>
      </template>
      <p v-else class="vy-body">{{ chapter.body }}</p>

      <div v-if="chapter.id === 'bubble'" class="vy-seg" role="radiogroup" aria-label="Heliosphere shape">
        <button
          v-for="s in shapes" :key="s.id" type="button" role="radio"
          :aria-checked="shape === s.id" :class="{ on: shape === s.id }" @click="shape = s.id"
        >{{ s.label }}</button>
      </div>

      <template v-if="chapter.id === 'bubble'">
        <button type="button" class="btn ghost vy-more" :aria-expanded="showData" @click="showData = !showData">
          {{ showData ? "Hide the data" : "What Voyager 1 measured" }}
        </button>
        <crossing-chart v-if="showData" id="v1_hp" />
        <button
          v-if="!kioskMode" type="button" class="btn ghost vy-more" :aria-pressed="playing"
          @click="toggleListen"
        >
          <font-awesome-icon :icon="playing ? 'pause' : 'volume-high'" />
          {{ playing ? "Stop" : "Listen to interstellar space" }}
        </button>
        <p v-if="playing" class="vy-note">
          Plasma waves recorded by Voyager 1 in 2012–13, converted to sound (not a microphone recording).
          Their rising pitch shows the gas getting denser beyond the Sun's bubble.
          Courtesy NASA and the University of Iowa, CC BY 4.0, space-audio.org.
        </p>
      </template>

      <nav class="vy-nav">
        <button type="button" class="btn ghost" :disabled="index === 0" @click="go(index - 1)">
          <font-awesome-icon icon="chevron-left" /> Back
        </button>
        <button type="button" class="btn primary" @click="go((index + 1) % chapters.length)">
          {{ chapter.next }} <font-awesome-icon icon="chevron-right" />
        </button>
      </nav>
    </section>

    <template v-if="kioskMode">
      <div v-if="attract" class="vy-attract" aria-hidden="true">
        <p class="vy-attract-line">{{ attractLine }}</p>
        <p class="vy-attract-touch">Touch to explore</p>
      </div>
      <kiosk-qr :url="kioskHomeUrl" :big="attract && attractFinale" />
    </template>
  </main>
</template>

<script lang="ts">
import { defineAsyncComponent, defineComponent } from "vue";

import BrandMark from "./components/BrandMark.vue";
import {
  KIOSK_IDLE_MS, KIOSK_RELOAD_HOUR, createIdleWatcher, installKioskGuards, scheduleDailyReload,
} from "./kiosk/kiosk";
import { CHAPTERS, JOURNEY_EVENTS } from "./data/chapters";
import {
  Ephemeris, formatLightTime, formatMiles, lightHoursFromEarth, loadEphemeris, nowMs,
  positionAt, distanceAu, whenLightTimeReaches,
} from "./data/ephem";

const JOURNEY_START = Date.parse("1977-08-20T00:00:00Z");
const JOURNEY_SECONDS = 24;
/** Pale Blue Dot: Voyager 1 narrow-angle frame, 1990-02-14 04:48 UTC (docs/RESEARCH-pbd.md). */
const PBD_MS = Date.parse("1990-02-14T04:48:00Z");

export default defineComponent({
  name: "App",
  components: {
    "brand-mark": BrandMark,
    "voyager-view-3d": defineAsyncComponent(() => import("./components/VoyagerView3D.vue")),
    "crossing-chart": defineAsyncComponent(() => import("./components/CrossingChart.vue")),
    "kiosk-qr": defineAsyncComponent(() => import("./components/KioskQr.vue")),
  },
  props: {
    kioskMode: { type: Boolean, default: false },
    kioskHomeUrl: { type: String, default: "" },
  },
  data() {
    return {
      chapters: CHAPTERS,
      index: 0,
      shape: "comet" as "comet" | "croissant" | "bubble",
      shapes: [
        { id: "comet", label: "Comet" }, { id: "croissant", label: "Croissant" }, { id: "bubble", label: "Bubble" },
      ] as const,
      eph: null as Ephemeris | null,
      now: nowMs(),
      sceneMs: nowMs(),
      startView: false,
      viewReady: false,
      raf: 0,
      journeyT0: 0,
      showData: false,
      playing: false,
      audio: null as HTMLAudioElement | null,
      pbd: false,
      attract: false,
      attractFinale: false,
      attractLine: "",
      attractTimers: [] as number[],
      kioskCleanup: [] as (() => void)[],
    };
  },
  computed: {
    chapter() { return this.chapters[this.index]; },
    v1Hours(): number | null {
      return this.eph ? lightHoursFromEarth(this.eph, "voyager1", this.now) : null;
    },
    /**
     * The moment Earth-to-V1 light time first reaches 24 h (~2026-11-18 UTC),
     * found from a FIXED search start so it is still known after the crossing.
     * Checked against Horizons to 2030: it never dips back below (HANDOFF).
     */
    crossMs(): number | null {
      return this.eph ? whenLightTimeReaches(this.eph, "voyager1", 24, Date.parse("2026-11-01T00:00:00Z")) : null;
    },
    crossDate(): string {
      return this.crossMs
        ? new Date(this.crossMs).toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric" })
        : "";
    },
    /** Hours from the crossing to now: negative before it, positive after. */
    sinceCrossH(): number | null {
      return this.crossMs ? (this.now - this.crossMs) / 3600000 : null;
    },
    hook(): string {
      if (this.v1Hours === null) { return ""; }
      const lt = formatLightTime(this.v1Hours);
      const since = this.sinceCrossH;
      if (since !== null && since >= 0 && since < 36) { return `Today Voyager 1 reached one light-day from Earth (${lt}).`; }
      if (this.v1Hours >= 24) { return `Voyager 1 is more than one light-day from Earth: ${lt} of light.`; }
      return `Voyager 1 is ${lt} of light from Earth.`;
    },
    todayBody(): string {
      if (!this.eph || this.v1Hours === null) { return ""; }
      const v1 = positionAt(this.eph.bodies.voyager1, this.now);
      const miles = formatMiles(distanceAu(v1, positionAt(this.eph.bodies.earth, this.now)));
      const lt = formatLightTime(this.v1Hours);
      const since = this.sinceCrossH;
      if (since !== null && since >= 0) {
        const first = since < 36 ? "Today it became" : `On ${this.crossDate} it became`;
        return `${first} the first human-made object one light-day from Earth. Voyager 1 is ${miles} away; `
          + `a radio signal now takes ${lt} to reach it, and it will never be closer than one light-day again.`;
      }
      let when = "";
      if (since !== null) {
        const totalH = Math.max(1, Math.round(-since));
        when = totalH < 48 ? `about ${totalH} hours`
          : `about ${Math.floor(totalH / 24)} days ${totalH % 24} hours`;
      }
      return `Voyager 1 is ${miles} away. A radio signal takes ${lt} to reach it. `
        + (when ? `In ${when} it will take a full day, and it stays beyond one light-day from then on.` : "");
    },
    sceneYear(): string { return new Date(this.sceneMs).getUTCFullYear().toString(); },
    journeyCaption(): string {
      let text = "";
      for (const e of JOURNEY_EVENTS) {
        // Show an event for ~4 years after it happens, then fall back to the body text.
        const t = Date.parse(e.date + "T00:00:00Z");
        if (t <= this.sceneMs && this.sceneMs - t < 4 * 365.25 * 86400000) { text = e.text; }
      }
      return text;
    },
  },
  watch: {
    "chapter.id"(id: string) {
      cancelAnimationFrame(this.raf);
      this.stopListen();
      this.pbd = false;
      if (id === "journey") {
        this.runJourney(JOURNEY_START, JOURNEY_SECONDS);
      } else {
        this.sceneMs = this.now;
      }
    },
  },
  created() {
    // Deep links: ?ch=1..5 (chapter), ?shape=comet|croissant|bubble (AUDIT-UI #22).
    const q = new URLSearchParams(window.location.search);
    const ch = Number(q.get("ch"));
    if (ch >= 1 && ch <= this.chapters.length) { this.index = ch - 1; }
    const sh = q.get("shape");
    if (sh === "comet" || sh === "croissant" || sh === "bubble") { this.shape = sh; }
  },
  async mounted() {
    try {
      this.eph = Object.freeze(await loadEphemeris()) as Ephemeris;
    } catch (err) {
      console.error("[App] ephemeris failed:", err);
    }
    if (this.kioskMode) { this.initKiosk(); }
    // Start WWT only after the hook has painted.
    requestAnimationFrame(() => { this.startView = true; });
    window.setInterval(() => {
      this.now = nowMs();
      if (this.chapter.id !== "journey") { this.sceneMs = this.now; }
    }, 30000);
  },
  methods: {
    go(i: number): void { this.index = i; },
    /** Play the journey from `fromMs` to now over `seconds` (eased: planet years slower). */
    runJourney(fromMs: number, seconds: number): void {
      cancelAnimationFrame(this.raf);
      this.journeyT0 = performance.now();
      this.sceneMs = fromMs;
      const step = () => {
        const f = Math.min(1, (performance.now() - this.journeyT0) / (seconds * 1000));
        const e = f * f * (3 - 2 * f) * 0.6 + f * 0.4;
        this.sceneMs = fromMs + (this.now - fromMs) * e;
        if (f < 1) { this.raf = requestAnimationFrame(step); }
      };
      this.raf = requestAnimationFrame(step);
    },
    startPbd(): void {
      cancelAnimationFrame(this.raf);
      this.sceneMs = PBD_MS;
      this.pbd = true;
    },
    endPbd(): void {
      this.pbd = false;
      this.runJourney(PBD_MS, 14);
    },

    // ── Lobby kiosk (?kiosk=1) ───────────────────────────────────────
    // Sol's kiosk runtime (idle watcher, guards, nightly reload) plus a Voyager
    // attract loop: a ~100 s walk through the chapters (AUDIT-UI kiosk script).
    // ?kioskIdle=<seconds> shortens the idle timeout for testing.
    initKiosk(): void {
      const idleS = Number(new URLSearchParams(location.search).get("kioskIdle"));
      const watcher = createIdleWatcher({
        idleMs: idleS > 0 ? idleS * 1000 : KIOSK_IDLE_MS,
        onIdle: () => this.startAttract(),
        onActive: () => { if (this.attract) { this.stopAttract(); } },
      });
      watcher.start();
      this.kioskCleanup.push(() => watcher.stop());
      this.kioskCleanup.push(installKioskGuards({ onExternalLink: () => { /* no navigation on the kiosk */ } }));
      this.kioskCleanup.push(scheduleDailyReload(KIOSK_RELOAD_HOUR, () => this.attract));
    },
    startAttract(): void {
      this.stopListen();
      this.attract = true;
      const v1 = this.v1Hours !== null && this.v1Hours < 24
        ? `Voyager 1 is ${formatLightTime(this.v1Hours)} of light from Earth, almost one light-day`
        : "Voyager 1 is now more than one light-day from Earth";
      const script: [number, () => void][] = [
        [0, () => { this.attractFinale = false; this.shape = "comet"; this.index = 0; this.attractLine = v1; }],
        [15, () => { this.index = 1; this.attractLine = "Launched in 1977. Still talking to us."; }],
        [40, () => { this.index = 2; this.attractLine = "It left the Sun's bubble in 2012. Nobody knows the bubble's shape."; }],
        [45, () => { this.shape = "croissant"; }],
        [50, () => { this.shape = "bubble"; }],
        [56, () => { this.shape = "comet"; this.index = 3; this.attractLine = "30,000 more years to cross the Oort cloud"; }],
        [72, () => { this.index = 4; this.attractLine = "Out of the Sun's bubble. Not out of the solar system. Not even close."; }],
        [88, () => { this.index = 0; this.attractFinale = true; this.attractLine = "Touch to explore, or take it home"; }],
        [100, () => this.startAttract()],
      ];
      this.clearAttractTimers();
      for (const [t, fn] of script) {
        this.attractTimers.push(window.setTimeout(() => { if (this.attract) { fn(); } }, t * 1000));
      }
    },
    stopAttract(): void {
      this.clearAttractTimers();
      this.attract = false;
      this.attractFinale = false;
      this.shape = "comet";
      this.index = 0;
    },
    clearAttractTimers(): void {
      this.attractTimers.forEach((t) => window.clearTimeout(t));
      this.attractTimers = [];
    },
    /**
     * Voyager 1 PWS interstellar plasma waves, hotlinked (CC BY 4.0, NASA /
     * University of Iowa; docs/RESEARCH-crossings.md). Opt-in, phone only,
     * stops on chapter change (AUDIT-UI #20).
     */
    toggleListen(): void {
      if (this.playing) { this.stopListen(); return; }
      if (!this.audio) {
        this.audio = new Audio("https://space.physics.uiowa.edu/plasma-wave/voyager/v1pws_interstellar_epo.mp4");
        this.audio.addEventListener("ended", () => { this.playing = false; });
      }
      this.audio.currentTime = 0;
      void this.audio.play().then(() => { this.playing = true; }).catch((err) => {
        console.error("[App] audio failed:", err);
        this.playing = false;
      });
    },
    stopListen(): void {
      this.audio?.pause();
      this.playing = false;
    },
  },
});
</script>
