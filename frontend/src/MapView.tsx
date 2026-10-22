import { useEffect, useRef, useState } from "react";
import { LngLatBounds, Map as MlMap, Marker, setWorkerUrl, type GeoJSONSource } from "maplibre-gl";

type Padding = { top: number; bottom: number; left: number; right: number };
import "maplibre-gl/dist/maplibre-gl.css";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import { emojiFiles } from "./lib/Emo";
import { Icon } from "./lib/Icon";

setWorkerUrl(workerUrl);

export type LatLon = [number, number];
/** A place on the map: an emoji in a coloured disc, numbered when it is part of an answer or a route. */
export type MapPin = {
  id: string;
  lat: number;
  lon: number;
  emoji: string;
  color: string;
  label: string;
  number?: number;
  state?: "done" | "current";
};
export type MapLine = { geometry: LatLon[]; tone: "main" | "alt" | "back" | "muted" | "link" };

// OpenFreeMap: free vector tiles from OpenStreetMap, no key; the same tiles carry building heights.
const STYLES = {
  dark: "https://tiles.openfreemap.org/styles/dark",
  light: "https://tiles.openfreemap.org/styles/positron",
};
const ASTANA: LatLon = [51.1283, 71.4305];
const PITCH_3D = 58;

// Map colours follow the graphite theme: graphite ground, cyan water hint, dim parks.
const DARK_PAINT: [string, string, string][] = [
  ["background", "background-color", "#15171c"],
  ["water", "fill-color", "#0e2a33"],
  ["landuse_park", "fill-color", "#17241d"],
  ["landcover_wood", "fill-color", "#17241d"],
  ["landuse_residential", "fill-color", "#191c22"],
  ["building", "fill-color", "#22262e"],
];
const TONE = {
  dark: { main: "#00B8D9", alt: "#00B8D9", back: "#7DF9FF", muted: "#5b6577", link: "#9AA3B2", casing: "#0b0d10", building: "#2a2f39", radius: "#00B8D9" },
  light: { main: "#0087a3", alt: "#0087a3", back: "#38bdf8", muted: "#9aa3b2", link: "#5b6577", casing: "#ffffff", building: "#d6d9df", radius: "#0087a3" },
};

const toLngLat = ([lat, lon]: LatLon): [number, number] => [lon, lat];
const still = () => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

/** A circle polygon of `meters` around a point (equirectangular, fine at city scale). */
function circle([lat, lon]: LatLon, meters: number) {
  const coords: [number, number][] = [];
  const dLat = meters / 111320;
  const dLon = meters / (111320 * Math.cos((lat * Math.PI) / 180));
  for (let i = 0; i <= 64; i++) {
    const a = (i / 64) * Math.PI * 2;
    coords.push([lon + dLon * Math.cos(a), lat + dLat * Math.sin(a)]);
  }
  return { type: "Feature" as const, properties: {}, geometry: { type: "Polygon" as const, coordinates: [coords] } };
}

function lineFeatures(lines: MapLine[]) {
  return {
    type: "FeatureCollection" as const,
    features: lines
      .filter((l) => l.geometry.length > 1)
      .map((l) => ({
        type: "Feature" as const,
        properties: { tone: l.tone },
        geometry: { type: "LineString" as const, coordinates: l.geometry.map(toLngLat) },
      })),
  };
}

/** A Noto emoji as DOM for map markers: still image, animated one on hover (see .emo in ui.css). */
function emojiNode(e: string) {
  const files = emojiFiles(e);
  const box = document.createElement("span");
  box.className = "emo";
  box.setAttribute("aria-hidden", "true");
  if (!files) {
    box.classList.add("emo-text");
    box.textContent = e;
    return box;
  }
  const still = document.createElement("img");
  still.className = "emo-still";
  still.src = files.still;
  still.alt = "";
  box.append(still);
  if (files.anim) {
    const anim = document.createElement("img");
    anim.className = "emo-anim";
    anim.loading = "lazy";
    anim.alt = "";
    anim.addEventListener("load", () => box.classList.add("ready"));
    anim.src = files.anim;
    box.append(anim);
  }
  return box;
}

