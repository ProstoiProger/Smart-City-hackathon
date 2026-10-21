import type { ChatResponse } from "../api";
import { comfortLabel, rejectedLabel } from "../lib/format";
import { Icon } from "../lib/Icon";
import { useT } from "../lib/i18n";

/** Weather and air that shaped this answer; hidden when they changed nothing worth saying. */
export function ComfortNote({ data }: { data: ChatResponse }) {
  const t = useT();
  const comfort = data.comfort;
  if (!comfort?.applies || !comfort.factors.length) return null;
  const shifted = comfort.factors.some((f) => f.level !== "advisory");
  return (
    <div className={"comfort-note " + (shifted ? "shifted" : "advisory")}>
      <strong>
        <Icon name="cloud-sun" /> {t("comfort.title")}
      </strong>
      <ul>
        {comfort.factors.map((f) => (
          <li key={f.code}>{comfortLabel(f, t)}</li>
        ))}
      </ul>
      {shifted && <small>{t("comfort.shift")}</small>}
      <small>{t("comfort.source")}</small>
    </div>
  );
}

/** Funnel of counts and the near-miss places with the reason each was left out. */
export function WhyNot({ data }: { data: ChatResponse }) {
  const t = useT();
  const funnel = data.funnel ?? [];
  const rejected = data.rejected ?? [];
  if (!funnel.length && !rejected.length) return null;
  const top = Math.max(1, ...funnel.map((s) => s.count));
  return (
    <details className="why-not">
      <summary>{t("why.title")}</summary>
      {!!funnel.length && (
        <>
          <strong className="why-sub">{t("why.funnel")}</strong>
          <ol className="funnel">
            {funnel.map((s) => (
              <li key={s.key}>
                <span>{t("funnel." + s.key)}</span>
                <b>{s.count}</b>
                <i aria-hidden="true" style={{ width: `${Math.max(4, Math.round((s.count / top) * 100))}%` }} />
              </li>
            ))}
          </ol>
        </>
      )}
      {!!rejected.length && (
        <ul className="rejected">
          {rejected.map((r) => (
            <li key={r.poi_id}>
              <b>{r.name}</b>
              <span>{rejectedLabel(r, t)}</span>
            </li>
          ))}
        </ul>
      )}
      <small>{t("why.note")}</small>
    </details>
  );
}
