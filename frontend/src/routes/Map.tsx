import { displayTitle } from "../lib/titles";
import { useEffect, useMemo, useRef, useState } from "react";
import * as maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { api,
  useApi,
  useUserNames,
  type Activity,
  type LiveSession,
  type MapPoint,
  type MapPoints,
} from "../lib/api";
import { when } from "../components/DataTable";
import FilterBar from "../components/FilterBar";
import { toQuery, type FilterState } from "../lib/filters";
import { buildMapStyle } from "../theme/mapStyle";
import MediaPanel from "../components/MediaPanel";
import StreamDetail from "../components/StreamDetail";
import { useNav } from "../lib/nav";
import { useBans } from "../lib/bans";
import TimeScrubber from "../components/TimeScrubber";
import type { HistoryPage, LocationDetail } from "../lib/api";

type Summary = { plays: number; users: number; devices: number; ips: number; seconds: number };
type Place = MapPoint["properties"];
type View = "map" | "list";

/* MapLibre 5 needs WebGL2 and throws on construction without it. Checking up
 * front means the list can be the default on machines that can't draw a map:
 * a headless VM, software rendering, an old driver. That beats showing an
 * error where a map should be. */
function webglAvailable(): boolean {
  try {
    const canvas = document.createElement("canvas");
    return Boolean(canvas.getContext("webgl2"));
  } catch {
    return false;
  }
}

