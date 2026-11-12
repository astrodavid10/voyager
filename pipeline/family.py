"""Voyager 1 "Family Portrait" (Solar System Portrait, 1990-02-14): images + 3D geometry.

Output (in ``<out>/pbd/``):
  family/<planet>.jpg               the six narrow-angle colour frames (Venus, Earth,
                                    Jupiter, Saturn, Uranus, Neptune), cut from PIA00453
  family/mosaic-pia00451.jpg        the 39-frame wide-angle mosaic with planet labels
  family/sun-earth-venus-pia00450.jpg  wide-angle Sun frame with Earth + Venus NAC insets
  family.json                       per-frame and per-panel geometry

Requires ``<out>/ephem`` (Voyager 1 + Earth) and ``<out>/pbd/pbd.json`` (run ``pbd``
first: the Earth frame's roll comes from it).  Other planets come from JPL Horizons.
Reasoning and sources: docs/RESEARCH-pbd.md, "Family Portrait".

Run:  python -m pipeline family --out public/data
"""

from __future__ import annotations

import io
import json
from datetime import timedelta
from pathlib import Path

import numpy as np
import requests
from PIL import Image
from scipy import ndimage as ndi
from scipy.optimize import minimize

from .pbd import (P_NATIVE, UTC, baked_position, camera, horizons_vec, project_tan,
                  to_px, unit)

ASSET = "https://assets.science.nasa.gov/content/dam/science/psd/photojournal/pia/pia00/{0}/{1}"
PANEL_ORDER = ["Venus", "Earth", "Jupiter", "Saturn", "Uranus", "Neptune"]   # caption order
PANEL_BOXES = {  # PIA00453 (620x500): left, top; each panel 180x200 px
    "Venus": (20, 20), "Earth": (220, 20), "Jupiter": (420, 20),
    "Saturn": (20, 260), "Uranus": (220, 260), "Neptune": (420, 260)}
PANEL_W, PANEL_H = 180, 200
# PIA00453 panels are "blown-up": the Earth panel matches PIA00452 (itself at native
# NAC scale, r=0.77 vs PIA23645) best at x1.6-1.8 (broad peak, 1.5-2.0); ray FWHM
# ratio gives ~1.9.  Assumed common to all six panels.
PANEL_MAG = 1.75
HORIZONS_ID = {"Venus": "299", "Earth": "399", "Jupiter": "599", "Saturn": "699",
               "Uranus": "799", "Neptune": "899"}
# Approximate label positions in PIA00451 (4000x1200), refined by blob centroid.
# J is a black glyph on a bright frame; the others are white.
MOSAIC_LABELS = {"Sun": (961, 663, "white"), "Venus": (911, 701, "white"),
                 "Earth": (879, 695, "white"), "Jupiter": (648, 609, "black"),
                 "Saturn": (1784, 655, "white"), "Uranus": (2543, 999, "white"),
                 "Neptune": (3647, 694, "white")}
# Orientation (deg, mod 90, image y down) of the edges of the wide-angle frame that
# contains each planet label in PIA00451, read from line fits to the frame edges
# (two edges each, agreeing to ~1-2 deg).  If MIPL placed the frames by their camera
# twist, the NAC frame twist differs between planets by the same amount (mod 90).
MOSAIC_FRAME_EDGE_DEG = {"Earth": 57.5, "Jupiter": 48.0, "Saturn": 64.5,
                         "Uranus": 78.0, "Neptune": 65.0}
CREDIT = {
    "PIA00451": "NASA/JPL-Caltech",
    "PIA00453": "NASA/JPL",
    "PIA00450": "NASA/JPL",
}


def fetch(pia: str, ext: str = "tif") -> Image.Image:
    url = ASSET.format(pia.lower(), "{0}.{1}".format(pia, ext))
    r = requests.get(url, timeout=120)
    r.raise_for_status()
    return Image.open(io.BytesIO(r.content)).convert("RGB")


def save_jpeg(im: Image.Image, path: Path, max_bytes: int) -> tuple:
    for q in (92, 88, 85, 82, 78, 74, 70):
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=q, optimize=True, progressive=True)
        if buf.tell() <= max_bytes:
            break
    path.write_bytes(buf.getvalue())
    return buf.tell(), q


