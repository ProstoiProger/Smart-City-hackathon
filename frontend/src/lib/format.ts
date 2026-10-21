import type { ComfortFactor, EventMatch, Poi, Price, PriceEntry, Rejected } from "../api";
import { has, type T, type Vars } from "./i18n";

function amount(value: number, currency: string | undefined, loc: string) {
  return `${value.toLocaleString(loc)} ${currency || "KZT"}`;
}

export function money(p: Poi, t: T, loc: string): string {
  if (p.free_entry === true) return t("money.free");
  if (p.adult_ticket_price?.amount != null)
    return t("money.adult", { v: amount(p.adult_ticket_price.amount, p.adult_ticket_price.currency, loc) });
  if (p.standard_ticket_price?.amount != null)
    return t("money.standard", { v: amount(p.standard_ticket_price.amount, p.standard_ticket_price.currency, loc) });
  const budget: Price | undefined = p.estimated_visit_budget;
  if (budget?.amount_min != null) return t("money.average", { v: amount(budget.amount_min, budget.currency, loc) });
  return t("money.unknown");
}

export function tariff(entry: PriceEntry, t: T, loc: string): string {
  const label = entry.label || (has("tariff." + entry.kind) ? t("tariff." + entry.kind) : t("tariff.other"));
  const low = entry.amount ?? entry.amount_min ?? entry.value?.amount ?? entry.value?.amount_min;
  const high = entry.amount_max ?? entry.value?.amount_max;
  const currency = entry.currency || entry.value?.currency || "";
  const value =
    low != null
      ? low.toLocaleString(loc) + (high != null && high !== low ? "–" + high.toLocaleString(loc) : "") + " " + currency
      : t("tariff.seeSource");
  const unit = entry.unit && has("unit." + entry.unit) ? " / " + t("unit." + entry.unit) : "";
  return `${label}: ${value}${unit}`;
}

export function ruleLabel(field: string, t: T): string {
  return has("rule." + field) ? t("rule." + field) : t("rule.other");
}

export function ruleValue(value: unknown, t: T): string {
  if (value === true) return t("common.yes");
  if (value === false) return t("common.no");
  if (typeof value === "string") return value;
  if (Array.isArray(value)) return value.filter((v) => typeof v === "string").join("; ");
  return t("rule.inSource");
}

/** Category from the stable code; the backend label is the fallback for unknown codes. */
export function categoryLabel(p: Pick<Poi, "category" | "category_label">, t: T): string {
  return has("cat." + p.category) ? t("cat." + p.category) : p.category_label;
}

export function hoursLabel(p: Pick<Poi, "hours_status">, t: T): string {
  const key = "hours." + p.hours_status.status;
  return has(key) ? t(key) : p.hours_status.label;
}

export function yesNo(value: boolean | undefined | null, t: T): string {
  return value === true ? t("common.yes") : value === false ? t("common.no") : t("common.unknown");
}

function day(iso: string) {
  return `${iso.slice(8, 10)}.${iso.slice(5, 7)}`;
}

/** "23.10, 19:00" for timed events, "до 31.10" for running exhibitions. */
export function eventWhen(e: EventMatch, t: T): string {
  if (e.timed) return `${day(e.start)}, ${e.start.slice(11, 16)}`;
  return t("events.until", { date: day(e.end || e.start) });
}

export function groupCost(p: Poi, t: T, loc: string): string | null {
  const c = p.group_cost;
  if (!c) return null;
  const amount = c.amount === 0 ? "0" : `${c.amount.toLocaleString(loc)} ${c.currency === "KZT" ? "₸" : c.currency}`;
  return t("group.cost", { n: c.size, amount, basis: t("group.basis." + c.basis) });
}

/** Walking and visit time for a chat recommendation. */
export function itemTiming(p: Poi, t: T): string {
  return p.route
    ? t("chat.itemMeta", { walk: Math.ceil(p.route.duration_min), visit: p.suggested_visit_duration_min })
    : t("chat.itemVisit", { visit: p.suggested_visit_duration_min });
}

const numbers = (params: Record<string, unknown>): Vars =>
  Object.fromEntries(Object.entries(params).filter(([, v]) => typeof v === "number")) as Vars;

export function comfortLabel(f: ComfortFactor, t: T): string {
  return t("comfort.f." + f.code, numbers(f.params));
}

/** Why a near-miss place was left out, worded from the server's code and numbers. */
export function rejectedLabel(r: Rejected, t: T): string {
  const params: Vars = { ...numbers(r.params) };
  if (typeof r.params.at === "string") params.at = r.params.at;
  if (typeof r.params.other === "string") params.other = r.params.other;
  if (Array.isArray(r.params.attrs)) params.attrs = r.params.attrs.join(", ");
  return has("why." + r.code) ? t("why." + r.code, params) : r.code;
}

/** "HH:MM" of `offset` minutes after an ISO start ("2026-10-22T13:00+05:00"), in the start's own time zone. */
export function clockAt(start: string | undefined, offset: number): string {
  const m = /T(\d{2}):(\d{2})/.exec(start || "");
  if (!m) return "";
  const total = (((+m[1] * 60 + +m[2] + Math.round(offset)) % 1440) + 1440) % 1440;
  return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
}
