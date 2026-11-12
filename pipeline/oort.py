"""Synthetic Oort cloud point cloud -> data/oort.bin (+ models/oort.glb, POINTS)

PREDICTED, not observed. No simulation particle output is public (checked
2026-11-11), so this is a seeded, honest stand-in built from published shapes:

  * Outer cloud, 10,000-100,000 au, isotropic, n(r) ~ r^-3.5 (Duncan, Quinn &
    Tremaine 1987 lore; NASA: outer edge 10k-100k au).
  * Inner (Hills) cloud, 1,000-10,000 au, flattened into the plane of the
    simulated two-armed spiral (Nesvorny et al. 2025, ApJ 983, 74): a disk
    inclined ~30 deg to the ecliptic, nearly perpendicular to the Galactic
    plane, with its long axis along the ecliptic/Galactic node.

Binary layout: float32 little-endian, n x 4 = (x, y, z, kind) in ecliptic
J2000 au; kind 0 = outer cloud, 1 = inner cloud diffuse, 2 = inner spiral arm.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .glb import GLB, srgb_to_linear
from .tidal import galactic_axes_in_ecliptic

SEED = 19770905  # Voyager 1 launch date


def run(out: Path) -> dict:
    rng = np.random.default_rng(SEED)
    Xg, _Yg, Zg = galactic_axes_in_ecliptic()
    ecl_n = np.array([0.0, 0.0, 1.0])
    node = np.cross(ecl_n, Zg); node /= np.linalg.norm(node)          # ecliptic ∩ galactic plane
    disk_n = np.cross(node, Zg); disk_n /= np.linalg.norm(disk_n)     # plane ⟂ galactic, contains node
    e1, e2 = node, np.cross(disk_n, node)
    inc = np.degrees(np.arccos(abs(disk_n @ ecl_n)))
    print("  inner-cloud plane inclination to ecliptic: {0:.1f} deg".format(inc))

    # outer, isotropic, p(r) ~ r^-1.5 on [1e4, 1e5]
    n_out = 16000
    r1, r2 = 1e4, 1e5
    u = rng.random(n_out)
    r = (r1 ** -0.5 + u * (r2 ** -0.5 - r1 ** -0.5)) ** -2
    v = rng.normal(size=(n_out, 3)); v /= np.linalg.norm(v, axis=1, keepdims=True)
    outer = v * r[:, None]

    # inner diffuse disk
    n_in = 5000
    ri = np.exp(rng.uniform(np.log(1e3), np.log(1.2e4), n_in))
    th = rng.uniform(0, 2 * np.pi, n_in)
    h = rng.normal(scale=0.28, size=n_in) * ri
    inner = (ri * np.cos(th))[:, None] * e1 + (ri * np.sin(th))[:, None] * e2 + h[:, None] * disk_n

    # two-armed spiral, ~15,000 au along its length
    n_arm = 4000
    s = rng.uniform(0, 1, n_arm)
    ra = 1.5e3 + s * 8.5e3
    arm = rng.integers(0, 2, n_arm)
    ta = arm * np.pi + 2.2 * np.log(ra / 1.5e3) + rng.normal(scale=0.16, size=n_arm)
    ha = rng.normal(scale=0.08, size=n_arm) * ra
    spiral = (ra * np.cos(ta))[:, None] * e1 + (ra * np.sin(ta))[:, None] * e2 + ha[:, None] * disk_n

    pts = np.vstack([outer, inner, spiral])
    kind = np.concatenate([np.zeros(n_out), np.ones(n_in), np.full(n_arm, 2.0)])
    arr = np.hstack([pts, kind[:, None]]).astype("<f4")
    (out / "oort.bin").write_bytes(arr.tobytes())

    glb = GLB()
    cols = {0: [0.70, 0.85, 1.0], 1: [0.80, 0.90, 1.0], 2: [1.0, 0.95, 0.80]}
    col = np.array([cols[int(k)] for k in kind])
    rgba = np.hstack([srgb_to_linear(col), np.full((len(col), 1), 0.8)])
    glb.add_mesh("oort_cloud", pts, color=rgba, points=True, material="oort",
                 extras={"tier": "PREDICTED (synthetic; shapes from published simulations)"})
    d = out / "models"; d.mkdir(parents=True, exist_ok=True)
    nb = glb.save(d / "oort.glb", root_extras={"frame": "heliocentric ecliptic J2000", "units": "au",
                                               "seed": SEED,
                                               "sources": ["Nesvorny+ 2025 ApJ 983 74", "Vokrouhlicky+ 2019 AJ 157 181",
                                                           "Kaib & Volk 2022 review arXiv:2206.00010"]})
    meta = {"count": int(len(pts)), "outer": n_out, "inner": n_in, "spiral": n_arm,
            "inner_plane_normal": disk_n.tolist(), "inner_plane_inclination_deg": float(inc)}
    (out / "oort.json").write_text(json.dumps(meta, indent=1))
    print("  oort.bin {0:.0f} KB, oort.glb {1:.0f} KB".format(arr.nbytes / 1024, nb / 1024))
    return meta
