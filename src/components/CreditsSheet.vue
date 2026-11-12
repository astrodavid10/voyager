<template>
  <div class="cs-backdrop" @click.self="$emit('close')">
    <div ref="panel" class="cs-panel" role="dialog" aria-modal="true" aria-labelledby="cs-title" tabindex="-1">
      <button ref="close" type="button" class="cs-close" aria-label="Close" @click="$emit('close')">
        <font-awesome-icon icon="xmark" />
      </button>
      <h2 id="cs-title">About Voyager</h2>
      <p>
        Where the twin Voyager spacecraft are right now, how they got there, what they found at the edge of the
        Sun's bubble, and how far the Sun's gravity really reaches. Every chapter says whether it shows something
        <strong class="t-m">measured</strong>, <strong class="t-o">modelled</strong> or
        <strong class="t-p">predicted</strong>.
      </p>

      <h3>Data and images</h3>
      <ul>
        <li>Trajectories: NASA/JPL Horizons.</li>
        <li>
          Voyager particle data: NASA Space Physics Data Facility. CRS: E. C. Stone, A. C. Cummings; LECP:
          S. M. Krimigis; PLS: J. D. Richardson.
        </li>
        <li>Plasma-wave sound: NASA and The University of Iowa (CC BY 4.0, space-audio.org).</li>
        <li>Pale Blue Dot: NASA/JPL-Caltech, <em>Pale Blue Dot Revisited</em> (PIA23645).</li>
        <li>
          Heliosphere: shaped after McComas et al. 2015 (IBEX), Kleimann et al. 2022, Opher et al. 2015/2020 and
          Dialynas et al. 2017, and fitted through Voyager's own crossings.
        </li>
        <li>
          The Sun's gravitational domain: Veras &amp; Evans 2013, Bovy 2017, McKee et al. 2015. The Oort cloud
          is illustrative, after Vokrouhlický et al. 2019 and Nesvorný et al. 2025.
        </li>
        <li>
          Milky Way: ESA/Gaia/DPAC, Stefan Payne-Wardenaar (CC BY-SA 3.0 IGO), with arms after Reid et al. 2019.
        </li>
        <li>
          Pulsars: Golden Record cover (NASA/JPL), identified by W. R. Johnston; ATNF Pulsar Catalogue.
          Gliese 445 flyby: Gaia DR3; Bailer-Jones &amp; Farnocchia 2019.
        </li>
        <li>Sky: all-sky panorama by Eckhard Slawik (NOIRLab/NSF/AURA/E. Slawik/M. Zamani, CC BY 4.0).</li>
      </ul>

      <p class="cs-fine">Created by A. David Weigel.</p>

      <!-- Institutional lockup stays ONE image (brand kit: the planetarium
           wordmark never appears without the USSRC logo); see sol/InfoModal. -->
      <div class="cs-logos">
        <a
          class="cs-logo-link" href="https://www.rocketcenter.com/INTUITIVEPlanetarium" target="_blank"
          rel="noopener" aria-label="INTUITIVE Planetarium at the U.S. Space &amp; Rocket Center"
        >
          <img class="cs-logo-ip" src="../assets/ip-ussrc.png" alt="INTUITIVE Planetarium at the U.S. Space &amp; Rocket Center">
        </a>
        <a class="cs-attr" href="https://www.cosmicds.cfa.harvard.edu/" target="_blank" rel="noopener">
          <img src="../assets/logo_cosmicds.png" alt="CosmicDS">
          <span>Interactive developed using the CosmicDS toolkit</span>
        </a>
        <a class="cs-attr" href="https://worldwidetelescope.org/" target="_blank" rel="noopener">
          <img src="../assets/logo_wwt.png" alt="WorldWide Telescope">
          <span>Powered by WorldWide Telescope</span>
        </a>
      </div>
    </div>
  </div>
</template>

<script lang="ts">
import { defineComponent } from "vue";

export default defineComponent({
  name: "CreditsSheet",
  emits: ["close"],
  mounted() {
    (this.$refs.close as HTMLElement | undefined)?.focus();
    window.addEventListener("keydown", this.onKey);
  },
  beforeUnmount() { window.removeEventListener("keydown", this.onKey); },
  methods: {
    onKey(e: KeyboardEvent): void {
      if (e.key === "Escape") { this.$emit("close"); return; }
      if (e.key !== "Tab") { return; }
      // Keep focus inside the dialog.
      const panel = this.$refs.panel as HTMLElement | undefined;
      if (!panel) { return; }
      const items = panel.querySelectorAll<HTMLElement>("a[href], button");
      if (!items.length) { return; }
      const first = items[0], last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); } else if (
        !e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    },
  },
});
</script>

<style lang="less">
.cs-backdrop {
  position: fixed; inset: 0; z-index: 60; background: rgba(2, 1, 8, 0.72);
  display: flex; align-items: flex-start; justify-content: center; overflow-y: auto; padding: 16px;
}
.cs-panel {
  position: relative; width: min(100%, 34rem); margin: auto; padding: 18px 20px 20px;
  background: #0d0a24; border: 1px solid rgba(160, 170, 255, 0.22); border-radius: 16px; color: #eef0ff;
  h2 { margin: 0 44px 10px 0; font-size: 22px; }
  h3 { margin: 16px 0 6px; font-size: 16px; }
  p, li { font-size: 15px; line-height: 1.45; }
  ul { margin: 0; padding-left: 18px; li { margin-bottom: 6px; } }
  a { color: #ffd166; }
  .t-m { color: #9be29b; } .t-o { color: #ffd166; } .t-p { color: #c9a7ff; }
}
.cs-close {
  position: absolute; top: 8px; right: 8px; width: 44px; height: 44px; display: grid; place-items: center;
  font-size: 20px; color: #b9bfe6; cursor: pointer; border-radius: 10px;
  &:focus-visible { outline: 3px solid #ffd166; }
}
.cs-fine { margin: 16px 0 0; font-style: italic; color: #b9bfe6; font-size: 14px; }
.cs-logos {
  display: flex; flex-direction: column; align-items: center; gap: 10px; margin-top: 14px; padding-top: 14px;
  border-top: 1px solid rgba(160, 170, 255, 0.18);
}
.cs-logo-ip { display: block; max-width: 13rem; height: auto; }
.cs-attr {
  display: flex; align-items: center; gap: 10px; color: #dfe3ff !important; text-decoration: none; font-size: 14px;
  img { width: 28px; height: 28px; object-fit: contain; }
}
</style>
