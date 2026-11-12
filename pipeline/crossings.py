"""Bake real Voyager particle/plasma time series around the four boundary crossings.

Output (in ``<out>/crossings/``):
  index.json            list of crossings + the plasma-wave ("sound") record
  v1_ts.json v2_ts.json v1_hp.json v2_hp.json
                        one file per crossing: daily series over about +/-1.5 yr
  plasma_waves.json     V1 PWS interstellar plasma oscillations: audio/spectrogram
                        URLs + licence, f_p -> n_e relation, published densities

Every number in the series comes from a file downloaded here from NASA SPDF.
Nothing is interpolated or gap-filled. Each crossing file has one shared daily
grid ``t``; every series' ``v`` is aligned to it and holds null on days with no
measurement (one shared ``t`` keeps the files under ~60 KB).

Sources (all plain ASCII, so no CDF reader is needed):
  LECP ions   Krimigis/Decker (JHU/APL) 1-day scan-averaged Z>=1 ion fluxes
              https://spdf.gsfc.nasa.gov/pub/data/voyager/voyager{1,2}/particle/lecp/
              (SPASE spase://NASA/NumericalData/Voyager{1,2}/LECP/Flux/Ion/P1D)
  CRS         Stone/Cummings (Caltech/GSFC) daily H/He fluxes
              https://spdf.gsfc.nasa.gov/pub/data/voyager/voyager{1,2}/crs/additional_data/one_day/
              (V1 also served by CDAWeb as VOYAGER1_CRS_DAILY_FLUX)
  PLS (V2)    Richardson (MIT) daily averages
              https://spdf.gsfc.nasa.gov/pub/data/voyager/voyager2/plasma/daily/

Run (conda env ``sdo``):  python -m pipeline crossings --out public/data
"""

from __future__ import annotations

import json
import math
import re
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import requests

SPDF = "https://spdf.gsfc.nasa.gov/pub/data/voyager"
HALF_WINDOW_DAYS = 548  # about 1.5 yr either side of the crossing

# id, craft number, craft name, event, crossing date, r (au), literature note
CROSSINGS = [
    ("v1_ts", 1, "Voyager 1", "Termination shock", "2004-12-16", 94.0,
     "Stone et al. 2005, Science 309, 2017; Decker et al. 2005, Science 309, 2020. "
     "Termination-shock particle bursts were already seen upstream from mid-2002, so the "
     "low-energy rise starts well BEFORE the crossing date."),
    ("v2_ts", 2, "Voyager 2", "Termination shock", "2007-08-31", 83.7,
     "Stone et al. 2008, Nature 454, 71; Richardson et al. 2008, Nature 454, 63. "
     "Voyager 2 crossed the moving shock several times around 2007-08-30/09-01; "
     "the plasma instrument saw the solar wind slow down (pls_speed)."),
    ("v1_hp", 1, "Voyager 1", "Heliopause", "2012-08-25", 121.6,
     "Stone et al. 2013, Science 341, 150; Krimigis et al. 2013, Science 341, 144. "
     "Heliospheric particles fell by orders of magnitude while galactic cosmic rays "
     "rose; Voyager 1's plasma instrument had failed in 1980, so plasma density came "
     "later from the plasma-wave instrument (see plasma_waves.json)."),
    ("v2_hp", 2, "Voyager 2", "Heliopause", "2018-11-05", 119.0,
     "Stone et al. 2019, Nature Astronomy 3, 1013; Krimigis et al. 2019, NatAstron 3, 997; "
     "Richardson et al. 2019, NatAstron 3, 1019 (plasma). The late-January 2020 gap matches "
     "the Voyager 2 fault-protection event that NASA reported switched its science "
     "instruments off for several days."),
]

