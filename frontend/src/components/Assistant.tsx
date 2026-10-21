import { useEffect, useRef, useState } from "react";
import { safeUrl } from "../api";
import { eventWhen, groupCost, itemTiming } from "../lib/format";
import { Icon } from "../lib/Icon";
import { locale, useT } from "../lib/i18n";
import { usePrefs } from "../lib/prefs";
import { canListen, canSpeak, speak, stopSpeaking, useDictation, warmUpVoices } from "../lib/voice";
import type { Walk } from "../useWalk";
import { Explanation } from "./Explanation";
import { GroupFitList, GroupPanel } from "./GroupPanel";
import { ComfortNote, WhyNot } from "./Insights";

const SUGGESTIONS = ["chat.s1", "chat.s2", "chat.s3"];
const VOICE_ERRORS = { denied: "chat.voiceDenied", "no-speech": "chat.voiceNoSpeech", failed: "chat.voiceFailed" } as const;

function useSpokenReplies(): [boolean, (v: boolean) => void] {
  const [on, setOn] = useState(() => {
    try {
      return localStorage.getItem("spokenReplies") !== "0";
    } catch {
      return true;
    }
  });
  const set = (v: boolean) => {
    setOn(v);
    try {
      localStorage.setItem("spokenReplies", v ? "1" : "0");
    } catch {
      // Preference is kept for this session only.
    }
  };
  return [on, set];
}

