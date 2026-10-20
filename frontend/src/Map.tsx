import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet.markercluster";
import "leaflet/dist/leaflet.css";
import "leaflet.markercluster/dist/MarkerCluster.css";
import "leaflet.markercluster/dist/MarkerCluster.Default.css";
import type { Poi, Route } from "./api";

export const colors: Record<string, string> = {
  food_drink: "#b26032",
  nature: "#387752",
  culture: "#745d91",
  sightseeing: "#246878",
  children: "#b97522",
  entertainment: "#98596a",
};
export default function CityMap({
  items,
  selected,
  origin,
  routes,
  picking,
  onSelect,
  onOrigin,
  onTileError,
  labels,
  theme,
}: {
  items: Poi[];
  selected?: Poi;
  origin: [number, number] | null;
  routes: Route[];
  picking: boolean;
  onSelect: (p: Poi) => void;
  onOrigin: (p: [number, number]) => void;
  onTileError: () => void;
  labels: { aria: string; start: string; startPin: string };
  theme: string;
}) {
  const el = useRef<HTMLDivElement>(null),
    map = useRef<L.Map | null>(null),
    markers = useRef<L.MarkerClusterGroup | null>(null),
    paths = useRef<L.LayerGroup | null>(null),
    start = useRef<L.Marker | null>(null);
  const handlers = useRef({ picking, onOrigin, onSelect, onTileError });
  handlers.current = { picking, onOrigin, onSelect, onTileError };
  useEffect(() => {
    const m = L.map(el.current!, { zoomControl: false }).setView(
      [51.1283, 71.4305],
      13,
    );
    map.current = m;
    L.control.zoom({ position: "bottomright" }).addTo(m);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
      maxZoom: 19,
    })
      .on("tileerror", () => handlers.current.onTileError())
      .addTo(m);
    markers.current = L.markerClusterGroup({
      showCoverageOnHover: false,
      maxClusterRadius: 45,
    }).addTo(m);
    paths.current = L.layerGroup().addTo(m);
    m.on("click", (e: L.LeafletMouseEvent) => {
      if (handlers.current.picking)
        handlers.current.onOrigin([e.latlng.lat, e.latlng.lng]);
    });
    const ro = new ResizeObserver(() => m.invalidateSize());
    ro.observe(el.current!);
    return () => {
      ro.disconnect();
      m.remove();
    };
  }, []);
  // Toggle the class on the element itself: a React className would overwrite the
  // classes Leaflet adds (leaflet-container clips the tiles; without it the page scrolls).
  useEffect(() => {
    el.current?.classList.toggle("picking", picking);
  }, [picking]);
  useEffect(() => {
    const group = markers.current;
    if (!group) return;
    group.clearLayers();
    for (const p of items) {
      const color = colors[p.category] || "#536656";
      const icon = L.divIcon({
        className: "poi-pin-wrap",
        html: `<span class="poi-pin" style="background:${color}"></span>`,
        iconSize: [24, 24],
        iconAnchor: [12, 12],
      });
      const label = document.createElement("span");
      label.textContent = p.display_name;
      L.marker([p.latitude, p.longitude], {
        icon,
        keyboard: true,
        title: p.display_name,
      })
        .bindTooltip(label)
        .on("click", () => handlers.current.onSelect(p))
        .addTo(group);
    }
    // Show the start and what was found: results may lie far from the current view.
    const m = map.current;
    if (m && items.length) {
      const bounds = L.latLngBounds(items.map((p) => [p.latitude, p.longitude] as L.LatLngTuple));
      if (origin) bounds.extend(origin);
      m.invalidateSize();
      const size = m.getSize();
      if (size.x > 0 && size.y > 0) m.fitBounds(bounds, { padding: [40, 40], maxZoom: 15 });
    }
    // Refit only when a new result set arrives, not when the start pin moves.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [items]);
  useEffect(() => {
    const m = map.current;
    if (!selected || !m) return;
    // On mobile the map panel becomes visible in the same render; Leaflet still has a
    // 0x0 size cached, and flyTo would compute NaN coordinates.
    m.invalidateSize();
    const target: L.LatLngExpression = [selected.latitude, selected.longitude];
    const size = m.getSize();
    if (size.x > 0 && size.y > 0) m.flyTo(target, 15, { duration: 0.5 });
    else m.setView(target, 15);
  }, [selected]);
  useEffect(() => {
    if (start.current) {
      start.current.remove();
      start.current = null;
    }
    if (origin && map.current)
      start.current = L.marker(origin, {
        icon: L.divIcon({
          className: "start-wrap",
          html: `<span class="start-pin">${labels.startPin}</span>`,
          iconSize: [28, 28],
          iconAnchor: [14, 14],
        }),
        title: labels.start,
      }).addTo(map.current);
  }, [origin, labels.start, labels.startPin]);
  useEffect(() => {
    const layer = paths.current;
    layer?.clearLayers();
    if (!layer || !map.current) return;
    const bounds = L.latLngBounds([]);
    // Route colors follow the active theme tokens.
    const css = getComputedStyle(document.documentElement);
    const routeColors = [css.getPropertyValue("--route-1").trim(), css.getPropertyValue("--route-2").trim()];
    routes.forEach((r, i) => {
      if (r.geometry.length > 1)
        L.polyline(r.geometry, {
          color: routeColors[i % 2],
          weight: 5,
          opacity: 0.85,
        }).addTo(layer);
      r.geometry.forEach((p) => bounds.extend(p));
    });
    if (origin && routes[0]?.geometry[0])
      L.polyline([origin, routes[0].geometry[0]], {
        color: css.getPropertyValue("--text-2").trim(),
        weight: 2,
        dashArray: "4 6",
      }).addTo(layer);
    if (bounds.isValid())
      map.current.fitBounds(bounds, { padding: [35, 35], maxZoom: 16 });
  }, [routes, origin, theme]);
  return (
    <div
      ref={el}
      className="map-canvas"
      role="region"
      aria-label={labels.aria}
    />
  );
}
