"""Voyager data/model pipeline.  Run from the repo root in the conda env `sdo`:

    python -m pipeline all --out public/data
    python -m pipeline ephem --out public/data
"""

import argparse
import sys
from pathlib import Path


def main(argv=None):
    p = argparse.ArgumentParser(prog="pipeline")
    p.add_argument("step", choices=["ephem", "helio", "tidal", "oort", "stars", "crossings", "pbd", "pulsars", "flybys", "all"])
    p.add_argument("--out", type=Path, default=Path("public/data"))
    a = p.parse_args(argv)
    a.out.mkdir(parents=True, exist_ok=True)
    steps = ["ephem", "helio", "tidal", "oort", "stars", "crossings"] if a.step == "all" else [a.step]
    for s in steps:
        print("== {0}".format(s))
        mod = __import__("pipeline." + s, fromlist=["run"])
        mod.run(a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
