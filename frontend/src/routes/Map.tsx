import { useEffect, useMemo, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import { useApi, type MapPoint, type MapPoints } from "../lib/api";
import FilterBar from "../components/FilterBar";
import { EMPTY, toQuery, type FilterState } from "../lib/filters";
import { buildMapStyle } from "../theme/mapStyle";
import MediaPanel from "../components/MediaPanel";
import type { HistoryPage } from "../lib/api";

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

export default function MapRoute({ geoipReady }: { geoipReady: boolean }) {
  const [filters, setFilters] = useState<FilterState>(EMPTY);
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

        {selected && (
          <Drawer
            place={selected}
            onClose={() => setSelected(null)}
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

function MapCanvas({
  features,
  onSelect,
  showHistory,
  showAccuracy,
}: {
  features: MapPoint[];
  onSelect: (place: Place) => void;
  showHistory: boolean;
  showAccuracy: boolean;
}) {
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const [ready, setReady] = useState(false);
  const [mapError, setMapError] = useState<string | null>(null);

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
                  properties: {},
                  geometry: groundCircle(
                    f.geometry.coordinates[0],
                    f.geometry.coordinates[1],
                    f.properties.accuracy_km as number,
                  ),
                }))
            : [],
      });
    }

    const existing = m.getSource("plays") as maplibregl.GeoJSONSource | undefined;
    if (existing) {
      existing.setData(data);
      return;
    }

    m.addSource("accuracy", { type: "geojson", data: emptyCollection() });
    m.addLayer({
      id: "accuracy-fill",
      type: "fill",
      source: "accuracy",
      paint: {
        // Opaque on purpose. Translucent circles stack where they overlap and
        // the darker patches read as "more certain", which is backwards. A
        // flat tone makes overlapping areas merge into one shape instead.
        "fill-color": css("--map-accuracy", "#16212c"),
        "fill-opacity": 1,
        "fill-outline-color": css("--map-accuracy-edge", "#22303e"),
      },
    });

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
  }, [ready, features, onSelect, showHistory, showAccuracy]);

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
}: {
  place: Place;
  onClose: () => void;
  onFilterToTitle?: (ratingKey: number, title: string) => void;
}) {
  const [openMedia, setOpenMedia] = useState<number | null>(null);

  // Matched on city, because the map aggregates by coordinate and history has
  // no coordinate of its own. Two networks in one city therefore share a list,
  // which the heading says out loud rather than pretending otherwise.
  const recent = useApi<HistoryPage>(
    place.city ? `/history?city=${encodeURIComponent(place.city)}&size=8` : null,
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
          <h3>Recently watched in {place.city}</h3>
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
    </aside>
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
