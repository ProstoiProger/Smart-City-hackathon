import { useState } from "react";
import type { GroupMember } from "../api";
import { Emo } from "../lib/Emo";
import { LANDMARK_EMOJI } from "../lib/emoji";
import { Icon } from "../lib/Icon";
import { has, useT } from "../lib/i18n";
import type { Walk } from "../useWalk";
import { MINUTES, minutesLabel } from "./Planner";

const SIZES = [2, 3, 4, 5, 6];
const AVATARS = ["🙂", "😎", "🤩", "🥳", "😋", "🤗"];
// "" — from the common start (the walk's start point), otherwise a landmark key.
type From = string;

/** A walk for a company: everyone's wish and, when they start apart, where to meet. */
export function Group({ walk, onGo }: { walk: Walk; onGo: () => void }) {
  const t = useT();
  const f = walk.filters;
  const { members, setMembers, ask } = walk.chat;
  const [from, setFrom] = useState<From[]>([]);
  const names = t("ui.group.names").split(",");
  const count = Math.max(2, members.length || f.groupSize);
  const list: GroupMember[] = Array.from({ length: count }, (_, i) => members[i] ?? { name: "", wish: "" });
  const nameOf = (i: number) => (i === 0 ? t("ui.group.you") : list[i].name.trim() || names[(i - 1) % names.length]);
  // The airport is ~18 km out: nobody meets the others on foot from there.
  const landmarks = Object.entries(walk.meta?.landmarks || {}).filter(([key]) => key !== "airport");
  const apart = list.some((_, i) => i > 0 && from[i]);

  const resize = (n: number) => {
    f.setGroupSize(n);
    setMembers(Array.from({ length: n }, (_, i) => members[i] ?? { name: "", wish: "" }));
    setFrom((s) => s.slice(0, n));
  };
  const setMember = (i: number, patch: Partial<GroupMember>) => {
    f.setGroupSize(count);
    setMembers(list.map((m, k) => (k === i ? { ...m, ...patch } : m)));
  };

  const go = () => {
    if (walk.busy) return;
    const wishes = list.map((m) => m.wish.trim()).filter(Boolean);
    let query: string;
    if (apart) {
      // The meeting finder reads people and their places from the text (backend/meet.py):
      // "Где нам встретиться? Алия у MEGA, Данияр у Хан Шатыра. Хотим: кофе".
      const people = list
        .map((_, i) => (i > 0 && from[i] ? `${nameOf(i)} у ${walk.meta?.landmarks[from[i]]?.name ?? from[i]}` : ""))
        .filter(Boolean);
      query = `Где нам встретиться? ${people.join(", ")}.` + (wishes.length ? ` Хотим: ${wishes.join(", ")}.` : "");
    } else {
      query = wishes.length ? wishes.join("; ") : t("group.defaultQuery");
    }
    const company = list.map((m, i) => ({ name: nameOf(i), wish: m.wish }));
    setMembers(company);
    onGo();
    ask(query, true, company);
  };

  return (
    <div className="screen group">
      <h1 className="screen-title">{t("ui.group.title")}</h1>
      <p className="screen-sub">{t("ui.group.sub")}</p>

      <div>
        <h2 className="section-title small">{t("ui.group.count")}</h2>
        <div className="segmented size-seg" role="radiogroup" aria-label={t("ui.group.count")}>
          {SIZES.map((n) => (
            <button key={n} role="radio" aria-checked={count === n} onClick={() => resize(n)}>
              <b>{n}</b>
            </button>
          ))}
        </div>
      </div>

      <ol className="member-list">
        {list.map((m, i) => (
          <li key={i} className="member-card" style={{ animationDelay: `${i * 50}ms` }}>
            <span className="member-avatar">
              <Emo e={AVATARS[i % AVATARS.length]} />
            </span>
            <div className="member-fields">
              {i === 0 ? (
                <strong className="member-name">{t("ui.group.you")}</strong>
              ) : (
                <input
                  className="member-input name"
                  aria-label={t("group.name")}
                  placeholder={names[(i - 1) % names.length]}
                  value={m.name}
                  maxLength={30}
                  onChange={(e) => setMember(i, { name: e.target.value })}
                />
              )}
              <input
                className="member-input"
                aria-label={t("ui.group.wishOf", { name: nameOf(i) })}
                placeholder={t("group.wish")}
                value={m.wish}
                maxLength={200}
                onChange={(e) => setMember(i, { wish: e.target.value })}
              />
              {i > 0 && (
                <label className="member-from">
                  <Icon name="map-pin" />
                  <span className="sr-only">{t("ui.group.fromOf", { name: nameOf(i) })}</span>
                  <select
                    value={from[i] ?? ""}
                    onChange={(e) =>
                      setFrom((s) => {
                        const next = [...s];
                        next[i] = e.target.value;
                        return next;
                      })
                    }
                  >
                    <option value="">{t("ui.group.fromCommon", { name: f.originName })}</option>
                    {landmarks.map(([key, lm]) => (
                      <option key={key} value={key}>
                        {has("lm." + key) ? t("lm." + key) : lm.name}
                      </option>
                    ))}
                  </select>
                </label>
              )}
            </div>
          </li>
        ))}
      </ol>

      <p className={"note" + (apart ? " meet" : "")}>
        <Emo e={apart ? "📍" : "🫶"} /> {apart ? t("ui.group.meetHint") : t("ui.group.fitHint")}
      </p>

      <div>
        <h2 className="section-title small">{t("ui.howMuchTime")}</h2>
        <div className="segmented time-seg" role="radiogroup" aria-label={t("filters.time")}>
          {MINUTES.map((n) => {
            const l = minutesLabel(n, t);
            return (
              <button key={n} role="radio" aria-checked={f.minutes === n} onClick={() => f.setMinutes(n)}>
                <b>{l.value}</b>
                <small>{l.unit}</small>
              </button>
            );
          })}
        </div>
      </div>

      <div className="origin-line">
        <Emo e={(f.landmarkKey && LANDMARK_EMOJI[f.landmarkKey]) || "📍"} />
        <span>{t("ui.group.start", { name: f.originName })}</span>
      </div>

      <div className="cta-dock">
        <button className="cta" disabled={walk.busy} onClick={go}>
          <span className="cta-main">
            <Icon name="users" /> {apart ? t("ui.group.goMeet") : t("group.go")}
          </span>
          <small>{t("ui.group.ctaSub", { n: count })}</small>
        </button>
      </div>
    </div>
  );
}
