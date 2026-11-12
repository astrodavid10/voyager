"""The Sun's tidal (Jacobi) region in the Galactic tide -> models/tidal.glb

Hill approximation in a frame co-rotating with the Galaxy (x toward the
Galactic center, y along rotation, z toward the North Galactic Pole):

    Phi_eff = -GM/r - 2 A Omega x^2 + 1/2 nu^2 z^2,   Omega = A - B,
    nu^2 = 4 pi G rho0 + 2 (B^2 - A^2)                (Veras & Evans 2013, eq. 10)

r_t = (GM / 4 A Omega)^(1/3); L1/L2 at x = +-r_t; the critical (zero-velocity)
surface has Jacobi energy Phi_L = -3/2 GM/r_t. In units of r_t with GM = 1:

    F(r) = 1/r + 1/2 nx^2 r^2 - 1/2 q nz^2 r^2 - 3/2 = 0,   q = nu^2 / (4 A Omega)

smallest root in (0, 1] per direction n. Shape: 1 : 2/3 : ~0.52 (x : y : z),
a "lemon" pinched to points at L1/L2. Values: A = 15.3, B = -11.9 km/s/kpc
(Bovy 2017); rho0 = 0.097 Msun/pc^3 (McKee+ 2015). r_t = 1.373 pc = 283k au.

Caveat for the narrative: this surface marks where escape becomes energetically
POSSIBLE; long-term stable orbits lie well inside it (~0.5-1 pc, Heisler &
Tremaine 1986). It is drawn as a soft, fuzzy zone, not a wall.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from scipy.optimize import brentq

from .glb import GLB, grid_faces, srgb_to_linear, vertex_normals

G = 4.30091e-3          # pc (km/s)^2 / Msun
M = 1.0013              # Sun + planets
A, B = 15.3e-3, -11.9e-3  # km/s/pc
RHO0 = 0.097
PC_AU = 206264.806


def galactic_axes_in_ecliptic():
    import astropy.units as u
    from astropy.coordinates import BarycentricMeanEcliptic, SkyCoord
    def ax(l, b):
        c = SkyCoord(l=l * u.deg, b=b * u.deg, frame="galactic").transform_to(BarycentricMeanEcliptic(equinox="J2000"))
        return np.array(c.cartesian.xyz.value, dtype=float)
    X, Y, Z = ax(0, 0), ax(90, 0), ax(0, 90)
    return X, Y, Z


def run(out: Path) -> dict:
    omega = A - B
    rt_pc = (G * M / (4 * A * omega)) ** (1 / 3)
    nu2 = 4 * np.pi * G * RHO0 + 2 * (B * B - A * A)
    q = nu2 / (4 * A * omega)
    rt_au = rt_pc * PC_AU
    print("  r_t = {0:.3f} pc = {1:,.0f} au, q = {2:.3f}".format(rt_pc, rt_au, q))

    n_lat, n_lon = 73, 128
    lat = np.linspace(-np.pi / 2, np.pi / 2, n_lat)
    lon = np.linspace(0, 2 * np.pi, n_lon, endpoint=False)
    LA, LO = np.meshgrid(lat, lon, indexing="ij")
    n = np.stack([np.cos(LA) * np.cos(LO), np.cos(LA) * np.sin(LO), np.sin(LA)], -1).reshape(-1, 3)
    r = np.empty(len(n))
    grid = np.linspace(0.02, 1.0, 400)
    for k, (nx, _ny, nz) in enumerate(n):
        f = lambda rr: 1 / rr + 0.5 * nx * nx * rr * rr - 0.5 * q * nz * nz * rr * rr - 1.5  # noqa: E731
        vals = f(grid)
        idx = np.nonzero(vals <= 0)[0]
        if len(idx) == 0 or idx[0] == 0:
            r[k] = 1.0
        else:
            i = idx[0]
            r[k] = brentq(f, grid[i - 1], grid[i]) if vals[i] < 0 else grid[i]
    X, Y, Z = galactic_axes_in_ecliptic()
    Mrot = np.stack([X, Y, Z], 1)               # columns: galactic axes in ecliptic
    pts_gal = n * r[:, None] * rt_au
    pts = pts_gal @ Mrot.T
    axes = [float(np.abs(pts_gal[:, i]).max() / PC_AU) for i in range(3)]
    print("  semi-axes (pc): x {0:.3f}  y {1:.3f}  z {2:.3f}".format(*axes))

    faces = grid_faces(n_lat, n_lon)  # rows = lat rings, wrapped in lon
    normals = vertex_normals(pts, faces)
    glb = GLB()
    rgb = srgb_to_linear([0.55, 0.85, 1.0])
    # One shell; the viewer's rim shader makes it a soft, fuzzy edge, not a wall.
    col = np.hstack([np.tile(rgb, (len(pts), 1)), np.full((len(pts), 1), 0.30)])
    glb.add_mesh("tidal_edge", pts, faces, color=col, normals=normals, material="tidal",
                 extras={"tier": "PREDICTED (physics boundary, not an official edge)"})
    d = out / "models"
    d.mkdir(parents=True, exist_ok=True)
    nb = glb.save(d / "tidal.glb", root_extras={
        "frame": "heliocentric ecliptic J2000", "units": "au",
        "r_t_au": rt_au, "semi_axes_pc": axes, "q": q,
        "sources": ["Veras & Evans 2013 MNRAS (arXiv:1212.4150)", "Bovy 2017 MNRAS 468 L63",
                    "McKee, Parravano & Hollenbach 2015 ApJ 814 13", "Heisler & Tremaine 1986 Icarus 65 13"]})
    print("  tidal.glb {0:.0f} KB".format(nb / 1024))
    meta = {"r_t_au": rt_au, "semi_axes_au": [a * PC_AU for a in axes],
            "galactic_center_dir": X.tolist(), "ngp_dir": Z.tolist(), "rotation_dir": Y.tolist()}
    (d / "tidal.json").write_text(json.dumps(meta, indent=1))
    return meta
