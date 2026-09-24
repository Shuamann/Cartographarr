import { useEffect, useMemo, useRef, useState } from "react";
import * as maplibregl from "maplibre-gl";
import { useApi, type Activity, type MapPoints } from "../lib/api";
import { buildGlobeStyle } from "../theme/globeStyle";

/* The globe behind the home page.
 *
 * The app is a map of who watches from where, so the first thing it shows is
 * that, turning. Not the Map tab's basemap: no roads, no cities, no labels.
 * Coastlines and a grid of meridians, drawn from the country outlines already
 * bundled for picking countries, in the accent, slightly see through, sat off
 * the left edge so the menu has the right of the page to itself.
 *
 * It is still a real map underneath, which means the layers people already
 * know (places, heat, playing now, countries) work on it.
 *
 * It keeps out of the way: a gentle spin that stops when the tab is hidden or
 * the machine asks for less motion, and nothing at all where there is no
 * WebGL. It can be taken hold of and turned, which is the one thing everybody
 * tries on a globe; it carries on from wherever it was let go of, once it has
 * been left alone for a few seconds.
 *
 * There is also a moon. It is a joke, and it says so when you press it.
 */

type Layer = "history" | "heat" | "live" | "countries";

const DEGREES_PER_SECOND = 3;

/* How long the globe stays where it was put before it starts turning again.
 * Long enough to look at what you dragged into view, short enough that the
 * page does not feel broken. */
const HOLD_MS = 4000;

function webgl(): boolean {
  try {
    return Boolean(document.createElement("canvas").getContext("webgl2"));
  } catch {
    return false;
  }
}

function css(name: string, fallback: string): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

