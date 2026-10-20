import type { Poi, Price, PriceEntry } from "../api";
import { has, type T } from "./i18n";

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
