import { safeUrl, type EventRecord, type Poi } from "../api";
import { hoursLabel, money, yesNo } from "../lib/format";
import { Icon } from "../lib/Icon";
import { locale, useT } from "../lib/i18n";
import { usePrefs } from "../lib/prefs";
import type { Walk } from "../useWalk";

export function ComparePanel({ walk }: { walk: Walk }) {
  const t = useT();
  const { lang } = usePrefs();
  const { comparison, setComparison } = walk.compareState;
  if (!comparison.length) return null;
  const rows: [string, (p: Poi) => string][] = [
    ["compare.walk", (p) => (p.route ? t("detail.minutes", { n: Math.ceil(p.route.duration_min) }) : t("compare.noRoute"))],
    ["compare.visit", (p) => t("compare.visitValue", { n: p.suggested_visit_duration_min })],
    ["compare.price", (p) => money(p, t, locale(lang))],
    ["compare.hours", (p) => hoursLabel(p, t)],
    ["compare.outlets", (p) => yesNo(p.power_outlets === true ? true : undefined, t)],
    ["compare.quiet", (p) => yesNo(p.quiet_place === true ? true : undefined, t)],
  ];
  return (
    <div className="compare-panel" role="region" aria-label={t("compare.region")}>
      <div className="sheet-top">
        <h2>{t("selection.compare")}</h2>
        <button aria-label={t("detail.close")} onClick={() => setComparison([])}>
          <Icon name="x" />
        </button>
      </div>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>{t("compare.condition")}</th>
              {comparison.map((p) => (
                <th key={p.poi_id}>{p.display_name}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map(([key, value]) => (
              <tr key={key}>
                <th>{t(key)}</th>
                {comparison.map((p) => (
                  <td key={p.poi_id}>{value(p)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p>{t("compare.note")}</p>
      <button
        className="primary icon-button"
        disabled={walk.busy}
        onClick={() => {
          setComparison([]);
          walk.buildPlan();
        }}
      >
        <Icon name="route" />
        {t("selection.plan")}
      </button>
    </div>
  );
}

/** Ticket page: Ticketon when the listing has one, otherwise the publisher page. */
function ticketLink(event: EventRecord): { href?: string; ticketon: boolean } {
  const urls = [event.registration_url, event.source_url].map((u) => safeUrl(u)).filter(Boolean) as string[];
  const ticketon = urls.find((u) => new URL(u).hostname.endsWith("ticketon.kz"));
  return { href: ticketon || urls[0], ticketon: !!ticketon };
}

/** "08.10.2026" from an ISO date, with the time when the listing has one. */
function eventDate(iso: string) {
  const date = `${iso.slice(8, 10)}.${iso.slice(5, 7)}.${iso.slice(0, 4)}`;
  return iso.length > 10 && iso.slice(11, 16) !== "00:00" ? `${date}, ${iso.slice(11, 16)}` : date;
}

export function AfishaPanel({ walk }: { walk: Walk }) {
  const t = useT();
  const { afisha, setAfisha } = walk.afishaState;
  if (afisha === null) return null;
  return (
    <section className="compare-panel afisha" aria-label={t("afisha.region")}>
      <div className="sheet-top">
        <h2>{t("afisha.region")}</h2>
        <button aria-label={t("afisha.close")} onClick={() => setAfisha(null)}>
          <Icon name="x" />
        </button>
      </div>
      <p>{t("afisha.note")}</p>
      {!afisha.length && <p>{t("afisha.empty")}</p>}
      {afisha.slice(0, 30).map((event) => {
        const link = ticketLink(event);
        return (
          <article className="event-row" key={event.event_id}>
            <h3>{event.event_name}</h3>
            <p>
              {eventDate(event.event_start)}
              {event.event_end && event.event_end !== event.event_start ? " — " + eventDate(event.event_end) : ""}
              {event.event_location ? " · " + event.event_location : ""}
            </p>
            {link.href && (
              <div className="detail-actions">
                <a className="icon-button" href={link.href} target="_blank" rel="noreferrer">
                  {link.ticketon ? t("afisha.ticketon") : t("detail.source")}
                  <Icon name="external-link" />
                </a>
              </div>
            )}
          </article>
        );
      })}
    </section>
  );
}

export function Notification({ walk }: { walk: Walk }) {
  const t = useT();
  const { error, notice, dismiss } = walk;
  if (!error && !notice) return null;
  return (
    <div className={"notification " + (error ? "error" : "")} role={error ? "alert" : "status"}>
      <Icon name={error ? "circle-alert" : "info"} />
      <span>{error || notice}</span>
      <button aria-label={t("detail.close")} onClick={dismiss}>
        <Icon name="x" />
      </button>
    </div>
  );
}
