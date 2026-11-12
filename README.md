# Voyager: one light-day from home

An interactive companion to the INTUITIVE® Planetarium show: where Voyager 1 and 2 are right now, how they got there, what they found at the edge of the Sun's bubble, and how far the Sun's gravity really reaches.

**Live:** https://astrodavid10.github.io/voyager/

- Opens on today: Voyager 1's one-way light time from Earth, counting down to **one light-day (around 18 November 2026)**.
- A five-chapter story:
  1. Today
  2. The journey, 1977 to now
  3. Leaving the Sun's bubble, with three competing heliosphere shapes
  4. The Oort cloud
  5. Where the Sun's pull gives way to the Galaxy's
- A distance ladder, from 1 au to the Sun's tidal edge at about 283,000 au.
- Real Voyager particle data from the heliopause crossing.
- The interstellar plasma-wave recording.

Built on [WorldWide Telescope](https://worldwidetelescope.org/) (3D solar-system mode) with a three.js overlay.

## Evidence tiers

Every chapter is labeled with what kind of knowledge it shows:

- **MEASURED:** Voyager's trajectories and crossings, and the IBEX nose distance.
- **MODELED:** the heliosphere's tail, the bow wave, the solar-cycle breathing.
- **PREDICTED:** the Oort cloud and its simulated spiral, and the tidal boundary.

## Data and models

The `pipeline/` folder holds the Python generators. Run them in an env with numpy, scipy, astropy and requests: `python -m pipeline all --out public/data`.

| Product | Source |
|---|---|
| Trajectories | JPL Horizons (heliocentric ecliptic J2000) |
| Heliosphere (`models/heliosphere.glb`) | Heliopause as a Rankine half-body (Parker 1961; Kleimann et al. 2022), fitted through both Voyager heliopause crossings. Termination shock fitted through both shock crossings. Inflow direction from McComas et al. 2015 (IBEX). Tail shapes after Opher et al. 2015/2020 (croissant) and Dialynas et al. 2017 (bubble). |
| Sun's tidal region (`models/tidal.glb`) | Hill approximation in the Galactic tide (Veras & Evans 2013) with Oort constants from Bovy 2017 and local density from McKee et al. 2015 |
| Oort cloud | Synthetic and illustrative. Shapes from Vokrouhlický et al. 2019 and Nesvorný et al. 2025 (the inner-cloud spiral, predicted by simulation). |
| Crossing data | NASA SPDF: Voyager CRS (PI E. C. Stone; A. C. Cummings), LECP (PI S. M. Krimigis) and PLS (J. D. Richardson) |

## Credits

- Plasma-wave audio: NASA and The University of Iowa (CC BY 4.0, https://space-audio.org/).
- Mission imagery: NASA/JPL-Caltech.
- Sky panorama: all-sky mosaic by Eckhard Slawik, as published by NOIRLab (credit NOIRLab/NSF/AURA/E. Slawik/M. Zamani, CC BY 4.0), tiled for WorldWide Telescope / AAS.
- Pale Blue Dot: NASA/JPL-Caltech, *Pale Blue Dot Revisited* (PIA23645). It is placed in 3D along Voyager 1's 1990 line of sight; the camera roll is estimated from the sunlight direction.
- Milky Way: ESA/Gaia/DPAC, Stefan Payne-Wardenaar, **CC BY-SA 3.0 IGO**. The files in `public/data/galaxy/` stay under that license (see `ATTRIBUTION.txt`). Spiral arms after Reid et al. 2019.
- Pulsar map: pulsars identified on the Golden Record cover as decoded by W. R. Johnston. Current values from the ATNF Pulsar Catalogue v2.9.0 (Manchester et al. 2005).
- Future flybys: Bailer-Jones & Farnocchia 2019 (RNAAS 3, 59), with Gaia DR3 positions.
- Golden Record cover: NASA/JPL.
- Interactive: INTUITIVE® Planetarium at the U.S. Space & Rocket Center, with CosmicDS.
- 3D overlay bridge: adapted from `three-wwt` (license in `src/three/three-wwt/LICENSE`).

## Development

```bash
corepack yarn install
corepack yarn serve
corepack yarn lint && corepack yarn build
```

Deep links:
- `?ch=1` to `?ch=5`: open a chapter.
- `?shape=comet|croissant|bubble`: pick the heliosphere shape.
- `?now=2026-11-19T12:00Z`: set "now", to test the date-dependent copy.
- `?kiosk=1`: lobby kiosk mode.
