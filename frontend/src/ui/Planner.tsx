import { useRef, useState } from "react";
import type { Weather } from "../api";
import { comfortLabel } from "../lib/format";
import { Emo } from "../lib/Emo";
import { Icon } from "../lib/Icon";
import { LANDMARK_EMOJI } from "../lib/emoji";
import { visitedIds } from "../lib/history";
import { has, useT } from "../lib/i18n";
import { usePrefs } from "../lib/prefs";
import { canListen, stopSpeaking, useDictation } from "../lib/voice";
import type { Walk } from "../useWalk";

export const MINUTES = [30, 45, 60, 90, 120, 180];

/** Quick wishes: each adds its words to the request; several can be on at once. */
export const WISHES = [
  { key: "coffee", emoji: "☕" },
  { key: "food", emoji: "🍽️" },
  { key: "park", emoji: "🌲" },
  { key: "water", emoji: "🌊" },
  { key: "kids", emoji: "🎈" },
  { key: "culture", emoji: "🎭" },
  { key: "views", emoji: "📸" },
  { key: "art", emoji: "🎨" },
  { key: "indoor", emoji: "🏠" },
  { key: "night", emoji: "🌛" },
];


/** "HH:MM" when a walk of `minutes` that starts now (or at `when`) ends. */
export function endClock(when: string, minutes: number) {
  const base = when ? new Date(when) : new Date();
  if (Number.isNaN(base.getTime())) return "";
  const end = new Date(base.getTime() + minutes * 60000);
  return `${String(end.getHours()).padStart(2, "0")}:${String(end.getMinutes()).padStart(2, "0")}`;
}

export function minutesLabel(n: number, t: (k: string, v?: Record<string, string | number>) => string) {
  return n < 120 ? { value: String(n), unit: t("ui.min") } : { value: String(n / 60), unit: t("ui.hour") };
}

/** Lucide icon for a WMO weather code (Open-Meteo `weather_code`). */
function weatherEmoji(code?: number | null): string {
  if (code == null) return "🌤️";
  if (code <= 1) return "☀️";
  if (code === 2) return "⛅";
  if ((code >= 71 && code <= 77) || code === 85 || code === 86) return "❄️";
  if (code >= 95) return "⛈️";
  if (code >= 51) return "🌧️";
  if (code >= 45 && code <= 48) return "🌫️";
  return "☁️";
}

export function WeatherPills({ weather }: { weather?: Weather }) {
  const t = useT();
  if (!weather?.available) return null;
  const harsh = weather.comfort?.applies ? weather.comfort.factors : [];
  return (
    <div className="weather-pills">
      <a
        className="pill-btn"
        href={weather.source_url}
        target="_blank"
        rel="noreferrer"
        title={[weather.note, ...harsh.map((f) => comfortLabel(f, t))].filter(Boolean).join(" · ")}
        aria-label={t("weather.now", { t: weather.temperature_c ?? "", w: weather.wind_kmh ?? "" })}
      >
        <Emo e={weatherEmoji(weather.weather_code)} />
        <b>
          {(weather.temperature_c ?? 0) > 0 ? "+" : ""}
          {Math.round(weather.temperature_c ?? 0)}°
        </b>
        <span className="muted">
          <Emo e="💨" /> {Math.round(weather.wind_kmh ?? 0)}
        </span>
      </a>
      {harsh.length > 0 && <span className="pill-btn warn">{comfortLabel(harsh[0], t)}</span>}
    </div>
  );
}

