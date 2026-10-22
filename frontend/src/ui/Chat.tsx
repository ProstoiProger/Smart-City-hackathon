import { useEffect, useRef, useState } from "react";
import type { Plan, Poi } from "../api";
import { categoryLabel, clockAt, groupCost, itemTiming } from "../lib/format";
import { Emo } from "../lib/Emo";
import { Icon } from "../lib/Icon";
import { locale, useT } from "../lib/i18n";
import { usePrefs } from "../lib/prefs";
import { canListen, canSpeak, stopSpeaking, useDictation } from "../lib/voice";
import type { Walk } from "../useWalk";
import { ComfortNote } from "../components/Insights";
import { Emoji } from "./PlaceCard";
import { Events, followUps } from "./Results";

const SUGGESTIONS = [
  { key: "chat.s1", emoji: "☕" },
  { key: "chat.s2", emoji: "🎈" },
  { key: "chat.s3", emoji: "✈️" },
  { key: "ui.chatS4", emoji: "🌛" },
];
const VOICE_ERRORS = { denied: "chat.voiceDenied", "no-speech": "chat.voiceNoSpeech", failed: "chat.voiceFailed" } as const;

/** The conversation with the assistant; every answer also lands on the map and the walk tab. */
export function Chat({
  walk,
  onOpen,
  onShowRoute,
  spoken,
  setSpoken,
}: {
  walk: Walk;
  onOpen: (p: Poi) => void;
  onShowRoute: (p: Plan) => void;
  spoken: boolean;
  setSpoken: (v: boolean) => void;
}) {
  const t = useT();
  const { lang } = usePrefs();
  const { messages, ask } = walk.chat;
  const [text, setText] = useState("");
  const end = useRef<HTMLDivElement>(null);
  const draft = useRef("");

  useEffect(() => {
    end.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [messages, walk.busy]);

  const send = (value: string) => {
    if (!value.trim() || walk.busy) return;
    stopSpeaking();
    setText("");
    ask(value);
  };
  const mic = useDictation(
    lang,
    (heard) => setText(draft.current ? draft.current + " " + heard : heard),
    (heard) => send(draft.current ? draft.current + " " + heard : heard),
  );

  return (
    <div className="screen chat">
      <div className="chat-head">
        <span className="bot-avatar">
          <Emo e="✨" />
        </span>
        <div>
          <h1 className="screen-title small">{t("nav.chat")}</h1>
          <p className="screen-sub">{t("chat.subtitle")}</p>
        </div>
        {canSpeak() && (
          <button
            className="round-btn"
            aria-pressed={spoken}
            aria-label={spoken ? t("chat.speakOn") : t("chat.speakOff")}
            title={spoken ? t("chat.speakOn") : t("chat.speakOff")}
            onClick={() => {
              if (spoken) stopSpeaking();
              setSpoken(!spoken);
            }}
          >
            <Icon name={spoken ? "volume-2" : "volume-x"} />
          </button>
        )}
      </div>

      <div className="conversation" aria-live="polite">
        {!messages.length && (
          <div className="chat-welcome">
            <p className="welcome-big">
              {t("chat.welcome1")} {t("chat.welcome2")}
            </p>
            <p className="screen-sub">{t("chat.welcomeHint")}</p>
            <div className="suggestions">
              {SUGGESTIONS.map((s, i) => (
                <button key={s.key} style={{ animationDelay: `${i * 60}ms` }} onClick={() => send(t(s.key))}>
                  <Emo e={s.emoji} />
                  {t(s.key)}
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((m) => (
          <article key={m.id} className={"bubble " + m.role}>
            <p>{m.text}</p>
            {m.data && <ComfortNote data={m.data} />}
            {m.data?.warnings.map((w) => (
              <p className="note warn" key={w}>
                {w}
              </p>
            ))}
            {m.data?.mini_route && (m.data.mini_route.stops.length > 0 || m.data.mini_route.finish) && (
              <button className="route-chip" onClick={() => onShowRoute(m.data!.mini_route!)}>
                <Emo e="🗺️" />
                <span>
                  <strong>
                    {m.data.mini_route.finish
                      ? t(m.data.mini_route.finish.loop ? "route.loopTitle" : "route.finishTitle", {
                          label: m.data.mini_route.finish.label,
                          n: m.data.mini_route.stops.length,
                          at: clockAt(m.data.mini_route.session?.start_at, m.data.mini_route.finish.arrival_offset_min),
                        })
                      : t("route.title", {
                          n: m.data.mini_route.stops.length,
                          total: Math.round(m.data.mini_route.total_duration_min),
                          budget: m.data.mini_route.budget_minutes ?? m.data.minutes,
                        })}
                  </strong>
                  <small>{t("route.show")}</small>
                </span>
                <Icon name="chevron-right" />
              </button>
            )}
            {!!m.data?.items.length && (
              <div className="bubble-places">
                {m.data.items.map((p, i) => (
                  <button key={p.poi_id} className="mini-place" onClick={() => onOpen(p)}>
                    <span className="option-num small">{i + 1}</span>
                    <Emoji p={p} size="sm" />
                    <span>
                      <strong>{p.display_name}</strong>
                      <small>
                        {categoryLabel(p, t)} · {itemTiming(p, t)}
                      </small>
                      {groupCost(p, t, locale(lang)) && <small className="group-cost">{groupCost(p, t, locale(lang))}</small>}
                    </span>
                  </button>
                ))}
              </div>
            )}
            {m.data && <Events data={m.data} />}
            {m.data && m === messages[messages.length - 1] && !walk.busy && followUps(m.data).length > 0 && (
              <div className="quick-replies" role="group" aria-label={t("quick.label")}>
                {followUps(m.data).map((key) => (
                  <button key={key} onClick={() => send(t(key))}>
                    {t(key)}
                  </button>
                ))}
              </div>
            )}
          </article>
        ))}
        {walk.busy && (
          <div className="bubble typing" role="status" aria-label={t("chat.thinking")}>
            <i />
            <i />
            <i />
          </div>
        )}
        <div ref={end} />
      </div>

      <form
        className="composer"
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
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              send(text);
            }
          }}
          placeholder={t("chat.ask")}
          maxLength={1500}
          rows={1}
        />
        {canListen() && (
          <button
            type="button"
            className={"mic-btn" + (mic.listening ? " listening" : "")}
            aria-pressed={mic.listening}
            aria-label={mic.listening ? t("chat.voiceStop") : t("chat.voiceStart")}
            title={mic.listening ? t("chat.voiceStop") : t("chat.voiceStart")}
            disabled={walk.busy}
            onClick={() => {
              if (mic.listening) return mic.stop();
              stopSpeaking();
              draft.current = text.trim();
              mic.start();
            }}
          >
            <Icon name="mic" />
          </button>
        )}
        <button className="send-btn" disabled={walk.busy || !text.trim()} aria-label={t("chat.send")}>
          <Icon name="send-horizontal" />
        </button>
      </form>
      {(mic.listening || mic.error) && (
        <p className={"hint" + (mic.error ? " error" : "")} role="status">
          {mic.listening ? t("chat.listening") : mic.error ? t(VOICE_ERRORS[mic.error]) : ""}
        </p>
      )}
      <p className="privacy-note">
        {t("chat.privacy")}
        {canListen() ? " " + t("chat.voicePrivacy") : ""}
      </p>
    </div>
  );
}
