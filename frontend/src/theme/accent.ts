/* One colour, and everything the app needs around it.
 *
 * Theming here is a single accent: pick it once and the buttons, links, map
 * pins, charts and the sign-in page follow, in light and in dark. The rest
 * (hover, the ink that sits on top, the soft wash behind selections) is worked
 * out rather than asked for, because a picker with four colour inputs is four
 * chances to make something unreadable.
 *
 * It is not only the parts that light up. Borders, the raised surfaces, the
 * land on the map and the first chart series are all pulled a little way
 * towards the accent as well, so a green install looks green everywhere
 * rather than grey with green buttons. The pull is small on purpose: enough
 * to read as one colour scheme, not enough to lose the difference between a
 * card and the page behind it.
 */

type Rgb = { r: number; g: number; b: number };

function parse(hex: string): Rgb | null {
  const body = hex.trim().replace(/^#/, "");
  const full = body.length === 3 ? body.replace(/./g, (c) => c + c) : body;
  if (!/^[0-9a-f]{6}$/i.test(full)) return null;
  return {
    r: parseInt(full.slice(0, 2), 16),
    g: parseInt(full.slice(2, 4), 16),
    b: parseInt(full.slice(4, 6), 16),
  };
}

const hex = ({ r, g, b }: Rgb): string =>
  "#" + [r, g, b].map((v) => Math.round(Math.min(255, Math.max(0, v))).toString(16).padStart(2, "0")).join("");

const mix = (a: Rgb, b: Rgb, amount: number): Rgb => ({
  r: a.r + (b.r - a.r) * amount,
  g: a.g + (b.g - a.g) * amount,
  b: a.b + (b.b - a.b) * amount,
});

/* Perceived brightness, the sRGB way, for deciding what can sit on top. */
function luminance({ r, g, b }: Rgb): number {
  const channel = (v: number) => {
    const x = v / 255;
    return x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

const WHITE: Rgb = { r: 255, g: 255, b: 255 };
const BLACK: Rgb = { r: 10, g: 14, b: 20 };

/* Every variable this file writes, listed so they can be cleared in one go.
 * They are cleared before anything is read, because a value already overridden
 * reads back as the override and tinting a tint drifts further every time. */
const DERIVED = [
  "--accent",
  "--accent-hover",
  "--accent-ink",
  "--accent-soft",
  "--accent-line",
  "--border",
  "--border-strong",
  "--surface-2",
  "--surface-3",
  "--map-point",
  "--map-accuracy",
  "--map-land",
  "--map-border",
  "--map-heat-2",
  "--chart-1",
];

/* How far each part of the page is pulled towards the accent. Structure moves
 * a little, things meant to be the accent move all the way. */
const TINTS: [name: string, amount: number][] = [
  ["--border", 0.22],
  ["--border-strong", 0.22],
  ["--surface-2", 0.06],
  ["--surface-3", 0.09],
  ["--map-land", 0.05],
  ["--map-border", 0.22],
];

/* Applied on load and again whenever the theme flips, since a colour that
 * needs lightening on white needs darkening on black. */
export function applyAccent(colour: string | null | undefined): void {
  const root = document.documentElement;
  for (const name of DERIVED) root.style.removeProperty(name);
  const rgb = colour ? parse(colour) : null;
  if (!rgb) return;

  const dark = (root.dataset.theme ?? "light") === "dark";
  const bright = luminance(rgb) > 0.45;
  const base = getComputedStyle(root);
  const tint = (name: string, amount: number): void => {
    const from = parse(base.getPropertyValue(name).trim());
    if (from) root.style.setProperty(name, hex(mix(from, rgb, amount)));
  };

  for (const [name, amount] of TINTS) tint(name, amount);

  root.style.setProperty("--accent", hex(rgb));
  // Hover moves away from the page: lighter on a dark page, darker on a light one.
  root.style.setProperty("--accent-hover", hex(mix(rgb, dark ? WHITE : BLACK, 0.22)));
  root.style.setProperty("--accent-ink", bright ? hex(BLACK) : "#ffffff");
  // The wash behind a selection: the accent barely there against the page.
  root.style.setProperty("--accent-soft", hex(mix(rgb, dark ? BLACK : WHITE, dark ? 0.82 : 0.88)));
  // A rule or a keyline that should read as the accent without shouting.
  root.style.setProperty("--accent-line", hex(mix(rgb, dark ? BLACK : WHITE, dark ? 0.5 : 0.55)));
  // Map pins are the same idea as a button, so they take the same colour.
  root.style.setProperty("--map-point", hex(rgb));
  root.style.setProperty("--map-accuracy", hex(mix(rgb, dark ? WHITE : BLACK, 0.1)));
  // The heat ramp leaves from the accent and climbs away from it, so the
  // coolest end of a busy map belongs to the same scheme as everything else.
  root.style.setProperty("--map-heat-2", hex(mix(rgb, WHITE, 0.28)));
  // Series one is the accent: the single line on a one line chart.
  root.style.setProperty("--chart-1", hex(rgb));
}

/* What the picker offers, so nobody has to type a hex code to try one. */
export const ACCENTS: { name: string; value: string }[] = [
  { name: "Cyan", value: "#22d3ee" },
  { name: "Teal", value: "#14b8a6" },
  { name: "Green", value: "#22c55e" },
  { name: "Amber", value: "#f59e0b" },
  { name: "Orange", value: "#fb7185" },
  { name: "Violet", value: "#a78bfa" },
  { name: "Blue", value: "#60a5fa" },
  { name: "Plex gold", value: "#e5a00d" },
];
