// Voyager 1 "Family Portrait" (1990-02-14) aligned in 3D. Data: public/data/pbd/
// family.json from pipeline/family.py (docs/RESEARCH-pbd.md §5).
//
// Two kinds of panel, both exact from Voyager 1's 1990 position:
//   * planet frames (PIA00453 crops): flat panels perpendicular to each frame's
//     boresight, at the planet's depth, sized to the frame FOV; each planet
//     reprojects onto its pixel (< 0.01 px in the pipeline).
//   * wide-angle panels: PIA00450 (Sun, Earth, Venus; fits the sky to 0.002 deg)
//     and the PIA00451 60-frame mosaic (a hand-assembled mosaic; a flat plane fits
//     it to 0.36 deg rms, so it is a backdrop, not a measurement). Corners come
//     as directions on the unit plane; placed at v1 + D * corner.
// Mercury (too near the Sun), Mars (lost in scattered light) and Pluto (too dim)
// were not imaged. No WWT imports (sol footgun 12).

import {
  AdditiveBlending, BufferGeometry, DoubleSide, Float32BufferAttribute, Group, Matrix4, Mesh, MeshBasicMaterial, PlaneGeometry,
  SRGBColorSpace, Texture, TextureLoader, Vector3,
} from "three";

type V3 = [number, number, number];

/* eslint-disable @typescript-eslint/naming-convention -- pipeline JSON keys */
export interface FamilyFrame {
  planet: string; image: string; fov_deg_x: number; fov_deg_y: number;
  center_dir_ecl: V3; up_ecl: V3; right_ecl: V3; v1_au: V3; planet_au: V3;
}
interface WidePanel { image: string; corners_on_unit_plane: V3[] }
export interface FamilyData {
  frames: FamilyFrame[]; mosaic: WidePanel; sun_earth_venus: WidePanel; v1_au: V3;
  not_imaged: Record<string, string>; credit: string;
}
/* eslint-enable @typescript-eslint/naming-convention */

export interface FamilyPortrait {
  group: Group;
  data: FamilyData;
  /** Half-height (au) of each planet frame panel, for camera framing. */
  frameHalfHeight: Record<string, number>;
  setOpacity(wide: number, frames: number): void;
}

function mat(tex: Texture): MeshBasicMaterial {
  return new MeshBasicMaterial({ map: tex, transparent: true, opacity: 0, depthWrite: false, depthTest: false, side: DoubleSide });
}

export async function createFamilyPortrait(base: string): Promise<FamilyPortrait> {
  const data = (await (await fetch(base + "pbd/family.json")).json()) as FamilyData;
  const loader = new TextureLoader();
  const load = async (p: string) => {
    const t = await loader.loadAsync(base + p);
    t.colorSpace = SRGBColorSpace;
    return t;
  };
  const group = new Group();
  const v1 = new Vector3(...data.v1_au);
  const wideMats: MeshBasicMaterial[] = [];
  const frameMats: MeshBasicMaterial[] = [];
  const frameHalfHeight: Record<string, number> = {};

  // Wide panels: corners TL, TR, BR, BL (checked against right/up in the JSON).
  const wide = async (p: WidePanel, d: number, order: number) => {
    const c = p.corners_on_unit_plane.map((k) => v1.clone().addScaledVector(new Vector3(...k), d));
    const g = new BufferGeometry();
    g.setAttribute("position", new Float32BufferAttribute([
      ...c[0].toArray(), ...c[1].toArray(), ...c[2].toArray(), ...c[3].toArray()], 3));
    g.setAttribute("uv", new Float32BufferAttribute([0, 1, 1, 1, 1, 0, 0, 0], 2));
    g.setIndex([0, 3, 1, 1, 3, 2]);
    const m = mat(await load(p.image));
    // Additive: the mosaic's black background becomes transparent, so the real
    // sky shows between the frames instead of a dark slab.
    m.blending = AdditiveBlending;
    wideMats.push(m);
    const mesh = new Mesh(g, m);
    mesh.renderOrder = order;
    mesh.frustumCulled = false;
    group.add(mesh);
  };
  // Behind everything at 60 au; the precise Sun-Earth-Venus panel in front at 45 au.
  await wide(data.mosaic, 60, 18);
  await wide(data.sun_earth_venus, 45, 19);

  for (const f of data.frames) {
    const c = new Vector3(...f.center_dir_ecl).normalize();
    const up = new Vector3(...f.up_ecl).normalize();
    const right = new Vector3(...f.right_ecl).normalize();
    const depth = new Vector3(...f.planet_au).sub(v1).dot(c);
    const w = 2 * depth * Math.tan(((f.fov_deg_x / 2) * Math.PI) / 180);
    const h = 2 * depth * Math.tan(((f.fov_deg_y / 2) * Math.PI) / 180);
    frameHalfHeight[f.planet] = h / 2;
    const m = mat(await load(f.image));
    frameMats.push(m);
    const mesh = new Mesh(new PlaneGeometry(w, h), m);
    mesh.quaternion.setFromRotationMatrix(new Matrix4().makeBasis(right, up, c.clone().negate()));
    mesh.position.copy(v1.clone().addScaledVector(c, depth));
    mesh.renderOrder = 22;
    mesh.frustumCulled = false;
    group.add(mesh);
  }
  group.visible = false;
  return {
    group, data, frameHalfHeight,
    setOpacity(a: number, b: number) {
      for (const m of wideMats) { m.opacity = a; }
      for (const m of frameMats) { m.opacity = b; }
      group.visible = a > 0.001 || b > 0.001;
    },
  };
}
