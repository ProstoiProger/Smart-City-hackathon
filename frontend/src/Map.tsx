import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet.markercluster";
import "leaflet/dist/leaflet.css";
import "leaflet.markercluster/dist/MarkerCluster.css";
import "leaflet.markercluster/dist/MarkerCluster.Default.css";
import type { Poi, Route, TourDetail } from "./api";
import sprite from "./assets/icons.svg";

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
  routeStart,
  finish,
  focusPoint,
  originFocus = 0,
  people,
  stops,
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
  /** Where the drawn route begins (the start, or the walker's place after a re-plan). */
  routeStart?: [number, number] | null;
  finish?: { point: [number, number]; label: string };
  /** Where the "my point" button takes the map: the start, or the walker's place on a walk. */
  focusPoint?: [number, number] | null;
  /** Changes when the user picks a new start: the map flies to `origin`. */
  originFocus?: number;
  /** The stops of the route on screen, drawn as numbered pins in their order. */
  stops?: Poi[];
  /** A company meeting: where each person starts. */
  people?: { name: string; latitude: number; longitude: number }[];
  picking: boolean;
  onSelect: (p: Poi) => void;
  onOrigin: (p: [number, number]) => void;
  onTileError: () => void;
  labels: { aria: string; start: string; startName: string; finish?: string; recenter?: string };
  theme: string;
  tour?: { detail: TourDetail; current: number } | null;
  onTourStop?: (index: number) => void;
}) {
  const el = useRef<HTMLDivElement>(null),
    map = useRef<L.Map | null>(null),
    markers = useRef<L.MarkerClusterGroup | null>(null),
    paths = useRef<L.LayerGroup | null>(null),
    tourLayer = useRef<L.LayerGroup | null>(null),
    start = useRef<L.Marker | null>(null),
    end = useRef<L.Marker | null>(null),
    crowd = useRef<L.LayerGroup | null>(null),
    stopLayer = useRef<L.LayerGroup | null>(null);
  const focus = useRef(focusPoint ?? null);
  focus.current = focusPoint ?? null;
  const recenter = useRef<HTMLButtonElement | null>(null);
  const goTo = useRef<(point: [number, number]) => void>(() => {});
  const handlers = useRef({ picking, onOrigin, onSelect, onTileError, onTourStop });
  handlers.current = { picking, onOrigin, onSelect, onTileError, onTourStop };
  useEffect(() => {
    const m = L.map(el.current!, { zoomControl: false }).setView(
      [51.1283, 71.4305],
      13,
    );
    map.current = m;
    L.control.zoom({ position: "bottomright" }).addTo(m);
    goTo.current = (point) => {
      m.invalidateSize();
      const zoom = Math.max(m.getZoom(), 16);
      const size = m.getSize();
      // A hidden map (mobile tab not shown yet) has no size: flyTo would compute NaN.
      if (!size.x || !size.y) {
        m.setView(point, zoom);
        return;
      }
      // A sheet over the bottom of the map hides its centre: centre the point in
      // the part of the map that stays visible above the sheet.
      const box = el.current!.getBoundingClientRect();
      const sheet = el.current!.parentElement?.querySelector(".detail-sheet")?.getBoundingClientRect();
      const visible = sheet && sheet.top > box.top + 80 ? sheet.top - box.top : box.height;
      const shift = (box.height - visible) / 2;
      const target = m.unproject(m.project(point, zoom).add([0, shift]), zoom);
      const still = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
      if (still) m.setView(target, zoom);
      else m.flyTo(target, zoom, { duration: 0.6 });
    };
    // "My point": one tap brings the start (or the walker's place) back into view.
    // Bottom corners stack upwards, so this sits above the zoom buttons.
    const Recenter = L.Control.extend({
      onAdd() {
        const bar = L.DomUtil.create("div", "leaflet-bar map-recenter");
        const button = L.DomUtil.create("button", "", bar) as HTMLButtonElement;
        button.type = "button";
        button.innerHTML = `<svg class="ic" aria-hidden="true" focusable="false"><use href="${sprite}#i-locate"/></svg>`;
        L.DomEvent.disableClickPropagation(bar);
        L.DomEvent.on(button, "click", () => focus.current && goTo.current(focus.current));
        recenter.current = button;
        return bar;
      },
    });
    new Recenter({ position: "bottomright" }).addTo(m);
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
    crowd.current = L.layerGroup().addTo(m);
    stopLayer.current = L.layerGroup().addTo(m);
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
  // Route stops: numbered pins, never clustered, redrawn whenever the route changes
  // (a closed place replaced, plan B taken, an edit in the chat).
  useEffect(() => {
    const layer = stopLayer.current;
    layer?.clearLayers();
    if (!layer || !stops?.length) return;
    stops.forEach((p, i) => {
      const color = colors[p.category] || "#536656";
      const label = document.createElement("span");
      label.textContent = `${i + 1}. ${p.display_name}`;
      L.marker([p.latitude, p.longitude], {
        icon: L.divIcon({
          className: "poi-pin-wrap",
          html: `<span class="stop-pin" style="background:${color}">${i + 1}</span>`,
          iconSize: [30, 30],
          iconAnchor: [15, 15],
        }),
        title: label.textContent,
        keyboard: false,
        zIndexOffset: 700,
      })
        .bindTooltip(label)
        .addTo(layer);
    });
  }, [stops]);
  // Meeting: a small named pin where each person starts.
  useEffect(() => {
    const layer = crowd.current;
    layer?.clearLayers();
    if (!layer || !people?.length) return;
    for (const p of people) {
      const label = document.createElement("span");
      label.textContent = p.name;
      L.marker([p.latitude, p.longitude], {
        icon: L.divIcon({
          className: "person-wrap",
          html: `<span class="person-pin">${label.innerHTML}</span>`,
          iconSize: [0, 0],
          iconAnchor: [0, 0],
        }),
        title: p.name,
        keyboard: false,
        zIndexOffset: 800,
      }).addTo(layer);
    }
  }, [people]);
  // A start chosen by the user (landmark, map point, geolocation): fly there smoothly.
  useEffect(() => {
    if (originFocus && origin) goTo.current(origin);
    // Only a new pick moves the map; origin changes from chat answers are fitted with the results.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [originFocus]);
  useEffect(() => {
    const button = recenter.current;
    if (!button) return;
    button.title = labels.recenter ?? "";
    button.setAttribute("aria-label", labels.recenter ?? "");
    button.disabled = !focusPoint;
  }, [labels.recenter, focusPoint]);
  useEffect(() => {
    end.current?.remove();
    end.current = null;
    if (!finish || !map.current) return;
    // The finish of a walk: a dark pin with a flag and its name, unlike the orange start.
    const name = document.createElement("span");
    name.textContent = finish.label;
    end.current = L.marker(finish.point, {
      icon: L.divIcon({
        className: "start-wrap finish-wrap",
        html:
          `<span class="start-pin finish-pin"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 22V4a1 1 0 0 1 1-1h11l-2 4 2 4H5"/></svg></span>` +
          `<span class="start-chip finish-chip"><b>${labels.finish ?? ""}</b>${name.innerHTML}</span>`,
        iconSize: [40, 50],
        iconAnchor: [20, 48],
      }),
      title: `${labels.finish ?? ""}: ${finish.label}`,
      zIndexOffset: 900,
      keyboard: false,
    }).addTo(map.current);
  }, [finish?.point[0], finish?.point[1], finish?.label, labels.finish]);
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
    const from = routeStart === undefined ? origin : routeStart;
    if (from && routes[0]?.geometry[0])
      L.polyline([from, routes[0].geometry[0]], {
        color: css.getPropertyValue("--text-2").trim(),
        weight: 2,
        dashArray: "4 6",
      }).addTo(layer);
    if (bounds.isValid())
      map.current.fitBounds(bounds, { padding: [35, 35], maxZoom: 16 });
  }, [routes, origin, routeStart, theme]);
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
