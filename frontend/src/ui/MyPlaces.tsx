import { useState } from "react";
import { categoryLabel } from "../lib/format";
import { Emo } from "../lib/Emo";
import { categoryColor, LANDMARK_EMOJI, placeEmoji } from "../lib/emoji";
import { visitedIds } from "../lib/history";
import type { HistoryEntry } from "../lib/history";
import { Icon } from "../lib/Icon";
import { locale, useT } from "../lib/i18n";
import { usePrefs } from "../lib/prefs";
import { refOf, type SavedPlace } from "../lib/saved";
import type { Walk } from "../useWalk";
import { startName } from "./History";

type Filter = "all" | "want" | "fav";

/** "Мои места": places to go and favourites, and saved walks; all of it in this browser only. */
export function MyPlaces({ walk, onBack, onRepeat }: { walk: Walk; onBack: () => void; onRepeat: (e: HistoryEntry) => void }) {
  const t = useT();
  const { lang } = usePrefs();
  const s = walk.saved;
  const [part, setPart] = useState<"places" | "walks">("places");
  const [filter, setFilter] = useState<Filter>("all");
  const seen = new Set(visitedIds(walk.history.entries));
  const places = s.places.filter((p) => (filter === "all" || p[filter]) && !(s.unseen && seen.has(p.id)));
  const day = (iso: string) => new Date(iso + "T12:00").toLocaleDateString(locale(lang), { day: "numeric", month: "long" });
  // Kind labels come from the category code; the stored place carries no server label.
  const kind = (p: SavedPlace) => categoryLabel({ category: p.category, category_label: "" }, t);
  return (
    <div className="screen my-places">
      <div className="screen-top">
        <button className="back-btn" onClick={onBack}>
          <Icon name="arrow-left" /> {t("ui.back")}
        </button>
      </div>
      <h1 className="screen-title with-icon">
        <Icon name="heart" /> {t("ui.saved.title")}
      </h1>

      <div className="part-tabs" role="tablist" aria-label={t("ui.saved.title")}>
        <button role="tab" aria-selected={part === "places"} onClick={() => setPart("places")}>
          {t("ui.saved.places")} <span className="count">{s.places.length}</span>
        </button>
        <button role="tab" aria-selected={part === "walks"} onClick={() => setPart("walks")}>
          {t("ui.saved.walks")} <span className="count">{s.walks.length}</span>
        </button>
      </div>

      {part === "places" ? (
        <>
          <div className="filter-pills" role="radiogroup" aria-label={t("ui.saved.filter")}>
            {(["all", "want", "fav"] as Filter[]).map((k) => (
              <button key={k} role="radio" aria-checked={filter === k} onClick={() => setFilter(k)}>
                {t("ui.saved.f." + k)}
              </button>
            ))}
          </div>
          <div className="settings-list">
            <label className="setting">
              <Icon name="map" />
              <span>{t("ui.saved.onMap")}</span>
              <input type="checkbox" className="toggle-input" checked={s.onMap} onChange={(e) => s.setOnMap(e.target.checked)} />
            </label>
            <label className="setting">
              <Icon name="search" />
              <span>
                {t("ui.saved.unseen")}
                <small>{t("ui.saved.unseenHint")}</small>
              </span>
              <input type="checkbox" className="toggle-input" checked={s.unseen} onChange={(e) => s.setUnseen(e.target.checked)} />
            </label>
          </div>

          {!places.length ? (
            <div className="empty-big">
              <span className="empty-icon">
                <Emo e={filter === "want" ? "🔖" : "💖"} />
              </span>
              <strong>{t(s.places.length ? "ui.saved.emptyFilter" : "ui.saved.empty")}</strong>
              <p>{t("ui.saved.emptyHint")}</p>
            </div>
          ) : (
            <ul className="saved-list">
              {places.map((p, i) => (
                <li key={p.id} className="saved-item" style={{ animationDelay: `${Math.min(i, 10) * 40}ms` }}>
                  <button className="saved-open" onClick={() => s.open(p.id)}>
                    <span className="emoji-tile" style={{ ["--cat" as string]: categoryColor(p.category) }}>
                      <Emo e={placeEmoji(p)} />
                    </span>
                    <span className="saved-body">
                      <strong>{p.name}</strong>
                      <small>
                        {kind(p)} · {day(p.date)}
                        {seen.has(p.id) ? " · " + t("ui.beenHere") : ""}
                      </small>
                    </span>
                  </button>
                  <span className="saved-marks">
                    <button
                      className={"mark-btn want" + (p.want ? " on" : "")}
                      aria-pressed={p.want}
                      aria-label={t("ui.saved.want") + ": " + p.name}
                      title={t("ui.saved.want")}
                      onClick={() => s.toggle(refOf(p), "want")}
                    >
                      <Icon name="bookmark" />
                    </button>
                    <button
                      className={"mark-btn fav" + (p.fav ? " on" : "")}
                      aria-pressed={p.fav}
                      aria-label={t("ui.saved.fav") + ": " + p.name}
                      title={t("ui.saved.fav")}
                      onClick={() => s.toggle(refOf(p), "fav")}
                    >
                      <Icon name="heart" />
                    </button>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </>
      ) : !s.walks.length ? (
        <div className="empty-big">
          <span className="empty-icon">
            <Emo e="🗺️" />
          </span>
          <strong>{t("ui.saved.noWalks")}</strong>
          <p>{t("ui.saved.noWalksHint")}</p>
        </div>
      ) : (
        <ol className="history-list">
          {s.walks.map((e, i) => (
            <li key={e.id} className="history-item" style={{ animationDelay: `${Math.min(i, 8) * 50}ms` }}>
              <div className="history-head">
                <span className="history-when">
                  <Emo e={e.start.key ? (LANDMARK_EMOJI[e.start.key] ?? "📍") : "📍"} />
                  <span>
                    <strong>{e.wish || t("ui.saved.walkUntitled")}</strong>
                    <small>
                      <Icon name={e.mode === "loop" ? "repeat" : "flag"} /> {t("filters.minutes", { n: e.minutes })} · {startName(e.start, t)}
                    </small>
                  </span>
                </span>
                <button className="round-btn small" aria-label={t("ui.saved.removeWalk")} title={t("ui.saved.removeWalk")} onClick={() => s.removeWalk(e.id)}>
                  <Icon name="x" />
                </button>
              </div>
              <ul className="history-places">
                {e.places.map((p) => (
                  <li key={p.id}>
                    <button className="history-place" onClick={() => s.open(p.id)} style={{ ["--cat" as string]: categoryColor(p.category) }}>
                      <Emo e={placeEmoji(p)} />
                      <span>{p.name.split(",")[0]}</span>
                    </button>
                  </li>
                ))}
              </ul>
              <button className="soft-btn" disabled={walk.busy} onClick={() => onRepeat(e)}>
                <Icon name="rotate-ccw" /> {t("ui.history.repeat")}
              </button>
            </li>
          ))}
        </ol>
      )}
      <p className="privacy-note">
        <Emo e="🔒" /> {t("ui.saved.privacy")}
      </p>
    </div>
  );
}
