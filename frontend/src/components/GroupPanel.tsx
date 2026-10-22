import type { GroupFit } from "../api";
import { useT } from "../lib/i18n";

/** "Каждому": how a place suits every member, with the evidence behind each mark. */
export function GroupFitList({ fit }: { fit: GroupFit[] }) {
  const t = useT();
  return (
    <span className="group-fit">
      <b>{t("group.each")}</b>
      <ul>
        {fit.map((m) => (
          <li key={m.name} className={"fit-" + m.level}>
            <strong>{m.name}</strong> <span className={"pill fit-" + m.level}>{t("group.level." + m.level)}</span>
            {!!m.marks.length && (
              <small>{m.marks.map((x) => `${x.label}: ${t("qa.cert." + x.certainty).toLowerCase()}`).join(" · ")}</small>
            )}
          </li>
        ))}
      </ul>
    </span>
  );
}
