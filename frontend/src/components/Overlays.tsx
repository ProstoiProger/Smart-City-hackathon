import { safeUrl, type Poi } from "../api";
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

export function AfishaPanel({ walk }: { walk: Walk }) {
  const t = useT();
  const { lang } = usePrefs();
  const { afisha, setAfisha, eventChecks, checkingEvent, recheckEvent } = walk.afishaState;
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
        const check = eventChecks[event.event_id];
        return (
          <article className="event-row" key={event.event_id}>
            <h3>{event.event_name}</h3>
            <p>
              {event.event_start}
              {event.event_end && event.event_end !== event.event_start ? " — " + event.event_end : ""}
              {event.event_location ? " · " + event.event_location : ""}
            </p>
            <div className="detail-actions">
              <a
                className="icon-button"
                href={safeUrl(event.registration_url) || safeUrl(event.source_url)}
                target="_blank"
                rel="noreferrer"
              >
                {t("detail.source")}
                <Icon name="external-link" />
              </a>
              <button disabled={!!checkingEvent} onClick={() => recheckEvent(event)}>
                {checkingEvent === event.event_id ? t("afisha.checking") : t("afisha.check")}
              </button>
            </div>
            {check && (
              <p className={check.cancelled_as_reported ? "warning" : ""}>
                {check.cancelled_as_reported ? t("afisha.cancelled") + " " : ""}
                {check.note} ·{" "}
                {t("afisha.checkedAt", {
                  at: new Date(check.publisher_rechecked_at).toLocaleString(locale(lang), { timeZone: "Asia/Almaty" }),
                })}
              </p>
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
