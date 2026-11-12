"""Milky Way face-on texture for the 3D galaxy layer -> public/data/galaxy/

Source image: "The best Milky Way map, by Gaia" (artist's impression based on
Gaia data), credit ESA/Gaia/DPAC, Stefan Payne-Wardenaar, licence
CC BY-SA 3.0 IGO. https://www.esa.int/ESA_Multimedia/Images/2025/01/The_best_Milky_Way_map_by_Gaia
The high-contrast 4k square crop is the one WorldWide Telescope hosts at
https://data1.wwtassets.org/packages/2025/01_gaia_milky_way/Gaia-HighContrast-MilkyWay-4k.jpg

The outputs are downsampled, re-encoded copies (an adaptation), so they are
shared under the same licence, CC BY-SA 3.0 IGO. See docs/RESEARCH-galaxy.md.

Standalone (not part of `python -m pipeline all`):
    python pipeline/galaxy.py [source.jpg] [--out public/data/galaxy]
With no source it downloads the 4k image from wwtassets.
"""

from __future__ import annotations

import argparse
import io
import urllib.request
from pathlib import Path

from PIL import Image

SRC_URL = "https://data1.wwtassets.org/packages/2025/01_gaia_milky_way/Gaia-HighContrast-MilkyWay-4k.jpg"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("source", nargs="?")
    ap.add_argument("--out", default="public/data/galaxy")
    a = ap.parse_args()
    if a.source:
        im = Image.open(a.source)
    else:
        req = urllib.request.Request(SRC_URL, headers={"User-Agent": "galaxy-texture-build"})
        im = Image.open(io.BytesIO(urllib.request.urlopen(req, timeout=120).read()))
    im = im.convert("RGB")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for name, size, q in (("milkyway-2k.jpg", 2048, 80), ("milkyway-1k.jpg", 1024, 78)):
        im.resize((size, size), Image.LANCZOS).save(out / name, "JPEG", quality=q, optimize=True, progressive=True)
        print("  {0}: {1:,} bytes".format(name, (out / name).stat().st_size))


if __name__ == "__main__":
    main()