# LECP ion channel PL06 (Z>=1 ions ~0.5-1 MeV) energy edges per craft, from the
# SPASE records / V2 read_me (V1: 0.55-1.05, V2: 0.540-0.990 MeV/ion).
LECP_CH = "pl06_flux"
LECP_E = {1: (0.55, 1.05), 2: (0.540, 0.990)}
# CRS hydrogen bins integrated for the galactic-cosmic-ray proxy.
GCR_EMIN, GCR_EMAX = 125.0, 350.0
# CRS lowest hydrogen bin (3.0-4.6 MeV): anomalous / termination-shock protons.
CRS_LOW_MEV = 3.0


# ----------------------------------------------------------------- download
_session = requests.Session()
_session.headers["User-Agent"] = "voyager-datastory-pipeline/1.0 (python-requests)"


def get_text(url: str, retries: int = 4) -> str:
    last = None
    for attempt in range(retries):
        try:
            r = _session.get(url, timeout=120)
            if r.status_code == 404:
                raise FileNotFoundError(url)
            r.raise_for_status()
            return r.text
        except FileNotFoundError:
            raise
        except Exception as exc:  # loud, then retry
            last = exc
            print("  retry {0}/{1} {2}: {3}".format(attempt + 1, retries, url, exc))
            time.sleep(2 + 3 * attempt)
    raise RuntimeError("download failed: {0}: {1}".format(url, last))


def list_dir(url: str) -> list[str]:
    html = get_text(url)
    return sorted(set(re.findall(r'href="([^"?/][^"/]*)"', html)))


# ----------------------------------------------------------------- parsers
def doy_date(year: int, doy: int) -> date:
    return date(year, 1, 1) + timedelta(days=doy - 1)