def point_source(lum: np.ndarray, r: int = 6):
    """Brightest compact source (high-pass), centroided; continuous px coords."""
    hp = lum - ndi.gaussian_filter(lum, 8)
    sm = ndi.gaussian_filter(hp, 1.5)
    inner = sm[20:-20, 20:-20]
    y, x = np.unravel_index(np.argmax(inner), inner.shape)
    y += 20
    x += 20
    w = hp[y - r:y + r + 1, x - r:x + r + 1].clip(0)
    gy, gx = np.mgrid[-r:r + 1, -r:r + 1]
    cx = x + (w * gx).sum() / w.sum() + 0.5
    cy = y + (w * gy).sum() / w.sum() + 0.5
    ixx = (w * gx ** 2).sum() / w.sum()
    iyy = (w * gy ** 2).sum() / w.sum()
    ixy = (w * gx * gy).sum() / w.sum()
    ev = np.linalg.eigvalsh([[ixx, ixy], [ixy, iyy]])
    snr = float(sm[y, x] / sm.std())
    return float(cx), float(cy), float(np.sqrt(ev[1] / ev[0])), snr


def tangent_basis(c):
    e1 = unit(np.cross([0.0, 0.0, 1.0], c))      # toward increasing ecliptic longitude
    e2 = np.cross(c, e1)                          # toward ecliptic north
    return e1, e2


def gnomonic(d, c):
    e1, e2 = tangent_basis(c)
    z = d @ c
    return np.array([d @ e1 / z, d @ e2 / z])


def up_by_position_angle(d, psi):
    """Image-up unit vector at direction d with position angle psi (from local
    ecliptic north toward increasing longitude)."""
    e1, e2 = tangent_basis(unit(d))
    return unit(np.cos(psi) * e2 + np.sin(psi) * e1)


def position_angle(d, up):
    e1, e2 = tangent_basis(unit(d))
    return float(np.arctan2(up @ e1, up @ e2))


def solve_frame(target, up_hint, px, size, p):
    """Boresight + roll so `target` lands on `px` with image-up ~ up_hint (gnomonic)."""
    want_x = (px[0] - size[0] / 2.0) * p
    want_y = -(px[1] - size[1] / 2.0) * p
    f = unit(target)
    for _ in range(8):
        u = unit(up_hint - (up_hint @ f) * f)
        r = np.cross(f, u)
        ex, ey, _z = project_tan(target, f, r, u)
        f = unit(f + (ex - want_x) * r + (ey - want_y) * u)
    u = unit(up_hint - (up_hint @ f) * f)
    return f, np.cross(f, u), u


