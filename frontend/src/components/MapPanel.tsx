import { useState } from "react";
import CityMap from "../Map";
import { Icon } from "../lib/Icon";
import { useT } from "../lib/i18n";
import { usePrefs } from "../lib/prefs";
import type { Walk } from "../useWalk";
import { ItinerarySheet, PlaceSheet } from "./PlaceSheet";

export function MapPanel({ walk }: { walk: Walk }) {
  const t = useT();
  const { theme } = usePrefs();
  const [tileError, setTileError] = useState(false);
  const { items, selected, plan, filters } = walk;
  const routes = walk.tour ? [] : plan?.legs || (selected?.route ? [selected.route] : []);
  return (
    <section className="map-panel" aria-label={t("nav.map")}>
      <CityMap
        items={walk.tour ? [] : items}
        selected={selected}
        origin={filters.origin}
        routes={routes}
        picking={filters.picking}
        onSelect={(p) => walk.selectPlace(p, false)}
        onOrigin={walk.pickOrigin}
        onTileError={() => setTileError(true)}
        labels={{ aria: t("map.aria"), start: t("map.start"), startName: filters.originName }}
        theme={theme}
        tour={walk.tour}
        onTourStop={(i) => walk.tour && walk.setTour({ ...walk.tour, current: i })}
      />
      <div className="map-top">
        <span className="map-label">
          {filters.originName} <span>→</span> {t("filters.minutes", { n: filters.minutes })}
        </span>
        <button className="map-label icon-button" onClick={() => walk.selectPlace(undefined)}>
          <Icon name="x" />
          {t("map.clear")}
        </button>
      </div>
      {tileError && <div className="tile-error">{t("map.tileError")}</div>}
      {!selected && !plan && (
        <div className="map-note">
          {t("map.note")}
          <small>{t("map.noteHint")}</small>
        </div>
      )}
      {selected && <PlaceSheet walk={walk} p={selected} />}
      <ItinerarySheet walk={walk} />
    </section>
  );
}