export function Assistant({ walk, onHide }: { walk: Walk; onHide: () => void }) {
  const t = useT();
  const { lang } = usePrefs();
  const { messages, miniRoute, setMiniRoute, ask, members, setMembers } = walk.chat;
  const [text, setText] = useState("");
  const [spoken, setSpoken] = useSpokenReplies();
  const end = useRef<HTMLDivElement>(null);
  const draft = useRef("");
  const voiceTurn = useRef(false);
  const lastSpoken = useRef(0);

  useEffect(() => {
    end.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [messages]);

  const send = (value: string, byVoice = false) => {
    if (!value.trim() || walk.busy) return;
    stopSpeaking();
    voiceTurn.current = byVoice;
    setText("");
    ask(value);
  };

  const mic = useDictation(
    lang,
    (heard) => setText(draft.current ? draft.current + " " + heard : heard),
    (heard) => send(draft.current ? draft.current + " " + heard : heard, true),
  );
  const micOn = canListen();

  useEffect(() => {
    warmUpVoices();
    return stopSpeaking;
  }, []);

  // Every reply plays its short spoken summary once (for blind and low-vision users);
  // the speaker toggle by the input turns this off.
  useEffect(() => {
    const last = messages[messages.length - 1];
    if (!last || last.role !== "assistant" || last.id === lastSpoken.current) return;
    lastSpoken.current = last.id;
    if (spoken && canSpeak()) speak(last.data?.spoken || last.text, lang);
    voiceTurn.current = false;
  }, [messages, spoken, lang]);

  const toggleMic = () => {
    if (mic.listening) return mic.stop();
    stopSpeaking();
    draft.current = text.trim();
    mic.start();
  };

  const toggleSpoken = () => {
    if (spoken) stopSpeaking();
    setSpoken(!spoken);
  };

  return (
    <aside className="assistant" aria-label={t("nav.chat")}>
      <div className="assistant-head">
        <div className="assistant-title">
          <span aria-hidden="true">
            <Icon name="sparkles" />
          </span>
          <div>
            <h2>{t("nav.chat")}</h2>
            <p>{t("chat.subtitle")}</p>
          </div>
          <button className="chat-hide" aria-label={t("chat.hide")} title={t("chat.hide")} onClick={onHide}>
            <Icon name="chevron-right" />
          </button>
        </div>
      </div>
      <div className="conversation" aria-live="polite">
        {!messages.length && (
          <div className="chat-welcome">
            <h3>
              {t("chat.welcome1")}
              <br />
              {t("chat.welcome2")}
            </h3>
            <p>{t("chat.welcomeHint")}</p>
            <div className="suggestions">
              {SUGGESTIONS.map((key) => (
                <button key={key} onClick={() => send(t(key))}>
                  {t(key)}
                  <span aria-hidden="true">
                    <Icon name="arrow-up-right" />
                  </span>
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((m) => (
          <article key={m.id} className={"message " + m.role}>
            <small>
              {m.role === "user" ? t("chat.you") : t("chat.assistant", { p: m.data?.provider_used || t("chat.searchProvider") })}
            </small>
            <p>{m.text}</p>
            {!!m.data?.considered?.length && (
              <div className="considered">
                <strong>
                  <Icon name="info" /> {t("chat.considered")}
                </strong>
                <dl>
                  {m.data.considered.map((c) => (
                    <div key={c.label}>
                      <dt>{c.label}</dt>
                      <dd>{c.value}</dd>
                    </div>
                  ))}
                </dl>
              </div>
            )}
            {m.data && <ComfortNote data={m.data} />}
            {m.data?.warnings.map((w) => (
              <p className="warning" key={w}>
                {w}
              </p>
            ))}
            {m.data?.mini_route && (
              <div className="mini-route">
                <strong>
                  <Icon name="route" />{" "}
                  {t("route.title", {
                    n: m.data.mini_route.stops.length,
                    total: Math.round(m.data.mini_route.total_duration_min),
                    budget: m.data.mini_route.budget_minutes ?? m.data.minutes,
                  })}
                </strong>
                <small>{t("route.walk", { n: Math.round(m.data.mini_route.walk_duration_min ?? 0) })}</small>
                <button className="icon-button" onClick={() => walk.showPlan(m.data!.mini_route!)}>
                  <Icon name="map" />
                  {t("route.show")}
                </button>
              </div>
            )}
            {m.data?.items.map((p, i) => (
              <button key={p.poi_id} className="chat-place" onClick={() => walk.selectPlace(p)}>
                {m.data?.mini_route && (
                  <span className="route-meta">
                    {t("route.stop", {
                      order: i + 1,
                      at: m.data.mini_route.stops[i]?.arrival_offset_min ?? 0,
                      walk: Math.round(m.data.mini_route.legs[i]?.duration_min ?? 0),
                      visit: m.data.mini_route.stops[i]?.suggested_visit_duration_min ?? p.suggested_visit_duration_min,
                    })}
                  </span>
                )}
                {!m.data?.mini_route && <span className="route-meta">{itemTiming(p, t)}</span>}
                <strong>{p.display_name}</strong>
                <Explanation p={p} />
                {!!p.group_fit?.length && <GroupFitList fit={p.group_fit} />}
                {p.comfort && (
                  <small className={"comfort-tag " + p.comfort}>
                    <Icon name={p.comfort === "indoor" ? "check" : "cloud-sun"} /> {t("comfort." + p.comfort + "Note")}
                  </small>
                )}
                {p.events?.map((e) => (
                  <span key={e.event_id} className="event-meta">
                    <Icon name="calendar-clock" /> {t("events.here", { name: e.name, when: eventWhen(e, t) })}
                  </span>
                ))}
                {groupCost(p, t, locale(lang)) && <span className="group-cost">{groupCost(p, t, locale(lang))}</span>}
                {p.warnings?.map((w) => (
                  <small key={w}>{w}</small>
                ))}
              </button>
            ))}
            {!!m.data?.events?.length && (
              <div className="chat-events">
                <strong>
                  <Icon name="calendar-clock" /> {t("events.title")}
                </strong>
                <ul>
                  {m.data.events.map((e) => (
                    <li key={e.event_id}>
                      <b>{e.name}</b>
                      <span>
                        {eventWhen(e, t)}
                        {e.venue ? " · " + e.venue : ""}
                        {e.walk_min != null ? " · " + t("events.walk", { n: e.walk_min }) : ""}
                        {e.late ? " · " + t("events.late") : ""}
                        {e.price_from != null
                          ? " · " + t("events.price", { amount: `${e.price_from.toLocaleString(locale(lang))} ₸` })
                          : ""}
                        {e.age_group ? " · " + e.age_group : ""}
                      </span>
                      {safeUrl(e.source_url) && (
                        <a className="icon-button" href={safeUrl(e.source_url)} target="_blank" rel="noreferrer">
                          {t("events.source")}
                          <Icon name="external-link" />
                        </a>
                      )}
                    </li>
                  ))}
                </ul>
                <small>{t("events.note")}</small>
              </div>
            )}
            {m.data && <WhyNot data={m.data} />}
            {m.data && (
              <details className="trace">
                <summary>{t("chat.trace")}</summary>
                <ol>
                  {m.data.steps.map((s) => (
                    <li key={s.action}>
                      <strong>{s.action}</strong>
                      <span>{s.result}</span>
                    </li>
                  ))}
                </ol>
              </details>
            )}
          </article>
        ))}
        {walk.busy && (
          <p className="thinking" role="status">
            {t("chat.thinking")}
          </p>
        )}
        <div ref={end} />
      </div>
      <GroupPanel
        members={members}
        setMembers={setMembers}
        busy={walk.busy}
        onGo={() => ask(text.trim() || t("group.defaultQuery"))}
      />
      <label className="check route-toggle" title={t("chat.miniRouteHint")}>
        <input type="checkbox" checked={miniRoute} onChange={(e) => setMiniRoute(e.target.checked)} />
        <Icon name="route" />
        {t("chat.miniRoute")}
      </label>
      <form
        className="chat-compose"
        onSubmit={(e) => {
          e.preventDefault();
          send(text);
        }}
      >
        <label className="sr-only" htmlFor="chat-input">
          {t("chat.ask")}
        </label>
        <textarea
          id="chat-input"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            // Enter sends, Shift+Enter keeps a new line.
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              send(text);
            }
          }}
          placeholder={t("chat.ask")}
          maxLength={1500}
          rows={2}
        />
        {micOn && (
          <button
            type="button"
            className={"voice-btn icon-button" + (mic.listening ? " listening" : "")}
            aria-pressed={mic.listening}
            aria-label={mic.listening ? t("chat.voiceStop") : t("chat.voiceStart")}
            title={mic.listening ? t("chat.voiceStop") : t("chat.voiceStart")}
            disabled={walk.busy}
            onClick={toggleMic}
          >
            <Icon name="mic" />
          </button>
        )}
        <button className="primary icon-button" disabled={walk.busy || !text.trim()} aria-label={t("chat.send")}>
          <Icon name="send-horizontal" />
        </button>
      </form>
      {(micOn || canSpeak()) && (
        <div className="voice-bar">
          <p className={"voice-status" + (mic.error ? " error" : "")} role="status">
            {mic.listening ? t("chat.listening") : mic.error ? t(VOICE_ERRORS[mic.error]) : ""}
          </p>
          {canSpeak() && (
            <button
              type="button"
              className="voice-speak icon-button"
              aria-pressed={spoken}
              aria-label={spoken ? t("chat.speakOn") : t("chat.speakOff")}
              title={spoken ? t("chat.speakOn") : t("chat.speakOff")}
              onClick={toggleSpoken}
            >
              <Icon name={spoken ? "volume-2" : "volume-x"} />
            </button>
          )}
        </div>
      )}
      <p className="privacy">
        {t("chat.privacy")}
        {micOn ? " " + t("chat.voicePrivacy") : ""}
      </p>
    </aside>
  );
}
