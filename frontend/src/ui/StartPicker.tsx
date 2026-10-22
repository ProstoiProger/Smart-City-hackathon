import { Emo } from "../lib/Emo";
import { Icon } from "../lib/Icon";
import { LANDMARK_EMOJI } from "../lib/emoji";
import { has, useT } from "../lib/i18n";
import type { Walk } from "../useWalk";

export function StartPicker({ walk, onDone }: { walk: Walk; onDone: () => void }) {
  const t = useT();
  const f = walk.filters;
  return (
    <div className="screen start-picker">
      <div className="screen-top">
        <button
          className="back-btn"
          onClick={() => {
            f.setPicking(false);
            onDone();
          }}
        >
          <Icon name="arrow-left" /> {t("ui.back")}
        </button>
      </div>
      <h1 className="screen-title">{t("ui.whereFrom")}</h1>
      <div className="choice-list">
        <button
          className="choice"
          onClick={() => {
            f.locate();
            onDone();
          }}
        >
          <span className="choice-icon">
            <Emo e="📍" />
          </span>
          <span>
            <strong>{t("filters.myLocation")}</strong>
            <small>{t("ui.myLocationHint")}</small>
          </span>
        </button>
        <button className={"choice" + (f.picking ? " on" : "")} aria-pressed={f.picking} onClick={() => f.setPicking(!f.picking)}>
          <span className="choice-icon">
            <Emo e="🎯" />
          </span>
          <span>
            <strong>{f.picking ? t("filters.picking") : t("filters.pickOnMap")}</strong>
            <small>{t("ui.pickHint")}</small>
          </span>
        </button>
      </div>
      <p className="privacy-note">{t("ui.privacyStart")}</p>
      <h2 className="section-title">{t("ui.popular")}</h2>
      <div className="landmark-grid">
        {Object.entries(walk.meta?.landmarks || {}).map(([key, lm], i) => (
          <button
            key={key}
            className={"landmark" + (f.landmarkKey === key ? " on" : "")}
            aria-pressed={f.landmarkKey === key}
            style={{ animationDelay: `${i * 40}ms` }}
            onClick={() => {
              f.setLandmark(key);
              onDone();
            }}
          >
            <span className="landmark-emoji">
              <Emo e={LANDMARK_EMOJI[key] ?? "📍"} />
            </span>
            <span>{has("lm." + key) ? t("lm." + key) : lm.name}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
