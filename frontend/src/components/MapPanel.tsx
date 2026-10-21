import { useMemo, useState } from "react";
import type { Poi } from "../api";
import CityMap from "../Map";
import { Icon } from "../lib/Icon";
import { useT } from "../lib/i18n";
import { usePrefs } from "../lib/prefs";
import type { Walk } from "../useWalk";
import { ItinerarySheet, PlaceSheet } from "./PlaceSheet";

// One empty list for every render: a new [] each time would refit the map on every keystroke.
const NO_PLACES: Poi[] = [];

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
          : walk.meeting
            ? ((selected ?? items[0])?.meeting_routes ?? [])
            : selected?.route
              ? [selected.route]
              : [],
    [walk.tour, plan, selected, walk.meeting, items],
  );
  // The end of a walk at another place gets its own pin; a loop ends at the start pin.
  const finish = !walk.tour && plan?.finish && !plan.finish.loop ? plan.finish : undefined;
  return (
    <section className="map-panel" aria-label={t("nav.map")}>
      <CityMap
        // A route on screen shows its own stops, numbered; search results step aside.
        items={walk.tour || plan ? NO_PLACES : items}
        stops={walk.tour ? undefined : plan?.stops}
        selected={selected}
        origin={filters.origin}
        routes={routes}
        // After a re-plan the rest of the walk starts where the walker is, not at the start pin.
        routeStart={walk.trip && plan ? walk.trip.position : walk.meeting ? null : filters.origin}
        focusPoint={walk.trip && plan ? walk.trip.position : filters.origin}
        originFocus={walk.originFocus}
        people={walk.meeting ?? undefined}
        finish={finish && { point: [finish.latitude, finish.longitude], label: finish.label }}
        picking={filters.picking}
        onSelect={(p) => walk.selectPlace(p, false)}
        onOrigin={walk.pickOrigin}
        onTileError={() => setTileError(true)}
        labels={{ aria: t("map.aria"), start: t("map.start"), startName: filters.originName, finish: t("map.finish"), recenter: t("map.recenter") }}
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
