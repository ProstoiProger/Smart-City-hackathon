import { useEffect, useState, type ReactNode } from "react";
import { request, safeUrl, type Poi } from "../api";
import { categoryLabel, eventWhen, groupCost, hoursLabel, money, ruleLabel, ruleValue, tariff } from "../lib/format";
import { Icon } from "../lib/Icon";
import { locale, useT } from "../lib/i18n";
import { usePrefs } from "../lib/prefs";
import type { Walk } from "../useWalk";
import { Explanation } from "./Explanation";
import { PlaceQA } from "./PlaceQA";

function SourceLink({ url, children }: { url?: string; children?: ReactNode }) {
  const t = useT();
  const href = safeUrl(url);
  if (!href) return null;
  return (
    <a href={href} target="_blank" rel="noreferrer" className="icon-button">
      {children ?? t("detail.source")}
      <Icon name="external-link" />
    </a>
  );
}

const STATUS_TONE: Record<string, string> = {
  supported: "ok",
  single_mention: "neutral",
  mixed: "warn",
  contradicted: "bad",
};

function ReviewSignals({ p }: { p: Poi }) {
  const t = useT();
  const signals = Object.entries(p.review_signals || {});
  if (!signals.length) return null;
  return (
    <details open>
      <summary>{t("reviews.title")}</summary>
      <ul className="signals">
        {signals.map(([key, s]) => (
          <li key={key} className="signal">
            <div className="signal-head">
              <strong>{t("signal." + key)}</strong>
              <span className={"pill " + (STATUS_TONE[s.status] || "neutral")}>{t("signalStatus." + s.status)}</span>
              <small>{t("reviews.tally", { pos: s.positive, neg: s.negative + s.mixed })}</small>
            </div>
            {s.quotes.slice(0, 2).map((q) => (
              <figure key={q.review_id} className={"quote " + q.polarity}>
                <blockquote>{q.text}</blockquote>
                <figcaption>
                  {q.date?.slice(0, 10)} ·{" "}
                  <SourceLink url={`https://2gis.kz/astana/firm/${q.branch_id}/tab/reviews`}>{t("reviews.link")}</SourceLink>
                </figcaption>
              </figure>
            ))}
          </li>
        ))}
      </ul>
      <small>
        {t("reviews.footer")} {p.reviews_considered ? t("reviews.footerCount", { n: p.reviews_considered }) : ""}
      </small>
    </details>
  );
}

const DAYS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"];

/** "Пн–Пт 09:00–21:00 · Сб–Вс 10:00–20:00", or "Ежедневно …" when every day is the same. */
function Hours({ p }: { p: Poi }) {
  const t = useT();
  const byDay = p.opening_hours_by_day;
  if (!byDay) return <p className="pc-hours-text">{p.opening_hours || t("detail.noSchedule")}</p>;
  const text = (d: string) =>
    (byDay[d] || []).map(([a, b]) => `${a}–${b}`).join(", ") || t("hours.dayOff");
  const groups: { from: string; to: string; value: string }[] = [];
  for (const d of DAYS) {
    const value = text(d);
    const last = groups[groups.length - 1];
    if (last && last.value === value) last.to = d;
    else groups.push({ from: d, to: d, value });
  }
  if (groups.length === 1) return <p className="pc-hours-text">{t("hours.daily", { v: groups[0].value })}</p>;
  return (
    <dl className="pc-hours-table">
      {groups.map((g) => (
        <div key={g.from}>
          <dt>{t("day." + g.from) + (g.to !== g.from ? "–" + t("day." + g.to) : "")}</dt>
          <dd>{g.value}</dd>
        </div>
      ))}
    </dl>
  );
}

function restriction(value: unknown): string | null {
  if (typeof value === "string") return value === "yes" ? null : value; // OSM access=yes is public access
  if (value && typeof value === "object" && "description" in value) return String((value as { description: unknown }).description);
  return null;
}

function Amenities({ p }: { p: Poi }) {
  const t = useT();
  const rows: [string, boolean | null | undefined][] = [
    ["amen.wifi", p.wifi_available],
    ["amen.outlets", p.power_outlets],
    ["amen.quiet", p.quiet_place],
    ["amen.entrance", p.entrance_accessible],
    ["amen.ramp", p.ramps],
    ["amen.wheelchair", p.wheelchair_accessible],
    ["amen.booking", p.reservation_required ?? p.booking_required],
  ];
  const known = rows.filter(([, v]) => v === true || v === false);
  const rules = restriction(p.access_restrictions);
  const minAge = (p.age_restrictions as { min_age?: string | number } | null | undefined)?.min_age;
  const unknown = [
    ...rows.filter(([, v]) => v !== true && v !== false).map(([k]) => t(k + ".short")),
    ...(rules ? [] : [t("amen.rules.short")]),
    ...(minAge ? [] : [t("amen.age.short")]),
  ];
  return (
    <details open>
      <summary>{t("detail.hoursAmenities")}</summary>
      <Hours p={p} />
      {known.length > 0 && (
        <ul className="amenities">
          {known.map(([key, value]) => (
            <li key={key} className={value ? "yes" : "no"}>
              <Icon name={value ? "check" : "x"} />
              {t(key)}
              <span className="sr-only">: {value ? t("common.yes") : t("common.no")}</span>
            </li>
          ))}
        </ul>
      )}
      {rules && <p>{t("detail.rules", { v: rules })}</p>}
      {minAge && <p>{t("detail.age", { v: t("detail.ageMin", { n: minAge }) })}</p>}
      {unknown.length > 0 && <small className="pc-unknown">{t("amen.noData", { list: unknown.join(", ") })}</small>}
    </details>
  );
}

