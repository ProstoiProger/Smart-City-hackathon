import { Emo } from "../lib/Emo";
import { categoryColor, LANDMARK_EMOJI, placeEmoji } from "../lib/emoji";
import type { HistoryEntry } from "../lib/history";
import { visitedIds } from "../lib/history";
import { Icon } from "../lib/Icon";
import { has, locale, useT } from "../lib/i18n";
import { usePrefs } from "../lib/prefs";
import type { Walk } from "../useWalk";

/** Where the walk started, in the interface language. */
export function startName(start: HistoryEntry["start"], t: ReturnType<typeof useT>) {
  if (start.key && has("lm." + start.key)) return t("lm." + start.key);
  if (start.label.startsWith("i18n:")) return t(start.label.slice(5));
  return start.label;
}

/** Past walks, kept only in this browser: repeat one, mark where you have been, or clear it all. */
export function History({ walk, onBack, onRepeat }: { walk: Walk; onBack: () => void; onRepeat: (e: HistoryEntry) => void }) {
  const t = useT();
  const { lang } = usePrefs();
  const h = walk.history;
  const visited = visitedIds(h.entries).length;
  const minutes = h.entries.reduce((a, e) => a + e.minutes, 0);
  const day = (iso: string) => new Date(iso + "T12:00").toLocaleDateString(locale(lang), { day: "numeric", month: "long" });
  return (
    <div className="screen history">
      <div className="screen-top">
        <button className="back-btn" onClick={onBack}>
          <Icon name="arrow-left" /> {t("ui.back")}
        </button>
      </div>
      <h1 className="screen-title">{t("ui.history.title")}</h1>
      <p className="privacy-note">
        <Emo e="🔒" /> {t("ui.history.privacy")}
      </p>

      {h.entries.length > 0 && (
        <div className="history-stats">
          <span>
            <b>{h.entries.length}</b>
            <small>{t("ui.history.walks")}</small>
          </span>
          <span>
            <b>{minutes}</b>
            <small>{t("ui.history.minutes")}</small>
          </span>
          <span>
            <b>{visited}</b>
            <small>{t("ui.history.visitedCount")}</small>
          </span>
        </div>
      )}

      {!h.on && <p className="note">{t("ui.history.off")}</p>}
      {!h.entries.length && h.on && <p className="empty-note">{t("ui.history.empty")}</p>}
      {h.entries.length > 0 && <p className="hint">{t("ui.history.markHint")}</p>}

      <ol className="history-list">
        {h.entries.map((e, i) => (
          <li key={e.id} className="history-item" style={{ animationDelay: `${Math.min(i, 8) * 50}ms` }}>
            <div className="history-head">
              <span className="history-when">
                <Emo e={e.start.key ? (LANDMARK_EMOJI[e.start.key] ?? "📍") : "📍"} />
                <span>
                  <strong>
                    {day(e.date)} · {t("filters.minutes", { n: e.minutes })}
                  </strong>
                  <small>
                    <Icon name={e.mode === "loop" ? "repeat" : "flag"} /> {t(e.mode === "loop" ? "ui.mode.loop" : "ui.mode.oneway")} ·{" "}
                    {startName(e.start, t)}
                  </small>
                </span>
              </span>
              <button className="round-btn small" aria-label={t("ui.history.delete")} title={t("ui.history.delete")} onClick={() => h.forget(e.id)}>
                <Icon name="x" />
              </button>
            </div>
            {e.wish && <p className="history-wish">«{e.wish}»</p>}
            <ul className="history-places">
              {e.places.map((p) => (
                <li key={p.id}>
                  <button
                    className={"history-place " + p.status}
                    aria-pressed={p.status === "visited"}
                    disabled={p.status === "closed"}
                    title={p.status === "closed" ? t("ui.history.closed") : t("ui.history.visitedMark")}
                    style={{ ["--cat" as string]: categoryColor(p.category) }}
                    onClick={() => h.markPlace(p.id, p.status === "visited" ? "planned" : "visited", e.id)}
                  >
                    <Emo e={placeEmoji(p)} />
                    <span>{p.name.split(",")[0]}</span>
                    {p.status === "visited" && <Icon name="check" />}
                    {p.status === "closed" && <small>{t("ui.history.closed")}</small>}
                  </button>
                </li>
              ))}
            </ul>
            <button className="soft-btn" disabled={walk.busy} onClick={() => onRepeat(e)}>
              <Icon name="rotate-ccw" /> {t("ui.history.repeat")}
            </button>
          </li>
        ))}
      </ol>

      <h2 className="section-title">{t("ui.settings")}</h2>
      <div className="settings-grid flat">
        <label className="switch">
          <input type="checkbox" checked={h.on} onChange={(ev) => h.setOn(ev.target.checked)} />
          <span>{t("ui.history.save")}</span>
        </label>
        <label className="switch">
          <input type="checkbox" checked={h.newOnly} onChange={(ev) => h.setNewOnly(ev.target.checked)} />
          <span>
            {t("ui.history.newOnly")}
            <small>{t("ui.history.newOnlyHint", { n: visited })}</small>
          </span>
        </label>
        <button
          className="ghost-btn danger"
          disabled={!h.entries.length}
          onClick={() => {
            h.clear();
            walk.notify(t("ui.history.cleared"));
          }}
        >
          <Icon name="x" /> {t("ui.history.clear")}
        </button>
      </div>
    </div>
  );
}
