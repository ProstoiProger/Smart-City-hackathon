import { useMemo, useState } from "react";
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
  // Memoized: a new array on every render would refit the map on every keystroke.
  const routes = useMemo(
    () =>
      walk.tour
        ? []
        : plan
          ? [...plan.legs, ...(plan.finish ? [plan.finish.leg] : [])]
          : selected?.route
            ? [selected.route]
            : [],
    [walk.tour, plan, selected],
  );
  // The end of a walk at another place gets its own pin; a loop ends at the start pin.
  const finish = !walk.tour && plan?.finish && !plan.finish.loop ? plan.finish : undefined;
  return (
    <section className="map-panel" aria-label={t("nav.map")}>
      <CityMap
        items={walk.tour ? [] : items}
        selected={selected}
        origin={filters.origin}
        routes={routes}
        // After a re-plan the rest of the walk starts where the walker is, not at the start pin.
        routeStart={walk.trip && plan ? walk.trip.position : filters.origin}
        finish={finish && { point: [finish.latitude, finish.longitude], label: finish.label }}
        picking={filters.picking}
        onSelect={(p) => walk.selectPlace(p, false)}
        onOrigin={walk.pickOrigin}
        onTileError={() => setTileError(true)}
        labels={{ aria: t("map.aria"), start: t("map.start"), startName: filters.originName, finish: t("map.finish") }}
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