function Published({ p }: { p: Poi }) {
  const t = useT();
  const { lang } = usePrefs();
  return (
    <>
      {!!p.visit_rules?.constraints?.length && (
        <details>
          <summary>{t("rules.title")}</summary>
          <ul className="sources">
            {p.visit_rules.constraints.map((r, i) => (
              <li key={i}>
                {ruleLabel(r.field, t)}: {ruleValue(r.value, t)} <SourceLink url={r.source_url} />
              </li>
            ))}
          </ul>
          <small>{t("rules.note")}</small>
        </details>
      )}
      {!!p.children_facilities?.length && (
        <details>
          <summary>{t("kids.title")}</summary>
          <ul className="sources">
            {p.children_facilities.map((f, i) => (
              <li key={i}>
                {f.feature} <SourceLink url={f.source_url} />
              </li>
            ))}
          </ul>
          <small>{t("kids.note")}</small>
        </details>
      )}
      {!!p.pricing?.entries?.length && (
        <details>
          <summary>{t("prices.title")}</summary>
          <ul className="sources">
            {p.pricing.entries.map((e, i) => (
              <li key={i}>
                {tariff(e, t, locale(lang))} <SourceLink url={e.source_url} />
              </li>
            ))}
          </ul>
          <small>{t("prices.note")}</small>
        </details>
      )}
      {!!p.linked_venue_documents?.length && (
        <details>
          <summary>{t("docs.title")}</summary>
          <p>{t("docs.note")}</p>
          <ul className="sources">
            {p.linked_venue_documents.map((d) => (
              <li key={d.source_id}>
                <SourceLink url={d.url}>{d.title || t("docs.untitled")}</SourceLink>
              </li>
            ))}
          </ul>
        </details>
      )}
      {!!p.semantic_attributes?.length && (
        <details>
          <summary>{t("attrs.title")}</summary>
          <ul className="attr-chips">
            {p.semantic_attributes.slice(0, 25).map((a) => (
              <li key={a}>{a}</li>
            ))}
          </ul>
          <small>{t("attrs.note")}</small>
        </details>
      )}
    </>
  );
}

type Photo = { status: "loading" | "ok" | "none"; url?: string; source_url?: string };

/** Main 2GIS photo, requested only when this card opens. */
function usePhoto(poiId: string): [Photo, () => void] {
  const [photo, setPhoto] = useState<Photo>({ status: "loading" });
  useEffect(() => {
    let alive = true;
    setPhoto({ status: "loading" });
    request<{ available: boolean; url?: string; source_url?: string }>(`pois/${encodeURIComponent(poiId)}/photo`)
      .then((r) => alive && setPhoto(r.available && r.url ? { status: "ok", url: r.url, source_url: r.source_url } : { status: "none" }))
      .catch(() => alive && setPhoto({ status: "none" }));
    return () => {
      alive = false;
    };
  }, [poiId]);
  return [photo, () => setPhoto({ status: "none" })];
}

const HOURS_TONE: Record<string, string> = {
  open_by_schedule: "ok",
  closed_by_schedule: "bad",
  closed_reported: "bad",
};

