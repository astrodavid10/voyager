"""Family Portrait mosaic as a warped mesh that lines up EXACTLY from Voyager 1.

Run after ``family`` (offline: reads family.json and the saved mosaic JPEG):

    python -m pipeline family_mesh --out public/data

Why: PIA00451 is a hand-assembled mosaic, not a projection.  The flat-card fit in
family.json is off by up to 0.6 deg (50 px at Saturn) and, because its best tangent
point is 49 deg from the image center, it reads as a steeply tilted card.  Here the
mosaic becomes a grid of sky DIRECTIONS instead:

  1. a conformal (stereographic) sky->image fit with a free center (the mosaic's
     frames stay square, so it is locally conformal), then
  2. a thin-plate-spline correction in image space that sends every planet letter
     (J, E, V, S, U, N) and the Sun exactly onto its 1990 direction from Voyager 1.

Seen from Voyager 1's position the image then sits undistorted on the sky with
every letter on its planet.  Between the control points it is an interpolation
(the mosaic itself is only good to ~1 deg), which the note in the JSON says.

Also writes ``family/mosaic-pia00451-clean.jpg``: the mosaic without NASA's six
labeled inset thumbnails, which sit around its edge at arbitrary places (they read
as planets in the wrong spots).  Each planet's own narrow-angle frame is already
shown at its true position by the app.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy.interpolate import RBFInterpolator
from scipy.optimize import minimize

from .family import tangent_basis
from .pbd import unit

# Inset thumbnails + their captions in the saved 3000x900 JPEG (x0, y0, x1, y1).
INSETS = {
    "JUPITER": (84, 282, 224, 458), "EARTH": (189, 492, 325, 669), "VENUS": (293, 701, 431, 879),
    "SATURN": (1289, 689, 1428, 869), "URANUS": (1901, 451, 2040, 626), "NEPTUNE": (2687, 695, 2848, 873),
}
NX, NY = 97, 31          # mesh vertices across x, y (image is 3000 x 900)


def stereo_fit(img_pts: dict, dirs: dict):
    """Stereographic sky->pixel similarity fit; returns (c, b1, b2, a, b, tx, ty, rms)."""
    keys = list(img_pts)
    c0 = unit(sum(dirs[k] for k in keys))
    e1, e2 = tangent_basis(c0)

    def proj(d, c):
        b1, b2 = tangent_basis(c)
        k_ = 2.0 / (1.0 + np.clip(d @ c, -1, 1))
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
                 options={"xatol": 1e-8, "fatol": 1e-7, "maxiter": 6000}).x
    c = cen(t)
    sol, rms = solve(c)
    b1, b2 = tangent_basis(c)
    return c, b1, b2, sol, rms, proj


def run(out: Path) -> dict:
    d = out / "pbd"
    fam = json.loads((d / "family.json").read_text())
    m = fam["mosaic"]
    v1 = np.array(fam["v1_au"])
    dirs = {f["planet"]: unit(np.array(f["planet_au"]) - v1) for f in fam["frames"]}
    dirs["Sun"] = unit(-v1)
    s = m["width_px"] / 4000.0                           # fit points are in the 4000x1200 original
    pts = {k: np.array(v) * s for k, v in m["fit_points"].items() if k in dirs}

    c, b1, b2, (a, bb, tx, ty), rms, proj = stereo_fit(pts, dirs)
    to_px = lambda dd: np.array([a * proj(dd, c)[0] - bb * proj(dd, c)[1] + tx,  # noqa: E731
                                 bb * proj(dd, c)[0] + a * proj(dd, c)[1] + ty])
    keys = list(pts)
    lab = np.array([pts[k] for k in keys])
    want = np.array([to_px(dirs[k]) for k in keys])
    # image px -> "ideal" stereographic px; exact at every letter.
    tps = RBFInterpolator(lab, want - lab, kernel="thin_plate_spline", degree=1, smoothing=0.0)

    det = a * a + bb * bb

    def px_to_dir(p):
        q = p + tps(p)                                   # (n, 2)
        X = (a * (q[:, 0] - tx) + bb * (q[:, 1] - ty)) / det
        Y = (-bb * (q[:, 0] - tx) + a * (q[:, 1] - ty)) / det
        r2 = X * X + Y * Y
        z = (4 - r2) / (4 + r2)
        out_ = z[:, None] * c + ((1 + z) / 2)[:, None] * (X[:, None] * b1 + Y[:, None] * b2)
        return out_ / np.linalg.norm(out_, axis=1)[:, None]

    W, H = m["width_px"], m["height_px"]
    gx, gy = np.meshgrid(np.linspace(0, W, NX), np.linspace(0, H, NY))
    grid = np.stack([gx.ravel(), gy.ravel()], 1)
    gdir = px_to_dir(grid)
    # validation: letters -> directions
    back = px_to_dir(lab)
    err = {k: round(float(np.degrees(np.arccos(np.clip(back[i] @ dirs[k], -1, 1)))), 6) for i, k in enumerate(keys)}
    span = np.degrees(np.arccos(np.clip(gdir[NX * (NY // 2)] @ gdir[NX * (NY // 2) + NX - 1], -1, 1)))
    centre = unit(px_to_dir(np.array([[W / 2, H / 2]]))[0])
    up = unit(px_to_dir(np.array([[W / 2, H / 2 - 20]]))[0] - centre)
    print("  stereographic rms {0:.1f} px; letters after warp (deg): {1}; width {2:.1f} deg".format(rms, err, span))

    im = Image.open(d / "family" / "mosaic-pia00451.jpg").convert("RGB")
    dr = ImageDraw.Draw(im)
    for box in INSETS.values():
        dr.rectangle(box, fill=(0, 0, 0))
    im.save(d / "family" / "mosaic-pia00451-clean.jpg", quality=86, optimize=True)

    m["mesh"] = {
        "image": "pbd/family/mosaic-pia00451-clean.jpg",
        "nx": NX, "ny": NY,
        "dirs": [round(float(x), 6) for x in gdir.ravel()],
        "center_dir_ecl": [round(float(x), 6) for x in centre],
        "up_ecl": [round(float(x), 6) for x in up],
        "letter_error_deg": err,
        "stereographic_rms_px": round(rms, 1),
        "note": ("Rows top->bottom, columns left->right, uv = (col/(nx-1), 1-row/(ny-1)). Each vertex "
                 "is a unit sky direction from Voyager 1 (place at v1 + D*dir). Stereographic fit plus "
                 "a thin-plate correction so each planet letter lands on its planet; between letters it "
                 "is an interpolation of a hand-assembled mosaic (~1 deg). NASA's labeled inset "
                 "thumbnails are blanked in the -clean image."),
    }
    (d / "family.json").write_text(json.dumps(fam, indent=1))
    return m["mesh"]
