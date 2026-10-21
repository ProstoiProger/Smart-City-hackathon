import { useEffect, useRef, useState } from "react";
import {
  request,
  type ChatResponse,
  type EventRecord,
  type TourDetail,
  type GroupMember,
  type Meta,
  type Plan,
  type Poi,
  type Provider,
  type ReplanResponse,
  type TripAction,
  type TripSession,
  type Weather,
} from "./api";
import { has, useT } from "./lib/i18n";

export type Panel = "places" | "map" | "chat";
export type Message = { id: number; role: "user" | "assistant"; text: string; data?: ChatResponse };
export type Origin = [number, number];
/** A walk in progress: the plan's session plus what happened on the way. */
export type Trip = {
  session: TripSession;
  /** Minutes since the start at `position` (after the last visit). */
  elapsed: number;
  position: Origin;
  visited: string[];
  excluded: string[];
  flags: string[];
  history: { id: string; name: string; status: "visited" | "closed" }[];
  /** What the last re-plan changed (server-composed text). */
  note?: string;
};

function freshTrip(session: TripSession): Trip {
  return {
    session,
    elapsed: 0,
    position: [session.start.latitude, session.start.longitude],
    visited: [],
    excluded: [],
    flags: [],
    history: [],
  };
}

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
  const [members, setMembers] = useState<GroupMember[]>([]);
  const [tour, setTour] = useState<{ detail: TourDetail; current: number } | null>(null);
  const [airportTransfer, setAirportTransfer] = useState("");
  const [airportReserve, setAirportReserve] = useState("");
  const [provider, setProvider] = useState<Provider>("offline");
  const [miniRoute, setMiniRoute] = useState(false);
  // "" — anywhere, "loop" — back to the start, or a landmark key.
  const [finishKey, setFinishKey] = useState("");
  const [trip, setTrip] = useState<Trip | null>(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
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

  /** `nextCategory` lets a category chip search right away, before the state update lands. */
  async function search(nextCategory?: string) {
    const cat = nextCategory ?? category;
    const seq = ++serial.current;
    searchAbort.current?.abort();
    const controller = new AbortController();
    searchAbort.current = controller;
    setLoading(true);
    setError("");
    setPlan(undefined);
    setTrip(null);
    setSelected(undefined);
    try {
      const data = await request<{ items: Poi[]; warnings: string[] }>(
        "search",
        { ...ctx(), query, category: cat || null, open_only: openOnly, strict_amenities: strict, limit: 50 },
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
        members: members.length >= 2 ? members : undefined,
        ...finishBody(),
      });
      setMessages((m) => [...m, { id: Date.now() + 1, role: "assistant", text: data.answer, data }]);
      setItems(data.items);
      setSelected(undefined);
      // A mini-route (or the way to a finish) goes straight onto the map as the current itinerary.
      const route = data.mini_route;
      setPlan(route && (route.stops.length || route.finish) ? route : undefined);
      setTrip(route?.session ? freshTrip(route.session) : null);
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

  function finishBody() {
    if (finishKey === "loop") return { finish_loop: true };
    const lm = finishKey ? meta?.landmarks[finishKey] : undefined;
    if (!lm) return {};
    return {
      finish_latitude: lm.lat,
      finish_longitude: lm.lon,
      finish_label: has("lm." + finishKey) ? t("lm." + finishKey) : lm.name,
    };
  }

  /** "Посетили": the next stop moves to the history; the times of the rest stay. */
  function visitStop() {
    if (!plan || !trip || !plan.stops.length) return;
    const [s, ...rest] = plan.stops;
    setPlan({ ...plan, stops: rest, legs: plan.legs.slice(1) });
    setTrip({
      ...trip,
      elapsed: (s.arrival_offset_min ?? trip.elapsed) + s.suggested_visit_duration_min,
      position: [s.latitude, s.longitude],
      visited: [...trip.visited, s.poi_id],
      history: [...trip.history, { id: s.poi_id, name: s.display_name, status: "visited" }],
      note: undefined,
    });
  }

  /** The rest of the walk after an event; the finish and its deadline stay. */
  async function replan(action: TripAction) {
    if (!plan || !trip || busy) return;
    const next = plan.stops[0];
    const closing = action === "closed" && next;
    setBusy(true);
    setError("");
    try {
      const data = await request<ReplanResponse>("replan", {
        ...trip.session,
        action,
        elapsed: closing ? (next.arrival_offset_min ?? trip.elapsed) : trip.elapsed,
        position: closing
          ? { latitude: next.latitude, longitude: next.longitude }
          : { latitude: trip.position[0], longitude: trip.position[1] },
        stop_id: closing ? next.poi_id : null,
        keep: plan.stops.map((p) => p.poi_id),
        visited: trip.visited,
        excluded: trip.excluded,
        flags: trip.flags,
        open_only: openOnly,
        strict_amenities: strict,
        no_steps: noSteps,
        max_snap_m: snapRadius,
      });
      const st = data.state;
      setTrip({
        ...trip,
        elapsed: st.elapsed,
        position: [st.position.latitude, st.position.longitude],
        visited: st.visited,
        excluded: st.excluded,
        flags: st.flags,
        history: closing ? [...trip.history, { id: next.poi_id, name: next.display_name, status: "closed" }] : trip.history,
        note: data.answer,
      });
      setPlan(
        data.plan
          ? { ...data.plan, session: trip.session }
          : { ...plan, stops: [], legs: [], finish: undefined },
      );
    } catch (e) {
      setError(message(e, "err.replan"));
    } finally {
      setBusy(false);
    }
  }

  async function buildPlan(ids: string[]) {
    setBusy(true);
    setError("");
    setTrip(null);
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

  /** A route from a chat answer starts its walk over. */
  function showPlan(p: Plan) {
    setSelected(undefined);
    setPlan(p);
    setTrip(p.session ? freshTrip(p.session) : null);
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
    setOriginLabel("i18n:map.pointOnMap");
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
        setOriginLabel("i18n:filters.myLocation");
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

  // Landmarks are shown in the interface language; map/geolocation starts by their kind;
  // a place named in the chat keeps the name the server returned.
  const landmarkKey = Object.entries(meta?.landmarks || {}).find(
    ([, p]) => origin && p.lat === origin[0] && p.lon === origin[1],
  )?.[0];
  const originName =
    landmarkKey && has("lm." + landmarkKey)
      ? t("lm." + landmarkKey)
      : originLabel.startsWith("i18n:")
        ? t(originLabel.slice(5))
        : originLabel;

  return {
    meta, weather, items, selected, plan, panel, setPanel, loading, busy, error, notice, dismiss,
    filters: {
      query, setQuery, category, setCategory, minutes, setMinutes, when, setWhen,
      origin, originLabel, originName, landmarkKey, setLandmark, picking, setPicking, locate,
      openOnly, setOpenOnly, noSteps, setNoSteps, snapRadius, setSnapRadius, strict, setStrict, groupSize, setGroupSize,
      finishKey, setFinishKey,
      airportTransfer, setAirportTransfer, airportReserve, setAirportReserve,
    },
    chat: { messages, miniRoute, setMiniRoute, ask, members, setMembers },
    afishaState: { afisha, setAfisha, openAfisha },
    tour, setTour,
    trip, visitStop, replan,
    search, buildPlan, selectPlace, setPlan, showPlan, pickOrigin,
  };
}

export type Walk = ReturnType<typeof useWalk>;
