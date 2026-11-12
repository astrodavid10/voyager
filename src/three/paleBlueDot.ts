// The Pale Blue Dot photo, placed in 3D exactly where Voyager 1's narrow-angle
// camera pointed on 1990-02-14 04:48 UTC (data: public/data/pbd/pbd.json from
// pipeline/pbd.py; docs/RESEARCH-pbd.md).
//
// The photo is a flat panel PERPENDICULAR to the camera's boresight, centered on
// the boresight and placed at Earth's depth (40.47 au from Voyager), sized to the
// camera's field (0.353 x 0.349 deg -> ~0.25 au across). Seen from Voyager's
// position, or from anywhere on the Voyager-Earth sightline, Earth sits exactly
// on its pixel in the photo (checked to < 1e-6 au in the pipeline).
//
// Basis: (right, up, -center) is right-handed (right x up = -center), so the
// panel faces Voyager and the texture is not mirrored. Camera roll is DERIVED
// from the Sun direction (no archived pointing exists; roll_method in the JSON).
// No WWT imports (sol footgun 12).

import {
  DoubleSide, EdgesGeometry, LineBasicMaterial, LineSegments, Matrix4, Mesh, MeshBasicMaterial, PlaneGeometry,
  SRGBColorSpace, TextureLoader, Vector3,
} from "three";

export type V3 = [number, number, number];

export interface PbdData {
  utc: string;
  image: string;
  fov_deg_x: number; // eslint-disable-line @typescript-eslint/naming-convention
  fov_deg_y: number; // eslint-disable-line @typescript-eslint/naming-convention
  v1_au: V3; // eslint-disable-line @typescript-eslint/naming-convention
  earth_au: V3; // eslint-disable-line @typescript-eslint/naming-convention
  center_dir_ecl: V3; // eslint-disable-line @typescript-eslint/naming-convention
  up_ecl: V3; // eslint-disable-line @typescript-eslint/naming-convention
  right_ecl: V3; // eslint-disable-line @typescript-eslint/naming-convention
  v1_earth_distance_km: number; // eslint-disable-line @typescript-eslint/naming-convention
  credit: string;
}

export interface PaleBlueDot {
  mesh: Mesh;
  data: PbdData;
  /** Panel half-height in au, for camera framing. */
  halfHeightAu: number;
  setOpacity(a: number): void;
  dispose(): void;
}

export async function createPaleBlueDot(base: string): Promise<PaleBlueDot> {
  const data = (await (await fetch(base + "pbd/pbd.json")).json()) as PbdData;
  const tex = await new TextureLoader().loadAsync(base + data.image);
  tex.colorSpace = SRGBColorSpace;

  const v1 = new Vector3(...data.v1_au);
  const earth = new Vector3(...data.earth_au);
  const c = new Vector3(...data.center_dir_ecl).normalize();
  const up = new Vector3(...data.up_ecl).normalize();
  const right = new Vector3(...data.right_ecl).normalize();
  const depth = earth.clone().sub(v1).dot(c);
  const w = 2 * depth * Math.tan(((data.fov_deg_x / 2) * Math.PI) / 180);
  const h = 2 * depth * Math.tan(((data.fov_deg_y / 2) * Math.PI) / 180);

  const mat = new MeshBasicMaterial({
    map: tex, transparent: true, opacity: 0, depthWrite: false, depthTest: false, side: DoubleSide,
  });
  const mesh = new Mesh(new PlaneGeometry(w, h), mat);
  const basis = new Matrix4().makeBasis(right, up, c.clone().negate());
  mesh.quaternion.setFromRotationMatrix(basis);
  mesh.position.copy(v1.clone().addScaledVector(c, depth));
  mesh.renderOrder = 20;
  mesh.frustumCulled = false;
  mesh.visible = false;
  // Thin frame so guests can see where the photo ends (it is mostly black).
  const edgeMat = new LineBasicMaterial({ color: 0xd8c08a, transparent: true, opacity: 0, depthTest: false });
  const edges = new LineSegments(new EdgesGeometry(mesh.geometry), edgeMat);
  edges.renderOrder = 21;
  edges.frustumCulled = false;
  mesh.add(edges);

  return {
    mesh, data, halfHeightAu: h / 2,
    setOpacity(a: number) { mat.opacity = a; edgeMat.opacity = 0.8 * a; mesh.visible = a > 0.001; },
    dispose() { mesh.geometry.dispose(); mat.dispose(); tex.dispose(); edges.geometry.dispose(); edgeMat.dispose(); },
  };
}
