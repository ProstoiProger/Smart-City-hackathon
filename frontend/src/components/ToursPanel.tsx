import { useEffect, useRef, useState } from "react";
import { request, safeUrl, type TourCard, type TourDetail } from "../api";
import { comfortLabel } from "../lib/format";
import { Icon } from "../lib/Icon";
import { locale, useT } from "../lib/i18n";
import { usePrefs } from "../lib/prefs";
import { canSpeak, speak, stopSpeaking } from "../lib/voice";
import type { Walk } from "../useWalk";

function meters(a: [number, number], b: [number, number]) {
  const rad = Math.PI / 180;
  const h =
    Math.sin(((b[0] - a[0]) * rad) / 2) ** 2 +
    Math.cos(a[0] * rad) * Math.cos(b[0] * rad) * Math.sin(((b[1] - a[1]) * rad) / 2) ** 2;
  return 6371000 * 2 * Math.asin(Math.min(1, Math.sqrt(h)));
}

const ARRIVE_SLACK_M = 40;

/** Follows the device position on the device only: nothing is sent anywhere. */
function useWatch(on: boolean) {
  const [pos, setPos] = useState<[number, number] | null>(null);
  const [denied, setDenied] = useState(false);
  useEffect(() => {
    if (!on || !navigator.geolocation) return;
    setDenied(false);
    const id = navigator.geolocation.watchPosition(
      (p) => setPos([p.coords.latitude, p.coords.longitude]),
      () => setDenied(true),
      { enableHighAccuracy: true, maximumAge: 5000 },
    );
    return () => {
      navigator.geolocation.clearWatch(id);
      setPos(null);
    };
  }, [on]);
  return { pos, denied };
}

