import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Plan, Poi } from "./api";
import { CityPage } from "./components/CityPage";
import { Notification } from "./components/Overlays";
import { BackendStatus } from "./lib/BackendStatus";
import { categoryColor, placeEmoji } from "./lib/emoji";
import { ErrorBoundary } from "./lib/ErrorBoundary";
import { Emo } from "./lib/Emo";
import { Icon } from "./lib/Icon";
import { useT } from "./lib/i18n";
import { usePrefs } from "./lib/prefs";
import { canSpeak, speak, warmUpVoices } from "./lib/voice";
import { MapView, type MapLine, type MapPin } from "./MapView";
import { Chat } from "./ui/Chat";
import { Group } from "./ui/Group";
import { More } from "./ui/More";
import { Nearby } from "./ui/Nearby";
import { PlaceDetail } from "./ui/PlaceDetail";
import { Planner } from "./ui/Planner";
import { Results } from "./ui/Results";
import { StartPicker } from "./ui/StartPicker";
import type { HistoryEntry } from "./lib/history";
import { useWalk } from "./useWalk";

type Tab = "walk" | "nearby" | "group" | "chat" | "more";
const TABS: { key: Tab; icon: string }[] = [
  { key: "walk", icon: "navigation" },
  { key: "nearby", icon: "compass" },
  { key: "group", icon: "users" },
  { key: "chat", icon: "sparkles" },
  { key: "more", icon: "layout-grid" },
];
// Walking pace for the reach circle on the map (≈4.2 km/h), with time kept for a visit.
const PACE_M_PER_MIN = 70;
const DESKTOP = 860;

function useStored(key: string, fallback: boolean): [boolean, (v: boolean) => void] {
  const [on, setOn] = useState(() => {
    try {
      const v = localStorage.getItem(key);
      return v == null ? fallback : v === "1";
    } catch {
      return fallback;
    }
  });
  const set = (v: boolean) => {
    setOn(v);
    try {
      localStorage.setItem(key, v ? "1" : "0");
    } catch {
      // Kept for this page only.
    }
  };
  return [on, set];
}

function pinOf(p: Poi, number?: number): MapPin {
  return { id: p.poi_id, lat: p.latitude, lon: p.longitude, emoji: placeEmoji(p), color: categoryColor(p.category), label: p.display_name, number };
}

