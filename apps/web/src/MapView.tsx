import { useEffect, useRef, useState } from "react";
import type { Map as MapLibreMap, Marker } from "maplibre-gl";
import { useNavigate } from "react-router";

export type MapPoint = {
  id: string;
  lat: number;
  lon: number;
  label: string;
  href?: string;
};

export type Bounds = {
  min_lat: number;
  min_lon: number;
  max_lat: number;
  max_lon: number;
};

// shortcut: OpenStreetMap's public tiles allow light use only; use a tile provider before real traffic.
const TILES = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
// India, when there is nothing to show yet.
const DEFAULT_CENTER: [number, number] = [78.9629, 20.5937];

/**
 * A MapLibre map with OpenStreetMap tiles. Loaded on demand, so pages without a map stay light.
 * Where WebGL is missing (old browsers, tests) it says so; every map is paired with text.
 */
export function MapView({
  points,
  label,
  zoom = 12,
  onPick,
  onSearchArea,
}: {
  points: MapPoint[];
  label: string;
  /** Zoom for a single point; several points are fitted instead. */
  zoom?: number;
  /** Called with the clicked spot. */
  onPick?: (lat: number, lon: number) => void;
  /** Shows a "Search this area" button that reports the visible area. */
  onSearchArea?: (bounds: Bounds) => void;
}) {
  const container = useRef<HTMLDivElement>(null);
  const [map, setMap] = useState<MapLibreMap | null>(null);
  const [failed, setFailed] = useState(false);
  const [library, setLibrary] = useState<typeof import("maplibre-gl") | null>(
    null,
  );
  const navigate = useNavigate();
  // Latest callbacks, so the map is created once.
  const pick = useRef(onPick);
  useEffect(() => {
    pick.current = onPick;
  }, [onPick]);

  useEffect(() => {
    let created: MapLibreMap | null = null;
    let cancelled = false;
    Promise.all([
      import("maplibre-gl"),
      // Vite neither pre-bundles nor emits MapLibre's worker by itself; ship it as an asset.
      import("maplibre-gl/dist/maplibre-gl-worker.mjs?url"),
      import("maplibre-gl/dist/maplibre-gl.css"),
    ])
      .then(([lib, worker]) => {
        if (cancelled || !container.current) return;
        lib.setWorkerUrl(worker.default);
        created = new lib.Map({
          container: container.current,
          style: {
            version: 8,
            sources: {
              osm: {
                type: "raster",
                tiles: [TILES],
                tileSize: 256,
                maxzoom: 19,
                attribution: "© OpenStreetMap contributors",
              },
            },
            layers: [{ id: "osm", type: "raster", source: "osm" }],
          },
          center: DEFAULT_CENTER,
          zoom: 4,
        });
        created.addControl(new lib.NavigationControl({ showCompass: false }));
        created.on("click", (event) =>
          pick.current?.(event.lngLat.lat, event.lngLat.lng),
        );
        setLibrary(lib);
        setMap(created);
      })
      .catch(() => !cancelled && setFailed(true));
    return () => {
      cancelled = true;
      created?.remove();
    };
  }, []);

  useEffect(() => {
    if (!map || !library) return;
    const markers: Marker[] = points.map((point) => {
      const marker = new library.Marker()
        .setLngLat([point.lon, point.lat])
        .addTo(map);
      const element = marker.getElement();
      element.title = point.label;
      element.setAttribute("aria-label", point.label);
      if (point.href) {
        const href = point.href;
        element.style.cursor = "pointer";
        element.addEventListener("click", (event) => {
          event.stopPropagation();
          void navigate(href);
        });
      }
      return marker;
    });
    const [first] = points;
    if (points.length === 1 && first) {
      map.jumpTo({ center: [first.lon, first.lat], zoom });
    } else if (points.length > 1) {
      const bounds = new library.LngLatBounds();
      for (const point of points) bounds.extend([point.lon, point.lat]);
      map.fitBounds(bounds, { padding: 40, maxZoom: 14, duration: 0 });
    }
    return () => markers.forEach((marker) => marker.remove());
  }, [map, library, points, zoom, navigate]);

  function searchArea() {
    if (!map || !onSearchArea) return;
    const bounds = map.getBounds();
    // A zoomed-out view can wrap past the edges the API accepts.
    const clamp = (value: number, limit: number) =>
      Math.min(limit, Math.max(-limit, value));
    onSearchArea({
      min_lat: clamp(bounds.getSouth(), 90),
      min_lon: clamp(bounds.getWest(), 180),
      max_lat: clamp(bounds.getNorth(), 90),
      max_lon: clamp(bounds.getEast(), 180),
    });
  }

  if (failed) return <p>The map cannot be shown in this browser.</p>;
  return (
    <div className="map-block">
      <div ref={container} className="map" role="region" aria-label={label} />
      {onSearchArea && (
        <button type="button" onClick={searchArea} disabled={!map}>
          Search this area
        </button>
      )}
    </div>
  );
}
