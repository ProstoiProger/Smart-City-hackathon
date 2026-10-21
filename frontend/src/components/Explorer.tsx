import type { FormEvent } from "react";
import { colors } from "../Map";
import { categoryLabel, money } from "../lib/format";
import { Icon } from "../lib/Icon";
import { has, locale, useT } from "../lib/i18n";
import { usePrefs } from "../lib/prefs";
import type { Walk } from "../useWalk";

const MINUTES = [30, 45, 60, 90, 120, 180, 240];
const CHIP_CATEGORIES = ["food_drink", "nature", "culture", "sightseeing", "children", "entertainment", "nightlife"];

function Filters({ walk }: { walk: Walk }) {
  const t = useT();
  const { meta, loading, setPanel, search } = walk;
  const f = walk.filters;
  const landmark = f.landmarkKey || "custom";
  return (
    <form
      className="filters"
      onSubmit={(e: FormEvent) => {
        e.preventDefault();
        search();
      }}
    >
      <label className="sr-only" htmlFor="search">
        {t("filters.search")}
      </label>
      <div className="search-row">
        <div className="search-field">
          <Icon name="search" />
          <input
            id="search"
            type="search"
            value={f.query}
            onChange={(e) => f.setQuery(e.target.value)}
            placeholder={t("filters.placeholder")}
            maxLength={1500}
          />
        </div>
        <button className="primary" disabled={loading}>
          {t("filters.find")}
        </button>
      </div>
      {/* Quick categories, one tap searches; tapping the active one clears it. */}
      <div className="chips" role="group" aria-label={t("filters.category")}>
        {CHIP_CATEGORIES.filter((code) => !meta || meta.categories[code]).map((code) => {
          const active = f.category === code;
          return (
            <button
              key={code}
              type="button"
              className="chip"
              aria-pressed={active}
              disabled={loading}
              onClick={() => {
                const next = active ? "" : code;
                f.setCategory(next);
                search(next);
              }}
            >
              <span className="chip-dot" style={{ background: colors[code] || "#536656" }} />
              {t("chip." + code)}
            </button>
          );
        })}
      </div>
      <div className="start-row">
        <div>
          <label htmlFor="origin">{t("filters.start")}</label>
          <select id="origin" value={landmark} onChange={(e) => f.setLandmark(e.target.value)}>
            {/* A picked point, geolocation or chat place; landmarks are listed once below. */}
            {landmark === "custom" && <option value="custom">{f.originName}</option>}
            {Object.entries(meta?.landmarks || {}).map(([key, p]) => (
              <option key={key} value={key}>
                {has("lm." + key) ? t("lm." + key) : p.name}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="minutes">{t("filters.time")}</label>
          <select id="minutes" value={f.minutes} onChange={(e) => f.setMinutes(+e.target.value)}>
            {MINUTES.map((n) => (
              <option key={n} value={n}>
                {t("filters.minutes", { n })}
              </option>
            ))}
          </select>
        </div>
      </div>
      <div className="finish-row">
        <label htmlFor="finish">{t("filters.finish")}</label>
        <select id="finish" value={f.finishKey} onChange={(e) => f.setFinishKey(e.target.value)} aria-describedby="finish-hint">
          <option value="">{t("filters.finishNone")}</option>
          <option value="loop">{t("filters.finishLoop")}</option>
          {Object.entries(meta?.landmarks || {})
            .filter(([key]) => key !== f.landmarkKey)
            .map(([key, p]) => (
              <option key={key} value={key}>
                {has("lm." + key) ? t("lm." + key) : p.name}
              </option>
            ))}
        </select>
        <small id="finish-hint">{t("filters.finishHint")}</small>
      </div>
      <div className="origin-actions">
        <button
          type="button"
          className="icon-button"
          aria-pressed={f.picking}
          onClick={() => {
            f.setPicking(!f.picking);
            setPanel("map");
          }}
        >
          <Icon name="map-pin" />
          {f.picking ? t("filters.picking") : t("filters.pickOnMap")}
        </button>
        <button type="button" className="icon-button" onClick={f.locate}>
          <Icon name="locate" />
          {t("filters.myLocation")}
        </button>
      </div>
      <details className="more-filters">
        <summary>{t("filters.conditions")}</summary>
        <details>
          <summary>{t("filters.flight")}</summary>
          <label htmlFor="airport-transfer">{t("filters.transfer")}</label>
          <input
            id="airport-transfer"
            type="number"
            min="0"
            max="240"
            value={f.airportTransfer}
            onChange={(e) => f.setAirportTransfer(e.target.value)}
          />
          <label htmlFor="airport-reserve">{t("filters.reserve")}</label>
          <input
            id="airport-reserve"
            type="number"
            min="0"
            max="240"
            value={f.airportReserve}
            onChange={(e) => f.setAirportReserve(e.target.value)}
          />
          <small>{t("filters.flightHint")}</small>
        </details>
        <label htmlFor="group-size">{t("filters.group")}</label>
        <select id="group-size" value={f.groupSize} onChange={(e) => f.setGroupSize(Number(e.target.value))}>
          {[1, 2, 3, 4, 5, 6].map((n) => (
            <option key={n} value={n}>
              {t("filters.groupOption", { n })}
            </option>
          ))}
        </select>
        <small>{t("filters.groupHint")}</small>
        <label htmlFor="when">{t("filters.when")}</label>
        <input id="when" type="datetime-local" value={f.when} onChange={(e) => f.setWhen(e.target.value)} />
        <label className="check">
          <input type="checkbox" checked={f.openOnly} onChange={(e) => f.setOpenOnly(e.target.checked)} />
          {t("filters.openOnly")}
        </label>
        <label className="check">
          <input type="checkbox" checked={f.noSteps} onChange={(e) => f.setNoSteps(e.target.checked)} />
          {t("filters.noSteps")}
        </label>
        <small>{t("filters.noStepsHint")}</small>
        <label htmlFor="snap-radius">{t("filters.snap", { m: f.snapRadius })}</label>
        <input
          id="snap-radius"
          type="range"
          min={meta?.snap_radius_m?.min ?? 30}
          max={meta?.snap_radius_m?.max ?? 300}
          step={10}
          value={f.snapRadius}
          onChange={(e) => f.setSnapRadius(Number(e.target.value))}
        />
        <small>{t("filters.snapHint")}</small>
        <label className="check">
          <input type="checkbox" checked={f.strict} onChange={(e) => f.setStrict(e.target.checked)} />
          {t("filters.strict")}
        </label>
      </details>
    </form>
  );
}

function Results({ walk }: { walk: Walk }) {
  const t = useT();
  const { lang } = usePrefs();
  const loc = locale(lang);
  const { items, loading, selected, selectPlace } = walk;
  return (
    <>
      <div className="results-heading">
        <h2>{t("nav.places")}</h2>
        <span aria-live="polite">{loading ? t("results.searching") : t("results.found", { n: items.length })}</span>
      </div>
      <div className="results" aria-busy={loading}>
        {!loading && !items.length ? (
          <div className="empty">
            <h3>{t("results.emptyTitle")}</h3>
            <p>{t("results.emptyHint")}</p>
          </div>
        ) : (
          items.map((p) => {
            return (
              <article key={p.poi_id} className={"place-row " + (selected?.poi_id === p.poi_id ? "selected" : "")}>
                <button className="place-main" onClick={() => selectPlace(p)}>
                  <span className="place-text">
                    <h3>{p.display_name}</h3>
                    <span className="place-kind">
                      <span className="category-dot" style={{ background: colors[p.category] || "#536656" }} />
                      {categoryLabel(p, t)}
                    </span>
                    {p.rating ? (
                      <span className="place-rating">
                        <Icon name="star-solid" />
                        <b>{p.rating}</b>
                        {p.ratings_count ? <span>{t("place.ratingCount", { n: p.ratings_count.toLocaleString(loc) })}</span> : null}
                      </span>
                    ) : (
                      <span className="place-rating none">{t("place.noRating")}</span>
                    )}
                    <span className="place-address">{p.address || t("place.noAddress")}</span>
                    <span className="place-price">{money(p, t, loc)}</span>
                  </span>
                  {p.route && (
                    <span className="place-walk">
                      <Icon name="route" />
                      {t("place.walkShort", { n: Math.ceil(p.route.duration_min) })}
                    </span>
                  )}
                </button>
              </article>
            );
          })
        )}
      </div>
    </>
  );
}

export function Explorer({ walk }: { walk: Walk }) {
  const t = useT();
  return (
    <aside className="explorer" aria-label={t("nav.places")}>
      <div className="explorer-head">
        <h1>{t("explorer.title")}</h1>
        <p>{t("explorer.subtitle")}</p>
      </div>
      <Filters walk={walk} />
      <Results walk={walk} />
    </aside>
  );
}
