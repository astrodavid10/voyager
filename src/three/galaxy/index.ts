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
// (astropy): toward the Galactic center (l=0,b=0) = (-0.05488, -0.99382, -0.09648);
// l=90 = (0.49411, -0.11099, 0.86229); North Galactic Pole = (-0.86767, -0.00035, 0.49715).
// Sun–Galactic-center distance: 8.178 kpc (GRAVITY 2019), see frame.ts.
//
// No WWT imports here (sol footgun 12): take what you need from the context.
//
// ── What this is ─────────────────────────────────────────────────────
// A port of JWST's Galaxy3D v3 (JWST/GALAXY3D_PLAN.md) from raw WebGL inside
// WWT's draw hook to three.js objects under `world`:
//
//   slices  the face-on Gaia artist's-impression texture drawn as a stack of
//           quads parallel to the plane, shaped by a sech^2 vertical envelope
//           (thin disk + flare + bulge), screen-blended. The mid-plane quad is
//           the "poster"; the others give it a body.
//   dust    dark billboards, multiplicative (ZERO, ONE_MINUS_SRC_ALPHA).
//   glow    luminous billboards, screen-blended: bulge, arm puffs, knots.
//   stars   small points (JWST's Phase C, never built there).
//   marker  a pulsing "you are here" ring on the Sun.
//
// New here: the frame comes from the Galactic axes and a cited R0 instead of
// WWT's legacy image-quad rotation chain; the Sun sits 20.8 pc above the
// plane; the disk is warped; arms follow Reid et al. 2019 where measured and
// the texture elsewhere (structure.ts); labels() exposes 3D anchor points.
//
// Blending is order-independent in every pass, so nothing is sorted. Nothing
// reads or writes depth. All shaders pin clip-space z to 0: WWT's far plane is
// only 3x the camera distance, which would otherwise slice the far side of the
// Galaxy off at intermediate zooms.
//
// Tiers: full = 2k texture, 5 slices a side, ~4,000 sprites, 36k stars.
// lite (ctx.lite, or a GPU that cannot hold a 2k texture) = 1k texture, 2
// slices a side, ~1,300 sprites, 8k stars; ~90 kB of download.
//
// Deep links (debugging): ?gxarms=1 draws the Reid et al. arm ridges, the bar
// axis and the Sun-center line; ?gxexp=1.3 scales the exposure.

import {
  AddEquation, BufferGeometry, CanvasTexture, CustomBlending, DoubleSide, Float32BufferAttribute,
  Group, InstancedBufferAttribute, InstancedBufferGeometry, LineSegments, LinearFilter,
  LinearMipmapLinearFilter, Mesh, NormalBlending, OneFactor, OneMinusSrcAlphaFactor,
  OneMinusSrcColorFactor, Points, ShaderMaterial, Texture, TextureLoader, Vector2, Vector3, ZeroFactor,
} from "three";
import type { Camera, Material, WebGLRenderer } from "three";

import { ARMS, BAR_ANGLE_RAD, BAR_HALF_LEN_KPC, armPoint } from "./arms";
import { ATLAS_COLS, ATLAS_ROWS, buildAtlas } from "./atlas";
import { AU_PER_KPC, R0_KPC, TEX_SIDE_KPC, Z_SUN_KPC, galaxyMatrix, texUV, warpZ } from "./frame";
import { buildModel } from "./structure";
import type { Guide, SpriteBatch } from "./structure";

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

/** A labeled 3D anchor the host can turn into an HTML pin. */
export interface GalaxyLabel {
  id: string;
  label: string;
  /** Optional second line. */
  sub?: string;
  kind: "sun" | "center" | "arm";
  /** Scene coordinates: heliocentric ecliptic J2000, au (add world.position like any pin). */
  position: [number, number, number];
  /** Suggested zoom range (viewRAu) over which the label is worth showing. */
  minViewRAu: number;
  maxViewRAu: number;
}

export interface GalaxyLayer {
  update(frame: GalaxyFrame): void;
  setVisible(visible: boolean): void;
  dispose(): void;
  /** Labeled anchor points (static; safe to call once and cache). */
  labels(): GalaxyLabel[];
  /** Current fade, 0 (hidden) .. 1 (fully on), after the last update(). */
  opacity(): number;
  /** Show or hide the Reid et al. 2019 arm ridges (calibration overlay). */
  setDebugArms(on: boolean): void;
  /** Which tier was built. */
  readonly tier: "full" | "lite";
}

