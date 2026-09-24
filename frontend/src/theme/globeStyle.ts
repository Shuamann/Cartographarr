import type { StyleSpecification } from "maplibre-gl";

/* The globe on the home page is drawn, not fetched.
 *
 * The Map tab wants a real basemap: roads, cities, the lot. The home page
 * wants a shape turning behind the words, so it gets one built from the
 * country outlines already bundled for picking countries, plus a grid of
 * meridians and parallels. No tiles, no labels, nothing asked of anyone else,
 * and it starts the moment the page does.
 *
 * Every colour is a token, so it follows the theme and whatever accent has
 * been chosen, the same as the rest of the app.
 */

function token(name: string, fallback: string): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

function rgba(hex: string, alpha: number): string {
  const body = hex.replace("#", "");
  const full = body.length === 3 ? body.replace(/./g, (c) => c + c) : body;
  const n = parseInt(full, 16);
  if (Number.isNaN(n) || full.length !== 6) return hex;
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
}

/* Meridians and parallels every 15 degrees: the wireframe under everything. */
export function graticule(step = 15): GeoJSON.FeatureCollection {
  const features: GeoJSON.Feature[] = [];
  for (let lon = -180; lon < 180; lon += step) {
    const line: [number, number][] = [];
    for (let lat = -80; lat <= 80; lat += 5) line.push([lon, lat]);
    features.push({ type: "Feature", properties: { kind: "meridian" }, geometry: { type: "LineString", coordinates: line } });
  }
  for (let lat = -75; lat <= 75; lat += step) {
    const line: [number, number][] = [];
    for (let lon = -180; lon <= 180; lon += 5) line.push([lon, lat]);
    features.push({ type: "Feature", properties: { kind: "parallel" }, geometry: { type: "LineString", coordinates: line } });
  }
  return { type: "FeatureCollection", features };
}

export function buildGlobeStyle(countries: GeoJSON.FeatureCollection): StyleSpecification {
  const accent = token("--accent", "#22d3ee");
  const dark = (document.documentElement.dataset.theme ?? "light") === "dark";
  // A pale page needs more of the line than a dark one does: the same alpha
  // that reads as a wireframe on black disappears on white.
  const ink = dark
    ? { body: token("--surface-2", "#0f1720"), shell: 0.55, grid: 0.16, land: 0.07, coast: 0.45 }
    : { body: token("--surface-3", "#e3e8ef"), shell: 0.75, grid: 0.3, land: 0.14, coast: 0.65 };

  return {
    version: 8,
    // No glyphs and no sprite: nothing here has a label or an icon.
    sources: {
      countries: { type: "geojson", data: countries },
      graticule: { type: "geojson", data: graticule() },
    },
    layers: [
      {
        // Under the globe projection this paints the sphere itself, which is
        // what gives the shape its body without hiding what is behind it.
        id: "globe-body",
        type: "background",
        paint: { "background-color": rgba(ink.body, ink.shell) },
      },
      {
        id: "globe-graticule",
        type: "line",
        source: "graticule",
        paint: { "line-color": rgba(accent, ink.grid), "line-width": 1 },
      },
      {
        id: "globe-land",
        type: "fill",
        source: "countries",
        paint: { "fill-color": rgba(accent, ink.land) },
      },
      {
        id: "globe-coast",
        type: "line",
        source: "countries",
        paint: { "line-color": rgba(accent, ink.coast), "line-width": 0.8 },
      },
    ],
  };
}