export default function App() {
  const t = useT();
  const { theme, lang, setLang } = usePrefs();
  const walk = useWalk();
  const f = walk.filters;
  const [tab, setTab] = useState<Tab>("walk");
  const [stage, setStage] = useState<"plan" | "results">("plan");
  const [startPicker, setStartPicker] = useState(false);
  const [awaiting, setAwaiting] = useState(false);
  const [hover, setHover] = useState<string | null>(null);
  const [cityOpen, setCityOpen] = useState(false);
  const [tileError, setTileError] = useState(false);
  const [sheetOpen, setSheetOpen] = useState(true);
  const [spoken, setSpoken] = useStored("spokenReplies", true);
  const panel = useRef<HTMLElement>(null);
  const body = useRef<HTMLDivElement>(null);
  const focusKey = useRef(0);
  const [focus, setFocus] = useState<{ point: [number, number]; key: number; zoom?: number } | null>(null);
  // A past walk to run again once its time, mode and start are on the filters.
  const [repeat, setRepeat] = useState<HistoryEntry | null>(null);
  useEffect(() => {
    if (!repeat || f.minutes !== repeat.minutes || f.walkMode !== repeat.mode) return;
    setRepeat(null);
    walk.chat.ask(repeat.wish || t("ui.defaultQuery"), true);
    // Runs when the filters caught up with the walk to repeat.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [repeat, f.minutes, f.walkMode]);
  const repeatWalk = (e: HistoryEntry) => {
    f.setMinutes(e.minutes);
    f.setWalkMode(e.mode);
    if (e.start.key && walk.meta?.landmarks[e.start.key]) f.setLandmark(e.start.key);
    setTab("walk");
    setStartPicker(false);
    setStage("results");
    setAwaiting(true);
    setRepeat(e);
  };

  // The answer arrived (or failed): the loading steps give way to the result.
  useEffect(() => {
    if (!walk.busy) setAwaiting(false);
  }, [walk.busy]);

  // Every reply plays its short spoken summary once, for blind and low-vision users.
  const lastSpoken = useRef(0);
  useEffect(() => warmUpVoices(), []);
  useEffect(() => {
    const last = walk.chat.messages[walk.chat.messages.length - 1];
    if (!last || last.role !== "assistant" || last.id === lastSpoken.current) return;
    lastSpoken.current = last.id;
    if (spoken && canSpeak()) speak(last.data?.spoken || last.text, lang);
    // Speak each new reply once, in the language of the moment.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [walk.chat.messages]);

  // A start picked on the map or from geolocation closes the picker and shows the panel again.
  useEffect(() => {
    if (!walk.originFocus || !f.origin) return;
    setStartPicker(false);
    setSheetOpen(true);
    focusKey.current += 1;
    setFocus({ point: f.origin, key: focusKey.current, zoom: 15 });
    // Only a new pick moves the map.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [walk.originFocus]);

  // Picking a point needs the map: the sheet folds away on phones.
  useEffect(() => {
    if (f.picking && window.innerWidth < DESKTOP) setSheetOpen(false);
  }, [f.picking]);

  useEffect(() => {
    body.current?.scrollTo({ top: 0 });
  }, [tab, stage, startPicker, walk.selected?.poi_id]);

  useEffect(() => {
    if (!walk.selected) return;
    focusKey.current += 1;
    setFocus({ point: [walk.selected.latitude, walk.selected.longitude], key: focusKey.current, zoom: 16 });
    setSheetOpen(true);
  }, [walk.selected]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || document.querySelector(".photo-lightbox")) return;
      if (walk.selected) walk.selectPlace(undefined);
      else if (startPicker) setStartPicker(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [walk, startPicker]);

  const openPlace = (p: Poi) => walk.selectPlace(p, false);
  const showRoute = (p: Plan) => {
    walk.showPlan(p);
    setTab("walk");
    setStage("results");
  };
  const switchTab = (next: Tab) => {
    walk.selectPlace(undefined, false);
    setStartPicker(false);
    f.setPicking(false);
    setTab(next);
    setSheetOpen(true);
  };

  // What the map draws follows the screen: the walk and its answer, the nearby list, or a guided tour.
  const answerShown = (tab === "walk" && stage === "results") || tab === "chat";
  const scene = useMemo(() => {
    const pins: MapPin[] = [];
    const lines: MapLine[] = [];
    let finish: { point: [number, number]; name: string } | null = null;
    let people: { name: string; latitude: number; longitude: number }[] = [];
    let key = "";
    const plan = walk.plan;
    if (walk.tour) {
      const { detail, current } = walk.tour;
      detail.legs.forEach((leg, i) => lines.push({ geometry: leg.geometry, tone: i < current ? "muted" : "main" }));
      detail.stops.forEach((s, i) =>
        pins.push({
          id: "tour:" + s.id,
          lat: s.latitude,
          lon: s.longitude,
          emoji: s.outdoor ? "🌲" : "🏛️",
          color: "#00B8D9",
          label: s.name,
          number: i + 1,
          state: i === current ? "current" : i < current ? "done" : undefined,
        }),
      );
      key = "tour:" + detail.id;
    } else if (tab === "nearby") {
      walk.items.forEach((p) => pins.push(pinOf(p)));
      key = "near:" + walk.items.map((p) => p.poi_id).join(",");
    } else if (answerShown && plan) {
      plan.stops.forEach((p, i) => pins.push(pinOf(p, i + 1)));
      plan.legs.forEach((l) => lines.push({ geometry: l.geometry, tone: "main" }));
      if (plan.finish) {
        lines.push({ geometry: plan.finish.leg.geometry, tone: plan.finish.loop ? "back" : "main" });
        if (!plan.finish.loop) finish = { point: [plan.finish.latitude, plan.finish.longitude], name: plan.finish.label };
      }
      // After a re-plan the rest of the walk starts where the walker is: a dotted link from there.
      if (walk.trip && plan.legs[0]?.geometry[0]) lines.push({ geometry: [walk.trip.position, plan.legs[0].geometry[0]], tone: "link" });
      key = "plan:" + plan.stops.map((p) => p.poi_id).join(",") + ":" + (plan.finish?.label ?? "");
    } else if (answerShown && walk.answer) {
      const items = walk.answer.items;
      items.forEach((p, i) => pins.push(pinOf(p, i + 1)));
      if (walk.meeting) {
        people = walk.meeting;
        (items[0]?.meeting_routes ?? []).forEach((r) => lines.push({ geometry: r.geometry, tone: "main" }));
      } else {
        const lit = hover ?? walk.selected?.poi_id;
        items.forEach((p) => p.route && lines.push({ geometry: p.route.geometry, tone: p.poi_id === lit ? "main" : "alt" }));
      }
      key = "answer:" + items.map((p) => p.poi_id).join(",");
    }
    const sel = walk.selected;
    if (sel && !pins.some((p) => p.id === sel.poi_id)) pins.push(pinOf(sel));
    if (sel?.route && !lines.some((l) => l.tone === "main" && l.geometry === sel.route!.geometry) && !(answerShown && plan))
      lines.push({ geometry: sel.route.geometry, tone: "main" });
    return { pins, lines, finish, people, key };
  }, [walk.tour, walk.items, walk.plan, walk.answer, walk.meeting, walk.selected, walk.trip, tab, answerShown, hover]);

  // The hover only re-colours lines: the fit waits for a new set of places.
  const fitKey = scene.key;
  // Straight-line reach: half the budget each way (round trip) minus a visit, with streets
  // longer than the crow flies (×0.7).
  const reach =
    tab === "walk" && stage === "plan" && !walk.tour
      ? Math.round(Math.max(250, (f.walkMode === "loop" ? 0.5 : 1) * Math.max(10, f.minutes - 20) * PACE_M_PER_MIN * 0.7))
      : null;
  const padding = useCallback(() => {
    const r = panel.current?.getBoundingClientRect();
    if (!r) return { top: 0, bottom: 0, left: 0, right: 0 };
    return window.innerWidth >= DESKTOP
      ? { top: 0, bottom: 0, left: r.right, right: 0 }
      : { top: 0, bottom: Math.max(0, window.innerHeight - r.top), left: 0, right: 0 };
  }, []);

  let screen;
  if (walk.selected)
    screen = (
      <PlaceDetail
        walk={walk}
        p={walk.selected}
        onBack={() => walk.selectPlace(undefined, false)}
        onRoute={() => {
          walk.buildPlan([walk.selected!.poi_id]);
          setTab("walk");
          setStage("results");
        }}
      />
    );
  else if (tab === "walk")
    screen = startPicker ? (
      <StartPicker walk={walk} onDone={() => setStartPicker(false)} />
    ) : stage === "results" ? (
      <Results walk={walk} pending={awaiting} onBack={() => setStage("plan")} onOpen={openPlace} hoverId={hover} setHover={setHover} />
    ) : (
      <Planner
        walk={walk}
        onStartPicker={() => setStartPicker(true)}
        onGo={() => {
          setAwaiting(true);
          setStage("results");
        }}
      />
    );
  else if (tab === "nearby") screen = <Nearby walk={walk} onOpen={openPlace} hoverId={hover} setHover={setHover} />;
  else if (tab === "group")
    screen = (
      <Group
        walk={walk}
        onGo={() => {
          setTab("walk");
          setStartPicker(false);
          setAwaiting(true);
          setStage("results");
        }}
      />
    );
  else if (tab === "chat") screen = <Chat walk={walk} onOpen={openPlace} onShowRoute={showRoute} spoken={spoken} setSpoken={setSpoken} />;
  else screen = <More walk={walk} onCity={() => setCityOpen(true)} onRepeat={repeatWalk} spoken={spoken} setSpoken={setSpoken} />;

  const screenKey = walk.selected ? "place:" + walk.selected.poi_id : tab + ":" + stage + ":" + startPicker;

  return (
    <>
      <BackendStatus />
      <ErrorBoundary>
        <MapView
          theme={theme}
          pins={scene.pins}
          lines={scene.lines}
          start={f.origin ? { point: f.origin, name: f.originName } : null}
          finish={scene.finish}
          people={scene.people}
          radiusM={reach}
          activeId={hover ?? walk.selected?.poi_id}
          fitKey={fitKey}
          focus={focus}
          picking={f.picking}
          onPin={(id) => {
            if (id.startsWith("tour:")) {
              const i = walk.tour?.detail.stops.findIndex((s) => "tour:" + s.id === id) ?? -1;
              if (walk.tour && i >= 0) walk.setTour({ ...walk.tour, current: i });
              return;
            }
            const p = [...(walk.plan?.stops ?? []), ...(walk.answer?.items ?? []), ...walk.items].find((x) => x.poi_id === id);
            if (p) openPlace(p);
          }}
          onHover={setHover}
          onPick={walk.pickOrigin}
          onTileError={() => setTileError(true)}
          padding={padding}
          labels={{
            aria: t("map.aria"),
            start: t("map.start"),
            finish: t("map.finish"),
            zoomIn: t("ui.zoomIn"),
            zoomOut: t("ui.zoomOut"),
            to3d: t("ui.to3d"),
            to2d: t("ui.to2d"),
            recenter: t("map.recenter"),
          }}
        />
      </ErrorBoundary>
      {f.picking && (
        <div className="pick-banner" role="status">
          <Emo e="🎯" /> {t("ui.pickBanner")}
          <button className="soft-btn" onClick={() => f.setPicking(false)}>
            {t("ui.cancel")}
          </button>
        </div>
      )}
      {tileError && <div className="tile-error">{t("map.tileError")}</div>}

      <aside ref={panel} className={"panel" + (sheetOpen ? "" : " folded")} aria-label={t("ui.panel")}>
        <header className="panel-head">
          <button
            className="sheet-grip"
            aria-label={sheetOpen ? t("ui.foldPanel") : t("ui.unfoldPanel")}
            aria-expanded={sheetOpen}
            onClick={() => setSheetOpen(!sheetOpen)}
          >
            <i />
          </button>
          <a href="/" className="brand" aria-label={t("brand.aria")}>
            <span className="brand-mark" aria-hidden="true">
              <svg viewBox="0 0 32 32">
                <path d="M16 4.5c-5.1 0-9.2 4-9.2 9 0 6.6 9.2 14 9.2 14s9.2-7.4 9.2-14c0-5-4.1-9-9.2-9Z" />
                <circle cx="16" cy="13.6" r="3.4" />
              </svg>
            </span>
            <span className="brand-name">
              Astana <b>Walk</b>
            </span>
            <span className="brand-city">{t("top.city")}</span>
          </a>
          <div className="lang-seg" role="group" aria-label={t("top.lang")}>
            <button aria-pressed={lang === "ru"} onClick={() => setLang("ru")} lang="ru">
              РУС
            </button>
            <button aria-pressed={lang === "kk"} onClick={() => setLang("kk")} lang="kk">
              ҚАЗ
            </button>
            <button aria-pressed={lang === "en"} onClick={() => setLang("en")} lang="en">
              ENG
            </button>
          </div>
        </header>
        <div className="panel-body" ref={body}>
          <ErrorBoundary>
            <div className="screen-anim" key={screenKey}>
              {screen}
            </div>
          </ErrorBoundary>
        </div>
        <nav className="tabbar" aria-label={t("nav.sections")}>
          {TABS.map((x) => (
            <button key={x.key} aria-current={tab === x.key ? "page" : undefined} onClick={() => switchTab(x.key)}>
              <Icon name={x.icon} />
              <span>{t("ui.tab." + x.key)}</span>
              {x.key === "chat" && walk.busy && <i className="tab-dot" aria-hidden="true" />}
            </button>
          ))}
        </nav>
      </aside>
      <Notification walk={walk} />
      {cityOpen && <CityPage onClose={() => setCityOpen(false)} />}
    </>
  );
}