def fit_panel(img_pts: dict, dirs: dict, size, free_center: bool, mirror_ok=True):
    """Fit a gnomonic tangent plane + similarity (scale, rotation, offset) mapping sky
    directions onto image pixels.  Returns the panel definition and residuals."""
    keys = [k for k in img_pts if k in dirs]
    c0 = unit(sum(dirs[k] for k in keys))

    def solve(c, mir):
        A, b = [], []
        for k in keys:
            X, Y = gnomonic(dirs[k], c)
            Y *= mir
            A += [[X, -Y, 1, 0], [Y, X, 0, 1]]
            b += [img_pts[k][0], img_pts[k][1]]
        A, b = np.array(A), np.array(b)
        sol = np.linalg.lstsq(A, b, rcond=None)[0]
        res = (A @ sol - b).reshape(-1, 2)
        return sol, res

    def center_of(t):
        e1, e2 = tangent_basis(c0)
        return unit(c0 + t[0] * e1 + t[1] * e2)

    best = None
    for mir in ((1, -1) if mirror_ok else (1,)):
        if free_center:
            obj = lambda t: (solve(center_of(t), mir)[1] ** 2).sum()  # noqa: E731
            t = minimize(obj, [0.0, 0.0], method="Nelder-Mead",
                         options={"xatol": 1e-6, "fatol": 1e-6, "maxiter": 4000}).x
            c = center_of(t)
        else:
            c = c0
        sol, res = solve(c, mir)
        rms = float(np.sqrt((res ** 2).sum(1).mean()))
        if best is None or rms < best[0]:
            best = (rms, mir, c, sol, res)
    rms, mir, c, sol, res = best
    a, bb, tx, ty = sol
    scale = float(np.hypot(a, bb))                # px per tangent unit
    M = np.array([[a, -bb], [bb, a]]) @ np.diag([1.0, mir])
    Minv = np.linalg.inv(M)
    e1, e2 = tangent_basis(c)

    def pix_to_plane(u, v):                       # point on the tangent plane at distance 1
        X, Y = Minv @ (np.array([u, v]) - [tx, ty])
        return c + X * e1 + Y * e2

    W, H = size
    centre = pix_to_plane(W / 2.0, H / 2.0)
    right = unit(pix_to_plane(W / 2.0 + 1, H / 2.0) - centre)
    up = unit(pix_to_plane(W / 2.0, H / 2.0 - 1) - centre)
    corners = [pix_to_plane(0, 0), pix_to_plane(W, 0), pix_to_plane(W, H), pix_to_plane(0, H)]

    def sep(a_, b_):
        return float(np.degrees(np.arccos(np.clip(unit(a_) @ unit(b_), -1, 1))))
    width_deg = sep(pix_to_plane(0, H / 2.0), pix_to_plane(W, H / 2.0))
    height_deg = sep(pix_to_plane(W / 2.0, 0), pix_to_plane(W / 2.0, H))
    out = {
        "projection": "gnomonic (flat plane): the image is a rectangle on the plane tangent to "
                      "plane_normal_dir at unit distance; place corners at v1 + D*corner",
        "plane_normal_dir": [round(float(x), 9) for x in c],
        "center_dir_ecl": [round(float(x), 9) for x in unit(centre)],
        "up_ecl": [round(float(x), 9) for x in up],
        "right_ecl": [round(float(x), 9) for x in right],
        "corners_on_unit_plane": [[round(float(x), 7) for x in k] for k in corners],
        "px_per_deg_at_tangent_point": round(scale * np.pi / 180, 3),
        "angular_width_deg": round(width_deg, 3),     # across the middle row, seen from V1
        "angular_height_deg": round(height_deg, 3),   # down the middle column
        "tangent_point_from_center_deg": round(sep(c, centre), 3),
        "mirrored": bool(mir < 0),
        "fit_points": {k: [round(float(img_pts[k][0]), 1), round(float(img_pts[k][1]), 1)] for k in keys},
        "fit_residual_px": {k: [round(float(r[0]), 1), round(float(r[1]), 1)] for k, r in zip(keys, res)},
        "fit_rms_px": round(rms, 2),
    }
    # residuals as angles on the sky: where the panel puts each label vs the true direction
    ang = {k: sep(pix_to_plane(*img_pts[k]), dirs[k]) for k in keys}
    out["fit_residual_deg"] = {k: round(v, 3) for k, v in ang.items()}
    out["fit_rms_deg"] = round(float(np.sqrt(np.mean(np.square(list(ang.values()))))), 3)
    return out


def panel_px(pn: dict, d, size) -> np.ndarray:
    """Pixel position of direction d on a fitted flat panel (corners on the unit plane)."""
    n = np.array(pn["plane_normal_dir"])
    C = [np.array(c) for c in pn["corners_on_unit_plane"]]
    x = d / (d @ n)
    ex, ey = C[1] - C[0], C[3] - C[0]
    return np.array([(x - C[0]) @ ex / (ex @ ex) * size[0], (x - C[0]) @ ey / (ey @ ey) * size[1]])


def fit_stereographic(img_pts: dict, dirs: dict):
    """Conformal (stereographic) sky->mosaic fit with a free projection centre.

    The mosaic's frames stay square, so it is locally conformal; angles on it must be
    read through a conformal model, not through the (non-conformal, oblique) flat
    panel used for display.  Returns a function direction -> pixel, and the rms (px)."""
    keys = [k for k in img_pts if k in dirs]
    c0 = unit(sum(dirs[k] for k in keys))
    e1, e2 = tangent_basis(c0)

    def proj(d, c):
        b1, b2 = tangent_basis(c)
        z = np.clip(d @ c, -1, 1)
        k_ = 2.0 / (1.0 + z)
        return np.array([k_ * (d @ b1), k_ * (d @ b2)])

    def solve(c):
        A, b = [], []
        for k in keys:
            X, Y = proj(dirs[k], c)
            A += [[X, -Y, 1, 0], [Y, X, 0, 1]]
            b += [img_pts[k][0], img_pts[k][1]]
        A, b = np.array(A), np.array(b)
        sol = np.linalg.lstsq(A, b, rcond=None)[0]
        return sol, float(np.sqrt(((A @ sol - b) ** 2).reshape(-1, 2).sum(1).mean()))

    cen = lambda t: unit(c0 + t[0] * e1 + t[1] * e2)  # noqa: E731
    t = minimize(lambda t: solve(cen(t))[1], [0.0, 0.0], method="Nelder-Mead",
                 options={"xatol": 1e-7, "fatol": 1e-6, "maxiter": 4000}).x
    c = cen(t)
    sol, rms = solve(c)
    a, bb, tx, ty = sol

    def to_px_(d):
        X, Y = proj(unit(d), c)
        return np.array([a * X - bb * Y + tx, bb * X + a * Y + ty])
    return to_px_, rms