export function PlaceSheet({ walk, p }: { walk: Walk; p: Poi }) {
  const t = useT();
  const { lang } = usePrefs();
  const loc = locale(lang);
  const [photo, dropPhoto] = usePhoto(p.poi_id);
  const [expanded, setExpanded] = useState(false);
  const close = (
    <button className="sheet-close" aria-label={t("detail.close")} onClick={() => walk.selectPlace(undefined)}>
      <Icon name="x" />
    </button>
  );
  const cost = groupCost(p, t, loc);
  return (
    <section className="detail-sheet place-card" aria-label={t("detail.region")}>
      {photo.status !== "none" && (
        <figure className={"pc-media " + photo.status}>
          {photo.status === "ok" && (
            <img src={photo.url} alt={t("photo.alt", { name: p.display_name })} loading="lazy" onError={dropPhoto} />
          )}
          {photo.status === "ok" && (
            <figcaption>
              <SourceLink url={photo.source_url}>{t("photo.credit")}</SourceLink>
            </figcaption>
          )}
          {close}
        </figure>
      )}
      <div className="pc-head">
        <span className="pc-kind">{categoryLabel(p, t)}</span>
        {photo.status === "none" && close}
      </div>
      <h2>{p.display_name}</h2>
      {p.address && <p className="pc-address">{p.address}</p>}
      <ul className="pc-chips">
        <li>
          <Icon name="route" />
          {p.route ? t("place.walk", { n: Math.ceil(p.route.duration_min) }) : t("detail.noRoute")}
        </li>
        <li>
          <Icon name="clock" />
          {t("chat.itemVisit", { visit: p.suggested_visit_duration_min })}
        </li>
        <li>{money(p, t, loc)}</li>
        {p.rating != null && (
          <li>
            <Icon name="star" />
            {p.rating}
            {p.ratings_count ? ` · ${p.ratings_count.toLocaleString(loc)}` : ""}
          </li>
        )}
        <li className={"pc-hours " + (HOURS_TONE[p.hours_status.status] || "unknown")} title={hoursLabel(p, t)}>
          {t("hoursShort." + p.hours_status.status)}
        </li>
      </ul>
      {(p.why || p.what_to_do) && (
        <div className="why-box">
          <Explanation p={p} />
        </div>
      )}
      {p.short_description && (
        <div className="pc-desc">
          <p className={expanded ? "" : "clamped"}>{p.short_description}</p>
          {p.short_description.length > 180 && (
            <button className="text-button" onClick={() => setExpanded(!expanded)}>
              {expanded ? t("detail.less") : t("detail.more")}
            </button>
          )}
          {p.description_type === "attribute_grounded_summary" && <small>{t("detail.groundedSummary")}</small>}
        </div>
      )}
      {(cost || !!p.events?.length) && (
        <div className="pc-extras">
          {cost && <p className="group-cost">{cost}</p>}
          {p.events?.map((e) => (
            <p key={e.event_id} className="event-meta">
              <Icon name="calendar-clock" /> {t("events.here", { name: e.name, when: eventWhen(e, t) })}{" "}
              <SourceLink url={e.source_url}>{t("events.source")}</SourceLink>
            </p>
          ))}
        </div>
      )}
      {!!p.warnings?.length && (
        <ul className="pc-alerts">
          {p.warnings.map((w) => (
            <li key={w} className="warning">
              <Icon name="info" />
              {w}
            </li>
          ))}
        </ul>
      )}
      <div className="pc-sections">
        <PlaceQA p={p} when={walk.filters.when} />
        <Amenities p={p} />
        <ReviewSignals p={p} />
        <Published p={p} />
        <details>
          <summary>{t("detail.sources")}</summary>
          <ul className="sources">
            {p.sources?.map((s, i) => (
              <li key={i}>
                {safeUrl(s.url) ? <SourceLink url={s.url}>{s.name || t("detail.source")}</SourceLink> : s.name}
                <small>{s.collected_at?.slice(0, 10)}</small>
              </li>
            ))}
          </ul>
          <small>{t("detail.snapshot", { date: walk.meta?.dataset_date ?? "" })}</small>
        </details>
      </div>
      <div className="detail-actions">
        <button className="primary icon-button" disabled={walk.busy} onClick={() => walk.buildPlan([p.poi_id])}>
          <Icon name="route" />
          {t("detail.routeHere")}
        </button>
        <SourceLink url={p.website}>{t("detail.website")}</SourceLink>
      </div>
    </section>
  );
}

export function ItinerarySheet({ walk }: { walk: Walk }) {
  const t = useT();
  const plan = walk.plan;
  if (!plan) return null;
  return (
    <section className="detail-sheet itinerary" aria-label={t("plan.region")}>
      <div className="sheet-top">
        <span>{plan.kind === "mini_route" ? t("plan.mini") : t("plan.yours")}</span>
        <button aria-label={t("detail.close")} onClick={() => walk.setPlan(undefined)}>
          <Icon name="x" />
        </button>
      </div>
      <h2>{plan.stops.length ? t("plan.total", { n: Math.ceil(plan.total_duration_min) }) : t("plan.notFound")}</h2>
      <ol>
        {plan.stops.map((p, i) => (
          <li key={p.poi_id}>
            <strong>{p.display_name}</strong>
            <span>
              {t("plan.leg", { walk: Math.ceil(plan.legs[i].duration_min), visit: p.suggested_visit_duration_min })}
            </span>
            <small>{hoursLabel(p, t)}</small>
          </li>
        ))}
      </ol>
      {plan.warnings.map((w) => (
        <p key={w} className="warning">
          {w}
        </p>
      ))}
      {plan.legs[0]?.warnings.map((w) => (
        <small key={w}>{w}</small>
      ))}
    </section>
  );
}
