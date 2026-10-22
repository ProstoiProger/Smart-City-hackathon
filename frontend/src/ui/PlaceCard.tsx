import type { Poi } from "../api";
import { categoryLabel, hoursLabel } from "../lib/format";
import { Emo } from "../lib/Emo";
import { Icon } from "../lib/Icon";
import { categoryColor, placeEmoji } from "../lib/emoji";
import { locale, useT, type T } from "../lib/i18n";
import { usePrefs } from "../lib/prefs";
import { Ring, type Segment } from "./Ring";

export const shortName = (name: string) => name.split(",")[0];

export const HOURS_TONE: Record<string, string> = {
  open_by_schedule: "ok",
  closed_by_schedule: "bad",
  closed_reported: "bad",
};

/** Way there, the visit, the way back (round trip only) and the time left of the budget. */
export function budgetSegments(p: Poi, minutes: number, loop: boolean, t: T): Segment[] {
  const there = p.route?.duration_min ?? 0;
  const visit = p.suggested_visit_duration_min;
  const back = loop ? there : 0;
  return [
    { key: "there", value: there, label: t("ui.ring.there") },
    { key: "visit", value: visit, label: t("ui.ring.visit") },
    ...(loop ? [{ key: "back", value: back, label: t("ui.ring.back") }] : []),
    { key: "reserve", value: Math.max(0, minutes - there - visit - back), label: t("ui.ring.reserve") },
  ];
}

export function Emoji({ p, size = "md" }: { p: Poi; size?: "sm" | "md" | "lg" }) {
  return (
    <span className={"emoji-tile " + size} style={{ ["--cat" as string]: categoryColor(p.category) }} aria-hidden="true">
      <Emo e={placeEmoji(p)} />
    </span>
  );
}

export function HoursBadge({ p }: { p: Poi }) {
  const t = useT();
  return (
    <span className={"hours-badge " + (HOURS_TONE[p.hours_status.status] || "unknown")} title={hoursLabel(p, t)}>
      <i aria-hidden="true" />
      {t("hoursShort." + p.hours_status.status)}
    </span>
  );
}

/** One recommendation: number, emoji, what it is, how far, and the time budget ring. */
export function OptionCard({
  p,
  index,
  minutes,
  loop,
  active,
  onOpen,
  onHover,
}: {
  p: Poi;
  index: number;
  minutes: number;
  loop: boolean;
  active: boolean;
  onOpen: () => void;
  onHover: (on: boolean) => void;
}) {
  const t = useT();
  const segments = budgetSegments(p, minutes, loop, t);
  const used = segments.filter((s) => s.key !== "reserve").reduce((a, s) => a + s.value, 0);
  const why = p.why || p.reasons?.join(" · ");
  return (
    <button
      className={"option-card" + (active ? " active" : "")}
      style={{ animationDelay: `${index * 70}ms` }}
      onClick={onOpen}
      onMouseEnter={() => onHover(true)}
      onMouseLeave={() => onHover(false)}
      onFocus={() => onHover(true)}
      onBlur={() => onHover(false)}
    >
      <span className="option-num">{index + 1}</span>
      <Emoji p={p} size="lg" />
      <span className="option-body">
        <strong>{p.display_name}</strong>
        <span className="option-kind">{categoryLabel(p, t)}</span>
        <span className="option-meta">
          {p.route ? (
            <span>
              <Icon name="footprints" /> {t("place.walkShort", { n: Math.max(1, Math.ceil(p.route.duration_min)) })}
            </span>
          ) : null}
          <HoursBadge p={p} />
        </span>
        {why && <span className="option-why">{why}</span>}
      </span>
      <span className="option-ring">
        <Ring segments={segments} total={minutes} size={78} center={Math.round(used)} unit={t("ui.min")} />
      </span>
    </button>
  );
}

/** A row of the "Рядом" list. */
export function PlaceRow({
  p,
  index,
  active,
  onOpen,
  onHover,
}: {
  p: Poi;
  index: number;
  active: boolean;
  onOpen: () => void;
  onHover: (on: boolean) => void;
}) {
  const t = useT();
  const { lang } = usePrefs();
  return (
    <button
      className={"place-row" + (active ? " active" : "")}
      style={{ animationDelay: `${Math.min(index, 12) * 35}ms` }}
      onClick={onOpen}
      onMouseEnter={() => onHover(true)}
      onMouseLeave={() => onHover(false)}
      onFocus={() => onHover(true)}
      onBlur={() => onHover(false)}
    >
      <Emoji p={p} />
      <span className="place-row-body">
        <strong>{p.display_name}</strong>
        <span className="option-kind">
          {categoryLabel(p, t)}
          {p.rating ? (
            <>
              {" · "}
              <span className="rating">
                <Emo e="⭐" /> {p.rating}
                {p.ratings_count ? <small> ({p.ratings_count.toLocaleString(locale(lang))})</small> : null}
              </span>
            </>
          ) : null}
        </span>
        <span className="option-meta">
          <HoursBadge p={p} />
        </span>
      </span>
      {p.route && (
        <span className="walk-pill">
          <Icon name="footprints" />
          {t("place.walkShort", { n: Math.max(1, Math.ceil(p.route.duration_min)) })}
        </span>
      )}
    </button>
  );
}