export function Planner({ walk, onStartPicker, onGo }: { walk: Walk; onStartPicker: () => void; onGo: () => void }) {
  const t = useT();
  const { lang } = usePrefs();
  const f = walk.filters;
  const [text, setText] = useState("");
  const [wishes, setWishes] = useState<string[]>([]);
  const draft = useRef("");

  const compose = (said = text) =>
    [said.trim(), ...wishes.map((k) => t("ui.wishq." + k))].filter(Boolean).join(", ") || t("ui.defaultQuery");

  const go = (query = compose()) => {
    if (walk.busy) return;
    stopSpeaking();
    onGo();
    walk.chat.ask(query, true);
  };

  const mic = useDictation(
    lang,
    (heard) => setText(draft.current ? draft.current + " " + heard : heard),
    (heard) => {
      const said = draft.current ? draft.current + " " + heard : heard;
      setText(said);
      go(compose(said));
    },
  );

  const toggleWish = (key: string) => setWishes((w) => (w.includes(key) ? w.filter((x) => x !== key) : [...w, key]));
  const loop = f.walkMode === "loop";
  const end = endClock(f.when, f.minutes);
  const landmarkEmoji = (f.landmarkKey && LANDMARK_EMOJI[f.landmarkKey]) || "📍";

  return (
    <div className="screen planner">
      <div className="hello-row">
        <span className="hello">{t("ui.now", { time: endClock("", 0) })}</span>
        <WeatherPills weather={walk.weather} />
      </div>
      <h1 className="screen-title">{t("ui.howMuchTime")}</h1>

      <div className="segmented time-seg" role="radiogroup" aria-label={t("filters.time")}>
        {MINUTES.map((n) => {
          const l = minutesLabel(n, t);
          return (
            <button key={n} role="radio" aria-checked={f.minutes === n} onClick={() => f.setMinutes(n)}>
              <b>{l.value}</b>
              <small>{l.unit}</small>
            </button>
          );
        })}
      </div>

      <div className="segmented mode-seg" role="radiogroup" aria-label={t("ui.mode")}>
        <button role="radio" aria-checked={loop} onClick={() => f.setWalkMode("loop")}>
          <Icon name="repeat" /> {t("ui.mode.loop")}
        </button>
        <button role="radio" aria-checked={!loop} onClick={() => f.setWalkMode("oneway")}>
          <Icon name="flag" /> {t("ui.mode.oneway")}
        </button>
      </div>

      <form
        className="ask-field"
        onSubmit={(e) => {
          e.preventDefault();
          go();
        }}
      >
        <Icon name="search" />
        <label className="sr-only" htmlFor="walk-ask">
          {t("ui.askLabel")}
        </label>
        <input
          id="walk-ask"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={t("ui.askPlaceholder")}
          maxLength={1500}
          autoComplete="off"
        />
        {canListen() && (
          <button
            type="button"
            className={"mic-btn" + (mic.listening ? " listening" : "")}
            aria-pressed={mic.listening}
            aria-label={mic.listening ? t("chat.voiceStop") : t("chat.voiceStart")}
            title={mic.listening ? t("chat.voiceStop") : t("chat.voiceStart")}
            onClick={() => {
              if (mic.listening) return mic.stop();
              stopSpeaking();
              draft.current = text.trim();
              mic.start();
            }}
          >
            <Icon name="mic" />
          </button>
        )}
      </form>
      {mic.listening && (
        <p className="hint live" role="status">
          {t("chat.listening")}
        </p>
      )}

      <div className="wish-chips" role="group" aria-label={t("ui.wishes")}>
        {WISHES.map((w, i) => (
          <button
            key={w.key}
            className="wish-chip"
            aria-pressed={wishes.includes(w.key)}
            style={{ animationDelay: `${i * 30}ms` }}
            onClick={() => toggleWish(w.key)}
          >
            <span className="wish-emoji">
              <Emo e={w.emoji} />
            </span>
            {t("ui.wish." + w.key)}
          </button>
        ))}
      </div>

      <button className="origin-card" onClick={onStartPicker}>
        <span className="origin-icon">
          <Emo e={landmarkEmoji} />
        </span>
        <span className="origin-text">
          <small>{t("ui.from")}</small>
          <strong>{f.originName}</strong>
          <span>{f.picking ? t("filters.picking") : t("ui.fromHint")}</span>
        </span>
        <Icon name="chevron-right" />
      </button>

      <div className="row-actions">
        <button className="ghost-btn" onClick={f.locate}>
          <Icon name="locate" /> {t("ui.fromMe")}
        </button>
      </div>

      <details className="more-settings">
        <summary>
          <Icon name="sliders-horizontal" /> {t("ui.moreSettings")}
          <Icon name="chevron-down" className="chev" />
        </summary>
        <div className="settings-grid">
          {!loop && (
            <label className="field">
              <span>{t("filters.finish")}</span>
              <select value={f.finishKey} onChange={(e) => f.setFinishKey(e.target.value)}>
                <option value="">{t("filters.finishNone")}</option>
                {Object.entries(walk.meta?.landmarks || {})
                  .filter(([key]) => key !== f.landmarkKey)
                  .map(([key, p]) => (
                    <option key={key} value={key}>
                      {has("lm." + key) ? t("lm." + key) : p.name}
                    </option>
                  ))}
              </select>
            </label>
          )}
          <label className="field">
            <span>{t("filters.when")}</span>
            <input type="datetime-local" value={f.when} onChange={(e) => f.setWhen(e.target.value)} />
          </label>
          <label className="switch">
            <input type="checkbox" checked={walk.chat.miniRoute} onChange={(e) => walk.chat.setMiniRoute(e.target.checked)} />
            <span>{t("ui.severalStops")}</span>
          </label>
          {walk.history.on && (
            <label className="switch">
              <input type="checkbox" checked={walk.history.newOnly} onChange={(e) => walk.history.setNewOnly(e.target.checked)} />
              <span>
                {t("ui.history.newOnly")}
                <small>{t("ui.history.newOnlyHint", { n: visitedIds(walk.history.entries).length })}</small>
              </span>
            </label>
          )}
          <label className="switch">
            <input type="checkbox" checked={f.openOnly} onChange={(e) => f.setOpenOnly(e.target.checked)} />
            <span>{t("filters.openOnly")}</span>
          </label>
          <label className="switch">
            <input type="checkbox" checked={f.noSteps} onChange={(e) => f.setNoSteps(e.target.checked)} />
            <span>{t("filters.noSteps")}</span>
          </label>
          <label className="switch">
            <input type="checkbox" checked={f.strict} onChange={(e) => f.setStrict(e.target.checked)} />
            <span>{t("filters.strict")}</span>
          </label>
          <label className="field">
            <span>{t("filters.snap", { m: f.snapRadius })}</span>
            <input
              type="range"
              min={walk.meta?.snap_radius_m?.min ?? 30}
              max={walk.meta?.snap_radius_m?.max ?? 300}
              step={10}
              value={f.snapRadius}
              onChange={(e) => f.setSnapRadius(Number(e.target.value))}
            />
          </label>
          <fieldset className="field-pair">
            <legend>{t("filters.flight")}</legend>
            <label className="field">
              <span>{t("filters.transfer")}</span>
              <input type="number" min="0" max="240" value={f.airportTransfer} onChange={(e) => f.setAirportTransfer(e.target.value)} />
            </label>
            <label className="field">
              <span>{t("filters.reserve")}</span>
              <input type="number" min="0" max="240" value={f.airportReserve} onChange={(e) => f.setAirportReserve(e.target.value)} />
            </label>
          </fieldset>
        </div>
      </details>

      <div className="cta-dock">
        <button className="cta" disabled={walk.busy} onClick={() => go()}>
          <span className="cta-main">
            <Icon name="sparkles" /> {t("ui.pickWalk")}
          </span>
          {end && <small>{t(loop ? "ui.backBy" : "ui.endBy", { at: end })}</small>}
        </button>
      </div>
    </div>
  );
}
