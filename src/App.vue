<template>
  <main class="vy" :class="{ kiosk: kioskMode }">
    <div class="vy-stage" aria-hidden="true">
      <voyager-view-3d
        v-if="startView"
        :chapter="chapter.id"
        :scene-ms="sceneMs"
        :shape="shape"
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
      <p v-else-if="chapter.id === 'journey'" class="vy-body">
        <strong class="vy-year">{{ sceneYear }}</strong> {{ journeyCaption || chapter.body }}
      </p>
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
  </main>
</template>

<script lang="ts">
import { defineAsyncComponent, defineComponent } from "vue";

import BrandMark from "./components/BrandMark.vue";
import { CHAPTERS, JOURNEY_EVENTS } from "./data/chapters";
import {
  Ephemeris, formatLightTime, formatMiles, lightHoursFromEarth, loadEphemeris, nowMs,
  positionAt, distanceAu, whenLightTimeReaches,
} from "./data/ephem";

const JOURNEY_START = Date.parse("1977-08-20T00:00:00Z");
const JOURNEY_SECONDS = 24;

export default defineComponent({
  name: "App",
  components: {
    "brand-mark": BrandMark,
    "voyager-view-3d": defineAsyncComponent(() => import("./components/VoyagerView3D.vue")),
    "crossing-chart": defineAsyncComponent(() => import("./components/CrossingChart.vue")),
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
    };
  },
  computed: {
    chapter() { return this.chapters[this.index]; },
    v1Hours(): number | null {
      return this.eph ? lightHoursFromEarth(this.eph, "voyager1", this.now) : null;
    },
    crossMs(): number | null {
      return this.eph ? whenLightTimeReaches(this.eph, "voyager1", 24, this.now) : null;
    },
    hook(): string {
      if (this.v1Hours === null) { return ""; }
      const lt = formatLightTime(this.v1Hours);
      if (this.v1Hours >= 24) { return `Voyager 1 is now more than one light-day from Earth (${lt}).`; }
      return `Voyager 1 is ${lt} of light from Earth.`;
    },
    todayBody(): string {
      if (!this.eph || this.v1Hours === null) { return ""; }
      const v1 = positionAt(this.eph.bodies.voyager1, this.now);
      const miles = formatMiles(distanceAu(v1, positionAt(this.eph.bodies.earth, this.now)));
      if (this.v1Hours >= 24) {
        return `Voyager 1 is ${miles} away. A radio signal now takes more than a full day to reach it, `
          + "and it will never be closer than one light-day again.";
      }
      let when = "";
      if (this.crossMs) {
        const dh = (this.crossMs - this.now) / 3600000;
        when = dh < 48 ? `about ${Math.round(dh)} hours` : `about ${Math.floor(dh / 24)} days ${Math.round(dh % 24)} hours`;
      }
      return `Voyager 1 is ${miles} away. A radio signal takes ${formatLightTime(this.v1Hours)} to reach it. `
        + (when ? `In ${when} it will take a full day, and it stays beyond one light-day from then on.` : "");
    },
    sceneYear(): string { return new Date(this.sceneMs).getUTCFullYear().toString(); },
    journeyCaption(): string {
      let text = "";
      for (const e of JOURNEY_EVENTS) {
        if (Date.parse(e.date + "T00:00:00Z") <= this.sceneMs) { text = e.text; }
      }
      return text;
    },
  },
  watch: {
    "chapter.id"(id: string) {
      cancelAnimationFrame(this.raf);
      this.stopListen();
      if (id === "journey") {
        this.journeyT0 = performance.now();
        this.sceneMs = JOURNEY_START;
        const step = () => {
          const f = Math.min(1, (performance.now() - this.journeyT0) / (JOURNEY_SECONDS * 1000));
          // Ease-in: the planet years pass slower than the cruise years.
          const e = f * f * (3 - 2 * f) * 0.6 + f * 0.4;
          this.sceneMs = JOURNEY_START + (this.now - JOURNEY_START) * e;
          if (f < 1) { this.raf = requestAnimationFrame(step); }
        };
        this.raf = requestAnimationFrame(step);
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
    // Start WWT only after the hook has painted.
    requestAnimationFrame(() => { this.startView = true; });
    window.setInterval(() => {
      this.now = nowMs();
      if (this.chapter.id !== "journey") { this.sceneMs = this.now; }
    }, 30000);
  },
  methods: {
    go(i: number): void { this.index = i; },
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
