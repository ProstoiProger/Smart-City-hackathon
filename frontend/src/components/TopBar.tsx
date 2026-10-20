import type { Meta, Weather } from "../api";
import { Icon } from "../lib/Icon";
import { locale, useT } from "../lib/i18n";
import { usePrefs } from "../lib/prefs";

export function TopBar({ meta, weather, onAfisha }: { meta?: Meta; weather?: Weather; onAfisha: () => void }) {
  const t = useT();
  const { theme, toggleTheme, lang, setLang } = usePrefs();
  return (
    <header className="topbar">
      <a href="/" className="brand" aria-label={t("brand.aria")}>
        <span className="brand-symbol" aria-hidden="true">
          <Icon name="arrow-up-right" />
        </span>
        Astana<span>Walk</span>
      </a>
      <div className="city-label">
        {t("top.city")} <span>·</span> {meta ? t("top.places", { n: meta.pois.toLocaleString(locale(lang)) }) : "…"}
        <small className="weather" title={weather?.note}>
          {weather?.available
            ? t("weather.now", { t: weather.temperature_c ?? "", w: weather.wind_kmh ?? "" })
            : t("weather.none")}{" "}
          {weather?.available && (
            <a
              href={weather.source_url}
              target="_blank"
              rel="noreferrer"
              title={t("weather.source", { at: weather.valid_at ?? "" })}
              aria-label={t("weather.source", { at: weather.valid_at ?? "" })}
            >
              <Icon name="external-link" />
            </a>
          )}
        </small>
      </div>
      <div className="topbar-actions">
        <button className="icon-button" onClick={onAfisha}>
          <Icon name="calendar-clock" />
          <span className="label">{t("top.afisha")}</span>
        </button>
        <button
          className="icon-button"
          onClick={toggleTheme}
          aria-label={theme === "dark" ? t("theme.toLight") : t("theme.toDark")}
          title={theme === "dark" ? t("theme.toLight") : t("theme.toDark")}
        >
          <Icon name={theme === "dark" ? "sun" : "moon"} />
        </button>
        <div className="language" role="group" aria-label={t("top.lang")}>
          <button aria-pressed={lang === "ru"} onClick={() => setLang("ru")} lang="ru">
            РУС
          </button>
          <button aria-pressed={lang === "kk"} onClick={() => setLang("kk")} lang="kk">
            ҚАЗ
          </button>
        </div>
      </div>
    </header>
  );
}
