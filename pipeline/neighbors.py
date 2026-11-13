"""The Sun's nearest stellar neighbors around its tidal edge -> neighbors.json

    python -m pipeline neighbors --out public/data

Heliocentric ecliptic J2000 positions (au) from ICRS RA/Dec + distance (SIMBAD /
Gaia DR3 parallaxes), plus each system's mass and its OWN tidal (Jacobi) radius in
the same Galactic tide as the Sun's (r_t scales as M^(1/3); pipeline/tidal.py).

Why these: they are the stars as close to the Sun as the Sun's own tidal edge
(283,000 au = 1.37 pc along its long axis, ~1 pc sideways). Alpha Centauri, at
1.35 pc, sits right at it. Passing stars are what actually stir the outer Oort
cloud (the smooth Galactic tide drawn by tidal.glb is the slow part).
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

PC_AU = 206264.806
LY_PER_PC = 3.26156
R_T_SUN_PC = 1.373          # pipeline/tidal.py with M = 1.0013

# name, RA deg, Dec deg (ICRS J2000), distance pc, system mass (Msun), label
STARS = [
    ("acen", "Alpha Centauri, the nearest stars", 219.9021, -60.8340, 1.3475, 2.11),  # A 1.08 + B 0.91 + Proxima 0.12
    ("barnard", "Barnard's Star", 269.4521, 4.6934, 1.8282, 0.16),
    ("luhman16", "Luhman 16, two brown dwarfs", 162.3288, -53.3194, 1.9960, 0.068),
    ("wolf359", "Wolf 359", 164.1205, 7.0147, 2.4086, 0.11),
    ("lalande", "Lalande 21185", 165.8341, 35.9699, 2.5469, 0.39),
    ("sirius", "Sirius", 101.2872, -16.7161, 2.6371, 3.08),          # A 2.06 + B 1.02
]


def run(out: Path) -> list:
    import astropy.units as u
    from astropy.coordinates import BarycentricMeanEcliptic, SkyCoord

    rows = []
    for sid, label, ra, dec, d_pc, mass in STARS:
        c = SkyCoord(ra=ra * u.deg, dec=dec * u.deg, distance=d_pc * u.pc, frame="icrs")
        e = c.transform_to(BarycentricMeanEcliptic(equinox="J2000"))
        xyz = np.array(e.cartesian.xyz.to(u.pc).value) * PC_AU
        g = c.galactic
        rows.append({
            "id": sid, "label": label, "dist_pc": d_pc, "dist_ly": round(d_pc * LY_PER_PC, 1),
            "mass_msun": mass, "xyz_au": [round(float(x), 1) for x in xyz],
            "ecl_lon_lat_deg": [round(float(e.lon.deg), 2), round(float(e.lat.deg), 2)],
            "gal_l_b_deg": [round(float(g.l.deg), 2), round(float(g.b.deg), 2)],
            "own_tidal_radius_pc": round(R_T_SUN_PC * (mass / 1.0013) ** (1 / 3), 3),
        })
        print("  {0:9s} {1:5.2f} pc  ecl {2}  gal {3}  r_t {4} pc".format(
            sid, d_pc, rows[-1]["ecl_lon_lat_deg"], rows[-1]["gal_l_b_deg"], rows[-1]["own_tidal_radius_pc"]))
    (out / "neighbors.json").write_text(json.dumps({
        "frame": "heliocentric ecliptic J2000", "units": "au", "stars": rows,
        "sources": ["SIMBAD (positions, distances from Gaia DR3 / Hipparcos parallaxes)",
                    "tidal radius scaling: Veras & Evans 2013"],
    }, indent=1))
    return rows
