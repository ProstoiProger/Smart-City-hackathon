import { useEffect, useState } from "react";
import { safeUrl, type ChatResponse, type Plan, type Poi } from "../api";
import { categoryLabel, clockAt, eventWhen, groupCost, hoursLabel } from "../lib/format";
import { Emo } from "../lib/Emo";
import { Icon } from "../lib/Icon";
import { locale, useT } from "../lib/i18n";
import { usePrefs } from "../lib/prefs";
import { canSpeak, speak, stopSpeaking } from "../lib/voice";
import type { Walk } from "../useWalk";
import { GroupFitList } from "../components/GroupPanel";
import { ComfortNote } from "../components/Insights";
import { Emoji, HoursBadge, OptionCard, shortName } from "./PlaceCard";
import { Ring, RingLegend, type Segment } from "./Ring";
import { visitedIds } from "../lib/history";

/** One-tap follow-ups for the last answer; each is sent as typed. */
export function followUps(data: ChatResponse): string[] {
  if (data.meeting || !data.items.length) return [];
  if (data.mini_route?.stops.length) {
    const food = data.mini_route.stops.some((s) => s.category === "food_drink");
    return ["quick.otherStops", "quick.closer", ...(food ? ["quick.noCafe"] : []), "quick.removeLast"];
  }
  const food = data.items.some((p) => p.category === "food_drink");
  const mixed = new Set(data.items.map((p) => p.category)).size > 1;
  return ["quick.more", "quick.closer", ...(data.items.length >= 2 ? ["quick.removeSecond"] : []), ...(food && mixed ? ["quick.noCafe"] : [])];
}

function AdviceCard({ data }: { data: ChatResponse }) {
  const t = useT();
  const { lang } = usePrefs();
  const [open, setOpen] = useState(false);
  const [playing, setPlaying] = useState(false);
  useEffect(() => () => stopSpeaking(), []);
  const long = data.answer.length > 160;
  return (
    <section className="advice-card">
      <span className="advice-label">
        <Icon name="sparkles" /> {t("ui.advice")}
      </span>
      <p className={open || !long ? "" : "clamped"}>{data.answer}</p>
      <div className="advice-actions">
        {long && (
          <button className="link-btn" onClick={() => setOpen(!open)}>
            {open ? t("detail.less") : t("detail.more")}
          </button>
        )}
        {canSpeak() && (
          <button
            className="soft-btn"
            aria-pressed={playing}
            onClick={() => {
              if (playing) {
                stopSpeaking();
                setPlaying(false);
                return;
              }
              setPlaying(true);
              speak(data.spoken || data.answer, lang, () => setPlaying(false));
            }}
          >
            <Icon name={playing ? "square" : "volume-2"} /> {playing ? t("tours.stopListen") : t("ui.listen")}
          </button>
        )}
      </div>
    </section>
  );
}

function routeSegments(plan: Plan, t: ReturnType<typeof useT>): { segments: Segment[]; used: number; budget: number } {
  const there = plan.legs.reduce((a, l) => a + l.duration_min, 0);
  const visit = plan.stops.reduce((a, s) => a + s.suggested_visit_duration_min, 0);
  const back = plan.finish ? plan.finish.leg.duration_min : 0;
  const used = plan.finish ? plan.finish.arrival_offset_min : there + visit;
  const budget = plan.budget_minutes ?? Math.ceil(used);
  return {
    used,
    budget,
    segments: [
      { key: "there", value: there, label: t("ui.ring.walk") },
      { key: "visit", value: visit, label: t("ui.ring.visit") },
      ...(plan.finish ? [{ key: "back", value: back, label: t(plan.finish.loop ? "ui.ring.back" : "ui.ring.toFinish") }] : []),
      { key: "reserve", value: Math.max(0, budget - used), label: t("ui.ring.reserve") },
    ],
  };
}