// ── Fade ─────────────────────────────────────────────────────────────
/** Invisible below this zoom radius (au): about 16 light-years. */
export const FADE_START_AU = 1e6;
/** Fully on from this zoom radius (au): about 1,600 light-years. */
export const FADE_FULL_AU = 1e8;

function smoothstep(e0: number, e1: number, x: number): number {
  const t = Math.min(1, Math.max(0, (x - e0) / (e1 - e0)));
  return t * t * (3 - 2 * t);
}

// ── Shaders ──────────────────────────────────────────────────────────
// NOTE view-space z is POSITIVE in front of this camera (WWT's lookAtLH), so
// distances use length(eye.xyz), never -eye.z.
const PIN_DEPTH = "gl_Position.z = 0.0;"; // see the header: dodge WWT's far plane

const SLICE_VERT = /* glsl */ `
  attribute vec2 aMeta;       // |slice height| kpc, weight
  uniform vec2 uNearBase;     // camera-distance fade (au) for the mid-plane quad
  uniform vec2 uNearSlice;    // ... and for the volume slices
  varying vec2 vUv;
  varying vec2 vPlane;
  varying vec2 vMeta;
  varying float vCamFade;
  void main() {
    vec4 eye = modelViewMatrix * vec4(position, 1.0);
    gl_Position = projectionMatrix * eye;
    ${PIN_DEPTH}
    float d = length(eye.xyz);
    // Fragments near the camera fade out, so sitting inside the disk does not
    // fill the screen with fog while the far side still glows.
    vCamFade = aMeta.x > 0.0001 ? smoothstep(uNearSlice.x, uNearSlice.y, d) : smoothstep(uNearBase.x, uNearBase.y, d);
    vUv = uv;
    vPlane = position.xy;
    vMeta = aMeta;
  }`;

// sech^2 in the exp(-2|x|) <= 1 form, which cannot overflow a mediump float.
const SLICE_FRAG = /* glsl */ `
  precision mediump float;
  uniform sampler2D uTex;
  uniform float uOpacity;
  varying vec2 vUv;
  varying vec2 vPlane;
  varying vec2 vMeta;
  varying float vCamFade;
  float sech2(float x) {
    float e = exp(-2.0 * abs(x));
    float s = 1.0 + e;
    return 4.0 * e / (s * s);
  }
  void main() {
    float r = length(vPlane);
    float hz = 0.30 + 0.35 * max(0.0, r - 6.0) / 9.0;  // thin disk + outer flare
    hz += 1.10 * exp(-(r * r) / (1.4 * 1.4));          // bulge thickening
    float env = sech2(vMeta.x / hz);
    // The texture is square; fade to nothing over 15.5 -> 19 kpc.
    float vig = smoothstep(19.0, 15.5, r);
    float a = env * vMeta.y * uOpacity * vCamFade * vig;
    if (a <= 0.002) discard;
    // Subtract the image's noise floor, or it stacks into a visible slab.
    vec3 c = max(texture2D(uTex, vUv).rgb - 0.02, 0.0);
    gl_FragColor = vec4(c * a, 1.0);
  }`;

const SPRITE_VERT = /* glsl */ `
  attribute vec3 iPos;
  attribute float iSize;
  attribute vec4 iColor;
  attribute float iCell;
  uniform float uKpcAu;
  uniform vec2 uNear;
  uniform vec2 uAtlas;        // columns, rows
  varying vec2 vUv;
  varying vec4 vColor;
  void main() {
    vec4 eye = modelViewMatrix * vec4(iPos, 1.0);
    float fade = smoothstep(uNear.x, uNear.y, length(eye.xyz));
    eye.xy += position.xy * iSize * uKpcAu;   // camera-facing billboard, sized in au
    gl_Position = projectionMatrix * eye;
    ${PIN_DEPTH}
    float col = mod(iCell, uAtlas.x);
    float row = floor(iCell / uAtlas.x + 0.001);
    vec2 base = position.xy * 0.5 + 0.5;
    vUv = vec2((col + base.x) / uAtlas.x, 1.0 - (row + base.y) / uAtlas.y);
    vColor = vec4(iColor.rgb, iColor.a * fade);
  }`;

