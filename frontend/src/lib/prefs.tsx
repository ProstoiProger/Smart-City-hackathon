import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

export type Theme = "light" | "dark";
export type Lang = "ru" | "kk" | "en";

/** "Версия для слабовидящих": larger text, a high-contrast scheme, optional images,
 * wider spacing. The usual low-vision switch of public sites in Kazakhstan. */
export type LowVision = {
  on: boolean;
  /** Text size: 1 = A (×1.25), 2 = A+ (×1.5), 3 = A++ (×1.75). */
  size: 1 | 2 | 3;
  /** "dark": white on black with yellow; "light": black on white with blue. */
  scheme: Theme;
  images: boolean;
  spacing: boolean;
};

const LV_KEY = "lowVision";
export const LV_DEFAULT: LowVision = { on: false, size: 2, scheme: "dark", images: true, spacing: false };

interface Prefs {
  /** The colours in use: the chosen theme, or the low-vision scheme while that version is on. */
  theme: Theme;
  toggleTheme: () => void;
  lang: Lang;
  setLang: (lang: Lang) => void;
  lowVision: LowVision;
  setLowVision: (patch: Partial<LowVision>) => void;
}

const PrefsContext = createContext<Prefs | null>(null);
// The browser tab title in the interface language.
const TITLE: Record<Lang, string> = {
  ru: "Astana Walk — прогулки по городу",
  kk: "Astana Walk — қала бойынша серуен",
  en: "Astana Walk — walks around the city",
};

// index.html sets data-theme/lang before first paint; React starts from the same values.
function read<T extends string>(key: string, allowed: readonly T[], fallback: T): T {
  try {
    const value = localStorage.getItem(key) as T | null;
    if (value && allowed.includes(value)) return value;
  } catch {
    // Storage can be blocked (private mode); defaults still render correctly.
  }
  return fallback;
}

function write(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {
    // Preference is kept for this session only.
  }
}

function readLowVision(): LowVision {
  try {
    const raw = JSON.parse(localStorage.getItem(LV_KEY) || "null");
    if (raw && typeof raw === "object") {
      return {
        on: raw.on === true,
        size: [1, 2, 3].includes(raw.size) ? raw.size : LV_DEFAULT.size,
        scheme: raw.scheme === "light" ? "light" : "dark",
        images: raw.images !== false,
        spacing: raw.spacing === true,
      };
    }
  } catch {
    // Unreadable or blocked storage: the usual version.
  }
  return LV_DEFAULT;
}

export function PrefsProvider({ children }: { children: ReactNode }) {
  // The graphite map interface is dark first; light stays one tap away in "Город".
  const [chosen, setTheme] = useState<Theme>(() => read("uiTheme", ["light", "dark"] as const, "dark"));
  const [lang, setLang] = useState<Lang>(() => read("lang", ["ru", "kk", "en"] as const, "ru"));
  const [lowVision, setLV] = useState<LowVision>(readLowVision);
  const theme = lowVision.on ? lowVision.scheme : chosen;

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.querySelector('meta[name="theme-color"]')?.setAttribute(
      "content",
      lowVision.on ? (theme === "dark" ? "#000000" : "#ffffff") : theme === "dark" ? "#14161b" : "#eef0f3",
    );
  }, [theme, lowVision.on]);

  useEffect(() => write("uiTheme", chosen), [chosen]);

  // The low-vision attributes on <html>: ui.css reads them (index.html sets them before first paint).
  useEffect(() => {
    const d = document.documentElement.dataset;
    if (lowVision.on) {
      d.lv = "on";
      d.lvSize = String(lowVision.size);
      d.lvImages = lowVision.images ? "on" : "off";
      d.lvSpacing = lowVision.spacing ? "wide" : "normal";
    } else {
      delete d.lv;
      delete d.lvSize;
      delete d.lvImages;
      delete d.lvSpacing;
    }
    write(LV_KEY, JSON.stringify(lowVision));
  }, [lowVision]);

  useEffect(() => {
    document.documentElement.lang = lang;
    document.title = TITLE[lang];
    write("lang", lang);
  }, [lang]);

  return (
    <PrefsContext.Provider
      value={{
        theme,
        // In the low-vision version the switch flips its contrast scheme.
        toggleTheme: () =>
          lowVision.on
            ? setLV((v) => ({ ...v, scheme: v.scheme === "dark" ? "light" : "dark" }))
            : setTheme((t) => (t === "dark" ? "light" : "dark")),
        lang,
        setLang,
        lowVision,
        setLowVision: (patch) => setLV((v) => ({ ...v, ...patch })),
      }}
    >
      {children}
    </PrefsContext.Provider>
  );
}

export function usePrefs(): Prefs {
  const value = useContext(PrefsContext);
  if (!value) throw new Error("usePrefs must be used inside PrefsProvider");
  return value;
}
