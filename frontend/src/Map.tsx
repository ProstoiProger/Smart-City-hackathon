import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet.markercluster";
import "leaflet/dist/leaflet.css";
import "leaflet.markercluster/dist/MarkerCluster.css";
import "leaflet.markercluster/dist/MarkerCluster.Default.css";
import type { Poi, Route, TourDetail } from "./api";

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
  tour,
  onTourStop,
}: {
  items: Poi[];
  selected?: Poi;
  origin: [number, number] | null;
  routes: Route[];
  picking: boolean;
  onSelect: (p: Poi) => void;
  onOrigin: (p: [number, number]) => void;
  onTileError: () => void;
  labels: { aria: string; start: string; startName: string };
  theme: string;
  tour?: { detail: TourDetail; current: number } | null;
  onTourStop?: (index: number) => void;
}) {
  const el = useRef<HTMLDivElement>(null),
    map = useRef<L.Map | null>(null),
    markers = useRef<L.MarkerClusterGroup | null>(null),
    paths = useRef<L.LayerGroup | null>(null),
    tourLayer = useRef<L.LayerGroup | null>(null),
    start = useRef<L.Marker | null>(null);
  const handlers = useRef({ picking, onOrigin, onSelect, onTileError, onTourStop });
  handlers.current = { picking, onOrigin, onSelect, onTileError, onTourStop };
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
    tourLayer.current = L.layerGroup().addTo(m);
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
    if (origin && map.current) {
      // A large teardrop pin with a pulse and a name chip: the start must stand out
      // from clusters and category dots, whether it is a landmark or a picked point.
      const name = document.createElement("span");
      name.textContent = labels.startName;
      start.current = L.marker(origin, {
        icon: L.divIcon({
          className: "start-wrap",
          html:
            `<span class="start-pulse"></span>` +
            `<span class="start-pin"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 22V4a1 1 0 0 1 1-1h11l-2 4 2 4H5"/></svg></span>` +
            `<span class="start-chip"><b>${labels.start}</b>${name.innerHTML}</span>`,
          iconSize: [40, 50],
          iconAnchor: [20, 48],
        }),
        title: `${labels.start}: ${labels.startName}`,
        zIndexOffset: 1000,
        keyboard: false,
      }).addTo(map.current);
    }
  }, [origin, labels.start, labels.startName]);
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
  // A guided walk: numbered pins, the legs along the walking graph, the current stop highlighted.
  useEffect(() => {
    const layer = tourLayer.current;
    const m = map.current;
    layer?.clearLayers();
    if (!layer || !m || !tour) return;
    const css = getComputedStyle(document.documentElement);
    const line = css.getPropertyValue("--route-1").trim() || "#246878";
    const bounds = L.latLngBounds([]);
    tour.detail.legs.forEach((leg, i) => {
      if (leg.geometry.length > 1)
        L.polyline(leg.geometry, {
          color: line,
          weight: 5,
          opacity: i < tour.current ? 0.35 : 0.9,
          dashArray: leg.network ? undefined : "6 8",
        }).addTo(layer);
      leg.geometry.forEach((pt) => bounds.extend(pt));
    });
    tour.detail.stops.forEach((s, i) => {
      const state = i === tour.current ? "current" : i < tour.current ? "done" : "next";
      L.marker([s.latitude, s.longitude], {
        icon: L.divIcon({
          className: "tour-pin-wrap",
          html: `<span class="tour-pin ${state}">${i + 1}</span>`,
          iconSize: [30, 30],
          iconAnchor: [15, 15],
        }),
        title: s.name,
        zIndexOffset: i === tour.current ? 900 : 500,
      })
        .bindTooltip(s.name)
        .on("click", () => handlers.current.onTourStop?.(i))
        .addTo(layer);
      bounds.extend([s.latitude, s.longitude]);
    });
    m.invalidateSize();
    const size = m.getSize();
    if (size.x <= 0 || size.y <= 0) return;
    // The tour card docks over the lower part of the map: keep the route in the free upper part.
    const below = Math.round(size.y * 0.58);
    const here = tour.detail.stops[tour.current];
    const target = tour.current > 0 && here ? L.latLngBounds([[here.latitude, here.longitude]]) : bounds;
    if (target.isValid())
      m.flyToBounds(target, { paddingTopLeft: [40, 40], paddingBottomRight: [40, below], maxZoom: 16, duration: 0.5 });
  }, [tour, theme]);
  return (
    <div
      ref={el}
      className="map-canvas"
      role="region"
      aria-label={labels.aria}
    />
  );
}