def mosaic_up_angle(to_px_, f, u) -> float:
    """Image angle (deg, y down) of a NAC frame's up-vector drawn on the mosaic."""
    a = to_px_(f)
    b = to_px_(unit(f + 1e-4 * u))
    return float(np.degrees(np.arctan2(b[1] - a[1], b[0] - a[0])))


def wrap90(x):
    return (x + 45.0) % 90.0 - 45.0


def mosaic_labels(im: Image.Image) -> dict:
    L = np.asarray(im, dtype=np.float64).mean(axis=2)
    out = {}
    for k, (gx, gy, kind) in MOSAIC_LABELS.items():
        r = 22
        sub = L[gy - r:gy + r, gx - r:gx + r]
        m = sub > max(np.percentile(sub, 50) + 60, 200) if kind == "white" else sub < 40
        lab, n = ndi.label(m)
        best = None
        for i in range(1, n + 1):
            if (lab == i).sum() < 4:
                continue
            cy, cx = ndi.center_of_mass(m, lab, i)
            dd = np.hypot(cx - r, cy - r)
            if best is None or dd < best[0]:
                best = (dd, cx, cy)
        if best is None or best[0] > 15:
            raise RuntimeError("mosaic label {0} not found".format(k))
        out[k] = (gx - r + best[1] + 0.5, gy - r + best[2] + 0.5)
    return out


