// Far-field "moments" from chapter 5 (no WWT imports, sol footgun 12):
//   * the Golden Record pulsar map in 3D (public/data/pulsars.json: 14 pulsars
//     identified by W. R. Johnston, current ATNF v2.9.0 distances, ecliptic AU)
//   * Voyager 1's future flyby of Gliese 445 (public/data/flybys.json: straight-
//     line model from our Horizons asymptote + Gaia DR3; matches Bailer-Jones &
//     Farnocchia 2019 to 0.01 ly / 50 yr).
// Frame: heliocentric ecliptic J2000 AU, added under VoyagerView3D's world group.

import {
  AdditiveBlending, BufferGeometry, Float32BufferAttribute, Group, LineBasicMaterial, LineDashedMaterial,
  LineSegments, Line, Vector3,
} from "three";

type V3 = [number, number, number];

// ── pulsar map ───────────────────────────────────────────────────────
export interface PulsarRec { bname: string; jname: string; gl: number; dist_kpc: number; xyz_au: V3 } // eslint-disable-line @typescript-eslint/naming-convention
export interface PulsarData { pulsars: PulsarRec[]; galactic_centre: { xyz_au: V3; dist_kpc: number } } // eslint-disable-line @typescript-eslint/naming-convention

export interface PulsarMap { group: Group; data: PulsarData; setOpacity(a: number): void }

export async function createPulsarMap(base: string): Promise<PulsarMap> {
  const data = (await (await fetch(base + "pulsars.json")).json()) as PulsarData;
  const pos: number[] = [];
  for (const p of data.pulsars) { pos.push(0, 0, 0, ...p.xyz_au); }
  const g = new BufferGeometry();
  g.setAttribute("position", new Float32BufferAttribute(pos, 3));
  const mat = new LineBasicMaterial({ color: 0xf2cf74, transparent: true, opacity: 0, depthTest: false, blending: AdditiveBlending });
  const rays = new LineSegments(g, mat);
  // The cover's long line to the Galactic center.
  const gcG = new BufferGeometry();
  gcG.setAttribute("position", new Float32BufferAttribute([0, 0, 0, ...data.galactic_centre.xyz_au], 3));
  const gcMat = new LineBasicMaterial({ color: 0xffe9b0, transparent: true, opacity: 0, depthTest: false, blending: AdditiveBlending });
  const gc = new LineSegments(gcG, gcMat);
  const group = new Group();
  for (const o of [rays, gc]) { o.frustumCulled = false; o.renderOrder = 30; group.add(o); }
  group.visible = false;
  return {
    group, data,
    setOpacity(a: number) { mat.opacity = a; gcMat.opacity = 0.8 * a; group.visible = a > 0.001; },
  };
}

// ── flyby ────────────────────────────────────────────────────────────
interface FlybyBody { id: string; name: string; r0_au: V3; v_au_per_yr: V3 } // eslint-disable-line @typescript-eslint/naming-convention
interface Encounter { craft: string; star: string; t_years: number; year_ce?: number; min_dist_ly: number; source: string } // eslint-disable-line @typescript-eslint/naming-convention
export interface FlybyData { epoch: string; bodies: FlybyBody[]; encounters: Encounter[] }

export interface Flyby {
  group: Group;
  data: FlybyData;
  craft: FlybyBody;
  star: FlybyBody;
  encounter: Encounter;
  /** Positions at `years` after the epoch (2026-11-11). */
  at(years: number): { craft: V3; star: V3 };
  setOpacity(a: number): void;
}

const SPAN_YEARS = 60000;

export async function createFlyby(base: string): Promise<Flyby> {
  const data = (await (await fetch(base + "flybys.json")).json()) as FlybyData;
  const craft = data.bodies.find((b) => b.id === "voyager1")!;
  const star = data.bodies.find((b) => b.id === "gliese445")!;
  // Our own straight-line encounter (the pipeline's; Bailer-Jones & Farnocchia agree).
  const encounter = data.encounters.find((e) => e.craft === "voyager1" && e.star === "Gliese 445"
    && e.source.startsWith("this pipeline"))!;
  const at = (y: number) => ({
    craft: craft.r0_au.map((r, k) => r + craft.v_au_per_yr[k] * y) as V3,
    star: star.r0_au.map((r, k) => r + star.v_au_per_yr[k] * y) as V3,
  });
  const path = (b: FlybyBody, color: number) => {
    const g = new BufferGeometry().setFromPoints([
      new Vector3(...b.r0_au), new Vector3(...b.r0_au.map((r, k) => r + b.v_au_per_yr[k] * SPAN_YEARS) as V3),
    ]);
    const m = new LineDashedMaterial({ color, dashSize: 25000, gapSize: 18000, transparent: true, opacity: 0, depthTest: false });
    const l = new Line(g, m);
    l.computeLineDistances();
    l.frustumCulled = false;
    l.renderOrder = 30;
    return { l, m };
  };
  const pc = path(craft, 0xe69f00), ps = path(star, 0xff8a7a);
  const group = new Group();
  group.add(pc.l, ps.l);
  group.visible = false;
  return {
    group, data, craft, star, encounter, at,
    setOpacity(a: number) { pc.m.opacity = 0.8 * a; ps.m.opacity = 0.8 * a; group.visible = a > 0.001; },
  };
}

export const FLYBY_SPAN_YEARS = SPAN_YEARS;