def parse_lecp_daily(text: str, column: str) -> dict[date, float]:
    """LECP team yearly ASCII: 1 title line, 1 column-label line, then rows.
    Column order varies between years (some have dec_doy), so map by label.
    Missing = -99."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    labels = lines[1].split()
    if column not in labels:
        raise ValueError("column {0} not in LECP header {1}".format(column, labels))
    ci, iy, idoy = labels.index(column), labels.index("year"), labels.index("doy")
    out = {}
    for ln in lines[2:]:
        p = ln.split()
        if len(p) <= ci:
            continue
        v = float(p[ci])
        if v <= 0 or v < -98:  # -99 fill (and non-physical)
            continue
        out[doy_date(int(p[iy]), int(p[idoy]))] = v
    return out


def parse_crs_daily(text: str):
    """CRS one_day ASCII (see .../one_day/00readme.txt). Returns
    (bins = [(idx, lo, hi, species)], rows = {date: (values, uncs)})."""
    lines = text.splitlines()
    n = int(lines[3].split()[0])
    bins = []
    for ln in lines[4:4 + n]:
        m = re.match(r"\s*(\d+)\s+([\d.]+)\s*-\s*([\d.]+)\s+MeV/n\s+(\w+)", ln)
        if not m:
            raise ValueError("bad CRS header line: " + ln)
        bins.append((int(m.group(1)), float(m.group(2)), float(m.group(3)), m.group(4)))
    rows = {}
    for ln in lines[4 + n:]:
        p = ln.split()
        if len(p) < 1 + 2 * n:
            continue
        d = datetime.strptime(p[0][:10], "%Y-%m-%d").date()
        nums = np.array([float(x) for x in p[1:1 + 2 * n]])
        rows[d] = (nums[0::2], nums[1::2])
    return bins, rows


def crs_bin(bins, rows, lo_mev: float, species: str = "hydrogen"):
    """One CRS differential-flux bin (the first of `species` starting at lo_mev)."""
    for k, (i, lo, hi, sp) in enumerate(bins):
        if sp.lower().startswith(species) and abs(lo - lo_mev) < 0.05:
            out = {d: float(val[k]) for d, (val, unc) in rows.items() if unc[k] >= 0}
            return out, (lo, hi)
    raise ValueError("CRS bin {0} MeV {1} not found".format(lo_mev, species))


def gcr_integral(bins, rows) -> tuple[dict[date, float], str]:
    """Sum j*dE over CRS hydrogen bins inside [GCR_EMIN, GCR_EMAX] MeV.
    A day is dropped if any of those bins is flagged missing (value 0, unc -1)."""
    sel = [(k, lo, hi) for k, (i, lo, hi, sp) in enumerate(bins)
           if sp.lower().startswith("hydrogen") and lo >= GCR_EMIN and hi <= GCR_EMAX]
    if not sel:
        raise ValueError("no CRS H bins in GCR range")
    label = "{0:.1f}-{1:.1f} MeV".format(sel[0][1], sel[-1][2])
    out = {}
    for d, (val, unc) in rows.items():
        if any(unc[k] < 0 for k, _, _ in sel):
            continue
        out[d] = float(sum(val[k] * (hi - lo) for k, lo, hi in sel))
    return out, label


def parse_v2_pls_daily(text: str):
    """V2 PLS daily (v2_daily.fmt): col1 = year-1900 + fraction, col2 = DOY,
    cols 8-10 = VR,VT,VN km/s, col12 = fit density cm^-3, col15 = R au."""
    dens, speed = {}, {}
    for ln in text.splitlines():
        p = ln.split()
        if len(p) != 15:
            continue
        yr = 1900 + int(float(p[0]))
        d = doy_date(yr, int(float(p[1])))
        vr, vt, vn, n = float(p[7]), float(p[8]), float(p[9]), float(p[11])
        if 0 < n < 10:
            dens[d] = n
        v = math.sqrt(vr * vr + vt * vt + vn * vn)
        if 0 < v < 2000:
            speed[d] = v
    return dens, speed


# ----------------------------------------------------------------- helpers
def sig(x: float, n: int = 4) -> float:
    return float("{0:.{1}g}".format(x, n))


def clip(series: dict[date, float], d0: date, d1: date):
    ks = sorted(k for k in series if d0 <= k <= d1)
    return ks, [series[k] for k in ks]


def step_stats(t: list[date], v: list[float], dc: date) -> dict | None:
    """Mean over days -90..-10 vs +10..+90 around the crossing (gap days ignored)."""
    a = [x for d, x in zip(t, v) if -90 <= (d - dc).days <= -10]
    b = [x for d, x in zip(t, v) if 10 <= (d - dc).days <= 90]
    if len(a) < 10 or len(b) < 10:
        return {"note": "too few measured days on one side of the crossing for a before/after mean",
                "n_before": len(a), "n_after": len(b)}
    ma, mb = float(np.mean(a)), float(np.mean(b))
    return {"before_mean": sig(ma), "after_mean": sig(mb), "ratio_after_over_before": sig(mb / ma, 3),
            "n_before": len(a), "n_after": len(b), "windows_days": [[-90, -10], [10, 90]]}


def make_series(key, name, units, instrument, dataset, series, d0, d1, dc, extra=None):
    """Values are laid on the crossing's shared daily grid (top-level ``t``):
    ``v[i]`` belongs to ``t[i]``; null = no measurement that day (never filled)."""
    t, v = clip(series, d0, d1)
    s = {"key": key, "name": name, "units": units, "instrument": instrument, "dataset": dataset,
         "cadence": "1 day", "n": len(t)}
    if extra:
        s.update(extra)
    grid = {}
    for d, x in zip(t, v):
        grid[(d - d0).days] = sig(x)
    s["v"] = [grid.get(i) for i in range((d1 - d0).days + 1)]
    gaps, start = [], None
    for i, x in enumerate(s["v"] + [0.0]):
        if x is None and start is None:
            start = i
        elif x is not None and start is not None:
            if i - start >= 7:
                gaps.append([(d0 + timedelta(days=start)).isoformat(), i - start])
            start = None
    s["gaps_ge_7d"] = gaps  # [first missing day, length in days]
    if t:
        s["coverage"] = [t[0].isoformat(), t[-1].isoformat()]
        s["step"] = step_stats(t, v, dc)
    return s


def years(d0: date, d1: date):
    return range(d0.year, d1.year + 1)


# ----------------------------------------------------------------- per-source loaders
def load_lecp(craft: int, d0: date, d1: date):
    if craft == 1:
        base = "{0}/voyager1/particle/lecp/v1_ion_1day".format(SPDF)
        fname = "v1_{0}_ion_flux_1d.txt"
    else:
        base = "{0}/voyager2/particle/lecp/v2_ion_flux_1day".format(SPDF)
        fname = "v2_{0}_ion_flux_1d.txt"
    out, urls = {}, []
    for y in years(d0, d1):
        url = "{0}/{1}".format(base, fname.format(y))
        out.update(parse_lecp_daily(get_text(url), LECP_CH))
        urls.append(url)
    return out, urls


def load_crs(craft: int, d0: date, d1: date):
    base = "{0}/voyager{1}/crs/additional_data/one_day/".format(SPDF, craft)
    names = list_dir(base)
    out, low, urls, label, low_e = {}, {}, [], None, None
    for y in years(d0, d1):
        files = [f for f in names if re.fullmatch(r"vy{0}crs_1d_{1}(_\w+)?\.asc".format(craft, y), f)]
        if not files:
            print("  CRS: no daily file for voyager{0} {1}".format(craft, y))
        for f in files:
            url = base + f
            bins, rows = parse_crs_daily(get_text(url))
            g, lab = gcr_integral(bins, rows)
            label = label or lab
            if lab != label:
                print("  CRS bin set differs in {0}: {1} vs {2}".format(f, lab, label))
            out.update(g)
            lo_series, low_e = crs_bin(bins, rows, CRS_LOW_MEV)
            low.update(lo_series)
            urls.append(url)
    return out, low, low_e, urls, label, files_note(names, craft, d0, d1)


def files_note(names, craft, d0, d1):
    split = [f for f in names if re.fullmatch(r"vy{0}crs_1d_\d{{4}}_\w+\.asc".format(craft), f)
             and d0.year <= int(f[10:14]) <= d1.year]
    return split


def load_v2_pls():
    url = "{0}/voyager2/plasma/daily/".format(SPDF)
    f = [n for n in list_dir(url) if re.fullmatch(r"v2_daily_.*\.asc", n)]
    if not f:
        raise RuntimeError("no V2 PLS daily file at " + url)
    url = url + sorted(f)[-1]
    dens, speed = parse_v2_pls_daily(get_text(url))
    return dens, speed, url


# ----------------------------------------------------------------- products
def build_crossing(cid, craft, name, event, dstr, r_au, lit, pls=None):
    dc = date.fromisoformat(dstr)
    d0, d1 = dc - timedelta(days=HALF_WINDOW_DAYS), dc + timedelta(days=HALF_WINDOW_DAYS)
    print("== {0} {1} {2} window {3}..{4}".format(cid, name, event, d0, d1))
    series, sources, notes = [], [], [lit]

    gcr, low, low_e, urls, lab, split = load_crs(craft, d0, d1)
    sources += urls
    ds = ("VOYAGER1_CRS_DAILY_FLUX (CDAWeb) = SPDF crs/additional_data/one_day"
          if craft == 1 else "SPDF voyager2/crs/additional_data/one_day (not in CDAWeb as a daily set)")
    series.append(make_series(
        "crs_low", "Heliospheric protons {0:g}-{1:g} MeV".format(*low_e),
        "protons / (m^2 s sr MeV)", "CRS", ds + " (H bin 1)", low, d0, d1, dc,
        {"energy_MeV": list(low_e), "role": "heliospheric", "primary": True,
         "description": "CRS lowest-energy hydrogen bin: anomalous cosmic rays and termination-"
                        "shock particles, which are made inside the heliosphere. Rises toward and "
                        "across the termination shock; collapses at the heliopause, where the "
                        "remaining level is the galactic cosmic-ray contribution in this bin."}))

    lecp, urls = load_lecp(craft, d0, d1)
    sources += urls
    lo, hi = LECP_E[craft]
    series.append(make_series(
        "lecp_ions", "Low-energy ions {0}-{1} MeV".format(lo, hi),
        "ions / (cm^2 s sr MeV)", "LECP",
        "spase://NASA/NumericalData/Voyager{0}/LECP/Flux/Ion/P1D (channel PL06)".format(craft),
        lecp, d0, d1, dc,
        {"energy_MeV": [lo, hi], "role": "heliospheric",
         "description": "LECP Z>=1 ions (mostly protons), 1-day scan-averaged differential "
                        "intensity, channel PL06. The team's daily file carries no background "
                        "correction note; at both heliopause crossings this channel falls only "
                        "~4x, to a floor that is most likely instrument background from "
                        "penetrating cosmic rays rather than interstellar ions, so crs_low shows "
                        "the heliopause drop more cleanly."}))

    gextra = {"energy_MeV": [float(x) for x in lab.replace(" MeV", "").split("-")], "role": "galactic",
              "description": "Galactic cosmic-ray protons: CRS daily hydrogen differential fluxes "
                             "summed as sum(j*dE) over the {0} bins (gaps between bins are not "
                             "filled). An integral intensity, not the CRS team's >70 MeV count rate."
                             .format(lab)}
    if split:
        gextra["note"] = ("CRS daily files for this window are split ({0}). NASA reported on "
                          "2019-07-08 that the Voyager 2 CRS heater had recently been turned off; "
                          "the file names suggest before/after heater turn-off. Values after the "
                          "split may not be calibrated identically to those before."
                          .format(", ".join(split)))
    series.append(make_series("crs_gcr", "Galactic cosmic-ray protons {0}".format(lab),
                              "protons / (m^2 s sr)", "CRS", ds, gcr, d0, d1, dc, gextra))

    if pls is not None:
        dens, speed, url = pls
        sources.append(url)
        pnote = None
        if dc > max(dens):
            pnote = ("SPDF's public V2 PLS daily file ends {0} (2018 DOY 308), the day before the "
                     "heliopause crossing; post-crossing PLS plasma is not in the SPDF/CDAWeb "
                     "public products (CDAWeb VOYAGER2_PLS_HIRES_PLASMA_DATA_HSH also ends "
                     "2018-11-05T13:45). Richardson et al. 2019 (Nat Astron 3, 1019) report the "
                     "density jumped about 20-fold across the heliopause.".format(max(dens)))
        for key, nm, un, src in (("pls_density", "Proton density", "cm^-3", dens),
                                 ("pls_speed", "Bulk flow speed", "km/s", speed)):
            ex = {"role": "plasma",
                  "description": "Voyager 2 Plasma Science (PLS) daily average; density is the "
                                 "fit value (column 12), speed = |(VR,VT,VN)|."}
            if pnote:
                ex["note"] = pnote
            series.append(make_series(key, nm, un, "PLS",
                                      "SPDF voyager2/plasma/daily (v2_daily.fmt)",
                                      src, d0, d1, dc, ex))

    for s in series:
        if s["n"] == 0:
            s["note"] = (s.get("note", "") + " No data in this window.").strip()
    return {
        "id": cid, "craft": name, "event": event, "date": dstr, "r_au": r_au,
        "window": [d0.isoformat(), d1.isoformat()],
        "layout": "shared daily grid: series[k].v[i] is the value on t[i] (UTC day start); "
                  "null = no measurement that day",
        "t": [(d0 + timedelta(days=i)).isoformat() for i in range((d1 - d0).days + 1)],
        "series": series, "notes": notes,
        "source_urls": sources,
        "acknowledgement": "Data: NASA Space Physics Data Facility (SPDF); Voyager LECP "
                           "(PI S. M. Krimigis, JHU/APL), CRS (PI E. C. Stone, Caltech; "
                           "A. C. Cummings), PLS (J. D. Richardson, MIT).",
    }


def fp_to_ne(f_khz: float) -> float:
    return (f_khz / 8.98) ** 2


def plasma_waves() -> dict:
    meas = [
        # (date or span, f_p kHz or None, n_e, how, source)
        ("2012-10/2012-11", 2.1, None,
         "f_p from the tone 'near 2.1 kHz' (Univ. Iowa caption); n_e derived here with f_p=8.98 kHz*sqrt(n_e)",
         "https://space.physics.uiowa.edu/plasma-wave/voyager/v1pws_interstellar_epo.html"),
        ("2013-04-09", 2.6, 0.08,
         "Gurnett et al. 2013, Science 341, 1489: oscillations near 2.6 kHz -> n_e ~0.08 cm^-3",
         "https://doi.org/10.1126/science.1241681"),
        ("2015/2016 POEs and 2017-2020 narrowband emission", None, 0.11,
         "Ocker et al. 2021, Nature Astronomy 5, 761: 'consistent with n_e ~0.11 cm^-3'",
         "https://arxiv.org/abs/2105.04000"),
        ("2017-01/2020-02 (mean)", None, 0.12,
         "Ocker et al. 2021: mean VLISM density 0.12 cm^-3 used for rms(n_e)/n_e = 0.0041/0.12",
         "https://arxiv.org/abs/2105.04000"),
        ("2017-09 (leading edge of POE)", 3.06, None,
         "Ocker et al. 2021: POE leading edge at 3.06 kHz; n_e derived here",
         "https://arxiv.org/abs/2105.04000"),
        ("2017-09 (mid-September, shock passage)", 3.15, None,
         "Ocker et al. 2021: f_p rises to 3.15 kHz as the shock passes; n_e derived here",
         "https://arxiv.org/abs/2105.04000"),
    ]
    rows = []
    for when, f, ne, how, src in meas:
        row = {"when": when, "source": src, "how": how}
        if f is not None:
            row["f_p_kHz"] = f
        if ne is not None:
            row["n_e_cm3"] = ne
            row["n_e_kind"] = "published"
        else:
            row["n_e_cm3"] = round(fp_to_ne(f), 3)
            row["n_e_kind"] = "derived from f_p"
        rows.append(row)
    return {
        "id": "v1_pws_interstellar",
        "craft": "Voyager 1", "instrument": "PWS (Plasma Wave Subsystem)",
        "what": "Electron plasma oscillations in the very local interstellar medium. Their "
                "frequency is the local electron plasma frequency, so the pitch measures density. "
                "PWS senses electric-field waves in the plasma, not sound; the audio is the "
                "wave signal played through a speaker (frequencies are already in the audio band).",
        "relation": {"formula": "f_p = 8.98 kHz * sqrt(n_e / cm^-3)",
                     "inverse": "n_e = (f_p / 8.98 kHz)^2 cm^-3",
                     "source": "NRL Plasma Formulary (f_pe = 8.98e3 * n_e^1/2 Hz, n_e in cm^-3)"},
        "measurements": rows,
        "media": [
            {"title": "PIA17045: Voyager Captures Sounds of Interstellar Space (2013-09-12)",
             "kind": "video (mp4) with the PWS audio soundtrack + spectrogram, Oct-Nov 2012 and Apr-May 2013",
             "page": "https://science.nasa.gov/photojournal/voyager-captures-sounds-of-interstellar-space/",
             "mp4_320": "https://assets.science.nasa.gov/content/dam/science/psd/photojournal/pia/pia17/pia17045/PIA17045_20130906-320.mp4",
             "mp4_320_bytes": 1746284,
             "mp4_640": "https://assets.science.nasa.gov/content/dam/science/psd/photojournal/pia/pia17/pia17045/PIA17045_20130906-640.mp4",
             "mp4_640_bytes": 3532551,
             "spectrogram_jpg": "https://assets.science.nasa.gov/content/dam/science/psd/photojournal/pia/pia17/pia17045/PIA17045.jpg",
             "spectrogram_tif": "https://assets.science.nasa.gov/content/dam/science/psd/photojournal/pia/pia17/pia17045/PIA17045.tif",
             "credit": "NASA/JPL-Caltech/University of Iowa",
             "license": "NASA media are generally not subject to copyright in the US (NASA Images and "
                        "Media Usage Guidelines); because the credit includes the University of Iowa, "
                        "attribute 'NASA/JPL-Caltech/University of Iowa' and treat the audio as CC BY 4.0 "
                        "(the University of Iowa space-audio licence)."},
            {"title": "University of Iowa: Voyager 1 PWS electron plasma oscillations beyond the heliopause",
             "kind": "video (mp4) with audio; 225 days compressed to ~12 s, frequencies preserved",
             "page": "https://space.physics.uiowa.edu/plasma-wave/voyager/v1pws_interstellar_epo.html",
             "mp4": "https://space.physics.uiowa.edu/plasma-wave/voyager/v1pws_interstellar_epo.mp4",
             "mp4_bytes": 2699287,
             "youtube": "https://www.youtube.com/watch?v=aNB4FaNh0wQ",
             "credit": "Original space audio recordings provided courtesy of NASA and The University of Iowa. https://space-audio.org/",
             "license": "CC BY 4.0 (https://space.physics.uiowa.edu/plasma-wave/space-audio/citation.html)"},
            {"title": "University of Iowa: ongoing V1 interstellar plasma-wave observations (update)",
             "page": "https://space.physics.uiowa.edu/plasma-wave/voyager/v1pws_interstellar_update.html",
             "mp4": "https://space.physics.uiowa.edu/plasma-wave/voyager/v1pws_interstellar_update.mp4",
             "mp4_bytes": 2009284,
             "license": "CC BY 4.0 (space-audio.org citation page)"},
        ],
        "note": "No standalone official mp3/wav was found; the official audio is the soundtrack of "
                "the mp4s above. Nothing was downloaded into the repo.",
    }


def write_json(path: Path, obj) -> int:
    txt = json.dumps(obj, separators=(",", ":"), ensure_ascii=False)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(txt, encoding="utf-8")
    tmp.replace(path)
    return len(txt)


def run(out: Path) -> None:
    dest = Path(out) / "crossings"
    dest.mkdir(parents=True, exist_ok=True)
    pls = load_v2_pls()
    index = {"generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
             "half_window_days": HALF_WINDOW_DAYS, "crossings": []}
    for cid, craft, name, event, dstr, r_au, lit in CROSSINGS:
        obj = build_crossing(cid, craft, name, event, dstr, r_au, lit,
                             pls=pls if craft == 2 else None)
        nbytes = write_json(dest / (cid + ".json"), obj)
        print("  wrote {0}.json  {1:.1f} KB  ".format(cid, nbytes / 1024)
              + ", ".join("{0}={1}".format(s["key"], s["n"]) for s in obj["series"]))
        index["crossings"].append({
            "id": cid, "file": cid + ".json", "craft": name, "event": event, "date": dstr,
            "r_au": r_au, "series": [s["key"] for s in obj["series"]],
            "step": {s["key"]: s.get("step") for s in obj["series"]}})
    pw = plasma_waves()
    write_json(dest / "plasma_waves.json", pw)
    index["plasma_waves"] = {"file": "plasma_waves.json", "id": pw["id"]}
    write_json(dest / "index.json", index)
    print("  wrote index.json, plasma_waves.json -> {0}".format(dest))


if __name__ == "__main__":
    import sys
    run(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("public/data"))
