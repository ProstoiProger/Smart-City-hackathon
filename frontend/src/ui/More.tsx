import { AfishaPanel } from "../components/Overlays";
import { ToursPanel } from "../components/ToursPanel";
import type { HistoryEntry } from "../lib/history";
import { History } from "./History";
import { MyPlaces } from "./MyPlaces";
import { Emo } from "../lib/Emo";
import { Icon } from "../lib/Icon";
import { locale, useT } from "../lib/i18n";
import { usePrefs } from "../lib/prefs";
import { canSpeak, stopSpeaking } from "../lib/voice";
import type { Walk } from "../useWalk";

export type MoreView = "history" | "saved" | "tours" | null;

/** The city around the walk: events, guided walks, the gap map and the settings. */
export function More({
  walk,
  onCity,
  onRepeat,
  view,
  setView,
  spoken,
  setSpoken,
}: {
  walk: Walk;
  onCity: () => void;
  onRepeat: (e: HistoryEntry) => void;
  /** The open sub-screen; kept by the app so a place opened from a list returns to it. */
  view: MoreView;
  setView: (v: MoreView) => void;
  spoken: boolean;
  setSpoken: (v: boolean) => void;
}) {
  const t = useT();
  const { theme, toggleTheme, lang, lowVision, setLowVision } = usePrefs();
  const back = () => setView(null);
  if (view === "history") return <History walk={walk} onBack={back} onRepeat={onRepeat} />;
  if (view === "saved") return <MyPlaces walk={walk} onBack={back} onRepeat={onRepeat} />;
  if (walk.afishaState.afisha !== null)
    return (
      <div className="screen embedded">
        <AfishaPanel walk={walk} />
      </div>
    );
  if (view === "tours" || walk.tour)
    return (
      <div className="screen embedded">
        <ToursPanel walk={walk} onClose={back} />
      </div>
    );
  const tiles = [
    { key: "afisha", emoji: "🎟️", onClick: walk.afishaState.openAfisha },
    { key: "tours", emoji: "🌇", onClick: () => setView("tours") },
    { key: "gaps", emoji: "👀", onClick: onCity },
    { key: "saved", emoji: "💖", onClick: () => setView("saved") },
    { key: "history", emoji: "📚", onClick: () => setView("history") },
  ];
  return (
    <div className="screen more">
      <h1 className="screen-title">{t("ui.moreTitle")}</h1>
      <p className="screen-sub">{t("ui.moreSub")}</p>
      <div className="tile-grid">
        {tiles.map((tile, i) => (
          <button key={tile.key} className="tile" style={{ animationDelay: `${i * 60}ms` }} onClick={tile.onClick}>
            <span className="tile-emoji">
              <Emo e={tile.emoji} />
            </span>
            <strong>{t("ui.tile." + tile.key)}</strong>
            <small>{t("ui.tile." + tile.key + "Sub")}</small>
          </button>
        ))}
      </div>

      <h2 className="section-title">{t("ui.settings")}</h2>
      <div className="settings-list">
        <button className="setting" onClick={() => setLowVision({ on: !lowVision.on })} aria-pressed={lowVision.on}>
          <Emo e="👀" />
          <span>{t("lv.title")}</span>
          <i className={"toggle" + (lowVision.on ? " on" : "")} aria-hidden="true" />
        </button>
        <button className="setting" onClick={toggleTheme} aria-pressed={theme === "dark"}>
          <Emo e={theme === "dark" ? "🌛" : "☀️"} />
          <span>{t("ui.darkTheme")}</span>
          <i className={"toggle" + (theme === "dark" ? " on" : "")} aria-hidden="true" />
        </button>
        {canSpeak() && (
          <button
            className="setting"
            aria-pressed={spoken}
            onClick={() => {
              if (spoken) stopSpeaking();
              setSpoken(!spoken);
            }}
          >
            <Emo e="📣" />
            <span>{t("ui.voiceReplies")}</span>
            <i className={"toggle" + (spoken ? " on" : "")} aria-hidden="true" />
          </button>
        )}
      </div>

      <h2 className="section-title">{t("ui.about")}</h2>
      <div className="about-card">
        {walk.meta && (
          <p>
            <Emo e="📦" /> {t("ui.aboutData", { n: walk.meta.pois.toLocaleString(locale(lang)), date: walk.meta.dataset_date })}
          </p>
        )}
        <p>
          <Emo e="🔒" /> {t("chat.privacy")}
        </p>
        <p>
          <Emo e="🗺️" /> {t("ui.mapCredit")}
        </p>
        <a className="link-btn" href="/docs" target="_blank" rel="noreferrer">
          API <Icon name="external-link" />
        </a>
      </div>
    </div>
  );
}
