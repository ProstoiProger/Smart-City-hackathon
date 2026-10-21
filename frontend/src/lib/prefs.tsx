import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

export type Theme = "light" | "dark";
export type Lang = "ru" | "kk" | "en";

interface Prefs {
  theme: Theme;
  toggleTheme: () => void;
  lang: Lang;
  setLang: (lang: Lang) => void;
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

export function PrefsProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<Theme>(() =>
    read(
      "theme",
      ["light", "dark"] as const,
      window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light",
    ),
  );
  const [lang, setLang] = useState<Lang>(() => read("lang", ["ru", "kk", "en"] as const, "ru"));

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.querySelector('meta[name="theme-color"]')?.setAttribute("content", theme === "dark" ? "#0f1613" : "#173d32");
    write("theme", theme);
  }, [theme]);

  useEffect(() => {
    document.documentElement.lang = lang;
    document.title = TITLE[lang];
    write("lang", lang);
  }, [lang]);

  return (
    <PrefsContext.Provider
      value={{
        theme,
        toggleTheme: () => setTheme((t) => (t === "dark" ? "light" : "dark")),
        lang,
        setLang,
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
