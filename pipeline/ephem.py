"""Bake Voyager 1/2 and context-craft trajectories from JPL Horizons.

Output (in ``<out>/ephem/``):
  trajectories.json  meta: per body the start date, step, count, color, and the
                     binary file holding its positions
  <id>.bin           float32 little-endian, n x 3, heliocentric ecliptic J2000 AU

The frame is ecliptic J2000 (REF_PLANE=ECLIPTIC, REF_SYSTEM=ICRF), centered on the
Sun's body center (500@10), the same frame Sol's three.js scene uses. Epoch i is
``start + i * step_days`` (TDB from Horizons). The app treats it as UTC, which is
69 s off, invisible at this scale.

Horizons sends no CORS headers, so everything is baked here; the app never
calls Horizons.
"""

from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import requests

API = "https://ssd.jpl.nasa.gov/api/horizons.api"

# id, Horizons command, display name, color (Okabe-Ito), start, stop, step days.
# Earth is needed for the one-way light time FROM EARTH (not the Sun).
BODIES = [
    ("voyager1", "-31", "Voyager 1", "#E69F00", "1977-09-06", "2035-12-31", 1),
    ("voyager2", "-32", "Voyager 2", "#56B4E9", "1977-08-21", "2035-12-31", 1),
    ("newhorizons", "-98", "New Horizons", "#009E73", "2006-01-20", "2035-12-31", 2),
    ("pioneer10", "-23", "Pioneer 10", "#CC79A7", "1972-03-04", "2035-12-31", 2),
    ("pioneer11", "-24", "Pioneer 11", "#D55E00", "1973-04-07", "2035-12-31", 2),
    ("earth", "399", "Earth", "#4F8FE8", "1972-03-04", "2035-12-31", 2),
]


def fetch(cmd: str, start: str, stop: str, step_days: int, retries: int = 3) -> np.ndarray:
    params = {
        "format": "json", "COMMAND": "'{0}'".format(cmd), "OBJ_DATA": "NO",
        "MAKE_EPHEM": "YES", "EPHEM_TYPE": "VECTORS", "CENTER": "'500@10'",
        "START_TIME": "'{0}'".format(start), "STOP_TIME": "'{0}'".format(stop),
        "STEP_SIZE": "'{0} d'".format(step_days), "REF_PLANE": "ECLIPTIC",
        "REF_SYSTEM": "ICRF", "OUT_UNITS": "AU-D", "VEC_TABLE": "1", "CSV_FORMAT": "YES",
        "VEC_LABELS": "NO",
    }
    last = None
    for attempt in range(retries):
        try:
            r = requests.get(API, params=params, timeout=120)
            r.raise_for_status()
            text = r.json()["result"]
            a, b = text.index("$$SOE"), text.index("$$EOE")
            rows = [ln.split(",") for ln in text[a + 5:b].strip().splitlines()]
            xyz = np.array([[float(c[2]), float(c[3]), float(c[4])] for c in rows])
            return xyz
        except Exception as exc:  # loud, then retry (never swallow into empty)
            last = exc
            print("  WARN Horizons {0} attempt {1}: {2}".format(cmd, attempt + 1, exc))
            time.sleep(2.0 * 2 ** attempt)
    raise RuntimeError("Horizons failed for {0}: {1}".format(cmd, last))


def run(out: Path, verbose: bool = True) -> dict:
    d = out / "ephem"
    d.mkdir(parents=True, exist_ok=True)
    meta = {
        "schema": "voyager.ephem/1",
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "JPL Horizons API (VECTORS, CENTER 500@10, REF_PLANE ECLIPTIC, ICRF)",
        "frame": "heliocentric ecliptic J2000, AU, right-handed (x to vernal equinox, z to ecliptic north)",
        "time_note": "epochs are TDB at 00:00; epoch i = start + i*step_days",
        "bodies": [],
    }
    for bid, cmd, name, color, start, stop, step in BODIES:
        t0 = time.perf_counter()
        xyz = fetch(cmd, start, stop, step).astype("<f4")
        (d / "{0}.bin".format(bid)).write_bytes(xyz.tobytes())
        meta["bodies"].append({
            "id": bid, "horizons_id": cmd, "name": name, "color": color,
            "start": start, "step_days": step, "count": int(len(xyz)),
            "file": "ephem/{0}.bin".format(bid),
        })
        if verbose:
            r = np.linalg.norm(xyz, axis=1)
            print("  {0:12s} {1:6d} pts  r {2:7.2f} -> {3:7.2f} au  ({4:.1f}s)".format(
                name, len(xyz), r[0], r[-1], time.perf_counter() - t0))
    (d / "trajectories.json").write_text(json.dumps(meta, indent=1))
    return meta
