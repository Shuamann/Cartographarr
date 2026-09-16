import { useEffect, useMemo, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import {
  api,
  useApi,
  type Activity,
  type LiveSession,
  type MapPoint,
  type MapPoints,
} from "../lib/api";
import { when } from "../components/DataTable";
import FilterBar from "../components/FilterBar";
import { toQuery } from "../lib/filters";
import { useUrlFilters } from "../lib/useUrlFilters";
import { buildMapStyle } from "../theme/mapStyle";
import MediaPanel from "../components/MediaPanel";
import { useIsAvailable } from "../components/Gated";
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
  onBlockDevice,
}: {
  geoipReady: boolean;
  onOpenUser?: (userId: number) => void;
  onBlockDevice?: (machineId: string, label: string) => void;
}) {
  const [filters, setFilters] = useUrlFilters();
  const query = useMemo(() => toQuery(filters), [filters]);

  const points = useApi<MapPoints>(`/map/points${query}`);
  const summary = useApi<Summary>(`/stats/summary${query}`);
  const [selected, setSelected] = useState<Place | null>(null);

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
  const unplaceable = allLive.length - liveSessions.length;
  const [hovered, setHovered] = useState<Hover | null>(null);
  const [pinned, setPinned] = useState(false);

  function toggleLayer(name: string, value: boolean, set: (v: boolean) => void) {
    set(value);
    localStorage.setItem(`layer.${name}`, value ? "on" : "off");
  }

  // A place that no longer matches the filters shouldn't keep its panel open.
  useEffect(() => setSelected(null), [query]);

  const features = points.data?.features ?? [];

  return (
    <div className="map-page">
      <FilterBar value={filters} onChange={setFilters} />

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
            {unplaceable > 0 && (
              <span className="muted small" title="Local addresses have no public location">
                {unplaceable} on your network, not mappable
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
            showHeat={showHeat}
          />
        ) : (
          <LocationList features={features} selected={selected} onSelect={setSelected} />
        )}

        {!geoipReady && (
          <div className="map-banner">
            No location database installed, so there's nothing to place yet. Add a MaxMind key in
            Settings.
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
            onOpenUser={onOpenUser}
            onBlockDevice={onBlockDevice}
            onTerminated={live.reload}
          />
        )}

        {selected && (
          <Drawer
            place={selected}
            onClose={() => setSelected(null)}
            onOpenUser={onOpenUser}
            onFilterToTitle={(ratingKey, title) => {
              setFilters({ ...filters, rating_key: ratingKey, ratingKeyLabel: title });
              setSelected(null);
            }}
          />
        )}
      </div>
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
  showHeat,
}: {
  features: MapPoint[];
  onSelect: (place: Place) => void;
  showHistory: boolean;
  showAccuracy: boolean;
  liveSessions: LiveSession[];
  onHoverLive: (hover: Hover | null) => void;
  onPinLive: () => void;
  showHeat: boolean;
}) {
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
        center: [-98, 39],
        zoom: 3,
        attributionControl: { compact: true },
      });
    } catch (err) {
      setMapError(`The map couldn't start: ${(err as Error).message}`);
      return;
    }

    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    m.on("load", () => setReady(true));
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
          // Weighted by plays, then flattened with a square root. Raw counts
          // would let one city of 9,000 plays wash out everywhere else.
          "heatmap-weight": [
            "interpolate", ["linear"], ["sqrt", ["get", "plays"]],
            0, 0,
            100, 1,
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
        // Red only when every location inside is a hosting/VPN origin.
        "circle-color": [
          "case",
          ["==", ["get", "hosting"], ["get", "point_count"]],
          css("--danger", "#b91c1c"),
          css("--accent", "#0e7490"),
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
          css("--danger", "#b91c1c"),
          css("--accent", "#0e7490"),
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
      if (feature) onSelect(feature.properties as unknown as Place);
    });

    for (const layer of ["clusters", "points"]) {
      m.on("mouseenter", layer, () => (m.getCanvas().style.cursor = "pointer"));
      m.on("mouseleave", layer, () => (m.getCanvas().style.cursor = ""));
    }
  }, [ready, features, onSelect, showHistory, showAccuracy, showHeat]);

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
        // Deliberately left open: the flyout carries buttons, and closing the
        // instant the pointer leaves the pin would put them out of reach. The
        // flyout closes itself once the pointer leaves it.
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
  selected: Place | null;
  onSelect: (place: Place) => void;
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
            const isSelected =
              selected !== null && placeName(selected) === placeName(p) && selected.plays === p.plays;
            return (
              <tr
                key={key}
                className={isSelected ? "loc-row selected" : "loc-row"}
                onClick={() => onSelect(p)}
              >
                <td>
                  {placeName(p)}
                  {p.is_hosting && <span className="pill warn">VPN</span>}
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
  onClose,
  onFilterToTitle,
  onOpenUser,
}: {
  place: Place;
  onClose: () => void;
  onFilterToTitle?: (ratingKey: number, title: string) => void;
  onOpenUser?: (userId: number) => void;
}) {
  const [openMedia, setOpenMedia] = useState<number | null>(null);
  const [tab, setTab] = useState<"who" | "watched">("who");

  // Matched on city, because the map aggregates by coordinate while history
  // only stores an IP. Two networks in one city therefore share a result,
  // which the note below says out loud rather than implying the pin is exact.
  const detail = useApi<LocationDetail>(
    place.city ? `/location?city=${encodeURIComponent(place.city)}` : null,
  );
  const recent = useApi<HistoryPage>(
    place.city && tab === "watched"
      ? `/history?city=${encodeURIComponent(place.city)}&size=12`
      : null,
  );

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
        <p className="note warn-note">
          This traffic comes from a hosting or VPN provider, so the location is where the server
          is, not where the viewer is.
        </p>
      )}

      <dl className="stats">
        <Stat label="Plays" value={place.plays} />
        <Stat label="Users" value={place.users} />
        <Stat label="Devices" value={place.devices} />
        <Stat label="IPs" value={place.ips} />
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

      {place.city && (
        <>
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

              <h3>Users</h3>
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

              <h3>Devices</h3>
              <div className="mini-list">
                {detail.data?.devices.map((d) => (
                  <div key={d.machine_id} className="mini">
                    <div>
                      {d.player || "Unnamed"}
                      <p className="muted small">
                        {d.platform} · <code>{d.machine_id.slice(0, 14)}…</code>
                      </p>
                    </div>
                    <span className="muted">{d.plays.toLocaleString()}</span>
                  </div>
                ))}
              </div>

              <h3>Addresses</h3>
              <div className="mini-list">
                {detail.data?.addresses.map((a) => (
                  <div key={a.ip_address} className="mini">
                    <div>
                      <code>{a.ip_address}</code>
                      {a.is_hosting && <span className="pill warn">VPN</span>}
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
                        {row.full_title}
                        <span className="muted small block">
                          {row.player}
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
        </>
      )}
    </aside>
  );
}


/* Stream details, pinned next to its map pin.
 *
 * Positioned in React rather than a MapLibre popup so the actions are real
 * buttons wired to the same API calls the rest of the app uses.
 */
function LiveFlyout({
  session,
  x,
  y,
  pinned,
  onClose,
  onOpenUser,
  onBlockDevice,
  onTerminated,
}: {
  session: LiveSession;
  x: number;
  y: number;
  pinned: boolean;
  onClose: () => void;
  onOpenUser?: (userId: number) => void;
  onBlockDevice?: (machineId: string, label: string) => void;
  onTerminated?: () => void;
}) {
  const plexPass = useIsAvailable("plex_pass");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const who = session.friendly_name || session.username || "Unknown";
  const where = session.geo
    ? [session.geo.city, session.geo.region].filter(Boolean).join(", ")
    : session.ip_address;
  const progress = Math.min(Number(session.progress_percent ?? 0), 100);

  async function stop() {
    setBusy(true);
    setError(null);
    try {
      await api.post(`/activity/${session.session_key}/terminate`, {
        message: "This device is not permitted to stream. Contact the server owner.",
      });
      onTerminated?.();
      onClose();
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  return (
    <div
      className={pinned ? "flyout pinned" : "flyout"}
      style={{ left: x, top: y }}
      onMouseLeave={pinned ? undefined : onClose}
      role="dialog"
    >
      <div className="flyout-head">
        {session.rating_key && (
          <img
            className="stream-poster"
            src={`/api/media/${session.rating_key}/image?width=120&height=180`}
            alt=""
            onError={(e) => ((e.currentTarget as HTMLImageElement).style.display = "none")}
          />
        )}
        <div className="min0">
          <strong>{session.full_title}</strong>
          <p className="muted small">
            {session.user_id != null && onOpenUser ? (
              <button className="linkish" onClick={() => onOpenUser(session.user_id as number)}>
                {who}
              </button>
            ) : (
              who
            )}
          </p>
          <p className="muted small">
            {session.player} · {session.platform}
          </p>
          <p className="muted small">
            {where}
            {session.geo?.is_hosting && <span className="pill warn">VPN</span>}
          </p>
        </div>
        <button className="tab" onClick={onClose} aria-label="Close">
          ✕
        </button>
      </div>

      <p className="muted small">
        <span className="pill">{session.transcode_decision}</span>
        {session.video_full_resolution && <span className="pill">{session.video_full_resolution}</span>}
        {session.state && <span className="pill">{session.state}</span>}
        {Math.round(progress)}%
      </p>
      <div className="progress">
        <div className="progress-fill" style={{ width: `${progress}%` }} />
      </div>

      {error && <p className="note bad-note">{error}</p>}

      <div className="row wrap flyout-actions">
        <button className="btn danger" onClick={stop} disabled={busy || !plexPass.ok}>
          {busy ? "Stopping…" : "Stop stream"}
        </button>
        {onBlockDevice && session.machine_id && (
          <button
            className="btn"
            onClick={() =>
              onBlockDevice(session.machine_id as string, session.player || "this device")
            }
          >
            Ban device
          </button>
        )}
      </div>
      {!plexPass.ok && <p className="muted small">{plexPass.reason}</p>}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="stat">
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

/* Pin colours come from the same tokens as the basemap. */
const css = (name: string, fallback: string) =>
  getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;

function emptyCollection(): GeoJSON.FeatureCollection {
  return { type: "FeatureCollection", features: [] };
}

/* The first text layer in the style, so overlays can be slipped underneath it
 * rather than burying the place names. */
function firstSymbolLayer(map: maplibregl.Map): string | undefined {
  return map.getStyle().layers?.find((l) => l.type === "symbol")?.id;
}
