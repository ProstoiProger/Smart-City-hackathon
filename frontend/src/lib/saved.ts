import type { Poi } from "../api";
import type { HistoryEntry } from "./history";

/** "Мои места": places to go and favourites, and saved walks. Kept only in this browser
 * (localStorage), never sent to the server. Coordinates here are the places' own public
 * coordinates (for the map), never the user's position. */
export type SavedPlace = {
  id: string;
  name: string;
  category: string;
  subcategory?: string;
  latitude: number;
  longitude: number;
  /** "Хочу сходить". */
  want: boolean;
  /** "Избранное". */
  fav: boolean;
  /** Day it was saved (YYYY-MM-DD). */
  date: string;
};
/** A saved walk has the shape of a history entry, so it repeats the same way. */
export type SavedWalk = HistoryEntry;
export type SavedList = "want" | "fav";
/** What a list needs to know about a place. */
export type PlaceRef = Pick<Poi, "poi_id" | "display_name" | "category" | "subcategory" | "latitude" | "longitude">;

export function refOf(p: SavedPlace): PlaceRef {
  return { poi_id: p.id, display_name: p.name, category: p.category, subcategory: p.subcategory, latitude: p.latitude, longitude: p.longitude };
}

const PLACES = "savedPlaces.v1";
const WALKS = "savedWalks.v1";
const ON_MAP = "savedOnMap";
const UNSEEN = "savedUnseenOnly";
export const MAX_PLACES = 200;
export const MAX_WALKS = 50;

function read<T>(key: string): T[] {
  try {
    const raw = JSON.parse(localStorage.getItem(key) || "[]");
    return Array.isArray(raw) ? raw : [];
  } catch {
    return [];
  }
}

function write(key: string, items: unknown[]) {
  try {
    if (items.length) localStorage.setItem(key, JSON.stringify(items));
    else localStorage.removeItem(key);
  } catch {
    // Storage blocked (private mode): the lists live for this page only.
  }
}

export const loadPlaces = () => read<SavedPlace>(PLACES).slice(0, MAX_PLACES);
export const loadWalks = () => read<SavedWalk>(WALKS).slice(0, MAX_WALKS);
export const savePlaces = (items: SavedPlace[]) => write(PLACES, items.slice(0, MAX_PLACES));
export const saveWalks = (items: SavedWalk[]) => write(WALKS, items.slice(0, MAX_WALKS));

export function readSavedFlag(key: "onMap" | "unseen"): boolean {
  try {
    return localStorage.getItem(key === "onMap" ? ON_MAP : UNSEEN) === "1";
  } catch {
    return false;
  }
}

export function writeSavedFlag(key: "onMap" | "unseen", value: boolean) {
  try {
    localStorage.setItem(key === "onMap" ? ON_MAP : UNSEEN, value ? "1" : "0");
  } catch {
    // Kept for this page only.
  }
}

function today() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/** Puts a place on a list or takes it off; a place on neither list is forgotten. */
export function togglePlace(items: SavedPlace[], p: PlaceRef, list: SavedList): SavedPlace[] {
  const old = items.find((x) => x.id === p.poi_id);
  if (!old) {
    const fresh: SavedPlace = {
      id: p.poi_id,
      name: p.display_name,
      category: p.category,
      subcategory: p.subcategory,
      latitude: p.latitude,
      longitude: p.longitude,
      want: list === "want",
      fav: list === "fav",
      date: today(),
    };
    return [fresh, ...items];
  }
  const next = { ...old, [list]: !old[list] };
  return next.want || next.fav ? items.map((x) => (x.id === p.poi_id ? next : x)) : items.filter((x) => x.id !== p.poi_id);
}