function pinElement(p: MapPin, onClick: () => void, onHover: (on: boolean) => void) {
  const el = document.createElement("button");
  el.type = "button";
  el.className = "map-pin" + (p.number ? " numbered" : "") + (p.state ? " " + p.state : "");
  el.style.setProperty("--pin", p.color);
  el.setAttribute("aria-label", p.label);
  el.title = p.label;
  const face = document.createElement("span");
  face.className = "map-pin-face";
  face.append(emojiNode(p.emoji));
  el.append(face);
  if (p.number) {
    const n = document.createElement("span");
    n.className = "map-pin-num";
    n.textContent = String(p.number);
    el.append(n);
  }
  el.addEventListener("click", (e) => {
    e.stopPropagation();
    onClick();
  });
  el.addEventListener("mouseenter", () => onHover(true));
  el.addEventListener("mouseleave", () => onHover(false));
  // MapLibre positions the marker element with its own transform: the pin's
  // animations and hover lift live on the inner button, never on the wrapper.
  const wrap = document.createElement("div");
  wrap.className = "map-pin-wrap";
  wrap.append(el);
  return { wrap, pin: el };
}

function flagElement(kind: "start" | "finish", title: string, name: string) {
  const el = document.createElement("div");
  el.className = "map-flag " + kind;
  el.setAttribute("role", "img");
  el.setAttribute("aria-label", `${title}: ${name}`);
  const pulse = document.createElement("span");
  pulse.className = "map-flag-pulse";
  const dot = document.createElement("span");
  dot.className = "map-flag-dot";
  if (kind === "finish") dot.append(emojiNode("🏁"));
  const chip = document.createElement("span");
  chip.className = "map-flag-chip";
  const b = document.createElement("b");
  b.textContent = title;
  chip.append(b, document.createTextNode(name));
  el.append(...(kind === "start" ? [pulse] : []), dot, chip);
  return el;
}

