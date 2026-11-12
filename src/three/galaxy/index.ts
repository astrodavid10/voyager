// =====================================================================
// 3D Milky Way layer: the integration contract (owned by src/three/galaxy/)
// =====================================================================
// VoyagerView3D calls createGalaxy() once after the three.js stage exists and
// update() every frame. Everything else about the galaxy lives in this folder,
// so the galaxy work can proceed without touching the view or the app.
//
// Frame: the scene is heliocentric ECLIPTIC J2000 in AU (right-handed;
// x = vernal equinox, z = ecliptic north). Add your objects under `world`,
// which VoyagerView3D already offsets for WWT's viewTarget (HANDOFF V1).
// 1 pc = 206,264.806 au; 1 ly = 63,241.077 au. Galactic axes in ecliptic J2000
// (astropy): toward the Galactic centre (l=0,b=0) = (-0.05488, -0.99382, -0.09648);
// l=90 = (0.49411, -0.11099, 0.86229); North Galactic Pole = (-0.86767, -0.00035, 0.49715).
// Sun–Galactic-centre distance: use a cited value (GRAVITY 2019/2021: ~8.18 kpc).
//
// No WWT imports here (sol footgun 12): take what you need from the context.

import type { Camera, Group, WebGLRenderer } from "three";

export interface GalaxyContext {
  /** Root group, ecliptic J2000 AU, already offset for WWT's viewTarget. */
  world: Group;
  camera: Camera;
  renderer: WebGLRenderer;
  /** Device pixel ratio actually used for the canvas (capped at 2). */
  dpr: number;
  /** True on low-end devices (sol/JWST "lite" tier rules); keep it cheap. */
  lite: boolean;
}

export interface GalaxyFrame {
  /** Radius (au) framed on the screen's short axis: the zoom level. */
  viewRAu: number;
  /** Scene time, ms since epoch (UTC). */
  ms: number;
}

export interface GalaxyLayer {
  update(frame: GalaxyFrame): void;
  setVisible(visible: boolean): void;
  dispose(): void;
}

/** Stub until the Milky Way port lands. Returns null = no galaxy layer. */
export async function createGalaxy(_ctx: GalaxyContext): Promise<GalaxyLayer | null> {
  return null;
}
