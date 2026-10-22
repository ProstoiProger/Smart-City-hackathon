import { useEffect, useState, type ReactNode } from "react";
import { request, safeUrl, type Poi } from "../api";
import { PlaceQA } from "../components/PlaceQA";
import { categoryLabel, eventWhen, groupCost, money, ruleLabel, ruleValue, tariff } from "../lib/format";
import { Emo } from "../lib/Emo";
import { Icon } from "../lib/Icon";
import { locale, useT } from "../lib/i18n";
import { usePrefs } from "../lib/prefs";
import type { Walk } from "../useWalk";
import { budgetSegments, Emoji, HoursBadge } from "./PlaceCard";
import { Ring, RingLegend } from "./Ring";

export function SourceLink({ url, children }: { url?: string; children?: ReactNode }) {
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


/** The place opened from a card or a pin: photo, time budget, why, questions, data and sources. */
export function PlaceDetail({ walk, p: place, onBack, onRoute }: { walk: Walk; p: Poi; onBack: () => void; onRoute: () => void }) {
  // A stop of the route has no walk of its own: its leg from the previous point stands in.
  const stopAt = walk.plan?.stops.findIndex((s) => s.poi_id === place.poi_id) ?? -1;
  const p = place.route || stopAt < 0 || !walk.plan?.legs[stopAt] ? place : { ...place, route: walk.plan.legs[stopAt] };
  const t = useT();
  const { lang } = usePrefs();
  const loc = locale(lang);
  const [photo, dropPhoto] = usePhoto(p.poi_id);
  const [loaded, setLoaded] = useState(false);
  const [zoom, setZoom] = useState(false);
  const [expanded, setExpanded] = useState(false);
  useEffect(() => {
    setLoaded(false);
    setZoom(false);
    setExpanded(false);
  }, [p.poi_id]);
  useEffect(() => {
    if (!zoom) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setZoom(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [zoom]);
  const minutes = walk.answer?.minutes ?? walk.filters.minutes;
  const loop = walk.filters.walkMode === "loop";
  const segments = p.route ? budgetSegments(p, minutes, loop, t) : [];
  const used = segments.filter((s) => s.key !== "reserve").reduce((a, s) => a + s.value, 0);
  const cost = groupCost(p, t, loc);
  const share = async () => {
    const text = [p.display_name, p.address].filter(Boolean).join(" — ");
    try {
      if (navigator.share) await navigator.share({ title: p.display_name, text });
      else await navigator.clipboard.writeText(text);
      walk.notify(t("ui.shared"));
    } catch {
      // The user closed the share sheet.
    }
  };
  return (
    <div className="screen place-detail" aria-label={t("detail.region")}>
      <div className="screen-top">
        <button className="back-btn" onClick={onBack}>
          <Icon name="arrow-left" /> {t("ui.back")}
        </button>
        <span className="spacer" />
        <button className="round-btn" onClick={share} aria-label={t("ui.share")} title={t("ui.share")}>
          <Icon name="share-2" />
        </button>
      </div>

      {photo.status !== "none" && (
        <figure className={"pd-photo " + photo.status + (loaded ? " loaded" : "")}>
          {photo.status === "ok" && <img className="pd-photo-bg" src={photo.url} alt="" aria-hidden="true" />}
          {photo.status === "ok" && (
            <button className="pd-photo-open" onClick={() => setZoom(true)} aria-label={t("photo.open")}>
              <img src={photo.url} alt={t("photo.alt", { name: p.display_name })} onLoad={() => setLoaded(true)} onError={dropPhoto} />
            </button>
          )}
          {photo.status === "ok" && (
            <figcaption>
              <SourceLink url={photo.source_url}>{t("photo.credit")}</SourceLink>
            </figcaption>
          )}
        </figure>
      )}
      {zoom && photo.status === "ok" && (
        <div className="photo-lightbox" role="dialog" aria-modal="true" aria-label={t("photo.alt", { name: p.display_name })} onClick={() => setZoom(false)}>
          <img src={photo.url} alt={t("photo.alt", { name: p.display_name })} />
          <button className="round-btn" aria-label={t("detail.close")} onClick={() => setZoom(false)}>
            <Icon name="x" />
          </button>
        </div>
      )}

      <div className="pd-head">
        <Emoji p={p} size="lg" />
        <div>
          <h1 className="screen-title">{p.display_name}</h1>
          <p className="option-kind">
            {categoryLabel(p, t)}
            {p.address ? " · " + p.address : ""}
          </p>
        </div>
      </div>
      <div className="pd-chips">
        <HoursBadge p={p} />
        {p.rating != null && (
          <span className="chip-stat">
            <Emo e="⭐" /> {p.rating}
            {p.ratings_count ? <small> · {p.ratings_count.toLocaleString(loc)}</small> : null}
          </span>
        )}
        <span className="chip-stat">
          <Emo e="💸" /> {money(p, t, loc)}
        </span>
        {p.comfort && (
          <span className="chip-stat">
            <Emo e={p.comfort === "indoor" ? "🏠" : "🌤️"} /> {t("comfort." + p.comfort + "Note")}
          </span>
        )}
      </div>

      {p.route ? (
        <section className="budget-card">
          <Ring segments={segments} total={minutes} size={112} center={Math.round(used)} unit={t("ui.min")} />
          <div>
            <RingLegend segments={segments} unit={t("ui.min")} />
            <p className="budget-line">
              <Icon name="footprints" /> {t("ui.walkDistance", { m: Math.round(p.route.network_distance_m), n: Math.max(1, Math.ceil(p.route.duration_min)) })}
            </p>
          </div>
        </section>
      ) : (
        <p className="note">{t("detail.noRoute")}</p>
      )}

      {(p.why || p.what_to_do) && (
        <section className="why-card">
          {p.why && (
            <p>
              <Emo e="💡" /> <b>{t("expl.why")}</b> {p.why}
            </p>
          )}
          {p.what_to_do && (
            <p>
              <Emo e="👣" /> <b>{t("expl.todo")}</b> {p.what_to_do}
            </p>
          )}
        </section>
      )}

      {p.short_description && (
        <div className="pd-desc">
          <p className={expanded ? "" : "clamped"}>{p.short_description}</p>
          {p.short_description.length > 180 && (
            <button className="link-btn" onClick={() => setExpanded(!expanded)}>
              {expanded ? t("detail.less") : t("detail.more")}
            </button>
          )}
        </div>
      )}
      {cost && <p className="note">{cost}</p>}
      {p.events?.map((e) => (
        <p key={e.event_id} className="note">
          <Emo e="🎟️" /> {t("events.here", { name: e.name, when: eventWhen(e, t) })} <SourceLink url={e.source_url}>{t("events.source")}</SourceLink>
        </p>
      ))}
      {p.warnings?.map((w) => (
        <p key={w} className="note warn">
          <Icon name="info" /> {w}
        </p>
      ))}

      <div className="pd-sections">
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
                <small> {s.collected_at?.slice(0, 10)}</small>
              </li>
            ))}
          </ul>
          <small>{t("detail.snapshot", { date: walk.meta?.dataset_date ?? "" })}</small>
        </details>
      </div>

      <div className="cta-dock">
        <button className="cta" disabled={walk.busy} onClick={onRoute}>
          <span className="cta-main">
            <Icon name="route" /> {t("detail.routeHere")}
          </span>
        </button>
        {safeUrl(p.website) && (
          <a className="ghost-btn" href={safeUrl(p.website)} target="_blank" rel="noreferrer">
            {t("detail.website")} <Icon name="external-link" />
          </a>
        )}
      </div>
    </div>
  );
}
