import type { Poi } from "../api";

/** Walk history: kept only in this browser (localStorage), never sent to the server.
 * No coordinates: the start is a landmark key or a generic label ("Точка на карте",
 * "Моё местоположение"), so the history cannot reveal where someone lives. */
export type HistoryPlace = {
  id: string;
  name: string;
  category: string;
  subcategory?: string;
  status: "planned" | "visited" | "closed";
};
export type HistoryEntry = {
  id: string;
  /** Day only (YYYY-MM-DD): the exact time of leaving is not kept. */
  date: string;
  minutes: number;
  mode: "loop" | "oneway";
  /** A walk of stops in order, or options to choose from. */
  route: boolean;
  /** Landmark key, or a label: "i18n:…" for a picked point or geolocation, a public place name from the chat. */
  start: { key?: string; label: string };
  /** The words of the request, without the conversation. */
  wish: string;
  places: HistoryPlace[];
};

const KEY = "walkHistory.v1";
const ON = "walkHistoryOn";
const NEW_ONLY = "walkNewOnly";
export const MAX_ENTRIES = 20;
const MAX_DAYS = 30;
const MAX_WISH = 120;

function today() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function fresh(entries: HistoryEntry[]) {
  const oldest = Date.now() - MAX_DAYS * 86400000;
  return entries.filter((e) => new Date(e.date + "T12:00").getTime() >= oldest).slice(0, MAX_ENTRIES);
}

export function loadHistory(): HistoryEntry[] {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) || "[]");
    return Array.isArray(raw) ? fresh(raw) : [];
  } catch {
    return [];
  }
}

export function saveHistory(entries: HistoryEntry[]) {
  try {
    if (entries.length) localStorage.setItem(KEY, JSON.stringify(fresh(entries)));
    else localStorage.removeItem(KEY);
  } catch {
    // Storage blocked (private mode): the history lives for this page only.
  }
}

export function readFlag(key: "on" | "newOnly"): boolean {
  try {
    const v = localStorage.getItem(key === "on" ? ON : NEW_ONLY);
    return key === "on" ? v !== "0" : v === "1";
  } catch {
    return key === "on";
  }
}

export function writeFlag(key: "on" | "newOnly", value: boolean) {
  try {
    localStorage.setItem(key === "on" ? ON : NEW_ONLY, value ? "1" : "0");
  } catch {
    // Kept for this page only.
  }
}

export function newEntry(fields: Omit<HistoryEntry, "id" | "date" | "places" | "wish"> & { wish: string; places: Poi[] }): HistoryEntry {
  return {
    ...fields,
    id: Math.random().toString(36).slice(2, 10),
    date: today(),
    wish: fields.wish.trim().slice(0, MAX_WISH),
    places: fields.places.map(toPlace),
  };
}

export function toPlace(p: Poi): HistoryPlace {
  return { id: p.poi_id, name: p.display_name, category: p.category, subcategory: p.subcategory, status: "planned" };
}

/** New places join as planned; places already there keep what happened to them. */
export function mergePlaces(old: HistoryPlace[], now: Poi[]): HistoryPlace[] {
  const done = old.filter((p) => p.status !== "planned");
  const seen = new Set(done.map((p) => p.id));
  return [...done, ...now.filter((p) => !seen.has(p.poi_id)).map(toPlace)];
}

/** Places visited on earlier walks: left out when "только новые места" is on. */
export function visitedIds(entries: HistoryEntry[]): string[] {
  const ids = new Set<string>();
  for (const e of entries) for (const p of e.places) if (p.status === "visited") ids.add(p.id);
  return [...ids].slice(0, 100);
}