export default function MapRoute({
  geoipReady,
  onOpenUser,
  focusSession,
  onFocusUsed,
  focusPlace,
  onFocusPlaceUsed,
  filters,
  onFilters,
}: {
  geoipReady: boolean;
  onOpenUser?: (userId: number) => void;
  focusSession?: LiveSession | null;
  onFocusUsed?: () => void;
  focusPlace?: { lat: number; lon: number } | null;
  onFocusPlaceUsed?: () => void;
  filters: FilterState;
  onFilters: (next: FilterState) => void;
}) {
  const nav = useNav();
  const query = useMemo(() => toQuery(filters), [filters]);

  const points = useApi<MapPoints>(`/map/points${query}`);
  const summary = useApi<Summary>(`/stats/summary${query}`);
  const [selected, setSelected] = useState<MapPoint | null>(null);

  const canDrawMap = useMemo(webglAvailable, []);
  const [view, setView] = useState<View>(() => {
    const saved = localStorage.getItem("view") as View | null;
    if (saved && (saved === "list" || canDrawMap)) return saved;
    return canDrawMap ? "map" : "list";
  });

  function choose(next: View) {
    setView(next);
    localStorage.setItem("view", next);
  }

  const [showHistory, setShowHistory] = useState(
    () => localStorage.getItem("layer.history") !== "off",
  );
  const [showAccuracy, setShowAccuracy] = useState(
    () => localStorage.getItem("layer.accuracy") !== "off",
  );
  const [showLive, setShowLive] = useState(() => localStorage.getItem("layer.live") !== "off");
  const [showHeat, setShowHeat] = useState(() => localStorage.getItem("layer.heat") === "on");
  const [heatMetric, setHeatMetric] = useState<HeatMetric>(() => {
    const saved = localStorage.getItem("layer.heatMetric");
    return saved === "devices" || saved === "users" ? saved : "plays";
  });

  const [showBanned, setShowBanned] = useState(() => localStorage.getItem("layer.banned") !== "off");
  // Countries: shaded by what the list says to do about each, and clickable.
  const [showCountries, setShowCountries] = useState(() => localStorage.getItem("layer.countries") !== "off");
  const blocked = useApi<{ items: { code: string; name: string | null; mode: string }[] }>(
    nav.isAdmin && showCountries ? "/geoblocks" : null,
    [showCountries],
  );
  const [picked, setPicked] = useState<{ code: string; name: string } | null>(null);
  const modes = useMemo(() => {
    const out: Record<string, string> = {};
    for (const row of blocked.data?.items ?? []) out[row.code] = row.mode;
    return out;
  }, [blocked.data]);
  const bans = useBans();
  // Refetched when the ban list changes, so a ban made elsewhere appears.
  const bannedPoints = useApi<GeoJSON.FeatureCollection>(bans.ids.size ? "/map/banned" : null, [bans.ids.size]);

  const live = useApi<Activity>("/activity");
  useEffect(() => {
    const timer = setInterval(live.reload, 5000);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Only streams we can actually place belong on a map. A LAN address has no
  // location to look up, so those are counted and explained rather than
  // silently missing.
  const allLive = live.data?.sessions ?? [];
  const liveSessions = allLive.filter((s) => s.geo?.lat != null);
  // Two different reasons a stream is missing from the map, and they call for
  // different words: a LAN address has no public location at all, a public one
  // just has not been looked up yet.
  const onNetwork = allLive.filter((s) => s.geo?.lat == null && s.location !== "wan").length;
  const unlocated = allLive.length - liveSessions.length - onNetwork;
  const [hovered, setHovered] = useState<Hover | null>(null);
  const [pinned, setPinned] = useState(false);

  // Arriving from the dashboard's Show on map button. The list cannot fly
  // anywhere, so the map has to be the visible half first.
  useEffect(() => {
    if (!focusSession) return;
    // Nothing to fly to without a location, so let it go now rather than
    // leaving it waiting to fire on some later visit.
    if (focusSession.geo?.lat == null) {
      onFocusUsed?.();
      return;
    }
    if (canDrawMap) choose("map");
    setShowLive(true);
    localStorage.setItem("layer.live", "on");
    // Deliberately not pinning here: the hover handler ignores a new session
    // while something is already pinned, so pinning first would swallow the
    // card this was meant to open. MapCanvas pins it once it is placed.
    setPinned(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusSession]);

  function toggleLayer(name: string, value: boolean, set: (v: boolean) => void) {
    set(value);
    localStorage.setItem(`layer.${name}`, value ? "on" : "off");
  }

  // A place that no longer matches the filters shouldn't keep its panel open.
  useEffect(() => setSelected(null), [query]);

  const features = points.data?.features ?? [];

  // Arriving from a profile's Where from: once the points for the new filters
  // are in, open the nearest one and fly there. Consumed either way, so it
  // does not fire again on a later visit.
  const [flyTarget, setFlyTarget] = useState<{ center: [number, number]; at: number } | null>(null);
  useEffect(() => {
    if (!focusPlace || !points.data || points.loading) return;
    let nearest: MapPoint | null = null;
    let best = Infinity;
    for (const f of points.data.features) {
      const d = (f.properties.lat - focusPlace.lat) ** 2 + (f.properties.lon - focusPlace.lon) ** 2;
      if (d < best) {
        best = d;
        nearest = f;
      }
    }
    // Within roughly half a degree, so a place with no plays under these
    // filters does not open somewhere else entirely.
    if (nearest && best < 0.25) setSelected(nearest);
    if (canDrawMap) choose("map");
    setFlyTarget({ center: [focusPlace.lon, focusPlace.lat], at: Date.now() });
    onFocusPlaceUsed?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusPlace, points.data, points.loading]);

  return (
    <div className="map-page">
      <FilterBar value={filters} onChange={onFilters} />

      <div className="viewbar">
        <div className="segmented">
          <button
            className={view === "map" ? "seg on" : "seg"}
            onClick={() => choose("map")}
            disabled={!canDrawMap}
            title={canDrawMap ? "Show the map" : "This browser has no WebGL, so the map can't draw"}
          >
            Map
          </button>
          <button className={view === "list" ? "seg on" : "seg"} onClick={() => choose("list")}>
            List
          </button>
        </div>
        {view === "map" && canDrawMap && (
          <div className="row layer-toggles">
            <label className="check">
              <input
                type="checkbox"
                checked={showHistory}
                onChange={(e) => toggleLayer("history", e.target.checked, setShowHistory)}
              />
              History
            </label>
            <label className="check">
              <input
                type="checkbox"
                checked={showAccuracy}
                onChange={(e) => toggleLayer("accuracy", e.target.checked, setShowAccuracy)}
              />
              Accuracy
            </label>
            <label className="check" title="Density instead of individual pins">
              <input
                type="checkbox"
                checked={showHeat}
                onChange={(e) => toggleLayer("heat", e.target.checked, setShowHeat)}
              />
              Heat
            </label>
            {showHeat && (
              <div className="segmented heat-metric" title="What the heat counts at each place">
                {(["plays", "devices", "users"] as HeatMetric[]).map((metric) => (
                  <button
                    key={metric}
                    className={heatMetric === metric ? "seg on" : "seg"}
                    onClick={() => {
                      setHeatMetric(metric);
                      localStorage.setItem("layer.heatMetric", metric);
                    }}
                    title={
                      metric === "plays"
                        ? "Every play counts"
                        : `Distinct ${metric} seen at each place. One seen in several places counts in each.`
                    }
                  >
                    {metric === "plays" ? "Plays" : metric === "devices" ? "Devices" : "Users"}
                  </button>
                ))}
              </div>
            )}
            <label className="check" title="Where banned devices played from, and where they tried to stream after the ban">
              <input
                type="checkbox"
                checked={showBanned}
                onChange={(e) => toggleLayer("banned", e.target.checked, setShowBanned)}
              />
              Banned
              {bans.ids.size > 0 && <span className="ms-count banned">{bans.ids.size}</span>}
            </label>
            <label className="check">
              <input
                type="checkbox"
                checked={showLive}
                onChange={(e) => toggleLayer("live", e.target.checked, setShowLive)}
              />
              Live
              {liveSessions.length > 0 && (
                <span className="ms-count live">{liveSessions.length}</span>
              )}
            </label>
            {onNetwork > 0 && (
              <span className="muted small" title="An address on your own network has no public location">
                {onNetwork} on your network, not mappable
              </span>
            )}
            {unlocated > 0 && (
              <span className="muted small" title="The location database has no answer for this address yet">
                {unlocated} waiting for a location
              </span>
            )}
          </div>
        )}

        {!canDrawMap && (
          <span className="muted small">
            No WebGL here, so showing the list instead. The map works in a browser with graphics
            acceleration.
          </span>
        )}
      </div>

      <div className="view-body">
        {view === "map" ? (
          <MapCanvas
            features={features}
            onSelect={setSelected}
            showHistory={showHistory}
            showAccuracy={showAccuracy}
            liveSessions={showLive ? liveSessions : []}
            onHoverLive={(h) => {
              // A pinned flyout stays put until it is dismissed.
              if (!pinned) setHovered(h);
            }}
            onPinLive={() => setPinned(true)}
            focusSession={focusSession}
            onFocusUsed={onFocusUsed}
            flyTarget={flyTarget}
            showHeat={showHeat}
            heatMetric={heatMetric}
            banned={showBanned ? bannedPoints.data ?? null : null}
            countryModes={showCountries && nav.isAdmin ? modes : null}
            onPickCountry={(code, name) => setPicked({ code, name })}
          />
        ) : (
          <LocationList features={features} selected={selected} onSelect={setSelected} />
        )}

        <Legend
          isAdmin={nav.isAdmin}
          heat={showHeat}
          countries={showCountries}
          listed={Object.keys(modes).length}
          onCountries={(on) => {
            toggleLayer("countries", on, setShowCountries);
            if (!on) setPicked(null);
          }}
        />

        {picked && (
          <CountryPicker
            code={picked.code}
            name={picked.name}
            mode={modes[picked.code] ?? null}
            onClose={() => setPicked(null)}
            onChanged={() => {
              blocked.reload();
              setPicked(null);
            }}
          />
        )}

        {!geoipReady && (
          <div className="map-banner">
            {nav.isAdmin
              ? "No location database installed, so there's nothing to place yet. Add a MaxMind key in Settings."
              : "Locations are not set up on this server yet, so there is nothing to place. Ask an admin."}
          </div>
        )}
        {geoipReady && features.length === 0 && !points.loading && (
          <div className="map-banner">Nothing to show yet. The first sync may still be running.</div>
        )}
        {points.error && <div className="map-banner bad">{points.error}</div>}

        {summary.data && (
          <div className="summary">
            <Tile label="Plays" value={summary.data.plays} />
            <Tile label="Users" value={summary.data.users} />
            <Tile label="Devices" value={summary.data.devices} />
            <Tile label="Locations" value={features.length} />
            <Tile label="Hours" value={Math.round(summary.data.seconds / 3600)} />
          </div>
        )}

        {hovered && (
          <LiveFlyout
            session={hovered.session}
            x={hovered.x}
            y={hovered.y}
            pinned={pinned}
            onClose={() => {
              setHovered(null);
              setPinned(false);
            }}
            onTerminated={live.reload}
          />
        )}

        {selected && (
          <Drawer
            place={selected.properties}
            lat={selected.properties.lat}
            lon={selected.properties.lon}
            filterQuery={query}
            onClose={() => setSelected(null)}
            onOpenUser={onOpenUser}
            onFilterToTitle={(ratingKey, title) => {
              onFilters({ ...filters, rating_key: ratingKey, ratingKeyLabel: title });
              setSelected(null);
            }}
          />
        )}
      </div>

      {view === "map" && canDrawMap && (
        <TimeScrubber filters={filters} onChange={onFilters} />
      )}
    </div>
  );
}

/* ---- map --------------------------------------------------------------- */

/* A circle on the ground, as a polygon.
 *
 * MapLibre's circle-radius is in screen pixels, which would keep a 50 km
 * uncertainty the same size whether you are looking at a continent or a
 * street. A real polygon stays true to the ground instead.
 */
function groundCircle(lon: number, lat: number, km: number, steps = 64): GeoJSON.Polygon {
  const latDelta = km / 110.574;
  const lonDelta = km / (111.32 * Math.cos((lat * Math.PI) / 180) || 1);
  const ring: [number, number][] = [];
  for (let i = 0; i <= steps; i++) {
    const angle = (i / steps) * 2 * Math.PI;
    ring.push([lon + lonDelta * Math.cos(angle), lat + latDelta * Math.sin(angle)]);
  }
  return { type: "Polygon", coordinates: [ring] };
}

type Hover = { session: LiveSession; x: number; y: number };

function MapCanvas({
  features,
  onSelect,
  showHistory,
  showAccuracy,
  liveSessions,
  onHoverLive,
  onPinLive,
  focusSession,
  onFocusUsed,
  flyTarget,
  showHeat,
  heatMetric,
  banned,
  countryModes,
  onPickCountry,
}: {
  features: MapPoint[];
  onSelect: (feature: MapPoint) => void;
  showHistory: boolean;
  showAccuracy: boolean;
  liveSessions: LiveSession[];
  onHoverLive: (hover: Hover | null) => void;
  onPinLive: () => void;
  focusSession?: LiveSession | null;
  onFocusUsed?: () => void;
  flyTarget?: { center: [number, number]; at: number } | null;
  showHeat: boolean;
  heatMetric: HeatMetric;
  banned: GeoJSON.FeatureCollection | null;
  /* Country code to flag, warn or stop. Null when the layer is off. */
  countryModes: Record<string, string> | null;
  onPickCountry: (code: string, name: string) => void;
}) {
  const nav = useNav();
  const openDeviceRef = useRef(nav.openDevice);
  openDeviceRef.current = nav.openDevice;
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const [ready, setReady] = useState(false);
  const [mapError, setMapError] = useState<string | null>(null);

  // Map event handlers are registered once and would otherwise capture the
  // first render's values forever, so the live data is read through refs.
  const liveRef = useRef(liveSessions);
  liveRef.current = liveSessions;
  const onHoverRef = useRef(onHoverLive);
  onHoverRef.current = onHoverLive;
  const onPinRef = useRef(onPinLive);
  onPinRef.current = onPinLive;

  useEffect(() => {
    if (!container.current || map.current) return;

    let m: maplibregl.Map;
    try {
      m = new maplibregl.Map({
        container: container.current,
        style: buildMapStyle(),
        center: lastView().center,
        zoom: lastView().zoom,
        attributionControl: { compact: true },
      });
    } catch (err) {
      setMapError(`The map couldn't start: ${(err as Error).message}`);
      return;
    }

    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    m.on("load", () => setReady(true));
    // Off unless localStorage has debug.map set: lets a browser test reach the
    // map to compare where a pin is drawn with where it answers the pointer.
    try {
      if (localStorage.getItem("debug.map")) (window as unknown as { __map?: maplibregl.Map }).__map = m;
    } catch {
      /* storage unavailable */
    }
    // MapLibre swallows style and tile failures by default, which turns a bad
    // source into a blank rectangle with no explanation.
    m.on("error", (e) => {
      console.error("map error:", e.error?.message ?? e);
      setMapError(e.error?.message ?? "Map failed to load");
    });
    map.current = m;

    // A map created while its container is hidden or still laying out comes up
    // 0x0 and never fetches a tile, because MapLibre measures once.
    const observer = new ResizeObserver(() => m.resize());
    observer.observe(container.current);

    return () => {
      observer.disconnect();
      rememberView(m);
      m.remove();
      map.current = null;
      setReady(false);
    };
  }, []);

  // Restyle on theme change.
  useEffect(() => {
    const observer = new MutationObserver(() => {
      if (!map.current) return;
      setReady(false);
      map.current.setStyle(buildMapStyle());
      map.current.once("styledata", () => setReady(true));
    });
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-theme"],
    });
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const m = map.current;
    if (!m || !ready) return;

    const shown = showHistory ? features : [];
    const data: MapPoints = { type: "FeatureCollection", features: shown };

    const circles = m.getSource("accuracy") as maplibregl.GeoJSONSource | undefined;
    if (circles) {
      circles.setData({
        type: "FeatureCollection",
        features:
          showAccuracy && showHistory
            ? shown
                .filter((f) => f.properties.accuracy_km)
                .map((f) => ({
                  type: "Feature" as const,
                  properties: { accuracy_km: f.properties.accuracy_km },
                  geometry: groundCircle(
                    f.geometry.coordinates[0],
                    f.geometry.coordinates[1],
                    f.properties.accuracy_km as number,
                  ),
                }))
            : [],
      });
    }

    const heat = m.getSource("heat") as maplibregl.GeoJSONSource | undefined;
    if (heat) heat.setData(showHeat ? data : { type: "FeatureCollection", features: [] });

    for (const [id, visible] of [
      ["heat", showHeat],
      ["clusters", !showHeat],
      ["cluster-count", !showHeat],
      ["points", !showHeat],
    ] as [string, boolean][]) {
      if (m.getLayer(id)) {
        m.setLayoutProperty(id, "visibility", visible ? "visible" : "none");
      }
    }

    const existing = m.getSource("plays") as maplibregl.GeoJSONSource | undefined;
    if (existing) {
      existing.setData(data);
      return;
    }

    m.addSource("accuracy", { type: "geojson", data: emptyCollection() });
    m.addLayer(
      {
        id: "accuracy-fill",
        type: "fill",
        source: "accuracy",
        paint: {
          "fill-color": css("--map-accuracy", "#7fb4d8"),
          // Faint, and fainter still the less certain the fix is. A 5 km
          // circle is a real claim and reads solid; a 1000 km one is barely
          // a claim at all and should look like it. Overlaps then build up
          // like a heatmap, which is honest: more plays, more colour.
          "fill-opacity": [
            "interpolate",
            ["linear"],
            ["get", "accuracy_km"],
            5, 0.20,
            50, 0.12,
            200, 0.07,
            1000, 0.035,
          ],
        },
      },
      // Under the labels. On top of them, city names became unreadable.
      firstSymbolLayer(m),
    );

    // Unclustered copy of the same points. A heatmap wants every point, not
    // a handful of cluster centroids, which would produce a few hot blobs
    // wherever clustering happened to land.
    m.addSource("heat", { type: "geojson", data: emptyCollection() });
    m.addLayer(
      {
        id: "heat",
        type: "heatmap",
        source: "heat",
        layout: { visibility: "none" },
        paint: {
          "heatmap-weight": heatWeight("plays"),
          "heatmap-color": [
            "interpolate", ["linear"], ["heatmap-density"],
            0, css("--map-heat-1", "rgba(34,211,238,0)"),
            0.2, css("--map-heat-2", "#22d3ee"),
            0.45, css("--map-heat-3", "#818cf8"),
            0.7, css("--map-heat-4", "#f472b6"),
            1, css("--map-heat-5", "#fde047"),
          ],
          "heatmap-intensity": ["interpolate", ["linear"], ["zoom"], 0, 1, 9, 3],
          "heatmap-radius": ["interpolate", ["linear"], ["zoom"], 0, 12, 9, 40],
          "heatmap-opacity": 0.75,
        },
      },
      firstSymbolLayer(m),
    );

    m.addSource("plays", {
      type: "geojson",
      data,
      cluster: true,
      clusterRadius: 45,
      clusterMaxZoom: 12,
      // Cluster totals sum plays, not pins, so one busy city outweighs a dozen
      // one-off locations. `hosting` lets the circle be coloured honestly.
      clusterProperties: {
        plays: ["+", ["get", "plays"]],
        hosting: ["+", ["case", ["get", "is_hosting"], 1, 0]],
      },
    });

    m.addLayer({
      id: "clusters",
      type: "circle",
      source: "plays",
      filter: ["has", "point_count"],
      paint: {
        // The VPN colour only when every location inside is a hosting or VPN
        // origin, so a mixed cluster never hides ordinary plays.
        "circle-color": [
          "case",
          ["==", ["get", "hosting"], ["get", "point_count"]],
          css("--vpn", "#a78bfa"),
          css("--map-point", "#22d3ee"),
        ],
        "circle-opacity": 0.85,
        "circle-stroke-width": 2,
        "circle-stroke-color": css("--surface", "#fff"),
        "circle-radius": ["interpolate", ["linear"], ["get", "plays"], 1, 16, 500, 26, 5000, 38],
      },
    });

    m.addLayer({
      id: "cluster-count",
      type: "symbol",
      source: "plays",
      filter: ["has", "point_count"],
      layout: {
        "text-field": ["number-format", ["get", "plays"], { "max-fraction-digits": 0 }],
        "text-font": ["Open Sans Regular"],
        "text-size": 12,
      },
      paint: { "text-color": css("--accent-ink", "#fff") },
    });

    m.addLayer({
      id: "points",
      type: "circle",
      source: "plays",
      filter: ["!", ["has", "point_count"]],
      paint: {
        "circle-color": [
          "case",
          ["get", "is_hosting"],
          css("--vpn", "#a78bfa"),
          css("--map-point", "#22d3ee"),
        ],
        "circle-opacity": 0.9,
        "circle-stroke-width": 2,
        "circle-stroke-color": css("--surface", "#fff"),
        "circle-radius": ["interpolate", ["linear"], ["get", "plays"], 1, 6, 100, 12, 2000, 20],
      },
    });

    m.on("click", "clusters", (e) => {
      const feature = e.features?.[0];
      if (!feature) return;
      const source = m.getSource("plays") as maplibregl.GeoJSONSource;
      source.getClusterExpansionZoom(feature.properties!.cluster_id).then((zoom) => {
        m.easeTo({
          center: (feature.geometry as GeoJSON.Point).coordinates as [number, number],
          zoom,
        });
      });
    });

    m.on("click", "points", (e) => {
      const feature = e.features?.[0];
      if (!feature) return;
      onSelect({
        type: "Feature",
        geometry: feature.geometry as GeoJSON.Point,
        properties: feature.properties as unknown as Place,
      } as MapPoint);
    });

    for (const layer of ["clusters", "points"]) {
      m.on("mouseenter", layer, () => (m.getCanvas().style.cursor = "pointer"));
      m.on("mouseleave", layer, () => (m.getCanvas().style.cursor = ""));
    }
  }, [ready, features, onSelect, showHistory, showAccuracy, showHeat]);

  useEffect(() => {
    const m = map.current;
    if (!m || !ready || !m.getLayer("heat")) return;
    m.setPaintProperty("heat", "heatmap-weight", heatWeight(heatMetric));
  }, [ready, heatMetric]);

  // ---- fly to a place ------------------------------------------------------
  useEffect(() => {
    const m = map.current;
    if (!m || !flyTarget) return;
    m.flyTo({ center: flyTarget.center, zoom: Math.max(m.getZoom(), 8), duration: 900 });
  }, [ready, flyTarget]);

  // ---- fly to one stream -------------------------------------------------
  useEffect(() => {
    // Not gated on the style having loaded: the camera and the projection both
    // work before that, and waiting would drop the request if the basemap is
    // slow or unreachable.
    const m = map.current;
    if (!m || !focusSession?.geo?.lat) return;

    const at: [number, number] = [focusSession.geo.lon as number, focusSession.geo.lat as number];

    // The card is placed from the pin's screen position, which is only final
    // once the camera has stopped.
    let done = false;
    const place = () => {
      if (done) return;
      done = true;
      const point = m.project(at);
      onHoverRef.current({ session: focusSession, x: point.x, y: point.y });
      onPinRef.current();
      onFocusUsed?.();
    };

    // Listener first: a flyTo that has nowhere to go finishes before the call
    // returns, and the card would never open.
    m.once("moveend", place);
    const fallback = setTimeout(place, 1200);
    m.flyTo({ center: at, zoom: Math.max(m.getZoom(), 7), duration: 900 });

    return () => {
      clearTimeout(fallback);
      m.off("moveend", place);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, focusSession]);

  // ---- banned devices ----------------------------------------------------
  useEffect(() => {
    const m = map.current;
    if (!m || !ready) return;
    const data = banned ?? { type: "FeatureCollection" as const, features: [] };

    const existing = m.getSource("banned") as maplibregl.GeoJSONSource | undefined;
    if (existing) {
      existing.setData(data);
      return;
    }
    m.addSource("banned", { type: "geojson", data });

    const red = css("--banned", "#f85149");
    // Where it played from: a ring, since it is history, not an event.
    m.addLayer({
      id: "banned-seen",
      type: "circle",
      source: "banned",
      filter: ["==", ["get", "kind"], "seen"],
      paint: {
        "circle-color": "rgba(0,0,0,0)",
        "circle-stroke-color": red,
        "circle-stroke-width": 2,
        "circle-radius": ["interpolate", ["linear"], ["get", "count"], 1, 7, 100, 12, 1000, 18],
      },
    });
    // Where it tried after the ban: a solid dot, the thing worth noticing.
    m.addLayer({
      id: "banned-attempt",
      type: "circle",
      source: "banned",
      filter: ["==", ["get", "kind"], "attempt"],
      paint: {
        "circle-color": red,
        "circle-stroke-color": css("--surface", "#fff"),
        "circle-stroke-width": 2,
        "circle-radius": ["interpolate", ["linear"], ["get", "count"], 1, 6, 20, 10, 200, 14],
      },
    });

    for (const layer of ["banned-seen", "banned-attempt"]) {
      m.on("mouseenter", layer, () => (m.getCanvas().style.cursor = "pointer"));
      m.on("mouseleave", layer, () => (m.getCanvas().style.cursor = ""));
      m.on("click", layer, (e) => {
        const id = e.features?.[0]?.properties?.machine_id;
        if (id) openDeviceRef.current?.(String(id));
      });
    }
  }, [ready, banned]);

  // ---- countries ---------------------------------------------------------
  //
  // Boundaries ship with the app (Natural Earth, public domain, trimmed to a
  // code and a name), so choosing a country is done on the map rather than
  // from a list of names, and what the list already says is shaded in.
  const pickCountryRef = useRef(onPickCountry);
  pickCountryRef.current = onPickCountry;

  useEffect(() => {
    const m = map.current;
    if (!m || !ready || !countryModes) return;
    let cancelled = false;

    (async () => {
      if (!m.getSource("countries")) {
        const shapes = (await import("../assets/countries.json")).default as unknown as GeoJSON.FeatureCollection;
        if (cancelled || !map.current) return;
        m.addSource("countries", { type: "geojson", data: shapes });
        // Under the pins: places and streams stay the thing you click most.
        const under = ["heat", "clusters", "points", "accuracy-fill"].find((id) => m.getLayer(id));
        m.addLayer({ id: "country-fill", type: "fill", source: "countries", paint: { "fill-color": "rgba(0,0,0,0)" } }, under);
        m.addLayer({ id: "country-line", type: "line", source: "countries", paint: { "line-color": "rgba(0,0,0,0)", "line-width": 1 } }, under);
        m.on("mouseenter", "country-fill", () => (m.getCanvas().style.cursor = "pointer"));
        m.on("mouseleave", "country-fill", () => (m.getCanvas().style.cursor = ""));
        m.on("click", "country-fill", (e) => {
          // A country sits under everything, so a click meant for a pin would
          // otherwise open the country picker as well as the place.
          const pins = ["points", "clusters", "live-dot", "live-ring", "banned-seen", "banned-attempt"].filter((id) => m.getLayer(id));
          if (m.queryRenderedFeatures(e.point, { layers: pins }).length) return;
          const props = e.features?.[0]?.properties;
          if (props?.code) pickCountryRef.current(String(props.code), String(props.name ?? props.code));
        });
      }
      if (cancelled) return;
      // One colour per mode, everything else barely there but still clickable.
      const colour: Record<string, string> = {
        stop: css("--banned", "#f85149"),
        warn: css("--warn", "#d29922"),
        flag: css("--accent", "#22d3ee"),
      };
      const fill: (string | unknown[])[] = ["match", ["get", "code"]];
      const line: (string | unknown[])[] = ["match", ["get", "code"]];
      for (const [code, mode] of Object.entries(countryModes)) {
        fill.push(code, colour[mode] ?? colour.flag);
        line.push(code, colour[mode] ?? colour.flag);
      }
      const plainFill = "rgba(127,127,127,0.06)";
      const plainLine = "rgba(127,127,127,0.25)";
      fill.push(plainFill);
      line.push(plainLine);
      // A match needs at least one case, so with nothing listed the colour is
      // the plain one rather than an expression MapLibre would refuse.
      const listed = Object.keys(countryModes).length > 0;
      m.setPaintProperty("country-fill", "fill-color", listed ? (fill as maplibregl.ExpressionSpecification) : plainFill);
      m.setPaintProperty("country-fill", "fill-opacity", 0.35);
      m.setPaintProperty("country-line", "line-color", listed ? (line as maplibregl.ExpressionSpecification) : plainLine);
    })();

    return () => {
      cancelled = true;
    };
  }, [ready, countryModes]);

  // Layers stay loaded once added, so turning the layer off hides them.
  useEffect(() => {
    const m = map.current;
    if (!m || !ready) return;
    for (const id of ["country-fill", "country-line"]) {
      if (m.getLayer(id)) m.setLayoutProperty(id, "visibility", countryModes ? "visible" : "none");
    }
  }, [ready, countryModes]);

  // ---- live streams ------------------------------------------------------
  useEffect(() => {
    const m = map.current;
    if (!m || !ready) return;

    const data: GeoJSON.FeatureCollection = {
      type: "FeatureCollection",
      features: liveSessions.map((s) => ({
        type: "Feature",
        properties: { session_key: s.session_key },
        geometry: {
          type: "Point",
          coordinates: [s.geo!.lon as number, s.geo!.lat as number],
        },
      })),
    };

    const existing = m.getSource("live") as maplibregl.GeoJSONSource | undefined;
    if (existing) {
      existing.setData(data);
      return;
    }

    m.addSource("live", { type: "geojson", data });

    // A ring in its own colour, not a filled dot. Shape as well as colour,
    // because colour alone fails for anyone colour blind and washes out
    // against a dark basemap.
    m.addLayer({
      id: "live-halo",
      type: "circle",
      source: "live",
      paint: {
        "circle-color": css("--live", "#fbbf24"),
        "circle-opacity": 0.18,
        "circle-radius": 22,
      },
    });
    m.addLayer({
      id: "live-ring",
      type: "circle",
      source: "live",
      paint: {
        "circle-color": "rgba(0,0,0,0)",
        "circle-stroke-color": css("--live", "#fbbf24"),
        "circle-stroke-width": 3,
        "circle-radius": 11,
      },
    });
    m.addLayer({
      id: "live-dot",
      type: "circle",
      source: "live",
      paint: { "circle-color": css("--live", "#fbbf24"), "circle-radius": 4 },
    });

    const show = (e: maplibregl.MapLayerMouseEvent) => {
      const key = String(e.features?.[0]?.properties?.session_key ?? "");
      const session = liveRef.current.find((s) => s.session_key === key);
      if (!session) return;
      m.getCanvas().style.cursor = "pointer";
      onHoverRef.current({ session, x: e.point.x, y: e.point.y });
    };

    for (const layer of ["live-halo", "live-ring", "live-dot"]) {
      m.on("mouseenter", layer, show);
      m.on("mousemove", layer, show);
      // Clicking pins it open, so the flyout survives the pointer wandering
      // off on the way to a button.
      m.on("click", layer, (e) => {
        show(e);
        onPinRef.current();
      });
      m.on("mouseleave", layer, () => {
        m.getCanvas().style.cursor = "";
        // Hovering only previews. The preview closes when the pointer leaves
        // the pin, so passing over a stream while panning does not leave a
        // card in the way. Clicking pins it, and a pinned card ignores this.
        onHoverRef.current(null);
      });
    }
  }, [ready, liveSessions]);


  return (
    <>
      <div ref={container} className="map" />
      {mapError && <div className="map-banner bad">{mapError}</div>}
    </>
  );
}

/* ---- list -------------------------------------------------------------- */

type SortKey = "place" | "plays" | "users" | "devices" | "ips" | "last_play";

function LocationList({
  features,
  selected,
  onSelect,
}: {
  features: MapPoint[];
  selected: MapPoint | null;
  onSelect: (feature: MapPoint) => void;
}) {
  const [sort, setSort] = useState<SortKey>("plays");
  const [asc, setAsc] = useState(false);

  const rows = useMemo(() => {
    const value = (p: Place) =>
      sort === "place" ? placeName(p).toLowerCase() : (p[sort] as number | null) ?? 0;
    return [...features].sort((a, b) => {
      const [x, y] = [value(a.properties), value(b.properties)];
      const cmp = typeof x === "string" ? x.localeCompare(y as string) : (x as number) - (y as number);
      return asc ? cmp : -cmp;
    });
  }, [features, sort, asc]);

  function header(key: SortKey, label: string, numeric = false) {
    const active = sort === key;
    return (
      <th
        className={`${numeric ? "num " : ""}${active ? "sorted" : ""}`}
        onClick={() => {
          if (active) setAsc(!asc);
          else {
            setSort(key);
            setAsc(key === "place");
          }
        }}
      >
        {label}
        {active && <span className="caret">{asc ? "▲" : "▼"}</span>}
      </th>
    );
  }

  if (features.length === 0) return <div className="list-wrap" />;

  return (
    <div className="list-wrap">
      <table className="table locations">
        <thead>
          <tr>
            {header("place", "Location")}
            <th>Network</th>
            {header("plays", "Plays", true)}
            {header("users", "Users", true)}
            {header("devices", "Devices", true)}
            {header("ips", "IPs", true)}
            {header("last_play", "Last play", true)}
          </tr>
        </thead>
        <tbody>
          {rows.map((f) => {
            const p = f.properties;
            const key = `${f.geometry.coordinates[0]},${f.geometry.coordinates[1]}`;
            const isSelected = selected !== null && selected.properties === p;
            return (
              <tr
                key={key}
                className={isSelected ? "loc-row selected" : "loc-row"}
                onClick={() => onSelect(f)}
              >
                <td>
                  {placeName(p)}
                  {p.is_hosting && <span className="pill vpn">VPN</span>}
                </td>
                <td className="muted">{p.asn_org}</td>
                <td className="num">{p.plays.toLocaleString()}</td>
                <td className="num">{p.users}</td>
                <td className="num">{p.devices}</td>
                <td className="num">{p.ips}</td>
                <td className="num muted">
                  {p.last_play ? new Date(p.last_play * 1000).toLocaleDateString() : "-"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/* ---- shared ------------------------------------------------------------ */

function placeName(p: Place): string {
  return [p.city, p.region, p.country].filter(Boolean).join(", ") || "Unknown location";
}

function Drawer({
  place,
  lat,
  lon,
  filterQuery,
  onClose,
  onFilterToTitle,
  onOpenUser,
}: {
  place: Place;
  lat: number;
  lon: number;
  /* The map's filters as a query string, so the panel lists what the pin shows. */
  filterQuery: string;
  onClose: () => void;
  onFilterToTitle?: (ratingKey: number, title: string) => void;
  onOpenUser?: (userId: number) => void;
}) {
  const nav = useNav();
  const [openMedia, setOpenMedia] = useState<number | null>(null);
  const [tab, setTab] = useState<"who" | "watched">("who");
  const [focus, setFocus] = useState<"users" | "devices" | "addresses" | null>(null);

  // Keyed on coordinates, the same way the map groups pins. Plenty of
  // addresses resolve to a country with no city at all, and keying on city
  // left those panels empty.
  const extra = filterQuery.replace(/^\?/, "");
  const detail = useApi<LocationDetail>(`/location?lat=${lat}&lon=${lon}${extra ? `&${extra}` : ""}`);
  const recent = useApi<HistoryPage>(
    tab === "watched" ? `/location/plays?lat=${lat}&lon=${lon}&size=25${extra ? `&${extra}` : ""}` : null,
  );
  const names = useUserNames();

  function show(which: "users" | "devices" | "addresses") {
    setTab("who");
    setFocus(which);
    // Rendered first, then scrolled to.
    requestAnimationFrame(() =>
      document.getElementById(`loc-${which}`)?.scrollIntoView({ behavior: "smooth", block: "start" }),
    );
  }

  return (
    <aside className="drawer">
      <header>
        <div>
          <h2>{placeName(place)}</h2>
          {place.asn_org && <p className="muted">{place.asn_org}</p>}
        </div>
        <button className="tab" onClick={onClose} aria-label="Close">
          ✕
        </button>
      </header>

      {place.is_hosting && (
        <p className="note vpn-note">
          This traffic comes from a hosting or VPN provider, so the location is where the server
          is, not where the viewer is.
        </p>
      )}

      <dl className="stats">
        <Stat label="Plays" value={place.plays} onClick={() => setTab("watched")} />
        <Stat label="Users" value={place.users} onClick={() => show("users")} />
        <Stat label="Devices" value={place.devices} onClick={() => show("devices")} />
        <Stat label="IPs" value={place.ips} onClick={() => show("addresses")} />
      </dl>

      {place.accuracy_km != null && (
        <p className="muted small">
          Placed within about {place.accuracy_km.toLocaleString()} km. GeoLite2 gives a city
          centroid, not an address, so treat the pin as an area.
        </p>
      )}
      {place.last_play && (
        <p className="muted small">
          Last play {new Date(place.last_play * 1000).toLocaleString()}
        </p>
      )}

      {nav.isAdmin && place.country_code && <BlockCountry code={place.country_code} name={place.country} />}

      <div className="segmented drawer-tabs">
        <button className={tab === "who" ? "seg on" : "seg"} onClick={() => setTab("who")}>
          Who
        </button>
        <button
          className={tab === "watched" ? "seg on" : "seg"}
          onClick={() => setTab("watched")}
        >
          Watched
        </button>
      </div>

      {tab === "who" && (
            <>
              {detail.error && <p className="note bad-note">{detail.error}</p>}

          <h3 id="loc-users" className={focus === "users" ? "lit" : undefined}>Users</h3>
              <div className="mini-list">
                {detail.data?.users.map((u) => (
                  <div key={u.user_id ?? u.name} className="mini">
                    <div>
                      {u.user_id != null && onOpenUser ? (
                        <button className="linkish" onClick={() => onOpenUser(u.user_id as number)}>
                          {u.name}
                        </button>
                      ) : (
                        u.name
                      )}
                      <p className="muted small">last {when(u.last_play)}</p>
                    </div>
                    <span className="muted">{u.plays.toLocaleString()}</span>
                  </div>
                ))}
              </div>

          <h3 id="loc-devices" className={focus === "devices" ? "lit" : undefined}>Devices</h3>
              <div className="mini-list">
                {detail.data?.devices.map((d) => (
                  <div key={d.machine_id} className="mini">
                    <div>
                      {nav.openDevice ? (
                        <button className="linkish" onClick={() => nav.openDevice?.(d.machine_id)}>
                          {d.player || "Unnamed"}
                        </button>
                      ) : (
                        d.player || "Unnamed"
                      )}
                      <p className="muted small">
                        {d.platform} · <code>{d.machine_id.slice(0, 14)}…</code>
                      </p>
                    </div>
                    <span className="muted">{d.plays.toLocaleString()}</span>
                  </div>
                ))}
              </div>

          <h3 id="loc-addresses" className={focus === "addresses" ? "lit" : undefined}>Addresses</h3>
              <div className="mini-list">
                {detail.data?.addresses.map((a) => (
                  <div key={a.ip_address} className="mini">
                    <div>
                      {nav.openAddress ? (
                        <button className="linkish" onClick={() => nav.openAddress?.(a.ip_address)}>
                          <code>{a.ip_address}</code>
                        </button>
                      ) : (
                        <code>{a.ip_address}</code>
                      )}
                      {a.is_hosting && <span className="pill vpn">VPN</span>}
                      <p className="muted small">{a.asn_org}</p>
                    </div>
                    <span className="muted">{a.plays.toLocaleString()}</span>
                  </div>
                ))}
              </div>
            </>
          )}

      {tab === "watched" && (
            <>
              {recent.data?.items.length === 0 && <p className="muted small">Nothing recorded.</p>}
              <div className="mini-list">
                {recent.data?.items.map((row) => (
                  <div key={row.row_id}>
                    <button
                      className="mini as-row"
                      onClick={() =>
                        setOpenMedia(openMedia === row.rating_key ? null : row.rating_key)
                      }
                    >
                      <span>
                        {row.full_title ? displayTitle(row) : <span className="muted">Withheld, another viewer</span>}
                        <span className="muted small block">
                          {row.user_id != null && (nav.openUser || onOpenUser) ? (
                            <span
                              className="linkish"
                              role="link"
                              onClick={(e) => {
                                e.stopPropagation();
                                (onOpenUser ?? nav.openUser)?.(row.user_id as number);
                              }}
                            >
                              {names.get(row.user_id) ?? row.user_id}
                            </span>
                          ) : null}
                          {row.user_id != null && row.player ? " · " : ""}
                          {row.machine_id && nav.openDevice ? (
                            <span
                              className="linkish"
                              role="link"
                              onClick={(e) => {
                                e.stopPropagation();
                                nav.openDevice?.(row.machine_id as string);
                              }}
                            >
                              {row.player}
                            </span>
                          ) : (
                            row.player
                          )}
                          {row.transcode_decision === "transcode" ? " · transcode" : ""}
                        </span>
                      </span>
                      <span className="muted small">
                        {row.started ? new Date(row.started * 1000).toLocaleDateString() : ""}
                      </span>
                    </button>
                    {openMedia === row.rating_key && row.rating_key !== null && (
                      <MediaPanel ratingKey={row.rating_key} onFilterToTitle={onFilterToTitle} />
                    )}
                  </div>
                ))}
              </div>
        </>
      )}
    </aside>
  );
}


/* A live stream's popup, next to its map pin.
 *
 * The content is the shared StreamDetail, the same one the dashboard shows,
 * so the facts, links and actions match wherever a stream is opened. This
 * only adds what a popup needs: a position, dragging, and closing.
 */
function LiveFlyout({
  session,
  x,
  y,
  pinned,
  onClose,
  onTerminated,
}: {
  session: LiveSession;
  x: number;
  y: number;
  pinned: boolean;
  onClose: () => void;
  onTerminated?: () => void;
}) {
  // Dragged by any part that is not a control, because it opens over the pin
  // it describes and that is exactly the part of the map you want to look at.
  const [offset, setOffset] = useState({ dx: 0, dy: 0 });
  const [dragging, setDragging] = useState(false);
  const from = useRef<{ x: number; y: number; dx: number; dy: number } | null>(null);

  useEffect(() => setOffset({ dx: 0, dy: 0 }), [session.session_key]);

  function startDrag(e: React.PointerEvent) {
    if ((e.target as HTMLElement).closest("button, a, input, textarea, select, .stream-summary, .ms")) return;
    from.current = { x: e.clientX, y: e.clientY, dx: offset.dx, dy: offset.dy };
    setDragging(true);
    e.currentTarget.setPointerCapture(e.pointerId);
  }

  function moveDrag(e: React.PointerEvent) {
    const start = from.current;
    if (!start) return;
    setOffset({ dx: start.dx + e.clientX - start.x, dy: start.dy + e.clientY - start.y });
  }

  function endDrag(e: React.PointerEvent) {
    if (!from.current) return;
    from.current = null;
    setDragging(false);
    e.currentTarget.releasePointerCapture(e.pointerId);
  }

  const moved = offset.dx !== 0 || offset.dy !== 0;
  // The card is tall, so a pin near the top of the map opens it below the pin
  // rather than off the top of the screen.
  const below = y < 360;

  return (
    <div
      className={["flyout", pinned || moved ? "pinned" : "", dragging ? "dragging" : ""].filter(Boolean).join(" ")}
      style={{
        left: x,
        top: y,
        transform: below
          ? `translate(calc(-50% + ${offset.dx}px), calc(20px + ${offset.dy}px))`
          : `translate(calc(-50% + ${offset.dx}px), calc(-100% - 20px + ${offset.dy}px))`,
      }}
      // Once it has been moved it stays put: dragging something away only to
      // have it close when the pointer leaves would be useless.
      // An unpinned card is a preview: it closes with the pin's hover, and it
      // lets the pointer through so it never blocks dragging the map.
      onMouseLeave={pinned || moved || dragging ? undefined : onClose}
      onPointerDown={startDrag}
      onPointerMove={moveDrag}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
      role="dialog"
    >
      <StreamDetail session={session} onClose={onClose} onChanged={onTerminated} compact onMap />
    </div>
  );
}

function Stat({
  label,
  value,
  onClick,
}: {
  label: string;
  value: number;
  onClick?: () => void;
}) {
  return (
    <div
      className={onClick ? "stat clickable" : "stat"}
      onClick={onClick}
      role={onClick ? "button" : undefined}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={(e) => {
        if (onClick && (e.key === "Enter" || e.key === " ")) onClick();
      }}
    >
      <dt>{label}</dt>
      <dd>{value.toLocaleString()}</dd>
    </div>
  );
}

function Tile({ label, value }: { label: string; value: number }) {
  return (
    <div className="summary-tile">
      <span className="summary-value">{value.toLocaleString()}</span>
      <span className="summary-label">{label}</span>
    </div>
  );
}

type HeatMetric = "plays" | "devices" | "users";

/* How much each place adds to the heat.
 *
 * Flattened with a square root and scaled per measure, so a city with 9,000
 * plays does not wash out everywhere else, and a count of devices (usually a
 * handful per place) still shows up at all. Devices and users are distinct
 * counts per place within the current filters: one device seen in three
 * cities warms all three, which is what "devices seen here" means.
 */
function heatWeight(metric: HeatMetric): maplibregl.ExpressionSpecification {
  // The square root at which a place counts as fully hot. Plays keep the
  // scale the map always used; the distinct counts are far smaller numbers.
  const hot = metric === "plays" ? 100 : metric === "devices" ? 5 : 4;
  return ["interpolate", ["linear"], ["sqrt", ["get", metric]], 0, 0, hot, 1];
}

/* Pin colours come from the same tokens as the basemap. */
const css = (name: string, fallback: string) =>
  getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;

/* Where the map was last looked at.
 *
 * The map is unmounted when another tab is opened, so without this every visit
 * snapped back to the whole of North America and any zooming had to be redone.
 */
const VIEW_KEY = "map.view";

function lastView(): { center: [number, number]; zoom: number } {
  try {
    const saved = JSON.parse(localStorage.getItem(VIEW_KEY) ?? "");
    if (Array.isArray(saved?.center) && typeof saved?.zoom === "number") return saved;
  } catch {
    /* nothing saved, or unreadable */
  }
  return { center: [-98, 39], zoom: 3 };
}

function rememberView(map: maplibregl.Map): void {
  try {
    const center = map.getCenter();
    localStorage.setItem(
      VIEW_KEY,
      JSON.stringify({ center: [center.lng, center.lat], zoom: map.getZoom() }),
    );
  } catch {
    /* storage unavailable, the default view is fine */
  }
}

function emptyCollection(): GeoJSON.FeatureCollection {
  return { type: "FeatureCollection", features: [] };
}

/* The first text layer in the style, so overlays can be slipped underneath it
 * rather than burying the place names. */
function firstSymbolLayer(map: maplibregl.Map): string | undefined {
  return map.getStyle().layers?.find((l) => l.type === "symbol")?.id;
}


/* Add the country this pin is in to the country list, from the map. Flag to
 * start with: it records every stream from there without cutting anyone off,
 * and the mode can be raised in Rules once you have seen what it catches. */
function BlockCountry({ code, name }: { code: string; name: string | null }) {
  const [state, setState] = useState<"idle" | "saving" | "done" | string>("idle");
  const listed = useApi<{ items: { code: string; mode: string }[] }>("/geoblocks");
  const already = listed.data?.items.find((c) => c.code === code.toUpperCase());

  if (already) {
    return (
      <p className="muted small">
        {name || code} is on the country list, set to {already.mode}. Change it in Rules.
      </p>
    );
  }
  return (
    <p className="muted small">
      <button
        className="tab"
        disabled={state === "saving" || state === "done"}
        onClick={async () => {
          const reason = window.prompt(`Why add ${name || code} to the country list? Streams from there will be recorded.`, "");
          if (reason === null) return;
          setState("saving");
          try {
            await api.post("/geoblocks", { code, mode: "flag", reason });
            setState("done");
            listed.reload();
          } catch (err) {
            setState((err as Error).message);
          }
        }}
      >
        {state === "done" ? `${name || code} is flagged` : `Flag streams from ${name || code}`}
      </button>
      {typeof state === "string" && !["idle", "saving", "done"].includes(state) && <span className="danger-text"> {state}</span>}
    </p>
  );
}


/* Clicked a country: what happens when a stream comes from there.
 *
 * Flag records it and nothing else, which is where a country should usually
 * start; warn messages the viewer; stop ends the stream. The same list lives
 * under Rules, with what it would have caught before it is allowed to act. */
function CountryPicker({
  code,
  name,
  mode,
  onClose,
  onChanged,
}: {
  code: string;
  name: string;
  mode: string | null;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const seen = useApi<{ code: string; name: string; plays: number }[]>("/geoblocks/countries");
  const here = seen.data?.find((c) => c.code === code);

  async function set(next: string | null) {
    setBusy(true);
    setError(null);
    try {
      if (next === null) await api.del(`/geoblocks/${code}`);
      else await api.post("/geoblocks", { code, mode: next, reason: "" });
      onChanged();
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  return (
    <div className="country-picker">
      <div className="row-between">
        <strong>{name}</strong>
        <button className="tab" onClick={onClose} aria-label="Close">
          ✕
        </button>
      </div>
      <p className="muted small">
        {here ? `${here.plays.toLocaleString()} ${here.plays === 1 ? "play" : "plays"} from here` : "Nothing has been watched from here"}
        {mode ? ` \u00b7 currently ${mode}` : ""}
      </p>
      {error && <p className="note bad-note">{error}</p>}
      <div className="segmented">
        {[
          { id: "flag", label: "Flag" },
          { id: "warn", label: "Warn" },
          { id: "stop", label: "Stop" },
        ].map((m) => (
          <button key={m.id} className={mode === m.id ? "seg on" : "seg"} disabled={busy} onClick={() => set(m.id)}>
            {m.label}
          </button>
        ))}
      </div>
      {mode && (
        <button className="tab" disabled={busy} onClick={() => set(null)}>
          Take off the list
        </button>
      )}
      <p className="muted small">Flag records the stream. Warn messages the viewer. Stop ends it.</p>
    </div>
  );
}


/* What the colours mean, folded away until someone wants it.
 *
 * The map says a lot at a glance: size is how much was watched, purple is a
 * VPN, red is banned, and a shaded country is one the list has something to
 * say about. None of that is guessable, so it is written down here rather than
 * learned by accident. */
function Legend({
  isAdmin,
  heat,
  countries,
  listed,
  onCountries,
}: {
  isAdmin: boolean;
  heat: boolean;
  countries: boolean;
  listed: number;
  onCountries: (on: boolean) => void;
}) {
  const [open, setOpen] = useState(() => localStorage.getItem("map.legend") === "on");

  function toggle() {
    const next = !open;
    setOpen(next);
    localStorage.setItem("map.legend", next ? "on" : "off");
  }

  return (
    <div className={open ? "legend open" : "legend"}>
      <button className="legend-tab" onClick={toggle} aria-expanded={open}>
        {open ? "Hide key" : "Key"}
      </button>
      {open && (
        <div className="legend-body">
          <h3>Places</h3>
          <p className="legend-row">
            <span className="dot" style={{ background: "var(--map-point)" }} />
            Somewhere watched from. Bigger means more plays.
          </p>
          <p className="legend-row">
            <span className="dot" style={{ background: "var(--vpn)" }} />
            A VPN or hosting address, so the pin is the server, not the viewer.
          </p>
          <p className="legend-row">
            <span className="ring" style={{ borderColor: "var(--banned)" }} />
            A banned device: a ring where it played, a solid dot where it tried since.
          </p>
          <p className="legend-row">
            <span className="dot live" style={{ background: "var(--live)" }} />
            Playing right now.
          </p>
          <p className="legend-row">
            <span className="ring" style={{ borderColor: "var(--map-accuracy)" }} />
            How vague the location is. A city centroid, never an address.
          </p>
          {heat && (
            <p className="legend-row">
              <span className="ramp" />
              Busier places run from blue through pink to yellow.
            </p>
          )}

          {isAdmin && (
            <>
              <h3>Countries</h3>
              <p className="legend-row">
                <span className="swatch" style={{ background: "var(--accent)" }} />
                Flagged: streams from there are recorded.
              </p>
              <p className="legend-row">
                <span className="swatch" style={{ background: "var(--warn)" }} />
                Warned: the viewer is messaged.
              </p>
              <p className="legend-row">
                <span className="swatch" style={{ background: "var(--banned)" }} />
                Stopped: the stream is ended.
              </p>
              <p className="muted small">
                Click any country to set or change it{listed > 0 ? `. ${listed} on the list.` : "."}
              </p>
              <label className="check">
                <input type="checkbox" checked={countries} onChange={(e) => onCountries(e.target.checked)} />
                Shade and click countries
              </label>
            </>
          )}
        </div>
      )}
    </div>
  );
}
