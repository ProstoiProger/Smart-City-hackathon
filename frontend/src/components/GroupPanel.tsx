import type { GroupFit, GroupMember } from "../api";
import { Icon } from "../lib/Icon";
import { useT } from "../lib/i18n";

const MAX = 6;

/** Each member's own wish; the assistant looks for the place where nobody is left out. */
export function GroupPanel({
  members,
  setMembers,
  busy,
  onGo,
}: {
  members: GroupMember[];
  setMembers: (m: GroupMember[]) => void;
  busy: boolean;
  onGo: () => void;
}) {
  const t = useT();
  const set = (i: number, patch: Partial<GroupMember>) =>
    setMembers(members.map((m, k) => (k === i ? { ...m, ...patch } : m)));
  const ready = members.length >= 2 && members.some((m) => m.wish.trim());
  return (
    <details className="group-panel" open={members.length > 0}>
      <summary>
        <Icon name="users" /> {t("group.title")}
      </summary>
      <p className="group-hint">{t("group.hint")}</p>
      <ul>
        {members.map((m, i) => (
          <li key={i}>
            <input
              aria-label={t("group.name")}
              placeholder={t("group.name")}
              value={m.name}
              maxLength={30}
              onChange={(e) => set(i, { name: e.target.value })}
            />
            <input
              aria-label={t("group.wish")}
              placeholder={t("group.wish")}
              value={m.wish}
              maxLength={200}
              onChange={(e) => set(i, { wish: e.target.value })}
            />
            <button
              type="button"
              className="icon-button"
              aria-label={t("group.remove")}
              title={t("group.remove")}
              onClick={() => setMembers(members.filter((_, k) => k !== i))}
            >
              <Icon name="x" />
            </button>
          </li>
        ))}
      </ul>
      <div className="group-actions">
        <button
          type="button"
          className="icon-button"
          disabled={members.length >= MAX}
          onClick={() => setMembers([...members, { name: "", wish: "" }])}
        >
          <Icon name="plus" /> {members.length >= MAX ? t("group.max") : t("group.add")}
        </button>
        <button type="button" className="primary icon-button" disabled={busy || !ready} onClick={onGo}>
          {t("group.go")}
        </button>
      </div>
    </details>
  );
}

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
