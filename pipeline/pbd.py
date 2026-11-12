"""Pale Blue Dot: the image plus the geometry to pin it into the 3D scene.

Output (in ``<out>/pbd/``):
  pale-blue-dot.jpg  NASA's 2020 remaster (PIA23645), resampled to 2x its native
                     666 x 659 frame (1332 x 1318), JPEG <= ~300 KB
  pbd.json           where Voyager 1 and Earth were, which way the camera looked,
                     which way is image-up, and the field of view

Sources and reasoning: docs/RESEARCH-pbd.md.  In short:

* Time: 1990-02-14 04:48 UTC (NASA, PIA23645 caption), Voyager 1 narrow-angle
  camera (NAC), violet/blue/green exposures of 0.72/0.72/0.48 s.
* Positions: the app's own baked ephemeris (``<out>/ephem``), interpolated
  linearly exactly as ``src/data/ephem.ts`` does, so the overlay lines up with
  the Earth and Voyager the scene draws.  Cross-checked against JPL Horizons.
* Scale: NAIF IK vg1_issna_v02.ti gives the NAC FOV as a square of corner
  tangent 0.003700098 over 800 pixels -> 9.2502e-6 (tan) per native pixel.
  The remaster's native size is 666 x 659 (caption); NASA's JPEG is that
  frame upsampled x7.853.
* Roll: there is NO archived pointing for this frame (the PDS Voyager ISS
  archive ends 1989-09-29; the NAIF Voyager 1 CK covers only the bus, not the
  scan platform).  The roll is DERIVED FROM THE SUN: the caption says the Sun
  is toward the bottom of the view, where the image is brightest; we measure
  that axis from the main scattered-light ray and from the brightness gradient
  (they agree to <1 deg) and turn the camera about the line of sight until the
  real Sun projects along it.  The opposite (180 deg) solution is also written
  under ``alt_sun_toward_top`` because the 1990 Sun/Earth/Venus composite
  (PIA00450) shows the Earth inset the other way round.

Run:  python -m pipeline pbd --out public/data
"""

from __future__ import annotations

import io
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import requests
from PIL import Image
from scipy.ndimage import gaussian_filter, gaussian_filter1d, median_filter

IMG_URL = ("https://assets.science.nasa.gov/content/dam/science/psd/photojournal/"
           "pia/pia23/pia23645/PIA23645.jpg")
UTC = datetime(1990, 2, 14, 4, 48, 0, tzinfo=timezone.utc)
NATIVE = (666, 659)               # PIA23645 Figure A, "at its original resolution"
OUT_SCALE = 2                     # saved JPEG = 2x native
NAC_TAN_HALF = 0.003700098        # NAIF vg1_issna_v02.ti corner tangent (0.424 deg full)
NAC_PIX = 800
P_NATIVE = 2 * NAC_TAN_HALF / NAC_PIX   # tangent-plane units per native pixel
MAX_BYTES = 300_000
HORIZONS = "https://ssd.jpl.nasa.gov/api/horizons.api"
AU_KM = 149597870.7


def unit(v):
    v = np.asarray(v, float)
    return v / np.linalg.norm(v)


# ---------------------------------------------------------------- ephemeris
def baked_position(out: Path, bid: str, t: datetime) -> np.ndarray:
    meta = json.loads((out / "ephem" / "trajectories.json").read_text())
    b = next(b for b in meta["bodies"] if b["id"] == bid)
    xyz = np.frombuffer((out / b["file"]).read_bytes(), dtype="<f4").reshape(-1, 3).astype(float)
    t0 = datetime.fromisoformat(b["start"]).replace(tzinfo=timezone.utc)
    f = (t - t0).total_seconds() / 86400.0 / b["step_days"]
    i = int(np.floor(f))
    u = f - i
    return xyz[i] * (1 - u) + xyz[i + 1] * u


