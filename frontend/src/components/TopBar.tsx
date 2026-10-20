import type { Meta, Weather } from "../api";
import { Icon } from "../lib/Icon";
import { locale, useT } from "../lib/i18n";
import { usePrefs } from "../lib/prefs";

/** Lucide icon for a WMO weather code (Open-Meteo `weather_code`). */
function weatherIcon(code?: number | null): string {
  if (code == null) return "cloud";
  if (code <= 1) return "sun";
  if (code === 2) return "cloud-sun";
  if ((code >= 71 && code <= 77) || code === 85 || code === 86) return "cloud-snow";
  if (code >= 51) return "cloud-rain";
  return "cloud";
}

export function TopBar({ meta, weather, onAfisha }: { meta?: Meta; weather?: Weather; onAfisha: () => void }) {
  const t = useT();
  const { theme, toggleTheme, lang, setLang } = usePrefs();
  return (
    <header className="topbar">
      <a href="/" className="brand" aria-label={t("brand.aria")}>
        <span className="brand-symbol" aria-hidden="true">
          <Icon name="map-pin" />
        </span>
        <span className="brand-name">
          Astana<span>Walk</span>
        </span>
      </a>
      <div className="top-stats">
        <span className="stat">
          <Icon name="map-pin" />
          <b>{t("top.city")}</b>
          {meta && <span className="stat-sub">{t("top.places", { n: meta.pois.toLocaleString(locale(lang)) })}</span>}
        </span>
        {weather?.available ? (
          <a
            className="stat weather"
            href={weather.source_url}
            target="_blank"
            rel="noreferrer"
            title={`${weather.note ?? ""} ${t("weather.source", { at: weather.valid_at ?? "" })}`}
            aria-label={t("weather.now", { t: weather.temperature_c ?? "", w: weather.wind_kmh ?? "" })}
          >
            <Icon name={weatherIcon(weather.weather_code)} />
            <b>{Math.round(weather.temperature_c ?? 0)}°</b>
            <span className="stat-sub">
              <Icon name="wind" />
              {t("weather.wind", { w: Math.round(weather.wind_kmh ?? 0) })}
            </span>
          </a>
        ) : (
          <span className="stat weather">
            <Icon name="cloud" />
            <span className="stat-sub">{t("weather.none")}</span>
          </span>
        )}
      </div>
      <div className="topbar-actions">
        <button className="afisha-button icon-button" onClick={onAfisha}>
          <Icon name="calendar-clock" />
          <span className="label">{t("top.afisha")}</span>
        </button>
        <button
          className="icon-button round"
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
