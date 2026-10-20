import { useEffect, useRef, useState } from "react";
import {
  request,
  type ChatResponse,
  type EventRecord,
  type Meta,
  type Plan,
  type Poi,
  type Provider,
  type Weather,
} from "./api";
import { useT } from "./lib/i18n";

export type Panel = "places" | "map" | "chat";
export type Message = { id: number; role: "user" | "assistant"; text: string; data?: ChatResponse };
export type Origin = [number, number];

const BAYTEREK: Origin = [51.1282882, 71.4304546];
const ASTANA_BOUNDS = { minLat: 50.8, maxLat: 51.5, minLon: 71, maxLon: 71.9 };

/** All workspace state and API actions; components only render and call these. */
export function useWalk() {
  const t = useT();
  const [meta, setMeta] = useState<Meta>();
  const [weather, setWeather] = useState<Weather>();
  const [items, setItems] = useState<Poi[]>([]);
  const [selected, setSelected] = useState<Poi>();
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("");
  const [minutes, setMinutes] = useState(90);
  const [when, setWhen] = useState("");
  const [origin, setOrigin] = useState<Origin | null>(BAYTEREK);
  const [originLabel, setOriginLabel] = useState("Бәйтерек");
  const [picking, setPicking] = useState(false);
  const [openOnly, setOpenOnly] = useState(false);
  const [noSteps, setNoSteps] = useState(false);
  const [snapRadius, setSnapRadius] = useState(150);
  const [strict, setStrict] = useState(false);
  const [groupSize, setGroupSize] = useState(1);
  const [airportTransfer, setAirportTransfer] = useState("");
  const [airportReserve, setAirportReserve] = useState("");
  const [provider, setProvider] = useState<Provider>("offline");
  const [miniRoute, setMiniRoute] = useState(false);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [compareIds, setCompareIds] = useState<string[]>([]);
  const [comparison, setComparison] = useState<Poi[]>([]);
  const [plan, setPlan] = useState<Plan>();
  const [panel, setPanel] = useState<Panel>("map");
  const [afisha, setAfisha] = useState<EventRecord[] | null>(null);
  const serial = useRef(0);
  const searchAbort = useRef<AbortController | null>(null);

  // Notices (not errors) are hints; they leave on their own instead of covering the card.
  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(""), 6000);
    return () => window.clearTimeout(timer);
  }, [notice]);

  const message = (e: unknown, fallbackKey: string) => (e instanceof Error && e.message ? e.message : t(fallbackKey));

  const ctx = () => ({
    latitude: origin?.[0],
    longitude: origin?.[1],
    minutes,
    when: when || null,
    no_steps: noSteps,
    max_snap_m: snapRadius,
    // 1 = not set: the chat can still read "нас 4" from the text.
    group_size: groupSize > 1 ? groupSize : null,
    airport_transfer_min: airportTransfer === "" ? null : Number(airportTransfer),
    airport_reserve_min: airportReserve === "" ? null : Number(airportReserve),
  });

  async function search() {
    const seq = ++serial.current;
    searchAbort.current?.abort();
    const controller = new AbortController();
    searchAbort.current = controller;
    setLoading(true);
    setError("");
    setPlan(undefined);
    setSelected(undefined);
    try {
      const data = await request<{ items: Poi[]; warnings: string[] }>(
        "search",
        { ...ctx(), query, category: category || null, open_only: openOnly, strict_amenities: strict, limit: 50 },
        controller.signal,
      );
      if (seq !== serial.current) return;
      setItems(data.items);
      setNotice(data.warnings.join(" "));
    } catch (e) {
      if (seq === serial.current) setError(message(e, "err.search"));
    } finally {
      if (seq === serial.current) setLoading(false);
    }
  }

  useEffect(() => {
    request<Meta>("meta")
      .then((m) => {
        setMeta(m);
        setProvider(m.default_provider);
        if (m.snap_radius_m) setSnapRadius(m.snap_radius_m.default);
      })
      .catch(() => setError(t("err.backend")));
    search();
    request<Weather>("weather").then(setWeather).catch(() => {});
    return () => searchAbort.current?.abort();
    // Initial load only; later searches are explicit user actions.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function ask(text: string) {
    const clean = text.trim();
    if (!clean || busy) return;
    setBusy(true);
    setError("");
    setPanel("chat");
    setMessages((m) => [...m, { id: Date.now(), role: "user", text: clean }]);
    try {
      const data = await request<ChatResponse>("chat", {
        ...ctx(),
        query: clean,
        provider,
        category: category || null,
        open_only: openOnly,
        strict_amenities: strict,
        // Unchecked: the server still builds a route when the request asks for a walk.
        mini_route: miniRoute ? true : null,
      });
      setMessages((m) => [...m, { id: Date.now() + 1, role: "assistant", text: data.answer, data }]);
      setItems(data.items);
      setSelected(undefined);
      // A mini-route goes straight onto the map as the current itinerary.
      setPlan(data.mini_route?.stops.length ? data.mini_route : undefined);
      if (data.origin) {
        setOrigin([data.origin.latitude, data.origin.longitude]);
        if (data.origin.label) setOriginLabel(data.origin.label);
      }
      setMinutes(data.minutes);
    } catch (e) {
      setMessages((m) => [...m, { id: Date.now() + 1, role: "assistant", text: message(e, "chat.unavailable") }]);
    } finally {
      setBusy(false);
    }
  }

  function toggleCompare(p: Poi) {
    setCompareIds((ids) =>
      ids.includes(p.poi_id) ? ids.filter((i) => i !== p.poi_id) : ids.length < 3 ? [...ids, p.poi_id] : ids,
    );
  }

  function clearCompare() {
    setCompareIds([]);
    setComparison([]);
  }

  async function compare() {
    setError("");
    try {
      const data = await request<{ items: Poi[] }>("compare", { ...ctx(), poi_ids: compareIds });
      setComparison(data.items);
    } catch (e) {
      setError(message(e, "err.compare"));
    }
  }

  async function buildPlan(ids = compareIds) {
    setBusy(true);
    setError("");
    try {
      const data = await request<Plan>("plan", { ...ctx(), poi_ids: ids });
      setPlan(data);
      setSelected(undefined);
      setPanel("map");
      setNotice(data.stops.length ? "" : t("notice.planEmpty"));
    } catch (e) {
      setError(message(e, "err.plan"));
    } finally {
      setBusy(false);
    }
  }

  function showPlan(p: Plan) {
    setSelected(undefined);
    setPlan(p);
    setPanel("map");
  }

  function selectPlace(p: Poi | undefined, showMap = true) {
    setSelected(p);
    setPlan(undefined);
    if (p && showMap) setPanel("map");
  }

  function setLandmark(key: string) {
    const lm = meta?.landmarks[key];
    if (!lm) return;
    setOrigin([lm.lat, lm.lon]);
    setOriginLabel(lm.name);
  }

  function pickOrigin(point: Origin) {
    setOrigin(point);
    setOriginLabel(t("map.pointOnMap"));
    setPicking(false);
    setNotice(t("notice.originUpdated"));
  }

  function locate() {
    if (!navigator.geolocation) {
      setError(t("err.geoUnsupported"));
      return;
    }
    navigator.geolocation.getCurrentPosition(
      ({ coords }) => {
        const b = ASTANA_BOUNDS;
        if (coords.latitude < b.minLat || coords.latitude > b.maxLat || coords.longitude < b.minLon || coords.longitude > b.maxLon) {
          setError(t("err.geoOutside"));
          return;
        }
        setOrigin([coords.latitude, coords.longitude]);
        setOriginLabel(t("filters.myLocation"));
        setNotice(t("notice.geoUpdated"));
      },
      () => setError(t("err.geoDenied")),
      { enableHighAccuracy: false, timeout: 10000, maximumAge: 60000 },
    );
  }

  async function openAfisha() {
    try {
      const data = await request<{ items: EventRecord[] }>("events");
      setAfisha(data.items);
    } catch (e) {
      setError(message(e, "err.afisha"));
    }
  }

  function dismiss() {
    setError("");
    setNotice("");
  }

  return {
    meta, weather, items, selected, plan, panel, setPanel, loading, busy, error, notice, dismiss,
    filters: {
      query, setQuery, category, setCategory, minutes, setMinutes, when, setWhen,
      origin, originLabel, setLandmark, picking, setPicking, locate,
      openOnly, setOpenOnly, noSteps, setNoSteps, snapRadius, setSnapRadius, strict, setStrict, groupSize, setGroupSize,
      airportTransfer, setAirportTransfer, airportReserve, setAirportReserve,
    },
    chat: { messages, miniRoute, setMiniRoute, ask },
    compareState: { compareIds, comparison, setComparison, toggleCompare, clearCompare, compare },
    afishaState: { afisha, setAfisha, openAfisha },
    search, buildPlan, selectPlace, setPlan, showPlan, pickOrigin,
  };
}

export type Walk = ReturnType<typeof useWalk>;