export function MapView({
  theme,
  pins,
  lines,
  start,
  finish,
  people,
  radiusM,
  activeId,
  fitKey,
  focus,
  picking,
  onPin,
  onHover,
  onPick,
  onTileError,
  padding,
  labels,
}: {
  theme: "light" | "dark";
  pins: MapPin[];
  lines: MapLine[];
  start: { point: LatLon; name: string } | null;
  finish: { point: LatLon; name: string } | null;
  people: { name: string; latitude: number; longitude: number }[];
  /** Reach of the walk around the start, drawn as a dashed circle; null hides it. */
  radiusM: number | null;
  /** The pin highlighted from the panel (hovered card or opened place). */
  activeId?: string;
  /** Changes when a new answer or route arrives: the map fits everything drawn. */
  fitKey: string;
  /** Changes when the user picks a point or place to look at: the map flies there. */
  focus: { point: LatLon; key: number; zoom?: number } | null;
  picking: boolean;
  onPin: (id: string) => void;
  onHover: (id: string | null) => void;
  onPick: (point: LatLon) => void;
  onTileError: () => void;
  /** Screen space covered by the floating panel, so fitted content stays visible. */
  padding: () => Padding;
  labels: { aria: string; start: string; finish: string; zoomIn: string; zoomOut: string; to3d: string; to2d: string; recenter: string };
}) {
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<MlMap | null>(null);
  // Set on "style.load", cleared when a theme switch swaps the base style.
  const styleReady = useRef(false);
  const [is3d, setIs3d] = useState(() => {
    try {
      return localStorage.getItem("map3d") !== "0";
    } catch {
      return true;
    }
  });
  const pinMarkers = useRef(new Map<string, { marker: Marker; el: HTMLElement }>());
  const flags = useRef<{ start?: Marker; finish?: Marker; people: Marker[] }>({ people: [] });
  // Latest drawn data: re-applied after a theme switch reloads the base style.
  const data = useRef({ lines, start, radiusM, is3d, theme });
  data.current = { lines, start, radiusM, is3d, theme };
  const handlers = useRef({ onPin, onHover, onPick, onTileError, picking, padding });
  handlers.current = { onPin, onHover, onPick, onTileError, picking, padding };

  const applyOverlays = () => {
    const m = map.current;
    if (!m || !styleReady.current) return;
    const d = data.current;
    const tone = TONE[d.theme];
    if (!m.getSource("walk-lines")) {
      if (d.theme === "dark")
        for (const [layer, prop, value] of DARK_PAINT) if (m.getLayer(layer)) (m.setPaintProperty as (l: string, p: string, v: unknown) => void).call(m, layer, prop, value);
      const firstSymbol = m.getStyle().layers.find((l) => l.type === "symbol")?.id;
      m.addLayer(
        {
          id: "building-3d",
          type: "fill-extrusion",
          source: "openmaptiles",
          "source-layer": "building",
          minzoom: 13,
          paint: {
            "fill-extrusion-color": tone.building,
            "fill-extrusion-height": ["coalesce", ["get", "render_height"], 8],
            "fill-extrusion-base": ["coalesce", ["get", "render_min_height"], 0],
            "fill-extrusion-opacity": 0.92,
            "fill-extrusion-vertical-gradient": true,
          },
        },
        firstSymbol,
      );
      m.addSource("walk-radius", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      m.addLayer({ id: "walk-radius-fill", type: "fill", source: "walk-radius", paint: { "fill-color": tone.radius, "fill-opacity": 0.07 } });
      m.addLayer({
        id: "walk-radius-line",
        type: "line",
        source: "walk-radius",
        paint: { "line-color": tone.radius, "line-width": 1.6, "line-dasharray": [3, 3], "line-opacity": 0.8 },
      });
      m.addSource("walk-lines", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      m.addLayer({
        id: "walk-lines-casing",
        type: "line",
        source: "walk-lines",
        filter: ["in", ["get", "tone"], ["literal", ["main", "alt", "back"]]],
        layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": tone.casing, "line-width": 9, "line-opacity": 0.85 },
      });
      m.addLayer({
        id: "walk-lines",
        type: "line",
        source: "walk-lines",
        layout: { "line-cap": "round", "line-join": "round" },
        paint: {
          "line-color": ["match", ["get", "tone"], "main", tone.main, "alt", tone.alt, "back", tone.back, "muted", tone.muted, tone.link],
          "line-width": ["match", ["get", "tone"], "main", 5, "back", 4, "alt", 3.5, 2],
          "line-opacity": ["match", ["get", "tone"], "alt", 0.55, "muted", 0.6, 1],
          "line-dasharray": ["match", ["get", "tone"], "back", ["literal", [1.5, 1.5]], "link", ["literal", [1, 2.5]], ["literal", [1, 0]]],
        },
      });
    }
    m.setLayoutProperty("building-3d", "visibility", d.is3d ? "visible" : "none");
    (m.getSource("walk-lines") as GeoJSONSource).setData(lineFeatures(d.lines));
    (m.getSource("walk-radius") as GeoJSONSource).setData(
      d.start && d.radiusM ? circle(d.start.point, d.radiusM) : { type: "FeatureCollection", features: [] },
    );
  };

  useEffect(() => {
    const m = new MlMap({
      container: el.current!,
      style: STYLES[data.current.theme],
      center: toLngLat(ASTANA),
      zoom: 13.4,
      pitch: data.current.is3d ? PITCH_3D : 0,
      bearing: data.current.is3d ? -18 : 0,
      maxPitch: 70,
      attributionControl: { compact: true },
      // The style's own labels are Latin; ours (pins, chips) carry the local names.
      fadeDuration: 150,
    });
    map.current = m;
    m.on("style.load", () => {
      styleReady.current = true;
      applyOverlays();
    });
    m.on("click", (e) => {
      if (handlers.current.picking) handlers.current.onPick([e.lngLat.lat, e.lngLat.lng]);
    });
    let reported = false;
    m.on("error", (e) => {
      const err = e as unknown as { sourceId?: string; tile?: unknown };
      if (!reported && (err.tile || err.sourceId)) {
        reported = true;
        handlers.current.onTileError();
      }
    });
    const ro = new ResizeObserver(() => m.resize());
    ro.observe(el.current!);
    return () => {
      ro.disconnect();
      m.remove();
      map.current = null;
    };
    // The map is created once; props reach it through the effects below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // A theme switch swaps the base style; our layers come back on "style.load".
  const firstTheme = useRef(theme);
  useEffect(() => {
    if (theme === firstTheme.current) return;
    firstTheme.current = theme;
    styleReady.current = false;
    map.current?.setStyle(STYLES[theme]);
  }, [theme]);

  useEffect(applyOverlays, [lines, start?.point[0], start?.point[1], radiusM]);

  useEffect(() => {
    try {
      localStorage.setItem("map3d", is3d ? "1" : "0");
    } catch {
      // Kept for this page only.
    }
    const m = map.current;
    if (!m) return;
    applyOverlays();
    const view = { pitch: is3d ? PITCH_3D : 0, bearing: is3d ? -18 : 0 };
    if (still()) m.jumpTo(view);
    else m.easeTo({ ...view, duration: 700 });
    // applyOverlays reads the latest state from refs.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [is3d]);

  useEffect(() => {
    el.current?.classList.toggle("picking", picking);
  }, [picking]);

  // Pins: rebuilt when the set changes (at most a few dozen), highlighted in place on hover.
  useEffect(() => {
    const m = map.current;
    if (!m) return;
    for (const { marker } of pinMarkers.current.values()) marker.remove();
    pinMarkers.current.clear();
    pins.forEach((p, i) => {
      const { wrap, pin } = pinElement(
        p,
        () => handlers.current.onPin(p.id),
        (on) => handlers.current.onHover(on ? p.id : null),
      );
      pin.style.animationDelay = `${Math.min(i, 20) * 25}ms`;
      const marker = new Marker({ element: wrap, anchor: "bottom" }).setLngLat([p.lon, p.lat]).addTo(m);
      pinMarkers.current.set(p.id, { marker, el: pin });
    });
  }, [pins]);

  useEffect(() => {
    for (const [id, { el: node, marker }] of pinMarkers.current) {
      node.classList.toggle("active", id === activeId);
      marker.getElement().style.zIndex = id === activeId ? "5" : "";
    }
  }, [activeId, pins]);

  useEffect(() => {
    const m = map.current;
    flags.current.start?.remove();
    flags.current.start = undefined;
    if (!m || !start) return;
    flags.current.start = new Marker({ element: flagElement("start", labels.start, start.name), anchor: "bottom" })
      .setLngLat(toLngLat(start.point))
      .addTo(m);
  }, [start?.point[0], start?.point[1], start?.name, labels.start]);

  useEffect(() => {
    const m = map.current;
    flags.current.finish?.remove();
    flags.current.finish = undefined;
    if (!m || !finish) return;
    flags.current.finish = new Marker({ element: flagElement("finish", labels.finish, finish.name), anchor: "bottom" })
      .setLngLat(toLngLat(finish.point))
      .addTo(m);
  }, [finish?.point[0], finish?.point[1], finish?.name, labels.finish]);

  useEffect(() => {
    const m = map.current;
    flags.current.people.forEach((x) => x.remove());
    flags.current.people = [];
    if (!m) return;
    for (const p of people) {
      const node = document.createElement("div");
      node.className = "map-person";
      node.append(emojiNode("🧑"), document.createTextNode(" " + p.name));
      flags.current.people.push(new Marker({ element: node, anchor: "bottom" }).setLngLat([p.longitude, p.latitude]).addTo(m));
    }
  }, [people]);

  // A new answer: show the start, every pin and every line, clear of the panel.
  useEffect(() => {
    const m = map.current;
    if (!m || !fitKey) return;
    const b = new LngLatBounds();
    for (const l of lines) for (const p of l.geometry) b.extend(toLngLat(p));
    for (const p of pins) b.extend([p.lon, p.lat]);
    if (start) b.extend(toLngLat(start.point));
    if (finish) b.extend(toLngLat(finish.point));
    if (b.isEmpty()) return;
    const pad = handlers.current.padding();
    m.fitBounds(b, {
      padding: { top: pad.top + 60, bottom: pad.bottom + 60, left: pad.left + 60, right: pad.right + 70 },
      maxZoom: 16.2,
      pitch: data.current.is3d ? PITCH_3D : 0,
      duration: still() ? 0 : 900,
    });
    // Only a new result set refits; hovering or theme changes leave the view alone.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fitKey]);

  // The planner shows the whole reach circle: it grows and shrinks with the chosen time.
  useEffect(() => {
    const m = map.current;
    if (!m || !start || !radiusM) return;
    const [lat, lon] = start.point;
    const dLat = radiusM / 111320;
    const dLon = radiusM / (111320 * Math.cos((lat * Math.PI) / 180));
    const pad = handlers.current.padding();
    m.fitBounds(
      [
        [lon - dLon, lat - dLat],
        [lon + dLon, lat + dLat],
      ],
      {
        padding: { top: pad.top + 40, bottom: pad.bottom + 40, left: pad.left + 40, right: pad.right + 80 },
        pitch: data.current.is3d ? PITCH_3D : 0,
        duration: still() ? 0 : 800,
      },
    );
  }, [radiusM, start?.point[0], start?.point[1]]);

  const flyTo = (point: LatLon, zoom = 15.5) => {
    const m = map.current;
    if (!m) return;
    const opts = { center: toLngLat(point), zoom: Math.max(m.getZoom(), zoom), padding: handlers.current.padding() };
    if (still()) m.jumpTo(opts);
    else m.flyTo({ ...opts, duration: 1100, essential: true });
  };

  useEffect(() => {
    if (focus) flyTo(focus.point, focus.zoom);
    // The key changes on every request, even to the same point.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focus?.key]);

  const zoom = (by: number) => map.current?.easeTo({ zoom: (map.current?.getZoom() ?? 13) + by, duration: still() ? 0 : 250 });

  return (
    <div className="map-wrap">
      <div ref={el} className="map-canvas" role="region" aria-label={labels.aria} />
      <div className="map-controls">
        <button type="button" className="map-btn" aria-label={labels.zoomIn} title={labels.zoomIn} onClick={() => zoom(1)}>
          <Icon name="plus" />
        </button>
        <button type="button" className="map-btn" aria-label={labels.zoomOut} title={labels.zoomOut} onClick={() => zoom(-1)}>
          <Icon name="minus" />
        </button>
        <button
          type="button"
          className={"map-btn map-3d" + (is3d ? " on" : "")}
          aria-pressed={is3d}
          aria-label={is3d ? labels.to2d : labels.to3d}
          title={is3d ? labels.to2d : labels.to3d}
          onClick={() => setIs3d(!is3d)}
        >
          {is3d ? "3D" : "2D"}
        </button>
        <button
          type="button"
          className="map-btn"
          aria-label={labels.recenter}
          title={labels.recenter}
          disabled={!start}
          onClick={() => start && flyTo(start.point, 16)}
        >
          <Icon name="locate" />
        </button>
      </div>
    </div>
  );
}
