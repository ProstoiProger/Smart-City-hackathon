import { useEffect, useMemo, useRef, useState } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { request, type CityAudit, type CityCell } from "../api";
import { Icon } from "../lib/Icon";
import { locale, useT } from "../lib/i18n";
import { usePrefs } from "../lib/prefs";

const LEVELS = ["none", "guess", "far", "ok"] as const;
type Level = (typeof LEVELS)[number];
const LEVEL_COLOR: Record<Level, string> = { none: "#c0392b", guess: "#8e5bb5", far: "#d99a1e", ok: "#2f8f4e" };
const PRIORITY: Record<Level, number> = { none: 0, guess: 1, far: 2, ok: 3 };

function GapMap({
  audit,
  scenario,
  selected,
  onSelect,
}: {
  audit: CityAudit;
  scenario: string;
  selected: number | null;
  onSelect: (i: number) => void;
}) {
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const layer = useRef<L.LayerGroup | null>(null);
  const pick = useRef(onSelect);
  pick.current = onSelect;

  useEffect(() => {
    const m = L.map(el.current!, { zoomControl: true }).setView([51.1283, 71.4305], 12);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
      maxZoom: 18,
    }).addTo(m);
    map.current = m;
    layer.current = L.layerGroup().addTo(m);
    const ro = new ResizeObserver(() => m.invalidateSize());
    ro.observe(el.current!);
    return () => {
      ro.disconnect();
      m.remove();
    };
  }, []);

  useEffect(() => {
    const group = layer.current;
    const m = map.current;
    if (!group || !m) return;
    group.clearLayers();
    const { lat, lon } = audit.cell_step;
    const bounds = L.latLngBounds([]);
    audit.cells.forEach((c, i) => {
      const level = c.results[scenario].level as Level;
      const box = L.latLngBounds([c.lat - lat / 2, c.lon - lon / 2], [c.lat + lat / 2, c.lon + lon / 2]);
      bounds.extend(box);
      L.rectangle(box, {
        color: i === selected ? "#111" : LEVEL_COLOR[level],
        weight: i === selected ? 3 : 1,
        fillColor: LEVEL_COLOR[level],
        fillOpacity: level === "ok" ? 0.18 : 0.5,
      })
        .on("click", () => pick.current(i))
        .addTo(group);
    });
    m.invalidateSize();
    const size = m.getSize();
    if (bounds.isValid() && size.x > 0 && size.y > 0) m.fitBounds(bounds, { padding: [20, 20] });
    // Refit only when the scenario or data changes, not on every selection.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [audit, scenario]);

  useEffect(() => {
    // Selection only restyles; the view stays where the user left it.
    const group = layer.current;
    if (!group) return;
    let i = 0;
    group.eachLayer((l) => {
      const c = audit.cells[i++];
      const level = c.results[scenario].level as Level;
      (l as L.Rectangle).setStyle({
        color: i - 1 === selected ? "#111" : LEVEL_COLOR[level],
        weight: i - 1 === selected ? 3 : 1,
      });
    });
  }, [selected, audit, scenario]);

  return <div ref={el} className="city-map" role="region" aria-label="map" />;
}

function CellInfo({ cell, scenario }: { cell: CityCell; scenario: string }) {
  const t = useT();
  const r = cell.results[scenario];
  return (
    <div className="city-cell">
      <strong>{cell.label ?? t("city.cell")}</strong>
      <span className={"pill city-" + r.level}>{t("city.level." + r.level)}</span>
      <small>
        {t("city.cellInfo", { places: cell.places, options: r.options })}
        {r.nearest_min != null ? " · " + t("city.nearest", { n: r.nearest_min }) : ""}
      </small>
      {!!r.best.length && <small>{t("city.best", { list: r.best.join(", ") })}</small>}
    </div>
  );
}

function Coverage({ audit }: { audit: CityAudit }) {
  const t = useT();
  const { lang } = usePrefs();
  const c = audit.coverage;
  const rows: [string, number][] = [
    ["hours", c.with_hours],
    ["rating", c.with_rating],
    ["price", c.with_price],
    ["reviews", c.with_review_signals],
    ["access", c.with_accessibility],
  ];
  return (
    <section className="city-coverage">
      <h3>{t("city.coverage")}</h3>
      <p>{t("city.coverageNote", { n: c.places.toLocaleString(locale(lang)), events: c.events })}</p>
      <ul>
        {rows.map(([key, n]) => {
          const pct = Math.round((n / c.places) * 100);
          return (
            <li key={key}>
              <span>{t("city.cov." + key)}</span>
              <b>{pct}%</b>
              <i aria-hidden="true" style={{ width: `${Math.max(2, pct)}%` }} />
            </li>
          );
        })}
      </ul>
    </section>
  );
}

export function CityPage({ onClose }: { onClose: () => void }) {
  const t = useT();
  const { lang } = usePrefs();
  const [audit, setAudit] = useState<CityAudit | null>(null);
  const [failed, setFailed] = useState(false);
  const [scenario, setScenario] = useState("kids_evening");
  const [selected, setSelected] = useState<number | null>(null);

  useEffect(() => {
    let alive = true;
    request<CityAudit>("city/audit")
      .then((a) => alive && setAudit(a))
      .catch(() => alive && setFailed(true));
    return () => {
      alive = false;
    };
  }, []);

  const worst = useMemo(() => {
    if (!audit) return [];
    const seen = new Set<string>();
    return audit.cells
      .map((c, i) => ({ c, i, level: c.results[scenario].level as Level }))
      .filter((x) => x.level !== "ok")
      .sort((a, b) => PRIORITY[a.level] - PRIORITY[b.level] || b.c.places - a.c.places)
      .filter((x) => {
        const key = x.c.label ?? String(x.i);
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
      })
      .slice(0, 6);
  }, [audit, scenario]);

  const info = audit?.scenarios.find((s) => s.id === scenario);
  const day = info ? new Date(info.when).toLocaleString(locale(lang), { weekday: "short", hour: "2-digit", minute: "2-digit" }) : "";
  return (
    <section className="city-page" aria-label={t("city.title")}>
      <header className="city-head">
        <div>
          <h2>{t("city.title")}</h2>
          <p>{t("city.sub")}</p>
        </div>
        <button className="icon-button round" aria-label={t("city.close")} title={t("city.close")} onClick={onClose}>
          <Icon name="x" />
        </button>
      </header>
      {failed && (
        <p className="warning" role="alert">
          {t("city.noAudit")}
        </p>
      )}
      {!audit && !failed && <p role="status">{t("tours.loading")}</p>}
      {audit && (
        <div className="city-body">
          <div className="city-tabs" role="tablist" aria-label={t("city.title")}>
            {audit.scenarios.map((s) => {
              const gaps = s.summary.none + s.summary.guess + s.summary.far;
              return (
                <button
                  key={s.id}
                  role="tab"
                  aria-selected={scenario === s.id}
                  onClick={() => {
                    setScenario(s.id);
                    setSelected(null);
                  }}
                >
                  {t("city.s." + s.id)} <small>{gaps}</small>
                </button>
              );
            })}
          </div>
          <div className="city-grid">
            <GapMap audit={audit} scenario={scenario} selected={selected} onSelect={setSelected} />
            <aside className="city-side">
              <p className="city-why">{t("city.why." + scenario)}</p>
              <small>
                {t("city.ask", { q: t("city.q." + scenario), at: day })}
              </small>
              <ul className="city-legend">
                {LEVELS.map((l) => (
                  <li key={l}>
                    <i style={{ background: LEVEL_COLOR[l] }} aria-hidden="true" />
                    <span>{t("city.level." + l)}</span>
                    <b>{info?.summary[l] ?? 0}</b>
                  </li>
                ))}
              </ul>
              {selected != null && <CellInfo cell={audit.cells[selected]} scenario={scenario} />}
              <h3>{t("city.worst")}</h3>
              <ol className="city-worst">
                {worst.map((x) => (
                  <li key={x.i}>
                    <button className="text-button" onClick={() => setSelected(x.i)}>
                      {x.c.label ?? t("city.cell")}
                    </button>
                    <span className={"pill city-" + x.level}>{t("city.level." + x.level)}</span>
                  </li>
                ))}
              </ol>
              <Coverage audit={audit} />
            </aside>
          </div>
        </div>
      )}
    </section>
  );
}
