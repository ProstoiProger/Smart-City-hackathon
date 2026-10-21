import type { Poi } from "../api";
import { useT } from "../lib/i18n";

/** "Why" and "what to do" for a place; its sources are on the place card. */
export function Explanation({ p }: { p: Poi }) {
  const t = useT();
  if (!p.why && !p.what_to_do) return <span>{p.reasons?.join(" · ")}</span>;
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
    </span>
  );
}
