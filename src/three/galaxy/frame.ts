// =====================================================================
// Milky Way frame: galactocentric kpc -> heliocentric ecliptic J2000 au
// =====================================================================
// Everything in the galaxy layer is authored in GALACTOCENTRIC kpc:
//   +x = the Sun -> Galactic centre direction (l = 0, b = 0)
//   +y = the direction of Galactic rotation at the Sun (l = 90)
//   +z = the North Galactic Pole
// with the Galactic centre at the origin and the mid-plane at z = 0. The Sun
// therefore sits at (-R0, 0, +Z_SUN). Seen from +z (north) the Galaxy turns
// CLOCKWISE: the Sun moves toward +y.
//
// One matrix (galaxyMatrix) takes that frame to the scene frame, heliocentric
// ecliptic J2000 in au, so nothing else in the folder does frame maths.
//
// Sources (docs/RESEARCH-galaxy.md):
//   R0     8.178 kpc  GRAVITY Collaboration 2019, A&A 625, L10
//   Z_SUN  20.8 pc    Bennett & Bovy 2019, MNRAS 482, 1417
//   axes   astropy Galactic -> BarycentricMeanEcliptic(J2000), as given in the
//          integration contract (index.ts)
// The 0.15 deg tilt between "b = 0 as seen from the Sun" and the true
// mid-plane (atan(Z_SUN / R0)) is ignored: it moves the far edge by ~50 pc.
//
// No WWT imports (sol footgun 12).

import { Matrix4, Vector3 } from "three";

export const AU_PER_PC = 206264.806;
export const AU_PER_KPC = AU_PER_PC * 1000;
/** Sun to Galactic-centre distance, kpc (GRAVITY 2019). */
export const R0_KPC = 8.178;
/** Height of the Sun above the Galactic mid-plane, kpc (Bennett & Bovy 2019). */
export const Z_SUN_KPC = 0.0208;

/** Galactic axes as unit vectors in ecliptic J2000 (see index.ts). */
export const GAL_X_ECL: readonly [number, number, number] = [-0.05488, -0.99382, -0.09648];
export const GAL_Y_ECL: readonly [number, number, number] = [0.49411, -0.11099, 0.86229];
export const GAL_Z_ECL: readonly [number, number, number] = [-0.86767, -0.00035, 0.49715];

/**
 * Side of the square face-on texture, kpc. The image is a view from the North
 * Galactic Pole with the Galactic centre in the middle, the Sun below it and
 * l = 90 to the LEFT; the half-width is 2.4 R0 (the scale JWST's Galaxy3D used,
 * and the one at which the Reid et al. 2019 arm fits land on the painted arms).
 */
export const TEX_SIDE_KPC = 4.8 * R0_KPC;

/** Galactocentric kpc -> scene (heliocentric ecliptic J2000, au). */
export function galaxyMatrix(): Matrix4 {
  // Re-orthonormalise the 5-digit axes so the matrix is a clean rotation.
  const x = new Vector3(...GAL_X_ECL).normalize();
  const z = new Vector3(...GAL_Z_ECL);
  z.addScaledVector(x, -z.dot(x)).normalize();
  const y = new Vector3().crossVectors(z, x); // right-handed: z cross x = y
  const check = y.dot(new Vector3(...GAL_Y_ECL));
  if (check < 0.9999) {
    console.warn("[galaxy] Galactic axes are not a right-handed orthonormal set; y.l90 =", check);
  }
  const s = AU_PER_KPC;
  // Galactic centre in the scene: R0 along +x, and the mid-plane Z_SUN below the Sun.
  const o = new Vector3().addScaledVector(x, R0_KPC * s).addScaledVector(z, -Z_SUN_KPC * s);
  return new Matrix4().set(
    x.x * s, y.x * s, z.x * s, o.x,
    x.y * s, y.y * s, z.y * s, o.y,
    x.z * s, y.z * s, z.z * s, o.z,
    0, 0, 0, 1,
  );
}

/** Texture uv (three.js convention, v up) for a galactocentric point. */
export function texUV(xKpc: number, yKpc: number): [number, number] {
  return [0.5 - yKpc / TEX_SIDE_KPC, 0.5 + xKpc / TEX_SIDE_KPC];
}

// ── Warp and flare ───────────────────────────────────────────────────
// Illustrative, sized to the Cepheid maps (Chen et al. 2019, Nat. Astron. 3,
// 320; Skowron et al. 2019, Science 365, 478): the disk starts to bend near
// R ~ 9 kpc and is ~1 kpc off the plane by R ~ 16 kpc, up (north) on the
// l ~ 90 side and down on the l ~ 270 side, with the Sun close to the line of
// nodes. The flare roughly doubles the scale height between 6 and 15 kpc.
const WARP_START_KPC = 9.0;
const WARP_COEF = 0.055;
const WARP_POWER = 1.5;

/** Mid-plane height (kpc) of the warped disk at galactocentric (x, y). */
export function warpZ(xKpc: number, yKpc: number): number {
  const r = Math.hypot(xKpc, yKpc);
  if (r <= WARP_START_KPC) { return 0; }
  return WARP_COEF * Math.pow(r - WARP_START_KPC, WARP_POWER) * (yKpc / r);
}

/** Disk scale-height multiplier at radius r (kpc). */
export function flare(rKpc: number): number {
  return rKpc <= 6 ? 1 : 1 + (rKpc - 6) * 0.125;
}
