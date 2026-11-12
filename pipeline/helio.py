"""Heliosphere surfaces -> public/data/models/heliosphere.glb

Geometry (docs/RESEARCH notes; PLAN.md "Research updates"):
  * Nose axis: interstellar gas arrives FROM ecliptic (255.7 deg, +5.1 deg)
    (McComas+ 2015 IBEX; Swaczyna+ 2023 agrees on direction).
  * Heliopause (HP): Rankine half-body r = q / cos(theta/2) (Parker 1961;
    Kleimann+ 2022 eq. 8-9), theta measured from the nose, scaled by a
    north/south factor (1 + a * dhat.zhat). q and a are SOLVED so the surface
    passes exactly through both Voyager crossings: V1 121.60 au (2012-08-25)
    and V2 119.02 au (2018-11-05), positions from our own Horizons bake.
  * Termination shock (TS): prolate r = r0 * (1 + k (1 - cos theta)/2) times
    the same kind of N/S factor, solved through V1 94.02 au (2004-12-16) and
    V2 83.67 au (2007-08-31). k = 1 (tail-side ~2x nose, Kleimann 2022 s2.2).
  * Tails are MODELED and disputed: one mesh, three shapes as morph targets
    with identical topology, so the measured nose stays fixed while tails swap:
      comet     (base)   long tail, dissolving past ~400 au, no hard end
      croissant (target) two lobes along the solar axis, closed by ~420 au
                         (Opher+ 2015/2020; Kornbleuth+ 2021/2026)
      bubble    (target) nearly round, closed at ~1.3 q (Dialynas+ 2017)
  * Breathing (target): TS +6 au, HP +2 au radial (illustrative, model-based).
  * Bow wave: soft upwind glow at ~1.9 q, faded to 0 by 120 deg. Whether a bow
    SHOCK exists is debated (McComas 2012 vs Scherer & Fichtner 2014).

Frame: heliocentric ecliptic J2000, AU. Alpha (COLOR_0.a) encodes evidence:
solid where measured, dissolving where modeled.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np

from .glb import GLB, grid_faces, srgb_to_linear, vertex_normals

NOSE_LON, NOSE_LAT = 255.7, 5.1
N_PHI = 64
NOSE_RINGS = 40          # theta 0..90 deg, identical in every shape
TAIL_RINGS = 44


def unit(lon_deg, lat_deg):
    lo, la = np.radians(lon_deg), np.radians(lat_deg)
    return np.array([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)])


def nose_frame():
    x = unit(NOSE_LON, NOSE_LAT)
    z = np.array([0.0, 0.0, 1.0]) - x[2] * x
    z /= np.linalg.norm(z)
    y = np.cross(z, x)
    return x, y, z


def craft_pos(out: Path, bid: str, d: str) -> np.ndarray:
    meta = json.loads((out / "ephem" / "trajectories.json").read_text())
    b = next(b for b in meta["bodies"] if b["id"] == bid)
    xyz = np.fromfile(out / b["file"], dtype="<f4").reshape(-1, 3).astype(float)
    i = (date.fromisoformat(d) - date.fromisoformat(b["start"])).days // b["step_days"]
    return xyz[i]


def theta_z(p, X, Z):
    dh = p / np.linalg.norm(p)
    return np.arccos(np.clip(dh @ X, -1, 1)), dh @ Z


def fit_two(r1, r2, g1, g2, z1, z2):
    """Solve r = r0 * g * (1 + a z) through two points."""
    R = (r1 / g1) / (r2 / g2)
    a = (R - 1) / (z1 - R * z2)
    r0 = r1 / (g1 * (1 + a * z1))
    return r0, a


def to_ecl(xn, rho, phi, X, Y, Z):
    """Nose-frame cylindrical (x along nose, rho, phi from Y toward Z) -> ecliptic."""
    return (xn[..., None] * X + (rho * np.cos(phi))[..., None] * Y
            + (rho * np.sin(phi))[..., None] * Z)


def nsfactor(p, a, Z):
    d = np.linalg.norm(p, axis=-1, keepdims=True)
    d[d == 0] = 1
    return p * (1 + a * (p @ Z)[..., None] / d)


def build_hp(q, a, X, Y, Z):
    phi = np.linspace(0, 2 * np.pi, N_PHI, endpoint=False)
    th_nose = np.radians(np.linspace(0, 90, NOSE_RINGS))
    nose_r = q / np.cos(th_nose / 2)
    nx, nrho = nose_r * np.cos(th_nose), nose_r * np.sin(th_nose)
    rho90 = nrho[-1]
    u = np.linspace(0, 1, TAIL_RINGS + 1)[1:]

    shapes = {}
    # comet: Rankine to 150 deg over half the tail rings, then a long cylinder.
    half = TAIL_RINGS // 2
    th_t = np.radians(np.linspace(90, 150, half + 1)[1:])
    rt = q / np.cos(th_t / 2)
    cx = np.concatenate([rt * np.cos(th_t), np.linspace(rt[-1] * np.cos(th_t[-1]), -1500, TAIL_RINGS - half + 1)[1:]])
    crho = np.concatenate([rt * np.sin(th_t), np.full(TAIL_RINGS - half, 2 * q * np.sin(np.radians(75)))])
    shapes["comet"] = (cx[:, None] * np.ones_like(phi), crho[:, None] * np.ones_like(phi))
    # croissant: lobes north/south, pinched east/west, closing at ~3.5 q.
    xe = -3.5 * q
    kx = xe * u
    R = rho90 * (1 + 0.28 * np.sin(np.pi * u)) * np.sqrt(np.clip(1 - u ** 4, 0, 1))
    p = np.clip(1.4 * u, 0, 0.92)[:, None]
    lobe = (1 - p) + p * np.abs(np.sin(phi))[None, :] ** 0.55
    shapes["croissant"] = (kx[:, None] * np.ones_like(phi), R[:, None] * lobe)
    # bubble: half-ellipsoid back, length 1.3 q.
    al = u * np.pi / 2
    shapes["bubble"] = ((-1.3 * q * np.sin(al))[:, None] * np.ones_like(phi),
                        (rho90 * np.cos(al) + 1e-3)[:, None] * np.ones_like(phi))

    out = {}
    for k, (tx, trho) in shapes.items():
        xn = np.concatenate([nx[:, None] * np.ones_like(phi), tx])
        rho = np.concatenate([nrho[:, None] * np.ones_like(phi), trho])
        pts = to_ecl(xn, rho, np.broadcast_to(phi, xn.shape), X, Y, Z)
        out[k] = nsfactor(pts, a, Z).reshape(-1, 3)
    return out, len(th_nose) + TAIL_RINGS


def build_ts(r0, a, X, Y, Z, k_tail):
    n_r = NOSE_RINGS + TAIL_RINGS
    phi = np.linspace(0, 2 * np.pi, N_PHI, endpoint=False)
    th = np.linspace(0, np.pi, n_r)
    r = r0 * (1 + k_tail * (1 - np.cos(th)) / 2)
    xn = (r * np.cos(th))[:, None] * np.ones_like(phi)
    rho = (r * np.sin(th))[:, None] * np.ones_like(phi)
    pts = to_ecl(xn, rho, np.broadcast_to(phi, xn.shape), X, Y, Z)
    return nsfactor(pts, a, Z).reshape(-1, 3), n_r


def rgba(hex_, alpha):
    h = hex_.lstrip("#")
    rgb = srgb_to_linear([int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)])
    a = np.asarray(alpha, dtype=float).reshape(-1, 1)
    return np.hstack([np.tile(rgb, (len(a), 1)), a])


def run(out: Path) -> dict:
    X, Y, Z = nose_frame()
    v1_ts, v2_ts = craft_pos(out, "voyager1", "2004-12-16"), craft_pos(out, "voyager2", "2007-08-31")
    v1_hp, v2_hp = craft_pos(out, "voyager1", "2012-08-25"), craft_pos(out, "voyager2", "2018-11-05")

    t1, z1 = theta_z(v1_hp, X, Z)
    t2, z2 = theta_z(v2_hp, X, Z)
    q, a_hp = fit_two(np.linalg.norm(v1_hp), np.linalg.norm(v2_hp),
                      1 / np.cos(t1 / 2), 1 / np.cos(t2 / 2), z1, z2)
    s1, w1 = theta_z(v1_ts, X, Z)
    s2, w2 = theta_z(v2_ts, X, Z)
    g = lambda t: 1 + (1 - np.cos(t)) / 2  # noqa: E731
    r0, a_ts = fit_two(np.linalg.norm(v1_ts), np.linalg.norm(v2_ts), g(s1), g(s2), w1, w2)
    print("  HP: q = {0:.2f} au, a = {1:+.3f}  (V1 theta {2:.1f} deg, V2 {3:.1f} deg)".format(
        q, a_hp, np.degrees(t1), np.degrees(t2)))
    print("  TS: r0 = {0:.2f} au, a = {1:+.3f}".format(r0, a_ts))

    glb = GLB()
    n_r = NOSE_RINGS + TAIL_RINGS
    faces = grid_faces(n_r, N_PHI)

    # ── heliopause ──
    hp, _ = build_hp(q, a_hp, X, Y, Z)
    base = hp["comet"]
    # alpha: solid on the nose (measured), dissolving down the tail (modeled)
    xn = base @ X
    alpha = 0.34 * np.clip(1 - (-xn - 120) / 420, 0, 1) ** 1.4
    alpha = np.maximum(alpha, 0.0)
    nb = vertex_normals(base, faces)
    breathe = base * (1 + 2.0 / 120.0)
    hp_node = glb.add_mesh(
        "heliopause", base, faces, color=rgba("#c58cff", alpha), normals=nb,
        targets=[{"name": "croissant", "pos": hp["croissant"], "normals": vertex_normals(hp["croissant"], faces)},
                 {"name": "bubble", "pos": hp["bubble"], "normals": vertex_normals(hp["bubble"], faces)},
                 {"name": "breathe", "pos": breathe, "normals": nb}],
        material="heliopause",
        extras={"tier": "MEASURED nose, MODELED tail", "q_au": round(float(q), 3), "ns_a": round(float(a_hp), 4),
                "fit_through": ["V1 2012-08-25 121.60 au", "V2 2018-11-05 119.02 au"],
                "model": "Rankine half-body r=q/cos(theta/2), Parker 1961; Kleimann+ 2022 eq.8-9"})
    glb.animate_weights("hp_breathe_11yr", hp_node, np.array([0, 2.75, 5.5, 8.25, 11.0]),
                        np.array([[0, 0, 0.5], [0, 0, 1.0], [0, 0, 0.5], [0, 0, 0.0], [0, 0, 0.5]]))

    # ── termination shock ──
    ts_comet, _ = build_ts(r0, a_ts, X, Y, Z, 1.0)
    ts_crois, _ = build_ts(r0, a_ts, X, Y, Z, 0.6)
    ts_bub, _ = build_ts(r0, a_ts, X, Y, Z, 0.3)
    nts = vertex_normals(ts_comet, faces)
    ts_node = glb.add_mesh(
        "termination_shock", ts_comet, faces, color=rgba("#6ec6ff", np.full(len(ts_comet), 0.22)), normals=nts,
        targets=[{"name": "croissant", "pos": ts_crois, "normals": vertex_normals(ts_crois, faces)},
                 {"name": "bubble", "pos": ts_bub, "normals": vertex_normals(ts_bub, faces)},
                 {"name": "breathe", "pos": ts_comet * (1 + 6.0 / 90.0), "normals": nts}],
        material="termination_shock",
        extras={"tier": "MEASURED at two points, MODELED elsewhere", "r0_au": round(float(r0), 3),
                "ns_a": round(float(a_ts), 4),
                "fit_through": ["V1 2004-12-16 94.02 au", "V2 2007-08-31 83.67 au"]})
    glb.animate_weights("ts_breathe_11yr", ts_node, np.array([0, 2.75, 5.5, 8.25, 11.0]),
                        np.array([[0, 0, 0.5], [0, 0, 1.0], [0, 0, 0.5], [0, 0, 0.0], [0, 0, 0.5]]))

    # ── bow wave (soft, upwind only) ──
    n_bw = 36
    th = np.radians(np.linspace(0, 120, n_bw))
    phi = np.linspace(0, 2 * np.pi, N_PHI, endpoint=False)
    qb = 1.9 * q
    rb = qb / np.cos(th / 2)
    pts = to_ecl((rb * np.cos(th))[:, None] * np.ones_like(phi), (rb * np.sin(th))[:, None] * np.ones_like(phi),
                 np.broadcast_to(phi, (n_bw, N_PHI)), X, Y, Z).reshape(-1, 3)
    a_bw = np.repeat(0.10 * np.clip(1 - np.degrees(th) / 120, 0, 1) ** 1.5, N_PHI)
    fb = grid_faces(n_bw, N_PHI)
    glb.add_mesh("bow_wave", pts, fb, color=rgba("#8fa3ff", a_bw), normals=vertex_normals(pts, fb),
                 material="bow_wave",
                 extras={"tier": "MODELED", "q_au": round(float(qb), 1),
                         "note": "bow wave vs weak bow shock is debated (McComas+ 2012; Scherer & Fichtner 2014)"})

    d = out / "models"
    d.mkdir(parents=True, exist_ok=True)
    nbytes = glb.save(d / "heliosphere.glb", root_extras={
        "frame": "heliocentric ecliptic J2000", "units": "au",
        "nose_from_ecliptic_deg": [NOSE_LON, NOSE_LAT],
        "morph_targets": ["croissant", "bubble", "breathe"],
        "sources": ["McComas+ 2015 ApJS 220 22", "Kleimann+ 2022 SSR 218 36", "Opher+ 2015 ApJL 800 L28",
                    "Opher+ 2020 NatAstron 4 675", "Dialynas+ 2017 NatAstron 1 0115", "Stone+ 2013 Science 341 150",
                    "Burlaga+ 2019 NatAstron 3 1007"]})
    print("  heliosphere.glb {0:.0f} KB".format(nbytes / 1024))
    meta = {"q_au": float(q), "hp_ns_a": float(a_hp), "ts_r0_au": float(r0), "ts_ns_a": float(a_ts),
            "nose_from_ecliptic_deg": [NOSE_LON, NOSE_LAT],
            "nose_axis": X.tolist(), "north_axis": Z.tolist()}
    (d / "heliosphere.json").write_text(json.dumps(meta, indent=1))
    return meta
