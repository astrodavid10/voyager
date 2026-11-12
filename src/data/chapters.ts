// The five-chapter story (AUDIT-UI #3). Copy is guest-facing: plain words,
// miles and light time before au, and the fixed phrase "left the Sun's
// bubble, not the solar system" (AUDIT-UI #12).

export type Tier = "MEASURED" | "MODELED" | "PREDICTED";

export interface Chapter {
  id: string;
  title: string;
  /** Evidence badges shown on the card. */
  tiers: Tier[];
  /** Static body text; chapter 1's body is computed live in App.vue. */
  body: string;
  /** Next-button label. */
  next?: string;
}

export const CHAPTERS: Chapter[] = [
  {
    id: "today",
    title: "One light-day from home",
    tiers: ["MEASURED"],
    body: "",
    next: "How it got there",
  },
  {
    id: "journey",
    title: "Forty-nine years outward",
    tiers: ["MEASURED"],
    body: "Launched in 1977, the twins toured the giant planets, then kept going. "
      + "They are still sending data home on about 4 watts of radio power.",
    next: "Leaving the Sun's bubble",
  },
  {
    id: "bubble",
    title: "Nobody knows the shape yet",
    tiers: ["MEASURED", "MODELED"],
    body: "The Sun blows a bubble of solar wind, the heliosphere. Voyager 1 crossed its edge, "
      + "the heliopause, in 2012 and Voyager 2 in 2018: two measured points. The tail is "
      + "inference, and models disagree. NASA's IMAP mission is mapping it now.",
    next: "Zoom out",
  },
  {
    id: "oort",
    title: "The Oort cloud",
    tiers: ["PREDICTED"],
    body: "Far beyond the bubble, trillions of icy bodies are thought to orbit the Sun. "
      + "No one has seen the Oort cloud directly; its shape comes from computer simulations. "
      + "Voyager 1 needs about 300 more years to reach its inner edge, and 30,000 to cross it.",
    next: "The real edge",
  },
  {
    id: "edge",
    title: "Where the Sun's pull gives way",
    tiers: ["PREDICTED"],
    body: "About 283,000 times farther than Earth is from the Sun, the Galaxy's pull starts to win "
      + "over the Sun's. It is a fuzzy zone, not a wall, stretched toward the center of the Milky Way. "
      + "Voyager has left the Sun's bubble, not the solar system. "
      + "Each Voyager carries a Golden Record of sounds and images from Earth for whoever finds it.",
    next: "Back to today",
  },
];

/** Journey captions, keyed by date (UTC). */
export const JOURNEY_EVENTS: { date: string; craft: "voyager1" | "voyager2" | "both"; text: string }[] = [
  { date: "1977-08-20", craft: "voyager2", text: "Voyager 2 launches" },
  { date: "1977-09-05", craft: "voyager1", text: "Voyager 1 launches" },
  { date: "1979-03-05", craft: "voyager1", text: "Voyager 1 at Jupiter" },
  { date: "1979-07-09", craft: "voyager2", text: "Voyager 2 at Jupiter" },
  { date: "1980-11-12", craft: "voyager1", text: "Voyager 1 at Saturn" },
  { date: "1981-08-25", craft: "voyager2", text: "Voyager 2 at Saturn" },
  { date: "1986-01-24", craft: "voyager2", text: "Voyager 2 at Uranus, the only visit ever" },
  { date: "1989-08-25", craft: "voyager2", text: "Voyager 2 at Neptune, the only visit ever" },
  { date: "1990-02-14", craft: "voyager1", text: "Voyager 1 looks back: the Pale Blue Dot" },
  { date: "2004-12-16", craft: "voyager1", text: "Voyager 1 crosses the termination shock" },
  { date: "2007-08-31", craft: "voyager2", text: "Voyager 2 crosses the termination shock" },
  { date: "2012-08-25", craft: "voyager1", text: "Voyager 1 leaves the Sun's bubble" },
  { date: "2018-11-05", craft: "voyager2", text: "Voyager 2 leaves the Sun's bubble" },
];

/** Boundary crossings, drawn as markers on the trajectories. */
export const CROSSINGS = [
  { craft: "voyager1", date: "2004-12-16", kind: "TS", label: "Termination shock 2004 · 94 au" },
  { craft: "voyager2", date: "2007-08-31", kind: "TS", label: "Termination shock 2007 · 84 au" },
  { craft: "voyager1", date: "2012-08-25", kind: "HP", label: "Heliopause 2012 · 121.6 au" },
  { craft: "voyager2", date: "2018-11-05", kind: "HP", label: "Heliopause 2018 · 119.0 au" },
] as const;

/** Distance-ladder rungs (AUDIT-UI #8), au. */
export const LADDER = [
  { id: "earth", label: "Earth", au: 1 },
  { id: "neptune", label: "Neptune", au: 30 },
  { id: "heliopause", label: "Heliopause", au: 120 },
  { id: "voyager1", label: "Voyager 1", au: 172 },
  { id: "inner-oort", label: "Inner Oort", au: 2000 },
  { id: "outer-oort", label: "Outer Oort", au: 100000 },
  { id: "edge", label: "Gravity's edge", au: 283000 },
  { id: "galaxy", label: "Milky Way", au: 3.0e9 },
];