def horizons_vec(cmd: str, center: str, corr: str = "NONE") -> np.ndarray:
    p = {"format": "json", "COMMAND": "'{0}'".format(cmd), "OBJ_DATA": "NO", "MAKE_EPHEM": "YES",
         "EPHEM_TYPE": "VECTORS", "CENTER": "'{0}'".format(center),
         "TLIST": "'{0}'".format(UTC.strftime("%Y-%m-%d %H:%M:%S")), "TIME_TYPE": "UT",
         "REF_PLANE": "ECLIPTIC", "REF_SYSTEM": "ICRF", "OUT_UNITS": "AU-D", "VEC_TABLE": "1",
         "VEC_CORR": "'{0}'".format(corr), "CSV_FORMAT": "YES", "VEC_LABELS": "NO"}
    r = requests.get(HORIZONS, params=p, timeout=60)
    r.raise_for_status()
    text = r.json()["result"]
    a, b = text.index("$$SOE"), text.index("$$EOE")
    c = text[a + 5:b].strip().split(",")
    return np.array([float(c[2]), float(c[3]), float(c[4])])


# ---------------------------------------------------------------- image measurements
def measure_earth(lum: np.ndarray):
    """Earth = the one compact bright point (high-pass peak), refined by centroid."""
    hp = lum - gaussian_filter(lum, 25)
    y, x = np.unravel_index(np.argmax(hp), hp.shape)
    r = 12
    box = hp[y - r:y + r + 1, x - r:x + r + 1].clip(0)
    yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
    cx = x + (box * xx).sum() / box.sum()
    cy = y + (box * yy).sum() / box.sum()
    second = np.sort(hp[::4, ::4].ravel())[-200]
    return float(cx), float(cy), float(hp[y, x]), float(second)


