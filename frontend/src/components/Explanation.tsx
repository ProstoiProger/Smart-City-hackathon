import type { Poi } from "../api";
import { useT } from "../lib/i18n";

/** "Why" and "what to do" with an honest label: model text vs. data, and what it was based on. */
export function Explanation({ p }: { p: Poi }) {
  const t = useT();
  if (!p.why && !p.what_to_do) return <span>{p.reasons?.join(" · ")}</span>;
  const generated = p.explanation?.generated;
  // Data-based templates (no Gemini) still suggest a plan: it is an idea, not a fact.
  const idea = generated || p.explanation?.template;
  const basis = p.explanation?.basis ?? [];
  return (
    <span className="explanation">
      {p.why && (
        <span>
          <b>{t("expl.why")}</b> {p.why}
        </span>
      )}
      {p.what_to_do && (
        <span>
          <b>{t("expl.todo")}</b> {p.what_to_do}
        </span>
      )}
      <small className="source-tag">
        {generated ? t("expl.gemini") : t("expl.data")}
        {basis.length > 0 && t("expl.basis", { list: basis.map((b) => t("basis." + b)).join(", ") })}
        {idea && t("expl.idea")}
      </small>
    </span>
  );
}
