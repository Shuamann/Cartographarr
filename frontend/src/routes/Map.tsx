import { useEffect, useMemo, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import { useApi, type MapPoint, type MapPoints } from "../lib/api";
import FilterBar from "../components/FilterBar";
import { EMPTY, toQuery, type FilterState } from "../lib/filters";
import { buildMapStyle } from "../theme/mapStyle";

type Summary = { plays: number; users: number; devices: number; ips: number; seconds: number };

export default function MapRoute({ geoipReady }: { geoipReady: boolean }) {
  const [filters, setFilters] = useState<FilterState>(EMPTY);
  const query = useMemo(() => toQuery(filters), [filters]);

  const points = useApi<MapPoints>(`/map/points${query}`);
  const summary = useApi<Summary>(`/stats/summary${query}`);
  const [selected, setSelected] = useState<MapPoint["properties"] | null>(null);

  const container = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const [ready, setReady] = useState(false);
  const [mapError, setMapError] = useState<string | null>(null);

  // ---- create once -------------------------------------------------------
  useEffect(() => {
    if (!container.current || map.current) return;
    const m = new maplibregl.Map({
      container: container.current,
      style: buildMapStyle(),
      center: [-98, 39],
      zoom: 3,
      attributionControl: { compact: true },
    });
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
    // 0x0 and never fetches a tile, because MapLibre measures once. Watching
    // the container covers that, window resizes, and panel collapses alike.
    const observer = new ResizeObserver(() => m.resize());
    observer.observe(container.current);

    return () => {
      observer.disconnect();
      m.remove();
      map.current = null;
    };
  }, []);

  // ---- restyle on theme change ------------------------------------------
  useEffect(() => {
    const root = document.documentElement;
    const observer = new MutationObserver(() => {
      if (!map.current) return;
      // setStyle wipes our layers, so rebuild them once the new style settles.
      setReady(false);
      map.current.setStyle(buildMapStyle());
      map.current.once("styledata", () => setReady(true));
    });
    observer.observe(root, { attributes: true, attributeFilter: ["data-theme"] });
    return () => observer.disconnect();
  }, []);

  // ---- data layers -------------------------------------------------------
  useEffect(() => {
    const m = map.current;
    if (!m || !ready || !points.data) return;

    const existing = m.getSource("plays") as maplibregl.GeoJSONSource | undefined;
    if (existing) {
      existing.setData(points.data);
      return;
    }

    m.addSource("plays", {
      type: "geojson",
      data: points.data,
      cluster: true,
      clusterRadius: 45,
      clusterMaxZoom: 12,
      // Cluster totals must sum plays, not count pins — one busy city
      // outweighs a dozen one-off locations and the circle should say so.
      // `hosting` counts how many of the grouped locations are VPN/hosting,
      // so the cluster can be coloured honestly (see below).
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
        // Red only when every location in the cluster is a hosting/VPN origin.
        // One flagged IP among fifty ordinary ones shouldn't turn the whole
        // circle red, and an all-VPN cluster shouldn't look ordinary.
        "circle-color": [
          "case",
          ["==", ["get", "hosting"], ["get", "point_count"]],
          danger(),
          accent(),
        ],
        "circle-opacity": 0.85,
        "circle-stroke-width": 2,
        "circle-stroke-color": surface(),
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
      paint: { "text-color": accentInk() },
    });

    m.addLayer({
      id: "points",
      type: "circle",
      source: "plays",
      filter: ["!", ["has", "point_count"]],
      paint: {
        // Hosting/VPN origins get the warning colour: they're the ones worth
        // a second look.
        "circle-color": ["case", ["get", "is_hosting"], danger(), accent()],
        "circle-opacity": 0.9,
        "circle-stroke-width": 2,
        "circle-stroke-color": surface(),
        "circle-radius": ["interpolate", ["linear"], ["get", "plays"], 1, 6, 100, 12, 2000, 20],
      },
    });

    m.on("click", "clusters", (e) => {
      const feature = e.features?.[0];
      if (!feature) return;
      const source = m.getSource("plays") as maplibregl.GeoJSONSource;
      source.getClusterExpansionZoom(feature.properties!.cluster_id).then((zoom) => {
        m.easeTo({ center: (feature.geometry as GeoJSON.Point).coordinates as [number, number], zoom });
      });
    });

    m.on("click", "points", (e) => {
      const feature = e.features?.[0];
      if (feature) setSelected(feature.properties as unknown as MapPoint["properties"]);
    });

    for (const layer of ["clusters", "points"]) {
      m.on("mouseenter", layer, () => (m.getCanvas().style.cursor = "pointer"));
      m.on("mouseleave", layer, () => (m.getCanvas().style.cursor = ""));
    }
  }, [ready, points.data]);

  // A pin that no longer matches the filters shouldn't keep its drawer open.
  useEffect(() => setSelected(null), [query]);

  return (
    <div className="map-page">
      <FilterBar value={filters} onChange={setFilters} />

      <div className="map-wrap">
        <div ref={container} className="map" />

        {summary.data && (
          <div className="summary">
            <Tile label="Plays" value={summary.data.plays} />
            <Tile label="Users" value={summary.data.users} />
            <Tile label="Devices" value={summary.data.devices} />
            <Tile label="Locations" value={points.data?.features.length ?? 0} />
            <Tile label="Hours" value={Math.round(summary.data.seconds / 3600)} />
          </div>
        )}

        {!geoipReady && (
          <div className="map-banner">
            No location database installed, so there are no pins yet. Add a MaxMind key in Settings.
          </div>
        )}
        {geoipReady && points.data?.features.length === 0 && !points.loading && (
          <div className="map-banner">Nothing to show yet — the first sync may still be running.</div>
      )}
        {points.error && <div className="map-banner bad">{points.error}</div>}
        {mapError && <div className="map-banner bad">{mapError}</div>}

        {selected && <Drawer place={selected} onClose={() => setSelected(null)} />}
      </div>
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

function Drawer({
  place,
  onClose,
}: {
  place: MapPoint["properties"];
  onClose: () => void;
}) {
  const where = [place.city, place.region, place.country].filter(Boolean).join(", ");
  return (
    <aside className="drawer">
      <header>
        <div>
          <h2>{where || "Unknown location"}</h2>
          {place.asn_org && <p className="muted">{place.asn_org}</p>}
        </div>
        <button className="tab" onClick={onClose} aria-label="Close">
          ✕
        </button>
      </header>

      {place.is_hosting && (
        <p className="note warn-note">
          This traffic comes from a hosting or VPN provider, so the location is where the server
          is — not where the viewer is.
        </p>
      )}

      <dl className="stats">
        <Stat label="Plays" value={place.plays} />
        <Stat label="Users" value={place.users} />
        <Stat label="Devices" value={place.devices} />
        <Stat label="IPs" value={place.ips} />
      </dl>

      {place.last_play && (
        <p className="muted">
          Last play {new Date(place.last_play * 1000).toLocaleString()}
        </p>
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

/* Pin colours come from the same tokens as the basemap. */
const css = (name: string, fallback: string) =>
  getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
const accent = () => css("--accent", "#0e7490");
const accentInk = () => css("--accent-ink", "#ffffff");
const surface = () => css("--surface", "#ffffff");
const danger = () => css("--danger", "#b91c1c");