def measure_sun_axis(native_lum: np.ndarray, earth_xy):
    """Image-plane direction (deg, atan2(dy, dx) with y DOWN) toward the Sun.

    Two independent estimates: (1) the main scattered-light ray, the one that
    crosses Earth, fitted as x = a + b*y; (2) the large-scale brightness
    gradient (plane fit).  The ray gives the axis; the gradient gives the sign
    (brighter = sunward, as the PIA23645 caption states).
    """
    L = native_lum
    h, w = L.shape
    ex, ey = earth_xy
    pts = []
    for yrow in range(10, h - 10, 10):
        prof = L[yrow - 5:yrow + 5].mean(axis=0)
        prof = gaussian_filter1d(prof, 2) - gaussian_filter1d(prof, 30)
        # the main ray passes through Earth and leans ~0.16 px/px; search +-25 px
        xe = ex - 0.16 * (yrow - ey)
        lo, hi = int(max(0, xe - 25)), int(min(w, xe + 25))
        seg = prof[lo:hi]
        i = int(np.argmax(seg))
        if 2 < i < len(seg) - 3:
            y0, y1, y2 = seg[i - 1], seg[i], seg[i + 1]
            pts.append((lo + i + 0.5 * (y0 - y2) / (y0 - 2 * y1 + y2), yrow))
    pts = np.array(pts)
    A = np.c_[np.ones(len(pts)), pts[:, 1]]
    coef = np.linalg.lstsq(A, pts[:, 0], rcond=None)[0]
    res = pts[:, 0] - A @ coef
    keep = np.abs(res) < 2.5 * res.std() + 0.5
    coef = np.linalg.lstsq(A[keep], pts[keep, 0], rcond=None)[0]
    rms = float((pts[keep, 0] - A[keep] @ coef).std())
    ray_off_earth = float(coef[0] + coef[1] * ey - ex)

    s = max(1, w // 200)
    c = median_filter(L[::s, ::s], 9)
    yy, xx = np.mgrid[0:c.shape[0], 0:c.shape[1]]
    G = np.c_[np.ones(c.size), (xx / c.shape[1] - 0.5).ravel(), (yy / c.shape[0] - 0.5).ravel()]
    g = np.linalg.lstsq(G, c.ravel(), rcond=None)[0]
    grad_deg = float(np.degrees(np.arctan2(g[2], g[1])))

    ray_vec = unit([coef[1], 1.0])                      # along the ray, pointing down
    if np.dot(ray_vec, [g[1], g[2]]) < 0:
        ray_vec = -ray_vec
    ray_deg = float(np.degrees(np.arctan2(ray_vec[1], ray_vec[0])))
    sun_deg = float(np.degrees(np.arctan2(np.sin(np.radians(ray_deg)) + np.sin(np.radians(grad_deg)),
                                          np.cos(np.radians(ray_deg)) + np.cos(np.radians(grad_deg)))))
    return {"ray_a": float(coef[0]), "ray_b": float(coef[1]), "ray_rms_px": rms,
            "ray_points": int(keep.sum()), "ray_offset_at_earth_px": ray_off_earth,
            "ray_deg": ray_deg, "gradient_deg": grad_deg,
            "gradient_dn_per_frame": float(np.hypot(g[1], g[2])), "mean_dn": float(g[0]),
            "sun_deg": sun_deg}


# ---------------------------------------------------------------- camera
def camera(earth_dir, sun_dir, sun_img_deg, earth_px, size, p):
    """Orthonormal camera (forward=image centre, right, up) in ecliptic J2000.

    sun_img_deg: direction toward the Sun in the image, atan2(dy, dx), y DOWN.
    earth_px: Earth's pixel position (continuous, origin top-left corner).
    p: tangent-plane units per pixel.  Gnomonic projection.
    """
    phi = np.radians(sun_img_deg)
    alpha, beta = np.cos(phi), -np.sin(phi)       # components on (right, up)
    want_x = (earth_px[0] - size[0] / 2.0) * p    # Earth right of centre -> +
    want_y = -(earth_px[1] - size[1] / 2.0) * p   # Earth below centre -> - (up axis)
    f = unit(earth_dir)
    for _ in range(8):                            # boresight offset + roll, jointly
        r, u = basis_from_earth(f, earth_dir, sun_dir, alpha, beta)
        ex, ey, _z = project_tan(earth_dir, f, r, u)
        # moving the boresight by +d along r moves Earth's image by -d
        f = unit(f + (ex - want_x) * r + (ey - want_y) * u)
    r, u = basis_from_earth(f, earth_dir, sun_dir, alpha, beta)
    return f, r, u


def project_tan(d, f, r, u):
    d = unit(d)
    z = np.dot(d, f)
    return np.dot(d, r) / z, np.dot(d, u) / z, z


def basis_from_earth(f, earth_dir, sun_dir, alpha, beta):
    """Roll the camera about f until the Earth->Sun direction on the image plane
    has components (alpha, beta) on (right, up)."""
    # provisional basis
    t = unit(np.cross(f, [0.0, 0.0, 1.0]))
    r0, u0 = t, unit(np.cross(t, f))
    e = np.array(project_tan(earth_dir, f, r0, u0)[:2])
    s = np.array(project_tan(sun_dir, f, r0, u0)[:2])
    ang_have = np.arctan2(*(s - e)[::-1])
    ang_want = np.arctan2(beta, alpha)
    rot = ang_want - ang_have                     # rotate image content by +rot
    # rotating content by +rot (CCW on right/up axes) == rotating axes by -rot
    cr, sr = np.cos(rot), np.sin(rot)
    r = cr * r0 - sr * u0
    u = sr * r0 + cr * u0
    return unit(r), unit(u)


def to_px(d, f, r, u, size, p):
    x, y, z = project_tan(d, f, r, u)
    return size[0] / 2.0 + x / p, size[1] / 2.0 - y / p, z


# ---------------------------------------------------------------- main
def run(out: Path, verbose: bool = True) -> dict:
    d = out / "pbd"
    d.mkdir(parents=True, exist_ok=True)

    # 1. image -------------------------------------------------------------
    r = requests.get(IMG_URL, timeout=120)
    r.raise_for_status()
    src = Image.open(io.BytesIO(r.content)).convert("RGB")
    W0, H0 = src.size
    k = W0 / NATIVE[0]
    if abs(H0 / NATIVE[1] - k) > 1e-3:
        raise RuntimeError("PIA23645 aspect changed: {0}x{1}".format(W0, H0))
    lum = np.asarray(src, dtype=np.float64).mean(axis=2)
    ex0, ey0, peak, second = measure_earth(lum)
    if peak < 3 * second:
        raise RuntimeError("Earth not unambiguous: peak {0:.1f} vs {1:.1f}".format(peak, second))
    # continuous native coordinates (origin = top-left corner of the frame)
    earth_native = ((ex0 + 0.5) / k, (ey0 + 0.5) / k)
    native_lum = np.asarray(src.convert("L").resize(NATIVE, Image.LANCZOS), dtype=np.float64)
    sun = measure_sun_axis(native_lum, (earth_native[0] - 0.5, earth_native[1] - 0.5))
    if not (45 < sun["sun_deg"] < 135):
        raise RuntimeError("Sun axis not toward the bottom as NASA states: {0}".format(sun))

    size = (NATIVE[0] * OUT_SCALE, NATIVE[1] * OUT_SCALE)
    small = src.resize(size, Image.LANCZOS)
    for q in (92, 88, 85, 82, 78, 74, 70, 65):   # smooth gradients band below ~85
        buf = io.BytesIO()
        small.save(buf, "JPEG", quality=q, optimize=True, progressive=True)
        if buf.tell() <= MAX_BYTES:
            break
    (d / "pale-blue-dot.jpg").write_bytes(buf.getvalue())
    jpeg_bytes, jpeg_q = buf.tell(), q
    p = P_NATIVE / OUT_SCALE
    earth_px = (earth_native[0] * OUT_SCALE, earth_native[1] * OUT_SCALE)

    # 2. positions ---------------------------------------------------------
    v1 = baked_position(out, "voyager1", UTC)
    ea = baked_position(out, "earth", UTC)
    view = unit(ea - v1)
    sun_dir = unit(-v1)
    dist_au = float(np.linalg.norm(ea - v1))
    elong = float(np.degrees(np.arccos(np.clip(np.dot(view, sun_dir), -1, 1))))
    check = {}
    try:
        hv1 = horizons_vec("-31", "500@10")
        he = horizons_vec("399", "500@10")
        e_lt = horizons_vec("399", "500@-31", "LT")
        check = {
            "horizons_v1_au": [round(float(x), 7) for x in hv1],
            "horizons_earth_au": [round(float(x), 7) for x in he],
            "baked_minus_horizons_v1_km": round(float(np.linalg.norm(hv1 - v1) * AU_KM)),
            "baked_minus_horizons_earth_km": round(float(np.linalg.norm(he - ea) * AU_KM)),
            "earth_dir_error_arcsec": round(float(np.degrees(np.arccos(np.clip(
                np.dot(view, unit(he - hv1)), -1, 1))) * 3600), 3),
            "light_time_corrected_earth_offset_arcsec": round(float(np.degrees(np.arccos(np.clip(
                np.dot(view, unit(e_lt)), -1, 1))) * 3600), 2),
        }
    except Exception as exc:  # loud; the baked numbers stand on their own
        print("  WARN Horizons cross-check failed: {0}".format(exc))

    # 3. camera ------------------------------------------------------------
    def solve(sun_img_deg):
        f, rr, uu = camera(view, sun_dir, sun_img_deg, earth_px, size, p)
        ep = to_px(view, f, rr, uu, size, p)
        sp = to_px(sun_dir, f, rr, uu, size, p)
        ang = float(np.degrees(np.arctan2(sp[1] - ep[1], sp[0] - ep[0])))
        north = to_px(unit(view + 1e-4 * np.array([0, 0, 1.0])), f, rr, uu, size, p)
        north_deg = float(np.degrees(np.arctan2(north[1] - ep[1], north[0] - ep[0])))
        return f, rr, uu, ep, sp, ang, north_deg

    f, rr, uu, ep, sp, ang, north_deg = solve(sun["sun_deg"])
    fa, ra, ua, epa, spa, anga, north_a = solve(sun["sun_deg"] - 180.0)
    err = float(np.hypot(ep[0] - earth_px[0], ep[1] - earth_px[1]))
    sun_off = not (0 <= sp[0] <= size[0] and 0 <= sp[1] <= size[1])
    if err > 0.05 or not sun_off or abs((ang - sun["sun_deg"] + 180) % 360 - 180) > 0.05:
        raise RuntimeError("camera solve failed: earth err {0:.3f}px sun {1}".format(err, sp))

    fov_x = float(np.degrees(2 * np.arctan(size[0] / 2.0 * p)))
    fov_y = float(np.degrees(2 * np.arctan(size[1] / 2.0 * p)))
    r6 = lambda v: [round(float(x), 9) for x in v]  # noqa: E731
    doc = {
        "schema": "voyager.pbd/1",
        "utc": UTC.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "image": "pbd/pale-blue-dot.jpg",
        "width_px": size[0], "height_px": size[1],
        "fov_deg_x": round(fov_x, 6), "fov_deg_y": round(fov_y, 6),
        "projection": "gnomonic (pinhole); image centre = center_dir_ecl; px origin top-left, y down, "
                      "continuous coords (pixel i spans [i, i+1))",
        "tan_per_px": p,
        "earth_px": [round(earth_px[0], 2), round(earth_px[1], 2)],
        "earth_uv": [round(earth_px[0] / size[0], 5), round(earth_px[1] / size[1], 5)],
        "v1_au": r6(v1), "earth_au": r6(ea),
        "v1_earth_distance_au": round(dist_au, 5),
        "v1_earth_distance_km": int(round(dist_au * AU_KM, -3)),
        "v1_sun_distance_au": round(float(np.linalg.norm(v1)), 5),
        "v1_ecliptic_lat_deg": round(float(np.degrees(np.arcsin(v1[2] / np.linalg.norm(v1)))), 3),
        "earth_sun_elongation_deg": round(elong, 4),
        "view_dir_ecl": r6(view),
        "center_dir_ecl": r6(f),
        "up_ecl": r6(uu),
        "right_ecl": r6(rr),
        "sun_dir_ecl": r6(sun_dir),
        "sun_image_dir_deg": round(sun["sun_deg"], 2),
        "ecliptic_north_image_dir_deg": round(north_deg, 2),
        "roll_method": "derived-from-sun",
        "roll_note": ("No archived pointing exists for this frame (PDS VGISS ends 1989-09-29; NAIF "
                      "Voyager 1 CK is bus-only). Image-up chosen so the real Sun direction projects "
                      "along the measured sunward axis: the main scattered-light ray and the "
                      "brightness gradient, toward the bottom as the PIA23645 caption states. "
                      "Axis good to ~+-2 deg; the sign rests on the NASA caption (see alt)."),
        "alt_sun_toward_top": {
            "note": "180-deg roll alternative, as the 1990 composite PIA00450 orients the Earth inset",
            "center_dir_ecl": r6(fa), "up_ecl": r6(ua), "right_ecl": r6(ra),
            "ecliptic_north_image_dir_deg": round(north_a, 2),
        },
        "measurements": {
            "source_jpeg_px": [W0, H0], "source_scale_vs_native": round(k, 4),
            "earth_px_source": [round(ex0, 2), round(ey0, 2)],
            "earth_px_native": [round(earth_native[0], 2), round(earth_native[1], 2)],
            "main_ray_native": "x = {0:.2f} + {1:.4f} * y  (rms {2:.2f} px, {3} rows)".format(
                sun["ray_a"], sun["ray_b"], sun["ray_rms_px"], sun["ray_points"]),
            "main_ray_offset_at_earth_px": round(sun["ray_offset_at_earth_px"], 2),
            "ray_axis_deg": round(sun["ray_deg"], 2),
            "brightness_gradient_deg": round(sun["gradient_deg"], 2),
            "jpeg_bytes": jpeg_bytes, "jpeg_quality": jpeg_q,
        },
        "validation": {
            "earth_projects_to_px": [round(ep[0], 3), round(ep[1], 3)],
            "earth_error_px": round(err, 4),
            "sun_projects_to_px": [round(sp[0], 1), round(sp[1], 1)],
            "sun_off_frame": bool(sun_off),
            "sun_from_earth_image_dir_deg": round(ang, 2),
            "sun_distance_from_earth_native_px": round(float(np.hypot(sp[0] - ep[0], sp[1] - ep[1])) / OUT_SCALE, 1),
        },
        "horizons_check": check,
        "camera": {"instrument": "Voyager 1 ISS narrow-angle camera (1500 mm f/8.5, 800x800 vidicon)",
                   "filters_exposures_s": {"violet": 0.72, "blue": 0.72, "green": 0.48},
                   "nac_fov_deg": 0.424, "native_frame_crop_px": list(NATIVE),
                   "crop_note": "PIA23645 is a 666x659 crop of the 800x800 frame (Figure A, native "
                                "resolution); NASA's JPEG is it upsampled x7.853; this file is x2."},
        "credit": "NASA/JPL-Caltech (Pale Blue Dot Revisited, PIA23645; processing Kevin M. Gill)",
        "license": ("NASA/JPL mission imagery, not copyrighted (public domain in the US); JPL Image Use "
                    "Policy: usable for any purpose without prior permission, with the caption's "
                    "credit line"),
        "sources": [
            "https://science.nasa.gov/photojournal/pale-blue-dot-revisited (PIA23645)",
            "https://science.nasa.gov/photojournal/solar-system-portrait-earth-as-pale-blue-dot (PIA00452)",
            "https://science.nasa.gov/photojournal/solar-system-portrait-view-of-the-sun-earth-and-venus (PIA00450)",
            "https://naif.jpl.nasa.gov/pub/naif/VOYAGER/kernels/ik/vg1_issna_v02.ti",
            "https://ssd.jpl.nasa.gov/api/horizons.api",
            "https://www.jpl.nasa.gov/jpl-image-use-policy",
        ],
    }
    (d / "pbd.json").write_text(json.dumps(doc, indent=1))
    if verbose:
        print("  image {0}x{1} -> {2}x{3}  {4} KB (q{5})".format(W0, H0, size[0], size[1], jpeg_bytes // 1024, jpeg_q))
        print("  earth_px {0:.2f},{1:.2f}  (native {2:.2f},{3:.2f}); main ray passes {4:+.2f} px from it".format(
            earth_px[0], earth_px[1], earth_native[0], earth_native[1], sun["ray_offset_at_earth_px"]))
        print("  sun axis: ray {0:.2f} deg, gradient {1:.2f} deg -> {2:.2f} deg (y down)".format(
            sun["ray_deg"], sun["gradient_deg"], sun["sun_deg"]))
        print("  V1-Earth {0:.4f} au, elongation {1:.4f} deg, V1 ecl lat {2:.2f}".format(
            dist_au, elong, doc["v1_ecliptic_lat_deg"]))
        print("  validate: Earth -> ({0:.3f},{1:.3f}) err {2:.4f}px; Sun -> ({3:.0f},{4:.0f}) off-frame={5} "
              "dir {6:.2f} deg; ecl north at {7:.1f} deg".format(ep[0], ep[1], err, sp[0], sp[1], sun_off, ang, north_deg))
        if check:
            print("  horizons: V1 {0} km, Earth {1} km, Earth dir {2}\"; light-time shift {3}\"".format(
                check["baked_minus_horizons_v1_km"], check["baked_minus_horizons_earth_km"],
                check["earth_dir_error_arcsec"], check["light_time_corrected_earth_offset_arcsec"]))
    return doc