// Premultiplied output, so one shader serves both the glow (screen) and the
// dust (multiplicative) blend modes.
const SPRITE_FRAG = /* glsl */ `
  precision mediump float;
  uniform sampler2D uAtlasTex;
  uniform float uOpacity;
  varying vec2 vUv;
  varying vec4 vColor;
  void main() {
    float a = texture2D(uAtlasTex, vUv).a * vColor.a * uOpacity;
    if (a <= 0.002) discard;
    gl_FragColor = vec4(vColor.rgb * a, a);
  }`;

const STAR_VERT = /* glsl */ `
  attribute vec4 aColor;      // rgb, size multiplier
  uniform float uSize;
  varying vec3 vCol;
  void main() {
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
    ${PIN_DEPTH}
    gl_PointSize = uSize * aColor.a;
    vCol = aColor.rgb;
  }`;

const STAR_FRAG = /* glsl */ `
  precision mediump float;
  uniform float uOpacity;
  varying vec3 vCol;
  void main() {
    float a = smoothstep(0.5, 0.1, length(gl_PointCoord - 0.5)) * uOpacity;
    gl_FragColor = vec4(vCol * a, 1.0);
  }`;

const MARK_VERT = /* glsl */ `
  uniform float uSize;
  void main() {
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
    ${PIN_DEPTH}
    gl_PointSize = uSize;
  }`;

// A steady ring plus one that expands and fades: reads as "here" at a glance.
const MARK_FRAG = /* glsl */ `
  precision mediump float;
  uniform float uOpacity;
  uniform float uPulse;
  void main() {
    float r = length(gl_PointCoord - 0.5) * 2.0;
    float ring = smoothstep(0.10, 0.04, abs(r - 0.34));
    float core = smoothstep(0.12, 0.05, r);
    float wave = smoothstep(0.10, 0.02, abs(r - (0.34 + 0.6 * uPulse))) * (1.0 - uPulse);
    float a = clamp(ring + core + 0.8 * wave, 0.0, 1.0) * uOpacity;
    if (a <= 0.003) discard;
    gl_FragColor = vec4(vec3(1.0, 0.86, 0.45), a);
  }`;

const LINE_VERT = /* glsl */ `
  attribute vec3 aColor;
  varying vec3 vCol;
  void main() {
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
    ${PIN_DEPTH}
    vCol = aColor;
  }`;
const LINE_FRAG = /* glsl */ `
  precision mediump float;
  varying vec3 vCol;
  void main() { gl_FragColor = vec4(vCol, 1.0); }`;

// ── Geometry builders ────────────────────────────────────────────────
const SLICES_FULL_KPC = [0.12, 0.28, 0.5, 0.85, 1.5];
const SLICES_LITE_KPC = [0.2, 0.7];
// Total strength of the volume stack relative to the mid-plane quad
// (calibrated in JWST: the lite stack sits lower and passes ~2x more light).
const SLICE_GAIN_FULL = 3.0;
const SLICE_GAIN_LITE = 1.1;

/** Slab thickness each slice stands for, normalized to sum to 1 per side. */
function sliceWeights(h: number[]): number[] {
  const w = h.map((v, i) => {
    const lo = i === 0 ? 0 : (h[i - 1] + v) / 2;
    const hi = i === h.length - 1 ? v + (v - lo) : (v + h[i + 1]) / 2;
    return hi - lo;
  });
  const sum = w.reduce((a, b) => a + b, 0);
  return w.map((x) => x / sum);
}

