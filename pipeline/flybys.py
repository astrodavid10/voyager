"""Future stellar flybys of Voyager 1 (Gliese 445) and Voyager 2 (Ross 248).

Output: ``<out>/flybys.json``

Everything is in heliocentric ecliptic J2000, au, the frame of ``ephem/*.bin``.
Each body moves on a straight line: position(t) = r0 + v * t, with t in Julian
years from EPOCH (2026-11-11). The Sun is held at the origin.

  * Spacecraft: the hyperbolic asymptote of the last state in our own Horizons bake
    (ephem/voyagerN.bin, daily). The asymptotic speed comes from the energy
    integral (v_inf^2 = v^2 - 2GM/r), and the direction from the eccentricity
    vector (true anomaly -> arccos(-1/e)). r0 is the baked position on EPOCH.
  * Stars: Gaia DR3 astrometry plus Gaia DR3 radial velocity, fetched live from
    the ESA Gaia archive TAP. If the archive is unreachable, the snapshot in
    GAIA_SNAPSHOT (queried 2026-11-11) is used instead. Gaia's epoch is 2016.0, so
    each star is moved linearly to EPOCH.
  * The linear model ignores the Galaxy's potential, the Sun's own motion
    relative to the local standard of rest (this is a Sun-relative frame),
    and any perspective effects. Bailer-Jones & Farnocchia (2019) integrated
    through a Galactic potential using Gaia DR2 data; their values are reported
    alongside ours.

Run (conda env ``sdo``):  python -m pipeline flybys --out public/data
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import requests

AU_KM = 149597870.7
YR_S = 365.25 * 86400.0
KMS_AUYR = YR_S / AU_KM                      # 1 km/s = 0.2109 au/yr
LY_AU = 63241.077084                         # IAU light-year in au
PC_AU = 206264.806
GM_SUN = 1.32712440041e11                    # km^3/s^2
GM_SS = GM_SUN * 1.00134                     # Sun + planets (beyond ~100 au the craft feel the total)
EPOCH = date(2026, 11, 11)
GAIA_EPOCH = 2016.0

GAIA_TAP = "https://gea.esac.esa.int/tap-server/tap/sync"
STARS = {
    "gliese445": {"name": "Gliese 445", "alt": "AC +79 3888, GJ 445, Gaia DR3 1129149723913123456",
                  "source_id": 1129149723913123456, "sptype": "M4.0V"},
    "ross248": {"name": "Ross 248", "alt": "GJ 905, HH Andromedae, Gaia DR3 1926461164913660160",
                "source_id": 1926461164913660160, "sptype": "M5.0V"},
}
# Gaia DR3 snapshot (gaiadr3.gaia_source, queried 2026-11-11): ra, dec [deg], parallax [mas],
# pmra, pmdec [mas/yr], radial_velocity [km/s], with errors.
GAIA_SNAPSHOT = {
    1129149723913123456: dict(ra=176.9394079814786, dec=78.69329745305299, parallax=190.32514271529305,
                              parallax_error=0.019362431, pmra=748.4182886031707, pmdec=480.80430000482306,
                              radial_velocity=-111.504585, radial_velocity_error=0.15323243),
    1926461164913660160: dict(ra=355.4800152581559, dec=44.170375700747755, parallax=316.48118678226916,
                              parallax_error=0.044448785, pmra=112.52746493350043, pmdec=-1591.6497618145506,
                              radial_velocity=-77.289825, radial_velocity_error=0.18532437),
}

# Bailer-Jones & Farnocchia 2019, RNAAS 3, 59 (extended version arXiv:1912.03503, Table 1).
# Times are kyr "from now" (the paper is dated 2019); d in pc; 5th-95th percentiles in brackets.
BJF = {
    "asymptote_icrf": {  # barycentric ICRF RA, Dec (deg) and speed (km/s) leaving the solar system
        "voyager1": (262.8760, 12.3199, 16.6048),
        "voyager2": (316.2717, -67.5491, 14.8550),
    },
    "encounters": [
        ("voyager1", "Proxima Centauri", 16.7, (16.5, 16.9), 1.072, (1.061, 1.083), 43.2, "first encounter < ~1 pc"),
        ("voyager1", "TYC 3135-52-1", 302.7, (299.5, 306.1), 0.296, (0.289, 0.302), 46.5,
         "closest; star sits above the main sequence - possible binary, astrometry may be unreliable"),
        ("voyager1", "HD 28343", 487.5, (483.2, 492.3), 0.400, (0.395, 0.407), 22.5, "third closest"),
        ("voyager1", "Gaia DR2 2091429484365218432", 3405.3, (3224.4, 3595.7), 0.392, (0.229, 0.540), 45.9, "second closest"),
        ("voyager1", "Gliese 445", 44.0, (44.0, 44.1), 0.575, (0.574, 0.576), 116.0,
         "earliest encounter within 1 pc; the NASA 'AC+79 3888' flyby"),
        ("voyager2", "Proxima Centauri", 20.3, (20.2, 20.3), 0.878, (0.867, 0.890), 46.3, "first encounter"),
        ("voyager2", "Ross 248", 42.0, (41.9, 42.2), 0.529, (0.528, 0.531), 72.3, "closest; the NASA flyby"),
        ("voyager2", "Gaia DR2 4370380741264455296", 2245.6, (2168.4, 2334.7), 0.558, (0.319, 0.843), 69.9,
         "second closest, though the star is now 160 pc away"),
        ("voyager2", "h1 Sgr", 1965.4, (1810.8, 2141.0), 0.708, (0.480, 0.941), 40.9, "fourth closest; a delta Scuti star"),
    ],
}
NASA = [
    ("voyager1", "Gliese 445", 40000, 1.6,
     "JPL Voyager 'Interstellar Mission' page (now offline; widely quoted): 'within 1.6 light years ... of AC+79 3888' in ~40,000 yr. "
     "NASA image article 'Reaching for the Stars' (2013-09-11) gives 1.7 ly."),
    ("voyager2", "Ross 248", 40000, 1.7,
     "NASA/JPL Photojournal PIA22921 caption and JPL interstellar mission page: ~1.7 ly from Ross 248 in ~40,000 yr."),
]
PAIRS = [("voyager1", "gliese445"), ("voyager2", "ross248")]


def ecl_rotation():
    """3x3 matrix taking ICRS cartesian -> ecliptic J2000 cartesian (astropy)."""
    import astropy.units as u
    from astropy.coordinates import ICRS, BarycentricMeanEcliptic, CartesianRepresentation, SkyCoord
    cols = []
    for e in np.eye(3):
        c = SkyCoord(CartesianRepresentation(e * u.au), frame=ICRS())
        cols.append(c.transform_to(BarycentricMeanEcliptic(equinox="J2000")).cartesian.xyz.to(u.au).value)
    return np.array(cols).T


def radec_unit(ra, dec):
    a, d = math.radians(ra), math.radians(dec)
    return np.array([math.cos(d) * math.cos(a), math.cos(d) * math.sin(a), math.sin(d)])


def lonlat(v):
    v = np.asarray(v, float)
    r = np.linalg.norm(v)
    return float(math.degrees(math.atan2(v[1], v[0])) % 360.0), float(math.degrees(math.asin(v[2] / r)))


def fetch_gaia(ids):
    q = ("SELECT source_id, ra, dec, parallax, parallax_error, pmra, pmdec, radial_velocity, "
         "radial_velocity_error FROM gaiadr3.gaia_source WHERE source_id IN ({0})").format(",".join(str(i) for i in ids))
    try:
        r = requests.post(GAIA_TAP, data={"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "csv", "QUERY": q}, timeout=120)
        r.raise_for_status()
        lines = r.text.strip().splitlines()
        head = lines[0].split(",")
        rows = {}
        for ln in lines[1:]:
            vals = ln.split(",")
            d = {k: float(v) for k, v in zip(head[1:], vals[1:])}
            rows[int(vals[0])] = d
        if all(i in rows for i in ids):
            return rows, "Gaia DR3 (ESA Gaia archive TAP, live)"
    except Exception as exc:  # noqa: BLE001
        print("  Gaia TAP failed ({0}); using snapshot".format(exc))
    return GAIA_SNAPSHOT, "Gaia DR3 (snapshot queried 2026-11-11)"


def star_state(g, R):
    """Return (r_icrs_au at Gaia epoch, v_icrs_kms) from Gaia astrometry + RV."""
    ra, dec = math.radians(g["ra"]), math.radians(g["dec"])
    d_pc = 1000.0 / g["parallax"]
    rhat = np.array([math.cos(dec) * math.cos(ra), math.cos(dec) * math.sin(ra), math.sin(dec)])
    ehat = np.array([-math.sin(ra), math.cos(ra), 0.0])
    nhat = np.array([-math.sin(dec) * math.cos(ra), -math.sin(dec) * math.sin(ra), math.cos(dec)])
    k = 4.740470463533348  # km/s per (mas/yr * kpc) == au/yr -> km/s
    vt_e = k * g["pmra"] * d_pc / 1000.0
    vt_n = k * g["pmdec"] * d_pc / 1000.0
    v = g["radial_velocity"] * rhat + vt_e * ehat + vt_n * nhat
    return R @ (rhat * d_pc * PC_AU), R @ v, d_pc


def craft_asymptote(pos_au, day_index):
    """Hyperbolic asymptote from the state at day_index (central difference, daily samples)."""
    i = day_index
    r = pos_au[i] * AU_KM
    v = (pos_au[i + 1] - pos_au[i - 1]) * AU_KM / (2 * 86400.0)
    rn, vn = np.linalg.norm(r), np.linalg.norm(v)
    eps = vn * vn / 2 - GM_SS / rn
    vinf = math.sqrt(2 * eps)
    h = np.cross(r, v)
    evec = np.cross(v, h) / GM_SS - r / rn
    e = np.linalg.norm(evec)
    p = evec / e
    q = np.cross(h / np.linalg.norm(h), p)
    nu = math.acos(-1.0 / e)
    vhat = math.cos(nu) * p + math.sin(nu) * q
    return vinf, vhat, vn, rn / AU_KM, e


def closest(r1, v1, r2, v2):
    """Closest approach of two linear tracks; r in au, v in au/yr. Returns (t_yr, d_au, v_rel_kms)."""
    dr, dv = np.asarray(r2) - np.asarray(r1), np.asarray(v2) - np.asarray(v1)
    t = -float(dr @ dv) / float(dv @ dv)
    d = float(np.linalg.norm(dr + dv * t))
    return t, d, float(np.linalg.norm(dv)) / KMS_AUYR


def run(out: Path) -> dict:
    out = Path(out)
    meta = json.loads((out / "ephem" / "trajectories.json").read_text(encoding="utf-8"))
    R = ecl_rotation()
    epoch_yr = 2026 + (EPOCH - date(2026, 1, 1)).days / 365.25

    bodies, crafts = [], {}
    for cid in ("voyager1", "voyager2"):
        b = next(x for x in meta["bodies"] if x["id"] == cid)
        pos = np.fromfile(out / b["file"], dtype="<f4").reshape(-1, 3).astype(np.float64)
        start = date.fromisoformat(b["start"])
        step = int(b["step_days"])
        assert step == 1, "flybys expects a daily bake"
        i_ep = (EPOCH - start).days
        i_last = len(pos) - 2
        vinf, vhat, vlast, rlast, ecc = craft_asymptote(pos, i_last)
        # cross-check: same calculation 10 years earlier should give the same asymptote
        vinf_b, vhat_b, *_ = craft_asymptote(pos, i_last - 3652)
        ra, dec, vb = BJF["asymptote_icrf"][cid]
        bj_hat = R @ radec_unit(ra, dec)
        ang = math.degrees(math.acos(max(-1.0, min(1.0, float(vhat @ bj_hat)))))
        r0 = pos[i_ep]
        v_auyr = vhat * vinf * KMS_AUYR
        lon, lat = lonlat(vhat)
        bjlon, bjlat = lonlat(bj_hat)
        crafts[cid] = (r0, v_auyr)
        bodies.append({
            "id": cid, "kind": "spacecraft", "name": b["name"], "color": b.get("color"),
            "r0_au": [round(float(x), 4) for x in r0],
            "v_au_per_yr": [round(float(x), 6) for x in v_auyr],
            "v_kms": [round(float(x), 5) for x in vhat * vinf],
            "speed_kms": round(vinf, 4),
            "dir_unit": [round(float(x), 7) for x in vhat],
            "dir_ecl_lon_lat_deg": [round(lon, 3), round(lat, 3)],
            "derivation": ("hyperbolic asymptote of the last baked state ({0}, r = {1:.2f} au, v = {2:.3f} km/s, e = {3:.3f}); "
                           "GM = Sun + planets. Same calculation 10 yr earlier: v_inf {4:.4f} km/s, direction differs by {5:.4f} deg.").format(
                (start.fromordinal(start.toordinal() + i_last)).isoformat(), rlast, vlast, ecc, vinf_b,
                math.degrees(math.acos(min(1.0, float(vhat @ vhat_b))))),
            "check_bailer_jones_2019": {"speed_kms": vb, "dir_ecl_lon_lat_deg": [round(bjlon, 3), round(bjlat, 3)],
                                        "angle_to_ours_deg": round(ang, 3),
                                        "note": "converted from their barycentric ICRF RA/Dec"},
        })

    gaia, gsrc = fetch_gaia([s["source_id"] for s in STARS.values()])
    stars = {}
    for sid, s in STARS.items():
        g = gaia[s["source_id"]]
        r16, v, d_pc = star_state(g, R)
        v_auyr = v * KMS_AUYR
        r0 = r16 + v_auyr * (epoch_yr - GAIA_EPOCH)
        stars[sid] = (r0, v_auyr)
        tsun, dsun, _ = closest(np.zeros(3), np.zeros(3), r0, v_auyr)
        lon, lat = lonlat(r0)
        bodies.append({
            "id": sid, "kind": "star", "name": s["name"], "aka": s["alt"], "sptype": s["sptype"],
            "r0_au": [round(float(x), 1) for x in r0],
            "v_au_per_yr": [round(float(x), 5) for x in v_auyr],
            "v_kms": [round(float(x), 4) for x in v],
            "speed_kms": round(float(np.linalg.norm(v)), 3),
            "dist_now_ly": round(float(np.linalg.norm(r0)) / LY_AU, 4),
            "ecl_lon_lat_deg": [round(lon, 4), round(lat, 4)],
            "gaia_dr3": {k: g[k] for k in ("ra", "dec", "parallax", "parallax_error", "pmra", "pmdec",
                                            "radial_velocity", "radial_velocity_error")},
            "gaia_ref_epoch": GAIA_EPOCH,
            "closest_to_sun_linear": {"t_years": round(tsun, 0), "dist_ly": round(dsun / LY_AU, 3),
                                      "dist_pc": round(dsun / PC_AU, 3)},
        })

    encounters = []
    for cid, sid in PAIRS:
        rc, vc = crafts[cid]
        rs, vs = stars[sid]
        t, d, vrel = closest(rc, vc, rs, vs)
        # how far the Sun is from the craft at that moment (the craft is then nearer the star than the Sun?)
        dsun = float(np.linalg.norm(rc + vc * t))
        tcross = None
        # first time the craft is nearer the star than the Sun
        ts = np.linspace(0, 2 * t, 20001)
        nearer = np.linalg.norm((rs - rc)[None, :] + (vs - vc)[None, :] * ts[:, None], axis=1) < \
            np.linalg.norm(rc[None, :] + vc[None, :] * ts[:, None], axis=1)
        if nearer.any():
            tcross = float(ts[np.argmax(nearer)])
        encounters.append({
            "craft": cid, "star": STARS[sid]["name"], "t_years": round(t, 0),
            "year_ce": round(epoch_yr + t, 0),
            "min_dist_ly": round(d / LY_AU, 4), "min_dist_au": round(d, 0), "min_dist_pc": round(d / PC_AU, 4),
            "v_rel_kms": round(vrel, 2), "craft_sun_dist_ly_then": round(dsun / LY_AU, 3),
            "craft_nearer_star_than_sun_from_t_years": None if tcross is None else round(tcross, 0),
            "source": "this pipeline: straight-line model, t from {0}; {1}; craft = asymptote of our Horizons bake".format(
                EPOCH.isoformat(), gsrc),
        })
    for cid, star, tk, tci, dpc, dci, vrel, note in BJF["encounters"]:
        encounters.append({
            "craft": cid, "star": star, "t_years": tk * 1000.0, "t_years_5_95": [tci[0] * 1000.0, tci[1] * 1000.0],
            "min_dist_ly": round(dpc * PC_AU / LY_AU, 3), "min_dist_au": round(dpc * PC_AU, -2),
            "min_dist_pc": dpc, "min_dist_pc_5_95": list(dci), "v_rel_kms": vrel,
            "source": "Bailer-Jones & Farnocchia 2019, RNAAS 3, 59 (arXiv:1912.03503 Table 1); Gaia DR2, Galactic potential; t from ~2019",
            "note": note,
        })
    for cid, star, t, ly, src in NASA:
        encounters.append({"craft": cid, "star": star, "t_years": t, "min_dist_ly": ly,
                           "min_dist_au": round(ly * LY_AU, -3), "source": "NASA/JPL (classic, pre-Gaia): " + src})

    res = {
        "schema": "voyager.flybys/1",
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "frame": "heliocentric ecliptic J2000, au (same as ephem/*.bin); Sun fixed at origin",
        "epoch": EPOCH.isoformat(),
        "model": "position(t) = r0_au + v_au_per_yr * t, t in Julian years from epoch (negative = past)",
        "units": {"au_per_ly": LY_AU, "au_per_pc": PC_AU, "kms_to_au_per_yr": KMS_AUYR},
        "bodies": bodies,
        "encounters": encounters,
        "notes": [
            "Gliese 445 does most of the traveling: it is falling toward the Sun at ~111 km/s (Gaia DR3 RV) "
            "while Voyager 1 recedes at 16.6 km/s. In ~44,000 yr the star itself passes ~1.0 pc (3.3 ly) from the "
            "Sun (our linear model; see bodies[].closest_to_sun_linear).",
            "Gaia-era distances (Bailer-Jones & Farnocchia 2019): V1-Gliese 445 0.575 pc = 1.88 ly at 44.0 kyr; "
            "V2-Ross 248 0.529 pc = 1.73 ly at 42.0 kyr. NASA's classic 1.6 / 1.7 ly at ~40 kyr are close; "
            "V1's is ~0.3 ly too small.",
            "Neither flyby is Voyager's closest. With Gaia DR2, V1's closest known star is TYC 3135-52-1 (0.30 pc, "
            "~303 kyr; possibly binary) and Proxima Centauri comes first for both craft (~1 pc at 17-20 kyr).",
            "Our straight-line model (Gaia DR3, no Galactic gravity) reproduces Bailer-Jones & Farnocchia (Gaia DR2, "
            "Galactic potential) to <1% in distance and time for both flybys: over ~40 kyr these nearby stars barely "
            "feel the Galaxy, and the remaining differences are mostly DR2 -> DR3 astrometry.",
            "The craft's r0 is its baked position on the epoch; the velocity is the asymptote (the craft are still "
            "slowing by ~0.3 km/s, a positional error of a few hundred au over 40 kyr, negligible against ~1e5 au).",
        ],
    }
    (out / "flybys.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    print("  -> {0}".format(out / "flybys.json"))
    for b in bodies:
        if b["kind"] == "spacecraft":
            print("  {0}: v_inf {1} km/s dir {2}  (BJF {3} km/s, {4} deg apart)".format(
                b["id"], b["speed_kms"], b["dir_ecl_lon_lat_deg"], b["check_bailer_jones_2019"]["speed_kms"],
                b["check_bailer_jones_2019"]["angle_to_ours_deg"]))
        else:
            print("  {0}: {1} ly now, {2} km/s; closest to Sun {3}".format(b["id"], b["dist_now_ly"], b["speed_kms"],
                                                                           b["closest_to_sun_linear"]))
    for e in encounters:
        print("  {0} {1:28s} t={2:>9} yr  d={3} ly  [{4}]".format(e["craft"], e["star"], e["t_years"], e["min_dist_ly"], e["source"][:40]))
    return res
