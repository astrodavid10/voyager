"""The Golden Record pulsar map: 14 pulsars + the Galactic-center line.

Output: ``<out>/pulsars.json``

What is in it
  * The 14 pulsars on the Voyager record cover (the same map as the Pioneer 10/11
    plaques; NASA: the cover "repeats the pulsar map from the Pioneer plaques").
    Identifications: Johnston, "Pulsar map" (johnstonsarchive.net/astro/pulsarmap.html),
    which matches every binary period on the map to one pulsar.
  * Current ATNF Pulsar Catalogue values, fetched live from the psrcat web form
    (Manchester et al. 2005, AJ 129, 1993): GL, GB, DIST, DIST_DM, PX, DIST_A,
    P0, P1, DM, PEPOCH.
  * The period encoded on the map, as the integer number of hydrogen 21-cm
    periods (Johnston's decoding of the binary), and that integer x the H period.
  * Heliocentric ecliptic-J2000 xyz in au from (l, b, DIST) via astropy
    Galactic -> BarycentricMeanEcliptic(equinox J2000).  The ~au offset between
    the Sun and the barycentre is irrelevant at kpc distances.
  * The map as drawn: line angle and length for every line, digitised by eye
    from NASA's photograph of the cover (see DRAWN below - approximate).

Run (conda env ``sdo``):  python -m pipeline pulsars --out public/data
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import requests

KPC_AU = 2.06264806e8                 # 1 kpc in au
H_FREQ_HZ = 1420405751.768            # H I hyperfine transition (Hellwig+ 1970)
H_PERIOD_S = 1.0 / H_FREQ_HZ          # 7.0402e-10 s
NOW_ISO = "2026-11-11"                # epoch for extrapolated periods (story "today")
NOW_MJD = 61355.0                     # MJD of NOW_ISO

ATNF_FORM = "https://www.atnf.csiro.au/research/pulsar/psrcat/proc_form.php"
ATNF_HOME = "https://www.atnf.csiro.au/research/pulsar/psrcat/"

# GRAVITY Collaboration 2019, A&A 625, L10: R0 = 8178 +/- 13 (stat) +/- 22 (sys) pc.
GC_DIST_KPC = 8.178
GC_ALT = {"dist_kpc": 8.275, "source": "GRAVITY Collaboration 2021, A&A 647, A59 (8275 +/- 9 +/- 33 pc)"}

# Map order follows Johnston's numbering (clockwise listing from the GC line).
# (map #, B-name, J-name, map period in H-units [Johnston decoding of the binary],
#  Johnston's map distance reading with GC line = 100, Johnston's implied map distance pc,
#  Johnston's derived epoch of the period)
JOHNSTON = [
    (1, "B1727-47", "J1731-4744", 1178486506, 27, 2300, 1970.1),
    (2, "B1451-68", "J1456-6843", 374101871, 2, 160, 1969.0),
    (3, "B1240-64", "J1243-6423", 551117432, 56, 4700, 1969.1),
    (4, "B0833-45", "J0835-4510", 126726823, 15, 1300, 1971.7),
    (5, "B0950+08", "J0953+0755", 359455043, 1, 120, 1968.9),
    (6, "B0823+26", "J0826+2637", 753751947, 2, 160, 1969.8),
    (7, "B0531+21", "J0534+2200", 47057538, 18, 1500, 1969.9),
    (8, "B0525+21", "J0528+2200", 5320116676, 11, 980, 1966.7),
    (9, "B0329+54", "J0332+5434", 1014906390, 7, 570, 1970.2),
    (10, "B2217+47", "J2219+4754", 764842161, 10, 850, 1969.9),
    (11, "B2016+28", "J2018+2839", 792520205, 3, 280, 1969.9),
    (12, "B1933+16", "J1935+1616", 509549854, 40, 3400, 1970.2),
    (13, "B1929+10", "J1932+1059", 321746104, 1, 81, 1971.3),
    (14, "B1642-03", "J1645-0317", 550675372, 4, 320, None),  # Johnston: date discordant, discarded
]

NOTES = {
    "B0531+21": "The Crab pulsar. Young and slowing fast (P1 ~ 4e-13), so its map period is "
                "already ~1% short of today's - the map is a clock as well as a map.",
    "B0833-45": "The Vela pulsar; glitches. The map period is ~0.01% short of today's.",
    "B1240-64": "Its period was then known only to 3 digits (0.388 s) but is written on the map "
                "to ~10 digits, so the map value is ~0.1% off (Wikipedia, Pioneer plaque, citing "
                "Sagan, Sagan & Drake 1972, Science 175, 881).",
    "B1727-47": "Johnston notes the period used for the map was later corrected.",
    "B0950+08": "Distance now from VLBI parallax (0.26 kpc).",
    "B1929+10": "Distance now from VLBI parallax; the nearest of the 14.",
    "B0329+54": "The brightest pulsar in the northern sky.",
    "B1642-03": "Johnston could not get a consistent epoch from this period.",
    "B0525+21": "Longest period on the map (3.745 s).",
}

# ---- The map as drawn -------------------------------------------------------------
# Line END points digitised by eye from NASA's photograph of the Voyager cover
# (https://science.nasa.gov/mission/voyager/golden-record-cover/, 2400 px rendition),
# in a 2x crop with origin at full-image (190, 620) px of the 1200-px rendition.
# Precision ~ +/-2 deg and +/-0.02 GC-line lengths (photo is slightly oblique).
# The Crab and B0525+21 lines are almost parallel (l = 184.6 and 183.9); which of the
# two left-pointing lines is which was assigned by Johnston's relative lengths (U).
DRAWN_SUN = (405.0, 467.0)
DRAWN_GC_END = (1340.0, 475.0)
DRAWN = {
    "B1727-47": (860, 605), "B1451-68": (533, 612), "B1240-64": (680, 895),
    "B0833-45": (373, 775), "B0950+08": (278, 610), "B0823+26": (198, 530),
    "B0531+21": (44, 496), "B0525+21": (76, 480), "B0329+54": (207, 337),
    "B2217+47": (357, 178), "B2016+28": (483, 272), "B1933+16": (728, 58),
    "B1929+10": (545, 318), "B1642-03": (672, 405),
}


def _f(s):
    s = (s or "").strip()
    if s in ("", "*"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


FIELDS = ["Name", "JName", "GL", "GB", "P0", "P1", "DM", "PEpoch", "Dist", "Dist_DM", "PX",
          "DIST_A", "DIST_AMN", "DIST_AMX", "Assoc"]


def fetch_atnf(jnames):
    params = {k: k for k in FIELDS}
    params.update({
        "startUserDefined": "true", "sort_attr": "jname", "sort_order": "asc",
        "condition": "", "pulsar_names": "\r\n".join(jnames), "ephemeris": "short",
        "coords_unit": "raj/decj", "style": "Long csv with errors", "no_value": "*",
        "fsize": "3", "state": "query", "table_bottom.x": "40", "table_bottom.y": "22",
    })
    r = requests.get(ATNF_FORM, params=params, timeout=120)
    r.raise_for_status()
    body = r.text.split("<pre>", 1)[1].split("</pre>", 1)[0].strip().splitlines()
    # Header names the value columns; the unnamed columns after each are its error / reference.
    head = body[0].split(";")
    col = {name.strip().upper(): i for i, name in enumerate(head) if name.strip() and name.strip() != "#"}
    rows = {}
    for line in body[2:]:
        c = line.split(";")
        if not c or not c[0].strip().isdigit():
            continue

        def v(name, off=0, num=True):
            i = col.get(name)
            if i is None or i + off >= len(c):
                return None
            return _f(c[i + off]) if num else (c[i + off].strip() if c[i + off].strip() not in ("", "*") else None)

        rows[v("PSRJ", num=False)] = {
            "bname": v("NAME", num=False), "jname": v("PSRJ", num=False),
            "gl": v("GL"), "gb": v("GB"),
            "p0_s": v("P0"), "p0_ref": v("P0", 2, False),
            "p1": v("P1"), "dm": v("DM"), "pepoch_mjd": v("PEPOCH"),
            "dist_kpc": v("DIST"), "dist_dm_kpc": v("DIST_DM"), "dist_dm_ref": v("DIST_DM", 1, False),
            "px_mas": v("PX"), "px_err": v("PX", 1), "px_ref": v("PX", 2, False),
            "dist_a_kpc": v("DIST_A"), "dist_a_ref": v("DIST_A", 2, False),
            "dist_amn_kpc": v("DIST_AMN"), "dist_amx_kpc": v("DIST_AMX"), "dist_am_ref": v("DIST_AMN", 1, False),
            "assoc": v("ASSOC", num=False),
        }
    version = None
    try:
        h = requests.get(ATNF_HOME, timeout=60).text
        i = h.find("Catalog Version")
        if i >= 0:
            version = h[i:i + 40].split('"')[0].strip()
    except Exception:
        pass
    return rows, version


def _eq(a, b):
    return a is not None and b is not None and abs(a - b) < 1e-6


def dist_method(a):
    d = a["dist_kpc"]
    if d is None:
        return "none"
    px = ""
    if a["px_mas"] and a["px_err"]:
        px = "; parallax {0} +/- {1} mas ({2})".format(a["px_mas"], a["px_err"], a["px_ref"])
    if _eq(d, a["dist_a_kpc"]):
        return "independent (non-DM) distance, ref {0}{1}".format(a["dist_a_ref"], px)
    if _eq(d, a["dist_amx_kpc"]) or _eq(d, a["dist_amn_kpc"]):
        return "independent range {0}-{1} kpc, ref {2}{3}{4}".format(
            a["dist_amn_kpc"], a["dist_amx_kpc"], a["dist_am_ref"],
            "; assoc " + a["assoc"] if a["assoc"] else "", px)
    if px and abs(d - 1.0 / a["px_mas"]) / d < 0.15:
        return "parallax" + px
    if _eq(d, a["dist_dm_kpc"]):
        return "dispersion measure, YMW16 electron-density model ({0})".format(a["dist_dm_ref"])
    return "ATNF best estimate" + px


def galactic_to_ecliptic_au(l_deg, b_deg, d_kpc):
    import astropy.units as u
    from astropy.coordinates import BarycentricMeanEcliptic, SkyCoord
    c = SkyCoord(l=l_deg * u.deg, b=b_deg * u.deg, distance=d_kpc * u.kpc, frame="galactic")
    e = c.transform_to(BarycentricMeanEcliptic(equinox="J2000"))
    return (np.asarray(e.cartesian.xyz.to(u.au).value, dtype=float)), float(e.lon.deg), float(e.lat.deg)


def drawn_geometry():
    sx, sy = DRAWN_SUN
    gx, gy = DRAWN_GC_END
    gc_len = math.hypot(gx - sx, gy - sy)
    gc_ang = math.degrees(math.atan2(-(gy - sy), gx - sx))   # photo tilt, ~ -0.5 deg
    out = {}
    for b, (x, y) in DRAWN.items():
        ang = (math.degrees(math.atan2(-(y - sy), x - sx)) - gc_ang) % 360.0
        out[b] = (round(ang, 1), round(math.hypot(x - sx, y - sy) / gc_len, 3))
    return out


def run(out: Path) -> dict:
    jnames = [j for _, _, j, *_ in JOHNSTON]
    atnf, version = fetch_atnf(jnames)
    missing = [j for j in jnames if j not in atnf]
    if missing:
        raise RuntimeError("ATNF query did not return: {0}".format(missing))
    drawn = drawn_geometry()

    pulsars = []
    for num, bname, jname, h_units, map_rel, map_pc, map_epoch in JOHNSTON:
        a = atnf[jname]
        xyz, elon, elat = galactic_to_ecliptic_au(a["gl"], a["gb"], a["dist_kpc"])
        p_map = h_units * H_PERIOD_S
        # spin-down only (P1); glitches (Vela, Crab) and timing noise ignored
        p_now = a["p0_s"] + (a["p1"] or 0.0) * (NOW_MJD - a["pepoch_mjd"]) * 86400.0
        ang, ln = drawn[bname]
        dl = ((ang - a["gl"] + 180.0) % 360.0) - 180.0
        pulsars.append({
            "id": jname.lower().replace("+", "p").replace("-", "m"),
            "map_number": num,
            "bname": bname,
            "jname": jname,
            "gl": a["gl"],
            "gb": a["gb"],
            "dist_kpc": a["dist_kpc"],
            "dist_method": dist_method(a),
            "dist_dm_kpc": a["dist_dm_kpc"],
            "px_mas": a["px_mas"],
            "dm_pc_cm3": a["dm"],
            "p0_s": a["p0_s"],
            "p0_epoch_mjd": a["pepoch_mjd"],
            "p1": a["p1"],
            "p0_1977_s_on_map": round(p_map, 10),
            "map_period_h_units": h_units,
            "map_period_binary": format(h_units, "b"),
            "map_period_epoch_johnston": map_epoch,
            "p0_now_s_extrapolated": round(p_now, 12),
            "p0_now_epoch": NOW_ISO,
            "p0_now_minus_map_ppm": round((p_now - p_map) / p_map * 1e6, 2),
            "map_distance_rel_gc100_johnston": map_rel,
            "map_distance_implied_kpc_johnston": map_pc / 1000.0,
            "drawn_angle_deg_ccw_from_gc_line": ang,
            "drawn_length_rel_gc_line": ln,
            "drawn_angle_minus_gl_deg": round(dl, 1),
            "xyz_au": [float(v) for v in xyz],
            "ecl_lon_deg": round(elon, 3),
            "ecl_lat_deg": round(elat, 3),
            "note": NOTES.get(bname, ""),
        })

    gxyz, glon, glat = galactic_to_ecliptic_au(0.0, 0.0, GC_DIST_KPC)
    res = {
        "schema": "voyager.pulsars/1",
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": ("Identifications and map-period decoding: W.R. Johnston, 'Pulsar map' "
                   "(johnstonsarchive.net/astro/pulsarmap.html; not peer reviewed), consistent with "
                   "Sagan, Sagan & Drake 1972, Science 175, 881. Current values: ATNF Pulsar Catalogue "
                   "{0} (Manchester et al. 2005, AJ 129, 1993), queried live. Drawn geometry: digitised by eye "
                   "from NASA/JPL's photo of the Voyager record cover.").format(version or "(version unknown)"),
        "atnf_version": version,
        "frame": "heliocentric ecliptic J2000 (astropy BarycentricMeanEcliptic equinox J2000), au; x to vernal equinox, z to ecliptic north",
        "kpc_au": KPC_AU,
        "map_conventions": {
            "drawn_angle": "measured counter-clockwise from the Galactic-center line (which points right on the cover); "
                           "it equals Galactic longitude l (median |angle - l| ~ 1-2 deg)",
            "drawn_length": "total engraved line length / Galactic-center line length, from the photo. "
                            "Short lines are lengthened to make room for the binary digits, so this is NOT the "
                            "encoded distance for nearby pulsars (U).",
            "map_distance_rel_gc100_johnston": "Johnston's reading of each pulsar's encoded distance with the GC line = 100; "
                                               "implied kpc assumes R0 ~ 8.5 kpc (scale x1.18 if the designers used the IAU-1964 R0 = 10 kpc). Read by eye from Murmurs of Earth (U).",
            "period": "binary integer x hydrogen hyperfine period; the map periods are ~1971 values, reused unchanged from the Pioneer plaque",
        },
        "pulsars": pulsars,
        "galactic_centre": {
            "xyz_au": [float(v) for v in gxyz],
            "ecl_lon_deg": round(glon, 3),
            "ecl_lat_deg": round(glat, 3),
            "dist_kpc": GC_DIST_KPC,
            "source": "GRAVITY Collaboration 2019, A&A 625, L10 (8178 +/- 13 stat +/- 22 sys pc); direction = (l, b) = (0, 0)",
            "alt": GC_ALT,
            "note": "Sgr A* itself lies at (l, b) = (359.944, -0.046); the map's line points at l = 0.",
        },
        "hydrogen_period_s": H_PERIOD_S,
        "hydrogen_freq_hz": H_FREQ_HZ,
    }
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "pulsars.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    print("  {0} pulsars, ATNF {1} -> {2}".format(len(pulsars), version, out / "pulsars.json"))
    for p in pulsars:
        print("  {0:9s} l={1:7.2f} drawn={2:6.1f} (d={3:+5.1f})  D now {4:6.3f} kpc  map {5:5.2f} kpc  P map {6:.10f} now {7:.10f}".format(
            p["bname"], p["gl"], p["drawn_angle_deg_ccw_from_gc_line"], p["drawn_angle_minus_gl_deg"],
            p["dist_kpc"], p["map_distance_implied_kpc_johnston"], p["p0_1977_s_on_map"], p["p0_s"]))
    return res