function buildSlices(lite: boolean): BufferGeometry {
  const heights = lite ? SLICES_LITE_KPC : SLICES_FULL_KPC;
  const gain = lite ? SLICE_GAIN_LITE : SLICE_GAIN_FULL;
  const weights = sliceWeights(heights);
  const n = lite ? 20 : 36; // grid subdivisions (the warp displaces the outer rings)
  const sliceCount = heights.length * 2 + 1;
  const per = (n + 1) * (n + 1);
  const pos = new Float32Array(sliceCount * per * 3);
  const uv = new Float32Array(sliceCount * per * 2);
  const meta = new Float32Array(sliceCount * per * 2);
  const index: number[] = [];
  let v = 0;
  for (let s = 0; s < sliceCount; s++) {
    const k = (s - 1) >> 1;
    const h = s === 0 ? 0 : heights[k] * ((s - 1) % 2 === 0 ? 1 : -1);
    const weight = s === 0 ? 1 : weights[k] * gain;
    const base = s * per;
    for (let iy = 0; iy <= n; iy++) {
      const y = (iy / n - 0.5) * TEX_SIDE_KPC;
      for (let ix = 0; ix <= n; ix++, v++) {
        const x = (ix / n - 0.5) * TEX_SIDE_KPC;
        pos[v * 3] = x; pos[v * 3 + 1] = y; pos[v * 3 + 2] = h + warpZ(x, y);
        const t = texUV(x, y);
        uv[v * 2] = t[0]; uv[v * 2 + 1] = t[1];
        meta[v * 2] = Math.abs(h); meta[v * 2 + 1] = weight;
      }
    }
    for (let iy = 0; iy < n; iy++) {
      for (let ix = 0; ix < n; ix++) {
        const a = base + iy * (n + 1) + ix, b = a + 1, c = a + n + 1, d = c + 1;
        index.push(a, c, b, b, c, d);
      }
    }
  }
  const g = new BufferGeometry();
  g.setAttribute("position", new Float32BufferAttribute(pos, 3));
  g.setAttribute("uv", new Float32BufferAttribute(uv, 2));
  g.setAttribute("aMeta", new Float32BufferAttribute(meta, 2));
  g.setIndex(index);
  return g;
}

function buildSpriteGeometry(batch: SpriteBatch): InstancedBufferGeometry {
  const g = new InstancedBufferGeometry();
  g.setAttribute("position", new Float32BufferAttribute([-1, -1, 0, 1, -1, 0, -1, 1, 0, 1, 1, 0], 3));
  g.setIndex([0, 1, 2, 2, 1, 3]);
  g.setAttribute("iPos", new InstancedBufferAttribute(batch.pos, 3));
  g.setAttribute("iSize", new InstancedBufferAttribute(batch.size, 1));
  g.setAttribute("iColor", new InstancedBufferAttribute(batch.color, 4));
  g.setAttribute("iCell", new InstancedBufferAttribute(batch.cell, 1));
  g.instanceCount = batch.count;
  return g;
}

function buildDebugArms(): BufferGeometry {
  const p: number[] = [], c: number[] = [];
  const seg = (a: [number, number], b: [number, number], col: number[]): void => {
    p.push(a[0], a[1], 0.03, b[0], b[1], 0.03); c.push(...col, ...col);
  };
  const cols = [[1, 0.3, 0.3], [0.3, 1, 0.3], [0.3, 1, 1], [1, 1, 0.3], [1, 0.3, 1], [1, 0.6, 0.2]];
  ARMS.forEach((arm, i) => {
    const steps = 64;
    for (let s = 0; s < steps; s++) {
      const b0 = arm.betaMinDeg + (arm.betaMaxDeg - arm.betaMinDeg) * (s / steps);
      const b1 = arm.betaMinDeg + (arm.betaMaxDeg - arm.betaMinDeg) * ((s + 1) / steps);
      seg(armPoint(arm, b0), armPoint(arm, b1), cols[i % cols.length]);
    }
  });
  const bx = -BAR_HALF_LEN_KPC * Math.cos(BAR_ANGLE_RAD), by = BAR_HALF_LEN_KPC * Math.sin(BAR_ANGLE_RAD);
  seg([bx, by], [-bx, -by], [1, 1, 1]);           // bar axis, near end on the Sun's +l side
  seg([-R0_KPC, 0], [0, 0], [0.6, 0.6, 0.6]);     // Sun -> Galactic center
  seg([-R0_KPC, 0], [-R0_KPC, 2], [0.2, 0.5, 1]); // from the Sun toward l = 90 (the direction of rotation)
  const g = new BufferGeometry();
  g.setAttribute("position", new Float32BufferAttribute(p, 3));
  g.setAttribute("aColor", new Float32BufferAttribute(c, 3));
  return g;
}

function loadTexture(url: string): Promise<Texture> {
  return new TextureLoader().loadAsync(url);
}

/** Downsample the loaded image to steer sprite placement; null if the canvas is unreadable. */
function makeGuide(image: CanvasImageSource, n: number): Guide | null {
  try {
    const c = document.createElement("canvas");
    c.width = n; c.height = n;
    const ctx = c.getContext("2d", { willReadFrequently: true });
    if (!ctx) { return null; }
    ctx.drawImage(image, 0, 0, n, n);
    return { n, data: ctx.getImageData(0, 0, n, n).data };
  } catch (err) {
    console.warn("[galaxy] texture guide unavailable; sprites fall back to unguided placement.", err);
    return null;
  }
}

