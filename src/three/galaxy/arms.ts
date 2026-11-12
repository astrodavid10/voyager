// =====================================================================
// Spiral arms: Reid et al. 2019 maser-parallax fits
// =====================================================================
// Reid, M. J., et al. 2019, ApJ 885, 131, Table 2 ("Spiral Arm
// Characteristics"). Each arm is a log spiral with one "kink":
//
//     ln(R / Rkink) = -(beta - betaKink) * tan(psi)
//
// beta is Galactocentric azimuth, 0 toward the Sun and increasing in the
// direction of Galactic rotation; psi is the pitch angle, psi< for
// beta < betaKink and psi> beyond it. R decreases as beta grows: the arms
// TRAIL. The fits only cover the azimuth range where masers were measured
// (betaMin..betaMax); nothing here extrapolates an arm around the far side,
// where the arm pattern is still not measured. The far side of the disk is
// carried by the texture (an artist's impression) instead.
//
// Reid et al. fit with R0 = 8.15 kpc. The radii are scaled by R0/8.15 so the
// arms keep their measured place relative to the Sun at our R0 (8.178 kpc).
//
// Frame: galactocentric kpc, as in frame.ts. A point at (R, beta) is
// (-R cos beta, R sin beta).

import { R0_KPC } from "./frame";

export interface ArmDef {
  id: string;
  name: string;
  betaMinDeg: number;
  betaMaxDeg: number;
  betaKinkDeg: number;
  rKinkKpc: number;
  psiLtDeg: number;
  psiGtDeg: number;
  /** Intrinsic (Gaussian 1 sigma) arm width, kpc. */
  widthKpc: number;
  /** Relative weight when scattering knots (rough arm prominence). */
  weight: number;
  /** Azimuth at which to hang the arm's label, degrees. */
  labelBetaDeg: number;
}

const SCALE = R0_KPC / 8.15;

export const ARMS: ArmDef[] = [
  { id: "norma", name: "Norma Arm", betaMinDeg: 5, betaMaxDeg: 54, betaKinkDeg: 18, rKinkKpc: 4.46, psiLtDeg: -1.0, psiGtDeg: 19.5, widthKpc: 0.14, weight: 0.5, labelBetaDeg: 44 },
  { id: "sctcen", name: "Scutum–Centaurus Arm", betaMinDeg: 0, betaMaxDeg: 104, betaKinkDeg: 23, rKinkKpc: 4.91, psiLtDeg: 14.1, psiGtDeg: 12.1, widthKpc: 0.23, weight: 1.0, labelBetaDeg: 75 },
  { id: "sgrcar", name: "Sagittarius–Carina Arm", betaMinDeg: 2, betaMaxDeg: 97, betaKinkDeg: 24, rKinkKpc: 6.04, psiLtDeg: 17.1, psiGtDeg: 1.0, widthKpc: 0.27, weight: 0.8, labelBetaDeg: 60 },
  { id: "local", name: "Local (Orion) Arm", betaMinDeg: -8, betaMaxDeg: 34, betaKinkDeg: 9, rKinkKpc: 8.26, psiLtDeg: 11.4, psiGtDeg: 11.4, widthKpc: 0.31, weight: 0.5, labelBetaDeg: 28 },
  { id: "perseus", name: "Perseus Arm", betaMinDeg: -23, betaMaxDeg: 115, betaKinkDeg: 40, rKinkKpc: 8.87, psiLtDeg: 10.3, psiGtDeg: 8.7, widthKpc: 0.35, weight: 1.0, labelBetaDeg: 70 },
  { id: "outer", name: "Outer Arm", betaMinDeg: -16, betaMaxDeg: 71, betaKinkDeg: 18, rKinkKpc: 12.24, psiLtDeg: 3.0, psiGtDeg: 9.4, widthKpc: 0.65, weight: 0.5, labelBetaDeg: 55 },
];

const RAD = Math.PI / 180;

/** Galactocentric radius (kpc) of an arm's ridge at azimuth beta (deg). */
export function armRadius(arm: ArmDef, betaDeg: number): number {
  const psi = betaDeg < arm.betaKinkDeg ? arm.psiLtDeg : arm.psiGtDeg;
  return SCALE * arm.rKinkKpc * Math.exp(-(betaDeg - arm.betaKinkDeg) * RAD * Math.tan(psi * RAD));
}

/** Galactocentric (x, y) kpc of an arm's ridge at azimuth beta (deg), offset dR kpc in radius. */
export function armPoint(arm: ArmDef, betaDeg: number, dR = 0): [number, number] {
  const r = armRadius(arm, betaDeg) + dR;
  return [-r * Math.cos(betaDeg * RAD), r * Math.sin(betaDeg * RAD)];
}

// ── Bar ──────────────────────────────────────────────────────────────
// Long bar: half-length ~5 kpc, ~27 deg from the Sun-centre line with the
// NEAR end at positive longitude (Wegg, Gerhard & Portail 2015, MNRAS 450,
// 4050). In this frame the near end points along (-cos 27, +sin 27).
export const BAR_ANGLE_RAD = 27 * RAD;
export const BAR_HALF_LEN_KPC = 5.0;
export const BAR_HALF_WID_KPC = 1.0;