function RouteView({ walk, plan, onOpen, hoverId, setHover }: { walk: Walk; plan: Plan; onOpen: (p: Poi) => void; hoverId: string | null; setHover: (id: string | null) => void }) {
  const t = useT();
  const { trip } = walk;
  const live = !!trip && plan.kind === "mini_route";
  const start = plan.session?.start_at;
  const finish = plan.finish;
  const ring = routeSegments(plan, t);
  return (
    <>
      <section className="route-card">
        <Ring segments={ring.segments} total={ring.budget} size={104} center={Math.round(ring.used)} unit={t("ui.min")} />
        <div className="route-card-side">
          <RingLegend segments={ring.segments} unit={t("ui.min")} />
          {finish && (
            <p className={"finish-line" + (finish.fits ? "" : " late")}>
              <Icon name={finish.loop ? "repeat" : "flag"} />
              {finish.fits
                ? t(finish.loop ? "ui.returnAt" : "ui.arriveAt", { at: clockAt(start, finish.arrival_offset_min), name: finish.label })
                : t("plan.finishLate", { walk: Math.round(finish.leg.duration_min), deadline: clockAt(start, plan.budget_minutes ?? 0) })}
            </p>
          )}
        </div>
      </section>

      {!!trip?.history.length && (
        <ul className="trip-history" aria-label={t("plan.history")}>
          {trip.history.map((h) => (
            <li key={h.id + h.status} className={h.status}>
              <Icon name={h.status === "visited" ? "check" : "x"} />
              <span>{shortName(h.name)}</span>
              <small>{t(h.status === "visited" ? "plan.done" : "plan.closed")}</small>
            </li>
          ))}
        </ul>
      )}

      <ol className="timeline">
        <li className="tl-start">
          <span className="tl-dot start" aria-hidden="true" />
          <span className="tl-body">
            <small>{t("map.start")}</small>
            <strong>{walk.filters.originName}</strong>
            {start && <span className="tl-time">{clockAt(start, live ? trip.elapsed : 0)}</span>}
          </span>
        </li>
        {plan.stops.map((p, i) => (
          <li key={p.poi_id} className={(live && i === 0 ? "next " : "") + (hoverId === p.poi_id ? "active" : "")}>
            <span className="tl-leg">
              <Icon name="footprints" /> {t("ui.walkMin", { n: Math.max(1, Math.ceil(plan.legs[i]?.duration_min ?? 0)) })}
            </span>
            <button className="tl-stop" onClick={() => onOpen(p)} onMouseEnter={() => setHover(p.poi_id)} onMouseLeave={() => setHover(null)}>
              <span className="tl-num">{i + 1}</span>
              <Emoji p={p} />
              <span className="tl-body">
                {live && i === 0 && <em className="next-badge">{t("plan.next")}</em>}
                <strong>{p.display_name}</strong>
                <span className="option-kind">
                  {categoryLabel(p, t)} · {t("ui.visitMin", { n: p.suggested_visit_duration_min })}
                </span>
                <span className="option-meta">
                  {start && p.arrival_offset_min != null && <span className="tl-time">{clockAt(start, p.arrival_offset_min)}</span>}
                  <HoursBadge p={p} />
                </span>
                {p.why && <span className="option-why">{p.why}</span>}
              </span>
            </button>
            {p.backup && (
              <div className={"backup" + (p.backup.fits ? "" : " over")}>
                <span>
                  {t(p.backup.kind === "indoor" ? "plan.backupIndoor" : "plan.backup", {
                    name: shortName(p.backup.display_name),
                    walk: p.backup.walk_from_stop_min,
                  })}{" "}
                  · {p.backup.fits ? t("plan.backupFits") : t("plan.backupOver", { n: Math.max(1, p.backup.delta_min) })}
                </span>
                {live && (
                  <button className="soft-btn" disabled={walk.busy} onClick={() => walk.replan("swap", p)}>
                    <Icon name="rotate-ccw" /> {t("trip.swap")}
                  </button>
                )}
              </div>
            )}
          </li>
        ))}
        {finish && (
          <li className="tl-finish">
            <span className="tl-leg">
              <Icon name="footprints" /> {t("ui.walkMin", { n: Math.max(1, Math.ceil(finish.leg.duration_min)) })}
            </span>
            <span className="tl-dot finish" aria-hidden="true">
              <Emo e={finish.loop ? "🏠" : "🏁"} />
            </span>
            <span className="tl-body">
              <small>{t(finish.loop ? "plan.backToStart" : "map.finish")}</small>
              <strong>{finish.loop ? walk.filters.originName : finish.label}</strong>
              {start && <span className="tl-time">{clockAt(start, finish.arrival_offset_min)}</span>}
            </span>
          </li>
        )}
      </ol>

      {!plan.stops.length && !finish && <p className="empty-note">{trip?.history.length ? t("plan.ended") : t("plan.notFound")}</p>}

      {live && (
        <section className="trip-panel">
          {trip.note && (
            <p className="trip-note" role="status">
              {trip.note}
            </p>
          )}
          <strong>{t("trip.title")}</strong>
          <div className="trip-grid">
            {!!plan.stops.length && (
              <button className="trip-btn primary" disabled={walk.busy} onClick={walk.visitStop}>
                <Emo e="✅" />
                {t("trip.visited")}
              </button>
            )}
            {!!plan.stops.length && (
              <button className="trip-btn" disabled={walk.busy} onClick={() => walk.replan("closed")}>
                <Emo e="🚧" />
                {t("trip.closed")}
              </button>
            )}
            <button className="trip-btn" disabled={walk.busy} onClick={() => walk.replan("delay")}>
              <Emo e="⏳" />
              {t("trip.delay")}
            </button>
            <button className="trip-btn" disabled={walk.busy} aria-pressed={trip.flags.includes("indoor")} onClick={() => walk.replan("cold")}>
              <Emo e="🥶" />
              {t("trip.cold")}
            </button>
            <button className="trip-btn" disabled={walk.busy} aria-pressed={trip.flags.includes("rest")} onClick={() => walk.replan("tired")}>
              <Emo e="😮‍💨" />
              {t("trip.tired")}
            </button>
          </div>
          <small>{t("trip.hint")}</small>
        </section>
      )}
      {plan.warnings.map((w) => (
        <p key={w} className="note warn">
          {w}
        </p>
      ))}
    </>
  );
}