export default function Globe({ isAdmin }: { isAdmin: boolean }) {
  const canDraw = useMemo(webgl, []);
  const frame = useRef<HTMLDivElement>(null);
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const shapes = useRef<GeoJSON.FeatureCollection | null>(null);
  /* When the spin may start again: pushed forward while a drag is going on,
   * and once more when it ends. Read by the animation frame rather than held
   * in state, because it changes far more often than anything is drawn. */
  const spinAfter = useRef(0);
  const [ready, setReady] = useState(false);
  const [moon, setMoon] = useState(false);
  const [layers, setLayers] = useState<Set<Layer>>(() => {
    try {
      const saved = localStorage.getItem("globe.layers");
      return new Set((saved ? JSON.parse(saved) : ["history", "live"]) as Layer[]);
    } catch {
      return new Set<Layer>(["history", "live"]);
    }
  });

  const points = useApi<MapPoints>(canDraw ? "/map/points" : null);
  const live = useApi<Activity>(canDraw ? "/activity" : null);
  const blocked = useApi<{ items: { code: string; mode: string }[] }>(
    canDraw && isAdmin && layers.has("countries") ? "/geoblocks" : null,
    [layers.has("countries")],
  );

  function toggle(layer: Layer) {
    const next = new Set(layers);
    if (next.has(layer)) next.delete(layer);
    else next.add(layer);
    setLayers(next);
    try {
      localStorage.setItem("globe.layers", JSON.stringify([...next]));
    } catch {
      /* remembering the layers is a convenience only */
    }
  }

  // ---- the map itself ------------------------------------------------------
  useEffect(() => {
    if (!canDraw || !container.current || map.current) return;
    let cancelled = false;
    let watcher: ResizeObserver | null = null;

    // The outlines are needed before the style can be built, so the map is
    // made once they arrive rather than swapped over afterwards.
    (async () => {
      const outlines = (await import("../assets/countries.json")).default as unknown as GeoJSON.FeatureCollection;
      if (cancelled || !container.current || map.current) return;
      shapes.current = outlines;
      const m = new maplibregl.Map({
        container: container.current,
        style: buildGlobeStyle(outlines),
        center: [-30, 18],
        zoom: fitZoom(container.current),
        // Turning it is welcome. Zooming is not: the size is worked out from
        // the space it has, and a scroll over a background is the page
        // scrolling, not the globe coming closer.
        interactive: true,
        scrollZoom: false,
        boxZoom: false,
        doubleClickZoom: false,
        dragRotate: false,
        touchPitch: false,
        keyboard: false,
        // Nothing is fetched from anyone, so there is nobody to credit.
        attributionControl: false,
      });
      map.current = m;
      m.on("load", () => {
        m.setProjection({ type: "globe" });
        m.setZoom(fitZoom(container.current!));
        measure(m, frame.current, container.current);
        setReady(true);
      });
      // Pinch turns into a two finger drag rather than a zoom.
      m.touchZoomRotate.disableRotation();
      // A hand on the globe stops it, and it stays stopped for a moment after
      // the hand comes off, so it does not lurch out from under the pointer.
      const hold = () => {
        spinAfter.current = performance.now() + HOLD_MS;
      };
      m.on("mousedown", hold);
      m.on("touchstart", hold);
      m.on("drag", hold);
      m.on("dragend", hold);
      // The page it sits behind changes height as its cards load, and a globe
      // that was sized for the old height is a marble in the corner.
      watcher = new ResizeObserver(() => {
        m.resize();
        m.setZoom(fitZoom(container.current!));
        measure(m, frame.current, container.current);
      });
      watcher.observe(container.current);
    })();

    return () => {
      cancelled = true;
      watcher?.disconnect();
      map.current?.remove();
      map.current = null;
      setReady(false);
    };
  }, [canDraw]);

  // Light and dark want different weights of line, and the globe is drawn in
  // the accent, so it is redrawn whenever either changes. The accent arrives
  // as inline custom properties on the root, which is why style is watched
  // alongside the theme: picking a colour in Settings repaints it as you go.
  useEffect(() => {
    const observer = new MutationObserver(() => {
      const m = map.current;
      if (!m || !shapes.current) return;
      setReady(false);
      m.setStyle(buildGlobeStyle(shapes.current));
      m.once("styledata", () => setReady(true));
    });
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme", "style"] });
    return () => observer.disconnect();
  }, []);

  // ---- the spin ------------------------------------------------------------
  useEffect(() => {
    if (!ready) return;
    const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (still) return;
    let frame = 0;
    let last = performance.now();
    const step = (now: number) => {
      const m = map.current;
      if (m && !document.hidden && now >= spinAfter.current) {
        const seconds = (now - last) / 1000;
        const centre = m.getCenter();
        m.setCenter([centre.lng - DEGREES_PER_SECOND * seconds, centre.lat]);
      }
      last = now;
      frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [ready]);

  // ---- what is drawn on it -------------------------------------------------
  useEffect(() => {
    const m = map.current;
    if (!m || !ready) return;

    const history = layers.has("history") && !layers.has("heat") ? points.data : null;
    const heat = layers.has("heat") ? points.data : null;
    setSource(m, "globe-points", history ?? empty());
    setSource(m, "globe-heat", heat ?? empty());

    if (!m.getLayer("globe-heat-layer")) {
      m.addLayer({
        id: "globe-heat-layer",
        type: "heatmap",
        source: "globe-heat",
        paint: {
          "heatmap-weight": ["interpolate", ["linear"], ["get", "plays"], 0, 0, 200, 1],
          "heatmap-radius": 18,
          "heatmap-opacity": 0.75,
          "heatmap-color": [
            "interpolate", ["linear"], ["heatmap-density"],
            0, "rgba(0,0,0,0)",
            0.2, css("--map-heat-2", "#22d3ee"),
            0.45, css("--map-heat-3", "#818cf8"),
            0.7, css("--map-heat-4", "#f472b6"),
            1, css("--map-heat-5", "#fde047"),
          ],
        },
      });
    }
    if (!m.getLayer("globe-points-layer")) {
      m.addLayer({
        id: "globe-points-layer",
        type: "circle",
        source: "globe-points",
        paint: {
          "circle-color": ["case", ["get", "is_hosting"], css("--vpn", "#a78bfa"), css("--map-point", "#22d3ee")],
          "circle-opacity": 0.85,
          "circle-radius": ["interpolate", ["linear"], ["get", "plays"], 1, 3, 100, 6, 2000, 11],
        },
      });
    }
  }, [ready, layers, points.data]);

  // Streams playing right now, which is the part worth watching turn.
  useEffect(() => {
    const m = map.current;
    if (!m || !ready) return;
    const sessions = layers.has("live") ? live.data?.sessions ?? [] : [];
    setSource(m, "globe-live", {
      type: "FeatureCollection",
      features: sessions
        .filter((s) => s.geo?.lat != null && s.geo?.lon != null)
        .map((s) => ({
          type: "Feature" as const,
          geometry: { type: "Point" as const, coordinates: [s.geo!.lon as number, s.geo!.lat as number] },
          properties: {},
        })),
    });
    if (!m.getLayer("globe-live-layer")) {
      m.addLayer({
        id: "globe-live-layer",
        type: "circle",
        source: "globe-live",
        paint: {
          "circle-color": css("--accent-hover", "#67e8f9"),
          "circle-radius": 6,
          "circle-stroke-color": css("--accent-hover", "#67e8f9"),
          "circle-stroke-opacity": 0.35,
          "circle-stroke-width": 8,
        },
      });
    }
  }, [ready, layers, live.data]);

  // The country list, shaded the way the Map tab shades it.
  useEffect(() => {
    const m = map.current;
    if (!m || !ready) return;
    let cancelled = false;
    const modes = new Map((blocked.data?.items ?? []).map((c) => [c.code, c.mode]));

    (async () => {
      if (!layers.has("countries")) {
        if (m.getLayer("globe-countries")) m.setLayoutProperty("globe-countries", "visibility", "none");
        return;
      }
      if (!m.getSource("globe-countries-source")) {
        const outlines = shapes.current ?? ((await import("../assets/countries.json")).default as unknown as GeoJSON.FeatureCollection);
        if (cancelled || !map.current) return;
        m.addSource("globe-countries-source", { type: "geojson", data: outlines });
        m.addLayer(
          { id: "globe-countries", type: "fill", source: "globe-countries-source", paint: { "fill-color": "rgba(0,0,0,0)" } },
          m.getLayer("globe-coast") ? "globe-coast" : undefined,
        );
      }
      if (cancelled) return;
      m.setLayoutProperty("globe-countries", "visibility", "visible");
      const colour: Record<string, string> = {
        stop: css("--banned", "#f85149"),
        warn: css("--warn", "#d29922"),
        flag: css("--accent", "#22d3ee"),
      };
      const fill: (string | unknown[])[] = ["match", ["get", "code"]];
      for (const [code, mode] of modes) fill.push(code, colour[mode] ?? colour.flag);
      fill.push("rgba(127,127,127,0.05)");
      m.setPaintProperty(
        "globe-countries",
        "fill-color",
        modes.size ? (fill as maplibregl.ExpressionSpecification) : "rgba(127,127,127,0.05)",
      );
      m.setPaintProperty("globe-countries", "fill-opacity", 0.35);
    })();

    return () => {
      cancelled = true;
    };
  }, [ready, layers, blocked.data]);

  if (!canDraw) return null;

  return (
    <div className="globe" ref={frame}>
      <div className="globe-glow" aria-hidden="true" />
      <div className="globe-canvas" ref={container} aria-hidden="true" />

      {/* The moon, which is a joke, and the one stream on it, which is also a
          joke. It orbits rather than sits there, dimming as it goes round the
          back, and says what it is when anybody presses it. */}
      <div className="globe-orbit">
        <div className="globe-orbit-centre">
          <div className="globe-arm">
            <button
              className="globe-moon"
              onClick={() => setMoon(!moon)}
              title="Something appears to be playing on the Moon"
              aria-label="Something appears to be playing on the Moon"
            >
              <span className="globe-moon-live" />
            </button>
          </div>
        </div>
      </div>
      {moon && (
        <div className="globe-moon-card" role="status">
          <p className="globe-moon-title">Sea of Tranquility</p>
          <p className="muted small">
            Apollo 11, One Small Step. Direct play, 4K, 2.6 seconds of round trip. Buffering, understandably.
          </p>
          <p className="muted small">
            Nobody is watching from the Moon. If this ever shows up on the Map tab, something has gone wrong with
            geolocation, or something has gone very right with the space programme.
          </p>
          <button className="tab" onClick={() => setMoon(false)}>
            Fair enough
          </button>
        </div>
      )}

      <div className="globe-layers">
        {([
          ["history", "Places"],
          ["heat", "Heat"],
          ["live", "Playing now"],
          ...(isAdmin ? ([["countries", "Countries"]] as [Layer, string][]) : []),
        ] as [Layer, string][]).map(([key, label]) => (
          <button
            key={key}
            className={layers.has(key) ? "globe-layer on" : "globe-layer"}
            onClick={() => toggle(key)}
            title={`Show ${label.toLowerCase()} on the globe`}
          >
            {label}
          </button>
        ))}
      </div>
    </div>
  );
}

/* A globe that fills the space it is given rather than a fixed zoom.
 *
 * MapLibre draws the world 512 pixels across at zoom 0 and doubles it each
 * zoom, and under the globe projection the sphere comes out a little over a
 * quarter of that width across, so the zoom that makes it most of the shorter
 * side is worked out rather than guessed at three screen sizes. */
const WORLD_TO_GLOBE = 3.78;

function fitZoom(element: HTMLElement): number {
  const shortest = Math.min(element.clientWidth || 900, element.clientHeight || 600);
  const wanted = shortest * 0.8;
  const zoom = Math.log2((wanted * WORLD_TO_GLOBE) / 512);
  return Math.max(0, Math.min(3, zoom));
}

/* Where the sphere actually landed, published as custom properties.
 *
 * The glow around the planet has to sit on its edge, and the edge is wherever
 * the projection put it rather than wherever the zoom sum said it should be.
 * The silhouette is found by walking east from the middle and keeping the
 * furthest the screen ever gets: past the limb the points fold back, so the
 * furthest is the limb. */
function measure(m: maplibregl.Map, frame: HTMLElement | null, canvas: HTMLElement | null): void {
  if (!frame || !canvas) return;
  const middle = m.getCenter();
  const origin = m.project(middle);
  let radius = 0;
  for (let east = 10; east <= 90; east += 2) {
    const point = m.project([middle.lng + east, middle.lat]);
    radius = Math.max(radius, Math.abs(point.x - origin.x));
  }
  if (!radius) return;
  // Through the rectangles rather than offsetLeft: the canvas is shifted with
  // a transform, and offsetLeft does not know about transforms.
  const box = canvas.getBoundingClientRect();
  const outer = frame.getBoundingClientRect();
  frame.style.setProperty("--globe-x", `${Math.round(box.left - outer.left + origin.x)}px`);
  frame.style.setProperty("--globe-y", `${Math.round(box.top - outer.top + origin.y)}px`);
  frame.style.setProperty("--globe-r", `${Math.round(radius)}px`);
}


function empty(): GeoJSON.FeatureCollection {
  return { type: "FeatureCollection", features: [] };
}

function setSource(m: maplibregl.Map, id: string, data: GeoJSON.FeatureCollection): void {
  const existing = m.getSource(id) as maplibregl.GeoJSONSource | undefined;
  if (existing) existing.setData(data);
  else m.addSource(id, { type: "geojson", data });
}
