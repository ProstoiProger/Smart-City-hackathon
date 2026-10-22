import { useEffect } from "react";
import type { Poi } from "../api";
import { categoryEmoji } from "../lib/emoji";
import { Emo } from "../lib/Emo";
import { Icon } from "../lib/Icon";
import { useT } from "../lib/i18n";
import type { Walk } from "../useWalk";
import { PlaceRow } from "./PlaceCard";

const CATEGORIES = ["food_drink", "nature", "culture", "sightseeing", "children", "entertainment", "nightlife", "quiet_spaces", "sport", "shopping"];

/** Places around the start: a text search and one-tap categories, sorted by the server. */
export function Nearby({
  walk,
  onOpen,
  hoverId,
  setHover,
}: {
  walk: Walk;
  onOpen: (p: Poi) => void;
  hoverId: string | null;
  setHover: (id: string | null) => void;
}) {
  const t = useT();
  const f = walk.filters;
  const items = walk.itemsSource === "search" ? walk.items : [];
  // After an answer of the assistant the list holds its places: search again around the start.
  useEffect(() => {
    if (walk.itemsSource !== "search" && !walk.loading) walk.search();
    // Only when the tab opens.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return (
    <div className="screen nearby">
      <h1 className="screen-title">{t("ui.nearbyTitle")}</h1>
      <p className="screen-sub">
        <Icon name="map-pin" /> {t("ui.startAt", { name: f.originName })} · {t("filters.minutes", { n: f.minutes })}
      </p>
      <form
        className="ask-field"
        onSubmit={(e) => {
          e.preventDefault();
          walk.search();
        }}
      >
        <Icon name="search" />
        <label className="sr-only" htmlFor="search">
          {t("filters.search")}
        </label>
        <input id="search" type="search" value={f.query} onChange={(e) => f.setQuery(e.target.value)} placeholder={t("filters.placeholder")} maxLength={1500} />
        <button className="send-btn" disabled={walk.loading} aria-label={t("filters.find")}>
          <Icon name="arrow-up-right" />
        </button>
      </form>
      <div className="wish-chips" role="group" aria-label={t("filters.category")}>
        {CATEGORIES.filter((c) => !walk.meta || walk.meta.categories[c]).map((code) => {
          const active = f.category === code;
          return (
            <button
              key={code}
              className="wish-chip"
              aria-pressed={active}
              disabled={walk.loading}
              onClick={() => {
                const next = active ? "" : code;
                f.setCategory(next);
                walk.search(next);
              }}
            >
              <span className="wish-emoji">
                <Emo e={categoryEmoji(code)} />
              </span>
              {t("chip." + code)}
            </button>
          );
        })}
      </div>
      <div className="list-head">
        <span aria-live="polite">{walk.loading ? t("results.searching") : t("results.found", { n: items.length })}</span>
      </div>
      <div className="place-list" aria-busy={walk.loading}>
        {items.map((p, i) => (
              <PlaceRow
                key={p.poi_id}
                p={p}
                index={i}
                active={hoverId === p.poi_id || walk.selected?.poi_id === p.poi_id}
                onOpen={() => onOpen(p)}
                onHover={(on) => setHover(on ? p.poi_id : null)}
              />
        ))}
        {!walk.loading && !items.length && (
          <div className="empty-note">
            <strong>{t("results.emptyTitle")}</strong>
            <p>{t("results.emptyHint")}</p>
          </div>
        )}
      </div>
    </div>
  );
}
