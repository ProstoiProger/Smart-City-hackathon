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
  type DialogState,
  type MeetingPerson,
  type Provider,
  type ReplanResponse,
  type TripAction,
  type TripSession,
  type Weather,
} from "./api";
import { has, useT } from "./lib/i18n";
import {
  loadHistory,
  mergePlaces,
  newEntry,
  readFlag,
  saveHistory,
  visitedIds,
  writeFlag,
  type HistoryEntry,
} from "./lib/history";
import { clockAt } from "./lib/format";

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
// The chat message a walk button stands for.
const TRIP_WORDS: Record<TripAction, string> = {
  closed: "trip.closed",
  delay: "trip.delay",
  cold: "trip.cold",
  tired: "trip.tired",
  swap: "trip.swap",
};
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
  const [finishKey, setFinishKey] = useState(() => {
    try {
      return localStorage.getItem("walkMode") === "oneway" ? "" : "loop";
    } catch {
      return "loop";
    }
  });
  const [trip, setTrip] = useState<Trip | null>(null);
  // Bumped when the user changes the start themself: the map flies there.
  const [originFocus, setOriginFocus] = useState(0);
  // People of a meeting question, drawn on the map with their walks to the place.
  const [meeting, setMeeting] = useState<MeetingPerson[] | null>(null);
  // The last answer of the chat: follow-ups ("ещё", "убери второе") refine it.
  const [dialog, setDialog] = useState<DialogState | null>(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  // The last answer of the assistant: the walk screen shows it as options or a route.
  const [answer, setAnswer] = useState<ChatResponse | null>(null);
  // Pins on the map are numbered when they are the assistant's answer, plain for a search.
  const [itemsSource, setItemsSource] = useState<"search" | "answer">("search");
  const [plan, setPlan] = useState<Plan>();
  const [panel, setPanel] = useState<Panel>("map");
  const [afisha, setAfisha] = useState<EventRecord[] | null>(null);
  const serial = useRef(0);
  const searchAbort = useRef<AbortController | null>(null);
  // Walk history: only in this browser, without coordinates (lib/history.ts).
  const [history, setHistoryState] = useState<HistoryEntry[]>(loadHistory);
  const [historyOn, setHistoryOnState] = useState(() => readFlag("on"));
  const [newOnly, setNewOnlyState] = useState(() => readFlag("newOnly"));
  // The entry of the walk on screen: follow-ups and walk buttons update it.
  const entryId = useRef<string | null>(null);

  function setHistory(update: (h: HistoryEntry[]) => HistoryEntry[]) {
    setHistoryState((h) => {
      const next = update(h);
      saveHistory(next);
      return next;
    });
  }

  function setHistoryOn(on: boolean) {
    setHistoryOnState(on);
    writeFlag("on", on);
  }

  function setNewOnly(on: boolean) {
    setNewOnlyState(on);
    writeFlag("newOnly", on);
  }

  function clearHistory() {
    entryId.current = null;
    setHistory(() => []);
  }

  /** The start as history keeps it: a landmark or a generic label, never coordinates. */
  function startForHistory(): HistoryEntry["start"] {
    if (landmarkKey) return { key: landmarkKey, label: meta?.landmarks[landmarkKey]?.name ?? landmarkKey };
    return { label: originLabel };
  }

  /** A new answer: a new entry for a fresh request, otherwise the current walk changes. */
  function remember(fresh: boolean, wish: string, places: Poi[], route: boolean, budget: number) {
    if (!historyOn || !places.length) return;
    const id = entryId.current;
    if (fresh || !id) {
      const entry = newEntry({ minutes: budget, mode: finishKey === "loop" ? "loop" : "oneway", route, start: startForHistory(), wish, places });
      entryId.current = entry.id;
      setHistory((h) => [entry, ...h]);
      return;
    }
    setHistory((h) => h.map((e) => (e.id === id ? { ...e, route, minutes: budget, places: mergePlaces(e.places, places) } : e)));
  }

  function markPlace(poiId: string, status: "visited" | "closed" | "planned", entry = entryId.current) {
    if (!entry) return;
    setHistory((h) =>
      h.map((e) => (e.id === entry ? { ...e, places: e.places.map((p) => (p.id === poiId ? { ...p, status } : p)) } : e)),
    );
  }

  function forgetWalk(id: string) {
    if (entryId.current === id) entryId.current = null;
    setHistory((h) => h.filter((e) => e.id !== id));
  }

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
    // "Только новые места": ids of places visited on earlier walks; the history itself stays here.
    exclude_ids: newOnly ? visitedIds(history) : [],
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
    // The walk on the "Прогулка" tab stays: a search only fills the "Рядом" list.
    setSelected(undefined);
    try {
      const data = await request<{ items: Poi[]; warnings: string[] }>(
        "search",
        { ...ctx(), query, category: cat || null, open_only: openOnly, strict_amenities: strict, limit: 50 },
        controller.signal,
      );
      if (seq !== serial.current) return;
      setItems(data.items);
      setItemsSource("search");
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

  /** `fresh`: a new walk from the planner (a new history entry), not a follow-up. */
  async function ask(text: string, fresh = false) {
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
        // The walk on screen: the message may edit it ("второе замени", "без кафе").
        // A fresh walk (planner, repeat from history) starts over instead of editing it.
        route: fresh ? undefined : routeContext(),
        dialog: fresh || routeContext() ? undefined : (dialog ?? undefined),
      });
      setMessages((m) => [...m, { id: Date.now() + 1, role: "assistant", text: data.answer, data }]);
      setAnswer(data);
      const stops = data.mini_route?.stops.length ? data.mini_route.stops : data.items;
      remember(fresh, clean, stops, !!data.mini_route?.stops.length, data.mini_route?.budget_minutes ?? data.minutes);
      setItems(data.items);
      setItemsSource("answer");
      setSelected(undefined);
      // A mini-route (or the way to a finish) goes straight onto the map as the current itinerary.
      const route = data.mini_route;
      setPlan(route && (route.stops.length || route.finish) ? route : undefined);
      setMeeting(data.meeting?.people ?? null);
      setDialog(data.dialog ?? null);
      // A new interest switched an old category chip off on the server: do the same here.
      if (data.cleared_category) setCategory("");
      if (data.trip_state && trip && route?.session) {
        // An edit continues the same walk: history, visited stops and time spent stay.
        const st = data.trip_state;
        setTrip({
          ...trip,
          session: route.session,
          elapsed: st.elapsed,
          position: [st.position.latitude, st.position.longitude],
          visited: st.visited,
          excluded: st.excluded,
          flags: st.flags,
          note: data.answer,
        });
      } else {
        setTrip(route?.session ? freshTrip(route.session) : null);
      }
      if (data.origin) {
        setOrigin([data.origin.latitude, data.origin.longitude]);
        if (data.origin.label) setOriginLabel(data.origin.label);
      }
      setMinutes(data.minutes);
    } catch (e) {
      setAnswer(null);
      setMessages((m) => [...m, { id: Date.now() + 1, role: "assistant", text: message(e, "chat.unavailable") }]);
    } finally {
      setBusy(false);
    }
  }

  function routeContext() {
    if (!trip || !plan || plan.kind !== "mini_route") return undefined;
    return {
      ...trip.session,
      elapsed: trip.elapsed,
      position: { latitude: trip.position[0], longitude: trip.position[1] },
      keep: plan.stops.map((p) => p.poi_id),
      visited: trip.visited,
      excluded: trip.excluded,
      flags: trip.flags,
      open_only: openOnly,
      strict_amenities: strict,
      no_steps: noSteps,
      max_snap_m: snapRadius,
    };
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
  /** A walk button pressed on the map shows in the chat as the user's message, and the
   * reply as the assistant's: the chat speaks it like any other answer. */
  function say(text: string) {
    setMessages((m) => [...m, { id: Date.now(), role: "user", text }]);
  }

  function reply(text: string, route?: Plan) {
    const data = route && (route.stops.length || route.finish)
      ? ({
          answer: text,
          spoken: text,
          items: route.stops,
          warnings: [],
          provider_used: "offline",
          steps: [],
          minutes: route.budget_minutes ?? minutes,
          mini_route: route,
          events: [],
        } as ChatResponse)
      : undefined;
    setMessages((m) => [...m, { id: Date.now() + 1, role: "assistant", text, data }]);
  }

  /** What comes next after "Посетили": the next stop, the finish, or the end of the walk. */
  function nextLine(rest: Poi[], route: Plan) {
    const start = route.session?.start_at;
    const next = rest[0];
    if (next) {
      const walkMin = Math.max(1, Math.round(route.legs[1]?.duration_min ?? 0));
      return t("trip.nextSay", {
        name: next.display_name.split(",")[0],
        walk: walkMin,
        at: clockAt(start, next.arrival_offset_min ?? 0),
      });
    }
    if (route.finish) {
      return t(route.finish.loop ? "trip.backSay" : "trip.finishSay", {
        name: route.finish.label,
        walk: Math.max(1, Math.round(route.finish.leg.duration_min)),
        at: clockAt(start, route.finish.arrival_offset_min),
      });
    }
    return t("trip.doneSay");
  }

  function visitStop() {
    if (!plan || !trip || !plan.stops.length) return;
    const [s, ...rest] = plan.stops;
    const after = { ...plan, stops: rest, legs: plan.legs.slice(1) };
    say(t("trip.visited"));
    reply(nextLine(rest, plan), after);
    markPlace(s.poi_id, "visited");
    setPlan(after);
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
  async function replan(action: TripAction, swap?: Poi) {
    if (!plan || !trip || busy) return;
    const next = plan.stops[0];
    const closing = action === "closed" && next;
    say(
      swap?.backup
        ? t("trip.swapSay", { from: swap.display_name.split(",")[0], to: swap.backup.display_name.split(",")[0] })
        : closing
          ? t("trip.closedSay", { name: next.display_name.split(",")[0] })
          : t(TRIP_WORDS[action]),
    );
    setBusy(true);
    setError("");
    try {
      const data = await request<ReplanResponse>("replan", {
        ...trip.session,
        action,
        // "Здесь закрыто": the walker is at the closed place, at its arrival time.
        elapsed: closing ? (next.arrival_offset_min ?? trip.elapsed) : trip.elapsed,
        position: closing
          ? { latitude: next.latitude, longitude: next.longitude }
          : { latitude: trip.position[0], longitude: trip.position[1] },
        stop_id: closing ? next.poi_id : swap ? swap.poi_id : null,
        replacement_id: swap?.backup?.poi_id ?? null,
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
      const after = data.plan
        ? { ...data.plan, session: trip.session }
        : { ...plan, stops: [], legs: [], finish: undefined };
      setPlan(after);
      if (closing) markPlace(next.poi_id, "closed");
      if (data.plan) remember(false, trip.session.query, data.plan.stops, true, trip.session.budget);
      reply(data.answer, after);
    } catch (e) {
      setError(message(e, "err.replan"));
      reply(message(e, "err.replan"));
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
      remember(true, data.stops.map((p) => p.display_name.split(",")[0]).join(", "), data.stops, true, minutes);
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

  /** Opens a place over the current screen; the walk on the map stays. */
  function selectPlace(p: Poi | undefined, showMap = true) {
    setSelected(p);
    if (p && showMap) setPanel("map");
  }

  /** "Туда и обратно" ends the walk at the start; "Только туда" leaves the end open. */
  function setWalkMode(mode: "loop" | "oneway") {
    setFinishKey(mode === "loop" ? "loop" : "");
    try {
      localStorage.setItem("walkMode", mode);
    } catch {
      // Kept for this page only.
    }
  }

  function setLandmark(key: string) {
    const lm = meta?.landmarks[key];
    if (!lm) return;
    setOrigin([lm.lat, lm.lon]);
    setOriginLabel(lm.name);
    setOriginFocus((n) => n + 1);
  }

  function pickOrigin(point: Origin) {
    setOrigin(point);
    setOriginLabel("i18n:map.pointOnMap");
    setOriginFocus((n) => n + 1);
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
        setOriginFocus((n) => n + 1);
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

  /** A short hint at the bottom of the screen ("Скопировано"). */
  function notify(text: string) {
    setError("");
    setNotice(text);
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
    meta, weather, items, selected, plan, panel, setPanel, loading, busy, error, notice, dismiss, notify,
    filters: {
      query, setQuery, category, setCategory, minutes, setMinutes, when, setWhen,
      origin, originLabel, originName, landmarkKey, setLandmark, picking, setPicking, locate,
      openOnly, setOpenOnly, noSteps, setNoSteps, snapRadius, setSnapRadius, strict, setStrict, groupSize, setGroupSize,
      finishKey, setFinishKey, walkMode: (finishKey === "loop" ? "loop" : "oneway") as "loop" | "oneway", setWalkMode,
      airportTransfer, setAirportTransfer, airportReserve, setAirportReserve,
    },
    chat: { messages, miniRoute, setMiniRoute, ask, members, setMembers },
    history: { entries: history, on: historyOn, setOn: setHistoryOn, newOnly, setNewOnly, clear: clearHistory, markPlace, forget: forgetWalk },
    answer, itemsSource,
    afishaState: { afisha, setAfisha, openAfisha },
    tour, setTour,
    trip, visitStop, replan, originFocus, meeting,
    search, buildPlan, selectPlace, setPlan, showPlan, pickOrigin,
  };
}

export type Walk = ReturnType<typeof useWalk>;