def run(out: Path, verbose: bool = True) -> dict:
    d = out / "pbd"
    fam = d / "family"
    fam.mkdir(parents=True, exist_ok=True)
    pbd = json.loads((d / "pbd.json").read_text())

    # ---- positions -------------------------------------------------------
    v1 = baked_position(out, "voyager1", UTC)
    pos = {"Earth": baked_position(out, "earth", UTC)}
    for k in ("Venus", "Jupiter", "Saturn", "Uranus", "Neptune"):
        pos[k] = horizons_vec(HORIZONS_ID[k], "500@10")
    dirs = {k: unit(p - v1) for k, p in pos.items()}
    dirs["Sun"] = unit(-v1)

    # sensitivity of each direction to the (unverified) per-frame time: 3 h earlier
    t3 = UTC - timedelta(hours=3)
    v1_3 = baked_position(out, "voyager1", t3)
    e3 = baked_position(out, "earth", t3)

    # ---- wide-angle Sun frame with Earth/Venus insets (PIA00450) -----------
    sev = fetch("PIA00450")
    L = np.asarray(sev, dtype=np.float64).mean(axis=2)
    yy, xx = np.nonzero(L > 250)
    sel = xx > sev.size[0] * 0.6
    sun_px = (float(xx[sel].mean()) + 0.5, float(yy[sel].mean()) + 0.5)
    hp = L - ndi.gaussian_filter(L, 15)

    def peak(x0, x1, y0, y1):
        sub = hp[y0:y1, x0:x1]
        y, x = np.unravel_index(np.argmax(sub), sub.shape)
        return float(x0 + x) + 0.5, float(y0 + y) + 0.5
    sev_pts = {"Sun": sun_px, "Earth": peak(232, 823, 1031, 1677), "Venus": peak(930, 1490, 1450, 2075)}
    sev_panel = fit_panel(sev_pts, dirs, sev.size, free_center=False)
    sev_small = sev.resize((sev.size[0] // 2, sev.size[1] // 2), Image.LANCZOS)
    nb_sev, _q = save_jpeg(sev_small, fam / "sun-earth-venus-pia00450.jpg", 400_000)
    sev_panel.update({
        "image": "pbd/family/sun-earth-venus-pia00450.jpg",
        "width_px": sev_small.size[0], "height_px": sev_small.size[1],
        "fit_points_note": "pixel coords are in the 3430x2650 NASA original; the saved JPEG is x0.5",
        "note": ("WA Sun frame (methane filter, 0.005 s) with the Earth and Venus NAC colour frames "
                 "inset at the WA scale. Placement fits the ephemeris to <0.1% in scale and ~0.2 deg in "
                 "angle with only 3 points (Sun, Earth, Venus), so it is a precise panel. Its insets are "
                 "the PBD rotated 90 deg clockwise, which puts the Sun toward the PBD's TOP (the "
                 "alt_sun_toward_top roll), opposite to NASA's 2020 caption."),
        "credit": CREDIT["PIA00450"], "source": "PIA00450", "jpeg_bytes": nb_sev,
    })

    # ---- 39-frame wide-angle mosaic (PIA00451) ----------------------------
    mos = fetch("PIA00451")
    labels = mosaic_labels(mos)
    # Two flat-plane fits: tangent point free (best fit, but it lands far off the image,
    # i.e. a strongly oblique plane) and tangent point = mean label direction (a plain
    # card facing V1).  Keep the plain card unless the free fit is clearly better.
    mos_free = fit_panel(labels, dirs, mos.size, free_center=True)
    mos_card = fit_panel(labels, dirs, mos.size, free_center=False)
    mos_panel = mos_free if mos_free["fit_rms_deg"] < 0.7 * mos_card["fit_rms_deg"] else mos_card
    mos_panel["alternative_fit_rms_deg"] = {"free_tangent_point": mos_free["fit_rms_deg"],
                                            "tangent_at_mean_direction": mos_card["fit_rms_deg"]}
    mos_small = mos.resize((3000, 900), Image.LANCZOS)
    nb_mos, _q = save_jpeg(mos_small, fam / "mosaic-pia00451.jpg", 400_000)
    mos_panel.update({
        "image": "pbd/family/mosaic-pia00451.jpg",
        "width_px": mos_small.size[0], "height_px": mos_small.size[1],
        "fit_points_note": ("label-glyph centroids (J, E, V, S, U, N and the Sun) in the 4000x1200 "
                            "NASA original; the saved JPEG is x0.75"),
        "note": ("Hand-assembled MIPL mosaic of wide-angle frames spanning ~55 deg; it is not a "
                 "rigorous projection. Flat-plane fit with free tangent point: see fit_rms_deg. Good "
                 "enough to hang as a backdrop card behind the planet frames at ~1-2 deg accuracy; "
                 "the inset thumbnails (JUPITER, EARTH...) around its edge are NOT at their sky "
                 "positions."),
        "credit": CREDIT["PIA00451"], "source": "PIA00451", "jpeg_bytes": nb_mos,
    })

    # ---- the six NAC frames (PIA00453) -------------------------------------
    six = fetch("PIA00453")
    p = P_NATIVE / PANEL_MAG
    size = (PANEL_W, PANEL_H)
    earth_up = np.array(pbd["up_ecl"])
    psi_earth = position_angle(dirs["Earth"], earth_up)
    stereo, stereo_rms = fit_stereographic(labels, dirs)   # conformal model, for angles only
    mos_panel["conformal_fit_rms_px_4000"] = round(stereo_rms, 1)
    mos_off_e = 0.0
    frames = []
    for k in PANEL_ORDER:
        x0, y0 = PANEL_BOXES[k]
        crop = six.crop((x0, y0, x0 + PANEL_W, y0 + PANEL_H))
        nbytes, q = save_jpeg(crop, fam / "{0}.jpg".format(k.lower()), 250_000)
        lum = np.asarray(crop, dtype=np.float64).mean(axis=2)
        px, py, elong, snr = point_source(lum)
        if snr < 8:
            raise RuntimeError("{0}: planet not detected (snr {1:.1f})".format(k, snr))
        if k == "Earth":
            # same construction as pbd.json: the real Sun projects along the measured
            # sunward axis (the PIA00453 Earth panel has PBD's orientation: ray tilt
            # -0.167 vs -0.161)
            f, r, u = camera(dirs["Earth"], dirs["Sun"], pbd["sun_image_dir_deg"], (px, py), size, p)
            method = "derived-from-sun"
            mos_off_e = wrap90(mosaic_up_angle(stereo, f, u) - MOSAIC_FRAME_EDGE_DEG["Earth"])
            twist_note = ("Earth frame-up drawn on the mosaic sits {0:+.1f} deg (mod 90) from the edges "
                          "of its wide-angle frame: an independent check of the Sun-derived roll "
                          "axis".format(mos_off_e))
        elif k == "Venus":
            u_hint = up_by_position_angle(dirs[k], psi_earth)
            f, r, u = solve_frame(dirs[k], u_hint, (px, py), size, p)
            method = "derived-from-sun (same twist as the Earth frame, 0.4 deg away; PIA00450)"
            twist_note = None
        else:
            # mosaic-twist: rotate about the line of sight until this frame sits on the mosaic
            # the way the Earth frame does relative to its wide-angle frame (smallest turn).
            best = None
            for dpsi in np.radians(np.arange(-45.0, 45.01, 0.05)):
                uh = up_by_position_angle(dirs[k], psi_earth + dpsi)
                ff = unit(dirs[k])
                uu = unit(uh - (uh @ ff) * ff)
                miss = abs(wrap90(mosaic_up_angle(stereo, ff, uu)
                                  - MOSAIC_FRAME_EDGE_DEG[k] - mos_off_e))
                if best is None or miss < best[0] - 1e-9:
                    best = (miss, dpsi)
            dpsi = best[1]
            f, r, u = solve_frame(dirs[k], up_by_position_angle(dirs[k], psi_earth + dpsi), (px, py), size, p)
            method = "mosaic-twist (relative to the Earth frame, from PIA00451 frame tilts; mod 90)"
            twist_note = ("{0:+.1f} deg from the Earth frame's sky position angle; +-5 deg; the mod-90 "
                          "choice is the smallest turn".format(float(np.degrees(dpsi))))
        # the other sign of the Earth roll (alt), same relative twist
        fa, ra, ua = solve_frame(dirs[k], -u, (px, py), size, p)
        ep = to_px(dirs[k], f, r, u, size, p)
        err = float(np.hypot(ep[0] - px, ep[1] - py))
        if err > 0.05:
            raise RuntimeError("{0}: reprojection error {1:.3f}px".format(k, err))
        sp = to_px(dirs["Sun"], f, r, u, size, p) if dirs["Sun"] @ f > 0 else None
        p3 = (e3 if k == "Earth" else pos[k]) - v1_3   # planets other than Earth: V1 motion only
        shift3 = float(np.degrees(np.arccos(np.clip(unit(p3) @ dirs[k], -1, 1))) * 3600)
        dist = float(np.linalg.norm(pos[k] - v1))
        frames.append({
            "planet": k,
            "utc": UTC.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "utc_note": ("verified (NASA PIA23645)" if k == "Earth" else
                         "per-frame time not published; evaluated at the Earth-frame time"),
            "image": "pbd/family/{0}.jpg".format(k.lower()),
            "width_px": PANEL_W, "height_px": PANEL_H,
            "fov_deg_x": round(float(np.degrees(2 * np.arctan(PANEL_W / 2 * p))), 5),
            "fov_deg_y": round(float(np.degrees(2 * np.arctan(PANEL_H / 2 * p))), 5),
            "tan_per_px": p,
            "planet_px": [round(px, 2), round(py, 2)],
            "planet_shape": "elongation {0:.2f}{1}".format(
                elong, " (15 s exposure smear)" if k in ("Uranus", "Neptune") else ""),
            "center_dir_ecl": [round(float(x), 9) for x in f],
            "up_ecl": [round(float(x), 9) for x in u],
            "right_ecl": [round(float(x), 9) for x in r],
            "view_dir_ecl": [round(float(x), 9) for x in dirs[k]],
            "alt_sun_toward_top": {"center_dir_ecl": [round(float(x), 9) for x in fa],
                                   "up_ecl": [round(float(x), 9) for x in ua],
                                   "right_ecl": [round(float(x), 9) for x in ra]},
            "v1_au": [round(float(x), 9) for x in v1],
            "planet_au": [round(float(x), 9) for x in pos[k]],
            "v1_planet_distance_au": round(dist, 4),
            "elongation_from_sun_deg": round(float(np.degrees(np.arccos(dirs[k] @ dirs["Sun"]))), 3),
            "shift_if_3h_earlier_native_px": round(float(np.radians(shift3 / 3600) / P_NATIVE), 1),
            "roll_method": method,
            "roll_note": twist_note,
            "validation": {"planet_reprojects_to_px": [round(ep[0], 3), round(ep[1], 3)],
                           "error_px": round(err, 4),
                           "sun_px": None if sp is None else [round(sp[0], 1), round(sp[1], 1)]},
            "jpeg_bytes": nbytes,
        })

    doc = {
        "schema": "voyager.family/1",
        "event": "Voyager 1 Solar System Portrait ('Family Portrait'), 1990-02-14",
        "utc_note": ("The Earth frames were taken at 04:48 UTC (NASA); the cameras were switched off "
                     "at 05:22 UTC. Per-frame times for the other planets are not published in any "
                     "source we could reach; all geometry is evaluated at 04:48. "
                     "shift_if_3h_earlier_native_px gives the sensitivity."),
        "frames": frames,
        "frame_scale_note": ("PIA00453 panels are blown up x{0} relative to native NAC pixels "
                             "(measured on the Earth panel, +-15%; assumed for all six). NAC: "
                             "0.424 deg over 800 px (NAIF vg1_issna_v02.ti).".format(PANEL_MAG)),
        "roll_note": ("No scan-platform pointing survives for 1990 (PDS VGISS ends 1989-09-29; NAIF "
                      "CK is bus-only). Earth: Sun-derived as in pbd.json. Venus: same twist as Earth "
                      "(PIA00450 shows both insets with identical orientation). Jupiter-Neptune: "
                      "twist relative to Earth taken from the tilts of their wide-angle frames in "
                      "the PIA00451 mosaic (mod 90, smallest turn, +-5 deg). Every frame inherits the "
                      "Earth frame's 180-deg sign question: alt_sun_toward_top flips them all. The "
                      "outer planets are point sources, so their roll barely shows."),
        "not_imaged": {
            "Mercury": "too close to the Sun (0.39 deg from it as seen from Voyager 1)",
            "Mars": "not detectable because of scattered sunlight in the optics (1.26 deg from the Sun)",
            "Pluto": "too small and too far from the Sun (too dim)",
        },
        "mosaic": mos_panel,
        "sun_earth_venus": sev_panel,
        "v1_au": [round(float(x), 9) for x in v1],
        "sun_dir_ecl": [round(float(x), 9) for x in dirs["Sun"]],
        "credit": ("NASA/JPL-Caltech. Images PIA00450, PIA00451, PIA00453 (Voyager 1 Solar System "
                   "Portrait, 1990)."),
        "credit_per_image": CREDIT,
        "license": ("NASA/JPL mission imagery, not copyrighted (public domain in the US); JPL Image "
                    "Use Policy: usable for any purpose without prior permission, with credit"),
        "sources": [
            "https://science.nasa.gov/photojournal/solar-system-portrait-views-of-6-planets (PIA00453)",
            "https://science.nasa.gov/photojournal/solar-system-portrait-60-frame-mosaic (PIA00451)",
            "https://science.nasa.gov/photojournal/solar-system-portrait-view-of-the-sun-earth-and-venus (PIA00450)",
            "https://science.nasa.gov/photojournal/pale-blue-dot-revisited (PIA23645)",
            "https://naif.jpl.nasa.gov/pub/naif/VOYAGER/kernels/ik/vg1_issna_v02.ti",
            "https://ssd.jpl.nasa.gov/api/horizons.api",
            "https://www.jpl.nasa.gov/jpl-image-use-policy",
        ],
    }
    (d / "family.json").write_text(json.dumps(doc, indent=1))
    if verbose:
        for fr in frames:
            print("  {0:8s} px {1} elong {2:6.2f} deg dist {3:7.3f} au  err {4} px  3h-shift {5} px  {6}".format(
                fr["planet"], fr["planet_px"], fr["elongation_from_sun_deg"], fr["v1_planet_distance_au"],
                fr["validation"]["error_px"], fr["shift_if_3h_earlier_native_px"], fr["roll_method"][:24]))
        for nm, pn in (("PIA00450", sev_panel), ("PIA00451", mos_panel)):
            print("  {0}: {1:.2f} x {2:.2f} deg (tangent pt {8} deg from centre), {3:.1f} px/deg, rms {4} px "
                  "= {5} deg, mirrored={6}, {7} KB".format(
                      nm, pn["angular_width_deg"], pn["angular_height_deg"], pn["px_per_deg_at_tangent_point"],
                      pn["fit_rms_px"], pn["fit_rms_deg"], pn["mirrored"], pn["jpeg_bytes"] // 1024,
                      pn["tangent_point_from_center_deg"]))
            print("     residuals deg:", pn["fit_residual_deg"], pn.get("alternative_fit_rms_deg", ""))
    return doc
