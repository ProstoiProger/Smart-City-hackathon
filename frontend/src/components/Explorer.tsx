import type { FormEvent } from "react";
import { colors } from "../Map";
import { categoryLabel, money } from "../lib/format";
import { Icon } from "../lib/Icon";
import { locale, useT } from "../lib/i18n";
import { usePrefs } from "../lib/prefs";
import type { Walk } from "../useWalk";

const MINUTES = [30, 45, 60, 90, 120, 180, 240];

function Filters({ walk }: { walk: Walk }) {
  const t = useT();
  const { meta, loading, setPanel, search } = walk;
  const f = walk.filters;
  const landmark =
    Object.entries(meta?.landmarks || {}).find(([, p]) => p.lat === f.origin?.[0] && p.lon === f.origin?.[1])?.[0] ||
    "custom";
  return (
    <form
      className="filters"
      onSubmit={(e: FormEvent) => {
        e.preventDefault();
        search();
      }}
    >
      <label htmlFor="search">{t("filters.search")}</label>
      <div className="search-row">
        <input
          id="search"
          value={f.query}
          onChange={(e) => f.setQuery(e.target.value)}
          placeholder={t("filters.placeholder")}
          maxLength={1500}
        />
        <button className="primary icon-button" disabled={loading}>
          <Icon name="search" />
          {t("filters.find")}
        </button>
      </div>
      <div className="filter-row">
        <label className="sr-only" htmlFor="category">
          {t("filters.category")}
        </label>
        <select id="category" value={f.category} onChange={(e) => f.setCategory(e.target.value)}>
          <option value="">{t("filters.allCategories")}</option>
          {Object.entries(meta?.categories || {}).map(([code, label]) => (
            <option key={code} value={code}>
              {categoryLabel({ category: code, category_label: label }, t)}
            </option>
          ))}
        </select>
        <label className="sr-only" htmlFor="minutes">
          {t("filters.time")}
        </label>
        <select id="minutes" value={f.minutes} onChange={(e) => f.setMinutes(+e.target.value)}>
          {MINUTES.map((n) => (
            <option key={n} value={n}>
              {t("filters.minutes", { n })}
            </option>
          ))}
        </select>
      </div>
      <label htmlFor="origin">{t("filters.start")}</label>
      <select id="origin" value={landmark} onChange={(e) => f.setLandmark(e.target.value)}>
        <option value="custom">{f.originLabel}</option>
        {Object.entries(meta?.landmarks || {}).map(([key, p]) => (
          <option key={key} value={key}>
            {p.name}
          </option>
        ))}
      </select>
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
  const { compareIds, toggleCompare } = walk.compareState;
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
            const chosen = compareIds.includes(p.poi_id);
            return (
              <article key={p.poi_id} className={"place-row " + (selected?.poi_id === p.poi_id ? "selected" : "")}>
                <button className="place-main" onClick={() => selectPlace(p)}>
                  <span className="category-dot" style={{ background: colors[p.category] || "#536656" }} />
                  <span>
                    <span className="place-kind">{categoryLabel(p, t)}</span>
                    <h3>{p.display_name}</h3>
                    <p>{p.address || t("place.noAddress")}</p>
                    <div className="place-meta">
                      {p.route && <span>{t("place.walk", { n: Math.ceil(p.route.duration_min) })}</span>}
                      <span>
                        {p.rating
                          ? t("place.rating", {
                              r: p.rating,
                              n: p.ratings_count?.toLocaleString(loc) || t("place.ratingNoCount"),
                            })
                          : t("place.noRating")}
                      </span>
                    </div>
                  </span>
                </button>
                <div className="row-foot">
                  <small>{money(p, t, loc)}</small>
                  <button
                    className="text-button icon-button"
                    aria-pressed={chosen}
                    disabled={!chosen && compareIds.length >= 3}
                    onClick={() => toggleCompare(p)}
                  >
                    <Icon name={chosen ? "check" : "plus"} />
                    {chosen ? t("place.remove") : t("place.add")}
                  </button>
                </div>
              </article>
            );
          })
        )}
      </div>
    </>
  );
}

function SelectionBar({ walk }: { walk: Walk }) {
  const t = useT();
  const { compareIds, compare, clearCompare } = walk.compareState;
  if (!compareIds.length) return null;
  return (
    <div className="selection-bar">
      <span>{t("selection.count", { n: compareIds.length })}</span>
      <button className="icon-button" onClick={compare}>
        <Icon name="scale" />
        {t("selection.compare")}
      </button>
      <button className="primary icon-button" disabled={walk.busy} onClick={() => walk.buildPlan()}>
        <Icon name="route" />
        {t("selection.plan")}
      </button>
      <button className="icon-button" aria-label={t("selection.clear")} onClick={clearCompare}>
        <Icon name="x" />
      </button>
    </div>
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
      <SelectionBar walk={walk} />
    </aside>
  );
}