function Guide({ walk, detail, current }: { walk: Walk; detail: TourDetail; current: number }) {
  const t = useT();
  const { lang } = usePrefs();
  const [reading, setReading] = useState(false);
  const [gps, setGps] = useState(false);
  const { pos, denied } = useWatch(gps);
  const stop = detail.stops[current];
  const last = current === detail.stops.length - 1;
  const leg = detail.legs[current];
  const comfort = walk.weather?.comfort;
  const harsh = comfort?.applies && comfort.factors.filter((f) => f.level !== "advisory");
  const go = (i: number) => {
    stopSpeaking();
    setReading(false);
    walk.setTour({ detail, current: Math.max(0, Math.min(detail.stops.length, i)) });
  };

  // Reaching the next stop opens its card without a tap.
  const reached = useRef(-1);
  useEffect(() => {
    if (!pos || current >= detail.stops.length) return;
    const next = detail.stops[current];
    if (meters(pos, [next.latitude, next.longitude]) <= next.radius_m + ARRIVE_SLACK_M && reached.current !== current) {
      reached.current = current;
      go(current + 1 < detail.stops.length ? current + 1 : detail.stops.length);
    }
    // go() only reads stable props; the position is the trigger.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pos]);

  useEffect(() => () => stopSpeaking(), []);

  const read = () => {
    if (reading) {
      stopSpeaking();
      setReading(false);
      return;
    }
    setReading(true);
    speak([stop.name, ...stop.facts.map((f) => f.text), stop.tip ?? ""].join(". "), lang, () => setReading(false));
  };

  if (current >= detail.stops.length) {
    return (
      <div className="tour-guide done">
        <h3>{t("tours.finish")}</h3>
        <p>{t("tours.finishNote", { n: detail.stops.length, min: detail.walk_min })}</p>
        <div className="group-actions">
          <button className="icon-button" onClick={() => go(0)}>
            <Icon name="rotate-ccw" /> {t("tours.restart")}
          </button>
        </div>
      </div>
    );
  }
  const toStop = pos ? Math.round(meters(pos, [stop.latitude, stop.longitude])) : null;
  return (
    <div className="tour-guide">
      <small className="tour-step">{t("tours.step", { i: current + 1, n: detail.stops.length })}</small>
      <h3>{stop.name}</h3>
      {stop.outdoor && !!harsh && harsh.length > 0 && (
        <p className="warning tour-weather">
          <Icon name="cloud-sun" /> {t("tours.weatherWarn", { list: harsh.map((f) => comfortLabel(f, t)).join(", ") })}
        </p>
      )}
      <ul className="tour-facts">
        {stop.facts.map((f) => (
          <li key={f.text}>
            {f.text}{" "}
            {safeUrl(f.source) && (
              <a href={safeUrl(f.source)} target="_blank" rel="noreferrer" className="icon-button">
                {f.source_name}
                <Icon name="external-link" />
              </a>
            )}
          </li>
        ))}
      </ul>
      {stop.tip && (
        <p className="tour-tip">
          <b>{t("tours.tip")}</b> {stop.tip}
        </p>
      )}
      {toStop != null && <small>{t("tours.distance", { n: toStop })}</small>}
      {!last && leg && (
        <small>{t("tours.walkNext", { n: Math.max(1, Math.round(leg.duration_min)) })}</small>
      )}
      <div className="group-actions">
        {canSpeak() && (
          <button className="icon-button" aria-pressed={reading} onClick={read}>
            <Icon name={reading ? "square" : "headphones"} /> {reading ? t("tours.stopListen") : t("tours.listen")}
          </button>
        )}
        <button className="icon-button" disabled={current === 0} onClick={() => go(current - 1)}>
          <Icon name="chevron-left" /> {t("tours.prev")}
        </button>
        <button className="primary icon-button" onClick={() => go(current + 1)}>
          {last ? t("tours.here") : t("tours.next")} <Icon name="chevron-right" />
        </button>
      </div>
      {typeof navigator !== "undefined" && "geolocation" in navigator && (
        <label className="check">
          <input type="checkbox" checked={gps} onChange={(e) => setGps(e.target.checked)} />
          {t("tours.gps")}
        </label>
      )}
      {gps && <small>{denied ? t("tours.gpsDenied") : t("tours.gpsOn")}</small>}
    </div>
  );
}

export function ToursPanel({ walk, onClose }: { walk: Walk; onClose: () => void }) {
  const t = useT();
  const { lang } = usePrefs();
  const [cards, setCards] = useState<TourCard[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState("");
  const { tour, setTour } = walk;

  useEffect(() => {
    let alive = true;
    setCards(null);
    setFailed(false);
    request<{ items: TourCard[] }>(`tours?lang=${lang}`)
      .then((r) => alive && setCards(r.items))
      .catch(() => alive && setFailed(true));
    return () => {
      alive = false;
    };
  }, [lang]);

  // A language switch reloads the open tour, keeping the current stop.
  const open = tour?.detail.id;
  const keep = useRef(tour?.current ?? 0);
  keep.current = tour?.current ?? 0;
  useEffect(() => {
    if (!open) return;
    request<TourDetail>(`tours/${open}?lang=${lang}`)
      .then((d) => setTour({ detail: d, current: keep.current }))
      .catch(() => setFailed(true));
    // Reload on language only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lang]);

  const start = async (id: string) => {
    setBusy(id);
    setFailed(false);
    try {
      walk.setPanel("map");
      setTour({ detail: await request<TourDetail>(`tours/${id}?lang=${lang}`), current: 0 });
    } catch {
      setFailed(true);
    } finally {
      setBusy("");
    }
  };

  const loc = locale(lang);
  return (
    <section className="compare-panel afisha tours" aria-label={t("tours.title")}>
      <div className="sheet-top">
        <h2>{tour ? tour.detail.title : t("tours.title")}</h2>
        <button
          aria-label={t("tours.close")}
          onClick={() => {
            stopSpeaking();
            setTour(null);
            onClose();
          }}
        >
          <Icon name="x" />
        </button>
      </div>
      {failed && (
        <p className="warning" role="alert">
          {t("tours.error")}
        </p>
      )}
      {tour ? (
        <>
          <button className="text-button icon-button" onClick={() => setTour(null)}>
            <Icon name="chevron-left" /> {t("tours.back")}
          </button>
          <p>
            {tour.detail.subtitle} · {t("tours.min", { n: tour.detail.duration_min })} ·{" "}
            {t("tours.km", { n: tour.detail.distance_km.toLocaleString(loc) })}
          </p>
          <Guide walk={walk} detail={tour.detail} current={tour.current} />
          <details>
            <summary>{t("tours.route")}</summary>
            <ol className="tour-stops">
              {tour.detail.stops.map((s, i) => (
                <li key={s.id} aria-current={i === tour.current}>
                  <button className="text-button" onClick={() => setTour({ ...tour, current: i })}>
                    {s.name}
                  </button>
                  {i < tour.detail.legs.length && (
                    <small>{t("tours.legMin", { n: Math.max(1, Math.round(tour.detail.legs[i].duration_min)) })}</small>
                  )}
                </li>
              ))}
            </ol>
            {tour.detail.hours && (
              <p>
                <b>{t("tours.hours")}:</b> {tour.detail.hours.text}
              </p>
            )}
            {tour.detail.best_season && (
              <p>
                <b>{t("tours.season")}:</b> {tour.detail.best_season}
              </p>
            )}
          </details>
          <small>{t("tours.note")}</small>
        </>
      ) : (
        <>
          <p>{t("tours.intro")}</p>
          {!cards && !failed && <p role="status">{t("tours.loading")}</p>}
          {cards?.map((c) => (
            <article className="event-row tour-card" key={c.id}>
              <h3>{c.title}</h3>
              <p>{c.subtitle}</p>
              <p className="tour-meta">
                {t("tours.stops", { n: c.stops })} · {t("tours.facts", { n: c.facts })} ·{" "}
                {t("tours.min", { n: c.duration_min })} · {t("tours.km", { n: c.distance_km.toLocaleString(loc) })}
              </p>
              <div className="detail-actions">
                <button className="primary icon-button" disabled={!!busy} onClick={() => start(c.id)}>
                  <Icon name="footprints" /> {t("tours.start")}
                </button>
              </div>
            </article>
          ))}
        </>
      )}
    </section>
  );
}