export function Events({ data }: { data: ChatResponse }) {
  const t = useT();
  const { lang } = usePrefs();
  if (!data.events?.length) return null;
  return (
    <section className="events-card">
      <strong>
        <Emo e="🎟️" /> {t("events.title")}
      </strong>
      <ul>
        {data.events.map((e) => (
          <li key={e.event_id}>
            <b>{e.name}</b>
            <span>
              {eventWhen(e, t)}
              {e.venue ? " · " + e.venue : ""}
              {e.walk_min != null ? " · " + t("events.walk", { n: e.walk_min }) : ""}
              {e.late ? " · " + t("events.late") : ""}
              {e.price_from != null ? " · " + t("events.price", { amount: `${e.price_from.toLocaleString(locale(lang))} ₸` }) : ""}
            </span>
            {safeUrl(e.source_url) && (
              <a className="link-btn" href={safeUrl(e.source_url)} target="_blank" rel="noreferrer">
                {t("events.source")} <Icon name="external-link" />
              </a>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

/** Small follow-up composer under an answer: "ещё", "поближе", "второе замени". */
export function FollowUp({ walk, data }: { walk: Walk; data: ChatResponse | null }) {
  const t = useT();
  const [text, setText] = useState("");
  const chips = data && !walk.busy ? followUps(data) : [];
  return (
    <div className="follow-up">
      {chips.length > 0 && (
        <div className="quick-replies" role="group" aria-label={t("quick.label")}>
          {chips.map((key) => (
            <button key={key} onClick={() => walk.chat.ask(t(key))}>
              {t(key)}
            </button>
          ))}
        </div>
      )}
      <form
        className="ask-field small"
        onSubmit={(e) => {
          e.preventDefault();
          if (!text.trim()) return;
          walk.chat.ask(text);
          setText("");
        }}
      >
        <label className="sr-only" htmlFor="follow-input">
          {t("ui.refine")}
        </label>
        <input id="follow-input" value={text} onChange={(e) => setText(e.target.value)} placeholder={t("ui.refine")} maxLength={1500} autoComplete="off" />
        <button className="send-btn" disabled={walk.busy || !text.trim()} aria-label={t("chat.send")}>
          <Icon name="send-horizontal" />
        </button>
      </form>
    </div>
  );
}

export function Results({
  walk,
  pending,
  onBack,
  onOpen,
  hoverId,
  setHover,
}: {
  walk: Walk;
  /** A new request is on its way: the previous answer is not shown meanwhile. */
  pending: boolean;
  onBack: () => void;
  onOpen: (p: Poi) => void;
  hoverId: string | null;
  setHover: (id: string | null) => void;
}) {
  const t = useT();
  const { lang } = usePrefs();
  const data = pending ? null : walk.answer;
  const plan = pending ? undefined : walk.plan;
  const lastText = walk.chat.messages[walk.chat.messages.length - 1];
  const minutes = plan?.budget_minutes ?? data?.minutes ?? walk.filters.minutes;
  const loop = plan ? !!plan.finish?.loop : walk.filters.walkMode === "loop";
  const routeShown = !!plan && (plan.stops.length > 0 || !!plan.finish || !!walk.trip?.history.length);
  const seen = new Set(visitedIds(walk.history.entries));
  const shownIds = (routeShown ? plan!.stops : (data?.items ?? [])).map((p) => p.poi_id).join();
  const walkSaved = !!shownIds && walk.saved.walks.some((w) => w.places.map((p) => p.id).join() === shownIds);
  const start = plan?.session?.start_at;
  const share = async () => {
    const lines = [
      t(routeShown ? "ui.routeTitle" : "ui.optionsTitle", { n: minutes }),
      ...(routeShown ? plan!.stops : data?.items ?? []).map((p, i) => `${i + 1}. ${shortName(p.display_name)}`),
    ].join("\n");
    try {
      if (navigator.share) await navigator.share({ title: "Astana Walk", text: lines });
      else await navigator.clipboard.writeText(lines);
      walk.notify(t("ui.shared"));
    } catch {
      // The user closed the share sheet.
    }
  };

  return (
    <div className="screen results">
      <div className="screen-top">
        <button className="back-btn" onClick={onBack}>
          <Icon name="arrow-left" /> {t("ui.change")}
        </button>
        <span className="spacer" />
        {!pending && shownIds && (
          <button
            className={"round-btn mark-btn want" + (walkSaved ? " on" : "")}
            aria-pressed={walkSaved}
            aria-label={t("ui.saved.saveWalk")}
            title={t("ui.saved.saveWalk")}
            disabled={walkSaved}
            onClick={() => {
              walk.saved.saveWalk();
              walk.notify(t("ui.saved.walkSaved"));
            }}
          >
            <Icon name="bookmark" />
          </button>
        )}
        {(data || routeShown) && (
          <button className="round-btn" onClick={share} aria-label={t("ui.share")} title={t("ui.share")}>
            <Icon name="share-2" />
          </button>
        )}
      </div>
      <h1 className="screen-title">{t(routeShown || (pending && loop) ? "ui.routeTitle" : "ui.optionsTitle", { n: minutes })}</h1>
      {walk.busy && (
        <p className="results-busy" role="status">
          <i aria-hidden="true" /> {t(pending ? "ui.searching" : "ui.thinking")}
        </p>
      )}
      <p className="screen-sub">
        <Icon name="map-pin" /> {t("ui.startAt", { name: walk.filters.originName })}
        {plan?.finish && start ? " · " + t(plan.finish.loop ? "ui.backByShort" : "ui.endByShort", { at: clockAt(start, plan.finish.arrival_offset_min) }) : ""}
      </p>

      {data && <AdviceCard key={data.answer} data={data} />}
      {!data && !pending && lastText?.role === "assistant" && !routeShown && <p className="note warn">{lastText.text}</p>}
      {data && <ComfortNote data={data} />}
      {data?.warnings.map((w) => (
        <p key={w} className="note warn">
          <Icon name="info" /> {w}
        </p>
      ))}

      {routeShown ? (
        <RouteView walk={walk} plan={plan!} onOpen={onOpen} hoverId={hoverId} setHover={setHover} />
      ) : (
        <div className="options">
          {data?.items.map((p, i) => (
            <div key={p.poi_id} className="option-wrap">
              <OptionCard
                p={p}
                index={i}
                minutes={minutes}
                loop={loop}
                active={hoverId === p.poi_id}
                seen={seen.has(p.poi_id)}
                onOpen={() => onOpen(p)}
                onHover={(on) => setHover(on ? p.poi_id : null)}
              />
              {p.meeting && (
                <p className="option-extra">
                  <Icon name="users" /> {p.meeting.map((x) => t("meet.walk", { name: x.name, n: x.walk_min })).join(" · ")}
                </p>
              )}
              {!!p.group_fit?.length && <GroupFitList fit={p.group_fit} />}
              {groupCost(p, t, locale(lang)) && <p className="option-extra">{groupCost(p, t, locale(lang))}</p>}
              {p.events?.map((e) => (
                <p key={e.event_id} className="option-extra">
                  <Emo e="🎟️" /> {t("events.here", { name: e.name, when: eventWhen(e, t) })}
                </p>
              ))}
              {!!p.warnings?.length && <p className="option-extra warn">{p.warnings[0]}</p>}
              <span className="sr-only">{hoursLabel(p, t)}</span>
            </div>
          ))}
          {data && !data.items.length && <p className="empty-note">{t("results.emptyHint")}</p>}
        </div>
      )}

      {data && <Events data={data} />}
      {!pending && <FollowUp walk={walk} data={data} />}
    </div>
  );
}
