export type Provider = "offline" | "gemini";
export interface Source {
  name?: string;
  url?: string;
  collected_at?: string;
  license?: string;
}
export interface Price {
  amount?: number;
  amount_min?: number;
  amount_max?: number;
  currency?: string;
  basis?: string;
}
export interface Route {
  geometry: [number, number][];
  duration_min: number;
  network_duration_min: number;
  network_distance_m: number;
  origin_snap_m: number;
  destination_snap_m: number;
  warnings: string[];
  steps_excluded: boolean;
}
export interface Poi {
  poi_id: string;
  display_name: string;
  latitude: number;
  longitude: number;
  address?: string;
  category: string;
  category_label: string;
  short_description?: string;
  website?: string;
  phone?: string;
  opening_hours?: string;
  /** Day code (Mo…Su) → [open, close] intervals; a missing or empty day is a day off. */
  opening_hours_by_day?: Record<string, [string, string][]> | null;
  hours_status: { status: string; label: string };
  rating?: number;
  ratings_count?: number;
  power_outlets?: boolean;
  quiet_place?: boolean;
  wifi_available?: boolean;
  wheelchair_accessible?: boolean;
  playground?: boolean;
  free_entry?: boolean;
  adult_ticket_price?: Price;
  child_ticket_price?: Price;
  estimated_visit_budget?: Price;
  suggested_visit_duration_min: number;
  arrival_offset_min?: number;
  events?: EventMatch[];
  group_cost?: { size: number; amount: number; currency: string; basis: string };
  total_duration_min?: number;
  route?: Route;
  reasons?: string[];
  warnings?: string[];
  sources?: Source[];
  reservation_required?: boolean;
  booking_required?: boolean;
  access_restrictions?: unknown;
  age_restrictions?: unknown;
  last_updated_at?: string;
  subcategory_label?: string;
  semantic_attributes?: string[];
  standard_ticket_price?: Price;
  entrance_accessible?: boolean;
  ramps?: boolean;
  elevators?: boolean;
  description_type?: string;
  children_facilities?: { feature: string; source_url: string }[];
  pricing?: { entries: PriceEntry[] };
  visit_rules?: {
    constraints: { field: string; value: unknown; source_url?: string }[];
  };
  linked_venue_documents?: { source_id: string; url: string; title?: string }[];
  why?: string | null;
  what_to_do?: string | null;
  explanation?: { generated: boolean; template?: boolean; basis: string[]; note: string };
  evidence?: Record<string, string>;
  /** Group mode: how this place fits each member's wish. */
  group_fit?: GroupFit[];
  /** Shelter from the weather: outdoor / mixed / indoor. */
  exposure?: "outdoor" | "mixed" | "indoor";
  /** Set when current weather changed this place's rank (outdoor pushed down, indoor up). */
  comfort?: "outdoor" | "indoor";
  review_signals?: Record<string, ReviewSignal> | null;
  reviews_considered?: number | null;
}
export interface ReviewSignal {
  status: "supported" | "single_mention" | "mixed" | "contradicted";
  positive: number;
  negative: number;
  mixed: number;
  last_mention?: string;
  quotes: {
    text: string;
    polarity: "positive" | "negative" | "mixed";
    review_id: string;
    date?: string;
    branch_id: string;
  }[];
}
export interface PriceEntry {
  kind: string;
  unit?: string;
  amount?: number;
  amount_min?: number;
  amount_max?: number;
  currency?: string;
  value?: Price;
  source_url?: string;
  label?: string;
}
export interface EventRecord {
  event_id: string;
  event_name: string;
  event_start: string;
  event_end?: string;
  event_location?: string;
  registration_url?: string;
  source_url: string;
  source_name?: string;
}
export interface Meta {
  pois: number;
  search_backend: string;
  categories: Record<string, string>;
  landmarks: Record<string, { name: string; lat: number; lon: number }>;
  default_provider: Provider;
  providers: Record<Provider, { configured: boolean }>;
  dataset_date: string;
  snap_radius_m?: { default: number; min: number; max: number };
}
export interface CityCell {
  lat: number;
  lon: number;
  label: string | null;
  places: number;
  results: Record<
    string,
    { options: number; confirmed: number; nearest_min: number | null; best: string[]; level: "none" | "guess" | "far" | "ok" }
  >;
}
export interface CityAudit {
  generated_for: string;
  cell_step: { lat: number; lon: number };
  scenarios: {
    id: string;
    request: string;
    when: string;
    strict: boolean;
    summary: { none: number; guess: number; far: number; ok: number; cells: number };
  }[];
  cells: CityCell[];
  coverage: {
    places: number;
    with_hours: number;
    with_rating: number;
    with_accessibility: number;
    with_review_signals: number;
    with_price: number;
    events: number;
  };
}
export interface TourCard {
  id: string;
  title: string;
  subtitle: string;
  duration_min: number;
  distance_km: number;
  outdoor: boolean;
  stops: number;
  facts: number;
}
export interface TourStop {
  id: string;
  name: string;
  latitude: number;
  longitude: number;
  radius_m: number;
  outdoor: boolean;
  facts: { text: string; source: string; source_name: string }[];
  tip: string | null;
}
export interface TourLeg {
  geometry: [number, number][];
  duration_min: number;
  network_distance_m: number;
  network: boolean;
}
export interface TourDetail extends Omit<TourCard, "stops" | "facts"> {
  best_season: string | null;
  hours: { text: string; source?: string } | null;
  stops: TourStop[];
  legs: TourLeg[];
  walk_min: number;
  note: string;
}
export interface GroupMember {
  name: string;
  wish: string;
}
export interface GroupFit extends GroupMember {
  level: "match" | "partial" | "none";
  marks: { label: string; certainty: "yes" | "likely" | "unknown" | "no" }[];
}
export interface ComfortFactor {
  code: "frost" | "cold" | "heat" | "wet" | "storm" | "wind" | "smog";
  level: "advisory" | "harsh" | "severe";
  params: Record<string, number | null>;
}
export interface Comfort {
  applies: boolean;
  level: string;
  factors: ComfortFactor[];
}
export interface Air {
  available: boolean;
  aqi?: number;
  pm2_5?: number;
  source?: string;
  source_url?: string;
}
export interface FunnelStep {
  key: "matched" | "nearby" | "reachable" | "open" | "answer";
  count: number;
}
export interface Rejected {
  poi_id: string;
  name: string;
  category?: string;
  latitude?: number;
  longitude?: number;
  code: string;
  params: Record<string, number | string | string[]>;
}
export interface QaAnswer {
  topic: string;
  answer: string;
  certainty: "yes" | "likely" | "unknown" | "no";
  evidence: string[];
  source: string;
}
export interface PlaceAnswer {
  poi_id: string;
  name: string;
  question: string;
  answers: QaAnswer[];
  note: string;
}
export interface Weather {
  available: boolean;
  air?: Air;
  comfort?: Comfort;
  temperature_c?: number;
  feels_like_c?: number;
  wind_kmh?: number;
  /** WMO weather code from Open-Meteo. */
  weather_code?: number | null;
  valid_at?: string;
  fetched_at: string;
  note: string;
  source_url: string;
}
export interface ChatResponse {
  answer: string;
  items: Poi[];
  warnings: string[];
  provider_used: Provider;
  generated_text?: boolean;
  steps: { action: string; result: string }[];
  origin?: { latitude: number; longitude: number; label?: string };
  minutes: number;
  mini_route?: Plan | null;
  events?: EventMatch[];
  group?: { size: number; from_text: boolean; members?: { name: string; wish: string }[] } | null;
  /** What the answer used: start, budget, time, filters, intents (server-composed text). */
  considered?: { label: string; value: string }[];
  comfort?: Comfort & { air?: Air };
  funnel?: FunnelStep[];
  rejected?: Rejected[];
}
export interface EventMatch {
  event_id: string;
  name: string;
  start: string;
  end?: string;
  timed: boolean;
  category?: string;
  venue?: string;
  venue_poi_id?: string | null;
  walk_min?: number | null;
  /** The show starts before the walker can get there on foot. */
  late?: boolean;
  price_from?: number | null;
  currency?: string | null;
  age_group?: string | null;
  source_url?: string;
}
export interface Plan {
  kind?: "mini_route";
  stops: Poi[];
  legs: Route[];
  total_duration_min: number;
  walk_duration_min?: number;
  budget_minutes?: number;
  warnings: string[];
  return_trip_included: boolean;
}
export async function request<T>(
  path: string,
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  const timeout = AbortSignal.timeout(90000);
  const response = await fetch("/api/" + path, {
    method: body === undefined ? "GET" : "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: signal ? AbortSignal.any([signal, timeout]) : timeout,
  });
  if (!response.ok) {
    let detail = "";
    try {
      const data = await response.json();
      detail = typeof data.detail === "string" ? data.detail : "";
    } catch {}
    throw new Error(
      detail || `HTTP ${response.status}`,
    );
  }
  return response.json();
}
export function safeUrl(url?: string) {
  try {
    const u = new URL(url || "");
    return ["http:", "https:"].includes(u.protocol) ? u.href : undefined;
  } catch {
    return undefined;
  }
}
