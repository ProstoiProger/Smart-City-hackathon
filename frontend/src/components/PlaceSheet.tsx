import type { ReactNode } from "react";
import { safeUrl, type Poi } from "../api";
import { categoryLabel, hoursLabel, money, ruleLabel, ruleValue, tariff, yesNo } from "../lib/format";
import { Icon } from "../lib/Icon";
import { locale, useT } from "../lib/i18n";
import { usePrefs } from "../lib/prefs";
import type { Walk } from "../useWalk";
import { Explanation } from "./Explanation";

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

function ReviewSignals({ p }: { p: Poi }) {
  const t = useT();
  const signals = Object.entries(p.review_signals || {});
  if (!signals.length) return null;
  return (
    <details open>
      <summary>{t("reviews.title")}</summary>
      <ul className="signals">
        {signals.map(([key, s]) => (
          <li key={key} className={"signal " + s.status}>
            <strong>{t("signal." + key)}</strong>{" "}
            <span>
              {t("reviews.counts", { status: t("signalStatus." + s.status), pos: s.positive })}
              {s.negative + s.mixed > 0 && t("reviews.against", { n: s.negative + s.mixed })}
            </span>
            {s.quotes.slice(0, 2).map((q) => (
              <q key={q.review_id} className={q.polarity}>
                {q.text}
                <small>
                  {" "}
                  {q.date?.slice(0, 10)}{" "}
                  <SourceLink url={`https://2gis.kz/astana/firm/${q.branch_id}/tab/reviews`}>{t("reviews.link")}</SourceLink>
                </small>
              </q>
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

function Amenities({ p }: { p: Poi }) {
  const t = useT();
  const rows: [string, boolean | undefined][] = [
    ["amen.wifi", p.wifi_available],
    ["amen.outlets", p.power_outlets],
    ["amen.quiet", p.quiet_place],
    ["amen.entrance", p.entrance_accessible],
    ["amen.ramp", p.ramps],
    ["amen.wheelchair", p.wheelchair_accessible],
    ["amen.booking", p.reservation_required ?? p.booking_required],
  ];
  return (
    <details>
      <summary>{t("detail.hoursAmenities")}</summary>
      <p>{p.opening_hours || t("detail.noSchedule")}</p>
      <dl>
        {rows.map(([key, value]) => (
          <div key={key}>
            <dt>{t(key)}</dt>
            <dd>{yesNo(value, t)}</dd>
          </div>
        ))}
      </dl>
      <p>
        {t("detail.rules", {
          v: p.access_restrictions ? JSON.stringify(p.access_restrictions) : t("detail.rulesUnknown"),
        })}
      </p>
      <p>{t("detail.age", { v: p.age_restrictions ? JSON.stringify(p.age_restrictions) : t("detail.ageUnknown") })}</p>
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
          <p>{p.semantic_attributes.slice(0, 25).join(" · ")}</p>
          <small>{t("attrs.note")}</small>
        </details>
      )}
    </>
  );
}

export function PlaceSheet({ walk, p }: { walk: Walk; p: Poi }) {
  const t = useT();
  const { lang } = usePrefs();
  const { compareIds, toggleCompare } = walk.compareState;
  return (
    <section className="detail-sheet" aria-label={t("detail.region")}>
      <div className="sheet-top">
        <span>{categoryLabel(p, t)}</span>
        <button aria-label={t("detail.close")} onClick={() => walk.selectPlace(undefined)}>
          <Icon name="x" />
        </button>
      </div>
      <h2>{p.display_name}</h2>
      <p>{p.short_description}</p>
      {(p.why || p.what_to_do) && (
        <div className="why-box">
          <Explanation p={p} />
        </div>
      )}
      {p.description_type === "attribute_grounded_summary" && <small>{t("detail.groundedSummary")}</small>}
      <div className="facts-grid">
        <div>
          <small>{t("detail.walk")}</small>
          <strong>{p.route ? t("detail.minutes", { n: Math.ceil(p.route.duration_min) }) : t("detail.noRoute")}</strong>
        </div>
        <div>
          <small>{t("detail.visit")}</small>
          <strong>{t("detail.minutes", { n: p.suggested_visit_duration_min })}</strong>
        </div>
        <div>
          <small>{t("detail.cost")}</small>
          <strong>{money(p, t, locale(lang))}</strong>
        </div>
      </div>
      <p className="hours-note">{hoursLabel(p, t)}</p>
      <Amenities p={p} />
      <ReviewSignals p={p} />
      <Published p={p} />
      {p.warnings?.map((w) => (
        <p className="warning" key={w}>
          {w}
        </p>
      ))}
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
      </details>
      <div className="detail-actions">
        <button className="primary icon-button" disabled={walk.busy} onClick={() => walk.buildPlan([p.poi_id])}>
          <Icon name="route" />
          {t("detail.routeHere")}
        </button>
        <button onClick={() => toggleCompare(p)}>
          {compareIds.includes(p.poi_id) ? t("place.remove") : t("place.add")}
        </button>
        <SourceLink url={p.website}>{t("detail.website")}</SourceLink>
      </div>
      <small>{t("detail.snapshot", { date: walk.meta?.dataset_date ?? "" })}</small>
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
        <span>{t("plan.yours")}</span>
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
