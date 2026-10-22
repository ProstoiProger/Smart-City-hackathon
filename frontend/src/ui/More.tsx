import { useState } from "react";
import { AfishaPanel } from "../components/Overlays";
import { ToursPanel } from "../components/ToursPanel";
import { Emo } from "../lib/Emo";
import { Icon } from "../lib/Icon";
import { locale, useT } from "../lib/i18n";
import { usePrefs } from "../lib/prefs";
import { canSpeak, stopSpeaking } from "../lib/voice";
import type { Walk } from "../useWalk";

/** The city around the walk: events, guided walks, the gap map and the settings. */
export function More({
  walk,
  onCity,
  spoken,
  setSpoken,
}: {
  walk: Walk;
  onCity: () => void;
  spoken: boolean;
  setSpoken: (v: boolean) => void;
}) {
  const t = useT();
  const { theme, toggleTheme, lang } = usePrefs();
  const [tours, setTours] = useState(!!walk.tour);
  if (walk.afishaState.afisha !== null)
    return (
      <div className="screen embedded">
        <AfishaPanel walk={walk} />
      </div>
    );
  if (tours)
    return (
      <div className="screen embedded">
        <ToursPanel walk={walk} onClose={() => setTours(false)} />
      </div>
    );
  const tiles = [
    { key: "afisha", emoji: "🎟️", onClick: walk.afishaState.openAfisha },
    { key: "tours", emoji: "🌇", onClick: () => setTours(true) },
    { key: "gaps", emoji: "👀", onClick: onCity },
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