/**
 * Build the Milky Way layer. Rejects if the texture cannot be fetched (the
 * caller logs it and carries on without a galaxy).
 */
export async function createGalaxy(ctx: GalaxyContext): Promise<GalaxyLayer | null> {
  const maxTex = ctx.renderer.capabilities.maxTextureSize;
  const lite = ctx.lite || maxTex < 2048;
  const params = new URLSearchParams(location.search);
  const exposure = Math.min(3, Math.max(0.2, Number(params.get("gxexp")) || 1));

  const file = lite ? "milkyway-1k.jpg" : "milkyway-2k.jpg";
  const tex = await loadTexture(new URL(`data/galaxy/${file}`, document.baseURI).href);
  // Raw sRGB values in, raw values out: the screen blend is tuned in display space (as in JWST).
  tex.generateMipmaps = true;
  tex.minFilter = LinearMipmapLinearFilter;
  tex.magFilter = LinearFilter;
  tex.anisotropy = Math.min(lite ? 2 : 8, ctx.renderer.capabilities.getMaxAnisotropy());

  const model = buildModel(makeGuide(tex.image as CanvasImageSource, 256), lite);
  const atlasCanvas = buildAtlas(lite ? 64 : 128);
  const atlas = atlasCanvas ? new CanvasTexture(atlasCanvas) : null;

  const root = new Group();
  root.name = "milky-way";
  root.matrixAutoUpdate = false;
  root.matrix.copy(galaxyMatrix());
  root.visible = false;

  const disposables: { dispose(): void }[] = [tex];
  if (atlas) { disposables.push(atlas); }
  const faders: { mat: ShaderMaterial; gain: number }[] = [];
  const common = { depthTest: false, depthWrite: false, transparent: true, side: DoubleSide };
  // Color blends that leave the canvas alpha alone (WWT's page composite must not change).
  const screen = {
    blending: CustomBlending, blendEquation: AddEquation, blendSrc: OneFactor, blendDst: OneMinusSrcColorFactor,
    blendSrcAlpha: ZeroFactor, blendDstAlpha: OneFactor,
  };
  const darken = {
    blending: CustomBlending, blendEquation: AddEquation, blendSrc: ZeroFactor, blendDst: OneMinusSrcAlphaFactor,
    blendSrcAlpha: ZeroFactor, blendDstAlpha: OneFactor,
  };
  function add<T extends Mesh | Points | LineSegments>(obj: T, order: number, gain: number): T {
    obj.frustumCulled = false; // positions are displaced in the shader / span 1e10 au
    obj.renderOrder = order;   // negative: under every other layer in the scene
    root.add(obj);
    disposables.push(obj.geometry, obj.material as Material);
    if (gain > 0) { faders.push({ mat: obj.material as ShaderMaterial, gain }); }
    return obj;
  }

  // Slices (mid-plane quad + volume stack).
  add(new Mesh(buildSlices(lite), new ShaderMaterial({
    ...common, ...screen,
    uniforms: {
      uTex: { value: tex }, uOpacity: { value: 0 },
      uNearBase: { value: new Vector2(6.0e7, 6.0e8) },
      uNearSlice: { value: new Vector2(6.0e8, 2.0e9) },
    },
    vertexShader: SLICE_VERT, fragmentShader: SLICE_FRAG,
  })), -40, exposure);

  // Stars under the dust, so the lanes carve them.
  const starGeom = new BufferGeometry();
  starGeom.setAttribute("position", new Float32BufferAttribute(model.stars.pos, 3));
  starGeom.setAttribute("aColor", new Float32BufferAttribute(model.stars.color, 4));
  const starMat = new ShaderMaterial({
    ...common, ...screen,
    uniforms: { uSize: { value: 1.4 * ctx.dpr }, uOpacity: { value: 0 } },
    vertexShader: STAR_VERT, fragmentShader: STAR_FRAG,
  });
  add(new Points(starGeom, starMat), -39, 0);

  if (atlas) {
    const spriteUniforms = (): Record<string, { value: unknown }> => ({
      uAtlasTex: { value: atlas }, uOpacity: { value: 0 }, uKpcAu: { value: AU_PER_KPC },
      uNear: { value: new Vector2(3.0e8, 1.2e9) }, uAtlas: { value: new Vector2(ATLAS_COLS, ATLAS_ROWS) },
    });
    add(new Mesh(buildSpriteGeometry(model.dust), new ShaderMaterial({
      ...common, ...darken, uniforms: spriteUniforms(), vertexShader: SPRITE_VERT, fragmentShader: SPRITE_FRAG,
    })), -38, 1);
    add(new Mesh(buildSpriteGeometry(model.glow), new ShaderMaterial({
      ...common, ...screen, uniforms: spriteUniforms(), vertexShader: SPRITE_VERT, fragmentShader: SPRITE_FRAG,
    })), -37, exposure);
  }

  // "You are here": the Sun, 8.178 kpc out and 20.8 pc above the mid-plane.
  const markGeom = new BufferGeometry();
  markGeom.setAttribute("position", new Float32BufferAttribute([-R0_KPC, 0, Z_SUN_KPC], 3));
  const markMat = new ShaderMaterial({
    ...common, blending: NormalBlending,
    uniforms: { uSize: { value: 46 * ctx.dpr }, uOpacity: { value: 0 }, uPulse: { value: 0 } },
    vertexShader: MARK_VERT, fragmentShader: MARK_FRAG,
  });
  add(new Points(markGeom, markMat), -30, 0);

  let debug: LineSegments | null = null;
  function setDebugArms(on: boolean): void {
    if (on && !debug) {
      debug = add(new LineSegments(buildDebugArms(), new ShaderMaterial({
        depthTest: false, depthWrite: false, transparent: true, vertexShader: LINE_VERT, fragmentShader: LINE_FRAG,
      })), -29, 0);
    }
    if (debug) { debug.visible = on; }
  }
  if (params.has("gxarms")) { setDebugArms(true); }

  ctx.world.add(root);

  // ── labels ──
  const m = root.matrix;
  const toScene = (x: number, y: number, z: number): [number, number, number] => {
    const v = new Vector3(x, y, z).applyMatrix4(m);
    return [v.x, v.y, v.z];
  };
  const labelList: GalaxyLabel[] = [
    {
      id: "gx-sun", label: "You are here", sub: "The Sun, 26,700 light-years from the center", kind: "sun",
      position: [0, 0, 0], minViewRAu: 3e7, maxViewRAu: Infinity,
    },
    {
      id: "gx-center", label: "Center of the Milky Way", sub: "Sagittarius A*", kind: "center",
      position: toScene(0, 0, 0), minViewRAu: 3e8, maxViewRAu: Infinity,
    },
    ...ARMS.map((arm): GalaxyLabel => {
      const [x, y] = armPoint(arm, arm.labelBetaDeg);
      return {
        id: `gx-arm-${arm.id}`, label: arm.name, kind: "arm",
        position: toScene(x, y, warpZ(x, y)), minViewRAu: 1e9, maxViewRAu: 2e10,
      };
    }),
  ];

  let wanted = true;
  let fade = 0;
  let disposed = false;

  return {
    tier: lite ? "lite" : "full",
    update(frame: GalaxyFrame): void {
      if (disposed) { return; }
      const r = Math.max(1, frame.viewRAu);
      fade = smoothstep(Math.log10(FADE_START_AU), Math.log10(FADE_FULL_AU), Math.log10(r));
      const on = wanted && fade > 0.002;
      root.visible = on;
      if (!on) { return; }
      for (const f of faders) { f.mat.uniforms.uOpacity.value = fade * f.gain; }
      // Fixed-size points pile up as the Galaxy shrinks on screen: thin them out.
      starMat.uniforms.uOpacity.value = fade * 0.75 * Math.min(1, Math.pow(4e9 / r, 1.5));
      // The ring only means something once the Sun is a dot in the disk.
      markMat.uniforms.uOpacity.value = smoothstep(7.3, 8.3, Math.log10(r));
      markMat.uniforms.uPulse.value = (performance.now() % 2400) / 2400;
    },
    setVisible(visible: boolean): void {
      wanted = visible;
      if (!visible) { root.visible = false; }
    },
    dispose(): void {
      if (disposed) { return; }
      disposed = true;
      root.removeFromParent();
      for (const d of disposables) { d.dispose(); }
    },
    labels: () => labelList.map((l) => ({ ...l, position: [...l.position] as [number, number, number] })),
    opacity: () => (wanted ? fade : 0),
    setDebugArms,
  };
}
