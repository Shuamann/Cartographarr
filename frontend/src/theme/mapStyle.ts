import type { StyleSpecification } from "maplibre-gl";

/* The basemap is painted from the app's own design tokens.
 *
 * This is the reason for vector tiles over raster: a raster basemap arrives
 * pre-coloured by whoever rendered it, and the only way to reshade it is a CSS
 * filter over the whole canvas, pins included. Here every layer is ours, so
 * flipping the theme restyles land, water and labels along with the chrome.
 *
 * Tiles come from CARTO's free vector service. Swapping in a self-hosted
 * .pmtiles basemap later is a change to `sources`, nothing else.
 */

const TILES = "https://basemaps.cartocdn.com/vector/carto.streets/v1/tiles.json";

function token(name: string, fallback: string): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

export function buildMapStyle(): StyleSpecification {
  const water = token("--map-water", "#d6e3ef");
  const land = token("--map-land", "#eef1f5");
  const road = token("--map-road", "#ffffff");
  const border = token("--map-border", "#c3ccd8");
  const label = token("--map-label", "#5a6675");
  const halo = token("--map-label-halo", "#ffffff");

  return {
    version: 8,
    glyphs: "https://basemaps.cartocdn.com/fonts/{fontstack}/{range}.pbf",
    sources: { carto: { type: "vector", url: TILES } },
    layers: [
      { id: "bg", type: "background", paint: { "background-color": land } },
      {
        id: "water",
        type: "fill",
        source: "carto",
        "source-layer": "water",
        paint: { "fill-color": water },
      },
      {
        id: "roads",
        type: "line",
        source: "carto",
        "source-layer": "transportation",
        // Roads are context, not content, so thin and only once zoomed in.
        minzoom: 5,
        paint: {
          "line-color": road,
          "line-opacity": 0.5,
          "line-width": ["interpolate", ["linear"], ["zoom"], 5, 0.3, 14, 1.5],
        },
      },
      {
        id: "boundaries",
        type: "line",
        source: "carto",
        "source-layer": "boundary",
        filter: ["<=", ["get", "admin_level"], 4],
        paint: { "line-color": border, "line-width": 0.7 },
      },
      {
        id: "place-labels",
        type: "symbol",
        source: "carto",
        "source-layer": "place",
        filter: ["in", ["get", "class"], ["literal", ["country", "state", "city"]]],
        layout: {
          "text-field": ["get", "name"],
          "text-font": ["Open Sans Regular"],
          "text-size": ["interpolate", ["linear"], ["zoom"], 3, 10, 10, 14],
        },
        paint: {
          "text-color": label,
          "text-halo-color": halo,
          "text-halo-width": 1.2,
        },
      },
    ],
  };
}
